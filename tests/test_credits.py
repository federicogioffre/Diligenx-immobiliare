from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.credit_transaction import CreditTransaction
from app.models.deal import DealStatus
from app.models.document import Document, DocumentStatus


@pytest.fixture
def credits_on(monkeypatch):
    monkeypatch.setattr(settings, "CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "CREDITS_UNLIMITED_EMAILS", [])


@pytest.fixture
def dispatch(monkeypatch):
    mock = AsyncMock(return_value="arq")
    monkeypatch.setattr("app.services.jobs.enqueue_or_run", mock)
    return mock


def _doc(db, deal, pages=None, text="x"):
    db.add(Document(deal_id=deal.id, filename="a.pdf", file_path="unused", file_size=1,
                    mime_type="application/pdf", status=DocumentStatus.processed,
                    page_count=pages, raw_text=text))
    db.commit()


def _balance(db, user):
    db.refresh(user)
    return user.credit_balance


def test_analysis_costs_one_credit_per_page(client, db, test_user, test_deal, auth_headers, credits_on, dispatch):
    _doc(db, test_deal, pages=12)
    _doc(db, test_deal, pages=None, text="y" * 6001)  # DOCX/TXT: 3000 chars a page
    test_user.credit_balance = 20
    db.commit()
    cost = client.get(f"/deals/{test_deal.id}/analysis-cost", headers=auth_headers).json()
    assert cost == {"cost": 15, "balance": 20, "charged": True, "sufficient": True}
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 202
    assert _balance(db, test_user) == 5
    entry = db.query(CreditTransaction).one()
    assert (entry.delta, entry.balance_after, entry.reason, entry.deal_id) == (-15, 5, "analysis", test_deal.id)


def test_insufficient_credits_refuse_analysis_and_leave_deal_untouched(
        client, db, test_user, test_deal, auth_headers, credits_on, dispatch):
    _doc(db, test_deal, pages=40)
    test_user.credit_balance = 39
    db.commit()
    response = client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
    assert response.status_code == 402
    assert response.json()["detail"]["code"] == "insufficient_credits"
    assert response.json()["detail"]["required"] == 40
    dispatch.assert_not_awaited()
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.draft
    assert _balance(db, test_user) == 39
    assert db.query(CreditTransaction).count() == 0


def test_queue_failure_refunds_the_analysis(client, db, test_user, test_deal, auth_headers, credits_on, monkeypatch):
    _doc(db, test_deal, pages=10)
    test_user.credit_balance = 10
    db.commit()
    monkeypatch.setattr("app.services.jobs.enqueue_or_run", AsyncMock(side_effect=HTTPException(503, "down")))
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 503
    assert _balance(db, test_user) == 10
    reasons = [t.reason for t in db.query(CreditTransaction).order_by(CreditTransaction.id)]
    assert reasons == ["analysis", "refund"]


def test_rejected_admission_does_not_charge(client, db, test_user, test_deal, auth_headers, credits_on, dispatch):
    _doc(db, test_deal, pages=5)
    test_user.credit_balance = 50
    db.commit()
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 202
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 409
    assert _balance(db, test_user) == 45


def test_unlimited_and_disabled_accounts_are_not_charged(client, db, test_user, test_deal, auth_headers, monkeypatch, dispatch):
    _doc(db, test_deal, pages=5)
    monkeypatch.setattr(settings, "CREDITS_ENABLED", True)
    monkeypatch.setattr(settings, "CREDITS_UNLIMITED_EMAILS", ["TEST@example.com"])
    assert client.get(f"/deals/{test_deal.id}/analysis-cost", headers=auth_headers).json()["sufficient"] is True
    assert client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers).status_code == 202
    assert _balance(db, test_user) == 0
    assert db.query(CreditTransaction).count() == 0


def test_question_is_charged_and_refunded_on_failure(client, db, test_user, test_deal, auth_headers, credits_on, monkeypatch):
    monkeypatch.setattr(settings, "ASK_CREDIT_COST", 2)
    test_user.credit_balance = 3
    db.commit()
    monkeypatch.setattr("packages.agents.deal_qa_agent.answer_deal_question",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model down")))
    assert client.post(f"/deals/{test_deal.id}/ask", json={"question": "Chi è il socio?"},
                       headers=auth_headers).status_code == 500
    assert _balance(db, test_user) == 3
    monkeypatch.setattr("packages.agents.deal_qa_agent.answer_deal_question",
                        lambda *a, **k: {"question": "Chi è il socio?", "answer": "X", "sources": []})
    assert client.post(f"/deals/{test_deal.id}/ask", json={"question": "Chi è il socio?"},
                       headers=auth_headers).status_code == 200
    assert _balance(db, test_user) == 1
    assert client.post(f"/deals/{test_deal.id}/ask", json={"question": "Chi è il socio?"},
                       headers=auth_headers).status_code == 402


def test_report_refunded_when_analysis_is_incomplete(client, db, test_user, test_deal, auth_headers, credits_on, monkeypatch):
    from packages.agents.report_agent import IncompleteAnalysisError

    def incomplete(*args, **kwargs):
        raise IncompleteAnalysisError("not analysed")

    monkeypatch.setattr("packages.agents.report_agent.generate_due_diligence_report", incomplete)
    test_user.credit_balance = settings.REPORT_CREDIT_COST
    db.commit()
    assert client.post(f"/deals/{test_deal.id}/report", headers=auth_headers).status_code == 409
    assert _balance(db, test_user) == settings.REPORT_CREDIT_COST


def test_signup_grants_opening_balance(client, db, monkeypatch):
    monkeypatch.setattr(settings, "SIGNUP_CREDITS", 120)
    response = client.post("/auth/register", json={"email": "new@example.com", "password": "Str0ng-password!"})
    assert response.status_code == 201, response.text
    assert response.json()["credit_balance"] == 120
    entry = db.query(CreditTransaction).one()
    assert (entry.reason, entry.delta, entry.balance_after) == ("signup", 120, 120)


def test_ledger_endpoint_and_cli_top_up(client, db, test_user, auth_headers, credits_on, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app import credits_cli
    monkeypatch.setattr(credits_cli, "SessionLocal", sessionmaker(bind=db.get_bind()))
    assert credits_cli.main(["grant", "TEST@example.com", "250", "--note", "beta"]) == 0
    assert credits_cli.main(["grant", "test@example.com", "-300"]) == 1
    assert credits_cli.main(["grant", "nobody@example.com", "5"]) == 1
    db.expire_all()  # the CLI wrote through its own session
    body = client.get("/users/me/credits", headers=auth_headers).json()
    assert body["balance"] == 250 and body["charged"] is True
    assert body["transactions"][0]["note"] == "beta"
