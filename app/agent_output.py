from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

NonEmptyText = Annotated[str, Field(min_length=1, max_length=4000)]
PolicyId = Annotated[str, Field(pattern=r"^POL-[A-Za-z0-9.]+$")]


class LangChainBriefResponse(BaseModel):
    """Schema requested from the LangChain model runnable."""

    summary: NonEmptyText
    key_risks: list[NonEmptyText] = Field(min_length=1, max_length=20)
    next_actions: list[NonEmptyText] = Field(min_length=1, max_length=20)
    governance_note: NonEmptyText
    evidence_ids: list[PolicyId] = Field(min_length=1, max_length=50)
    materials_complete: bool


class LangChainAnswerResponse(BaseModel):
    """Schema requested from the LangChain model runnable."""

    answer: NonEmptyText
    supporting_evidence_ids: list[PolicyId] = Field(min_length=1, max_length=50)
    follow_up_actions: list[NonEmptyText] = Field(min_length=1, max_length=20)
    governance_note: NonEmptyText


class GovernedBrief(LangChainBriefResponse):
    model_config = ConfigDict(extra="allow")

    provider: NonEmptyText


class GovernedAnswer(LangChainAnswerResponse):
    model_config = ConfigDict(extra="allow")

    provider: NonEmptyText
    fallback: bool


class AgentOutputValidationError(ValueError):
    pass


def validate_brief(output: dict, allowed_evidence_ids: set[str] | None = None) -> dict:
    try:
        parsed = GovernedBrief.model_validate(output)
    except ValidationError as error:
        raise AgentOutputValidationError(f"Agent 报告输出不满足结构约束：{error.errors()[0]['msg']}") from error
    _validate_evidence(parsed.evidence_ids, allowed_evidence_ids)
    _validate_governance_boundary([parsed.summary, *parsed.key_risks, *parsed.next_actions])
    return parsed.model_dump(exclude_none=True)


def validate_answer(output: dict, allowed_evidence_ids: set[str] | None = None) -> dict:
    try:
        parsed = GovernedAnswer.model_validate(output)
    except ValidationError as error:
        raise AgentOutputValidationError(f"Agent 问答输出不满足结构约束：{error.errors()[0]['msg']}") from error
    _validate_evidence(parsed.supporting_evidence_ids, allowed_evidence_ids)
    _validate_governance_boundary([parsed.answer, *parsed.follow_up_actions])
    return parsed.model_dump(exclude_none=True)


def openai_schema_for_task(task: str) -> dict:
    """Compatibility helper for callers that still need a JSON schema."""
    schema_model = LangChainAnswerResponse if task == "answer_question" else LangChainBriefResponse
    return {
        "name": f"fincredit_{task}",
        "schema": schema_model.model_json_schema(),
        "strict": True,
    }


def _validate_evidence(evidence_ids: list[str], allowed_evidence_ids: set[str] | None) -> None:
    if len(evidence_ids) != len(set(evidence_ids)):
        raise AgentOutputValidationError("Agent 输出包含重复的政策证据编号")
    if allowed_evidence_ids is not None:
        unknown = sorted(set(evidence_ids) - allowed_evidence_ids)
        if unknown:
            raise AgentOutputValidationError(f"Agent 输出引用了未检索到的政策证据：{', '.join(unknown)}")


_DECISION_PATTERNS = (
    re.compile(r"(?:系统已|决定|结论为|建议|应当|可以|予以|立即).{0,16}(?:批准|同意|拒绝|退回)"),
    re.compile(r"(?:批准|拒绝|退回).{0,8}(?:该笔|本笔)?授信"),
)


def _validate_governance_boundary(parts: list[str]) -> None:
    text = " ".join(parts)
    # Explicit negative explanations are allowed; actionable decision language
    # in the model-authored business content is not.
    text = re.sub(r"(?:不得|不能|不可|不应|不建议).{0,8}(?:批准|同意|拒绝|退回)", "", text)
    if any(pattern.search(text) for pattern in _DECISION_PATTERNS):
        raise AgentOutputValidationError("Agent 输出越过人工审批边界")
