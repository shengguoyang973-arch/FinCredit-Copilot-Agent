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
