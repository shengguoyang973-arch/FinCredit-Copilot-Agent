"""Load and validate de-identified, versioned Agent evaluation datasets."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.agent_provider import AgentContext
from app.config import get_settings
from app.evaluation import EvaluationCase


_IDENTIFIER_PATTERNS = (
    re.compile(r"\b\d{15,18}[A-Za-z]?\b"),
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"(?:身份证|统一社会信用代码|开户地址|客户姓名|注册号)"),
)
_ALLOWED_TASKS = {"generate_brief", "answer_question"}


def load_evaluation_dataset(path: Path | None = None) -> tuple[dict, list[EvaluationCase]]:
    source = path or get_settings().evaluation_dataset_path
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("脱敏评测集无法读取或不是有效 JSON") from error
    manifest = validate_evaluation_dataset(payload, source.name)
    cases = [_case_from_payload(item) for item in payload["cases"]]
    return manifest, cases


def validate_evaluation_dataset(payload: dict[str, Any], source_label: str = "dataset") -> dict:
    if payload.get("classification") != "deidentified":
        raise ValueError("评测集必须声明 classification=deidentified")
    dataset_id = payload.get("dataset_id")
    cases = payload.get("cases")
    if not isinstance(dataset_id, str) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{5,80}", dataset_id):
        raise ValueError("评测集 dataset_id 格式无效")
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测集至少需要一个案例")
    case_ids: set[str] = set()
    for item in cases:
        _validate_case(item, case_ids)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "dataset_id": dataset_id,
        "dataset_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "classification": "deidentified",
        "case_count": len(cases),
        "source_label": payload.get("source_label") or source_label,
    }


def _validate_case(item: Any, case_ids: set[str]) -> None:
    if not isinstance(item, dict):
        raise ValueError("评测案例必须是对象")
    case_id, task, context = item.get("id"), item.get("task"), item.get("context")
    if not isinstance(case_id, str) or not re.fullmatch(r"EVAL-[A-Z0-9-]{4,80}", case_id) or case_id in case_ids:
        raise ValueError("评测案例 ID 无效或重复")
    case_ids.add(case_id)
    if task not in _ALLOWED_TASKS or not isinstance(context, dict):
        raise ValueError("评测案例任务或上下文无效")
    required = {"application_id", "customer_name", "requested_amount", "suggested_max_amount", "conclusion", "findings", "evidence", "materials_complete", "missing_materials"}
    if not required.issubset(context):
        raise ValueError("评测案例缺少必要脱敏上下文字段")
    if not str(context["application_id"]).startswith("EVAL-") or not str(context["customer_name"]).startswith("脱敏企业-"):
        raise ValueError("评测上下文必须使用 EVAL 标识与脱敏企业别名")
    if task == "answer_question" and not isinstance(item.get("question"), str):
        raise ValueError("问答评测案例必须有问题")
    if not isinstance(item.get("expected_terms", []), list) or not isinstance(item.get("expected_evidence_ids", []), list):
        raise ValueError("评测期望字段必须是列表")
    text = json.dumps(item, ensure_ascii=False, sort_keys=True)
    if any(pattern.search(text) for pattern in _IDENTIFIER_PATTERNS):
        raise ValueError("脱敏评测集包含疑似直接标识信息")


def _case_from_payload(item: dict[str, Any]) -> EvaluationCase:
    context = item["context"]
    agent_context = AgentContext(
        application_id=context["application_id"], customer_name=context["customer_name"],
        requested_amount=context["requested_amount"], suggested_max_amount=context["suggested_max_amount"],
        conclusion=context["conclusion"], findings=context["findings"], evidence=context["evidence"],
        materials_complete=context["materials_complete"], missing_materials=context["missing_materials"],
        tool_results=context.get("tool_results", []),
    )
    return EvaluationCase(
        id=item["id"], task=item["task"], context=agent_context, question=item.get("question", ""),
        expected_terms=tuple(item.get("expected_terms", [])), expected_evidence_ids=tuple(item.get("expected_evidence_ids", [])),
    )
