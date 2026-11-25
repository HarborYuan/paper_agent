import asyncio
from datetime import datetime

import pytest
from sqlmodel import SQLModel, Session, StaticPool, create_engine

import src.worker as worker
from src.models import Paper


class _RecordingNotifier:
    def __init__(self):
        self.sent = []

    async def send_message(self, msg):
        self.sent.append(msg)
        return True


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _insert_paper(engine, **overrides):
    fields = dict(
        id="2501.00001",
        title="Test Paper",
        authors='["A. Author"]',
        summary_generic="abstract",
        published_at=datetime(2026, 1, 1),
        category_primary="cs.CV",
        all_categories='["cs.CV"]',
        pdf_url="https://arxiv.org/pdf/2501.00001",
        updated_at=datetime(2026, 1, 1),
        status="SUMMARIZED",
        score=90,
        summary_personalized="summary",
    )
    fields.update(overrides)
    paper = Paper(**fields)
    with Session(engine) as session:
        session.add(paper)
        session.commit()
    return fields["id"]


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(worker.settings, "ANTHROPIC_API_KEY", "test-key")


def test_notify_false_skips_push(monkeypatch):
    engine = _make_engine()
    pid = _insert_paper(engine)
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(worker, "get_notifier", lambda: (_ for _ in ()).throw(AssertionError("notifier requested")))

    asyncio.run(worker.process_single_paper(pid, notify=False))

    with Session(engine) as session:
        assert session.get(Paper, pid).status == "SUMMARIZED"  # left for the batched digest


def test_notify_true_pushes(monkeypatch):
    engine = _make_engine()
    pid = _insert_paper(engine)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(worker, "get_notifier", lambda: notifier)

    asyncio.run(worker.process_single_paper(pid, notify=True))

    assert len(notifier.sent) == 1
    with Session(engine) as session:
        assert session.get(Paper, pid).status == "PUSHED"


def test_scored_paper_gets_its_deep_read(monkeypatch):
    """SCORED = reviewed as worth reading but not deep-read yet: a single-paper run finishes it."""
    from src.services import verdict_pipeline
    engine = _make_engine()
    pid = _insert_paper(engine, status="SCORED", summary_personalized=None)
    called = []

    async def _deep(papers, runner, log=None, batch=None, final=True):
        called.extend(p.id for p in papers)
        return {}
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(worker, "get_notifier", lambda: None)
    monkeypatch.setattr(verdict_pipeline, "deep_read", _deep)

    asyncio.run(worker.process_single_paper(pid, notify=False))

    assert called == [pid]


def test_no_key_does_nothing(monkeypatch):
    engine = _make_engine()
    pid = _insert_paper(engine, status="NEW")
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(worker.settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(worker, "get_notifier", lambda: (_ for _ in ()).throw(AssertionError("notifier requested")))
    asyncio.run(worker.process_single_paper(pid))
    with Session(engine) as session:
        assert session.get(Paper, pid).status == "NEW"
