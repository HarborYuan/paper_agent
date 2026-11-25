"""
Projects: named collections of papers that also steer recall.

- Embedding route: project vector = mean of the seed papers' vectors and the embedded description;
  new papers within PROJECT_SIM_THRESHOLD (cosine) become candidates.
- Screen route: the screen prompt lists the active projects and returns matched_projects.
- Candidates from either route go to review (even below the relevance gate); the reviewer confirms
  each match, and confirmed matches are added with source="auto". Seeds / manual adds are kept as such.
"""
import json
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
from sqlmodel import Session, select

from src.config import settings
from src.database import engine
from src.models import Paper, Project, ProjectPaper


# ---------------------------------------------------------------------------- CRUD
def _kw(p: Project) -> List[str]:
    try:
        return json.loads(p.keywords) if p.keywords else []
    except json.JSONDecodeError:
        return []


def resolve(key: Union[int, str]) -> Optional[Project]:
    """Project by id or (case-insensitive) name."""
    with Session(engine) as s:
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            p = s.get(Project, int(key))
            if p:
                return p
        name = str(key).strip().lower()
        for p in s.exec(select(Project)).all():
            if p.name.lower() == name:
                return p
    return None


def to_dict(p: Project, n_papers: Optional[int] = None) -> dict:
    d = {"id": p.id, "name": p.name, "description": p.description, "keywords": _kw(p), "active": p.active,
         "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat()}
    if n_papers is not None:
        d["n_papers"] = n_papers
    return d


def list_projects(active_only: bool = False) -> List[dict]:
    with Session(engine) as s:
        ps = s.exec(select(Project)).all()
        counts = {}
        for pp in s.exec(select(ProjectPaper)).all():
            counts[pp.project_id] = counts.get(pp.project_id, 0) + 1
    return [to_dict(p, counts.get(p.id, 0)) for p in ps if p.active or not active_only]


def create(name: str, description: str = "", keywords: Optional[List[str]] = None,
           seed_paper_ids: Optional[List[str]] = None) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("name is required")
    if resolve(name):
        raise ValueError(f"project '{name}' already exists")
    with Session(engine) as s:
        p = Project(name=name, description=description or "", keywords=json.dumps(keywords or [], ensure_ascii=False))
        s.add(p)
        s.commit()
        s.refresh(p)
    if seed_paper_ids:
        add_papers(p.id, seed_paper_ids, source="seed")
    return get(p.id)


def update(key, name: Optional[str] = None, description: Optional[str] = None,
           keywords: Optional[List[str]] = None, active: Optional[bool] = None) -> Optional[dict]:
    p = resolve(key)
    if p is None:
        return None
    with Session(engine) as s:
        p = s.get(Project, p.id)
        if name is not None and name.strip() and name.strip() != p.name:
            if resolve(name.strip()):
                raise ValueError(f"project '{name}' already exists")
            p.name = name.strip()
        if description is not None:
            p.description = description
        if keywords is not None:
            p.keywords = json.dumps(keywords, ensure_ascii=False)
        if active is not None:
            p.active = active
        p.updated_at = datetime.now()
        s.add(p)
        s.commit()
    return get(p.id)


def delete(key) -> bool:
    p = resolve(key)
    if p is None:
        return False
    with Session(engine) as s:
        for pp in s.exec(select(ProjectPaper).where(ProjectPaper.project_id == p.id)).all():
            s.delete(pp)
        s.delete(s.get(Project, p.id))
        s.commit()
    return True


def add_papers(key, paper_ids: Iterable[str], source: str = "manual", reason: Optional[str] = None,
               similarity: Optional[float] = None) -> Dict[str, List[str]]:
    p = resolve(key)
    if p is None:
        raise ValueError("project not found")
    added, unknown, existing = [], [], []
    with Session(engine) as s:
        for pid in paper_ids:
            pid = pid.strip()
            if not s.get(Paper, pid):
                unknown.append(pid)
                continue
            row = s.get(ProjectPaper, (p.id, pid))
            if row:
                # a manual / seed add upgrades an auto match; never downgrade
                if source in ("seed", "manual") and row.source == "auto":
                    row.source = source
                    s.add(row)
                existing.append(pid)
                continue
            s.add(ProjectPaper(project_id=p.id, paper_id=pid, source=source, reason=reason, similarity=similarity))
            added.append(pid)
        s.commit()
    return {"added": added, "already": existing, "unknown": unknown}


def remove_papers(key, paper_ids: Iterable[str]) -> List[str]:
    p = resolve(key)
    if p is None:
        raise ValueError("project not found")
    removed = []
    with Session(engine) as s:
        for pid in paper_ids:
            row = s.get(ProjectPaper, (p.id, pid))
            if row:
                s.delete(row)
                removed.append(pid)
        s.commit()
    return removed


def get(key, limit: int = 200) -> Optional[dict]:
    from src.services.paper_views import compact_paper
    p = resolve(key)
    if p is None:
        return None
    with Session(engine) as s:
        rows = s.exec(select(ProjectPaper).where(ProjectPaper.project_id == p.id)).all()
        papers = {x.id: x for x in s.exec(select(Paper).where(Paper.id.in_([r.paper_id for r in rows]))).all()} if rows else {}
    items = []
    for r in sorted(rows, key=lambda r: (papers[r.paper_id].published_at if r.paper_id in papers else datetime.min), reverse=True)[:limit]:
        if r.paper_id not in papers:
            continue
        c = compact_paper(papers[r.paper_id])
        c.update(project_source=r.source, project_reason=r.reason, project_similarity=r.similarity,
                 added_at=r.added_at.isoformat())
        items.append(c)
    d = to_dict(p, len(rows))
    d["papers"] = items
    return d


def projects_of(paper_id: str) -> List[str]:
    with Session(engine) as s:
        rows = s.exec(select(ProjectPaper).where(ProjectPaper.paper_id == paper_id)).all()
        names = {p.id: p.name for p in s.exec(select(Project)).all()}
    return [names[r.project_id] for r in rows if r.project_id in names]


# ---------------------------------------------------------------------------- recall
def active_projects() -> List[Project]:
    with Session(engine) as s:
        return list(s.exec(select(Project).where(Project.active == True)).all())  # noqa: E712


def prompt_block(projects: List[Project]) -> str:
    """Stable text listing the active projects (part of cached system prompts)."""
    lines = []
    for p in sorted(projects, key=lambda p: p.name.lower()):
        kw = _kw(p)
        lines.append(f"- {p.name}: {p.description.strip()}" + (f" (keywords: {', '.join(kw)})" if kw else ""))
    return "\n".join(lines)


async def _project_vector(p: Project) -> Optional[np.ndarray]:
    from src.services import embedding_service as es
    with Session(engine) as s:
        seeds = [r.paper_id for r in s.exec(select(ProjectPaper).where(
            ProjectPaper.project_id == p.id, ProjectPaper.source.in_(["seed", "manual"]))).all()]
    parts = []
    sv, _ = es.seed_vector(seeds) if seeds else (None, [])
    if sv is not None:
        parts.append(sv)
    text = " ".join([p.name, p.description or "", ", ".join(_kw(p))]).strip()
    if text:
        try:
            v = np.asarray((await es.embed_texts([text], ref=f"project:{p.id}"))[0], dtype=np.float32)
            parts.append(v / (np.linalg.norm(v) or 1.0))
        except Exception as e:
            print(f"  - project embedding failed for {p.name}: {e}")
    if not parts:
        return None
    m = np.mean(np.stack(parts), axis=0)
    return m / (np.linalg.norm(m) or 1.0)


async def embedding_candidates(paper_ids: List[str], projects: List[Project]) -> Dict[str, List[Tuple[str, float]]]:
    """{paper_id: [(project_name, cosine)]} for papers within PROJECT_SIM_THRESHOLD of a project."""
    from src.services import embedding_service as es
    out: Dict[str, List[Tuple[str, float]]] = {}
    if not paper_ids or not projects:
        return out
    try:
        es._ensure_index()
    except Exception:
        return out
    allowed = set(paper_ids)
    for p in projects:
        qv = await _project_vector(p)
        if qv is None:
            continue
        for pid, sim in es.index.search(qv, k=len(allowed), allowed=allowed):
            if sim >= float(settings.PROJECT_SIM_THRESHOLD):
                out.setdefault(pid, []).append((p.name, round(float(sim), 4)))
    return out


async def suggestions(key, k: int = 20, days: Optional[int] = None) -> List[dict]:
    """Papers already in the library that look like this project but are not in it yet."""
    from src.services import embedding_service as es
    from src.services.paper_views import compact_paper
    p = resolve(key)
    if p is None:
        return []
    with Session(engine) as s:
        have = {r.paper_id for r in s.exec(select(ProjectPaper).where(ProjectPaper.project_id == p.id)).all()}
    qv = await _project_vector(p)
    if qv is None:
        return []
    es._ensure_index()
    hits = es.index.search(qv, k=k + len(have), exclude=have or None)[:k]
    with Session(engine) as s:
        by_id = {x.id: x for x in s.exec(select(Paper).where(Paper.id.in_([h[0] for h in hits]))).all()}
    out = []
    for pid, sim in hits:
        if pid in by_id:
            c = compact_paper(by_id[pid])
            c["similarity"] = round(float(sim), 4)
            out.append(c)
    return out
