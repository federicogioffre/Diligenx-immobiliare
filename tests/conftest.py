import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Ensure app package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

# Override DATABASE_URL before importing app
os.environ["DATABASE_URL"] = "sqlite:///./test_diligenx.db"

from app.main import app  # noqa: E402
from app.db.session import Base, get_db  # noqa: E402
from app.models import User, Workspace, Deal  # noqa: E402
from app.models.document_chunk import EMBEDDING_DIM  # noqa: E402
from app.core.security import hash_password, create_access_token  # noqa: E402
from packages.retrieval.embedding_service import FakeEmbeddingProvider, set_embedding_provider  # noqa: E402
from app.core.limiter import limiter  # noqa: E402

TEST_DATABASE_URL = "sqlite:///./test_diligenx.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _use_fake_embeddings():
    """Use FakeEmbeddingProvider globally — no OpenAI calls in tests."""
    set_embedding_provider(FakeEmbeddingProvider(dimension=EMBEDDING_DIM))
    yield
    set_embedding_provider(None)


@pytest.fixture(autouse=True)
def _disable_rate_limiter():
    """slowapi keeps in-memory counters that persist across tests, causing
    spurious 429s once a per-minute budget is exhausted. Disable globally in
    tests; dedicated tests for rate limiting can re-enable it locally."""
    limiter.enabled = False
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = True


@pytest.fixture
def db() -> Session:
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db: Session) -> TestClient:
    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db: Session) -> User:
    user = User(
        email="test@example.com",
        hashed_password=hash_password("testpass123"),
        full_name="Test User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict:
    token = create_access_token(test_user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_workspace(db: Session, test_user: User) -> Workspace:
    ws = Workspace(name="Test Workspace", owner_id=test_user.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


@pytest.fixture
def test_deal(db: Session, test_workspace: Workspace) -> Deal:
    deal = Deal(
        workspace_id=test_workspace.id,
        title="Test Deal",
        description="A test deal",
        value=100_000.0,
        target_company_names=["TargetCo S.p.A."],
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal
