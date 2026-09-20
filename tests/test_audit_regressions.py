"""Regression tests for the independently reproduced audit scenarios."""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from datetime import datetime, timedelta, timezone
from app.core.security import hash_password
PASSWORD = "testpass123"
PASSWORD_HASH = hash_password(PASSWORD)

class StubLLM:
    def __init__(self, value="Sintesi verificata per audit."):
        self.value = value
        self.prompts = []
    def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "GROUNDING REVIEW\n" in prompt:
            from packages.agents.deal_analysis_agent import FakeLLMProvider
            return FakeLLMProvider().complete(prompt, **kwargs)
        return self.value

@pytest.fixture
def seeded(test_user, test_workspace, test_deal):
    return test_user, test_workspace, test_deal

@pytest.fixture
def auth(auth_headers):
    return auth_headers

@pytest.fixture
def llm(monkeypatch):
    import packages.agents.report_agent as module
    provider = StubLLM()
    # The report runs on the judgment provider; the stub must serve that role.
    monkeypatch.setattr(module, "get_judgment_provider", lambda: provider)
    return provider

def complete_inputs(db, deal):
    if not db.query(Document).filter_by(deal_id=deal.id).count():
        document(db, deal.id)
    fingerprint, _ = corpus_fingerprint(db, deal.id)
    start = datetime.now(timezone.utc) - timedelta(minutes=2)
    for i, (_, name) in enumerate(STAGES[:-1]):
        run = db.query(AgentRun).filter_by(deal_id=deal.id, agent_name=name).first()
        if run is None:
            run = AgentRun(deal_id=deal.id, agent_name=name)
            db.add(run)
        run.status = AgentRunStatus.completed
        run.started_at = start + timedelta(seconds=i * 2)
        run.completed_at = run.started_at + timedelta(seconds=1)
        run.input_hash = fingerprint
    db.commit()

from app.models import User, Workspace, Deal
from app.models.document import Document, DocumentStatus
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.report import Report, ReportStatus
from app.models.red_flag import RedFlag, Severity
from app.models.clause_finding import ClauseFinding, ClauseType
from packages.agents.report_agent import generate_due_diligence_report
from packages.agents.red_flag_aggregator import RedFlagAggregationAgent
from packages.agents.contract_agent import ContractAgent
from packages.agents.financial_agent import FinancialAgent
from packages.agents.analysis_checkpoint import corpus_fingerprint, STAGES


def document(db, deal_id, **overrides):
    values = dict(deal_id=deal_id, filename="contratto.txt", file_path="audit-only.txt",
                  mime_type="text/plain", file_size=80, status=DocumentStatus.processed,
                  page_count=1, language="it", raw_text="Il contratto disciplina i rapporti tra le parti.")
    values.update(overrides)
    doc = Document(**values)
    db.add(doc)
    db.commit()
    return doc


def flag_payload(doc_id, **overrides):
    values = dict(title="Audit finding", issue="Finding per audit locale", severity="medium",
                  category="covenant", source_document_id=doc_id, confidence=0.9)
    values.update(overrides)
    return values


def test_A01_pdf_export_blocks_internal_resources(client, db, seeded, auth, llm):
    """End-to-end local SSRF canary; only a loopback listener is contacted."""
    hits = []
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jhWQAAAAASUVORK5CYII=")
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(png)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/audit-canary.png"
        title = f"Acquisizione ![audit]({url})"
        deal_id = seeded[2].id
        assert client.patch(f"/deals/{deal_id}", json={"title": title}, headers=auth).status_code == 200
        complete_inputs(db, seeded[2])
        generated = client.post(f"/deals/{deal_id}/report", headers=auth)
        assert generated.status_code == 200, generated.text
        exported = client.get(f"/deals/{deal_id}/report/export?format=pdf", headers=auth)
        assert not hits
        assert exported.status_code == 200, exported.text
        assert exported.content.startswith(b"%PDF")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_A02_old_token_cannot_authenticate_recreated_account(client, db, seeded, auth):
    old_id = seeded[0].id
    # Keep a higher ID so SQLite cannot accidentally reuse the deleted ID.
    db.add(User(id=900, email="sentinel@example.com", hashed_password=PASSWORD_HASH))
    db.commit()
    deleted = client.request("DELETE", "/users/me", json={"password": PASSWORD}, headers=auth)
    assert deleted.status_code == 204, deleted.text
    assert client.get("/users/me", headers=auth).status_code == 401
    recreated = client.post("/auth/register", json={"email": "test@example.com", "password": "a-new-owner-password", "full_name": "New account"})
    assert recreated.status_code == 201, recreated.text
    new_id = recreated.json()["id"]
    assert new_id != old_id
    leaked_identity = client.get("/users/me", headers=auth)
    assert leaked_identity.status_code == 401


def test_A03_report_requires_completed_analysis(client, db, seeded, auth, llm):
    deal = seeded[2]
    assert db.query(AgentRun).filter_by(deal_id=deal.id).count() == 0
    assert db.query(Document).filter_by(deal_id=deal.id).count() == 0
    response = client.post(f"/deals/{deal.id}/report", headers=auth)
    assert response.status_code == 409, response.text
    assert db.query(Report).filter_by(deal_id=deal.id).count() == 0
    assert db.query(AgentRun).filter_by(deal_id=deal.id).count() == 0


def test_A04_target_change_preserves_report_but_blocks_stale_publication(client, db, seeded, auth, llm):
    deal = seeded[2]
    doc = document(db, deal.id)
    old_hash, _ = corpus_fingerprint(db, deal.id)
    for _, name in STAGES:
        db.add(AgentRun(deal_id=deal.id, agent_name=name, status=AgentRunStatus.completed, input_hash=old_hash))
    db.add(RedFlag(deal_id=deal.id, title="Rischio esclusivo Alfa", issue="Passivita di Alfa S.r.l.", severity=Severity.high, category="financial", source_document_id=doc.id))
    deal.status = "reviewed"
    db.commit()
    complete_inputs(db, deal)
    original = generate_due_diligence_report(deal.id, db, provider=llm)["markdown"]
    response = client.patch(f"/deals/{deal.id}", headers=auth, json={"target_company_names": ["Beta S.r.l."]})
    assert response.status_code == 200, response.text
    db.refresh(deal)
    report = db.query(Report).filter_by(deal_id=deal.id).one()
    assert report.content == original
    assert "Beta S.r.l." not in report.content
    assert "Rischio esclusivo Alfa" in report.content
    assert deal.status == "draft" and report.status == ReportStatus.completed
    new_hash, _ = corpus_fingerprint(db, deal.id)
    assert old_hash != new_hash
    assert all(r.input_hash == old_hash for r in db.query(AgentRun).filter_by(deal_id=deal.id))
    assert client.post(f"/deals/{deal.id}/report", headers=auth).status_code == 409
    existing = client.get(f"/deals/{deal.id}/report", headers=auth)
    assert existing.json()["stale"] is True
    assert existing.json()["generation_available"] is False
    assert client.get(f"/deals/{deal.id}/report/export?format=pdf", headers=auth).status_code == 409


def test_A05_report_rejects_unanalysed_new_document(db, seeded, llm):
    deal = seeded[2]
    document(db, deal.id)
    fingerprint, _ = corpus_fingerprint(db, deal.id)
    for _, name in STAGES:
        db.add(AgentRun(deal_id=deal.id, agent_name=name, status=AgentRunStatus.completed, input_hash=fingerprint))
    db.commit()
    complete_inputs(db, deal)
    added = document(db, deal.id, filename="mai_analizzato.txt")
    assert corpus_fingerprint(db, deal.id)[0] != fingerprint
    from packages.agents.report_agent import IncompleteAnalysisError
    with pytest.raises(IncompleteAnalysisError):
        generate_due_diligence_report(deal.id, db, provider=llm)
    assert all(r.input_hash == fingerprint for r in db.query(AgentRun).filter_by(deal_id=deal.id))


def test_A06_model_page_999_rejected_on_one_page_document(db, seeded, monkeypatch, llm):
    deal = seeded[2]
    source = "The purchaser shall obtain prior written lender consent before any change of control."
    doc = document(db, deal.id, raw_text=source)
    reply = [{"title": "Consent", "clause_type": "change_of_control", "content": source, "page_number": 999, "confidence": 0.99}]
    contract = ContractAgent(provider=StubLLM(json.dumps(reply)))
    payload = contract._extract_clause_payloads(doc.id, source)[0]
    assert payload["page_number"] == 999
    db.add(ClauseFinding(document_id=doc.id, clause_type=ClauseType.change_of_control,
                         title=payload["title"], content=payload["content"], page_number=payload["page_number"], confidence=0.99))
    db.commit()
    aggregator = RedFlagAggregationAgent(provider=llm)
    monkeypatch.setattr(aggregator, "_call_llm_for_flags", lambda *args: [flag_payload(doc.id, source_page=999)])
    aggregator.run(deal.id, db)
    db.commit()
    finding = db.query(RedFlag).filter_by(deal_id=deal.id).one()
    assert doc.page_count == 1 and finding.source_page is None
    complete_inputs(db, deal)
    report = generate_due_diligence_report(deal.id, db, provider=llm)
    assert "999" not in report["markdown"]


def test_A07_aggregator_rejects_other_tenants_document_fk(db, seeded, monkeypatch, llm):
    own_deal = seeded[2]
    document(db, own_deal.id)
    other = User(email="other-tenant@example.com", hashed_password=PASSWORD_HASH)
    db.add(other)
    db.flush()
    workspace = Workspace(name="Other tenant", owner_id=other.id)
    db.add(workspace)
    db.flush()
    foreign_deal = Deal(workspace_id=workspace.id, title="Foreign deal")
    db.add(foreign_deal)
    db.commit()
    foreign_doc = document(db, foreign_deal.id)
    aggregator = RedFlagAggregationAgent(provider=llm)
    monkeypatch.setattr(aggregator, "_call_llm_for_flags", lambda *args: [flag_payload(foreign_doc.id)])
    from packages.agents.deal_analysis_agent import LLMResponseError
    with pytest.raises(LLMResponseError, match="outside this deal"):
        aggregator.run(own_deal.id, db)
    db.rollback()
    assert db.query(RedFlag).filter_by(deal_id=own_deal.id).count() == 0


def test_A08_delete_deal_removes_original_file(client, db, seeded, auth, tmp_path):
    original = tmp_path / "confidential.txt"
    original.write_text("Confidential audit fixture", encoding="utf-8")
    doc = document(db, seeded[2].id, file_path=str(original))
    doc_id, deal_id = doc.id, seeded[2].id
    response = client.delete(f"/deals/{deal_id}", headers=auth)
    assert response.status_code == 204, response.text
    assert db.query(Document).filter_by(id=doc_id).first() is None
    assert not original.exists()
    # Subsequent account erasure cannot find this orphaned key anymore.
    response = client.request("DELETE", "/users/me", headers=auth, json={"password": PASSWORD})
    assert response.status_code == 204
    assert not original.exists()


def test_A09_change_of_control_retains_high_floor():
    agent = FinancialAgent(provider=StubLLM("[]"))
    standalone = agent._heuristic_payloads("Financing: change of control requires lender consent.", [])
    combined = agent._heuristic_payloads("Financial covenant. Financing: change of control requires lender consent.", [])
    assert len(standalone) == len(combined) == 1
    assert standalone[0]["severity"] == "high"
    assert combined[0]["severity"] == "high"
    assert "change-of-control" in combined[0]["title"].lower()


def test_A10_unverified_amount_is_not_document_evidence(db, seeded):
    doc = document(db, seeded[2].id, raw_text="Esiste un finanziamento bancario; il documento non riporta alcun importo.")
    reply = [{"finding_type": "debt_like_item", "title": "Debt", "description": "Debt noted", "severity": "medium", "amount_eur": 987654321.0, "confidence": 0.99}]
    agent = FinancialAgent(provider=StubLLM(json.dumps(reply)))
    payload = agent._financial_payloads_batch(doc.filename, doc.raw_text, doc.id)
    findings = agent._persist_findings(doc, payload, seeded[2].id, db)
    assert "987654321" not in doc.raw_text
    assert findings[0].structured_payload_json["amount_eur"] is None
    assert findings[0].structured_payload_json["amount_source"] == "unverified"


def test_A11_patch_null_clears_nullable_fields(client, db, seeded, auth):
    deal = seeded[2]
    response = client.patch(f"/deals/{deal.id}", headers=auth, json={"description": None, "value": None})
    assert response.status_code == 200, response.text
    assert response.json()["description"] is None
    assert response.json()["value"] is None


def test_A12_password_80_utf8_bytes_returns_validation_error(client):
    response = client.post("/auth/register", json={"email": "longpass@example.com", "password": "é" * 40})
    assert response.status_code == 422, response.text


def test_A13_clause_relevance_receives_complete_tail():
    provider = StubLLM('[{"clause_index": 0, "relevance": "low", "reason": "Boilerplate"}]')
    agent = ContractAgent(provider=provider)
    content = "The following definitions apply. " * 15 + " UNIQUE_RISK_MARKER: termination is immediate if the purchaser changes."
    result = agent._classify_relevance_payloads([dict(clause_type="other", title="General terms", content=content)], "contract.txt", False)
    assert "UNIQUE_RISK_MARKER" in provider.prompts[0]
    assert not result


def test_A14_document_types_normalized_and_validated():
    from packages.agents.deal_analysis_agent import _parse_classification
    assert _parse_classification('{"document_type":"Contract"}')["document_type"] == "contract"
    from packages.agents.deal_analysis_agent import LLMResponseError
    with pytest.raises(LLMResponseError):
        _parse_classification('{"document_type":"made_up_type"}')


def test_password_reset_revokes_previously_issued_access_token(client, db, seeded, auth):
    from app.core.security import create_password_reset_token
    token = create_password_reset_token(seeded[0].email, seeded[0].hashed_password)
    response = client.post('/auth/reset-password', json={'token': token, 'new_password': 'new-audit-password'})
    assert response.status_code == 204
    assert client.get('/users/me', headers=auth).status_code == 401
    assert client.post('/auth/login', data={'username': seeded[0].email, 'password': 'new-audit-password'}).status_code == 200


@pytest.mark.parametrize('quote,amount', [('EUR 1.234,56', 1234.56), ('Euro 1,234.56', 1234.56),
    ('€ 1 234,5', 1234.5), ('EUR 240000', 240000)])
def test_grounded_amount_accepts_verbatim_currency_evidence(quote, amount):
    from packages.agents.evidence import grounded_amount
    assert grounded_amount({'amount_eur': amount, 'amount_evidence': quote}, 'Debito: ' + quote) == (amount, 'document', quote)


@pytest.mark.parametrize('item', [
    {'amount_eur': float('inf'), 'amount_evidence': 'EUR 100'},
    {'amount_eur': 100, 'amount_evidence': 'USD 100'},
    {'amount_eur': 100, 'amount_evidence': 'EUR 100 milioni'},
    {'amount_eur': 100, 'amount_evidence': 'EUR 100 invented'},
    {'amount_eur': 100, 'amount_evidence': None},
])
def test_grounded_amount_rejects_unverified_or_ambiguous_evidence(item):
    from packages.agents.evidence import grounded_amount
    amount, source, evidence = grounded_amount(item, 'EUR 100; USD 100; EUR 100 milioni')
    assert (amount, source, evidence) == (None, 'unverified', None)


def test_verified_page_uses_ingestion_chunks_and_rejects_ambiguous_quote():
    from types import SimpleNamespace
    from packages.agents.evidence import verified_clause_page
    chunks = [SimpleNamespace(page_number=2, content='Consent is required before transfer.')]
    assert verified_clause_page('Consent is required before transfer.', chunks, 3) == 2
    assert verified_clause_page('Consent is required before transfer.', chunks, 1) is None
    chunks.append(SimpleNamespace(page_number=1, content=chunks[0].content))
    assert verified_clause_page(chunks[0].content, chunks, 3) is None


def test_deal_deletion_failure_retains_database_references(client, db, seeded, auth, monkeypatch):
    import app.services.storage as storage
    doc = document(db, seeded[2].id)
    def fail(*args, **kwargs):
        raise OSError('storage temporarily unavailable')
    monkeypatch.setattr(storage, 'delete_file', fail)
    response = client.delete(f'/deals/{seeded[2].id}', headers=auth)
    assert response.status_code == 503
    assert db.query(Document).filter_by(id=doc.id).one().file_path == 'audit-only.txt'


def test_analysis_row_lock_wait_runs_outside_the_event_loop(client, db, seeded, auth, monkeypatch):
    from sqlalchemy.orm import Query
    import app.api.routes.deals as routes
    import app.services.jobs as jobs
    threads = {}
    original = Query.one
    def one(query):
        if query._for_update_arg is not None:
            threads['lock'] = threading.get_ident()
        return original(query)
    async def inactive(*args):
        threads['loop'] = threading.get_ident()
    async def enqueue(*args, **kwargs):
        pass
    monkeypatch.setattr(Query, 'one', one)
    monkeypatch.setattr(routes, '_require_inactive_analysis_job', inactive)
    monkeypatch.setattr(jobs, 'enqueue_or_run', enqueue)
    response = client.post(f'/deals/{seeded[2].id}/analyze', headers=auth)
    assert response.status_code == 202, response.text
    assert threads['lock'] != threads['loop']
