"""
Tests for the env-file backed settings layer: lossless rewrite, secrets masking,
validation, hot-apply, env-var override warnings, scheduler reload hook.
"""
import io
import json
import pytest
from dotenv import dotenv_values

from src.services import env_file as ef
from src.services.settings_service import describe_settings, update_settings


# ---------------------------------------------------------------------------
# env_file.py
# ---------------------------------------------------------------------------
# Note: inside SAMPLE, \\" is the dotenv escape for a literal quote (file text: \"quoted\").
SAMPLE = '''# Paper Agent config
DATABASE_URL="sqlite:////config/paper_agent.db"
OPENAI_API_KEY=sk-legacy   # keep me
ARXIV_CATEGORIES=["cs.CV","cs.CL","cs.AI"]

# profile spans lines
USER_PROFILE="I am a PhD researcher.
## Core interests
- tokenizers, \\"quoted\\""
ENABLE_AUTO_UPDATE=true
AUTO_UPDATE_TIME="04:00" # UTC
'''


def _vals(text):
    return dotenv_values(stream=io.StringIO(text))


def test_sample_parses_as_expected():
    vals = _vals(SAMPLE)
    assert vals["USER_PROFILE"] == 'I am a PhD researcher.\n## Core interests\n- tokenizers, "quoted"'


def test_render_updated_preserves_everything_else():
    new_profile = 'new\nprofile "q" \\ back'
    out = ef.render_updated(SAMPLE, {"AUTO_UPDATE_TIME": "05:30", "USER_PROFILE": new_profile})
    # untouched lines identical
    assert '# Paper Agent config\n' in out
    assert 'OPENAI_API_KEY=sk-legacy   # keep me\n' in out
    assert 'ARXIV_CATEGORIES=["cs.CV","cs.CL","cs.AI"]\n' in out
    assert '# profile spans lines\n' in out
    vals = _vals(out)
    assert vals["AUTO_UPDATE_TIME"] == "05:30"
    assert vals["USER_PROFILE"] == new_profile
    assert vals["OPENAI_API_KEY"] == "sk-legacy"
    assert vals["ENABLE_AUTO_UPDATE"] == "true"
    # order preserved: USER_PROFILE still before ENABLE_AUTO_UPDATE
    assert out.index("USER_PROFILE=") < out.index("ENABLE_AUTO_UPDATE=")
    # idempotent: applying the same update again changes nothing
    assert ef.render_updated(out, {"AUTO_UPDATE_TIME": "05:30", "USER_PROFILE": new_profile}) == out


def test_render_updated_appends_missing_and_dedupes():
    src = 'A=1\nB=2\nA=3\n'
    out = ef.render_updated(src, {"A": "9", "NEW_KEY": "x y"})
    vals = _vals(out)
    assert vals["A"] == "9" and vals["B"] == "2" and vals["NEW_KEY"] == "x y"
    assert out.count("A=") == 1
    assert "# Written by Paper Agent Settings page" in out


def test_update_env_file_atomic_and_creates(tmp_path):
    path = tmp_path / "sub" / ".env"
    ef.update_env_file({"FOO": "bar"}, path)
    assert path.read_text().strip().endswith('FOO="bar"')
    ef.update_env_file({"FOO": "baz", "N": "1"}, path)
    assert dotenv_values(path) == {"FOO": "baz", "N": "1"}
    assert not list(tmp_path.joinpath("sub").glob(".env.*.tmp"))  # no temp leftovers


def test_encode_value_roundtrip():
    weird = 'a "b" c\\d\n\ttab # not comment $X'
    assert _vals(f"K={ef.encode_value(weird)}\n")["K"] == weird


# ---------------------------------------------------------------------------
# settings_service + endpoints (env_file fixture from conftest)
# ---------------------------------------------------------------------------
def test_describe_masks_secrets(env_file):
    # the live settings object is the source of truth; load the secret through the normal path
    update_settings({"OPENROUTER_API_KEY": "sk-or-test-secret-1234"})
    desc = describe_settings()
    by_key = {f["key"]: f for f in desc["fields"]}
    sec = by_key["OPENROUTER_API_KEY"]
    assert sec["type"] == "secret" and sec["value"] is None
    assert sec["configured"] is True and sec["hint"] == "…1234"
    assert sec["default"] is None
    # the secret never appears anywhere in the payload
    assert "sk-or-test-secret-1234" not in json.dumps(desc)
    assert desc["env_file"]["path"] == str(env_file)
    assert by_key["LLM_MODEL_STAGE1"]["source"] == "file"
    assert by_key["DATABASE_URL"]["editable"] is False


def test_update_settings_validates_and_hot_applies(env_file):
    from src.config import settings as app_settings
    for bad in ({"STAGE2_THRESHOLD": 500}, {"AUTO_UPDATE_TIME": "25:99"}, {"SUMMARY_LANGUAGE": "FR"},
                {"DATABASE_URL": "sqlite:///x.db"}, {"NOPE": 1}):
        with pytest.raises(ValueError):
            update_settings(bad)

    applied, warnings = update_settings({
        "ARXIV_CATEGORIES": "cs.CV, cs.LG",
        "ENABLE_AUTO_UPDATE": "false",
        "SUMMARY_LANGUAGE": "CN",
        "USER_PROFILE": "line1\nline2",
        "OPENROUTER_API_KEY": "",          # empty secret -> unchanged
    })
    assert warnings == []
    assert "OPENROUTER_API_KEY" not in applied
    # hot-applied with proper types
    assert app_settings.ARXIV_CATEGORIES == ["cs.CV", "cs.LG"]
    assert app_settings.ENABLE_AUTO_UPDATE is False
    assert app_settings.SUMMARY_LANGUAGE == "CN"
    assert app_settings.USER_PROFILE == "line1\nline2"
    # persisted in a form pydantic-settings reads back identically
    vals = dotenv_values(env_file)
    assert json.loads(vals["ARXIV_CATEGORIES"]) == ["cs.CV", "cs.LG"]
    assert vals["ENABLE_AUTO_UPDATE"] == "false"
    assert vals["USER_PROFILE"] == "line1\nline2"
    assert vals["OPENROUTER_API_KEY"] == "sk-or-test-secret-1234"   # untouched

    # secret update is applied but echoed masked
    applied, _ = update_settings({"OPENROUTER_API_KEY": "sk-or-new-key-9999"})
    assert applied["OPENROUTER_API_KEY"] == "(updated)"
    assert app_settings.OPENROUTER_API_KEY == "sk-or-new-key-9999"
    assert describe_settings()["fields"][0]["hint"] == "…9999"


def test_env_var_override_warning(env_file, monkeypatch):
    monkeypatch.setenv("SCORE_THRESHOLD", "90")
    applied, warnings = update_settings({"SCORE_THRESHOLD": 80})
    assert applied["SCORE_THRESHOLD"] == "80"
    assert warnings and "SCORE_THRESHOLD" in warnings[0]
    f = next(x for x in describe_settings()["fields"] if x["key"] == "SCORE_THRESHOLD")
    assert f["source"] == "env" and f["env_var"] == "SCORE_THRESHOLD"


def test_settings_endpoints(client, env_file):
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "fields" in data and data["env_file"]["path"] == str(env_file)
    assert "sk-or-test-secret-1234" not in r.text
    assert "scheduler" in data

    r = client.put("/api/settings", json={"values": {"SCORE_THRESHOLD": 88, "LARK_WEBHOOK_URL": "https://hook.example/abc"}})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["applied"]["SCORE_THRESHOLD"] == "88"
    assert data["applied"]["LARK_WEBHOOK_URL"] == "(updated)"
    assert "hook.example" not in json.dumps(data["fields"])
    lark = next(f for f in data["fields"] if f["key"] == "LARK_WEBHOOK_URL")
    assert lark["configured"] is True

    assert client.put("/api/settings", json={"values": {"SCORE_THRESHOLD": 101}}).status_code == 400

    r = client.put("/api/settings/profile", json={"profile": "## New profile\n- x"})
    assert r.status_code == 200 and r.json()["profile"] == "## New profile\n- x"
    assert client.get("/api/profile").json()["profile"] == "## New profile\n- x"
    assert dotenv_values(env_file)["USER_PROFILE"] == "## New profile\n- x"


def test_schedule_change_reloads_scheduler(client, env_file, monkeypatch):
    from unittest.mock import AsyncMock
    import src.main as main_mod
    reload_mock = AsyncMock()
    monkeypatch.setattr(main_mod.scheduler_service, "reload", reload_mock)
    r = client.put("/api/settings", json={"values": {"AUTO_UPDATE_TIME": "03:30", "ENABLE_AUTO_UPDATE": True}})
    assert r.status_code == 200, r.text
    reload_mock.assert_awaited_once()
    client.put("/api/settings", json={"values": {"SUMMARY_LANGUAGE": "EN"}})
    assert reload_mock.await_count == 1   # not called for unrelated keys
