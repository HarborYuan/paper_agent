"""Agent-facing endpoints: recent papers, fuzzy author lookup, bulk author update."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlmodel import Session

from src.models import Paper, Author
from src.services import author_index as ai


def test_normalize_and_keys():
    assert ai.normalize_name("Xiaoming Wang") == "xiaoming wang"
    assert ai.normalize_name("Wang, Xiaoming") == "xiaoming wang"
    assert ai.normalize_name("Jean-Pierre  Müller") == "jean pierre muller"
    assert ai.normalize_name("X. Wang") == "x wang"
    assert ai.sorted_key("xiaoming wang") == "wang xiaoming"
    assert ai.initials_key("xiaoming wang") == "x wang" and ai.initials_key("x wang") == "x wang"
    assert ai.initials_key("prince") == "prince"


def _seed(session, now=None):
    now = now or datetime.now()
    rows = [
        ("a1", '["Xiaoming Wang", "Jane Doe"]', 90, 1),
        ("a2", '["Wang Xiaoming", "Someone Else"]', 70, 3),
        ("a3", '["X. Wang", "Another Person"]', 88, 5),
        ("a4", '["Xin Wang", "Third Person"]', 60, 2),
        ("a5", '["Declan P. O\'Regan"]', 86, 40),
    ]
    for pid, authors, score, days_ago in rows:
        session.add(Paper(id=pid, title=f"Paper {pid}", authors=authors, summary_generic="s", published_at=now - timedelta(days=days_ago),
                          category_primary="cs.CV", all_categories="[]", pdf_url="", score=score, status="PUSHED"))
    session.commit()


@pytest.fixture
def seeded(session):
    _seed(session)
    # make the index read from the test engine
    eng = session.get_bind()
    with patch("src.services.author_index.engine", eng):
        ai.author_index.counts.clear(); ai.author_index.built_at = 0.0
        yield session
    ai.author_index.counts.clear(); ai.author_index.built_at = 0.0


def test_resolve_levels(seeded):
    assert ai.author_index.resolve("xiaoming wang") == (["Xiaoming Wang"], "exact")          # case folded
    assert ai.author_index.resolve("Wang, Xiaoming") == (["Xiaoming Wang"], "exact")         # Last, First
    v, kind = ai.author_index.resolve("Xiaoming Wang")                                     # exact beats token-order variant
    assert v == ["Xiaoming Wang"] and kind == "exact"
    v, kind = ai.author_index.resolve("wang xiaoming")
    assert kind == "exact" and v == ["Wang Xiaoming"]                                       # that exact string exists too
    v, kind = ai.author_index.resolve("X. Wang")
    assert kind == "exact" and v == ["X. Wang"]
    v, kind = ai.author_index.resolve("Xiaoyu Wang")                 # unknown full name -> only abbreviated variants
    assert kind == "initials" and v == ["X. Wang"]
    v, kind = ai.author_index.resolve("X.-M. Wang")                  # abbreviated query not stored verbatim -> all candidates, ambiguous
    assert kind == "initials" and set(v) == {"Xiaoming Wang", "X. Wang", "Xin Wang"}
    assert ai.author_index.resolve("Xeno Wang") == (["X. Wang"], "initials")
    assert ai.author_index.resolve("Nobody Here") == ([], "none")
    assert ai.author_index.resolve("Declan O'Regan") == ([], "none") or ai.author_index.resolve("Declan P. O'Regan")[1] == "exact"


def test_lookup_endpoint(client, seeded):
    r = client.post("/api/authors/lookup", json={"names": ["Xiaoming Wang", "Xiaoyu Wang", "Nobody"], "days": 30})
    assert r.status_code == 200, r.text
    res = {x["query"]: x for x in r.json()["results"]}
    xl = res["Xiaoming Wang"]
    assert xl["match_type"] == "exact" and [m["name"] for m in xl["matches"]] == ["Xiaoming Wang"]
    assert [p["id"] for p in xl["papers"]] == ["a1"] and "tldr" in xl["papers"][0]
    amb = res["Xiaoyu Wang"]
    assert amb["match_type"] == "initials" and amb["ambiguous"] is False           # single abbreviated variant "X. Wang"
    assert {p["id"] for p in amb["papers"]} == {"a3"}
    assert res["Nobody"]["matches"] == [] and res["Nobody"]["papers"] == []
    # abbreviated query -> ambiguous over all candidates; filters: min_score drops a4 (60)
    r = client.post("/api/authors/lookup", json={"names": ["X.-M. Wang"], "min_score": 85})
    amb = r.json()["results"][0]
    assert amb["ambiguous"] is True and {p["id"] for p in amb["papers"]} == {"a1", "a3"}
    # mark_important only for unambiguous matches
    r = client.post("/api/authors/lookup", json={"names": ["Xiaoming Wang", "X.-M. Wang"], "mark_important": True})
    res = {x["query"]: x for x in r.json()["results"]}
    assert res["Xiaoming Wang"]["is_important"] is True and res["X.-M. Wang"]["is_important"] is False
    # the ambiguous query still reports per-candidate flags (Xiaoming Wang was just flagged)
    assert {m["name"]: m["is_important"] for m in res["X.-M. Wang"]["matches"]}["Xiaoming Wang"] is True
    assert seeded.get(Author, "Xiaoming Wang").is_important is True
    assert seeded.get(Author, "Xin Wang") is None
    # validation
    assert client.post("/api/authors/lookup", json={"names": []}).status_code == 400


def test_bulk_and_reindex(client, seeded):
    r = client.post("/api/authors/bulk", json={"authors": [{"name": "Jane Doe", "is_important": True, "website": "https://example.org"},
                                                           {"name": "Someone Else", "bio": "x"}, {"name": "  "}]})
    assert r.status_code == 200 and r.json()["count"] == 2
    assert seeded.get(Author, "Jane Doe").is_important is True and seeded.get(Author, "Jane Doe").website == "https://example.org"
    assert seeded.get(Author, "Someone Else").bio == "x" and seeded.get(Author, "Someone Else").is_important is False
    assert client.post("/api/authors/reindex").json()["authors"] >= 7


def test_recent_papers(client, seeded):
    r = client.get("/api/papers/recent", params={"days": 7})
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert ids == ["a1", "a4", "a2", "a3"] and "a5" not in ids          # newest first, a5 is 40 days old
    r = client.get("/api/papers/recent", params={"days": 7, "min_score": 85})
    assert [p["id"] for p in r.json()] == ["a1", "a3"]
    r = client.get("/api/papers/recent", params={"days": 7, "status": "PUSHED,SUMMARIZED", "limit": 2})
    assert len(r.json()) == 2 and "tldr" in r.json()[0]
    r = client.get("/api/papers/recent", params={"days": 7, "compact": "false"})
    assert "summary_generic" in r.json()[0]
