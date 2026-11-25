"""An arXiv API outage must reach Lark instead of masquerading as a quiet day."""
import asyncio
from datetime import datetime

import pytest
from sqlmodel import SQLModel, Session, StaticPool, create_engine

import src.services.arxiv as arxiv
import src.services.notifier as notifier_mod
import src.worker as worker
from src.models import Paper
from src.services.arxiv import ArxivAPIError


# ---------------------------------------------------------------------------
# query_api: retries, error feeds, empty feeds
# ---------------------------------------------------------------------------
FEED_OK = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2609.00001v2</id>
    <published>2026-09-01T00:00:00Z</published><updated>2026-09-03T00:00:00Z</updated>
    <title>A  Paper</title><summary>abs</summary>
    <author><name>Ada Lovelace</name></author>
    <arxiv:comment>Accepted to CVPR 2026</arxiv:comment>
    <arxiv:primary_category term="cs.CV"/><category term="cs.CV"/>
  </entry>
</feed>"""
FEED_EMPTY = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>"""
FEED_ERROR = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/api/errors#incorrect_id_format_for_x</id><title>Error</title>
  <summary>incorrect id format for x</summary></entry></feed>"""


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


def _fake_client(responses, calls):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            calls.append(params)
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
    return _Client


def test_query_api_retries_then_succeeds(monkeypatch):
    calls = []
    monkeypatch.setattr(arxiv.httpx, "Client", _fake_client(
        [_Resp(503, "busy"), arxiv.httpx.ConnectError("boom"), _Resp(200, FEED_EMPTY), _Resp(200, FEED_OK)], calls))
    feed = arxiv.query_api({"search_query": "cat:cs.CV"}, retry_delays=(0, 0, 0))
    assert len(calls) == 4 and len(feed.entries) == 1


def test_query_api_raises_after_all_attempts(monkeypatch):
    monkeypatch.setattr(arxiv.httpx, "Client", _fake_client([_Resp(500, "x")] * 3, []))
    with pytest.raises(ArxivAPIError, match="HTTP 500"):
        arxiv.query_api({"search_query": "cat:cs.CV"}, retry_delays=(0, 0))


def test_query_api_error_entry_is_not_retried(monkeypatch):
    calls = []
    monkeypatch.setattr(arxiv.httpx, "Client", _fake_client([_Resp(200, FEED_ERROR)], calls))
    with pytest.raises(ArxivAPIError, match="incorrect id format"):
        arxiv.query_api({"id_list": "x"}, retry_delays=(0, 0))
    assert len(calls) == 1


def test_fetch_metadata_parses_comment(monkeypatch):
    monkeypatch.setattr(arxiv.httpx, "Client", _fake_client([_Resp(200, FEED_OK)], []))
    meta = arxiv.fetch_metadata(["2609.00001v1"], retry_delays=())
    m = meta["2609.00001"]
    assert m["title"] == "A Paper" and m["authors"] == ["Ada Lovelace"]
    assert m["comment"] == "Accepted to CVPR 2026" and m["updated"].day == 3


# ---------------------------------------------------------------------------
# run_worker: alert on outage, no "taking a break" message
# ---------------------------------------------------------------------------
class _FailingFetcher:
    def __init__(self, categories=None):
        pass

    def fetch_papers(self, max_results=0):
        raise ArxivAPIError("arXiv API failed after 4 attempts: HTTP 503")

    def filter_new_papers(self, papers):
        return []

    def save_papers(self, papers):
        pass


class _Notifier:
    def __init__(self):
        self.sent = []

    async def send_message(self, msg, title=None):
        self.sent.append((title, msg))
        return True

    async def send_messages(self, msgs):
        self.sent.extend(msgs)
        return True


def _engine_with(status=None):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    if status:
        with Session(engine) as s:
            s.add(Paper(id="2501.00001", title="T", authors='["A"]', summary_generic="a",
                        published_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
                        category_primary="cs.CV", all_categories='["cs.CV"]', pdf_url="", status=status))
            s.commit()
    return engine


def _patch(monkeypatch, engine, notifier):
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(worker, "ArxivFetcher", _FailingFetcher)
    monkeypatch.setattr(worker, "get_notifier", lambda: notifier)
    monkeypatch.setattr(notifier_mod, "get_notifier", lambda: notifier)
    monkeypatch.setattr(worker.settings, "HOT_ENABLED", False)

    async def _no_embed(*a, **kw):
        return 0
    monkeypatch.setattr(worker, "embed_new_papers", _no_embed)
    monkeypatch.setattr(worker.settings, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("src.database.engine", engine)


def test_outage_alerts_lark_instead_of_rest_day(monkeypatch):
    n = _Notifier()
    _patch(monkeypatch, _engine_with("PUSHED"), n)
    asyncio.run(worker.run_worker())
    assert len(n.sent) == 1
    title, msg = n.sent[0]
    assert "arXiv API" in title and "HTTP 503" in msg
    assert "Taking a break" not in msg


def test_outage_still_processes_pending_papers(monkeypatch):
    n = _Notifier()
    _patch(monkeypatch, _engine_with("NEW"), n)
    scored = []

    async def _score(papers, log=None):
        scored.extend(p.id for p in papers)
        return {"reviewed": 0, "deep_read": 0}


    monkeypatch.setattr(worker, "score_papers", _score)
    asyncio.run(worker.run_worker())
    assert scored == ["2501.00001"]
    assert "arXiv API" in (n.sent[0][0] or "")


# ---------------------------------------------------------------------------
# fetch_papers: paging
# ---------------------------------------------------------------------------
def _feed(ids):
    entries = "".join(f"""<entry><id>http://arxiv.org/abs/{i}v1</id>
    <published>2026-11-24T00:00:00Z</published><updated>2026-11-24T00:00:00Z</updated>
    <title>P {i}</title><summary>abs</summary><author><name>Ada Lovelace</name></author>
    <arxiv:primary_category term="cs.CV"/><category term="cs.CV"/></entry>""" for i in ids)
    return ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
            f'xmlns:arxiv="http://arxiv.org/schemas/atom">{entries}</feed>')


def _fetcher(monkeypatch, responses, known=()):
    calls = []
    monkeypatch.setattr(arxiv.httpx, "Client", _fake_client(responses, calls))
    monkeypatch.setattr(arxiv.ArxivFetcher, "_known_ids", staticmethod(lambda ids: set(ids) & set(known)))
    return arxiv.ArxivFetcher(["cs.CV"]), calls


def test_fetch_pages_until_a_page_is_already_in_the_library(monkeypatch):
    pages = [["2611.00006", "2611.00005"], ["2611.00004", "2611.00003"], ["2611.00002", "2611.00001"]]
    f, calls = _fetcher(monkeypatch, [_Resp(200, _feed(p)) for p in pages],
                        known={"2611.00003", "2611.00002", "2611.00001"})
    got = f.fetch_papers(max_results=100, page_size=2, page_delay=0, retry_delays=())
    assert [c["start"] for c in calls] == [0, 2, 4]  # page 2 is partly new, page 3 fully known -> stop
    assert [p.id for p in got] == ["2611.00006", "2611.00005", "2611.00004", "2611.00003", "2611.00002", "2611.00001"]


def test_fetch_stops_at_end_of_listing_and_dedupes_shifted_entries(monkeypatch):
    f, calls = _fetcher(monkeypatch, [_Resp(200, _feed(["2611.00003", "2611.00002"])),
                                      _Resp(200, _feed(["2611.00002"]))])
    got = f.fetch_papers(max_results=100, page_size=2, page_delay=0, retry_delays=())
    assert len(calls) == 2 and [p.id for p in got] == ["2611.00003", "2611.00002"]


def test_later_page_failure_keeps_earlier_pages(monkeypatch):
    f, _ = _fetcher(monkeypatch, [_Resp(200, _feed(["2611.00004", "2611.00003"])), _Resp(429, "slow down")])
    with pytest.raises(ArxivAPIError) as ei:
        f.fetch_papers(max_results=100, page_size=2, page_delay=0, retry_delays=())
    assert "HTTP 429" in str(ei.value) and [p.id for p in ei.value.partial] == ["2611.00004", "2611.00003"]


def test_retry_waits_for_retry_after(monkeypatch):
    slept, calls = [], []
    resp = _Resp(429, "slow down")
    resp.headers = {"retry-after": "120"}
    monkeypatch.setattr(arxiv.httpx, "Client", _fake_client([resp, _Resp(200, FEED_OK)], calls))
    monkeypatch.setattr(arxiv.time, "sleep", slept.append)
    arxiv.query_api({"search_query": "cat:cs.CV"}, retry_delays=(10,))
    assert slept == [120]
