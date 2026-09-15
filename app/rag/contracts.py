from __future__ import annotations

from dataclasses import dataclass

from langchain_core.documents import Document

from app.config import Settings, get_settings
from app.domain import PolicyClause


@dataclass(frozen=True)
class RAGConfig:
    top_k: int = 3
    lexical_weight: float = 0.85
    vector_weight: float = 0.15
    min_vector_score: float = 0.0
    chunk_size: int = 180

    def __post_init__(self) -> None:
        if not 1 <= self.top_k <= 50:
            raise ValueError("top_k 必须在 1 到 50 之间")
        if self.lexical_weight < 0 or self.vector_weight < 0:
            raise ValueError("检索权重不能小于 0")
        if self.lexical_weight + self.vector_weight <= 0:
            raise ValueError("检索权重之和必须大于 0")
        if not -1 <= self.min_vector_score <= 1:
            raise ValueError("min_vector_score 必须在 -1 到 1 之间")
        if self.chunk_size < 50:
            raise ValueError("chunk_size 不能小于 50")

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "RAGConfig":
        settings = settings or get_settings()
        return cls(
            top_k=settings.rag_top_k,
            lexical_weight=settings.rag_lexical_weight,
            vector_weight=settings.rag_vector_weight,
            min_vector_score=settings.rag_min_vector_score,
            chunk_size=settings.rag_chunk_size,
        )

    def to_dict(self) -> dict:
        return {
            "top_k": self.top_k,
            "lexical_weight": self.lexical_weight,
            "vector_weight": self.vector_weight,
            "min_vector_score": self.min_vector_score,
            "chunk_size": self.chunk_size,
        }


@dataclass(frozen=True)
class RAGPolicyHit:
    policy: PolicyClause
    document: Document

    @property
    def relevance_score(self) -> float:
        return float(self.document.metadata.get("relevance_score", 0.0))


@dataclass(frozen=True)
class RAGResult:
    query: str
    hits: tuple[RAGPolicyHit, ...]
    config: RAGConfig
    retriever: str = "langchain-hybrid-memory-v2"

    def trace(self) -> dict:
        return {
            "retriever": self.retriever,
            "query": self.query,
            "config": self.config.to_dict(),
            "hits": [
                {
                    "policy_id": hit.policy.id,
                    "citation": hit.document.metadata.get("citation"),
                    "relevance_score": hit.relevance_score,
                    "lexical_score": hit.document.metadata.get("lexical_score", 0.0),
                    "vector_score": hit.document.metadata.get("vector_score", 0.0),
                    "forced_match": bool(hit.document.metadata.get("forced_match", False)),
                }
                for hit in self.hits
            ],
        }
