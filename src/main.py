import os
import json

from fastapi import FastAPI, APIRouter, BackgroundTasks, HTTPException, Depends, Query, WebSocket, WebSocketDisconnect
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
from src.models import Paper, Author
from src.worker import run_worker, process_single_paper, resummarize_single_paper
from src.services.arxiv import ArxivFetcher
from src.logger import logger
from src.scheduler import SchedulerService
from src.config import settings
from src.services.settings_service import (
    get_llm_config, update_llm_config, llm_defaults, describe_settings, update_settings,
)
from src.services.model_catalog import model_catalog
from src.services.usage_service import usage_summary, estimate as estimate_cost



scheduler_service = SchedulerService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        init_db()
        await scheduler_service.start()
    except Exception as e:
        await logger.log(f"DB/Scheduler Init Error: {e}")
    try:
        ok = await model_catalog.refresh()
        await logger.log(f"Model catalog: {'loaded ' + str(model_catalog.status()['count']) + ' models' if ok else 'unavailable (' + str(model_catalog.status()['last_error']) + ')'}")
    except Exception as e:
        await logger.log(f"Model catalog refresh failed: {e}")
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

# All JSON/WebSocket endpoints live under /api so they can never collide with
# frontend (client-side) routes such as /authors or /settings.
api = APIRouter(prefix="/api")

@api.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await logger.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.disconnect(websocket)

@api.post("/run")
async def trigger_run(background_tasks: BackgroundTasks):
    """
    Trigger the paper fetching and processing cycle in the background.
    """
    background_tasks.add_task(run_worker)
    return {"message": "Paper processing cycle started in background."}

class AddPaperRequest(SQLModel):
    input: str

@api.post("/papers/add")
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

@api.get("/papers", response_model=List[Paper])
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

@api.get("/papers/search", response_model=List[Paper])
def search_papers(
    q: str = Query(..., description="Search by title"),
    limit: int = 50,
    session: Session = Depends(get_session)
):
    query = select(Paper).where(Paper.title.icontains(q)).order_by(Paper.score.desc(), Paper.published_at.desc()).limit(limit)
    results = session.exec(query).all()
    return results

@api.get("/papers/start-date")
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

@api.get("/papers/next-date")
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

@api.get("/papers/{paper_id}", response_model=Paper)
def get_paper(paper_id: str, session: Session = Depends(get_session)):
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper

# In-memory store for rate limiting
RESCORE_LAST_RUN = {}  # date_str -> last_run_timestamp
RESUMMARIZE_LAST_RUN = {}  # paper_id -> last_run_timestamp

@api.post("/papers/{paper_id}/resummarize")
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


@api.patch("/papers/{paper_id}/score")
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



@api.post("/papers/re-score-date")
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

@api.get("/authors")
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

class AuthorUpdate(SQLModel):
    bio: Optional[str] = None
    website: Optional[str] = None
    affiliation: Optional[str] = None
    is_important: Optional[bool] = None

@api.patch("/authors/{author_name}")
async def update_author(author_name: str, update_data: AuthorUpdate, session: Session = Depends(get_session)):
    """
    Update author metadata (bio, website, affiliation, is_important).
    Creates the author if they don't exist.
    """
    author = session.get(Author, author_name)
    if not author:
        author = Author(name=author_name)
    
    if update_data.bio is not None:
        author.bio = update_data.bio
    if update_data.website is not None:
        author.website = update_data.website
    if update_data.affiliation is not None:
        author.affiliation = update_data.affiliation
    if update_data.is_important is not None:
        author.is_important = update_data.is_important
        
    author.updated_at = datetime.now()
    session.add(author)
    session.commit()
    session.refresh(author)
    return author

@api.get("/authors/{author_name}/details", response_model=Author)
def get_author_details(author_name: str, session: Session = Depends(get_session)):
    author = session.get(Author, author_name)
    if not author:
        # Return empty/default if not found, or 404? 
        # Frontend expects data probably. Let's return default.
        return Author(name=author_name)
    return author

@api.get("/authors/{author_name}/papers", response_model=List[Paper])
def list_papers_by_author(author_name: str, days: Optional[int] = Query(None, description="Filter papers published within the last N days"), session: Session = Depends(get_session)):
    """
    Get all papers for a specific author.
    Optionally filter to papers published within the last N days.
    """
    search_term = json.dumps(author_name) # Foo"Bar name
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

@api.get("/profile")
def get_profile():
    return {"profile": settings.USER_PROFILE}


# ---------------------------------------------------------------------------
# Settings — backed by the env file (/config/.env in Docker, ./.env locally).
# Saving rewrites only the touched keys and hot-applies them; secrets are never returned.
# ---------------------------------------------------------------------------
class LLMSettingsUpdate(SQLModel):
    stage1_model: Optional[str] = None
    stage2_model: Optional[str] = None
    summary_model: Optional[str] = None
    stage2_threshold: Optional[int] = None
    score_threshold: Optional[int] = None


class SettingsUpdate(SQLModel):
    values: dict


class ProfileUpdate(SQLModel):
    profile: str


def _llm_settings_payload(warnings: Optional[List[str]] = None):
    cfg = get_llm_config()
    desc = describe_settings()
    return {
        "profile": settings.USER_PROFILE,
        "provider": desc["provider"],
        "env_file": desc["env_file"],
        "models": {"stage1": cfg.stage1_model, "stage2": cfg.stage2_model, "summary": cfg.summary_model},
        "thresholds": {"stage2_threshold": cfg.stage2_threshold, "score_threshold": cfg.score_threshold},
        "defaults": llm_defaults(),
        "summary_language": settings.SUMMARY_LANGUAGE,
        "catalog": model_catalog.status(),
        "warnings": warnings or [],
    }


@api.get("/settings")
def get_all_settings():
    """Every editable setting with its effective value, source (env var / env file / default) and schema. Secrets masked."""
    desc = describe_settings()
    desc["scheduler"] = {"next_run_time": scheduler_service.next_run_time()}
    return desc


@api.put("/settings")
async def put_all_settings(update: SettingsUpdate):
    """
    Update any editable settings: {"values": {"KEY": value, ...}}.
    Writes the env file, hot-applies, and reloads the scheduler if schedule keys changed.
    For secret keys, an empty value means "leave unchanged".
    """
    try:
        applied, warnings = update_settings(update.values or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Could not write env file: {e}")
    if any(k in applied for k in ("ENABLE_AUTO_UPDATE", "AUTO_UPDATE_TIME")):
        await scheduler_service.reload()
    if applied:
        await logger.log(f"Settings updated: {', '.join(k for k in applied if not k.startswith('_'))}")
    desc = describe_settings()
    desc["scheduler"] = {"next_run_time": scheduler_service.next_run_time()}
    desc["applied"] = applied
    desc["warnings"] = warnings
    return desc


@api.put("/settings/profile")
async def put_profile(update: ProfileUpdate):
    """Update USER_PROFILE (written to the env file, applied immediately)."""
    try:
        applied, warnings = update_settings({"USER_PROFILE": update.profile})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Could not write env file: {e}")
    await logger.log("Settings updated: USER_PROFILE")
    return {"profile": settings.USER_PROFILE, "applied": applied, "warnings": warnings}


@api.get("/settings/llm")
def get_llm_settings():
    """Current models / thresholds / provider status (used by the Models card)."""
    return _llm_settings_payload()


@api.put("/settings/llm")
async def put_model_settings(update: LLMSettingsUpdate):
    """
    Update model selection / thresholds. Written to the env file and used by the next run.
    Model ids are validated against the provider catalog when the provider is OpenRouter.
    """
    # Validate model ids against the catalog (only meaningful when the provider is OpenRouter,
    # whose ids match the catalog; legacy endpoints use their own ids)
    await model_catalog.refresh()
    if settings.llm_provider == "openrouter" and model_catalog.status()["count"] > 0:
        for field in ("stage1_model", "stage2_model", "summary_model"):
            mid = getattr(update, field)
            if mid and model_catalog.get(mid.strip()) is None:
                raise HTTPException(status_code=400, detail=f"Unknown model id for {field}: {mid}")
    try:
        cfg, warnings = update_llm_config(
            stage1_model=update.stage1_model,
            stage2_model=update.stage2_model,
            summary_model=update.summary_model,
            stage2_threshold=update.stage2_threshold,
            score_threshold=update.score_threshold,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Could not write env file: {e}")
    await logger.log(
        f"Settings updated — stage1: {cfg.stage1_model} | stage2: {cfg.stage2_model} (>= {cfg.stage2_threshold}) | "
        f"summary: {cfg.summary_model} (>= {cfg.score_threshold})"
    )
    return _llm_settings_payload(warnings)


@api.get("/models")
async def list_models(
    q: Optional[str] = Query(None, description="Filter by substring of id/name"),
    limit: Optional[int] = Query(None, description="Max results"),
    refresh: bool = Query(False, description="Force refresh from provider"),
):
    """Provider model catalog with list prices (USD per 1M tokens)."""
    await model_catalog.refresh(force=refresh)
    items = [m.to_dict() for m in model_catalog.list(q=q, limit=limit)]
    return {"models": items, "catalog": model_catalog.status()}


@api.get("/llm/usage")
def get_llm_usage(days: int = Query(30, description="Breakdown window in days"), session: Session = Depends(get_session)):
    """Real LLM spend: totals for today/7d/30d/all-time and a by-task/by-model breakdown."""
    return usage_summary(session, breakdown_days=days)


@api.get("/llm/estimate")
async def get_llm_estimate(
    stage1_model: Optional[str] = None,
    stage2_model: Optional[str] = None,
    summary_model: Optional[str] = None,
    stage2_threshold: Optional[int] = None,
    score_threshold: Optional[int] = None,
    session: Session = Depends(get_session),
):
    """
    Projected cost per day / month for a model selection (defaults to the current settings).
    Uses observed average tokens per task and observed paper volumes when available.
    """
    await model_catalog.refresh()
    cfg = get_llm_config()
    if stage1_model: cfg.stage1_model = stage1_model
    if stage2_model: cfg.stage2_model = stage2_model
    if summary_model: cfg.summary_model = summary_model
    if stage2_threshold is not None: cfg.stage2_threshold = stage2_threshold
    if score_threshold is not None: cfg.score_threshold = score_threshold
    return estimate_cost(session, cfg)

@api.get("/health")
def read_root():
    return {"message": "Welcome to Paper Agent. POST /api/run to start processing.", "docs": "/docs", "api_prefix": "/api"}


app.include_router(api)

# Root-level liveness probe (kept outside /api for docker/uptime checks)
@app.get("/health")
def health_root():
    return read_root()



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
