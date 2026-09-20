"""The judgment stages may run on a different model than bulk reading."""
from unittest.mock import patch

import pytest

from packages.agents import deal_analysis_agent as llm
from packages.agents.deal_analysis_agent import (
    AnthropicLLMProvider, FakeLLMProvider, OpenAILLMProvider, set_llm_provider,
)


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(llm, "_llm_provider", None)
    monkeypatch.setattr(llm, "_judgment_provider", None)
    yield
    set_llm_provider(None)


def _settings(monkeypatch, **overrides):
    from app.core.config import Settings
    import app.core.config as config
    for name in ("ANALYSIS_MODEL", "JUDGMENT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    values = {"OPENAI_API_KEY": "openai-test", "ANTHROPIC_API_KEY": "anthropic-test", **overrides}
    settings = Settings(_env_file=None, **values)
    monkeypatch.setattr(config, "settings", settings)
    return settings


def test_empty_judgment_model_means_the_analysis_provider(fresh, monkeypatch):
    _settings(monkeypatch)
    with patch("openai.OpenAI"), patch("anthropic.Anthropic"):
        assert llm.get_judgment_provider() is llm.get_llm_provider()


def test_judgment_model_selects_its_own_vendor_and_keeps_luna_for_reading(fresh, monkeypatch):
    _settings(monkeypatch, JUDGMENT_MODEL="claude-sonnet-5")
    with patch("openai.OpenAI"), patch("anthropic.Anthropic") as anthropic_client:
        reading, judgment = llm.get_llm_provider(), llm.get_judgment_provider()
    assert isinstance(reading, OpenAILLMProvider) and reading._model == "gpt-5.6-luna"
    assert isinstance(judgment, AnthropicLLMProvider) and judgment._model == "claude-sonnet-5"
    anthropic_client.assert_called_once_with(api_key="anthropic-test")
    assert llm.get_judgment_provider() is judgment


def test_missing_judgment_key_never_falls_back_to_the_other_vendor(fresh, monkeypatch):
    _settings(monkeypatch, JUDGMENT_MODEL="claude-sonnet-5", ANTHROPIC_API_KEY="")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch("openai.OpenAI"), pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY.*JUDGMENT_MODEL"):
        llm.get_judgment_provider()


def test_a_test_stub_covers_both_roles(fresh, monkeypatch):
    _settings(monkeypatch, JUDGMENT_MODEL="claude-sonnet-5")
    stub = FakeLLMProvider()
    set_llm_provider(stub)
    assert llm.get_judgment_provider() is stub


def test_beta_requires_the_judgment_model_key(monkeypatch):
    from app.core.config import settings
    from app.core.runtime_validation import validate_beta_configuration
    monkeypatch.setattr(settings, "BETA_MODE", True)
    monkeypatch.setattr(settings, "JUDGMENT_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        validate_beta_configuration()


class Recording(FakeLLMProvider):
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.markers = []

    def complete(self, prompt, max_tokens=3072):
        for marker in ("CLASSIFY", "EXTRACT CLAUSES", "RED FLAGS", "GROUNDING REVIEW", "EXECUTIVE SUMMARY"):
            if marker in prompt.upper():
                self.markers.append(marker)
                break
        return super().complete(prompt, max_tokens)


def test_pipeline_routes_judgment_stages_to_the_judgment_provider(db, test_deal, monkeypatch):
    from app.models.document import Document, DocumentStatus
    from packages.agents.orchestrator import run_deal_analysis_pipeline
    db.add(Document(deal_id=test_deal.id, filename="service_agreement.txt", file_path="/tmp/x",
                    mime_type="text/plain", file_size=100, status=DocumentStatus.processed,
                    raw_text="SERVICE AGREEMENT\nTERMINATION: Either party may terminate with 30 days notice.\n"))
    db.commit()
    reading, judgment = Recording("reading"), Recording("judgment")
    monkeypatch.setattr(llm, "get_llm_provider", lambda: reading)
    monkeypatch.setattr(llm, "get_judgment_provider", lambda: judgment)
    import packages.agents.orchestrator as orchestrator
    monkeypatch.setattr(orchestrator, "get_llm_provider", lambda: reading)

    result = run_deal_analysis_pipeline(test_deal.id, db)
    assert result["completed"], result
    assert "CLASSIFY" in reading.markers and "EXTRACT CLAUSES" in reading.markers
    assert "RED FLAGS" in judgment.markers and "GROUNDING REVIEW" in judgment.markers
    assert "RED FLAGS" not in reading.markers and "CLASSIFY" not in judgment.markers
