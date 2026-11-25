"""
Tests for the verdict pipeline: verdict -> score mapping, arXiv HTML segmentation, the Claude runner
(real time + batch, with a fake client) and the screen -> review -> deep read orchestration.
"""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from src.models import LLMUsage, Paper, PaperReading
from src.services import claude_runner, reading_page, reading_service, verdict_pipeline
from src.services.claude_runner import ClaudeRequest, ClaudeRunner, estimate_cost


# ---------------------------------------------------------------------------- fixtures
@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("src.database.engine", engine)
    monkeypatch.setattr(verdict_pipeline, "engine", engine)
    from src.services import project_service
    monkeypatch.setattr(project_service, "engine", engine)
    return engine


def _paper(pid, title="A paper", authors=("Ada Lovelace",)):
    return Paper(id=pid, title=title, authors=json.dumps(list(authors)), summary_generic="An abstract.",
                 published_at=datetime(2026, 11, 20), category_primary="cs.CV", all_categories='["cs.CV"]',
                 pdf_url=f"https://arxiv.org/pdf/{pid}", full_text="Body text. " * 50)


# ---------------------------------------------------------------------------- scoring
def test_verdict_score_bands():
    hi = {"novelty": 5, "evidence": 5, "reusability": 5}
    lo = {"novelty": 0, "evidence": 0, "reusability": 0}
    assert verdict_pipeline.verdict_score("must_read", hi) == 99
    assert verdict_pipeline.verdict_score("must_read", lo) == 92
    assert 85 <= verdict_pipeline.verdict_score("worth_reading", {"novelty": 3, "evidence": 3, "reusability": 3}) <= 91
    assert verdict_pipeline.verdict_score("skim", hi) == 84   # never reaches the push threshold
    assert verdict_pipeline.verdict_score("skip", lo) == 20


def test_estimate_cost_cache_and_batch():
    u = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    assert estimate_cost("claude-sonnet-5-5", u) == pytest.approx(2 + 10 + 0.10)
    assert estimate_cost("claude-sonnet-5-5", u, batch=True) == pytest.approx((2 + 10 + 0.10) / 2)
    assert estimate_cost("unknown-model", u) is None


# ---------------------------------------------------------------------------- segmentation
HTML = """<html><body><article class="ltx_document">
<h1 class="ltx_title ltx_title_document">Title</h1>
<div class="ltx_abstract"><h6 class="ltx_title ltx_title_abstract">Abstract</h6><p class="ltx_p">We study $x$ things.</p></div>
<section class="ltx_section"><h2 class="ltx_title ltx_title_section">1 Introduction</h2>
<div class="ltx_para"><p class="ltx_p">First paragraph with <math alttext="\\alpha"><mi>α</mi></math> math<span class="ltx_note">footnote</span>.</p></div>
<figure class="ltx_figure"><img src="2611.00001v1/x1.png"><figcaption>Figure 1: A plot.</figcaption></figure>
<figure class="ltx_figure"><svg><text>tikz</text></svg><figcaption>Figure 2: A TikZ drawing.</figcaption></figure>
<figure class="ltx_table"><figcaption>Table 1: Results.</figcaption><div class="ltx_transformed_outer"><table><tr><td>1.0</td></tr></table></div></figure>
<table class="ltx_equation ltx_eqn_table"><tr><td><math alttext="E=mc^2"></math></td></tr></table>
</section>
<section class="ltx_bibliography"><p class="ltx_p">[1] A reference.</p></section>
</article></body></html>"""


def test_segment_units_and_crop_detection():
    units = reading_service.segment(HTML, "https://arxiv.org/html/2611.00001")
    kinds = [u["kind"] for u in units]
    assert kinds == ["heading", "para", "heading", "para", "figure", "figure", "table", "equation"]
    para = units[3]
    assert para["id"] == "P2" and "$\\alpha$" in para["text"] and "footnote" not in para["text"]
    f1, f2, t1 = units[4], units[5], units[6]
    assert f1["srcs"] == ["https://arxiv.org/html/2611.00001v1/x1.png"]
    assert not reading_service.needs_crop(f1)
    assert reading_service.needs_crop(f2) and reading_service.needs_crop(t1)
    assert units[7]["tex"] == "E=mc^2"
    assert all("reference" not in (u.get("text") or "") for u in units)  # stops at the bibliography


# ---------------------------------------------------------------------------- runner
class _Msg(SimpleNamespace):
    pass


def _message(text, stop="end_turn"):
    return _Msg(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 100, "output_tokens": 20,
                                                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 50}))


class FakeClient:
    """Answers every request with responder(params) -> text. Supports stream() and batches."""

    def __init__(self, responder, batch_fails=False):
        self.responder = responder
        self.batch_fails = batch_fails
        self.calls = []
        outer = self

        class _Stream:
            def __init__(self, params):
                self.params = params

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get_final_message(self):
                outer.calls.append(("stream", self.params))
                return _message(outer.responder(self.params))

        class _Batches:
            def __init__(self):
                self.reqs = None

            async def create(self, requests):
                if outer.batch_fails:
                    raise RuntimeError("batch API down")
                self.reqs = requests
                outer.calls.append(("batch", len(requests)))
                return SimpleNamespace(id="b1", processing_status="in_progress")

            async def retrieve(self, bid):
                return SimpleNamespace(id=bid, processing_status="ended")

            async def cancel(self, bid):
                return None

            async def results(self, bid):
                reqs = self.reqs

                async def gen():
                    for r in reqs:
                        yield SimpleNamespace(custom_id=r["custom_id"], result=SimpleNamespace(
                            type="succeeded", message=_message(outer.responder(r["params"]))))
                return gen()

        class _Messages:
            def __init__(self):
                self.batches = _Batches()

            def stream(self, **params):
                return _Stream(params)

        self.messages = _Messages()


async def test_runner_realtime_and_batch(db):
    client = FakeClient(lambda p: json.dumps({"ok": p["messages"][0]["content"]}))
    reqs = [ClaudeRequest(key=f"k{i}", task="t", model="claude-haiku-5-5", system="S", user=f"u{i}",
                          schema={"type": "object"}) for i in range(3)]
    rt = await ClaudeRunner(client=client, use_batch=False).run(reqs)
    assert {k: v.data["ok"] for k, v in rt.items()} == {"k0": "u0", "k1": "u1", "k2": "u2"}
    # system prompt is sent as a cached block
    assert client.calls[0][1]["system"][0]["cache_control"] == {"type": "ephemeral"}
    bt = await ClaudeRunner(client=client, use_batch=True, poll_seconds=0).run(reqs)
    assert all(r.ok and r.batch for r in bt.values())
    with Session(db) as s:
        rows = s.exec(select(LLMUsage)).all()
    assert len(rows) == 6 and all(r.cost is not None for r in rows)
    assert sum(r.model.endswith("(batch)") for r in rows) == 3


async def test_runner_batch_failure_falls_back(db):
    client = FakeClient(lambda p: json.dumps({"x": 1}), batch_fails=True)
    res = await ClaudeRunner(client=client, use_batch=True).run(
        [ClaudeRequest(key="a", task="t", model="claude-haiku-5-5", system="S", user="u", schema={"type": "object"})])
    assert res["a"].ok and not res["a"].batch


async def test_runner_refusal_and_bad_json(db):
    class C(FakeClient):
        pass
    client = FakeClient(lambda p: "not json")
    res = await ClaudeRunner(client=client, use_batch=False).run(
        [ClaudeRequest(key="a", task="t", model="claude-haiku-5-5", system="S", user="u", schema={"type": "object"})])
    assert not res["a"].ok and "invalid JSON" in res["a"].error


# ---------------------------------------------------------------------------- pipeline
UNITS = [
    {"id": "H0", "kind": "heading", "level": 2, "text": "Abstract", "section": "Abstract"},
    {"id": "P1", "kind": "para", "text": "We are the first to solve vision.", "section": "Abstract"},
    {"id": "P2", "kind": "para", "text": "Our method uses a tokenizer.", "section": "Abstract"},
]


def _responder(p):
    user = p["messages"][0]["content"]
    sys_ = p.get("system", [{"text": ""}])[0]["text"]
    if "You screen new arXiv papers" in sys_:
        rel = 5 if "Core paper" in user else 2
        return json.dumps({"main_contribution": "c", "matched_interest": "x", "matched_section": "core",
                           "relevance": rel, "one_line_reason": "r"})
    if "reviewing new papers" in sys_:
        return json.dumps({"strengths": ["s"], "weaknesses": ["w"], "risk_flags": [], "relevance": 5, "novelty": 4,
                           "evidence": 3, "reusability": 4, "verdict": "worth_reading", "one_line_reason": "good",
                           "affiliations": ["Uni A", "Lab B"], "main_company": "Lab B", "main_university": "Uni A",
                           "main_affiliation": "Uni A"})
    if "final, full-text read" in sys_:
        return json.dumps({"verdict": "must_read", "verdict_change_reason": "experiments are strong", "relevance": 5,
                           "novelty": 4, "evidence": 4, "reusability": 4, "one_line_reason": "great",
                           "tldr": "Short.",
                           "notes": [{"ids": ["P1", "P2"], "gist": "要点。",
                                      "flags": [{"id": "P1", "span": "the first to solve vision", "kind": "big_claim", "why": "太大"},
                                                {"id": "P2", "span": "not in the text", "kind": "questionable", "why": "x"}]}]})
    if "You translate" in sys_:
        return json.dumps({"translations": [{"id": "P1", "zh": "我们首次解决了视觉。"}, {"id": "P2", "zh": "方法用 tokenizer。"}]})
    raise AssertionError("unexpected request")


async def test_run_pipeline_end_to_end(db, monkeypatch):
    monkeypatch.setattr(verdict_pipeline.settings, "SCREEN_MIN_RELEVANCE", 4)

    async def fake_units(pid, pdf_url=None):
        return [dict(u) for u in UNITS]
    monkeypatch.setattr(reading_service, "fetch_units", fake_units)
    with Session(db) as s:
        s.add(_paper("2611.00001", title="Core paper"))
        s.add(_paper("2611.00002", title="Other paper"))
        s.commit()
        papers = s.exec(select(Paper)).all()
    runner = ClaudeRunner(client=FakeClient(_responder), use_batch=True, poll_seconds=0)
    stats = await verdict_pipeline.run_pipeline(papers, runner)
    assert stats == {"screened": 2, "reviewed": 1, "deep_read": 1, "deferred": 0, "project_candidates": 0}
    with Session(db) as s:
        core, other = s.get(Paper, "2611.00001"), s.get(Paper, "2611.00002")
        reading = s.get(PaperReading, "2611.00001")
    assert other.status == "FILTERED" and other.score == 40
    assert core.status == "SUMMARIZED" and core.score >= 92 and core.main_affiliation == "Uni A"
    reason = json.loads(core.score_reason)
    assert reason["pipeline"] == "verdict" and reason["stage2"]["verdict"] == "worth_reading"
    assert reason["deep"]["verdict"] == "must_read" and core.summary_personalized.startswith("## TL;DR")
    assert reading.status == "DONE" and reading.source == "html"
    notes = json.loads(reading.notes)
    assert [f["verified"] for f in notes[0]["flags"]] == [True, False]
    assert json.loads(reading.translations)["P2"] == "方法用 tokenizer。"
    # the reading page renders the verified flag only
    html = reading_page.render(core, verdict_pipeline.get_reading("2611.00001"))
    assert "<mark class='b' id='f1'>the first to solve vision</mark>" in html
    assert "not in the text</mark>" not in html and "Must Read" in html and "方法用 tokenizer。" in html


async def test_failed_review_keeps_paper_new(db, monkeypatch):
    def responder(p):
        if "reviewing new papers" in p["system"][0]["text"]:
            return "garbage"
        return _responder(p)
    with Session(db) as s:
        s.add(_paper("2611.00003", title="Core paper"))
        s.commit()
        papers = s.exec(select(Paper)).all()
    await verdict_pipeline.run_pipeline(papers, ClaudeRunner(client=FakeClient(responder), use_batch=False))
    with Session(db) as s:
        p = s.get(Paper, "2611.00003")
    assert p.status == "NEW" and p.score_stage1 == 100   # screened, retried next run


async def test_budget_guard_trims_and_blocks(db, monkeypatch):
    from src.services import claude_budget
    monkeypatch.setattr(claude_budget.settings, "CLAUDE_MONTHLY_BUDGET", 1)
    with Session(db) as s:
        s.add(LLMUsage(task="t", model="claude-sonnet-5-5 (batch)", cost=0.95))   # 0.05 left
        s.add(LLMUsage(task="t", model="openai/gpt-4o-mini", cost=50.0))          # other providers don't count
        s.add(_paper("2611.00009", title="Core paper"))
        s.commit()
        papers = s.exec(select(Paper)).all()
    st = claude_budget.status()
    assert st["spent"] == pytest.approx(0.95) and st["remaining"] == pytest.approx(0.05)
    assert claude_budget.affordable("deep", 5) == 0 and claude_budget.affordable("review", 5) == 3

    async def fake_units(pid, pdf_url=None):
        return [dict(u) for u in UNITS]
    monkeypatch.setattr(reading_service, "fetch_units", fake_units)
    stats = await verdict_pipeline.run_pipeline(papers, ClaudeRunner(client=FakeClient(_responder), use_batch=False))
    assert stats["reviewed"] == 1 and stats["deep_read"] == 0 and stats["deferred"] == 1
    with Session(db) as s:
        assert s.get(Paper, "2611.00009").status == "SCORED"   # waits for the next cycle
    with pytest.raises(verdict_pipeline.BudgetExceeded):
        await verdict_pipeline.deep_read_on_demand("2611.00009")


def test_cycle_start_reset_day(monkeypatch):
    from src.services import claude_budget
    monkeypatch.setattr(claude_budget.settings, "CLAUDE_BUDGET_RESET_DAY", 15)
    assert claude_budget.cycle_start(datetime(2026, 11, 24)) == datetime(2026, 11, 15)
    assert claude_budget.cycle_start(datetime(2026, 1, 3)) == datetime(2025, 12, 15)


async def test_project_match_collects_without_push(db, monkeypatch):
    from src.services import project_service
    with Session(db) as s:
        s.add(_paper("2611.00010", title="Seed paper"))
        s.add(_paper("2611.00011", title="Proj paper"))
        s.commit()
    project_service.create("MaskTok", "Discrete mask tokenizer for MLLMs", ["mask token"], ["2611.00010"])

    async def no_emb(ids, projects):
        return {}
    monkeypatch.setattr(project_service, "embedding_candidates", no_emb)
    seen = {}

    def responder(p):
        sys_, user = p["system"][0]["text"], p["messages"][0]["content"]
        if "You screen new arXiv papers" in sys_:
            seen["screen_schema"] = p["output_config"]["format"]["schema"]["properties"].get("matched_projects")
            assert "MaskTok: Discrete mask tokenizer" in sys_
            return json.dumps({"main_contribution": "c", "matched_interest": "x", "matched_section": "none",
                               "relevance": 2, "one_line_reason": "r", "matched_projects": ["MaskTok"]})
        if "reviewing new papers" in sys_:
            assert "CANDIDATE PROJECTS: MaskTok" in user
            return json.dumps({"strengths": [], "weaknesses": [], "risk_flags": [], "relevance": 2, "novelty": 3,
                               "evidence": 3, "reusability": 3, "verdict": "skim", "one_line_reason": "adjacent",
                               "affiliations": [], "main_company": None, "main_university": None, "main_affiliation": None,
                               "project_matches": [{"project": "MaskTok", "relevant": True, "reason": "a mask baseline"}]})
        raise AssertionError("no deep read expected")
    with Session(db) as s:
        papers = [s.get(Paper, "2611.00011")]
    stats = await verdict_pipeline.run_pipeline(papers, ClaudeRunner(client=FakeClient(responder), use_batch=False))
    assert seen["screen_schema"]["items"]["enum"] == ["MaskTok"]
    assert stats["reviewed"] == 1 and stats["deep_read"] == 0 and stats["project_candidates"] == 1
    proj = project_service.get("masktok")
    by_id = {x["id"]: x for x in proj["papers"]}
    assert by_id["2611.00010"]["project_source"] == "seed"
    assert by_id["2611.00011"]["project_source"] == "auto" and by_id["2611.00011"]["project_reason"] == "a mask baseline"
    with Session(db) as s:
        assert s.get(Paper, "2611.00011").status == "FILTERED"   # collected, not pushed
    # manual add upgrades, remove works, unknown ids reported
    r = project_service.add_papers("MaskTok", ["2611.00011", "9999.99999"], source="manual")
    assert r["already"] == ["2611.00011"] and r["unknown"] == ["9999.99999"]
    assert {x["id"]: x for x in project_service.get("MaskTok")["papers"]}["2611.00011"]["project_source"] == "manual"
    assert project_service.remove_papers("MaskTok", ["2611.00011"]) == ["2611.00011"]
    with pytest.raises(ValueError):
        project_service.create("masktok ")  # duplicate name (case-insensitive)


async def test_hot_lane_refresh_pending_section(db, monkeypatch):
    from src.services import hot_service
    monkeypatch.setattr(hot_service, "engine", db)
    monkeypatch.setattr(hot_service.settings, "HOT_MIN_UPVOTES", 50)
    monkeypatch.setattr(hot_service.settings, "HOT_MIN_STARS", 500)
    monkeypatch.setattr(hot_service.settings, "HOT_MAX_PER_RUN", 5)
    monkeypatch.setattr(hot_service.settings, "PUBLIC_BASE_URL", "http://nas:8000")
    with Session(db) as s:
        for pid in ("2611.00021", "2611.00022", "2611.00023"):
            s.add(_paper(pid, title=f"Paper {pid}"))
        s.commit()

    async def fake_day(client, day):
        if day != hot_service.datetime.now(hot_service.timezone.utc).date().isoformat():
            return []
        return [{"paper": {"id": "2611.00021", "upvotes": 120, "githubStars": 10, "ai_summary": "Big model."}},
                {"paper": {"id": "2611.00022v2", "upvotes": 12, "githubStars": 900}},
                {"paper": {"id": "2611.00023", "upvotes": 20, "githubStars": 0}}]
    monkeypatch.setattr(hot_service, "fetch_day", fake_day)
    r = await hot_service.refresh()
    assert r == {"seen": 3, "added": 0}
    pend = hot_service.pending()
    assert [x.paper_id for x in pend] == ["2611.00021", "2611.00022"]   # upvotes or stars; 00023 is not hot
    with Session(db) as s:
        papers = {p.id: p for p in s.exec(select(Paper)).all()}
    msg = hot_service.section(pend, papers, {"2611.00021": "大家在讨论。"})
    assert "🔥 Hot this week (2)" in msg and "👍 120" in msg and "⭐ 900 stars" in msg
    assert "💬 大家在讨论。" in msg and "http://nas:8000/read/2611.00021" in msg and "💡 Big model." in msg
    hot_service.mark_pushed(["2611.00021", "2611.00022"])
    assert hot_service.pending() == []
    await hot_service.refresh()            # upvotes only go up; pushed papers stay pushed
    assert hot_service.pending() == []


def test_openrouter_provider_maps_ids_and_disables_batch(monkeypatch):
    from src.services import claude_runner as cr
    monkeypatch.setattr(cr.settings, "CHAT_PROVIDER", "openrouter")
    monkeypatch.setattr(cr.settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(cr.settings, "LLM_USE_BATCH", True)
    assert cr.openrouter_model_id("claude-haiku-5-5") == "anthropic/claude-haiku-5.5"
    assert cr.openrouter_model_id("claude-sonnet-5") == "anthropic/claude-sonnet-5"
    req = ClaudeRequest(key="a", task="t", model="claude-sonnet-5-5", system="S", user="u")
    assert req.params()["model"] == "anthropic/claude-sonnet-5.5"
    runner = ClaudeRunner()
    assert runner.use_batch is False
    assert str(runner.client.base_url).rstrip("/") == "https://openrouter.ai/api"
    assert cr.settings.chat_api_key == "sk-or-test" and cr.settings.chat_key_name == "OPENROUTER_API_KEY"


def test_anthropic_provider_keeps_ids(monkeypatch):
    from src.services import claude_runner as cr
    monkeypatch.setattr(cr.settings, "CHAT_PROVIDER", "anthropic")
    monkeypatch.setattr(cr.settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    req = ClaudeRequest(key="a", task="t", model="claude-sonnet-5-5", system="S", user="u")
    assert req.params()["model"] == "claude-sonnet-5-5"
    assert "api.anthropic.com" in str(ClaudeRunner().client.base_url)


def test_legacy_two_stage_review_is_reused():
    p = _paper("2608.00001")
    p.score = 88
    p.score_reason = json.dumps({"stage1": {"score": 85}, "stage2": {"model": "anthropic/claude-sonnet-5", "score": 88,
                                 "relevance": 5, "novelty": 4, "quality": 3, "clarity": 4, "one_line_reason": "solid"}})
    rv = verdict_pipeline.provisional_review(p)
    assert rv["verdict"] == "worth_reading" and rv["evidence"] == 3 and rv["legacy"] is True
    assert [verdict_pipeline.score_to_verdict(x) for x in (95, 85, 70, 40)] == ["must_read", "worth_reading", "skim", "skip"]
    p.score_reason = json.dumps({"stage1": {"score": 40}})
    assert verdict_pipeline.provisional_review(p) is None          # screened only -> a new review runs
    p.score_reason = json.dumps({"stage2": {"error": "stage-2 scoring failed"}})
    assert verdict_pipeline.provisional_review(p) is None


def test_reading_page_keeps_heading_inside_cross_heading_note(db):
    units = [
        {"id": "H0", "kind": "heading", "level": 3, "text": "3.1 Method"},
        {"id": "P1", "kind": "para", "text": "Intro of the subsection."},
        {"id": "H2", "kind": "heading", "level": 4, "text": "Anchors."},
        {"id": "P2", "kind": "para", "text": "Body under the run-in title."},
        {"id": "H4", "kind": "heading", "level": 4, "text": "Tree."},
        {"id": "P3", "kind": "para", "text": "Next paragraph."},
    ]
    reading = {"status": "DONE", "units": units, "translations": {},
               "notes": [{"ids": ["P1", "P2"], "gist": "要点一", "flags": []},
                         {"ids": ["P3"], "gist": "要点二", "flags": []}]}
    html = reading_page.render(_paper("2611.00009"), reading)
    # the run-in title sits between its neighbours inside the card, and is not repeated after it
    assert html.count("Anchors.</h4>") == 1
    assert html.index("Intro of the subsection.") < html.index("Anchors.</h4>") < html.index("Body under the run-in title.")
    assert "class='sec in' id='s-H2'" in html
    assert html.index("Body under the run-in title.") < html.index("Tree.</h4>") < html.index("Next paragraph.")
    assert html.count("href='#s-H0'") == 1


@pytest.mark.asyncio
async def test_backfill_reruns_old_days(db, monkeypatch):
    from datetime import date
    monkeypatch.setattr(verdict_pipeline.settings, "SCREEN_MIN_RELEVANCE", 4)

    async def fake_units(pid, pdf_url=None):
        return [dict(u) for u in UNITS]
    monkeypatch.setattr(reading_service, "fetch_units", fake_units)
    with Session(db) as s:
        for pid, day in (("2611.00001", 20), ("2611.00002", 20), ("2611.00003", 18)):
            p = _paper(pid, title="Core paper" if pid == "2611.00001" else "Other paper")
            p.published_at = datetime(2026, 11, day, 12)
            p.status, p.score_reason = "PUSHED", json.dumps({"stage1": {"score": 80}})  # old pipeline
            s.add(p)
        s.commit()
    runner = ClaudeRunner(client=FakeClient(_responder), use_batch=True, poll_seconds=0)
    st = await verdict_pipeline.backfill(date(2026, 11, 19), date(2026, 11, 20), runner=runner)
    assert list(st["days"]) == ["2026-11-20", "2026-11-19"] and not st["running"]
    assert st["days"]["2026-11-20"]["deep_read"] == 1 and st["days"]["2026-11-19"] == {}
    with Session(db) as s:
        core, other, untouched = (s.get(Paper, i) for i in ("2611.00001", "2611.00002", "2611.00003"))
    assert core.status == "SUMMARIZED" and verdict_pipeline.is_verdict_scored(core)
    assert other.status == "FILTERED" and untouched.status == "PUSHED" and not verdict_pipeline.is_verdict_scored(untouched)


def test_backfill_status_route_is_not_shadowed():
    from fastapi.testclient import TestClient
    from src.main import app
    r = TestClient(app).get("/api/papers/backfill-verdicts")
    assert r.status_code == 200 and "running" in r.json()
