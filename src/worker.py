import asyncio
import json

from sqlmodel import Session, select
from src.database import engine
from src.config import settings
from src.models import Paper, Author
from src.services.arxiv import ArxivFetcher
from src.services.llm import LLMService
from src.services.notifier import get_notifier
from src.services.pdf_service import pdf_service
from src.utils import sanitize_text
from src.logger import logger

SCORE_THRESHOLD = 85
CONCURRENCY_LIMIT = 5
PAPER_SYNC_LIMIT = 500

async def process_paper_score(sem: asyncio.Semaphore, llm: LLMService, paper: Paper):
    async with sem:
        await logger.log(f"Scoring paper: {paper.id}")

        # Check for user score first
        if paper.user_score is not None:
             await logger.log(f"  - Skipping AI scoring for {paper.id}, user score present: {paper.user_score}")
             return

        score_data = await llm.score_paper(paper, settings.USER_PROFILE)
        
        # Check for important authors
        is_important_author = False
        try:
            with Session(engine) as session:
                # Get authors from paper
                authors = paper.authors_list
                if authors:
                    # Check if any is marked important
                    statement = select(Author).where(
                        Author.name.in_(authors), 
                        Author.is_important == True
                    )
                    important_authors = session.exec(statement).all()
                    if important_authors:
                        is_important_author = True
                        await logger.log(f"  - Found important author(s): {[a.name for a in important_authors]}")
        except Exception as e:
            await logger.log(f"  - Error checking important authors: {e}")

        if is_important_author and score_data.score < 90:
            await logger.log(f"  - Boosting score from {score_data.score} to 90 due to important author.")
            score_data.score = 90

        
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
        await logger.log(f"Summarizing paper: {paper.id}")
        
        # Need to re-fetch paper from DB or just use passed object? Passed object is detached or from session?
        # Better to fetch full text here.
        full_text = None
        if paper.pdf_url:
            full_text = await pdf_service.extract_text_from_url(paper.pdf_url)
        
        affiliations = None
        if full_text:
            await logger.log(f"  - Extracted full text for {paper.id}")
            # Extract affiliations
            aff_data = await llm.extract_affiliations(paper, full_text)
            if aff_data:
                await logger.log(f"  - Affiliations: {aff_data.main_affiliation}")
            # Summarize with full text
            summary = await llm.summarize_paper(paper, full_text=full_text)
        else:
            await logger.log(f"  - Full text not available for {paper.id}")
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
    await logger.log("Starting worker cycle...")
    
    # 1. Fetch
    fetcher = ArxivFetcher(categories=settings.ARXIV_CATEGORIES)
    # 2000 for MVP; usually good enough
    fetched_papers = await asyncio.to_thread(fetcher.fetch_papers, max_results=PAPER_SYNC_LIMIT)
    new_papers = fetcher.filter_new_papers(fetched_papers)
    fetcher.save_papers(new_papers)
    
    llm = LLMService()
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    # 2. Score NEW papers
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "NEW")
        papers_to_score = session.exec(statement).all()
        
    if papers_to_score:
        await logger.log(f"Scoring {len(papers_to_score)} papers...")
        await asyncio.gather(*[process_paper_score(sem, llm, p) for p in papers_to_score])
    
    # 3. Summarize SCORED papers (High score)
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "SCORED") # Filtering handled in scoring step
        papers_to_summarize = session.exec(statement).all()
        
    if papers_to_summarize:
        await logger.log(f"Summarizing {len(papers_to_summarize)} papers...")
        await asyncio.gather(*[process_paper_summary(sem, llm, p) for p in papers_to_summarize])
        
    # 4. Notify
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "SUMMARIZED")
        papers_to_notify = session.exec(statement).all()
        
    if papers_to_notify:
        await logger.log(f"Notifying {len(papers_to_notify)} papers...")
        notifier = get_notifier()
        if notifier:
            # Group papers by published date
            from collections import defaultdict
            by_date = defaultdict(list)
            for p in papers_to_notify:
                date_key = p.published_at.strftime("%Y-%m-%d")
                by_date[date_key].append(p)
            
            # Sort dates (newest first), sort papers within each date by score desc
            messages = []
            for date_key in sorted(by_date.keys(), reverse=True):
                date_papers = sorted(by_date[date_key], key=lambda x: x.score or 0, reverse=True)
                digest = f"📅 {date_key}  ({len(date_papers)} papers)\n"
                digest += "─" * 30 + "\n\n"
                for i, p in enumerate(date_papers, 1):
                    aff = f" | {p.main_affiliation}" if p.main_affiliation else ""
                    digest += f"{i}. {p.title}\n"
                    digest += f"   ⭐ Score: {p.score}{aff}\n"
                    digest += f"   🔗 {p.pdf_url}\n"
                    if p.summary_personalized:
                        tldr = p.summary_personalized[:150].replace("\n", " ")
                        digest += f"   💡 {tldr}...\n"
                    digest += "\n"
                messages.append(digest)
            
            success = await notifier.send_messages(messages)
            
            if success:
                with Session(engine) as session:
                    for p in papers_to_notify:
                        db_p = session.get(Paper, p.id)
                        db_p.status = "PUSHED"
                        session.add(db_p)
                    session.commit()
        else:
            await logger.log("No notifier configured.")


async def process_single_paper(paper_id: str, force_rescore: bool = False):
    """
    Process a single paper: score -> (if good) summarize -> notify (if configured)
    """
    await logger.log(f"Processing single paper: {paper_id} (force_rescore={force_rescore})")
    
    # Check if paper exists
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
    
    if not paper:
        await logger.log(f"Paper {paper_id} not found in DB.")
        return

    llm = LLMService()
    sem = asyncio.Semaphore(1) # processed singly, so limit doesn't matter much
    
    # 1. Score
    # Force status to NEW to ensure scoring runs? Or just run it.
    if force_rescore or paper.status == "NEW" or paper.status == "FILTERED": 
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


async def resummarize_single_paper(paper_id: str):
    """
    Force re-summarize a single paper regardless of its current status.
    Always re-runs scoring and summarization, skipping notification.
    """
    await logger.log(f"Force re-summarizing paper: {paper_id}")

    with Session(engine) as session:
        paper = session.get(Paper, paper_id)

    if not paper:
        await logger.log(f"Paper {paper_id} not found in DB.")
        return

    llm = LLMService()
    sem = asyncio.Semaphore(1)

    # 1. Re-score
    if paper.user_score is None:
        await process_paper_score(sem, llm, paper)
    else:
        await logger.log(f"  - Skipping re-scoring for {paper.id}, user score present: {paper.user_score}")

    # Reload after scoring
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
    if not paper:
        return

    # 2. Always summarize (regardless of score)
    await process_paper_summary(sem, llm, paper)

    await logger.log(f"Finished re-summarizing paper: {paper_id}")


if __name__ == "__main__":
    from src.database import init_db
    try:
        init_db()
    except Exception as e:
        print(f"DB Init Error: {e}")
    asyncio.run(run_worker())
