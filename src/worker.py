import asyncio
import json
from datetime import datetime
from typing import Dict, List

from sqlmodel import Session, select
from src.database import engine
from src.config import settings
from src.models import Paper
from src.services.arxiv import ArxivFetcher, ArxivAPIError
from src.services.notifier import get_notifier, alert_arxiv_failure
from src.services.paper_views import summary_tldr
from src.services.settings_service import get_llm_config
from src.services.usage_service import cost_since
from src.services.embedding_service import embed_new_papers
from src.logger import logger

PAPER_SYNC_LIMIT = 500
VERDICT_LABEL = {"must_read": "Must Read", "worth_reading": "Worth Reading"}


async def score_papers(papers: List[Paper], log=None) -> Dict[str, int]:
    """
    Verdict pipeline over NEW papers (screen -> review -> deep read, each stage one Batch API job), then
    deep reads left over from earlier runs (status SCORED), within the per-run cap and the Claude budget.
    """
    from src.services import claude_budget, verdict_pipeline
    from src.services.claude_runner import ClaudeRunner
    log = log or logger.log
    runner = ClaudeRunner()
    with Session(engine) as session:
        pending_deep = session.exec(select(Paper).where(Paper.status == "SCORED", Paper.user_score == None)).all()  # noqa: E711
    stats = {"screened": 0, "reviewed": 0, "deep_read": 0}
    if papers:
        await log(f"Verdict pipeline on {len(papers)} papers...")
        stats = await verdict_pipeline.run_pipeline(papers, runner, log=log)
    if pending_deep:
        cap = min(settings.DEEP_READ_MAX_PER_RUN - stats.get("deep_read", 0),
                  claude_budget.affordable("deep", len(pending_deep)))
        chosen = verdict_pipeline.select_for_deep(pending_deep, cap)
        if chosen:
            await log(f"Deep-reading {len(chosen)} of {len(pending_deep)} paper(s) left from earlier runs...")
            done = await verdict_pipeline.deep_read(chosen, runner, log, final=True)
            stats["deep_read"] = stats.get("deep_read", 0) + len(done)
    return stats


def _verdict(p: Paper):
    try:
        r = json.loads(p.score_reason or "{}")
        return (r.get("deep") or r.get("stage2") or {}).get("verdict") if isinstance(r, dict) else None
    except json.JSONDecodeError:
        return None


async def run_worker():
    await logger.log("Starting worker cycle...")
    run_started_at = datetime.now()

    # 1. Fetch
    fetcher = ArxivFetcher(categories=settings.ARXIV_CATEGORIES)
    fetch_error = None
    try:
        fetched_papers = await asyncio.to_thread(fetcher.fetch_papers, max_results=PAPER_SYNC_LIMIT)
    except ArxivAPIError as e:
        # Don't mistake an outage for a quiet day: alert, then still work through pending papers
        fetch_error = e
        fetched_papers = []
        await logger.log(f"arXiv fetch failed: {e}")
        if not await alert_arxiv_failure("Daily arXiv fetch", e):
            await logger.log("arXiv failure alert not sent (no notifier configured or push failed).")
    new_papers = fetcher.filter_new_papers(fetched_papers)
    fetcher.save_papers(new_papers)

    # 1b. Embed every paper still without a vector: today's papers plus anything added by hand, bulk inserts
    # or an earlier failed call — no manual backfill needed. Non-fatal.
    try:
        n = await embed_new_papers(limit=settings.EMBED_CATCHUP_PER_RUN, log=logger.log)
        if n:
            await logger.log(f"Embedded {n} paper(s).")
    except Exception as e:
        await logger.log(f"Embedding skipped: {e}")

    # 1c. Hot lane: refresh Hugging Face popularity; hot papers missing from the library are added as NEW.
    if settings.HOT_ENABLED:
        try:
            from src.services import hot_service
            await hot_service.refresh(log=logger.log)
        except Exception as e:
            await logger.log(f"Hot lane refresh skipped: {e}")

    notifier = get_notifier()

    # Papers can sit as NEW without today's fetch producing anything: a backfill
    # inserts them directly, and an earlier run may have died mid-scoring. Those
    # still deserve a cycle, so only the genuinely idle case stops early.
    with Session(engine) as session:
        pending_new = session.exec(select(Paper.id).where(Paper.status == "NEW")).first()

    # Nothing new and nothing pending — send rest-day notification and stop early
    if not new_papers and not pending_new:
        await logger.log("No new papers retrieved.")
        if notifier:
            if not fetch_error:  # the outage alert already went out; "taking a break" would be misleading
                await notifier.send_message(
                    "😴 No new papers retrieved today. Taking a break!"
                )
        else:
            await logger.log("No notifier configured.")
        return

    cfg = get_llm_config()
    await logger.log(f"Models — screen: {cfg.stage1_model} | review: {cfg.stage2_model} | deep read: {cfg.summary_model}")

    # 2. Score NEW papers
    with Session(engine) as session:
        papers_to_score = session.exec(select(Paper).where(Paper.status == "NEW")).all()
    scored_count = len(papers_to_score)
    stats = {"reviewed": 0, "deep_read": 0}
    if not settings.chat_api_key:
        await logger.log(f"{settings.chat_key_name} is not configured — scoring skipped; papers stay NEW.")
        if notifier:
            await notifier.send_message(f"⚠️ Paper Agent: {settings.chat_key_name} is not configured, so today's papers were not scored. Set it on the Settings page.")
    else:
        stats = await score_papers(papers_to_score)
    above_threshold_count = 0
    if papers_to_score:
        with Session(engine) as session:
            above_threshold_count = len(session.exec(select(Paper).where(
                Paper.id.in_([p.id for p in papers_to_score]), Paper.score >= cfg.score_threshold)).all())

    # 4. Notify
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "SUMMARIZED")
        papers_to_notify = session.exec(statement).all()

    if not notifier:
        await logger.log("No notifier configured.")
        return

    # Always emit a summary header about today's scoring activity
    run_cost = cost_since(run_started_at)
    from src.services import claude_budget
    b = claude_budget.status()
    budget_line = f"   • Claude budget: ${b['spent']:.2f} / ${b['budget']:.0f} this cycle\n"
    cost_line = f"   • LLM cost this run: ${run_cost:.3f}\n" if run_cost is not None else ""
    summary_msg = (
        f"📊 Today's scoring\n"
        f"   • Scored: {scored_count} paper(s)\n"
        f"   • Reviewed (relevance ≥ {settings.SCREEN_MIN_RELEVANCE}): {stats.get('reviewed', 0)}\n"
        f"   • Deep read: {stats.get('deep_read', 0)}\n"
        f"   • Must Read / Worth Reading: {above_threshold_count}\n"
        f"{cost_line}"
        f"{budget_line}"
    )
    messages = [summary_msg]

    if papers_to_notify:
        await logger.log(f"Notifying {len(papers_to_notify)} papers...")
        # Group papers by published date
        from collections import defaultdict
        by_date = defaultdict(list)
        for p in papers_to_notify:
            date_key = p.published_at.strftime("%Y-%m-%d")
            by_date[date_key].append(p)

        # Sort dates (newest first), sort papers within each date by score desc
        for date_key in sorted(by_date.keys(), reverse=True):
            date_papers = sorted(by_date[date_key], key=lambda x: x.score or 0, reverse=True)
            digest = f"📅 {date_key}  ({len(date_papers)} papers)\n"
            digest += "─" * 30 + "\n\n"
            for i, p in enumerate(date_papers, 1):
                aff = f" | {p.main_affiliation}" if p.main_affiliation else ""
                digest += f"{i}. {p.title}\n"
                authors = p.authors_list
                if authors:
                    author_str = ", ".join(authors[:3])
                    if len(authors) > 3:
                        author_str += f" +{len(authors) - 3} more"
                    digest += f"   👥 {author_str}\n"
                label = VERDICT_LABEL.get(_verdict(p))
                digest += (f"   ⭐ {label} ({p.score}){aff}\n" if label else f"   ⭐ Score: {p.score}{aff}\n")
                from src.services import project_service
                projs = project_service.projects_of(p.id)
                if projs:
                    digest += f"   📁 {', '.join(projs)}\n"
                if settings.PUBLIC_BASE_URL:
                    digest += f"   📖 {settings.PUBLIC_BASE_URL.rstrip('/')}/read/{p.id}\n"
                digest += f"   🔗 {p.pdf_url}\n"
                if p.summary_personalized:
                    digest += f"   💡 {summary_tldr(p.summary_personalized, 150)}\n"
                digest += "\n"
            messages.append(digest)

    # Hot section: popular papers, relevant or not, each pushed once
    hot_ids = []
    if settings.HOT_ENABLED:
        try:
            from src.services import hot_service
            sigs = hot_service.pending()
            if sigs:
                with Session(engine) as session:
                    hot_papers = {p.id: p for p in session.exec(select(Paper).where(
                        Paper.id.in_([x.paper_id for x in sigs]))).all()}
                talk = await hot_service.chatter(list(hot_papers.values()), log=logger.log)
                hot_msg = hot_service.section(sigs, hot_papers, talk)
                if hot_msg:
                    messages.append(hot_msg)
                    hot_ids = list(hot_papers)
        except Exception as e:
            await logger.log(f"Hot section skipped: {e}")

    success = await notifier.send_messages(messages)
    if success and hot_ids:
        from src.services import hot_service
        hot_service.mark_pushed(hot_ids)

    if success and papers_to_notify:
        with Session(engine) as session:
            for p in papers_to_notify:
                db_p = session.get(Paper, p.id)
                db_p.status = "PUSHED"
                session.add(db_p)
            session.commit()


async def process_single_paper(paper_id: str, force_rescore: bool = False, notify: bool = True):
    """
    One paper in real time: screen -> review -> deep read (when it is worth reading) -> notify.
    With notify=False the paper is left in SUMMARIZED, so the next scheduled run picks it up
    in the batched digest instead of an individual message.
    """
    from src.services import verdict_pipeline
    from src.services.claude_runner import ClaudeRunner
    await logger.log(f"Processing single paper: {paper_id} (force_rescore={force_rescore}, notify={notify})")
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
    if not paper:
        await logger.log(f"Paper {paper_id} not found in DB.")
        return
    if not settings.chat_api_key:
        await logger.log(f"{settings.chat_key_name} is not configured — cannot score.")
        return
    try:  # vector first: semantic search and project recall need it
        await embed_new_papers([paper_id])
    except Exception as e:
        await logger.log(f"Embedding of {paper_id} skipped: {e}")
    runner = ClaudeRunner(use_batch=False)
    if force_rescore or paper.status in ("NEW", "FILTERED"):
        await verdict_pipeline.run_pipeline([paper], runner, log=logger.log)
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
    if paper and paper.status == "SCORED":  # reviewed as worth reading, deep read still missing
        await verdict_pipeline.deep_read([paper], runner, logger.log, final=True)
        with Session(engine) as session:
            paper = session.get(Paper, paper_id)
    if not paper:
        return

    if notify and paper.status == "SUMMARIZED":
        notifier = get_notifier()
        if notifier:
            label = VERDICT_LABEL.get(_verdict(paper), f"Score {paper.score}")
            digest = f"*New Paper Added:*\n\n📄 *{paper.title}* ({label})\n[PDF]({paper.pdf_url})\n"
            if settings.PUBLIC_BASE_URL:
                digest += f"📖 {settings.PUBLIC_BASE_URL.rstrip('/')}/read/{paper.id}\n"
            digest += f"tl;dr: {summary_tldr(paper.summary_personalized, 200)}\n\n"
            if await notifier.send_message(digest):
                with Session(engine) as session:
                    db_p = session.get(Paper, paper.id)
                    db_p.status = "PUSHED"
                    session.add(db_p)
                    session.commit()


async def resummarize_single_paper(paper_id: str):
    """Redo the deep read of one paper (reviewing it first if needed); no notification, status unchanged."""
    from src.services import verdict_pipeline
    await logger.log(f"Re-running the deep read of {paper_id}")
    await verdict_pipeline.deep_read_on_demand(paper_id, log=logger.log)


if __name__ == "__main__":
    from src.database import init_db
    try:
        init_db()
    except Exception as e:
        print(f"DB Init Error: {e}")
    asyncio.run(run_worker())
