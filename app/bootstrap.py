from __future__ import annotations

from app.database import connection
from app import document_store, knowledge_store, prompt_store, rule_store, state_store, workflow_store
from app import data_platform_service
from app.migrations.sqlite import apply_migrations


def initialize_application() -> None:
    with connection() as conn:
        apply_migrations(conn)
    knowledge_store.initialize()
    rule_store.initialize()
    prompt_store.initialize()
    workflow_store.initialize()
    state_store.initialize()
    document_store.initialize()
    data_platform_service.initialize()
