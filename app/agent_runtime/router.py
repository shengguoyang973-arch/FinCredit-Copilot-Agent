from __future__ import annotations

import os
import hashlib


def provider_chain() -> list[str]:
    configured = os.getenv("FINCREDIT_AGENT_PROVIDER_CHAIN", "").strip()
    if configured:
        return [item.strip().lower() for item in configured.split(",") if item.strip()]
    return [os.getenv("FINCREDIT_AGENT_PROVIDER", "deterministic-local").strip().lower()]


def route_provider(task: str | None = None, subject: str | None = None) -> str:
    """Stable canary routing; the same subject stays on the same Provider."""
    del task
    chain = provider_chain()
    if len(chain) < 2:
        return chain[0]
    try:
        percentage = max(0, min(100, int(os.getenv("FINCREDIT_AGENT_GRAY_PERCENT", "0"))))
    except ValueError:
        percentage = 0
    if not subject or percentage <= 0:
        return chain[0]
    bucket = int(hashlib.sha256(subject.encode("utf-8")).hexdigest()[:8], 16) % 100
    return chain[1] if bucket < percentage else chain[0]
