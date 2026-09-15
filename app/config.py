from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "FinCredit Copilot"
    app_version: str = "0.3.0"
    service_name: str = "fincredit-copilot"
    deployment_environment: str = "development"
    identity_provider: str = "demo-header"
    agent_provider: str = "deterministic-local"
    openai_model: str = "gpt-4.1-mini"
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_base_url: str = "https://api.deepseek.com"
    openai_timeout_seconds: float = 20.0
    agent_max_retries: int = 2
    agent_circuit_failure_threshold: int = 3
    agent_circuit_cooldown_seconds: float = 30.0
    max_document_bytes: int = 2_000_000
    rag_top_k: int = 3
    rag_lexical_weight: float = 0.85
    rag_vector_weight: float = 0.15
    rag_min_vector_score: float = 0.0
    rag_chunk_size: int = 180
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "fincredit.db"


def get_settings() -> Settings:
    data_dir = Path(os.getenv("FINCREDIT_DATA_DIR", str(Settings.data_dir)))
    max_document_bytes = int(os.getenv("FINCREDIT_MAX_DOCUMENT_BYTES", str(Settings.max_document_bytes)))
    return Settings(
        deployment_environment=os.getenv("FINCREDIT_ENVIRONMENT", Settings.deployment_environment).strip().lower(),
        identity_provider=os.getenv("FINCREDIT_IDENTITY_PROVIDER", Settings.identity_provider).strip().lower(),
        agent_provider=os.getenv("FINCREDIT_AGENT_PROVIDER", Settings.agent_provider).strip().lower(),
        openai_model=os.getenv("OPENAI_MODEL", Settings.openai_model).strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", Settings.deepseek_model).strip(),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", Settings.deepseek_base_url).strip(),
        openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", str(Settings.openai_timeout_seconds))),
        agent_max_retries=int(os.getenv("FINCREDIT_AGENT_MAX_RETRIES", str(Settings.agent_max_retries))),
        agent_circuit_failure_threshold=int(os.getenv("FINCREDIT_AGENT_CIRCUIT_FAILURE_THRESHOLD", str(Settings.agent_circuit_failure_threshold))),
        agent_circuit_cooldown_seconds=float(os.getenv("FINCREDIT_AGENT_CIRCUIT_COOLDOWN_SECONDS", str(Settings.agent_circuit_cooldown_seconds))),
        max_document_bytes=max_document_bytes,
        rag_top_k=int(os.getenv("FINCREDIT_RAG_TOP_K", str(Settings.rag_top_k))),
        rag_lexical_weight=float(os.getenv("FINCREDIT_RAG_LEXICAL_WEIGHT", str(Settings.rag_lexical_weight))),
        rag_vector_weight=float(os.getenv("FINCREDIT_RAG_VECTOR_WEIGHT", str(Settings.rag_vector_weight))),
        rag_min_vector_score=float(os.getenv("FINCREDIT_RAG_MIN_VECTOR_SCORE", str(Settings.rag_min_vector_score))),
        rag_chunk_size=int(os.getenv("FINCREDIT_RAG_CHUNK_SIZE", str(Settings.rag_chunk_size))),
        data_dir=data_dir,
    )


def validate_settings(settings: Settings | None = None) -> list[str]:
    """Return non-secret configuration errors for startup/readiness checks."""
    settings = settings or get_settings()
    errors: list[str] = []
    if settings.deployment_environment not in {"development", "test", "production"}:
        errors.append("FINCREDIT_ENVIRONMENT 必须是 development、test 或 production")
    if settings.identity_provider not in {"demo-header", "oidc"}:
        errors.append("FINCREDIT_IDENTITY_PROVIDER 必须是 demo-header 或 oidc")
    if settings.deployment_environment == "production" and settings.identity_provider == "demo-header":
        errors.append("生产环境禁止使用 demo-header 身份提供方")
    if settings.openai_timeout_seconds <= 0:
        errors.append("OPENAI_TIMEOUT_SECONDS 必须大于 0")
    if settings.agent_max_retries < 0:
        errors.append("FINCREDIT_AGENT_MAX_RETRIES 不能小于 0")
    if settings.max_document_bytes <= 0:
        errors.append("FINCREDIT_MAX_DOCUMENT_BYTES 必须大于 0")
    if not 1 <= settings.rag_top_k <= 50:
        errors.append("FINCREDIT_RAG_TOP_K 必须在 1 到 50 之间")
    if settings.rag_lexical_weight < 0 or settings.rag_vector_weight < 0:
        errors.append("RAG 检索权重不能小于 0")
    if settings.rag_lexical_weight + settings.rag_vector_weight <= 0:
        errors.append("RAG 检索权重之和必须大于 0")
    if not -1 <= settings.rag_min_vector_score <= 1:
        errors.append("FINCREDIT_RAG_MIN_VECTOR_SCORE 必须在 -1 到 1 之间")
    if settings.rag_chunk_size < 50:
        errors.append("FINCREDIT_RAG_CHUNK_SIZE 不能小于 50")
    if settings.agent_provider in {"deepseek", "deepseek-chat"} and not os.getenv("DEEPSEEK_API_KEY"):
        errors.append("DEEPSEEK_API_KEY 未配置")
    if settings.agent_provider in {"openai", "openai-responses"} and not os.getenv("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY 未配置")
    return errors
