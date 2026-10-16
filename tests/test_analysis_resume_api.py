import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from arq.jobs import JobStatus
from app.main import _fastapi
from app.models.deal import DealStatus
from app.models.agent_run import AgentRun, AgentRunStatus
from packages.agents.analysis_checkpoint import CheckpointError
from packages.agents.analysis_progress import read_progress


@pytest.fixture
def queue(client):
    pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=object()), get=AsyncMock(return_value=None))
    _fastapi.state.arq_pool = pool
    yield pool
    _fastapi.state.arq_pool = None


def test_resume_claims_once_and_uses_same_stable_job(client, db, test_deal, auth_headers, queue):
    with patch('arq.jobs.Job.status', AsyncMock(return_value=JobStatus.not_found)), \
         patch('packages.agents.analysis_checkpoint.validate_resume', return_value=SimpleNamespace()):
        response = client.post(f'/deals/{test_deal.id}/resume-analysis', headers=auth_headers)
        assert response.status_code == 202, response.text
        duplicate = client.post(f'/deals/{test_deal.id}/resume-analysis', headers=auth_headers)
        assert duplicate.status_code == 409
    queue.enqueue_job.assert_awaited_once_with('run_resume_pipeline_for_deal', test_deal.id,
                                               test_deal.workspace.owner_id, _job_id=f'analysis:{test_deal.id}')
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.analyzing


@pytest.mark.parametrize('state', [JobStatus.in_progress, JobStatus.queued])
def test_resume_cannot_overlap_existing_job(client, test_deal, auth_headers, queue, state):
    with patch('arq.jobs.Job.status', AsyncMock(return_value=state)):
        assert client.post(f'/deals/{test_deal.id}/resume-analysis', headers=auth_headers).status_code == 409
    queue.enqueue_job.assert_not_called()


def test_resume_rejects_changed_corpus_without_claim(client, db, test_deal, auth_headers, queue):
    with patch('arq.jobs.Job.status', AsyncMock(return_value=JobStatus.not_found)), \
         patch('packages.agents.analysis_checkpoint.validate_resume', side_effect=CheckpointError('Documenti cambiati')):
        assert client.post(f'/deals/{test_deal.id}/resume-analysis', headers=auth_headers).status_code == 409
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.draft
    queue.enqueue_job.assert_not_called()


def test_resume_queue_unavailable_fails_closed(client, db, test_deal, auth_headers, queue):
    with patch('arq.jobs.Job.status', AsyncMock(side_effect=ConnectionError())):
        assert client.post(f'/deals/{test_deal.id}/resume-analysis', headers=auth_headers).status_code == 503
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.draft
    queue.enqueue_job.assert_not_called()


def test_uncertain_enqueue_keeps_admission_locked(client, db, test_deal, auth_headers, queue):
    queue.enqueue_job.side_effect = ConnectionError()
    with patch('arq.jobs.Job.status', AsyncMock(return_value=JobStatus.not_found)), \
         patch('packages.agents.analysis_checkpoint.validate_resume', return_value=SimpleNamespace()):
        assert client.post(f'/deals/{test_deal.id}/resume-analysis', headers=auth_headers).status_code == 503
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.analyzing


@pytest.mark.parametrize('path,method', [('analysis-checkpoint','get'),('analysis-progress','get'),('resume-analysis','post')])
def test_recovery_endpoints_hide_other_owners(client, db, test_deal, auth_headers, queue, path, method):
    from app.models import User
    other = User(email='other-recovery@example.com', hashed_password='irrelevant')
    db.add(other)
    db.flush()
    test_deal.workspace.owner_id = other.id
    db.commit()
    assert getattr(client, method)(f'/deals/{test_deal.id}/{path}', headers=auth_headers).status_code == 404


def test_active_deal_metadata_and_delete_are_locked(client, db, test_deal, auth_headers):
    test_deal.status = DealStatus.analyzing
    db.commit()
    admission = test_deal.updated_at
    assert client.patch(f'/deals/{test_deal.id}', json={'title':'Changed'}, headers=auth_headers).status_code == 409
    assert client.delete(f'/deals/{test_deal.id}', headers=auth_headers).status_code == 409
    db.refresh(test_deal)
    assert test_deal.updated_at == admission
    assert test_deal.title == 'Test Deal'


def test_progress_is_bound_to_current_run(client, db, test_deal, auth_headers, queue):
    test_deal.status = DealStatus.analyzing
    run = AgentRun(deal_id=test_deal.id, agent_name='encumbrances_review', status=AgentRunStatus.running)
    db.add(run)
    db.commit()
    data = dict(agent_name='encumbrances_review', run_id=run.id, completed_batches=3,
                total_batches=20, document_id=1, updated_at='2026-09-18T07:00:00Z')
    queue.get.return_value = json.dumps(data)
    assert client.get(f'/deals/{test_deal.id}/analysis-progress', headers=auth_headers).json() == data
    queue.get.return_value = json.dumps({**data, 'run_id':run.id+1})
    assert client.get(f'/deals/{test_deal.id}/analysis-progress', headers=auth_headers).json() is None


def test_progress_outage_does_not_fail_analysis():
    pool = SimpleNamespace(get=AsyncMock(side_effect=ConnectionError()))
    assert asyncio.run(read_progress(pool, 1, 2)) is None


def test_fresh_analysis_cannot_be_deduplicated_against_finishing_job(client, db, test_deal, auth_headers, queue):
    with patch('arq.jobs.Job.status', AsyncMock(return_value=JobStatus.in_progress)):
        assert client.post(f'/deals/{test_deal.id}/analyze', headers=auth_headers).status_code == 409
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.draft
    queue.enqueue_job.assert_not_called()


def test_runs_from_previous_analysis_do_not_appear_completed(client, db, test_deal, auth_headers):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    db.add_all([
        AgentRun(deal_id=test_deal.id, agent_name='report_generation', status=AgentRunStatus.completed,
                 started_at=now-timedelta(days=1), completed_at=now-timedelta(hours=23)),
        AgentRun(deal_id=test_deal.id, agent_name='intake', status=AgentRunStatus.completed,
                 started_at=now-timedelta(minutes=3), completed_at=now-timedelta(minutes=2)),
        AgentRun(deal_id=test_deal.id, agent_name='financial_analysis', status=AgentRunStatus.running,
                 started_at=now-timedelta(minutes=1)),
    ])
    db.commit()
    response = client.get(f'/deals/{test_deal.id}/agent-runs', headers=auth_headers)
    assert response.status_code == 200
    assert {row['agent_name'] for row in response.json()} == {'intake', 'financial_analysis'}
