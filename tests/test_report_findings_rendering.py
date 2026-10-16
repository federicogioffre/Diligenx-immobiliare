"""Tests for how a red flag's quantitative fields reach the report.

Covers:
- The amount and fiscal years a finding carries are rendered in the Key
  Findings row, in the conventions of the report's language
- The remedy tag is rendered at the end of the recommendation cell
- Rows without figures or without a tag render exactly as before
- The chain-of-title scope sentence is computed from the titles on file
- The dated property rules reach the aggregation context
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.models.red_flag import DueDiligenceArea, Severity
from packages.real_estate import rules_registry
from packages.agents.report_agent import (
    _format_amount,
    _format_figures,
    _render_introduction,
    _render_key_findings,
)


def _flag(**overrides) -> SimpleNamespace:
    base = dict(
        title="Mortgage to be cancelled",
        issue="A voluntary mortgage registered in 2015 secures the seller's loan.",
        risk="The buyer acquires the property subject to the mortgage.",
        recommendation="Provide in the preliminary contract that the seller cancels it at the deed.",
        severity=Severity.high,
        area=DueDiligenceArea.encumbrances,
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
            ("seller_undertaking", "[Seller's undertaking]", "[Impegno del venditore]"),
            ("escrow", "[Escrow with the notary]", "[Deposito presso il notaio]"),
            ("condition_precedent", "[Condition precedent]", "[Condizione sospensiva]"),
            ("price_adjustment", "[Price reduction]", "[Riduzione del prezzo]"),
            ("pre_closing_verification", "[Verification before the deed]", "[Verifica prima del rogito]"),
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
        markdown = _render_key_findings([_flag(remedy_type="earn_out")], "en")
        assert "earn" not in markdown.lower()

    def test_tag_survives_a_missing_recommendation(self):
        flag = _flag(recommendation=None, remedy_type="warranty")
        assert "[Seller's warranty]" in _render_key_findings([flag], "en")


# ── Scope sentence ──────────────────────────────────────────────────────────


class TestChainScopeSentence:
    def test_without_dated_titles_the_chain_is_not_verified(self):
        assert "twenty-year chain of title is not verified" in _render_introduction("Via Roma 1", [], "en")
        assert "la provenienza ventennale non è verificata" in _render_introduction("Via Roma 1", [], "it")

    def test_covered_chain(self):
        coverage = rules_registry.chain_coverage([date(2001, 3, 1)], as_of=date(2026, 10, 16))
        intro = _render_introduction("Via Roma 1", [], "it", coverage)
        assert "1 marzo 2001" in intro and "coprono il ventennio" in intro

    def test_gap_in_the_chain(self):
        coverage = rules_registry.chain_coverage([date(2015, 3, 12)], as_of=date(2026, 10, 16))
        intro = _render_introduction("Via Roma 1", [], "en", coverage)
        assert "12 March 2015" in intro and "is not covered" in intro and "16 October 2006" in intro

    @pytest.mark.parametrize("lang,phrase", [
        ("en", "left to the notary and the technician"),
        ("it", "rimessi al notaio e al tecnico"),
    ])
    def test_costs_are_disclaimed(self, lang: str, phrase: str):
        """The report states that it does not price a regularisation itself."""
        assert phrase in _render_introduction("Via Roma 1", [], lang)

    @pytest.mark.parametrize("lang,phrase", [
        ("en", "does not include an inspection of the property"),
        ("it", "non comprende il sopralluogo"),
    ])
    def test_inspection_is_excluded(self, lang: str, phrase: str):
        assert phrase in _render_introduction("Via Roma 1", [], lang)


class TestRulesContext:
    @pytest.mark.parametrize("fragment", [
        "563 c.c.", "29, comma 1-bis, L. 52/1985", "D.P.R. 380/2001",
        "63, quarto e quinto comma", "2847", "D.M. 37/2008", "D.Lgs. 192/2005",
    ])
    def test_rules_in_force_are_in_the_context(self, fragment: str):
        assert fragment in rules_registry.rules_context(date(2026, 10, 16))

    def test_superseded_version_is_not_cited(self):
        assert "testo anteriore alla L. 220/2012" not in rules_registry.rules_context(date(2026, 10, 16))
        assert "testo anteriore alla L. 220/2012" in rules_registry.rules_context(date(2010, 1, 1))
