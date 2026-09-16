"""Four-eyes governed runtime Prompt versions linked to review feedback."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

from app.database import connection as database_connection
from app.state_store import audit_in_transaction


SUPPORTED_TASKS = frozenset({"generate_brief", "answer_question"})
_REQUIRED_TEXT = {
    "generate_brief": ("不得自动批准、拒绝或退回授信申请", "合法 JSON", "summary", "evidence_ids"),
    "answer_question": ("不得自动批准、拒绝或退回授信申请", "合法 JSON", "answer", "supporting_evidence_ids"),
}


def _connection() -> sqlite3.Connection:
    return database_connection()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize() -> None:
    """Seed the immutable v1 runtime baselines exactly once."""
    from app.prompt_registry import DEFAULT_PROMPTS

    with _connection() as connection:
        if connection.execute("SELECT COUNT(*) FROM prompt_versions").fetchone()[0]:
            return
        now = _now()
        for prompt in DEFAULT_PROMPTS.values():
            connection.execute(
                """INSERT INTO prompt_versions(
                    task, version, prompt_id, content, content_hash, status, feedback_ids_json,
                    rationale, created_by, submitted_by, reviewed_by, review_comment, created_at, activated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', '[]', ?, 'system', 'system', 'system', ?, ?, ?)""",
                (
                    prompt.task, prompt.version, prompt.prompt_id, prompt.content,
                    _content_hash(prompt.task, prompt.prompt_id, prompt.version, prompt.content, []),
                    "系统内置受控基线", "系统种子基线", now, now,
                ),
            )
            audit_in_transaction(
                connection, "prompt_baseline_seeded", "system", prompt.task,
                version=prompt.version, content_hash=_content_hash(
                    prompt.task, prompt.prompt_id, prompt.version, prompt.content, []
                ),
            )


def validate_prompt_content(task: str, content: str) -> str:
    if task not in SUPPORTED_TASKS:
        raise ValueError("不支持的 Prompt 任务")
    normalized = content.strip()
    if any(required not in normalized for required in _REQUIRED_TEXT[task]):
        raise ValueError("Prompt 必须保留结构化输出与人工授信决策边界约束")
    if "忽略" in normalized and "指令" in normalized:
        raise ValueError("Prompt 不允许包含覆盖既有指令的措辞")
    return normalized


def create_prompt_draft(
    *, task: str, version: str, content: str, feedback_ids: list[str], rationale: str, actor_id: str,
    audit_action: str = "prompt_draft_created", audit_detail: dict | None = None,
) -> dict:
    content = validate_prompt_content(task, content)
    if not re.fullmatch(r"v[1-9][0-9]{0,20}", version):
        raise ValueError("Prompt 版本必须使用 vN 格式")
    if len(feedback_ids) != len(set(feedback_ids)):
        raise ValueError("feedback_ids 不能包含重复项")
    if not rationale.strip():
        raise ValueError("Prompt 变更原因不能为空")
    _validate_feedback_ids(feedback_ids)
    item = {
        "task": task, "version": version, "prompt_id": _prompt_id(task), "content": content,
        "feedback_ids": sorted(feedback_ids), "rationale": rationale.strip(), "created_by": actor_id,
        "created_at": _now(),
    }
    item["content_hash"] = _content_hash(task, item["prompt_id"], version, content, item["feedback_ids"])
    with _connection() as connection:
        try:
            connection.execute(
                """INSERT INTO prompt_versions(
                    task, version, prompt_id, content, content_hash, status, feedback_ids_json,
                    rationale, created_by, submitted_by, reviewed_by, review_comment, created_at, activated_at
                ) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, NULL, NULL, NULL, ?, NULL)""",
                (
                    item["task"], item["version"], item["prompt_id"], item["content"], item["content_hash"],
                    _json(item["feedback_ids"]), item["rationale"], item["created_by"], item["created_at"],
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("该 Prompt 任务的版本已存在") from error
        audit_in_transaction(
            connection, audit_action, actor_id, task, version=version, content_hash=item["content_hash"],
            feedback_count=len(item["feedback_ids"]), **(audit_detail or {}),
        )
    return get_prompt_version(task, version)  # type: ignore[return-value]


def submit_prompt(task: str, version: str, actor_id: str) -> dict:
    with _connection() as connection:
        updated = connection.execute(
            """UPDATE prompt_versions SET status = 'pending_review', submitted_by = ?
               WHERE task = ? AND version = ? AND status = 'draft'""",
            (actor_id, task, version),
        )
        if updated.rowcount != 1:
            raise ValueError("仅草稿 Prompt 可以提交复核")
        audit_in_transaction(connection, "prompt_submitted", actor_id, task, version=version)
    return get_prompt_version(task, version)  # type: ignore[return-value]


def decide_prompt(task: str, version: str, actor_id: str, decision: str, comment: str) -> dict:
    if decision not in {"approved", "rejected"}:
        raise ValueError("Prompt 复核决定必须是 approved 或 rejected")
    now = _now()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM prompt_versions WHERE task = ? AND version = ?", (task, version),
        ).fetchone()
        if not row or row["status"] != "pending_review":
            raise ValueError("仅待复核 Prompt 可以审批")
        if actor_id in {row["created_by"], row["submitted_by"]}:
            raise PermissionError("Prompt 作者或提交人不能复核自己的版本")
        if not _hash_matches(row):
            raise ValueError("Prompt 内容哈希不匹配，禁止审批并须重新创建版本")
        if decision == "approved":
            connection.execute(
                "UPDATE prompt_versions SET status = 'retired' WHERE task = ? AND status = 'active'", (task,),
            )
            next_status, activated_at = "active", now
        else:
            next_status, activated_at = "rejected", None
        connection.execute(
            """UPDATE prompt_versions SET status = ?, reviewed_by = ?, review_comment = ?, activated_at = ?
               WHERE task = ? AND version = ?""",
            (next_status, actor_id, comment.strip(), activated_at, task, version),
        )
        audit_in_transaction(
            connection, f"prompt_{decision}", actor_id, task, version=version, status=next_status,
            comment=comment.strip(),
        )
    return get_prompt_version(task, version)  # type: ignore[return-value]


def create_rollback_draft(
    *, task: str, target_version: str, new_version: str, reason: str, actor_id: str,
) -> dict:
    target = get_prompt_version(task, target_version)
    if not target or target["status"] not in {"active", "retired"}:
        raise ValueError("回滚目标必须是已批准的活动或历史 Prompt 版本")
    return create_prompt_draft(
        task=task, version=new_version, content=target["content"], feedback_ids=[],
        rationale=f"rollback:{target_version}:{reason.strip()}", actor_id=actor_id,
        audit_action="prompt_rollback_draft_created",
        audit_detail={"target_version": target_version, "new_version": new_version, "reason": reason.strip()},
    )


def get_active_prompt(task: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM prompt_versions WHERE task = ? AND status = 'active'", (task,),
        ).fetchone()
    return _to_prompt(row) if row else None


def get_prompt_version(task: str, version: str) -> dict | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT * FROM prompt_versions WHERE task = ? AND version = ?", (task, version),
        ).fetchone()
    return _to_prompt(row) if row else None


def list_prompt_versions(*, task: str | None = None, active_only: bool = True) -> list[dict]:
    clauses: list[str] = []
    values: list[str] = []
    if task:
        clauses.append("task = ?")
        values.append(task)
    if active_only:
        clauses.append("status = 'active'")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM prompt_versions{where} ORDER BY task, created_at DESC, version DESC", values,
        ).fetchall()
    return [_to_prompt(row) for row in rows]


def prompt_diff(task: str, version: str) -> dict:
    candidate = get_prompt_version(task, version)
    if not candidate:
        raise ValueError("Prompt 版本不存在")
    with _connection() as connection:
        baseline_row = connection.execute(
            """SELECT * FROM prompt_versions WHERE task = ? AND version <> ?
               AND status IN ('active', 'retired') ORDER BY status = 'active' DESC, activated_at DESC, created_at DESC LIMIT 1""",
            (task, version),
        ).fetchone()
    baseline = _to_prompt(baseline_row) if baseline_row else None
    changes = {
        "content": {"changed": baseline is None or baseline["content"] != candidate["content"], "from_hash": baseline["content_hash"] if baseline else None, "to_hash": candidate["content_hash"]},
        "feedback_ids": {"from": baseline["feedback_ids"] if baseline else [], "to": candidate["feedback_ids"]},
        "rationale": {"from": baseline["rationale"] if baseline else None, "to": candidate["rationale"]},
    }
    return {
        "task": task, "candidate_version": version, "candidate_status": candidate["status"],
        "candidate_content_hash": candidate["content_hash"], "content_hash_valid": _prompt_hash_valid(candidate),
        "baseline_version": baseline["version"] if baseline else None, "changes": changes,
    }


def _validate_feedback_ids(feedback_ids: list[str]) -> None:
    if not feedback_ids:
        return
    placeholders = ",".join("?" for _ in feedback_ids)
    with _connection() as connection:
        rows = connection.execute(f"SELECT id FROM agent_feedback WHERE id IN ({placeholders})", feedback_ids).fetchall()
    if {row["id"] for row in rows} != set(feedback_ids):
        raise ValueError("存在未找到的人工反馈编号，不能作为 Prompt 变更依据")


def _prompt_id(task: str) -> str:
    from app.prompt_registry import DEFAULT_PROMPTS
    try:
        return DEFAULT_PROMPTS[task].prompt_id
    except KeyError as error:
        raise ValueError("不支持的 Prompt 任务") from error


def _hash_matches(row: sqlite3.Row) -> bool:
    return row["content_hash"] == _content_hash(
        row["task"], row["prompt_id"], row["version"], row["content"], json.loads(row["feedback_ids_json"]),
    )


def _prompt_hash_valid(prompt: dict) -> bool:
    return prompt["content_hash"] == _content_hash(
        prompt["task"], prompt["prompt_id"], prompt["version"], prompt["content"], prompt["feedback_ids"],
    )


def _content_hash(task: str, prompt_id: str, version: str, content: str, feedback_ids: list[str]) -> str:
    return hashlib.sha256(_json({
        "task": task, "prompt_id": prompt_id, "version": version, "content": content,
        "feedback_ids": sorted(feedback_ids),
    }).encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _to_prompt(row: sqlite3.Row) -> dict:
    return {
        "task": row["task"], "version": row["version"], "prompt_id": row["prompt_id"], "content": row["content"],
        "content_hash": row["content_hash"], "status": row["status"], "feedback_ids": json.loads(row["feedback_ids_json"]),
        "rationale": row["rationale"], "created_by": row["created_by"], "submitted_by": row["submitted_by"],
        "reviewed_by": row["reviewed_by"], "review_comment": row["review_comment"], "created_at": row["created_at"],
        "activated_at": row["activated_at"],
    }
