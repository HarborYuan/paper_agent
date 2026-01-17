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
    pdf_url: str
    
    score: Optional[int] = None
    score_reason: Optional[str] = None # JSON with details
    summary_personalized: Optional[str] = None
    
    status: str = "NEW" # NEW, SCORED, FILTERED, SUMMARIZED, PUSHED, ERROR
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def authors_list(self) -> List[str]:
        return json.loads(self.authors) if self.authors else []
