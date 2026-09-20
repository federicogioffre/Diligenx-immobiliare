"""Red-flag aggregation agent.

Aggregates findings from ALL specialist agents — ``ClauseFinding`` rows (from
:class:`~packages.agents.contract_agent.ContractAgent`) plus ``AgentFinding``
rows (from :class:`~packages.agents.corporate_agent.CorporateAgent` and any
other future specialist) — into consolidated ``RedFlag`` records.

Key features
------------
Deduplication
    After the LLM returns its raw list of red flags, the agent fingerprints
    each item's normalized title/category, source document, amount and fiscal
    years. When two flags share the same fingerprint the one with the
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
    Every ``high`` red flag automatically generates an
    ``OpenQuestion`` prompting the deal team to supply a mitigation plan.

Orchestrator compatibility
    ``AGENT_NAME = "red_flag_aggregation"`` matches the orchestrator's
    ``AGENT_RED_FLAG`` constant.  The orchestrator's stage-4 function is a
    thin wrapper that delegates entirely to this agent, preserving all
    existing orchestrator tests unchanged.
"""
import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    _complete_llm_items,
    _normalize_severity,
    _parse_dd_area,
    get_llm_provider,
)

logger = logging.getLogger(__name__)

# ── Public constant ────────────────────────────────────────────────────────────

AGENT_NAME = "red_flag_aggregation"

# ── Severity ordering (used for dedup winner selection) ───────────────────────
# "critical" is kept in the ranking because raw LLM output may still use it
# (it is normalized to "high" at persistence time).

_SEVERITY_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


# ── Agent ─────────────────────────────────────────────────────────────────────


# The instrument that answers a finding. This is the tag a law firm's
# consolidated risk memo assigns to each risk: every line there ends in a
# warranty cross-reference, "indemnity", "earn-out", or an action to take
# before closing.
_VALID_REMEDY_TYPES = (
    "indemnity",
    "warranty",
    "price_adjustment",
    "earn_out",
    "condition_precedent",
    "pre_closing_verification",
    "post_closing_action",
    "information_request",
)

# What the finding hits. This is the orthogonal tag a financial adviser's
# key-findings page carries (Value / SPA / Other) — a different question
# from which instrument answers it, and the natural filter for a client
# asking "show me everything that has to land in the contract".
_VALID_IMPACTS = ("value", "spa", "other")


def _normalize_choice(raw: object, allowed: tuple[str, ...]) -> str | None:
    """Return *raw* if it is one of *allowed*, else None.

    None means "the model did not say", which stays distinct from a wrong
    guess: a red flag tagged with the wrong remedy is worse than one left
    untagged for a human to fill in.
    """
    if raw is None:
        return None
    value = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    return value if value in allowed else None


# Categories whose presence is not a matter of degree. A capital loss under
# artt. 2446-2447 c.c. and a going-concern doubt are events with statutory
# consequences: they are high or they are wrong.
_NON_NEGOTIABLE_HIGH = frozenset({"capital_loss", "going_concern"})


def _build_severity_floors(agent_findings: list) -> dict[str, str]:
    """Minimum severity per finding category, from what the specialists found.

    Two sources of a floor: a tax finding graded ``actual`` — an omission
    with no available defence — and the categories in
    :data:`_NON_NEGOTIABLE_HIGH`.

    The floor is applied by matching the red flag's ``category`` against the
    source finding's, so it is a **safety net, not the mechanism**: the
    prompt already instructs the model to keep such findings high, and this
    catches the case where it does not. It can only raise a severity, never
    lower one, so a missed match costs nothing.
    """
    floors: dict[str, str] = {}
    for af in agent_findings:
        category = (af.category or "").strip().lower()
        if not category:
            continue
        payload = af.structured_payload_json or {}
        if payload.get("defensibility") == "actual" or category in _NON_NEGOTIABLE_HIGH:
            floors[category] = "high"
    return floors


def _apply_severity_floor(severity: str, floor: str | None) -> str:
    """Return the higher of *severity* and *floor*.

    Shares :data:`_SEVERITY_ORDER` with the deduplication, so the two agree
    on what "higher" means — including the ``critical`` the raw LLM output
    sometimes still uses.
    """
    if floor is None:
        return severity
    if _SEVERITY_ORDER.get(floor, 0) > _SEVERITY_ORDER.get(severity, 0):
        return floor
    return severity


def _flag_payload(item: dict, severity_was_floored: bool) -> dict | None:
    """Carry the quantitative fields forward onto the red flag.

    The specialist agents extract an amount and the fiscal years it relates
    to; losing them at aggregation would mean the report can only say "a tax
    assessment was notified" where the source document said how much and for
    which year. Empty values are dropped so an ordinary flag stores nothing.
    """
    payload: dict = {}

    amount = item.get("amount_eur")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount >= 0:
        payload["amount_eur"] = float(amount)
        payload["amount_source"] = item.get("amount_source", "unverified")
        payload["amount_evidence"] = item.get("amount_evidence")

    years = item.get("fiscal_years")
    if isinstance(years, (list, tuple)):
        parsed = sorted({int(y) for y in years if str(y).strip().lstrip("-").isdigit()})
        if parsed:
            payload["fiscal_years"] = parsed

    if severity_was_floored:
        # Recorded so a reviewer can see the severity did not come from the
        # model's judgement alone.
        payload["severity_floored"] = True

    if item.get("grounding_reviewed") is True:
        payload["grounding_reviewed"] = True
        payload["evidence"] = item["evidence"]
        payload["source_pages"] = item["source_pages"]

    return payload or None


def _summarize_payload(payload: dict | None) -> str:
    """Render the specialist agents' structured fields for the LLM context.

    Only the fields that are present are emitted, so an ordinary finding
    stays a single short line. Without this the aggregator would see the
    tax and financial agents' prose and none of their structure — the
    defensibility grade, the amount the document stated, the fiscal years,
    the mitigating factors — and would have to guess what was already known.
    """
    if not payload:
        return ""

    bits: list[str] = []

    grade = payload.get("defensibility")
    if grade:
        bits.append(f"defensibility={grade}")

    tax_kind = payload.get("tax_kind")
    if tax_kind and tax_kind != "altro":
        bits.append(f"tax={tax_kind}")

    amount = payload.get("amount_eur")
    if amount is not None and payload.get("amount_source") == "document":
        bits.append(f"amount_stated_by_document=EUR {amount:,.0f}")
        if payload.get("amount_evidence"):
            bits.append("amount_evidence=" + str(payload["amount_evidence"]))

    years = payload.get("fiscal_years")
    if years:
        bits.append("FY " + ", ".join(str(y) for y in years))

    periods = payload.get("assessment_periods") or []
    barred = [str(pd["fiscal_year"]) for pd in periods if pd.get("time_barred")]
    if barred:
        bits.append("time-barred: FY " + ", ".join(barred))

    mitigations = payload.get("mitigating_factors")
    if mitigations:
        bits.append("mitigants: " + ", ".join(mitigations))

    counterparty = payload.get("counterparty")
    if counterparty:
        bits.append(f"counterparty={counterparty}")

    if payload.get("change_of_control_clause") is True:
        bits.append("change-of-control clause: yes")
    if payload.get("financial_covenant") is True:
        bits.append("financial covenant: yes")

    legal_basis = payload.get("legal_basis")
    if legal_basis:
        bits.append(f"cited: {legal_basis}")

    if payload.get("source") == "heuristic":
        bits.append("raised by keyword floor, not extracted")

    return " | ".join(bits)


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
                    "low": int, "medium": int, "high": int
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

            # Revalidate legacy findings against ingestion evidence. A page
            # returned by another model is not an independent source of truth.
            from packages.agents.evidence import verified_clause_page
            pages_by_doc: dict[int, set[int]] = {}
            for cf in clause_findings:
                doc = doc_map.get(cf.document_id)
                page = verified_clause_page(cf.content, doc.chunks, doc.page_count) if doc else None
                if page is not None:
                    pages_by_doc.setdefault(cf.document_id, set()).add(page)

            logger.info(
                "[%s] deal=%d — gathered %d clause finding(s), %d agent finding(s)",
                self.AGENT_NAME, deal_id,
                len(clause_findings), len(agent_findings),
            )

            # ── 4. Build context + call LLM ───────────────────────────── #
            context_text = self._build_context_text(
                clause_findings, agent_findings, doc_map
            )
            from packages.agents.output_language import (
                language_instruction,
                resolve_output_language,
            )
            output_lang = resolve_output_language(deal, db)
            severity_floors = _build_severity_floors(agent_findings)
            from packages.agents.grounding_review import snapshot_documents, review_grounded_flags
            review_documents = snapshot_documents(doc_map, clause_findings, agent_findings)
            from packages.agents.stage_tx import release_connection_before_llm
            release_connection_before_llm(db)
            raw_flags = self._call_llm_for_flags(
                context_text, deal_id, language_instruction(output_lang), output_lang
            )

            logger.info(
                "[%s] deal=%d — LLM returned %d raw flag(s)",
                self.AGENT_NAME, deal_id, len(raw_flags),
            )

            # ── 5. Deduplicate ────────────────────────────────────────── #
            deduped_flags, dedup_removed = self._deduplicate(raw_flags)

            # Review complete source evidence before replacing any previous
            # outputs. A valid JSON response alone is not a fidelity check.
            deduped_flags = review_grounded_flags(
                self._llm, deduped_flags, review_documents, output_lang
            )

            if dedup_removed:
                logger.info(
                    "[%s] deal=%d — deduplication removed %d flag(s) (%d unique remain)",
                    self.AGENT_NAME, deal_id, dedup_removed, len(deduped_flags),
                )

            # ── 6. Persist ────────────────────────────────────────────── #
            # Clear ALL red flags for the deal (this agent owns them).
            # `synchronize_session="fetch"` also expunges the deleted rows from the
            # session identity map; otherwise the inserts below can collide with
            # stale RedFlag instances when SQLite reuses rowids.
            db.query(RedFlag).filter(
                RedFlag.deal_id == deal_id,
            ).delete(synchronize_session="fetch")

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

            red_flags, open_questions = self._persist_flags_and_questions(
                deal_id,
                deduped_flags,
                db,
                pages_by_doc,
                severity_floors=severity_floors,
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
                    snippet = cf.content or ""
                    # Expose the page so the LLM can cite it in source_page.
                    page = f" (p. {cf.page_number})" if cf.page_number is not None else ""
                    parts.append(f"  [{cf.clause_type.value}]{page} {cf.title}: {snippet}")

            doc_agents = agents_by_doc.get(doc_id, [])
            if doc_agents:
                parts.append("Agent Findings:")
                for af in doc_agents:
                    sev = (
                        af.severity.value
                        if hasattr(af.severity, "value")
                        else str(af.severity)
                    )
                    desc_snippet = af.description or ""
                    extra = _summarize_payload(af.structured_payload_json)
                    extra = f"  [{extra}]" if extra else ""
                    parts.append(
                        f"  [{af.category}] {af.title}: {desc_snippet}"
                        f"  (agent: {af.agent_name}, severity: {sev}){extra}"
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
                desc_snippet = af.description or ""
                extra = _summarize_payload(af.structured_payload_json)
                extra = f"  [{extra}]" if extra else ""
                parts.append(
                    f"  [{af.category}] {af.title}: {desc_snippet}"
                    f"  (agent: {af.agent_name}, severity: {sev}){extra}"
                )
            parts.append("")

        return "\n".join(parts) if parts else "No findings available."

    # ── LLM call ────────────────────────────────────────────────────────

    def _call_llm_for_flags(
        self, context_text: str, deal_id: int, lang_instruction: str = "", output_lang: str = "en"
    ) -> list[dict]:
        from packages.prompts.deal_prompts import RED_FLAG_AGGREGATION_PROMPT
        from packages.agents.legal_rules import build_legal_rules_context

        from packages.agents.document_coverage import aggregation_batches
        from packages.agents.output_language import recommendation_examples

        results: list[dict] = []
        for index, batch in enumerate(aggregation_batches(context_text), start=1):
            prompt = RED_FLAG_AGGREGATION_PROMPT.format(
                findings_by_document=batch,
                legal_rules_context=build_legal_rules_context(),
                language_instruction=lang_instruction,
                recommendation_examples=recommendation_examples(output_lang),
            )
            results.extend(_complete_llm_items(
                self._llm, prompt, max_tokens=12288, context=f"Red flags for deal {deal_id}, batch {index}"
            ))
        return results

    # ── Deduplication ───────────────────────────────────────────────────

    @staticmethod
    def _fingerprint(flag: dict) -> tuple[str, str, str]:
        """Merge title variants only when their source and exposure match.

        Similar titles across documents are not proof of the same obligation.
        Conservative merging also preserves different amounts or fiscal years.
        """
        title = re.sub(r"[^a-z0-9]", "", flag.get("title", "").lower())
        category = flag.get("category", "").lower().strip()
        years = flag.get("fiscal_years") or []
        if not isinstance(years, list):
            years = [years]
        exposure = json.dumps({
            "source_document_id": flag.get("source_document_id"),
            "amount_eur": flag.get("amount_eur"),
            "fiscal_years": sorted(str(year) for year in years),
        }, sort_keys=True, default=str)
        return (title, category, exposure)

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

    @staticmethod
    def _validate_source_page(
        raw_page, source_doc_id, pages_by_doc: dict[int, set[int]]
    ) -> int | None:
        """Return the cited page only if it is a real page of that document's
        clause findings; otherwise None. Prevents hallucinated citations."""
        if raw_page is None or source_doc_id is None:
            return None
        if type(raw_page) is not int:
            return None
        page = raw_page
        return page if page in pages_by_doc.get(source_doc_id, set()) else None

    def _persist_flags_and_questions(
        self,
        deal_id: int,
        flags: list[dict],
        db: Session,
        pages_by_doc: dict[int, set[int]] | None = None,
        severity_floors: dict[str, str] | None = None,
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
        pages_by_doc = pages_by_doc or {}
        severity_floors = severity_floors or {}

        from app.models.document import Document
        allowed_documents = {row.id: row for row in db.query(Document).filter_by(deal_id=deal_id)}
        for item in flags:
            source_id = item.get("source_document_id")
            if source_id is not None and (type(source_id) is not int or source_id not in allowed_documents):
                from packages.agents.deal_analysis_agent import LLMResponseError
                raise LLMResponseError("Aggregation cited a document outside this deal")
            from packages.agents.evidence import grounded_amount
            source_doc = allowed_documents.get(source_id)
            amount, amount_source, amount_evidence = grounded_amount(item, source_doc.raw_text or "" if source_doc else "")
            item["amount_eur"] = amount
            item["amount_source"] = amount_source
            item["amount_evidence"] = amount_evidence

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

            severity_str = _normalize_severity(item.get("severity", "medium"))

            if finding_type in ("observation", "information_request"):
                # Store as an AgentFinding so the report can present it
                # in the Observations / Information Requests sections.
                af = AgentFinding(
                    deal_id=deal_id,
                    document_id=item.get("source_document_id"),
                    agent_name=self.AGENT_NAME,
                    category=finding_type,
                    title=str(item.get("title", ""))[:500],
                    description=item.get("issue") or item.get("description", ""),
                    severity=Severity(severity_str),
                    confidence=item.get("confidence"),
                    structured_payload_json=_flag_payload(item, False),
                )
                db.add(af)
            else:
                source_doc_id = item.get("source_document_id")
                category = str(item.get("category", "general"))[:100]

                floored = _apply_severity_floor(
                    severity_str, severity_floors.get(category.strip().lower())
                )
                if floored != severity_str:
                    logger.info(
                        "[%s] deal=%d — raised '%s' from %s to %s: the source "
                        "finding admits no defence",
                        self.AGENT_NAME, deal_id,
                        item.get("title", ""), severity_str, floored,
                    )

                flag = RedFlag(
                    deal_id=deal_id,
                    title=str(item.get("title", ""))[:500],
                    # "description" is the legacy LLM output key for the issue.
                    issue=item.get("issue") or item.get("description", ""),
                    risk=item.get("risk"),
                    recommendation=item.get("recommendation"),
                    severity=Severity(floored),
                    area=_parse_dd_area(item.get("area")),
                    category=category,
                    confidence=item.get("confidence"),
                    source_document_id=source_doc_id,
                    source_page=(item.get("source_page") if item.get("grounding_reviewed") is True
                                 else self._validate_source_page(
                                     item.get("source_page"), source_doc_id, pages_by_doc
                                 )),
                    remedy_type=_normalize_choice(
                        item.get("remedy_type"), _VALID_REMEDY_TYPES
                    ),
                    impact=_normalize_choice(item.get("impact"), _VALID_IMPACTS),
                    structured_payload_json=_flag_payload(item, floored != severity_str),
                )
                db.add(flag)
                red_flags.append(flag)

        # Flush so flags get IDs before we reference them in questions.
        db.flush()

        open_questions: list[OpenQuestion] = []
        for flag in red_flags:
            if flag.severity == Severity.high:
                q = OpenQuestion(
                    deal_id=deal_id,
                    agent_name=self.AGENT_NAME,
                    question=(
                        f"Red flag '{flag.title}' (severity={flag.severity.value}): "
                        f"{flag.issue} — What is the mitigation plan?"
                    ),
                    priority=Priority.high,
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
