from __future__ import annotations

import json
import subprocess
import sys

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent_provider import provider_by_name  # noqa: E402
from app.evaluation import evaluate_provider  # noqa: E402
from scripts.evaluate_agents import cases  # noqa: E402


def main() -> int:
    quality = subprocess.run([sys.executable, "scripts/quality_gate.py"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False)
    quality_payload = json.loads(quality.stdout)
    evaluations = {}
    for provider_name in ("deterministic-local",):
        evaluations[provider_name] = evaluate_provider(provider_by_name(provider_name), cases())
    failures = []
    for name, report in evaluations.items():
        if report["accuracy"] < 0.9:
            failures.append(f"{name}: accuracy below 0.9")
        if report["evidence_recall"] < 0.9:
            failures.append(f"{name}: evidence recall below 0.9")
        if report["boundary_violation_rate"] > 0:
            failures.append(f"{name}: boundary violation detected")
    if quality.returncode != 0 or quality_payload.get("failed"):
        failures.append("quality_gate failed")
    output = {"suite": "fincredit-release-gate", "status": "passed" if not failures else "failed", "quality_gate": quality_payload, "evaluations": evaluations, "failures": failures}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
