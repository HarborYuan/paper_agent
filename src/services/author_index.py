"""
Fuzzy author lookup for "people of interest" queries.

Author strings on papers come straight from arXiv and vary in form ("Xiaoming Wang", "Wang, Xiaoming",
"X. Wang", accents, hyphens). This module builds an in-memory index of every author name seen on any
paper and resolves a query name to the stored variants by, in order:
  1. exact normalised match  (case / accents / punctuation / "Last, First" folded)
  2. same sorted tokens      (token order swapped, e.g. "Wang Xiaoming")
  3. first-initial + last name ("X. Wang" ~ "Xiaoming Wang")  — may match several people, flagged
"""
import json
import re
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from sqlmodel import Session, select

from src.database import engine
from src.models import Paper, Author

INDEX_TTL_SECONDS = 3600


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    if "," in s:                                   # "Last, First" -> "First Last"
        last, first = s.split(",", 1)
        s = f"{first} {last}"
    s = s.replace("-", " ").replace(".", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sorted_key(norm: str) -> str:
    return " ".join(sorted(norm.split()))


def initials_key(norm: str) -> str:
    toks = norm.split()
    if len(toks) < 2:
        return norm
    return f"{toks[0][0]} {toks[-1]}"


def is_initials_form(norm: str) -> bool:
    """True for names whose given-name part is abbreviated ("x wang", "j p smith")."""
    toks = norm.split()
    return len(toks) >= 2 and all(len(t) <= 2 for t in toks[:-1])


@dataclass
class AuthorIndex:
    exact: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    by_sorted: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    by_initials: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    counts: Counter = field(default_factory=Counter)
    built_at: float = 0.0

    def stale(self) -> bool:
        return (time.time() - self.built_at) > INDEX_TTL_SECONDS

    def build(self) -> int:
        exact, by_sorted, by_initials, counts = defaultdict(set), defaultdict(set), defaultdict(set), Counter()
        with Session(engine) as s:
            for authors_json in s.exec(select(Paper.authors)).all():   # scalars (single-column select)
                if not authors_json:
                    continue
                try:
                    names = json.loads(authors_json)
                except json.JSONDecodeError:
                    parts = authors_json.strip("[]").split('", "')
                    names = [p.strip('"') for p in parts if p.strip('"')]
                for n in names:
                    if not isinstance(n, str) or not n.strip():
                        continue
                    norm = normalize_name(n)
                    if not norm:
                        continue
                    exact[norm].add(n); by_sorted[sorted_key(norm)].add(n); by_initials[initials_key(norm)].add(n)
                    counts[n] += 1
        self.exact, self.by_sorted, self.by_initials, self.counts = exact, by_sorted, by_initials, counts
        self.built_at = time.time()
        return len(counts)

    def ensure(self) -> None:
        if not self.counts or self.stale():
            self.build()

    def resolve(self, name: str) -> Tuple[List[str], str]:
        """Return (matched stored variants sorted by paper count, match_type)."""
        self.ensure()
        norm = normalize_name(name)
        if not norm:
            return [], "none"
        for key, table, kind in ((norm, self.exact, "exact"), (sorted_key(norm), self.by_sorted, "token_order")):
            hits = table.get(key)
            if hits:
                return sorted(hits, key=lambda v: -self.counts[v]), kind
        # Level 3: first-initial + last name. A full-name query only matches stored *abbreviated* variants
        # ("Xiaoming Wang" ~ "X. Wang", not "Xeno Wang"); an abbreviated query matches every candidate (ambiguous).
        cands = self.by_initials.get(initials_key(norm)) or set()
        if cands:
            if not is_initials_form(norm):
                cands = {v for v in cands if is_initials_form(normalize_name(v))}
            if cands:
                return sorted(cands, key=lambda v: -self.counts[v]), "initials"
        return [], "none"


author_index = AuthorIndex()


def papers_for_variants(session: Session, variants: List[str], days: Optional[int] = None,
                        min_score: Optional[int] = None, limit: int = 20) -> List[Paper]:
    if not variants:
        return []
    found: Dict[str, Paper] = {}
    for v in variants:
        q = select(Paper).where(Paper.authors.contains(json.dumps(v)))
        if days is not None:
            q = q.where(Paper.published_at >= datetime.now() - timedelta(days=days))
        if min_score is not None:
            q = q.where(Paper.score >= min_score)
        for p in session.exec(q).all():
            if v in p.authors_list:
                found[p.id] = p
    papers = sorted(found.values(), key=lambda p: (p.published_at or datetime.min), reverse=True)
    return papers[:limit] if limit else papers


def lookup(session: Session, names: List[str], days: Optional[int] = None, min_score: Optional[int] = None,
           limit_per_author: int = 20, mark_important: bool = False) -> List[dict]:
    from src.services.paper_views import compact_paper
    out = []
    for name in names:
        variants, kind = author_index.resolve(name)
        papers = papers_for_variants(session, variants, days=days, min_score=min_score, limit=limit_per_author)
        ambiguous = kind == "initials" and len(variants) > 1
        important_by_name: Dict[str, bool] = {}
        if variants:
            if mark_important and not ambiguous and kind != "none":
                for v in variants:
                    row = session.get(Author, v) or Author(name=v)
                    row.is_important = True
                    row.updated_at = datetime.now()
                    session.add(row)
                session.commit()
            rows = session.exec(select(Author).where(Author.name.in_(variants))).all()
            important_by_name = {r.name: bool(r.is_important) for r in rows}
        out.append({
            "query": name,
            "match_type": kind,
            "matches": [{"name": v, "paper_count": author_index.counts.get(v, 0),
                         "is_important": important_by_name.get(v, False)} for v in variants],
            "ambiguous": ambiguous,
            # only meaningful for an unambiguous match: "this person is flagged important"
            "is_important": (not ambiguous) and any(important_by_name.values()),
            "papers": [compact_paper(p) for p in papers],
        })
    return out
