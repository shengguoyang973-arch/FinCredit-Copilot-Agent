from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent_provider import provider_by_name
from app.evaluation import EvaluationCase, evaluate_provider
from app.evaluation_dataset import load_evaluation_dataset


def cases() -> list[EvaluationCase]:
    return load_evaluation_dataset()[1]


if __name__ == "__main__":
    providers = [item.strip() for item in os.getenv("FINCREDIT_EVAL_PROVIDERS", "deterministic-local").split(",") if item.strip()]
    manifest, dataset_cases = load_evaluation_dataset()
    report = {name: evaluate_provider(provider_by_name(name), dataset_cases) for name in providers}
    print(json.dumps({"suite": "fincredit-agent-evaluation", "dataset": manifest, "providers": report}, ensure_ascii=False, indent=2))
