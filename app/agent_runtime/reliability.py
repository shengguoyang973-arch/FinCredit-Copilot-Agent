from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from threading import Lock
from typing import Callable, TypeVar

from app.config import get_settings

T = TypeVar("T")


class ProviderCircuitOpenError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReliabilityConfig:
    timeout_seconds: float = 20.0
    max_retries: int = 2
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0


class ProviderCircuitBreaker:
    def __init__(self, config: ReliabilityConfig):
        self.config = config
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = Lock()

    @property
    def open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self.config.cooldown_seconds:
                self._opened_at = None
                self._failures = 0
                return False
            return True

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.config.failure_threshold:
                self._opened_at = time.monotonic()


class ReliableInvoker:
    _breakers: dict[str, ProviderCircuitBreaker] = {}
    _breakers_lock = Lock()

    def __init__(self, config: ReliabilityConfig | None = None, breaker: ProviderCircuitBreaker | None = None):
        settings = get_settings()
        self.config = config or ReliabilityConfig(
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.agent_max_retries,
            failure_threshold=settings.agent_circuit_failure_threshold,
            cooldown_seconds=settings.agent_circuit_cooldown_seconds,
        )
        self.breaker = breaker or ProviderCircuitBreaker(self.config)

    @classmethod
    def for_provider(cls, provider: str) -> "ReliableInvoker":
        settings = get_settings()
        config = ReliabilityConfig(
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.agent_max_retries,
            failure_threshold=settings.agent_circuit_failure_threshold,
            cooldown_seconds=settings.agent_circuit_cooldown_seconds,
        )
        with cls._breakers_lock:
            breaker = cls._breakers.setdefault(provider, ProviderCircuitBreaker(config))
        return cls(config, breaker)

    def invoke(self, operation: Callable[[], T]) -> tuple[T, int]:
        if self.breaker.open:
            raise ProviderCircuitOpenError("Provider 熔断器已打开")
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(operation)
            try:
                result = future.result(timeout=self.config.timeout_seconds)
                executor.shutdown(wait=True, cancel_futures=False)
                self.breaker.success()
                return result, attempt
            except FutureTimeoutError:
                future.cancel()
                # Do not wait for a timed-out provider call. The provider-level
                # network timeout remains responsible for releasing its worker.
                executor.shutdown(wait=False, cancel_futures=True)
                last_error = TimeoutError("Provider 调用超时")
                self.breaker.failure()
            except Exception as error:
                executor.shutdown(wait=True, cancel_futures=False)
                last_error = error
                self.breaker.failure()
            if attempt < self.config.max_retries:
                time.sleep(min(0.1 * (2**attempt), 1.0))
        assert last_error is not None
        raise last_error
