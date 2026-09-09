from __future__ import annotations

from collections import Counter

from app.workflow_store import list_all_agent_runs


def agent_metrics(limit: int = 200) -> dict:
    runs = list_all_agent_runs(limit)
    provider_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    latencies: list[float] = []
    fallback_count = 0
    total_tokens = 0
    total_cost = 0.0

    for run in runs:
        provider_counts[run["provider"]] += 1
        input_snapshot = run["input_snapshot"]
        output = run["output"]
        task_counts[input_snapshot.get("task", "unknown")] += 1
        for tool_name in input_snapshot.get("tool_names", []):
            tool_counts[tool_name] += 1
        if output.get("fallback"):
            fallback_count += 1
        usage = output.get("usage", {})
        total_tokens += int(usage.get("total_tokens", 0) or 0)
        total_cost += float(usage.get("estimated_cost_usd", 0) or 0)
        if isinstance(input_snapshot.get("duration_ms"), int | float):
            latencies.append(float(input_snapshot["duration_ms"]))

    total = len(runs)
    return {
        "total_runs": total,
        "fallback_runs": fallback_count,
        "fallback_rate": round(fallback_count / total, 4) if total else 0,
        "average_duration_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "max_duration_ms": round(max(latencies), 2) if latencies else 0,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(total_cost, 6),
        "provider_counts": dict(provider_counts),
        "task_counts": dict(task_counts),
        "tool_counts": dict(tool_counts),
        "recent_runs": [{
            "id": run["id"],
            "application_id": run["application_id"],
            "provider": run["provider"],
            "task": run["input_snapshot"].get("task"),
            "duration_ms": run["input_snapshot"].get("duration_ms"),
            "fallback": bool(run["output"].get("fallback")),
            "tool_names": run["input_snapshot"].get("tool_names", []),
            "created_at": run["created_at"],
        } for run in runs[:10]],
    }
