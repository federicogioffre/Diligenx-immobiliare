"""AI analysis pipeline for deals.

Classifies documents, extracts contract clauses, and detects red flags.

Design:
- ``LLMProvider`` ABC makes the Claude client swappable in tests.
- ``FakeLLMProvider`` returns deterministic JSON stubs — no network calls.
- ``DealAnalysisAgent.analyze_deal()`` is idempotent: it clears previous
  ClauseFinding / RedFlag rows before writing new ones.
- Deal status transitions: draft/reviewed → analyzing → reviewed (or back to
  draft on failure).
"""
import json
import logging
import re
import unicodedata
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Valid enum values (must stay in sync with ORM models) ─────────────────

_VALID_CLAUSE_TYPES = {
    "termination", "liability", "indemnification", "confidentiality",
    "non_compete", "payment_terms", "warranty", "intellectual_property",
    "governing_law", "change_of_control", "other",
}

# "critical" is still accepted from LLM output for robustness, but it is
# normalized to "high" before persistence: the Severity enum (and the
# practitioner reports it mirrors) uses a 3-level scale.
_VALID_SEVERITIES = {"low", "medium", "high", "critical"}

_VALID_DD_AREAS = {
    "corporate", "indebtedness", "real_estate", "employees",
    "suppliers_customers", "insurance", "litigation", "ip_it",
    "data_protection", "other",
}


def _normalize_severity(value: str) -> str:
    """Map raw LLM severity to the 3-level Severity enum."""
    if value not in _VALID_SEVERITIES:
        return "medium"
    return "high" if value == "critical" else value


def _parse_dd_area(value: object):
    """Return a DueDiligenceArea for a raw LLM area string, or None."""
    from app.models.red_flag import DueDiligenceArea

    if isinstance(value, str) and value in _VALID_DD_AREAS:
        return DueDiligenceArea(value)
    return None

# ── Grounding check ────────────────────────────────────────────────────────

# Minimum confidence score accepted from the LLM (0–1).
# Clauses with confidence below this threshold are discarded.
_MIN_CONFIDENCE: float = 0.65

# Minimum fraction of content words that must appear in the source text
# for the fuzzy fallback to consider a clause grounded.
# Lowered from 0.80 → 0.65 to accommodate PDF-extraction artefacts and
# minor reformulations by the LLM (especially for non-English documents).
_WORD_OVERLAP_THRESHOLD: float = 0.65


def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace, and strip Unicode diacritics.

    Stripping diacritics allows comparison between PDF-extracted text (which
    may mis-encode accented characters, e.g. Italian 'à' → 'a') and LLM
    output (which preserves the proper Unicode form).
    """
    # NFKD decomposition separates base letter from combining accent marks;
    # keeping only ASCII letters/digits/spaces makes the comparison robust to
    # encoding mismatches without losing semantic content.
    nfkd = unicodedata.normalize("NFKD", text.lower())
    ascii_approx = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_approx).strip()


def is_grounded(content: str, source: str) -> bool:
    """Return True if *content* is grounded in *source*.

    Uses two checks in order:

    1. **Exact substring match** (after whitespace normalisation and stripping
       a trailing ellipsis that the LLM uses when truncating long clauses).
       This is the primary check for truly verbatim extractions.

    2. **Word-overlap fallback** — at least ``_WORD_OVERLAP_THRESHOLD`` of the
       content's words must appear somewhere in the source.  This handles
       minor OCR artefacts, punctuation differences, or line-break collapses
       that prevent an exact match while the content is still real.

    Hallucinated content (invented phrases, wrong party names, non-existent
    amounts, etc.) typically fails both checks and is discarded.
    """
    if not content or not source:
        return False

    # Strip a trailing ellipsis the LLM adds when truncating long clauses.
    # NB: str.rstrip takes a *set of characters*, so rstrip("...") would strip
    # every trailing '.' (mangling e.g. "S.p.A." → "S.p.A"). Use removesuffix.
    raw = content.strip()
    for suffix in ("…", "..."):
        while raw.endswith(suffix):
            raw = raw[: -len(suffix)].strip()
    if not raw:
        return False

    content_norm = _normalise(raw)
    source_norm = _normalise(source)

    # 1. Exact substring match
    if content_norm in source_norm:
        return True

    # Guard against the most dangerous hallucination for legal DD: invented
    # figures (amounts, penalties, dates, percentages). Every numeric token in
    # the content must actually appear in the source, or the clause is rejected
    # regardless of how many surrounding words happen to overlap.
    source_numbers = set(re.findall(r"\d+", source_norm))
    if any(num not in source_numbers for num in re.findall(r"\d+", content_norm)):
        return False

    # 2. Word-overlap fallback
    content_words = content_norm.split()
    if not content_words:
        return False
    source_word_set = set(source_norm.split())
    overlap = sum(1 for w in content_words if w in source_word_set) / len(content_words)
    return overlap >= _WORD_OVERLAP_THRESHOLD

# Document types that warrant full clause extraction
_CONTRACT_TYPES = {"contract", "agreement", "legal"}


# ── LLM Provider abstraction ───────────────────────────────────────────────

class LLMProvider(ABC):
    """Abstract interface for LLM completion providers."""

    @abstractmethod
    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        """Return text completion for the given prompt."""
        ...


class AnthropicLLMProvider(LLMProvider):
    """Claude via the Anthropic SDK.

    Uses Anthropic prompt caching: every prompt is sent as a single
    ``text`` content block tagged with ``cache_control={"type":"ephemeral"}``.

    The pipeline is idempotent — re-running ``/analyze`` for the same deal
    sends the same document text through the same prompt templates. With
    caching, the second pass within Anthropic's 5-minute TTL pays the cheap
    cache-read price (~10% of input cost) instead of re-tokenising the full
    prompt prefix. For prompts shorter than the model's minimum cache size
    (1024 tokens on Sonnet/Opus) the ``cache_control`` marker is silently
    ignored by the API, so flagging every prompt is safe.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=0,  # deterministic — minimises hallucination
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }
            ],
        )
        return msg.content[0].text


class FakeLLMProvider(LLMProvider):
    """Deterministic stub for tests — no network calls required.

    Detects the intent of each prompt by inspecting marker keywords placed
    at the start of every prompt template (e.g. ``CLASSIFY``, ``EXTRACT
    CLAUSES``, ``RED FLAGS``, ``CORPORATE GOVERNANCE``).
    """

    def complete(self, prompt: str, max_tokens: int = 2048) -> str:
        p = prompt.upper()
        # Order matters — prompts may contain keywords from other branches.
        # DUE DILIGENCE REPORT must come before RED FLAGS.
        # ANSWER THE QUESTION must come before CLASSIFY (QA context may
        # contain the word "classify").
        # CORPORATE GOVERNANCE must come before RED FLAGS (governance
        # descriptions may mention risk/flag language).
        if "DUE DILIGENCE REPORT" in p:
            return self._fake_report()
        # EXECUTIVE SUMMARY must come before RED FLAGS — the summary prompt
        # embeds the red-flag findings under a "--- RED FLAGS ---" header.
        if "EXECUTIVE SUMMARY" in p:
            return (
                "The review covered the documents made available for the deal. "
                "Analysis identified one high-severity red flag concerning a "
                "unilateral termination right, which requires specific Sellers' "
                "representations and warranties in the SPA. The remaining "
                "findings are observations with no impact on completion."
            )
        if "ANSWER THE QUESTION" in p:
            return json.dumps({
                "answer": (
                    "Based on the contract documents, either party may "
                    "terminate the agreement with 30 days written notice. "
                    "Liability is capped at the total contract value."
                ),
                "cited_chunks": [0],
            })
        if "CLASSIFY" in p:
            return json.dumps({
                "document_type": "contract",
                "confidence": 0.9,
                "rationale": "Document contains terms, obligations, and signatures.",
            })
        if "EXTRACT CLAUSES" in p:
            return json.dumps([
                {
                    "clause_type": "termination",
                    "title": "Termination Clause",
                    "content": "Either party may terminate with 30 days written notice.",
                    "page_number": 1,
                    "confidence": 0.85,
                },
                {
                    "clause_type": "liability",
                    "title": "Limitation of Liability",
                    "content": "Liability shall not exceed the total contract value.",
                    "page_number": 2,
                    "confidence": 0.80,
                },
            ])
        if "CORPORATE INTRODUCTORY INFORMATION" in p:
            return json.dumps([
                {
                    "company_name": "TargetCo S.p.A.",
                    "legal_form": "Joint-stock company (società per azioni)",
                    "incorporation_date": "Established on 1 January 2010; registered with the Companies' Registry of [REDACTED].",
                    "registered_office": "Italy, [ADDRESS REDACTED]",
                    "corporate_capital": "Euro 1.000.000,00 fully paid",
                    "shareholders": "Holding S.r.l. — 100% of the corporate capital",
                    "pledge": None,
                    "managing_body": "Board of Directors composed of Mr A. (Chairman) and Mr B. (Managing Director), appointed in 2024.",
                    "auditors": "Board of Statutory Auditors: Mr C. (President), Mr D. and Ms E. (Statutory Auditors).",
                    "auditing_company": "Big-4 Auditor S.p.A., mandate until 2026.",
                    "business": "Production and marketing of widgets, as per the corporate purpose in art. 3 of the by-laws.",
                    "fiscal_year": "31 December of each year",
                    "duration": "Until 31 December 2050",
                    "confidence": 0.85,
                    "source_document_id": None,
                }
            ])
        if "CCNL COMPLIANCE" in p:
            # Deterministic stub: return one compliance finding so tests can
            # verify wiring without needing real employment documents.
            return json.dumps([
                {
                    "category": "compensation",
                    "title": "Potential below-minimum salary level",
                    "description": "Salary levels should be verified against CCNL minimum tables.",
                    "severity": "low",
                    "confidence": 0.70,
                }
            ])
        if "RELEVANCE FILTERING" in p:
            # Parse clause indices from the JSON block in the prompt and mark all as high.
            import re as _re
            indices = [int(m) for m in _re.findall(r'"clause_index"\s*:\s*(\d+)', prompt)]
            if not indices:
                return json.dumps([])
            return json.dumps([
                {"clause_index": idx, "relevance": "high", "reason": "Relevant for M&A due diligence."}
                for idx in indices
            ])
        if "CORPORATE GOVERNANCE" in p:
            return json.dumps([
                {
                    "insight_type": "voting_threshold",
                    "title": "Supermajority Required for Major Decisions",
                    "description": (
                        "Requires 75% shareholder approval for material changes, "
                        "creating potential deadlock risk."
                    ),
                    "severity": "medium",
                    "confidence": 0.88,
                },
                {
                    "insight_type": "transfer_restriction",
                    "title": "Right of First Refusal on Share Transfers",
                    "description": (
                        "Existing shareholders have right of first refusal, "
                        "limiting liquidity for minority holders."
                    ),
                    "severity": "low",
                    "confidence": 0.92,
                },
                {
                    "insight_type": "veto_right",
                    "title": "Investor Veto on Key Operational Decisions",
                    "description": (
                        "Preferred shareholders hold veto rights over budget "
                        "approval and acquisitions above $500,000."
                    ),
                    "severity": "high",
                    "confidence": 0.85,
                },
            ])
        if "RED FLAGS" in p:
            return json.dumps([
                {
                    "finding_type": "red_flag",
                    "title": "Unilateral Termination Right",
                    "issue": "Only one party has the right to terminate without cause, creating imbalance.",
                    "risk": "The counterparty may exit the agreement at any time, leaving the target without recourse.",
                    "recommendation": "Insert specific Sellers' representations and warranties in the SPA.",
                    "severity": "high",
                    "area": "suppliers_customers",
                    "category": "termination",
                    "confidence": 0.88,
                    "source_document_id": None,
                },
                {
                    "finding_type": "observation",
                    "title": "Limitation of Liability Clause",
                    "description": "Liability capped at total contract value; standard provision, no immediate risk.",
                    "severity": "low",
                    "category": "liability",
                    "confidence": 0.80,
                    "source_document_id": None,
                },
                {
                    "finding_type": "information_request",
                    "title": "Governing Jurisdiction Not Specified",
                    "description": "No governing law clause identified; confirm applicable jurisdiction before signing.",
                    "severity": "low",
                    "category": "compliance",
                    "confidence": 0.75,
                    "source_document_id": None,
                },
            ])
        return json.dumps([])

    @staticmethod
    def _fake_report() -> str:
        """Canned Markdown report returned for REPORT prompts."""
        return (
            "## Executive Summary\n\n"
            "The deal involves a standard service agreement. Analysis identified "
            "one high-severity red flag and one information request requiring "
            "resolution before signing.\n\n"
            "## Red Flags\n\n"
            "**[HIGH] Unilateral Termination Right** — Art. 5.2 grants only one party "
            "the right to terminate without cause. Obtain a bilateral termination "
            "right or a break-fee mechanism before closing.\n\n"
            "## Observations\n\n"
            "- **[LOW] Limitation of Liability** — Liability capped at total contract "
            "value; standard provision, no immediate risk.\n\n"
            "## Information Requests\n\n"
            "1. **Governing Jurisdiction** — No governing law clause identified; "
            "confirm applicable jurisdiction before signing.\n\n"
            "## Documents Reviewed\n\n"
            "| Document | Language | Pages |\n"
            "|----------|----------|-------|\n"
            "| service_agreement.txt | en | 3 |\n"
        )


# ── Provider singleton ─────────────────────────────────────────────────────

_llm_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider (auto-detects API key).

    Reads ``ANTHROPIC_API_KEY`` from the app ``Settings`` object (which
    loads from ``.env`` via pydantic-settings) so the key is found even
    when it is not present in ``os.environ`` at process start.

    Falls back to ``FakeLLMProvider`` only when the key is genuinely absent.
    """
    global _llm_provider
    if _llm_provider is not None:
        return _llm_provider

    # Prefer the pydantic-settings value (populated from .env) over the raw
    # environment so the key is always found regardless of launch method.
    import os
    try:
        from app.core.config import settings as _settings
        api_key = _settings.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
    except Exception:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if api_key:
        model = "claude-sonnet-4-6"
        try:
            from app.core.config import settings as _settings
            model = _settings.ANALYSIS_MODEL or model
        except Exception:
            pass
        logger.info("Using AnthropicLLMProvider (%s).", model)
        _llm_provider = AnthropicLLMProvider(api_key=api_key, model=model)
    else:
        logger.warning(
            "ANTHROPIC_API_KEY not set — using FakeLLMProvider. "
            "Analysis results will be deterministic stubs."
        )
        _llm_provider = FakeLLMProvider()
    return _llm_provider


def set_llm_provider(provider: LLMProvider | None) -> None:
    """Override the global LLM provider (useful in tests)."""
    global _llm_provider
    _llm_provider = provider


# ── JSON parsing helper ────────────────────────────────────────────────────

def _safe_json(raw: str) -> list | dict:
    """Parse JSON from LLM output, with fallback recovery for truncated arrays.

    The LLM occasionally returns a JSON array whose last element is cut off
    (max-tokens reached mid-string) or contains a character that breaks the
    JSON parser (e.g. an unescaped quote inside Italian legal text).  Rather
    than discarding the entire batch, we attempt to salvage the valid prefix.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop opening fence (```json or ```)
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Fast path — well-formed JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Recovery: for JSON arrays, truncate at the last complete object and
    # close the array.  This preserves all valid items from the batch even
    # when the final item is broken.
    if text.startswith("["):
        # Try closing after the last complete "}," or "}" before end
        last_close = text.rfind("},")
        if last_close == -1:
            last_close = text.rfind("}")
        if last_close > 0:
            candidate = text[: last_close + 1] + "]"
            try:
                result = json.loads(candidate)
                logger.debug(
                    "_safe_json: recovered %d item(s) from truncated JSON array",
                    len(result) if isinstance(result, list) else 1,
                )
                return result
            except json.JSONDecodeError:
                pass

    # Nothing worked — let the original exception propagate so the caller
    # can log it and continue with an empty item list.
    return json.loads(text)


# ── Main agent ─────────────────────────────────────────────────────────────

class DealAnalysisAgent:
    """AI analysis pipeline for a deal.

    For every *processed* document in the deal:
      1. Classify document type.
      2. If it is a contract / agreement / legal document → extract clauses.

    Then across all extracted clause findings:
      3. Detect red flags at the deal level.

    Idempotent: existing ClauseFinding and RedFlag rows are deleted before
    new ones are written, so re-running always produces a clean result.

    Status transitions:
      any → analyzing → reviewed   (success)
      any → analyzing → draft       (failure, rolled back)
    """

    def __init__(self, provider: LLMProvider | None = None):
        self._llm = provider or get_llm_provider()

    # ── Public entry point ────────────────────────────────────────────── #

    def analyze_deal(self, deal_id: int, db: Session) -> dict:
        """Run the full analysis pipeline for a deal.

        Returns::

            {
                "deal_id": int,
                "documents_analyzed": int,
                "clause_findings_count": int,
                "red_flags_count": int,
            }
        """
        from app.models.deal import Deal, DealStatus
        from app.models.document import Document, DocumentStatus
        from app.models.clause_finding import ClauseFinding
        from app.models.red_flag import RedFlag

        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if deal is None:
            raise ValueError(f"Deal {deal_id} not found")

        logger.info("Starting analysis for deal %d ('%s')", deal_id, deal.title)

        # ── 0. Transition status ──────────────────────────────────────── #
        deal.status = DealStatus.analyzing
        db.commit()

        try:
            # ── 1. Idempotency: clear previous results ────────────────── #
            doc_ids = [
                row.id
                for row in db.query(Document.id)
                .filter(Document.deal_id == deal_id)
                .all()
            ]
            if doc_ids:
                db.query(ClauseFinding).filter(
                    ClauseFinding.document_id.in_(doc_ids)
                ).delete(synchronize_session=False)
            db.query(RedFlag).filter(RedFlag.deal_id == deal_id).delete(
                synchronize_session=False
            )
            db.flush()
            logger.debug("Cleared previous analysis results for deal %d.", deal_id)

            # ── 2. Process each processed document ───────────────────── #
            documents = (
                db.query(Document)
                .filter(
                    Document.deal_id == deal_id,
                    Document.status == DocumentStatus.processed,
                )
                .all()
            )

            all_findings: list = []
            documents_analyzed = 0

            for doc in documents:
                logger.info("Analysing document %d (%s)", doc.id, doc.filename)
                text = self._get_document_text(doc)
                if not text:
                    logger.warning(
                        "Document %d has no text — skipping.", doc.id
                    )
                    continue

                doc_type = self._classify_document(text, doc.filename)
                logger.info(
                    "Document %d classified as '%s' (confidence=%.2f)",
                    doc.id,
                    doc_type["document_type"],
                    doc_type.get("confidence", 0.0),
                )

                if doc_type["document_type"] in _CONTRACT_TYPES:
                    findings = self._extract_clauses(doc.id, text, db)
                    all_findings.extend(findings)
                    logger.info(
                        "Extracted %d clause findings from document %d.",
                        len(findings),
                        doc.id,
                    )

                documents_analyzed += 1

            # ── 3. Red-flag detection across all findings ─────────────── #
            red_flags = self._detect_red_flags(deal_id, all_findings, db)
            logger.info(
                "Detected %d red flags for deal %d.", len(red_flags), deal_id
            )

            # ── 4. Finalise ───────────────────────────────────────────── #
            deal.status = DealStatus.reviewed
            db.commit()

            result = {
                "deal_id": deal_id,
                "documents_analyzed": documents_analyzed,
                "clause_findings_count": len(all_findings),
                "red_flags_count": len(red_flags),
            }
            logger.info("Analysis complete for deal %d: %s", deal_id, result)
            return result

        except Exception:
            logger.exception("Analysis failed for deal %d", deal_id)
            db.rollback()
            deal = db.query(Deal).filter(Deal.id == deal_id).first()
            if deal:
                deal.status = DealStatus.draft
                db.commit()
            raise

    # ── Step helpers ──────────────────────────────────────────────────── #

    # Maximum characters sent to the LLM per extraction batch.
    # claude-sonnet-4-6 has a 200k-token context window; 80k chars ≈ 20k tokens,
    # leaving ample room for the prompt template and the JSON response.
    _BATCH_CHARS = 80_000

    def _get_document_text(self, doc) -> str:
        """Return the full document text.

        Prefers ``doc.raw_text`` (stored during ingestion).  Falls back to an
        empty string so callers can skip documents without text gracefully.
        """
        return doc.raw_text or ""

    @staticmethod
    def _split_into_batches(text: str, batch_size: int) -> list[str]:
        """Split *text* into non-overlapping batches of at most *batch_size* chars.

        Splits on newlines where possible so clauses are not cut mid-sentence.
        """
        if not text:
            return []
        if len(text) <= batch_size:
            return [text]
        batches: list[str] = []
        start = 0
        while start < len(text):
            end = start + batch_size
            if end < len(text):
                # Try to break on a newline boundary
                nl = text.rfind("\n", start, end)
                if nl > start:
                    end = nl + 1
            batches.append(text[start:end])
            start = end
        return batches

    def _classify_document(self, text: str, filename: str = "") -> dict:
        """Ask the LLM to classify the document type."""
        from packages.prompts.deal_prompts import DOCUMENT_CLASSIFICATION_PROMPT

        # Classification only needs a representative excerpt
        prompt = DOCUMENT_CLASSIFICATION_PROMPT.format(
            filename=filename,
            text=text[:4000],
        )
        raw = self._llm.complete(prompt, max_tokens=256)
        try:
            return _safe_json(raw)
        except Exception:
            logger.warning("Classification parse error: %r", raw)
            return {"document_type": "other", "confidence": 0.0, "rationale": raw}

    def _extract_clauses(
        self, document_id: int, text: str, db: Session
    ) -> list:
        """Extract clauses from the full document text, processing in batches.

        Sends the document in chunks of up to ``_BATCH_CHARS`` characters so
        that long contracts are fully analysed rather than silently truncated.
        Persists ``ClauseFinding`` rows and returns the created objects.
        """
        from app.models.clause_finding import ClauseFinding, ClauseType
        from packages.prompts.deal_prompts import CLAUSE_EXTRACTION_PROMPT

        batches = self._split_into_batches(text, self._BATCH_CHARS)
        findings = []

        for batch_idx, batch_text in enumerate(batches):
            prompt = CLAUSE_EXTRACTION_PROMPT.format(
                text=batch_text,
                batch_info=(
                    f"(Part {batch_idx + 1} of {len(batches)})"
                    if len(batches) > 1
                    else ""
                ),
            )
            raw = self._llm.complete(prompt, max_tokens=8192)
            try:
                items = _safe_json(raw)
            except Exception as exc:
                logger.warning(
                    "Clause extraction parse error for doc %d batch %d (%s); "
                    "last 300 chars: %r",
                    document_id, batch_idx, exc, raw[-300:],
                )
                items = []

            for item in items if isinstance(items, list) else []:
                content = item.get("content", "")
                confidence = item.get("confidence")

                # ── Grounding check ──────────────────────────────────── #
                # Discard low-confidence items
                if confidence is not None and confidence < _MIN_CONFIDENCE:
                    logger.debug(
                        "doc=%d batch=%d — dropped low-confidence clause "
                        "(%.2f): %r", document_id, batch_idx, confidence,
                        item.get("title", ""),
                    )
                    continue

                # Discard items whose content cannot be found in the source
                if not is_grounded(content, batch_text):
                    logger.warning(
                        "doc=%d batch=%d — dropped hallucinated clause "
                        "(not found in source): %r | content: %r",
                        document_id, batch_idx,
                        item.get("title", ""), content[:120],
                    )
                    continue

                clause_type_str = item.get("clause_type", "other")
                if clause_type_str not in _VALID_CLAUSE_TYPES:
                    clause_type_str = "other"
                finding = ClauseFinding(
                    document_id=document_id,
                    clause_type=ClauseType(clause_type_str),
                    title=str(item.get("title", ""))[:500],
                    content=content,
                    page_number=item.get("page_number"),
                    confidence=confidence,
                )
                db.add(finding)
                findings.append(finding)

        db.flush()
        return findings

    def _detect_red_flags(
        self, deal_id: int, clause_findings: list, db: Session
    ) -> list:
        """Detect red flags from collected clause findings and persist RedFlag rows."""
        from app.models.red_flag import RedFlag, Severity
        from packages.prompts.deal_prompts import RED_FLAG_DETECTION_PROMPT

        findings_text = (
            "\n".join(
                f"- [{f.clause_type.value}] {f.title}: {f.content[:200]}"
                for f in clause_findings
            )
            or "No clause findings available."
        )

        prompt = RED_FLAG_DETECTION_PROMPT.format(findings=findings_text)
        raw = self._llm.complete(prompt, max_tokens=2048)
        try:
            items = _safe_json(raw)
        except Exception:
            logger.warning(
                "Red-flag parse error for deal %d: %r", deal_id, raw
            )
            items = []

        red_flags = []
        for item in items if isinstance(items, list) else []:
            severity_str = _normalize_severity(item.get("severity", "medium"))
            flag = RedFlag(
                deal_id=deal_id,
                title=str(item.get("title", ""))[:500],
                # "description" is the legacy LLM output key for the issue.
                issue=item.get("issue") or item.get("description", ""),
                risk=item.get("risk"),
                recommendation=item.get("recommendation"),
                severity=Severity(severity_str),
                area=_parse_dd_area(item.get("area")),
                category=str(item.get("category", "general"))[:100],
                confidence=item.get("confidence"),
                source_document_id=item.get("source_document_id"),
            )
            db.add(flag)
            red_flags.append(flag)

        db.flush()
        return red_flags


# ── Module-level convenience function ─────────────────────────────────────

def analyze_deal(
    deal_id: int, db: Session, provider: LLMProvider | None = None
) -> dict:
    """Create a ``DealAnalysisAgent`` and run the full pipeline."""
    return DealAnalysisAgent(provider=provider).analyze_deal(deal_id, db)
