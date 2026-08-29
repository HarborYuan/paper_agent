"""
Daily / weekly / monthly trend reports over the high-scoring papers of a period.

Python computes the statistics (counts, institutions, categories, authors, score distribution,
deltas vs the previous period, LLM cost); the LLM writes the narrative from those numbers plus
the paper list. Reports are stored in the `report` table and pushed to Lark right after the
daily digest (see worker.run_worker), and can be generated / pushed on demand from the UI.
"""
import json
import re
import calendar
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlmodel import Session, select

from src.config import settings
from src.database import engine
from src.models import Paper, Author, Report, LLMUsage
from src.services.paper_views import summary_tldr
from src.services.prompt_service import prompt_service
from src.services.settings_service import get_llm_config
from src.utils import sanitize_text

KINDS = ("daily", "weekly", "monthly")
TITLES = {"daily": "📰 Daily Report", "weekly": "📊 Weekly Report", "monthly": "📈 Monthly Report"}
TOP_N = 8


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------
def period_for(kind: str, ref: date) -> Tuple[datetime, datetime, str]:
    """
    Return (start inclusive, end exclusive, label) for a report kind anchored at `ref` (UTC date).
      daily   -> the day `ref`
      weekly  -> the 7 days ending the day before `ref`   (run on Monday => Mon..Sun of last week)
      monthly -> the previous calendar month if ref is the 1st, else the month containing `ref`
    """
    if kind not in KINDS:
        raise ValueError(f"unknown report kind: {kind}")
    if kind == "daily":
        start = datetime.combine(ref, datetime.min.time())
        return start, start + timedelta(days=1), ref.isoformat()
    if kind == "weekly":
        end = datetime.combine(ref, datetime.min.time())
        start = end - timedelta(days=7)
        return start, end, f"{start.date().isoformat()} – {(end - timedelta(days=1)).date().isoformat()}"
    # monthly
    if ref.day == 1:
        last_month_end = ref - timedelta(days=1)
        year, month = last_month_end.year, last_month_end.month
    else:
        year, month = ref.year, ref.month
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), (month % 12) + 1, 1)
    return start, end, f"{year:04d}-{month:02d}"


def _prev_period(start: datetime, end: datetime) -> Tuple[datetime, datetime]:
    span = end - start
    return start - span, start


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def _select_papers(session: Session, start: datetime, end: datetime, threshold: int,
                   paper_ids: Optional[List[str]] = None) -> List[Paper]:
    if paper_ids is not None:
        if not paper_ids:
            return []
        papers = session.exec(select(Paper).where(Paper.id.in_(paper_ids))).all()
    else:
        papers = session.exec(select(Paper).where(
            Paper.published_at >= start, Paper.published_at < end, Paper.score >= threshold
        )).all()
    return sorted(papers, key=lambda p: ((p.score or 0), p.published_at), reverse=True)


def _count_top(values, n=TOP_N) -> List[Dict[str, Any]]:
    c = Counter(v.strip() for v in values if v and str(v).strip())
    return [{"name": k, "count": v} for k, v in c.most_common(n)]


def _with_prev(cur: List[Dict[str, Any]], prev_values) -> List[Dict[str, Any]]:
    pc = Counter(v.strip() for v in prev_values if v and str(v).strip())
    return [{**row, "prev": pc.get(row["name"], 0)} for row in cur]


def compute_stats(session: Session, kind: str, start: datetime, end: datetime,
                  paper_ids: Optional[List[str]] = None) -> Tuple[Dict[str, Any], List[Paper]]:
    cfg = get_llm_config()
    threshold, s2_threshold = cfg.score_threshold, cfg.stage2_threshold
    papers = _select_papers(session, start, end, threshold, paper_ids)
    pstart, pend = _prev_period(start, end)
    prev_papers = _select_papers(session, pstart, pend, threshold)

    # Volume in the period (by created_at for daily-at-run-time sets, else published_at)
    if paper_ids is not None:
        fetched = session.exec(select(func.count(Paper.id)).where(Paper.created_at >= start, Paper.created_at < end)).one() or 0
        stage2 = session.exec(select(func.count(Paper.id)).where(Paper.created_at >= start, Paper.created_at < end,
                                                                Paper.score_stage1 >= s2_threshold)).one() or 0
    else:
        fetched = session.exec(select(func.count(Paper.id)).where(Paper.published_at >= start, Paper.published_at < end)).one() or 0
        stage2 = session.exec(select(func.count(Paper.id)).where(Paper.published_at >= start, Paper.published_at < end,
                                                                Paper.score_stage1 >= s2_threshold)).one() or 0
    prev_fetched = session.exec(select(func.count(Paper.id)).where(Paper.published_at >= pstart, Paper.published_at < pend)).one() or 0

    scores = [p.score for p in papers if p.score is not None]
    buckets = {"85-89": 0, "90-94": 0, "95-100": 0, "other": 0}
    for sc in scores:
        if 85 <= sc <= 89: buckets["85-89"] += 1
        elif 90 <= sc <= 94: buckets["90-94"] += 1
        elif sc >= 95: buckets["95-100"] += 1
        else: buckets["other"] += 1

    authors_counter = Counter(a for p in papers for a in p.authors_list)
    # NB: SQLModel returns scalars (not 1-tuples) for single-column selects
    important = set(session.exec(select(Author.name).where(Author.is_important == True)).all()) if papers else set()
    important_seen = sorted(a for a in authors_counter if a in important)

    try:
        cost = session.exec(select(func.coalesce(func.sum(LLMUsage.cost), 0.0)).where(
            LLMUsage.created_at >= start, LLMUsage.created_at < end)).one()
        cost = float(cost or 0.0)
    except Exception:
        cost = None

    # Embedding-based topic clusters (only when enough papers have vectors)
    clusters: List[List[str]] = []
    try:
        from src.services.embedding_service import cluster as embed_cluster
        if len(papers) >= 4:
            clusters, _missing = embed_cluster([p.id for p in papers])
            if len(clusters) <= 1:
                clusters = []
    except Exception as e:
        print(f"  - clustering skipped: {e}")

    stats = {
        "period": {"kind": kind, "start": start.date().isoformat(), "end_exclusive": end.date().isoformat()},
        "clusters": clusters,
        "selected": len(papers),
        "fetched": int(fetched),
        "stage2_reviewed": int(stage2),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "score_buckets": buckets,
        "companies": _with_prev(_count_top(p.main_company for p in papers), (p.main_company for p in prev_papers)),
        "universities": _with_prev(_count_top(p.main_university for p in papers), (p.main_university for p in prev_papers)),
        "affiliations": _with_prev(_count_top(p.main_affiliation for p in papers), (p.main_affiliation for p in prev_papers)),
        "categories": _count_top(p.category_primary for p in papers),
        "top_authors": [{"name": k, "count": v} for k, v in authors_counter.most_common(10) if v > 1] or
                       [{"name": k, "count": v} for k, v in authors_counter.most_common(5)],
        "important_authors_seen": important_seen,
        "prev": {"selected": len(prev_papers), "fetched": int(prev_fetched),
                 "period": {"start": pstart.date().isoformat(), "end_exclusive": pend.date().isoformat()}},
        "llm_cost_usd": round(cost, 4) if cost else None,   # None (not 0) when no usage rows fall in the period
    }
    return stats, papers


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def _paper_view(p: Paper) -> Dict[str, Any]:
    reason = ""
    if p.score_reason:
        try:
            d = json.loads(p.score_reason)
            if isinstance(d, dict):
                st = d.get("stage2") or d.get("stage1") or d
                reason = st.get("one_line_reason") or ""
        except json.JSONDecodeError:
            reason = ""
    tldr = summary_tldr(p.summary_personalized, 280)
    return {"id": p.id, "title": p.title, "score": p.score, "affiliation": p.main_affiliation or p.main_company or "",
            "reason": reason[:300], "tldr": tldr}


def build_prompt(kind: str, label: str, stats: Dict[str, Any], papers: List[Paper]) -> str:
    cfg = get_llm_config()
    title_of = {p.id: p.title for p in papers}
    cluster_views = [
        [{"id": pid, "title": title_of.get(pid, pid)} for pid in c]
        for c in (stats.get("clusters") or [])
    ]
    stats_for_prompt = {k: v for k, v in stats.items() if k != "clusters"}
    return prompt_service.render_prompt(
        "report.jinja2",
        kind=kind, period_label=label, score_threshold=cfg.score_threshold,
        user_profile=settings.USER_PROFILE, language=settings.SUMMARY_LANGUAGE,
        stats_json=json.dumps(stats_for_prompt, ensure_ascii=False, indent=1),
        papers=[_paper_view(p) for p in papers],
        clusters=cluster_views,
    )


# ---------------------------------------------------------------------------
# Generate / store / render
# ---------------------------------------------------------------------------
def find_report(session: Session, kind: str, start: datetime) -> Optional[Report]:
    return session.exec(select(Report).where(Report.kind == kind, Report.period_start == start)).first()


async def generate_report(kind: str, ref: Optional[date] = None, paper_ids: Optional[List[str]] = None,
                          llm=None, replace: bool = True) -> Optional[Report]:
    """
    Build stats + prompt for the period, ask the LLM, store (replacing an existing report for the
    same kind+period when replace=True). Returns the Report, or None if there was nothing to report
    on or the LLM call failed.
    """
    ref = ref or datetime.utcnow().date()
    start, end, label = period_for(kind, ref)
    with Session(engine) as session:
        existing = find_report(session, kind, start)
        if existing and not replace:
            return existing
        # Daily at run time: union with ids already covered today (second manual run the same day)
        ids = paper_ids
        if ids is not None and existing and existing.paper_ids:
            try:
                ids = sorted(set(ids) | set(json.loads(existing.paper_ids)))
            except json.JSONDecodeError:
                pass
        stats, papers = compute_stats(session, kind, start, end, ids)
        if not papers:
            return None
        prompt = build_prompt(kind, label, stats, papers)
        covered = [p.id for p in papers]
        existing_id = existing.id if existing else None

    if llm is None:
        from src.services.llm import LLMService
        llm = LLMService()
    content = await llm.generate_report(prompt, ref=f"report:{kind}:{label}")
    if not content:
        return None
    content = sanitize_text(content.strip())
    content = re.sub(r"^```[a-zA-Z]*\n?", "", content).strip()
    content = re.sub(r"\n?```$", "", content).strip()

    with Session(engine) as session:
        rep = session.get(Report, existing_id) if existing_id else None
        if rep is None:
            rep = Report(kind=kind, period_start=start, period_end=end, period_label=label,
                         title=f"{TITLES[kind]} · {label}", content=content)
        rep.title = f"{TITLES[kind]} · {label}"
        rep.content = content
        rep.stats = json.dumps(stats, ensure_ascii=False)
        rep.paper_ids = json.dumps(covered)
        rep.paper_count = len(covered)
        rep.model = llm.config.model_for_task("report")
        rep.updated_at = datetime.now()
        session.add(rep)
        session.commit()
        session.refresh(rep)
        session.expunge(rep)
        return rep


def markdown_to_lark_text(md: str) -> str:
    """Lark 'post' cards are plain text: turn headings into 【…】, strip emphasis markers."""
    out = []
    for line in md.splitlines():
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if m:
            out.append(f"【{m.group(1).strip()}】")
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"\1", line)
        line = re.sub(r"`(.+?)`", r"\1", line)
        out.append(line)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def report_to_lark(report: Report) -> Tuple[str, str]:
    footer = f"\n\n— {report.paper_count} papers · {report.model or 'LLM'}"
    return report.title, markdown_to_lark_text(report.content) + footer


def mark_pushed(report_id: int) -> None:
    with Session(engine) as session:
        rep = session.get(Report, report_id)
        if rep:
            rep.pushed = True
            rep.pushed_at = datetime.now()
            session.add(rep)
            session.commit()


async def run_scheduled_reports(today: date, daily_paper_ids: Optional[List[str]], llm=None,
                                log=None) -> List[Report]:
    """
    Called at the end of a worker run. Generates whichever reports are due:
      daily   — when enabled and this run pushed papers
      weekly  — when enabled and today is REPORT_WEEKLY_DAY and no report exists for that week
      monthly — when enabled and today is the 1st and no report exists for last month
    Returns the reports to push (in order).
    """
    async def _log(msg):
        if log:
            await log(msg)
    out: List[Report] = []
    try:
        if settings.REPORT_DAILY_ENABLED and daily_paper_ids:
            rep = await generate_report("daily", today, paper_ids=daily_paper_ids, llm=llm)
            if rep:
                out.append(rep); await _log(f"Report: daily ({rep.paper_count} papers)")
        if settings.REPORT_WEEKLY_ENABLED and today.weekday() == int(settings.REPORT_WEEKLY_DAY):
            start, _, _ = period_for("weekly", today)
            with Session(engine) as s:
                exists = find_report(s, "weekly", start) is not None
            if not exists:
                rep = await generate_report("weekly", today, llm=llm)
                if rep:
                    out.append(rep); await _log(f"Report: weekly {rep.period_label} ({rep.paper_count} papers)")
        if settings.REPORT_MONTHLY_ENABLED and today.day == 1:
            start, _, _ = period_for("monthly", today)
            with Session(engine) as s:
                exists = find_report(s, "monthly", start) is not None
            if not exists:
                rep = await generate_report("monthly", today, llm=llm)
                if rep:
                    out.append(rep); await _log(f"Report: monthly {rep.period_label} ({rep.paper_count} papers)")
    except Exception as e:
        await _log(f"Report generation failed: {e}")
    return out
