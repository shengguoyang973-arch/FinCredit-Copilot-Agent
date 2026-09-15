from fastapi import Header, HTTPException, status

from app.config import get_settings
from app.domain import Role, User
from app.identity import identity_provider_for
from app.repository import USERS


def current_user(x_user_id: str | None = Header(None, alias="X-User-Id"), authorization: str | None = Header(None)) -> User:
    settings = get_settings()
    try:
        provider = identity_provider_for(settings.identity_provider)
        if settings.identity_provider == "oidc":
            if not authorization:
                raise LookupError("缺少 Authorization Bearer Token")
            if not authorization.startswith("Bearer ") or not authorization.removeprefix("Bearer ").strip():
                raise LookupError("Authorization 必须使用 Bearer Token")
        token = authorization.removeprefix("Bearer ").strip() if authorization else None
        return provider.authenticate(token=token, user_id=x_user_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


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
    if not user.roles.intersection({Role.RISK_MANAGER, Role.APPROVER}):
        return False
    creator = USERS.get(application.created_by)
    if not creator:
        return False
    return creator.organization_id == user.organization_id


def filter_customer_fields(customer: dict | None, user: User) -> dict | None:
    if customer is None:
        return None
    result = dict(customer)
    if Role.ACCOUNT_MANAGER in user.roles and Role.COMPLIANCE_ADMIN not in user.roles:
        result.pop("overdue_days_12m", None)
    return result
