from fastapi.testclient import TestClient

from app import online_evaluation
from app.main import app


client = TestClient(app)
COMPLIANCE = {"X-User-Id": "compliance_001"}
RISK = {"X-User-Id": "rm_001"}


def test_online_evaluation_requires_baseline_before_it_declares_health() -> None:
    response = client.get("/v1/observability/online-evaluation", headers=COMPLIANCE)
    assert response.status_code == 200
    assert response.json()["status"] in {"insufficient_data", "baseline_required"}


def test_baseline_and_drift_alerts_use_persisted_run_metrics(monkeypatch) -> None:
    monkeypatch.setenv("FINCREDIT_DRIFT_MIN_SAMPLES", "1")
    run = client.post(
        "/v1/applications/APP001/agent-question", headers=RISK, json={"question": "下一步如何处理？"},
    )
    assert run.status_code == 200
    baseline = client.post("/v1/observability/online-evaluation/baselines", headers=COMPLIANCE, json={})
    assert baseline.status_code == 201
    assert baseline.json()["baseline"]["sample_count"] >= 1

    monkeypatch.setattr(online_evaluation, "online_run_metrics", lambda limit=None: {
        "sample_count": 1, "window_runs": 50, "fallback_rate": 1.0, "p95_latency_ms": 10_000.0,
        "evidence_coverage": 1.0, "boundary_violation_rate": 0.0,
        "plan_adherence_rate": 1.0, "plan_sample_count": 1,
    })
    assessment = online_evaluation.assess_and_sync_alerts()
    assert assessment["status"] == "alert"
    assert {item["signal"] for item in assessment["alerts"]} == {"fallback_rate", "p95_latency_ms"}
    listed = client.get("/v1/observability/drift-alerts", headers=COMPLIANCE)
    assert listed.status_code == 200
    assert {item["signal"] for item in listed.json()["items"]} == {"fallback_rate", "p95_latency_ms"}
    alert_id = listed.json()["items"][0]["id"]
    action = client.post(
        f"/v1/observability/drift-alerts/{alert_id}/actions", headers=COMPLIANCE,
        json={"action": "investigating", "comment": "已创建排查工单并核对模型服务日志。"},
    )
    assert action.status_code == 201
    history = client.get(f"/v1/observability/drift-alerts/{alert_id}/actions", headers=COMPLIANCE)
    assert history.status_code == 200
    assert history.json()["items"][0]["action"] == "investigating"
    missing = client.get("/v1/observability/drift-alerts/ADA-UNKNOWN/actions", headers=COMPLIANCE)
    assert missing.status_code == 404
