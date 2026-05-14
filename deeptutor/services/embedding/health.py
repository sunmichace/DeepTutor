"""Embedding runtime health checks."""

from __future__ import annotations

from dataclasses import dataclass

from .client import get_embedding_client, reset_embedding_client
from .config import EmbeddingConfig, get_embedding_config


@dataclass
class EmbeddingHealthResult:
    ok: bool
    binding: str = ""
    model: str = ""
    base_url: str = ""
    dimension: int = 0
    error: str = ""
    suggestion: str = ""


def _suggest_fix(config: EmbeddingConfig | None, error: Exception | str) -> str:
    message = str(error)
    binding = (config.binding if config else "").lower()
    base_url = (config.effective_url or config.base_url or "") if config else ""

    if "deepseek.com" in base_url.lower() or binding == "deepseek":
        return (
            "DeepSeek chat models do not expose an OpenAI-compatible /embeddings "
            "endpoint in this environment. Configure a real embedding provider such as "
            "Ollama (nomic-embed-text), OpenAI, Jina, Cohere, or a vLLM/LM Studio "
            "server that supports /embeddings."
        )
    if "404" in message and "/embeddings" in message:
        return (
            "The configured endpoint does not provide /embeddings. Check "
            "EMBEDDING_HOST, EMBEDDING_BINDING, and EMBEDDING_MODEL."
        )
    if binding == "ollama" or "11434" in base_url:
        return "Start Ollama with `ollama serve` and pull the configured embedding model."
    return "Configure a working embedding provider before building the vector index."


async def check_embedding_health(sample_text: str = "DeepTutor embedding health check") -> EmbeddingHealthResult:
    """Run a single lightweight embedding request and return a structured result."""
    config: EmbeddingConfig | None = None
    try:
        reset_embedding_client()
        config = get_embedding_config()
        client = get_embedding_client(config)
        vectors = await client.embed([sample_text])
        dim = len(vectors[0]) if vectors else 0
        if not vectors or dim <= 0:
            raise ValueError("Embedding provider returned no vectors.")
        return EmbeddingHealthResult(
            ok=True,
            binding=config.binding,
            model=config.model,
            base_url=config.effective_url or config.base_url or "",
            dimension=dim,
        )
    except Exception as exc:
        return EmbeddingHealthResult(
            ok=False,
            binding=config.binding if config else "",
            model=config.model if config else "",
            base_url=(config.effective_url or config.base_url or "") if config else "",
            dimension=config.dim if config else 0,
            error=f"{type(exc).__name__}: {exc}",
            suggestion=_suggest_fix(config, exc),
        )
