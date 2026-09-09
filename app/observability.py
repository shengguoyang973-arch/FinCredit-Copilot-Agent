from __future__ import annotations

import contextvars
import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        for key in ("method", "path", "status_code", "duration_ms", "event", "application_id", "provider", "run_id", "task", "fallback"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def current_request_id() -> str | None:
    return request_id_var.get()


def log_event(message: str, **extra: object) -> None:
    logging.getLogger("fincredit").info(message, extra=extra)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or f"req-{uuid4().hex[:16]}"
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            request_id_var.reset(token)
        response.headers["X-Request-Id"] = request_id
        log_event(
            "http_request_completed",
            event="http_request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
