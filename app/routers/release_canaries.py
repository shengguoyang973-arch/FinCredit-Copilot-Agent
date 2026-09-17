from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.canary_release_store import create_canary, decide_canary, execute_canary, finalize_canary, list_canaries, submit_canary
from app.domain import Role, User
from app.schemas import CanaryCreateRequest, CanaryDecisionRequest, CanaryFinalizationRequest
from app.security import require_roles


router = APIRouter(prefix="/v1/release-canaries", tags=["release-canaries"])


@router.get("")
def canaries(limit: int = Query(default=100, ge=1, le=500), user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    return {"items": list_canaries(limit=limit)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: CanaryCreateRequest, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    try:
        item = create_canary(candidate_provider=body.candidate_provider, baseline_provider=body.baseline_provider, name=body.name, traffic_percent=body.traffic_percent, actor_id=user.id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"message": "脱敏灰度发布草稿已创建；不会自动改变线上模型或 Prompt。", "canary": item}


@router.post("/{canary_id}/submit")
def submit(canary_id: str, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    try:
        item = submit_canary(canary_id, actor_id=user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"canary": item}


@router.post("/{canary_id}/decision")
def decide(canary_id: str, body: CanaryDecisionRequest, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    try:
        item = decide_canary(canary_id, decision=body.decision, comment=body.comment, actor_id=user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"canary": item}


@router.post("/{canary_id}/execute")
def execute(canary_id: str, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    try:
        item = execute_canary(canary_id, actor_id=user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"message": "脱敏灰度评测已完成；结果不自动投产。", "canary": item}


@router.post("/{canary_id}/finalize")
def finalize(canary_id: str, body: CanaryFinalizationRequest, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    try:
        item = finalize_canary(canary_id, action=body.action, comment=body.comment, actor_id=user.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"message": "灰度结论已留痕；实际生产变更仍须走既有 Prompt/部署治理。", "canary": item}
