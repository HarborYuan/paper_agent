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
    
    score: Optional[int] = None
    user_score: Optional[int] = None # Manually set by user, takes precedence
    score_reason: Optional[str] = None # JSON with details
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

