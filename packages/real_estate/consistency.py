"""Deterministic cross-document checks on the property's identification.

No model call. The stage reads the ``PropertyProfile`` rows the identity
stage extracted and compares what the documents state about the same unit:

* **identifiers** — a unit the deed or the floor plan identifies (foglio,
  particella, subalterno) that the cadastral extract does not list, or lists
  under another subalterno;
* **owners** — the owners of record in the cadastral extract against the
  acquirers in the deed, and against the sellers in a preliminary contract
  or a valuation (art. 29, comma 1-bis, L. 52/1985 requires the notary to
  reconcile them);
* **category** — two authoritative sources stating a different cadastral
  category for the same unit;
* **surface** — a difference above ``SURFACE_TOLERANCE`` between the
  surfaces two authoritative sources state;
* **chain** — whether the titles on file reach back twenty years.

Each discrepancy is an ``AgentFinding`` (``agent_name = consistency_check``)
that names both documents and quotes both values, and flows into the
red-flag aggregation like any specialist's finding. The check never decides
which document is right: that is the notary's and the surveyor's job.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from sqlalchemy.orm import Session

from packages.real_estate import stage_support
from packages.real_estate import rules_registry as rr
from packages.real_estate.property_identity import holder_names, normalize_value, unit_key

logger = logging.getLogger(__name__)

AGENT_NAME = "consistency_check"
SURFACE_TOLERANCE = 0.10

_DEED_KINDS = ("atto_provenienza",)
_TITLE_KINDS = ("atto_provenienza", "successione")
_SELLER_KINDS = ("preliminare", "perizia")
_COMPARED_TO_CADASTRE = ("atto_provenienza", "planimetria")
_AUTHORITATIVE = ("atto_provenienza", "visura_catastale", "planimetria", "successione")


def _ident(profile) -> str:
    bits = [f"{label} {getattr(profile, attr)}"
            for attr, label in (("foglio", "foglio"), ("particella", "particella"), ("subalterno", "sub."))
            if getattr(profile, attr, None)]
    return ", ".join(bits)


def _doc(profile) -> str:
    doc = getattr(profile, "source_document", None)
    return getattr(doc, "filename", None) or f"documento {profile.source_document_id}"


_THOUSANDS = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?")
_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")


def _first_number(value: str | None) -> float | None:
    """First figure in Italian or English notation: "1.234,5 mq" → 1234.5."""
    match = _NUMBER.search(value or "")
    if match is None:
        return None
    token = match.group()
    if _THOUSANDS.fullmatch(token):
        token = token.replace(".", "")
    return float(token.replace(",", "."))


def _finding(category: str, title: str, description: str, severity: str, profiles: list, **extra) -> dict:
    documents = []
    for profile in profiles:
        if profile.source_document_id is not None and profile.source_document_id not in [d["document_id"] for d in documents]:
            documents.append({"document_id": profile.source_document_id, "filename": _doc(profile),
                              "source_kind": profile.source_kind})
    return {
        "category": category,
        "title": title[:100],
        "description": description[:400],
        "severity": severity,
        "document_id": documents[0]["document_id"] if documents else None,
        "payload": {"finding_type": category, "source": "deterministic",
                    "compared_documents": documents, **extra},
    }


def compare_profiles(profiles: list, as_of: date | None = None) -> list[dict]:
    """Every discrepancy among *profiles*, as finding dicts. Pure function."""
    findings: list[dict] = []
    by_kind: dict[str, list] = {}
    for profile in profiles:
        by_kind.setdefault(profile.source_kind or "other", []).append(profile)

    cadastre = [p for p in by_kind.get("visura_catastale", []) if unit_key(p)]
    cadastre_keys = {unit_key(p): p for p in cadastre}

    # ── Identifiers ─────────────────────────────────────────────────────
    if cadastre:
        reported: set[tuple] = set()
        for kind in _COMPARED_TO_CADASTRE:
            for profile in by_kind.get(kind, []):
                key = unit_key(profile)
                if key is None or key in cadastre_keys or (kind, key) in reported:
                    continue
                reported.add((kind, key))
                same_parcel = [p for k, p in cadastre_keys.items() if k[:2] == key[:2]]
                if same_parcel:
                    others = "; ".join(_ident(p) for p in same_parcel)
                    findings.append(_finding(
                        "cadastral_identifier_mismatch",
                        "Subalterno diverso tra i documenti",
                        f"{_doc(profile)} identifica l'unità come {_ident(profile)}; "
                        f"la visura catastale ({_doc(same_parcel[0])}) riporta {others}.",
                        "high", [profile, *same_parcel],
                        values={kind: _ident(profile), "visura_catastale": others},
                    ))
                else:
                    findings.append(_finding(
                        "cadastral_identifier_mismatch",
                        "Unità non presente nella visura catastale",
                        f"{_doc(profile)} identifica un'unità come {_ident(profile)}, che non compare "
                        f"nella visura catastale agli atti ({_doc(cadastre[0])}).",
                        "medium", [profile, cadastre[0]],
                        values={kind: _ident(profile)},
                    ))

    # ── Owners ──────────────────────────────────────────────────────────
    def compare_holders(kind_list, category, title, role):
        for kind in kind_list:
            for profile in by_kind.get(kind, []):
                key = unit_key(profile)
                record = cadastre_keys.get(key) if key else (cadastre[0] if len(cadastre_keys) == 1 else None)
                if record is None:
                    continue
                stated, of_record = holder_names(profile.intestatari), holder_names(record.intestatari)
                if not stated or not of_record or stated == of_record:
                    continue
                overlap = stated & of_record
                names = lambda p: "; ".join(h.get("name", "") for h in (p.intestatari or []) if isinstance(h, dict))
                findings.append(_finding(
                    category, title,
                    f"{_doc(profile)} indica come {role}: {names(profile)}; la visura catastale "
                    f"({_doc(record)}) indica come intestatari: {names(record)}.",
                    "medium" if overlap else "high", [profile, record],
                    values={kind: names(profile), "visura_catastale": names(record)},
                ))

    compare_holders(_DEED_KINDS, "cadastral_owner_mismatch",
                    "Intestatari catastali diversi dagli acquirenti dell'atto", "acquirenti")
    compare_holders(_SELLER_KINDS, "seller_owner_mismatch",
                    "Venditori diversi dagli intestatari catastali", "proprietari o venditori")

    # ── Category and surface, unit by unit ──────────────────────────────
    units: dict[tuple, list] = {}
    for profile in profiles:
        key = unit_key(profile)
        if key is not None and (profile.source_kind or "") in _AUTHORITATIVE:
            units.setdefault(key, []).append(profile)
    for key, rows in units.items():
        categories = {}
        for row in rows:
            if row.categoria:
                categories.setdefault(normalize_value(row.categoria), row)
        if len(categories) > 1:
            listed = "; ".join(f"{_doc(r)}: categoria {r.categoria}" for r in categories.values())
            findings.append(_finding(
                "cadastral_category_mismatch", "Categoria catastale diversa tra i documenti",
                f"Per l'unità {_ident(rows[0])} i documenti riportano categorie diverse ({listed}).",
                "medium", list(categories.values()),
            ))
        surfaces = [(r, _first_number(r.superficie)) for r in rows if _first_number(r.superficie)]
        if len(surfaces) > 1:
            low = min(surfaces, key=lambda item: item[1])
            high = max(surfaces, key=lambda item: item[1])
            if high[1] > 0 and (high[1] - low[1]) / high[1] > SURFACE_TOLERANCE:
                findings.append(_finding(
                    "surface_mismatch", "Superficie diversa tra i documenti",
                    f"Per l'unità {_ident(rows[0])}: {_doc(low[0])} indica {low[0].superficie}, "
                    f"{_doc(high[0])} indica {high[0].superficie}.",
                    "low", [low[0], high[0]],
                ))

    # ── Twenty-year chain ───────────────────────────────────────────────
    titles = [(p, rr.parse_date(p.data_titolo)) for kind in _TITLE_KINDS for p in by_kind.get(kind, [])]
    dated = [(p, d) for p, d in titles if d is not None]
    if dated:
        coverage = rr.chain_coverage([d for _, d in dated], as_of)
        if not coverage.covered:
            earliest = min(dated, key=lambda item: item[1])
            findings.append(_finding(
                "chain_gap_20y", "Provenienza ventennale non documentata",
                f"Il titolo più risalente agli atti ({_doc(earliest[0])}) è del {earliest[0].data_titolo}; "
                f"la provenienza ventennale richiede titoli anteriori al "
                f"{rr.format_date(coverage.required_from, 'it')}.",
                "medium", [earliest[0]],
                earliest_title=coverage.earliest_title.isoformat(),
                required_from=coverage.required_from.isoformat(),
            ))
    return findings


def chain_coverage_for(profiles: list, as_of: date | None = None):
    """Twenty-year coverage of the titles on file, or None when no title is dated."""
    dates = [rr.parse_date(p.data_titolo) for p in profiles if (p.source_kind or "") in _TITLE_KINDS]
    dates = [d for d in dates if d is not None]
    return rr.chain_coverage(dates, as_of) if dates else None


class ConsistencyCheckAgent:
    AGENT_NAME = AGENT_NAME

    def run(self, deal_id: int, db: Session) -> dict:
        from sqlalchemy.orm import joinedload

        from app.models.agent_finding import AgentFinding
        from app.models.property_profile import PropertyProfile
        from app.models.red_flag import Severity

        run = stage_support.open_run(db, deal_id, self.AGENT_NAME)
        try:
            profiles = (
                db.query(PropertyProfile)
                .options(joinedload(PropertyProfile.source_document))
                .filter(PropertyProfile.deal_id == deal_id)
                .order_by(PropertyProfile.id)
                .all()
            )
            findings = compare_profiles(profiles)
            db.query(AgentFinding).filter(
                AgentFinding.deal_id == deal_id, AgentFinding.agent_name == self.AGENT_NAME,
            ).delete(synchronize_session=False)
            for item in findings:
                db.add(AgentFinding(
                    deal_id=deal_id,
                    document_id=item["document_id"],
                    agent_name=self.AGENT_NAME,
                    category=item["category"],
                    title=item["title"],
                    description=item["description"],
                    severity=Severity(item["severity"]),
                    confidence=0.9,
                    structured_payload_json=item["payload"],
                ))
            db.flush()
            result = {
                "deal_id": deal_id,
                "profiles_compared": len(profiles),
                "units_identified": len({unit_key(p) for p in profiles if unit_key(p)}),
                "findings_count": len(findings),
                "findings_by_category": {
                    category: sum(1 for f in findings if f["category"] == category)
                    for category in sorted({f["category"] for f in findings})
                },
            }
            stage_support.complete_run(db, run, result)
            return result
        except Exception as exc:
            stage_support.fail_run(db, run, exc)
            raise

