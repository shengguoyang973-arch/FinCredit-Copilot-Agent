import pytest
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from app.knowledge_store import list_policies
from app.rag import RAGConfig, build_policy_retriever, retrieve_policy_context
from app.rag.tuning import RAGEvaluationCase, evaluate_rag, tune_rag


def test_policy_retriever_uses_langchain_contract() -> None:
    retriever = build_policy_retriever(list_policies(), RAGConfig(top_k=3))
    assert isinstance(retriever, BaseRetriever)
    documents = retriever.invoke("流动资金贷款额度和营业收入比例")
    assert documents
    assert isinstance(documents[0], Document)
    assert documents[0].metadata["policy_id"] == "POL-2.1"
    assert 0 <= documents[0].metadata["relevance_score"] <= 1


def test_rule_evidence_is_attached_to_rag_trace() -> None:
    result = retrieve_policy_context(
        "流动资金贷款额度和营业收入比例",
        list_policies(),
        config=RAGConfig(top_k=1, min_vector_score=1.0),
        required_policy_ids={"POL-3.4"},
    )
    assert "POL-3.4" in [hit.policy.id for hit in result.hits]
    trace = result.trace()
    assert trace["retriever"] == "langchain-hybrid-policy-v1"
    assert any(hit["policy_id"] == "POL-3.4" and hit["forced_match"] for hit in trace["hits"])


def test_rag_tuning_selects_a_measured_configuration() -> None:
    cases = [RAGEvaluationCase("limit", "营业收入比例和贷款额度", ("POL-2.1",))]
    current = evaluate_rag(list_policies(), cases, RAGConfig(top_k=1))
    tuning = tune_rag(list_policies(), cases)
    assert current["hit_rate"] == 1.0
    assert tuning["candidate_count"] == 36
    assert tuning["best"]["score"] >= current["score"]


def test_rag_config_rejects_invalid_weights() -> None:
    with pytest.raises(ValueError, match="权重之和"):
        RAGConfig(lexical_weight=0, vector_weight=0)
