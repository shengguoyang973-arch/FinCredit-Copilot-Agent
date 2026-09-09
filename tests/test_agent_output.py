import pytest

from app.agent_output import AgentOutputValidationError, validate_answer, validate_brief


def test_validate_brief_accepts_governed_output() -> None:
    output = {
        "provider": "deterministic-local",
        "summary": "系统预审结论为需人工强化审查。",
        "key_risks": ["缺少材料。"],
        "next_actions": ["补齐材料。"],
        "governance_note": "Agent 不自动批准、拒绝或退回授信申请。",
        "evidence_ids": ["POL-1.2"],
        "materials_complete": False,
    }
    assert validate_brief(output) == output


def test_validate_answer_rejects_missing_fields() -> None:
    with pytest.raises(AgentOutputValidationError):
        validate_answer({"provider": "deterministic-local", "answer": "缺字段"})


def test_validate_answer_rejects_final_credit_decision() -> None:
    output = {
        "provider": "deterministic-local",
        "answer": "系统已批准该笔授信。",
        "supporting_evidence_ids": [],
        "follow_up_actions": [],
        "governance_note": "错误边界。",
        "fallback": False,
    }
    with pytest.raises(AgentOutputValidationError):
        validate_answer(output)
