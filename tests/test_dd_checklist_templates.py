"""Requests must be usable without unconfigured deal-specific thresholds."""

import pytest

from packages.agents.dd_checklist import CHECKLIST


@pytest.mark.parametrize("language", ["it", "en"])
def test_checklist_does_not_publish_unresolved_thresholds(language):
    for item in CHECKLIST:
        text = item[f"request_{language}"]
        assert "[●]" not in text, item["key"]
        assert "indicata in premessa" not in text, item["key"]
        assert "set out in the introduction" not in text, item["key"]


@pytest.mark.parametrize("key", ["G.7", "H.2"])
def test_unthresholded_requests_collect_values_for_materiality_review(key):
    item = next(item for item in CHECKLIST if item["key"] == key)
    assert "valore" in item["request_it"]
    assert "value" in item["request_en"]
