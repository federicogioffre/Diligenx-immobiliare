"""Explicit prerequisite evidence for report-rendering tests."""
from datetime import datetime, timedelta, timezone
from app.models.document import Document, DocumentStatus
from app.models.agent_run import AgentRun, AgentRunStatus
from packages.agents.analysis_checkpoint import corpus_fingerprint, STAGES


def complete_report_inputs(db, deal):
    if not db.query(Document).filter_by(deal_id=deal.id).count():
        db.add(Document(deal_id=deal.id, filename="report-source.txt", file_path="report-source.txt",
                        mime_type="text/plain", file_size=10, raw_text="Report source fixture",
                        page_count=1, status=DocumentStatus.processed))
        db.flush()
    fingerprint, _ = corpus_fingerprint(db, deal.id)
    start = datetime.now(timezone.utc) - timedelta(minutes=2)
    for i, (_, name) in enumerate(STAGES[:-1]):
        run = db.query(AgentRun).filter_by(deal_id=deal.id, agent_name=name).first()
        if run is None:
            run = AgentRun(deal_id=deal.id, agent_name=name)
            db.add(run)
        run.status = AgentRunStatus.completed
        run.started_at = start + timedelta(seconds=2*i)
        run.completed_at = run.started_at + timedelta(seconds=1)
        run.input_hash = fingerprint
    db.commit()
    return fingerprint
