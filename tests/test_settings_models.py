"""Settings API for the Claude models: payload shape, validation, legacy-id fallback."""
from src.config import settings as app_settings
from src.services.settings_service import get_llm_config, stale_model_warnings, update_llm_config


def test_get_llm_settings(client):
    r = client.get("/api/settings/llm")
    assert r.status_code == 200
    d = r.json()
    assert set(d["models"]) == {"screen", "review", "deep_read", "translate"}
    assert d["provider"]["chat"] == "anthropic" and "embeddings" in d["provider"]
    assert "profile" in d and "warnings" in d


def test_put_models_requires_claude_ids(client, env_file):
    r = client.put("/api/settings/llm", json={"stage2_model": "anthropic/claude-sonnet-5"})
    assert r.status_code == 400
    r = client.put("/api/settings/llm", json={"stage1_model": "claude-sonnet-5-5"})
    assert r.status_code == 200, r.text
    assert r.json()["models"]["screen"] == "claude-sonnet-5-5"
    assert 'LLM_MODEL_STAGE1="claude-sonnet-5-5"' in env_file.read_text()


def test_legacy_model_ids_fall_back_to_claude(monkeypatch):
    monkeypatch.setattr(app_settings, "LLM_MODEL_STAGE1", "deepseek/deepseek-v4-flash")
    monkeypatch.setattr(app_settings, "LLM_MODEL_SUMMARY", "anthropic/claude-sonnet-5")
    cfg = get_llm_config()
    assert cfg.stage1_model == "claude-haiku-5-5" and cfg.summary_model == "claude-sonnet-5-5"
    w = stale_model_warnings()
    assert any("LLM_MODEL_STAGE1" in x for x in w) and any("LLM_MODEL_SUMMARY" in x for x in w)


def test_update_llm_config_rejects_non_claude(env_file):
    import pytest
    with pytest.raises(ValueError):
        update_llm_config(summary_model="openai/gpt-4o-mini")


def test_usage_endpoint(client):
    r = client.get("/api/llm/usage")
    assert r.status_code == 200
    assert {"today", "last_7d", "last_30d", "all_time"} <= set(r.json()["periods"])
    assert client.get("/api/llm/estimate").status_code in (404, 405, 200)  # removed endpoint falls through to the SPA / 404
