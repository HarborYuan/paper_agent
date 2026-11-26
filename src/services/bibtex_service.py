"""
BibTeX library — a store driven by the agent (MCP), no automatic venue lookup.

Entries come from the arXiv API (title / authors). Freshly fetched arXiv papers are normally not
accepted anywhere yet, so the server never guesses: while writing a paper the agent asks for
entries (`get_entries`), checks the ones flagged `needs_check` itself (arXiv comments via `hints`,
Semantic Scholar, DBLP, OpenReview, proceedings pages, ...), and writes the result back
(`set_status`). A published entry is final — it is never flagged again. A "still a preprint"
verdict is trusted for RECHECK_DAYS, then flagged for another look.

Four fields per entry, typed by where it appeared:

    preprint    @article{key, title, author, journal = {arXiv preprint arXiv:2608.19556}, year}
    conference  @inproceedings{key, title, author, booktitle = {CVPR}, year}
    journal     @article{key, title, author, journal = {IEEE TPAMI}, year}

Authors: an entry starts with the arXiv author list. The official version can differ (authors added,
names changed, order changed), so with a published verdict the agent may also write the author list of
the official version; once it is there, it wins — in rendered entries and when `fix_bibtex` rewrites a
pasted entry. Without it the arXiv list (library) / the pasted author text (fix_bibtex) is used.

The venue name and type are stored exactly as the agent writes them — the naming convention
(conference short names, well-known journal short names, otherwise full names) lives in the MCP
tool descriptions. Cite keys never change once assigned, so LaTeX sources keep compiling when an
entry gets its venue.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from sqlmodel import Session, select

from src.models import BibEntry, Paper
from src.services.arxiv import ArxivAPIError, fetch_metadata

RECHECK_DAYS = 30
STATUSES = ("unchecked", "preprint", "published")
VENUE_TYPES = ("conference", "journal")

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
_STOPWORDS = {"a", "an", "the", "on", "of", "in", "for", "to", "towards", "toward", "is", "are", "do", "does",
              "can", "why", "what", "how", "when", "and", "with", "via", "from", "by", "at", "we", "your", "you"}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def arxiv_year(paper_id: str, fallback: Optional[datetime] = None) -> int:
    m = re.match(r"(?:[a-z\-\.]+/)?(\d{2})(\d{2})", paper_id, re.I)
    if m:
        yy = int(m.group(1))
        return (1900 if yy >= 91 else 2000) + yy
    return (fallback or datetime.now()).year


def base_cite_key(authors: List[str], year: int, title: str) -> str:
    title = re.sub(r"\\[a-zA-Z]+", " ", title or "")   # \texttt{Complex-Edit} -> Complex-Edit
    last = ""
    if authors:
        tokens = [t for t in re.split(r"\s+", _ascii(authors[0]).strip()) if t]
        if tokens:
            last = re.sub(r"[^a-z]", "", tokens[-1].lower())
    words = [re.sub(r"[^a-z0-9]", "", w) for w in re.split(r"[\s\-:]+", _ascii(title).lower())]
    word = next((w for w in words if w and w not in _STOPWORDS), "")
    return f"{last or 'anon'}{year}{word}"


def _unique_key(session: Session, base: str, paper_id: str) -> str:
    taken = set(session.exec(select(BibEntry.cite_key).where(BibEntry.cite_key.startswith(base),
                                                             BibEntry.paper_id != paper_id)).all())
    if base not in taken:
        return base
    for suffix in "bcdefghijklmnopqrstuvwxyz":
        if base + suffix not in taken:
            return base + suffix
    return f"{base}{paper_id.replace('.', '')}"


# Symbols arXiv titles carry as Unicode that pdflatex cannot typeset (accented letters are fine under utf8)
_SYMBOLS = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "ζ": "zeta", "η": "eta",
    "θ": "theta", "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "π": "pi",
    "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta", "Λ": "Lambda", "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma",
    "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega", "∞": "infty", "×": "times", "±": "pm", "≤": "leq", "≥": "geq",
    "≠": "neq", "≈": "approx", "→": "rightarrow", "←": "leftarrow", "↔": "leftrightarrow",
    "⇒": "Rightarrow", "∈": "in", "∑": "sum", "∏": "prod", "∂": "partial", "∇": "nabla", "·": "cdot",
    "ℓ": "ell", "⊕": "oplus", "⊗": "otimes", "∼": "sim", "∗": "ast",
}


def latex_symbols(text: str) -> str:
    """α -> {\\alpha} inside $...$ math, $\\alpha$ outside it."""
    parts = re.split(r"(?<!\\)\$", text)
    for i, part in enumerate(parts):
        math = i % 2 == 1 and i < len(parts) - 1      # an unpaired trailing $ opens no math
        parts[i] = "".join(("{\\%s}" if math else "$\\%s$") % _SYMBOLS[c] if c in _SYMBOLS else c for c in part)
    return "$".join(parts)


def escape_latex(text: str) -> str:
    text = " ".join((text or "").split())
    return latex_symbols(re.sub(r"(?<!\\)([&%#])", r"\\\1", text))


def format_raw(kind: str, field: str, key: str, title: str, author: str, venue: str, year: str) -> str:
    """The four-field layout; values are written as given, delimiters included (`{...}`, `"..."`, a macro)."""
    return (f"@{kind}{{{key},\n"
            f"  title{' ' * (len(field) - 5)} = {title},\n"
            f"  author{' ' * (len(field) - 6)} = {author},\n"
            f"  {field} = {venue},\n"
            f"  year{' ' * (len(field) - 4)} = {year}\n"
            f"}}")


def format_entry(key: str, title: str, author: str, venue_type: Optional[str], venue: str, year) -> str:
    """conference -> @inproceedings + booktitle; journal / preprint -> @article + journal."""
    kind, field = ("inproceedings", "booktitle") if venue_type == "conference" else ("article", "journal")
    return format_raw(kind, field, key, f"{{{title}}}", f"{{{author}}}", f"{{{venue}}}", f"{{{year}}}")


def is_published(entry: BibEntry) -> bool:
    return entry.status == "published" and bool(entry.venue)


def venue_of(entry: BibEntry) -> str:
    return entry.venue if is_published(entry) else f"arXiv preprint arXiv:{entry.paper_id}"


def year_of(entry: BibEntry) -> int:
    return entry.venue_year if is_published(entry) and entry.venue_year else entry.arxiv_year


def authors_of(entry: BibEntry) -> List[str]:
    """The official version's author list once the agent has written it for a published entry, else arXiv's."""
    if is_published(entry) and entry.published_authors:
        return json.loads(entry.published_authors)
    return json.loads(entry.authors or "[]")


def needs_check(entry: BibEntry, now: Optional[datetime] = None) -> bool:
    """unchecked, or 'still a preprint' older than RECHECK_DAYS. Published entries are final."""
    if entry.status == "published":
        return False
    if entry.status == "preprint" and entry.checked_at:
        return entry.checked_at < (now or datetime.now()) - timedelta(days=RECHECK_DAYS)
    return True


def render(entry: BibEntry) -> str:
    authors = authors_of(entry)
    # Double braces keep the title's capitalisation (SAM, OMG-Seg, 3D) under styles that lowercase titles
    return format_entry(entry.cite_key, f"{{{escape_latex(entry.title)}}}", " and ".join(escape_latex(a) for a in authors),
                        entry.venue_type if is_published(entry) else None, escape_latex(venue_of(entry)), year_of(entry))


def entry_dict(entry: BibEntry) -> Dict:
    return {
        "paper_id": entry.paper_id, "cite_key": entry.cite_key, "title": entry.title,
        "status": entry.status, "needs_check": needs_check(entry),
        "venue_type": entry.venue_type if is_published(entry) else "preprint",
        "venue": venue_of(entry), "year": year_of(entry), "evidence": entry.evidence,
        "authors": authors_of(entry),
        "authors_source": "published" if is_published(entry) and entry.published_authors else "arxiv",
        "checked_at": entry.checked_at.isoformat() if entry.checked_at else None,
        "bibtex": render(entry),
    }


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------
def normalize_id(pid: str) -> str:
    pid = pid.strip()
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([^\s?#]+)", pid)
    if m:
        pid = m.group(1)
    pid = re.sub(r"^arxiv:", "", pid, flags=re.I)
    pid = re.sub(r"\.pdf$", "", pid)
    return re.sub(r"v\d+$", "", pid)


def get_entries(session: Session, paper_ids: Iterable[str]) -> Dict:
    """
    Entries for the given arXiv ids, creating missing ones as `unchecked` preprints. Metadata comes
    from the arXiv API, falling back to the local paper table when the API is down. No venue lookup.
    Returns {"entries": [BibEntry], "missing": [ids], "warnings": [str]}.
    """
    ids = list(dict.fromkeys(normalize_id(i) for i in paper_ids if i and i.strip()))
    existing = {e.paper_id: e for e in session.exec(select(BibEntry).where(BibEntry.paper_id.in_(ids))).all()} if ids else {}
    new_ids = [i for i in ids if i not in existing]
    warnings: List[str] = []
    missing: List[str] = []
    if new_ids:
        try:
            meta = fetch_metadata(new_ids)
        except ArxivAPIError as e:
            meta = {}
            warnings.append(f"arXiv API unavailable, used local metadata where possible: {e}")
        local = {p.id: p for p in session.exec(select(Paper).where(Paper.id.in_(new_ids))).all()}
        for pid in new_ids:
            m, p = meta.get(pid), local.get(pid)
            if not m and not p:
                missing.append(pid)
                continue
            title = m["title"] if m else " ".join(p.title.split())
            authors = m["authors"] if m else p.authors_list
            year = arxiv_year(pid, (m or {}).get("published") or (p.published_at if p else None))
            entry = BibEntry(paper_id=pid, title=title, authors=json.dumps(authors, ensure_ascii=False),
                             arxiv_year=year, cite_key=_unique_key(session, base_cite_key(authors, year, title), pid))
            session.add(entry)
            session.flush()   # so the next _unique_key sees this key
            existing[pid] = entry
        session.commit()
    return {"entries": [existing[i] for i in ids if i in existing], "missing": missing, "warnings": warnings}


def list_entries(session: Session) -> List[BibEntry]:
    return list(session.exec(select(BibEntry).order_by(BibEntry.cite_key)).all())


def export(entries: List[BibEntry]) -> str:
    return "\n\n".join(render(e) for e in entries) + ("\n" if entries else "")


def hints(session: Session, paper_ids: Iterable[str]) -> List[Dict]:
    """
    Read-only evidence for the agent: the *current* arXiv comment / journal_ref / DOI (authors usually
    add "Accepted to CVPR 2026" with the camera-ready version), returned raw — the agent interprets
    them. Writes nothing but the title / authors refresh. Raises ArxivAPIError.
    """
    ids = list(dict.fromkeys(normalize_id(i) for i in paper_ids if i and i.strip()))
    meta = fetch_metadata(ids)
    out = []
    for pid in ids:
        m = meta.get(pid)
        if not m:
            out.append({"paper_id": pid, "found": False})
            continue
        entry = session.get(BibEntry, pid)
        if entry and m["title"]:
            entry.title = m["title"]
            if m["authors"]:
                entry.authors = json.dumps(m["authors"], ensure_ascii=False)
            session.add(entry)
        out.append({
            "paper_id": pid, "found": True, "title": m["title"],
            "comment": m["comment"], "journal_ref": m["journal_ref"], "doi": m["doi"],
            "latest_version": m["updated"].date().isoformat() if m["updated"] else None,
        })
    session.commit()
    return out


class BibUpdateError(ValueError):
    pass


def set_status(session: Session, paper_id: str, status: str, venue: Optional[str] = None,
               venue_type: Optional[str] = None, year: Optional[int] = None,
               evidence: Optional[str] = None, authors: Optional[List[str]] = None) -> BibEntry:
    """
    Write the agent's verdict back.
      published  — needs venue, venue_type (conference | journal) and year; stored as given. Final.
                   `authors`: the official version's author list, in order — from then on it replaces
                   the arXiv list. Omitted: an earlier official list is kept, else arXiv's is used.
      preprint   — checked, not published yet; trusted for RECHECK_DAYS.
      unchecked  — reset.
    Creates the entry if it is not in the library yet. Raises BibUpdateError / LookupError.
    """
    if status not in STATUSES:
        raise BibUpdateError(f"status must be one of {STATUSES}")
    pid = normalize_id(paper_id)
    entry = session.get(BibEntry, pid)
    if not entry:
        res = get_entries(session, [pid])
        if not res["entries"]:
            raise LookupError(f"arXiv paper {pid} not found")
        entry = res["entries"][0]
    now = datetime.now()
    if status == "published":
        if not venue or not venue.strip() or not year:
            raise BibUpdateError("published needs venue and year")
        if venue_type not in VENUE_TYPES:
            raise BibUpdateError(f"published needs venue_type: one of {VENUE_TYPES}")
        if authors is not None:
            names = [" ".join(a.split()) for a in authors if isinstance(a, str)]
            if not names or len(names) != len(authors) or not all(names):
                raise BibUpdateError("authors must be a non-empty list of names, in the order of the official version")
            entry.published_authors = json.dumps(names, ensure_ascii=False)
        entry.venue, entry.venue_type, entry.venue_year = " ".join(venue.split()), venue_type, int(year)
        entry.checked_at = now
    else:
        entry.venue = entry.venue_type = entry.venue_year = entry.published_authors = None
        entry.checked_at = now if status == "preprint" else None
    entry.status = status
    entry.evidence = evidence if status != "unchecked" else None
    entry.updated_at = now
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def delete_entry(session: Session, paper_id: str) -> bool:
    entry = session.get(BibEntry, normalize_id(paper_id))
    if not entry:
        return False
    session.delete(entry)
    session.commit()
    return True


# ---------------------------------------------------------------------------
# Syncing an arbitrary .bib with the library
# ---------------------------------------------------------------------------
@dataclass
class ParsedEntry:
    start: int
    end: int
    type: str
    key: str
    fields: Dict[str, str]   # lower-cased name -> value without the outer {} / ""
    raw: Dict[str, str] = field(default_factory=dict)   # lower-cased name -> value exactly as written


def _match_close(text: str, i: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parse_fields(body: str, raw: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        m = re.compile(r"[\s,]*([A-Za-z][\w\-:.]*)\s*=\s*").match(body, i)
        if not m:
            break
        name, i = m.group(1).lower(), m.end()
        value_start = i
        parts = []
        while i < n:
            if body[i] == "{":
                j = _match_close(body, i, "{", "}")
                if j < 0:
                    j = n - 1
                parts.append(body[i + 1:j])
                i = j + 1
            elif body[i] == '"':
                j, depth = i + 1, 0
                while j < n and not (body[j] == '"' and depth == 0 and body[j - 1] != "\\"):
                    depth += {"{": 1, "}": -1}.get(body[j], 0)
                    j += 1
                parts.append(body[i + 1:j])
                i = j + 1
            else:
                m2 = re.compile(r"[^,#}\s]+").match(body, i)
                parts.append(m2.group(0) if m2 else "")
                i = m2.end() if m2 else i + 1
            m3 = re.compile(r"\s*#\s*").match(body, i)
            if m3:
                i = m3.end()
                continue
            break
        fields[name] = "".join(parts).strip()
        if raw is not None:
            raw[name] = body[value_start:i].strip()
    return fields


def parse_bibtex(text: str) -> List[ParsedEntry]:
    out = []
    for m in re.finditer(r"@\s*(\w+)\s*([{(])", text):
        if out and m.start() < out[-1].end:
            continue
        typ = m.group(1).lower()
        open_ch = m.group(2)
        close = _match_close(text, m.end() - 1, open_ch, "}" if open_ch == "{" else ")")
        if close < 0:
            continue
        if typ in ("comment", "string", "preamble"):
            continue
        body = text[m.end():close]
        key, _, rest = body.partition(",")
        raw: Dict[str, str] = {}
        out.append(ParsedEntry(m.start(), close + 1, typ, key.strip(), _parse_fields(rest, raw), raw))
    return out


_ARXIV_ID = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(?:v\d+)?(?![\d])")


def arxiv_id_of(e: ParsedEntry) -> Optional[str]:
    if e.fields.get("eprint") and _ARXIV_ID.fullmatch(e.fields["eprint"].strip()):
        return _ARXIV_ID.fullmatch(e.fields["eprint"].strip()).group(1)
    blob = " ".join(e.fields.get(k, "") for k in ("journal", "booktitle", "volume", "url", "doi", "note",
                                                   "howpublished", "eprint", "archiveprefix", "publisher"))
    if not re.search(r"(?i)arxiv|corr", blob):
        return None
    m = _ARXIV_ID.search(blob)
    return m.group(1) if m else None


def is_preprint(e: ParsedEntry) -> bool:
    if e.type in ("book", "inbook", "phdthesis", "mastersthesis", "techreport", "manual"):
        return False
    where = e.fields.get("journal") or e.fields.get("booktitle") or ""
    if where.strip():
        return bool(re.search(r"(?i)arxiv|\bcorr\b|preprint", where))
    # no venue at all: an arXiv paper, or something else entirely (a website, software, a dataset)
    return e.type in PAPER_TYPES or arxiv_id_of(e) is not None




PAPER_TYPES = ("inproceedings", "conference", "article")
FOUR = ("title", "author", "year")   # + booktitle | journal


def _clean_published(e: ParsedEntry) -> Optional[tuple]:
    """
    An already-published conference / journal entry cut down to four fields -> (text, dropped fields),
    or None when there is nothing to cut. Values are copied as written (braces, quotes, @string macros) — the venue name is
    the agent's business, the server only drops pages / volume / publisher / doi / url / ...
    """
    if e.type not in PAPER_TYPES or not all(e.fields.get(k) for k in ("title", "year")):
        return None
    name = "journal" if e.fields.get("journal") and (e.type == "article" or not e.fields.get("booktitle")) else "booktitle"
    if not e.fields.get(name):
        return None
    kind = "article" if name == "journal" else "inproceedings"
    retyped = kind != e.type and not (e.type == "conference" and kind == "inproceedings")
    if not retyped and not _extra_fields(e, name):
        return None
    return (format_raw(kind, name, e.key, e.raw["title"], e.raw.get("author", "{}"), e.raw[name], e.raw["year"]),
            _extra_fields(e, name))


def _extra_fields(e: ParsedEntry, venue_field: str) -> List[str]:
    return sorted(k for k in e.fields if k not in FOUR and k != venue_field)


def _clean_preprint(e: ParsedEntry, pid: str, year: int) -> Optional[str]:
    """A not-(yet-)published arXiv entry in the four-field preprint form; the id moves into `journal`."""
    if e.type == "article" and not _extra_fields(e, "journal") and pid in e.fields.get("journal", ""):
        return None
    return format_raw("article", "journal", e.key, e.raw["title"], e.raw.get("author", "{}"),
                      f"{{arXiv preprint arXiv:{pid}}}", e.raw.get("year") or f"{{{year}}}")


def fix_bibtex(session: Session, text: str) -> Dict:
    """
    Sync a pasted .bib with the library and cut every paper entry down to four fields (title, author,
    booktitle | journal, year) — no lookups.
      * arXiv-preprint entries the library knows as published get their venue (@inproceedings/booktitle
        for conferences) -> `changes`; when the library has the official version's author list, the
        author field is replaced by it (`authors: "published"` in the change), else it is kept.
      * arXiv-preprint entries that are not published become `journal = {arXiv preprint arXiv:<id>}`;
        ones not in the library are added as `unchecked`.
      * published @inproceedings / @article entries lose pages, volume, publisher, doi, url, ...;
        their venue text is kept as written.
    Cite key and title are always kept, and so is the author text except in the case above. Entries that already have just the four fields,
    preprint entries without an arXiv id, and every other kind of entry (@book, @misc for a website,
    @string, comments) are left byte for byte. Returns the new text plus:
      changes      — preprint -> published venue
      cleaned      — entries that lost fields (`dropped`)
      needs_check  — the agent should check these, write back with set_status, then call again
      no_arxiv_id  — preprint entries without a recognisable arXiv id (agent handles them by hand)
    """
    entries = parse_bibtex(text)
    pre = {id(e): arxiv_id_of(e) for e in entries if is_preprint(e) and e.fields.get("title")}
    res = get_entries(session, [i for i in pre.values() if i])
    library = {b.paper_id: b for b in res["entries"]}

    changes, cleaned, open_items, no_id, out, last = [], [], [], [], [], 0
    for e in entries:
        new = None
        if id(e) in pre:
            pid = pre[id(e)]
            if not pid:
                no_id.append({"cite_key": e.key, "title": e.fields["title"]})
                continue
            b = library.get(pid)
            if b and is_published(b):
                official = " and ".join(escape_latex(a) for a in authors_of(b)) if b.published_authors else None
                new = format_entry(e.key, e.fields["title"], official or e.fields.get("author", ""),
                                   b.venue_type, escape_latex(b.venue), b.venue_year)
                changes.append({"cite_key": e.key, "arxiv_id": pid, "authors": "published" if official else "kept",
                                "from": e.fields.get("journal") or e.fields.get("booktitle") or f"@{e.type}",
                                "to": f"{b.venue} {b.venue_year} ({b.venue_type})"})
            else:
                if not b or needs_check(b):
                    open_items.append({"cite_key": e.key, "arxiv_id": pid, "status": b.status if b else "not-found",
                                       "checked_at": b.checked_at.isoformat() if b and b.checked_at else None})
                new = _clean_preprint(e, pid, b.arxiv_year if b else arxiv_year(pid))
                if new:
                    cleaned.append({"cite_key": e.key, "dropped": _extra_fields(e, "journal")})
        else:
            hit = _clean_published(e)
            if hit:
                new = hit[0]
                cleaned.append({"cite_key": e.key, "dropped": hit[1]})
        if new:
            out.append(text[last:e.start])
            out.append(new)
            last = e.end
    out.append(text[last:])
    return {"bibtex": "".join(out), "changes": changes, "cleaned": cleaned, "needs_check": open_items,
            "no_arxiv_id": no_id, "entries_total": len(entries), "preprints": len(pre), "warnings": res["warnings"]}
