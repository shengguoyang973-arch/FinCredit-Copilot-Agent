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
