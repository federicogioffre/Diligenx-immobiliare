"""Tests for AnthropicLLMProvider.

The provider wraps the real Anthropic SDK, so we mock the underlying client
and assert on the shape of the payload — in particular that every prompt is
sent with a ``cache_control`` breakpoint so prompt caching is in effect.
"""

from unittest.mock import MagicMock, patch

import pytest

from packages.agents.deal_analysis_agent import AnthropicLLMProvider


def _make_provider_with_mock_client(response_text: str = "ok") -> tuple[AnthropicLLMProvider, MagicMock]:
    """Construct an AnthropicLLMProvider whose .messages.create is mocked."""
    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text=response_text)]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_msg

    with patch("anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicLLMProvider(api_key="sk-test", model="claude-sonnet-4-6")
    return provider, mock_client


def test_complete_returns_text_from_response():
    provider, _ = _make_provider_with_mock_client("hello world")
    assert provider.complete("any prompt") == "hello world"


def test_complete_sends_prompt_with_cache_control_marker():
    """Every call must tag its content block with cache_control=ephemeral.

    This is what enables prompt caching: Anthropic caches the prefix up to
    and including the marked block. Without this, the idempotent re-runs of
    /analyze would pay full input cost every time.
    """
    provider, mock_client = _make_provider_with_mock_client()
    provider.complete("classify this contract")

    mock_client.messages.create.assert_called_once()
    kwargs = mock_client.messages.create.call_args.kwargs

    messages = kwargs["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"

    content = messages[0]["content"]
    # Must be the structured (list-of-blocks) form, not a bare string —
    # cache_control only attaches to content blocks.
    assert isinstance(content, list)
    assert len(content) == 1

    block = content[0]
    assert block["type"] == "text"
    assert block["text"] == "classify this contract"
    assert block["cache_control"] == {"type": "ephemeral"}


def test_complete_uses_configured_model_and_temperature():
    """Sanity check that we don't regress temperature=0 or the model name.

    The 1.x Anthropic SDK removed ``temperature`` from the ``create()``
    signature (passing it raises ``TypeError: Messages.create() got an
    unexpected keyword argument 'temperature'`` and every LLM stage of the
    pipeline fails). It must travel in ``extra_body`` instead.
    """
    provider, mock_client = _make_provider_with_mock_client()
    provider.complete("x", max_tokens=512)

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 512
    assert "temperature" not in kwargs
    # temperature=0 keeps the analysis output deterministic across re-runs.
    assert kwargs["extra_body"] == {"temperature": 0}


def test_complete_matches_real_sdk_signature():
    """The kwargs we send must be accepted by the installed SDK.

    Guards against the production failure where ``temperature`` was passed
    as a keyword to a 1.x ``Messages.create`` that no longer declares it.
    """
    import inspect

    import anthropic

    provider, mock_client = _make_provider_with_mock_client()
    provider.complete("x")
    kwargs = mock_client.messages.create.call_args.kwargs

    sig = inspect.signature(anthropic.resources.messages.Messages.create)
    unknown = set(kwargs) - set(sig.parameters)
    assert not unknown, f"kwargs not accepted by Messages.create: {unknown}"


@pytest.mark.parametrize(
    "model",
    ["claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-5", "claude-opus-5", "claude-fable-5-1"],
)
def test_no_temperature_for_models_that_reject_sampling_params(model):
    """Opus 4.7+, Sonnet 5 and the Claude 5 family return a 400 for any
    sampling parameter, so the request must carry no temperature at all."""
    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text="ok")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_msg

    with patch("anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicLLMProvider(api_key="sk-test", model=model)
    provider.complete("x")

    kwargs = mock_client.messages.create.call_args.kwargs
    assert "temperature" not in kwargs
    assert kwargs["extra_body"] is None


@pytest.mark.parametrize(
    "model",
    ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5", "claude-sonnet-4-5-20250929"],
)
def test_temperature_kept_for_models_that_accept_it(model):
    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text="ok")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_msg

    with patch("anthropic.Anthropic", return_value=mock_client):
        provider = AnthropicLLMProvider(api_key="sk-test", model=model)
    provider.complete("x")

    assert mock_client.messages.create.call_args.kwargs["extra_body"] == {"temperature": 0}
