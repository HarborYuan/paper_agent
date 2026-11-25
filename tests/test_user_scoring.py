import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool
import sys
import os

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import app, get_session
from src.models import Paper
from unittest.mock import AsyncMock, MagicMock

# In-memory DB for testing
@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", 
        connect_args={"check_same_thread": False}, 
        poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

from datetime import datetime

def test_user_score_endpoint(client, session):
    # 1. Create a paper
    paper = Paper(
        id="test.123",
        title="Test Paper",
        authors="[]",
        summary_generic="Summary",
        published_at=datetime(2023, 1, 1),
        category_primary="cs.AI",
        all_categories="[]",
        pdf_url="http://example.com",
        status="NEW"
    )
    session.add(paper)
    session.commit()

    # 2. Set user score
    response = client.patch("/api/papers/test.123/score", params={"score": 99})
    assert response.status_code == 200
    data = response.json()
    assert data["user_score"] == 99
    assert data["score"] == 99
    assert data["status"] == "SCORED"
    
    # 3. Verify in DB
    session.refresh(paper)
    assert paper.user_score == 99
    assert paper.score == 99
    assert paper.status == "SCORED"

    # 4. Test invalid score
    response = client.patch("/api/papers/test.123/score", params={"score": 101})
    assert response.status_code == 400

@pytest.mark.asyncio
async def test_pipeline_skips_user_scored_papers():
    """User-scored papers are never sent to the model (no request is built for them)."""
    from src.services import verdict_pipeline

    class _Runner:
        async def run(self, reqs, log=None, batch=None):
            raise AssertionError("no requests expected for user-scored papers")

    paper = Paper(id="test.456", title="T", authors="[]", summary_generic="S", published_at="2023-01-01T00:00:00",
                  category_primary="cs.AI", all_categories="[]", pdf_url="http://example.com", status="NEW", user_score=88)
    stats = await verdict_pipeline.run_pipeline([paper], _Runner())
    assert stats["screened"] == 0
