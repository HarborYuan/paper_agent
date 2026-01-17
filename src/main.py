from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends
from sqlmodel import Session, select
from typing import List, Optional
from contextlib import asynccontextmanager

from src.database import init_db, get_session, engine
from src.models import Paper
from src.worker import run_worker

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

@app.post("/run")
async def trigger_run(background_tasks: BackgroundTasks):
    """
    Trigger the paper fetching and processing cycle in the background.
    """
    background_tasks.add_task(run_worker)
    return {"message": "Paper processing cycle started in background."}

@app.get("/papers", response_model=List[Paper])
def list_papers(status: Optional[str] = None, limit: int = 50, session: Session = Depends(get_session)):
    query = select(Paper)
    if status:
        query = query.where(Paper.status == status)
    query = query.order_by(Paper.published_at.desc()).limit(limit)
    results = session.exec(query).all()
    return results

@app.get("/")
def read_root():
    return {"message": "Welcome to Paper Agent. POST /run to start processing."}
