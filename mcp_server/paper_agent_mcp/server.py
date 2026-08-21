"""
Paper Agent MCP server (stdio).

Thin, explicit tools over the Paper Agent HTTP API so an LLM agent (Claude Code, etc.) can:
search papers semantically or by title, pull recent high-scoring papers, follow people of interest,
read a paper's summary / full text, browse trend reports, and write feedback back (user scores,
important people). Every tool returns compact JSON-serialisable data.

Run:  paper-agent-mcp --base-url http://nas:8000      (or env PAPER_AGENT_URL)
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional

import httpx
try:                                   # mcp SDK 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:                    # mcp SDK 1.x
    from mcp.server.fastmcp import FastMCP

DEFAULT_URL = os.environ.get("PAPER_AGENT_URL", "http://nas:8000")
_base_url = DEFAULT_URL.rstrip("/")
_timeout = float(os.environ.get("PAPER_AGENT_TIMEOUT", "90"))

mcp = FastMCP(
    "paper-agent",
    instructions=(
        "Tools for the user's personal arXiv Paper Agent (scores every new cs.CV/cs.CL/cs.AI paper against "
        "their research profile, summarises the best ones, writes daily/weekly/monthly trend reports). "
        "Use search_papers for topic questions (semantic, any language; optionally seed with paper ids), "
        "recent_papers for 'what came out lately', papers_by_people for people of interest, get_paper to read "
        "one paper in depth (summary, scoring rationale, optional full text), related_papers for neighbours, "
        "list_reports/get_report for trend reports. set_user_score and mark_people_important write the user's "
        "feedback back so future scoring improves. Paper ids are arXiv ids like 2608.19556."
    ),
)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _client() -> httpx.Client:
    return httpx.Client(base_url=_base_url, timeout=_timeout, headers={"User-Agent": "paper-agent-mcp/1.0"})


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(f"Paper Agent API {resp.status_code} on {resp.request.method} {resp.request.url.path}: {detail}")


def _get(path: str, **params: Any) -> Any:
    params = {k: v for k, v in params.items() if v is not None}
    with _client() as c:
        r = c.get(path, params=params)
        _raise_for(r)
        return r.json()


def _post(path: str, body: Optional[Dict[str, Any]] = None, **params: Any) -> Any:
    params = {k: v for k, v in params.items() if v is not None}
    with _client() as c:
        r = c.post(path, json=body, params=params)
        _raise_for(r)
        return r.json()


def _patch(path: str, body: Optional[Dict[str, Any]] = None, **params: Any) -> Any:
    params = {k: v for k, v in params.items() if v is not None}
    with _client() as c:
        r = c.patch(path, json=body, params=params)
        _raise_for(r)
        return r.json()


# ---------------------------------------------------------------------------
# Tools — discovery
# ---------------------------------------------------------------------------
@mcp.tool()
def search_papers(
    query: Optional[str] = None,
    seed_ids: Optional[List[str]] = None,
    days: Optional[int] = None,
    min_score: Optional[int] = None,
    status: Optional[List[str]] = None,
    category: Optional[str] = None,
    exclude_ids: Optional[List[str]] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Semantic search over all papers (title+abstract embeddings). Give a natural-language `query` (any language)
    and/or `seed_ids` (arXiv ids — searches near their mean vector, seeds excluded). Filters: `days` (published
    within the last N days), `min_score` (e.g. 85 = the digest threshold), `status` (e.g. ["PUSHED"]),
    `category` (e.g. "cs.CV"), `exclude_ids`. Returns compact records with a cosine `similarity` (0–1).
    """
    body = {"query": query, "paper_ids": seed_ids, "days": days, "min_score": min_score, "status": status,
            "category": category, "exclude_ids": exclude_ids, "limit": limit, "compact": True}
    return _post("/api/papers/semantic-search", {k: v for k, v in body.items() if v is not None})


@mcp.tool()
def search_titles(q: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Substring search on paper titles (exact words). Prefer search_papers for topic questions."""
    return _get("/api/papers/search", q=q, limit=limit, compact=True)


@mcp.tool()
def recent_papers(
    days: int = 7,
    min_score: Optional[int] = 85,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Papers published within the last `days`, newest first, compact records. Default `min_score=85` gives the
    papers that made the user's digest; pass `min_score=None` (null) for everything fetched. `status` is a
    comma-separated list (NEW, SCORED, FILTERED, SUMMARIZED, PUSHED).
    """
    return _get("/api/papers/recent", days=days, min_score=min_score, status=status, category=category, limit=limit, compact=True)


@mcp.tool()
def related_papers(paper_id: str, k: int = 8) -> Dict[str, Any]:
    """Nearest neighbours of a paper by embedding (compact records with `similarity`). `available=false` if it has no vector yet."""
    return _get(f"/api/papers/{paper_id}/related", k=k)


@mcp.tool()
def get_paper(paper_id: str, include_text: bool = False, max_text_chars: int = 20000) -> Dict[str, Any]:
    """
    Full record of one paper: metadata, final/stage scores and the two-stage scoring rationale (`score_reason`,
    JSON string), the personalised markdown summary (`summary_personalized`), affiliations. With
    `include_text=true` also the extracted PDF text (`full_text`, truncated to `max_text_chars`).
    """
    d = _get(f"/api/papers/{paper_id}")
    text = d.pop("full_text", None)
    if include_text and text:
        d["full_text"] = text[:max_text_chars]
        d["full_text_truncated"] = len(text) > max_text_chars
        d["full_text_total_chars"] = len(text)
    else:
        d["has_full_text"] = bool(text)
    d["abs_url"] = f"https://arxiv.org/abs/{paper_id}"
    return d


@mcp.tool()
def get_papers(paper_ids: List[str]) -> List[Dict[str, Any]]:
    """Compact records for a list of arXiv ids (order preserved, unknown ids skipped)."""
    if not paper_ids:
        return []
    return _get("/api/papers", ids=",".join(paper_ids), compact=True)


# ---------------------------------------------------------------------------
# Tools — people of interest
# ---------------------------------------------------------------------------
@mcp.tool()
def papers_by_people(
    names: List[str],
    days: Optional[int] = 30,
    min_score: Optional[int] = None,
    limit_per_author: int = 20,
) -> Dict[str, Any]:
    """
    Papers by people of interest. Names are matched fuzzily against every author string seen on any paper
    (case/accents/punctuation folded, "Last, First", swapped token order, then first-initial+last name — the last
    may be ambiguous: check `ambiguous` and `matches`). Per name: `match_type`, `matches` (stored variants with
    paper counts and is_important), and their compact papers within `days` (null = all time), optional `min_score`.
    """
    return _post("/api/authors/lookup", {"names": names, "days": days, "min_score": min_score,
                                         "limit_per_author": limit_per_author, "mark_important": False})


@mcp.tool()
def mark_people_important(names: List[str], important: bool = True) -> Dict[str, Any]:
    """
    Flag (or unflag) people as important: their future papers get a score boost (to at least 90) and surface in
    the digest. Names are resolved fuzzily; ambiguous initials-only matches are NOT flagged — pass the exact
    stored variant (see papers_by_people `matches`) for those. Returns what was flagged.
    """
    if important:
        res = _post("/api/authors/lookup", {"names": names, "days": 1, "limit_per_author": 0, "mark_important": True})
        return {"flagged": [{"query": r["query"], "matches": [m["name"] for m in r["matches"]], "ambiguous": r["ambiguous"],
                             "match_type": r["match_type"]} for r in res["results"]]}
    res = _post("/api/authors/lookup", {"names": names, "days": 1, "limit_per_author": 0})
    exact = [m["name"] for r in res["results"] if not r["ambiguous"] for m in r["matches"]]
    out = _post("/api/authors/bulk", {"authors": [{"name": n, "is_important": False} for n in exact]}) if exact else {"updated": []}
    return {"unflagged": out.get("updated", [])}


# ---------------------------------------------------------------------------
# Tools — reports
# ---------------------------------------------------------------------------
@mcp.tool()
def list_reports(kind: Optional[str] = None, limit: int = 10, with_content: bool = False) -> List[Dict[str, Any]]:
    """
    Trend reports, newest first. `kind`: daily | weekly | monthly | null. Without `with_content` each item has
    title, period, paper_count, model, pushed and a 300-char preview — use get_report(id) for the full markdown.
    """
    items = _get("/api/reports", kind=kind, limit=limit)
    out = []
    for r in items:
        d = {k: r.get(k) for k in ("id", "kind", "period_label", "title", "paper_count", "model", "pushed", "created_at")}
        if with_content:
            d["content"] = r.get("content")
        else:
            c = (r.get("content") or "")
            d["preview"] = c[:300] + ("…" if len(c) > 300 else "")
        out.append(d)
    return out


@mcp.tool()
def get_report(report_id: int) -> Dict[str, Any]:
    """One trend report: markdown `content`, computed `stats` (JSON string: counts, institutions with deltas, clusters…), covered `paper_ids`."""
    return _get(f"/api/reports/{report_id}")


# ---------------------------------------------------------------------------
# Tools — feedback / write-back
# ---------------------------------------------------------------------------
@mcp.tool()
def set_user_score(paper_id: str, score: int) -> Dict[str, Any]:
    """
    Record the user's own judgement of a paper (0–100). Overrides the AI score, disables future re-scoring,
    and feeds later preference features. Use e.g. 95–100 for "read and excellent", 90 for "worth reading",
    40–60 for "not for me". Returns the updated paper (compact).
    """
    d = _patch(f"/api/papers/{paper_id}/score", score=score)
    return {k: d.get(k) for k in ("id", "title", "score", "user_score", "status")}


@mcp.tool()
def add_paper(arxiv_id_or_url: str) -> Dict[str, Any]:
    """
    Add a paper by arXiv id or URL. It is fetched from arXiv, then scored (two-stage) and summarised in the
    background; poll get_paper a minute later. If it already exists, re-processing is triggered only when needed.
    """
    return _post("/api/papers/add", {"input": arxiv_id_or_url})


@mcp.tool()
def agent_status() -> Dict[str, Any]:
    """Health of the Paper Agent instance: models/thresholds in use, embedding coverage, base URL."""
    llm = _get("/api/settings/llm")
    emb = _get("/api/embeddings/status")
    return {
        "base_url": _base_url,
        "models": llm.get("models"), "thresholds": llm.get("thresholds"), "provider": llm.get("provider"),
        "embeddings": {k: emb.get(k) for k in ("model", "dim", "total_papers", "embedded", "missing", "index_size")},
    }


# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> None:
    global _base_url, _timeout
    ap = argparse.ArgumentParser(description="Paper Agent MCP server (stdio)")
    ap.add_argument("--base-url", default=DEFAULT_URL, help="Paper Agent base URL (default: $PAPER_AGENT_URL or http://nas:8000)")
    ap.add_argument("--timeout", type=float, default=_timeout, help="HTTP timeout in seconds")
    args = ap.parse_args(argv)
    _base_url = args.base_url.rstrip("/")
    _timeout = args.timeout
    print(f"paper-agent-mcp: serving tools for {_base_url}", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
