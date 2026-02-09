import json
import asyncio
from typing import Optional, Dict, Any, List
from openai import AsyncOpenAI
from pydantic import BaseModel
from src.config import settings
from src.models import Paper
from src.services.prompt_service import prompt_service
from src.services.pdf_service import pdf_service
from src.utils import sanitize_text

class ScoreResponse(BaseModel):
    score: int
    relevance: int
    novelty: int
    clarity: int
    risk_flags: List[str]
    one_line_reason: str

class AffiliationResponse(BaseModel):
    affiliations: List[str]
    main_company: Optional[str]
    main_university: Optional[str]
    main_affiliation: Optional[str]

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
        prompt = prompt_service.render_prompt("scoring.jinja2", paper=paper, user_profile=user_profile)
        
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

    async def summarize_paper(self, paper: Paper, full_text: Optional[str] = None) -> Optional[str]:
        """
        Generate a structured summary for a high-scoring paper.
        """
        if full_text:
            full_text = sanitize_text(full_text)
            
        prompt = prompt_service.render_prompt("summarization.jinja2", paper=paper, full_text=full_text)
        
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

    async def extract_affiliations(self, paper: Paper, full_text: str) -> Optional[AffiliationResponse]:
        """
        Extract affiliations from paper text.
        We use the first ~4000 chars of full text as it usually contains the header/affiliations.
        """
        if full_text:
            full_text = sanitize_text(full_text) or ""
            
        text_snippet = full_text[:4000]
        prompt = prompt_service.render_prompt("affiliation.jinja2", text_snippet=text_snippet)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            return AffiliationResponse(**data)
        except Exception as e:
            print(f"Error extracting affiliations for {paper.id}: {e}")
            return None




async def run_llm_cycle():
    import asyncio
    from sqlmodel import Session, select, func
    from src.database import engine
    
    llm = LLMService()
    user_profile = "I am interested in AI agents, large language models, and automation."
    
    with Session(engine) as session:
        # Randomly sample 3 papers
        papers = session.exec(select(Paper).order_by(func.random()).limit(3)).all()
        print(f"Found {len(papers)} papers to process.")
        
        for paper in papers:
            print(f"Processing paper: {paper.title} ({paper.id})")
            
            # Score
            score = await llm.score_paper(paper, user_profile)
            if score:
                paper.score = score.score
                paper.score_reason = score.one_line_reason
                print(f"  - Scored: {paper.score}")
                
                # If score is high (e.g. >= 50), fetch full text
                if paper.score >= 50:
                    print("  - Fetching full text...")
                    full_text = await pdf_service.extract_text_from_url(paper.pdf_url)
                    if full_text:
                        paper.full_text = full_text
                        print(f"  - Extracted {len(full_text)} characters")
                    else:
                        print("  - Failed to extract text")

                    # Summarize
                    summary = await llm.summarize_paper(paper, full_text=paper.full_text)
                    if summary:
                        paper.summary_personalized = summary
                        print(f"  - Summarized")
            
            session.add(paper)
            session.commit()
            session.refresh(paper)
            
    print("Cycle complete.")

if __name__ == "__main__":
    asyncio.run(run_llm_cycle())
