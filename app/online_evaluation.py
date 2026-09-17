"""Online quality evaluation and drift alerts for persisted Agent runs.

The evaluator deliberately uses only structured run metadata and model outputs;
it never copies customer data, material text, or prompts into alert records.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from app.config import get_settings
from app.database import connection as database_connection
from app.human_feedback import feedback_metrics, feedback_verdicts_by_run
from app.prompt_observation_store import latest_observation_review_summaries
from app.workflow_store import list_agent_run_workflow_outcomes, list_all_agent_runs


def _connection() -> sqlite3.Connection:
    return database_connection()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def online_run_metrics(limit: int | None = None) -> dict:
    """Compute privacy-preserving online quality signals for recent completed runs."""
    settings = get_settings()
    runs = list_all_agent_runs(limit or settings.online_evaluation_window_runs)
    completed = [run for run in runs if run["state"] == "completed"]
    fallback_count = 0
    durations: list[float] = []
    evidence_coverages: list[float] = []
    plan_adherence: list[float] = []
    boundary_violations = 0
    for run in completed:
        snapshot = run["input_snapshot"]
        output = run["output"]
        fallback_count += int(bool(output.get("fallback")))
        duration = snapshot.get("duration_ms")
        if isinstance(duration, int | float):
            durations.append(float(duration))
        expected_evidence = {str(item) for item in snapshot.get("evidence_ids", [])}
        actual_evidence = {
            str(item) for item in output.get("evidence_ids", output.get("supporting_evidence_ids", []))
        }
        evidence_coverages.append(
            len(expected_evidence.intersection(actual_evidence)) / len(expected_evidence) if expected_evidence else 1.0
        )
        planned = snapshot.get("planned_tool_names", [])
        if planned:
            actual_tools = snapshot.get("tool_names", [])
            execution = snapshot.get("plan_execution", [])
            plan_adherence.append(float(
                actual_tools == planned and all(step.get("status") == "completed" for step in execution)
            ))
        if _has_boundary_violation(output):
            boundary_violations += 1
    total = len(completed)
    return {
        "sample_count": total,
        "window_runs": limit or settings.online_evaluation_window_runs,
        "fallback_rate": _rate(fallback_count, total),
        "p95_latency_ms": _percentile(durations, 0.95),
        "evidence_coverage": _mean(evidence_coverages),
        "boundary_violation_rate": _rate(boundary_violations, total),
        "plan_adherence_rate": _mean(plan_adherence) if plan_adherence else None,
        "plan_sample_count": len(plan_adherence),
    } | feedback_metrics([run["id"] for run in completed])


def prompt_performance_report(limit: int | None = None) -> dict:
    """Group observable human signals by the frozen Prompt used by each Run.

    A human approval outcome reflects a business-workflow decision, not an
    automated correctness label. The report intentionally never marks a Prompt
    as healthy, better, or safe to use for autonomous credit decisions.
    """
    settings = get_settings()
    window_runs = limit or settings.online_evaluation_window_runs
    completed = [run for run in list_all_agent_runs(window_runs) if run["state"] == "completed"]
    latest_reviews = latest_observation_review_summaries()
    run_ids = [run["id"] for run in completed]
    feedback_by_run = feedback_verdicts_by_run(run_ids)
    outcomes_by_run: dict[str, list[dict]] = {}
    for outcome in list_agent_run_workflow_outcomes(run_ids):
        outcomes_by_run.setdefault(outcome["run_id"], []).append(outcome)

    cohorts: dict[tuple[str, str, str], list[dict]] = {}
    for run in completed:
        snapshot = run["input_snapshot"]
        task = str(snapshot.get("task") or run["task"] or "unknown")
        prompt_id = str(snapshot.get("prompt_id") or "untracked")
        prompt_version = str(snapshot.get("prompt_version") or "untracked")
        cohorts.setdefault((task, prompt_id, prompt_version), []).append(run)

    items: list[dict] = []
    for (task, prompt_id, prompt_version), cohort_runs in cohorts.items():
        cohort_run_ids = {run["id"] for run in cohort_runs}
        verdicts = [
            verdict
            for run_id in cohort_run_ids
            for verdict in feedback_by_run.get(run_id, [])
        ]
        reviewed_runs = sum(bool(feedback_by_run.get(run_id)) for run_id in cohort_run_ids)
        outcomes = [
            outcome
            for run_id in cohort_run_ids
            for outcome in outcomes_by_run.get(run_id, [])
        ]
        decisions = {decision: sum(outcome["decision"] == decision for outcome in outcomes)
                     for decision in ("approved", "rejected", "returned")}
        outcome_count = len(outcomes)
        item = {
            "task": task,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "run_count": len(cohort_runs),
            "feedback_count": len(verdicts),
            "feedback_coverage": _rate(reviewed_runs, len(cohort_runs)),
            "human_acceptance_rate": _rate(sum(verdict == "accepted" for verdict in verdicts), len(verdicts)) if verdicts else None,
            "human_correction_rate": _rate(
                sum(verdict in {"needs_revision", "incorrect"} for verdict in verdicts), len(verdicts)
            ) if verdicts else None,
            "workflow_outcome_count": outcome_count,
            "workflow_outcome_coverage": _rate(outcome_count, len(cohort_runs)),
            "human_decision_counts": decisions,
            "assessment": "observed_only" if outcome_count >= settings.prompt_outcome_min_samples else "insufficient_workflow_outcomes",
        }
        review = latest_reviews.get((task, prompt_version))
        if review:
            item["observation_review"] = review
        items.append(item)
    items.sort(key=lambda item: (-item["run_count"], item["task"], item["prompt_id"], item["prompt_version"]))
    return {
        "window_runs": window_runs,
        "completed_run_count": len(completed),
        "minimum_workflow_outcomes": settings.prompt_outcome_min_samples,
        "cohorts": items,
        "disclaimer": "人工工作流结果仅用于 Prompt 发布后观察，不是模型训练标签、授信结果预测或自动决策依据。",
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * percentile) - 1)], 2)


def _has_boundary_violation(output: dict) -> bool:
    text = _json(output)
    return any(token in text for token in ("系统已批准", "系统已拒绝", "自动批准该笔授信"))


def create_baseline(*, name: str, actor_id: str) -> dict:
    metrics = online_run_metrics()
    settings = get_settings()
    if metrics["sample_count"] < settings.drift_min_samples:
        raise ValueError("完成的 Agent Run 数不足，不能建立线上评估基线")
    if metrics["plan_sample_count"] < settings.drift_min_samples:
        raise ValueError("包含任务规划轨迹的 Agent Run 数不足，不能建立线上评估基线")
    baseline_id, now = f"AEB-{uuid4().hex[:16].upper()}", _now()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "UPDATE agent_evaluation_baselines SET retired_at = ? WHERE name = ? AND retired_at IS NULL", (now, name)
        )
        connection.execute(
            """INSERT INTO agent_evaluation_baselines(
                id, name, metrics_json, sample_count, created_by, created_at, retired_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL)""",
            (baseline_id, name, _json(metrics), metrics["sample_count"], actor_id, now),
        )
    return get_active_baseline(name)  # type: ignore[return-value]


def get_active_baseline(name: str = "default") -> dict | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM agent_evaluation_baselines WHERE name = ? AND retired_at IS NULL", (name,)
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"], "name": row["name"], "metrics": json.loads(row["metrics_json"]),
        "sample_count": row["sample_count"], "created_by": row["created_by"], "created_at": row["created_at"],
    }


def online_evaluation_report(name: str = "default") -> dict:
    metrics = online_run_metrics()
    baseline = get_active_baseline(name)
    status, signals = _assessment(metrics, baseline)
    return {
        "status": status,
        "observed": metrics,
        "baseline": baseline,
        "signals": signals,
        "thresholds": _thresholds(),
    }


def assess_and_sync_alerts(name: str = "default") -> dict:
    report = online_evaluation_report(name)
    if report["status"] not in {"healthy", "alert"}:
        return report | {"alerts": list_drift_alerts(status="open")}
    alerts = _sync_alerts(report["signals"], report["baseline"])
    return report | {"alerts": alerts}


def _assessment(metrics: dict, baseline: dict | None) -> tuple[str, list[dict]]:
    settings = get_settings()
    if metrics["sample_count"] < settings.drift_min_samples or metrics["plan_sample_count"] < settings.drift_min_samples:
        return "insufficient_data", []
    if baseline is None:
        return "baseline_required", []
    base = baseline["metrics"]
    signals: list[dict] = []
    _add_high_signal(signals, "boundary_violation_rate", metrics["boundary_violation_rate"], 0.0, "线上输出触发授信自动决策边界词")
    _add_high_signal(
        signals, "fallback_rate", metrics["fallback_rate"],
        max(settings.drift_max_fallback_rate, float(base["fallback_rate"]) + 0.05),
        "模型降级率超过基线容差或服务目标",
    )
    _add_high_signal(
        signals, "p95_latency_ms", metrics["p95_latency_ms"],
        max(settings.drift_max_p95_latency_ms, float(base["p95_latency_ms"]) * 1.5 + 50),
        "P95 延迟超过基线容差或服务目标",
    )
    _add_low_signal(
        signals, "evidence_coverage", metrics["evidence_coverage"],
        max(settings.drift_min_evidence_coverage, float(base["evidence_coverage"]) - 0.05),
        "输出证据覆盖率低于基线容差或服务目标",
    )
    _add_low_signal(
        signals, "plan_adherence_rate", metrics["plan_adherence_rate"],
        max(settings.drift_min_plan_adherence, float(base["plan_adherence_rate"]) - 0.05),
        "任务规划与实际工具执行不一致",
    )
    return ("alert" if signals else "healthy"), signals


def _add_high_signal(signals: list[dict], signal: str, observed: float, threshold: float, message: str) -> None:
    if observed > threshold:
        signals.append({"signal": signal, "severity": "high", "observed": observed, "threshold": threshold, "message": message})


def _add_low_signal(signals: list[dict], signal: str, observed: float | None, threshold: float, message: str) -> None:
    if observed is not None and observed < threshold:
        signals.append({"signal": signal, "severity": "high", "observed": observed, "threshold": threshold, "message": message})


def _thresholds() -> dict:
    settings = get_settings()
    return {
        "min_samples": settings.drift_min_samples,
        "max_fallback_rate": settings.drift_max_fallback_rate,
        "max_p95_latency_ms": settings.drift_max_p95_latency_ms,
        "min_evidence_coverage": settings.drift_min_evidence_coverage,
        "min_plan_adherence": settings.drift_min_plan_adherence,
    }


def _sync_alerts(signals: list[dict], baseline: dict | None) -> list[dict]:
    if baseline is None:
        return []
    now = _now()
    active_signals = {signal["signal"] for signal in signals}
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        open_rows = connection.execute("SELECT * FROM agent_drift_alerts WHERE status = 'open'").fetchall()
        by_signal = {row["signal"]: row for row in open_rows}
        for signal in signals:
            payload = _json({"observed": signal["observed"], "threshold": signal["threshold"]})
            existing = by_signal.get(signal["signal"])
            if existing:
                connection.execute(
                    """UPDATE agent_drift_alerts
                       SET severity = ?, baseline_id = ?, observed_json = ?, message = ?, last_detected_at = ?
                       WHERE id = ?""",
                    (signal["severity"], baseline["id"], payload, signal["message"], now, existing["id"]),
                )
            else:
                connection.execute(
                    """INSERT INTO agent_drift_alerts(
                        id, signal, severity, status, baseline_id, observed_json, message,
                        first_detected_at, last_detected_at, resolved_at
                    ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, NULL)""",
                    (f"ADA-{uuid4().hex[:16].upper()}", signal["signal"], signal["severity"], baseline["id"],
                     payload, signal["message"], now, now),
                )
        for signal, row in by_signal.items():
            if signal not in active_signals:
                connection.execute(
                    "UPDATE agent_drift_alerts SET status = 'resolved', resolved_at = ? WHERE id = ?", (now, row["id"])
                )
    return list_drift_alerts(status="open")


def list_drift_alerts(*, status: str | None = None, limit: int = 100) -> list[dict]:
    query = "SELECT * FROM agent_drift_alerts"
    values: list[object] = []
    if status:
        query += " WHERE status = ?"
        values.append(status)
    query += " ORDER BY last_detected_at DESC LIMIT ?"
    values.append(limit)
    with _connection() as connection:
        rows = connection.execute(query, values).fetchall()
    return [{
        "id": row["id"], "signal": row["signal"], "severity": row["severity"], "status": row["status"],
        "baseline_id": row["baseline_id"], "observed": json.loads(row["observed_json"]), "message": row["message"],
        "first_detected_at": row["first_detected_at"], "last_detected_at": row["last_detected_at"],
        "resolved_at": row["resolved_at"],
    } for row in rows]
