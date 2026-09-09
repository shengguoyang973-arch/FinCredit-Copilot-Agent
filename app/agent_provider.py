from __future__ import annotations

import json
import os
from dataclasses import dataclass

from app.config import get_settings
from app.agent_runtime.router import route_provider
from app.prompt_registry import get_prompt
from app.agent_output import openai_schema_for_task, validate_answer, validate_brief


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


class AgentProvider:
    name = "base"

    def generate_brief(self, context: AgentContext) -> dict:
        raise NotImplementedError

    def answer_question(self, context: AgentContext, question: str) -> dict:
        raise NotImplementedError


class DeterministicAgentProvider(AgentProvider):
    name = "deterministic-local"

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
            "summary": f"{context.customer_name}申请流动资金授信 {context.requested_amount:,} 元，系统预审结论为：{context.conclusion}。",
            "key_risks": key_risks,
            "next_actions": next_actions,
            "governance_note": "Agent 仅生成尽调辅助意见，不自动批准、拒绝或退回授信申请；所有结论必须由具备权限的人员复核。",
            "evidence_ids": [item["id"] for item in context.evidence],
            "materials_complete": context.materials_complete,
        })

    def answer_question(self, context: AgentContext, question: str) -> dict:
        high_risks = [item for item in context.findings if item["severity"] in {"high", "block"}]
        missing_labels = [item["label"] for item in context.missing_materials]
        if "为什么" in question or "原因" in question or "不能" in question:
            answer = "主要原因是：" + "；".join(item["message"] for item in high_risks)
            if missing_labels:
                answer += f"；当前还缺少材料：{'、'.join(missing_labels)}。"
        elif "下一步" in question or "处理" in question:
            answer = "建议先补齐缺失材料并复核高风险项，再由有权限的审批人根据原始材料和制度条款作出人工决定。"
        else:
            answer = f"我已基于申请 {context.application_id} 的规则命中、政策证据和材料状态回答。当前结论为：{context.conclusion}。"
        return validate_answer({
            "provider": self.name,
            "answer": answer,
            "supporting_evidence_ids": [item["id"] for item in context.evidence],
            "follow_up_actions": self.generate_brief(context)["next_actions"],
            "governance_note": "Agent 可解释业务事实、规则命中和下一步建议，但不能替代人工审批或作出授信决定。",
            "fallback": False,
        })


class OpenAIResponsesAgentProvider(AgentProvider):
    name = "openai-responses"

    def __init__(self, fallback: AgentProvider | None = None):
        self.settings = get_settings()
        self.fallback = fallback or DeterministicAgentProvider()

    def generate_brief(self, context: AgentContext) -> dict:
        fallback_output = self.fallback.generate_brief(context)
        return self._call_model("generate_brief", context, "", fallback_output)

    def answer_question(self, context: AgentContext, question: str) -> dict:
        fallback_output = self.fallback.answer_question(context, question)
        return self._call_model("answer_question", context, question, fallback_output)

    def _call_model(self, task: str, context: AgentContext, question: str, fallback_output: dict) -> dict:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return fallback_output | {"provider": self.name, "fallback": True, "fallback_reason": "OPENAI_API_KEY 未配置，已使用本地确定性 Provider。"}
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=self.settings.openai_timeout_seconds)
            response = client.responses.create(
                model=self.settings.openai_model,
                text={"format": {"type": "json_schema", **openai_schema_for_task(task)}},
                input=[
                    {"role": "system", "content": self._system_prompt(task)},
                    {"role": "user", "content": json.dumps(self._payload(task, context, question), ensure_ascii=False)},
                ],
            )
            parsed = self._parse_response(response)
            output = parsed | {"provider": self.name, "model": self.settings.openai_model, "fallback": False, "usage": _usage_payload(response)}
            return validate_answer(output) if task == "answer_question" else validate_brief(output)
        except Exception as error:
            return fallback_output | {
                "provider": self.name,
                "fallback": True,
                "fallback_reason": f"真实模型调用失败，已降级到本地 Provider：{type(error).__name__}",
            }

    def _system_prompt(self, task: str) -> str:
        return get_prompt(task).content

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
            "materials": {
                "complete": context.materials_complete,
                "missing": context.missing_materials,
            },
            "tool_results": context.tool_results,
        }

    def _parse_response(self, response: object) -> dict:
        text = getattr(response, "output_text", "")
        if not text:
            raise ValueError("模型响应为空")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("模型响应不是 JSON 对象")
        return parsed


class DeepSeekChatAgentProvider(AgentProvider):
    name = "deepseek-chat"

    def __init__(self, fallback: AgentProvider | None = None):
        self.settings = get_settings()
        self.fallback = fallback or DeterministicAgentProvider()

    def generate_brief(self, context: AgentContext) -> dict:
        fallback_output = self.fallback.generate_brief(context)
        return self._call_model("generate_brief", context, "", fallback_output)

    def answer_question(self, context: AgentContext, question: str) -> dict:
        fallback_output = self.fallback.answer_question(context, question)
        return self._call_model("answer_question", context, question, fallback_output)

    def _call_model(self, task: str, context: AgentContext, question: str, fallback_output: dict) -> dict:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return fallback_output | {
                "provider": self.name,
                "fallback": True,
                "fallback_reason": "DEEPSEEK_API_KEY 未配置，已使用本地确定性 Provider。",
            }
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=api_key,
                base_url=self.settings.deepseek_base_url,
                timeout=self.settings.openai_timeout_seconds,
            )
            response = client.chat.completions.create(
                model=self.settings.deepseek_model,
                messages=[
                    {"role": "system", "content": self._system_prompt(task)},
                    {"role": "user", "content": json.dumps(self._payload(task, context, question), ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                stream=False,
            )
            parsed = self._parse_response(response)
            output = parsed | {"provider": self.name, "model": self.settings.deepseek_model, "fallback": False, "usage": _usage_payload(response)}
            return validate_answer(output) if task == "answer_question" else validate_brief(output)
        except Exception as error:
            return fallback_output | {
                "provider": self.name,
                "fallback": True,
                "fallback_reason": f"DeepSeek 模型调用失败，已降级到本地 Provider：{type(error).__name__}",
            }

    def _system_prompt(self, task: str) -> str:
        return get_prompt(task).content

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
            "materials": {
                "complete": context.materials_complete,
                "missing": context.missing_materials,
            },
            "tool_results": context.tool_results,
        }

    def _parse_response(self, response: object) -> dict:
        choices = getattr(response, "choices", [])
        if not choices:
            raise ValueError("模型响应为空")
        message = choices[0].message
        text = getattr(message, "content", "")
        if not text:
            raise ValueError("模型响应内容为空")
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("模型响应不是 JSON 对象")
        return parsed


def get_agent_provider(task: str | None = None, subject: str | None = None) -> AgentProvider:
    provider = route_provider(task, subject)
    return provider_by_name(provider)


def provider_by_name(provider: str) -> AgentProvider:
    if provider in {"openai", "openai-responses"}:
        return OpenAIResponsesAgentProvider()
    if provider in {"deepseek", "deepseek-chat"}:
        return DeepSeekChatAgentProvider()
    return DeterministicAgentProvider()


def _usage_payload(response: object) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0}
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", prompt + completion) or 0)
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
