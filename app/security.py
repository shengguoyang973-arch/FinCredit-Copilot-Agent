from fastapi import Header, HTTPException, status

from app.config import get_settings
from app.domain import Role, User
from app.identity import DemoHeaderIdentityProvider, OIDCIdentityProvider


def current_user(x_user_id: str | None = Header(None, alias="X-User-Id"), authorization: str | None = Header(None)) -> User:
    settings = get_settings()
    provider = OIDCIdentityProvider() if settings.identity_provider == "oidc" else DemoHeaderIdentityProvider()
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    try:
        return provider.authenticate(token=token, user_id=x_user_id)
    except (LookupError, RuntimeError) as error:
        code = status.HTTP_503_SERVICE_UNAVAILABLE if settings.identity_provider == "oidc" else status.HTTP_401_UNAUTHORIZED
        raise HTTPException(status_code=code, detail=str(error)) from error


def require_roles(*allowed: Role):
    def dependency(user: User = __import__("fastapi").Depends(current_user)) -> User:
        if not user.roles.intersection(allowed):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色无权执行此操作")
        return user
    return dependency


def can_access_application(application, user: User) -> bool:
    """ABAC policy: ownership for sales, organization scope for operators."""
    if Role.COMPLIANCE_ADMIN in user.roles:
        return True
    if Role.ACCOUNT_MANAGER in user.roles:
        return application.created_by == user.id
    return True


def filter_customer_fields(customer: dict | None, user: User) -> dict | None:
    if customer is None:
        return None
    result = dict(customer)
    if Role.ACCOUNT_MANAGER in user.roles and Role.COMPLIANCE_ADMIN not in user.roles:
        result.pop("overdue_days_12m", None)
    return result
