"""Red-flag aggregation agent.

Aggregates findings from ALL specialist agents — ``ClauseFinding`` rows (from
:class:`~packages.agents.contract_agent.ContractAgent`) plus ``AgentFinding``
rows (from :class:`~packages.agents.corporate_agent.CorporateAgent` and any
other future specialist) — into consolidated ``RedFlag`` records.

Key features
------------
Deduplication
    After the LLM returns its raw list of red flags, the agent fingerprints
    each item as ``(normalize(title), category)`` (lower-cased, punctuation
    stripped).  When two flags share the same fingerprint the one with the
    **higher severity** is retained; the rest are discarded.  The count of
    discarded duplicates is reported in the result.

Severity-based prioritization
    During deduplication the severity hierarchy is
    ``low < medium < high < critical``.  The retained flag inherits the
    highest severity seen for that fingerprint.

Document grouping
    All findings are passed to the LLM pre-grouped by source document (with
    the document ID and filename visible).  The LLM is instructed to populate
    ``source_document_id`` with the matching integer, enabling traceable
    ``RedFlag`` rows.

Open questions
    Every ``high`` or ``critical`` red flag automatically generates an
    ``OpenQuestion`` prompting the deal team to supply a mitigation plan.

Orchestrator compatibility
    ``AGENT_NAME = "red_flag_aggregation"`` matches the orchestrator's
    ``AGENT_RED_FLAG`` constant.  The orchestrator's stage-4 function is a
    thin wrapper that delegates entirely to this agent, preserving all
    existing orchestrator tests unchanged.
"""
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    _safe_json,
    _VALID_SEVERITIES,
    get_llm_provider,
)

logger = logging.getLogger(__name__)

# ── Public constant ────────────────────────────────────────────────────────────

AGENT_NAME = "red_flag_aggregation"

# ── Severity ordering (used for dedup winner selection) ───────────────────────

_SEVERITY_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


# ── Agent ─────────────────────────────────────────────────────────────────────


class RedFlagAggregationAgent:
    """Aggregate specialist findings into deduplicated ``RedFlag`` records.

    Usage::

        agent = RedFlagAggregationAgent()
        result = agent.run(deal_id, db)

    Or use the module-level convenience wrapper :func:`run_red_flag_aggregation`.
    """

    AGENT_NAME = AGENT_NAME

    def __init__(self, provider: LLMProvider | None = None):
        self._llm = provider or get_llm_provider()

    # ── Public entry point ─────────────────────────────────────────────────

    def run(self, deal_id: int, db: Session) -> dict:
        """Aggregate all specialist findings into ``RedFlag`` records.

        Returns::

            {
                "deal_id": int,
                "red_flags_count": int,
                "open_questions_count": int,
                "flags_by_severity": {
                    "low": int, "medium": int, "high": int, "critical": int
                },
                "flags_by_category": {"<category>": int, ...},
                "dedup_removed": int,   # near-duplicates discarded
            }

        Raises ``ValueError`` if *deal_id* does not exist.
        """
        from app.models.deal import Deal
        from app.models.agent_run import AgentRun, AgentRunStatus
        from app.models.red_flag import RedFlag
        from app.models.open_question import OpenQuestion
        from app.models.agent_finding import AgentFinding

        # ── 0. Validate ──────────────────────────────────────────────── #
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        logger.info(
            "[%s] deal=%d ('%s') — starting red-flag aggregation",
            self.AGENT_NAME, deal_id, deal.title,
        )

        # ── 1. Idempotency ────────────────────────────────────────────── #
        db.query(AgentRun).filter(
            AgentRun.deal_id == deal_id,
            AgentRun.agent_name == self.AGENT_NAME,
        ).delete(synchronize_session=False)

        # Clear ALL red flags for the deal (this agent owns them).
        db.query(RedFlag).filter(
            RedFlag.deal_id == deal_id,
        ).delete(synchronize_session=False)

        # Clear own observations / information_request AgentFindings.
        db.query(AgentFinding).filter(
            AgentFinding.deal_id == deal_id,
            AgentFinding.agent_name == self.AGENT_NAME,
            AgentFinding.category.in_(["observation", "information_request"]),
        ).delete(synchronize_session=False)

        # Clear only own open questions.
        db.query(OpenQuestion).filter(
            OpenQuestion.deal_id == deal_id,
            OpenQuestion.agent_name == self.AGENT_NAME,
        ).delete(synchronize_session=False)

        db.flush()

        # ── 2. Open AgentRun ──────────────────────────────────────────── #
        run = AgentRun(
            deal_id=deal_id,
            agent_name=self.AGENT_NAME,
            status=AgentRunStatus.running,
            started_at=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()

        try:
            # ── 3. Gather inputs ──────────────────────────────────────── #
            doc_map = self._get_documents(db, deal_id)
            clause_findings = self._gather_clause_findings(db, doc_map)
            agent_findings = self._gather_agent_findings(db, deal_id)

            logger.info(
                "[%s] deal=%d — gathered %d clause finding(s), %d agent finding(s)",
                self.AGENT_NAME, deal_id,
                len(clause_findings), len(agent_findings),
            )

            # ── 4. Build context + call LLM ───────────────────────────── #
            context_text = self._build_context_text(
                clause_findings, agent_findings, doc_map
            )
            raw_flags = self._call_llm_for_flags(context_text, deal_id)

            logger.info(
                "[%s] deal=%d — LLM returned %d raw flag(s)",
                self.AGENT_NAME, deal_id, len(raw_flags),
            )

            # ── 5. Deduplicate ────────────────────────────────────────── #
            deduped_flags, dedup_removed = self._deduplicate(raw_flags)

            if dedup_removed:
                logger.info(
                    "[%s] deal=%d — deduplication removed %d flag(s) (%d unique remain)",
                    self.AGENT_NAME, deal_id, dedup_removed, len(deduped_flags),
                )

            # ── 6. Persist ────────────────────────────────────────────── #
            red_flags, open_questions = self._persist_flags_and_questions(
                deal_id, deduped_flags, db
            )

            db.flush()

            # ── 7. Complete run ───────────────────────────────────────── #
            run.completed_at = datetime.now(timezone.utc)
            run.status = AgentRunStatus.completed
            _started = run.started_at
            if _started is not None and _started.tzinfo is None:
                _started = _started.replace(tzinfo=timezone.utc)
            _duration = (run.completed_at - _started).total_seconds() if _started is not None else 0.0
            db.flush()

            result = self._build_result(deal_id, red_flags, open_questions, dedup_removed)
            logger.info(
                "[%s] deal=%d — completed in %.2fs: %s",
                self.AGENT_NAME, deal_id, _duration, result,
            )
            return result

        except Exception as exc:
            logger.exception(
                "[%s] deal=%d — failed", self.AGENT_NAME, deal_id
            )
            run.completed_at = datetime.now(timezone.utc)
            run.status = AgentRunStatus.failed
            run.error_message = str(exc)[:2000]
            _started = run.started_at
            if _started is not None and _started.tzinfo is None:
                _started = _started.replace(tzinfo=timezone.utc)
            _duration = (run.completed_at - _started).total_seconds() if _started is not None else 0.0
            logger.warning(
                "[%s] deal=%d — FAILED in %.2fs: %s",
                self.AGENT_NAME, deal_id, _duration, str(exc)[:200],
            )
            db.flush()
            raise

    # ── Input gathering ─────────────────────────────────────────────────

    def _get_documents(self, db: Session, deal_id: int) -> dict:
        """Return {doc_id: Document} for every document in the deal."""
        from app.models.document import Document
        docs = db.query(Document).filter(Document.deal_id == deal_id).all()
        return {d.id: d for d in docs}

    def _gather_clause_findings(self, db: Session, doc_map: dict) -> list:
        """Return all ``ClauseFinding`` rows for documents in *doc_map*."""
        from app.models.clause_finding import ClauseFinding
        if not doc_map:
            return []
        return (
            db.query(ClauseFinding)
            .filter(ClauseFinding.document_id.in_(list(doc_map.keys())))
            .all()
        )

    def _gather_agent_findings(self, db: Session, deal_id: int) -> list:
        """Return ``AgentFinding`` rows from specialist agents.

        Excludes:
        * This agent's own output rows (defensive — it doesn't write any).
        * ``document_router`` rows (classification metadata; low signal for
          risk detection).
        """
        from app.models.agent_finding import AgentFinding
        return (
            db.query(AgentFinding)
            .filter(
                AgentFinding.deal_id == deal_id,
                AgentFinding.agent_name != self.AGENT_NAME,
                AgentFinding.agent_name != "document_router",
            )
            .all()
        )

    # ── Context building ────────────────────────────────────────────────

    def _build_context_text(
        self,
        clause_findings: list,
        agent_findings: list,
        doc_map: dict,
    ) -> str:
        """Build a document-grouped context string for the LLM.

        Example output::

            === Document 3: service_agreement.txt ===
            Clause Findings:
              [termination] Termination Clause: Either party may terminate...
              [liability] Limitation of Liability: Liability shall not exceed...
            Agent Findings:
              [clause_extraction_summary] 2 clauses extracted  (agent: contract_analysis, severity: low)

            === Document 7: shareholder_agreement.txt ===
            Agent Findings:
              [veto_right] Investor Veto: Preferred shareholders hold veto...  (agent: corporate_governance, severity: high)
        """
        # Group clause findings by document_id
        clauses_by_doc: dict[int, list] = {}
        for cf in clause_findings:
            clauses_by_doc.setdefault(cf.document_id, []).append(cf)

        # Group agent findings by document_id (None = cross-document)
        agents_by_doc: dict[int | None, list] = {}
        for af in agent_findings:
            agents_by_doc.setdefault(af.document_id, []).append(af)

        # All document IDs that have at least one finding
        all_doc_ids = sorted(
            set(clauses_by_doc.keys())
            | {k for k in agents_by_doc.keys() if k is not None}
        )

        parts: list[str] = []

        for doc_id in all_doc_ids:
            doc = doc_map.get(doc_id)
            filename = doc.filename if doc else f"document_{doc_id}"
            parts.append(f"=== Document {doc_id}: {filename} ===")

            doc_clauses = clauses_by_doc.get(doc_id, [])
            if doc_clauses:
                parts.append("Clause Findings:")
                for cf in doc_clauses:
                    snippet = (cf.content or "")[:200]
                    parts.append(f"  [{cf.clause_type.value}] {cf.title}: {snippet}")

            doc_agents = agents_by_doc.get(doc_id, [])
            if doc_agents:
                parts.append("Agent Findings:")
                for af in doc_agents:
                    sev = (
                        af.severity.value
                        if hasattr(af.severity, "value")
                        else str(af.severity)
                    )
                    desc_snippet = (af.description or "")[:200]
                    parts.append(
                        f"  [{af.category}] {af.title}: {desc_snippet}"
                        f"  (agent: {af.agent_name}, severity: {sev})"
                    )

            parts.append("")  # blank line between documents

        # Deal-level / cross-document findings (document_id is None)
        cross_doc = agents_by_doc.get(None, [])
        if cross_doc:
            parts.append("=== Cross-Document / Deal-Level Findings ===")
            for af in cross_doc:
                sev = (
                    af.severity.value
                    if hasattr(af.severity, "value")
                    else str(af.severity)
                )
                desc_snippet = (af.description or "")[:200]
                parts.append(
                    f"  [{af.category}] {af.title}: {desc_snippet}"
                    f"  (agent: {af.agent_name}, severity: {sev})"
                )
            parts.append("")

        return "\n".join(parts) if parts else "No findings available."

    # ── LLM call ────────────────────────────────────────────────────────

    def _call_llm_for_flags(self, context_text: str, deal_id: int) -> list[dict]:
        from packages.prompts.deal_prompts import RED_FLAG_AGGREGATION_PROMPT
        from packages.agents.legal_rules import build_legal_rules_context

        prompt = RED_FLAG_AGGREGATION_PROMPT.format(
            findings_by_document=context_text,
            legal_rules_context=build_legal_rules_context(),
        )
        raw = self._llm.complete(prompt, max_tokens=4096)

        try:
            items = _safe_json(raw)
        except Exception:
            logger.warning(
                "[%s] deal=%d — parse error: %r", self.AGENT_NAME, deal_id, raw
            )
            items = []

        return items if isinstance(items, list) else []

    # ── Deduplication ───────────────────────────────────────────────────

    @staticmethod
    def _fingerprint(flag: dict) -> tuple[str, str]:
        """Normalised (title, category) key for deduplication."""
        title = re.sub(r"[^a-z0-9]", "", flag.get("title", "").lower())
        category = flag.get("category", "").lower().strip()
        return (title, category)

    def _deduplicate(
        self, raw_flags: list[dict]
    ) -> tuple[list[dict], int]:
        """Deduplicate by fingerprint; keep the highest-severity variant.

        Returns ``(deduplicated_flags, number_removed)``.
        """
        seen: dict[tuple, dict] = {}

        for flag in raw_flags:
            fp = self._fingerprint(flag)
            if fp not in seen:
                seen[fp] = flag
            else:
                existing_sev = _SEVERITY_ORDER.get(
                    seen[fp].get("severity", "low"), 0
                )
                new_sev = _SEVERITY_ORDER.get(flag.get("severity", "low"), 0)
                if new_sev > existing_sev:
                    seen[fp] = flag

        deduped = list(seen.values())
        removed = len(raw_flags) - len(deduped)
        return deduped, removed

    # ── Persistence ──────────────────────────────────────────────────────

    def _persist_flags_and_questions(
        self, deal_id: int, flags: list[dict], db: Session
    ) -> tuple[list, list]:
        """Persist ``RedFlag`` rows and generate ``OpenQuestion`` for high/critical.

        Items with ``finding_type`` of ``"observation"`` or
        ``"information_request"`` are stored as ``AgentFinding`` rows rather
        than ``RedFlag`` rows so that the report agent can present them in
        separate sections without inflating the red-flag count.
        """
        from app.models.red_flag import RedFlag, Severity
        from app.models.open_question import OpenQuestion, Priority
        from app.models.agent_finding import AgentFinding

        _VALID_FINDING_TYPES = {"red_flag", "observation", "information_request"}
        _MIN_FLAG_CONFIDENCE = 0.50   # drop red_flags below this threshold

        red_flags: list[RedFlag] = []
        for item in flags:
            # Drop low-confidence flags before persisting
            conf = item.get("confidence")
            if conf is not None and conf < _MIN_FLAG_CONFIDENCE:
                logger.debug(
                    "[%s] dropped low-confidence flag (%.2f): %r",
                    self.AGENT_NAME, conf, item.get("title", ""),
                )
                continue
            finding_type = item.get("finding_type", "red_flag")
            if finding_type not in _VALID_FINDING_TYPES:
                finding_type = "red_flag"

            severity_str = item.get("severity", "medium")
            if severity_str not in _VALID_SEVERITIES:
                severity_str = "medium"

            if finding_type in ("observation", "information_request"):
                # Store as an AgentFinding so the report can present it
                # in the Observations / Information Requests sections.
                af = AgentFinding(
                    deal_id=deal_id,
                    document_id=item.get("source_document_id"),
                    agent_name=self.AGENT_NAME,
                    category=finding_type,
                    title=str(item.get("title", ""))[:500],
                    description=item.get("description", ""),
                    severity=Severity(severity_str),
                    confidence=item.get("confidence"),
                )
                db.add(af)
            else:
                flag = RedFlag(
                    deal_id=deal_id,
                    title=str(item.get("title", ""))[:500],
                    description=item.get("description", ""),
                    severity=Severity(severity_str),
                    category=str(item.get("category", "general"))[:100],
                    confidence=item.get("confidence"),
                    source_document_id=item.get("source_document_id"),
                )
                db.add(flag)
                red_flags.append(flag)

        # Flush so flags get IDs before we reference them in questions.
        db.flush()

        open_questions: list[OpenQuestion] = []
        for flag in red_flags:
            if flag.severity in (Severity.high, Severity.critical):
                q = OpenQuestion(
                    deal_id=deal_id,
                    agent_name=self.AGENT_NAME,
                    question=(
                        f"Red flag '{flag.title}' (severity={flag.severity.value}): "
                        f"{flag.description} — What is the mitigation plan?"
                    ),
                    priority=(
                        Priority.high
                        if flag.severity == Severity.critical
                        else Priority.medium
                    ),
                )
                db.add(q)
                open_questions.append(q)

        db.flush()
        return red_flags, open_questions

    # ── Result builder ───────────────────────────────────────────────────

    def _build_result(
        self,
        deal_id: int,
        red_flags: list,
        open_questions: list,
        dedup_removed: int,
    ) -> dict:
        from app.models.red_flag import Severity

        flags_by_severity: dict[str, int] = {s.value: 0 for s in Severity}
        flags_by_category: dict[str, int] = {}

        for flag in red_flags:
            sev_val = (
                flag.severity.value
                if hasattr(flag.severity, "value")
                else str(flag.severity)
            )
            flags_by_severity[sev_val] = flags_by_severity.get(sev_val, 0) + 1
            cat = flag.category
            flags_by_category[cat] = flags_by_category.get(cat, 0) + 1

        return {
            "deal_id": deal_id,
            "red_flags_count": len(red_flags),
            "open_questions_count": len(open_questions),
            "flags_by_severity": flags_by_severity,
            "flags_by_category": flags_by_category,
            "dedup_removed": dedup_removed,
        }


# ── Module-level convenience function ──────────────────────────────────────────


def run_red_flag_aggregation(
    deal_id: int,
    db: Session,
    *,
    provider: LLMProvider | None = None,
) -> dict:
    """Create a :class:`RedFlagAggregationAgent` and run aggregation."""
    return RedFlagAggregationAgent(provider=provider).run(deal_id, db)
