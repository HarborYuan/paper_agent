"""
Paper Agent MCP server (stdio).

Thin, explicit tools over the Paper Agent HTTP API so an LLM agent (Claude Code, etc.) can:
search papers semantically or by title, pull recent high-scoring papers, follow people of interest,
read a paper's verdict / TL;DR / full text and bilingual deep read, manage projects, and write feedback back (user scores,
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
        "their research profile: a screen, a review and, for the papers worth reading, a full deep read with a "
        "bilingual reading page; it also collects papers into the user's projects). "
        "Use search_papers for topic questions (semantic, any language; optionally seed with paper ids), "
        "recent_papers for 'what came out lately', papers_by_people for people of interest, get_paper to read "
        "one paper in depth (verdict, TL;DR, optional full text), related_papers for neighbours, "
        "deep_read_paper / get_deep_read for the paragraph-by-paragraph reading with flagged claims, "
        "list_projects / get_project / create_project / add_papers_to_project for projects. set_user_score and mark_people_important write the user's "
        "feedback back so future scoring improves. BibTeX: get_bibtex returns citation entries for any arXiv id; "
        "the server never looks up venues itself — for entries in `needs_check` YOU verify whether the paper was "
        "accepted (bibtex_venue_hints, then web sources if needed) and write the verdict back with set_bibtex_status, "
        "so it never has to be checked again; fix_bibtex syncs a whole .bib file with the library. "
        "Paper ids are arXiv ids like 2608.19556."
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


def _put(path: str, body: Optional[Dict[str, Any]] = None) -> Any:
    with _client() as c:
        r = c.put(path, json=body)
        _raise_for(r)
        return r.json()


def _delete(path: str) -> Any:
    with _client() as c:
        r = c.delete(path)
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
    Full record of one paper: metadata, final score, the pipeline rationale (`score_reason`, JSON string with
    `stage1` = screen relevance, `stage2` = review verdict and dimensions, `deep` = final verdict after the full
    read), the TL;DR (`summary_personalized`), affiliations. With `include_text=true` also the extracted PDF text
    (`full_text`, truncated to `max_text_chars`). The bilingual reading page is at /read/<id> (see get_deep_read).
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
def deep_read_paper(paper_id: str, force: bool = False) -> Dict[str, Any]:
    """
    Start a deep read of one paper (Claude, real time, ~1-2 minutes, ~$0.1-0.2): reviews it if needed, then
    writes the final verdict (must_read / worth_reading / skim / skip), the structured summary, a
    paragraph-by-paragraph Chinese gist with questionable / big claims flagged, and a full Chinese translation.
    Returns the status and `read_url` (the bilingual reading page). Already done -> returns DONE unless force=true.
    Check progress with get_deep_read.
    """
    d = _post(f"/api/papers/{paper_id}/deep-read", force=force)
    d["read_url"] = _base_url + d.get("read_url", f"/read/{paper_id}")
    return d


@mcp.tool()
def get_deep_read(paper_id: str, include_notes: bool = False) -> Dict[str, Any]:
    """
    Deep-read status of a paper (NONE / PENDING / RUNNING / DONE / ERROR), the final verdict with its
    dimensions, and the verified claim flags (questionable / big_claim with the quoted span and why).
    With include_notes=true also the per-paragraph Chinese gist notes (no translations — open read_url for those).
    """
    d = _get(f"/api/papers/{paper_id}/reading", full=include_notes)
    if include_notes:
        d.pop("units", None)
        d.pop("translations", None)
        d["flags"] = [f for n in d.get("notes", []) for f in n.get("flags", []) if f.get("verified")]
    d["read_url"] = _base_url + d.get("read_url", f"/read/{paper_id}")
    return d


# ---------------------------------------------------------------------------
# Tools — projects
# ---------------------------------------------------------------------------
@mcp.tool()
def list_projects() -> List[Dict[str, Any]]:
    """The user's research projects (id, name, description, keywords, active, n_papers). Each project collects papers;
    new papers are recalled for active projects every night and confirmed by the reviewer."""
    return _get("/api/projects")


@mcp.tool()
def get_project(project: str, limit: int = 50) -> Dict[str, Any]:
    """One project (by name or id) with its papers, newest first. Each paper has project_source
    (seed / manual / auto = recalled and confirmed by the reviewer) and project_reason."""
    return _get(f"/api/projects/{project}", limit=limit)


@mcp.tool()
def create_project(name: str, description: str, keywords: Optional[List[str]] = None,
                   seed_paper_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Create a project. The description (what the project does, its method and what kind of paper it needs) and the
    seed papers (arXiv ids already in the library; add missing ones with add_paper first) drive recall, so write the
    description concretely. Returns the project.
    """
    return _post("/api/projects", {"name": name, "description": description, "keywords": keywords or [],
                                   "seed_paper_ids": seed_paper_ids or []})


@mcp.tool()
def update_project(project: str, name: Optional[str] = None, description: Optional[str] = None,
                   keywords: Optional[List[str]] = None, active: Optional[bool] = None) -> Dict[str, Any]:
    """Edit a project (by name or id). active=false stops nightly recall for it but keeps its papers."""
    body = {"name": name, "description": description, "keywords": keywords, "active": active}
    return _patch(f"/api/projects/{project}", {k: v for k, v in body.items() if v is not None})


@mcp.tool()
def add_papers_to_project(project: str, paper_ids: List[str], as_seed: bool = False) -> Dict[str, Any]:
    """Add papers to a project (manual, or as seeds that anchor recall). Reports ids not in the library."""
    return _post(f"/api/projects/{project}/papers", {"paper_ids": paper_ids, "source": "seed" if as_seed else "manual"})


@mcp.tool()
def remove_papers_from_project(project: str, paper_ids: List[str]) -> Dict[str, Any]:
    """Remove papers from a project."""
    removed = []
    for pid in paper_ids:
        removed += _delete(f"/api/projects/{project}/papers/{pid}").get("removed", [])
    return {"removed": removed}


@mcp.tool()
def project_suggestions(project: str, k: int = 20) -> List[Dict[str, Any]]:
    """Library papers most similar to a project (seed papers + description) that are not in it yet — for backfilling."""
    return _get(f"/api/projects/{project}/suggestions", k=k)


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
    Add a paper by arXiv id or URL. It is fetched from arXiv, then screened, reviewed and (if worth reading)
    deep-read in the background; poll get_paper a minute or two later. If it already exists, re-processing is
    triggered only when needed.
    """
    return _post("/api/papers/add", {"input": arxiv_id_or_url})


@mcp.tool()
def agent_status() -> Dict[str, Any]:
    """Health of the Paper Agent instance: Claude models and gates in use, Claude budget, embedding coverage, base URL."""
    llm = _get("/api/settings/llm")
    emb = _get("/api/embeddings/status")
    return {
        "base_url": _base_url,
        "models": llm.get("models"), "gates": llm.get("gates"), "provider": llm.get("provider"),
        "warnings": llm.get("warnings"), "claude_budget": _get("/api/claude/budget"),
        "embeddings": {k: emb.get(k) for k in ("model", "dim", "total_papers", "embedded", "missing", "index_size")},
    }


# ---------------------------------------------------------------------------
# Tools — BibTeX (agent-driven: the server stores verdicts, the agent checks venues)
# ---------------------------------------------------------------------------
_BIB_WORKFLOW = """
Workflow when citing: get_bibtex(ids) -> for each id in `needs_check` (never checked, or "still a preprint"
checked > 30 days ago) call bibtex_venue_hints; if the arXiv comment / journal_ref is not conclusive, check
DBLP / OpenReview / the proceedings / Semantic Scholar yourself -> set_bibtex_status(...) -> get_bibtex again.
Published entries are final and never need checking again.
Naming — the venue is stored and printed exactly as you write it, so follow this strictly:
- Conferences: ALWAYS the bare abbreviation — CVPR, ICCV, ECCV, NeurIPS, ICLR, ICML, ACL, EMNLP, NAACL, AAAI,
  IJCAI, WACV, BMVC, ACM MM, SIGGRAPH, KDD, ... NEVER the long form: not "Proceedings of the IEEE/CVF Conference
  on Computer Vision and Pattern Recognition", not "IEEE/CVF CVPR", not "Proc. CVPR", not "CVPR 2026" (the year
  goes in `year`, never in `venue`). Workshops: "CVPR Workshops"; findings: "Findings of EMNLP".
- NIPS vs NeurIPS: the conference was renamed in 2018. year <= 2017 -> "NIPS"; year >= 2018 -> "NeurIPS".
  Never "Advances in Neural Information Processing Systems", never "NeurIPS" for a 2017-or-earlier paper.
- Journals: well-known ones by short name (IEEE TPAMI, IJCV, IEEE TIP, IEEE TMM, IEEE TCSVT, IEEE TNNLS,
  IEEE TVCG, IEEE RA-L, ACM TOG, JMLR, TMLR, TACL); any other journal by its full name.
- Year = year of the venue (ICLR 2025), not of the arXiv upload.
Fields — an entry has exactly four: title, author, booktitle | journal, year. NEVER add pages, volume, number,
month, publisher, organization, address, editor, series, doi, url, eprint or note — not in an entry you write by
hand (e.g. for `no_arxiv_id` items), and not squeezed into `venue`. Do not copy publisher BibTeX (IEEE Xplore,
ACM DL, DBLP, Google Scholar) verbatim: take only the venue and year from it.
"""


def _bib_entries_brief(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keep = ("paper_id", "cite_key", "title", "status", "needs_check", "venue_type", "venue", "year", "checked_at",
            "authors_source")
    return [{k: e.get(k) for k in keep} for e in entries]


@mcp.tool()
def get_bibtex(paper_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    BibTeX for arXiv papers (ids or URLs) — any arXiv paper, not only scored ones; new ones are added to the
    library as unchecked preprints. Omit `paper_ids` for the whole library. Entries render as
    @inproceedings{booktitle} (conference), @article{journal} (journal) or @article{journal = {arXiv preprint ...}}.
    Returns `bibtex` (ready to paste), per-entry status, `needs_check` (ids whose venue you should verify),
    `missing` ids and `warnings`.
    """
    d = _get("/api/bibtex", ids=",".join(paper_ids) if paper_ids else None)
    d["entries"] = _bib_entries_brief(d.get("entries", []))
    return d


@mcp.tool()
def bibtex_venue_hints(paper_ids: List[str]) -> Dict[str, Any]:
    """
    Read-only venue evidence from the *current* arXiv record: the authors' comment (e.g. "Accepted to CVPR 2026",
    usually added with the camera-ready version), journal_ref, DOI and latest version date, raw — interpret them
    yourself ("submitted to" / "under review" is not an acceptance) and confirm before writing back. Nothing is stored.
    """
    return _get("/api/bibtex/hints", ids=",".join(paper_ids))


_SET_STATUS_DOC = """
    Write your venue verdict for one paper back to the library (creates the entry if needed).
    status="published": venue, venue_type ("conference" | "journal") and year required —
      final, never flagged again. status="preprint": you checked and it is not published yet (re-flagged after
      30 days). status="unchecked": reset. `evidence`: URL or short note on where you confirmed it.
    `authors` (published only): the author list of the OFFICIAL version, in order, as full names
      ("Kaiming He", not "He, K."). The arXiv list can differ from it (authors added, names or order changed);
      once you write it, the official list wins everywhere — get_bibtex entries and fix_bibtex rewrites. Pass
      it whenever a reliable official source gives the complete list (proceedings / publisher page, OpenReview
      camera-ready, the publisher's or DBLP's BibTeX); never from memory, never a truncated "et al." list. If
      you have no such source, omit it: the arXiv list (or the author text already in the .bib) is used.
    """ + _BIB_WORKFLOW


@mcp.tool(description=_SET_STATUS_DOC)
def set_bibtex_status(
    paper_id: str,
    status: str = "published",
    venue: Optional[str] = None,
    venue_type: Optional[str] = None,
    year: Optional[int] = None,
    evidence: Optional[str] = None,
    authors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return _put(f"/api/bibtex/{paper_id}/status", {"status": status, "venue": venue, "venue_type": venue_type,
                                                    "year": year, "evidence": evidence, "authors": authors})


@mcp.tool()
def fix_bibtex(bibtex: str) -> Dict[str, Any]:
    """
    Sync a whole .bib file (pass its text) with the library and cut every paper entry down to four fields
    (title, author, booktitle | journal, year), no lookups. arXiv-preprint entries whose paper is known as
    published get their venue (conferences become @inproceedings/booktitle); the other arXiv entries become
    `journal = {arXiv preprint arXiv:<id>}`; published @inproceedings / @article entries lose pages, volume,
    publisher, doi, url, ... but keep their venue text as written — rename a long venue (see the naming rules
    of set_bibtex_status) yourself in the returned text. Cite key and title are always kept; the author text is
    kept too, except that an entry getting its published venue takes the official author list when the library
    has one (written with set_bibtex_status `authors`);
    other kinds of entry (@book, @misc for a website, @string) are left untouched. Returns the new `bibtex`,
    `changes` (preprint -> venue), `cleaned` (entries that lost fields), `needs_check` (verify these,
    set_bibtex_status each, then call fix_bibtex again) and `no_arxiv_id` (preprint entries without an arXiv
    id — handle by hand, four fields only).
    """
    return _post("/api/bibtex/fix", {"bibtex": bibtex})


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
