from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Query
from sqlmodel import Session, select, SQLModel
from typing import List, Optional
from datetime import datetime
from contextlib import asynccontextmanager

from src.database import init_db, get_session, engine
from src.models import Paper
from src.worker import run_worker, process_single_paper
from src.services.arxiv import ArxivFetcher
import re

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        init_db()
    except Exception as e:
        print(f"DB Init Error: {e}")
    yield
    # Shutdown (if needed)

app = FastAPI(title="Paper Agent API", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# In-memory store for rate limiting: date_str -> last_run_timestamp
RESCORE_LAST_RUN = {}

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

@app.get("/")
def read_root():
    return {"message": "Welcome to Paper Agent. POST /run to start processing."}
