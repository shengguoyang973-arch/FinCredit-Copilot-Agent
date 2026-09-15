from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain import Role, User
from app.repository import audit, get_application
from app.schemas import ApprovalDecisionRequest
from app.security import can_access_application, require_roles
from app.workflow_store import decide_approval_task, get_approval_task

router = APIRouter(prefix="/v1/approval-tasks", tags=["approval"])


@router.get("/{task_id}")
def approval_task(task_id: str, user: User = Depends(require_roles(Role.RISK_MANAGER, Role.APPROVER, Role.COMPLIANCE_ADMIN))) -> dict:
    task = get_approval_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="审批任务不存在")
    application = get_application(task["application_id"])
    if not application or not can_access_application(application, user):
        raise HTTPException(status_code=403, detail="当前组织无权访问该审批任务")
    audit("approval_task_viewed", user.id, task_id)
    return task


@router.post("/{task_id}/decision")
def decide_task(task_id: str, body: ApprovalDecisionRequest, user: User = Depends(require_roles(Role.APPROVER))) -> dict:
    existing_task = get_approval_task(task_id)
    if not existing_task:
        raise HTTPException(status_code=404, detail="审批任务不存在")
    existing_application = get_application(existing_task["application_id"])
    if not existing_application or not can_access_application(existing_application, user):
        raise HTTPException(status_code=403, detail="当前组织无权处理该审批任务")
    try:
        task = decide_approval_task(task_id, body.decision, user.id, body.comment)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    application = get_application(task["application_id"])
    assert application is not None
    audit("approval_decided", user.id, application.id, decision=body.decision, task_id=task_id)
    return {"application_id": application.id, "application_status": application.status, "approval_task": task,
            "message": "人工审批决定已记录；系统未自动作出任何授信决定。"}
