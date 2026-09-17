import pytest
from app.core.config import settings
from app.core.runtime_validation import validate_beta_configuration


@pytest.fixture
def valid_beta(monkeypatch):
    values = dict(BETA_MODE=True, DATABASE_URL="postgresql://app@localhost/db", DEBUG=False,
                  SECRET_KEY="beta-test-secret-" * 4, AUTH_COOKIE_SECURE=True,
                  REDIS_URL="redis://localhost", S3_BUCKET="staging",
                  ANTHROPIC_API_KEY="test-placeholder", OPENAI_API_KEY="test-placeholder")
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def test_valid_beta_configuration(valid_beta):
    validate_beta_configuration()


@pytest.mark.parametrize("name,value", [
    ("REDIS_URL", ""), ("S3_BUCKET", ""), ("ANTHROPIC_API_KEY", ""),
    ("OPENAI_API_KEY", ""), ("DEBUG", True), ("AUTH_COOKIE_SECURE", False),
    ("DATABASE_URL", "sqlite:///test.db"), ("SECRET_KEY", "short"),
    ("WORKER_MAX_JOBS", 0),
])
def test_beta_rejects_incomplete_runtime(valid_beta, monkeypatch, name, value):
    monkeypatch.setattr(settings, name, value)
    with pytest.raises(RuntimeError):
        validate_beta_configuration()


def test_beta_cannot_reuse_cached_fake_providers(valid_beta, monkeypatch):
    from packages.agents import deal_analysis_agent as llm
    from packages.retrieval import embedding_service as embeddings
    monkeypatch.setattr(llm, "_llm_provider", llm.FakeLLMProvider())
    monkeypatch.setattr(embeddings, "_default_provider", embeddings.FakeEmbeddingProvider())
    with pytest.raises(RuntimeError, match="fake"):
        llm.get_llm_provider()
    with pytest.raises(RuntimeError, match="fake"):
        embeddings.get_embedding_provider()
