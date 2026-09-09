from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VectorDocument:
    id: str
    text: str
    metadata: dict
    vector: tuple[float, ...]


class InMemoryVectorStore:
    """Adapter boundary for pgvector, Milvus, Elasticsearch or another vector DB."""

    def __init__(self) -> None:
        self._documents: dict[str, VectorDocument] = {}

    def upsert(self, document: VectorDocument) -> None:
        self._documents[document.id] = document

    def search(self, query_vector: list[float], limit: int = 20) -> list[tuple[VectorDocument, float]]:
        scored = [(document, _cosine(query_vector, document.vector)) for document in self._documents.values()]
        return sorted(scored, key=lambda item: (-item[1], item[0].id))[:limit]

    def count(self) -> int:
        return len(self._documents)


def _cosine(left: list[float], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
    right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
    return dot / (left_norm * right_norm)
