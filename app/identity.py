from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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
    """Production seam; wire this to the enterprise JWKS verifier."""

    name = "oidc"

    def authenticate(self, token: str | None = None, user_id: str | None = None) -> User:
        del token, user_id
        raise RuntimeError("OIDC Provider 尚未配置企业 JWKS 验签器")


def claims_to_user(claims: IdentityClaims) -> User:
    return User(claims.subject, claims.name, set(claims.roles), claims.organization_id, dict(claims.attributes))


def identity_provider_for(name: str) -> IdentityProvider:
    """Resolve only explicitly supported providers; unknown values fail closed."""
    if name == DemoHeaderIdentityProvider.name:
        return DemoHeaderIdentityProvider()
    if name == OIDCIdentityProvider.name:
        return OIDCIdentityProvider()
    raise RuntimeError(f"未配置的身份提供方：{name}")
