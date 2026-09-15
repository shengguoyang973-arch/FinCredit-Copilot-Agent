from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, status

from app.approval_policy import SubmissionPolicyError
from app.agent_runtime.queue import get_agent_queue
from app.agent_runtime.guardrails import AgentGuardrailError
from app.config import get_settings
from app.document_store import ALLOWED_TYPES, material_check, save_document
from app.domain import Role, User
from app.repository import audit, get_application, get_customer
from app.schemas import AgentQuestionRequest, ApprovalSubmissionRequest
from app.security import can_access_application, current_user, filter_customer_fields, require_roles
from app.services import answer_business_question, pre_review, resume_agent_run_execution, submit_for_approval
from app.workflow_store import get_report, get_agent_run, list_agent_run_events, list_agent_runs

router = APIRouter(prefix="/v1/applications", tags=["applications"])
settings = get_settings()


def assert_application_access(application_id: str, user: User) -> None:
    application = get_application(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="授信申请不存在")
    if not can_access_application(application, user):
        raise HTTPException(status_code=403, detail="客户经理只能访问本人创建的申请")


@router.get("/{application_id}")
def application_detail(application_id: str, user: User = Depends(current_user)) -> dict:
    application = get_application(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="授信申请不存在")
    if not can_access_application(application, user):
        raise HTTPException(status_code=403, detail="客户经理只能查看本人创建的申请")
    customer = get_customer(application.customer_id)
    audit("application_viewed", user.id, application_id)
    return {"application": application.__dict__, "customer": filter_customer_fields(customer, user)}


@router.get("/{application_id}/materials")
def application_materials(application_id: str, user: User = Depends(current_user)) -> dict:
    assert_application_access(application_id, user)
    result = material_check(application_id)
    audit("materials_viewed", user.id, application_id, complete=result["complete"])
    return result


@router.put("/{application_id}/materials/{document_type}", status_code=status.HTTP_201_CREATED)
def upload_material(application_id: str, document_type: str, content: bytes = Body(), filename: str = Header(..., alias="X-Filename"), content_type: str = Header("application/octet-stream", alias="Content-Type"), user: User = Depends(require_roles(Role.ACCOUNT_MANAGER))) -> dict:
    assert_application_access(application_id, user)
    if document_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=422, detail="不支持的材料类型")
    if len(content) > settings.max_document_bytes:
        raise HTTPException(status_code=413, detail=f"演示版材料大小不得超过 {settings.max_document_bytes // 1_000_000}MB")
    try:
        document = save_document(application_id, document_type, unquote(filename), content_type, content, user.id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    audit("material_uploaded", user.id, application_id, document_id=document["id"], document_type=document_type, sha256=document["sha256"])
    return document


@router.post("/{application_id}/pre-review")
def run_pre_review(application_id: str, user: User = Depends(require_roles(Role.RISK_MANAGER))) -> dict:
    application = get_application(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="授信申请不存在")
    if not can_access_application(application, user):
        raise HTTPException(status_code=403, detail="当前组织无权访问该授信申请")
    try:
        return pre_review(application, user)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("/{application_id}/pre-review-report")
def review_report(application_id: str, user: User = Depends(current_user)) -> dict:
    application = get_application(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="授信申请不存在")
    if not can_access_application(application, user):
        raise HTTPException(status_code=403, detail="客户经理只能查看本人创建的申请报告")
    report = get_report(application_id)
    if not report:
        raise HTTPException(status_code=404, detail="该申请尚未生成预审报告")
    audit("review_report_viewed", user.id, application_id)
    return report | {"customer_snapshot": filter_customer_fields(report.get("customer_snapshot"), user)}


@router.get("/{application_id}/agent-runs")
def agent_runs(application_id: str, user: User = Depends(require_roles(Role.RISK_MANAGER, Role.APPROVER, Role.COMPLIANCE_ADMIN))) -> dict:
    assert_application_access(application_id, user)
    runs = list_agent_runs(application_id)
    audit("agent_runs_viewed", user.id, application_id, result_count=len(runs))
    return {"application_id": application_id, "items": runs}


@router.get("/{application_id}/agent-runs/{run_id}/events")
def agent_run_events(application_id: str, run_id: str, user: User = Depends(require_roles(Role.RISK_MANAGER, Role.APPROVER, Role.COMPLIANCE_ADMIN))) -> dict:
    """Return the append-only lifecycle events for one Agent Run."""
    assert_application_access(application_id, user)
    run = get_agent_run(run_id)
    if not run or run["application_id"] != application_id:
        raise HTTPException(status_code=404, detail="Agent Run 不存在")
    events = list_agent_run_events(run_id)
    audit("agent_run_events_viewed", user.id, application_id, run_id=run_id, result_count=len(events))
    return {"run_id": run_id, "application_id": application_id, "state": run["state"], "items": events}


@router.post("/{application_id}/agent-runs/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_agent_run(application_id: str, run_id: str, background_tasks: BackgroundTasks, user: User = Depends(require_roles(Role.RISK_MANAGER))) -> dict:
    application = get_application(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="授信申请不存在")
    if not can_access_application(application, user):
        raise HTTPException(status_code=403, detail="当前组织无权访问该授信申请")
    try:
        run = get_agent_run(run_id)
        if not run or run["application_id"] != application_id:
            raise ValueError("待恢复的 Agent Run 不存在或不属于当前申请")
        if run["state"] not in {"failed", "context_building"}:
            raise ValueError(f"当前 Run 状态不支持恢复：{run['state']}")
        job = get_agent_queue().enqueue(background_tasks, resume_agent_run_execution, application, user, run_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    audit("agent_run_resume_requested", user.id, application_id, run_id=run_id)
    return {"run_id": run_id, "job_id": job.id, "status": "queued", "message": "已加入 Agent 恢复队列"}


@router.post("/{application_id}/agent-question")
def agent_question(application_id: str, body: AgentQuestionRequest, user: User = Depends(require_roles(Role.RISK_MANAGER, Role.APPROVER, Role.COMPLIANCE_ADMIN))) -> dict:
    assert_application_access(application_id, user)
    application = get_application(application_id)
    assert application is not None
    try:
        return answer_business_question(application, user, body.question)
    except AgentGuardrailError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/{application_id}/submit")
def submit(application_id: str, body: ApprovalSubmissionRequest | None = None, user: User = Depends(require_roles(Role.RISK_MANAGER))) -> dict:
    application = get_application(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="授信申请不存在")
    if not can_access_application(application, user):
        raise HTTPException(status_code=403, detail="当前组织无权访问该授信申请")
    try:
        task = submit_for_approval(application, user, body.override_reason if body else None)
    except SubmissionPolicyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "message": "提交审批未通过策略校验",
            "submission_policy": error.decision.to_dict(),
        }) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return {"application_id": application.id, "status": application.status, "approval_task": task, "message": "已提交人工审批"}
