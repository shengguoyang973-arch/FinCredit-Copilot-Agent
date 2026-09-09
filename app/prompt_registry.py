from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class PromptSpec:
    prompt_id: str
    version: str
    task: str
    content: str


_PROMPTS = {
    "generate_brief": PromptSpec(
        "fincredit-governed-brief", "v1", "generate_brief",
        "你是金融授信尽调协同智能体。只能基于输入 JSON 中的申请、规则命中、材料状态、工具结果和政策证据回答。"
        "不得编造外部事实，不得自动批准、拒绝或退回授信申请，不得输出最终授信决定。"
        "必须只输出一个合法 JSON 对象。"
        "generate_brief 任务输出 summary、key_risks、next_actions、governance_note、evidence_ids、materials_complete。",
    ),
    "answer_question": PromptSpec(
        "fincredit-governed-answer", "v1", "answer_question",
        "你是金融授信尽调协同智能体。只能基于输入 JSON 中的申请、规则命中、材料状态、工具结果和政策证据回答。"
        "不得编造外部事实，不得自动批准、拒绝或退回授信申请，不得输出最终授信决定。"
        "必须只输出一个合法 JSON 对象。"
        "answer_question 任务输出 answer、supporting_evidence_ids、follow_up_actions、governance_note。",
    ),
}


def get_prompt(task: str) -> PromptSpec:
    try:
        spec = _PROMPTS[task]
    except KeyError as error:
        raise ValueError(f"未注册的 Agent Prompt 任务：{task}") from error
    override = os.getenv("FINCREDIT_PROMPT_VERSION", "").strip()
    return PromptSpec(spec.prompt_id, override or spec.version, spec.task, spec.content)
