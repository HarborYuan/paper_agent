"""
Verdict pipeline (SCORING_PIPELINE = "verdict"), Claude API direct.

  screen  (stage-1 model, Haiku)  title + abstract -> relevance tier 0-5
  review  (stage-2 model, Sonnet) abstract + first STAGE2_TEXT_CHAR_LIMIT chars -> verdict + affiliations
  deep    (summary model, Sonnet) whole paper as reading units -> final verdict, summary,
                                   per-group gist + claim flags
  translate (translate model, Haiku) every unit -> Chinese, alongside the deep read

Verdicts map onto the existing 0-100 score so the UI, MCP, reports and thresholds keep working:
must_read 92-99, worth_reading 85-91, skim 60-84, skip 20-59 (position inside the band from
novelty + evidence + reusability). Papers at must_read / worth_reading get the deep read; the
deep read's verdict is final. score_reason keeps the {"stage1", "stage2"} shape plus "deep".
"""
import asyncio
import json
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

from sqlmodel import Session, select

from src.config import settings
from src.database import engine
from src.models import Author, Paper, PaperReading
from src.services import claude_budget, project_service, reading_service
from src.services.claude_runner import ClaudeRequest, ClaudeRunner
from src.services.pdf_service import pdf_service
from src.services.prompt_service import prompt_service
from src.services.settings_service import (TASK_STAGE1, TASK_STAGE2, TASK_SUMMARY, get_llm_config)
from src.utils import sanitize_text

TASK_TRANSLATE = "translate"
VERDICTS = ["must_read", "worth_reading", "skim", "skip"]
PUSH_VERDICTS = ("must_read", "worth_reading")
BANDS = {"must_read": (92, 99), "worth_reading": (85, 91), "skim": (60, 84), "skip": (20, 59)}

# ---------------------------------------------------------------------------- schemas
_DIM = {"type": "integer", "enum": [0, 1, 2, 3, 4, 5]}
_STRS = {"type": "array", "items": {"type": "string"}}
_NSTR = {"type": ["string", "null"]}


def _obj(props: Dict[str, Any]) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


SCREEN_SCHEMA = _obj({
    "main_contribution": {"type": "string"}, "matched_interest": {"type": "string"},
    "matched_section": {"type": "string", "enum": ["core", "strong", "angle", "excluded", "none"]},
    "relevance": _DIM, "one_line_reason": {"type": "string"},
})
REVIEW_SCHEMA = _obj({
    "strengths": _STRS, "weaknesses": _STRS, "risk_flags": _STRS,
    "relevance": _DIM, "novelty": _DIM, "evidence": _DIM, "reusability": _DIM,
    "verdict": {"type": "string", "enum": VERDICTS}, "one_line_reason": {"type": "string"},
    "affiliations": _STRS, "main_company": _NSTR, "main_university": _NSTR, "main_affiliation": _NSTR,
})
_FLAG = _obj({"id": {"type": "string"}, "span": {"type": "string"},
              "kind": {"type": "string", "enum": ["questionable", "big_claim"]}, "why": {"type": "string"}})
DEEP_SCHEMA = _obj({
    "verdict": {"type": "string", "enum": VERDICTS}, "verdict_change_reason": {"type": "string"},
    "relevance": _DIM, "novelty": _DIM, "evidence": _DIM, "reusability": _DIM,
    "one_line_reason": {"type": "string"}, "tldr": {"type": "string"},
    "notes": {"type": "array", "items": _obj({"ids": _STRS, "gist": {"type": "string"},
                                               "flags": {"type": "array", "items": _FLAG}})},
})
def screen_schema(project_names: List[str]) -> dict:
    if not project_names:
        return SCREEN_SCHEMA
    props = dict(SCREEN_SCHEMA["properties"])
    props["matched_projects"] = {"type": "array", "items": {"type": "string", "enum": sorted(project_names)}}
    return _obj(props)


def review_schema(project_names: List[str]) -> dict:
    if not project_names:
        return REVIEW_SCHEMA
    props = dict(REVIEW_SCHEMA["properties"])
    props["project_matches"] = {"type": "array", "items": _obj({
        "project": {"type": "string", "enum": sorted(project_names)}, "relevant": {"type": "boolean"},
        "reason": {"type": "string"}})}
    return _obj(props)


TRANSLATE_SCHEMA = _obj({"translations": {"type": "array", "items": _obj({"id": {"type": "string"}, "zh": {"type": "string"}})}})


# ---------------------------------------------------------------------------- helpers
def verdict_score(verdict: str, d: Dict[str, Any]) -> int:
    lo, hi = BANDS.get(verdict, BANDS["skip"])
    q = (int(d.get("novelty") or 0) + int(d.get("evidence") or 0) + int(d.get("reusability") or 0)) / 15
    return int(round(lo + q * (hi - lo)))


def _authors_str(p: Paper) -> str:
    a = p.authors_list
    return ", ".join(a[:8]) + (f" (+{len(a) - 8} more)" if len(a) > 8 else "")


def _profile() -> str:
    return settings.USER_PROFILE


def _reason(p: Paper) -> Dict[str, Any]:
    try:
        d = json.loads(p.score_reason) if p.score_reason else {}
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        return {}


def score_to_verdict(score: Optional[int]) -> str:
    """Inverse of the verdict bands, for scores from the old two-stage pipeline."""
    s = int(score or 0)
    return "must_read" if s >= 92 else "worth_reading" if s >= 85 else "skim" if s >= 60 else "skip"


def provisional_review(p: Paper) -> Optional[Dict[str, Any]]:
    """
    The review a deep read starts from. A two-stage review from the old pipeline (0-100 score, quality /
    clarity, no verdict) is reused, not redone: its score is mapped to a verdict and quality stands in
    for evidence. None when the paper was never reviewed.
    """
    s2 = _reason(p).get("stage2")
    if not isinstance(s2, dict) or s2.get("error"):
        return None
    if s2.get("verdict") in VERDICTS:
        return s2
    return {"verdict": score_to_verdict(s2.get("score", p.score)), "relevance": s2.get("relevance", 0),
            "novelty": s2.get("novelty", 0), "evidence": s2.get("quality", 0), "reusability": 0,
            "one_line_reason": s2.get("one_line_reason") or "(review from the previous scoring pipeline)",
            "legacy": True}


def _important_ids(papers: Iterable[Paper]) -> set:
    """Papers with at least one author marked important (they skip the gates and get >= 90)."""
    with Session(engine) as s:
        names = {a.name for a in s.exec(select(Author).where(Author.is_important == True)).all()}  # noqa: E712
    if not names:
        return set()
    return {p.id for p in papers if any(n in names for n in p.authors_list)}


def _save(paper: Paper, **fields) -> None:
    with Session(engine) as s:
        db = s.get(Paper, paper.id)
        if not db:
            return
        for k, v in fields.items():
            setattr(db, k, v)
        db.updated_at = datetime.now()
        s.add(db)
        s.commit()
        for k, v in fields.items():
            setattr(paper, k, v)


def _verify_flags(notes: List[dict], units: List[dict]) -> None:
    text = {u["id"]: (u.get("text") or u.get("caption") or "") for u in units}
    norm = lambda t: re.sub(r"\s+", " ", t or "").strip()
    for n in notes:
        for f in n.get("flags", []):
            f["verified"] = bool(f.get("span")) and norm(f["span"]) in norm(text.get(f.get("id"), ""))


# ---------------------------------------------------------------------------- request builders
def screen_request(p: Paper, model: str, projects: Optional[list] = None) -> ClaudeRequest:
    projects = projects or []
    return ClaudeRequest(
        key=f"screen:{p.id}", task=TASK_STAGE1, model=model, paper_id=p.id,
        schema=screen_schema([x.name for x in projects]),
        system=prompt_service.render_prompt("screen_system.jinja2", user_profile=_profile(),
                                            projects=project_service.prompt_block(projects)),
        user=prompt_service.render_prompt("screen_user.jinja2", paper=p), max_tokens=4000, effort="low")


def review_request(p: Paper, full_text: Optional[str], model: str, projects: Optional[list] = None,
                   candidates: Optional[List[str]] = None) -> ClaudeRequest:
    limit = settings.STAGE2_TEXT_CHAR_LIMIT
    ex = full_text[:limit] if full_text else None
    projects = projects or []
    return ClaudeRequest(
        key=f"review:{p.id}", task=TASK_STAGE2, model=model, paper_id=p.id,
        schema=review_schema([x.name for x in projects]),
        system=prompt_service.render_prompt("review_system.jinja2", user_profile=_profile(),
                                            projects=project_service.prompt_block(projects)),
        user=prompt_service.render_prompt(
            "review_user.jinja2", paper=p, authors_str=_authors_str(p), text_snippet=ex,
            truncated=bool(full_text) and len(full_text) > limit,
            visible_pct=round(100 * len(ex) / len(full_text)) if full_text else 100,
            candidate_projects=sorted(candidates or [])),
        max_tokens=16000)


def deep_request(p: Paper, review: Dict[str, Any], units: Optional[List[dict]], full_text: Optional[str],
                 model: str) -> ClaudeRequest:
    return ClaudeRequest(
        key=f"deep:{p.id}", task=TASK_SUMMARY, model=model, paper_id=p.id, schema=DEEP_SCHEMA,
        system=prompt_service.render_prompt("deep_system.jinja2", user_profile=_profile(),
                                            language=settings.SUMMARY_LANGUAGE),
        user=prompt_service.render_prompt(
            "deep_user.jinja2", paper=p, authors_str=_authors_str(p), review=SimpleNamespace(**review),
            units=units, full_text=(full_text or "")[:300_000] if not units else None),
        max_tokens=48000)


def translate_request(p: Paper, units: List[dict]) -> ClaudeRequest:
    return ClaudeRequest(
        key=f"translate:{p.id}", task=TASK_TRANSLATE, model=get_llm_config().translate_model, paper_id=p.id,
        schema=TRANSLATE_SCHEMA,
        system=prompt_service.render_prompt("translate_system.jinja2"),
        user=prompt_service.render_prompt("translate_user.jinja2", units=units), max_tokens=64000, effort="low")


# ---------------------------------------------------------------------------- text
async def _full_text(p: Paper) -> Optional[str]:
    if p.full_text:
        return p.full_text
    if not p.pdf_url:
        return None
    try:
        text = await pdf_service.extract_text_from_url(p.pdf_url)
    except Exception:
        text = None
    if text:
        _save(p, full_text=sanitize_text(text))
    return p.full_text


# ---------------------------------------------------------------------------- stages
async def screen(papers: List[Paper], runner: ClaudeRunner, log=None, batch=None,
                 keep: Iterable[str] = (), projects: Optional[list] = None) -> Dict[str, dict]:
    """Papers below SCREEN_MIN_RELEVANCE (and not in `keep`) become FILTERED; the rest stay NEW until
    reviewed, so a failed review is simply retried on the next run."""
    model = get_llm_config().stage1_model
    keep = set(keep)
    res = await runner.run([screen_request(p, model, projects) for p in papers], log, batch=batch)
    out = {}
    for p in papers:
        r = res.get(f"screen:{p.id}")
        if r is None or not r.ok:
            continue  # stays NEW; retried next run
        d = r.data
        s1 = 20 * int(d["relevance"])
        reason = {"pipeline": "verdict", "stage1": {"model": model, "score": s1, **d}}
        passed = d["relevance"] >= settings.SCREEN_MIN_RELEVANCE or p.id in keep or bool(d.get("matched_projects"))
        _save(p, score_stage1=s1, score=s1, score_model=model, score_reason=json.dumps(reason, ensure_ascii=False),
              status="NEW" if passed else "FILTERED")
        out[p.id] = d
    return out


async def review(papers: List[Paper], runner: ClaudeRunner, log=None, batch=None, projects: Optional[list] = None,
                 candidates: Optional[Dict[str, Dict[str, Optional[float]]]] = None) -> Dict[str, dict]:
    """candidates: {paper_id: {project_name: cosine or None}}; confirmed matches join the project."""
    model = get_llm_config().stage2_model
    candidates = candidates or {}
    texts = await asyncio.gather(*(_full_text(p) for p in papers))
    res = await runner.run([review_request(p, t, model, projects, list(candidates.get(p.id, {})))
                            for p, t in zip(papers, texts)], log, batch=batch)
    out = {}
    for p, t in zip(papers, texts):
        r = res.get(f"review:{p.id}")
        if r is None or not r.ok:
            continue
        d = r.data
        score = verdict_score(d["verdict"], d)
        reason = _reason(p)
        reason["stage2"] = {"model": model, "had_full_text": bool(t), "score": score, **d}
        fields = dict(score=score, score_model=model, score_reason=json.dumps(reason, ensure_ascii=False),
                      status="SCORED" if d["verdict"] in PUSH_VERDICTS else "FILTERED")
        if d.get("affiliations"):
            fields.update(affiliations=sanitize_text(json.dumps(d["affiliations"], ensure_ascii=False)),
                          main_company=sanitize_text(d.get("main_company")),
                          main_university=sanitize_text(d.get("main_university")),
                          main_affiliation=sanitize_text(d.get("main_affiliation")))
        _save(p, **fields)
        cand = candidates.get(p.id, {})
        for m in d.get("project_matches", []) or []:
            if m.get("relevant") and m.get("project") in cand:
                try:
                    project_service.add_papers(m["project"], [p.id], source="auto", reason=m.get("reason"),
                                               similarity=cand[m["project"]])
                except ValueError:
                    pass
        out[p.id] = d
    return out


async def deep_read(papers: List[Paper], runner: ClaudeRunner, log=None, batch=None,
                    final: bool = True) -> Dict[str, dict]:
    """
    Full read + translation. With final=True (pipeline) the deep verdict sets the final score and
    status (SUMMARIZED when it clears SCORE_THRESHOLD); with final=False (on-demand) only the
    reading, summary and score_reason["deep"] are written.
    """
    cfg = get_llm_config()
    model = cfg.summary_model
    reqs, ctx = [], {}
    for p in papers:
        reason = _reason(p)
        rv = provisional_review(p) or {"verdict": "worth_reading", "relevance": 0, "novelty": 0, "evidence": 0,
                                       "reusability": 0, "one_line_reason": "(no provisional review)"}
        units = await reading_service.fetch_units(p.id, p.pdf_url)
        text = None if units else await _full_text(p)
        ctx[p.id] = (units, rv)
        _upsert_reading(p.id, status="RUNNING", source="html" if units else "text", model=model,
                        units=reading_service.dumps(units) if units else None, error=None)
        reqs.append(deep_request(p, rv, units, text, model))
        if units:
            reqs.append(translate_request(p, units))
    res = await runner.run(reqs, log, batch=batch)
    important = _important_ids(papers) if final else set()
    out = {}
    for p in papers:
        units, rv = ctx[p.id]
        r = res.get(f"deep:{p.id}")
        if r is None or not r.ok:
            _upsert_reading(p.id, status="ERROR", error=(r.error if r else "no result"))
            continue
        d = r.data
        notes = d.pop("notes", [])
        tl = (d.pop("tldr", "") or "").strip()
        summary = f"## TL;DR\n{tl}" if tl else ""
        if units:
            _verify_flags(notes, units)
        tr = res.get(f"translate:{p.id}")
        translations = {t["id"]: t["zh"] for t in (tr.data or {}).get("translations", [])} if tr and tr.ok else {}
        score = verdict_score(d["verdict"], d)
        reason = _reason(p)
        reason["deep"] = {"model": model, "score": score, **d}
        fields: Dict[str, Any] = dict(score_reason=json.dumps(reason, ensure_ascii=False),
                                      summary_personalized=sanitize_text(summary) or p.summary_personalized)
        if final:
            if p.id in important and score < 90:
                reason["boost"] = {"reason": "important_author", "from": score, "to": 90}
                fields["score_reason"] = json.dumps(reason, ensure_ascii=False)
                score = 90
            fields.update(score=score, score_model=model,
                          status="SUMMARIZED" if score >= cfg.score_threshold else "FILTERED")
        _save(p, **fields)
        _upsert_reading(p.id, status="DONE", notes=json.dumps(notes, ensure_ascii=False),
                        translations=json.dumps(translations, ensure_ascii=False),
                        deep=json.dumps(reason["deep"], ensure_ascii=False), error=None)
        out[p.id] = reason["deep"]
    return out


def _upsert_reading(paper_id: str, **fields) -> None:
    with Session(engine) as s:
        row = s.get(PaperReading, paper_id) or PaperReading(paper_id=paper_id)
        for k, v in fields.items():
            setattr(row, k, v)
        row.updated_at = datetime.now()
        s.add(row)
        s.commit()


# ---------------------------------------------------------------------------- orchestration
class BudgetExceeded(RuntimeError):
    pass


async def _say(log, msg):
    if log:
        await log(msg)
    else:
        print(msg)


def select_for_deep(papers: List[Paper], limit: int) -> List[Paper]:
    """Most valuable first: must_read before worth_reading, then by score."""
    rank = {"must_read": 0, "worth_reading": 1}

    def key(p):
        v = (provisional_review(p) or {}).get("verdict")
        return (rank.get(v, 2), -(p.score or 0))
    return sorted(papers, key=key)[:max(0, limit)]


async def run_pipeline(papers: List[Paper], runner: Optional[ClaudeRunner] = None, log=None,
                       batch: Optional[bool] = None, deep_limit: Optional[int] = None) -> Dict[str, int]:
    """
    Screen -> review -> deep read for NEW papers (user-scored papers are skipped). Every stage is
    sized against the Claude budget first; whatever does not fit stays NEW / SCORED for the next run.
    """
    runner = runner or ClaudeRunner()
    papers = [p for p in papers if p.user_score is None]
    stats = {"screened": 0, "reviewed": 0, "deep_read": 0, "deferred": 0, "project_candidates": 0}
    if not papers:
        return stats
    n = claude_budget.affordable("screen", len(papers))
    if n < len(papers):
        await _say(log, f"Claude budget: screening {n} of {len(papers)} papers ({claude_budget.status()})")
        stats["deferred"] += len(papers) - n
        papers = papers[:n]
    if not papers:
        return stats
    important = _important_ids(papers)
    projects = project_service.active_projects()
    emb = await project_service.embedding_candidates([p.id for p in papers], projects) if projects else {}
    s = await screen(papers, runner, log, batch, keep=important | set(emb), projects=projects)
    stats["screened"] = len(s)
    # project candidates from both routes: {paper_id: {project: cosine or None}}
    cand: Dict[str, Dict[str, Optional[float]]] = {}
    for pid, hits in emb.items():
        cand.setdefault(pid, {}).update({name: sim for name, sim in hits})
    for pid, d in s.items():
        for name in d.get("matched_projects", []) or []:
            cand.setdefault(pid, {}).setdefault(name, None)
    stats["project_candidates"] = len(cand)
    to_review = [p for p in papers if p.id in s and (s[p.id]["relevance"] >= settings.SCREEN_MIN_RELEVANCE
                                                    or p.id in important or p.id in cand)]
    to_review.sort(key=lambda p: -s[p.id]["relevance"])
    n = claude_budget.affordable("review", len(to_review))
    if n < len(to_review):
        await _say(log, f"Claude budget: reviewing {n} of {len(to_review)} papers; the rest stay NEW")
        stats["deferred"] += len(to_review) - n
        to_review = to_review[:n]
    await _say(log, f"Screen: {len(s)} scored, {len(to_review)} go to review")
    rv = await review(to_review, runner, log, batch, projects=projects, candidates=cand)
    stats["reviewed"] = len(rv)
    to_deep = [p for p in to_review if p.id in rv and (rv[p.id]["verdict"] in PUSH_VERDICTS or p.id in important)]
    limit = deep_limit if deep_limit is not None else settings.DEEP_READ_MAX_PER_RUN
    limit = min(limit, claude_budget.affordable("deep", len(to_deep)))
    chosen = select_for_deep(to_deep, limit)
    if len(chosen) < len(to_deep):
        await _say(log, f"Deep read: {len(chosen)} of {len(to_deep)} this run (cap / budget); the rest stay SCORED")
        stats["deferred"] += len(to_deep) - len(chosen)
    await _say(log, f"Review: {len(rv)} reviewed, {len(chosen)} go to deep read")
    dr = await deep_read(chosen, runner, log, batch, final=True)
    stats["deep_read"] = len(dr)
    return stats


async def deep_read_on_demand(paper_id: str, log=None) -> Optional[dict]:
    """Deep read one paper now (real time), reviewing it first if it has no review yet."""
    with Session(engine) as s:
        p = s.get(Paper, paper_id)
    if p is None:
        return None
    if claude_budget.affordable("deep", 3) < 3:   # real time costs ~2x batch; keep a margin
        raise BudgetExceeded(f"Claude budget nearly used up: {claude_budget.status()}")
    runner = ClaudeRunner(use_batch=False)
    if provisional_review(p) is None:   # never reviewed (old two-stage reviews are reused)
        await review([p], runner, log, batch=False)
    res = await deep_read([p], runner, log, batch=False, final=False)
    return res.get(paper_id)


def get_reading(paper_id: str) -> Optional[dict]:
    with Session(engine) as s:
        row = s.get(PaperReading, paper_id)
    if row is None:
        return None
    load = lambda v, default: json.loads(v) if v else default
    return {"paper_id": row.paper_id, "status": row.status, "source": row.source, "model": row.model,
            "error": row.error, "units": load(row.units, []), "notes": load(row.notes, []),
            "translations": load(row.translations, {}), "deep": load(row.deep, None),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}
