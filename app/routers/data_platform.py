from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import get_settings
from app.data_platform import (
    get_ingestion_batch,
    ingest_records,
    list_canonical_records,
    list_data_contracts,
    list_ingestion_batches,
    list_lineage_events,
    save_data_contract,
    verify_lineage_chain,
)
from app.domain import Role, User
from app.schemas import DataContractUpsertRequest, DataIngestionRequest
from app.security import require_roles
from app.state_store import audit


router = APIRouter(prefix="/v1/data-platform", tags=["data-platform"])


@router.get("/catalog")
def catalog(
    include_retired: bool = False,
    user: User = Depends(require_roles(Role.RISK_MANAGER, Role.APPROVER, Role.COMPLIANCE_ADMIN)),
) -> dict:
    if include_retired and Role.COMPLIANCE_ADMIN not in user.roles:
        raise HTTPException(status_code=403, detail="仅合规管理员可查看已退役数据契约")
    items = list_data_contracts(include_retired=include_retired)
    audit("data_catalog_viewed", user.id, "data_catalog", result_count=len(items), include_retired=include_retired)
    return {"items": items}


@router.post("/contracts", status_code=status.HTTP_201_CREATED)
def publish_contract(
    body: DataContractUpsertRequest,
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    try:
        contract = save_data_contract(body.model_dump(by_alias=True), user.id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"message": "数据契约已发布；旧生效版本已退役", "contract": contract}


@router.post("/ingestion-batches", status_code=status.HTTP_201_CREATED)
def ingest_batch(
    body: DataIngestionRequest,
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    if len(body.records) > get_settings().data_platform_max_batch_records:
        raise HTTPException(status_code=422, detail="数据批次记录数超过 FINCREDIT_DATA_PLATFORM_MAX_BATCH_RECORDS 限制")
    try:
        batch = ingest_records(
            source_system=body.source_system, contract_id=body.contract_id,
            organization_id=body.organization_id, records=body.records, actor_id=user.id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "message": "数据批次已通过契约和质量校验并发布" if batch["status"] == "accepted" else "数据批次已拒绝；未发布任何规范记录",
        "batch": batch,
    }


@router.get("/batches")
def batches(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    items = list_ingestion_batches(limit=limit)
    audit("data_batches_viewed", user.id, "data_platform", result_count=len(items))
    return {"items": items}


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: str, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    batch = get_ingestion_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="数据接入批次不存在")
    audit("data_batch_viewed", user.id, batch_id)
    return batch


@router.get("/records/{entity_type}")
def canonical_records(
    entity_type: str,
    organization_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_roles(Role.RISK_MANAGER, Role.APPROVER, Role.COMPLIANCE_ADMIN)),
) -> dict:
    if Role.COMPLIANCE_ADMIN not in user.roles:
        if organization_id and organization_id != user.organization_id:
            raise HTTPException(status_code=403, detail="当前组织无权读取目标组织的规范数据")
        organization_id = user.organization_id
    items = list_canonical_records(entity_type=entity_type, organization_id=organization_id, limit=limit)
    audit("canonical_data_viewed", user.id, f"canonical.{entity_type}", organization_id=organization_id, result_count=len(items))
    return {"entity_type": entity_type, "organization_id": organization_id, "items": items}


@router.get("/lineage")
def lineage(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    items = list_lineage_events(limit=limit)
    audit("data_lineage_viewed", user.id, "data_lineage", result_count=len(items))
    return {"items": items}


@router.get("/lineage/integrity")
def lineage_integrity(user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    result = verify_lineage_chain()
    audit("data_lineage_integrity_checked", user.id, "data_lineage", valid=result["valid"])
    return result
