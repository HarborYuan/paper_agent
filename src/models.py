from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field
import json

class Paper(SQLModel, table=True):
    id: str = Field(primary_key=True)  # arXiv ID
    title: str
    authors: str  # JSON list
    summary_generic: str
    published_at: datetime
    category_primary: str
    all_categories: str  # JSON list
    pdf_url: str

    full_text: Optional[str] = Field(default=None)

    affiliations: Optional[str] = None # JSON list
    main_company: Optional[str] = None
    main_university: Optional[str] = None
    main_affiliation: Optional[str] = None

    score: Optional[int] = None            # Final score (stage 2 if it ran, else stage 1; user_score overrides)
    score_stage1: Optional[int] = None     # Cheap first-pass screening score
    score_model: Optional[str] = None      # Model that produced the final AI score
    user_score: Optional[int] = None # Manually set by user, takes precedence
    score_reason: Optional[str] = None # JSON with details ({"stage1": {...}, "stage2": {...}})
    summary_personalized: Optional[str] = None

    status: str = "NEW" # NEW, SCORED, FILTERED, SUMMARIZED, PUSHED, ERROR

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def authors_list(self) -> List[str]:
        if not self.authors:
            return []
        try:
            return json.loads(self.authors)
        except json.JSONDecodeError:
            # Fallback for malformed JSON (e.g. unescaped quotes in names like O"Regan")
            # Split by '", "' delimiter and strip surrounding brackets/quotes
            parts = self.authors.strip('[]').split('", "')
            return [p.strip('"') for p in parts if p.strip('"')]


class SchemaVersion(SQLModel, table=True):
    id: int = Field(primary_key=True, default=1)
    version: int
    updated_at: datetime = Field(default_factory=datetime.now)

class Author(SQLModel, table=True):
    name: str = Field(primary_key=True)
    bio: Optional[str] = None
    website: Optional[str] = None
    affiliation: Optional[str] = None
    is_important: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class LLMUsage(SQLModel, table=True):
    """
    One row per LLM call. Used for real-cost accounting and for estimating
    per-task token volumes when previewing a model switch.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    paper_id: Optional[str] = Field(default=None, index=True)
    task: str = Field(index=True)   # score_stage1 | score_stage2 | summarize | affiliation
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: Optional[float] = None    # USD, as reported by OpenRouter (or estimated from list price)
    cost_estimated: bool = False    # True if cost was computed from list price rather than reported
    latency_ms: Optional[int] = None
    success: bool = True
    created_at: datetime = Field(default_factory=datetime.now, index=True)
