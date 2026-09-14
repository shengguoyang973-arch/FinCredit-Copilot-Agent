"""LangChain-compatible retrieval-augmented generation primitives."""

from app.rag.contracts import RAGConfig, RAGPolicyHit, RAGResult
from app.rag.retriever import LangChainPolicyRetriever, build_policy_retriever
from app.rag.service import retrieve_policy_context

__all__ = [
    "LangChainPolicyRetriever",
    "RAGConfig",
    "RAGPolicyHit",
    "RAGResult",
    "build_policy_retriever",
    "retrieve_policy_context",
]
