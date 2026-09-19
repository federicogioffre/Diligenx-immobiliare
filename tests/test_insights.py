"""Tests for GET /workspaces/{id}/insights — aggregate metrics for the dashboard."""

from app.core.security import create_access_token, hash_password
from app.models.deal import Deal, DealStatus
from app.models.missing_document import MissingDocument
from app.models.open_question import Priority
from app.models.red_flag import RedFlag, Severity
from app.models.user import User
from app.models.workspace import Workspace


# ── helpers ────────────────────────────────────────────────────────────────


def _make_deal(db, workspace, *, title="D", status=DealStatus.draft) -> Deal:
    deal = Deal(workspace_id=workspace.id, title=title, status=status)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


def _make_red_flag(db, deal, *, severity=Severity.medium, category="termination") -> RedFlag:
    rf = RedFlag(
        deal_id=deal.id,
        title="A flag",
        issue="…",
        severity=severity,
        category=category,
    )
    db.add(rf)
    db.commit()
    return rf


def _make_missing(db, deal, *, category="contract") -> MissingDocument:
    md = MissingDocument(
        deal_id=deal.id,
        document_category=category,
        expected_item="Primary contract",
        reason="Not provided",
        priority=Priority.high,
    )
    db.add(md)
    db.commit()
    return md


# ── auth & ownership ──────────────────────────────────────────────────────


def test_insights_requires_authentication(client, test_workspace):
    resp = client.get(f"/workspaces/{test_workspace.id}/insights")
    assert resp.status_code in (401, 403)


def test_insights_unknown_workspace_returns_404(client, auth_headers):
    resp = client.get("/workspaces/99999/insights", headers=auth_headers)
    assert resp.status_code == 404


def test_insights_workspace_of_other_user_returns_404(client, db, test_workspace):
    """Owner-scoping: another user's workspace ID must look like 404, not 403."""
    other = User(
        email="other@example.com",
        hashed_password=hash_password("otherpass"),
        full_name="Other",
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    headers = {"Authorization": f"Bearer {create_access_token(other.email, user_id=other.id, hashed_password=other.hashed_password)}"}

    resp = client.get(f"/workspaces/{test_workspace.id}/insights", headers=headers)
    assert resp.status_code == 404


# ── empty workspace ───────────────────────────────────────────────────────


def test_insights_empty_workspace_returns_zeroed_buckets(
    client, auth_headers, test_workspace
):
    """Even with no deals, all status/severity buckets must be present."""
    resp = client.get(f"/workspaces/{test_workspace.id}/insights", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["workspace_id"] == test_workspace.id
    assert data["deals_total"] == 0
    assert data["deals_analyzed"] == 0
    assert data["red_flags_total"] == 0
    assert data["deals_with_missing_documents"] == 0
    assert data["top_red_flag_categories"] == []

    assert set(data["deals_by_status"].keys()) == {
        "draft", "analyzing", "reviewed", "closed",
    }
    assert all(v == 0 for v in data["deals_by_status"].values())

    assert set(data["red_flags_by_severity"].keys()) == {
        "low", "medium", "high",
    }
    assert all(v == 0 for v in data["red_flags_by_severity"].values())


# ── populated workspace ──────────────────────────────────────────────────


def test_insights_counts_deals_by_status(client, auth_headers, db, test_workspace):
    _make_deal(db, test_workspace, title="d1", status=DealStatus.draft)
    _make_deal(db, test_workspace, title="d2", status=DealStatus.draft)
    _make_deal(db, test_workspace, title="d3", status=DealStatus.reviewed)
    _make_deal(db, test_workspace, title="d4", status=DealStatus.analyzing)

    data = client.get(
        f"/workspaces/{test_workspace.id}/insights", headers=auth_headers
    ).json()

    assert data["deals_total"] == 4
    assert data["deals_by_status"]["draft"] == 2
    assert data["deals_by_status"]["analyzing"] == 1
    assert data["deals_by_status"]["reviewed"] == 1
    assert data["deals_by_status"]["closed"] == 0
    # analyzed = anything past draft
    assert data["deals_analyzed"] == 2


def test_insights_aggregates_red_flags_by_severity(
    client, auth_headers, db, test_workspace
):
    deal = _make_deal(db, test_workspace, status=DealStatus.reviewed)
    _make_red_flag(db, deal, severity=Severity.high)
    _make_red_flag(db, deal, severity=Severity.high)
    _make_red_flag(db, deal, severity=Severity.high)
    _make_red_flag(db, deal, severity=Severity.medium)

    data = client.get(
        f"/workspaces/{test_workspace.id}/insights", headers=auth_headers
    ).json()

    assert data["red_flags_total"] == 4
    assert data["red_flags_by_severity"]["high"] == 3
    assert data["red_flags_by_severity"]["medium"] == 1
    assert data["red_flags_by_severity"]["low"] == 0


def test_insights_top_categories_ordered_desc_and_limited_to_5(
    client, auth_headers, db, test_workspace
):
    deal = _make_deal(db, test_workspace, status=DealStatus.reviewed)
    # 6 distinct categories, with counts that should produce a clear order.
    plan = [
        ("termination", 5),
        ("liability", 4),
        ("confidentiality", 3),
        ("compliance", 2),
        ("payment", 2),
        ("other", 1),  # this one should be excluded by the top-5 limit
    ]
    for cat, n in plan:
        for _ in range(n):
            _make_red_flag(db, deal, category=cat)

    data = client.get(
        f"/workspaces/{test_workspace.id}/insights", headers=auth_headers
    ).json()

    cats = data["top_red_flag_categories"]
    assert len(cats) == 5
    assert [c["category"] for c in cats[:3]] == [
        "termination", "liability", "confidentiality",
    ]
    assert cats[0]["count"] == 5
    # "other" with count 1 must not appear
    assert "other" not in [c["category"] for c in cats]


def test_insights_counts_distinct_deals_with_missing_documents(
    client, auth_headers, db, test_workspace
):
    """A deal with multiple MissingDocument rows is still counted once."""
    d1 = _make_deal(db, test_workspace, title="d1", status=DealStatus.reviewed)
    d2 = _make_deal(db, test_workspace, title="d2", status=DealStatus.reviewed)
    _make_deal(db, test_workspace, title="d3", status=DealStatus.reviewed)  # complete
    _make_missing(db, d1, category="contract")
    _make_missing(db, d1, category="financial")  # second on same deal
    _make_missing(db, d2, category="legal")

    data = client.get(
        f"/workspaces/{test_workspace.id}/insights", headers=auth_headers
    ).json()

    assert data["deals_with_missing_documents"] == 2


def test_insights_excludes_other_workspaces_data(
    client, auth_headers, db, test_user, test_workspace
):
    """Counts must NOT bleed across workspaces, even within the same user."""
    other_ws = Workspace(name="Other WS", owner_id=test_user.id)
    db.add(other_ws)
    db.commit()
    db.refresh(other_ws)

    in_ws = _make_deal(db, test_workspace, status=DealStatus.reviewed)
    out_ws = _make_deal(db, other_ws, status=DealStatus.reviewed)
    _make_red_flag(db, in_ws, severity=Severity.high)
    _make_red_flag(db, out_ws, severity=Severity.medium)
    _make_red_flag(db, out_ws, severity=Severity.medium)

    data = client.get(
        f"/workspaces/{test_workspace.id}/insights", headers=auth_headers
    ).json()

    assert data["deals_total"] == 1
    assert data["red_flags_total"] == 1
    assert data["red_flags_by_severity"]["high"] == 1
    assert data["red_flags_by_severity"]["medium"] == 0
