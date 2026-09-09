from app.agent_runtime.router import route_provider


def test_provider_canary_routing_is_stable(monkeypatch) -> None:
    monkeypatch.setenv("FINCREDIT_AGENT_PROVIDER_CHAIN", "deterministic-local,deepseek-chat")
    monkeypatch.setenv("FINCREDIT_AGENT_GRAY_PERCENT", "100")
    assert route_provider("generate_brief", "APP001") == "deepseek-chat"
    assert route_provider("generate_brief", "APP001") == "deepseek-chat"


def test_provider_defaults_to_primary_without_gray_release(monkeypatch) -> None:
    monkeypatch.setenv("FINCREDIT_AGENT_PROVIDER_CHAIN", "deterministic-local,deepseek-chat")
    monkeypatch.setenv("FINCREDIT_AGENT_GRAY_PERCENT", "0")
    assert route_provider("generate_brief", "APP001") == "deterministic-local"
