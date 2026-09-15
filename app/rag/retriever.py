from __future__ import annotations

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict
from functools import lru_cache

from app.config import get_settings
from app.domain import PolicyClause
from app.embedding import get_embedding_adapter
from app.hybrid_retrieval import HybridPolicyRetriever
from app.rag.contracts import RAGConfig
from app.vector_store import get_vector_store


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
        settings = get_settings()
        engine = _runtime_engine(
            self.rag_config.lexical_weight, self.rag_config.vector_weight,
            self.rag_config.min_vector_score, self.rag_config.chunk_size,
            settings.embedding_provider, settings.embedding_model, settings.embedding_dimensions,
            settings.vector_store_backend, settings.pgvector_connection, settings.pgvector_collection,
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


@lru_cache(maxsize=16)
def _runtime_engine(
    lexical_weight: float, vector_weight: float, min_vector_score: float, chunk_size: int,
    embedding_provider: str, embedding_model: str, embedding_dimensions: int,
    vector_backend: str, pgvector_connection: str, pgvector_collection: str,
) -> HybridPolicyRetriever:
    # The explicit arguments form a non-secret cache key. This keeps policy
    # embeddings warm across requests while still rotating on configuration changes.
    del embedding_provider, embedding_model, embedding_dimensions, vector_backend, pgvector_connection, pgvector_collection
    settings = get_settings()
    embedding = get_embedding_adapter(settings)
    return HybridPolicyRetriever(
        embedding=embedding,
        store=get_vector_store(embedding, settings),
        lexical_weight=lexical_weight,
        vector_weight=vector_weight,
        min_vector_score=min_vector_score,
        chunk_size=chunk_size,
    )
