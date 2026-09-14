from __future__ import annotations

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict

from app.domain import PolicyClause
from app.hybrid_retrieval import HybridPolicyRetriever
from app.rag.contracts import RAGConfig


class LangChainPolicyRetriever(BaseRetriever):
    """Expose FinCredit hybrid policy retrieval through LangChain's API."""

    policies: list[PolicyClause]
    rag_config: RAGConfig

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        del run_manager
        engine = HybridPolicyRetriever(
            lexical_weight=self.rag_config.lexical_weight,
            vector_weight=self.rag_config.vector_weight,
            min_vector_score=self.rag_config.min_vector_score,
            chunk_size=self.rag_config.chunk_size,
        )
        hits = engine.search(query, self.policies, limit=self.rag_config.top_k)
        return [
            Document(
                page_content=hit.policy.content,
                metadata={
                    "policy_id": hit.policy.id,
                    "title": hit.policy.title,
                    "version": hit.policy.version,
                    "effective_date": hit.policy.effective_date,
                    "keywords": list(hit.policy.keywords),
                    "citation": hit.citation,
                    "relevance_score": hit.rerank_score,
                    "lexical_score": hit.lexical_score,
                    "vector_score": hit.vector_score,
                    "matched_terms": list(hit.matched_terms),
                    "forced_match": False,
                },
            )
            for hit in hits
        ]


def build_policy_retriever(
    policies: list[PolicyClause],
    config: RAGConfig | None = None,
) -> LangChainPolicyRetriever:
    return LangChainPolicyRetriever(policies=policies, rag_config=config or RAGConfig.from_settings())
