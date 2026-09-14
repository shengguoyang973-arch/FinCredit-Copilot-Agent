import time

import pytest

from app.agent_runtime.reliability import (
    ProviderCircuitOpenError,
    ReliabilityConfig,
    ReliableInvoker,
)


def test_invoker_retries_transient_failure() -> None:
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("temporary")
        return "ok"

    result, used_attempts = ReliableInvoker(ReliabilityConfig(max_retries=2, timeout_seconds=1)).invoke(operation)
    assert result == "ok"
    assert used_attempts == 2
    assert attempts == 3


def test_invoker_times_out_and_opens_circuit() -> None:
    config = ReliabilityConfig(timeout_seconds=0.01, max_retries=0, failure_threshold=1, cooldown_seconds=60)
    invoker = ReliableInvoker(config)
    with pytest.raises(TimeoutError):
        invoker.invoke(lambda: time.sleep(0.1))
    with pytest.raises(ProviderCircuitOpenError):
        invoker.invoke(lambda: "never")
