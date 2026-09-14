from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from app.domain import PolicyClause
from app.rag.contracts import RAGConfig
from app.rag.service import retrieve_policy_context


@dataclass(frozen=True)
class RAGEvaluationCase:
    id: str
    query: str
    expected_policy_ids: tuple[str, ...]


def evaluate_rag(
    policies: list[PolicyClause],
    cases: list[RAGEvaluationCase],
    config: RAGConfig,
) -> dict:
    results: list[dict] = []
    for case in cases:
        retrieval = retrieve_policy_context(case.query, policies, config=config)
        retrieved_ids = [hit.policy.id for hit in retrieval.hits]
        expected = set(case.expected_policy_ids)
        matched = expected.intersection(retrieved_ids)
        first_rank = min(
            (retrieved_ids.index(policy_id) + 1 for policy_id in expected if policy_id in retrieved_ids),
            default=None,
        )
        results.append({
            "case_id": case.id,
            "retrieved_policy_ids": retrieved_ids,
            "expected_policy_ids": list(case.expected_policy_ids),
            "hit": bool(matched),
            "recall": len(matched) / len(expected) if expected else 1.0,
            "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
        })
    total = len(results)
    hit_rate = sum(item["hit"] for item in results) / total if total else 0.0
    recall = sum(item["recall"] for item in results) / total if total else 0.0
    mrr = sum(item["reciprocal_rank"] for item in results) / total if total else 0.0
    return {
        "config": config.to_dict(),
        "cases": total,
        "hit_rate": round(hit_rate, 4),
        "recall": round(recall, 4),
        "mrr": round(mrr, 4),
        "score": round(hit_rate * 0.25 + recall * 0.35 + mrr * 0.40, 4),
        "results": results,
    }


def tune_rag(
    policies: list[PolicyClause],
    cases: list[RAGEvaluationCase],
) -> dict:
    candidates = []
    for lexical_weight, top_k, min_score in product((0.4, 0.55, 0.7, 0.85), (1, 3, 5), (0.0, 0.1, 0.2)):
        config = RAGConfig(
            top_k=top_k,
            lexical_weight=lexical_weight,
            vector_weight=1 - lexical_weight,
            min_vector_score=min_score,
        )
        candidates.append(evaluate_rag(policies, cases, config))
    ranked = sorted(
        candidates,
        key=lambda item: (-item["score"], -item["mrr"], item["config"]["top_k"], -item["config"]["lexical_weight"]),
    )
    return {"best": ranked[0], "candidate_count": len(ranked), "candidates": ranked}
