"""
Compact, LLM/agent-friendly views of papers (small payloads, no full text / raw JSON blobs).
"""
import json
import re
from typing import Any, Dict, Optional

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


def tldr(p: Paper, chars: int = TLDR_CHARS) -> str:
    if not p.summary_personalized:
        return ""
    txt = re.sub(r"^#+.*$", "", p.summary_personalized, flags=re.M)
    txt = re.sub(r"^```.*$", "", txt, flags=re.M)
    txt = " ".join(txt.split())
    return txt[:chars] + ("…" if len(txt) > chars else "")


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
