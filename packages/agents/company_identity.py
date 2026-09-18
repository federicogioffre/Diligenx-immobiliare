"""Pure, conservative company identity and report-view consolidation.

The saved per-document profiles remain the evidence. This module only builds
views for the confirmed scope; it never mutates a profile or loads a relation.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
import math
import re
from types import SimpleNamespace
import unicodedata


PROFILE_FIELDS = (
    "legal_form", "incorporation_date", "registered_office", "corporate_capital",
    "shareholders", "pledge", "managing_body", "auditors", "auditing_company",
    "business", "fiscal_year", "duration",
)
_LEGAL_FORMS = tuple(
    (re.compile(r"(?<!\w)" + r"[\s.]*".join(form) + r"\.?(?!\w)"), form)
    for form in ("srls", "sapa", "srl", "spa", "snc", "sas", "ss", "llc", "llp", "ltd")
)


def normalize_company_name(value: str | None) -> str:
    """Normalize formatting, retaining the legal form and all name tokens.

    No prefix/substring/fuzzy matching or removal of corporate suffixes:
    'Alfa Srl', 'Alfa Spa' and 'Alfa Servizi Srl' remain different entities.
    """
    if not isinstance(value, str):
        return ""
    name = unicodedata.normalize("NFC", value).casefold().strip()
    for pattern, replacement in _LEGAL_FORMS:
        name = pattern.sub(replacement, name)
    return " ".join(name.split())


def _value_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _profile_order(profile) -> tuple:
    identity = getattr(profile, "id", None)
    source_id = getattr(profile, "source_document_id", None)
    return (identity is None, identity or 0, source_id is None, source_id or 0,
            str(getattr(profile, "created_at", "") or ""),
            tuple(str(getattr(profile, field, "") or "") for field in PROFILE_FIELDS))


def _source_filename(profile) -> str | None:
    # ORM relationships must be eager-loaded by the caller; a detached profile
    # must remain safe to consolidate and must not trigger an N+1 query stream.
    attributes = getattr(profile, "__dict__", {})
    filename = attributes.get("source_filename")
    document = attributes.get("source_document")
    if not filename and document is not None:
        filename = getattr(document, "filename", None)
    return filename.strip() if isinstance(filename, str) and filename.strip() else None


def consolidate_company_profiles(
    profiles: Iterable,
    target_company_names: Sequence[str] | None,
) -> list[SimpleNamespace]:
    """Return one view per matching target, in confirmed-target order.

    Non-empty disagreements are retained in the field and named in
    ``conflicting_fields``. Source rows and their individual values are never
    replaced by this view. Missing scope returns an empty list.
    """
    if not target_company_names or isinstance(target_company_names, (str, bytes)):
        return []
    targets = {}
    for name in target_company_names:
        key = normalize_company_name(name)
        if key:
            targets.setdefault(key, name.strip())
    if not targets:
        return []

    grouped = {key: [] for key in targets}
    for profile in profiles:
        key = normalize_company_name(getattr(profile, "company_name", None))
        if key in grouped:
            grouped[key].append(profile)

    result = []
    for key, target_name in targets.items():
        members = sorted(grouped[key], key=_profile_order)
        if not members:
            continue
        representative = members[0]
        values = {attribute: getattr(representative, attribute, None)
                  for attribute in ("id", "deal_id", "created_at", "updated_at", "source_document_id")}
        values["company_name"] = target_name
        conflicting_fields = []
        field_sources = {}
        for field in PROFILE_FIELDS:
            alternatives = {}
            for profile in members:
                raw = getattr(profile, field, None)
                if raw is not None and str(raw).strip():
                    evidence = alternatives.setdefault(_value_key(str(raw)), {
                        "value": str(raw).strip(), "source_document_ids": [],
                        "source_filenames": [], "profile_ids": [],
                    })
                    source_id = getattr(profile, "source_document_id", None)
                    profile_id = getattr(profile, "id", None)
                    filename = _source_filename(profile)
                    for attribute, item in (("source_document_ids", source_id), ("profile_ids", profile_id)):
                        if isinstance(item, int) and not isinstance(item, bool) and item not in evidence[attribute]:
                            evidence[attribute].append(item)
                    if filename and filename not in evidence["source_filenames"]:
                        evidence["source_filenames"].append(filename)
            for evidence in alternatives.values():
                evidence["source_document_ids"].sort()
                evidence["profile_ids"].sort()
            field_sources[field] = list(alternatives.values())
            if len(alternatives) > 1:
                conflicting_fields.append(field)
            # Preserve every distinct line without multiplying repeated lines
            # in multi-line fields such as shareholders and managing bodies.
            lines = {}
            for alternative in alternatives.values():
                for line in alternative["value"].splitlines():
                    if line.strip():
                        lines.setdefault(_value_key(line), line.strip())
            values[field] = "\n".join(lines.values()) or None

        sources = {}
        for profile in members:
            source_id = getattr(profile, "source_document_id", None)
            if isinstance(source_id, int) and not isinstance(source_id, bool):
                sources.setdefault(source_id, _source_filename(profile))
                if not sources[source_id]:
                    sources[source_id] = _source_filename(profile)
        source_ids = sorted(sources)
        if values["source_document_id"] is None and source_ids:
            values["source_document_id"] = source_ids[0]
        filenames = list(dict.fromkeys(sources[source_id] for source_id in source_ids if sources[source_id]))
        confidences = [getattr(profile, "confidence", None) for profile in members]
        confidences = [value for value in confidences
                       if isinstance(value, (int, float)) and not isinstance(value, bool)
                       and math.isfinite(value) and 0 <= value <= 1]
        values.update(confidence=min(confidences) if confidences else None,
                      source_document_ids=source_ids, source_filenames=filenames,
                      conflicting_fields=conflicting_fields, field_sources=field_sources)
        result.append(SimpleNamespace(**values))
    return result
