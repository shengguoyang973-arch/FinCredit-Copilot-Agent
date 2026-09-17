from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWKClient

from app.config import Settings, validate_settings
from app.domain import Role, User
from app.identity import DemoHeaderIdentityProvider, OIDCIdentityProvider, identity_provider_for
from app.repository import USERS
from app.security import can_access_application, filter_customer_fields


def test_demo_identity_provider_returns_claimed_user() -> None:
    user = DemoHeaderIdentityProvider().authenticate(user_id="sales_001")
    assert user.organization_id == "branch-shanghai"
    assert Role.ACCOUNT_MANAGER in user.roles


def test_abac_limits_sales_to_owned_application() -> None:
    user = USERS["sales_001"]
    owned = type("Application", (), {"created_by": "sales_001"})()
    other = type("Application", (), {"created_by": "someone_else"})()
    assert can_access_application(owned, user)
    assert not can_access_application(other, user)


def test_field_level_policy_hides_overdue_from_sales() -> None:
    customer = {"name": "测试企业", "overdue_days_12m": 0}
    filtered = filter_customer_fields(customer, USERS["sales_001"])
    assert filtered == {"name": "测试企业"}


def test_unknown_identity_provider_is_not_downgraded_to_demo() -> None:
    try:
        identity_provider_for("typo-provider")
    except RuntimeError as error:
        assert "未配置的身份提供方" in str(error)
    else:
        raise AssertionError("未知身份提供方不应被接受")


def test_production_configuration_rejects_demo_identity() -> None:
    errors = validate_settings(Settings(deployment_environment="production", identity_provider="demo-header"))
    assert "生产环境禁止使用 demo-header 身份提供方" in errors
    with pytest.raises(RuntimeError, match="生产环境禁止"):
        identity_provider_for("demo-header", Settings(deployment_environment="production"))


def test_production_configuration_requires_postgres_platform_and_webhook_delivery() -> None:
    errors = validate_settings(oidc_settings(deployment_environment="production"))
    assert "生产环境必须使用 postgres 数据中台后端" in errors
    assert "生产环境必须启用 webhook 事件投递" in errors


def test_operator_access_is_limited_to_creator_organization() -> None:
    application = type("Application", (), {"created_by": "sales_001"})()
    other_branch = User("risk_other", "异地风险经理", {Role.RISK_MANAGER}, "branch-beijing")
    assert can_access_application(application, USERS["rm_001"])
    assert not can_access_application(application, other_branch)


def oidc_settings(**overrides) -> Settings:
    values = {
        "identity_provider": "oidc",
        "oidc_jwks_url": "https://id.example.test/.well-known/jwks.json",
        "oidc_issuer": "https://id.example.test/",
        "oidc_audience": "fincredit-api",
    }
    values.update(overrides)
    return Settings(**values)


def signed_token(private_key, **overrides) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "enterprise-risk-1", "name": "企业风险经理",
        "roles": ["risk_manager"], "organization_id": "branch-shanghai",
        "iss": "https://id.example.test/", "aud": "fincredit-api",
        "iat": now, "exp": now + timedelta(minutes=5),
    }
    payload.update(overrides)
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "enterprise-key-1"})


def test_oidc_provider_resolves_kid_from_jwks_and_maps_verified_claims(monkeypatch) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk.update({"kid": "enterprise-key-1", "use": "sig", "alg": "RS256"})
    client = PyJWKClient("https://id.example.test/.well-known/jwks.json")
    monkeypatch.setattr(client, "fetch_data", lambda: {"keys": [jwk]})
    user = OIDCIdentityProvider(oidc_settings(), client).authenticate(signed_token(private_key))
    assert user.id == "enterprise-risk-1"
    assert user.organization_id == "branch-shanghai"
    assert user.roles == {Role.RISK_MANAGER}


def test_oidc_provider_rejects_wrong_audience_and_missing_business_role() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key()))
    provider = OIDCIdentityProvider(oidc_settings(), client)
    with pytest.raises(LookupError, match="验签或声明校验失败"):
        provider.authenticate(signed_token(private_key, aud="other-api"))
    with pytest.raises(LookupError, match="业务角色"):
        provider.authenticate(signed_token(private_key, roles=["unmapped_role"]))


def test_oidc_configuration_rejects_symmetric_algorithm() -> None:
    errors = validate_settings(oidc_settings(oidc_algorithms=("HS256",)))
    assert "FINCREDIT_OIDC_ALGORITHMS 只允许受信任的非对称签名算法" in errors
    with pytest.raises(RuntimeError, match="非对称签名算法"):
        OIDCIdentityProvider(oidc_settings(oidc_algorithms=("HS256",))).authenticate("invalid")


def test_oidc_enterprise_group_can_map_to_business_role() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key()))
    settings = oidc_settings(oidc_role_mappings=(("credit-risk-group", "risk_manager"),))
    user = OIDCIdentityProvider(settings, client).authenticate(
        signed_token(private_key, roles=["credit-risk-group"])
    )
    assert user.roles == {Role.RISK_MANAGER}
