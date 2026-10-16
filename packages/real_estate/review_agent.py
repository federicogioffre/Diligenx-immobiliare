"""Documentary reviewer shared by the four real-estate specialists.

The pattern is the one Diligenx's tax and financial agents implement, made
declarative: a specialist states its name, the document types routing
sends it, the keywords that select a document on their own, its prompt,
its finding types and its keyword floor; this class does the rest —

* select documents: routing output ∪ keyword detection;
* commit before the LLM phase, then analyse every document in overlapping
  batches on one bounded queue (``collect_documents_payloads``), so a long
  notarial report does not become a sequential tail of the stage;
* validate each finding: known type, three-level severity, an amount only
  when a verbatim quotation in the text carries it (``grounded_amount``);
* add **floor findings** for keywords the model must not silently drop (a
  "pignoramento" in a registry search is a finding whatever the model said),
  at most one per type and only where the model produced nothing as severe;
* persist ``AgentFinding`` rows, replacing the previous run's in the same
  transaction, and keep a failed document's previous findings, recording the
  gap as an open question (``record_unanalysed_documents``).

A specialist may enrich a payload deterministically in ``enrich`` — the
title-chain reviewer computes whether a donation is still within the
twenty-year window, the encumbrances reviewer whether a mortgage
registration has passed twenty years — so the model never does arithmetic
on dates.
"""
from __future__ import annotations

import logging
from typing import NamedTuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    _complete_llm_items,
    _normalize_severity,
    get_llm_provider,
)
from packages.real_estate import stage_support

logger = logging.getLogger(__name__)

_HEURISTIC_CONFIDENCE = 0.60
_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}


class Heuristic(NamedTuple):
    """A keyword whose presence the review must never drop."""

    keyword: str
    finding_type: str
    title: str
    severity: str
    note: str | None = None


class DocumentReviewAgent:
    """Base class; subclasses only declare data and, optionally, ``enrich``."""

    AGENT_NAME: str = ""
    ROUTED_TYPES: frozenset[str] = frozenset()
    DOC_KEYWORDS: tuple[str, ...] = ()
    PROMPT: str = ""
    VALID_FINDING_TYPES: frozenset[str] = frozenset()
    FALLBACK_TYPE: str = "other"
    HEURISTICS: tuple[Heuristic, ...] = ()
    MAX_TOKENS = 8192
    BATCH_CHARS = 10000

    def __init__(self, provider: LLMProvider | None = None):
        self._llm = provider or get_llm_provider()

    # ── Entry point ─────────────────────────────────────────────────────

    def run(
        self,
        deal_id: int,
        db: Session,
        *,
        classifications: list[dict] | None = None,
        document_ids: set[int] | None = None,
    ) -> dict:
        from app.core.config import settings
        from app.models.agent_finding import AgentFinding
        from app.models.deal import Deal
        from packages.agents.analysis_progress import publish_progress
        from packages.agents.document_coverage import collect_documents_payloads
        from packages.agents.stage_failures import record_unanalysed_documents, split_outcomes
        from packages.agents.stage_tx import release_connection_before_llm

        if db.query(Deal).filter(Deal.id == deal_id).first() is None:
            raise ValueError(f"Deal {deal_id} not found")

        run = stage_support.open_run(db, deal_id, self.AGENT_NAME)
        try:
            documents = stage_support.select_documents(
                db, deal_id,
                document_ids=document_ids,
                routed_document_ids=stage_support.routed_ids(classifications, self.ROUTED_TYPES),
                keywords=self.DOC_KEYWORDS,
            )
            work = [(doc.id, doc.filename, doc.raw_text) for doc in documents if (doc.raw_text or "").strip()]
            filenames = {doc_id: filename for doc_id, filename, _ in work}
            logger.info("[%s] deal=%d — %d document(s) to review", self.AGENT_NAME, deal_id, len(work))

            run_id = run.id
            release_connection_before_llm(db)
            workers = max(1, min(2, settings.LLM_MAX_CONCURRENCY, settings.LLM_MAX_IN_FLIGHT))
            outcomes = collect_documents_payloads(
                [(doc_id, text) for doc_id, _, text in work],
                lambda doc_id, batch: self._payloads(doc_id, filenames[doc_id], batch),
                max_chars=self.BATCH_CHARS,
                max_workers=workers,
                progress_context=self.AGENT_NAME,
                on_progress=lambda done, total, doc_id: publish_progress(
                    deal_id, run_id, done, total, doc_id, agent_name=self.AGENT_NAME,
                ),
                isolate_failures=True,
            )
            analysed, failed = split_outcomes(work, outcomes)

            kept_ids = [doc_id for (doc_id, _, _), _ in failed]
            db.query(AgentFinding).filter(
                AgentFinding.deal_id == deal_id,
                AgentFinding.agent_name == self.AGENT_NAME,
                or_(AgentFinding.document_id.is_(None), AgentFinding.document_id.notin_(kept_ids)),
            ).delete(synchronize_session=False)
            db.flush()

            findings = []
            heuristic_count = 0
            by_document = []
            for (doc_id, filename, text), payloads in analysed:
                floor = self.floor_payloads(text, payloads)
                heuristic_count += len(floor)
                rows = self._persist(db, deal_id, doc_id, filename, payloads + floor)
                findings.extend(rows)
                by_document.append({"document_id": doc_id, "filename": filename, "finding_count": len(rows)})

            by_severity = {"low": 0, "medium": 0, "high": 0}
            by_type: dict[str, int] = {}
            for finding in findings:
                by_severity[finding.severity.value] += 1
                by_type[finding.category] = by_type.get(finding.category, 0) + 1
            result = {
                "deal_id": deal_id,
                "documents_analyzed": len(analysed),
                "agent_findings_count": len(findings),
                "heuristic_findings_count": heuristic_count,
                "findings_by_severity": by_severity,
                "findings_by_finding_type": by_type,
                "findings_by_document": by_document,
                "failed_documents": record_unanalysed_documents(
                    db, deal_id, self.AGENT_NAME,
                    [(doc_id, filename, failure.error) for (doc_id, filename, _), failure in failed],
                ),
            }
            stage_support.complete_run(db, run, result)
            return result
        except Exception as exc:
            stage_support.fail_run(db, run, exc)
            raise

    # ── Model output ────────────────────────────────────────────────────

    def _payloads(self, document_id: int, filename: str, text: str) -> list[dict]:
        """LLM + validation for one batch. Pure: safe on a worker thread."""
        items = _complete_llm_items(
            self._llm,
            self.PROMPT.format(filename=filename, text=text),
            max_tokens=self.MAX_TOKENS,
            context=f"{self.AGENT_NAME}, document {document_id}",
        )
        payloads = []
        for item in items:
            payload = self.normalize(item, text)
            if payload is not None:
                payloads.append(payload)
        return payloads

    def normalize(self, item: dict, text: str) -> dict | None:
        from packages.agents.evidence import grounded_amount

        if not isinstance(item, dict):
            return None
        finding_type = str(item.get("finding_type") or "").strip().lower()
        if finding_type not in self.VALID_FINDING_TYPES:
            finding_type = self.FALLBACK_TYPE
        amount, amount_source, amount_evidence = grounded_amount(item, text)
        parties = item.get("parties")
        parties = [" ".join(str(p).split())[:200] for p in parties if p][:10] if isinstance(parties, list) else []
        confidence = item.get("confidence")
        payload = {
            "finding_type": finding_type,
            "title": " ".join(str(item.get("title", "")).split())[:100],
            "description": " ".join(str(item.get("description", "")).split())[:400],
            "severity": _normalize_severity(str(item.get("severity", "")).lower()),
            "event_date": _short(item.get("event_date"), 60),
            "parties": parties,
            "registry_reference": _short(item.get("registry_reference"), 120),
            "amount_eur": amount,
            "amount_source": amount_source,
            "amount_evidence": amount_evidence,
            "confidence": confidence if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None,
            "source": "llm",
        }
        if not payload["title"] and not payload["description"]:
            return None
        return self.enrich(payload)

    def enrich(self, payload: dict) -> dict:
        """Deterministic additions computed from the payload. Default: none."""
        return payload

    # ── Keyword floor ───────────────────────────────────────────────────

    def floor_payloads(self, text: str, payloads: list[dict]) -> list[dict]:
        strongest: dict[str, int] = {}
        for payload in payloads:
            rank = _SEVERITY_ORDER.get(payload["severity"], 0)
            strongest[payload["finding_type"]] = max(rank, strongest.get(payload["finding_type"], -1))

        floor: list[dict] = []
        seen: set[str] = set()
        ordered = sorted(self.HEURISTICS, key=lambda h: _SEVERITY_ORDER[h.severity], reverse=True)
        for heuristic in ordered:
            if heuristic.finding_type in seen:
                continue
            if strongest.get(heuristic.finding_type, -1) >= _SEVERITY_ORDER[heuristic.severity]:
                continue
            if not stage_support.mentions_any(text, (heuristic.keyword,)):
                continue
            description = (
                f'The document mentions "{heuristic.keyword}". The matter was not '
                "extracted by the analysis and must be verified against the document."
            )
            if heuristic.note:
                description = f"{description} {heuristic.note}"
            floor.append(self.enrich({
                "finding_type": heuristic.finding_type,
                "title": heuristic.title,
                "description": description[:400],
                "severity": heuristic.severity,
                "event_date": None,
                "parties": [],
                "registry_reference": None,
                "amount_eur": None,
                "amount_source": "not_stated",
                "amount_evidence": None,
                "confidence": _HEURISTIC_CONFIDENCE,
                "source": "heuristic",
            }))
            seen.add(heuristic.finding_type)
        return floor

    # ── Persistence ─────────────────────────────────────────────────────

    def _persist(self, db: Session, deal_id: int, doc_id: int, filename: str, payloads: list[dict]) -> list:
        from app.models.agent_finding import AgentFinding
        from app.models.red_flag import Severity

        rows = []
        for payload in payloads:
            structured = {k: v for k, v in payload.items()
                          if k not in {"title", "description", "severity", "confidence"}}
            structured.update({"document_id": doc_id, "filename": filename})
            row = AgentFinding(
                deal_id=deal_id,
                document_id=doc_id,
                agent_name=self.AGENT_NAME,
                category=payload["finding_type"],
                title=payload["title"] or payload["finding_type"],
                description=payload["description"],
                severity=Severity(payload["severity"]),
                confidence=payload["confidence"],
                structured_payload_json=structured,
            )
            db.add(row)
            rows.append(row)
        db.flush()
        return rows


def _short(value, limit: int) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = " ".join(str(value).split())
    return text[:limit] or None
