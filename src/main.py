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
from pydantic import BaseModel

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
from src.services.usage_service import usage_summary
from src.services.notifier import get_notifier
from src.services import embedding_service
from src.services.paper_views import compact_paper
from src.services import author_index as author_index_service
from src.services import bibtex_service
from src.services import verdict_pipeline, reading_page, claude_budget, project_service
from src.services.arxiv import ArxivAPIError



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
        n = embedding_service.index.load()
        await logger.log(f"Embedding index: {n} vectors ({embedding_service.current_model()})")
    except Exception as e:
        await logger.log(f"Embedding index not loaded: {e}")
    try:
        ok = await model_catalog.refresh()
        await logger.log(f"Model catalog: {'loaded ' + str(model_catalog.status()['count']) + ' models' if ok else 'unavailable (' + str(model_catalog.status()['last_error']) + ')'}")
    except Exception as e:
        await logger.log(f"Model catalog refresh failed: {e}")
    yield
    # Shutdown (if needed)
    scheduler_service.shutdown()

def _resolve_app_version() -> str:
    try:
        from importlib.metadata import version as _pkg_version
        return _pkg_version("paper-agent")
    except Exception:
        pass
    try:
        import tomllib
        from pathlib import Path
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        return tomllib.loads(pyproject.read_text())["project"]["version"]
    except Exception:
        return "unknown"

APP_VERSION = _resolve_app_version()

app = FastAPI(title="Paper Agent API", version=APP_VERSION, lifespan=lifespan)

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
    push: bool = True  # False: skip the individual notification; the next scheduled digest picks the paper up

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
             background_tasks.add_task(process_single_paper, arxiv_id, False, request.push)
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
    background_tasks.add_task(process_single_paper, new_paper.id, False, request.push)

    return {"message": f"Paper {new_paper.id} added and processing started.", "paper": new_paper}

class BulkPaperIn(SQLModel):
    id: str
    title: str
    authors: List[str] = []
    abstract: str = ""
    published_at: datetime
    updated_at: Optional[datetime] = None
    category_primary: str = ""
    all_categories: List[str] = []
    pdf_url: str = ""

class BulkInsertRequest(SQLModel):
    papers: List[BulkPaperIn]

@api.post("/papers/bulk-insert")
def bulk_insert_papers(request: BulkInsertRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """
    Insert paper metadata directly as NEW, skipping ids that already exist.
    Built for backfill: nothing is fetched from arXiv and nothing is pushed
    here — the scheduled run scores all NEW papers in batch and the digest
    picks up whatever qualifies.
    """
    if len(request.papers) > 1000:
        raise HTTPException(status_code=400, detail="At most 1000 papers per request")
    wanted = [re.sub(r'v\d+$', '', p.id.strip()) for p in request.papers]
    existing = {p.id for p in session.exec(select(Paper).where(Paper.id.in_(wanted))).all()}
    inserted = 0
    for p in request.papers:
        pid = re.sub(r'v\d+$', '', p.id.strip())
        if pid in existing:
            continue
        existing.add(pid)
        session.add(Paper(
            id=pid,
            title=p.title,
            authors=json.dumps(p.authors),
            summary_generic=p.abstract,
            published_at=p.published_at,
            category_primary=p.category_primary,
            all_categories=json.dumps(p.all_categories),
            pdf_url=p.pdf_url or f"https://arxiv.org/pdf/{pid}",
            updated_at=p.updated_at or p.published_at,
        ))
        inserted += 1
    session.commit()
    new_ids = [re.sub(r'v\d+$', '', p.id.strip()) for p in request.papers]
    background_tasks.add_task(_embed_quietly, new_ids)   # vectors right away; scoring runs with the next nightly job
    return {"inserted": inserted, "skipped": len(request.papers) - inserted}


async def _embed_quietly(paper_ids):
    try:
        await embedding_service.embed_new_papers(paper_ids)
    except Exception as e:
        await logger.log(f"Embedding of inserted papers skipped: {e} (the nightly run will catch up)")

@api.get("/papers", response_model=None)
def list_papers(
    status: Optional[str] = None, 
    limit: int = 50, 
    date: Optional[str] = Query(None, description="Filter by date (YYYY-MM-DD)"),
    ids: Optional[str] = Query(None, description="Comma-separated arXiv ids to fetch (ignores date/status)"),
    compact: bool = Query(False, description="Small agent-friendly records (no full text / raw JSON)"),
    session: Session = Depends(get_session)
):
    if ids:
        wanted = [x.strip() for x in ids.split(",") if x.strip()]
        found = {p.id: p for p in session.exec(select(Paper).where(Paper.id.in_(wanted))).all()}
        papers = [found[i] for i in wanted if i in found]
        return [compact_paper(p) for p in papers] if compact else papers
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
    return [compact_paper(p) for p in results] if compact else results

@api.get("/papers/search", response_model=None)
def search_papers(
    q: str = Query(..., description="Search by title"),
    limit: int = 50,
    compact: bool = Query(False, description="Small agent-friendly records"),
    session: Session = Depends(get_session)
):
    query = select(Paper).where(Paper.title.icontains(q)).order_by(Paper.score.desc(), Paper.published_at.desc()).limit(limit)
    results = session.exec(query).all()
    return [compact_paper(p) for p in results] if compact else results

@api.get("/papers/recent")
def recent_papers(
    days: int = Query(7, description="Papers published within the last N days"),
    min_score: Optional[int] = Query(None, description="Minimum (final) score, e.g. 85 for the digest set"),
    status: Optional[str] = Query(None, description="Comma-separated statuses, e.g. PUSHED,SUMMARIZED"),
    category: Optional[str] = None,
    limit: int = 100,
    compact: bool = True,
    session: Session = Depends(get_session),
):
    """Recent papers (newest first; ties by score) with optional score/status/category filters. Compact by default."""
    q = select(Paper).where(Paper.published_at >= datetime.now() - timedelta(days=days))
    if min_score is not None:
        q = q.where(Paper.score >= min_score)
    if status:
        q = q.where(Paper.status.in_([x.strip() for x in status.split(",") if x.strip()]))
    if category:
        q = q.where(Paper.category_primary == category)
    q = q.order_by(Paper.published_at.desc(), Paper.score.desc()).limit(max(1, min(limit, 1000)))
    papers = session.exec(q).all()
    return [compact_paper(p) for p in papers] if compact else papers


class SemanticSearchRequest(SQLModel):
    query: Optional[str] = None                 # natural-language query (any language)
    paper_ids: Optional[List[str]] = None       # seed papers: search near their mean vector (excluded from results)
    days: Optional[int] = None                  # only papers published within the last N days
    since: Optional[str] = None                 # YYYY-MM-DD (inclusive)
    until: Optional[str] = None                 # YYYY-MM-DD (exclusive)
    min_score: Optional[int] = None
    status: Optional[List[str]] = None          # e.g. ["PUSHED", "SUMMARIZED"]
    category: Optional[str] = None              # primary category, e.g. "cs.CV"
    exclude_ids: Optional[List[str]] = None
    limit: int = 30
    compact: bool = True


def _allowed_ids_for_filters(session: Session, req: SemanticSearchRequest) -> Optional[set]:
    """Translate filters into the candidate id set (None = no filter)."""
    conds = []
    if req.days is not None:
        conds.append(Paper.published_at >= datetime.now() - timedelta(days=req.days))
    if req.since:
        conds.append(Paper.published_at >= datetime.strptime(req.since, "%Y-%m-%d"))
    if req.until:
        conds.append(Paper.published_at < datetime.strptime(req.until, "%Y-%m-%d"))
    if req.min_score is not None:
        conds.append(Paper.score >= req.min_score)
    if req.status:
        conds.append(Paper.status.in_(req.status))
    if req.category:
        conds.append(Paper.category_primary == req.category)
    if not conds:
        return None
    q = select(Paper.id)
    for c in conds:
        q = q.where(c)
    return set(session.exec(q).all())


async def _semantic_search_impl(req: SemanticSearchRequest, session: Session):
    if not (req.query and req.query.strip()) and not req.paper_ids:
        raise HTTPException(status_code=400, detail="Provide `query` text and/or `paper_ids` seeds.")
    try:
        allowed = _allowed_ids_for_filters(session, req)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    if allowed is not None and not allowed:
        return {"query": req.query, "results": [], "index_size": embedding_service.index.size(), "filters_matched": 0}
    try:
        hits = await embedding_service.semantic_search(
            req.query, k=max(1, min(req.limit, 200)), seed_ids=req.paper_ids,
            allowed=allowed, exclude=set(req.exclude_ids or []),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding request failed: {e}")
    by_id = {p.id: p for p in session.exec(select(Paper).where(Paper.id.in_([h[0] for h in hits]))).all()} if hits else {}
    results = []
    for pid, sim in hits:
        p = by_id.get(pid)
        if not p:
            continue
        if req.compact:
            results.append(compact_paper(p, similarity=sim))
        else:
            d = p.model_dump(); d.pop("full_text", None); d["similarity"] = round(sim, 4)
            results.append(d)
    return {"query": req.query, "seed_ids": req.paper_ids, "results": results,
            "index_size": embedding_service.index.size(),
            "filters_matched": len(allowed) if allowed is not None else None}


@api.get("/papers/semantic-search")
async def semantic_search_papers(
    q: str = Query(..., description="Natural-language query (any language)"),
    limit: int = 30,
    days: Optional[int] = Query(None, description="Only papers published within the last N days"),
    min_score: Optional[int] = None,
    category: Optional[str] = None,
    compact: bool = Query(False, description="Small agent-friendly records (default full records for the UI)"),
    session: Session = Depends(get_session),
):
    """Semantic search over title+abstract embeddings (one embedding call per query). Returns papers with cosine `similarity`."""
    if not q.strip():
        return {"query": q, "results": [], "index_size": embedding_service.index.size()}
    req = SemanticSearchRequest(query=q, limit=limit, days=days, min_score=min_score, category=category, compact=compact)
    return await _semantic_search_impl(req, session)


@api.post("/papers/semantic-search")
async def semantic_search_papers_post(req: SemanticSearchRequest, session: Session = Depends(get_session)):
    """
    Semantic search for agents: `query` text and/or `paper_ids` seeds (search near their mean vector),
    with filters (`days` / `since` / `until` / `min_score` / `status` / `category` / `exclude_ids`).
    Compact records by default.
    """
    return await _semantic_search_impl(req, session)


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

@api.get("/papers/{paper_id}/related")
def related_papers(paper_id: str, k: int = 8, session: Session = Depends(get_session)):
    """Nearest neighbours of a paper by embedding. `available=false` if the paper has no vector yet."""
    if not session.get(Paper, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    hits = embedding_service.related(paper_id, k=k)
    if hits is None:
        return {"available": False, "results": []}
    by_id = {p.id: p for p in session.exec(select(Paper).where(Paper.id.in_([h[0] for h in hits]))).all()}
    results = [compact_paper(by_id[pid], similarity=sim) for pid, sim in hits if pid in by_id]
    return {"available": True, "results": results}


@api.post("/papers/{paper_id}/deep-read")
async def trigger_deep_read(paper_id: str, background_tasks: BackgroundTasks, force: bool = False,
                            session: Session = Depends(get_session)):
    """
    Deep read one paper now (Claude API, real time): review first if needed, then the final verdict,
    summary, paragraph-by-paragraph gist + claim flags and a full Chinese translation.
    The result is shown at /read/{paper_id}; poll GET /api/papers/{paper_id}/reading for status.
    Takes 1-2 minutes and roughly $0.1-0.2.
    """
    if not session.get(Paper, paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    if not settings.chat_api_key:
        raise HTTPException(status_code=400, detail=f"{settings.chat_key_name} is not configured")
    existing = verdict_pipeline.get_reading(paper_id)
    if existing and existing["status"] == "RUNNING" and not force:
        return {"status": "RUNNING", "read_url": f"/read/{paper_id}"}
    if existing and existing["status"] == "DONE" and not force:
        return {"status": "DONE", "read_url": f"/read/{paper_id}"}
    verdict_pipeline._upsert_reading(paper_id, status="PENDING", error=None)

    if claude_budget.affordable("deep", 3) < 3:
        raise HTTPException(status_code=429, detail=f"Claude budget nearly used up: {claude_budget.status()}")

    async def job():
        try:
            await verdict_pipeline.deep_read_on_demand(paper_id, log=logger.log)
        except Exception as e:
            verdict_pipeline._upsert_reading(paper_id, status="ERROR", error=str(e)[:500])
            await logger.log(f"Deep read of {paper_id} failed: {e}")
    background_tasks.add_task(job)
    return {"status": "STARTED", "read_url": f"/read/{paper_id}"}


# ---------------------------------------------------------------------------- projects
class ProjectIn(BaseModel):
    name: str
    description: str = ""
    keywords: List[str] = []
    seed_paper_ids: List[str] = []


class ProjectPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None
    active: Optional[bool] = None


class ProjectPapersIn(BaseModel):
    paper_ids: List[str]
    source: str = "manual"


@api.get("/projects")
def list_projects():
    """All projects with paper counts."""
    return project_service.list_projects()


@api.post("/projects")
def create_project(body: ProjectIn):
    """Create a project; seed papers anchor its embedding recall (they must already be in the library)."""
    try:
        return project_service.create(body.name, body.description, body.keywords, body.seed_paper_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.get("/projects/{key}")
def get_project(key: str, limit: int = 200):
    """Project (by id or name) with its papers, newest first."""
    d = project_service.get(key, limit=limit)
    if d is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return d


@api.patch("/projects/{key}")
def patch_project(key: str, body: ProjectPatch):
    try:
        d = project_service.update(key, body.name, body.description, body.keywords, body.active)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if d is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return d


@api.delete("/projects/{key}")
def delete_project(key: str):
    if not project_service.delete(key):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": key}


@api.post("/projects/{key}/papers")
def add_project_papers(key: str, body: ProjectPapersIn):
    """Add papers (source: manual or seed). Unknown ids are reported, not added — add them to the library first."""
    if body.source not in ("manual", "seed"):
        raise HTTPException(status_code=400, detail="source must be manual or seed")
    try:
        return project_service.add_papers(key, body.paper_ids, source=body.source)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@api.delete("/projects/{key}/papers/{paper_id}")
def remove_project_paper(key: str, paper_id: str):
    try:
        return {"removed": project_service.remove_papers(key, [paper_id])}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@api.get("/projects/{key}/suggestions")
async def project_suggestions(key: str, k: int = 20):
    """Library papers closest to the project (seed papers + description) that are not in it yet."""
    if project_service.resolve(key) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return await project_service.suggestions(key, k=k)


@api.get("/claude/models")
def list_claude_models():
    """Claude models for the selected CHAT_PROVIDER, with list prices (USD per 1M tokens)."""
    from src.services.claude_runner import PRICES
    names = {"claude-haiku-5-5": "Claude Haiku 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5", "claude-sonnet-5": "Claude Sonnet 5",
             "claude-opus-5-5": "Claude Opus 5.5", "claude-opus-5": "Claude Opus 5", "claude-fable-5-2": "Claude Fable 5.2",
             "claude-haiku-4-5": "Claude Haiku 4.5"}
    return {"key_configured": bool(settings.chat_api_key), "provider": settings.CHAT_PROVIDER,
            "models": [{"id": k, "name": names.get(k, k), "prompt_price_per_m": v[0], "completion_price_per_m": v[1]}
                       for k, v in PRICES.items()]}


@api.get("/claude/budget")
def get_claude_budget():
    """Claude API spend this billing cycle vs CLAUDE_MONTHLY_BUDGET (list-price estimate)."""
    return claude_budget.status()


@api.get("/papers/{paper_id}/reading")
def get_paper_reading(paper_id: str, full: bool = False):
    """Deep-read status; with full=true also the units, notes (gist + claim flags) and translations."""
    r = verdict_pipeline.get_reading(paper_id)
    if r is None:
        return {"paper_id": paper_id, "status": "NONE", "read_url": f"/read/{paper_id}"}
    r["read_url"] = f"/read/{paper_id}"
    if not full:
        flags = [f for n in r["notes"] for f in n.get("flags", []) if f.get("verified")]
        r = {k: v for k, v in r.items() if k not in ("units", "notes", "translations")}
        r["flags"] = flags
    return r


os.makedirs(settings.figure_dir, exist_ok=True)
app.mount("/api/figures", StaticFiles(directory=settings.figure_dir), name="figures")


# In-memory store for rate limiting
RESCORE_LAST_RUN = {}  # date_str -> last_run_timestamp
RESUMMARIZE_LAST_RUN = {}  # paper_id -> last_run_timestamp

@api.post("/papers/{paper_id}/resummarize")
async def resummarize_paper(paper_id: str, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """
    Redo the deep read of one paper (same as POST /papers/{id}/deep-read?force=true).
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
async def rescore_date(date: str, background_tasks: BackgroundTasks, push: bool = False, session: Session = Depends(get_session)):
    """
    Re-run the verdict pipeline (screen -> review -> deep read) on all papers of a date, as Batch API jobs.
    Rate limited to once per 60 seconds per date. Newly qualifying papers stay SUMMARIZED and go out with
    the next scheduled digest (`push` is kept for compatibility).
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
        
        papers = [p for p in papers if p.user_score is None]

        async def job():
            from src.services.claude_runner import ClaudeRunner
            await verdict_pipeline.run_pipeline(papers, ClaudeRunner(), log=logger.log)
        background_tasks.add_task(job)
        return {"message": f"Started re-scoring {len(papers)} papers on {date} (Batch API; newly qualifying papers go out with the next digest)"}
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

@api.post("/papers/backfill-verdicts")
async def backfill_verdicts(start: str, end: str, background_tasks: BackgroundTasks, max_cost: float = 50.0,
                            deep_limit: int = 200, silent: bool = True):
    """
    Re-run the verdict pipeline over a date range (YYYY-MM-DD, inclusive), newest day first, as Batch API
    jobs: screen -> review -> deep read with no nightly deep-read cap (`deep_limit` per day), stopping before
    a day once this run is within ~$5 of `max_cost`. With `silent` (default) the results are not sent in the
    next digest. Progress: GET /api/papers/backfill-verdicts.
    """
    if verdict_pipeline.BACKFILL.get("running"):
        raise HTTPException(status_code=409, detail="A backfill is already running.")
    try:
        lo, hi = datetime.strptime(start, "%Y-%m-%d").date(), datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    if lo > hi:
        raise HTTPException(status_code=400, detail="start is after end")
    if not settings.chat_api_key:
        raise HTTPException(status_code=400, detail=f"{settings.chat_key_name} is not configured")
    verdict_pipeline.BACKFILL["running"] = True

    async def job():
        try:
            await verdict_pipeline.backfill(lo, hi, max_cost, deep_limit=deep_limit, silent=silent, log=logger.log)
        except Exception as e:
            verdict_pipeline.BACKFILL.update(running=False, error=str(e)[:500])
            await logger.log(f"Backfill failed: {e}")
    background_tasks.add_task(job)
    return {"message": f"Backfill started for {start} .. {end} (cap ${max_cost:.0f})"}


@api.get("/papers/backfill-verdicts")
def backfill_status():
    return verdict_pipeline.BACKFILL


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


class AuthorLookupRequest(SQLModel):
    names: List[str]
    days: Optional[int] = None
    min_score: Optional[int] = None
    limit_per_author: int = 20
    mark_important: bool = False


class AuthorBulkItem(SQLModel):
    name: str
    is_important: Optional[bool] = None
    bio: Optional[str] = None
    website: Optional[str] = None
    affiliation: Optional[str] = None


class AuthorBulkRequest(SQLModel):
    authors: List[AuthorBulkItem]


@api.post("/authors/lookup")
def lookup_authors(req: AuthorLookupRequest, session: Session = Depends(get_session)):
    """
    Batch "people of interest" lookup. Each name is matched fuzzily against every author string seen on
    any paper (case/accents/punctuation folded, "Last, First" and swapped token order, then first-initial+last
    name — the latter may be ambiguous and is flagged). Returns matched variants and their papers
    (compact; optional `days` / `min_score`). `mark_important=true` flags unambiguous matches for the score boost.
    """
    names = [n.strip() for n in (req.names or []) if n and n.strip()]
    if not names:
        raise HTTPException(status_code=400, detail="Provide at least one name.")
    if len(names) > 200:
        raise HTTPException(status_code=400, detail="At most 200 names per request.")
    results = author_index_service.lookup(
        session, names, days=req.days, min_score=req.min_score,
        limit_per_author=max(0, min(req.limit_per_author, 200)), mark_important=req.mark_important,
    )
    return {"results": results, "index_authors": len(author_index_service.author_index.counts)}


@api.post("/authors/bulk")
def bulk_update_authors(req: AuthorBulkRequest, session: Session = Depends(get_session)):
    """Upsert many authors at once (is_important / bio / website / affiliation). Creates missing authors."""
    updated = []
    for item in req.authors:
        name = item.name.strip()
        if not name:
            continue
        row = session.get(Author, name) or Author(name=name)
        for f in ("is_important", "bio", "website", "affiliation"):
            v = getattr(item, f)
            if v is not None:
                setattr(row, f, v)
        row.updated_at = datetime.now()
        session.add(row)
        updated.append(name)
    session.commit()
    return {"updated": updated, "count": len(updated)}


@api.post("/authors/reindex")
def reindex_authors():
    """Rebuild the fuzzy author index (it also refreshes itself hourly)."""
    n = author_index_service.author_index.build()
    return {"authors": n}

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
    translate_model: Optional[str] = None


class SettingsUpdate(SQLModel):
    values: dict


class ProfileUpdate(SQLModel):
    profile: str


def _llm_settings_payload(warnings: Optional[List[str]] = None):
    from src.services.settings_service import stale_model_warnings
    cfg = get_llm_config()
    desc = describe_settings()
    return {
        "profile": settings.USER_PROFILE,
        "provider": desc["provider"],
        "env_file": desc["env_file"],
        "models": {"screen": cfg.stage1_model, "review": cfg.stage2_model, "deep_read": cfg.summary_model,
                   "translate": cfg.translate_model},
        "gates": {"screen_min_relevance": settings.SCREEN_MIN_RELEVANCE, "deep_read_max_per_run": settings.DEEP_READ_MAX_PER_RUN,
                  "push_score": cfg.score_threshold},
        "defaults": llm_defaults(),
        "summary_language": settings.SUMMARY_LANGUAGE,
        "warnings": (warnings or []) + stale_model_warnings(),
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
    """Update the Claude models (ids must start with claude-). Written to the env file, used by the next run."""
    try:
        cfg, warnings = update_llm_config(
            stage1_model=update.stage1_model, stage2_model=update.stage2_model, summary_model=update.summary_model,
            translate_model=update.translate_model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (OSError, PermissionError) as e:
        raise HTTPException(status_code=500, detail=f"Could not write env file: {e}")
    await logger.log(f"Models updated — screen: {cfg.stage1_model} | review: {cfg.stage2_model} | deep read: {cfg.summary_model}")
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


# ---------------------------------------------------------------------------
# Embeddings admin
# ---------------------------------------------------------------------------
@api.get("/embeddings/status")
def embeddings_status():
    """Coverage of the current embedding model, index size, backfill progress."""
    return embedding_service.status()


@api.post("/embeddings/backfill")
async def embeddings_backfill(background_tasks: BackgroundTasks):
    """Embed every paper that has no vector for the current model (background; idempotent)."""
    st = embedding_service.status()
    if st["backfill"]["running"]:
        return {"message": "Backfill already running.", **st}
    if not st["key_configured"]:
        raise HTTPException(status_code=400, detail="No LLM API key configured.")
    background_tasks.add_task(embedding_service.backfill, logger.log)
    return {"message": f"Backfill started for {st['missing']} paper(s).", **st}


@api.post("/embeddings/reload")
def embeddings_reload():
    """Force-reload the in-memory index from the DB."""
    n = embedding_service.index.load(force=True)
    return {"index_size": n, "model": embedding_service.current_model()}


@api.get("/embeddings/models")
async def embeddings_models(refresh: bool = False):
    """Embedding models offered by the provider (from the catalog's /embeddings/models list)."""
    await model_catalog.refresh(force=refresh)
    return {"models": [m.to_dict() for m in model_catalog.list(kind="embedding")], "catalog": model_catalog.status()}




# ---------------------------------------------------------------------------
# BibTeX library (agent-driven: no automatic venue lookup)
# ---------------------------------------------------------------------------
def _bib_payload(entries, extra=None):
    out = {"bibtex": bibtex_service.export(entries), "entries": [bibtex_service.entry_dict(e) for e in entries],
           "needs_check": [e.paper_id for e in entries if bibtex_service.needs_check(e)]}
    out.update(extra or {})
    return out

@api.get("/bibtex")
def get_bibtex(ids: Optional[str] = Query(None, description="Comma-separated arXiv ids (added to the library if new). Omit for the whole library."),
               session: Session = Depends(get_session)):
    """BibTeX for the given papers, or the whole library. `needs_check` = entries whose venue the agent should verify."""
    if not ids:
        return _bib_payload(bibtex_service.list_entries(session))
    res = bibtex_service.get_entries(session, ids.split(","))
    return _bib_payload(res["entries"], {"missing": res["missing"], "warnings": res["warnings"]})

@api.get("/bibtex/hints")
def bibtex_hints(ids: str = Query(..., description="Comma-separated arXiv ids"), session: Session = Depends(get_session)):
    """Read-only venue evidence from the current arXiv record (raw comment / journal_ref / DOI) for the agent to interpret."""
    try:
        return {"hints": bibtex_service.hints(session, ids.split(","))}
    except ArxivAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))

@api.get("/bibtex/{paper_id:path}/entry")
def get_bibtex_entry(paper_id: str, session: Session = Depends(get_session)):
    res = bibtex_service.get_entries(session, [paper_id])
    if not res["entries"]:
        raise HTTPException(status_code=404, detail=f"arXiv paper {paper_id} not found")
    return {**bibtex_service.entry_dict(res["entries"][0]), "warnings": res["warnings"]}

class BibStatusUpdate(SQLModel):
    status: str = "published"          # published | preprint (checked, not yet) | unchecked (reset)
    venue: Optional[str] = None        # published: stored as given ("CVPR", "IEEE TPAMI", full journal name)
    venue_type: Optional[str] = None   # conference | journal (required for published)
    year: Optional[int] = None
    evidence: Optional[str] = None     # URL / note on where it was confirmed
    authors: Optional[List[str]] = None  # published: author list of the official version (replaces arXiv's)

@api.put("/bibtex/{paper_id:path}/status")
def set_bibtex_status(paper_id: str, update: BibStatusUpdate, session: Session = Depends(get_session)):
    """Write the agent's venue verdict back. Published entries are final; 'preprint' is trusted for 30 days."""
    try:
        entry = bibtex_service.set_status(session, paper_id, update.status, update.venue, update.venue_type,
                                          update.year, update.evidence, update.authors)
    except bibtex_service.BibUpdateError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return bibtex_service.entry_dict(entry)

@api.delete("/bibtex/{paper_id:path}/entry")
def delete_bibtex_entry(paper_id: str, session: Session = Depends(get_session)):
    if not bibtex_service.delete_entry(session, paper_id):
        raise HTTPException(status_code=404, detail="Not in the BibTeX library")
    return {"deleted": paper_id}

class BibFixRequest(SQLModel):
    bibtex: str

@api.post("/bibtex/fix")
def fix_bibtex(req: BibFixRequest, session: Session = Depends(get_session)):
    """Sync a pasted .bib with the library (no lookups); lists what the agent still needs to check."""
    return bibtex_service.fix_bibtex(session, req.bibtex)


@api.get("/health")
def read_root():
    return {"message": "Welcome to Paper Agent. POST /api/run to start processing.", "docs": "/docs", "api_prefix": "/api", "version": APP_VERSION}


app.include_router(api)

@app.get("/picks")
def picks_page(date: Optional[str] = None, days: int = 7, session: Session = Depends(get_session)):
    """Must Read / Worth Reading papers for `days` publication days ending at `date` (default: latest)."""
    from fastapi.responses import HTMLResponse
    from src.models import PaperReading
    verdicts = ("must_read", "worth_reading")
    rows = session.exec(select(Paper).where(Paper.status.in_(["SUMMARIZED", "PUSHED"]))
                        .order_by(Paper.published_at.desc()).limit(3000)).all()

    def verdict_of(p):
        try:
            r = json.loads(p.score_reason or "{}")
        except json.JSONDecodeError:
            return None
        return ((r.get("deep") or r.get("stage2") or {}) if isinstance(r, dict) else {}).get("verdict")
    picks = [p for p in rows if verdict_of(p) in verdicts]
    all_days = sorted({p.published_at.strftime("%Y-%m-%d") for p in picks}, reverse=True)
    end = date if date in all_days else (all_days[0] if all_days else None)
    i = all_days.index(end) if end else 0
    window = all_days[i:i + days]
    by_day = [(d, sorted([p for p in picks if p.published_at.strftime("%Y-%m-%d") == d],
                         key=lambda p: (verdict_of(p) != "must_read", -(p.score or 0)))) for d in window]
    ids = [p.id for _, ps in by_day for p in ps]
    readings = {}
    for r in session.exec(select(PaperReading).where(PaperReading.paper_id.in_(ids))).all() if ids else []:
        notes = json.loads(r.notes) if r.notes else []
        fl = [f for n in notes for f in n.get("flags", []) if f.get("verified")]
        readings[r.paper_id] = {"status": r.status, "flags": {"q": sum(f["kind"] == "questionable" for f in fl),
                                                              "b": sum(f["kind"] == "big_claim" for f in fl)}}
    projects = {pid: project_service.projects_of(pid) for pid in ids}
    later = all_days[max(0, i - days)] if i > 0 else None
    earlier = all_days[i + days] if i + days < len(all_days) else None
    return HTMLResponse(reading_page.render_picks(by_day, readings, projects, earlier, later, "Daily Picks"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/read/{paper_id:path}")
def read_page(paper_id: str, session: Session = Depends(get_session)):
    """Bilingual reading page: original paragraphs, Chinese gist + translation, flagged claims."""
    from fastapi.responses import HTMLResponse
    paper = session.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return HTMLResponse(reading_page.render(paper, verdict_pipeline.get_reading(paper_id)),
                        headers={"Cache-Control": "no-cache"})


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
        class CachedStaticFiles(StaticFiles):
            async def get_response(self, path, scope):
                resp = await super().get_response(path, scope)
                if resp.status_code == 200:
                    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return resp
        app.mount("/assets", CachedStaticFiles(directory=assets_dir), name="assets")

    # SPA catch-all: any route not matched by the API or /assets
    # serves the frontend index.html so client-side routing works on refresh
    # The app shell must always be revalidated, otherwise browsers keep a stale index.html
    # (and therefore stale JS) across upgrades; hashed /assets/* are safe to cache for long.
    NO_CACHE = {"Cache-Control": "no-cache"}

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # If the requested file exists on disk, serve it (e.g. favicon, manifest)
        file_path = os.path.join(frontend_dist, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path, headers=NO_CACHE)
        # Otherwise, serve index.html for client-side routing
        return FileResponse(os.path.join(frontend_dist, "index.html"), headers=NO_CACHE)
