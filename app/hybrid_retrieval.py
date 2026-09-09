from __future__ import annotations

from dataclasses import dataclass

from app.embedding import EmbeddingAdapter, get_embedding_adapter
from app.knowledge_retrieval import PolicyHit, retrieve_policy_hits
from app.knowledge_retrieval import chunk_policy
from app.domain import PolicyClause
from app.vector_store import InMemoryVectorStore, VectorDocument


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
    def __init__(self, embedding: EmbeddingAdapter | None = None, store: InMemoryVectorStore | None = None):
        self.embedding = embedding or get_embedding_adapter()
        self.store = store or InMemoryVectorStore()
        self._policies: dict[str, PolicyClause] = {}

    def index(self, policies: list[PolicyClause]) -> None:
        for policy in policies:
            self._policies[policy.id] = policy
            for chunk in chunk_policy(policy):
                text = f"{policy.title} {' '.join(policy.keywords)} {chunk['text']}"
                self.store.upsert(VectorDocument(chunk["id"], text, chunk, tuple(self.embedding.embed(text))))

    def search(self, query: str, policies: list[PolicyClause], limit: int = 10) -> list[HybridPolicyHit]:
        self.index(policies)
        lexical = {hit.policy.id: hit for hit in retrieve_policy_hits(query, policies, limit=limit * 2)}
        vector_scores: dict[str, float] = {}
        for document, score in self.store.search(self.embedding.embed(query), limit=limit * 4):
            policy_id = document.metadata["policy_id"]
            vector_scores[policy_id] = max(vector_scores.get(policy_id, -1.0), score)
        hits: list[HybridPolicyHit] = []
        for policy_id, policy in self._policies.items():
            lexical_hit = lexical.get(policy_id)
            lexical_score = lexical_hit.score if lexical_hit else 0.0
            vector_score = vector_scores.get(policy_id, 0.0)
            if not lexical_hit and vector_score < 0.15:
                continue
            # Rerank favors explicit term matches while retaining semantic recall.
            rerank_score = lexical_score * 0.65 + max(vector_score, 0.0) * 10 * 0.35
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


_RETRIEVER = HybridPolicyRetriever()


def retrieve_hybrid_policy_hits(query: str, policies: list[PolicyClause], limit: int = 10) -> list[HybridPolicyHit]:
    return _RETRIEVER.search(query, policies, limit)
