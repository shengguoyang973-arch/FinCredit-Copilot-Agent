from __future__ import annotations

import time
from dataclasses import asdict

from app.agent_provider import AgentContext, get_agent_provider
from app.agent_tools import execute_agent_tools
from app.agent_runtime import AgentRunState
from app.agent_runtime.reliability import ReliableInvoker
from app.agent_runtime.guardrails import redact_sensitive_text, validate_agent_question
from app.prompt_registry import get_prompt
from app.approval_policy import SubmissionPolicyError, evaluate_submission_policy
from app.document_store import material_check
from app.domain import ApplicationStatus, LoanApplication, PolicyClause, Role, User
from app.knowledge_store import list_policies
from app.observability import current_request_id, log_event
from app.rag import retrieve_policy_context
from app.repository import audit, get_customer
from app.risk_rules import PreReviewRuleDecision, evaluate_pre_review_rules
from app.workflow_store import (
    create_agent_run,
    create_approval_task,
    finalize_agent_run,
    finalize_pre_review,
    get_report,
    get_agent_run,
    transition_agent_run,
    update_agent_run_snapshot,
)


def search_policies(query: str) -> list[PolicyClause]:
    return [hit.policy for hit in retrieve_policy_context(query, list_policies()).hits]


def pre_review(application: LoanApplication, actor: User, existing_run_id: str | None = None) -> dict:
    if Role.RISK_MANAGER not in actor.roles:
        raise PermissionError("只有风险经理可以发起预审")
    if application.status not in {
        ApplicationStatus.DRAFT,
        ApplicationStatus.PRE_REVIEWED,
        ApplicationStatus.RETURNED,
    }:
        raise ValueError("当前申请状态不允许生成或覆盖预审报告")
    agent_provider = get_agent_provider("generate_brief", application.id)
    run = get_agent_run(existing_run_id) if existing_run_id else create_agent_run(application.id, agent_provider.name, "generate_brief", actor.id, {"task": "generate_brief", "request_id": current_request_id()})
    if not run or run["application_id"] != application.id:
        raise ValueError("待恢复的 Agent Run 不存在或不属于当前申请")
    run_id = run["id"]
    try:
        if run["state"] == AgentRunState.CREATED.value:
            transition_agent_run(run_id, AgentRunState.CONTEXT_BUILDING)
        customer, materials, rule_decision, findings, evidence, agent_context = _build_agent_context(application)
        snapshot = _agent_input_snapshot(agent_context, "generate_brief")
        update_agent_run_snapshot(run_id, snapshot)
        if agent_context.tool_results:
            transition_agent_run(run_id, AgentRunState.TOOL_RUNNING, tool_count=len(agent_context.tool_results))
        transition_agent_run(run_id, AgentRunState.MODEL_RUNNING, provider=agent_provider.name)
        started = time.perf_counter()
        agent_brief, attempts = _invoke_agent_provider(
            agent_provider,
            "generate_brief",
            agent_context,
            "",
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        snapshot = _agent_input_snapshot(agent_context, "generate_brief", duration_ms=duration_ms) | {"attempts": attempts}
        transition_agent_run(run_id, AgentRunState.VALIDATING)
        if agent_brief.get("fallback"):
            transition_agent_run(run_id, AgentRunState.FALLBACK, reason=agent_brief.get("fallback_reason"))
            transition_agent_run(run_id, AgentRunState.VALIDATING, event_type="fallback_output_validated")
        agent_brief = agent_brief | {"run_id": run_id, "created_at": run["created_at"]}
        report = {
            "application_id": application.id,
            "conclusion": rule_decision.conclusion,
            "disclaimer": "本报告为系统预审草稿，不构成授信决定；须由具备权限的人员复核并审批。",
            "customer_snapshot": customer,
            "requested_amount": application.requested_amount,
            "suggested_max_amount": rule_decision.suggested_max_amount,
            "findings": findings,
            "evidence": evidence,
            "materials": materials,
            "rag": agent_context.retrieval_trace,
            "agent_brief": agent_brief,
        }
        agent_run = finalize_pre_review(
            application.id,
            run_id,
            report,
            actor.id,
            snapshot,
            agent_brief,
        )
        application.status = ApplicationStatus.PRE_REVIEWED
    except Exception as error:
        try:
            transition_agent_run(run_id, AgentRunState.FAILED, error_code=type(error).__name__)
        except (KeyError, ValueError):
            pass
        raise
    _log_agent_run(application.id, agent_provider.name, agent_run["id"], "generate_brief", duration_ms, agent_brief)
    audit("agent_brief_generated", actor.id, application.id, provider=agent_provider.name, run_id=agent_run["id"])
    audit("pre_review_completed", actor.id, application.id, conclusion=report["conclusion"], finding_count=len(findings))
    return report


def answer_business_question(application: LoanApplication, actor: User, question: str, existing_run_id: str | None = None) -> dict:
    question = validate_agent_question(question)
    model_question = redact_sensitive_text(question)
    agent_provider = get_agent_provider("answer_question", application.id)
    run = get_agent_run(existing_run_id) if existing_run_id else create_agent_run(application.id, agent_provider.name, "answer_question", actor.id, {"task": "answer_question", "question": model_question, "request_id": current_request_id()})
    if not run or run["application_id"] != application.id:
        raise ValueError("待恢复的 Agent Run 不存在或不属于当前申请")
    run_id = run["id"]
    try:
        if run["state"] == AgentRunState.CREATED.value:
            transition_agent_run(run_id, AgentRunState.CONTEXT_BUILDING)
        _, _, _, _, _, agent_context = _build_agent_context(application, model_question)
        snapshot = _agent_input_snapshot(agent_context, "answer_question", model_question)
        update_agent_run_snapshot(run_id, snapshot)
        if agent_context.tool_results:
            transition_agent_run(run_id, AgentRunState.TOOL_RUNNING, tool_count=len(agent_context.tool_results))
        transition_agent_run(run_id, AgentRunState.MODEL_RUNNING, provider=agent_provider.name)
        started = time.perf_counter()
        answer, attempts = _invoke_agent_provider(
            agent_provider,
            "answer_question",
            agent_context,
            model_question,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        snapshot = _agent_input_snapshot(agent_context, "answer_question", model_question, duration_ms) | {"attempts": attempts}
        transition_agent_run(run_id, AgentRunState.VALIDATING)
        if answer.get("fallback"):
            transition_agent_run(run_id, AgentRunState.FALLBACK, reason=answer.get("fallback_reason"))
            transition_agent_run(run_id, AgentRunState.VALIDATING, event_type="fallback_output_validated")
        agent_run = finalize_agent_run(run_id, snapshot, answer)
    except Exception as error:
        try:
            transition_agent_run(run_id, AgentRunState.FAILED, error_code=type(error).__name__)
        except (KeyError, ValueError):
            pass
        raise
    answer = answer | {"run_id": agent_run["id"], "created_at": agent_run["created_at"]}
    _log_agent_run(application.id, agent_provider.name, agent_run["id"], "answer_question", duration_ms, answer)
    audit("agent_question_answered", actor.id, application.id, provider=agent_provider.name, run_id=agent_run["id"])
    return {"application_id": application.id, "question": model_question, "answer": answer}


def resume_agent_run_execution(application: LoanApplication, actor: User, run_id: str) -> dict:
    """Re-enter an interrupted Run using its persisted task and question snapshot."""
    run = get_agent_run(run_id)
    if not run or run["application_id"] != application.id:
        raise ValueError("待恢复的 Agent Run 不存在或不属于当前申请")
    if run["state"] not in {AgentRunState.CONTEXT_BUILDING.value, AgentRunState.FAILED.value}:
        raise ValueError(f"当前 Run 状态不支持恢复：{run['state']}")
    if run["state"] == AgentRunState.FAILED.value:
        from app.workflow_store import resume_agent_run
        resume_agent_run(run_id, actor.id)
    if run["task"] == "generate_brief":
        return pre_review(application, actor, existing_run_id=run_id)
    if run["task"] == "answer_question":
        question = run["input_snapshot"].get("question")
        if not question:
            raise ValueError("Agent Run 缺少可恢复的业务问题")
        return answer_business_question(application, actor, question, existing_run_id=run_id)
    raise ValueError(f"不支持恢复的 Agent 任务：{run['task']}")


def submit_for_approval(application: LoanApplication, actor: User, override_reason: str | None = None) -> dict:
    if application.status != ApplicationStatus.PRE_REVIEWED:
        raise ValueError("仅已完成预审的申请可提交审批")
    report = get_report(application.id)
    if not report:
        raise ValueError("提交审批前必须先生成预审报告")
    policy_decision = evaluate_submission_policy(report, override_reason)
    if not policy_decision.allowed:
        raise SubmissionPolicyError(policy_decision)
    task = create_approval_task(application.id, actor.id)
    application.status = ApplicationStatus.PENDING_APPROVAL
    audit("approval_submitted", actor.id, application.id, submission_policy=policy_decision.to_dict())
    return task | {"submission_policy": policy_decision.to_dict()}


def _build_agent_context(application: LoanApplication, question: str | None = None) -> tuple[dict, dict, PreReviewRuleDecision, list[dict], list[dict], AgentContext]:
    customer = get_customer(application.customer_id)
    assert customer is not None
    materials = material_check(application.id)
    rule_decision = evaluate_pre_review_rules(application, customer, materials)
    findings = rule_decision.findings_as_dicts()
    policy_query = question or " ".join([
        application.purpose,
        rule_decision.conclusion,
        *(item["message"] for item in findings),
    ])
    retrieval = retrieve_policy_context(
        policy_query,
        list_policies(),
        required_policy_ids=rule_decision.policy_evidence_ids,
    )
    evidence = [
        asdict(hit.policy) | {
            "citation": hit.document.metadata.get("citation"),
            "retrieval_score": hit.relevance_score,
        }
        for hit in sorted(retrieval.hits, key=lambda item: item.policy.id)
    ]
    tool_results = execute_agent_tools(application, question)
    agent_context = AgentContext(
        application_id=application.id,
        customer_name=customer["name"],
        requested_amount=application.requested_amount,
        suggested_max_amount=rule_decision.suggested_max_amount,
        conclusion=rule_decision.conclusion,
        findings=findings,
        evidence=evidence,
        materials_complete=materials["complete"],
        missing_materials=materials["missing"],
        tool_results=tool_results,
        retrieval_trace=retrieval.trace(),
    )
    return customer, materials, rule_decision, findings, evidence, agent_context


def _agent_input_snapshot(agent_context: AgentContext, task: str, question: str | None = None, duration_ms: float | None = None) -> dict:
    return {
        "task": task,
        "application_id": agent_context.application_id,
        "question": question,
        "requested_amount": agent_context.requested_amount,
        "suggested_max_amount": agent_context.suggested_max_amount,
        "conclusion": agent_context.conclusion,
        "finding_rule_ids": [item["rule_id"] for item in agent_context.findings],
        "evidence_ids": [item["id"] for item in agent_context.evidence],
        "materials_complete": agent_context.materials_complete,
        "missing_material_types": [item["type"] for item in agent_context.missing_materials],
        "tool_names": [item["tool_name"] for item in agent_context.tool_results],
        "tool_count": len(agent_context.tool_results),
        "rag": agent_context.retrieval_trace,
        "duration_ms": duration_ms,
        "request_id": current_request_id(),
        "prompt_id": get_prompt(task).prompt_id,
        "prompt_version": get_prompt(task).version,
    }


def _invoke_agent_provider(
    provider,
    task: str,
    context: AgentContext,
    question: str,
) -> tuple[dict, int]:
    """Retry model errors before asking the Provider for governed fallback."""
    invoker = ReliableInvoker.for_provider(provider.name)
    operation = (
        (lambda: provider.answer_question(context, question))
        if task == "answer_question"
        else (lambda: provider.generate_brief(context))
    )
    try:
        return invoker.invoke(operation)
    except Exception as error:
        return provider.degraded_output(task, context, question, error), invoker.config.max_retries + 1


def _log_agent_run(application_id: str, provider: str, run_id: str, task: str, duration_ms: float, output: dict) -> None:
    log_event(
        "agent_run_completed",
        event="agent_run_completed",
        application_id=application_id,
        provider=provider,
        run_id=run_id,
        task=task,
        duration_ms=duration_ms,
        fallback=bool(output.get("fallback")),
    )
