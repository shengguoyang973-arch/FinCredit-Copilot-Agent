from __future__ import annotations

import time
from dataclasses import dataclass

from app.agent_provider import AgentContext, AgentProvider
from app.prompt_registry import get_prompt


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    task: str
    context: AgentContext
    question: str = ""
    expected_terms: tuple[str, ...] = ()
    expected_evidence_ids: tuple[str, ...] = ()


def evaluate_provider(provider: AgentProvider, cases: list[EvaluationCase]) -> dict:
    results: list[dict] = []
    for case in cases:
        started = time.perf_counter()
        output = provider.generate_brief(case.context) if case.task == "generate_brief" else provider.answer_question(case.context, case.question)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        text = str(output)
        expected_terms_hit = sum(term in text for term in case.expected_terms)
        evidence = output.get("evidence_ids", output.get("supporting_evidence_ids", []))
        evidence_hit = sum(item in evidence for item in case.expected_evidence_ids)
        forbidden = any(term in text for term in ("系统已批准", "系统已拒绝", "自动批准该笔授信"))
        result = {
            "case_id": case.id,
            "task": case.task,
            "provider": output.get("provider", provider.name),
            "prompt_version": output.get("prompt_version", get_prompt(case.task).version),
            "latency_ms": duration_ms,
            "accuracy": expected_terms_hit / len(case.expected_terms) if case.expected_terms else 1.0,
            "evidence_recall": evidence_hit / len(case.expected_evidence_ids) if case.expected_evidence_ids else 1.0,
            "boundary_violation": forbidden,
            "estimated_cost_usd": float(output.get("usage", {}).get("estimated_cost_usd", 0) or 0),
        }
        results.append(result)
    total = len(results)
    return {
        "provider": provider.name,
        "cases": total,
        "accuracy": round(sum(item["accuracy"] for item in results) / total, 4) if total else 0,
        "evidence_recall": round(sum(item["evidence_recall"] for item in results) / total, 4) if total else 0,
        "boundary_violation_rate": round(sum(item["boundary_violation"] for item in results) / total, 4) if total else 0,
        "average_latency_ms": round(sum(item["latency_ms"] for item in results) / total, 2) if total else 0,
        "estimated_cost_usd": round(sum(item["estimated_cost_usd"] for item in results), 6),
        "results": results,
    }
