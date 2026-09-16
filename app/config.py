from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Settings:
    app_name: str = "FinCredit Copilot"
    app_version: str = "0.6.0"
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
    data_platform_max_batch_records: int = 500
    rag_top_k: int = 3
    rag_lexical_weight: float = 0.85
    rag_vector_weight: float = 0.15
    rag_min_vector_score: float = 0.0
    rag_chunk_size: int = 180
    embedding_provider: str = "hash-local"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 256
    vector_store_backend: str = "memory"
    pgvector_connection: str = ""
    pgvector_collection: str = "fincredit_policy_chunks"
    policy_timezone: str = "Asia/Shanghai"
    oidc_jwks_url: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    oidc_roles_claim: str = "roles"
    oidc_org_claim: str = "organization_id"
    oidc_name_claim: str = "name"
    oidc_role_mappings: tuple[tuple[str, str], ...] = ()
    oidc_leeway_seconds: int = 30
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
        data_platform_max_batch_records=int(os.getenv(
            "FINCREDIT_DATA_PLATFORM_MAX_BATCH_RECORDS", str(Settings.data_platform_max_batch_records)
        )),
        rag_top_k=int(os.getenv("FINCREDIT_RAG_TOP_K", str(Settings.rag_top_k))),
        rag_lexical_weight=float(os.getenv("FINCREDIT_RAG_LEXICAL_WEIGHT", str(Settings.rag_lexical_weight))),
        rag_vector_weight=float(os.getenv("FINCREDIT_RAG_VECTOR_WEIGHT", str(Settings.rag_vector_weight))),
        rag_min_vector_score=float(os.getenv("FINCREDIT_RAG_MIN_VECTOR_SCORE", str(Settings.rag_min_vector_score))),
        rag_chunk_size=int(os.getenv("FINCREDIT_RAG_CHUNK_SIZE", str(Settings.rag_chunk_size))),
        embedding_provider=os.getenv("FINCREDIT_EMBEDDING_PROVIDER", Settings.embedding_provider).strip().lower(),
        embedding_model=os.getenv("FINCREDIT_EMBEDDING_MODEL", Settings.embedding_model).strip(),
        embedding_dimensions=int(os.getenv("FINCREDIT_EMBEDDING_DIMENSIONS", str(Settings.embedding_dimensions))),
        vector_store_backend=os.getenv("FINCREDIT_VECTOR_STORE_BACKEND", Settings.vector_store_backend).strip().lower(),
        pgvector_connection=os.getenv("FINCREDIT_PGVECTOR_CONNECTION", Settings.pgvector_connection).strip(),
        pgvector_collection=os.getenv("FINCREDIT_PGVECTOR_COLLECTION", Settings.pgvector_collection).strip(),
        policy_timezone=os.getenv("FINCREDIT_POLICY_TIMEZONE", Settings.policy_timezone).strip(),
        oidc_jwks_url=os.getenv("FINCREDIT_OIDC_JWKS_URL", Settings.oidc_jwks_url).strip(),
        oidc_issuer=os.getenv("FINCREDIT_OIDC_ISSUER", Settings.oidc_issuer).strip(),
        oidc_audience=os.getenv("FINCREDIT_OIDC_AUDIENCE", Settings.oidc_audience).strip(),
        oidc_algorithms=tuple(filter(None, (
            item.strip().upper()
            for item in os.getenv("FINCREDIT_OIDC_ALGORITHMS", ",".join(Settings.oidc_algorithms)).split(",")
        ))),
        oidc_roles_claim=os.getenv("FINCREDIT_OIDC_ROLES_CLAIM", Settings.oidc_roles_claim).strip(),
        oidc_org_claim=os.getenv("FINCREDIT_OIDC_ORG_CLAIM", Settings.oidc_org_claim).strip(),
        oidc_name_claim=os.getenv("FINCREDIT_OIDC_NAME_CLAIM", Settings.oidc_name_claim).strip(),
        oidc_role_mappings=tuple(sorted(
            (str(source), str(target)) for source, target in json.loads(
                os.getenv("FINCREDIT_OIDC_ROLE_MAPPINGS", "{}")
            ).items()
        )),
        oidc_leeway_seconds=int(os.getenv("FINCREDIT_OIDC_LEEWAY_SECONDS", str(Settings.oidc_leeway_seconds))),
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
    if settings.embedding_provider not in {"hash-local", "openai"}:
        errors.append("FINCREDIT_EMBEDDING_PROVIDER 必须是 hash-local 或 openai")
    if settings.vector_store_backend not in {"memory", "pgvector"}:
        errors.append("FINCREDIT_VECTOR_STORE_BACKEND 必须是 memory 或 pgvector")
    if settings.embedding_dimensions <= 0:
        errors.append("FINCREDIT_EMBEDDING_DIMENSIONS 必须大于 0")
    if settings.embedding_provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY 未配置，无法使用 OpenAI Embedding")
    if settings.vector_store_backend == "pgvector" and not settings.pgvector_connection:
        errors.append("FINCREDIT_PGVECTOR_CONNECTION 未配置")
    try:
        ZoneInfo(settings.policy_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        errors.append("FINCREDIT_POLICY_TIMEZONE 不是有效的 IANA 时区")
    if settings.identity_provider == "oidc":
        required_oidc = {
            "FINCREDIT_OIDC_JWKS_URL": settings.oidc_jwks_url,
            "FINCREDIT_OIDC_ISSUER": settings.oidc_issuer,
            "FINCREDIT_OIDC_AUDIENCE": settings.oidc_audience,
        }
        errors.extend(f"{name} 未配置" for name, value in required_oidc.items() if not value)
        asymmetric_algorithms = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}
        if not settings.oidc_algorithms or not set(settings.oidc_algorithms).issubset(asymmetric_algorithms):
            errors.append("FINCREDIT_OIDC_ALGORITHMS 只允许受信任的非对称签名算法")
        if settings.oidc_leeway_seconds < 0:
            errors.append("FINCREDIT_OIDC_LEEWAY_SECONDS 不能小于 0")
        supported_roles = {"account_manager", "risk_manager", "approver", "compliance_admin"}
        if any(not source or target not in supported_roles for source, target in settings.oidc_role_mappings):
            errors.append("FINCREDIT_OIDC_ROLE_MAPPINGS 包含无效业务角色映射")
        if settings.deployment_environment == "production" and (
            not settings.oidc_jwks_url.startswith("https://") or not settings.oidc_issuer.startswith("https://")
        ):
            errors.append("生产 OIDC JWKS URL 与 Issuer 必须使用 HTTPS")
    if settings.deployment_environment == "production" and settings.embedding_provider != "openai":
        errors.append("生产环境必须使用 openai Embedding Provider")
    if settings.deployment_environment == "production" and settings.vector_store_backend != "pgvector":
        errors.append("生产环境必须使用 pgvector 向量数据库")
    if settings.openai_timeout_seconds <= 0:
        errors.append("OPENAI_TIMEOUT_SECONDS 必须大于 0")
    if settings.agent_max_retries < 0:
        errors.append("FINCREDIT_AGENT_MAX_RETRIES 不能小于 0")
    if settings.max_document_bytes <= 0:
        errors.append("FINCREDIT_MAX_DOCUMENT_BYTES 必须大于 0")
    if not 1 <= settings.data_platform_max_batch_records <= 10_000:
        errors.append("FINCREDIT_DATA_PLATFORM_MAX_BATCH_RECORDS 必须在 1 到 10000 之间")
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
