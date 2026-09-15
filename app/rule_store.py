from __future__ import annotations

import json
import sqlite3
from string import Formatter

from app.database import connection as database_connection
from app.domain import PolicyRule


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
        connection.execute("UPDATE policy_rules SET is_active = 0 WHERE id = ?", (rule.id,))
        connection.execute(
            """INSERT OR REPLACE INTO policy_rules
               (id, policy_id, version, rule_type, parameters_json, severity, failure_result,
                failure_message, pass_message, effective_date, source_name, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (rule.id, rule.policy_id, rule.version, rule.rule_type,
             json.dumps(rule.parameters, ensure_ascii=False, sort_keys=True), rule.severity,
             rule.failure_result, rule.failure_message, rule.pass_message,
             rule.effective_date, rule.source_name),
        )
        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def list_policy_rules(*, active_only: bool = True) -> list[PolicyRule]:
    where = "WHERE is_active = 1" if active_only else ""
    with _connection() as connection:
        rows = connection.execute(
            f"SELECT * FROM policy_rules {where} ORDER BY id, effective_date DESC, version DESC"
        ).fetchall()
    return [_to_rule(row) for row in rows]


def active_policy_ids() -> set[str]:
    return {rule.policy_id for rule in list_policy_rules() if rule.policy_id}


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
    )
