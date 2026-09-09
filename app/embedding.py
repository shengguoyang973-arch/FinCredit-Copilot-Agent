from __future__ import annotations

import hashlib
import math
import os
from typing import Protocol


class EmbeddingAdapter(Protocol):
    name: str

    def embed(self, text: str) -> list[float]:
        ...


class HashEmbeddingAdapter:
    """Offline deterministic adapter for tests and demos; replace in production."""

    name = "hash-local"

    def __init__(self, dimensions: int = 128):
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        normalized = text.lower()
        tokens = [normalized[index:index + 2] for index in range(max(0, len(normalized) - 1))]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class OpenAIEmbeddingAdapter:
    name = "openai-embeddings"

    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model

    def embed(self, text: str) -> list[float]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY 未配置，无法使用 Embedding Provider")
        from openai import OpenAI

        response = OpenAI(api_key=api_key).embeddings.create(model=self.model, input=text)
        return list(response.data[0].embedding)


def get_embedding_adapter() -> EmbeddingAdapter:
    provider = os.getenv("FINCREDIT_EMBEDDING_PROVIDER", "hash-local").strip().lower()
    if provider in {"openai", "openai-embeddings"}:
        return OpenAIEmbeddingAdapter(os.getenv("FINCREDIT_EMBEDDING_MODEL", "text-embedding-3-small"))
    return HashEmbeddingAdapter(int(os.getenv("FINCREDIT_EMBEDDING_DIMENSIONS", "128")))
