from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.config import Settings, get_settings
from app.domain import Role, User
from app.repository import USERS


@dataclass(frozen=True)
class IdentityClaims:
    subject: str
    name: str
    roles: frozenset[Role]
    organization_id: str
    attributes: dict[str, str]


class IdentityProvider(Protocol):
    name: str

    def authenticate(self, token: str | None = None, user_id: str | None = None) -> User:
        ...


class DemoHeaderIdentityProvider:
    name = "demo-header"

    def authenticate(self, token: str | None = None, user_id: str | None = None) -> User:
        del token
        user = USERS.get(user_id or "")
        if not user:
            raise LookupError("未知演示用户")
        return user


class OIDCIdentityProvider:
    """Verify enterprise JWTs against a configured JWKS, issuer and audience."""

    name = "oidc"
    allowed_algorithms = {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"}

    def __init__(self, settings: Settings | None = None, jwks_client: Any | None = None) -> None:
        self.settings = settings or get_settings()
        self._jwks_client = jwks_client

    def _client(self):
        if self._jwks_client is None:
            from jwt import PyJWKClient

            self._jwks_client = PyJWKClient(self.settings.oidc_jwks_url, cache_jwk_set=True, cache_keys=True)
        return self._jwks_client

    def authenticate(self, token: str | None = None, user_id: str | None = None) -> User:
        del user_id
        if not token:
            raise LookupError("缺少 OIDC Token")
        if not self.settings.oidc_jwks_url or not self.settings.oidc_issuer or not self.settings.oidc_audience:
            raise RuntimeError("OIDC JWKS、Issuer 或 Audience 未完整配置")
        if not self.settings.oidc_algorithms or not set(self.settings.oidc_algorithms).issubset(self.allowed_algorithms):
            raise RuntimeError("OIDC 仅允许显式配置的非对称签名算法")
        try:
            import jwt
            from jwt.exceptions import PyJWKClientConnectionError, PyJWTError

            signing_key = self._client().get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self.settings.oidc_algorithms),
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer,
                leeway=self.settings.oidc_leeway_seconds,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
        except PyJWKClientConnectionError as error:
            raise RuntimeError("企业 OIDC JWKS 端点不可用") from error
        except PyJWTError as error:
            raise LookupError("OIDC Token 验签或声明校验失败") from error

        raw_roles = _claim_value(payload, self.settings.oidc_roles_claim)
        if isinstance(raw_roles, str):
            role_values = {item.strip() for item in raw_roles.replace(",", " ").split() if item.strip()}
        elif isinstance(raw_roles, (list, tuple, set)):
            role_values = {str(item) for item in raw_roles}
        else:
            role_values = set()
        role_mappings = dict(self.settings.oidc_role_mappings)
        mapped_role_values = {role_mappings.get(value, value) for value in role_values}
        roles = frozenset(role for role in Role if role.value in mapped_role_values)
        if not roles:
            raise LookupError("OIDC Token 未包含受支持的业务角色")
        organization_id = _claim_value(payload, self.settings.oidc_org_claim)
        if not isinstance(organization_id, str) or not organization_id.strip():
            raise LookupError("OIDC Token 缺少组织声明")
        name = _claim_value(payload, self.settings.oidc_name_claim)
        subject = str(payload["sub"])
        attributes = {
            key: str(payload[key]) for key in ("region", "department", "tenant_id")
            if key in payload and isinstance(payload[key], (str, int, float, bool))
        }
        return claims_to_user(IdentityClaims(
            subject=subject,
            name=str(name or payload.get("preferred_username") or subject),
            roles=roles,
            organization_id=organization_id.strip(),
            attributes=attributes,
        ))


def claims_to_user(claims: IdentityClaims) -> User:
    return User(claims.subject, claims.name, set(claims.roles), claims.organization_id, dict(claims.attributes))


def _claim_value(payload: dict, claim_name: str) -> Any:
    if claim_name in payload:
        return payload[claim_name]
    value: Any = payload
    for component in claim_name.split("."):
        if not isinstance(value, dict) or component not in value:
            return None
        value = value[component]
    return value


def identity_provider_for(name: str, settings: Settings | None = None) -> IdentityProvider:
    """Resolve only explicitly supported providers; unknown values fail closed."""
    if name == DemoHeaderIdentityProvider.name:
        if settings and settings.deployment_environment == "production":
            raise RuntimeError("生产环境禁止使用 demo-header 身份提供方")
        return DemoHeaderIdentityProvider()
    if name == OIDCIdentityProvider.name:
        return OIDCIdentityProvider(settings)
    raise RuntimeError(f"未配置的身份提供方：{name}")
