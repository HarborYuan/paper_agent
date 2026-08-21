"""
Embeddings: vector (de)serialisation, index search / neighbours, clustering, embed_papers with a
mocked provider, missing/backfill bookkeeping, report-cluster plumbing, and the HTTP endpoints.
"""
import json
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from src.models import Paper, PaperEmbedding, LLMUsage
from src.services import embedding_service as es


def _unit(v):
    v = np.asarray(v, dtype=np.float32); return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_bytes_roundtrip():
    v = [0.1, -2.5, 3.0]
    assert np.allclose(es.from_bytes(es.to_bytes(v)), np.asarray(v, dtype=np.float32))


def test_index_search_and_neighbours():
    idx = es.EmbeddingIndex()
    idx.add(["a", "b", "c", "d"], np.stack([_unit([1, 0, 0]), _unit([0.9, 0.1, 0]), _unit([0, 1, 0]), _unit([0, 0, 1])]), "m")
    hits = idx.search(np.asarray([1, 0, 0], dtype=np.float32), k=2)
    assert [h[0] for h in hits] == ["a", "b"] and hits[0][1] == pytest.approx(1.0, abs=1e-5)
    hits = idx.search(np.asarray([1, 0, 0], dtype=np.float32), k=2, exclude={"a"})
    assert [h[0] for h in hits] == ["b", "c"]
    # update in place, add new, dimension mismatch -> empty
    idx.add(["a", "e"], np.stack([_unit([0, 0, 1]), _unit([0, 1, 1])]), "m")
    assert idx.size() == 5 and idx.search(np.asarray([0, 0, 1], dtype=np.float32), k=1)[0][0] in ("a", "d")
    assert idx.search(np.asarray([1, 0], dtype=np.float32), k=1) == []


@pytest.fixture
def edb(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    from src.config import settings as app_settings
    monkeypatch.setattr(app_settings, "EMBEDDING_MODEL", "test/embed")
    monkeypatch.setattr(app_settings, "EMBEDDING_DIM", 3)
    monkeypatch.setattr(app_settings, "OPENROUTER_API_KEY", "sk-or-test")
    fresh = es.EmbeddingIndex()
    with patch("src.services.embedding_service.engine", engine), patch.object(es, "index", fresh):
        with Session(engine) as s:
            base = datetime(2026, 8, 18)
            for i, (pid, title) in enumerate([("p1", "Video tokenizer"), ("p2", "Image tokenizer VQ"), ("p3", "Long video generation"),
                                              ("p4", "Streaming video diffusion"), ("p5", "Network intrusion detection")]):
                s.add(Paper(id=pid, title=title, authors="[]", summary_generic=f"abstract {i}", published_at=base + timedelta(days=i),
                            category_primary="cs.CV", all_categories="[]", pdf_url="", score=90, status="PUSHED"))
            s.commit()
        yield engine


FAKE_VECS = {"p1": [1, 0.1, 0], "p2": [0.9, 0.2, 0], "p3": [0, 1, 0.1], "p4": [0.1, 0.9, 0], "p5": [0, 0, 1]}


async def _fake_embed_texts(texts, **kw):
    # map by title keyword so tests are deterministic
    out = []
    for t in texts:
        key = next((k for k, title in [("p1", "Video tokenizer"), ("p2", "Image tokenizer VQ"), ("p3", "Long video generation"),
                                        ("p4", "Streaming video diffusion"), ("p5", "Network intrusion detection")] if t.startswith(title)), None)
        if key is None:   # a query
            out.append([1, 0, 0] if "tokenizer" in t else [0, 1, 0])
        else:
            out.append(FAKE_VECS[key])
    return out


def test_embed_papers_missing_backfill_and_search(edb):
    assert set(es.missing_paper_ids()) == {"p1", "p2", "p3", "p4", "p5"}
    with patch.object(es, "embed_texts", AsyncMock(side_effect=_fake_embed_texts)) as emb:
        n = asyncio.run(es.embed_new_papers(["p1", "p2", "p3"]))
        assert n == 3 and emb.await_count == 1
        assert set(es.missing_paper_ids()) == {"p4", "p5"}
        with Session(edb) as s:
            row = s.get(PaperEmbedding, "p1")
            assert row.model == "test/embed" and row.dim == 3 and np.allclose(es.from_bytes(row.vector), [1, 0.1, 0])
        # index was updated incrementally
        assert es.index.size() == 3
        # backfill the rest
        asyncio.run(es.backfill())
        assert es.missing_paper_ids() == [] and es.index.size() == 5 and es.status()["embedded"] == 5
        # semantic search embeds the query and ranks
        hits = asyncio.run(es.semantic_search("tokenizer", k=2))
        assert [h[0] for h in hits] == ["p1", "p2"]
        # related excludes self
        rel = es.related("p3", k=2)
        assert [r[0] for r in rel] == ["p4", "p1"] or [r[0] for r in rel][0] == "p4"
        # cluster: tokenizers vs video vs security
        clusters, missing = es.cluster(["p1", "p2", "p3", "p4", "p5"], k=3)
        assert missing == [] and len(clusters) == 3
        assert any(set(c) == {"p1", "p2"} for c in clusters) and any(set(c) == {"p3", "p4"} for c in clusters)
        # model switch -> everything stale, index reloads empty, status reports it
        from src.config import settings as app_settings
        app_settings.EMBEDDING_MODEL = "other/model"
        assert set(es.missing_paper_ids()) == {"p1", "p2", "p3", "p4", "p5"}
        st = es.status()
        assert st["embedded"] == 0 and st["stale_other_model"] == 5 and st["index_size"] == 0
        assert es.related("p1") is None


def test_embed_texts_records_usage_and_retries_without_dims(edb):
    calls = []
    class FakeResp:
        def __init__(self, code, payload): self.status_code = code; self._p = payload; self.text = json.dumps(payload)
        def json(self): return self._p
    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            calls.append(json)
            if "dimensions" in json:
                return FakeResp(400, {"error": {"message": "dimensions not supported"}})
            return FakeResp(200, {"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}],
                                  "usage": {"prompt_tokens": 12, "total_tokens": 12, "cost": 0.000001}})
    with patch("src.services.embedding_service.httpx.AsyncClient", FakeClient):
        vecs = asyncio.run(es.embed_texts(["a", "b"], ref="t"))
    assert vecs == [[1, 0], [0, 1]]            # re-ordered by index
    assert len(calls) == 2 and "dimensions" in calls[0] and "dimensions" not in calls[1]
    with Session(edb) as s:
        rows = s.exec(select(LLMUsage).where(LLMUsage.task == "embed")).all()
        assert len(rows) == 1 and rows[0].prompt_tokens == 12 and rows[0].cost == pytest.approx(0.000001) and rows[0].success


def test_report_prompt_includes_clusters(edb):
    from src.services import report_service as rs
    from datetime import date
    with patch("src.services.report_service.engine", edb), \
         patch.object(es, "embed_texts", AsyncMock(side_effect=_fake_embed_texts)):
        asyncio.run(es.backfill())
        start, end, label = rs.period_for("weekly", date(2026, 8, 25))
        with Session(edb) as s:
            stats, papers = rs.compute_stats(s, "weekly", start, end)
        assert stats["clusters"] and sum(len(c) for c in stats["clusters"]) == 5
        prompt = rs.build_prompt("weekly", label, stats, papers)
        assert "PRE-COMPUTED TOPIC CLUSTERS" in prompt and "[p1] Video tokenizer" in prompt
        assert '"clusters"' not in prompt   # raw id lists are not duplicated into the stats JSON


def test_retrieval_endpoints(client, session):
    now = datetime(2026, 8, 20)
    for pid, title in [("q1", "Alpha"), ("q2", "Beta"), ("q3", "Gamma")]:
        session.add(Paper(id=pid, title=title, authors="[]", summary_generic="s", published_at=now, category_primary="cs.CV",
                          all_categories="[]", pdf_url="", score=90, status="PUSHED", full_text="BIG TEXT"))
    session.commit()
    # semantic search: mocked service
    with patch("src.main.embedding_service.semantic_search", AsyncMock(return_value=[("q2", 0.91), ("q1", 0.5)])), \
         patch("src.main.embedding_service.index") as idx:
        idx.size.return_value = 3
        r = client.get("/api/papers/semantic-search", params={"q": "beta things"})
        assert r.status_code == 200
        res = r.json()["results"]
        assert [x["id"] for x in res] == ["q2", "q1"] and res[0]["similarity"] == 0.91 and "full_text" not in res[0]
        assert client.get("/api/papers/semantic-search", params={"q": "   "}).json()["results"] == []
    with patch("src.main.embedding_service.semantic_search", AsyncMock(side_effect=RuntimeError("boom"))):
        assert client.get("/api/papers/semantic-search", params={"q": "x"}).status_code == 502
    # related
    with patch("src.main.embedding_service.related", return_value=[("q3", 0.8)]):
        r = client.get("/api/papers/q1/related")
        assert r.json()["available"] is True and r.json()["results"][0]["id"] == "q3"
    with patch("src.main.embedding_service.related", return_value=None):
        assert client.get("/api/papers/q1/related").json()["available"] is False
    assert client.get("/api/papers/nope/related").status_code == 404
    # status / backfill / reload
    fake_status = {"model": "m", "dim": 3, "total_papers": 3, "embedded": 1, "missing": 2, "stale_other_model": 0,
                   "index_size": 1, "index_loaded_at": None, "backfill": {"running": False}, "key_configured": True}
    with patch("src.main.embedding_service.status", return_value=fake_status), \
         patch("src.main.embedding_service.backfill", AsyncMock()) as bf:
        assert client.get("/api/embeddings/status").json()["missing"] == 2
        r = client.post("/api/embeddings/backfill")
        assert r.status_code == 200 and "started" in r.json()["message"]
    with patch("src.main.embedding_service.index") as idx:
        idx.load.return_value = 7
        assert client.post("/api/embeddings/reload").json()["index_size"] == 7


# ---------------------------------------------------------------------------
# Filters, seeds, compact views
# ---------------------------------------------------------------------------
def test_index_search_with_allowed_mask():
    idx = es.EmbeddingIndex()
    idx.add(["a", "b", "c", "d"], np.stack([_unit([1, 0, 0]), _unit([0.9, 0.1, 0]), _unit([0.8, 0.2, 0]), _unit([0, 0, 1])]), "m")
    q = np.asarray([1, 0, 0], dtype=np.float32)
    assert [h[0] for h in idx.search(q, k=3)] == ["a", "b", "c"]
    assert [h[0] for h in idx.search(q, k=3, allowed={"c", "d"})] == ["c", "d"]
    assert [h[0] for h in idx.search(q, k=3, allowed={"c", "d"}, exclude={"c"})] == ["d"]
    assert idx.search(q, k=3, allowed=set()) == []


def test_seed_search_and_compact(edb):
    with patch.object(es, "embed_texts", AsyncMock(side_effect=_fake_embed_texts)) as emb:
        asyncio.run(es.backfill())
        emb.reset_mock()
        # seeds only: no embedding call, seeds excluded, neighbours of the "video" pair first
        hits = asyncio.run(es.semantic_search(seed_ids=["p3", "p4"], k=3))
        assert emb.await_count == 0
        assert [h[0] for h in hits][0] in ("p1", "p2") or "p3" not in [h[0] for h in hits]
        assert not ({"p3", "p4"} & {h[0] for h in hits})
        # query + allowed filter
        hits = asyncio.run(es.semantic_search("tokenizer", k=5, allowed={"p2", "p5"}))
        assert [h[0] for h in hits] == ["p2", "p5"]
        # seed vector of unknown id -> missing reported
        v, missing = es.seed_vector(["p1", "nope"])
        assert v is not None and missing == ["nope"]
    from src.services.paper_views import compact_paper
    with Session(edb) as s:
        p = s.get(Paper, "p1")
        p.summary_personalized = "## Problem\nSolves X.\n## Key Contributions\n- a\n- b"
        p.score_reason = json.dumps({"stage1": {"one_line_reason": "fits tokenizers"}, "stage2": {"one_line_reason": "strong fit"}})
        c = compact_paper(p, similarity=0.87654)
    assert c["id"] == "p1" and c["similarity"] == 0.8765 and c["reason"] == "strong fit"
    assert c["tldr"].startswith("Solves X.") and "##" not in c["tldr"] and c["has_summary"] is True
    assert c["abs_url"] == "https://arxiv.org/abs/p1" and "full_text" not in c and "summary_personalized" not in c


def test_semantic_search_post_and_compact_endpoints(client, session):
    now = datetime(2026, 8, 20)
    for pid, title, score, days_ago in [("s1", "Alpha tokenizer", 90, 1), ("s2", "Beta tokenizer", 70, 40), ("s3", "Gamma video", 88, 2)]:
        session.add(Paper(id=pid, title=title, authors='["Ann Lee"]', summary_generic="s", published_at=datetime.now() - timedelta(days=days_ago),
                          category_primary="cs.CV", all_categories="[]", pdf_url="", score=score, status="PUSHED", full_text="BIG"))
    session.commit()
    captured = {}
    async def fake_search(query=None, k=20, seed_ids=None, allowed=None, exclude=None):
        captured.update(query=query, k=k, seed_ids=seed_ids, allowed=allowed, exclude=exclude)
        cands = [("s1", 0.9), ("s2", 0.8), ("s3", 0.7)]
        return [c for c in cands if (allowed is None or c[0] in allowed) and c[0] not in (exclude or set())][:k]
    with patch("src.main.embedding_service.semantic_search", AsyncMock(side_effect=fake_search)), \
         patch("src.main.embedding_service.index") as idx:
        idx.size.return_value = 3
        # filters: last 7 days + min_score 85 -> only s1 and s3 are candidates
        r = client.post("/api/papers/semantic-search", json={"query": "tokenizer", "days": 7, "min_score": 85, "limit": 5})
        assert r.status_code == 200, r.text
        data = r.json()
        assert captured["allowed"] == {"s1", "s3"} and data["filters_matched"] == 2
        assert [x["id"] for x in data["results"]] == ["s1", "s3"]
        assert set(data["results"][0].keys()) >= {"id", "title", "authors", "score", "similarity", "reason", "tldr", "abs_url"}
        assert "full_text" not in data["results"][0] and data["results"][0]["authors"] == ["Ann Lee"]
        # seeds + exclude, no query
        r = client.post("/api/papers/semantic-search", json={"paper_ids": ["s1"], "exclude_ids": ["s2"], "compact": False})
        assert r.status_code == 200 and captured["seed_ids"] == ["s1"] and captured["exclude"] == {"s2"}
        assert "summary_generic" in r.json()["results"][0]   # non-compact record
        # neither query nor seeds -> 400 ; bad date -> 400 ; filters matching nothing -> empty, no search call
        assert client.post("/api/papers/semantic-search", json={}).status_code == 400
        assert client.post("/api/papers/semantic-search", json={"query": "x", "since": "2026/01/01"}).status_code == 400
        r = client.post("/api/papers/semantic-search", json={"query": "x", "category": "cs.NOPE"})
        assert r.status_code == 200 and r.json()["results"] == [] and r.json()["filters_matched"] == 0
        # GET keeps working, compact flag
        r = client.get("/api/papers/semantic-search", params={"q": "tokenizer", "compact": "true", "days": 7})
        assert r.status_code == 200 and r.json()["results"][0]["id"] == "s1" and "tldr" in r.json()["results"][0]
    # ids= fetch + compact on list/search
    r = client.get("/api/papers", params={"ids": "s3,s1,missing", "compact": "true"})
    assert [x["id"] for x in r.json()] == ["s3", "s1"] and "tldr" in r.json()[0]
    r = client.get("/api/papers/search", params={"q": "tokenizer", "compact": "true"})
    assert {x["id"] for x in r.json()} == {"s1", "s2"} and "full_text" not in r.json()[0]
    r = client.get("/api/papers/search", params={"q": "tokenizer"})
    assert "summary_generic" in r.json()[0]
