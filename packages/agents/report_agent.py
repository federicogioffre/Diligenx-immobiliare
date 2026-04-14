"""Due-diligence report generation for deals.

Reads ClauseFinding, RedFlag, and Document records that already exist in the
database (produced by ``DealAnalysisAgent``) and asks the LLM to compose a
structured Markdown report.

The report is stored in the ``Report`` table with
``report_type = due_diligence``.  Calling the function again for the same deal
replaces the previous due-diligence report (idempotent).
"""
import logging

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import LLMProvider, get_llm_provider

logger = logging.getLogger(__name__)


def generate_due_diligence_report(
    deal_id: int,
    db: Session,
    provider: LLMProvider | None = None,
) -> dict:
    """Generate (or regenerate) a due-diligence report for *deal_id*.

    Returns::

        {"report_id": int, "deal_id": int, "markdown": str}

    Raises ``ValueError`` if the deal does not exist.
    """
    from app.models.deal import Deal
    from app.models.document import Document, DocumentStatus
    from app.models.clause_finding import ClauseFinding
    from app.models.red_flag import RedFlag
    from app.models.report import Report, ReportType, ReportStatus
    from packages.prompts.deal_prompts import REPORT_GENERATION_PROMPT

    llm = provider or get_llm_provider()

    # ── Validate deal ─────────────────────────────────────────────────── #
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if deal is None:
        raise ValueError(f"Deal {deal_id} not found")

    logger.info("Generating due-diligence report for deal %d ('%s')", deal_id, deal.title)

    # ── Upsert Report row (status = generating) ──────────────────────── #
    report = (
        db.query(Report)
        .filter(
            Report.deal_id == deal_id,
            Report.report_type == ReportType.due_diligence,
        )
        .first()
    )
    if report is None:
        report = Report(
            deal_id=deal_id,
            report_type=ReportType.due_diligence,
            title=f"Due Diligence Report — {deal.title}",
        )
        db.add(report)
    else:
        report.title = f"Due Diligence Report — {deal.title}"

    report.status = ReportStatus.generating
    report.content = None
    db.commit()
    db.refresh(report)
    report_id = report.id  # safe reference even after rollback

    # ── Build context for the prompt ──────────────────────────────────── #
    try:
        from app.models.agent_finding import AgentFinding
        from packages.agents.red_flag_aggregator import AGENT_NAME as AGGREGATOR_AGENT

        documents = (
            db.query(Document)
            .filter(
                Document.deal_id == deal_id,
                Document.status == DocumentStatus.processed,
            )
            .all()
        )

        doc_ids = [d.id for d in documents]
        findings: list[ClauseFinding] = []
        if doc_ids:
            findings = (
                db.query(ClauseFinding)
                .filter(ClauseFinding.document_id.in_(doc_ids))
                .all()
            )

        red_flags = (
            db.query(RedFlag)
            .filter(RedFlag.deal_id == deal_id)
            .all()
        )

        # Observations and information requests produced by the red-flag
        # aggregation agent and stored as AgentFinding rows.
        observations = (
            db.query(AgentFinding)
            .filter(
                AgentFinding.deal_id == deal_id,
                AgentFinding.agent_name == AGGREGATOR_AGENT,
                AgentFinding.category == "observation",
            )
            .all()
        )
        info_requests = (
            db.query(AgentFinding)
            .filter(
                AgentFinding.deal_id == deal_id,
                AgentFinding.agent_name == AGGREGATOR_AGENT,
                AgentFinding.category == "information_request",
            )
            .all()
        )

        deal_info = (
            f"Title: {deal.title}\n"
            f"Description: {deal.description or 'N/A'}\n"
            f"Value: {deal.value or 'N/A'}"
        )

        docs_text = (
            "\n".join(
                f"- {d.filename} (lang={d.language or 'unknown'}, pages={d.page_count or '?'})"
                for d in documents
            )
            or "No processed documents."
        )

        findings_text = (
            "\n".join(
                f"- [{f.clause_type.value}] {f.title}: {f.content[:200]} "
                f"(confidence={f.confidence})"
                for f in findings
            )
            or "No clause findings."
        )

        red_flags_text = (
            "\n".join(
                f"- [{f.severity.value.upper()}] {f.title}: {f.description} "
                f"(category={f.category})"
                for f in red_flags
            )
            or "No red flags detected."
        )

        observations_text = (
            "\n".join(
                f"- [{f.severity.value.upper()}] {f.title}: {f.description}"
                for f in observations
            )
            or "None."
        )

        info_requests_text = (
            "\n".join(
                f"- {f.title}: {f.description}"
                for f in info_requests
            )
            or "None."
        )

        # ── Call LLM ─────────────────────────────────────────────────── #
        prompt = REPORT_GENERATION_PROMPT.format(
            deal_info=deal_info,
            documents=docs_text,
            clause_findings=findings_text,
            red_flags=red_flags_text,
            observations=observations_text,
            information_requests=info_requests_text,
        )
        markdown = llm.complete(prompt, max_tokens=4096)

        # ── Persist result ────────────────────────────────────────────── #
        report.content = markdown
        report.status = ReportStatus.completed
        db.commit()
        db.refresh(report)

        logger.info(
            "Report %d generated for deal %d (%d chars).",
            report.id, deal_id, len(markdown),
        )

        return {
            "report_id": report.id,
            "deal_id": deal_id,
            "markdown": markdown,
        }

    except Exception:
        logger.exception("Report generation failed for deal %d", deal_id)
        db.rollback()
        # Mark as failed — the report was committed before the try block
        report = db.query(Report).filter(Report.id == report_id).first()
        if report:
            report.status = ReportStatus.failed
            db.commit()
        raise
