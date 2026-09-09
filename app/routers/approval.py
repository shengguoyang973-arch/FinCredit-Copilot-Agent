from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain import ApplicationStatus, Role, User
from app.repository import audit, get_application, update_status
from app.schemas import ApprovalDecisionRequest
from app.security import require_roles
from app.workflow_store import decide_approval_task, get_approval_task

router = APIRouter(prefix="/v1/approval-tasks", tags=["approval"])


@router.get("/{task_id}")
def approval_task(task_id: str, user: User = Depends(require_roles(Role.RISK_MANAGER, Role.APPROVER, Role.COMPLIANCE_ADMIN))) -> dict:
    task = get_approval_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="审批任务不存在")
    audit("approval_task_viewed", user.id, task_id)
    return task


@router.post("/{task_id}/decision")
def decide_task(task_id: str, body: ApprovalDecisionRequest, user: User = Depends(require_roles(Role.APPROVER))) -> dict:
    try:
        task = decide_approval_task(task_id, body.decision, user.id, body.comment)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    application = get_application(task["application_id"])
    assert application is not None
    target_status = {"approved": ApplicationStatus.APPROVED, "rejected": ApplicationStatus.REJECTED, "returned": ApplicationStatus.PRE_REVIEWED}[body.decision]
    update_status(application, target_status)
    audit("approval_decided", user.id, application.id, decision=body.decision, task_id=task_id)
    return {"application_id": application.id, "application_status": application.status, "approval_task": task,
            "message": "人工审批决定已记录；系统未自动作出任何授信决定。"}
