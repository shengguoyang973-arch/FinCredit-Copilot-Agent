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
)
from app.repository import audit
from app.schemas import DriftAlertActionRequest, OnlineEvaluationBaselineRequest
from app.security import require_roles

router = APIRouter(prefix="/v1/observability", tags=["observability"])


@router.get("/agent-metrics")
def get_agent_metrics(limit: int = Query(default=200, ge=1, le=1000), user: User = Depends(require_roles(Role.COMPLIANCE_ADMIN))) -> dict:
    return agent_metrics(limit) | {"online_evaluation": online_evaluation_report()}


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
