"""AI analysis pipeline for deals.

Classifies documents, extracts contract clauses, and detects red flags.

Design:
- ``LLMProvider`` ABC makes the model client swappable in tests.
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
from packages.llm_config import DEFAULT_ANALYSIS_MODEL, analysis_api_key_name

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
    "data_protection", "financial", "tax", "other",
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

# Model families that still accept ``temperature`` / ``top_p`` / ``top_k``:
# the Claude 4.6 / 4.5 line (Opus 4.6, Sonnet 4.6, Opus 4.5, Sonnet 4.5,
# Haiku 4.5) and everything older. Opus 4.7+, Sonnet 5 and the Claude 5
# family (Opus 5, Fable, Mythos) return a 400 for any sampling parameter.
_SAMPLING_PARAM_MODELS = re.compile(
    r"claude-(?:(?:opus|sonnet|haiku)-(?:4-[0-6]|4(?:-\d{8})?$|3(?:-\d)?)|3-)"
)


def _accepts_sampling_params(model: str) -> bool:
    """True when *model* still honours ``temperature`` (see above)."""
    return bool(_SAMPLING_PARAM_MODELS.match(model))


class LLMResponseError(RuntimeError):
    """An AI response is incomplete or cannot be used as analysis evidence."""


class LLMFormatError(LLMResponseError):
    """A completed response has an invalid data format; one retry is allowed."""


class LLMTruncatedError(LLMResponseError):
    """The model spent its whole output budget without finishing the answer.

    Usually a runaway generation (a loop on a short input); retried once by
    ``_complete_json`` because it is stochastic, then fatal for that request.
    """



class LLMProvider(ABC):
    """Abstract interface for LLM completion providers."""

    @abstractmethod
    def complete(self, prompt: str, max_tokens: int = 3072) -> str:
        """Return text completion for the given prompt."""
        ...

    def complete_json(
        self, prompt: str, max_tokens: int = 3072, *, response_type: str = "array",
        item_schema: dict | None = None,
    ) -> str:
        """JSON transport hook; text-only providers retain their existing API."""
        return self.complete(prompt, max_tokens=max_tokens)


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

    Sampling: ``temperature=0`` keeps the analysis output as repeatable as
    possible across re-runs. The 1.x Anthropic SDK removed ``temperature``
    from the ``messages.create()`` signature (passing it is a ``TypeError``),
    so it is sent through ``extra_body`` — and only for the model families
    that still accept sampling parameters (the Claude 4.6 / 4.5 line and
    older). Claude Opus 4.7+, Sonnet 5 and the Claude 5 family reject the
    parameter with a 400, so for those the request carries no temperature.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-5"):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _extra_body(self) -> dict | None:
        if _accepts_sampling_params(self._model):
            return {"temperature": 0}
        return None

    def _request(self, prompt: str, max_tokens: int, **options):
        from time import monotonic
        from packages.agents.provider_limits import llm_slot
        started = monotonic()
        # Sonnet 5 enables thinking by default. Preserve the pipeline
        # contract: max_tokens is reserved for the extracted answer.
        thinking_options = (
            {"thinking": {"type": "disabled"}}
            if self._model == "claude-sonnet-5" or self._model.startswith("claude-sonnet-5-")
            else {}
        )
        with llm_slot():
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                extra_body=self._extra_body(),
                **thinking_options,
                **options,
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
        usage = getattr(msg, "usage", None)
        logger.info(
            "llm_usage model=%s seconds=%.3f input_tokens=%s output_tokens=%s cache_read_tokens=%s cache_write_tokens=%s stop_reason=%s",
            self._model, monotonic() - started,
            getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None),
            getattr(usage, "cache_read_input_tokens", None), getattr(usage, "cache_creation_input_tokens", None),
            msg.stop_reason,
        )
        if msg.stop_reason == "refusal":
            raise LLMResponseError("AI provider refused the analysis request")
        if msg.stop_reason == "max_tokens":
            raise LLMTruncatedError("AI response was truncated at the output token limit")
        return msg

    def complete(self, prompt: str, max_tokens: int = 3072) -> str:
        msg = self._request(prompt, max_tokens)
        text = "".join(
            block.text for block in msg.content
            if isinstance(getattr(block, "text", None), str)
        )
        if not text.strip():
            raise LLMResponseError("AI response contained no text")
        return text

    def complete_json(
        self, prompt: str, max_tokens: int = 3072, *, response_type: str = "array",
        item_schema: dict | None = None,
    ) -> str:
        """Get data through a single tool input, separate from assistant prose.

        No tool is executed: this is only a structured response envelope.
        The stage-specific fields are defined in each analysis prompt and
        validated by the caller. Refusals and token-limit stops remain fatal.
        """
        if response_type not in {"array", "object"}:
            raise ValueError("Unsupported JSON response type")
        schema = {"type": response_type}
        if response_type == "array":
            schema["items"] = item_schema if item_schema is not None else {"type": "object"}
        elif item_schema is not None:
            raise ValueError("An item schema requires an array response")
        msg = self._request(
            prompt, max_tokens,
            tools=[{
                "name": "submit_analysis",
                **({"strict": True} if item_schema is not None else {}),
                "description": (
                    "Submit the complete analysis requested in the user prompt. "
                    "Put the requested JSON value in the result field, using every "
                    "field and all records required by that prompt. Preserve all "
                    "source evidence, qualifications and the requested language. "
                    "An empty array is valid only when the analysis found no items. "
                    "Do not put analysis data in assistant text or call this tool twice."
                ),
                "input_schema": {
                    "type": "object", "properties": {"result": schema},
                    "required": ["result"], "additionalProperties": False,
                },
            }],
            tool_choice={"type": "tool", "name": "submit_analysis", "disable_parallel_tool_use": True},
        )
        calls = [block for block in msg.content if getattr(block, "type", None) == "tool_use"]
        if (
            msg.stop_reason != "tool_use" or len(calls) != 1
            or calls[0].name != "submit_analysis"
            or not isinstance(calls[0].input, dict)
            or set(calls[0].input) != {"result"}
        ):
            raise LLMFormatError("AI provider did not return one complete structured analysis")
        try:
            return json.dumps(calls[0].input["result"], ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise LLMFormatError("AI provider returned invalid structured data") from exc


class OpenAILLMProvider(LLMProvider):
    """OpenAI Responses with one explicit data submission and no fallback model."""

    def __init__(self, api_key: str, model: str = DEFAULT_ANALYSIS_MODEL):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def _request(self, prompt: str, max_tokens: int, **options):
        from time import monotonic
        from packages.agents.provider_limits import llm_slot
        started = monotonic()
        with llm_slot():
            response = self._client.responses.create(
                model=self._model, input=prompt, max_output_tokens=max_tokens,
                # Match the previous non-thinking workload: the existing stage
                # limits remain answer budgets rather than hidden reasoning.
                reasoning={"effort": "none"}, store=False, truncation="disabled",
                **options,
            )
        usage = getattr(response, "usage", None)
        logger.info(
            "llm_usage provider=openai model=%s seconds=%.3f input_tokens=%s output_tokens=%s "
            "cache_read_tokens=%s reasoning_tokens=%s status=%s",
            self._model, monotonic() - started,
            getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None),
            getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", None),
            getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", None),
            response.status,
        )
        if any(getattr(part, "type", None) == "refusal"
               for item in response.output for part in getattr(item, "content", [])):
            raise LLMResponseError("AI provider refused the analysis request")
        if response.status != "completed" or getattr(response, "error", None):
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            if reason == "max_output_tokens":
                raise LLMTruncatedError("AI response was truncated at the output token limit")
            raise LLMResponseError(f"AI response did not complete (status={response.status})")
        return response

    def complete(self, prompt: str, max_tokens: int = 3072) -> str:
        response = self._request(prompt, max_tokens)
        text = response.output_text
        if not isinstance(text, str) or not text.strip():
            raise LLMResponseError("AI response contained no text")
        return text

    def complete_json(
        self, prompt: str, max_tokens: int = 3072, *, response_type: str = "array",
        item_schema: dict | None = None,
    ) -> str:
        if response_type not in {"array", "object"}:
            raise ValueError("Unsupported JSON response type")
        schema = {"type": response_type}
        if response_type == "array":
            schema["items"] = item_schema if item_schema is not None else {"type": "object"}
        elif item_schema is not None:
            raise ValueError("An item schema requires an array response")
        response = self._request(
            prompt, max_tokens,
            tools=[{
                "type": "function", "name": "submit_analysis",
                # Generic specialist records have prompt-defined fields. Do not
                # let Responses auto-normalize those open objects into empty ones.
                "strict": item_schema is not None,
                "description": (
                    "Submit the complete analysis requested in the user prompt. "
                    "Put the requested JSON value in result, preserving all records, "
                    "fields, source evidence, qualifications and requested language. "
                    "An empty array is valid only when no items were found. "
                    "Do not put analysis data in assistant text or call twice."
                ),
                "parameters": {"type": "object", "properties": {"result": schema},
                               "required": ["result"], "additionalProperties": False},
            }],
            tool_choice={"type": "function", "name": "submit_analysis"},
            parallel_tool_calls=False,
        )
        calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
        if (len(calls) != 1 or calls[0].name != "submit_analysis"
                or calls[0].status != "completed"):
            raise LLMFormatError("AI provider did not return one complete structured analysis")
        try:
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate JSON field")
                    result[key] = value
                return result

            envelope = json.loads(calls[0].arguments, object_pairs_hook=unique_object)
            if not isinstance(envelope, dict) or set(envelope) != {"result"}:
                raise ValueError("Invalid result envelope")
            expected = list if response_type == "array" else dict
            if not isinstance(envelope["result"], expected):
                raise ValueError("Invalid result type")
            return json.dumps(envelope["result"], ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise LLMFormatError("AI provider returned invalid structured data") from exc


def create_llm_provider(api_key: str, model: str = DEFAULT_ANALYSIS_MODEL) -> LLMProvider:
    provider_class = OpenAILLMProvider if analysis_api_key_name(model) == "OPENAI_API_KEY" else AnthropicLLMProvider
    return provider_class(api_key=api_key, model=model)


class FakeLLMProvider(LLMProvider):
    """Deterministic stub for tests — no network calls required.

    Detects the intent of each prompt by inspecting marker keywords placed
    at the start of every prompt template (e.g. ``CLASSIFY``, ``EXTRACT
    CLAUSES``, ``RED FLAGS``, ``CORPORATE GOVERNANCE``).
    """

    def complete(self, prompt: str, max_tokens: int = 3072) -> str:
        p = prompt.upper()
        if "GROUNDING REVIEW\n" in prompt:
            # Deterministic protocol stub only. Tests for unsupported prose use
            # explicit adversarial review responses instead of this provider.
            payload = json.loads(prompt.rsplit("INPUT_JSON:\n", 1)[1])
            reviewed = []
            for item in payload["items"]:
                candidate = item["candidate"]
                fields = {
                    k: candidate.get(k) for k in
                    (("text",) if payload["kind"] == "text" else
                     ("title", "issue", "risk", "recommendation"))
                }
                documents = payload["documents"]
                doc = next((d for d in documents if d["document_id"] == candidate.get("source_document_id")),
                           documents[0] if documents else None)
                reviewed.append({
                    "index": item["index"], "supported": True, "fields": fields,
                    "evidence": ([{"source_document_id": doc["document_id"],
                                   "quote": doc["text"], "fields": list(fields)}]
                                 if doc else []),
                })
            return json.dumps(reviewed)
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
            if "OUTPUT LANGUAGE: WRITE ALL FREE-TEXT OUTPUT IN ITALIAN." in p:
                return "La revisione riguarda i documenti disponibili per l'operazione. I rilievi e le relative condizioni sono riportati nelle sezioni successive."
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
            input_block = prompt.split("INPUT CLAUSES:", 1)[1].split("Return ONLY", 1)[0]
            indices = [int(m) for m in _re.findall(r'"clause_index"\s*:\s*(\d+)', input_block)]
            if not indices:
                return json.dumps([])
            return json.dumps([
                {"clause_index": idx, "relevance": "high", "reason": "Relevant for M&A due diligence."}
                for idx in indices
            ])
        if "ANALYZE FINANCIAL STATEMENTS" in p:
            return json.dumps([
                {
                    "finding_type": "auditor_opinion",
                    "title": "Qualified opinion on the FY2023 financial statements",
                    "description": (
                        "The auditors issued a qualified opinion on the FY2023 "
                        "financial statements over the recoverability of "
                        "receivables from related parties."
                    ),
                    "amount_eur": None,
                    "counterparty": None,
                    "change_of_control_clause": None,
                    "financial_covenant": None,
                    "severity": "high",
                    "confidence": 0.88,
                },
                {
                    "finding_type": "covenant",
                    "title": "Financial covenants on the term loan",
                    "description": (
                        "The notes disclose a net debt / EBITDA covenant on the "
                        "term loan, tested semi-annually, with a change-of-control "
                        "event of default."
                    ),
                    "amount_eur": None,
                    "counterparty": "Bank",
                    "change_of_control_clause": True,
                    "financial_covenant": True,
                    "severity": "medium",
                    "confidence": 0.84,
                },
                {
                    "finding_type": "debt_like_item",
                    "title": "Overdue VAT payables",
                    "description": (
                        "VAT payables of Euro 120.000 relating to prior periods "
                        "were still unpaid at the balance-sheet date."
                    ),
                    "amount_eur": 120000,
                    "counterparty": None,
                    "change_of_control_clause": None,
                    "financial_covenant": None,
                    "severity": "high",
                    "confidence": 0.86,
                },
                {
                    "finding_type": "equity_position",
                    "title": "Capital contribution reserve",
                    "description": (
                        "A versamento in conto capitale of Euro 250.000 is "
                        "recorded among the reserves; repayment terms are not "
                        "specified in the notes."
                    ),
                    "amount_eur": 250000,
                    "counterparty": None,
                    "change_of_control_clause": None,
                    "financial_covenant": None,
                    "severity": "low",
                    "confidence": 0.79,
                },
            ])

        if "ANALYZE TAX MATTERS" in p:
            return json.dumps([
                {
                    "finding_type": "tax_assessment",
                    "tax_kind": "ires",
                    "title": "Notified tax assessment for FY2022",
                    "description": (
                        "Avviso di accertamento notified for FY2022 claiming "
                        "Euro 240.000 in additional IRES, penalties and interest; "
                        "appeal pending before the first-instance tax court."
                    ),
                    "legal_basis": "art. 39 D.P.R. 600/1973",
                    "fiscal_years": [2022],
                    "amount_eur": 240000,
                    "defensibility": "high",
                    "mitigating_factors": [],
                    "confidence": 0.90,
                },
                {
                    "finding_type": "tax_debt",
                    "tax_kind": "iva",
                    "title": "Ongoing instalment plan with the collection agency",
                    "description": (
                        "A 72-instalment payment plan (rateizzazione) with "
                        "Agenzia delle Entrate-Riscossione is in progress for "
                        "Euro 85.000 of assessed VAT."
                    ),
                    "legal_basis": None,
                    "fiscal_years": [2021],
                    "amount_eur": 85000,
                    "defensibility": "medium",
                    "mitigating_factors": ["instalment_plan_in_force"],
                    "confidence": 0.85,
                },
                {
                    "finding_type": "tax_regime",
                    "tax_kind": "ires",
                    "title": "Patent box election in force",
                    "description": (
                        "The company elected the patent box regime for the "
                        "2021-2025 period; no current exposure evidenced."
                    ),
                    "legal_basis": None,
                    "fiscal_years": [],
                    "amount_eur": None,
                    "defensibility": "low",
                    "mitigating_factors": [],
                    "confidence": 0.80,
                },
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
            if "No findings available." in prompt:
                return "[]"
            flags = [
                {
                    "finding_type": "red_flag",
                    "title": "Unilateral Termination Right",
                    "issue": "Only one party has the right to terminate without cause, creating imbalance.",
                    "risk": "The counterparty may exit the agreement at any time, leaving the target without recourse.",
                    "recommendation": "Insert specific Sellers' representations and warranties in the SPA.",
                    "remedy_type": "warranty",
                    "impact": "spa",
                    "amount_eur": None,
                    "fiscal_years": [],
                    "severity": "high",
                    "area": "suppliers_customers",
                    "category": "termination",
                    "confidence": 0.88,
                    "source_document_id": None,
                },
                {
                    "finding_type": "red_flag",
                    "title": "Notified tax assessment for FY2022",
                    "issue": (
                        "An avviso di accertamento for FY2022 claims Euro "
                        "240.000 of additional IRES, penalties and interest."
                    ),
                    "risk": (
                        "If upheld, the target bears the assessed amount plus "
                        "litigation costs; other open years may follow."
                    ),
                    "recommendation": (
                        "Insert a specific indemnity in the SPA covering the "
                        "assessed exposure, surviving until the expiry of the "
                        "assessment period for FY2022 plus a grace period."
                    ),
                    "remedy_type": "indemnity",
                    "impact": "value",
                    "amount_eur": 240000,
                    "fiscal_years": [2022],
                    "severity": "high",
                    "area": "tax",
                    "category": "tax_assessment",
                    "confidence": 0.90,
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
            ]
            if "OUTPUT LANGUAGE: WRITE ALL FREE-TEXT OUTPUT IN ITALIAN." in p:
                localized = [
                    ("Diritto di recesso unilaterale", "Solo una parte può recedere senza causa.",
                     "La controparte può interrompere il contratto lasciando la target senza tutela.",
                     "Prevedere garanzie specifiche del venditore nel contratto di acquisizione."),
                    ("Avviso fiscale relativo al 2022", "Un avviso contesta EUR 240.000 per imposte, sanzioni e interessi.",
                     "Se confermata, la pretesa comporta un esborso per la target.",
                     "Negoziare una garanzia specifica sull'esposizione contestata."),
                    ("Limitazione di responsabilità", "La responsabilità è limitata al valore del contratto.", None, None),
                    ("Giurisdizione da verificare", "Non è identificata una clausola sulla giurisdizione applicabile.", None, None),
                ]
                for flag, values in zip(flags, localized):
                    flag.update(dict(zip(("title", "issue", "risk", "recommendation"), values)))
                    flag.pop("description", None)
            return json.dumps(flags)
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
    """Select by model, never by whichever vendor key happens to be present."""
    global _llm_provider
    if _llm_provider is not None:
        from app.core.config import settings
        if settings.BETA_MODE and isinstance(_llm_provider, FakeLLMProvider):
            raise RuntimeError("BETA_MODE cannot use fake LLM analysis")
        return _llm_provider

    from app.core.config import settings
    import os
    model = settings.ANALYSIS_MODEL or DEFAULT_ANALYSIS_MODEL
    key_name = analysis_api_key_name(model)
    api_key = getattr(settings, key_name) or os.environ.get(key_name, "")
    if api_key:
        _llm_provider = create_llm_provider(api_key, model)
        logger.info("Using %s (%s).", type(_llm_provider).__name__, model)
    else:
        if settings.BETA_MODE:
            raise RuntimeError("BETA_MODE cannot use fake LLM analysis")
        if any(getattr(settings, name) or os.environ.get(name, "")
               for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")):
            raise RuntimeError(f"{key_name} is required for ANALYSIS_MODEL={model}")
        logger.warning(
            "No provider keys set — using FakeLLMProvider. "
            "Analysis results will be deterministic stubs."
        )
        _llm_provider = FakeLLMProvider()
    return _llm_provider


def set_llm_provider(provider: LLMProvider | None) -> None:
    """Override the global LLM provider (useful in tests)."""
    global _llm_provider
    _llm_provider = provider


# ── JSON parsing helper ────────────────────────────────────────────────────

def _escape_stray_quotes(text: str) -> str:
    """Escape double quotes the model left unescaped *inside* JSON strings.

    Italian legal text is full of quoted terms (``la clausola "change of
    control"``, ``il c.d. "patto di non concorrenza"``) and the model
    regularly copies them into a ``content`` value without escaping. The
    parser then fails with ``Expecting ',' delimiter`` and the whole batch
    of clauses is lost.

    Heuristic: walk the text tracking whether we are inside a string. A
    quote met inside a string closes it only if the next non-blank character
    is a structural token (``,`` ``}`` ``]`` ``:``); otherwise it is part of
    the text and gets escaped. A stray quote immediately followed by a comma
    is still ambiguous and left alone; invalid JSON then fails explicitly.
    """
    out: list[str] = []
    in_str = False
    escaped = False
    n = len(text)
    for i, ch in enumerate(text):
        if not in_str:
            if ch == '"':
                in_str = True
            out.append(ch)
            continue
        if escaped:
            escaped = False
            out.append(ch)
            continue
        if ch == "\\":
            escaped = True
            out.append(ch)
            continue
        if ch == '"':
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j >= n or text[j] in ",}]:":
                in_str = False
                out.append(ch)
            else:
                out.append('\\"')
            continue
        out.append(ch)
    return "".join(out)


def _safe_json(raw: str) -> list | dict:
    """Repair escaping errors only; never accept a truncated array prefix.

    Recovering the first objects silently loses findings. Callers must
    propagate invalid or incomplete responses so the orchestrator can
    preserve the previous outputs.
    """
    if not isinstance(raw, str):
        raise LLMFormatError("AI response contains incomplete or invalid JSON")
    text = raw.strip()
    fence = "```"
    if text.startswith(fence):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith(fence):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Do not change valid JSON, including literal backslashes/apostrophes.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Repair an odd backslash before an apostrophe; preserve escaped pairs.
    text = re.sub(r"(?<!\\)((?:\\\\)*)\\'", r"\1'", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Keep the PR 37 repair for unescaped quotes in document text.
    try:
        return json.loads(_escape_stray_quotes(text))
    except json.JSONDecodeError as exc:
        raise LLMFormatError("AI response contains incomplete or invalid JSON") from exc


def _parse_llm_items(raw: str, *, context: str) -> list[dict]:
    """Only an explicit, valid [] means that the model found no items."""
    try:
        items = _safe_json(raw)
    except LLMResponseError as exc:
        raise LLMResponseError(f"{context}: {exc}") from exc
    if not isinstance(items, list) or any(
        not isinstance(item, dict) or not item for item in items
    ):
        raise LLMResponseError(f"{context}: expected a JSON array of non-empty objects")
    return items


def _complete_json(
    provider: LLMProvider, prompt: str, *, max_tokens: int,
    context: str, response_type: str, item_schema: dict | None = None, validate_shape=None,
) -> list | dict:
    """Retry a format error or a truncated answer once, never dropping records.

    Transport errors and refusals are not retried. A truncated answer is
    almost always a runaway generation on a short input, which is stochastic:
    one retry with an explicit compactness instruction usually completes.
    The complete original source prompt is retained on the second attempt.
    Logs contain diagnostics only, never document text or model responses.
    """
    format_prefix = (
        "FORMAT RETRY: Return the complete requested analysis in the required JSON "
        "shape. Include every record and field. Do not substitute an empty result "
        "for a formatting failure. Follow the original task and source below.\n\n"
    )
    truncation_prefix = (
        "OUTPUT LIMIT RETRY: The previous answer exceeded the output limit before "
        "the JSON was complete. Return the complete requested analysis compactly: "
        "every record once, no repetition, no commentary, quotations kept to the "
        "passage that matters. Follow the original task and source below.\n\n"
    )
    retry_prefix = format_prefix
    for attempt in range(2):
        try:
            request_prompt = prompt if attempt == 0 else retry_prefix + prompt
            complete_json = getattr(provider, "complete_json", None)
            schema_options = {"item_schema": item_schema} if item_schema is not None else {}
            raw = (
                complete_json(request_prompt, max_tokens=max_tokens, response_type=response_type, **schema_options)
                if callable(complete_json) else provider.complete(request_prompt, max_tokens=max_tokens)
            )
            result = _safe_json(raw)
            valid = (
                isinstance(result, list) and all(isinstance(item, dict) and item for item in result)
                if response_type == "array" else isinstance(result, dict) and bool(result)
            )
            if not valid:
                raise LLMFormatError(f"AI response has an invalid JSON {response_type} shape")
            if validate_shape is not None:
                validate_shape(result)
            return result
        except LLMFormatError as exc:
            logger.warning("llm_json_format_error context=%s attempt=%d reason=%s", context, attempt + 1, exc)
            if attempt == 1:
                raise LLMResponseError(f"{context}: invalid AI response format after 2 attempts ({exc})") from exc
            retry_prefix = format_prefix
        except LLMTruncatedError as exc:
            logger.warning("llm_output_truncated context=%s attempt=%d", context, attempt + 1)
            if attempt == 1:
                raise LLMResponseError(f"{context}: {exc} (after 2 attempts)") from exc
            retry_prefix = truncation_prefix
        except LLMResponseError as exc:
            raise LLMResponseError(f"{context}: {exc}") from exc
    raise AssertionError("Unreachable JSON retry state")


def _complete_llm_items(
    provider: LLMProvider, prompt: str, *, max_tokens: int, context: str,
    item_schema: dict | None = None, validate_shape=None,
) -> list[dict]:
    return _complete_json(
        provider, prompt, max_tokens=max_tokens, context=context, response_type="array",
        item_schema=item_schema, validate_shape=validate_shape,
    )


def _complete_classification(provider: LLMProvider, prompt: str, *, context: str) -> dict:
    result = _complete_json(provider, prompt, max_tokens=512, context=context, response_type="object")
    return _parse_classification(json.dumps(result, ensure_ascii=False))


VALID_DOCUMENT_TYPES = frozenset({
    "contract", "agreement", "legal", "invoice", "financial_statement", "tax", "report", "other",
})


def _parse_classification(raw: str) -> dict:
    result = _safe_json(raw)
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("document_type"), str)
        or not result["document_type"].strip()
    ):
        raise LLMResponseError("Document classification: expected an object with document_type")
    document_type = result["document_type"].strip().lower()
    if document_type not in VALID_DOCUMENT_TYPES:
        raise LLMResponseError("Document classification: unsupported document_type")
    result["document_type"] = document_type
    return result


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
    # Keep batches bounded independently of the model context window,
    # leaving room for the prompt template and the structured response.
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
        return _complete_classification(self._llm, prompt, context="Document classification")

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
            items = _complete_llm_items(
                self._llm, prompt, max_tokens=12288,
                context=f"Contract document {document_id}, batch {batch_idx + 1}"
            )

            for item in items:
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
                    page_number=None,
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
        items = _complete_llm_items(self._llm, prompt, max_tokens=3072, context=f"Red flags for deal {deal_id}")

        red_flags = []
        for item in items:
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
