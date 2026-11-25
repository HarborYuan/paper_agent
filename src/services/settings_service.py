"""
Runtime-editable settings, backed by the dotenv file (see env_file.py).

Precedence (high → low): process env var  >  env file (what the UI writes)  >  code defaults.
Saving from the UI rewrites only the touched keys in the env file and hot-applies the new
values to the in-process `settings` object, so the next run picks them up without a restart.
Secrets are never returned to clients — only "configured" + a short hint.
"""
import json
import re
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional, Tuple

from src.config import Settings, settings
from src.services import env_file as envf   # module-qualified so tests can redirect the target file

# ---- LLM task names (shared with llm.py / usage_service.py)
TASK_STAGE1 = "score_stage1"
TASK_STAGE2 = "score_stage2"
TASK_SUMMARY = "summarize"
TASK_AFFILIATION = "affiliation"
TASK_EMBED = "embed"
ALL_TASKS = [TASK_STAGE1, TASK_STAGE2, TASK_SUMMARY, TASK_AFFILIATION, TASK_EMBED]


# ---------------------------------------------------------------------------
# Schema of editable settings
# ---------------------------------------------------------------------------
@dataclass
class Field:
    key: str
    group: str
    type: str                      # str | secret | int | bool | list | enum | text
    label: str
    description: str = ""
    editable: bool = True
    options: Optional[List[str]] = None
    min: Optional[int] = None
    max: Optional[int] = None
    pattern: Optional[str] = None  # regex for str validation
    owner: Optional[str] = None    # UI hint: which card owns the field (e.g. "models")

    def to_dict(self) -> dict:
        return asdict(self)


SCHEMA: List[Field] = [
    # Provider
    Field("OPENROUTER_API_KEY", "provider", "secret", "OpenRouter API key",
          "Used for embeddings (semantic search, related papers, project recall)."),
    Field("OPENROUTER_BASE_URL", "provider", "str", "OpenRouter base URL", "OpenAI-compatible endpoint.",
          pattern=r"^https?://.+"),
    Field("CHAT_PROVIDER", "provider", "enum", "Chat models via",
          "anthropic: Claude API (Batch API, subscription credits). openrouter: OpenRouter key, real time only.",
          options=["anthropic", "openrouter"]),
    Field("ANTHROPIC_API_KEY", "provider", "secret", "Anthropic API key",
          "Claude API key from the Claude Console. Model ids starting with claude- (e.g. claude-haiku-5-5) go to the Anthropic API."),
    # Verdict pipeline
    Field("SCREEN_MIN_RELEVANCE", "pipeline", "int", "Screen: minimum relevance for review", "", min=0, max=5),
    Field("LLM_MODEL_TRANSLATE", "models", "str", "Translation model", "", owner="models"),
    Field("LLM_USE_BATCH", "pipeline", "bool", "Use the Batch API for nightly runs", "50% cheaper; results usually within an hour."),
    Field("CLAUDE_MONTHLY_BUDGET", "pipeline", "int", "Claude budget per billing cycle (USD)",
          "Estimated spend cap; stages are skipped or trimmed once it is reached.", min=0, max=10000),
    Field("CLAUDE_BUDGET_RESET_DAY", "pipeline", "int", "Claude billing cycle reset day", "Day of month the included API credits refresh.", min=1, max=28),
    Field("DEEP_READ_MAX_PER_RUN", "pipeline", "int", "Max deep reads per run", "must_read first, then by score; the rest wait for the next run.", min=0, max=200),
    Field("PUBLIC_BASE_URL", "notification", "str", "Public base URL of this app",
          "Used for reading-page links in Lark messages, e.g. http://nas:8000. Empty = no links.", pattern=r"^(https?://.+)?$"),
    Field("PROJECT_SIM_THRESHOLD", "pipeline", "str", "Project recall: cosine threshold", "Embedding similarity for a new paper to become a project candidate (voyage-4 scale, ~0.74).", pattern=r"^0?\.\d+$"),
    Field("HOT_ENABLED", "pipeline", "bool", "Hot lane", "Push popular papers (Hugging Face Daily Papers) in their own section."),
    Field("HOT_MIN_UPVOTES", "pipeline", "int", "Hot: minimum HF upvotes", "", min=1, max=10000),
    Field("HOT_MIN_STARS", "pipeline", "int", "Hot: or minimum GitHub stars", "", min=1, max=1000000),
    Field("HOT_MAX_PER_RUN", "pipeline", "int", "Hot: papers per run", "", min=0, max=50),
    Field("HOT_LOOKBACK_DAYS", "pipeline", "int", "Hot: lookback days", "", min=1, max=30),
    Field("HOT_WEB_SEARCH", "pipeline", "bool", "Hot: web search for discussion", "One Claude web_search call per run (~$0.2). Brand-new papers often have little discussion yet."),
    Field("BATCH_MAX_WAIT_MINUTES", "pipeline", "int", "Batch: max wait before real-time retry (minutes)", "", min=5, max=1440),
    # Models / thresholds (owned by the Models card)
    Field("LLM_MODEL_STAGE1", "models", "str", "Screen model", "", owner="models"),
    Field("LLM_MODEL_STAGE2", "models", "str", "Review model", "", owner="models"),
    Field("LLM_MODEL_SUMMARY", "models", "str", "Deep-read model", "", owner="models"),
    Field("STAGE2_TEXT_CHAR_LIMIT", "pipeline", "int", "Review excerpt (chars)",
          "How much of the paper the reviewer sees.", min=1000, max=300000),
    # Retrieval
    Field("EMBEDDING_MODEL", "retrieval", "str", "Embedding model",
          "Used for semantic search, related papers and topic clustering. Changing it makes existing vectors stale — run Backfill afterwards."),
    Field("EMBEDDING_DIM", "retrieval", "int", "Embedding dimensions",
          "0 = model native size. Matryoshka models (voyage-4, text-embedding-3-*) accept 256 / 512 / 1024.", min=0, max=4096),
    # Pipeline
    Field("ARXIV_CATEGORIES", "pipeline", "list", "arXiv categories", "Comma-separated, e.g. cs.CV, cs.CL, cs.AI."),
    Field("SUMMARY_LANGUAGE", "pipeline", "enum", "Summary language", "", options=["EN", "CN"]),
    Field("USER_PROFILE", "profile", "text", "User profile prompt",
          "Guides scoring (relevance tiers) and the 'Relevance to Me' summary section."),
    # Schedule
    Field("ENABLE_AUTO_UPDATE", "schedule", "bool", "Daily auto-update", "Fetch + score + summarize + notify every day."),
    Field("AUTO_UPDATE_TIME", "schedule", "str", "Auto-update time (UTC, HH:MM)", "", pattern=r"^([01]?\d|2[0-3]):[0-5]\d$"),
    # Notification
    Field("LARK_WEBHOOK_URL", "notification", "secret", "Lark (飞书) webhook URL", "Leave unconfigured to disable notifications."),
    # System (read-only)
    Field("DATABASE_URL", "system", "str", "Database URL", "Set by the container / deployment; not editable here.", editable=False),
    Field("DEV_COMMIT", "system", "bool", "DEV_COMMIT (force re-run all migrations)", "Developer flag; not editable here.", editable=False),
]
SCHEMA_BY_KEY: Dict[str, Field] = {f.key: f for f in SCHEMA}
SECRET_KEYS = [f.key for f in SCHEMA if f.type == "secret"]


def _secret_hint(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return f"…{value[-4:]}" if len(value) > 8 else "…"


def _coerce(field: Field, raw: Any) -> Any:
    """Validate + convert a client-supplied value to the python type stored on `settings`."""
    if field.type == "int":
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{field.key} must be an integer")
        if field.min is not None and v < field.min or field.max is not None and v > field.max:
            raise ValueError(f"{field.key} must be between {field.min} and {field.max}")
        return v
    if field.type == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
        raise ValueError(f"{field.key} must be true/false")
    if field.type == "list":
        if isinstance(raw, list):
            items = [str(x).strip() for x in raw]
        else:
            s = str(raw).strip()
            if s.startswith("["):
                try:
                    items = [str(x).strip() for x in json.loads(s)]
                except json.JSONDecodeError:
                    raise ValueError(f"{field.key} must be a comma-separated list")
            else:
                items = [x.strip() for x in s.split(",")]
        items = [x for x in items if x]
        if not items:
            raise ValueError(f"{field.key} must not be empty")
        return items
    if field.type == "enum":
        v = str(raw).strip()
        if field.options and v not in field.options:
            raise ValueError(f"{field.key} must be one of {field.options}")
        return v
    # str / secret / text
    v = "" if raw is None else str(raw)
    if field.type != "text":
        v = v.strip()
    if field.pattern and v and not re.match(field.pattern, v):
        raise ValueError(f"{field.key} has an invalid format")
    return v


def _to_env_string(field: Field, value: Any) -> str:
    if field.type == "bool":
        return "true" if value else "false"
    if field.type == "list":
        return json.dumps(list(value))
    return "" if value is None else str(value)


def _current(field: Field) -> Any:
    return getattr(settings, field.key, None)


def _default(field: Field) -> Any:
    f = Settings.model_fields.get(field.key)
    return f.default if f is not None else None


# ---------------------------------------------------------------------------
# Public API: whole-config view + update
# ---------------------------------------------------------------------------
def describe_settings() -> Dict[str, Any]:
    """Everything the Settings page needs. Secrets are masked."""
    path = envf.resolve_env_file_path()
    file_values = envf.read_env_values(path)
    overrides = envf.env_overrides([f.key for f in SCHEMA])
    fields = []
    for f in SCHEMA:
        cur = _current(f)
        if f.key in overrides:
            source = "env"
        elif f.key in file_values:
            source = "file"
        else:
            source = "default"
        item = f.to_dict()
        item.update({
            "source": source,
            "env_var": overrides.get(f.key),
            "default": None if f.type == "secret" else _default(f),
        })
        if f.type == "secret":
            item["value"] = None
            item["configured"] = bool(cur)
            item["hint"] = _secret_hint(cur)
        else:
            item["value"] = cur
        fields.append(item)
    return {
        "env_file": {"path": str(path), "exists": path.is_file(), "writable": envf.is_writable(path)},
        "fields": fields,
        "provider": {
            "chat": settings.CHAT_PROVIDER, "chat_key_configured": bool(settings.chat_api_key),
            "embeddings": settings.llm_provider, "embeddings_key_configured": bool(settings.llm_api_key),
        },
    }


def update_settings(values: Dict[str, Any]) -> Tuple[Dict[str, str], List[str]]:
    """
    Validate, write to the env file, hot-apply. Returns (applied {key: env_string}, warnings).
    Secrets: an empty / missing value means "leave unchanged".
    """
    applied: Dict[str, Any] = {}
    env_updates: Dict[str, str] = {}
    for key, raw in values.items():
        f = SCHEMA_BY_KEY.get(key)
        if f is None:
            raise ValueError(f"Unknown setting: {key}")
        if not f.editable:
            raise ValueError(f"{key} is read-only")
        if f.type == "secret" and (raw is None or str(raw).strip() == ""):
            continue
        val = _coerce(f, raw)
        applied[key] = val
        env_updates[key] = _to_env_string(f, val)
    if not env_updates:
        return {}, []

    path = envf.update_env_file(env_updates)            # persist first; raises if not writable
    for key, val in applied.items():               # then hot-apply
        setattr(settings, key, val)

    warnings: List[str] = []
    overrides = envf.env_overrides(applied.keys())
    for key, var in overrides.items():
        warnings.append(
            f"{key} is also set as process environment variable '{var}', which outranks the env file — "
            f"the saved value will not take effect until you remove it from the container environment."
        )
    # Mask secrets in the echo
    echo = {k: ("(updated)" if SCHEMA_BY_KEY[k].type == "secret" else v) for k, v in env_updates.items()}
    echo["_env_file"] = str(path)
    return echo, warnings


# ---------------------------------------------------------------------------
# LLM config convenience (used by the verdict pipeline)
# ---------------------------------------------------------------------------
@dataclass
class LLMConfig:
    stage1_model: str          # screen
    stage2_model: str          # review
    summary_model: str         # deep read
    score_threshold: int       # final score that counts as "push" (verdict bands put Worth Reading at 85+)
    translate_model: str = "claude-haiku-5-5"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _claude(value: Optional[str], key: str) -> str:
    """Model ids from the old OpenRouter setup (e.g. deepseek/..., anthropic/claude-...) fall back to the default."""
    v = (value or "").strip()
    return v if v.startswith("claude-") else Settings.model_fields[key].default


def get_llm_config() -> LLMConfig:
    return LLMConfig(
        stage1_model=_claude(settings.LLM_MODEL_STAGE1, "LLM_MODEL_STAGE1"),
        stage2_model=_claude(settings.LLM_MODEL_STAGE2, "LLM_MODEL_STAGE2"),
        summary_model=_claude(settings.LLM_MODEL_SUMMARY, "LLM_MODEL_SUMMARY"),
        score_threshold=int(settings.SCORE_THRESHOLD),
        translate_model=_claude(settings.LLM_MODEL_TRANSLATE, "LLM_MODEL_TRANSLATE"),
    )


def stale_model_warnings() -> List[str]:
    """Settings still holding non-Claude ids (they are ignored and the default is used)."""
    out = []
    for key in ("LLM_MODEL_STAGE1", "LLM_MODEL_STAGE2", "LLM_MODEL_SUMMARY", "LLM_MODEL_TRANSLATE"):
        v = (getattr(settings, key) or "").strip()
        if v and not v.startswith("claude-"):
            out.append(f"{key}={v} is not a Claude model; using {Settings.model_fields[key].default} instead.")
    return out


def update_llm_config(
    stage1_model: Optional[str] = None,
    stage2_model: Optional[str] = None,
    summary_model: Optional[str] = None,
    translate_model: Optional[str] = None,
) -> Tuple[LLMConfig, List[str]]:
    values: Dict[str, Any] = {}
    for key, v in (("LLM_MODEL_STAGE1", stage1_model), ("LLM_MODEL_STAGE2", stage2_model),
                   ("LLM_MODEL_SUMMARY", summary_model), ("LLM_MODEL_TRANSLATE", translate_model)):
        if v:
            if not v.strip().startswith("claude-"):
                raise ValueError(f"{key} must be a Claude model id (claude-...), got {v}")
            values[key] = v.strip()
    _, warnings = update_settings(values)
    return get_llm_config(), warnings


def llm_defaults() -> Dict[str, Any]:
    return {
        "stage1": Settings.model_fields["LLM_MODEL_STAGE1"].default,
        "stage2": Settings.model_fields["LLM_MODEL_STAGE2"].default,
        "summary": Settings.model_fields["LLM_MODEL_SUMMARY"].default,
        "translate": Settings.model_fields["LLM_MODEL_TRANSLATE"].default,
    }
