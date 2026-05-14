"""
LlamaIndex Pipeline
===================

True LlamaIndex integration using official llama-index library.
"""

import asyncio
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from llama_index.core import (
    Document,
    Settings,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.bridge.pydantic import PrivateAttr

from deeptutor.logging import get_logger
from deeptutor.services.embedding import get_embedding_client, get_embedding_config
from deeptutor.services.rag.components.routing import FileTypeRouter

# Default knowledge base directory
DEFAULT_KB_BASE_DIR = str(
    Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "knowledge_bases"
)


class CustomEmbedding(BaseEmbedding):
    """
    Custom embedding adapter for OpenAI-compatible APIs.

    Works with any OpenAI-compatible endpoint including:
    - Google Gemini (text-embedding-004)
    - OpenAI (text-embedding-ada-002, text-embedding-3-*)
    - Azure OpenAI
    - Local models with OpenAI-compatible API
    """

    _client: Any = PrivateAttr()
    _logger: Any = PrivateAttr()
    _progress_callback: Any = PrivateAttr(default=None)

    def __init__(self, **kwargs):
        progress_cb = kwargs.pop("progress_callback", None)
        super().__init__(**kwargs)
        self._client = get_embedding_client()
        self._logger = get_logger("CustomEmbedding")
        self._progress_callback = progress_cb

    def set_progress_callback(self, callback):
        """Set progress callback fn(batch_num, total_batches)."""
        self._progress_callback = callback

    @classmethod
    def class_name(cls) -> str:
        return "custom_embedding"

    def _run_in_new_loop(self, coro):
        """Run an async coroutine from sync context using a fresh event loop.

        Avoids nest_asyncio which can deadlock when called from thread pools
        inside a running server event loop.
        """
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    async def _aget_query_embedding(self, query: str) -> List[float]:
        """Get embedding for a query."""
        embeddings = await self._client.embed([query])
        return embeddings[0]

    async def _aget_text_embedding(self, text: str) -> List[float]:
        """Get embedding for a text."""
        embeddings = await self._client.embed([text])
        return embeddings[0]

    async def _aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for multiple texts."""
        return await self._client.embed(
            texts, progress_callback=self._progress_callback
        )

    def _get_query_embedding(self, query: str) -> List[float]:
        """Sync version - called by LlamaIndex sync API."""
        return self._run_in_new_loop(self._aget_query_embedding(query))

    def _get_text_embedding(self, text: str) -> List[float]:
        """Sync version - called by LlamaIndex sync API."""
        return self._run_in_new_loop(self._aget_text_embedding(text))

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Sync batch version - called by LlamaIndex for bulk embedding."""
        self._logger.info(f"Embedding {len(texts)} text chunks...")
        result = self._run_in_new_loop(self._aget_text_embeddings(texts))
        self._logger.info(f"Embedding complete: {len(result)} vectors")
        return result


class LlamaIndexPipeline:
    """
    True LlamaIndex pipeline using official llama-index library.

    Uses LlamaIndex's native components:
    - VectorStoreIndex for indexing
    - CustomEmbedding for OpenAI-compatible embeddings
    - SentenceSplitter for chunking
    - StorageContext for persistence
    """

    def __init__(self, kb_base_dir: Optional[str] = None):
        """
        Initialize LlamaIndex pipeline.

        Args:
            kb_base_dir: Base directory for knowledge bases
        """
        self.logger = get_logger("LlamaIndexPipeline")
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        self._configure_settings()

    def _configure_settings(self):
        """Configure LlamaIndex global settings."""
        embedding_cfg = get_embedding_config()

        Settings.embed_model = CustomEmbedding()
        Settings.chunk_size = 512
        Settings.chunk_overlap = 50

        self.logger.info(
            f"LlamaIndex configured: embedding={embedding_cfg.model} "
            f"({embedding_cfg.dim}D, {embedding_cfg.binding}), chunk_size=512"
        )

    async def _verify_embedding_connectivity(self) -> None:
        """Quick smoke-test: embed a single token to catch config/network issues early."""
        self.logger.info("Verifying embedding API connectivity...")
        try:
            client = get_embedding_client()
            result = await client.embed(["connectivity test"])
            if not result or not result[0]:
                raise RuntimeError("Embedding API returned empty result")
            self.logger.info(
                f"Embedding API OK (returned {len(result[0])}-dim vector)"
            )
        except Exception as e:
            self.logger.error(f"Embedding API connectivity check failed: {e}")
            raise RuntimeError(
                f"Cannot reach embedding API. Please check your embedding configuration. Error: {e}"
            ) from e

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        """
        Initialize KB using real LlamaIndex components.

        Args:
            kb_name: Knowledge base name
            file_paths: List of file paths to process
            **kwargs: Additional arguments (accepts progress_callback)

        Returns:
            True if successful
        """
        progress_callback = kwargs.get("progress_callback")

        self.logger.info(
            f"Initializing KB '{kb_name}' with {len(file_paths)} files using LlamaIndex"
        )

        kb_dir = Path(self.kb_base_dir) / kb_name
        storage_dir = kb_dir / "llamaindex_storage"
        storage_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Verify embedding API is reachable before doing any heavy work
            await self._verify_embedding_connectivity()

            # Parse documents with centralized file routing
            documents = []
            classification = FileTypeRouter.classify_files(file_paths)

            for file_path_str in classification.parser_files:
                file_path = Path(file_path_str)
                self.logger.info(f"Parsing document: {file_path.name}")
                text = self._extract_document_text(file_path)
                if text.strip():
                    documents.append(
                        Document(
                            text=text,
                            metadata={
                                "file_name": file_path.name,
                                "file_path": str(file_path),
                                "file_type": file_path.suffix.lower().lstrip("."),
                            },
                        )
                    )
                    self.logger.info(f"Loaded: {file_path.name} ({len(text)} chars)")
                else:
                    self.logger.warning(f"Skipped empty document: {file_path.name}")

            for file_path_str in classification.text_files:
                file_path = Path(file_path_str)
                self.logger.info(f"Parsing text: {file_path.name}")
                text = await FileTypeRouter.read_text_file(str(file_path))
                if text.strip():
                    documents.append(
                        Document(
                            text=text,
                            metadata={
                                "file_name": file_path.name,
                                "file_path": str(file_path),
                            },
                        )
                    )
                    self.logger.info(f"Loaded: {file_path.name} ({len(text)} chars)")
                else:
                    self.logger.warning(f"Skipped empty document: {file_path.name}")

            for file_path_str in classification.unsupported:
                self.logger.warning(f"Skipped unsupported file: {Path(file_path_str).name}")

            if not documents:
                self.logger.error("No valid documents found")
                return False

            self.logger.info(
                f"Creating VectorStoreIndex with {len(documents)} documents "
                f"(chunking + embedding)..."
            )

            if progress_callback and isinstance(Settings.embed_model, CustomEmbedding):
                Settings.embed_model.set_progress_callback(progress_callback)

            loop = asyncio.get_event_loop()
            index = await loop.run_in_executor(
                None,
                lambda: VectorStoreIndex.from_documents(documents, show_progress=True),
            )

            # Persist index
            index.storage_context.persist(persist_dir=str(storage_dir))
            self.logger.info(f"Index persisted to {storage_dir}")

            self.logger.info(f"KB '{kb_name}' initialized successfully with LlamaIndex")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize KB: {e}")
            import traceback

            self.logger.error(traceback.format_exc())
            return False
        finally:
            if isinstance(Settings.embed_model, CustomEmbedding):
                Settings.embed_model.set_progress_callback(None)

    def _extract_document_text(self, file_path: Path) -> str:
        """Extract text from supported parser-routed documents."""
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            return self._extract_pdf_text(file_path)
        if ext == ".doc":
            return self._extract_legacy_doc_text(file_path)
        if ext == ".docx":
            return self._extract_docx_text(file_path)
        if ext == ".pptx":
            return self._extract_pptx_text(file_path)
        self.logger.warning(f"Unsupported parser document type: {file_path.name}")
        return ""

    def _extract_pdf_text(self, file_path: Path) -> str:
        """Extract text from PDF using PyMuPDF."""
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            texts = []
            for page in doc:
                texts.append(page.get_text())
            doc.close()
            return "\n\n".join(texts)
        except ImportError:
            self.logger.warning("PyMuPDF not installed. Cannot extract PDF text.")
            return ""
        except Exception as e:
            self.logger.error(f"Failed to extract PDF text: {e}")
            return ""

    def _extract_docx_text(self, file_path: Path) -> str:
        """Extract readable text from DOCX paragraphs and tables."""
        try:
            from docx import Document as DocxDocument
        except ImportError:
            self.logger.warning("python-docx not installed. Cannot extract DOCX text.")
            return ""
        try:
            doc = DocxDocument(str(file_path))
            parts: list[str] = []
            for paragraph in doc.paragraphs:
                text = paragraph.text.strip()
                if text:
                    parts.append(text)
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            return "\n\n".join(parts)
        except Exception as e:
            self.logger.error(f"Failed to extract DOCX text: {e}")
            return ""

    def _extract_legacy_doc_text(self, file_path: Path) -> str:
        """Extract text from legacy .doc files via LibreOffice conversion."""
        converter = self._find_office_converter()
        if not converter:
            self.logger.warning("LibreOffice/soffice not found. Cannot extract legacy DOC text.")
            return ""
        try:
            with tempfile.TemporaryDirectory(prefix="deeptutor-doc-") as temp_dir:
                cmd = [
                    converter,
                    "--headless",
                    "--convert-to",
                    "txt:Text",
                    "--outdir",
                    temp_dir,
                    str(file_path),
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
                converted = Path(temp_dir) / f"{file_path.stem}.txt"
                if not converted.exists():
                    self.logger.warning(f"LibreOffice did not produce TXT for {file_path.name}")
                    return ""
                return FileTypeRouter.read_text_file_sync(str(converted))
        except subprocess.TimeoutExpired:
            self.logger.error(f"Timed out converting legacy DOC: {file_path.name}")
            return ""
        except Exception as e:
            self.logger.error(f"Failed to extract legacy DOC text: {e}")
            return ""

    @staticmethod
    def _find_office_converter() -> str:
        """Find a LibreOffice-compatible command for legacy Office conversion."""
        import shutil

        return shutil.which("libreoffice") or shutil.which("soffice") or ""

    def _extract_pptx_text(self, file_path: Path) -> str:
        """Extract readable text from PPTX slides, tables, and notes."""
        try:
            from pptx import Presentation
        except ImportError:
            self.logger.warning("python-pptx not installed. Cannot extract PPTX text.")
            return ""
        try:
            presentation = Presentation(str(file_path))
            parts: list[str] = []
            for index, slide in enumerate(presentation.slides, start=1):
                slide_parts: list[str] = []
                for shape in slide.shapes:
                    if getattr(shape, "has_text_frame", False):
                        text = shape.text.strip()
                        if text:
                            slide_parts.append(text)
                    if getattr(shape, "has_table", False):
                        for row in shape.table.rows:
                            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                            if cells:
                                slide_parts.append(" | ".join(cells))
                notes = getattr(slide, "notes_slide", None)
                notes_text_frame = getattr(getattr(notes, "notes_text_frame", None), "text", "")
                if notes_text_frame and notes_text_frame.strip():
                    slide_parts.append(notes_text_frame.strip())
                if slide_parts:
                    parts.append(f"Slide {index}\n" + "\n".join(slide_parts))
            return "\n\n".join(parts)
        except Exception as e:
            self.logger.error(f"Failed to extract PPTX text: {e}")
            return ""

    async def search(
        self,
        query: str,
        kb_name: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Search using LlamaIndex retriever.

        Args:
            query: Search query
            kb_name: Knowledge base name
            **kwargs: Additional arguments (top_k, etc.)

        Returns:
            Search results dictionary with answer, content, and sources
        """
        kwargs.pop("mode", None)
        self.logger.info(f"Searching KB '{kb_name}' with query: {query[:50]}...")

        kb_dir = Path(self.kb_base_dir) / kb_name
        storage_dir = kb_dir / "llamaindex_storage"

        docstore_path = storage_dir / "docstore.json"
        if not storage_dir.exists() or not docstore_path.exists():
            self.logger.warning(f"No LlamaIndex storage found at {storage_dir}")
            return {
                "query": query,
                "answer": "No documents indexed. Please upload documents first.",
                "content": "",
                "provider": "llamaindex",
            }

        embedding_mismatch_warning = ""
        try:
            import json as _json

            cfg_path = Path(self.kb_base_dir) / "kb_config.json"
            if cfg_path.exists():
                with open(cfg_path, encoding="utf-8") as _f:
                    kb_entry = _json.load(_f).get("knowledge_bases", {}).get(kb_name, {})
                if kb_entry.get("embedding_mismatch"):
                    stored = kb_entry.get("embedding_model", "unknown")
                    current = get_embedding_config().model
                    embedding_mismatch_warning = (
                        f"Warning: KB '{kb_name}' was indexed with '{stored}' "
                        f"but current model is '{current}'. Re-index recommended."
                    )
                    self.logger.warning(embedding_mismatch_warning)
        except Exception:
            pass

        try:
            # Load index from storage (run in thread pool)
            loop = asyncio.get_event_loop()

            def load_and_retrieve():
                storage_context = StorageContext.from_defaults(persist_dir=str(storage_dir))
                index = load_index_from_storage(storage_context)
                top_k = kwargs.get("top_k", 5)

                # Use retriever instead of query_engine to avoid LLM requirement
                retriever = index.as_retriever(similarity_top_k=top_k)
                nodes = retriever.retrieve(query)
                return nodes

            # Execute retrieval in thread pool to avoid blocking
            nodes = await loop.run_in_executor(None, load_and_retrieve)

            context_parts = []
            sources = []
            for i, node in enumerate(nodes):
                context_parts.append(node.node.text)
                meta = node.node.metadata or {}
                sources.append({
                    "title": meta.get("file_name", meta.get("title", f"Document {i + 1}")),
                    "content": node.node.text[:200],
                    "source": meta.get("file_path", meta.get("file_name", "")),
                    "page": meta.get("page_label", meta.get("page", "")),
                    "chunk_id": node.node.node_id or str(i),
                    "score": round(node.score, 4) if node.score is not None else "",
                })

            content = "\n\n".join(context_parts) if context_parts else ""

            result: Dict[str, Any] = {
                "query": query,
                "answer": content,
                "content": content,
                "sources": sources,
                "provider": "llamaindex",
            }
            if embedding_mismatch_warning:
                result["warning"] = embedding_mismatch_warning
            return result

        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            import traceback

            self.logger.error(traceback.format_exc())
            return {
                "query": query,
                "answer": f"Search failed: {str(e)}",
                "content": "",
                "provider": "llamaindex",
            }

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        """
        Incrementally add documents to an existing LlamaIndex KB.

        If the storage directory exists, loads the existing index and inserts
        new documents. Otherwise, creates a new index.

        Args:
            kb_name: Knowledge base name
            file_paths: List of file paths to add
            **kwargs: Additional arguments (accepts progress_callback)

        Returns:
            True if successful
        """
        progress_callback = kwargs.get("progress_callback")

        self.logger.info(f"Adding {len(file_paths)} documents to KB '{kb_name}' using LlamaIndex")

        kb_dir = Path(self.kb_base_dir) / kb_name
        storage_dir = kb_dir / "llamaindex_storage"

        try:
            await self._verify_embedding_connectivity()

            if progress_callback and isinstance(Settings.embed_model, CustomEmbedding):
                Settings.embed_model.set_progress_callback(progress_callback)

            # Parse new documents with centralized file routing
            documents = []
            classification = FileTypeRouter.classify_files(file_paths)

            for file_path_str in classification.parser_files:
                file_path = Path(file_path_str)
                self.logger.info(f"Parsing PDF: {file_path.name}")
                text = self._extract_pdf_text(file_path)
                if text.strip():
                    documents.append(
                        Document(
                            text=text,
                            metadata={
                                "file_name": file_path.name,
                                "file_path": str(file_path),
                            },
                        )
                    )
                    self.logger.info(f"Loaded: {file_path.name} ({len(text)} chars)")
                else:
                    self.logger.warning(f"Skipped empty document: {file_path.name}")

            for file_path_str in classification.text_files:
                file_path = Path(file_path_str)
                self.logger.info(f"Parsing text: {file_path.name}")
                text = await FileTypeRouter.read_text_file(str(file_path))
                if text.strip():
                    documents.append(
                        Document(
                            text=text,
                            metadata={
                                "file_name": file_path.name,
                                "file_path": str(file_path),
                            },
                        )
                    )
                    self.logger.info(f"Loaded: {file_path.name} ({len(text)} chars)")
                else:
                    self.logger.warning(f"Skipped empty document: {file_path.name}")

            for file_path_str in classification.unsupported:
                self.logger.warning(f"Skipped unsupported file: {Path(file_path_str).name}")

            if not documents:
                self.logger.warning("No valid documents to add")
                return False

            loop = asyncio.get_event_loop()

            if storage_dir.exists():
                self.logger.info(f"Loading existing index from {storage_dir}...")

                def load_and_insert():
                    storage_context = StorageContext.from_defaults(persist_dir=str(storage_dir))
                    index = load_index_from_storage(storage_context)

                    for i, doc in enumerate(documents, 1):
                        self.logger.info(
                            f"Inserting document {i}/{len(documents)}: "
                            f"{doc.metadata.get('file_name', 'unknown')}"
                        )
                        index.insert(doc)

                    index.storage_context.persist(persist_dir=str(storage_dir))
                    return len(documents)

                num_added = await loop.run_in_executor(None, load_and_insert)
                self.logger.info(f"Added {num_added} documents to existing index")
            else:
                self.logger.info(f"Creating new index with {len(documents)} documents...")
                storage_dir.mkdir(parents=True, exist_ok=True)

                def create_index():
                    index = VectorStoreIndex.from_documents(documents, show_progress=True)
                    index.storage_context.persist(persist_dir=str(storage_dir))
                    return len(documents)

                num_added = await loop.run_in_executor(None, create_index)
                self.logger.info(f"Created new index with {num_added} documents")

            self.logger.info(f"Successfully added documents to KB '{kb_name}'")
            return True

        except Exception as e:
            self.logger.error(f"Failed to add documents: {e}")
            import traceback

            self.logger.error(traceback.format_exc())
            return False
        finally:
            if isinstance(Settings.embed_model, CustomEmbedding):
                Settings.embed_model.set_progress_callback(None)

    async def delete(self, kb_name: str) -> bool:
        """
        Delete knowledge base.

        Args:
            kb_name: Knowledge base name

        Returns:
            True if successful
        """
        import shutil

        kb_dir = Path(self.kb_base_dir) / kb_name

        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info(f"Deleted KB '{kb_name}'")
            return True

        return False
