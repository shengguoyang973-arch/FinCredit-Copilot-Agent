from app.domain import Role
from app.identity import DemoHeaderIdentityProvider
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
