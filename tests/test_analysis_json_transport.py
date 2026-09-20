"""Regression coverage for the multi-stage JSON failures of 2026-09-20."""
import json
from datetime import datetime, timedelta, timezone

import anthropic
import httpx2 as httpx
import pytest

from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.document import Document, DocumentStatus
from packages.agents.deal_analysis_agent import (
    AnthropicLLMProvider, FakeLLMProvider, LLMProvider, LLMResponseError,
    _complete_llm_items, _safe_json,
)
from packages.agents.deal_context import DealContext, DealContextProvider
from packages.agents.orchestrator import run_deal_analysis_pipeline


def tool(result):
    return {"type": "tool_use", "id": "toolu_test", "name": "submit_analysis", "input": {"result": result}}


def sdk_provider(responses):
    """Use the real SDK serialization and content types, with HTTP replay only."""
    requests = []
    queued = iter(responses)

    def handle(request):
        requests.append(json.loads(request.content))
        stop_reason, content = next(queued)
        return httpx.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 20, "output_tokens": 20},
        })

    provider = AnthropicLLMProvider.__new__(AnthropicLLMProvider)
    provider._model = "claude-sonnet-5"
    provider._client = anthropic.Anthropic(
        api_key="test", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    return provider, requests


def test_sdk_structured_transport_preserves_all_records_and_ignores_prose():
    items = [{"title": "Clausola α", "content": 'La società "Alfa"', "amount": 123},
             {"title": "Secondo rilievo", "evidence": [{"quote": "letterale"}]}]
    provider, requests = sdk_provider([("tool_use", [
        {"type": "text", "text": "Ecco i risultati.\n[]\n\n[]"}, tool(items),
    ])])
    assert _complete_llm_items(provider, "EXTRACT CLAUSES\nsource", max_tokens=6144, context="doc 193") == items
    assert len(requests) == 1
    payload = requests[0]
    assert payload["tool_choice"] == {
        "type": "tool", "name": "submit_analysis", "disable_parallel_tool_use": True,
    }
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["tools"][0]["input_schema"]["properties"]["result"]["type"] == "array"
    assert payload["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert payload["max_tokens"] == 6144
    assert "temperature" not in payload


def test_deal_context_forwards_structured_transport_once():
    provider, requests = sdk_provider([("tool_use", [tool({"document_type": "contract"})])])
    context = DealContext(4, ("Alfa S.p.A.",), (), 0, 0)
    wrapped = DealContextProvider(provider, context)
    assert json.loads(wrapped.complete_json("CLASSIFY", max_tokens=512, response_type="object")) == {
        "document_type": "contract",
    }
    payload = requests[0]
    assert payload["tools"][0]["input_schema"]["properties"]["result"]["type"] == "object"
    prompt = payload["messages"][0]["content"][0]["text"]
    assert prompt == context.prompt_prefix() + "CLASSIFY"


@pytest.mark.parametrize("kind", ["flags", "text"])
@pytest.mark.parametrize("partial", [False, True])
def test_review_schema_reaches_real_sdk_as_strict_tool_through_context(kind, partial):
    from packages.agents.grounding_review import _review_item_schema

    provider, requests = sdk_provider([("tool_use", [tool([{"index": 0}])])])
    wrapped = DealContextProvider(provider, DealContext(4, ("Alfa S.p.A.",), (), 0, 0))
    schema = _review_item_schema(kind, partial=partial)
    wrapped.complete_json("GROUNDING REVIEW", item_schema=schema)
    definition = requests[0]["tools"][0]
    assert definition["strict"] is True
    assert definition["input_schema"]["properties"]["result"]["items"] == schema
    expected = {"text"} if kind == "text" else {"title", "issue", "risk", "recommendation"}
    assert set(schema["properties"]["fields"]["required"]) == expected
    # Unsupported decisions may honestly have no quotations; acceptance still
    # requires evidence coverage in the production reviewer.
    assert schema["properties"]["evidence"]["minItems"] == 0
    assert "support_reason" in schema["required"]

    def verify_objects(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for child in value.values():
                verify_objects(child)
        elif isinstance(value, list):
            for child in value:
                verify_objects(child)

    verify_objects(definition["input_schema"])


@pytest.mark.parametrize("content", [
    [{"type": "text", "text": "[]\n\n[]"}],
    [tool([]), tool([{"title": "Do not silently discard me"}])],
    [tool("[]")], [tool([{}])], [tool(None)],
    [{"type": "tool_use", "id": "toolu_bad", "name": "submit_analysis", "input": {}}],
])
def test_invalid_structured_response_retries_whole_request_once(content):
    items = [{"title": "Rilievo completo"}]
    provider, requests = sdk_provider([("tool_use", content), ("tool_use", [tool(items)])])
    assert _complete_llm_items(provider, "ORIGINAL SOURCE", max_tokens=12288, context="doc 107") == items
    assert len(requests) == 2
    retry_prompt = requests[1]["messages"][0]["content"][0]["text"]
    assert retry_prompt.startswith("FORMAT RETRY:")
    assert retry_prompt.endswith("ORIGINAL SOURCE")
    assert requests[1]["max_tokens"] == requests[0]["max_tokens"]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refused_or_truncated_native_response_never_retries_or_accepts_partial_data(stop_reason):
    provider, requests = sdk_provider([(stop_reason, [tool([{"title": "Apparently complete"}])])])
    with pytest.raises(LLMResponseError, match="doc 217"):
        _complete_llm_items(provider, "source", max_tokens=6144, context="doc 217")
    assert len(requests) == 1


@pytest.mark.parametrize("raw", [
    "Ecco i risultati:\n[]", "[]\n\n[]", "```json\n[]\n```\nNota: nessun dato.",
    '[{"title":"first"},{"title":',
])
def test_text_provider_format_failure_retries_without_salvaging_prefix(raw):
    class TextProvider(LLMProvider):
        def __init__(self):
            self.calls = []

        def complete(self, prompt, max_tokens=3072):
            self.calls.append(prompt)
            return raw if len(self.calls) == 1 else '[{"title":"first"},{"title":"second"}]'

    provider = TextProvider()
    assert _complete_llm_items(provider, "original", max_tokens=6144, context="doc 215") == [
        {"title": "first"}, {"title": "second"},
    ]
    assert len(provider.calls) == 2
    with pytest.raises(LLMResponseError):
        _safe_json(raw)


def test_exhausted_format_retry_fails_with_context_and_does_not_log_source(caplog):
    provider, requests = sdk_provider([("tool_use", [tool(None)])] * 2)
    with pytest.raises(LLMResponseError, match="doc 215:.*after 2 attempts"):
        _complete_llm_items(provider, "CONFIDENTIAL SOURCE TEXT", max_tokens=6144, context="doc 215")
    assert len(requests) == 2
    assert "CONFIDENTIAL SOURCE TEXT" not in caplog.text


def test_valid_empty_native_response_is_successful_without_retry():
    provider, requests = sdk_provider([("tool_use", [tool([])])])
    assert _complete_llm_items(provider, "source", max_tokens=6144, context="doc 107") == []
    assert len(requests) == 1


def test_pipeline_recovers_transient_format_errors_in_all_four_affected_stages(db, test_deal):
    for filename in ("contract.txt", "bylaws.txt", "avviso_di_accertamento.txt", "financial_statements.txt"):
        db.add(Document(
            deal_id=test_deal.id, filename=filename, file_path="/tmp/" + filename,
            mime_type="text/plain", file_size=200, status=DocumentStatus.processed,
            raw_text="Either party may terminate with 30 days written notice. "
                     "Liability shall not exceed the total contract value.", language="en",
        ))
    db.commit()

    class IncidentProvider(FakeLLMProvider):
        markers = ("EXTRACT CLAUSES", "CORPORATE INTRODUCTORY INFORMATION", "ANALYZE TAX MATTERS",
                   "ANALYZE FINANCIAL STATEMENTS")

        def __init__(self):
            self.failed = set()
            self.recovered = set()

        def complete(self, prompt, max_tokens=3072):
            for marker in self.markers:
                if marker in prompt:
                    if marker not in self.failed:
                        self.failed.add(marker)
                        return "[]\n\n[]" if len(self.failed) % 2 else "Ecco i risultati:\n[]"
                    self.recovered.add(marker)
            return super().complete(prompt, max_tokens=max_tokens)

    provider = IncidentProvider()
    result = run_deal_analysis_pipeline(test_deal.id, db, provider=provider)
    assert result["completed"], result
    assert provider.failed == provider.recovered == set(provider.markers)
    assert all(run.status == AgentRunStatus.completed for run in db.query(AgentRun))


@pytest.mark.parametrize("raise_error", [True, False])
def test_failed_stage_retains_actual_elapsed_time(db, test_deal, monkeypatch, raise_error):
    from packages.agents import orchestrator

    start = datetime(2026, 9, 20, 6, 4, tzinfo=timezone.utc)
    current = [start]

    class Clock:
        @staticmethod
        def now(tz):
            return current[0]

    monkeypatch.setattr(orchestrator, "datetime", Clock)

    def fail():
        current[0] += timedelta(seconds=51)
        if raise_error:
            raise LLMResponseError("invalid format")
        return {"error": "invalid format"}

    result = orchestrator._execute_stage(db, test_deal.id, "tax_analysis", fail)
    assert result["error"] == "invalid format"
    run = db.query(AgentRun).filter_by(agent_name="tax_analysis").one()
    assert run.status == AgentRunStatus.failed
    assert (run.completed_at - run.started_at).total_seconds() == 51
