from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "returned"]
    comment: str = Field(min_length=2, max_length=1000)


class ApprovalSubmissionRequest(BaseModel):
    override_reason: str | None = Field(default=None, min_length=5, max_length=1000)


class AgentQuestionRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
