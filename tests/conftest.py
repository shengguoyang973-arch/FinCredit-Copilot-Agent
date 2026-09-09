import pytest

from app import database
from app import knowledge_store
from app import workflow_store
from app import state_store
from app import document_store
from app.migrations.sqlite import apply_migrations


@pytest.fixture(autouse=True)
def isolated_policy_database(tmp_path, monkeypatch):
    """Keep test policy imports out of the local demonstration knowledge base."""
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "fincredit-test.db")
    with database.connection() as connection:
        apply_migrations(connection)
    knowledge_store.initialize()
    workflow_store.initialize()
    state_store.initialize()
    document_store.initialize()
