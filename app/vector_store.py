from __future__ import annotations

import math
import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from app.config import Settings, get_settings
from app.embedding import EmbeddingAdapter


@dataclass(frozen=True)
class VectorDocument:
    id: str
    text: str
    metadata: dict
    vector: tuple[float, ...]


class VectorStoreAdapter(Protocol):
    backend: str

    def replace(self, documents: list[VectorDocument]) -> None:
        ...

    def search(self, query_vector: list[float], limit: int = 20) -> list[tuple[VectorDocument, float]]:
        ...

    def count(self) -> int:
        ...


class InMemoryVectorStore:
    """Adapter boundary for pgvector, Milvus, Elasticsearch or another vector DB."""

    backend = "memory"

    def __init__(self) -> None:
        self._documents: dict[str, VectorDocument] = {}

    def upsert(self, document: VectorDocument) -> None:
        self._documents[document.id] = document

    def search(self, query_vector: list[float], limit: int = 20) -> list[tuple[VectorDocument, float]]:
        scored = [(document, _cosine(query_vector, document.vector)) for document in self._documents.values()]
        return sorted(scored, key=lambda item: (-item[1], item[0].id))[:limit]

    def count(self) -> int:
        return len(self._documents)

    def clear(self) -> None:
        self._documents.clear()

    def replace(self, documents: list[VectorDocument]) -> None:
        self._documents = {document.id: document for document in documents}


class PGVectorStore:
    """Persistent pgvector adapter using langchain-postgres and cosine distance."""

    backend = "pgvector"

    def __init__(self, embedding: EmbeddingAdapter, connection: str, collection: str) -> None:
        from langchain_postgres import PGVector
        from sqlalchemy import create_engine, text

        self._collection = collection
        self._id_prefix = hashlib.sha256(collection.encode("utf-8")).hexdigest()[:12]
        self._engine = create_engine(connection, pool_pre_ping=True)
        self._store = PGVector(
            embeddings=embedding,
            connection=connection,
            collection_name=collection,
            embedding_length=embedding.dimensions,
            use_jsonb=True,
        )
        with self._engine.begin() as database:
            database.execute(text("""CREATE TABLE IF NOT EXISTS fincredit_vector_manifests (
                collection_name TEXT PRIMARY KEY, document_ids JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""))
            database.execute(text("""CREATE INDEX IF NOT EXISTS ix_langchain_pg_embedding_hnsw_cosine
                ON langchain_pg_embedding USING hnsw (embedding vector_cosine_ops)"""))
        self._count = 0

    def replace(self, documents: list[VectorDocument]) -> None:
        from sqlalchemy import text

        ids = [f"{self._id_prefix}:{document.id}" for document in documents]
        # Serialize refreshes across workers, upsert the new snapshot first, then
        # delete stale IDs. Search therefore never observes an empty collection.
        with self._engine.begin() as database:
            database.execute(text("SELECT pg_advisory_xact_lock(hashtext(:collection))"), {"collection": self._collection})
            previous = database.execute(text(
                "SELECT document_ids FROM fincredit_vector_manifests WHERE collection_name = :collection FOR UPDATE"
            ), {"collection": self._collection}).scalar_one_or_none() or []
            if documents:
                self._store.add_embeddings(
                    texts=[document.text for document in documents],
                    embeddings=[list(document.vector) for document in documents],
                    metadatas=[document.metadata | {"document_id": document.id} for document in documents],
                    ids=ids,
                )
            stale_ids = sorted(set(previous) - set(ids))
            if stale_ids:
                self._store.delete(ids=stale_ids)
            database.execute(text("""INSERT INTO fincredit_vector_manifests(collection_name, document_ids, updated_at)
                VALUES (:collection, CAST(:document_ids AS JSONB), CURRENT_TIMESTAMP)
                ON CONFLICT (collection_name) DO UPDATE SET
                    document_ids = EXCLUDED.document_ids, updated_at = CURRENT_TIMESTAMP"""), {
                "collection": self._collection, "document_ids": json.dumps(ids),
            })
        self._count = len(documents)

    def search(self, query_vector: list[float], limit: int = 20) -> list[tuple[VectorDocument, float]]:
        results = self._store.similarity_search_with_score_by_vector(query_vector, k=limit)
        hits: list[tuple[VectorDocument, float]] = []
        for document, distance in results:
            metadata = dict(document.metadata)
            document_id = str(metadata.pop("document_id", metadata.get("policy_id", "unknown")))
            # langchain-postgres returns cosine distance (0 is best). Convert it
            # to cosine similarity so memory and PostgreSQL backends rank alike.
            similarity = max(-1.0, min(1.0, 1.0 - float(distance)))
            hits.append((VectorDocument(document_id, document.page_content, metadata, ()), similarity))
        return hits

    def count(self) -> int:
        return self._count


def get_vector_store(embedding: EmbeddingAdapter, settings: Settings | None = None) -> VectorStoreAdapter:
    settings = settings or get_settings()
    if settings.deployment_environment == "production" and settings.vector_store_backend != "pgvector":
        raise RuntimeError("生产环境禁止使用内存向量库")
    if settings.vector_store_backend == "memory":
        return InMemoryVectorStore()
    if settings.vector_store_backend == "pgvector":
        if not settings.pgvector_connection:
            raise RuntimeError("FINCREDIT_PGVECTOR_CONNECTION 未配置")
        return PGVectorStore(embedding, settings.pgvector_connection, settings.pgvector_collection)
    raise RuntimeError(f"未配置的向量数据库：{settings.vector_store_backend}")


def vector_store_healthcheck(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.vector_store_backend == "memory":
        return
    from sqlalchemy import create_engine, text

    engine = create_engine(settings.pgvector_connection, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def _cosine(left: list[float], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return dot / (left_norm * right_norm)
