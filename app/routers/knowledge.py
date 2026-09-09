from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.domain import PolicyClause, Role, User
from app.knowledge_store import list_policies, save_policy
from app.hybrid_retrieval import retrieve_hybrid_policy_hits
from app.repository import audit
from app.schemas import PolicyImportRequest, PolicySearchRequest
from app.security import current_user, require_roles
from app.services import search_policies

router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])


@router.post("/search")
def knowledge_search(body: PolicySearchRequest, user: User = Depends(current_user)) -> dict:
    hits = retrieve_hybrid_policy_hits(body.query, list_policies())
    audit("policy_searched", user.id, "policy_library", query=body.query, result_count=len(hits))
    return {"query": body.query, "results": [hit.policy.__dict__ | {
        "relevance_score": hit.rerank_score,
        "lexical_score": hit.lexical_score,
        "vector_score": hit.vector_score,
        "matched_terms": list(hit.matched_terms),
        "citation": hit.citation,
    } for hit in hits]}


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
