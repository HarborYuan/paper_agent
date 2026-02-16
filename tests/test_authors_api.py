from fastapi.testclient import TestClient
from sqlmodel import Session
from src.models import Paper
from datetime import datetime

def test_list_authors(client: TestClient, session: Session):
    # Seed DB with papers
    p1 = Paper(
        id="1", title="P1", authors='["Author A", "Author B"]', 
        summary_generic="", published_at=datetime.now(), 
        category_primary="cs.CV", all_categories='["cs.CV"]', 
        pdf_url="", updated_at=datetime.now(), status="NEW"
    )
    p2 = Paper(
        id="2", title="P2", authors='["Author A", "Author C"]', 
        summary_generic="", published_at=datetime.now(), 
        category_primary="cs.AI", all_categories='["cs.AI"]', 
        pdf_url="", updated_at=datetime.now(), status="NEW"
    )
    session.add(p1)
    session.add(p2)
    session.commit()
    
    response = client.get("/authors")
    assert response.status_code == 200
    data = response.json()
    
    # Author A has 2 papers, B and C have 1 each
    assert len(data) == 3
    assert data[0]["name"] == "Author A"
    assert data[0]["count"] == 2
    
    names = [d["name"] for d in data]
    assert "Author B" in names
    assert "Author C" in names

def test_list_papers_by_author(client: TestClient, session: Session):
    # Seed DB
    p1 = Paper(
        id="1", title="P1", authors='["Author A"]', 
        summary_generic="", published_at=datetime.now(), 
        category_primary="cs.CV", all_categories='["cs.CV"]', 
        pdf_url="", updated_at=datetime.now(), status="NEW"
    )
    p2 = Paper(
        id="2", title="P2", authors='["Author B"]', 
        summary_generic="", published_at=datetime.now(), 
        category_primary="cs.AI", all_categories='["cs.AI"]', 
        pdf_url="", updated_at=datetime.now(), status="NEW"
    )
    session.add(p1)
    session.add(p2)
    session.commit()
    
    response = client.get("/authors/Author%20A/papers")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "1"
    
    response = client.get("/authors/Author%20C/papers")
    assert response.status_code == 200
    assert response.json() == []
