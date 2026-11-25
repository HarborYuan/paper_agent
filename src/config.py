from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///data/paper_agent.db"

    # ---- OpenRouter: embeddings (always) and the chat models when CHAT_PROVIDER = "openrouter" ----
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # Claude models (editable from the Settings page, which writes the env file and hot-applies them).
    LLM_MODEL_STAGE1: str = "claude-haiku-5-5"     # screen: title + abstract -> relevance tier
    LLM_MODEL_STAGE2: str = "claude-sonnet-5-5"    # review: abstract + first part -> verdict
    LLM_MODEL_SUMMARY: str = "claude-sonnet-5-5"   # deep read: whole paper -> final verdict, TL;DR, notes
    SCORE_THRESHOLD: int = 85         # final score that counts as a push (Must Read 92-99, Worth Reading 85-91)
    STAGE2_TEXT_CHAR_LIMIT: int = 20000       # excerpt shown to the reviewer

    # ---- Pipeline (Claude API direct) ----
    # screen (relevance tier) -> review (verdict + affiliations) -> deep read (final verdict, TL;DR,
    # paragraph notes, claim flags) + translation. See services/verdict_pipeline.py.
    ANTHROPIC_API_KEY: str | None = None
    CHAT_PROVIDER: str = "anthropic"   # "anthropic" (Claude API, Batch API available) | "openrouter" (real time only)
    SCREEN_MIN_RELEVANCE: int = 4      # screen relevance needed to go on to review
    LLM_MODEL_TRANSLATE: str = "claude-haiku-5-5"
    LLM_USE_BATCH: bool = True         # nightly runs go through the Message Batches API (50% off)
    BATCH_MAX_WAIT_MINUTES: int = 240  # after this, unfinished batch requests are retried in real time
    FIGURE_DIR: str | None = None      # PDF crops of broken figures/tables; default: "figures" next to the SQLite DB
    # Spend guard for the Claude API key (list-price estimate from the llmusage table, batch discount included).
    CLAUDE_MONTHLY_BUDGET: int = 80      # USD per billing cycle; stages are skipped once it is used up
    CLAUDE_BUDGET_RESET_DAY: int = 1       # day of month the billing cycle (and the included credits) resets
    DEEP_READ_MAX_PER_RUN: int = 12        # nightly cap on deep reads (must_read first, then by score)
    PROJECT_SIM_THRESHOLD: float = 0.74    # cosine (voyage-4) for a new paper to be a project candidate
    PUBLIC_BASE_URL: str | None = None     # e.g. http://nas:8000 — links in Lark messages to /read and /picks
    # Hot lane: popular papers (Hugging Face Daily Papers) pushed in their own section, relevant or not
    HOT_ENABLED: bool = True
    HOT_LOOKBACK_DAYS: int = 7
    HOT_MIN_UPVOTES: int = 50
    HOT_MIN_STARS: int = 500
    HOT_MAX_PER_RUN: int = 5
    HOT_WEB_SEARCH: bool = False           # one Claude web_search call per run (~$0.2): what people say about them

    # Embeddings (semantic search / related papers / topic clustering). Served through the same
    # OpenAI-compatible /embeddings endpoint (OpenRouter lists them under /embeddings/models).
    EMBEDDING_MODEL: str = "voyageai/voyage-4"
    EMBEDDING_DIM: int = 512          # 0 = model's native size; Matryoshka models accept 256/512/1024
    EMBEDDING_BATCH_SIZE: int = 64
    EMBED_CATCHUP_PER_RUN: int = 5000     # nightly: embed up to this many papers still missing a vector


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
        """Key for the OpenAI-compatible endpoints (embeddings, model catalog): OpenRouter."""
        return self.OPENROUTER_API_KEY

    @property
    def llm_base_url(self) -> str:
        return self.OPENROUTER_BASE_URL

    @property
    def chat_api_key(self) -> str | None:
        """Key for the chat models of the selected CHAT_PROVIDER."""
        return self.OPENROUTER_API_KEY if self.CHAT_PROVIDER == "openrouter" else self.ANTHROPIC_API_KEY

    @property
    def chat_key_name(self) -> str:
        return "OPENROUTER_API_KEY" if self.CHAT_PROVIDER == "openrouter" else "ANTHROPIC_API_KEY"

    @property
    def figure_dir(self) -> str:
        """FIGURE_DIR, else a "figures" folder beside the SQLite file (so Docker keeps it under /config)."""
        if self.FIGURE_DIR:
            return self.FIGURE_DIR
        import os
        url = self.DATABASE_URL
        if url.startswith("sqlite:///"):
            return os.path.join(os.path.dirname(url[len("sqlite:///"):]) or ".", "figures")
        return "data/figures"

    @property
    def llm_provider(self) -> str:
        return "openrouter"

settings = Settings()
