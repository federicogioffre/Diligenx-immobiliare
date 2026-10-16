"""Deterministic test provider for the real-estate prompts. No network.

Extends Diligenx's ``FakeLLMProvider``: the real-estate prompts are answered
from the document text itself (regular expressions over the fixture's
"Foglio 12 particella 345 sub. 5" lines), so a test controls the outcome
through its fixture documents; every other prompt — the source-fidelity
review, the executive summary — falls through to the parent.
"""
from __future__ import annotations

import json
import re

from packages.agents.deal_analysis_agent import FakeLLMProvider

_CATEGORY_AREA = {
    "donation_in_chain": "title_chain", "opposition_deed": "title_chain",
    "inheritance_not_accepted": "title_chain", "succession_missing": "title_chain",
    "marital_regime": "title_chain", "family_fund": "title_chain", "chain_gap_20y": "title_chain",
    "power_of_attorney": "title_chain", "other_title": "title_chain",
    "mortgage": "encumbrances", "foreclosure": "encumbrances", "seizure": "encumbrances",
    "judicial_claim": "encumbrances", "easement": "encumbrances", "fondo_patrimoniale": "encumbrances",
    "transcribed_preliminary": "encumbrances", "tax_lien": "encumbrances", "other_encumbrance": "encumbrances",
    "cadastral_nonconformity": "cadastral", "cadastral_identifier_mismatch": "cadastral",
    "cadastral_owner_mismatch": "cadastral", "seller_owner_mismatch": "title_chain",
    "cadastral_category_mismatch": "cadastral", "surface_mismatch": "cadastral",
    "building_irregularity": "building_compliance", "pending_amnesty": "building_compliance",
    "missing_habitability": "building_compliance", "superbonus_works": "building_compliance",
    "pre_1967_declaration": "building_compliance", "urban_planning_constraint": "building_compliance",
    "other_building": "building_compliance",
    "arrears": "condominium", "approved_extraordinary_works": "condominium",
    "use_restriction": "condominium", "pending_condo_litigation": "condominium",
    "other_condominium": "condominium",
    "lease_in_place": "occupancy", "occupied_without_title": "occupancy",
}

_REMEDY = {
    "mortgage": "seller_undertaking", "foreclosure": "condition_precedent",
    "donation_in_chain": "warranty", "cadastral_identifier_mismatch": "pre_closing_verification",
    "cadastral_owner_mismatch": "pre_closing_verification", "arrears": "escrow",
    "approved_extraordinary_works": "price_adjustment",
}

_DATE = r"(\d{1,2}[/.]\d{1,2}[/.]\d{4}|\d{4}-\d{2}-\d{2})"


def _document(prompt: str) -> tuple[str, str]:
    filename = re.search(r"^(?:Document|File name): (.+)$", prompt, re.MULTILINE)
    text = prompt.split("Document text", 1)[-1]
    return (filename.group(1).strip() if filename else ""), text


def _classify(filename: str, text: str) -> str:
    needle = (filename + " " + text[:1500]).lower()
    for keyword, kind in (
        ("visura", "visura_catastale"), ("planimetria", "planimetria"),
        ("ispezione", "ispezione_ipotecaria"), ("verbale", "verbale_assemblea"),
        ("preliminare", "preliminare"), ("perizia", "perizia"), ("successione", "successione"),
        ("prestazione energetica", "ape"), ("permesso di costruire", "titolo_edilizio"),
        ("atto di compravendita", "atto_provenienza"), ("atto di donazione", "atto_provenienza"),
        ("atto", "atto_provenienza"),
    ):
        if keyword in needle:
            return kind
    return "other"


def _holders(text: str) -> list[dict]:
    match = re.search(r"(?:INTESTATI|ACQUIRENTI|VENDITORI)\s*:\s*(.+)", text)
    if not match:
        return []
    holders = []
    for part in re.split(r";", match.group(1)):
        name = part.strip().strip(".")
        if name:
            cf = re.search(r"\(([A-Z0-9]{16})\)", name)
            holders.append({"name": re.sub(r"\s*\([A-Z0-9]{16}\)", "", name),
                            "tax_code": cf.group(1) if cf else None, "share": None, "right": "proprietà"})
    return holders


def _units(text: str) -> list[dict]:
    units = []
    for match in re.finditer(
        r"[Ff]oglio\s+(\d+)\s*,?\s*(?:particella|mappale)\s+(\d+)(?:\s*,?\s*sub(?:alterno|\.)?\s*(\d+))?", text,
    ):
        tail = text[match.end():match.end() + 300]
        category = re.search(r"categoria\s+([A-F]/\d+)", tail, re.IGNORECASE)
        surface = re.search(r"superficie[^0-9]{0,30}(\d+(?:,\d+)?)\s*(?:mq|m²)", tail, re.IGNORECASE)
        date = re.search(r"(?:in data|del)\s+" + _DATE, text)
        units.append({
            "unit_label": "Abitazione", "comune": None, "sezione": None,
            "foglio": match.group(1), "particella": match.group(2), "subalterno": match.group(3),
            "categoria": category.group(1) if category else None, "classe": None, "consistenza": None,
            "superficie": f"{surface.group(1)} mq" if surface else None, "rendita": None,
            "indirizzo": None, "piano": None, "intestatari": _holders(text),
            "titolo": None, "data_titolo": date.group(1) if date else None, "confidence": 0.9,
        })
    return units


def _review(marker: str, text: str) -> list[dict]:
    found = []

    def add(finding_type, title, severity, keyword):
        index = text.lower().find(keyword)
        if index < 0:
            return
        window = text[max(0, index - 200):index + 300]
        date = re.search(_DATE, window)
        found.append({
            "finding_type": finding_type, "title": title,
            "description": " ".join(window.split())[:300], "event_date": date.group(1) if date else None,
            "parties": [], "registry_reference": None, "amount_eur": None, "amount_evidence": None,
            "severity": severity, "confidence": 0.85,
        })

    if marker == "REVIEW TITLE CHAIN":
        add("donation_in_chain", "Donazione nella provenienza", "medium", "atto di donazione")
    elif marker == "REVIEW ENCUMBRANCES":
        add("mortgage", "Ipoteca volontaria iscritta", "medium", "ipoteca volontaria")
    elif marker == "REVIEW BUILDING AND CADASTRAL COMPLIANCE":
        add("missing_habitability", "Agibilità non rilasciata", "medium", "agibilità non")
    elif marker == "REVIEW CONDOMINIUM AND OCCUPANCY":
        add("approved_extraordinary_works", "Lavori straordinari deliberati", "medium", "lavori straordinari")
    return found


def _aggregate(prompt: str) -> list[dict]:
    flags = []
    current_doc = None
    italian = "OUTPUT LANGUAGE: WRITE ALL FREE-TEXT OUTPUT IN ITALIAN." in prompt.upper()
    for line in prompt.splitlines():
        header = re.match(r"=== Document (\d+):", line)
        if header:
            current_doc = int(header.group(1))
            continue
        match = re.match(r"\s+\[([a-z0-9_]+)\] (.+?): (.*)  \(agent: (\w+), severity: (\w+)\)", line)
        if not match:
            continue
        category, title, issue, _, severity = match.groups()
        flags.append({
            "finding_type": "red_flag" if severity in ("high", "medium") else "observation",
            # The grounding review checks the output language; a keyword-floor
            # description is English, so the Italian stub states the title.
            "title": title, "issue": (f"{title}, come risulta dal documento." if italian else issue[:300]),
            "risk": "Rischio per l'acquirente." if italian else "Risk for the buyer.",
            "recommendation": ("Verificare prima del rogito." if italian else "Verify before the deed."),
            "remedy_type": _REMEDY.get(category), "impact": "deed" if severity == "high" else "value",
            "amount_eur": None, "amount_evidence": None, "severity": severity,
            "area": _CATEGORY_AREA.get(category, "other"), "category": category,
            "confidence": 0.85, "source_document_id": current_doc, "source_page": None,
        })
    return flags


class FakeRealEstateLLMProvider(FakeLLMProvider):
    def complete(self, prompt: str, max_tokens: int = 3072) -> str:
        if "GROUNDING REVIEW\n" in prompt:
            return super().complete(prompt, max_tokens)
        upper = prompt.upper()
        if "EXECUTIVE SUMMARY" in upper:
            if "OUTPUT LANGUAGE: WRITE ALL FREE-TEXT OUTPUT IN ITALIAN." in upper:
                return ("La revisione riguarda i documenti disponibili per l'acquisto. I rilievi e "
                        "le relative condizioni sono riportati nelle sezioni successive.")
            return ("The review covered the documents made available for the purchase. The findings "
                    "and their conditions are set out in the sections below.")
        if "TRIAGE RED FLAGS" in upper and "REAL-ESTATE" in upper:
            if "No findings available." in prompt:
                return "[]"
            return json.dumps(_aggregate(prompt))
        if "CLASSIFY" in upper and "RESIDENTIAL PROPERTY" in upper:
            filename, text = _document(prompt)
            return json.dumps({"document_type": _classify(filename, text), "confidence": 0.9,
                               "rationale": "Deterministic test classification."})
        if "EXTRACT PROPERTY IDENTIFICATION" in upper:
            return json.dumps(_units(_document(prompt)[1]))
        for marker in ("REVIEW TITLE CHAIN", "REVIEW ENCUMBRANCES",
                       "REVIEW BUILDING AND CADASTRAL COMPLIANCE", "REVIEW CONDOMINIUM AND OCCUPANCY"):
            if marker in upper:
                return json.dumps(_review(marker, _document(prompt)[1]))
        return super().complete(prompt, max_tokens)
