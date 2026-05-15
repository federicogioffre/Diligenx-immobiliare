"""Tests for GET /deals/{id}/open-questions and /deals/{id}/missing-documents."""

from app.core.security import create_access_token, hash_password
from app.models.deal import Deal
from app.models.missing_document import MissingDocument
from app.models.open_question import OpenQuestion, Priority, QuestionStatus
from app.models.user import User
from app.models.workspace import Workspace


# ── helpers ────────────────────────────────────────────────────────────────


def _make_question(db, deal, *, priority=Priority.medium, question="Why?") -> OpenQuestion:
    q = OpenQuestion(
        deal_id=deal.id,
        agent_name="red_flag_aggregation",
        question=question,
        priority=priority,
        status=QuestionStatus.open,
    )
    db.add(q)
    db.commit()
    return q


def _make_missing(db, deal, *, category="contract", priority=Priority.medium) -> MissingDocument:
    md = MissingDocument(
        deal_id=deal.id,
        document_category=category,
        expected_item=f"{category} document",
        reason="Not provided during intake",
        priority=priority,
    )
    db.add(md)
    db.commit()
    return md


def _other_user_headers(db) -> dict:
    other = User(
        email="other@example.com",
        hashed_password=hash_password("pwd"),
        full_name="Other",
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    return {"Authorization": f"Bearer {create_access_token(other.email)}"}


# ── /open-questions ────────────────────────────────────────────────────────


def test_open_questions_requires_auth(client, test_deal):
    resp = client.get(f"/deals/{test_deal.id}/open-questions")
    assert resp.status_code in (401, 403)


def test_open_questions_404_for_unknown_deal(client, auth_headers):
    resp = client.get("/deals/99999/open-questions", headers=auth_headers)
    assert resp.status_code == 404


def test_open_questions_404_for_other_users_deal(client, db, test_deal):
    headers = _other_user_headers(db)
    resp = client.get(f"/deals/{test_deal.id}/open-questions", headers=headers)
    assert resp.status_code == 404


def test_open_questions_empty_list_when_none(client, auth_headers, test_deal):
    resp = client.get(f"/deals/{test_deal.id}/open-questions", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_open_questions_ordered_by_priority_desc(client, auth_headers, db, test_deal):
    _make_question(db, test_deal, priority=Priority.low,    question="L")
    _make_question(db, test_deal, priority=Priority.high,   question="H")
    _make_question(db, test_deal, priority=Priority.medium, question="M")

    data = client.get(
        f"/deals/{test_deal.id}/open-questions", headers=auth_headers
    ).json()

    assert [q["priority"] for q in data] == ["high", "medium", "low"]


def test_open_questions_scoped_to_deal(client, auth_headers, db, test_deal, test_workspace):
    other_deal = Deal(workspace_id=test_workspace.id, title="Other deal")
    db.add(other_deal); db.commit(); db.refresh(other_deal)
    _make_question(db, test_deal, question="In")
    _make_question(db, other_deal, question="Out")

    data = client.get(
        f"/deals/{test_deal.id}/open-questions", headers=auth_headers
    ).json()

    assert len(data) == 1
    assert data[0]["question"] == "In"


# ── /missing-documents ─────────────────────────────────────────────────────


def test_missing_documents_requires_auth(client, test_deal):
    resp = client.get(f"/deals/{test_deal.id}/missing-documents")
    assert resp.status_code in (401, 403)


def test_missing_documents_404_for_unknown_deal(client, auth_headers):
    resp = client.get("/deals/99999/missing-documents", headers=auth_headers)
    assert resp.status_code == 404


def test_missing_documents_404_for_other_users_deal(client, db, test_deal):
    headers = _other_user_headers(db)
    resp = client.get(f"/deals/{test_deal.id}/missing-documents", headers=headers)
    assert resp.status_code == 404


def test_missing_documents_empty_when_none(client, auth_headers, test_deal):
    resp = client.get(f"/deals/{test_deal.id}/missing-documents", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_missing_documents_ordered_by_priority_desc(client, auth_headers, db, test_deal):
    _make_missing(db, test_deal, category="financial", priority=Priority.low)
    _make_missing(db, test_deal, category="contract",  priority=Priority.high)
    _make_missing(db, test_deal, category="insurance", priority=Priority.medium)

    data = client.get(
        f"/deals/{test_deal.id}/missing-documents", headers=auth_headers
    ).json()

    assert [m["priority"] for m in data] == ["high", "medium", "low"]
    assert [m["document_category"] for m in data] == ["contract", "insurance", "financial"]


def test_missing_documents_scoped_to_deal(client, auth_headers, db, test_deal, test_workspace):
    other_deal = Deal(workspace_id=test_workspace.id, title="Other deal")
    db.add(other_deal); db.commit(); db.refresh(other_deal)
    _make_missing(db, test_deal,  category="contract")
    _make_missing(db, other_deal, category="legal")

    data = client.get(
        f"/deals/{test_deal.id}/missing-documents", headers=auth_headers
    ).json()

    assert len(data) == 1
    assert data[0]["document_category"] == "contract"
