"""Unit tests for the anti-hallucination grounding check.

``is_grounded(content, source)`` decides whether an LLM-produced clause is
actually supported by the source document. These tests pin the two
robustness properties added during review:

* invented figures (amounts, dates, percentages) are rejected even when the
  surrounding words overlap heavily with the source;
* a trailing ellipsis added by the LLM is stripped without mangling text that
  legitimately ends in a period (e.g. "S.p.A.").
"""
from packages.agents.deal_analysis_agent import is_grounded


class TestExactAndFuzzy:
    def test_verbatim_content_is_grounded(self):
        source = "The agreement has a term of five years commencing on 1 January."
        assert is_grounded("term of five years", source) is True

    def test_minor_reformulation_grounded_via_overlap(self):
        source = "The lease payment is 500 euros per month for the office space."
        # Same words, reordered/partial — should pass the word-overlap fallback.
        assert is_grounded("lease payment 500 euros per month", source) is True

    def test_fully_hallucinated_text_rejected(self):
        source = "The agreement has a term of five years."
        assert is_grounded("the parties agree to binding arbitration in London", source) is False

    def test_empty_inputs_not_grounded(self):
        assert is_grounded("", "something") is False
        assert is_grounded("something", "") is False


class TestNumericGuard:
    def test_invented_amount_rejected_despite_word_overlap(self):
        source = "The lease payment is 500 euros per month for the office space."
        # Every word except the figure appears in the source, but 900 does not.
        assert is_grounded("The lease payment is 900 euros per month", source) is False

    def test_matching_amount_is_grounded(self):
        source = "The lease payment is 500 euros per month for the office space."
        assert is_grounded("lease payment is 500 euros per month", source) is True

    def test_invented_year_rejected(self):
        source = "This agreement is effective from the year 2019 onwards."
        assert is_grounded("agreement effective from the year 2025", source) is False


class TestEllipsisStripping:
    def test_trailing_ellipsis_ignored(self):
        source = "The term is five years and shall renew automatically."
        assert is_grounded("The term is five years…", source) is True
        assert is_grounded("The term is five years...", source) is True

    def test_abbreviation_period_preserved(self):
        # The old rstrip('...') bug stripped every trailing '.', mangling
        # abbreviations. Verify an abbreviation ending in a period still grounds.
        source = "The seller is Rossi S.p.A. registered in Milan."
        assert is_grounded("Rossi S.p.A.", source) is True
