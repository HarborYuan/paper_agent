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
TASK_REPORT = "report"
TASK_EMBED = "embed"
ALL_TASKS = [TASK_STAGE1, TASK_STAGE2, TASK_SUMMARY, TASK_AFFILIATION, TASK_REPORT, TASK_EMBED]


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
          "Preferred provider. If set, requests go to OPENROUTER_BASE_URL."),
    Field("OPENROUTER_BASE_URL", "provider", "str", "OpenRouter base URL", "OpenAI-compatible endpoint.",
          pattern=r"^https?://.+"),
    Field("OPENAI_API_KEY", "provider", "secret", "OpenAI API key (legacy fallback)",
          "Used only when OPENROUTER_API_KEY is empty."),
    Field("OPENAI_BASE_URL", "provider", "str", "OpenAI base URL (legacy fallback)", "", pattern=r"^https?://.+"),
    # Models / thresholds (owned by the Models card)
    Field("LLM_MODEL_STAGE1", "models", "str", "Stage 1 model", "", owner="models"),
    Field("LLM_MODEL_STAGE2", "models", "str", "Stage 2 model", "", owner="models"),
    Field("LLM_MODEL_SUMMARY", "models", "str", "Summary model", "", owner="models"),
    Field("STAGE2_THRESHOLD", "models", "int", "Stage-2 threshold", "", min=0, max=100, owner="models"),
    Field("SCORE_THRESHOLD", "models", "int", "Score threshold", "", min=0, max=100, owner="models"),
    Field("STAGE2_TEXT_CHAR_LIMIT", "pipeline", "int", "Stage-2 text limit (chars)",
          "How much of the PDF text the stage-2 reviewer sees.", min=1000, max=200000),
    # Retrieval
    Field("EMBEDDING_MODEL", "retrieval", "str", "Embedding model",
          "Used for semantic search, related papers and topic clustering. Changing it makes existing vectors stale — run Backfill afterwards."),
    Field("EMBEDDING_DIM", "retrieval", "int", "Embedding dimensions",
          "0 = model native size. Matryoshka models (voyage-4, text-embedding-3-*) accept 256 / 512 / 1024.", min=0, max=4096),
    # Reports
    Field("LLM_MODEL_REPORT", "models", "str", "Report model", "", owner="models"),
    Field("REPORT_DAILY_ENABLED", "reports", "bool", "Daily report", "After each run: a short trend note on the papers pushed in that run (sent with the digest)."),
    Field("REPORT_WEEKLY_ENABLED", "reports", "bool", "Weekly report", "Covers the previous 7 days; generated on the weekday below."),
    Field("REPORT_MONTHLY_ENABLED", "reports", "bool", "Monthly report", "Covers the previous calendar month; generated on the 1st."),
    Field("REPORT_WEEKLY_DAY", "reports", "int", "Weekly report day (0 = Monday … 6 = Sunday, UTC)", "", min=0, max=6),
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
            "name": settings.llm_provider,
            "base_url": settings.llm_base_url,
            "key_configured": bool(settings.llm_api_key),
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
# LLM config convenience (used by worker / llm service / estimate)
# ---------------------------------------------------------------------------
@dataclass
class LLMConfig:
    stage1_model: str
    stage2_model: str
    summary_model: str
    stage2_threshold: int
    score_threshold: int
    report_model: str = "anthropic/claude-sonnet-5"

    def model_for_task(self, task: str) -> str:
        if task == TASK_STAGE2:
            return self.stage2_model
        if task == TASK_SUMMARY:
            return self.summary_model
        if task == TASK_REPORT:
            return self.report_model
        if task == TASK_EMBED:
            return settings.EMBEDDING_MODEL
        # stage-1 screening and affiliation extraction both use the cheap model
        return self.stage1_model

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def get_llm_config() -> LLMConfig:
    return LLMConfig(
        stage1_model=settings.LLM_MODEL_STAGE1,
        stage2_model=settings.LLM_MODEL_STAGE2,
        summary_model=settings.LLM_MODEL_SUMMARY,
        stage2_threshold=int(settings.STAGE2_THRESHOLD),
        score_threshold=int(settings.SCORE_THRESHOLD),
        report_model=settings.LLM_MODEL_REPORT,
    )


def update_llm_config(
    stage1_model: Optional[str] = None,
    stage2_model: Optional[str] = None,
    summary_model: Optional[str] = None,
    stage2_threshold: Optional[int] = None,
    score_threshold: Optional[int] = None,
    report_model: Optional[str] = None,
) -> Tuple[LLMConfig, List[str]]:
    values: Dict[str, Any] = {}
    if stage1_model:
        values["LLM_MODEL_STAGE1"] = stage1_model
    if report_model:
        values["LLM_MODEL_REPORT"] = report_model
    if stage2_model:
        values["LLM_MODEL_STAGE2"] = stage2_model
    if summary_model:
        values["LLM_MODEL_SUMMARY"] = summary_model
    if stage2_threshold is not None:
        values["STAGE2_THRESHOLD"] = stage2_threshold
    if score_threshold is not None:
        values["SCORE_THRESHOLD"] = score_threshold
    _, warnings = update_settings(values)
    return get_llm_config(), warnings


def llm_defaults() -> Dict[str, Any]:
    return {
        "stage1": Settings.model_fields["LLM_MODEL_STAGE1"].default,
        "stage2": Settings.model_fields["LLM_MODEL_STAGE2"].default,
        "summary": Settings.model_fields["LLM_MODEL_SUMMARY"].default,
        "report": Settings.model_fields["LLM_MODEL_REPORT"].default,
        "stage2_threshold": Settings.model_fields["STAGE2_THRESHOLD"].default,
        "score_threshold": Settings.model_fields["SCORE_THRESHOLD"].default,
    }
