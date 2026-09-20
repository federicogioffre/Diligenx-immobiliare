"""Corporate Introductory Information extraction agent.

Populates ``CompanyProfile`` rows — the structured equivalent of the
"Corporate Introductory Information" table in professional red-flag DD
reports. For each target company described in the deal's corporate
documents (visure camerali, atti costitutivi, statuti, patti parasociali,
or company profiles),
the agent extracts the standard fields (legal form, registered office,
capital, shareholders, board, auditors, business, fiscal year, duration)
via an LLM with strict grounding rules.

Auto-detection
--------------
When ``document_ids`` is *None*, every *processed* document in the deal is
inspected in bounded text windows. Corporate document names, profile
headings, or several distinct corporate fact fields select a document for
extraction. Selection does not certify the source or its contents.

Idempotency
-----------
Re-running for the same deal deletes this agent's previous ``AgentRun``
and ``CompanyProfile`` rows before writing fresh results.
"""
import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    get_llm_provider,
    _complete_llm_items,
)
from packages.agents.company_identity import normalize_company_name

logger = logging.getLogger(__name__)


AGENT_NAME = "corporate_intro_extraction"

# Reused / extended from corporate_agent — these match typical corporate
# documents, including informal profiles that are not registry certificates.
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
    "profilo societario",
    "scheda societaria",
    "anagrafica societaria",
    "corporate profile",
    "company profile",
    "company factsheet",
]

_MIN_PROFILE_CONFIDENCE = 0.55
_TEXT_MAX_CHARS = 12000
_SELECTION_WINDOW_CHARS = 12000
_SELECTION_OVERLAP_CHARS = 256

# A generic file can contain useful target facts without naming a particular
# legal document. Require three distinct field groups, so a company name or
# an invoice footer with only office/capital details does not trigger a call.
_CORPORATE_FACT_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"\b(?:sede\s+legale|registered\s+office)\b",
    r"\b(?:capitale\s+sociale|share\s+capital|paid[ -]in\s+capital|corporate\s+capital)\b",
    r"\b(?:assetto\s+proprietario|socio\s+unico|socia\s+unica|azionisti|shareholders?|shareholding|ownership)\b",
    r"\b(?:consiglio\s+di\s+amministrazione|amministrator[ei]|amministratric[ei]|managing\s+body|board\s+of\s+directors|sole\s+director)\b",
))


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
            # Scope is explicit user input, never inferred from a deal title or
            # from counterparties mentioned in its documents. Capture it before
            # releasing the session so worker threads only see plain values.
            target_company_names = tuple(
                name for name in (getattr(deal, "target_company_names", None) or [])
                if normalize_company_name(name)
            )
            documents = self._resolve_documents(db, deal_id, document_ids) if target_company_names else []

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
                lambda item: self._profile_payloads(item[0], item[1], item[2], target_company_names),
            )

            # Idempotency: wipe the previous run's profiles in the same
            # transaction as the new ones.
            if target_company_names:
                db.query(CompanyProfile).filter(
                    CompanyProfile.deal_id == deal_id,
                ).delete(synchronize_session="fetch")
                db.flush()

            profiles: list = []
            for doc, payloads in zip(documents, payload_lists):
                profiles.extend(self._persist_profiles(doc, payloads, deal_id, db, target_company_names))

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
        docs = q.order_by(Document.id).all()

        if document_ids is None:
            docs = [d for d in docs if self._looks_corporate(d)]

        return docs

    @staticmethod
    def _looks_corporate(doc) -> bool:
        filename = " ".join(
            (doc.filename or "").lower().replace("_", " ").replace("-", " ").split()
        )
        if any(kw in filename for kw in _CORPORATE_INTRO_KEYWORDS):
            return True

        # Scan all pages without making another document-sized string or
        # increasing the provider's extraction window. Overlap preserves
        # headings/field labels split at the edge of a selection window.
        text = doc.raw_text or ""
        fields_seen: set[int] = set()
        step = _SELECTION_WINDOW_CHARS - _SELECTION_OVERLAP_CHARS
        for start in range(0, len(text), step):
            window = " ".join(text[start:start + _SELECTION_WINDOW_CHARS].lower().split())
            if any(kw in window for kw in _CORPORATE_INTRO_KEYWORDS):
                return True
            fields_seen.update(
                index for index, pattern in enumerate(_CORPORATE_FACT_PATTERNS)
                if pattern.search(window)
            )
            if len(fields_seen) >= 3:
                return True
        return False

    def _profile_payloads(self, filename: str, raw_text: str, document_id: int,
                          target_company_names: list[str] | tuple[str, ...] | None = None) -> list[dict]:
        from packages.agents.document_coverage import collect_document_payloads

        if not target_company_names:
            return []
        parts = collect_document_payloads(
            raw_text,
            lambda batch: self._profile_payloads_batch(filename, batch, document_id, target_company_names),
            max_chars=_TEXT_MAX_CHARS,
        )
        # Keep differing chunk payloads as separate evidence rows. Concatenating
        # them here would hide conflicts within one document from the shared
        # consolidation layer. Identical overlap payloads are already deduped.
        return parts

    def _profile_payloads_batch(self, filename: str, raw_text: str, document_id: int,
                                target_company_names: list[str] | tuple[str, ...] | None = None) -> list[dict]:
        """Call the LLM and return validated profile payload dicts.

        PURE with respect to the database — safe to run on a worker thread
        (see packages.agents.concurrency). Persistence happens separately in
        :meth:`_persist_profiles`.
        """
        from packages.prompts.deal_prompts import CORPORATE_INTRO_EXTRACTION_PROMPT

        text = raw_text
        allowed = {normalize_company_name(name) for name in (target_company_names or ())}
        allowed.discard("")
        if not text.strip() or not allowed:
            return []

        prompt = CORPORATE_INTRO_EXTRACTION_PROMPT.format(
            filename=filename, text=text,
            target_company_names=json.dumps(target_company_names, ensure_ascii=False),
        )
        items = _complete_llm_items(
            self._llm, prompt, max_tokens=6144, context=f"{self.AGENT_NAME}, document {document_id}"
        )

        payloads: list[dict] = []
        for item in items:
            raw_name = item.get("company_name")
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            if normalize_company_name(name) not in allowed:
                continue  # Never trust the model to enforce the deal scope.
            conf = item.get("confidence")
            if conf is not None and conf < _MIN_PROFILE_CONFIDENCE:
                logger.debug(
                    "[%s] doc=%d — dropped low-conf profile %r (%.2f)",
                    self.AGENT_NAME, document_id, name, conf,
                )
                continue
            payloads.append({**item, "company_name": name, "confidence": conf})
        return payloads

    def _persist_profiles(self, doc, payloads: list[dict], deal_id: int, db: Session,
                          target_company_names: list[str] | tuple[str, ...] | None = None) -> list:
        """Create one ``CompanyProfile`` per payload. Main-thread only."""
        from app.models.company_profile import CompanyProfile

        allowed = {normalize_company_name(name) for name in (target_company_names or ())}
        allowed.discard("")
        profiles: list = []
        for item in payloads:
            if normalize_company_name(item.get("company_name")) not in allowed:
                continue
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
