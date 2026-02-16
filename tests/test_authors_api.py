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

def test_list_authors_with_days_filter(client: TestClient, session: Session):
    """Authors with only old papers should not appear when days filter is applied."""
    from datetime import timedelta
    now = datetime.now()
    
    # Recent paper (2 days ago)
    p1 = Paper(
        id="1", title="Recent", authors='["Author A"]',
        summary_generic="", published_at=now - timedelta(days=2),
        category_primary="cs.CV", all_categories='["cs.CV"]',
        pdf_url="", updated_at=now, status="NEW"
    )
    # Old paper (60 days ago)
    p2 = Paper(
        id="2", title="Old", authors='["Author B"]',
        summary_generic="", published_at=now - timedelta(days=60),
        category_primary="cs.AI", all_categories='["cs.AI"]',
        pdf_url="", updated_at=now, status="NEW"
    )
    session.add(p1)
    session.add(p2)
    session.commit()
    
    # Without filter: both authors
    response = client.get("/authors")
    assert len(response.json()) == 2
    
    # With 7-day filter: only Author A
    response = client.get("/authors?days=7")
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Author A"
    
    # With 90-day filter: both authors
    response = client.get("/authors?days=90")
    assert len(response.json()) == 2

def test_list_papers_by_author_with_days_filter(client: TestClient, session: Session):
    """Papers outside the time window should be excluded."""
    from datetime import timedelta
    now = datetime.now()
    
    p1 = Paper(
        id="1", title="Recent Paper", authors='["Author A"]',
        summary_generic="", published_at=now - timedelta(days=5),
        category_primary="cs.CV", all_categories='["cs.CV"]',
        pdf_url="", updated_at=now, status="NEW"
    )
    p2 = Paper(
        id="2", title="Old Paper", authors='["Author A"]',
        summary_generic="", published_at=now - timedelta(days=45),
        category_primary="cs.AI", all_categories='["cs.AI"]',
        pdf_url="", updated_at=now, status="NEW"
    )
    session.add(p1)
    session.add(p2)
    session.commit()
    
    # Without filter: both papers
    response = client.get("/authors/Author%20A/papers")
    assert len(response.json()) == 2
    
    # 7 days: only recent
    response = client.get("/authors/Author%20A/papers?days=7")
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "1"
    
    # 30 days: only recent
    response = client.get("/authors/Author%20A/papers?days=30")
    assert len(response.json()) == 1
    
    # 90 days: both
    response = client.get("/authors/Author%20A/papers?days=90")
    assert len(response.json()) == 2
