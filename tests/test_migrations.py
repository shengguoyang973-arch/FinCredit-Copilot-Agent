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
        "policy_rules",
        "data_contracts",
        "data_ingestion_batches",
        "data_quality_results",
        "data_records",
        "data_lineage_events",
        "agent_evaluation_baselines",
        "agent_drift_alerts",
        "agent_feedback",
        "agent_drift_alert_actions",
        "prompt_versions",
        "agent_run_workflow_outcomes",
        "prompt_observation_reviews",
        "prompt_remediation_cases",
        "prompt_remediation_case_events",
        "integration_outbox_events",
        "integration_outbox_attempts",
        "evaluation_dataset_manifests",
        "evaluation_canaries",
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


def test_prompt_workflow_outcomes_are_bound_to_an_approval_task() -> None:
    with database.connection() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(agent_run_workflow_outcomes)")}
    assert {
        "approval_task_id", "run_id", "prompt_id", "prompt_version", "report_hash", "decision",
    }.issubset(columns)


def test_prompt_observation_reviews_are_four_eyes_reviewable() -> None:
    with database.connection() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(prompt_observation_reviews)")}
    assert {
        "task", "version", "prompt_content_hash", "recommendation", "snapshot_hash", "status", "reviewed_by",
    }.issubset(columns)


def test_prompt_remediation_cases_have_a_status_history() -> None:
    with database.connection() as connection:
        case_columns = {row["name"] for row in connection.execute("PRAGMA table_info(prompt_remediation_cases)")}
        event_columns = {row["name"] for row in connection.execute("PRAGMA table_info(prompt_remediation_case_events)")}
    assert {"observation_review_id", "owner_id", "due_date", "resolution_type"}.issubset(case_columns)
    assert {"case_id", "from_status", "to_status", "actor_id"}.issubset(event_columns)


def test_integration_outbox_and_canary_tables_have_governance_fields() -> None:
    with database.connection() as connection:
        outbox_columns = {row["name"] for row in connection.execute("PRAGMA table_info(integration_outbox_events)")}
        canary_columns = {row["name"] for row in connection.execute("PRAGMA table_info(evaluation_canaries)")}
    assert {"destination", "payload_hash", "dedupe_key", "attempt_count", "status"}.issubset(outbox_columns)
    assert {"dataset_hash", "traffic_percent", "criteria_json", "reviewed_by", "report_json"}.issubset(canary_columns)


def test_policy_rule_lifecycle_columns_are_present() -> None:
    with database.connection() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(policy_rules)")}
    assert {"status", "created_by", "submitted_by", "reviewed_by", "review_comment", "activated_at"}.issubset(columns)
