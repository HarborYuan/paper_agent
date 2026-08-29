from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///data/paper_agent.db"

    # ---- LLM provider (OpenRouter by default; any OpenAI-compatible endpoint works) ----
    # Preferred: OPENROUTER_API_KEY. Legacy OPENAI_API_KEY / OPENAI_BASE_URL are still honored
    # as a fallback so existing deployments keep working.
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = "https://api.openai.com/v1"

    # Default models (OpenRouter ids). Editable at runtime from the Settings page, which writes the
    # new values back to the env file and hot-applies them (see services/settings_service.py).
    LLM_MODEL_STAGE1: str = "openai/gpt-4o-mini"          # cheap screening on title+abstract
    LLM_MODEL_STAGE2: str = "anthropic/claude-sonnet-5"    # careful review w/ intro text
    LLM_MODEL_SUMMARY: str = "openai/gpt-4o-mini"         # full-text summarization
    STAGE2_THRESHOLD: int = 60        # stage-1 score needed to trigger stage-2 review
    SCORE_THRESHOLD: int = 85         # final score needed to summarize + notify
    STAGE2_TEXT_CHAR_LIMIT: int = 20000       # first-pass excerpt shown to the stage-2 reviewer
    STAGE2_DEEP_TEXT_CHAR_LIMIT: int = 120000  # extended excerpt when the reviewer asks to read on

    # Embeddings (semantic search / related papers / topic clustering). Served through the same
    # OpenAI-compatible /embeddings endpoint (OpenRouter lists them under /embeddings/models).
    EMBEDDING_MODEL: str = "voyageai/voyage-4"
    EMBEDDING_DIM: int = 512          # 0 = model's native size; Matryoshka models accept 256/512/1024
    EMBEDDING_BATCH_SIZE: int = 64

    # Reports (LLM-written trend summaries over the selected papers; pushed after the daily digest)
    LLM_MODEL_REPORT: str = "anthropic/claude-sonnet-5"
    REPORT_DAILY_ENABLED: bool = True      # one per run, covering the papers pushed in that run
    REPORT_WEEKLY_ENABLED: bool = True     # on REPORT_WEEKLY_DAY, covering the previous 7 days
    REPORT_MONTHLY_ENABLED: bool = True    # on the 1st, covering the previous calendar month
    REPORT_WEEKLY_DAY: int = 0             # 0 = Monday … 6 = Sunday (UTC)

    # Notification (Lark / 飞书)
    LARK_WEBHOOK_URL: str | None = None
    ARXIV_CATEGORIES: List[str] = ["cs.CV", "cs.CL", "cs.AI"]

    # Language; CN / EN currently
    SUMMARY_LANGUAGE: str = "EN"

    # Auto Update
    ENABLE_AUTO_UPDATE: bool = False
    DEV_COMMIT: bool = False
    AUTO_UPDATE_TIME: str = "04:00" # UTC

    USER_PROFILE: str = """
    I am interested in Computer Vision and Multi-modal Learning.
    Keywords: Video Understanding, VLM, Segmentation, Reasoning, 3D.
    Avoid: Network Security, Pure Math, HCI.
    """

    model_config = SettingsConfigDict(
        # Load from /config/.env (Docker volume) first, then local .env
        env_file=["/config/.env", ".env"],
        env_file_encoding='utf-8',
        extra="ignore"
    )

    # ---- Derived helpers ----
    @property
    def llm_api_key(self) -> str | None:
        return self.OPENROUTER_API_KEY or self.OPENAI_API_KEY

    @property
    def llm_base_url(self) -> str:
        if self.OPENROUTER_API_KEY:
            return self.OPENROUTER_BASE_URL
        return self.OPENAI_BASE_URL or self.OPENROUTER_BASE_URL

    @property
    def llm_provider(self) -> str:
        return "openrouter" if self.OPENROUTER_API_KEY or "openrouter.ai" in (self.llm_base_url or "") else "openai-compatible"

settings = Settings()
