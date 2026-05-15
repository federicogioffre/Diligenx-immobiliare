"""Tests for AnthropicLLMProvider.

The provider wraps the real Anthropic SDK, so we mock the underlying client
and assert on the shape of the payload — in particular that every prompt is
sent with a ``cache_control`` breakpoint so prompt caching is in effect.
"""

from unittest.mock import MagicMock, patch

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
    """Sanity check that we don't regress temperature=0 or the model name."""
    provider, mock_client = _make_provider_with_mock_client()
    provider.complete("x", max_tokens=512)

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 512
    # temperature=0 keeps the analysis output deterministic across re-runs.
    assert kwargs["temperature"] == 0
