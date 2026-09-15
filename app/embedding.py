from __future__ import annotations

import hashlib
import math
from typing import Protocol

from app.config import Settings, get_settings


class EmbeddingAdapter(Protocol):
    name: str
    dimensions: int

    def embed(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
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

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)


class OpenAIEmbeddingAdapter:
    name = "openai-embeddings"

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int = 256,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
    ):
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client = None

    def _openai(self):
        if self._client is None:
            from langchain_openai import OpenAIEmbeddings

            self._client = OpenAIEmbeddings(
                model=self.model,
                dimensions=self.dimensions,
                request_timeout=self.timeout_seconds,
                max_retries=self.max_retries,
            )
        return self._client

    def embed(self, text: str) -> list[float]:
        return self.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(vector) for vector in self._openai().embed_documents(texts)]

    def embed_query(self, text: str) -> list[float]:
        return list(self._openai().embed_query(text))


def get_embedding_adapter(settings: Settings | None = None) -> EmbeddingAdapter:
    settings = settings or get_settings()
    if settings.deployment_environment == "production" and settings.embedding_provider != "openai":
        raise RuntimeError("生产环境禁止使用本地 Hash Embedding")
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingAdapter(
            settings.embedding_model,
            settings.embedding_dimensions,
            settings.openai_timeout_seconds,
            settings.agent_max_retries,
        )
    if settings.embedding_provider == "hash-local":
        return HashEmbeddingAdapter(settings.embedding_dimensions)
    raise RuntimeError(f"未配置的 Embedding Provider：{settings.embedding_provider}")
