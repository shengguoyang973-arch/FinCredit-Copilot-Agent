"""Deterministic, auditable planning for governed credit-Agent tasks.

Credit decisions must not depend on an unconstrained model inventing actions.
This planner therefore turns a supported task into a small dependency graph made
only of approved read-only tools and required system controls.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


PLANNER_VERSION = "v1"
SUPPORTED_TASKS = frozenset({"generate_brief", "answer_question"})


@dataclass(frozen=True)
class PlanStep:
    id: str
    title: str
    kind: str
    depends_on: tuple[str, ...] = ()
    tool_name: str | None = None
    required: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "depends_on": list(self.depends_on),
            "tool_name": self.tool_name,
            "required": self.required,
        }


@dataclass(frozen=True)
class TaskPlan:
    id: str
    version: str
    task: str
    goal: str
    question_class: str
    steps: tuple[PlanStep, ...]

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(step.tool_name for step in self.steps if step.tool_name)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "task": self.task,
            "goal": self.goal,
            "question_class": self.question_class,
            "steps": [step.to_dict() for step in self.steps],
            "tool_names": list(self.tool_names),
        }

    def execution_trace(self, tool_results: list[dict]) -> list[dict]:
        completed_tools = {item["tool_name"] for item in tool_results if item.get("status") == "success"}
        trace = []
        for step in self.steps:
            completed = step.tool_name in completed_tools if step.tool_name else True
            trace.append({"step_id": step.id, "status": "completed" if completed else "not_completed"})
        return trace


def build_task_plan(task: str, question: str | None = None) -> TaskPlan:
    if task not in SUPPORTED_TASKS:
        raise ValueError(f"不支持的 Agent 任务规划：{task}")
    question_class = _question_class(question) if task == "answer_question" else "pre_review"
    tools = [
        PlanStep("application_snapshot", "读取申请与脱敏客户画像", "tool", tool_name="get_application_snapshot"),
        PlanStep(
            "canonical_customer_profile", "读取数据中台规范客户画像", "tool",
            ("application_snapshot",), "get_canonical_customer_snapshot",
        ),
        PlanStep("material_status", "核验材料状态和完整性", "tool", tool_name="get_material_status"),
        PlanStep("policy_evidence", "读取当前政策证据编号", "tool", tool_name="get_policy_evidence"),
    ]
    if question_class == "process_question":
        tools.append(PlanStep(
            "approval_status", "读取当前人工审批状态", "tool", ("application_snapshot",), "get_approval_status",
        ))
    controls = [
        PlanStep("deterministic_controls", "执行确定性准入与风险规则", "system", tuple(step.id for step in tools)),
        PlanStep("rag_retrieval", "检索带引用的政策上下文", "system", ("deterministic_controls",)),
        PlanStep("structured_response", "生成受 schema 约束的辅助意见", "system", ("rag_retrieval",)),
        PlanStep("human_boundary", "保留人工审批边界，不执行授信决定", "governance", ("structured_response",)),
    ]
    goal = "生成可追溯的预审草稿" if task == "generate_brief" else "回答受证据约束的业务问题"
    identity = json.dumps({"version": PLANNER_VERSION, "task": task, "question_class": question_class}, sort_keys=True)
    plan_id = f"TPL-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12].upper()}"
    return TaskPlan(plan_id, PLANNER_VERSION, task, goal, question_class, tuple(tools + controls))


def _question_class(question: str | None) -> str:
    normalized = question or ""
    if any(token in normalized for token in ("审批", "提交", "状态", "处理")):
        return "process_question"
    return "risk_or_policy_question"
