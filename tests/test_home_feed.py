"""Home page feed (one publication day per call, light card records) and author lists on the server pages."""
import json
import re
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from src.database import get_session
from src.main import app
from src.models import Paper, PaperReading
from src.services import reading_page
from src.services.paper_views import short_authors, short_authors_text

MANY = [f"Author{i:02d} Example" for i in range(1, 30)] + ["Zelda O'Final-Écrivain"]


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    from src.services import project_service, verdict_pipeline
    monkeypatch.setattr(project_service, "engine", engine)
    monkeypatch.setattr(verdict_pipeline, "engine", engine)
    with Session(engine) as s:
        app.dependency_overrides[get_session] = lambda: s
        yield TestClient(app), s
    app.dependency_overrides.clear()


def _add(s, pid, day, score, authors=("Ada Example",), verdict=None, hour=20):
    reason = json.dumps({"stage2": {"verdict": verdict, "one_line_reason": "why"}}) if verdict else None
    s.add(Paper(id=pid, title=f"Paper {pid}", authors=json.dumps(list(authors)), summary_generic="An abstract. " * 100,
                published_at=datetime(2026, 11, day, hour), category_primary="cs.CV", all_categories="['cs.CV', 'cs.AI']",
                pdf_url=f"https://arxiv.org/pdf/{pid}", full_text="Body text. " * 5000, score=score,
                score_reason=reason, summary_personalized="## TL;DR\nShort teaser.\n\n## Method\nLong.",
                status="SUMMARIZED" if verdict else "SCORED"))


def test_feed_returns_every_qualifying_paper_of_a_day_and_skips_empty_days(env):
    client, s = env
    for i in range(40):                                  # a busy day: 40 papers above the bar, none cut
        _add(s, f"24.{i:03d}", 24, 86 + i % 10, hour=10 + i % 12)
    for i in range(30):
        _add(s, f"24.l{i:03d}", 24, 40)                  # below the bar
    _add(s, "23.000", 23, 50)                           # a day with nothing above the bar: skipped
    _add(s, "20.000", 20, 90)
    _add(s, "19.000", 19, None)                          # unscored: only with min_score=0
    s.add(PaperReading(paper_id="24.000", status="DONE", notes=json.dumps(
        [{"ids": ["p1"], "flags": [{"kind": "questionable", "verified": True}, {"kind": "big_claim", "verified": False}]}])))
    s.commit()

    r = client.get("/api/papers/feed", params={"min_score": 85}).json()
    assert r["date"] == "2026-11-24" and r["total"] == 70 and r["next"] == "2026-11-20"
    assert len(r["papers"]) == 40
    scores = [p["score"] for p in r["papers"]]
    assert scores == sorted(scores, reverse=True)
    card = next(p for p in r["papers"] if p["id"] == "24.000")
    assert "full_text" not in card and "score_reason" not in card
    assert card["tldr"] == "Short teaser." and len(card["abstract"]) <= 601
    assert card["all_categories"] == ["cs.CV", "cs.AI"]
    assert card["reading"] == {"status": "DONE", "flags": {"q": 1, "b": 0}}

    r = client.get("/api/papers/feed", params={"min_score": 85, "before": r["next"]}).json()
    assert r["date"] == "2026-11-20" and [p["id"] for p in r["papers"]] == ["20.000"] and r["next"] is None

    r = client.get("/api/papers/feed", params={"min_score": 0, "before": "2026-11-19"}).json()
    assert [p["id"] for p in r["papers"]] == ["19.000"]
    assert client.get("/api/papers/feed", params={"min_score": 99, "before": "2026-11-01"}).json()["date"] is None
    assert client.get("/api/papers/feed", params={"before": "11/24"}).status_code == 400


def test_feed_payload_is_small(env):
    client, s = env
    for i in range(30):
        _add(s, f"24.{i:03d}", 24, 90)
    s.commit()
    full = client.get("/api/papers", params={"date": "2026-11-24"}).content
    light = client.get("/api/papers/feed", params={"min_score": 85}).content
    assert len(light) * 20 < len(full)


def test_title_search_card_view(env):
    client, s = env
    _add(s, "24.001", 24, 90)
    s.commit()
    rows = client.get("/api/papers/search", params={"q": "Paper", "view": "card"}).json()
    assert rows[0]["id"] == "24.001" and "full_text" not in rows[0]
    assert "full_text" in client.get("/api/papers/search", params={"q": "Paper"}).json()[0]


def test_short_authors_keeps_the_last_author():
    assert short_authors(["A", "B", "C"]) == (["A", "B", "C"], 0, None)
    shown, hidden, last = short_authors(MANY)
    assert shown == MANY[:4] and hidden == len(MANY) - 5 and last == MANY[-1]
    assert short_authors_text(MANY, head=3, max_full=4).endswith(f"… (+{len(MANY) - 4}), {MANY[-1]}")


def test_reading_page_lists_and_links_every_author(env):
    _, s = env
    _add(s, "24.001", 24, 90, authors=MANY, verdict="must_read")
    s.commit()
    html = reading_page.render(s.get(Paper, "24.001"), None)
    hrefs = re.findall(r"<a class='au' href='([^']+)'>", html)
    assert len(hrefs) == len(MANY)
    assert hrefs[-1] == "/author/Zelda%20O%27Final-%C3%89crivain"
    assert "more</span>" not in html


def test_picks_card_keeps_last_author_and_never_nests_links(env):
    client, s = env
    _add(s, "24.001", 24, 90, authors=MANY, verdict="must_read")
    s.commit()
    html = client.get("/picks").text
    card = html[html.index("<article class=\"pick\">"):html.index("</article>")]
    assert "/author/Author01%20Example" in card and "/author/Zelda%20O%27Final-%C3%89crivain" in card
    assert "/author/Author05%20Example" not in card and f"… +{len(MANY) - 5}" in card
    assert "href=\"/read/24.001\"" in card
    # no <a> opened inside another <a>
    depth = 0
    for tag in re.findall(r"<(/?)a[\s>]", card):
        depth += -1 if tag else 1
        assert depth in (0, 1)
