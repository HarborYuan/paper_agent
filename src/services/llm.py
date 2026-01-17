import json
from typing import Optional, Dict, Any, List
from openai import AsyncOpenAI
from pydantic import BaseModel
from src.config import settings
from src.models import Paper

class ScoreResponse(BaseModel):
    score: int
    relevance: int
    novelty: int
    clarity: int
    risk_flags: List[str]
    one_line_reason: str

class LLMService:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL
        )
        self.model = "gpt-4o-mini" 

    async def score_paper(self, paper: Paper, user_profile: str) -> Optional[ScoreResponse]:
        """
        Score a paper based on title, abstract, and user profile.
        """
        prompt = f"""
        You are a research paper screening assistant.
        
        MY PROFILE/INTERESTS:
        {user_profile}
        
        PAPER TO EVALUATE:
        Title: {paper.title}
        Abstract: {paper.summary_generic}
        Category: {paper.category_primary}
        
        TASK:
        Evaluate this paper based on my interests.
        Return a JSON object with:
        - score (0-100): Overall suitability. <50 means irrelevant.
        - relevance (0-5): Direct relevance to my profile.
        - novelty (0-5)
        - clarity (0-5)
        - risk_flags (list of strings, e.g. "no code", "incremental")
        - one_line_reason (string)
        """
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            return ScoreResponse(**data)
        except Exception as e:
            print(f"Error scoring paper {paper.id}: {e}")
            return None

    async def summarize_paper(self, paper: Paper) -> Optional[str]:
        """
        Generate a structured summary for a high-scoring paper.
        """
        prompt = f"""
        You are a helpful research assistant.
        Please summarize the following paper for me.
        
        Target Audience: A researcher in this field.
        
        Format Requirement (Markdown):
        ## TL;DR
        (One sentence)
        
        ## Contribution
        - (Point 1)
        - (Point 2)
        
        ## Methodology
        (Concise explanation of the key technical approach)
        
        ## Experiments
        (Key results and benchmarks)
        
        ## Limitations
        (Any mentioned or apparent limitations)
        
        PAPER TEXT:
        Title: {paper.title}
        Abstract: {paper.summary_generic}
        """
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error summarizing paper {paper.id}: {e}")
            return None
