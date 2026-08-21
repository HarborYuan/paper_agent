"""
Reports: period computation, statistics, prompt building, generation with a mocked LLM,
Lark rendering, scheduled-run logic, and the HTTP endpoints.
"""
import json
import asyncio
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from src.models import Paper, Report, Author, LLMUsage
from src.services import report_service as rs
from src.services.settings_service import LLMConfig


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
def test_period_for():
    d = date(2026, 8, 24)  # a Monday
    s, e, label = rs.period_for("daily", d)
    assert (s.date(), e.date(), label) == (d, d + timedelta(days=1), "2026-08-24")
    s, e, label = rs.period_for("weekly", d)
    assert (s.date(), e.date()) == (date(2026, 8, 17), d) and label == "2026-08-17 – 2026-08-23"
    s, e, label = rs.period_for("monthly", date(2026, 9, 1))       # 1st -> previous month
    assert (s, e, label) == (datetime(2026, 8, 1), datetime(2026, 9, 1), "2026-08")
    s, e, label = rs.period_for("monthly", date(2026, 8, 21))      # mid-month -> that month
    assert (s, e, label) == (datetime(2026, 8, 1), datetime(2026, 9, 1), "2026-08")
    s, e, label = rs.period_for("monthly", date(2026, 1, 1))       # year boundary
    assert (s, e, label) == (datetime(2025, 12, 1), datetime(2026, 1, 1), "2025-12")
    with pytest.raises(ValueError):
        rs.period_for("yearly", d)


# ---------------------------------------------------------------------------
# Fixtures: in-memory DB wired into report_service + a seeded week of papers
# ---------------------------------------------------------------------------
def _paper(pid, title, published, score, company=None, univ=None, aff=None, authors=("Alice Liang", "Bob Chen"), stage1=None, summary=None):
    return Paper(id=pid, title=title, authors=json.dumps(list(authors)), summary_generic="abs",
                 published_at=published, category_primary="cs.CV", all_categories='["cs.CV"]',
                 pdf_url="http://x", score=score, score_stage1=stage1 if stage1 is not None else score,
                 main_company=company, main_university=univ, main_affiliation=aff or company or univ,
                 status="PUSHED" if score >= 85 else "FILTERED", created_at=published,
                 score_reason=json.dumps({"stage2": {"one_line_reason": f"why {pid}"}}),
                 summary_personalized=summary)


@pytest.fixture
def rdb():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with patch("src.services.report_service.engine", engine):
        with Session(engine) as s:
            base = datetime(2026, 8, 18)  # week of Aug 18-24
            s.add(_paper("2608.00001", "Video Tokenizer X", base + timedelta(days=0), 92, company="ByteDance", summary="## Problem\nTL;DR one"))
            s.add(_paper("2608.00002", "Long Video Gen Y", base + timedelta(days=1), 88, company="Google", univ="MIT"))
            s.add(_paper("2608.00003", "Agent Z", base + timedelta(days=2), 86, company="ByteDance", authors=("Alice Liang", "Carol Wu")))
            s.add(_paper("2608.00004", "Filtered paper", base + timedelta(days=2), 40))
            # previous week: one selected from Google
            s.add(_paper("2608.00009", "Old one", base - timedelta(days=3), 90, company="Google"))
            s.add(Author(name="Alice Liang", is_important=True))
            s.add(LLMUsage(task="score_stage1", model="m", prompt_tokens=1, completion_tokens=1, total_tokens=2, cost=0.5,
                           created_at=base + timedelta(days=1)))
            s.commit()
        yield engine


def test_compute_stats(rdb):
    start, end, _ = rs.period_for("weekly", date(2026, 8, 25))
    with Session(rdb) as s:
        stats, papers = rs.compute_stats(s, "weekly", start, end)
    assert [p.id for p in papers] == ["2608.00001", "2608.00002", "2608.00003"]   # score desc, filtered excluded
    assert stats["selected"] == 3 and stats["fetched"] == 4 and stats["stage2_reviewed"] == 3
    assert stats["avg_score"] == pytest.approx(88.7, abs=0.05)
    comp = {c["name"]: c for c in stats["companies"]}
    assert comp["ByteDance"]["count"] == 2 and comp["ByteDance"]["prev"] == 0
    assert comp["Google"]["count"] == 1 and comp["Google"]["prev"] == 1
    assert stats["prev"]["selected"] == 1
    assert stats["important_authors_seen"] == ["Alice Liang"]
    assert stats["top_authors"][0] == {"name": "Alice Liang", "count": 3}
    assert stats["llm_cost_usd"] == 0.5
    assert stats["score_buckets"] == {"85-89": 2, "90-94": 1, "95-100": 0, "other": 0}


def test_compute_stats_with_explicit_ids(rdb):
    start, end, _ = rs.period_for("daily", date(2026, 8, 21))
    with Session(rdb) as s:
        stats, papers = rs.compute_stats(s, "daily", start, end, paper_ids=["2608.00003", "2608.00001"])
    assert [p.id for p in papers] == ["2608.00001", "2608.00003"]
    assert stats["selected"] == 2


def test_build_prompt_mentions_papers_and_stats(rdb):
    start, end, label = rs.period_for("weekly", date(2026, 8, 25))
    with Session(rdb) as s:
        stats, papers = rs.compute_stats(s, "weekly", start, end)
    prompt = rs.build_prompt("weekly", label, stats, papers)
    assert "[2608.00001] Video Tokenizer X" in prompt and "why 2608.00001" in prompt and "TL;DR one" in prompt
    assert '"ByteDance"' in prompt and "## Topic Trends" in prompt and "Must-Read Top 5" in prompt
    assert "400–600 words" in prompt


def test_markdown_to_lark_text():
    md = "## Overview\nSome **bold** and *em* and `code`.\n\n\n- item [2608.00001] T\n### Sub"
    txt = rs.markdown_to_lark_text(md)
    assert txt.startswith("【Overview】\nSome bold and em and code.")
    assert "- item [2608.00001] T\n【Sub】" in txt
    assert "\n\n\n" not in txt


def _fake_llm(content="## Overview\nGenerated.\n## Must-Read Top 5\n1. [2608.00001] Video Tokenizer X — because"):
    llm = AsyncMock()
    llm.config = LLMConfig("c", "s", "m", 60, 85, report_model="rep/model")
    llm.generate_report.return_value = "```markdown\n" + content + "\n```"
    return llm


def test_generate_report_stores_and_replaces(rdb):
    llm = _fake_llm()
    rep = asyncio.run(rs.generate_report("weekly", date(2026, 8, 25), llm=llm))
    assert rep is not None and rep.kind == "weekly" and rep.period_label == "2026-08-18 – 2026-08-24"
    assert rep.content.startswith("## Overview")            # code fence stripped
    assert rep.paper_count == 3 and json.loads(rep.paper_ids) == ["2608.00001", "2608.00002", "2608.00003"]
    assert rep.model == "rep/model" and rep.title.startswith("📊 Weekly Report · 2026-08-18")
    assert json.loads(rep.stats)["selected"] == 3
    prompt_sent = llm.generate_report.call_args.args[0]
    assert "[2608.00002] Long Video Gen Y" in prompt_sent
    # regenerate -> same row updated, not duplicated
    rep2 = asyncio.run(rs.generate_report("weekly", date(2026, 8, 25), llm=_fake_llm("## Overview\nv2")))
    assert rep2.id == rep.id and rep2.content == "## Overview\nv2"
    with Session(rdb) as s:
        assert len(s.exec(select(Report)).all()) == 1
    # replace=False returns the existing one without calling the LLM
    llm3 = _fake_llm()
    rep3 = asyncio.run(rs.generate_report("weekly", date(2026, 8, 25), llm=llm3, replace=False))
    assert rep3.id == rep.id and llm3.generate_report.call_count == 0


def test_generate_report_empty_period_returns_none(rdb):
    llm = _fake_llm()
    assert asyncio.run(rs.generate_report("weekly", date(2026, 1, 5), llm=llm)) is None
    llm.generate_report.assert_not_called()


def test_daily_report_unions_ids_on_second_run(rdb):
    llm = _fake_llm()
    r1 = asyncio.run(rs.generate_report("daily", date(2026, 8, 21), paper_ids=["2608.00001"], llm=llm))
    assert r1.paper_count == 1
    r2 = asyncio.run(rs.generate_report("daily", date(2026, 8, 21), paper_ids=["2608.00003"], llm=llm))
    assert r2.id == r1.id and set(json.loads(r2.paper_ids)) == {"2608.00001", "2608.00003"}


def test_run_scheduled_reports_respects_settings(rdb, monkeypatch):
    from src.config import settings as app_settings
    monkeypatch.setattr(app_settings, "REPORT_DAILY_ENABLED", True)
    monkeypatch.setattr(app_settings, "REPORT_WEEKLY_ENABLED", True)
    monkeypatch.setattr(app_settings, "REPORT_MONTHLY_ENABLED", True)
    monkeypatch.setattr(app_settings, "REPORT_WEEKLY_DAY", 1)   # Tuesday
    llm = _fake_llm()
    # Tue Aug 25 with pushed papers -> daily + weekly (Aug 18-24 has 3 selected papers)
    out = asyncio.run(rs.run_scheduled_reports(date(2026, 8, 25), ["2608.00001"], llm=llm))
    assert [r.kind for r in out] == ["daily", "weekly"]
    # Tue Sep 1, rest day (no pushed papers): monthly (August) is due; weekly Aug 25-31 has no papers -> skipped
    out = asyncio.run(rs.run_scheduled_reports(date(2026, 9, 1), None, llm=llm))
    assert [r.kind for r in out] == ["monthly"]
    # same day again -> monthly already exists -> nothing
    out = asyncio.run(rs.run_scheduled_reports(date(2026, 9, 1), None, llm=llm))
    assert out == []
    # disabled -> nothing even with papers
    monkeypatch.setattr(app_settings, "REPORT_DAILY_ENABLED", False)
    out = asyncio.run(rs.run_scheduled_reports(date(2026, 8, 26), ["2608.00001"], llm=llm))
    assert out == []


def test_report_to_lark_and_mark_pushed(rdb):
    rep = asyncio.run(rs.generate_report("weekly", date(2026, 8, 25), llm=_fake_llm()))
    title, text = rs.report_to_lark(rep)
    assert title == rep.title and text.startswith("【Overview】") and "3 papers · rep/model" in text
    rs.mark_pushed(rep.id)
    with Session(rdb) as s:
        r = s.get(Report, rep.id)
        assert r.pushed is True and r.pushed_at is not None


# ---------------------------------------------------------------------------
# Endpoints (client fixture uses its own in-memory session; generation is mocked)
# ---------------------------------------------------------------------------
def test_report_endpoints(client, session):
    now = datetime(2026, 8, 21)
    session.add(Report(kind="daily", period_start=now, period_end=now + timedelta(days=1), period_label="2026-08-21",
                       title="📰 Daily Report · 2026-08-21", content="## Today at a Glance\nx", paper_count=2, model="m"))
    session.add(Report(kind="weekly", period_start=now - timedelta(days=7), period_end=now, period_label="w",
                       title="📊 Weekly Report · w", content="## Overview\ny", paper_count=5, model="m"))
    session.commit()
    r = client.get("/api/reports")
    assert r.status_code == 200 and [x["kind"] for x in r.json()] == ["daily", "weekly"]
    r = client.get("/api/reports", params={"kind": "weekly"})
    assert [x["kind"] for x in r.json()] == ["weekly"]
    rid = client.get("/api/reports").json()[0]["id"]
    assert client.get(f"/api/reports/{rid}").json()["title"].startswith("📰")
    assert client.get("/api/reports/9999").status_code == 404

    # generate: invalid kind / date
    assert client.post("/api/reports/generate", json={"kind": "yearly"}).status_code == 400
    assert client.post("/api/reports/generate", json={"kind": "daily", "date": "2026/08/21"}).status_code == 400
    # generate: mocked service
    fake = Report(id=123, kind="weekly", period_start=now, period_end=now, period_label="w2", title="t", content="c", paper_count=1)
    with patch("src.main.generate_report", AsyncMock(return_value=fake)) as gen:
        r = client.post("/api/reports/generate", json={"kind": "weekly", "date": "2026-08-25"})
        assert r.status_code == 200 and r.json()["period_label"] == "w2"
        gen.assert_awaited_once()
        # rate limited on immediate retry
        assert client.post("/api/reports/generate", json={"kind": "weekly", "date": "2026-08-25"}).status_code == 429
    with patch("src.main.generate_report", AsyncMock(return_value=None)):
        assert client.post("/api/reports/generate", json={"kind": "monthly", "date": "2020-01-01"}).status_code == 404

    # push: no notifier configured -> 400
    with patch("src.main.get_notifier", return_value=None):
        assert client.post(f"/api/reports/{rid}/push").status_code == 400
    # push: notifier ok -> pushed flag set
    notifier = AsyncMock(); notifier.send_messages.return_value = True
    with patch("src.main.get_notifier", return_value=notifier), patch("src.main.mark_pushed") as mp:
        r = client.post(f"/api/reports/{rid}/push")
        assert r.status_code == 200
        sent = notifier.send_messages.call_args.args[0]
        assert sent[0][0].startswith("📰") and "【Today at a Glance】" in sent[0][1]
        mp.assert_called_once_with(rid)

    # delete
    assert client.delete(f"/api/reports/{rid}").json() == {"deleted": rid}
    assert client.get(f"/api/reports/{rid}").status_code == 404
