from __future__ import annotations

import json
import sqlite3
import hashlib
from dataclasses import replace
from datetime import date, datetime, timezone
from string import Formatter
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.database import connection as database_connection
from app.domain import PolicyRule, PolicyRuleStatus
from app.state_store import audit_in_transaction


SEED_POLICY_RULES = (
    PolicyRule(
        "POL-1.2", "POL-1.2", "2026.01", "minimum",
        {"source": "customer", "field": "operating_years", "minimum": 2},
        "block", "fail", "企业持续经营不足两年，不满足基础准入要求。",
        "企业持续经营年限满足准入要求。", "2026-01-01", "seed-policy-rules",
    ),
    PolicyRule(
        "POL-2.1", "POL-2.1", "2026.01", "ratio_cap",
        {"application_field": "requested_amount", "base_field": "annual_revenue", "ratio": 0.30, "absolute_cap": 5_000_000},
        "high", "fail", "申请额度超出建议上限 {suggested_max_amount:,} 元。",
        "申请额度未超过建议上限 {suggested_max_amount:,} 元。", "2026-01-01", "seed-policy-rules",
    ),
    PolicyRule(
        "POL-3.4", "POL-3.4", "2026.01", "any_threshold",
        {"source": "customer", "conditions": [
            {"field": "overdue_days_12m", "operator": "gt", "value": 10},
            {"field": "debt_ratio", "operator": "gt", "value": 0.75},
        ]},
        "high", "review", "存在逾期或高负债率，必须人工强化审查。",
        "未触发逾期与高负债率人工强化审查条件。", "2026-01-01", "seed-policy-rules",
    ),
    PolicyRule(
        "MAT-1", None, "2026.01", "required_materials",
        {"required": {
            "business_license": "营业执照", "financial_statement": "财务报表", "bank_statement": "银行流水",
        }},
        "high", "review", "缺少以下材料：{missing_labels}，须补齐后由人工复核。",
        "必需材料已齐全。", "2026-01-01", "seed-policy-rules",
    ),
)

ALLOWED_RULE_TYPES = {"minimum", "ratio_cap", "any_threshold", "required_materials"}
ALLOWED_SEVERITIES = {"info", "medium", "high", "block"}
ALLOWED_FAILURE_RESULTS = {"fail", "review"}
ALLOWED_CUSTOMER_FIELDS = {"operating_years", "annual_revenue", "debt_ratio", "overdue_days_12m"}
ALLOWED_APPLICATION_FIELDS = {"requested_amount", "term_months"}


def _connection() -> sqlite3.Connection:
    return database_connection()


def initialize() -> None:
    with _connection() as connection:
        if connection.execute("SELECT COUNT(*) FROM policy_rules").fetchone()[0] == 0:
            for rule in SEED_POLICY_RULES:
                save_policy_rule(rule, connection)
        else:
            rows = connection.execute("SELECT * FROM policy_rules WHERE content_hash = ''").fetchall()
            for row in rows:
                connection.execute(
                    "UPDATE policy_rules SET content_hash = ? WHERE id = ? AND version = ?",
                    (_rule_content_hash(_to_rule(row)), row["id"], row["version"]),
                )


def validate_policy_rule(rule: PolicyRule) -> None:
    if rule.rule_type not in ALLOWED_RULE_TYPES:
        raise ValueError(f"不支持的规则类型：{rule.rule_type}")
    if rule.severity not in ALLOWED_SEVERITIES or rule.failure_result not in ALLOWED_FAILURE_RESULTS:
        raise ValueError("规则严重度或失败结果无效")
    params = rule.parameters
    allowed_placeholders = {
        "minimum": set(), "ratio_cap": {"suggested_max_amount"},
        "any_threshold": set(), "required_materials": {"missing_labels"},
    }[rule.rule_type]
    allowed_formats = {"suggested_max_amount": {"", ","}, "missing_labels": {""}}
    for message in (rule.failure_message, rule.pass_message):
        parsed = list(Formatter().parse(message))
        placeholders = {field_name for _, field_name, _, _ in parsed if field_name}
        if not placeholders.issubset(allowed_placeholders):
            raise ValueError(f"规则消息包含不支持的占位符：{sorted(placeholders - allowed_placeholders)}")
        for _, field_name, format_spec, conversion in parsed:
            if field_name and (conversion is not None or format_spec not in allowed_formats[field_name]):
                raise ValueError(f"规则消息占位符格式不受支持：{field_name}")
    if rule.rule_type == "minimum":
        if params.get("source") != "customer" or params.get("field") not in ALLOWED_CUSTOMER_FIELDS:
            raise ValueError("minimum 规则字段不在允许列表中")
        if not isinstance(params.get("minimum"), (int, float)):
            raise ValueError("minimum 规则必须配置数值 minimum")
    elif rule.rule_type == "ratio_cap":
        if params.get("application_field") not in ALLOWED_APPLICATION_FIELDS:
            raise ValueError("ratio_cap 申请字段不在允许列表中")
        if params.get("base_field") not in ALLOWED_CUSTOMER_FIELDS:
            raise ValueError("ratio_cap 客户字段不在允许列表中")
        if not isinstance(params.get("ratio"), (int, float)) or not 0 < params["ratio"] <= 1:
            raise ValueError("ratio_cap 的 ratio 必须在 0 到 1 之间")
        if not isinstance(params.get("absolute_cap"), (int, float)) or params["absolute_cap"] <= 0:
            raise ValueError("ratio_cap 的 absolute_cap 必须大于 0")
    elif rule.rule_type == "any_threshold":
        conditions = params.get("conditions")
        if params.get("source") != "customer" or not isinstance(conditions, list) or not conditions:
            raise ValueError("any_threshold 必须配置客户字段条件")
        for condition in conditions:
            if condition.get("field") not in ALLOWED_CUSTOMER_FIELDS or condition.get("operator") not in {"gt", "gte", "lt", "lte"}:
                raise ValueError("any_threshold 条件字段或操作符无效")
            if not isinstance(condition.get("value"), (int, float)):
                raise ValueError("any_threshold 条件值必须是数值")
    elif rule.rule_type == "required_materials":
        required = params.get("required")
        if not isinstance(required, dict) or not required or not all(isinstance(key, str) and isinstance(value, str) for key, value in required.items()):
            raise ValueError("required_materials 必须配置材料类型与标签")


def save_policy_rule(rule: PolicyRule, connection: sqlite3.Connection | None = None) -> None:
    """Trusted bootstrap/test helper that activates a validated rule immediately."""
    validate_policy_rule(rule)
    owns_connection = connection is None
    connection = connection or _connection()
    try:
        if rule.policy_id:
            exists = connection.execute(
                "SELECT 1 FROM policy_clauses WHERE id = ? AND is_active = 1", (rule.policy_id,),
            ).fetchone()
            if not exists:
                raise ValueError(f"规则引用的政策条款不存在：{rule.policy_id}")
        connection.execute(
            "UPDATE policy_rules SET is_active = 0, status = 'retired' WHERE id = ? AND is_active = 1",
            (rule.id,),
        )
        connection.execute(
            """INSERT OR REPLACE INTO policy_rules
               (id, policy_id, version, rule_type, parameters_json, severity, failure_result,
                failure_message, pass_message, effective_date, source_name, is_active,
                status, created_by, submitted_by, reviewed_by, review_comment, activated_at, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, ?, ?, ?, ?)""",
            (rule.id, rule.policy_id, rule.version, rule.rule_type,
             json.dumps(rule.parameters, ensure_ascii=False, sort_keys=True), rule.severity,
             rule.failure_result, rule.failure_message, rule.pass_message,
             rule.effective_date, rule.source_name, rule.created_by, rule.submitted_by,
             rule.reviewed_by, rule.review_comment,
             rule.activated_at or datetime.now(timezone.utc).isoformat(), _rule_content_hash(rule)),
        )
        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def create_policy_rule_draft(
    rule: PolicyRule,
    actor_id: str,
    *,
    audit_action: str = "policy_rule_draft_created",
    audit_detail: dict | None = None,
) -> PolicyRule:
    validate_policy_rule(rule)
    draft = replace(
        rule,
        status=PolicyRuleStatus.DRAFT,
        is_active=False,
        created_by=actor_id,
        submitted_by=None,
        reviewed_by=None,
        review_comment=None,
        activated_at=None,
        content_hash=_rule_content_hash(rule),
    )
    with _connection() as connection:
        _validate_policy_reference(draft, connection)
        try:
            connection.execute(
                """INSERT INTO policy_rules
                   (id, policy_id, version, rule_type, parameters_json, severity, failure_result,
                    failure_message, pass_message, effective_date, source_name, is_active,
                    status, created_by, submitted_by, reviewed_by, review_comment, activated_at, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'draft', ?, NULL, NULL, NULL, NULL, ?)""",
                (draft.id, draft.policy_id, draft.version, draft.rule_type,
                 json.dumps(draft.parameters, ensure_ascii=False, sort_keys=True), draft.severity,
                 draft.failure_result, draft.failure_message, draft.pass_message,
                 draft.effective_date, draft.source_name, actor_id, draft.content_hash),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"规则版本已存在：{draft.id}/{draft.version}") from error
        audit_in_transaction(
            connection, audit_action, actor_id, draft.id,
            version=draft.version, policy_id=draft.policy_id, rule_type=draft.rule_type,
            **(audit_detail or {}),
        )
    return draft


def submit_policy_rule(rule_id: str, version: str, actor_id: str) -> PolicyRule:
    with _connection() as connection:
        cursor = connection.execute(
            """UPDATE policy_rules SET status = 'pending_review', submitted_by = ?
               WHERE id = ? AND version = ? AND status = 'draft'""",
            (actor_id, rule_id, version),
        )
        if cursor.rowcount != 1:
            raise ValueError("仅草稿规则可以提交复核")
        row = connection.execute(
            "SELECT * FROM policy_rules WHERE id = ? AND version = ?", (rule_id, version),
        ).fetchone()
        audit_in_transaction(connection, "policy_rule_submitted", actor_id, rule_id, version=version)
    return _to_rule(row)


def decide_policy_rule(
    rule_id: str,
    version: str,
    actor_id: str,
    decision: str,
    comment: str,
    *,
    today: date | None = None,
) -> PolicyRule:
    if decision not in {"approved", "rejected"}:
        raise ValueError("规则复核决定必须是 approved 或 rejected")
    today = today or _business_date()
    now = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM policy_rules WHERE id = ? AND version = ?", (rule_id, version),
        ).fetchone()
        if not row or row["status"] != PolicyRuleStatus.PENDING_REVIEW.value:
            raise ValueError("仅待复核规则可以审批")
        if not row["content_hash"] or _rule_content_hash(_to_rule(row)) != row["content_hash"]:
            raise ValueError("规则内容哈希不匹配，禁止审批并须重新创建版本")
        if actor_id in {row["created_by"], row["submitted_by"]}:
            raise PermissionError("规则作者或提交人不能复核自己的规则版本")
        if decision == "rejected":
            status = PolicyRuleStatus.REJECTED
            is_active = 0
            activated_at = None
        elif date.fromisoformat(row["effective_date"]) > today:
            conflict = connection.execute(
                """SELECT 1 FROM policy_rules WHERE id = ? AND status = 'scheduled'
                   AND NOT (id = ? AND version = ?)""",
                (rule_id, rule_id, version),
            ).fetchone()
            if conflict:
                raise ValueError("该规则已有计划生效版本，请先驳回或等待其生效")
            status = PolicyRuleStatus.SCHEDULED
            is_active = 0
            activated_at = None
        else:
            status = PolicyRuleStatus.ACTIVE
            is_active = 1
            activated_at = now
            connection.execute(
                """UPDATE policy_rules SET is_active = 0, status = 'retired'
                   WHERE id = ? AND is_active = 1""",
                (rule_id,),
            )
        connection.execute(
            """UPDATE policy_rules SET status = ?, is_active = ?, reviewed_by = ?,
               review_comment = ?, activated_at = ? WHERE id = ? AND version = ?""",
            (status.value, is_active, actor_id, comment, activated_at, rule_id, version),
        )
        updated = connection.execute(
            "SELECT * FROM policy_rules WHERE id = ? AND version = ?", (rule_id, version),
        ).fetchone()
        audit_in_transaction(
            connection, f"policy_rule_{decision}", actor_id, rule_id,
            version=version, status=status.value, comment=comment,
        )
    return _to_rule(updated)


def create_rollback_draft(
    rule_id: str,
    target_version: str,
    new_version: str,
    effective_date: str,
    reason: str,
    actor_id: str,
) -> PolicyRule:
    with _connection() as connection:
        row = connection.execute(
            """SELECT * FROM policy_rules WHERE id = ? AND version = ?
               AND status IN ('active', 'retired')""",
            (rule_id, target_version),
        ).fetchone()
    if not row:
        raise ValueError("回滚目标必须是已批准的活动或历史规则版本")
    target = _to_rule(row)
    draft = replace(
        target,
        version=new_version,
        effective_date=effective_date,
        source_name=f"rollback:{target_version}:{reason}",
    )
    return create_policy_rule_draft(
        draft,
        actor_id,
        audit_action="policy_rule_rollback_draft_created",
        audit_detail={"target_version": target_version, "new_version": new_version, "reason": reason},
    )


def list_policy_rules(*, active_only: bool = True, as_of_date: date | None = None) -> list[PolicyRule]:
    where = "WHERE is_active = 1" if active_only else ""
    effective_on = as_of_date or _business_date()
    with _connection() as connection:
        has_due = connection.execute(
            "SELECT 1 FROM policy_rules WHERE status = 'scheduled' AND effective_date <= ? LIMIT 1",
            (effective_on.isoformat(),),
        ).fetchone()
    if has_due:
        with _connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            _activate_due_rules(connection, effective_on)
    with _connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM policy_rules {where} ORDER BY id, effective_date DESC, version DESC"
        ).fetchall()
    return [_to_rule(row) for row in rows]


def active_policy_ids() -> set[str]:
    return {rule.policy_id for rule in list_policy_rules() if rule.policy_id}


def policy_rule_diff(rule_id: str, version: str) -> dict:
    with _connection() as connection:
        candidate_row = connection.execute(
            "SELECT * FROM policy_rules WHERE id = ? AND version = ?", (rule_id, version),
        ).fetchone()
        if not candidate_row:
            raise ValueError("规则版本不存在")
        baseline_row = connection.execute(
            """SELECT * FROM policy_rules WHERE id = ? AND version <> ?
               AND status IN ('active', 'retired')
               ORDER BY is_active DESC, effective_date DESC, version DESC LIMIT 1""",
            (rule_id, version),
        ).fetchone()
    candidate = _to_rule(candidate_row)
    baseline = _to_rule(baseline_row) if baseline_row else None
    fields = (
        "policy_id", "rule_type", "parameters", "severity", "failure_result",
        "failure_message", "pass_message", "effective_date", "source_name",
    )
    changes = {
        field: {"from": getattr(baseline, field) if baseline else None, "to": getattr(candidate, field)}
        for field in fields
        if baseline is None or getattr(baseline, field) != getattr(candidate, field)
    }
    return {
        "rule_id": rule_id,
        "candidate_version": version,
        "candidate_status": candidate.status,
        "candidate_content_hash": candidate.content_hash,
        "content_hash_valid": bool(candidate.content_hash) and _rule_content_hash(candidate) == candidate.content_hash,
        "baseline_version": baseline.version if baseline else None,
        "changes": changes,
    }


def required_materials() -> dict[str, str]:
    for rule in list_policy_rules():
        if rule.rule_type == "required_materials":
            return dict(rule.parameters["required"])
    return {}


def _to_rule(row: sqlite3.Row) -> PolicyRule:
    return PolicyRule(
        row["id"], row["policy_id"], row["version"], row["rule_type"],
        json.loads(row["parameters_json"]), row["severity"], row["failure_result"],
        row["failure_message"], row["pass_message"], row["effective_date"], row["source_name"],
        PolicyRuleStatus(row["status"]), bool(row["is_active"]), row["created_by"],
        row["submitted_by"], row["reviewed_by"], row["review_comment"], row["activated_at"],
        row["content_hash"],
    )


def _validate_policy_reference(rule: PolicyRule, connection: sqlite3.Connection) -> None:
    if rule.policy_id:
        exists = connection.execute(
            "SELECT 1 FROM policy_clauses WHERE id = ? AND is_active = 1", (rule.policy_id,),
        ).fetchone()
        if not exists:
            raise ValueError(f"规则引用的政策条款不存在：{rule.policy_id}")


def _activate_due_rules(connection: sqlite3.Connection, as_of_date: date) -> list[tuple[str, str]]:
    rows = connection.execute(
        """SELECT id, version FROM policy_rules
           WHERE status = 'scheduled' AND effective_date <= ?
           ORDER BY effective_date, version""",
        (as_of_date.isoformat(),),
    ).fetchall()
    promoted: list[tuple[str, str]] = []
    for row in rows:
        active = connection.execute(
            "SELECT effective_date FROM policy_rules WHERE id = ? AND is_active = 1",
            (row["id"],),
        ).fetchone()
        if active and active["effective_date"] >= as_of_date.isoformat():
            connection.execute(
                "UPDATE policy_rules SET status = 'retired', is_active = 0 WHERE id = ? AND version = ?",
                (row["id"], row["version"]),
            )
            continue
        connection.execute(
            "UPDATE policy_rules SET is_active = 0, status = 'retired' WHERE id = ? AND is_active = 1",
            (row["id"],),
        )
        cursor = connection.execute(
            """UPDATE policy_rules SET is_active = 1, status = 'active', activated_at = ?
               WHERE id = ? AND version = ? AND status = 'scheduled'""",
            (datetime.now(timezone.utc).isoformat(), row["id"], row["version"]),
        )
        if cursor.rowcount == 1:
            promoted.append((row["id"], row["version"]))
            audit_in_transaction(
                connection, "policy_rule_scheduled_activated", "system", row["id"], version=row["version"],
            )
    return promoted


def _rule_content_hash(rule: PolicyRule) -> str:
    payload = {
        "id": rule.id,
        "policy_id": rule.policy_id,
        "version": rule.version,
        "rule_type": rule.rule_type,
        "parameters": rule.parameters,
        "severity": rule.severity,
        "failure_result": rule.failure_result,
        "failure_message": rule.failure_message,
        "pass_message": rule.pass_message,
        "effective_date": rule.effective_date,
        "source_name": rule.source_name,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _business_date() -> date:
    return datetime.now(ZoneInfo(get_settings().policy_timezone)).date()
