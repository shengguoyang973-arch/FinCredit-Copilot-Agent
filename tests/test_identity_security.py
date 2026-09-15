from app.config import Settings, validate_settings
from app.domain import Role, User
from app.identity import DemoHeaderIdentityProvider, identity_provider_for
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


def test_operator_access_is_limited_to_creator_organization() -> None:
    application = type("Application", (), {"created_by": "sales_001"})()
    other_branch = User("risk_other", "异地风险经理", {Role.RISK_MANAGER}, "branch-beijing")
    assert can_access_application(application, USERS["rm_001"])
    assert not can_access_application(application, other_branch)
