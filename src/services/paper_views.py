"""
Compact, LLM/agent-friendly views of papers (small payloads, no full text / raw JSON blobs).
"""
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from src.models import Paper

TLDR_CHARS = 300


def one_line_reason(p: Paper) -> str:
    if not p.score_reason:
        return ""
    try:
        d = json.loads(p.score_reason)
    except (json.JSONDecodeError, TypeError):
        return p.score_reason if isinstance(p.score_reason, str) and len(p.score_reason) < 200 else ""
    if not isinstance(d, dict):
        return ""
    st = d.get("stage2") or d.get("stage1") or d
    return str(st.get("one_line_reason") or "") if isinstance(st, dict) else ""


def summary_tldr(summary: Optional[str], chars: int = TLDR_CHARS) -> str:
    """
    One-line teaser from a structured summary: the "## TL;DR" section when present,
    otherwise the first heading-free lines. Single line, at most `chars` chars.
    """
    if not summary:
        return ""
    m = re.search(r"^##\s*TL;?DR[^\n]*\n(.*?)(?=^##\s|\Z)", summary, flags=re.M | re.S | re.I)
    txt = m.group(1) if m else summary
    txt = re.sub(r"^#+.*$", "", txt, flags=re.M)
    txt = re.sub(r"^```.*$", "", txt, flags=re.M)
    txt = " ".join(txt.split())
    return txt[:chars] + ("…" if len(txt) > chars else "")


def tldr(p: Paper, chars: int = TLDR_CHARS) -> str:
    return summary_tldr(p.summary_personalized, chars)


def compact_paper(p: Paper, similarity: Optional[float] = None) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "id": p.id,
        "title": p.title,
        "authors": p.authors_list,
        "published_at": p.published_at.isoformat() if p.published_at else None,
        "category": p.category_primary,
        "score": p.score,
        "user_score": p.user_score,
        "status": p.status,
        "main_affiliation": p.main_affiliation,
        "main_company": p.main_company,
        "reason": one_line_reason(p),
        "tldr": tldr(p),
        "has_summary": bool(p.summary_personalized),
        "pdf_url": p.pdf_url,
        "abs_url": f"https://arxiv.org/abs/{p.id}",
    }
    if similarity is not None:
        d["similarity"] = round(float(similarity), 4)
    return d


def short_authors(names: List[str], head: int = 4, max_full: int = 6) -> Tuple[List[str], int, Optional[str]]:
    """
    Shorten an author list for tight spaces without ever dropping the last author:
    up to `max_full` names stay whole; longer lists become (first `head`, hidden count, last).
    Returns (shown_head, hidden, last); hidden == 0 and last is None means the list is whole.
    """
    names = list(names or [])
    if len(names) <= max_full:
        return names, 0, None
    return names[:head], len(names) - head - 1, names[-1]


def short_authors_text(names: List[str], head: int = 4, max_full: int = 6) -> str:
    """"A, B, C, D, … (+5), Z" — plain-text form of short_authors."""
    shown, hidden, last = short_authors(names, head, max_full)
    return ", ".join(shown) + (f", … (+{hidden}), {last}" if last is not None else "")


def paper_verdict(p: Paper) -> Optional[str]:
    """Final verdict (deep read if any, else the review) or None."""
    try:
        r = json.loads(p.score_reason) if p.score_reason else {}
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(r, dict):
        return None
    fin = r.get("deep") or r.get("stage2") or {}
    return fin.get("verdict") if isinstance(fin, dict) else None


def reading_badges(session, ids: List[str]) -> Dict[str, dict]:
    """{paper_id: {"status", "flags": {"q": n, "b": n}}} for papers that have a deep read row."""
    from sqlmodel import select
    from src.models import PaperReading
    out: Dict[str, dict] = {}
    if not ids:
        return out
    rows = session.exec(select(PaperReading.paper_id, PaperReading.status, PaperReading.notes)
                        .where(PaperReading.paper_id.in_(ids))).all()
    for pid, status, notes in rows:
        try:
            ns = json.loads(notes) if notes else []
        except json.JSONDecodeError:
            ns = []
        fl = [f for n in ns for f in n.get("flags", []) if f.get("verified")]
        out[pid] = {"status": status, "flags": {"q": sum(f.get("kind") == "questionable" for f in fl),
                                                "b": sum(f.get("kind") == "big_claim" for f in fl)}}
    return out


ABSTRACT_CHARS = 600


def card_paper(p: Paper, reading: Optional[dict] = None) -> Dict[str, Any]:
    """What a home-page card shows: no full text, no raw scoring JSON, the abstract cut to a teaser."""
    try:
        cats = json.loads((p.all_categories or "[]").replace("'", '"'))
    except json.JSONDecodeError:
        cats = [p.category_primary]
    abstract = " ".join((p.summary_generic or "").split())
    return {
        "id": p.id,
        "title": p.title,
        "authors": p.authors_list,
        "published_at": p.published_at.isoformat() if p.published_at else None,
        "category_primary": p.category_primary,
        "all_categories": cats,
        "pdf_url": p.pdf_url,
        "score": p.score,
        "user_score": p.user_score,
        "score_stage1": p.score_stage1,
        "score_model": p.score_model,
        "status": p.status,
        "main_affiliation": p.main_affiliation,
        "main_company": p.main_company,
        "verdict": paper_verdict(p),
        "tldr": summary_tldr(p.summary_personalized, 400),
        "abstract": abstract[:ABSTRACT_CHARS] + ("…" if len(abstract) > ABSTRACT_CHARS else ""),
        "reading": reading,
    }
