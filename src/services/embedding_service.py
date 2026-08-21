"""
Embeddings for papers (title + abstract): semantic search, related papers, topic clustering.

- Vectors come from the OpenAI-compatible /embeddings endpoint (OpenRouter by default; the model
  is EMBEDDING_MODEL, truncated to EMBEDDING_DIM when > 0). One row per paper in PaperEmbedding,
  float32 little-endian bytes; `model`/`dim` recorded so a model switch is detectable.
- Retrieval is brute-force cosine over an in-memory, L2-normalised numpy matrix (tens of
  thousands of 512-d vectors = tens of MB; a query is a single matrix-vector product).
- Every embeddings call is logged to LLMUsage under task "embed" (tokens + cost).
"""
import asyncio
import math
import time
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import httpx
import numpy as np
from sqlmodel import Session, select
from sqlalchemy import func

from src.config import settings
from src.database import engine
from src.models import Paper, PaperEmbedding, LLMUsage
from src.services.model_catalog import model_catalog
from src.services.settings_service import TASK_EMBED

MAX_TEXT_CHARS = 6000


def current_model() -> str:
    return settings.EMBEDDING_MODEL


def current_dim() -> int:
    try:
        return int(settings.EMBEDDING_DIM or 0)
    except (TypeError, ValueError):
        return 0


def paper_text(paper: Paper) -> str:
    text = f"{paper.title or ''}\n\n{paper.summary_generic or ''}".strip()
    return text[:MAX_TEXT_CHARS]


def to_bytes(vec: Sequence[float]) -> bytes:
    return np.asarray(vec, dtype="<f4").tobytes()


def from_bytes(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype="<f4")


def _record_usage(model: str, usage: Optional[dict], latency_ms: int, ok: bool, ref: Optional[str]) -> None:
    try:
        prompt_tokens = int((usage or {}).get("prompt_tokens") or (usage or {}).get("total_tokens") or 0)
        cost = (usage or {}).get("cost")
        cost_est = False
        if cost is None and prompt_tokens:
            est = model_catalog.estimate_cost(model, prompt_tokens, 0)
            if est is not None:
                cost, cost_est = est, True
        with Session(engine) as s:
            s.add(LLMUsage(paper_id=ref, task=TASK_EMBED, model=model, prompt_tokens=prompt_tokens,
                           completion_tokens=0, total_tokens=prompt_tokens,
                           cost=float(cost) if cost is not None else None, cost_estimated=cost_est,
                           latency_ms=latency_ms, success=ok))
            s.commit()
    except Exception as e:
        print(f"  - (embedding usage logging failed: {e})")


async def embed_texts(texts: List[str], *, model: Optional[str] = None, dims: Optional[int] = None,
                      ref: Optional[str] = None) -> List[List[float]]:
    """Embed a batch of texts. Raises on failure (callers decide how to degrade)."""
    if not texts:
        return []
    model = model or current_model()
    dims = current_dim() if dims is None else dims
    if not settings.llm_api_key:
        raise RuntimeError("No LLM API key configured")
    url = settings.llm_base_url.rstrip("/") + "/embeddings"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json",
               "HTTP-Referer": "https://github.com/HarborYuan/paper_agent", "X-Title": "Paper Agent"}
    body: Dict = {"model": model, "input": texts}
    if dims and dims > 0:
        body["dimensions"] = dims
    attempts = [body]
    if "dimensions" in body:
        attempts.append({k: v for k, v in body.items() if k != "dimensions"})   # fallback: model ignores/rejects dims
    last_err = None
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, payload in enumerate(attempts):
            t0 = time.monotonic()
            try:
                resp = await client.post(url, headers=headers, json=payload)
                latency = int((time.monotonic() - t0) * 1000)
                if resp.status_code >= 400:
                    msg = resp.text[:300]
                    if i == 0 and len(attempts) > 1 and resp.status_code in (400, 404, 422):
                        print(f"  - embeddings ({model}) rejected dimensions={dims}: {msg}; retrying without")
                        continue
                    _record_usage(model, None, latency, False, ref)
                    raise RuntimeError(f"embeddings HTTP {resp.status_code}: {msg}")
                data = resp.json()
                vectors = [item["embedding"] for item in sorted(data["data"], key=lambda x: x.get("index", 0))]
                _record_usage(model, data.get("usage"), latency, True, ref)
                return vectors
            except httpx.HTTPError as e:
                last_err = e
                _record_usage(model, None, int((time.monotonic() - t0) * 1000), False, ref)
                break
    raise RuntimeError(f"embeddings request failed: {last_err}")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def missing_paper_ids(limit: Optional[int] = None, only_ids: Optional[List[str]] = None) -> List[str]:
    """Papers without a vector for the current model/dim (stale rows from other models count as missing)."""
    model = current_model()
    with Session(engine) as s:
        have = set(s.exec(select(PaperEmbedding.paper_id).where(PaperEmbedding.model == model)).all())
        q = select(Paper.id).order_by(Paper.published_at.desc())
        if only_ids is not None:
            q = q.where(Paper.id.in_(only_ids))
        ids = [pid for pid in s.exec(q).all() if pid not in have]
    return ids[:limit] if limit else ids


async def embed_papers(paper_ids: List[str], log=None) -> int:
    """Embed the given papers in batches and upsert their vectors. Returns the number embedded."""
    if not paper_ids:
        return 0
    model, dims = current_model(), current_dim()
    batch = max(1, int(settings.EMBEDDING_BATCH_SIZE or 64))
    done = 0
    for i in range(0, len(paper_ids), batch):
        chunk = paper_ids[i:i + batch]
        with Session(engine) as s:
            papers = s.exec(select(Paper).where(Paper.id.in_(chunk))).all()
        papers = [p for p in papers if p.title]
        if not papers:
            continue
        vectors = await embed_texts([paper_text(p) for p in papers], ref=f"embed:batch:{len(papers)}")
        now = datetime.now()
        with Session(engine) as s:
            for p, vec in zip(papers, vectors):
                row = s.get(PaperEmbedding, p.id)
                if row is None:
                    row = PaperEmbedding(paper_id=p.id, model=model, dim=len(vec), vector=to_bytes(vec), created_at=now)
                else:
                    row.model, row.dim, row.vector, row.created_at = model, len(vec), to_bytes(vec), now
                s.add(row)
            s.commit()
        index.add([p.id for p in papers], np.asarray(vectors, dtype=np.float32), model)
        done += len(papers)
        if log:
            await log(f"  - Embedded {done}/{len(paper_ids)} papers ({model})")
    return done


async def embed_new_papers(paper_ids: Optional[List[str]] = None, limit: Optional[int] = None, log=None) -> int:
    """Embed papers that have no current-model vector (optionally restricted to `paper_ids`)."""
    ids = missing_paper_ids(limit=limit, only_ids=paper_ids)
    if not ids:
        return 0
    return await embed_papers(ids, log=log)


_backfill = {"running": False, "done": 0, "total": 0, "error": None, "started_at": None, "finished_at": None}


async def backfill(log=None) -> None:
    """Embed every paper that lacks a current-model vector. Runs as a background task; idempotent."""
    if _backfill["running"]:
        return
    _backfill.update(running=True, done=0, error=None, started_at=datetime.now().isoformat(), finished_at=None)
    try:
        ids = missing_paper_ids()
        _backfill["total"] = len(ids)
        batch = max(1, int(settings.EMBEDDING_BATCH_SIZE or 64)) * 4
        for i in range(0, len(ids), batch):
            n = await embed_papers(ids[i:i + batch], log=None)
            _backfill["done"] += n
            if log:
                await log(f"Embedding backfill: {_backfill['done']}/{_backfill['total']}")
            await asyncio.sleep(0)  # yield
    except Exception as e:
        _backfill["error"] = str(e)
        if log:
            await log(f"Embedding backfill failed: {e}")
    finally:
        _backfill["running"] = False
        _backfill["finished_at"] = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# In-memory index
# ---------------------------------------------------------------------------
class EmbeddingIndex:
    def __init__(self):
        self.ids: List[str] = []
        self.pos: Dict[str, int] = {}
        self.matrix: Optional[np.ndarray] = None   # (n, d) L2-normalised float32
        self.model: Optional[str] = None
        self.loaded_at: Optional[datetime] = None
        self._lock = asyncio.Lock()

    def _reset(self, model: str):
        self.ids, self.pos, self.matrix, self.model = [], {}, None, model

    def load(self, force: bool = False) -> int:
        """(Re)load all vectors of the current model from the DB. Returns the index size."""
        model = current_model()
        if not force and self.matrix is not None and self.model == model:
            return len(self.ids)
        with Session(engine) as s:
            rows = s.exec(select(PaperEmbedding.paper_id, PaperEmbedding.vector, PaperEmbedding.dim)
                          .where(PaperEmbedding.model == model)).all()
        self._reset(model)
        if rows:
            dims = {d for _, _, d in rows}
            if len(dims) > 1:
                # mixed dims after an EMBEDDING_DIM change: keep the majority size; others are re-embedded by backfill
                dim = max(dims, key=lambda d: sum(1 for r in rows if r[2] == d))
                rows = [r for r in rows if r[2] == dim]
            mat = np.stack([from_bytes(v) for _, v, _ in rows]).astype(np.float32)
            self.matrix = _normalize(mat)
            self.ids = [pid for pid, _, _ in rows]
            self.pos = {pid: i for i, pid in enumerate(self.ids)}
        self.loaded_at = datetime.now()
        return len(self.ids)

    def add(self, ids: List[str], vectors: np.ndarray, model: str) -> None:
        if self.model != model or self.matrix is None and self.ids:
            self._reset(model)
        vecs = _normalize(np.asarray(vectors, dtype=np.float32))
        if self.matrix is not None and self.matrix.shape[1] != vecs.shape[1]:
            self._reset(model)
        new_rows, new_ids = [], []
        for pid, v in zip(ids, vecs):
            if pid in self.pos:
                self.matrix[self.pos[pid]] = v
            else:
                new_ids.append(pid); new_rows.append(v)
        if new_rows:
            block = np.stack(new_rows)
            self.matrix = block if self.matrix is None else np.vstack([self.matrix, block])
            for pid in new_ids:
                self.pos[pid] = len(self.ids); self.ids.append(pid)

    def vector_of(self, paper_id: str) -> Optional[np.ndarray]:
        i = self.pos.get(paper_id)
        return None if i is None or self.matrix is None else self.matrix[i]

    def search(self, vec: np.ndarray, k: int = 20, exclude: Optional[set] = None,
               allowed: Optional[set] = None) -> List[Tuple[str, float]]:
        """
        Top-k by cosine. `exclude`: ids to skip. `allowed`: if given, only these ids are candidates
        (used for date / score / status filters computed in SQL).
        """
        if self.matrix is None or not len(self.ids):
            return []
        q = _normalize(np.asarray(vec, dtype=np.float32).reshape(1, -1))[0]
        if q.shape[0] != self.matrix.shape[1]:
            return []
        sims = self.matrix @ q
        if allowed is not None:
            mask = np.fromiter((pid in allowed for pid in self.ids), dtype=bool, count=len(self.ids))
            if exclude:
                mask &= np.fromiter((pid not in exclude for pid in self.ids), dtype=bool, count=len(self.ids))
            cand = np.nonzero(mask)[0]
            if cand.size == 0:
                return []
            kk = min(max(k, 1), cand.size)
            sub = sims[cand]
            top = cand[np.argpartition(-sub, kk - 1)[:kk]]
            top = top[np.argsort(-sims[top])]
            return [(self.ids[i], float(sims[i])) for i in top]
        want = max(k, 1)
        kk = min(want + (len(exclude) if exclude else 0), len(self.ids))
        top = np.argpartition(-sims, kk - 1)[:kk]
        top = top[np.argsort(-sims[top])]
        out = []
        for i in top:
            pid = self.ids[i]
            if exclude and pid in exclude:
                continue
            out.append((pid, float(sims[i])))
            if len(out) >= want:
                break
        return out

    def size(self) -> int:
        return len(self.ids)


def _normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


index = EmbeddingIndex()


def _ensure_index() -> None:
    if index.matrix is None or index.model != current_model():
        index.load()


# ---------------------------------------------------------------------------
# Public retrieval API
# ---------------------------------------------------------------------------
def seed_vector(paper_ids: List[str]) -> Tuple[Optional[np.ndarray], List[str]]:
    """Mean of the (normalised) vectors of the given papers. Returns (vector | None, ids without a vector)."""
    _ensure_index()
    vecs, missing = [], []
    for pid in paper_ids:
        v = index.vector_of(pid)
        if v is None:
            with Session(engine) as s:
                row = s.get(PaperEmbedding, pid)
            if row is not None and row.model == current_model():
                v = _normalize(from_bytes(row.vector).reshape(1, -1))[0]
                index.add([pid], v.reshape(1, -1), row.model)
        if v is None:
            missing.append(pid)
        else:
            vecs.append(v)
    if not vecs:
        return None, missing
    m = np.mean(np.stack(vecs), axis=0)
    return _normalize(m.reshape(1, -1))[0], missing


async def semantic_search(query: Optional[str] = None, k: int = 20, seed_ids: Optional[List[str]] = None,
                          allowed: Optional[set] = None, exclude: Optional[set] = None) -> List[Tuple[str, float]]:
    """
    Rank papers by cosine to a query vector built from `query` text and/or the mean vector of `seed_ids`
    (both given -> average of the two). Seed papers are always excluded from the results.
    """
    _ensure_index()
    if not index.size():
        return []
    parts = []
    if query and query.strip():
        parts.append(_normalize(np.asarray((await embed_texts([query.strip()], ref="search"))[0], dtype=np.float32).reshape(1, -1))[0])
    exclude = set(exclude or [])
    if seed_ids:
        sv, _missing = seed_vector(seed_ids)
        if sv is not None:
            parts.append(sv)
        exclude |= set(seed_ids)
    if not parts:
        return []
    qv = _normalize(np.mean(np.stack(parts), axis=0).reshape(1, -1))[0]
    return index.search(qv, k=k, exclude=exclude or None, allowed=allowed)


def related(paper_id: str, k: int = 8) -> Optional[List[Tuple[str, float]]]:
    """Nearest neighbours of a paper by stored vector. None if the paper has no vector yet."""
    _ensure_index()
    v = index.vector_of(paper_id)
    if v is None:
        with Session(engine) as s:
            row = s.get(PaperEmbedding, paper_id)
        if row is None or row.model != current_model():
            return None
        v = from_bytes(row.vector)
        index.add([paper_id], v.reshape(1, -1), row.model)
    return index.search(v, k=k, exclude={paper_id})


def cluster(paper_ids: List[str], k: Optional[int] = None, seed: int = 0) -> Tuple[List[List[str]], List[str]]:
    """
    k-means (cosine, k-means++ init) over the papers' vectors.
    Returns (clusters sorted by size desc, ids without a vector). Fewer than 4 vectors -> one cluster.
    """
    _ensure_index()
    vecs, ids, missing = [], [], []
    for pid in paper_ids:
        v = index.vector_of(pid)
        if v is None:
            missing.append(pid)
        else:
            vecs.append(v); ids.append(pid)
    n = len(ids)
    if n == 0:
        return [], missing
    if n < 4:
        return [ids], missing
    X = np.stack(vecs)
    if k is None:
        k = int(max(2, min(7, round(math.sqrt(n / 2)))))
    k = min(k, n)
    rng = np.random.default_rng(seed)
    # k-means++ init
    centers = [X[rng.integers(n)]]
    for _ in range(1, k):
        d2 = np.min(np.stack([1 - X @ c for c in centers]), axis=0)
        d2 = np.clip(d2, 0, None)
        probs = d2 / d2.sum() if d2.sum() > 0 else np.full(n, 1.0 / n)
        centers.append(X[rng.choice(n, p=probs)])
    C = np.stack(centers)
    labels = np.zeros(n, dtype=int)
    for _ in range(25):
        sims = X @ C.T
        new_labels = np.argmax(sims, axis=1)
        if np.array_equal(new_labels, labels) and _ > 0:
            break
        labels = new_labels
        for j in range(k):
            members = X[labels == j]
            if len(members):
                c = members.mean(axis=0)
                C[j] = c / (np.linalg.norm(c) or 1.0)
    clusters = [[ids[i] for i in range(n) if labels[i] == j] for j in range(k)]
    clusters = [c for c in clusters if c]
    clusters.sort(key=len, reverse=True)
    return clusters, missing


def status() -> Dict:
    model, dim = current_model(), current_dim()
    with Session(engine) as s:
        total = s.exec(select(func.count(Paper.id))).one() or 0
        embedded = s.exec(select(func.count(PaperEmbedding.paper_id)).where(PaperEmbedding.model == model)).one() or 0
        stale = s.exec(select(func.count(PaperEmbedding.paper_id)).where(PaperEmbedding.model != model)).one() or 0
    return {
        "model": model, "dim": dim or "native", "total_papers": int(total), "embedded": int(embedded),
        "missing": int(total) - int(embedded), "stale_other_model": int(stale),
        "index_size": index.size() if index.model == model else 0,
        "index_loaded_at": index.loaded_at.isoformat() if index.loaded_at else None,
        "backfill": dict(_backfill),
        "key_configured": bool(settings.llm_api_key),
    }
