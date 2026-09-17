"""Human-approved, de-identified evaluation canaries for release readiness."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from app.agent_provider import provider_by_name
from app.config import get_settings
from app.database import connection as database_connection
from app.evaluation import evaluate_provider
from app.evaluation_dataset import load_evaluation_dataset
from app.integration_outbox import enqueue_in_transaction
from app.state_store import audit_in_transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _criteria() -> dict:
    settings = get_settings()
    return {
        "minimum_accuracy": settings.canary_min_accuracy,
        "minimum_evidence_recall": settings.canary_min_evidence_recall,
        "maximum_boundary_violation_rate": settings.canary_max_boundary_violation_rate,
        "maximum_regression_from_baseline": 0.03,
    }


def create_canary(*, name: str, candidate_provider: str, baseline_provider: str, traffic_percent: int, actor_id: str) -> dict:
    settings = get_settings()
    if traffic_percent > settings.canary_max_traffic_percent:
        raise ValueError("灰度比例超过 FINCREDIT_CANARY_MAX_TRAFFIC_PERCENT 上限")
    manifest, _ = load_evaluation_dataset()
    canary_id, now = f"CAN-{uuid4().hex[:16].upper()}", _now()
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT OR IGNORE INTO evaluation_dataset_manifests(
                dataset_id, dataset_hash, classification, case_count, source_label, registered_by, registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (manifest["dataset_id"], manifest["dataset_hash"], manifest["classification"], manifest["case_count"], manifest["source_label"], actor_id, now),
        )
        try:
            connection.execute(
                """INSERT INTO evaluation_canaries(
                    id, name, candidate_provider, baseline_provider, dataset_id, dataset_hash, traffic_percent,
                    criteria_json, status, created_by, created_at, submitted_by, submitted_at, reviewed_by,
                    reviewed_at, review_comment, executed_by, executed_at, report_json, finalized_by, finalized_at, final_comment
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)""",
                (canary_id, name, candidate_provider, baseline_provider, manifest["dataset_id"], manifest["dataset_hash"], traffic_percent, _json(_criteria()), actor_id, now),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("灰度发布名称已存在") from error
        audit_in_transaction(connection, "evaluation_canary_created", actor_id, canary_id, name=name, dataset_hash=manifest["dataset_hash"], traffic_percent=traffic_percent)
    return get_canary(canary_id)  # type: ignore[return-value]


def list_canaries(*, status: str | None = None, limit: int = 100) -> list[dict]:
    query, values = "SELECT * FROM evaluation_canaries", []
    if status:
        query += " WHERE status = ?"
        values.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    values.append(limit)
    with database_connection() as connection:
        rows = connection.execute(query, values).fetchall()
    return [_from_row(row) for row in rows]


def get_canary(canary_id: str) -> dict | None:
    with database_connection() as connection:
        row = connection.execute("SELECT * FROM evaluation_canaries WHERE id = ?", (canary_id,)).fetchone()
    return _from_row(row) if row else None


def submit_canary(canary_id: str, *, actor_id: str) -> dict:
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _required(connection, canary_id)
        if row["created_by"] != actor_id or row["status"] != "draft":
            raise ValueError("只有创建人可以提交草稿灰度发布")
        now = _now()
        connection.execute("UPDATE evaluation_canaries SET status = 'pending_review', submitted_by = ?, submitted_at = ? WHERE id = ?", (actor_id, now, canary_id))
        audit_in_transaction(connection, "evaluation_canary_submitted", actor_id, canary_id)
    return get_canary(canary_id)  # type: ignore[return-value]


def decide_canary(canary_id: str, *, decision: str, comment: str, actor_id: str) -> dict:
    if decision not in {"approved", "rejected"}:
        raise ValueError("灰度复核决定无效")
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _required(connection, canary_id)
        if row["status"] != "pending_review":
            raise ValueError("仅待复核的灰度发布可以处理")
        if actor_id in {row["created_by"], row["submitted_by"]}:
            raise PermissionError("灰度发布创建人或提交人不能复核自己的变更")
        now = _now()
        connection.execute("UPDATE evaluation_canaries SET status = ?, reviewed_by = ?, reviewed_at = ?, review_comment = ? WHERE id = ?", (decision, actor_id, now, comment.strip(), canary_id))
        audit_in_transaction(connection, f"evaluation_canary_{decision}", actor_id, canary_id)
    return get_canary(canary_id)  # type: ignore[return-value]


def execute_canary(canary_id: str, *, actor_id: str) -> dict:
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _required(connection, canary_id)
        if row["status"] != "approved":
            raise ValueError("仅已独立批准的灰度发布可以执行脱敏评测")
        connection.execute("UPDATE evaluation_canaries SET status = 'running', executed_by = ?, executed_at = ? WHERE id = ?", (actor_id, _now(), canary_id))
        audit_in_transaction(connection, "evaluation_canary_started", actor_id, canary_id)
    try:
        manifest, cases = load_evaluation_dataset()
        if manifest["dataset_hash"] != row["dataset_hash"]:
            raise ValueError("评测集指纹已变化；必须重新创建灰度发布")
        candidate = evaluate_provider(provider_by_name(row["candidate_provider"]), cases)
        baseline = evaluate_provider(provider_by_name(row["baseline_provider"]), cases)
        criteria = json.loads(row["criteria_json"])
        passed, checks = _evaluate_result(candidate, baseline, criteria)
        report = {"dataset": manifest, "candidate": candidate, "baseline": baseline, "checks": checks}
    except Exception as error:
        passed, report = False, {"error_type": type(error).__name__, "message": "灰度脱敏评测执行失败"}
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = _required(connection, canary_id)
        if current["status"] != "running":
            raise ValueError("灰度发布状态已被并发修改")
        status, now = ("passed" if passed else "failed"), _now()
        connection.execute("UPDATE evaluation_canaries SET status = ?, report_json = ?, executed_at = ? WHERE id = ?", (status, _json(report), now, canary_id))
        audit_in_transaction(connection, f"evaluation_canary_{status}", actor_id, canary_id, dataset_hash=current["dataset_hash"])
        if not passed:
            enqueue_in_transaction(connection, destination="siem", event_type="evaluation.canary.failed", severity="high", payload={"canary_id": canary_id, "status": "failed", "dataset_hash": current["dataset_hash"]}, dedupe_key=f"evaluation.canary.failed:{canary_id}")
    return get_canary(canary_id)  # type: ignore[return-value]


def finalize_canary(canary_id: str, *, action: str, comment: str, actor_id: str) -> dict:
    if action not in {"promoted", "rolled_back"}:
        raise ValueError("灰度最终动作无效")
    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = _required(connection, canary_id)
        if action == "promoted" and row["status"] != "passed":
            raise ValueError("只有通过脱敏评测的灰度发布可以标记为可推进")
        if action == "rolled_back" and row["status"] not in {"approved", "running", "passed", "failed"}:
            raise ValueError("当前灰度发布不能标记回退")
        if actor_id == row["created_by"]:
            raise PermissionError("灰度发布创建人不能执行最终推进或回退确认")
        now = _now()
        connection.execute("UPDATE evaluation_canaries SET status = ?, finalized_by = ?, finalized_at = ?, final_comment = ? WHERE id = ?", (action, actor_id, now, comment.strip(), canary_id))
        audit_in_transaction(connection, f"evaluation_canary_{action}", actor_id, canary_id)
        enqueue_in_transaction(connection, destination="siem", event_type=f"evaluation.canary.{action}", severity="medium", payload={"canary_id": canary_id, "status": action, "dataset_hash": row["dataset_hash"], "traffic_percent": row["traffic_percent"]}, dedupe_key=f"evaluation.canary.{action}:{canary_id}")
    return get_canary(canary_id)  # type: ignore[return-value]


def _evaluate_result(candidate: dict, baseline: dict, criteria: dict) -> tuple[bool, dict]:
    checks = {
        "minimum_accuracy": candidate["accuracy"] >= criteria["minimum_accuracy"],
        "minimum_evidence_recall": candidate["evidence_recall"] >= criteria["minimum_evidence_recall"],
        "maximum_boundary_violation_rate": candidate["boundary_violation_rate"] <= criteria["maximum_boundary_violation_rate"],
        "accuracy_regression": candidate["accuracy"] >= baseline["accuracy"] - criteria["maximum_regression_from_baseline"],
        "evidence_regression": candidate["evidence_recall"] >= baseline["evidence_recall"] - criteria["maximum_regression_from_baseline"],
    }
    return all(checks.values()), checks


def _required(connection: sqlite3.Connection, canary_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM evaluation_canaries WHERE id = ?", (canary_id,)).fetchone()
    if not row:
        raise KeyError("灰度发布不存在")
    return row


def _from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "candidate_provider": row["candidate_provider"], "baseline_provider": row["baseline_provider"],
        "dataset_id": row["dataset_id"], "dataset_hash": row["dataset_hash"], "traffic_percent": row["traffic_percent"],
        "criteria": json.loads(row["criteria_json"]), "status": row["status"], "created_by": row["created_by"], "created_at": row["created_at"],
        "submitted_by": row["submitted_by"], "submitted_at": row["submitted_at"], "reviewed_by": row["reviewed_by"], "reviewed_at": row["reviewed_at"],
        "review_comment": row["review_comment"], "executed_by": row["executed_by"], "executed_at": row["executed_at"],
        "report": json.loads(row["report_json"]) if row["report_json"] else None, "finalized_by": row["finalized_by"],
        "finalized_at": row["finalized_at"], "final_comment": row["final_comment"],
    }
