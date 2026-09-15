from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from threading import RLock

from app.embedding import EmbeddingAdapter, get_embedding_adapter
from app.knowledge_retrieval import retrieve_policy_hits
from app.knowledge_retrieval import chunk_policy
from app.domain import PolicyClause
from app.vector_store import InMemoryVectorStore, VectorDocument, VectorStoreAdapter


@dataclass(frozen=True)
class HybridPolicyHit:
    policy: PolicyClause
    score: float
    lexical_score: float
    vector_score: float
    rerank_score: float
    matched_terms: tuple[str, ...]
    citation: str


class HybridPolicyRetriever:
    def __init__(
        self,
        embedding: EmbeddingAdapter | None = None,
        store: VectorStoreAdapter | None = None,
        *,
        lexical_weight: float = 0.85,
        vector_weight: float = 0.15,
        min_vector_score: float = 0.0,
        chunk_size: int = 180,
    ):
        self.embedding = embedding or get_embedding_adapter()
        self.store = store or InMemoryVectorStore()
        self._policies: dict[str, PolicyClause] = {}
        self._index_fingerprint = ""
        self._lock = RLock()
        total_weight = lexical_weight + vector_weight
        if total_weight <= 0:
            raise ValueError("RAG 检索权重之和必须大于 0")
        self.lexical_weight = lexical_weight / total_weight
        self.vector_weight = vector_weight / total_weight
        self.min_vector_score = min_vector_score
        self.chunk_size = chunk_size

    def index(self, policies: list[PolicyClause]) -> None:
        payload = [policy.__dict__ for policy in sorted(policies, key=lambda item: item.id)]
        fingerprint = hashlib.sha256(json.dumps(
            {"policies": payload, "chunk_size": self.chunk_size, "embedding": self.embedding.name,
             "dimensions": self.embedding.dimensions},
            sort_keys=True, ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        with self._lock:
            if fingerprint == self._index_fingerprint:
                return
            documents: list[VectorDocument] = []
            current_policies: dict[str, PolicyClause] = {}
            for policy in policies:
                current_policies[policy.id] = policy
                for chunk in chunk_policy(policy, max_chars=self.chunk_size):
                    text = f"{policy.title} {' '.join(policy.keywords)} {chunk['text']}"
                    documents.append(VectorDocument(chunk["id"], text, chunk, ()))
            vectors = self.embedding.embed_documents([document.text for document in documents])
            indexed = [
                VectorDocument(document.id, document.text, document.metadata, tuple(vector))
                for document, vector in zip(documents, vectors)
            ]
            self.store.replace(indexed)
            self._policies = current_policies
            self._index_fingerprint = fingerprint

    def search(self, query: str, policies: list[PolicyClause], limit: int = 10) -> list[HybridPolicyHit]:
        self.index(policies)
        lexical = {hit.policy.id: hit for hit in retrieve_policy_hits(query, policies, limit=limit * 2)}
        vector_scores: dict[str, float] = {}
        for document, score in self.store.search(self.embedding.embed_query(query), limit=limit * 4):
            policy_id = document.metadata["policy_id"]
            vector_scores[policy_id] = max(vector_scores.get(policy_id, -1.0), score)
        hits: list[HybridPolicyHit] = []
        for policy_id, policy in self._policies.items():
            lexical_hit = lexical.get(policy_id)
            lexical_score = lexical_hit.score if lexical_hit else 0.0
            vector_score = vector_scores.get(policy_id, 0.0)
            if not lexical_hit and vector_score < self.min_vector_score:
                continue
            # Normalize lexical scores before blending them with cosine
            # similarity, making both weights meaningful and tunable.
            normalized_lexical_score = min(lexical_score / 10.0, 1.0)
            rerank_score = (
                normalized_lexical_score * self.lexical_weight
                + max(vector_score, 0.0) * self.vector_weight
            )
            hits.append(HybridPolicyHit(
                policy=policy,
                score=rerank_score,
                lexical_score=lexical_score,
                vector_score=vector_score,
                rerank_score=rerank_score,
                matched_terms=lexical_hit.matched_terms if lexical_hit else (),
                citation=lexical_hit.citation if lexical_hit else f"{policy.id}（版本 {policy.version}）",
            ))
        return sorted(hits, key=lambda hit: (-hit.rerank_score, hit.policy.id))[:limit]

def retrieve_hybrid_policy_hits(query: str, policies: list[PolicyClause], limit: int = 10) -> list[HybridPolicyHit]:
    # Preserve the legacy entry point while avoiding a process-global index
    # that could retain stale policy chunks after an update.
    return HybridPolicyRetriever().search(query, policies, limit)
