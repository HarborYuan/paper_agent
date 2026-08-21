"""
Tests for the two-stage scoring pipeline, runtime model settings, model catalog,
usage/cost endpoints and robust JSON parsing.
"""
import json
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from src.models import Paper, LLMUsage
from src.services.llm import extract_json_object, ScoreResponse, Stage2ScoreResponse
from src.services.model_catalog import ModelInfo, model_catalog
from src.services.settings_service import LLMConfig, get_llm_config, update_llm_config


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------
class TestExtractJson:
    def test_plain(self):
        assert extract_json_object('{"score": 90}') == {"score": 90}

    def test_code_fence(self):
        assert extract_json_object('```json\n{"score": 90, "risk_flags": []}\n```') == {"score": 90, "risk_flags": []}

    def test_leading_prose(self):
        txt = 'Sure! Here is the JSON:\n{"score": 72, "one_line_reason": "ok {braces} inside"}\nThanks.'
        assert extract_json_object(txt)["score"] == 72

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            extract_json_object("no json here")


# ---------------------------------------------------------------------------
# Settings service (env-file backed, hot-applied)
# ---------------------------------------------------------------------------
def test_llm_config_defaults_then_override(env_file):
    cfg = get_llm_config()
    assert cfg.stage1_model and cfg.stage2_model and cfg.summary_model
    assert cfg.stage2_threshold < cfg.score_threshold

    cfg2, warnings = update_llm_config(stage2_model="test/strong-model", stage2_threshold=70)
    assert cfg2.stage2_model == "test/strong-model" and cfg2.stage2_threshold == 70
    assert warnings == []
    # persisted to the env file and hot-applied
    text = env_file.read_text()
    assert 'LLM_MODEL_STAGE2="test/strong-model"' in text and 'STAGE2_THRESHOLD="70"' in text
    assert get_llm_config().stage2_threshold == 70


# ---------------------------------------------------------------------------
# Settings / models / usage endpoints
# ---------------------------------------------------------------------------
FAKE_MODELS = {
    "openai/gpt-4o-mini": ModelInfo("openai/gpt-4o-mini", "GPT-4o-mini", 0.15, 0.60, 128000, True, True),
    "anthropic/claude-sonnet-5": ModelInfo("anthropic/claude-sonnet-5", "Claude Sonnet 5", 2.0, 10.0, 1000000, True, True),
    "vendor/cheap": ModelInfo("vendor/cheap", "Cheap", 0.05, 0.10, 32000, False, False),
}


@pytest.fixture
def fake_catalog():
    from src.config import settings as app_settings
    with patch.object(model_catalog, "_models", dict(FAKE_MODELS)), \
         patch.object(model_catalog, "_fetched_at", 9e12), \
         patch.object(model_catalog, "refresh", AsyncMock(return_value=True)), \
         patch.object(app_settings, "OPENROUTER_API_KEY", "sk-or-test"):
        yield


def test_get_settings(client):
    r = client.get("/api/settings/llm")
    assert r.status_code == 200
    data = r.json()
    assert set(data["models"].keys()) == {"stage1", "stage2", "summary", "report"}
    assert "stage2_threshold" in data["thresholds"]
    assert "key_configured" in data["provider"]
    assert "profile" in data


def test_put_model_settings_validates(client, fake_catalog, env_file):
    # unknown model rejected when a catalog is present
    r = client.put("/api/settings/llm", json={"stage2_model": "nope/unknown"})
    assert r.status_code == 400
    # bad threshold rejected
    r = client.put("/api/settings/llm", json={"stage2_threshold": 140})
    assert r.status_code == 400
    # valid update persists and is echoed back
    r = client.put("/api/settings/llm", json={"stage1_model": "vendor/cheap", "stage2_model": "anthropic/claude-sonnet-5", "stage2_threshold": 55})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["models"]["stage1"] == "vendor/cheap"
    assert data["models"]["stage2"] == "anthropic/claude-sonnet-5"
    assert data["thresholds"]["stage2_threshold"] == 55
    assert client.get("/api/settings/llm").json()["models"]["stage1"] == "vendor/cheap"


def test_list_models(client, fake_catalog):
    r = client.get("/api/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["models"]]
    # recommended first
    assert ids[0] in ("anthropic/claude-sonnet-5", "openai/gpt-4o-mini")
    assert "vendor/cheap" in ids
    r = client.get("/api/models", params={"q": "cheap"})
    assert [m["id"] for m in r.json()["models"]] == ["vendor/cheap"]
    m = r.json()["models"][0]
    assert m["prompt_price_per_m"] == 0.05 and m["supports_json"] is False


def test_usage_and_estimate_endpoints(client, session, fake_catalog):
    # empty usage
    r = client.get("/api/llm/usage")
    assert r.status_code == 200
    assert r.json()["periods"]["all_time"]["calls"] == 0

    # seed some usage rows + a few papers so estimate has something to chew on
    for i in range(6):
        session.add(LLMUsage(paper_id=f"p{i}", task="score_stage1", model="openai/gpt-4o-mini",
                             prompt_tokens=1000, completion_tokens=100, total_tokens=1100, cost=0.0002))
    session.add(LLMUsage(paper_id="p0", task="score_stage2", model="anthropic/claude-sonnet-5",
                         prompt_tokens=4000, completion_tokens=400, total_tokens=4400, cost=0.012))
    for i in range(10):
        session.add(Paper(id=f"p{i}", title=f"P{i}", authors="[]", summary_generic="", published_at=datetime.now(),
                          category_primary="cs.CV", all_categories="[]", pdf_url="", score=90 if i < 2 else 40,
                          score_stage1=70 if i < 3 else 30, status="SCORED"))
    session.commit()

    r = client.get("/api/llm/usage")
    assert r.json()["periods"]["all_time"]["calls"] == 7
    assert abs(r.json()["periods"]["all_time"]["cost"] - (6 * 0.0002 + 0.012)) < 1e-9
    tasks = {b["task"]: b for b in r.json()["breakdown"]}
    assert tasks["score_stage1"]["avg_prompt_tokens"] == 1000

    r = client.get("/api/llm/estimate", params={"stage2_model": "anthropic/claude-sonnet-5", "stage1_model": "openai/gpt-4o-mini", "summary_model": "vendor/cheap"})
    assert r.status_code == 200, r.text
    est = r.json()
    per_task = {t["task"]: t for t in est["per_task"]}
    # stage1 has >=5 samples -> observed tokens; stage2 has 1 -> prior
    assert per_task["score_stage1"]["tokens_source"] == "observed"
    assert per_task["score_stage2"]["tokens_source"] == "prior"
    assert per_task["score_stage1"]["cost_per_call"] == pytest.approx((1000 * 0.15 + 100 * 0.60) / 1e6)
    assert est["total_per_day"] > 0
    assert est["missing_prices"] == []
    # volumes derived from the paper table: 10 papers in one day, 3 >= stage2 threshold (60), 2 >= 85
    assert per_task["score_stage1"]["calls_per_day"] == 10
    assert per_task["score_stage2"]["calls_per_day"] == 3
    assert per_task["summarize"]["calls_per_day"] == 2


# ---------------------------------------------------------------------------
# Worker: two-stage decision logic (LLM + PDF mocked, DB in-memory)
# ---------------------------------------------------------------------------
def _mk_paper(pid="2401.00001", **kw):
    base = dict(id=pid, title="T", authors='["Alice", "Bob"]', summary_generic="abstract",
                published_at=datetime(2024, 1, 1), category_primary="cs.CV", all_categories='["cs.CV"]',
                pdf_url="http://example.com/x.pdf", status="NEW")
    base.update(kw)
    return Paper(**base)


def _mk_llm(s1_score, s2_score=None, stage2_threshold=60, score_threshold=85):
    llm = AsyncMock()
    llm.config = LLMConfig("cheap/m", "strong/m", "sum/m", stage2_threshold, score_threshold)
    llm.score_paper.return_value = ScoreResponse(score=s1_score, relevance=4, novelty=3, clarity=3,
                                                 risk_flags=[], one_line_reason="s1")
    if s2_score is None:
        llm.score_paper_stage2.return_value = None
    else:
        llm.score_paper_stage2.return_value = Stage2ScoreResponse(
            score=s2_score, relevance=5, novelty=4, quality=4, clarity=4,
            risk_flags=["no_code"], strengths=["solid"], weaknesses=["small"], one_line_reason="s2")
    return llm


@pytest.fixture
def worker_env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with patch("src.worker.engine", engine), \
         patch("src.worker.pdf_service.extract_text_from_url", AsyncMock(return_value="INTRO TEXT " * 50)) as pdf_mock:
        yield engine, pdf_mock


def _run_score(engine, llm, paper):
    from src.worker import process_paper_score
    with Session(engine, expire_on_commit=False) as s:
        s.add(paper); s.commit()
    asyncio.run(process_paper_score(asyncio.Semaphore(1), llm, paper))
    with Session(engine) as s:
        return s.get(Paper, paper.id)


def test_low_stage1_skips_stage2(worker_env):
    engine, pdf_mock = worker_env
    llm = _mk_llm(s1_score=40, s2_score=95)
    p = _run_score(engine, llm, _mk_paper())
    llm.score_paper_stage2.assert_not_called()
    pdf_mock.assert_not_called()
    assert p.score == 40 and p.score_stage1 == 40 and p.score_model == "cheap/m"
    assert p.status == "FILTERED"
    reason = json.loads(p.score_reason)
    assert "stage1" in reason and "stage2" not in reason and reason["final"] == 40


def test_high_stage1_triggers_stage2_and_final_is_stage2(worker_env):
    engine, pdf_mock = worker_env
    llm = _mk_llm(s1_score=90, s2_score=70)   # stage 2 demotes it
    p = _run_score(engine, llm, _mk_paper())
    llm.score_paper_stage2.assert_called_once()
    # stage 2 got a text snippet from the PDF
    snippet = llm.score_paper_stage2.call_args.args[2]
    assert snippet and snippet.startswith("INTRO TEXT")
    assert p.score == 70 and p.score_stage1 == 90 and p.score_model == "strong/m"
    assert p.status == "FILTERED"            # 70 < 85
    assert p.full_text and p.full_text.startswith("INTRO TEXT")   # cached for summarization
    reason = json.loads(p.score_reason)
    assert reason["stage2"]["quality"] == 4 and reason["stage2"]["had_full_text"] is True


def test_stage2_promotes_to_scored(worker_env):
    engine, _ = worker_env
    llm = _mk_llm(s1_score=65, s2_score=88)
    p = _run_score(engine, llm, _mk_paper())
    assert p.score == 88 and p.status == "SCORED" and p.score_model == "strong/m"


def test_stage2_failure_keeps_stage1(worker_env):
    engine, _ = worker_env
    llm = _mk_llm(s1_score=88, s2_score=None)
    p = _run_score(engine, llm, _mk_paper())
    assert p.score == 88 and p.score_model == "cheap/m" and p.status == "SCORED"
    assert "error" in json.loads(p.score_reason)["stage2"]


def test_cached_full_text_is_reused(worker_env):
    engine, pdf_mock = worker_env
    llm = _mk_llm(s1_score=80, s2_score=90)
    p = _run_score(engine, llm, _mk_paper(full_text="CACHED BODY"))
    pdf_mock.assert_not_called()
    assert llm.score_paper_stage2.call_args.args[2] == "CACHED BODY"
    assert p.full_text == "CACHED BODY"


def test_user_score_skips_everything(worker_env):
    engine, _ = worker_env
    llm = _mk_llm(s1_score=10, s2_score=10)
    p = _run_score(engine, llm, _mk_paper(user_score=99, score=99))
    llm.score_paper.assert_not_called()
    assert p.score == 99


# ---------------------------------------------------------------------------
# Provider-aware model id resolution
# ---------------------------------------------------------------------------
def test_resolve_model_legacy_vs_openrouter():
    from src.services.llm import LLMService
    cfg = LLMConfig("openai/gpt-4o-mini", "anthropic/claude-sonnet-5", "openai/gpt-5-mini", 60, 85)
    svc = LLMService(config=cfg)
    svc.is_openrouter = True
    assert svc.resolve_model("anthropic/claude-sonnet-5") == "anthropic/claude-sonnet-5"
    svc.is_openrouter = False
    assert svc.resolve_model("openai/gpt-5-mini") == "gpt-5-mini"          # prefix stripped
    assert svc.resolve_model("gpt-4o-mini") == "gpt-4o-mini"               # bare id untouched
    assert svc.resolve_model("anthropic/claude-sonnet-5") == "gpt-4o-mini"  # other vendor -> stage-1 fallback


def test_catalog_price_fallback():
    with patch.object(model_catalog, "_models", dict(FAKE_MODELS)):
        assert model_catalog.get_for_pricing("gpt-4o-mini").id == "openai/gpt-4o-mini"
        assert model_catalog.get_for_pricing("openai/gpt-4o-mini").id == "openai/gpt-4o-mini"
        assert model_catalog.get_for_pricing("unknown") is None
        assert model_catalog.estimate_cost("gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)
