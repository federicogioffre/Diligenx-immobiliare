"""Review protocol, stale analysis and preservation of published reports."""
import json

from packages.agents.grounding_review import review_payload

import pytest

from app.models.red_flag import RedFlag, Severity
from app.models.report import Report
from packages.agents.deal_analysis_agent import FakeLLMProvider, LLMResponseError
from packages.agents.report_agent import generate_due_diligence_report
from tests.report_fixtures import complete_report_inputs


def prepare(db, deal):
    deal.report_language = 'it'
    flag = RedFlag(deal_id=deal.id, title='Violazione del covenant DSCR',
                   issue='DSCR 0,85 rispetto al minimo 1,20; non è documentata una deroga.',
                   risk='La banca può richiedere il rimborso dopo un termine di rimedio di 30 giorni dalla contestazione scritta.',
                   recommendation='Ottenere dalla banca una soluzione concordata prima del perfezionamento.',
                   severity=Severity.high, category='covenant')
    db.add(flag)
    complete_report_inputs(db, deal)


class SummaryReviewer(FakeLLMProvider):
    def __init__(self, db, supported=True, wrong_language=False):
        self.db, self.supported, self.wrong_language = db, supported, wrong_language
        self.review_payload = None

    def complete(self, prompt, **kwargs):
        # Neither generation nor review should hold an idle DB connection.
        assert not self.db.in_transaction()
        if 'GROUNDING REVIEW\n' in prompt:
            data = review_payload(prompt)
            self.review_payload = data
            context = json.loads(data['documents'][0]['text'])
            assert context['documents_reviewed'] == 1
            assert context['severity_counts']['high'] == 1
            corrected = ('La banca può richiedere il rimborso dopo un termine di rimedio '
                         'di 30 giorni dalla contestazione scritta.')
            if self.wrong_language:
                corrected = 'The bank can demand repayment after the expiry of the cure period.'
            return json.dumps([{'index': 0, 'supported': self.supported,
                                'fields': {'text': corrected},
                                'evidence': [{'source_document_id': 1,
                                              'quote': data['documents'][1]['text'],
                                              'fields': ['text']}]}])
        return 'Il rimborso è immediatamente esigibile per la violazione del covenant.'


def test_review_repairs_summary_before_publication(db, test_deal):
    prepare(db, test_deal)
    provider = SummaryReviewer(db)
    result = generate_due_diligence_report(test_deal.id, db, provider=provider)
    summary = result['markdown'].split('## 3. Executive Summary')[1].split('## 4.')[0]
    assert '30 giorni dalla contestazione scritta' in summary
    assert 'immediatamente esigibile' not in summary
    assert provider.review_payload['language'] == 'it'


@pytest.mark.parametrize('wrong_language', [False, True])
def test_failed_review_preserves_previous_report(db, test_deal, wrong_language):
    prepare(db, test_deal)
    previous = generate_due_diligence_report(test_deal.id, db, provider=FakeLLMProvider())['markdown']
    provider = SummaryReviewer(db, supported=wrong_language, wrong_language=wrong_language)
    with pytest.raises(LLMResponseError):
        generate_due_diligence_report(test_deal.id, db, provider=provider)
    assert db.query(Report).filter_by(deal_id=test_deal.id).one().content == previous


def test_analysis_revision_blocks_old_reports_and_resume(client, auth_headers, db, test_deal, monkeypatch):
    import packages.agents.analysis_checkpoint as checkpoint
    original_revision = checkpoint.ANALYSIS_REVISION
    # Also exercise deals without target names or transaction context.
    test_deal.target_company_names = None
    test_deal.report_language = 'en'
    test_deal.status = 'reviewed'
    monkeypatch.setattr(checkpoint, 'ANALYSIS_REVISION', original_revision - 1)
    complete_report_inputs(db, test_deal)
    old = generate_due_diligence_report(test_deal.id, db, provider=FakeLLMProvider())['markdown']
    monkeypatch.setattr(checkpoint, 'ANALYSIS_REVISION', original_revision)
    response = client.get(f'/deals/{test_deal.id}/report', headers=auth_headers)
    assert response.json()['stale'] is True
    assert response.json()['generation_available'] is False
    assert response.json()['markdown'] == old
    assert client.post(f'/deals/{test_deal.id}/report', headers=auth_headers).status_code == 409
    assert client.get(f'/deals/{test_deal.id}/report/export?format=docx', headers=auth_headers).status_code == 409
    with pytest.raises(checkpoint.CheckpointError):
        checkpoint.validate_resume(db, test_deal.id)


@pytest.mark.parametrize('change', ['metadata', 'same_corpus_reanalysis'])
def test_concurrent_change_during_model_call_cannot_overwrite_report(db, test_deal, change):
    from datetime import timedelta
    from sqlalchemy.orm import Session
    from app.models.deal import Deal
    from app.models.agent_run import AgentRun
    from packages.agents.report_agent import IncompleteAnalysisError

    prepare(db, test_deal)
    deal_id = test_deal.id
    previous = generate_due_diligence_report(deal_id, db, provider=FakeLLMProvider())['markdown']

    class ConcurrentWriter(FakeLLMProvider):
        changed = False
        def complete(self, prompt, **kwargs):
            assert not db.in_transaction()
            if not self.changed:
                self.changed = True
                with Session(db.get_bind()) as other:
                    if change == 'metadata':
                        other.query(Deal).filter_by(id=deal_id).one().title = 'Edited while the provider is running'
                    else:
                        # Same corpus hash, newer analysis generation.
                        for run in other.query(AgentRun).filter_by(deal_id=deal_id):
                            run.started_at += timedelta(seconds=1)
                            run.completed_at += timedelta(seconds=1)
                    other.commit()
            return super().complete(prompt, **kwargs)

    with pytest.raises(IncompleteAnalysisError):
        generate_due_diligence_report(deal_id, db, provider=ConcurrentWriter())
    assert db.query(Report).filter_by(deal_id=deal_id).one().content == previous
