from fastapi.testclient import TestClient
from sqlmodel import Session
from src.models import Paper
from datetime import datetime

def test_read_main(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to Paper Agent. POST /run to start processing."}

def test_list_papers_empty(client: TestClient):
    response = client.get("/papers")
    assert response.status_code == 200
    assert response.json() == []

def test_list_papers_with_data(client: TestClient, session: Session):
    # Seed DB
    paper = Paper(
        id="2001.00001",
        title="Test Paper",
        authors='["Author A"]',
        summary_generic="Abstract",
        published_at=datetime.now(),
        category_primary="cs.AI",
        pdf_url="http://example.com/pdf",
        updated_at=datetime.now(),
        status="NEW"
    )
    session.add(paper)
    session.commit()
    
    response = client.get("/papers")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "2001.00001"
    assert data[0]["title"] == "Test Paper"

def test_filter_papers(client: TestClient, session: Session):
    # Seed DB
    p1 = Paper(id="1", title="P1", authors="[]", summary_generic="", published_at=datetime.now(), category_primary="C", pdf_url="", updated_at=datetime.now(), status="NEW")
    p2 = Paper(id="2", title="P2", authors="[]", summary_generic="", published_at=datetime.now(), category_primary="C", pdf_url="", updated_at=datetime.now(), status="SCORED")
    session.add(p1)
    session.add(p2)
    session.commit()
    
    response = client.get("/papers?status=SCORED")
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "2"
    
def test_trigger_run(client: TestClient):
    # This just tests the endpoint kicks off a background task, 
    # consistent with FastAPI TestClient behavior for background tasks (they are executed synchronously usually in TestClient unless managed, 
    # but here we just check response message).
    # NOTE: Since we didn't mock the 'run_worker' logic, this might try to actually run it 
    # and fail if no dependencies (OpenAI key).
    # We should ideally mock 'src.main.run_worker'.
    from unittest.mock import patch
    
    with patch("src.main.run_worker") as mock_worker:
        response = client.post("/run")
        assert response.status_code == 200
        assert "background" in response.json()["message"]
        # In TestClient, background tasks are just added, we can check they were added if we inspect 'background_tasks' 
        # but mocking the function ensures it doesn't actually crash.
