"""Four-eyes reviews of privacy-preserving Prompt performance snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from app.database import connection as database_connection
from app.state_store import audit_in_transaction


RECOMMENDATIONS = frozenset({"continue_monitoring", "investigate", "rollback_recommended"})
DECISIONS = frozenset({"acknowledged", "rejected"})


def _connection() -> sqlite3.Connection:
    return database_connection()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def create_observation_review(
    *,
    task: str,
    version: str,
    cohort: dict,
    window_runs: int,
    minimum_workflow_outcomes: int,
    recommendation: str,
    rationale: str,
    actor_id: str,
) -> dict:
    """Persist a reviewable, aggregate-only snapshot for a governed Prompt.

    This accepts precomputed cohort data from the observability service so this
    store remains a persistence boundary and never has access to customer data.
    """
    if recommendation not in RECOMMENDATIONS:
        raise ValueError("不支持的 Prompt 观察建议")
    if cohort.get("workflow_outcome_count", 0) < minimum_workflow_outcomes:
        raise ValueError("最终人工工作流结果样本不足，不能发起 Prompt 观察复盘")
    if cohort.get("task") != task or cohort.get("prompt_version") != version:
        raise ValueError("Prompt 观察分群与目标版本不一致")
    snapshot = {
        "schema_version": "v1",
        "window_runs": window_runs,
        "minimum_workflow_outcomes": minimum_workflow_outcomes,
        "cohort": _safe_cohort(cohort),
        "disclaimer": "该快照仅包含聚合运行、反馈和人工工作流结果，不是模型训练标签或自动授信依据。",
    }
    snapshot_hash = _hash(snapshot)
    item = {
        "id": f"POR-{uuid4().hex[:16].upper()}",
        "task": task,
        "version": version,
        "prompt_id": str(cohort["prompt_id"]),
        "prompt_content_hash": _prompt_content_hash(task, version),
        "recommendation": recommendation,
        "rationale": rationale.strip(),
        "snapshot": snapshot,
        "snapshot_hash": snapshot_hash,
        "status": "pending_review",
        "created_by": actor_id,
        "created_at": _now(),
    }
    if not item["rationale"]:
        raise ValueError("Prompt 观察复盘原因不能为空")
    with _connection() as connection:
        try:
            connection.execute(
                """INSERT INTO prompt_observation_reviews(
                    id, task, version, prompt_id, prompt_content_hash, recommendation, rationale,
                    snapshot_json, snapshot_hash, status, created_by, created_at,
                    reviewed_by, reviewed_at, review_comment
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, NULL, NULL, NULL)""",
                (
                    item["id"], item["task"], item["version"], item["prompt_id"],
                    item["prompt_content_hash"], item["recommendation"], item["rationale"],
                    _json(item["snapshot"]), item["snapshot_hash"], item["created_by"], item["created_at"],
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("该 Prompt 性能快照已经发起过复盘") from error
        audit_in_transaction(
            connection,
            "prompt_observation_review_created",
            actor_id,
            task,
            version=version,
            prompt_id=item["prompt_id"],
            snapshot_hash=snapshot_hash,
            recommendation=recommendation,
            workflow_outcome_count=snapshot["cohort"]["workflow_outcome_count"],
        )
    return get_observation_review(item["id"])  # type: ignore[return-value]


def decide_observation_review(review_id: str, *, decision: str, comment: str, actor_id: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError("Prompt 观察复盘决定必须是 acknowledged 或 rejected")
    now = _now()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM prompt_observation_reviews WHERE id = ?", (review_id,)).fetchone()
        if not row:
            raise KeyError("Prompt 观察复盘不存在")
        if row["status"] != "pending_review":
            raise ValueError("仅待复核的 Prompt 观察复盘可以处理")
        if row["created_by"] == actor_id:
            raise PermissionError("Prompt 观察复盘创建人不能处理自己的复盘")
        updated = connection.execute(
            """UPDATE prompt_observation_reviews
               SET status = ?, reviewed_by = ?, reviewed_at = ?, review_comment = ?
               WHERE id = ? AND status = 'pending_review'""",
            (decision, actor_id, now, comment.strip(), review_id),
        )
        if updated.rowcount != 1:
            raise ValueError("Prompt 观察复盘已被并发处理")
        audit_in_transaction(
            connection,
            f"prompt_observation_review_{decision}",
            actor_id,
            row["task"],
            review_id=review_id,
            version=row["version"],
            prompt_id=row["prompt_id"],
            recommendation=row["recommendation"],
        )
    return get_observation_review(review_id)  # type: ignore[return-value]


def get_observation_review(review_id: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute("SELECT * FROM prompt_observation_reviews WHERE id = ?", (review_id,)).fetchone()
    return _to_review(row) if row else None


def list_observation_reviews(*, task: str, version: str) -> list[dict]:
    with _connection() as connection:
        rows = connection.execute(
            """SELECT * FROM prompt_observation_reviews
               WHERE task = ? AND version = ? ORDER BY created_at DESC, id DESC""",
            (task, version),
        ).fetchall()
    return [_to_review(row) for row in rows]


def latest_observation_review_summaries() -> dict[tuple[str, str], dict]:
    """Expose statuses only when enriching the observability response."""
    with _connection() as connection:
        rows = connection.execute(
            "SELECT * FROM prompt_observation_reviews ORDER BY created_at DESC, id DESC"
        ).fetchall()
    latest: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["task"], row["version"])
        if key not in latest:
            latest[key] = {
                "id": row["id"], "status": row["status"], "recommendation": row["recommendation"],
                "created_at": row["created_at"], "reviewed_at": row["reviewed_at"],
            }
    return latest


def _prompt_content_hash(task: str, version: str) -> str:
    with _connection() as connection:
        row = connection.execute(
            "SELECT content_hash FROM prompt_versions WHERE task = ? AND version = ?", (task, version)
        ).fetchone()
    if not row:
        raise KeyError("Prompt 版本不存在")
    return row["content_hash"]


def _safe_cohort(cohort: dict) -> dict:
    return {
        "task": cohort["task"], "prompt_id": cohort["prompt_id"], "prompt_version": cohort["prompt_version"],
        "run_count": cohort["run_count"], "feedback_count": cohort["feedback_count"],
        "feedback_coverage": cohort["feedback_coverage"],
        "human_acceptance_rate": cohort["human_acceptance_rate"],
        "human_correction_rate": cohort["human_correction_rate"],
        "workflow_outcome_count": cohort["workflow_outcome_count"],
        "workflow_outcome_coverage": cohort["workflow_outcome_coverage"],
        "human_decision_counts": cohort["human_decision_counts"],
    }


def _to_review(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "task": row["task"], "version": row["version"], "prompt_id": row["prompt_id"],
        "prompt_content_hash": row["prompt_content_hash"], "recommendation": row["recommendation"],
        "rationale": row["rationale"], "snapshot": json.loads(row["snapshot_json"]),
        "snapshot_hash": row["snapshot_hash"], "status": row["status"],
        "created_by": row["created_by"], "created_at": row["created_at"],
        "reviewed_by": row["reviewed_by"], "reviewed_at": row["reviewed_at"],
        "review_comment": row["review_comment"],
    }
