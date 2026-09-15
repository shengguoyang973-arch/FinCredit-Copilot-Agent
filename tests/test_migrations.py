from app import database
from app.migrations.sqlite import apply_migrations


def table_names() -> set[str]:
    with database.connection() as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def test_sqlite_migrations_create_expected_tables() -> None:
    expected = {
        "schema_migrations",
        "policy_clauses",
        "customers",
        "loan_applications",
        "audit_events",
        "review_reports",
        "approval_tasks",
        "agent_runs",
        "agent_run_events",
        "application_documents",
    }
    assert expected.issubset(table_names())


def test_sqlite_migrations_are_idempotent() -> None:
    with database.connection() as connection:
        first = apply_migrations(connection)
        second = apply_migrations(connection)
    assert first == []
    assert second == []


def test_governed_workflow_columns_are_present() -> None:
    with database.connection() as connection:
        approval_columns = {row["name"] for row in connection.execute("PRAGMA table_info(approval_tasks)")}
        audit_columns = {row["name"] for row in connection.execute("PRAGMA table_info(audit_events)")}
    assert {"reviewed_by", "report_hash"}.issubset(approval_columns)
    assert {"prev_hash", "event_hash"}.issubset(audit_columns)
