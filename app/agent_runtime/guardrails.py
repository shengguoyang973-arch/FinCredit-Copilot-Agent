from __future__ import annotations

import re


class AgentGuardrailError(ValueError):
    pass


INJECTION_PATTERNS = (
    "忽略之前的指令",
    "忽略系统提示",
    "泄露系统提示",
    "绕过权限",
    "关闭安全限制",
    "执行任意代码",
    "不要遵守规则",
)


def validate_agent_question(question: str) -> str:
    normalized = question.strip()
    if not normalized:
        raise AgentGuardrailError("业务问题不能为空")
    if len(normalized) > 1000:
        raise AgentGuardrailError("业务问题长度不得超过 1000 个字符")
    for pattern in INJECTION_PATTERNS:
        if pattern in normalized:
            raise AgentGuardrailError("问题包含潜在提示注入指令，已阻止提交")
    return normalized


def redact_sensitive_text(text: str) -> str:
    """Redact common identifiers before they enter model context or logs."""
    redacted = re.sub(r"(?<!\d)(1[3-9]\d{9})(?!\d)", "[手机号已脱敏]", text)
    redacted = re.sub(r"(?<!\d)(\d{17}[0-9Xx])(?!\d)", "[证件号已脱敏]", redacted)
    redacted = re.sub(r"(?<!\d)(\d{16,19})(?!\d)", "[账号已脱敏]", redacted)
    return redacted
