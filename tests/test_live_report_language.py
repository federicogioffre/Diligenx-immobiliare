"""Regressions from the real-provider Italian sample, without network calls."""
from types import SimpleNamespace

import pytest

from packages.agents.output_language import has_language_mismatch, recommendation_examples
from packages.agents.report_agent import _format_source_citation


@pytest.mark.parametrize('recommendation', [
    'As a condition precedent to Closing, obtain the consent of the lender bank to the Transaction and a waiver of the DSCR covenant breach.',
    'Insert a specific indemnity in the SPA covering the assessed exposure, surviving until the expiry of the assessment period for FY2024 plus a grace period, secured by an escrow or a holdback.',
    "Insert specific Sellers' representations and warranties in the SPA on the recoverability of trade receivables; insert a price-adjustment mechanism reflecting any shortfall.",
])
def test_rejects_actual_english_recommendations_in_italian_report(recommendation):
    assert has_language_mismatch(recommendation, 'it')
    assert not has_language_mismatch(recommendation, 'en')


@pytest.mark.parametrize('text', [
    'DSCR, SPA e IRES',
    'Ottenere il consenso della banca prima del closing e verificare il DSCR.',
    'La fonte riporta "the consent of the lender to the transaction"; occorre verificarne il rilascio.',
    'Verificare 01_profilo_societario.pdf e il documento the_consent_of_the_lender.pdf.',
    'Change of control',
])
def test_does_not_reject_quotes_names_or_legal_acronyms(text):
    assert not has_language_mismatch(text, 'it')


def test_detects_mixed_paragraph_without_masking_english_sentence():
    assert has_language_mismatch(
        'La banca deve fornire il consenso per la cessione delle quote della target. '
        'Obtain the consent of the bank before the completion of the Transaction.', 'it')


def test_recommendation_examples_follow_requested_language():
    for lang in ('it', 'en'):
        assert not has_language_mismatch(recommendation_examples(lang), lang)


def test_combined_finding_preserves_multiple_documents_and_pages():
    flag = SimpleNamespace(source_document_id=241, source_page=2, structured_payload_json={
        'grounding_reviewed': True,
        'source_pages': [
            {'source_document_id': 241, 'page': 2},
            {'source_document_id': 241, 'page': 1},
            {'source_document_id': 241, 'page': 2},
            {'source_document_id': 242, 'page': 1},
        ]})
    assert _format_source_citation(flag, {241: 'finanziamento.pdf', 242: 'bilancio.pdf'}, 'it') == (
        '(finanziamento.pdf, pagg. 1, 2; bilancio.pdf, pag. 1)')


def test_old_single_page_citation_stays_compatible():
    flag = SimpleNamespace(source_document_id=241, source_page=2, structured_payload_json=None)
    assert _format_source_citation(flag, {241: 'finanziamento.pdf'}, 'en') == '(finanziamento.pdf, p. 2)'


def test_source_without_known_page_is_not_lost_in_multi_source_citation():
    flag = SimpleNamespace(source_document_id=241, source_page=None, structured_payload_json={
        'grounding_reviewed': True,
        'evidence': [{'source_document_id': 241}, {'source_document_id': 242}],
        'source_pages': [{'source_document_id': 241, 'page': 2}],
    })
    assert _format_source_citation(flag, {241: 'loan.pdf', 242: 'accounts.pdf'}, 'en') == (
        '(loan.pdf, p. 2; accounts.pdf)')


def test_unreviewed_payload_cannot_override_legacy_citation():
    flag = SimpleNamespace(source_document_id=241, source_page=2, structured_payload_json={
        'source_pages': [{'source_document_id': 242, 'page': 99}],
    })
    assert _format_source_citation(flag, {241: 'loan.pdf', 242: 'accounts.pdf'}, 'en') == '(loan.pdf, p. 2)'
