from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.agent_output import (
    LangChainAnswerResponse,
    LangChainBriefResponse,
    validate_answer,
    validate_brief,
)
from app.agent_runtime.router import route_provider
from app.config import get_settings
from app.prompt_registry import get_prompt


@dataclass(frozen=True)
class AgentContext:
    application_id: str
    customer_name: str
    requested_amount: int
    suggested_max_amount: int
    conclusion: str
    findings: list[dict]
    evidence: list[dict]
    materials_complete: bool
    missing_materials: list[dict]
    tool_results: list[dict]
    retrieval_trace: dict = field(default_factory=dict)
    task_plan: dict = field(default_factory=dict)
    plan_execution: list[dict] = field(default_factory=list)
    context_governance: dict = field(default_factory=dict)


class AgentProvider:
    name = "base"
    runtime = "native"

    def generate_brief(self, context: AgentContext) -> dict:
        raise NotImplementedError

    def answer_question(self, context: AgentContext, question: str) -> dict:
        raise NotImplementedError

    def degraded_output(self, task: str, context: AgentContext, question: str, error: Exception) -> dict:
        raise error


class DeterministicAgentProvider(AgentProvider):
    name = "deterministic-local"
    runtime = "deterministic"

    def generate_brief(self, context: AgentContext) -> dict:
        high_risks = [item for item in context.findings if item["severity"] in {"high", "block"}]
        missing_labels = [item["label"] for item in context.missing_materials]
        key_risks = [item["message"] for item in high_risks] or ["未发现阻断性或高风险规则命中。"]
        next_actions = []
        if missing_labels:
            next_actions.append(f"补齐材料：{'、'.join(missing_labels)}。")
        if context.requested_amount > context.suggested_max_amount:
            next_actions.append("复核申请金额与企业收入匹配性，必要时调整授信额度。")
        if not next_actions:
            next_actions.append("由审批人结合尽调记录、材料原件和授信政策进行人工审批。")
        return validate_brief({
            "provider": self.name,
            "runtime": self.runtime,
            "summary": f"{context.customer_name}申请流动资金授信 {context.requested_amount:,} 元，系统预审结论为：{context.conclusion}。",
            "key_risks": key_risks,
            "next_actions": next_actions,
            "governance_note": "Agent 仅生成尽调辅助意见，不自动批准、拒绝或退回授信申请；所有结论必须由具备权限的人员复核。",
            "evidence_ids": [item["id"] for item in context.evidence],
            "materials_complete": context.materials_complete,
        }, _allowed_evidence_ids(context))

    def answer_question(self, context: AgentContext, question: str) -> dict:
        high_risks = [item for item in context.findings if item["severity"] in {"high", "block"}]
        missing_labels = [item["label"] for item in context.missing_materials]
        if "为什么" in question or "原因" in question or "不能" in question:
            reason_text = "；".join(item["message"] for item in high_risks) or "当前没有高风险或阻断规则命中"
            answer = "主要原因是：" + reason_text
            if missing_labels:
                answer += f"；当前还缺少材料：{'、'.join(missing_labels)}。"
        elif "下一步" in question or "处理" in question:
            answer = "建议先补齐缺失材料并复核高风险项，再由有权限的审批人根据原始材料和制度条款作出人工决定。"
        else:
            answer = f"我已基于申请 {context.application_id} 的规则命中、政策证据和材料状态回答。当前预审状态为：{context.conclusion}。"
        return validate_answer({
            "provider": self.name,
            "runtime": self.runtime,
            "answer": answer,
            "supporting_evidence_ids": [item["id"] for item in context.evidence],
            "follow_up_actions": self.generate_brief(context)["next_actions"],
            "governance_note": "Agent 可解释业务事实、规则命中和下一步建议，但不能替代人工审批或作出授信决定。",
            "fallback": False,
        }, _allowed_evidence_ids(context))


class LangChainStructuredAgentProvider(AgentProvider):
    """LCEL prompt -> ChatModel -> Pydantic structured-output pipeline."""

    runtime = "langchain"
    api_key_env = ""
    missing_key_message = "模型 API 密钥未配置"
    structured_method = "json_schema"
    use_responses_api = False

    def __init__(self, fallback: AgentProvider | None = None):
        self.settings = get_settings()
        self.fallback = fallback or DeterministicAgentProvider()

    @property
    def model_name(self) -> str:
        raise NotImplementedError

    @property
    def base_url(self) -> str | None:
        return None

    def generate_brief(self, context: AgentContext) -> dict:
        return self._call_model("generate_brief", context, "")

    def answer_question(self, context: AgentContext, question: str) -> dict:
        return self._call_model("answer_question", context, question)

    def _call_model(self, task: str, context: AgentContext, question: str) -> dict:
        api_key = os.getenv(self.api_key_env)
        if not api_key:
            return self.degraded_output(task, context, question, RuntimeError(self.missing_key_message))

        model = ChatOpenAI(
            model=self.model_name,
            api_key=api_key,
            base_url=self.base_url,
            timeout=self.settings.openai_timeout_seconds,
            max_retries=0,
            temperature=0.2,
            use_responses_api=self.use_responses_api,
        )
        schema = LangChainAnswerResponse if task == "answer_question" else LangChainBriefResponse
        structured_model = model.with_structured_output(
            schema,
            method=self.structured_method,
            include_raw=True,
            strict=True if self.structured_method == "json_schema" else None,
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", get_prompt(task).content),
            ("human", "以下是经过权限控制和脱敏的业务上下文 JSON：\n{payload}"),
        ])
        chain = prompt | structured_model
        result = chain.invoke(
            {"payload": json.dumps(self._payload(task, context, question), ensure_ascii=False)},
            config={
                "tags": ["fincredit", task, self.name],
                "metadata": {
                    "application_id": context.application_id,
                    "prompt_version": get_prompt(task).version,
                    "rag_retriever": context.retrieval_trace.get("retriever"),
                },
            },
        )
        parsed = result.get("parsed")
        if parsed is None:
            parsing_error = result.get("parsing_error")
            raise ValueError(f"LangChain 结构化输出解析失败：{type(parsing_error).__name__}")
        output = parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
        output |= {
            "provider": self.name,
            "runtime": self.runtime,
            "model": self.model_name,
            "fallback": False,
            "usage": _usage_payload(result.get("raw")),
        }
        allowed_ids = _allowed_evidence_ids(context)
        return validate_answer(output, allowed_ids) if task == "answer_question" else validate_brief(output, allowed_ids)

    def degraded_output(self, task: str, context: AgentContext, question: str, error: Exception) -> dict:
        fallback_output = (
            self.fallback.answer_question(context, question)
            if task == "answer_question"
            else self.fallback.generate_brief(context)
        )
        error_label = str(error) if str(error) == self.missing_key_message else type(error).__name__
        return fallback_output | {
            "provider": self.name,
            "runtime": self.runtime,
            "fallback": True,
            "fallback_reason": f"LangChain 模型调用失败，已降级到本地 Provider：{error_label}",
        }

    def _payload(self, task: str, context: AgentContext, question: str) -> dict:
        return {
            "task": task,
            "question": question,
            "application": {
                "id": context.application_id,
                "customer_name": context.customer_name,
                "requested_amount": context.requested_amount,
                "suggested_max_amount": context.suggested_max_amount,
                "conclusion": context.conclusion,
            },
            "findings": context.findings,
            "evidence": context.evidence,
            "context_governance": context.context_governance,
            "materials": {
                "complete": context.materials_complete,
                "missing": context.missing_materials,
            },
            "retrieval": context.retrieval_trace,
            "task_plan": context.task_plan,
            "tool_results": context.tool_results,
        }


class OpenAIResponsesAgentProvider(LangChainStructuredAgentProvider):
    name = "openai-responses"
    api_key_env = "OPENAI_API_KEY"
    missing_key_message = "OPENAI_API_KEY 未配置"
    structured_method = "json_schema"
    use_responses_api = True

    @property
    def model_name(self) -> str:
        return self.settings.openai_model


class DeepSeekChatAgentProvider(LangChainStructuredAgentProvider):
    name = "deepseek-chat"
    api_key_env = "DEEPSEEK_API_KEY"
    missing_key_message = "DEEPSEEK_API_KEY 未配置"
    structured_method = "json_mode"

    @property
    def model_name(self) -> str:
        return self.settings.deepseek_model

    @property
    def base_url(self) -> str:
        return self.settings.deepseek_base_url


def get_agent_provider(task: str | None = None, subject: str | None = None) -> AgentProvider:
    provider = route_provider(task, subject)
    return provider_by_name(provider)


def provider_by_name(provider: str) -> AgentProvider:
    if provider in {"openai", "openai-responses"}:
        return OpenAIResponsesAgentProvider()
    if provider in {"deepseek", "deepseek-chat"}:
        return DeepSeekChatAgentProvider()
    return DeterministicAgentProvider()


def _allowed_evidence_ids(context: AgentContext) -> set[str]:
    return {str(item["id"]) for item in context.evidence}


def _usage_payload(response: object | None) -> dict:
    usage = getattr(response, "usage_metadata", None) or {}
    response_metadata = getattr(response, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage", {}) if isinstance(response_metadata, dict) else {}
    prompt = int(usage.get("input_tokens", token_usage.get("prompt_tokens", 0)) or 0)
    completion = int(usage.get("output_tokens", token_usage.get("completion_tokens", 0)) or 0)
    total = int(usage.get("total_tokens", token_usage.get("total_tokens", prompt + completion)) or 0)
    input_rate = float(os.getenv("FINCREDIT_INPUT_COST_PER_1K_USD", "0"))
    output_rate = float(os.getenv("FINCREDIT_OUTPUT_COST_PER_1K_USD", "0"))
    estimated_cost = (prompt / 1000 * input_rate) + (completion / 1000 * output_rate)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "estimated_cost_usd": round(estimated_cost, 8),
        "pricing_configured": bool(input_rate or output_rate),
    }
