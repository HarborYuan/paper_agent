import asyncio
import json
from typing import List
from sqlmodel import Session, select
from src.database import engine
from src.config import settings
from src.models import Paper
from src.services.arxiv import ArxivFetcher
from src.services.llm import LLMService
from src.services.notifier import get_notifier
from src.services.pdf_service import pdf_service
from src.utils import sanitize_text

SCORE_THRESHOLD = 85
CONCURRENCY_LIMIT = 5
PAPER_SYNC_LIMIT = 500

async def process_paper_score(sem: asyncio.Semaphore, llm: LLMService, paper: Paper):
    async with sem:
        print(f"Scoring paper: {paper.id}")
        score_data = await llm.score_paper(paper, settings.USER_PROFILE)
        
        with Session(engine) as session:
            db_paper = session.get(Paper, paper.id)
            if db_paper and score_data:
                db_paper.score = score_data.score
                db_paper.score_reason = sanitize_text(score_data.model_dump_json())
                if score_data.score < SCORE_THRESHOLD:
                    db_paper.status = "FILTERED"
                else:
                    db_paper.status = "SCORED"
                session.add(db_paper)
                session.commit()

async def process_paper_summary(sem: asyncio.Semaphore, llm: LLMService, paper: Paper):
    async with sem:
        print(f"Summarizing paper: {paper.id}")
        
        # Need to re-fetch paper from DB or just use passed object? Passed object is detached or from session?
        # Better to fetch full text here.
        full_text = None
        if paper.pdf_url:
            full_text = await pdf_service.extract_text_from_url(paper.pdf_url)
        
        affiliations = None
        if full_text:
            print(f"  - Extracted full text for {paper.id}")
            # Extract affiliations
            aff_data = await llm.extract_affiliations(paper, full_text)
            if aff_data:
                print(f"  - Affiliations: {aff_data.main_affiliation}")
            # Summarize with full text
            summary = await llm.summarize_paper(paper, full_text=full_text)
        else:
            print(f"  - Full text not available for {paper.id}")
            summary = await llm.summarize_paper(paper)
        
        with Session(engine) as session:
            db_paper = session.get(Paper, paper.id)
            if db_paper:
                if full_text:
                    db_paper.full_text = sanitize_text(full_text)
                
                if aff_data:
                    db_paper.affiliations = sanitize_text(json.dumps(aff_data.affiliations))
                    db_paper.main_company = sanitize_text(aff_data.main_company)
                    db_paper.main_university = sanitize_text(aff_data.main_university)
                    db_paper.main_affiliation = sanitize_text(aff_data.main_affiliation)
                
                if summary:
                    db_paper.summary_personalized = sanitize_text(summary)
                    db_paper.status = "SUMMARIZED"
                
                session.add(db_paper)
                session.commit()

async def run_worker():
    print("Starting worker cycle...")
    
    # 1. Fetch
    fetcher = ArxivFetcher(categories=settings.ARXIV_CATEGORIES)
    # 2000 for MVP; usually good enough
    fetched_papers = fetcher.fetch_papers(max_results=PAPER_SYNC_LIMIT)
    new_papers = fetcher.filter_new_papers(fetched_papers)
    fetcher.save_papers(new_papers)
    
    llm = LLMService()
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    # 2. Score NEW papers
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "NEW")
        papers_to_score = session.exec(statement).all()
        
    if papers_to_score:
        print(f"Scoring {len(papers_to_score)} papers...")
        await asyncio.gather(*[process_paper_score(sem, llm, p) for p in papers_to_score])
    
    # 3. Summarize SCORED papers (High score)
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "SCORED") # Filtering handled in scoring step
        papers_to_summarize = session.exec(statement).all()
        
    if papers_to_summarize:
        print(f"Summarizing {len(papers_to_summarize)} papers...")
        await asyncio.gather(*[process_paper_summary(sem, llm, p) for p in papers_to_summarize])
        
    # 4. Notify
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "SUMMARIZED")
        papers_to_notify = session.exec(statement).all()
        
    if papers_to_notify:
        print(f"Notifying {len(papers_to_notify)} papers...")
        notifier = get_notifier()
        if notifier:
            digest = f"*Daily Paper Digest ({len(papers_to_notify)} papers)*\n\n"
            for p in papers_to_notify:
                digest += f"📄 *{p.title}* (Score: {p.score})\n"
                digest += f"[PDF]({p.pdf_url})\n"
                digest += f"tl;dr: {p.summary_personalized[:200]}...\n\n" # Truncate for preview
            
            success = await notifier.send_message(digest)
            
            if success:
                # Update status
                with Session(engine) as session:
                    for p in papers_to_notify:
                        # Re-fetch to attach to session
                        db_p = session.get(Paper, p.id)
                        db_p.status = "PUSHED"
                        session.add(db_p)
                    session.commit()
        else:
            print("No notifier configured.")


async def process_single_paper(paper_id: str):
    """
    Process a single paper: score -> (if good) summarize -> notify (if configured)
    """
    print(f"Processing single paper: {paper_id}")
    
    # Check if paper exists
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
    
    if not paper:
        print(f"Paper {paper_id} not found in DB.")
        return

    llm = LLMService()
    sem = asyncio.Semaphore(1) # processed singly, so limit doesn't matter much
    
    # 1. Score
    # Force status to NEW to ensure scoring runs? Or just run it.
    if paper.status == "NEW" or paper.status == "FILTERED": 
        # Re-score if needed
        await process_paper_score(sem, llm, paper)
    
    # Reload to check score
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
        
    if not paper: return

    # 2. Summarize
    if paper.status == "SCORED" or (paper.score and paper.score >= SCORE_THRESHOLD and not paper.summary_personalized):
        await process_paper_summary(sem, llm, paper)
        
    # Reload
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
        
    if not paper: return

    # 3. Notify
    if paper.status == "SUMMARIZED":
        notifier = get_notifier()
        if notifier:
            digest = f"*New Paper Added:*\n\n"
            digest += f"📄 *{paper.title}* (Score: {paper.score})\n"
            digest += f"[PDF]({paper.pdf_url})\n"
            digest += f"tl;dr: {paper.summary_personalized[:200]}...\n\n"
            
            success = await notifier.send_message(digest)
            
            if success:
                with Session(engine) as session:
                    db_p = session.get(Paper, paper.id)
                    db_p.status = "PUSHED"
                    session.add(db_p)
                    session.commit()


if __name__ == "__main__":
    from src.database import init_db
    try:
        init_db()
    except Exception as e:
        print(f"DB Init Error: {e}")
    asyncio.run(run_worker())
