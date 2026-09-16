import pytest

from app.prompt_registry import get_prompt


def test_prompt_registry_returns_versioned_task_prompt() -> None:
    spec = get_prompt("answer_question")
    assert spec.prompt_id == "fincredit-governed-answer"
    assert spec.version == "v1"
    assert "不得自动批准" in spec.content


def test_prompt_registry_rejects_unknown_task() -> None:
    with pytest.raises(ValueError, match="未注册"):
        get_prompt("unknown")


def test_prompt_version_environment_value_is_a_fail_closed_deployment_assertion(monkeypatch) -> None:
    monkeypatch.setenv("FINCREDIT_PROMPT_VERSION", "v999")
    with pytest.raises(ValueError, match="当前已批准"):
        get_prompt("answer_question")
