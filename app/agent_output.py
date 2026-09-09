from __future__ import annotations

BRIEF_REQUIRED_FIELDS = {
    "provider": str,
    "summary": str,
    "key_risks": list,
    "next_actions": list,
    "governance_note": str,
    "evidence_ids": list,
    "materials_complete": bool,
}

ANSWER_REQUIRED_FIELDS = {
    "provider": str,
    "answer": str,
    "supporting_evidence_ids": list,
    "follow_up_actions": list,
    "governance_note": str,
    "fallback": bool,
}

OPENAI_BRIEF_JSON_SCHEMA = {
    "name": "fincredit_agent_brief",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "key_risks", "next_actions", "governance_note", "evidence_ids", "materials_complete"],
        "properties": {
            "summary": {"type": "string"},
            "key_risks": {"type": "array", "items": {"type": "string"}},
            "next_actions": {"type": "array", "items": {"type": "string"}},
            "governance_note": {"type": "string"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "materials_complete": {"type": "boolean"},
        },
    },
    "strict": True,
}

OPENAI_ANSWER_JSON_SCHEMA = {
    "name": "fincredit_agent_answer",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer", "supporting_evidence_ids", "follow_up_actions", "governance_note"],
        "properties": {
            "answer": {"type": "string"},
            "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
            "follow_up_actions": {"type": "array", "items": {"type": "string"}},
            "governance_note": {"type": "string"},
        },
    },
    "strict": True,
}


class AgentOutputValidationError(ValueError):
    pass


def validate_brief(output: dict) -> dict:
    _validate_required(output, BRIEF_REQUIRED_FIELDS)
    _validate_governance_boundary(output)
    return output


def validate_answer(output: dict) -> dict:
    _validate_required(output, ANSWER_REQUIRED_FIELDS)
    _validate_governance_boundary(output)
    return output


def openai_schema_for_task(task: str) -> dict:
    return OPENAI_ANSWER_JSON_SCHEMA if task == "answer_question" else OPENAI_BRIEF_JSON_SCHEMA


def _validate_required(output: dict, fields: dict[str, type]) -> None:
    for field, expected_type in fields.items():
        if field not in output:
            raise AgentOutputValidationError(f"Agent 输出缺少字段：{field}")
        if not isinstance(output[field], expected_type):
            raise AgentOutputValidationError(f"Agent 输出字段类型错误：{field}")


def _validate_governance_boundary(output: dict) -> None:
    text = str(output)
    forbidden_phrases = ("批准该笔授信", "拒绝该笔授信", "系统已批准", "系统已拒绝")
    if any(phrase in text for phrase in forbidden_phrases):
        raise AgentOutputValidationError("Agent 输出越过人工审批边界")
