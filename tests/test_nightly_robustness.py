"""The nightly run must keep going, tell the user what it could not do, and never lose or repeat a push."""
import json
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlmodel import Session, SQLModel, StaticPool, create_engine, select

import src.worker as worker
from src.models import Paper, PaperReading
from src.services import claude_runner, notifier as notifier_mod, project_service, verdict_pipeline
from src.services.claude_runner import ClaudeRequest, ClaudeRunner


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    for mod in (worker, verdict_pipeline, project_service):
        monkeypatch.setattr(mod, "engine", eng)
    monkeypatch.setattr("src.database.engine", eng)
    monkeypatch.setattr(worker.settings, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(worker.settings, "HOT_ENABLED", False)
    monkeypatch.setattr(worker.settings, "PUBLIC_BASE_URL", "http://agent.local")

    class _Fetcher:
        def __init__(self, categories=None):
            pass

        def fetch_papers(self, max_results=0):
            return []

        def filter_new_papers(self, papers):
            return []

        def save_papers(self, papers):
            pass

    async def _no_embed(*a, **kw):
        return 0
    monkeypatch.setattr(worker, "ArxivFetcher", _Fetcher)
    monkeypatch.setattr(worker, "embed_new_papers", _no_embed)
    return eng


def _add(eng, pid, status, reason=None, title=None, score=90):
    with Session(eng) as s:
        s.add(Paper(id=pid, title=title or f"Paper {pid}", authors='["A. Author"]', summary_generic="abstract",
                    published_at=datetime(2026, 11, 20), category_primary="cs.CV", all_categories='["cs.CV"]',
                    pdf_url=f"https://arxiv.org/pdf/{pid}", status=status, score=score,
                    score_reason=json.dumps(reason) if reason else None, summary_personalized="## TL;DR\nShort."))
        s.commit()


class _Notifier:
    def __init__(self, fail_if=None):
        self.sent, self.fail_if = [], fail_if

    async def send_message(self, msg, title=None):
        self.sent.append((title, msg))
        return not (self.fail_if and self.fail_if in msg)


def _statuses(eng):
    with Session(eng) as s:
        return {p.id: p.status for p in s.exec(select(Paper)).all()}


async def _no_score(papers, log=None):
    return {"reviewed": 0, "deep_read": 0}


async def test_digest_is_chunked_and_marked_per_message(engine, monkeypatch):
    for i in range(23):
        _add(engine, f"2611.{i:05d}", "SUMMARIZED", score=99 - i)
    n = _Notifier(fail_if="part 2/3")
    monkeypatch.setattr(worker, "get_notifier", lambda: n)
    monkeypatch.setattr(worker, "score_papers", _no_score)
    await worker.run_worker()
    st = _statuses(engine)
    assert sum(v == "PUSHED" for v in st.values()) == 13    # parts 1 and 3
    assert [k for k, v in st.items() if v == "SUMMARIZED"] == [f"2611.{i:05d}" for i in range(10, 20)]
    assert all(msg.count("🔗") <= 10 for _, msg in n.sent)


async def test_crash_is_reported(engine, monkeypatch):
    _add(engine, "2611.00001", "NEW")

    async def boom(papers, log=None):
        raise RuntimeError("database is locked")
    n = _Notifier()
    monkeypatch.setattr(worker, "get_notifier", lambda: n)
    monkeypatch.setattr(worker, "score_papers", boom)
    await worker.run_worker()
    assert any(t and "run failed" in t and "database is locked" in m for t, m in n.sent)
    assert not verdict_pipeline.RUN_LOCK.locked()


async def test_leftover_deep_reads_run_on_a_quiet_day(engine, monkeypatch):
    _add(engine, "2611.00001", "SCORED", reason={"pipeline": "verdict"})
    called = []

    async def score(papers, log=None):
        called.append(len(papers))
        return {"reviewed": 0, "deep_read": 0}
    n = _Notifier()
    monkeypatch.setattr(worker, "get_notifier", lambda: n)
    monkeypatch.setattr(worker, "score_papers", score)
    await worker.run_worker()
    assert called == [0] and not any("Taking a break" in m for _, m in n.sent)


async def test_backlog_is_reported(engine, monkeypatch):
    v = {"pipeline": "verdict", "stage1": {"relevance": 5}, "stage2": {"verdict": "must_read"}}
    _add(engine, "2611.00001", "SCORED", reason={**v, "deep_failures": 1}, title="Flaky paper")
    _add(engine, "2611.00002", "SCORED", reason={**v, "deep_failures": 2}, title="Broken paper")
    _add(engine, "2611.00003", "SCORED", reason=v, title="Queued paper")
    _add(engine, "2611.00004", "NEW", reason={"pipeline": "verdict", "stage1": {"relevance": 5}})
    _add(engine, "2611.00005", "NEW")
    with Session(engine) as s:
        s.add(PaperReading(paper_id="2611.00001", status="ERROR", error="ReadTimeout: arxiv.org"))
        s.add(PaperReading(paper_id="2611.00002", status="ERROR", error="max_tokens", updated_at=datetime(2030, 1, 1)))
        s.commit()
    bl = verdict_pipeline.backlog()
    assert [x["id"] for x in bl["deep_retry"]] == ["2611.00001"]
    assert [x["id"] for x in bl["deep_gave_up"]] == ["2611.00002"]
    assert [x["id"] for x in bl["deep_waiting"]] == ["2611.00003"]
    assert [x["id"] for x in bl["review_pending"]] == ["2611.00004"] and bl["screen_pending"] == 1
    msg = worker.backlog_section(bl, since=datetime(2029, 1, 1))
    assert "Flaky paper" in msg and "ReadTimeout" in msg and "http://agent.local/paper/2611.00001" in msg
    assert "Broken paper" in msg and "1 waiting for a deep-read slot" in msg
    assert "1 waiting for a review" in msg and "1 not screened yet" in msg
    # a paper given up on an earlier night is only counted
    later = worker.backlog_section(bl, since=datetime(2031, 1, 1))
    assert "Broken paper" not in later and "1 given up earlier" in later


def test_restart_marks_running_readings_failed(engine):
    with Session(engine) as s:
        s.add(PaperReading(paper_id="2611.00001", status="RUNNING"))
        s.add(PaperReading(paper_id="2611.00002", status="DONE"))
        s.commit()
    assert verdict_pipeline.reset_interrupted() == 1
    assert verdict_pipeline.get_reading("2611.00001")["status"] == "ERROR"
    assert verdict_pipeline.get_reading("2611.00002")["status"] == "DONE"


async def test_lark_error_code_is_a_failure(monkeypatch):
    calls = []

    async def post(self, url, json=None, **kw):
        calls.append(json)
        return httpx.Response(200, json={"code": 9499, "msg": "Bad Request"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    lark = notifier_mod.LarkNotifier("http://lark.local/hook")
    lark.RETRY_DELAYS = (0, 0)
    assert await lark.send_message("hello") is False
    assert len(calls) == 3

    async def ok(self, url, json=None, **kw):
        return httpx.Response(200, json={"code": 0, "msg": "success"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx.AsyncClient, "post", ok)
    assert await lark.send_message("hello") is True


async def test_batch_polling_survives_a_network_blip(engine):
    created = []

    class _Batches:
        polls = 0

        async def create(self, requests):
            created.append(len(requests))
            self.reqs = requests
            return SimpleNamespace(id="b1", processing_status="in_progress")

        async def retrieve(self, bid):
            self.polls += 1
            if self.polls == 1:
                raise httpx.ConnectError("connection reset")
            return SimpleNamespace(id=bid, processing_status="ended")

        async def results(self, bid):
            async def gen():
                for r in self.reqs:
                    msg = SimpleNamespace(content=[SimpleNamespace(type="text", text='{"ok": 1}')],
                                          stop_reason="end_turn", usage=None)
                    yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(type="succeeded", message=msg))
            return gen()

    def no_stream(**params):
        raise AssertionError("fell back to real time")
    client = SimpleNamespace(messages=SimpleNamespace(batches=_Batches(), stream=no_stream))
    res = await ClaudeRunner(client=client, use_batch=True, poll_seconds=0).run(
        [ClaudeRequest(key="a", task="t", model="claude-haiku-5-5", system="S", user="u", schema={"type": "object"})])
    assert res["a"].ok and res["a"].batch and created == [1]
