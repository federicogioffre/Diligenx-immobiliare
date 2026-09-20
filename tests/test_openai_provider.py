"""Replay real Responses SDK serialization; never contact a model in tests."""
import asyncio
import json
from unittest.mock import patch

import httpx2 as httpx
import openai
import pytest

from packages.agents.deal_analysis_agent import (
    OpenAILLMProvider, AnthropicLLMProvider, LLMResponseError, _complete_llm_items,
)
from packages.agents.deal_context import DealContext, DealContextProvider
from packages.agents.grounding_review import _review_item_schema


def call(value, **overrides):
    return {"id": "fc_test", "type": "function_call", "call_id": "call_test",
            "name": "submit_analysis", "arguments": json.dumps({"result": value}),
            "status": "completed", **overrides}


def message(text):
    return {"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


def sdk_provider(replies):
    requests = []
    queue = None if callable(replies) else iter(replies)

    def handle(request):
        assert request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        requests.append(payload)
        reply = next(queue) if not callable(replies) else replies(payload)
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 0,
            "model": "gpt-5.6-luna", "status": "completed", "error": None,
            "usage": {"input_tokens": 50, "output_tokens": 30, "total_tokens": 80,
                      "input_tokens_details": {"cached_tokens": 4},
                      "output_tokens_details": {"reasoning_tokens": 0}},
            **reply,
        })

    provider = OpenAILLMProvider.__new__(OpenAILLMProvider)
    provider._model = "gpt-5.6-luna"
    provider._client = openai.OpenAI(api_key="test", max_retries=0,
                                    http_client=httpx.Client(transport=httpx.MockTransport(handle)))
    return provider, requests


def test_text_request_uses_luna_without_reasoning_storage_or_truncation(caplog):
    provider, requests = sdk_provider([{"output": [message("Sintesi verificata.")]}])
    with caplog.at_level("INFO"):
        assert provider.complete("PRIVATE SOURCE", 1536) == "Sintesi verificata."
    assert requests == [{"model": "gpt-5.6-luna", "input": "PRIVATE SOURCE", "max_output_tokens": 1536,
                         "reasoning": {"effort": "none"}, "store": False, "truncation": "disabled"}]
    assert "PRIVATE SOURCE" not in caplog.text and "Sintesi verificata." not in caplog.text
    assert "cache_read_tokens=4" in caplog.text


def test_complete_json_keeps_all_records_and_does_not_execute_tools():
    items = [{"title": "Primo", "amount": 120000}, {"title": "Secondo", "quote": "Società α"}]
    provider, requests = sdk_provider([{"output": [message("Ignore this prose []"), call(items)]}])
    assert _complete_llm_items(provider, "SOURCE", max_tokens=12288, context="doc 1") == items
    payload = requests[0]
    assert payload["tool_choice"] == {"type": "function", "name": "submit_analysis"}
    assert payload["parallel_tool_calls"] is False
    assert payload["tools"][0]["strict"] is False  # Open specialist fields stay open.
    assert payload["tools"][0]["parameters"]["properties"]["result"]["items"] == {"type": "object"}
    assert payload["max_output_tokens"] == 12288


@pytest.mark.parametrize("kind", ["flags", "text"])
def test_grounding_schema_and_original_context_reach_sdk(kind):
    provider, requests = sdk_provider([{"output": [call([])]}])
    context = DealContext(4, ("Aurora",), (), 0, 0)
    wrapped = DealContextProvider(provider, context)
    schema = _review_item_schema(kind)
    assert wrapped.complete_json("GROUNDING REVIEW", item_schema=schema) == "[]"
    payload = requests[0]
    assert payload["input"] == context.prompt_prefix() + "GROUNDING REVIEW"
    assert payload["tools"][0]["strict"] is True
    assert payload["tools"][0]["parameters"]["properties"]["result"]["items"] == schema


def test_object_transport_for_classification_and_qa():
    result = {"answer": "Risposta", "cited_chunks": [0]}
    provider, requests = sdk_provider([{"output": [call(result)]}])
    assert json.loads(provider.complete_json("QUESTION", response_type="object")) == result
    assert requests[0]["tools"][0]["parameters"]["properties"]["result"] == {"type": "object"}


def test_all_pipeline_stages_use_luna_sdk_transport(db, test_deal):
    from app.models.document import Document, DocumentStatus
    from app.models.agent_run import AgentRun, AgentRunStatus
    from packages.agents.deal_analysis_agent import FakeLLMProvider
    from packages.agents.orchestrator import run_deal_analysis_pipeline

    for filename in ("contract.txt", "bylaws.txt", "avviso_di_accertamento.txt", "financial_statements.txt"):
        db.add(Document(
            deal_id=test_deal.id, filename=filename, file_path="/tmp/" + filename,
            mime_type="text/plain", file_size=200, status=DocumentStatus.processed,
            raw_text="Either party may terminate with 30 days written notice. "
                     "Liability shall not exceed the total contract value.", language="en",
        ))
    db.commit()
    fake = FakeLLMProvider()

    def respond(payload):
        raw = fake.complete(payload["input"], max_tokens=payload["max_output_tokens"])
        return {"output": [call(json.loads(raw)) if payload.get("tools") else message(raw)]}

    provider, requests = sdk_provider(respond)
    with patch("anthropic.Anthropic", side_effect=AssertionError("Unexpected Anthropic call")):
        result = run_deal_analysis_pipeline(test_deal.id, db, provider=provider)
    assert result["completed"], result
    runs = db.query(AgentRun).all()
    assert len(runs) == 9
    assert all(run.status == AgentRunStatus.completed for run in runs)
    assert len(requests) >= 9
    assert all(request["model"] == "gpt-5.6-luna" for request in requests)


@pytest.mark.parametrize("citations,verified", [([0], True), ([], False), ([True, -1, 9], False)])
def test_qa_luna_transport_preserves_source_validation(db, test_deal, citations, verified):
    from packages.agents.deal_qa_agent import answer_deal_question
    from packages.retrieval.retrieval_service import ChunkMatch

    provider, requests = sdk_provider([{"output": [call({"answer": "30 days.", "cited_chunks": citations})]}])
    match = ChunkMatch(document_id=42, chunk_id=1, page_number=2,
                       content="Either party may terminate with 30 days notice.", score=0.99)
    with patch("packages.agents.deal_qa_agent.search_similar_chunks", return_value=[match]):
        result = answer_deal_question(test_deal.id, "What notice is required?", db, llm_provider=provider)
    assert requests[0]["model"] == "gpt-5.6-luna"
    assert requests[0]["tools"][0]["parameters"]["properties"]["result"] == {"type": "object"}
    if verified:
        assert result["answer"] == "30 days."
        assert result["sources"] == [{"document_id": 42, "page_number": 2, "excerpt": match.content}]
    else:
        assert result["sources"] == []
        assert result["answer"] != "30 days."


@pytest.mark.parametrize("output", [
    [message("[]")], [call([]), call([])], [call([], name="wrong")],
    [call([], status="in_progress")], [call("[]")], [call(None)],
    [call([], arguments='{"result": [], "result": [{"title":"hidden"}]}')],
    [call([], arguments='{"result": [{"title":"first","title":"second"}]}')],
    [call([], arguments='{"result": [{"title":"partial"},')],
    [call([], arguments='{"result": [], "extra": 1}')],
    [call([], arguments='{"result": [{"amount": NaN}]}')],
])
def test_malformed_complete_output_gets_one_full_format_retry(output):
    expected = [{"title": "Complete first"}, {"title": "Complete second"}]
    provider, requests = sdk_provider([{"output": output}, {"output": [call(expected)]}])
    assert _complete_llm_items(provider, "WHOLE SOURCE", max_tokens=6144, context="doc 1") == expected
    assert len(requests) == 2
    assert requests[1]["input"].startswith("FORMAT RETRY:")
    assert requests[1]["input"].endswith("WHOLE SOURCE")


@pytest.mark.parametrize("reply", [
    {"status": "failed", "output": [call([])]},
    {"status": "completed", "error": {"code": "server_error", "message": "failure"}, "output": [call([])]},
    {"output": [call([]), {**message(""), "content": [{"type": "refusal", "refusal": "refused"}]}]},
])
def test_failed_or_refused_result_is_never_accepted_or_retried(reply):
    provider, requests = sdk_provider([reply])
    with pytest.raises(LLMResponseError):
        _complete_llm_items(provider, "SOURCE", max_tokens=6144, context="doc 1")
    assert len(requests) == 1


def test_truncated_result_is_retried_once_compactly_and_never_accepted():
    truncated = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": [call([])]}
    provider, requests = sdk_provider([truncated, truncated])
    with pytest.raises(LLMResponseError, match="truncated.*after 2 attempts"):
        _complete_llm_items(provider, "SOURCE", max_tokens=6144, context="doc 1")
    assert len(requests) == 2
    assert requests[1]["input"].startswith("OUTPUT LIMIT RETRY:")
    assert requests[1]["input"].endswith("SOURCE")


def test_empty_native_array_is_valid_but_empty_text_is_not():
    provider, requests = sdk_provider([{"output": [call([])]}, {"output": []}])
    assert _complete_llm_items(provider, "SOURCE", max_tokens=6144, context="doc 1") == []
    with pytest.raises(LLMResponseError, match="no text"):
        provider.complete("SOURCE")
    assert len(requests) == 2


@pytest.mark.parametrize("model,expected", [(None, OpenAILLMProvider), ("claude-sonnet-5", AnthropicLLMProvider)])
def test_factory_selects_the_model_not_the_order_of_credentials(monkeypatch, model, expected):
    from app.core.config import Settings
    import app.core.config as config
    from packages.agents import deal_analysis_agent as llm
    monkeypatch.delenv("ANALYSIS_MODEL", raising=False)
    settings = Settings(_env_file=None, OPENAI_API_KEY="openai-test", ANTHROPIC_API_KEY="anthropic-test",
                        **({"ANALYSIS_MODEL": model} if model else {}))
    monkeypatch.setattr(config, "settings", settings)
    monkeypatch.setattr(llm, "_llm_provider", None)
    with patch("openai.OpenAI") as openai_client, patch("anthropic.Anthropic") as anthropic_client:
        result = llm.get_llm_provider()
    assert isinstance(result, expected)
    assert result._model == (model or "gpt-5.6-luna")
    selected, other = (openai_client, anthropic_client) if model is None else (anthropic_client, openai_client)
    selected.assert_called_once_with(api_key="openai-test" if model is None else "anthropic-test")
    other.assert_not_called()


@pytest.mark.parametrize("model,available,missing", [
    ("gpt-5.6-luna", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"),
    ("claude-sonnet-5", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"),
])
def test_missing_selected_key_cannot_fall_back_to_other_vendor(monkeypatch, model, available, missing):
    from app.core.config import settings
    from packages.agents import deal_analysis_agent as llm
    monkeypatch.setattr(settings, "BETA_MODE", False)
    monkeypatch.setattr(settings, "ANALYSIS_MODEL", model)
    monkeypatch.setattr(settings, available, "test")
    monkeypatch.setattr(settings, missing, "")
    monkeypatch.delenv(missing, raising=False)
    monkeypatch.setattr(llm, "_llm_provider", None)
    with pytest.raises(RuntimeError, match=missing):
        llm.get_llm_provider()


def test_legacy_entry_point_also_defaults_to_luna():
    from packages.agents.deal_agent import DealAnalysisAgent
    provider, requests = sdk_provider([{"output": [message("Summary")]}])
    with patch("openai.OpenAI", return_value=provider._client):
        agent = DealAnalysisAgent(api_key="test")
    assert asyncio.run(agent.run("Title", "Description")).summary == "Summary"
    assert requests[0]["model"] == "gpt-5.6-luna"
