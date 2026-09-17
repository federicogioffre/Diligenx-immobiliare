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
    _parse_llm_items,
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

        # Idempotency: replace this agent's previous run. Previous profiles
        # are deleted in the persistence phase, in the same transaction as
        # the new ones (see stage_tx).
        db.query(AgentRun).filter(
            AgentRun.deal_id == deal_id,
            AgentRun.agent_name == self.AGENT_NAME,
        ).delete(synchronize_session=False)
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

            # LLM+parse per document is pure → fan out on a bounded pool;
            # ORM persistence happens below on this thread, in input order.
            from packages.agents.concurrency import run_llm_tasks
            from packages.agents.stage_tx import release_connection_before_llm

            # Plain values for the workers: after the commit below the ORM
            # instances are expired and must not be touched off-thread.
            work = [(doc.filename, doc.raw_text or "", doc.id) for doc in documents]

            # No transaction may stay open across the LLM phase.
            release_connection_before_llm(db)

            payload_lists = run_llm_tasks(
                work,
                lambda item: self._profile_payloads(item[0], item[1], item[2]),
            )

            # Idempotency: wipe the previous run's profiles in the same
            # transaction as the new ones.
            db.query(CompanyProfile).filter(
                CompanyProfile.deal_id == deal_id,
            ).delete(synchronize_session="fetch")
            db.flush()

            profiles: list = []
            for doc, payloads in zip(documents, payload_lists):
                profiles.extend(self._persist_profiles(doc, payloads, deal_id, db))

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

    def _profile_payloads(self, filename: str, raw_text: str, document_id: int) -> list[dict]:
        from packages.agents.document_coverage import collect_document_payloads

        parts = collect_document_payloads(
            raw_text,
            lambda batch: self._profile_payloads_batch(filename, batch, document_id),
            max_chars=_TEXT_MAX_CHARS,
        )
        # Profile fields may appear in different parts of the same document.
        # Preserve differing values rather than silently letting the last part win.
        merged: dict[str, dict] = {}
        for item in parts:
            key = " ".join(item["company_name"].casefold().split())
            if key not in merged:
                merged[key] = dict(item)
                continue
            previous = merged[key]
            confidence = item.get("confidence")
            if confidence is not None:
                existing = previous.get("confidence")
                previous["confidence"] = min(existing, confidence) if existing is not None else confidence
            for field, value in item.items():
                if field in {"company_name", "confidence", "source_spans"} or value in (None, ""):
                    continue
                old = previous.get(field)
                if old in (None, ""):
                    previous[field] = value
                elif str(value) not in str(old).split("\n"):
                    previous[field] = f"{old}\n{value}"
            previous["source_spans"].extend(item["source_spans"])
        return list(merged.values())

    def _profile_payloads_batch(self, filename: str, raw_text: str, document_id: int) -> list[dict]:
        """Call the LLM and return validated profile payload dicts.

        PURE with respect to the database — safe to run on a worker thread
        (see packages.agents.concurrency). Persistence happens separately in
        :meth:`_persist_profiles`.
        """
        from packages.prompts.deal_prompts import CORPORATE_INTRO_EXTRACTION_PROMPT

        text = raw_text
        if not text.strip():
            return []

        prompt = CORPORATE_INTRO_EXTRACTION_PROMPT.format(
            filename=filename, text=text,
        )
        raw = self._llm.complete(prompt, max_tokens=4096)
        items = _parse_llm_items(
            raw, context=f"{self.AGENT_NAME}, document {document_id}"
        )

        payloads: list[dict] = []
        for item in items:
            name = (item.get("company_name") or "").strip()
            if not name:
                continue  # mandatory field — drop entry
            conf = item.get("confidence")
            if conf is not None and conf < _MIN_PROFILE_CONFIDENCE:
                logger.debug(
                    "[%s] doc=%d — dropped low-conf profile %r (%.2f)",
                    self.AGENT_NAME, document_id, name, conf,
                )
                continue
            payloads.append({**item, "company_name": name, "confidence": conf})
        return payloads

    def _persist_profiles(self, doc, payloads: list[dict], deal_id: int, db: Session) -> list:
        """Create one ``CompanyProfile`` per payload. Main-thread only."""
        from app.models.company_profile import CompanyProfile

        profiles: list = []
        for item in payloads:
            cp = CompanyProfile(
                deal_id=deal_id,
                company_name=item["company_name"][:500],
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
                confidence=item["confidence"],
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
