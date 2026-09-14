from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app import agent_provider
from app.agent_output import LangChainAnswerResponse
from app.agent_provider import AgentContext, OpenAIResponsesAgentProvider


def context() -> AgentContext:
    return AgentContext(
        "APP001",
        "测试企业",
        1_000_000,
        2_000_000,
        "建议进入人工审批",
        [{"rule_id": "POL-2.1", "severity": "info", "message": "额度在范围内。"}],
        [{"id": "POL-2.1", "title": "额度", "content": "额度政策", "version": "v1"}],
        True,
        [],
        [],
        {"retriever": "langchain-hybrid-policy-v1"},
    )


def test_langchain_provider_falls_back_without_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    output = OpenAIResponsesAgentProvider().answer_question(context(), "下一步如何处理？")
    assert output["provider"] == "openai-responses"
    assert output["runtime"] == "langchain"
    assert output["fallback"] is True
    assert "OPENAI_API_KEY" in output["fallback_reason"]


def test_langchain_provider_uses_structured_runnable(monkeypatch) -> None:
    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            assert kwargs["use_responses_api"] is True

        def with_structured_output(self, schema, **kwargs):
            assert schema is LangChainAnswerResponse
            assert kwargs["method"] == "json_schema"
            return RunnableLambda(lambda _: {
                "parsed": LangChainAnswerResponse(
                    answer="当前额度在政策范围内，仍须人工复核。",
                    supporting_evidence_ids=["POL-2.1"],
                    follow_up_actions=["核对原始材料。"],
                    governance_note="不替代人工审批。",
                ),
                "raw": AIMessage(content="", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}),
                "parsing_error": None,
            })

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(agent_provider, "ChatOpenAI", FakeChatOpenAI)
    output = OpenAIResponsesAgentProvider().answer_question(context(), "额度是否合规？")
    assert output["fallback"] is False
    assert output["runtime"] == "langchain"
    assert output["usage"]["total_tokens"] == 15
