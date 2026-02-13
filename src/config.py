from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///data/paper_agent.db"
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = "https://api.openai.com/v1"
    
    # Notification (Lark / 飞书)
    LARK_WEBHOOK_URL: str | None = None
    ARXIV_CATEGORIES: List[str] = ["cs.CV", "cs.CL", "cs.AI"]
    
    # Auto Update
    ENABLE_AUTO_UPDATE: bool = False
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

settings = Settings()
