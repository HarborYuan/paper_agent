from fastapi.testclient import TestClient
from sqlmodel import Session
from src.models import Paper
from datetime import datetime

def test_read_main(client: TestClient):
    # root liveness probe and the /api alias both work
    for path in ("/health", "/api/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert "message" in response.json()

def test_list_papers_empty(client: TestClient):
    response = client.get("/api/papers")
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
        all_categories='["cs.AI"]',
        pdf_url="http://example.com/pdf",
        updated_at=datetime.now(),
        status="NEW"
    )
    session.add(paper)
    session.commit()
    
    response = client.get("/api/papers")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "2001.00001"
    assert data[0]["title"] == "Test Paper"

def test_filter_papers(client: TestClient, session: Session):
    # Seed DB
    p1 = Paper(id="1", title="P1", authors="[]", summary_generic="", published_at=datetime.now(), category_primary="C", all_categories="[]", pdf_url="", updated_at=datetime.now(), status="NEW")
    p2 = Paper(id="2", title="P2", authors="[]", summary_generic="", published_at=datetime.now(), category_primary="C", all_categories="[]", pdf_url="", updated_at=datetime.now(), status="SCORED")
    session.add(p1)
    session.add(p2)
    session.commit()
    
    response = client.get("/api/papers?status=SCORED")
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
        response = client.post("/api/run")
        assert response.status_code == 200
        assert "background" in response.json()["message"]
        # In TestClient, background tasks are just added, we can check they were added if we inspect 'background_tasks' 
        # but mocking the function ensures it doesn't actually crash.


def test_mark_pushed_by_date(client: TestClient, session: Session):
    def add(pid, day, status):
        session.add(Paper(id=pid, title=pid, authors="[]", summary_generic="", published_at=datetime(2026, 11, day, 20),
                          category_primary="C", all_categories="[]", pdf_url="", updated_at=datetime.now(), status=status))
    add("a", 10, "SUMMARIZED"); add("b", 23, "SUMMARIZED"); add("c", 24, "SUMMARIZED"); add("d", 12, "SCORED")
    session.commit()
    r = client.post("/api/papers/mark-pushed", params={"start": "2026-11-10", "end": "2026-11-23"})
    assert r.status_code == 200 and r.json() == {"marked": 2}
    session.expire_all()
    assert [session.get(Paper, x).status for x in "abcd"] == ["PUSHED", "PUSHED", "SUMMARIZED", "SCORED"]
    assert client.post("/api/papers/mark-pushed", params={"start": "11/10", "end": "x"}).status_code == 400
