from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.domain import Role, User
from app.human_feedback import drift_alert_exists, list_drift_alert_actions, record_drift_alert_action
from app.metrics import agent_metrics
from app.online_evaluation import (
    assess_and_sync_alerts,
    create_baseline,
    list_drift_alerts,
    online_evaluation_report,
    prompt_performance_report,
)
from app.prompt_observation_store import (
    create_observation_review,
    decide_observation_review,
    get_observation_review,
    list_observation_reviews,
)
from app.prompt_store import get_prompt_version
from app.repository import audit
from app.schemas import (
    DriftAlertActionRequest,
    OnlineEvaluationBaselineRequest,
    PromptObservationReviewDecisionRequest,
    PromptObservationReviewRequest,
)
from app.security import require_roles

router = APIRouter(prefix="/v1/observability", tags=["observability"])


@router.get("/agent-metrics")
def get_agent_metrics(limit: int = Query(default=200, ge=1, le=1000), user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    return agent_metrics(limit) | {
        "online_evaluation": online_evaluation_report(),
        "prompt_performance": prompt_performance_report(limit),
    }


@router.get("/prompt-performance")
def get_prompt_performance(
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    report = prompt_performance_report(limit)
    audit(
        "prompt_performance_viewed",
        user.id,
        "agent_prompt_performance",
        completed_run_count=report["completed_run_count"],
        cohort_count=len(report["cohorts"]),
    )
    return report


@router.get("/prompt-performance/{task}/{version}/reviews")
def prompt_observation_reviews(
    task: str,
    version: str,
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    prompt = get_prompt_version(task, version)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 版本不存在")
    items = list_observation_reviews(task=task, version=version)
    audit("prompt_observation_reviews_viewed", user.id, task, version=version, result_count=len(items))
    return {"task": task, "version": version, "items": items}


@router.post("/prompt-performance/{task}/{version}/reviews", status_code=status.HTTP_201_CREATED)
def create_prompt_observation_review(
    task: str,
    version: str,
    body: PromptObservationReviewRequest,
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    prompt = get_prompt_version(task, version)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 版本不存在")
    if prompt["status"] not in {"active", "retired"}:
        raise HTTPException(status_code=409, detail="仅已批准的活动或历史 Prompt 版本可以发起观察复盘")
    performance = prompt_performance_report(limit)
    cohort = next(
        (item for item in performance["cohorts"] if item["task"] == task and item["prompt_version"] == version),
        None,
    )
    if not cohort:
        raise HTTPException(status_code=409, detail="当前观察窗口没有该 Prompt 版本的完成 Agent Run")
    try:
        review = create_observation_review(
            task=task,
            version=version,
            cohort=cohort,
            window_runs=performance["window_runs"],
            minimum_workflow_outcomes=performance["minimum_workflow_outcomes"],
            recommendation=body.recommendation,
            rationale=body.rationale,
            actor_id=user.id,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return {
        "message": "Prompt 发布后观察复盘已创建，须由另一名合规管理员处理；不会自动回滚或变更授信决定。",
        "review": review,
    }


@router.post("/prompt-performance/{task}/{version}/reviews/{review_id}/decision")
def decide_prompt_observation_review(
    task: str,
    version: str,
    review_id: str,
    body: PromptObservationReviewDecisionRequest,
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    existing = get_observation_review(review_id)
    if not existing or existing["task"] != task or existing["version"] != version:
        raise HTTPException(status_code=404, detail="Prompt 观察复盘不属于指定版本")
    try:
        review = decide_observation_review(
            review_id, decision=body.decision, comment=body.comment, actor_id=user.id,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    message = "Prompt 发布后观察复盘已由独立合规管理员确认。"
    if body.decision == "rejected":
        message = "Prompt 发布后观察复盘已驳回。"
    return {"message": message, "review": review}


@router.get("/online-evaluation")
def get_online_evaluation(user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    report = online_evaluation_report()
    audit("online_evaluation_viewed", user.id, "agent_online_evaluation", status=report["status"])
    return report


@router.post("/online-evaluation/baselines", status_code=status.HTTP_201_CREATED)
def establish_online_baseline(
    body: OnlineEvaluationBaselineRequest,
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    try:
        baseline = create_baseline(name=body.name, actor_id=user.id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    audit("online_evaluation_baseline_created", user.id, baseline["id"], name=body.name, sample_count=baseline["sample_count"])
    return {"message": "线上评估基线已建立", "baseline": baseline}


@router.post("/online-evaluation/assess")
def assess_online_evaluation(user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    report = assess_and_sync_alerts()
    audit(
        "online_evaluation_assessed", user.id, "agent_online_evaluation",
        status=report["status"], signal_count=len(report["signals"]), open_alert_count=len(report["alerts"]),
    )
    return report


@router.get("/drift-alerts")
def drift_alerts(
    alert_status: Literal["open", "resolved"] | None = Query(default="open", alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    items = list_drift_alerts(status=alert_status, limit=limit)
    audit("agent_drift_alerts_viewed", user.id, "agent_online_evaluation", status=alert_status, result_count=len(items))
    return {"items": items}


@router.get("/drift-alerts/{alert_id}/actions")
def drift_alert_actions(alert_id: str, user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    if not drift_alert_exists(alert_id):
        raise HTTPException(status_code=404, detail="漂移告警不存在")
    items = list_drift_alert_actions(alert_id)
    audit("agent_drift_alert_actions_viewed", user.id, alert_id, result_count=len(items))
    return {"alert_id": alert_id, "items": items}


@router.post("/drift-alerts/{alert_id}/actions", status_code=status.HTTP_201_CREATED)
def add_drift_alert_action(
    alert_id: str,
    body: DriftAlertActionRequest,
    user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN)),
) -> dict:
    try:
        item = record_drift_alert_action(
            alert_id=alert_id, action=body.action, comment=body.comment, actor_id=user.id,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    audit("agent_drift_alert_action_recorded", user.id, alert_id, alert_action=item["action"])
    return {"message": "漂移告警处置已记录", "action": item}
