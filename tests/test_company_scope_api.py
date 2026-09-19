"""User-confirmed corporate perimeter applies consistently to saved reports."""
from unittest.mock import patch

import pytest

from app.models.company_profile import CompanyProfile
from app.models.deal import Deal, DealStatus
from app.models.document import Document, DocumentStatus
from app.models.report import Report, ReportStatus, ReportType
from packages.agents.analysis_checkpoint import corpus_fingerprint


def seed_profiles(db, deal):
    rows = []
    for name, office, capital in [
        ("TargetCo S.p.A.", "Milano", None),
        ("TARGETCO SPA", None, "Euro 100.000"),
        ("Supplier S.r.l.", "Torino", None),
        ("TargetCo Servizi S.p.A.", "Roma", None),
    ]:
        doc = Document(deal_id=deal.id, filename=f"visura-{len(rows)}.pdf",
                       file_path=f"/test/{len(rows)}.pdf", mime_type="application/pdf",
                       file_size=20, status=DocumentStatus.processed, raw_text="Source evidence")
        db.add(doc)
        db.flush()
        row = CompanyProfile(deal_id=deal.id, company_name=name, registered_office=office,
                             corporate_capital=capital, source_document_id=doc.id)
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


def seed_report(db, deal, content=None):
    report = Report(deal_id=deal.id, title="Original report", report_type=ReportType.due_diligence,
                    status=ReportStatus.completed, content=content or (
                        "# Report\n\n## 1. Introduction\nOriginal summary.\n\n"
                        "## 2. Corporate Introductory Information\n"
                        "### 2.1 TargetCo S.p.A.\nOld target.\n"
                        "### 2.2 Supplier S.r.l.\nWrong entity.\n\n"
                        "## 3. Red Flags\nOriginal financial findings.\n"))
    db.add(report)
    db.commit()
    return report


def test_company_profiles_filters_and_consolidates_existing_evidence(client, auth_headers, db, test_deal):
    rows = seed_profiles(db, test_deal)
    response = client.get(f"/deals/{test_deal.id}/company-profiles", headers=auth_headers)
    assert response.status_code == 200
    profiles = response.json()
    assert len(profiles) == 1
    assert profiles[0]["registered_office"] == "Milano"
    assert profiles[0]["corporate_capital"] == "Euro 100.000"
    assert profiles[0]["source_document_ids"] == [rows[0].source_document_id, rows[1].source_document_id]
    assert len(profiles[0]["source_filenames"]) == 2
    assert db.query(CompanyProfile).count() == 4  # source evidence is retained


def test_no_scope_does_not_guess_from_title_or_profile_frequency(client, auth_headers, db, test_deal):
    seed_profiles(db, test_deal)
    test_deal.target_company_names = None
    test_deal.title = "Acquisition of TargetCo S.p.A."
    db.commit()
    response = client.get(f"/deals/{test_deal.id}/company-profiles", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_setting_scope_preserves_saved_report_and_requires_new_analysis(client, auth_headers, db, test_deal):
    seed_profiles(db, test_deal)
    report = seed_report(db, test_deal)
    previous = report.content
    with patch("packages.agents.deal_analysis_agent.get_llm_provider", side_effect=AssertionError("No LLM")):
        response = client.patch(f"/deals/{test_deal.id}", headers=auth_headers,
                                json={"target_company_names": ["TargetCo S.p.A."]})
    assert response.status_code == 200
    db.refresh(report)
    assert report.content == previous
    saved = client.get(f"/deals/{test_deal.id}/report", headers=auth_headers)
    assert saved.json()["markdown"] == report.content
    assert saved.json()["stale"] is True
    with patch("app.services.report_export.render_pdf", return_value=b"%PDF-1.4") as render:
        export = client.get(f"/deals/{test_deal.id}/report/export?format=pdf", headers=auth_headers)
    assert export.status_code == 409
    render.assert_not_called()


def test_scope_change_preserves_unknown_report_without_rewriting_it(client, auth_headers, db, test_deal):
    report = seed_report(db, test_deal, content="Custom report without a known introductory section")
    response = client.patch(f"/deals/{test_deal.id}", headers=auth_headers,
                            json={"target_company_names": ["Other S.r.l."], "title": "Changed"})
    assert response.status_code == 200
    db.refresh(test_deal)
    db.refresh(report)
    assert test_deal.title == "Changed"
    assert test_deal.target_company_names == ["Other S.r.l."]
    assert report.content == "Custom report without a known introductory section"


def test_scope_cannot_change_during_analysis(client, auth_headers, db, test_deal):
    test_deal.status = DealStatus.analyzing
    db.commit()
    response = client.patch(f"/deals/{test_deal.id}", headers=auth_headers,
                            json={"target_company_names": ["Other S.r.l."]})
    assert response.status_code == 409
    db.refresh(test_deal)
    assert test_deal.target_company_names == ["TargetCo S.p.A."]


def test_target_scope_participates_in_checkpoint_fingerprint(db, test_deal):
    seed_profiles(db, test_deal)
    original, _ = corpus_fingerprint(db, test_deal.id)
    test_deal.target_company_names = ["Different S.r.l."]
    db.flush()
    changed, _ = corpus_fingerprint(db, test_deal.id)
    assert changed != original
    test_deal.target_company_names = None
    db.flush()
    cleared, _ = corpus_fingerprint(db, test_deal.id)
    assert cleared != original and cleared != changed


@pytest.mark.parametrize("names", [[" "], ["!!!"], ["x" * 501], ["Target"] * 21, "Target", [1]])
def test_invalid_target_scope_rejected(client, auth_headers, test_deal, names):
    response = client.patch(f"/deals/{test_deal.id}", headers=auth_headers,
                            json={"target_company_names": names})
    assert response.status_code == 422


def test_scope_canonical_duplicates_removed_but_distinct_entities_retained(client, auth_headers, test_workspace):
    response = client.post(f"/deals/?workspace_id={test_workspace.id}", headers=auth_headers,
                           json={"title": "Project", "target_company_names": [
                               " TargetCo S.p.A. ", "TARGETCO SPA", "TargetCo S.r.l."]})
    assert response.status_code == 201
    assert response.json()["target_company_names"] == ["TargetCo S.p.A.", "TargetCo S.r.l."]


def test_missing_scope_field_preserves_scope_while_null_clears_it(client, auth_headers, test_deal):
    first = client.patch(f"/deals/{test_deal.id}", headers=auth_headers, json={"title": "Renamed"})
    assert first.status_code == 200
    assert first.json()["target_company_names"] == ["TargetCo S.p.A."]
    second = client.patch(f"/deals/{test_deal.id}", headers=auth_headers, json={"target_company_names": None})
    assert second.status_code == 200
    assert second.json()["target_company_names"] is None


def test_scope_update_and_profiles_are_owner_scoped(client, auth_headers, db, test_workspace):
    from app.models.user import User
    from app.models.workspace import Workspace
    other = User(email="scope-other@example.com", hashed_password="not-used")
    db.add(other)
    db.flush()
    workspace = Workspace(name="Other", owner_id=other.id)
    db.add(workspace)
    db.flush()
    deal = Deal(workspace_id=workspace.id, title="Other", target_company_names=["Private S.r.l."])
    db.add(deal)
    db.commit()
    assert client.get(f"/deals/{deal.id}/company-profiles", headers=auth_headers).status_code == 404
    assert client.patch(f"/deals/{deal.id}", headers=auth_headers,
                        json={"target_company_names": ["Changed"]}).status_code == 404
