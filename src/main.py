import os

from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from sqlmodel import Session, select, SQLModel
from typing import List, Optional
from datetime import datetime, timedelta
from collections import Counter
from contextlib import asynccontextmanager
import re

from src.database import init_db, get_session, engine
from src.models import Paper
from src.worker import run_worker, process_single_paper, resummarize_single_paper
from src.services.arxiv import ArxivFetcher
from src.logger import logger
from src.scheduler import SchedulerService



scheduler_service = SchedulerService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        init_db()
        scheduler_service.start()
    except Exception as e:
        print(f"DB/Scheduler Init Error: {e}")
    yield
    # Shutdown (if needed)
    scheduler_service.shutdown()

app = FastAPI(title="Paper Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await logger.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.disconnect(websocket)

@app.post("/run")
async def trigger_run(background_tasks: BackgroundTasks):
    """
    Trigger the paper fetching and processing cycle in the background.
    """
    background_tasks.add_task(run_worker)
    return {"message": "Paper processing cycle started in background."}

class AddPaperRequest(SQLModel):
    input: str

@app.post("/papers/add")
async def add_paper(request: AddPaperRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """
    Add a paper by arXiv ID or URL.
    """
    raw_input = request.input.strip()
    
    # Extract ID
    # Try to extract from URL first
    # https://arxiv.org/abs/2402.07320 -> 2402.07320
    # https://arxiv.org/pdf/2402.07320.pdf -> 2402.07320
    
    arxiv_id = raw_input
    if "arxiv.org" in raw_input:
        parts = raw_input.split("/")
        for part in parts:
            if part and part[0].isdigit():
                # Potential ID
                clean_part = re.sub(r'\.pdf$', '', part)
                # Check format roughly (digits.digits)
                if re.match(r'\d+\.\d+', clean_part):
                    arxiv_id = clean_part
                    break
                    
    # Remove version suffix if user pasted it manually
    arxiv_id = re.sub(r'v\d+$', '', arxiv_id)
    
    print(f"Attempting to add paper: {arxiv_id}")
    
    # Check simple existence first (optional, fetcher does it too but good for feedback)
    existing = session.get(Paper, arxiv_id)
    if existing:
        # If it exists, we can still trigger a re-process if requested? 
        # For now, just say it exists, but maybe trigger processing if it's incomplete?
        if existing.status in ["NEW", "FILTERED", "ERROR"]:
             background_tasks.add_task(process_single_paper, arxiv_id)
             return {"message": f"Paper {arxiv_id} already exists, triggered re-processing.", "id": arxiv_id}
        return {"message": f"Paper {arxiv_id} already exists.", "id": arxiv_id}

    # Fetch metadata
    fetcher = ArxivFetcher()
    papers = fetcher.fetch_paper_by_id(arxiv_id)
    
    if not papers:
        raise HTTPException(status_code=404, detail="Paper not found on arXiv")
        
    # Save to DB
    new_paper = papers[0]
    try:
        session.add(new_paper)
        session.commit()
    except Exception as e:
        # Race condition catch
        print(f"Error saving paper: {e}")
        return {"message": "Error saving paper, might already exist."}
        
    # Trigger processing
    background_tasks.add_task(process_single_paper, new_paper.id)
    
    return {"message": f"Paper {new_paper.id} added and processing started.", "paper": new_paper}

@app.get("/papers", response_model=List[Paper])
def list_papers(
    status: Optional[str] = None, 
    limit: int = 50, 
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    session: Session = Depends(get_session)
):
    query = select(Paper)
    
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
            # Filter by the whole day
            query = query.where(Paper.published_at >= datetime.combine(target_date, datetime.min.time()))
            query = query.where(Paper.published_at <= datetime.combine(target_date, datetime.max.time()))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    if status:
        query = query.where(Paper.status == status)
        
    # Always sort by score desc then published_at desc
    # query = query.order_by(Paper.published_at.desc()).limit(limit)
    # For daily view, we want high scores first
    query = query.order_by(Paper.score.desc(), Paper.published_at.desc())
    
    if not date:
        # If no date specified, apply limit (traditional view)
        query = query.limit(limit)
        
    results = session.exec(query).all()
    return results

@app.get("/papers/start-date")
def get_start_date(session: Session = Depends(get_session)):
    """
    Get the date of the earliest paper in the database.
    Used for infinite scroll termination.
    """
    statement = select(Paper.published_at).order_by(Paper.published_at.asc()).limit(1)
    result = session.exec(statement).first()
    
    if not result:
        return {"date": None}
        
    return {"date": result.date().isoformat()}

@app.get("/papers/next-date")
def get_next_date(date: str, session: Session = Depends(get_session)):
    """
    Get the next available date with papers before the given date.
    Used for skipping empty days in infinite scroll.
    """
    try:
        current_date = datetime.strptime(date, "%Y-%m-%d").date()
        # Find the max published_at that is strictly less than the start of current_date
        # We look for the latest paper BEFORE this day.
        
        # We want the date of the paper.
        query = select(Paper.published_at)\
            .where(Paper.published_at <= datetime.combine(current_date, datetime.max.time()))\
            .order_by(Paper.published_at.desc())\
            .limit(1)
            
        result = session.exec(query).first()
        
        if not result:
            return {"date": None}
            
        return {"date": result.date().isoformat()}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

@app.get("/papers/{paper_id}", response_model=Paper)
def get_paper(paper_id: str, session: Session = Depends(get_session)):
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper

# In-memory store for rate limiting
RESCORE_LAST_RUN = {}  # date_str -> last_run_timestamp
RESUMMARIZE_LAST_RUN = {}  # paper_id -> last_run_timestamp

@app.post("/papers/{paper_id}/resummarize")
async def resummarize_paper(paper_id: str, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """
    Trigger re-summarization for a single paper.
    Rate limited to once per 30 seconds per paper.
    """
    # Rate Limiting
    now = datetime.now()
    last_run = RESUMMARIZE_LAST_RUN.get(paper_id)
    if last_run:
        elapsed = (now - last_run).total_seconds()
        if elapsed < 30:
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {int(30 - elapsed)} seconds before re-summarizing this paper again."
            )

    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    RESUMMARIZE_LAST_RUN[paper_id] = now
    background_tasks.add_task(resummarize_single_paper, paper_id)
    return {"message": f"Re-summarization started for paper {paper_id}"}


@app.patch("/papers/{paper_id}/score")
async def update_paper_score(paper_id: str, score: int, session: Session = Depends(get_session)):
    """
    Manually set a score for a paper.
    This score takes precedence over AI scoring and prevents future AI re-scoring.
    """
    if score < 0 or score > 100:
        raise HTTPException(status_code=400, detail="Score must be between 0 and 100")

    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    paper.user_score = score
    paper.score = score # Update main score column for sorting/filtering
    paper.score_reason = "User assigned score"
    paper.status = "SCORED" # Ensure it shows up as scored
    
    session.add(paper)
    session.commit()
    session.refresh(paper)
    
    return paper



@app.post("/papers/re-score-date")
async def rescore_date(date: str, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """
    Trigger re-scoring for all papers on a specific date.
    Rate limited to once per 60 seconds per date.
    """
    try:
        # Rate Limiting
        now = datetime.now()
        last_run = RESCORE_LAST_RUN.get(date)
        if last_run:
            elapsed = (now - last_run).total_seconds()
            if elapsed < 60:
                raise HTTPException(
                    status_code=429, 
                    detail=f"Please wait {int(60 - elapsed)} seconds before re-scoring this date again."
                )
        
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        
        # Select all papers for this date
        query = select(Paper).where(
            Paper.published_at >= datetime.combine(target_date, datetime.min.time()),
            Paper.published_at <= datetime.combine(target_date, datetime.max.time())
        )
        papers = session.exec(query).all()
        
        if not papers:
            return {"message": f"No papers found for date {date}"}
            
        print(f"Triggering re-score for {len(papers)} papers on {date}")
        
        # Update timestamp
        RESCORE_LAST_RUN[date] = now
        
        for paper in papers:
            # Pass force_rescore=True
            background_tasks.add_task(process_single_paper, paper.id, True)
            
        return {"message": f"Started re-scoring for {len(papers)} papers on {date}"}
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

@app.get("/authors")
def list_authors(days: Optional[int] = Query(None, description="Filter papers published within the last N days"), session: Session = Depends(get_session)):
    """
    Get a ranked list of authors by paper count.
    Optionally filter to papers published within the last N days.
    """
    query = select(Paper)
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
        query = query.where(Paper.published_at >= cutoff)
    papers = session.exec(query).all()
    author_counts = Counter()
    
    for paper in papers:
        for author in paper.authors_list:
            author_counts[author] += 1
            
    # Convert to list of dicts and sort
    ranked_authors = [
        {"name": name, "count": count} 
        for name, count in author_counts.most_common()
    ]
    return ranked_authors

@app.get("/authors/{author_name}/papers", response_model=List[Paper])
def list_papers_by_author(author_name: str, days: Optional[int] = Query(None, description="Filter papers published within the last N days"), session: Session = Depends(get_session)):
    """
    Get all papers for a specific author.
    Optionally filter to papers published within the last N days.
    """
    search_term = f'"{author_name}"'
    query = select(Paper).where(Paper.authors.contains(search_term))
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
        query = query.where(Paper.published_at >= cutoff)
    papers = session.exec(query).all()
    
    # Refine filter to ensure exact match (not a substring of another author)
    filtered_papers = [
        p for p in papers if author_name in p.authors_list
    ]
    
    # Sort by score desc, published_at desc
    filtered_papers.sort(key=lambda x: (x.score or 0, x.published_at), reverse=True)
    
    return filtered_papers



@app.get("/health")
def read_root():
    return {"message": "Welcome to Paper Agent. POST /run to start processing.", "docs": "/docs"}



# Serve frontend static files if they exist (Docker/Deployment mode)
# This mimics the behavior of nginx serving the frontend
frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(frontend_dist):
    # Mount /assets separately so Vite-built JS/CSS/images are served directly
    assets_dir = os.path.join(frontend_dist, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # SPA catch-all: any route not matched by the API or /assets
    # serves the frontend index.html so client-side routing works on refresh
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # If the requested file exists on disk, serve it (e.g. favicon, manifest)
        file_path = os.path.join(frontend_dist, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        # Otherwise, serve index.html for client-side routing
        return FileResponse(os.path.join(frontend_dist, "index.html"))
