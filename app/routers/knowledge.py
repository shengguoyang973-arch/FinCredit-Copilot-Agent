from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.domain import PolicyClause, PolicyRule, Role, User
from app.knowledge_store import list_policies, save_policy
from app.rag import RAGConfig, retrieve_policy_context
from app.repository import audit
from app.rule_store import list_policy_rules, save_policy_rule
from app.schemas import PolicyImportRequest, PolicyRuleImportRequest, PolicySearchRequest
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
    settings = get_settings()
    retriever = f"langchain-hybrid-{settings.vector_store_backend}-v2"
    audit("rag_config_viewed", user.id, "policy_library", retriever=retriever)
    return {
        "retriever": retriever,
        "config": config.to_dict(),
        "embedding": {"provider": settings.embedding_provider, "model": settings.embedding_model,
                      "dimensions": settings.embedding_dimensions},
        "vector_store": {"backend": settings.vector_store_backend, "collection": settings.pgvector_collection},
    }


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


@router.get("/rules")
def policy_rules(include_inactive: bool = False, user: User = Depends(current_user)) -> dict:
    items = list_policy_rules(active_only=not include_inactive)
    active_versions = {(rule.id, rule.version) for rule in list_policy_rules()}
    audit("policy_rules_viewed", user.id, "policy_rules", result_count=len(items), include_inactive=include_inactive)
    return {"items": [asdict(rule) | {"is_active": (rule.id, rule.version) in active_versions} for rule in items]}


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def import_policy_rule(body: PolicyRuleImportRequest, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    rule = PolicyRule(
        body.id, body.policy_id, body.version, body.rule_type, body.parameters,
        body.severity, body.failure_result, body.failure_message, body.pass_message,
        body.effective_date, body.source_name,
    )
    try:
        save_policy_rule(rule)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    audit("policy_rule_imported", user.id, rule.id, version=rule.version, policy_id=rule.policy_id, rule_type=rule.rule_type)
    return {"message": "政策规则新版本已启用", "rule": asdict(rule)}
