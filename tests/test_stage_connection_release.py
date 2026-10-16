"""Pipeline stages must not hold a DB transaction open across the LLM phase.

Production failure this guards against: the contract stage ran 925 s of LLM
calls on 66 documents while its Postgres connection sat idle inside an open
transaction. The managed proxy closed the idle connection, the first write
afterwards raised ``SSL connection has been closed unexpectedly`` and the
whole stage was rolled back — every minute of LLM work lost, and the report
generated without a single contract clause.

The contract (``packages/agents/stage_tx``): open the running AgentRun,
copy the inputs out of the ORM, **commit** (connection back to the pool,
running row visible to the progress stream), fan out, then delete the
previous outputs and persist the new ones in a fresh transaction.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from packages.real_estate.fake_provider import FakeRealEstateLLMProvider
from packages.agents.deal_analysis_agent import _safe_json
from tests.conftest import TestingSession


# ── _safe_json: the model's invalid ``\'`` escape ─────────────────────────


def test_safe_json_repairs_backslash_apostrophe():
    r"""``l\'attività`` is not valid JSON; the batch used to be dropped whole."""
    raw = '[{"title": "Quota", "content": "quota per l\\\'attività contrattuale", "confidence": 0.85}]'
    items = _safe_json(raw)
    assert isinstance(items, list) and len(items) == 1
    assert items[0]["content"] == "quota per l'attività contrattuale"


def test_safe_json_keeps_legitimate_escapes():
    raw = '[{"content": "line one\\nline \\"two\\" \\\\ backslash"}]'
    assert _safe_json(raw)[0]["content"] == 'line one\nline "two" \\ backslash'


def test_safe_json_escapes_stray_quotes_inside_strings():
    """The production failure on docs 107/108/169: ``Expecting ',' delimiter``
    because the model copied quoted Italian terms into ``content`` verbatim."""
    raw = (
        '[{"clause_type": "change_of_control", "title": "Cambio di controllo", '
        '"content": "la clausola "change of control" e il c.d. "patto di non '
        'concorrenza" restano validi", "page_number": 3, "confidence": 0.92}, '
        '{"clause_type": "other", "title": "Altro", "content": "testo pulito", '
        '"page_number": null, "confidence": 0.8}]'
    )
    items = _safe_json(raw)
    assert len(items) == 2
    assert items[0]["content"] == (
        'la clausola "change of control" e il c.d. "patto di non concorrenza" restano validi'
    )
    assert items[0]["confidence"] == 0.92
    assert items[1]["content"] == "testo pulito"


def test_safe_json_stray_quote_repair_does_not_touch_valid_json():
    raw = '{"a": "x", "b": ["y", "z"], "c": {"d": "e: f, g"}}'
    assert _safe_json(raw) == {"a": "x", "b": ["y", "z"], "c": {"d": "e: f, g"}}


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def processed_doc(db: Session, test_deal):
    """Fully processed property document (post-ingestion state)."""
    from app.models.document import Document, DocumentStatus

    doc = Document(
        deal_id=test_deal.id,
        filename="ispezione_ipotecaria.txt",
        file_path="/tmp/ispezione_ipotecaria.txt",
        mime_type="text/plain",
        file_size=2048,
        status=DocumentStatus.processed,
        raw_text=(
            "ISPEZIONE IPOTECARIA - elenco sintetico delle formalità\n"
            "Immobile in Milano, Foglio 12 particella 345 sub. 5.\n"
            "Ipoteca volontaria iscritta in data 01/06/2015 a favore di Banca Esempio S.p.A. "
            "a garanzia di mutuo fondiario.\n"
        ),
        language="it",
        page_count=3,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


# ── Probing provider ───────────────────────────────────────────────────────


class _ProbeProvider(FakeRealEstateLLMProvider):
    """Test provider that records the DB state seen during each LLM call."""

    def __init__(self, db: Session, agent_name: str):
        from packages.agents.orchestrator import AGENT_ROUTER

        self._db = db
        # The routing stage records its AgentRun under AGENT_ROUTER.
        self._agent_name = AGENT_ROUTER if agent_name == "document_routing" else agent_name
        self.in_transaction: list[bool] = []
        self.running_row_visible: list[bool] = []

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        from app.models.agent_run import AgentRun, AgentRunStatus

        self.in_transaction.append(self._db.in_transaction())
        # A *separate* session sees only committed rows — exactly what the
        # progress stream and /agent-runs see while the stage is running.
        other = TestingSession()
        try:
            visible = (
                other.query(AgentRun)
                .filter(
                    AgentRun.agent_name == self._agent_name,
                    AgentRun.status == AgentRunStatus.running,
                )
                .count()
            )
        finally:
            other.close()
        self.running_row_visible.append(visible > 0)
        return super().complete(prompt, max_tokens)


def _run_agent(agent_name: str, db: Session, deal_id: int, doc_id: int, provider) -> None:
    # Document ids are passed explicitly so every agent actually calls the
    # LLM on the fixture document.
    if agent_name == "document_routing":
        from packages.agents.orchestrator import _stage_document_routing
        _stage_document_routing(deal_id, db, provider)
    elif agent_name == "property_identity":
        from packages.real_estate.property_identity_agent import PropertyIdentityAgent
        PropertyIdentityAgent(provider=provider).run(deal_id, db, document_ids={doc_id})
    else:
        from packages.real_estate.specialists import SPECIALISTS
        agent_cls = next(cls for cls in SPECIALISTS if cls.AGENT_NAME == agent_name)
        agent_cls(provider=provider).run(deal_id, db, document_ids={doc_id})


@pytest.mark.parametrize(
    "agent_name",
    [
        "document_routing",
        "property_identity",
        "title_chain_review",
        "encumbrances_review",
        "building_cadastral_review",
        "condominium_occupancy_review",
    ],
)
def test_no_open_transaction_during_llm_phase(db, test_deal, processed_doc, agent_name):
    provider = _ProbeProvider(db, agent_name)
    _run_agent(agent_name, db, test_deal.id, processed_doc.id, provider)

    assert provider.in_transaction, f"{agent_name}: the LLM was never called"
    assert not any(provider.in_transaction), (
        f"{agent_name}: transaction held open across the LLM phase"
    )
    assert all(provider.running_row_visible), (
        f"{agent_name}: running AgentRun not committed before the LLM phase"
    )


def test_running_row_is_replaced_by_a_single_completed_row(db, test_deal, processed_doc):
    """Committing the running row early must not leave a duplicate behind."""
    from app.models.agent_run import AgentRun, AgentRunStatus
    from packages.real_estate.specialists import EncumbrancesAgent

    EncumbrancesAgent(provider=FakeRealEstateLLMProvider()).run(test_deal.id, db)
    db.commit()
    EncumbrancesAgent(provider=FakeRealEstateLLMProvider()).run(test_deal.id, db)
    db.commit()

    rows = (
        db.query(AgentRun)
        .filter(AgentRun.deal_id == test_deal.id, AgentRun.agent_name == "encumbrances_review")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == AgentRunStatus.completed


# ── Rollback semantics are preserved ──────────────────────────────────────


class _FailingEncumbrancesProvider(FakeRealEstateLLMProvider):
    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        if "REVIEW ENCUMBRANCES" in prompt.upper():
            raise RuntimeError("simulated LLM outage")
        return super().complete(prompt, max_tokens)


def test_failed_review_stage_keeps_previous_findings(db, test_deal, processed_doc):
    """Deleting the previous outputs happens *after* the LLM phase, in the
    persistence transaction — so a failed stage still rolls the deletes back
    and the previous run's findings survive."""
    from app.models.agent_finding import AgentFinding
    from app.models.agent_run import AgentRun, AgentRunStatus
    from packages.agents.orchestrator import run_deal_analysis_pipeline

    def findings():
        return (
            db.query(AgentFinding)
            .filter(AgentFinding.deal_id == test_deal.id, AgentFinding.agent_name == "encumbrances_review")
            .count()
        )

    run_deal_analysis_pipeline(test_deal.id, db, provider=FakeRealEstateLLMProvider())
    before = findings()
    assert before > 0, "fixture should yield at least one finding"

    result = run_deal_analysis_pipeline(test_deal.id, db, provider=_FailingEncumbrancesProvider())
    assert "error" in result["stages"]["encumbrances_review"]
    assert findings() == before

    runs = (
        db.query(AgentRun)
        .filter(AgentRun.deal_id == test_deal.id, AgentRun.agent_name == "encumbrances_review")
        .all()
    )
    assert len(runs) == 1
    assert runs[0].status == AgentRunStatus.failed
