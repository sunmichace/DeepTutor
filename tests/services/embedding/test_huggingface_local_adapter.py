"""Tests for local HuggingFace embedding adapter."""

from __future__ import annotations

import asyncio
import sys
import types

import numpy as np
import pytest

from deeptutor.services.embedding.adapters.base import EmbeddingRequest
from deeptutor.services.embedding.adapters.huggingface_local import (
    HuggingFaceLocalEmbeddingAdapter,
)


def test_huggingface_local_adapter_embeds_with_sentence_transformer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            self.model_name = model_name
            self.kwargs = kwargs

        def encode(self, texts, **kwargs):
            return np.array([[float(i), float(i + 1)] for i, _ in enumerate(texts)])

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    HuggingFaceLocalEmbeddingAdapter._model_cache = {}

    adapter = HuggingFaceLocalEmbeddingAdapter(
        {
            "model": "BAAI/bge-small-zh-v1.5",
            "dimensions": 2,
            "base_url": "local://huggingface",
        }
    )

    response = asyncio.run(
        adapter.embed(
            EmbeddingRequest(
                texts=["公考面试", "结构化表达"],
                model="BAAI/bge-small-zh-v1.5",
                dimensions=2,
            )
        )
    )

    assert response.model == "BAAI/bge-small-zh-v1.5"
    assert response.dimensions == 2
    assert response.embeddings == [[0.0, 1.0], [1.0, 2.0]]
    assert adapter.device == "cpu"


def test_huggingface_local_adapter_falls_back_to_cpu_on_cuda_oom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_devices: list[str] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, **kwargs):
            self.model_name = model_name
            self.device = kwargs.get("device")
            loaded_devices.append(str(self.device))

        def encode(self, texts, **kwargs):
            if self.device == "cuda":
                raise RuntimeError("CUDA error: out of memory")
            return np.array([[1.0, 2.0] for _ in texts])

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    HuggingFaceLocalEmbeddingAdapter._model_cache = {}

    adapter = HuggingFaceLocalEmbeddingAdapter(
        {
            "model": "BAAI/bge-small-zh-v1.5",
            "dimensions": 2,
            "base_url": "local://huggingface",
            "device": "cuda",
        }
    )

    response = asyncio.run(
        adapter.embed(
            EmbeddingRequest(
                texts=["公考面试"],
                model="BAAI/bge-small-zh-v1.5",
                dimensions=2,
            )
        )
    )

    assert loaded_devices == ["cuda", "cpu"]
    assert adapter.device == "cpu"
    assert response.embeddings == [[1.0, 2.0]]


def test_huggingface_local_adapter_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    HuggingFaceLocalEmbeddingAdapter._model_cache = {}

    adapter = HuggingFaceLocalEmbeddingAdapter(
        {
            "model": "BAAI/bge-small-zh-v1.5",
            "dimensions": 512,
            "base_url": "local://huggingface",
        }
    )

    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="sentence-transformers"):
        asyncio.run(
            adapter.embed(
                EmbeddingRequest(
                    texts=["公考面试"],
                    model="BAAI/bge-small-zh-v1.5",
                    dimensions=512,
                )
            )
        )
