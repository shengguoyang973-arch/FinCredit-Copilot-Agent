from __future__ import annotations

import sqlite3

from app.database import connection as database_connection
from app.domain import PolicyClause

SEED_POLICIES = (
    PolicyClause("POL-1.2", "小微企业准入要求", "申请企业应持续经营满两年；禁止准入行业包括房地产开发、赌博及高污染限制行业。", "2026.01", "2026-01-01", ("准入", "经营", "行业", "两年")),
    PolicyClause("POL-2.1", "流动资金贷款额度", "单笔流动资金贷款原则上不超过申请企业最近一年营业收入的30%，且不得超过500万元。", "2026.01", "2026-01-01", ("额度", "收入", "500万", "流动资金")),
    PolicyClause("POL-3.4", "信用风险关注条件", "近12个月存在超过10天的逾期，或资产负债率高于75%的申请，须转人工强化审查，不得自动流转。", "2026.01", "2026-01-01", ("逾期", "负债率", "人工", "风险")),
)


def _connection() -> sqlite3.Connection:
    return database_connection()


def initialize() -> None:
    with _connection() as connection:
        count = connection.execute("SELECT COUNT(*) FROM policy_clauses").fetchone()[0]
        if count == 0:
            for clause in SEED_POLICIES:
                save_policy(clause, "seed-policy-library", connection)


def save_policy(clause: PolicyClause, source_name: str, connection: sqlite3.Connection | None = None) -> None:
    owns_connection = connection is None
    connection = connection or _connection()
    try:
        connection.execute(
            """INSERT OR REPLACE INTO policy_clauses
               (id, title, content, version, effective_date, keywords, source_name, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (clause.id, clause.title, clause.content, clause.version, clause.effective_date, "|".join(clause.keywords), source_name),
        )
        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def list_policies() -> list[PolicyClause]:
    with _connection() as connection:
        rows = connection.execute("SELECT * FROM policy_clauses WHERE is_active = 1 ORDER BY effective_date DESC, id").fetchall()
    return [_to_clause(row) for row in rows]


def get_policies(ids: set[str]) -> list[PolicyClause]:
    return [policy for policy in list_policies() if policy.id in ids]


def _to_clause(row: sqlite3.Row) -> PolicyClause:
    return PolicyClause(row["id"], row["title"], row["content"], row["version"], row["effective_date"], tuple(filter(None, row["keywords"].split("|"))))
