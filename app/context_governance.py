"""Bound and describe the data sent to an external-model prompt.

The report keeps its full evidence chain.  This module creates a separately
bounded copy for model context, retaining every evidence identifier and never
adding raw document material.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from app.config import get_settings


def constrain_model_context(evidence: list[dict], tool_results: list[dict]) -> tuple[list[dict], list[dict], dict]:
    settings = get_settings()
    bounded_evidence = copy.deepcopy(evidence)
    bounded_tools = copy.deepcopy(tool_results)
    # Calculate the overhead with every evidence body empty.  That leaves a
    # deterministic allocation for policy text while preserving identifiers and
    # citation metadata for every hit.
    base_evidence = [item | {"content": ""} for item in bounded_evidence]
    base_size = _size({"evidence": base_evidence, "tool_results": bounded_tools})
    if base_size > settings.agent_context_max_chars:
        raise ValueError("受控上下文元数据超过 FINCREDIT_AGENT_CONTEXT_MAX_CHARS，拒绝发送模型请求")
    remaining = max(0, settings.agent_context_max_chars - base_size)
    contents = [str(item.get("content", "")) for item in bounded_evidence]
    allocation = remaining // len(contents) if contents else 0
    truncated_ids: list[str] = []
    for item, content in zip(bounded_evidence, contents, strict=True):
        if len(content) > allocation:
            item["content"] = _truncate(content, allocation)
            truncated_ids.append(str(item.get("id", "unknown")))
    used_chars = _size({"evidence": bounded_evidence, "tool_results": bounded_tools})
    # JSON escaping and the truncation marker can make a character allocation
    # slightly larger than its serialized form permits.  Trim deterministically
    # until the contractual limit is met instead of sending an oversized prompt.
    while used_chars > settings.agent_context_max_chars:
        overflow = used_chars - settings.agent_context_max_chars
        candidates = [item for item in bounded_evidence if item.get("content")]
        if not candidates:
            raise ValueError("受控上下文无法在 FINCREDIT_AGENT_CONTEXT_MAX_CHARS 内编码")
        largest = max(candidates, key=lambda item: len(str(item["content"])))
        largest["content"] = _truncate(str(largest["content"]), max(0, len(str(largest["content"])) - overflow))
        evidence_id = str(largest.get("id", "unknown"))
        if evidence_id not in truncated_ids:
            truncated_ids.append(evidence_id)
        used_chars = _size({"evidence": bounded_evidence, "tool_results": bounded_tools})
    canonical = next(
        (item.get("result", {}) for item in bounded_tools if item.get("tool_name") == "get_canonical_customer_snapshot"),
        {},
    )
    metadata = {
        "max_chars": settings.agent_context_max_chars,
        "used_chars": used_chars,
        "truncated_evidence_ids": truncated_ids,
        "evidence_count": len(bounded_evidence),
        "canonical_data": {
            "available": bool(canonical.get("available")),
            "freshness": canonical.get("freshness"),
            "conflicting_fields": canonical.get("conflicting_fields", []),
            "classification": canonical.get("classification"),
        },
        "context_hash": hashlib.sha256(_payload(bounded_evidence, bounded_tools).encode("utf-8")).hexdigest(),
    }
    return bounded_evidence, bounded_tools, metadata


def _truncate(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    marker = "…[已按上下文预算截断]"
    if limit <= len(marker):
        return value[:limit]
    return value[:limit - len(marker)] + marker


def _payload(evidence: list[dict], tool_results: list[dict]) -> str:
    return json.dumps({"evidence": evidence, "tool_results": tool_results}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _size(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
