"""A fetch that finds nothing must still score papers already waiting as NEW.

Backfilled papers land in the DB directly, so run_worker's rest-day shortcut
would otherwise strand them: the daily fetch sees no new ids and returns before
the scoring step ever runs.
"""
import asyncio
from datetime import datetime

from sqlmodel import SQLModel, Session, StaticPool, create_engine

import src.worker as worker
from src.models import Paper


class _StubFetcher:
    def __init__(self, categories=None):
        pass

    def fetch_papers(self, max_results=0):
        return []

    def filter_new_papers(self, papers):
        return []

    def save_papers(self, papers):
        pass


class _StubLLM:
    class config:
        score_threshold = 85
        stage2_threshold = 60
        stage1_model = "stub-1"
        stage2_model = "stub-2"
        summary_model = "stub-s"


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _insert(engine, pid, status):
    with Session(engine) as session:
        session.add(Paper(
            id=pid,
            title="Test Paper",
            authors='["A. Author"]',
            summary_generic="abstract",
            published_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
            category_primary="cs.CV",
            all_categories='["cs.CV"]',
            pdf_url=f"https://arxiv.org/pdf/{pid}",
            status=status,
        ))
        session.commit()


def _base_patches(monkeypatch, engine, scored):
    async def _score(sem, llm, paper):
        scored.append(paper.id)

    async def _reports(*args, **kwargs):
        return []

    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(worker, "ArxivFetcher", _StubFetcher)
    monkeypatch.setattr(worker, "LLMService", _StubLLM)
    monkeypatch.setattr(worker, "process_paper_score", _score)
    monkeypatch.setattr(worker, "run_scheduled_reports", _reports)


def test_pending_new_is_scored_when_fetch_is_empty(monkeypatch):
    engine = _make_engine()
    _insert(engine, "2501.00001", "NEW")
    scored = []
    _base_patches(monkeypatch, engine, scored)
    monkeypatch.setattr(worker, "get_notifier", lambda: None)

    asyncio.run(worker.run_worker())

    assert scored == ["2501.00001"]


def test_rest_day_when_nothing_new_and_nothing_pending(monkeypatch):
    engine = _make_engine()
    _insert(engine, "2501.00002", "PUSHED")
    scored = []
    _base_patches(monkeypatch, engine, scored)

    sent = []

    class _Notifier:
        async def send_message(self, msg):
            sent.append(msg)
            return True

        async def send_messages(self, msgs):
            sent.extend(msgs)
            return True

    monkeypatch.setattr(worker, "get_notifier", lambda: _Notifier())

    asyncio.run(worker.run_worker())

    assert scored == []
    assert len(sent) == 1 and "No new papers" in sent[0]
