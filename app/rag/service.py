from __future__ import annotations

from langchain_core.documents import Document

from app.domain import PolicyClause
from app.rag.contracts import RAGConfig, RAGPolicyHit, RAGResult
from app.rag.retriever import build_policy_retriever


def retrieve_policy_context(
    query: str,
    policies: list[PolicyClause],
    *,
    config: RAGConfig | None = None,
    required_policy_ids: set[str] | frozenset[str] = frozenset(),
) -> RAGResult:
    """Retrieve ranked policy context and deterministically attach rule evidence.

    RAG ranking is used for relevance. ``required_policy_ids`` is reserved for
    policies directly referenced by deterministic credit rules; those clauses
    must remain in the evidence chain even if semantic retrieval misses them.
    """

    rag_config = config or RAGConfig.from_settings()
    documents = build_policy_retriever(policies, rag_config).invoke(query)
    by_id = {policy.id: policy for policy in policies}
    seen = {str(document.metadata["policy_id"]) for document in documents}
    for policy_id in sorted(required_policy_ids - seen):
        policy = by_id.get(policy_id)
        if not policy:
            continue
        documents.append(Document(
            page_content=policy.content,
            metadata={
                "policy_id": policy.id,
                "title": policy.title,
                "version": policy.version,
                "effective_date": policy.effective_date,
                "keywords": list(policy.keywords),
                "citation": f"{policy.id}（版本 {policy.version}，规则强制证据）",
                "relevance_score": 0.0,
                "lexical_score": 0.0,
                "vector_score": 0.0,
                "matched_terms": [],
                "forced_match": True,
            },
        ))

    hits = tuple(
        RAGPolicyHit(by_id[str(document.metadata["policy_id"])], document)
        for document in documents
        if str(document.metadata.get("policy_id")) in by_id
    )
    return RAGResult(query=query, hits=hits, config=rag_config)
