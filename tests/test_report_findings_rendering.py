"""Tests for how a red flag's quantitative fields reach the report.

Covers:
- The amount and fiscal years a finding carries are rendered in the Key
  Findings row, in the conventions of the report's language
- The remedy tag is rendered at the end of the recommendation cell
- Rows without figures or without a tag render exactly as before
- The tax scope sentence names the assessable period computed from the
  rules registry rather than a fixed number of years
- The new legal-rules entries reach the aggregation context
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.models.red_flag import DueDiligenceArea, Severity
from packages.agents import tax_rules_registry
from packages.agents.legal_rules import build_legal_rules_context
from packages.agents.report_agent import (
    _format_amount,
    _format_figures,
    _render_introduction,
    _render_key_findings,
)


def _flag(**overrides) -> SimpleNamespace:
    base = dict(
        title="Notified tax assessment",
        issue="An avviso di accertamento was notified for FY2022.",
        risk="The target bears the assessed amount.",
        recommendation="Insert a specific indemnity in the SPA.",
        severity=Severity.high,
        area=DueDiligenceArea.tax,
        source_document_id=None,
        source_page=None,
        remedy_type=None,
        impact=None,
        structured_payload_json=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── Amounts and fiscal years ────────────────────────────────────────────────


class TestFigures:
    @pytest.mark.parametrize(
        "lang,expected",
        [("en", "EUR 240,000"), ("it", "Euro 240.000")],
    )
    def test_amount_follows_the_language_conventions(self, lang: str, expected: str):
        assert _format_amount(240000.0, lang) == expected

    def test_amount_and_years_together(self):
        flag = _flag(
            structured_payload_json={"amount_eur": 85000, "fiscal_years": [2021, 2022]}
        )
        assert _format_figures(flag, "en") == "(EUR 85,000 · FY 2021, 2022)"
        assert _format_figures(flag, "it") == "(Euro 85.000 · es. 2021, 2022)"

    def test_years_without_an_amount(self):
        """A finding the document did not price still carries its years."""
        flag = _flag(structured_payload_json={"fiscal_years": [2022]})
        assert _format_figures(flag, "en") == "(FY 2022)"

    def test_amount_without_years(self):
        flag = _flag(structured_payload_json={"amount_eur": 1000})
        assert _format_figures(flag, "en") == "(EUR 1,000)"

    @pytest.mark.parametrize(
        "payload", [None, {}, {"amount_eur": None}, {"fiscal_years": []}]
    )
    def test_nothing_to_render(self, payload):
        assert _format_figures(_flag(structured_payload_json=payload), "en") == ""

    def test_figures_appear_in_the_key_findings_row(self):
        flag = _flag(
            structured_payload_json={"amount_eur": 240000, "fiscal_years": [2022]}
        )
        markdown = _render_key_findings([flag], "en")
        assert "(EUR 240,000 · FY 2022)" in markdown

    def test_row_without_figures_is_unchanged(self):
        markdown = _render_key_findings([_flag()], "en")
        assert "EUR" not in markdown
        assert "FY " not in markdown


# ── Remedy tag ──────────────────────────────────────────────────────────────


class TestRemedyTag:
    @pytest.mark.parametrize(
        "remedy,en,it",
        [
            ("indemnity", "[Indemnity]", "[Indennizzo]"),
            ("condition_precedent", "[Condition precedent]", "[Condizione sospensiva]"),
            ("price_adjustment", "[Price adjustment]", "[Aggiustamento prezzo]"),
            ("information_request", "[Information request]", "[Richiesta di informazioni]"),
        ],
    )
    def test_tag_is_rendered_in_both_languages(self, remedy, en, it):
        flag = _flag(remedy_type=remedy)
        assert en in _render_key_findings([flag], "en")
        assert it in _render_key_findings([flag], "it")

    def test_untagged_flag_renders_no_bracket(self):
        markdown = _render_key_findings([_flag()], "en")
        assert "_[" not in markdown

    def test_unknown_tag_is_ignored_rather_than_printed(self):
        """A value outside the vocabulary must not leak into the report."""
        markdown = _render_key_findings([_flag(remedy_type="escrow")], "en")
        assert "escrow" not in markdown.lower()

    def test_tag_survives_a_missing_recommendation(self):
        flag = _flag(recommendation=None, remedy_type="warranty")
        assert "[Warranty]" in _render_key_findings([flag], "en")


# ── Scope sentence ──────────────────────────────────────────────────────────


class TestTaxScopeSentence:
    def test_period_is_computed_not_fixed(self):
        """The assessment period moved from four years to five in 2016."""
        expected_first = min(tax_rules_registry.open_fiscal_years())
        intro = _render_introduction("Project X", ["Tax"], "en")
        assert str(expected_first) in intro
        assert "still open to assessment" in intro

    def test_italian_sentence(self):
        intro = _render_introduction("Project X", ["Fiscale"], "it")
        assert "periodi d'imposta ancora accertabili" in intro

    @pytest.mark.parametrize("lang,phrase", [
        ("en", "left to the client's tax advisors"),
        ("it", "rimessa ai consulenti fiscali del cliente"),
    ])
    def test_quantification_is_disclaimed(self, lang: str, phrase: str):
        """The report states that it does not price an exposure itself."""
        assert phrase in _render_introduction("Project X", [], lang)

    def test_sentence_matches_the_registry_for_a_past_date(self):
        """A review run in late 2020 reached back to fiscal year 2015."""
        sentence = tax_rules_registry.describe_scope(as_of=date(2020, 11, 11))
        assert "2015" in sentence


# ── Legal rules reaching the aggregation ────────────────────────────────────


class TestLegalRulesContext:
    @pytest.mark.parametrize(
        "fragment",
        [
            "25-novies",              # overdue public debts → crisis reporting
            "2484",                   # negative equity → dissolution cause
            "change-of-control",      # financing clauses the deal can trigger
            "release or replacement",  # sellers' guarantees
            "hold-harmless",          # side agreements shifting tax liabilities
            "former shareholders",    # positions from the target's own deals
            "not reconciled",         # documents not provided
        ],
    )
    def test_new_priorities_are_in_the_context(self, fragment: str):
        assert fragment in build_legal_rules_context()

    @pytest.mark.parametrize("fragment", ["art. 2477 c.c.", "more than 50 employees in 2006"])
    def test_new_safe_harbours_are_in_the_context(self, fragment: str):
        """An unaudited micro-company and an ordinary TFR are not findings."""
        assert fragment in build_legal_rules_context()
