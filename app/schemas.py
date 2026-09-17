from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_iso_date(value: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("必须是有效的 ISO 日期") from error
    return value


class PolicySearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)


class PolicyImportRequest(BaseModel):
    id: str = Field(pattern=r"^POL-[A-Za-z0-9.]+$")
    title: str = Field(min_length=2, max_length=100)
    content: str = Field(min_length=10, max_length=5000)
    version: str = Field(min_length=3, max_length=30)
    effective_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    keywords: list[str] = Field(min_length=1, max_length=20)
    source_name: str = Field(min_length=2, max_length=200)

    _effective_date_is_valid = field_validator("effective_date")(_validate_iso_date)


class PolicyRuleImportRequest(BaseModel):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{2,50}$")
    policy_id: str | None = Field(default=None, pattern=r"^POL-[A-Za-z0-9.]+$")
    version: str = Field(min_length=3, max_length=30)
    rule_type: Literal["minimum", "ratio_cap", "any_threshold", "required_materials"]
    parameters: dict
    severity: Literal["info", "medium", "high", "block"]
    failure_result: Literal["fail", "review"]
    failure_message: str = Field(min_length=2, max_length=1000)
    pass_message: str = Field(min_length=2, max_length=1000)
    effective_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    source_name: str = Field(min_length=2, max_length=200)

    _effective_date_is_valid = field_validator("effective_date")(_validate_iso_date)


class PolicyRuleDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(min_length=5, max_length=1000)


class PolicyRuleRollbackRequest(BaseModel):
    target_version: str = Field(min_length=3, max_length=30)
    new_version: str = Field(min_length=3, max_length=30)
    effective_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    reason: str = Field(min_length=5, max_length=500)

    _effective_date_is_valid = field_validator("effective_date")(_validate_iso_date)


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "returned"]
    comment: str = Field(min_length=2, max_length=1000)


class ApprovalSubmissionRequest(BaseModel):
    override_reason: str | None = Field(default=None, min_length=5, max_length=1000)


class AgentQuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class DataContractSchema(BaseModel):
    """A deliberately small, JSON-compatible contract for canonical records."""

    business_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    required_fields: list[str] = Field(min_length=1, max_length=100)
    field_types: dict[str, str] = Field(min_length=1, max_length=100)

    @field_validator("required_fields")
    @classmethod
    def required_fields_are_unique_and_safe(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("required_fields 不能包含重复字段")
        if any(not field.replace("_", "").isalnum() or not field[0].isalpha() for field in values):
            raise ValueError("required_fields 只能使用字母数字下划线字段名")
        return values

    @field_validator("field_types")
    @classmethod
    def field_types_are_supported(cls, values: dict[str, str]) -> dict[str, str]:
        supported = {"string", "integer", "number", "boolean", "object", "array"}
        if any(
            not key.replace("_", "").isalnum() or not key[0].isalpha() or value not in supported
            for key, value in values.items()
        ):
            raise ValueError("field_types 仅支持安全字段名和 string/integer/number/boolean/object/array 类型")
        return values

    @model_validator(mode="after")
    def business_key_and_required_fields_must_be_declared(self) -> "DataContractSchema":
        if self.business_key not in self.required_fields:
            raise ValueError("business_key 必须包含在 required_fields 中")
        if not set(self.required_fields).issubset(self.field_types):
            raise ValueError("required_fields 必须全部在 field_types 中声明")
        return self


class DataContractUpsertRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(pattern=r"^DC-[A-Za-z0-9.-]{3,60}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    domain_name: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    contract_schema: DataContractSchema = Field(alias="schema")
    classification: Literal["internal", "confidential", "restricted"]
    description: str = Field(min_length=10, max_length=500)
    allowed_sources: list[str] = Field(min_length=1, max_length=30)

    @field_validator("allowed_sources")
    @classmethod
    def allowed_sources_are_unique(cls, values: list[str]) -> list[str]:
        normalized = [item.strip().lower() for item in values]
        if any(not item or len(item) > 80 for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("allowed_sources 必须是唯一且非空的来源系统标识")
        return normalized


class DataIngestionRequest(BaseModel):
    source_system: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    contract_id: str = Field(pattern=r"^DC-[A-Za-z0-9.-]{3,60}$")
    organization_id: str = Field(pattern=r"^[A-Za-z0-9_-]{2,80}$")
    records: list[dict[str, Any]] = Field(min_length=1, max_length=10_000)


class OnlineEvaluationBaselineRequest(BaseModel):
    name: str = Field(default="default", pattern=r"^[a-z][a-z0-9_-]{1,63}$")


class AgentFeedbackRequest(BaseModel):
    verdict: Literal["accepted", "needs_revision", "incorrect"]
    category: Literal["facts", "evidence", "risk_assessment", "style", "other"]
    comment: str = Field(min_length=5, max_length=1000)


class DriftAlertActionRequest(BaseModel):
    action: Literal["acknowledged", "investigating", "false_positive"]
    comment: str = Field(min_length=5, max_length=1000)


class PromptDraftRequest(BaseModel):
    task: Literal["generate_brief", "answer_question"]
    version: str = Field(pattern=r"^v[1-9][0-9]{0,20}$")
    content: str = Field(min_length=80, max_length=8000)
    feedback_ids: list[str] = Field(default_factory=list, max_length=50)
    rationale: str = Field(min_length=10, max_length=1000)

    @field_validator("feedback_ids")
    @classmethod
    def feedback_ids_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("feedback_ids 不能包含重复项")
        if any(not value.startswith("AFB-") or len(value) > 40 for value in values):
            raise ValueError("feedback_ids 格式无效")
        return values


class PromptDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(min_length=5, max_length=1000)


class PromptRollbackRequest(BaseModel):
    target_version: str = Field(pattern=r"^v[1-9][0-9]{0,20}$")
    new_version: str = Field(pattern=r"^v[1-9][0-9]{0,20}$")
    reason: str = Field(min_length=10, max_length=1000)


class PromptObservationReviewRequest(BaseModel):
    recommendation: Literal["continue_monitoring", "investigate", "rollback_recommended"]
    rationale: str = Field(min_length=10, max_length=1000)


class PromptObservationReviewDecisionRequest(BaseModel):
    decision: Literal["acknowledged", "rejected"]
    comment: str = Field(min_length=5, max_length=1000)


class PromptRemediationCaseRequest(BaseModel):
    owner_id: str = Field(pattern=r"^[A-Za-z0-9._:@-]{2,128}$")
    due_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    _due_date_is_valid = field_validator("due_date")(_validate_iso_date)


class PromptRemediationCaseStatusRequest(BaseModel):
    status: Literal["in_progress", "resolved", "cancelled"]
    comment: str = Field(min_length=5, max_length=1000)
    resolution_type: Literal[
        "investigation_completed", "monitoring_completed", "rollback_draft_created", "no_change_justified",
    ] | None = None
    resolution_reference: str | None = Field(default=None, min_length=3, max_length=200)

    @model_validator(mode="after")
    def resolution_is_only_allowed_when_closing(self) -> "PromptRemediationCaseStatusRequest":
        if self.status == "resolved" and (self.resolution_type is None or self.resolution_reference is None):
            raise ValueError("关闭处置作业单必须提供结论类型与结论参考编号")
        if self.status != "resolved" and (self.resolution_type is not None or self.resolution_reference is not None):
            raise ValueError("仅关闭处置作业单时可以提供结论类型与结论参考编号")
        return self
