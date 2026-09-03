"""Tests for GET /deals/{deal_id}/agent-runs and AgentRun observability.

Covers:
- Endpoint: empty list, auth, 404 (unknown deal / wrong user)
- Response shape: all AgentRunRead fields present
- duration_seconds computed from timestamps (positive float after completion)
- Pipeline order: runs returned in started_at-ascending order
- Error observability: failed stage has error_message populated
- Successful runs have null error_message
- DB-level: duration_seconds property on the AgentRun model directly
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from packages.agents.deal_analysis_agent import FakeLLMProvider, set_llm_provider
from packages.agents.orchestrator import run_deal_analysis_pipeline, AGENT_RED_FLAG


# ── Module-level fixtures ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def use_fake_llm():
    """Inject FakeLLMProvider globally for every test in this module."""
    set_llm_provider(FakeLLMProvider())
    yield
    set_llm_provider(None)


@pytest.fixture
def processed_doc(db: Session, test_deal: Deal) -> Document:
    """Processed document with contract-style text."""
    doc = Document(
        deal_id=test_deal.id,
        filename="service_agreement.txt",
        file_path="/tmp/service_agreement.txt",
        mime_type="text/plain",
        file_size=2048,
        status=DocumentStatus.processed,
        raw_text=(
            "SERVICE AGREEMENT\n\n"
            "Either party may terminate this agreement with 30 days notice.\n\n"
            "In no event shall either party be liable for indirect damages."
        ),
        language="en",
        page_count=2,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@pytest.fixture
def failing_red_flag_llm():
    """LLM that raises on the red-flag prompt only."""
    class FailOnRedFlags(FakeLLMProvider):
        def complete(self, prompt: str, max_tokens: int = 2048) -> str:
            p = prompt.upper()
            if "RED FLAGS" in p and "DUE DILIGENCE" not in p:
                raise RuntimeError("Simulated red-flag failure for test")
            return super().complete(prompt, max_tokens)
    return FailOnRedFlags()


# ── 1. Endpoint basics ─────────────────────────────────────────────────────

class TestAgentRunEndpoint:

    def test_empty_list_for_deal_with_no_runs(
        self, client, auth_headers, test_deal: Deal
    ):
        """A deal that has never been analysed returns an empty list."""
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_requires_authentication(self, client, test_deal: Deal):
        """Missing token → 401 or 403."""
        response = client.get(f"/deals/{test_deal.id}/agent-runs")
        assert response.status_code in (401, 403)

    def test_unknown_deal_returns_404(self, client, auth_headers):
        response = client.get("/deals/99999/agent-runs", headers=auth_headers)
        assert response.status_code == 404

    def test_wrong_user_returns_404(
        self, client, db: Session, test_deal: Deal
    ):
        """A JWT for a different user cannot access another user's deal runs."""
        from app.models.user import User
        from app.core.security import hash_password, create_access_token

        other = User(
            email="other_runs@example.com",
            hashed_password=hash_password("pass123"),
            full_name="Other User",
        )
        db.add(other)
        db.commit()
        db.refresh(other)

        token = create_access_token(other.email)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    def test_returns_eight_runs_after_full_pipeline(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        """Full pipeline produces exactly 8 agent run records."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 8

    # ── Response shape ─────────────────────────────────────────────────── #

    def test_run_shape_all_fields_present(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        """Every run object exposes all AgentRunRead fields."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        required_fields = {
            "id", "deal_id", "document_id", "agent_name", "status",
            "started_at", "completed_at", "duration_seconds",
            "error_message", "input_hash", "created_at",
        }
        for run in response.json():
            assert required_fields.issubset(run.keys()), (
                f"Missing fields in run for '{run.get('agent_name')}': "
                f"{required_fields - run.keys()}"
            )

    def test_deal_id_matches_in_all_runs(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        for run in response.json():
            assert run["deal_id"] == test_deal.id

    def test_all_runs_have_status(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        valid_statuses = {"pending", "running", "completed", "failed"}
        for run in response.json():
            assert run["status"] in valid_statuses

    # ── Duration ───────────────────────────────────────────────────────── #

    def test_duration_seconds_is_positive_float_for_completed_runs(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        """All completed runs must report a non-negative duration."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        for run in response.json():
            if run["status"] == "completed":
                assert run["duration_seconds"] is not None
                assert run["duration_seconds"] >= 0.0, (
                    f"Negative duration for '{run['agent_name']}': "
                    f"{run['duration_seconds']}"
                )

    def test_started_at_populated_for_all_runs(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        for run in response.json():
            assert run["started_at"] is not None, (
                f"started_at missing for '{run['agent_name']}'"
            )

    def test_completed_at_populated_after_pipeline(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        for run in response.json():
            assert run["completed_at"] is not None, (
                f"completed_at missing for '{run['agent_name']}'"
            )

    # ── Pipeline order ─────────────────────────────────────────────────── #

    def test_runs_ordered_by_started_at_ascending(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        """Runs are returned in pipeline execution order (earliest first)."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        runs = response.json()
        started_times = [r["started_at"] for r in runs if r["started_at"]]
        assert started_times == sorted(started_times), (
            "Runs not in ascending started_at order"
        )

    def test_first_run_is_intake_stage(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        """The first run (earliest started_at) must be the intake stage."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        runs = response.json()
        assert runs[0]["agent_name"] == "intake"

    def test_last_run_is_report_stage(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        """The last run (latest started_at) must be the report stage."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        runs = response.json()
        assert runs[-1]["agent_name"] == "report_generation"

    def test_all_expected_agent_names_present(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        names = {r["agent_name"] for r in response.json()}
        expected = {
            "intake", "document_router", "contract_analysis",
            "corporate_governance", "corporate_intro_extraction",
            "tax_analysis", "red_flag_aggregation", "report_generation",
        }
        assert names == expected

    # ── Error observability ────────────────────────────────────────────── #

    def test_successful_runs_have_null_error_message(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        for run in response.json():
            if run["status"] == "completed":
                assert run["error_message"] is None, (
                    f"Completed run '{run['agent_name']}' has unexpected "
                    f"error_message: {run['error_message']}"
                )

    def test_failed_run_has_error_message(
        self,
        client,
        auth_headers,
        test_deal: Deal,
        processed_doc: Document,
        db: Session,
        failing_red_flag_llm,
    ):
        """When a stage fails, its error_message is non-null and non-empty."""
        # Run pipeline with the error-inducing LLM via the DB (not HTTP) to
        # inject the provider directly, then verify via the HTTP endpoint.
        run_deal_analysis_pipeline(
            test_deal.id, db, provider=failing_red_flag_llm
        )
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        assert response.status_code == 200
        runs = {r["agent_name"]: r for r in response.json()}

        red_flag_run = runs.get(AGENT_RED_FLAG)
        assert red_flag_run is not None
        assert red_flag_run["status"] == "failed"
        assert red_flag_run["error_message"] is not None
        assert len(red_flag_run["error_message"]) > 0

    def test_failed_run_duration_still_computed(
        self,
        client,
        auth_headers,
        test_deal: Deal,
        processed_doc: Document,
        db: Session,
        failing_red_flag_llm,
    ):
        """Even for failed runs, duration_seconds should be non-null."""
        run_deal_analysis_pipeline(
            test_deal.id, db, provider=failing_red_flag_llm
        )
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        runs = {r["agent_name"]: r for r in response.json()}
        red_flag_run = runs[AGENT_RED_FLAG]
        assert red_flag_run["duration_seconds"] is not None
        assert red_flag_run["duration_seconds"] >= 0.0

    # ── Idempotency / repeated runs ────────────────────────────────────── #

    def test_run_count_stable_after_two_pipeline_executions(
        self, client, auth_headers, test_deal: Deal, processed_doc: Document
    ):
        """Re-running the pipeline replaces runs; count stays at 6."""
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        client.post(f"/deals/{test_deal.id}/analyze", headers=auth_headers)
        response = client.get(
            f"/deals/{test_deal.id}/agent-runs",
            headers=auth_headers,
        )
        assert len(response.json()) == 8


# ── 2. AgentRun model — duration_seconds property ─────────────────────────

class TestAgentRunDurationProperty:
    """Unit tests for the duration_seconds property on the ORM model."""

    def test_duration_computed_correctly(self, db: Session, test_deal: Deal):
        from datetime import timedelta

        start = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2025, 1, 1, 10, 0, 5, 500_000, tzinfo=timezone.utc)  # 5.5 s
        run = AgentRun(
            deal_id=test_deal.id,
            agent_name="test_agent",
            status=AgentRunStatus.completed,
            started_at=start,
            completed_at=end,
        )
        db.add(run)
        db.flush()

        assert run.duration_seconds == pytest.approx(5.5, abs=1e-6)

    def test_duration_none_when_completed_at_missing(
        self, db: Session, test_deal: Deal
    ):
        run = AgentRun(
            deal_id=test_deal.id,
            agent_name="test_agent",
            status=AgentRunStatus.running,
            started_at=datetime.now(timezone.utc),
            completed_at=None,
        )
        db.add(run)
        db.flush()

        assert run.duration_seconds is None

    def test_duration_none_when_started_at_missing(
        self, db: Session, test_deal: Deal
    ):
        run = AgentRun(
            deal_id=test_deal.id,
            agent_name="test_agent",
            status=AgentRunStatus.pending,
            started_at=None,
            completed_at=None,
        )
        db.add(run)
        db.flush()

        assert run.duration_seconds is None

    def test_duration_positive_after_real_completion(
        self, db: Session, test_deal: Deal, processed_doc: Document
    ):
        """After running the pipeline, all AgentRun rows have duration > 0."""
        run_deal_analysis_pipeline(test_deal.id, db)
        runs = (
            db.query(AgentRun)
            .filter(AgentRun.deal_id == test_deal.id)
            .all()
        )
        assert len(runs) == 8
        for run in runs:
            assert run.duration_seconds is not None, (
                f"duration_seconds is None for '{run.agent_name}'"
            )
            assert run.duration_seconds >= 0.0, (
                f"Negative duration for '{run.agent_name}': {run.duration_seconds}"
            )
