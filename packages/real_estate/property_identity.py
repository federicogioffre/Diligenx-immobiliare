"""Consolidate what the documents state about each property unit.

The property-identity stage stores one ``PropertyProfile`` row per unit per
source document. This module groups the rows into units and states **one
value per field**, taken from the most authoritative source that carries it
— the same approach as Diligenx's ``company_identity`` for the target
company. Every distinct value survives in ``field_sources``; a field is
named in ``conflicting_fields`` only when two *authoritative* sources (deed,
cadastral extract, floor plan, succession) disagree, because a valuation's
commercial surface or a preliminary contract's description of the flat is
not a discrepancy a notary would act on.

Units are keyed by the cadastral identifiers (foglio, particella,
subalterno). A row without foglio and particella cannot be placed and forms
a unit of its own: merging it by a label such as "cantina" could attach it
to the wrong building.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: Lower rank = more authoritative.
SOURCE_RANK: dict[str, int] = {
    "atto_provenienza": 0,
    "visura_catastale": 1,
    "planimetria": 2,
    "successione": 3,
    "ispezione_ipotecaria": 4,
    "preliminare": 5,
    "perizia": 6,
    "titolo_edilizio": 7,
}
_DEFAULT_RANK = 9

#: Sources whose disagreement is a discrepancy, not a difference of purpose.
AUTHORITATIVE_KINDS = frozenset({"atto_provenienza", "visura_catastale", "planimetria", "successione"})

#: Fields shown in the identification table, in order.
FIELDS: tuple[str, ...] = (
    "unit_label", "indirizzo", "piano", "comune", "sezione", "foglio", "particella",
    "subalterno", "categoria", "classe", "consistenza", "superficie", "rendita",
    "titolo", "data_titolo",
)

#: Fields compared for conflicts. The title and its date legitimately differ
#: between documents (each deed records its own), so they are not compared.
COMPARED_FIELDS: tuple[str, ...] = (
    "comune", "sezione", "foglio", "particella", "subalterno", "categoria",
    "classe", "consistenza", "superficie", "rendita", "indirizzo",
)


def normalize_value(value: object) -> str:
    """Comparison form: no accents, case, punctuation, spaces or leading zeros."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = re.sub(r"[^a-z0-9/]", "", text)
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", text)


def normalize_identifier(value: object) -> str:
    """Cadastral identifier as a key: digits and letters only, no leading zeros."""
    text = normalize_value(value).replace("/", "")
    return text


def normalize_name(value: object) -> str:
    """A holder's name, order-insensitive ("Rossi Mario" == "Mario Rossi")."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    tokens = re.findall(r"[a-z]+", text)
    return " ".join(sorted(tokens))


def holder_keys(intestatari: object) -> set[str]:
    """Identity of each holder: the tax code when stated, else the name."""
    keys: set[str] = set()
    if not isinstance(intestatari, list):
        return keys
    for holder in intestatari:
        if not isinstance(holder, dict):
            continue
        tax_code = re.sub(r"[^A-Z0-9]", "", str(holder.get("tax_code") or "").upper())
        if len(tax_code) == 16:
            keys.add("cf:" + tax_code)
            continue
        name = normalize_name(holder.get("name"))
        if name:
            keys.add("name:" + name)
    return keys


def holder_names(intestatari: object) -> set[str]:
    if not isinstance(intestatari, list):
        return set()
    return {normalize_name(h.get("name")) for h in intestatari
            if isinstance(h, dict) and normalize_name(h.get("name"))}


def unit_key(profile) -> tuple[str, str, str] | None:
    foglio = normalize_identifier(getattr(profile, "foglio", None))
    particella = normalize_identifier(getattr(profile, "particella", None))
    if not foglio or not particella:
        return None
    return foglio, particella, normalize_identifier(getattr(profile, "subalterno", None))


def format_holders(intestatari: object) -> str:
    """Holders as one line each: "Mario Rossi (RSSMRA…) proprietà 1/2"."""
    if not isinstance(intestatari, list):
        return ""
    lines = []
    for holder in intestatari:
        if not isinstance(holder, dict) or not holder.get("name"):
            continue
        bits = [str(holder["name"]).strip()]
        if holder.get("tax_code"):
            bits.append(f"({str(holder['tax_code']).strip()})")
        right = " ".join(str(holder.get(k)).strip() for k in ("right", "share") if holder.get(k))
        if right:
            bits.append(right)
        lines.append(" ".join(bits))
    return "\n".join(lines)


@dataclass
class FieldSource:
    value: str
    source_document_ids: list[int] = field(default_factory=list)
    source_filenames: list[str] = field(default_factory=list)
    source_kinds: list[str] = field(default_factory=list)


@dataclass
class PropertyUnit:
    key: tuple[str, str, str] | None
    values: dict[str, str] = field(default_factory=dict)
    intestatari: list = field(default_factory=list)
    field_sources: dict[str, list[FieldSource]] = field(default_factory=dict)
    conflicting_fields: list[str] = field(default_factory=list)
    source_document_ids: list[int] = field(default_factory=list)
    source_filenames: list[str] = field(default_factory=list)
    profile_ids: list[int] = field(default_factory=list)
    profiles: list = field(default_factory=list)

    @property
    def label(self) -> str:
        bits = []
        if self.values.get("unit_label"):
            bits.append(self.values["unit_label"])
        ident = ", ".join(
            f"{name} {self.values[attr]}"
            for attr, name in (("foglio", "fg."), ("particella", "part."), ("subalterno", "sub."))
            if self.values.get(attr)
        )
        if ident:
            bits.append(ident)
        return " · ".join(bits) or "Unità non identificata"


def _rank(profile) -> tuple[int, int, int]:
    """Most authoritative first; within a rank, the most recent title first."""
    from packages.real_estate.rules_registry import parse_date

    kind_rank = SOURCE_RANK.get(getattr(profile, "source_kind", None) or "", _DEFAULT_RANK)
    day = parse_date(getattr(profile, "data_titolo", None))
    recency = -day.toordinal() if day else 0
    return kind_rank, recency, getattr(profile, "id", 0) or 0


def _filename(profile) -> str | None:
    doc = getattr(profile, "source_document", None)
    return getattr(doc, "filename", None)


def consolidate_property_profiles(profiles: list) -> list[PropertyUnit]:
    """Group the rows into units and pick one value per field."""
    groups: dict[object, list] = {}
    order: list[object] = []
    for profile in profiles:
        key = unit_key(profile)
        group_key = key if key is not None else ("row", getattr(profile, "id", id(profile)))
        if group_key not in groups:
            groups[group_key] = []
            order.append(group_key)
        groups[group_key].append(profile)

    units: list[PropertyUnit] = []
    for group_key in order:
        rows = sorted(groups[group_key], key=_rank)
        unit = PropertyUnit(key=group_key if group_key and group_key[0] != "row" else None, profiles=rows)
        for profile in rows:
            doc_id = getattr(profile, "source_document_id", None)
            filename = _filename(profile)
            if doc_id is not None and doc_id not in unit.source_document_ids:
                unit.source_document_ids.append(doc_id)
                if filename:
                    unit.source_filenames.append(filename)
            if getattr(profile, "id", None) is not None:
                unit.profile_ids.append(profile.id)
            for attr in FIELDS:
                raw = getattr(profile, attr, None)
                if raw is None or not str(raw).strip():
                    continue
                value = str(raw).strip()
                unit.values.setdefault(attr, value)
                sources = unit.field_sources.setdefault(attr, [])
                match = next((s for s in sources if normalize_value(s.value) == normalize_value(value)), None)
                if match is None:
                    match = FieldSource(value)
                    sources.append(match)
                if doc_id is not None and doc_id not in match.source_document_ids:
                    match.source_document_ids.append(doc_id)
                    if filename:
                        match.source_filenames.append(filename)
                kind = getattr(profile, "source_kind", None)
                if kind and kind not in match.source_kinds:
                    match.source_kinds.append(kind)
            if not unit.intestatari and getattr(profile, "intestatari", None):
                unit.intestatari = list(profile.intestatari)

        for attr in COMPARED_FIELDS:
            authoritative = {
                normalize_value(s.value) for s in unit.field_sources.get(attr, [])
                if AUTHORITATIVE_KINDS.intersection(s.source_kinds)
            }
            if len(authoritative) > 1:
                unit.conflicting_fields.append(attr)
        units.append(unit)
    return units
