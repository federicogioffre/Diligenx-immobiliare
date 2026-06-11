"""Corporate Introductory Information extraction agent.

Populates ``CompanyProfile`` rows — the structured equivalent of the
"Corporate Introductory Information" table in professional red-flag DD
reports. For each target company described in the deal's corporate
documents (visure camerali, atti costitutivi, statuti, patti parasociali),
the agent extracts the standard fields (legal form, registered office,
capital, shareholders, board, auditors, business, fiscal year, duration)
via an LLM with strict grounding rules.

Auto-detection
--------------
When ``document_ids`` is *None*, every *processed* document in the deal is
inspected and only those that look corporate (filename or first 1500
chars of body text contain corporate keywords) are sent to the LLM.

Idempotency
-----------
Re-running for the same deal deletes this agent's previous ``AgentRun``
and ``CompanyProfile`` rows before writing fresh results.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    get_llm_provider,
    _safe_json,
)

logger = logging.getLogger(__name__)


AGENT_NAME = "corporate_intro_extraction"

# Reused / extended from corporate_agent — these match the typical filenames
# and first lines of Italian corporate documents.
_CORPORATE_INTRO_KEYWORDS = [
    # English
    "articles of association",
    "memorandum of association",
    "bylaws",
    "by-laws",
    "shareholder agreement",
    "shareholders agreement",
    "shareholders' agreement",
    "certificate of incorporation",
    # Italian
    "visura",
    "atto costitutivo",
    "statuto sociale",
    "statuto",
    "patto parasociale",
    "patti parasociali",
    "camera di commercio",
    "registro delle imprese",
]

_MIN_PROFILE_CONFIDENCE = 0.55
_TEXT_MAX_CHARS = 12000


class CorporateIntroAgent:
    """Extract Corporate Introductory Information for each target company.

    Usage::

        agent = CorporateIntroAgent()
        result = agent.run(deal_id, db)
    """

    AGENT_NAME = AGENT_NAME

    def __init__(self, provider: LLMProvider | None = None):
        self._llm = provider or get_llm_provider()

    def run(
        self,
        deal_id: int,
        db: Session,
        document_ids: set[int] | None = None,
    ) -> dict:
        """Extract CompanyProfile rows for *deal_id*.

        Returns::

            {
                "deal_id": int,
                "documents_analysed": int,
                "company_profiles_count": int,
            }
        """
        from app.models.deal import Deal
        from app.models.agent_run import AgentRun, AgentRunStatus
        from app.models.company_profile import CompanyProfile

        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        logger.info(
            "[%s] deal=%d ('%s') — starting corporate intro extraction",
            self.AGENT_NAME, deal_id, deal.title,
        )

        # Idempotency: clear this agent's previous run + previous profiles.
        db.query(AgentRun).filter(
            AgentRun.deal_id == deal_id,
            AgentRun.agent_name == self.AGENT_NAME,
        ).delete(synchronize_session=False)
        db.query(CompanyProfile).filter(
            CompanyProfile.deal_id == deal_id,
        ).delete(synchronize_session="fetch")
        db.flush()

        run = AgentRun(
            deal_id=deal_id,
            agent_name=self.AGENT_NAME,
            status=AgentRunStatus.running,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()
        started = datetime.now(timezone.utc)

        try:
            documents = self._resolve_documents(db, deal_id, document_ids)
            profiles: list = []
            for doc in documents:
                profiles.extend(self._extract_for_document(doc, deal_id, db))

            db.flush()

            run.status = AgentRunStatus.completed
            run.completed_at = datetime.now(timezone.utc)

            duration = (run.completed_at - started).total_seconds()
            result = {
                "deal_id": deal_id,
                "documents_analysed": len(documents),
                "company_profiles_count": len(profiles),
            }
            logger.info(
                "[%s] deal=%d — completed in %.2fs: %s",
                self.AGENT_NAME, deal_id, duration, result,
            )
            db.commit()
            return result

        except Exception as exc:
            logger.exception("[%s] deal=%d — analysis failed", self.AGENT_NAME, deal_id)
            db.rollback()
            run = db.query(AgentRun).filter(AgentRun.id == run.id).first()
            if run:
                run.status = AgentRunStatus.failed
                run.completed_at = datetime.now(timezone.utc)
                run.error_message = str(exc)[:1000]
                db.commit()
            raise

    # ── Internals ──────────────────────────────────────────────────────────

    def _resolve_documents(
        self, db: Session, deal_id: int, document_ids: set[int] | None
    ) -> list:
        from app.models.document import Document, DocumentStatus

        if document_ids is not None and not document_ids:
            return []

        q = db.query(Document).filter(
            Document.deal_id == deal_id,
            Document.status == DocumentStatus.processed,
        )
        if document_ids is not None:
            q = q.filter(Document.id.in_(document_ids))
        docs = q.all()

        if document_ids is None:
            docs = [d for d in docs if self._looks_corporate(d)]

        return docs

    @staticmethod
    def _looks_corporate(doc) -> bool:
        haystack = (
            (doc.filename or "").lower().replace("_", " ").replace("-", " ")
            + " "
            + (doc.raw_text or "")[:1500].lower()
        )
        return any(kw in haystack for kw in _CORPORATE_INTRO_KEYWORDS)

    def _extract_for_document(self, doc, deal_id: int, db: Session) -> list:
        from app.models.company_profile import CompanyProfile
        from packages.prompts.deal_prompts import CORPORATE_INTRO_EXTRACTION_PROMPT

        text = (doc.raw_text or "")[:_TEXT_MAX_CHARS]
        if not text.strip():
            return []

        prompt = CORPORATE_INTRO_EXTRACTION_PROMPT.format(
            filename=doc.filename, text=text,
        )
        try:
            raw = self._llm.complete(prompt, max_tokens=4096)
            items = _safe_json(raw)
        except Exception:
            logger.warning(
                "[%s] doc=%d — parse error on LLM output", self.AGENT_NAME, doc.id,
            )
            return []

        profiles: list = []
        if not isinstance(items, list):
            return []
        for item in items:
            name = (item.get("company_name") or "").strip()
            if not name:
                continue  # mandatory field — drop entry
            conf = item.get("confidence")
            if conf is not None and conf < _MIN_PROFILE_CONFIDENCE:
                logger.debug(
                    "[%s] doc=%d — dropped low-conf profile %r (%.2f)",
                    self.AGENT_NAME, doc.id, name, conf,
                )
                continue

            cp = CompanyProfile(
                deal_id=deal_id,
                company_name=name[:500],
                legal_form=_str_or_none(item.get("legal_form"), 200),
                incorporation_date=_str_or_none(item.get("incorporation_date"), 100),
                registered_office=_str_or_none(item.get("registered_office"), 500),
                corporate_capital=_str_or_none(item.get("corporate_capital")),
                shareholders=_str_or_none(item.get("shareholders")),
                pledge=_str_or_none(item.get("pledge")),
                managing_body=_str_or_none(item.get("managing_body")),
                auditors=_str_or_none(item.get("auditors")),
                auditing_company=_str_or_none(item.get("auditing_company")),
                business=_str_or_none(item.get("business")),
                fiscal_year=_str_or_none(item.get("fiscal_year"), 200),
                duration=_str_or_none(item.get("duration"), 200),
                confidence=conf,
                source_document_id=doc.id,
            )
            db.add(cp)
            profiles.append(cp)
        return profiles


def _str_or_none(value, max_chars: int | None = None):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if max_chars is not None:
        return s[:max_chars]
    return s


def run_corporate_intro_extraction(
    deal_id: int,
    db: Session,
    document_ids: set[int] | None = None,
    provider: LLMProvider | None = None,
) -> dict:
    return CorporateIntroAgent(provider=provider).run(deal_id, db, document_ids)
