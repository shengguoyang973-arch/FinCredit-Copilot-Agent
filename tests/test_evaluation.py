from app.agent_provider import DeterministicAgentProvider
from scripts.evaluate_agents import cases
from app.evaluation import evaluate_provider


def test_evaluation_reports_quality_dimensions() -> None:
    report = evaluate_provider(DeterministicAgentProvider(), cases())
    assert report["cases"] == 3
    assert report["accuracy"] >= 0.8
    assert report["evidence_recall"] == 1.0
    assert report["boundary_violation_rate"] == 0
    assert "average_latency_ms" in report
    assert "estimated_cost_usd" in report
