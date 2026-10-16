"""Failed AI responses must never replace published evidence with partial results."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models.agent_finding import AgentFinding
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.property_profile import PropertyProfile
from app.models.deal import DealStatus
from app.models.document import Document, DocumentStatus
from app.models.open_question import OpenQuestion
from app.models.red_flag import RedFlag
from app.models.report import Report, ReportStatus
from packages.agents.deal_analysis_agent import (
    AnthropicLLMProvider, FakeLLMProvider, LLMResponseError,
    _parse_llm_items, _safe_json,
)
from packages.agents.orchestrator import run_deal_analysis_pipeline
from packages.agents.report_agent import generate_due_diligence_report
from packages.real_estate.fake_provider import FakeRealEstateLLMProvider

DOSSIER = {
    'Atto_compravendita.txt': (
        'ATTO DI COMPRAVENDITA in data 12/03/2015. Appartamento al Foglio 12 particella 345 sub. 5, '
        'categoria A/2. ACQUIRENTI: Mario Rossi\nPervenuto per atto di donazione trascritto il 10/05/2010.'
    ),
    'Visura_catastale.txt': (
        'VISURA CATASTALE. Foglio 12 particella 345 sub. 5 categoria A/2. INTESTATI: Mario Rossi'
    ),
    'Ispezione_ipotecaria.txt': (
        'ISPEZIONE IPOTECARIA. Ipoteca volontaria iscritta in data 01/06/2015 a favore di Banca S.p.A.'
    ),
    'Perizia_tecnica.txt': (
        'PERIZIA. Foglio 12 particella 345 sub. 5. Certificato di agibilità non rilasciato.'
    ),
    'Verbale_assemblea.txt': (
        'VERBALE DI ASSEMBLEA. Approvati lavori straordinari di rifacimento della facciata.'
    ),
}


class BadResponse(FakeRealEstateLLMProvider):
    def __init__(self, marker, response='[{"title": "partial"}, {"title":'):
        self.marker = marker
        self.response = response

    def complete(self, prompt, max_tokens=2048):
        if self.marker in prompt.upper():
            return self.response
        return super().complete(prompt, max_tokens)


@pytest.fixture
def analyzed(db, test_deal):
    for filename, text in DOSSIER.items():
        db.add(Document(
            deal_id=test_deal.id, filename=filename, file_path='/tmp/' + filename,
            mime_type='text/plain', file_size=200, status=DocumentStatus.processed,
            raw_text=text, language='it',
        ))
    db.commit()
    result = run_deal_analysis_pipeline(test_deal.id, db, provider=FakeRealEstateLLMProvider())
    assert result['completed'], result
    return test_deal


def rows(db, model, **filters):
    query = db.query(model).filter_by(**filters).order_by(model.id)
    return [tuple(getattr(row, col.name) for col in model.__table__.columns) for row in query]


@pytest.mark.parametrize(('stage', 'marker', 'model', 'filters'), [
    ('document_routing', 'CLASSIFY', AgentFinding, {'agent_name': 'document_router'}),
    ('property_identity', 'EXTRACT PROPERTY IDENTIFICATION', PropertyProfile, {}),
    ('title_chain_review', 'REVIEW TITLE CHAIN', AgentFinding, {'agent_name': 'title_chain_review'}),
    ('encumbrances_review', 'REVIEW ENCUMBRANCES', AgentFinding, {'agent_name': 'encumbrances_review'}),
    ('building_cadastral_review', 'REVIEW BUILDING AND CADASTRAL COMPLIANCE', AgentFinding,
     {'agent_name': 'building_cadastral_review'}),
    ('condominium_occupancy_review', 'REVIEW CONDOMINIUM AND OCCUPANCY', AgentFinding,
     {'agent_name': 'condominium_occupancy_review'}),
    ('red_flag_aggregation', 'RED FLAGS', RedFlag, {}),
    ('report_generation', 'EXECUTIVE SUMMARY', Report, {}),
])
def test_failed_retry_preserves_previous_outputs(db, analyzed, stage, marker, model, filters):
    before = rows(db, model, **filters)
    assert before, 'The baseline must contain data owned by the failing stage'
    old_flags = rows(db, RedFlag)
    old_questions = rows(db, OpenQuestion)
    old_report = rows(db, Report)
    provider = BadResponse(marker, ' ' if stage == 'report_generation' else '{broken')

    result = run_deal_analysis_pipeline(analyzed.id, db, provider=provider)

    assert not result['completed']
    assert 'error' in result['stages'][stage]
    assert 'error' in result['stages']['report_generation']
    assert rows(db, model, **filters) == before
    assert rows(db, Report) == old_report
    if stage != 'report_generation':
        assert 'error' in result['stages']['red_flag_aggregation']
        assert rows(db, RedFlag) == old_flags
        assert rows(db, OpenQuestion) == old_questions
    db.refresh(analyzed)
    assert analyzed.status == DealStatus.draft
    report_run = db.query(AgentRun).filter_by(agent_name='report_generation').one()
    assert report_run.status == AgentRunStatus.failed


@pytest.mark.parametrize('response', [
    '[{"title": "partial"}, {"title":', '{"error": "unavailable"}', '[{}]',
    '[{"title": "partial"}, null]',
])
def test_invalid_aggregation_never_publishes_a_first_report(db, test_deal, response):
    result = run_deal_analysis_pipeline(
        test_deal.id, db, provider=BadResponse('RED FLAGS', response),
    )
    assert not result['completed']
    assert 'error' in result['stages']['red_flag_aggregation']
    assert db.query(Report).count() == 0


def test_valid_empty_array_can_replace_old_findings(db, analyzed):
    assert db.query(RedFlag).count() > 0
    result = run_deal_analysis_pipeline(analyzed.id, db, provider=BadResponse('RED FLAGS', '[]'))
    assert result['completed'], result
    assert db.query(RedFlag).count() == 0
    assert db.query(Report).one().status == ReportStatus.completed


def test_successful_retry_recovers_after_failed_analysis(db, analyzed):
    failed = run_deal_analysis_pipeline(analyzed.id, db, provider=BadResponse('CLASSIFY', '[]'))
    assert not failed['completed']
    recovered = run_deal_analysis_pipeline(analyzed.id, db, provider=FakeRealEstateLLMProvider())
    assert recovered['completed'], recovered
    assert all(run.status == AgentRunStatus.completed for run in db.query(AgentRun))
    assert analyzed.status == DealStatus.reviewed


def test_later_review_batch_failure_preserves_the_documents_previous_findings(db, analyzed, monkeypatch):
    from packages.real_estate.review_agent import DocumentReviewAgent

    monkeypatch.setattr(DocumentReviewAgent, 'BATCH_CHARS', 1000)
    doc = db.query(Document).filter_by(filename='Ispezione_ipotecaria.txt').one()
    doc.raw_text = doc.raw_text + ('\nAnnotazione di rito senza effetti.' * 60)
    db.commit()
    before_failed_doc = rows(db, AgentFinding, agent_name='encumbrances_review', document_id=doc.id)
    assert before_failed_doc

    class FailLaterBatch(FakeRealEstateLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            if ('REVIEW ENCUMBRANCES' in prompt.upper() and 'Annotazione di rito' in prompt
                    and 'Ipoteca volontaria' not in prompt):
                return '[{"finding_type":'
            return super().complete(prompt, max_tokens)

    result = run_deal_analysis_pipeline(analyzed.id, db, provider=FailLaterBatch())
    # One document's failed request is a recorded gap, not a failed stage:
    # that document keeps its previous findings, the others are re-analysed.
    stage = result['stages']['encumbrances_review']
    assert 'error' not in stage
    assert [entry['filename'] for entry in stage['failed_documents']] == ['Ispezione_ipotecaria.txt']
    assert rows(db, AgentFinding, agent_name='encumbrances_review', document_id=doc.id) == before_failed_doc


def test_manual_report_failure_preserves_published_report(db, analyzed):
    before = rows(db, Report)

    class Unavailable(FakeLLMProvider):
        def complete(self, prompt, max_tokens=2048):
            raise RuntimeError('provider unavailable')

    with pytest.raises(RuntimeError, match='provider unavailable'):
        generate_due_diligence_report(analyzed.id, db, provider=Unavailable())
    assert rows(db, Report) == before


def test_manual_report_retry_clears_failure_in_progress_view(db, analyzed):
    failed = run_deal_analysis_pipeline(
        analyzed.id, db, provider=BadResponse('EXECUTIVE SUMMARY', ' '),
    )
    assert not failed['completed']
    generate_due_diligence_report(analyzed.id, db, provider=FakeRealEstateLLMProvider())
    run = db.query(AgentRun).filter_by(agent_name='report_generation').one()
    assert run.status == AgentRunStatus.completed
    assert run.error_message is None
    assert analyzed.status == DealStatus.reviewed


@pytest.mark.parametrize('status', [AgentRunStatus.failed, AgentRunStatus.running])
def test_manual_report_endpoint_blocks_incomplete_analysis(
    db, analyzed, client, auth_headers, status,
):
    old_report = rows(db, Report)
    run = db.query(AgentRun).filter_by(agent_name='encumbrances_review').one()
    run.status = status
    db.commit()
    response = client.post(f'/deals/{analyzed.id}/report', headers=auth_headers)
    assert response.status_code == 409, response.text
    assert rows(db, Report) == old_report
    response = client.get(f'/deals/{analyzed.id}/report', headers=auth_headers)
    assert response.status_code == 200


@pytest.mark.parametrize('raw', ['[{"title": "valid"},', '[{"title": "valid"}, {"title": "cut'])
def test_truncated_json_prefix_is_never_salvaged(raw):
    with pytest.raises(LLMResponseError, match='incomplete or invalid'):
        _safe_json(raw)


def test_valid_escaped_backslash_and_apostrophe_are_unchanged():
    value = [{"content": "literal backslash \\'quoted'"}]
    assert _safe_json(json.dumps(value)) == value


def test_manual_report_endpoint_blocks_queued_analysis(db, analyzed, client, auth_headers):
    # The request marks the deal analyzing before the worker replaces old runs.
    analyzed.status = DealStatus.analyzing
    db.commit()
    response = client.post(f'/deals/{analyzed.id}/report', headers=auth_headers)
    assert response.status_code == 409, response.text


@pytest.mark.parametrize('raw', ['null', '{}', '[null]', '[{}]', '[1]', '[{"title": "ok"}, "bad"]'])
def test_unusable_item_array_fails_instead_of_becoming_empty(raw):
    with pytest.raises(LLMResponseError):
        _parse_llm_items(raw, context='test extraction')


@pytest.mark.parametrize(('stop_reason', 'blocks'), [
    ('max_tokens', [SimpleNamespace(text='[]')]),
    ('end_turn', []),
    ('end_turn', [SimpleNamespace(text=' ')]),
    ('end_turn', [SimpleNamespace(type='thinking')]),
])
def test_anthropic_rejects_truncated_or_empty_output(stop_reason, blocks):
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(stop_reason=stop_reason, content=blocks)
    with patch('anthropic.Anthropic', return_value=client):
        provider = AnthropicLLMProvider(api_key='test', model='claude-sonnet-4-6')
    with pytest.raises(LLMResponseError):
        provider.complete('Analyze this document')
