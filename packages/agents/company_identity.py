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


_PUNCTUATION = re.compile(r"[^\w\s]+", re.UNICODE)


def _value_key(value: str) -> str:
    """Group renderings of the same value, keeping different values apart.

    Accents, apostrophes, case and punctuation are formatting, and a data room
    disagrees with itself on all of them: `societa' a responsabilita' limitata`
    and `Società a responsabilità limitata` are one legal form, not two. Digits
    and words survive untouched, so 20812 and 20051 stay different addresses.
    """
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(_PUNCTUATION.sub(" ", folded).split())


#: How far a document can be trusted for the identity table, most authoritative
#: first. A due-diligence introduction states what the registry extract says and
#: footnotes the rest; a tax return is the last place to read a registered
#: office from. Unrecognised filenames fall to the last bucket.
_SOURCE_RANKS = (
    (re.compile(r"visur", re.I), 0),
    (re.compile(r"statut|atto\s*costitutiv|costituzion", re.I), 1),
    (re.compile(r"libro\s*soci|decision[ei]\s*soci|patto|quot", re.I), 2),
    (re.compile(r"verbal|consiglio|assemble|cda", re.I), 3),
    (re.compile(r"bilanc|(?<![a-z])bil[\s_-]*\d{2,4}|nota\s*integrativ", re.I), 4),
)
_UNRANKED_SOURCE = len(_SOURCE_RANKS) + 1
#: The last rank that is a corporate record (visura, statuto/atto costitutivo,
#: libro soci/patti, verbali). Only a corporate record can contradict the
#: identity table: a loan contract's "purpose of the financing", one fiscal
#: year per set of accounts or a tax return's heading are not a discrepancy in
#: the company's oggetto sociale or fiscal year, and listing them buried the
#: real alternatives under a page of repetitions.
_CORPORATE_RECORD_RANK = 3
_DATE_PATTERNS = (
    re.compile(r"(?P<y>(?:19|20)\d{2})[.\-_/ ](?P<m>\d{1,2})[.\-_/ ](?P<d>\d{1,2})"),
    re.compile(r"(?P<d>\d{1,2})[.\-_/ ](?P<m>\d{1,2})[.\-_/ ](?P<y>(?:19|20)\d{2})"),
)
_YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def _source_rank(filename: str | None) -> int:
    if not filename:
        return _UNRANKED_SOURCE
    for pattern, rank in _SOURCE_RANKS:
        if pattern.search(filename):
            return rank
    return _UNRANKED_SOURCE


def _source_date(filename: str | None) -> tuple[int, int, int]:
    """The document's own date as written in its name, or the zero date.

    Upload order says nothing about which corporate fact is current, and the
    profile carries no document date, so the filename is the only signal
    available without re-reading every document.
    """
    if not filename:
        return (0, 0, 0)
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(filename):
            year, month, day = (int(match.group(name)) for name in ("y", "m", "d"))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return (year, month, day)
    years = [int(value) for value in _YEAR_PATTERN.findall(filename)]
    return (max(years), 0, 0) if years else (0, 0, 0)


def _authority(profile) -> tuple:
    """Sort key: the most authoritative source first, then the most recent."""
    filename = _source_filename(profile)
    year, month, day = _source_date(filename)
    return (_source_rank(filename), -year, -month, -day)


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

    Each field carries a single value, taken from the most authoritative and
    most recent source that states it (see ``_authority``). Every distinct
    value survives in ``field_sources`` with its documents. A field whose
    corporate records disagree is named in ``conflicting_fields`` and its
    reportable alternatives are in ``conflict_sources``, so the report can
    state one figure and still show what else the corporate records say. Source rows
    are never mutated. Missing scope returns an empty list.
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
        conflict_sources = {}
        for field in PROFILE_FIELDS:
            alternatives = {}
            standing = {}
            for position, profile in enumerate(members):
                raw = getattr(profile, field, None)
                if raw is None or not str(raw).strip():
                    continue
                key_of_value = _value_key(str(raw))
                rank = (_authority(profile), position)
                evidence = alternatives.setdefault(key_of_value, {
                    "value": str(raw).strip(), "source_document_ids": [],
                    "source_filenames": [], "profile_ids": [],
                })
                # Renderings that differ only in accents, case or punctuation
                # are one value, so the group is shown as its best source
                # spells it: the registry extract, not whichever verbale
                # happened to be read first.
                if rank < standing.get(key_of_value, rank):
                    evidence["value"] = str(raw).strip()
                standing[key_of_value] = min(standing.get(key_of_value, rank), rank)
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
            # One value per field, from the most authoritative and most recent
            # source. Merging every rendering instead gave an introduction with
            # eight spellings of one legal form and twenty-five of one
            # registered office; the alternatives stay in field_sources and the
            # report lists them under the table for the fields that disagree.
            best = min(standing, key=standing.__getitem__, default=None)
            values[field] = alternatives[best]["value"] if best is not None else None
            if best is None:
                conflict_sources[field] = []
                continue
            # A disagreement is reported only between corporate records, or,
            # where none states the field, between sources as authoritative as
            # the one the table relies on. Everything else stays in
            # field_sources as evidence, without being listed in the report.
            ceiling = max(standing[best][0][0], _CORPORATE_RECORD_RANK)
            conflict_sources[field] = [evidence for value_key, evidence in alternatives.items()
                                       if standing[value_key][0][0] <= ceiling]
            if len(conflict_sources[field]) > 1:
                conflicting_fields.append(field)

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
                      conflicting_fields=conflicting_fields, field_sources=field_sources,
                      conflict_sources=conflict_sources)
        result.append(SimpleNamespace(**values))
    return result
