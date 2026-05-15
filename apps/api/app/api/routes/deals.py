import asyncio
import json
import logging
from datetime import timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from app.core.limiter import limiter
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.agent_run import AgentRun
from app.models.deal import Deal
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.agent_run import AgentRunRead
from app.schemas.clause_finding import ClauseFindingRead
from app.schemas.missing_document import MissingDocumentRead
from app.schemas.open_question import OpenQuestionRead
from app.schemas.red_flag import RedFlagRead
from app.schemas.deal import (
    DealCreate,
    DealUpdate,
    DealRead,
    DealAnalysisResponse,
    DealQuestionRequest,
    DealQuestionResponse,
    RiskScoreResponse,
)
from app.schemas.report import ReportGenerateResponse
from app.services.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_user_workspace(db: Session, workspace_id: int, user: User) -> Workspace:
    ws = (
        db.query(Workspace)
        .filter(Workspace.id == workspace_id, Workspace.owner_id == user.id)
        .first()
    )
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.get("/", response_model=list[DealRead])
def list_deals(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_workspace(db, workspace_id, current_user)
    return db.query(Deal).filter(Deal.workspace_id == workspace_id).all()


@router.post("/", response_model=DealRead, status_code=201)
def create_deal(
    workspace_id: int,
    payload: DealCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_workspace(db, workspace_id, current_user)
    deal = Deal(**payload.model_dump(), workspace_id=workspace_id)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


@router.get("/{deal_id}", response_model=DealRead)
def get_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@router.patch("/{deal_id}", response_model=DealRead)
def update_deal(
    deal_id: int,
    payload: DealUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if payload.title is not None:
        deal.title = payload.title
    if payload.description is not None:
        deal.description = payload.description
    if payload.value is not None:
        deal.value = payload.value

    db.commit()
    db.refresh(deal)
    return deal


@router.delete("/{deal_id}", status_code=204)
def delete_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    db.delete(deal)
    db.commit()


def _run_pipeline_background(deal_id: int) -> None:
    """Run the analysis pipeline in a background task with its own DB session."""
    from app.db.session import SessionLocal
    from packages.agents.orchestrator import run_deal_analysis_pipeline

    db = SessionLocal()
    try:
        run_deal_analysis_pipeline(deal_id, db)
    except Exception:
        logger.exception("Background analysis pipeline failed for deal %d", deal_id)
    finally:
        db.close()


@router.post("/{deal_id}/analyze", response_model=DealAnalysisResponse, status_code=202)
@limiter.limit("5/minute")
async def analyze_deal(
    request: Request,
    deal_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger the multi-agent analysis pipeline asynchronously.

    Returns **202 Accepted** immediately after queuing the pipeline.  The
    pipeline runs in a background task (intake → routing → contracts →
    corporate → red-flags → report) and updates deal status and agent-run
    records as it progresses.

    Poll ``GET /deals/{deal_id}/agent-runs`` or ``GET /deals/{deal_id}``
    (deal.status transitions from ``analyzing`` → ``reviewed`` / ``draft``)
    to track progress.
    """
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    # Flip status immediately so the UI knows analysis has started.
    from app.models.deal import DealStatus
    deal.status = DealStatus.analyzing
    db.commit()
    db.refresh(deal)

    from app.services.jobs import enqueue_or_run
    await enqueue_or_run(
        request, background_tasks,
        "run_pipeline_for_deal", _run_pipeline_background, deal_id,
    )

    return DealAnalysisResponse(
        deal_id=deal_id,
        status=deal.status,
        completed=False,
        documents_analyzed=0,
        clause_findings_count=0,
        red_flags_count=0,
        open_questions_count=0,
        report_id=None,
        stages=None,
    )


@router.post("/{deal_id}/report", response_model=ReportGenerateResponse)
def generate_report(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a due-diligence report for a deal.

    Reads existing ClauseFinding and RedFlag records (produced by the
    ``/analyze`` endpoint) and asks the LLM to compose a structured
    Markdown report.  Idempotent: re-running replaces the previous report.
    """
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    from packages.agents.report_agent import generate_due_diligence_report

    try:
        result = generate_due_diligence_report(deal_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception("Report generation failed for deal %d", deal_id)
        raise HTTPException(status_code=500, detail="Report generation failed")

    return result


@router.post("/{deal_id}/ask", response_model=DealQuestionResponse)
def ask_deal_question(
    deal_id: int,
    payload: DealQuestionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ask a question about the documents in a deal.

    Uses retrieval-augmented generation: relevant document chunks are
    fetched via embedding similarity, then passed as context to the LLM
    which produces an answer with source citations.
    """
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    from packages.agents.deal_qa_agent import answer_deal_question

    try:
        result = answer_deal_question(deal_id, payload.question, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        logger.exception("Q&A failed for deal %d", deal_id)
        raise HTTPException(status_code=500, detail="Question answering failed")

    return result


@router.get("/{deal_id}/agent-runs", response_model=list[AgentRunRead])
def list_agent_runs(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all agent execution records for a deal in pipeline order.

    Returns one :class:`~app.schemas.agent_run.AgentRunRead` entry per
    agent stage that has been executed (or is currently running).  Rows are
    ordered by ``started_at`` ascending so that the response reflects the
    natural pipeline sequence: intake → routing → specialist → corporate →
    red-flag → report.

    Includes ``duration_seconds`` (computed from the two timestamp columns)
    and ``error_message`` for failed stages, making this endpoint the primary
    observability surface for the multi-agent pipeline.

    Returns an empty list for deals that have never been analysed.
    """
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    return (
        db.query(AgentRun)
        .filter(AgentRun.deal_id == deal_id)
        .order_by(AgentRun.started_at.asc().nulls_last())
        .all()
    )


@router.get("/{deal_id}/clause-findings", response_model=list[ClauseFindingRead])
def list_clause_findings(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all clause findings for documents in a deal."""
    from app.models.document import Document
    from app.models.clause_finding import ClauseFinding

    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    doc_ids = [
        row.id
        for row in db.query(Document.id).filter(Document.deal_id == deal_id).all()
    ]
    if not doc_ids:
        return []

    return (
        db.query(ClauseFinding)
        .filter(ClauseFinding.document_id.in_(doc_ids))
        .order_by(ClauseFinding.id.asc())
        .all()
    )


@router.get("/{deal_id}/red-flags", response_model=list[RedFlagRead])
def list_red_flags(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all red flags for a deal."""
    from app.models.red_flag import RedFlag

    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    return (
        db.query(RedFlag)
        .filter(RedFlag.deal_id == deal_id)
        .order_by(RedFlag.id.asc())
        .all()
    )


@router.get("/{deal_id}/open-questions", response_model=list[OpenQuestionRead])
def list_open_questions(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List unresolved follow-up questions raised by the analysis pipeline.

    Ordered by priority (high → low) and then by id, so the most actionable
    items appear at the top of the list in the UI.
    """
    from app.models.open_question import OpenQuestion, Priority

    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    # SQLAlchemy can't sort a Python enum directly across SQLite/Postgres in a
    # portable way, so we build the priority ranking with a CASE expression.
    from sqlalchemy import case

    priority_rank = case(
        (OpenQuestion.priority == Priority.high, 0),
        (OpenQuestion.priority == Priority.medium, 1),
        (OpenQuestion.priority == Priority.low, 2),
        else_=3,
    )

    return (
        db.query(OpenQuestion)
        .filter(OpenQuestion.deal_id == deal_id)
        .order_by(priority_rank.asc(), OpenQuestion.id.asc())
        .all()
    )


@router.get("/{deal_id}/missing-documents", response_model=list[MissingDocumentRead])
def list_missing_documents(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List documents the intake agent expected to find but didn't.

    Same priority ordering as open-questions so the two lists feel consistent
    when rendered side by side.
    """
    from app.models.missing_document import MissingDocument
    from app.models.open_question import Priority

    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    from sqlalchemy import case

    priority_rank = case(
        (MissingDocument.priority == Priority.high, 0),
        (MissingDocument.priority == Priority.medium, 1),
        (MissingDocument.priority == Priority.low, 2),
        else_=3,
    )

    return (
        db.query(MissingDocument)
        .filter(MissingDocument.deal_id == deal_id)
        .order_by(priority_rank.asc(), MissingDocument.id.asc())
        .all()
    )


@router.get("/{deal_id}/report", response_model=ReportGenerateResponse)
def get_report(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch the existing due-diligence report for a deal (no LLM call).

    Returns 404 if no report has been generated yet.
    """
    from app.models.report import Report, ReportType

    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    report = (
        db.query(Report)
        .filter(
            Report.deal_id == deal_id,
            Report.report_type == ReportType.due_diligence,
        )
        .order_by(Report.id.desc())
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="No report generated yet")

    return ReportGenerateResponse(
        report_id=report.id,
        deal_id=deal_id,
        markdown=report.content or "",
    )


@router.get("/{deal_id}/report/export")
def export_report(
    deal_id: int,
    format: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download the due-diligence report as a branded PDF or DOCX.

    Query param `format` must be 'pdf' or 'docx'. Returns 404 if the deal
    does not exist (or doesn't belong to the caller) or if no report has
    been generated yet. Returns 400 for an invalid format.
    """
    from app.models.report import Report, ReportType

    fmt = (format or "").lower()
    if fmt not in ("pdf", "docx"):
        raise HTTPException(status_code=400, detail="format must be 'pdf' or 'docx'")

    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    report = (
        db.query(Report)
        .filter(
            Report.deal_id == deal_id,
            Report.report_type == ReportType.due_diligence,
        )
        .order_by(Report.id.desc())
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="No report generated yet")

    from app.services.report_export import render_docx, render_pdf

    try:
        if fmt == "pdf":
            data = render_pdf(deal, report)
            media_type = "application/pdf"
            ext = "pdf"
        else:
            data = render_docx(deal, report)
            media_type = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            ext = "docx"
    except Exception:
        logger.exception("Report export failed for deal %d (%s)", deal_id, fmt)
        raise HTTPException(status_code=500, detail="Export failed")

    filename = f"diligenx_report_deal-{deal_id}.{ext}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{deal_id}/risk-score", response_model=RiskScoreResponse)
def get_risk_score(
    deal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Compute a 0–100 risk score for a deal from its existing analysis outputs.

    The score is **deterministic** — no LLM call is made.  It is derived from
    the counts and severities of RedFlag, AgentFinding (observations /
    information_requests) and MissingDocument rows already stored for the deal.

    Returns 404 if the deal does not exist or the user does not own it.
    Returns a score of 100 with empty categories if no analysis has been run yet.
    """
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == current_user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    from packages.agents.scoring_service import compute_risk_score

    try:
        result = compute_risk_score(deal_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return result


# Pipeline stage order for predictable SSE output
_PIPELINE_STAGES = [
    "intake",
    "document_router",
    "contract_analysis",
    "corporate_governance",
    "red_flag_aggregation",
    "report_generation",
]


@router.get("/{deal_id}/analysis-stream")
async def stream_analysis_progress(
    deal_id: int,
    token: str,
    db: Session = Depends(get_db),
):
    """Server-Sent Events stream for real-time pipeline progress.

    Emits one JSON event per second with the current deal status and a
    snapshot of all 6 pipeline stages.  The stream closes automatically
    when the deal leaves ``analyzing`` status (pipeline finished or failed).

    Authentication uses a ``?token=<jwt>`` query parameter because the
    browser ``EventSource`` API cannot send custom headers.  The token is
    the same JWT used for all other API calls.

    SSE format::

        data: {"deal_status": "analyzing", "stages": [...]}\\n\\n

    Connect directly to ``http://localhost:8000`` — do **not** route
    through the Next.js proxy, which buffers the full response before
    forwarding and breaks streaming.
    """
    from app.core.security import decode_token

    # Auth: validate JWT passed as query param (EventSource limitation)
    email = decode_token(token)
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # Ownership check using the injected (short-lived) db session
    deal = (
        db.query(Deal)
        .join(Deal.workspace)
        .filter(Deal.id == deal_id, Workspace.owner_id == user.id)
        .first()
    )
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    async def event_generator():
        from app.db.session import SessionLocal
        from app.models.agent_run import AgentRun
        from app.models.deal import Deal as DealModel

        stream_db = SessionLocal()
        try:
            while True:
                # Force fresh reads on every tick (bypass SQLAlchemy identity cache)
                stream_db.expire_all()

                fresh_deal = stream_db.query(DealModel).filter(DealModel.id == deal_id).first()
                if fresh_deal is None:
                    break

                runs = (
                    stream_db.query(AgentRun)
                    .filter(AgentRun.deal_id == deal_id)
                    .order_by(AgentRun.started_at.asc().nulls_last())
                    .all()
                )
                run_by_name = {r.agent_name: r for r in runs}

                stages = []
                for name in _PIPELINE_STAGES:
                    run = run_by_name.get(name)
                    if run:
                        # Compute duration without relying on the model property
                        duration = None
                        if run.started_at and run.completed_at:
                            s = run.started_at
                            c = run.completed_at
                            if s.tzinfo is None:
                                s = s.replace(tzinfo=timezone.utc)
                            if c.tzinfo is None:
                                c = c.replace(tzinfo=timezone.utc)
                            duration = round((c - s).total_seconds(), 2)
                        stages.append({
                            "agent_name": name,
                            "status": run.status.value,
                            "started_at": run.started_at.isoformat() if run.started_at else None,
                            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                            "duration_seconds": duration,
                            "error_message": run.error_message,
                        })
                    else:
                        stages.append({
                            "agent_name": name,
                            "status": "pending",
                            "started_at": None,
                            "completed_at": None,
                            "duration_seconds": None,
                            "error_message": None,
                        })

                payload = {
                    "deal_status": fresh_deal.status.value,
                    "stages": stages,
                }
                yield f"data: {json.dumps(payload)}\n\n"

                # Stop streaming once the pipeline has finished
                if fresh_deal.status.value != "analyzing":
                    break

                await asyncio.sleep(1)
        finally:
            stream_db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if present
        },
    )
