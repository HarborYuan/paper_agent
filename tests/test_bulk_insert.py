from datetime import datetime

from src.models import Paper


def _payload(pid):
    return {
        "id": pid,
        "title": "Test Title",
        "authors": ["A. Author"],
        "abstract": "abstract",
        "published_at": "2026-03-01T12:00:00",
        "category_primary": "cs.CV",
        "all_categories": ["cs.CV", "cs.CL"],
        "pdf_url": f"https://arxiv.org/pdf/{pid}",
    }


def test_bulk_insert_inserts_as_new_and_skips_existing(client, session):
    session.add(Paper(
        id="2603.00001", title="existing", authors="[]", summary_generic="",
        published_at=datetime(2026, 3, 1), category_primary="cs.CV",
        all_categories='["cs.CV"]', pdf_url="", status="PUSHED",
    ))
    session.commit()

    resp = client.post("/api/papers/bulk-insert", json={
        "papers": [_payload("2603.00001"), _payload("2603.00002v3")],
    })
    assert resp.status_code == 200
    assert resp.json() == {"inserted": 1, "skipped": 1}

    # version suffix stripped, inserted as NEW
    added = session.get(Paper, "2603.00002")
    assert added is not None
    assert added.status == "NEW"
    assert added.category_primary == "cs.CV"

    # existing paper untouched
    assert session.get(Paper, "2603.00001").status == "PUSHED"


def test_bulk_insert_dedupes_within_request(client, session):
    resp = client.post("/api/papers/bulk-insert", json={
        "papers": [_payload("2603.00003"), _payload("2603.00003")],
    })
    assert resp.status_code == 200
    assert resp.json() == {"inserted": 1, "skipped": 1}


def test_bulk_insert_rejects_oversized_batch(client):
    resp = client.post("/api/papers/bulk-insert", json={
        "papers": [_payload(f"2603.{10000 + i}") for i in range(1001)],
    })
    assert resp.status_code == 400
