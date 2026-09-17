from fastapi.testclient import TestClient
import pytest

from app import database
from app.integration_outbox import dispatch_pending, enqueue_in_transaction, get_event, list_attempts
from app.main import app


client = TestClient(app)
COMPLIANCE = {"X-User-Id": "compliance_001"}


def queue_event() -> str:
    with database.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        event = enqueue_in_transaction(
            connection, destination="siem", event_type="agent.drift_alert.opened", severity="high",
            payload={"alert_id": "ADA-TEST", "signal": "fallback_rate", "status": "open"}, dedupe_key="outbox-test-open",
        )
    assert event is not None
    return event["id"]


def test_outbox_is_durable_deduplicated_and_rejects_sensitive_payloads() -> None:
    event_id = queue_event()
    with database.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        duplicate = enqueue_in_transaction(
            connection, destination="siem", event_type="agent.drift_alert.opened", severity="high",
            payload={"alert_id": "ADA-TEST", "signal": "fallback_rate", "status": "open"}, dedupe_key="outbox-test-open",
        )
    assert duplicate is None
    assert get_event(event_id)["status"] == "pending"
    with database.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="不得包含"):
            enqueue_in_transaction(connection, destination="siem", event_type="bad", severity="high", payload={"customer_name": "不应发送"}, dedupe_key="bad")


def test_outbox_does_not_send_when_delivery_is_disabled() -> None:
    queue_event()
    result = dispatch_pending()
    assert result["delivery_mode"] == "disabled"
    assert result["attempted"] == 0


def test_outbox_webhook_dispatch_is_auditable(monkeypatch) -> None:
    class Response:
        status = 202

        def read(self, size):
            return b"accepted"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setenv("FINCREDIT_INTEGRATION_DELIVERY_MODE", "webhook")
    monkeypatch.setenv("FINCREDIT_SIEM_WEBHOOK_URL", "https://siem.example.test/events")
    monkeypatch.setenv("FINCREDIT_WORK_ITEM_WEBHOOK_URL", "https://work.example.test/events")
    monkeypatch.setattr("app.integration_outbox.urlopen", lambda request, timeout: Response())
    event_id = queue_event()
    result = dispatch_pending()
    assert result["delivered"] == 1
    assert get_event(event_id)["status"] == "delivered"
    assert list_attempts(event_id)[0]["response_status"] == 202
    listing = client.get("/v1/operations/integration-outbox", headers=COMPLIANCE)
    assert listing.status_code == 200
    assert listing.json()["items"][0]["payload_hash"]
