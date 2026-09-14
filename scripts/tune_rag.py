from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.bootstrap import initialize_application  # noqa: E402
from app.knowledge_store import list_policies  # noqa: E402
from app.rag.contracts import RAGConfig  # noqa: E402
from app.rag.tuning import RAGEvaluationCase, evaluate_rag, tune_rag  # noqa: E402

DEFAULT_DATASET = PROJECT_ROOT / "demo_data" / "rag_evaluation.json"


def load_cases(path: Path = DEFAULT_DATASET) -> list[RAGEvaluationCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        RAGEvaluationCase(
            id=item["id"],
            query=item["query"],
            expected_policy_ids=tuple(item["expected_policy_ids"]),
        )
        for item in payload["cases"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune FinCredit LangChain hybrid RAG parameters.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, help="Optional path for the complete tuning report.")
    parser.add_argument("--evaluate-current", action="store_true", help="Evaluate environment configuration without grid search.")
    args = parser.parse_args()

    initialize_application()
    policies = list_policies()
    cases = load_cases(args.dataset)
    if args.evaluate_current:
        report = {"mode": "evaluate-current", "result": evaluate_rag(policies, cases, RAGConfig.from_settings())}
    else:
        tuning = tune_rag(policies, cases)
        report = {
            "mode": "grid-search",
            "dataset": str(args.dataset),
            "best": tuning["best"],
            "candidate_count": tuning["candidate_count"],
        }

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
