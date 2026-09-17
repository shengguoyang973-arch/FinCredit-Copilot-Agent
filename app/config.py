from __future__ import annotations

import os
import json
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Settings:
    app_name: str = "FinCredit Copilot"
    app_version: str = "1.3.0"
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
    data_platform_backend: str = "sqlite"
    data_platform_postgres_dsn: str = ""
    data_platform_postgres_schema: str = "fincredit_data"
    online_evaluation_window_runs: int = 50
    drift_min_samples: int = 10
    prompt_outcome_min_samples: int = 10
    drift_max_fallback_rate: float = 0.2
    drift_max_p95_latency_ms: float = 5_000.0
    drift_min_evidence_coverage: float = 0.9
    drift_min_plan_adherence: float = 0.95
    agent_context_max_chars: int = 12_000
    canonical_data_max_age_hours: float = 168.0
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
    integration_delivery_mode: str = "disabled"
    siem_webhook_url: str = ""
    work_item_webhook_url: str = ""
    integration_hmac_secret: str = ""
    integration_timeout_seconds: float = 5.0
    integration_max_attempts: int = 5
    evaluation_dataset_path: Path = Path(__file__).resolve().parent.parent / "demo_data" / "deidentified_agent_evaluation.json"
    canary_min_accuracy: float = 0.9
    canary_min_evidence_recall: float = 0.9
    canary_max_boundary_violation_rate: float = 0.0
    canary_max_traffic_percent: int = 20
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
        data_platform_backend=os.getenv("FINCREDIT_DATA_PLATFORM_BACKEND", Settings.data_platform_backend).strip().lower(),
        data_platform_postgres_dsn=os.getenv("FINCREDIT_DATA_PLATFORM_POSTGRES_DSN", Settings.data_platform_postgres_dsn).strip(),
        data_platform_postgres_schema=os.getenv("FINCREDIT_DATA_PLATFORM_POSTGRES_SCHEMA", Settings.data_platform_postgres_schema).strip(),
        online_evaluation_window_runs=int(os.getenv(
            "FINCREDIT_ONLINE_EVALUATION_WINDOW_RUNS", str(Settings.online_evaluation_window_runs)
        )),
        drift_min_samples=int(os.getenv("FINCREDIT_DRIFT_MIN_SAMPLES", str(Settings.drift_min_samples))),
        prompt_outcome_min_samples=int(os.getenv(
            "FINCREDIT_PROMPT_OUTCOME_MIN_SAMPLES", str(Settings.prompt_outcome_min_samples)
        )),
        drift_max_fallback_rate=float(os.getenv(
            "FINCREDIT_DRIFT_MAX_FALLBACK_RATE", str(Settings.drift_max_fallback_rate)
        )),
        drift_max_p95_latency_ms=float(os.getenv(
            "FINCREDIT_DRIFT_MAX_P95_LATENCY_MS", str(Settings.drift_max_p95_latency_ms)
        )),
        drift_min_evidence_coverage=float(os.getenv(
            "FINCREDIT_DRIFT_MIN_EVIDENCE_COVERAGE", str(Settings.drift_min_evidence_coverage)
        )),
        drift_min_plan_adherence=float(os.getenv(
            "FINCREDIT_DRIFT_MIN_PLAN_ADHERENCE", str(Settings.drift_min_plan_adherence)
        )),
        agent_context_max_chars=int(os.getenv(
            "FINCREDIT_AGENT_CONTEXT_MAX_CHARS", str(Settings.agent_context_max_chars)
        )),
        canonical_data_max_age_hours=float(os.getenv(
            "FINCREDIT_CANONICAL_DATA_MAX_AGE_HOURS", str(Settings.canonical_data_max_age_hours)
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
        integration_delivery_mode=os.getenv("FINCREDIT_INTEGRATION_DELIVERY_MODE", Settings.integration_delivery_mode).strip().lower(),
        siem_webhook_url=os.getenv("FINCREDIT_SIEM_WEBHOOK_URL", Settings.siem_webhook_url).strip(),
        work_item_webhook_url=os.getenv("FINCREDIT_WORK_ITEM_WEBHOOK_URL", Settings.work_item_webhook_url).strip(),
        integration_hmac_secret=os.getenv("FINCREDIT_INTEGRATION_HMAC_SECRET", Settings.integration_hmac_secret),
        integration_timeout_seconds=float(os.getenv(
            "FINCREDIT_INTEGRATION_TIMEOUT_SECONDS", str(Settings.integration_timeout_seconds)
        )),
        integration_max_attempts=int(os.getenv(
            "FINCREDIT_INTEGRATION_MAX_ATTEMPTS", str(Settings.integration_max_attempts)
        )),
        evaluation_dataset_path=Path(os.getenv("FINCREDIT_EVALUATION_DATASET_PATH", str(Settings.evaluation_dataset_path))),
        canary_min_accuracy=float(os.getenv("FINCREDIT_CANARY_MIN_ACCURACY", str(Settings.canary_min_accuracy))),
        canary_min_evidence_recall=float(os.getenv(
            "FINCREDIT_CANARY_MIN_EVIDENCE_RECALL", str(Settings.canary_min_evidence_recall)
        )),
        canary_max_boundary_violation_rate=float(os.getenv(
            "FINCREDIT_CANARY_MAX_BOUNDARY_VIOLATION_RATE", str(Settings.canary_max_boundary_violation_rate)
        )),
        canary_max_traffic_percent=int(os.getenv(
            "FINCREDIT_CANARY_MAX_TRAFFIC_PERCENT", str(Settings.canary_max_traffic_percent)
        )),
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
    if settings.data_platform_backend not in {"sqlite", "postgres"}:
        errors.append("FINCREDIT_DATA_PLATFORM_BACKEND 必须是 sqlite 或 postgres")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", settings.data_platform_postgres_schema):
        errors.append("FINCREDIT_DATA_PLATFORM_POSTGRES_SCHEMA 必须是安全的 PostgreSQL schema 标识")
    if settings.data_platform_postgres_dsn and not settings.data_platform_postgres_dsn.startswith(("postgresql://", "postgres://")):
        errors.append("FINCREDIT_DATA_PLATFORM_POSTGRES_DSN 必须是 PostgreSQL psycopg 连接串")
    if settings.data_platform_backend == "postgres" and not settings.data_platform_postgres_dsn:
        errors.append("FINCREDIT_DATA_PLATFORM_POSTGRES_DSN 未配置")
    if settings.deployment_environment == "production" and settings.data_platform_backend != "postgres":
        errors.append("生产环境必须使用 postgres 数据中台后端")
    if not 1 <= settings.online_evaluation_window_runs <= 10_000:
        errors.append("FINCREDIT_ONLINE_EVALUATION_WINDOW_RUNS 必须在 1 到 10000 之间")
    if not 1 <= settings.drift_min_samples <= settings.online_evaluation_window_runs:
        errors.append("FINCREDIT_DRIFT_MIN_SAMPLES 必须在 1 到在线评估窗口大小之间")
    if not 1 <= settings.prompt_outcome_min_samples <= settings.online_evaluation_window_runs:
        errors.append("FINCREDIT_PROMPT_OUTCOME_MIN_SAMPLES 必须在 1 到在线评估窗口大小之间")
    if not 0 <= settings.drift_max_fallback_rate <= 1:
        errors.append("FINCREDIT_DRIFT_MAX_FALLBACK_RATE 必须在 0 到 1 之间")
    if settings.drift_max_p95_latency_ms <= 0:
        errors.append("FINCREDIT_DRIFT_MAX_P95_LATENCY_MS 必须大于 0")
    if not 0 <= settings.drift_min_evidence_coverage <= 1:
        errors.append("FINCREDIT_DRIFT_MIN_EVIDENCE_COVERAGE 必须在 0 到 1 之间")
    if not 0 <= settings.drift_min_plan_adherence <= 1:
        errors.append("FINCREDIT_DRIFT_MIN_PLAN_ADHERENCE 必须在 0 到 1 之间")
    if not 2_000 <= settings.agent_context_max_chars <= 100_000:
        errors.append("FINCREDIT_AGENT_CONTEXT_MAX_CHARS 必须在 2000 到 100000 之间")
    if settings.canonical_data_max_age_hours < 0:
        errors.append("FINCREDIT_CANONICAL_DATA_MAX_AGE_HOURS 不能小于 0")
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
    if settings.integration_delivery_mode not in {"disabled", "webhook"}:
        errors.append("FINCREDIT_INTEGRATION_DELIVERY_MODE 必须是 disabled 或 webhook")
    if settings.integration_delivery_mode == "webhook":
        required_integrations = {
            "FINCREDIT_SIEM_WEBHOOK_URL": settings.siem_webhook_url,
            "FINCREDIT_WORK_ITEM_WEBHOOK_URL": settings.work_item_webhook_url,
        }
        errors.extend(f"{name} 未配置" for name, value in required_integrations.items() if not value)
        if settings.deployment_environment == "production":
            if not all(url.startswith("https://") for url in required_integrations.values()):
                errors.append("生产 SIEM 与工单 Webhook 必须使用 HTTPS")
            if len(settings.integration_hmac_secret) < 32:
                errors.append("生产 Webhook 必须配置至少 32 字符的 FINCREDIT_INTEGRATION_HMAC_SECRET")
    if settings.deployment_environment == "production" and settings.integration_delivery_mode != "webhook":
        errors.append("生产环境必须启用 webhook 事件投递")
    if not 0.1 <= settings.integration_timeout_seconds <= 60:
        errors.append("FINCREDIT_INTEGRATION_TIMEOUT_SECONDS 必须在 0.1 到 60 之间")
    if not 1 <= settings.integration_max_attempts <= 20:
        errors.append("FINCREDIT_INTEGRATION_MAX_ATTEMPTS 必须在 1 到 20 之间")
    if not settings.evaluation_dataset_path.is_file():
        errors.append("FINCREDIT_EVALUATION_DATASET_PATH 不存在或不是文件")
    if not 0 <= settings.canary_min_accuracy <= 1:
        errors.append("FINCREDIT_CANARY_MIN_ACCURACY 必须在 0 到 1 之间")
    if not 0 <= settings.canary_min_evidence_recall <= 1:
        errors.append("FINCREDIT_CANARY_MIN_EVIDENCE_RECALL 必须在 0 到 1 之间")
    if not 0 <= settings.canary_max_boundary_violation_rate <= 1:
        errors.append("FINCREDIT_CANARY_MAX_BOUNDARY_VIOLATION_RATE 必须在 0 到 1 之间")
    if not 1 <= settings.canary_max_traffic_percent <= 100:
        errors.append("FINCREDIT_CANARY_MAX_TRAFFIC_PERCENT 必须在 1 到 100 之间")
    return errors
