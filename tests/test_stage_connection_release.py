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

from packages.agents.deal_analysis_agent import FakeLLMProvider, _safe_json
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
    """Fully processed contract document (post-ingestion state)."""
    from app.models.document import Document, DocumentStatus

    doc = Document(
        deal_id=test_deal.id,
        filename="service_agreement.txt",
        file_path="/tmp/service_agreement.txt",
        mime_type="text/plain",
        file_size=2048,
        status=DocumentStatus.processed,
        raw_text=(
            "SERVICE AGREEMENT\n\n"
            "This agreement is entered into by and between Party A (Client) "
            "and Party B (Provider).\n\n"
            "TERMINATION: Either party may terminate this agreement with 30 days "
            "written notice.\n\n"
            "LIABILITY: In no event shall either party be liable for indirect, "
            "incidental, or consequential damages.\n\n"
            "CONFIDENTIALITY: Both parties agree to keep all information "
            "disclosed under this agreement strictly confidential."
        ),
        language="en",
        page_count=3,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


# ── Probing provider ───────────────────────────────────────────────────────


class _ProbeProvider(FakeLLMProvider):
    """FakeLLMProvider that records the DB state seen during each LLM call."""

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
    # LLM on the fixture document (the specialists otherwise auto-detect by
    # keyword and would skip a plain service agreement).
    if agent_name == "contract_analysis":
        from packages.agents.contract_agent import ContractAgent
        ContractAgent(provider=provider).run(deal_id, db, contract_document_ids={doc_id})
    elif agent_name == "corporate_governance":
        from packages.agents.corporate_agent import CorporateAgent
        CorporateAgent(provider=provider).run(deal_id, db, document_ids={doc_id})
    elif agent_name == "corporate_intro_extraction":
        from packages.agents.corporate_intro_agent import CorporateIntroAgent
        CorporateIntroAgent(provider=provider).run(deal_id, db, document_ids={doc_id})
    elif agent_name == "tax_analysis":
        from packages.agents.tax_agent import TaxAgent
        TaxAgent(provider=provider).run(deal_id, db, document_ids={doc_id})
    elif agent_name == "financial_analysis":
        from packages.agents.financial_agent import FinancialAgent
        FinancialAgent(provider=provider).run(deal_id, db, document_ids={doc_id})
    elif agent_name == "document_routing":
        from packages.agents.orchestrator import _stage_document_routing
        _stage_document_routing(deal_id, db, provider)
    else:  # pragma: no cover
        raise AssertionError(agent_name)


@pytest.mark.parametrize(
    "agent_name",
    [
        "document_routing",
        "contract_analysis",
        "corporate_governance",
        "corporate_intro_extraction",
        "tax_analysis",
        "financial_analysis",
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
    from packages.agents.contract_agent import ContractAgent

    ContractAgent(provider=FakeLLMProvider()).run(test_deal.id, db)
    db.commit()
    ContractAgent(provider=FakeLLMProvider()).run(test_deal.id, db)
    db.commit()

    rows = (
        db.query(AgentRun)
        .filter(AgentRun.deal_id == test_deal.id, AgentRun.agent_name == "contract_analysis")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == AgentRunStatus.completed


# ── Rollback semantics are preserved ──────────────────────────────────────


class _FailingContractProvider(FakeLLMProvider):
    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        if "EXTRACT CLAUSES" in prompt.upper():
            raise RuntimeError("simulated LLM outage")
        return super().complete(prompt, max_tokens)


def test_failed_contract_stage_keeps_previous_clause_findings(db, test_deal, processed_doc):
    """Deleting the previous outputs now happens *after* the LLM phase, in
    the persistence transaction — so a failed stage still rolls the deletes
    back and the previous run's clauses survive."""
    from app.models.agent_run import AgentRun, AgentRunStatus
    from app.models.clause_finding import ClauseFinding
    from packages.agents.orchestrator import run_deal_analysis_pipeline

    run_deal_analysis_pipeline(test_deal.id, db, provider=FakeLLMProvider())
    before = (
        db.query(ClauseFinding)
        .filter(ClauseFinding.document_id == processed_doc.id)
        .count()
    )
    assert before > 0, "fixture should yield at least one clause"

    result = run_deal_analysis_pipeline(
        test_deal.id, db, provider=_FailingContractProvider()
    )
    assert "error" in result["stages"]["specialist_analysis"]

    after = (
        db.query(ClauseFinding)
        .filter(ClauseFinding.document_id == processed_doc.id)
        .count()
    )
    assert after == before

    runs = (
        db.query(AgentRun)
        .filter(AgentRun.deal_id == test_deal.id, AgentRun.agent_name == "contract_analysis")
        .all()
    )
    assert len(runs) == 1
    assert runs[0].status == AgentRunStatus.failed
