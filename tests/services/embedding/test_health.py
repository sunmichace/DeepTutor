"""Tests for embedding health diagnostics."""

from __future__ import annotations

from deeptutor.services.embedding.config import EmbeddingConfig
from deeptutor.services.embedding.health import _suggest_fix


def test_deepseek_embedding_health_suggestion_is_actionable() -> None:
    cfg = EmbeddingConfig(
        binding="custom",
        model="deepseek-embedding",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
        effective_url="https://api.deepseek.com/v1",
        dim=1024,
    )

    suggestion = _suggest_fix(
        cfg,
        "HTTPStatusError: 404 Not Found for https://api.deepseek.com/v1/embeddings",
    )

    assert "DeepSeek" in suggestion
    assert "embedding provider" in suggestion
    assert "Ollama" in suggestion
