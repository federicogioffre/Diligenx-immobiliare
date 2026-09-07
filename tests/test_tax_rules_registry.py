"""Tests for the year-indexed registry of Italian tax rules.

Covers:
- Rule resolution by fiscal year, including rules that were repealed and
  rules that were repealed and later reintroduced in a different shape
- Assessment periods: the four-year term up to fiscal year 2015, the
  five-year term from 2016, the longer terms where no return was filed,
  and the citation attached to each
- Time-barring and the derived list of fiscal years still open
- The registry's design promise: no penalty rate, interest rate or
  reduction fraction anywhere in it
"""
import re
from datetime import date

import pytest

from packages.agents import tax_rules_registry as registry


# ── Rule resolution ─────────────────────────────────────────────────────────


class TestResolve:
    def test_resolves_the_version_in_force(self):
        old = registry.resolve("assessment_period", 2014)
        new = registry.resolve("assessment_period", 2020)
        assert old is not None and new is not None
        assert old is not new
        assert "before L. 208/2015" in old.citation
        assert "L. 208/2015" in new.citation

    def test_unknown_rule_returns_none(self):
        assert registry.resolve("no_such_rule", 2020) is None

    def test_rule_not_yet_in_force_returns_none(self):
        """A rule must not be cited for a year it did not govern."""
        assert registry.resolve("preliminary_cross_examination", 2019) is None
        assert registry.resolve("preliminary_cross_examination", 2024) is not None

    def test_repealed_rule_is_not_returned_for_later_years(self):
        """The assessment-term doubling died with fiscal year 2015."""
        assert registry.resolve("assessment_period_doubling", 2015) is not None
        assert registry.resolve("assessment_period_doubling", 2016) is None

    def test_rule_repealed_then_reintroduced(self):
        """Costs towards privileged jurisdictions: in, out, and back in."""
        assert registry.resolve("black_list_costs", 2014) is not None
        assert registry.resolve("black_list_costs", 2018) is None
        assert registry.resolve("black_list_costs_repeal", 2018) is not None
        assert registry.resolve("black_list_costs_reintroduced", 2018) is None
        assert registry.resolve("black_list_costs_reintroduced", 2024) is not None

    def test_obligations_that_no_longer_exist(self):
        """An abolished filing must never be cited as a current obligation."""
        assert registry.resolve("spesometro", 2015) is not None
        assert registry.resolve("spesometro", 2020) is None
        assert registry.resolve("black_list_communication", 2020) is None
        assert registry.resolve("electronic_invoicing", 2020) is not None

    def test_ace_and_its_repeal(self):
        assert registry.resolve("ace", 2022) is not None
        assert registry.resolve("ace", 2024) is None
        assert registry.resolve("ace_repeal", 2024) is not None

    @pytest.mark.parametrize("language,expected", [("en", "assessment"), ("it", "accertamento")])
    def test_gloss_is_bilingual(self, language: str, expected: str):
        text = registry.gloss("assessment_period", 2020, language=language)
        assert text is not None
        assert expected in text.lower()

    def test_citation_helper(self):
        assert registry.citation("directors_fees", 2020) == "Art. 95 co. 5 T.U.I.R."
        assert registry.citation("no_such_rule", 2020) is None

    def test_known_rule_ids_are_sorted_and_non_empty(self):
        ids = registry.known_rule_ids()
        assert ids == sorted(ids)
        assert "assessment_period" in ids


# ── Assessment periods ──────────────────────────────────────────────────────


class TestAssessmentPeriod:
    @pytest.mark.parametrize(
        "fiscal_year,expiry",
        [
            (2014, date(2019, 12, 31)),  # filed 2015, four-year term
            (2015, date(2020, 12, 31)),  # last year under the old term
            (2016, date(2022, 12, 31)),  # first year under the five-year term
            (2019, date(2025, 12, 31)),
            (2022, date(2028, 12, 31)),
        ],
    )
    def test_expiry_by_fiscal_year(self, fiscal_year: int, expiry: date):
        assert registry.assessment_period(fiscal_year).expiry == expiry

    def test_term_lengthens_when_no_return_was_filed(self):
        assert registry.assessment_period(2014, return_filed=False).expiry == date(
            2020, 12, 31
        )
        assert registry.assessment_period(2020, return_filed=False).expiry == date(
            2028, 12, 31
        )

    def test_filing_year_follows_the_fiscal_year(self):
        period = registry.assessment_period(2022)
        assert period.filing_year == 2023
        assert period.years_from_filing == 5

    def test_citation_matches_the_applicable_version(self):
        assert "before L. 208/2015" in registry.assessment_period(2014).citation
        assert "L. 208/2015" in registry.assessment_period(2020).citation

    def test_time_barring_is_evaluated_against_a_date(self):
        period = registry.assessment_period(2016)
        assert period.is_time_barred(date(2022, 12, 31)) is False
        assert period.is_time_barred(date(2023, 1, 1)) is True

    def test_notes_flag_what_is_not_baked_into_the_date(self):
        old = registry.assessment_period(2015)
        assert any("doubl" in n.lower() for n in old.notes)
        assert any("amended return" in n.lower() for n in old.notes)

        unfiled = registry.assessment_period(2020, return_filed=False)
        assert any("no return was filed" in n.lower() for n in unfiled.notes)


class TestOpenFiscalYears:
    def test_matches_a_known_historical_scope(self):
        """A review run in late 2020 reached back to fiscal year 2015."""
        years = registry.open_fiscal_years(as_of=date(2020, 11, 11))
        assert min(years) == 2015
        assert 2014 not in years

    def test_years_are_contiguous_and_sorted(self):
        years = registry.open_fiscal_years(as_of=date(2026, 9, 6))
        assert years == sorted(years)
        assert years == list(range(min(years), max(years) + 1))

    def test_scope_sentence_is_computed_not_fixed(self):
        sentence = registry.describe_scope(as_of=date(2020, 11, 11))
        assert "2015" in sentence
        italian = registry.describe_scope(as_of=date(2020, 11, 11), language="it")
        assert "accertabili" in italian


# ── The design promise ──────────────────────────────────────────────────────


class TestNoRatesAnywhere:
    """The registry cites the law; it never carries the arithmetic.

    Penalty rates, interest rates and reduction fractions depend on the
    fiscal year *and* on the procedure followed, and have been amended
    repeatedly. Quantifying an exposure is the client's tax advisers' job,
    so a number here would be a liability rather than a feature.
    """

    def _all_text(self) -> str:
        parts = []
        for versions in registry.RULES.values():
            for rule in versions:
                parts.extend([rule.gloss_en, rule.gloss_it])
        return " ".join(parts)

    def test_no_percentages_in_the_glosses(self):
        assert re.search(r"\d+\s*%", self._all_text()) is None

    def test_no_reduction_fractions_in_the_glosses(self):
        assert re.search(r"\b1\s*/\s*\d\b", self._all_text()) is None

    def test_quantification_policy_is_available_in_both_languages(self):
        assert "tax advisors" in registry.QUANTIFICATION_POLICY_EN
        assert "consulenti fiscali" in registry.QUANTIFICATION_POLICY_IT

    def test_every_rule_records_when_it_was_verified(self):
        for versions in registry.RULES.values():
            for rule in versions:
                assert isinstance(rule.last_verified, date)

    def test_versions_of_a_rule_do_not_overlap(self):
        for rule_id, versions in registry.RULES.items():
            spans = sorted(
                (r.valid_from, r.valid_to if r.valid_to is not None else 9999)
                for r in versions
            )
            for (_, end), (nxt_start, _) in zip(spans, spans[1:]):
                assert end < nxt_start, f"overlapping versions for {rule_id}"
