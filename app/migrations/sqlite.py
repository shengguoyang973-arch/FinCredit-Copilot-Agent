from __future__ import annotations

import sqlite3

MIGRATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("0001_initial_schema", (
        """CREATE TABLE IF NOT EXISTS policy_clauses (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,
            version TEXT NOT NULL, effective_date TEXT NOT NULL, keywords TEXT NOT NULL,
            source_name TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1
        )""",
        "CREATE TABLE IF NOT EXISTS customers (id TEXT PRIMARY KEY, customer_json TEXT NOT NULL)",
        """CREATE TABLE IF NOT EXISTS loan_applications (
            id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, requested_amount INTEGER NOT NULL,
            term_months INTEGER NOT NULL, purpose TEXT NOT NULL, created_by TEXT NOT NULL, status TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, actor_id TEXT NOT NULL,
            resource_id TEXT NOT NULL, detail_json TEXT NOT NULL, timestamp TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS review_reports (
            application_id TEXT PRIMARY KEY, report_json TEXT NOT NULL,
            created_by TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS approval_tasks (
            id TEXT PRIMARY KEY, application_id TEXT NOT NULL, status TEXT NOT NULL,
            submitted_by TEXT NOT NULL, submitted_at TEXT NOT NULL, decided_by TEXT,
            decided_at TEXT, decision_comment TEXT)""",
        """CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY, application_id TEXT NOT NULL, provider TEXT NOT NULL,
            input_snapshot_json TEXT NOT NULL, output_json TEXT NOT NULL,
            created_by TEXT NOT NULL, created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS application_documents (
            id TEXT PRIMARY KEY, application_id TEXT NOT NULL, document_type TEXT NOT NULL,
            filename TEXT NOT NULL, content_type TEXT NOT NULL, byte_size INTEGER NOT NULL,
            sha256 TEXT NOT NULL, extracted_json TEXT NOT NULL, imported_by TEXT NOT NULL,
            imported_at TEXT NOT NULL)""",
    )),
    ("0002_agent_runtime", (
        "ALTER TABLE agent_runs ADD COLUMN task TEXT NOT NULL DEFAULT 'unknown'",
        "ALTER TABLE agent_runs ADD COLUMN state TEXT NOT NULL DEFAULT 'completed'",
        "ALTER TABLE agent_runs ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
        "UPDATE agent_runs SET updated_at = created_at WHERE updated_at = ''",
        """CREATE TABLE IF NOT EXISTS agent_run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            from_state TEXT NOT NULL,
            to_state TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES agent_runs(id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_id ON agent_run_events(run_id, id)",
    )),
    ("0003_governed_workflow", (
        "ALTER TABLE approval_tasks ADD COLUMN reviewed_by TEXT",
        "ALTER TABLE approval_tasks ADD COLUMN report_hash TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE audit_events ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE audit_events ADD COLUMN event_hash TEXT NOT NULL DEFAULT ''",
        "CREATE INDEX IF NOT EXISTS idx_approval_tasks_application ON approval_tasks(application_id, submitted_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_audit_events_hash ON audit_events(event_hash)",
    )),
    ("0004_configurable_policy_rules", (
        """CREATE TABLE IF NOT EXISTS policy_rules (
            id TEXT NOT NULL, policy_id TEXT, version TEXT NOT NULL,
            rule_type TEXT NOT NULL, parameters_json TEXT NOT NULL,
            severity TEXT NOT NULL, failure_result TEXT NOT NULL,
            failure_message TEXT NOT NULL, pass_message TEXT NOT NULL,
            effective_date TEXT NOT NULL, source_name TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id, version)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_policy_rules_active ON policy_rules(is_active, id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_rules_one_active ON policy_rules(id) WHERE is_active = 1",
    )),
    ("0005_policy_rule_lifecycle", (
        "ALTER TABLE policy_rules ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE policy_rules ADD COLUMN created_by TEXT NOT NULL DEFAULT 'system'",
        "ALTER TABLE policy_rules ADD COLUMN submitted_by TEXT",
        "ALTER TABLE policy_rules ADD COLUMN reviewed_by TEXT",
        "ALTER TABLE policy_rules ADD COLUMN review_comment TEXT",
        "ALTER TABLE policy_rules ADD COLUMN activated_at TEXT",
        "UPDATE policy_rules SET status = CASE WHEN is_active = 1 THEN 'active' ELSE 'retired' END",
        "CREATE INDEX IF NOT EXISTS idx_policy_rules_lifecycle ON policy_rules(status, effective_date, id)",
    )),
    ("0006_policy_rule_integrity", (
        "ALTER TABLE policy_rules ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_rules_one_scheduled ON policy_rules(id) WHERE status = 'scheduled'",
    )),
    ("0007_data_platform", (
        """CREATE TABLE IF NOT EXISTS data_contracts (
            id TEXT NOT NULL, version TEXT NOT NULL, domain_name TEXT NOT NULL,
            entity_type TEXT NOT NULL, schema_json TEXT NOT NULL,
            classification TEXT NOT NULL, description TEXT NOT NULL,
            allowed_sources_json TEXT NOT NULL, status TEXT NOT NULL,
            owner_id TEXT NOT NULL, contract_hash TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY (id, version)
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_data_contracts_one_active ON data_contracts(id) WHERE status = 'active'",
        "CREATE INDEX IF NOT EXISTS idx_data_contracts_catalog ON data_contracts(status, domain_name, entity_type)",
        """CREATE TABLE IF NOT EXISTS data_ingestion_batches (
            id TEXT PRIMARY KEY, source_system TEXT NOT NULL, contract_id TEXT NOT NULL,
            contract_version TEXT NOT NULL, organization_id TEXT NOT NULL,
            status TEXT NOT NULL, payload_hash TEXT NOT NULL, record_count INTEGER NOT NULL,
            accepted_count INTEGER NOT NULL, rejected_count INTEGER NOT NULL,
            submitted_by TEXT NOT NULL, submitted_at TEXT NOT NULL, finalized_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_data_batches_contract ON data_ingestion_batches(contract_id, submitted_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_data_batches_organization ON data_ingestion_batches(organization_id, submitted_at DESC)",
        """CREATE TABLE IF NOT EXISTS data_quality_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL,
            rule_code TEXT NOT NULL, severity TEXT NOT NULL, passed INTEGER NOT NULL,
            affected_records INTEGER NOT NULL, detail_json TEXT NOT NULL, executed_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_data_quality_batch ON data_quality_results(batch_id, id)",
        """CREATE TABLE IF NOT EXISTS data_records (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, organization_id TEXT NOT NULL,
            entity_type TEXT NOT NULL, business_key TEXT NOT NULL, record_json TEXT NOT NULL,
            record_hash TEXT NOT NULL, classification TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 1,
            ingested_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_data_records_current ON data_records(organization_id, entity_type, business_key, is_current)",
        "CREATE INDEX IF NOT EXISTS idx_data_records_batch ON data_records(batch_id)",
        """CREATE TABLE IF NOT EXISTS data_lineage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL,
            event_type TEXT NOT NULL, source_system TEXT NOT NULL, target_dataset TEXT NOT NULL,
            contract_id TEXT NOT NULL, contract_version TEXT NOT NULL, payload_hash TEXT NOT NULL,
            record_count INTEGER NOT NULL, actor_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
            prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_data_lineage_hash ON data_lineage_events(event_hash)",
        "CREATE INDEX IF NOT EXISTS idx_data_lineage_batch ON data_lineage_events(batch_id, id)",
    )),
    ("0008_online_evaluation", (
        """CREATE TABLE IF NOT EXISTS agent_evaluation_baselines (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, metrics_json TEXT NOT NULL,
            sample_count INTEGER NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
            retired_at TEXT
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_eval_one_active_baseline ON agent_evaluation_baselines(name) WHERE retired_at IS NULL",
        """CREATE TABLE IF NOT EXISTS agent_drift_alerts (
            id TEXT PRIMARY KEY, signal TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
            baseline_id TEXT NOT NULL, observed_json TEXT NOT NULL, message TEXT NOT NULL,
            first_detected_at TEXT NOT NULL, last_detected_at TEXT NOT NULL, resolved_at TEXT
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_drift_one_open_signal ON agent_drift_alerts(signal) WHERE status = 'open'",
        "CREATE INDEX IF NOT EXISTS idx_agent_drift_status ON agent_drift_alerts(status, last_detected_at DESC)",
    )),
    ("0009_human_feedback_and_context_governance", (
        """CREATE TABLE IF NOT EXISTS agent_feedback (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, application_id TEXT NOT NULL,
            verdict TEXT NOT NULL, category TEXT NOT NULL, comment TEXT NOT NULL,
            content_hash TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_feedback_one_per_reviewer ON agent_feedback(run_id, created_by)",
        "CREATE INDEX IF NOT EXISTS idx_agent_feedback_run ON agent_feedback(run_id, created_at DESC)",
        """CREATE TABLE IF NOT EXISTS agent_drift_alert_actions (
            id TEXT PRIMARY KEY, alert_id TEXT NOT NULL, action TEXT NOT NULL,
            comment TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_agent_drift_alert_actions_alert ON agent_drift_alert_actions(alert_id, created_at DESC)",
    )),
    ("0010_governed_prompt_lifecycle", (
        """CREATE TABLE IF NOT EXISTS prompt_versions (
            task TEXT NOT NULL, version TEXT NOT NULL, prompt_id TEXT NOT NULL,
            content TEXT NOT NULL, content_hash TEXT NOT NULL, status TEXT NOT NULL,
            feedback_ids_json TEXT NOT NULL, rationale TEXT NOT NULL,
            created_by TEXT NOT NULL, submitted_by TEXT, reviewed_by TEXT,
            review_comment TEXT, created_at TEXT NOT NULL, activated_at TEXT,
            PRIMARY KEY (task, version)
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_versions_one_active ON prompt_versions(task) WHERE status = 'active'",
        "CREATE INDEX IF NOT EXISTS idx_prompt_versions_lifecycle ON prompt_versions(task, status, created_at DESC)",
    )),
    ("0011_prompt_workflow_outcomes", (
        """CREATE TABLE IF NOT EXISTS agent_run_workflow_outcomes (
            approval_task_id TEXT PRIMARY KEY, application_id TEXT NOT NULL, run_id TEXT NOT NULL,
            prompt_id TEXT NOT NULL, prompt_version TEXT NOT NULL, report_hash TEXT NOT NULL,
            decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected', 'returned')),
            decided_by TEXT NOT NULL, decided_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_agent_run_outcomes_prompt ON agent_run_workflow_outcomes(prompt_id, prompt_version, decided_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_agent_run_outcomes_run ON agent_run_workflow_outcomes(run_id, decided_at DESC)",
    )),
    ("0012_prompt_observation_reviews", (
        """CREATE TABLE IF NOT EXISTS prompt_observation_reviews (
            id TEXT PRIMARY KEY, task TEXT NOT NULL, version TEXT NOT NULL, prompt_id TEXT NOT NULL,
            prompt_content_hash TEXT NOT NULL, recommendation TEXT NOT NULL
                CHECK(recommendation IN ('continue_monitoring', 'investigate', 'rollback_recommended')),
            rationale TEXT NOT NULL, snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('pending_review', 'acknowledged', 'rejected')),
            created_by TEXT NOT NULL, created_at TEXT NOT NULL, reviewed_by TEXT,
            reviewed_at TEXT, review_comment TEXT,
            UNIQUE(task, version, snapshot_hash)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_prompt_observation_reviews_prompt ON prompt_observation_reviews(task, version, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_prompt_observation_reviews_status ON prompt_observation_reviews(status, created_at DESC)",
    )),
    ("0013_prompt_remediation_cases", (
        """CREATE TABLE IF NOT EXISTS prompt_remediation_cases (
            id TEXT PRIMARY KEY, observation_review_id TEXT NOT NULL UNIQUE, task TEXT NOT NULL,
            version TEXT NOT NULL, prompt_id TEXT NOT NULL, recommendation TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open', 'in_progress', 'resolved', 'cancelled')),
            owner_id TEXT NOT NULL, due_date TEXT NOT NULL, created_by TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_by TEXT,
            resolved_at TEXT, resolution_type TEXT, resolution_reference TEXT, resolution_note TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_prompt_remediation_cases_status_due ON prompt_remediation_cases(status, due_date)",
        "CREATE INDEX IF NOT EXISTS idx_prompt_remediation_cases_prompt ON prompt_remediation_cases(task, version, created_at DESC)",
        """CREATE TABLE IF NOT EXISTS prompt_remediation_case_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, event_type TEXT NOT NULL,
            from_status TEXT NOT NULL, to_status TEXT NOT NULL, comment TEXT NOT NULL,
            actor_id TEXT NOT NULL, occurred_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_prompt_remediation_case_events_case ON prompt_remediation_case_events(case_id, id)",
    )),
)


def apply_migrations(connection: sqlite3.Connection) -> list[str]:
    connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        id TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    applied = {row["id"] for row in connection.execute("SELECT id FROM schema_migrations").fetchall()}
    executed: list[str] = []
    for migration_id, statements in MIGRATIONS:
        if migration_id in applied:
            continue
        for statement in statements:
            try:
                connection.execute(statement)
            except sqlite3.OperationalError as error:
                # A process may have been interrupted after an ALTER TABLE but
                # before schema_migrations was committed. Treat only duplicate
                # column errors as an idempotent retry; surface all other errors.
                if "duplicate column name" not in str(error).lower():
                    raise
        connection.execute("INSERT INTO schema_migrations(id) VALUES (?)", (migration_id,))
        executed.append(migration_id)
    return executed
