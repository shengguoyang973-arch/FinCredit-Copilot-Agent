from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.domain import PolicyClause, Role, User
from app.knowledge_store import list_policies, save_policy
from app.rag import RAGConfig, retrieve_policy_context
from app.repository import audit
from app.schemas import PolicyImportRequest, PolicySearchRequest
from app.security import current_user, require_roles

router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])


@router.post("/search")
def knowledge_search(body: PolicySearchRequest, user: User = Depends(current_user)) -> dict:
    retrieval = retrieve_policy_context(body.query, list_policies())
    audit(
        "policy_searched",
        user.id,
        "policy_library",
        query=body.query,
        result_count=len(retrieval.hits),
        retriever=retrieval.retriever,
    )
    return {
        "query": body.query,
        "retriever": retrieval.retriever,
        "rag_config": retrieval.config.to_dict(),
        "results": [hit.policy.__dict__ | {
            "relevance_score": hit.relevance_score,
            "lexical_score": hit.document.metadata.get("lexical_score", 0.0),
            "vector_score": hit.document.metadata.get("vector_score", 0.0),
            "matched_terms": hit.document.metadata.get("matched_terms", []),
            "citation": hit.document.metadata.get("citation"),
        } for hit in retrieval.hits],
    }


@router.get("/rag-config")
def rag_config(user: User = Depends(current_user)) -> dict:
    config = RAGConfig.from_settings()
    audit("rag_config_viewed", user.id, "policy_library", retriever="langchain-hybrid-policy-v1")
    return {"retriever": "langchain-hybrid-policy-v1", "config": config.to_dict()}


@router.get("/policies")
def policies(user: User = Depends(current_user)) -> dict:
    items = list_policies()
    audit("policy_library_viewed", user.id, "policy_library", result_count=len(items))
    return {"items": [policy.__dict__ for policy in items]}


@router.post("/policies", status_code=status.HTTP_201_CREATED)
def import_policy(body: PolicyImportRequest, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    clause = PolicyClause(body.id, body.title, body.content, body.version, body.effective_date, tuple(body.keywords))
    save_policy(clause, body.source_name)
    audit("policy_imported", user.id, clause.id, source_name=body.source_name, version=body.version)
    return {"message": "政策条款已入库", "policy": clause.__dict__}
