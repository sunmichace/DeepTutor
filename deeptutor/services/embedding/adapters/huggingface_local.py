"""Local HuggingFace/SentenceTransformers embedding adapter."""

from __future__ import annotations

import asyncio
from functools import partial
import os
from typing import Any, Dict

import numpy as np

from .base import BaseEmbeddingAdapter, EmbeddingRequest, EmbeddingResponse


class HuggingFaceLocalEmbeddingAdapter(BaseEmbeddingAdapter):
    """Generate embeddings with a local sentence-transformers model.

    The model name may be a HuggingFace repository id such as
    ``BAAI/bge-small-zh-v1.5`` or a local filesystem path. The underlying
    library handles cache/download behavior.
    """

    _model_cache: dict[str, Any] = {}

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.device = config.get("device") or os.getenv("EMBEDDING_DEVICE") or "cpu"

    def _load_model(self) -> Any:
        model_name = str(self.model or "").strip()
        if not model_name:
            raise ValueError("EMBEDDING_MODEL is required for huggingface_local embeddings.")
        cache_key = f"{model_name}::{self.device}"
        if cache_key in self._model_cache:
            return self._model_cache[cache_key]
        model = self._load_model_on_device(model_name, self.device)
        self._model_cache[cache_key] = model
        return model

    def _load_model_on_device(self, model_name: str, device: str) -> Any:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "huggingface_local embeddings require sentence-transformers. "
                "Install it with `pip install sentence-transformers` or "
                "`pip install -r requirements/cli.txt`."
            ) from exc
        return SentenceTransformer(model_name, device=device)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        texts = request.texts
        if not texts:
            return EmbeddingResponse(
                embeddings=[],
                model=request.model or self.model,
                dimensions=int(request.dimensions or self.dimensions or 0),
                usage={"prompt_tokens": 0, "total_tokens": 0},
            )

        try:
            model = self._load_model()
            vectors = await self._encode(model, texts, request)
        except Exception as exc:
            if self.device == "cpu" or not _is_cuda_out_of_memory(exc):
                raise
            self._model_cache.pop(f"{self.model}::{self.device}", None)
            self.device = "cpu"
            model = self._load_model()
            vectors = await self._encode(model, texts, request)
        if isinstance(vectors, np.ndarray):
            embeddings = vectors.astype(float).tolist()
        else:
            embeddings = [list(map(float, vector)) for vector in vectors]

        actual_dims = len(embeddings[0]) if embeddings else 0
        expected_dims = request.dimensions or self.dimensions
        if expected_dims and actual_dims != expected_dims:
            # SentenceTransformers dimensions are fixed by model. Keep the
            # actual vectors; health checks and logs will expose the mismatch.
            pass

        return EmbeddingResponse(
            embeddings=embeddings,
            model=request.model or self.model,
            dimensions=actual_dims,
            usage={"prompt_tokens": 0, "total_tokens": 0},
        )

    async def _encode(
        self,
        model: Any,
        texts: list[str],
        request: EmbeddingRequest,
    ) -> Any:
        encode = partial(
            model.encode,
            texts,
            batch_size=max(1, min(len(texts), 32)),
            normalize_embeddings=bool(request.normalized),
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return await asyncio.to_thread(encode)

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "dimensions": self.dimensions,
            "supports_variable_dimensions": False,
            "provider": "huggingface_local",
        }


def _is_cuda_out_of_memory(exc: Exception) -> bool:
    message = str(exc).lower()
    return "cuda" in message and "out of memory" in message
