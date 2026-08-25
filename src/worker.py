import asyncio
import json
from datetime import datetime

from sqlmodel import Session, select
from src.database import engine
from src.config import settings
from src.models import Paper, Author
from src.services.arxiv import ArxivFetcher
from src.services.llm import LLMService
from src.services.notifier import get_notifier
from src.services.pdf_service import pdf_service
from src.services.settings_service import get_llm_config
from src.services.usage_service import cost_since
from src.services.report_service import run_scheduled_reports, report_to_lark, mark_pushed
from src.services.embedding_service import embed_new_papers
from src.utils import sanitize_text
from src.logger import logger

CONCURRENCY_LIMIT = 5
PAPER_SYNC_LIMIT = 500


def _score_threshold() -> int:
    return get_llm_config().score_threshold


async def process_paper_score(sem: asyncio.Semaphore, llm: LLMService, paper: Paper):
    """
    Two-stage scoring:
      stage 1 — cheap model, title+abstract, recall-oriented
      stage 2 — stronger model, abstract + beginning of full text, precision-oriented;
                runs only when stage-1 score >= stage2_threshold. Final score = stage 2 when it ran.
    """
    async with sem:
        await logger.log(f"Scoring paper: {paper.id}")

        # Check for user score first
        if paper.user_score is not None:
             await logger.log(f"  - Skipping AI scoring for {paper.id}, user score present: {paper.user_score}")
             return

        cfg = llm.config
        details = {}

        # ---- Stage 1
        s1 = await llm.score_paper(paper, settings.USER_PROFILE)
        if s1 is None:
            await logger.log(f"  - Stage-1 scoring failed for {paper.id}; leaving as NEW")
            return
        final_score = s1.score
        final_model = cfg.stage1_model
        details["stage1"] = {"model": cfg.stage1_model, **s1.model_dump()}
        await logger.log(f"  - Stage 1 ({cfg.stage1_model}): {s1.score}")

        # ---- Stage 2 (conditional)
        fetched_text = None
        if s1.score >= cfg.stage2_threshold:
            # Reuse cached full text if we already have it, else fetch the PDF now
            # (the text is stored so summarization can reuse it later).
            with Session(engine) as session:
                db_paper = session.get(Paper, paper.id)
                cached_text = db_paper.full_text if db_paper else None
            text = cached_text
            if not text and paper.pdf_url:
                text = await pdf_service.extract_text_from_url(paper.pdf_url)
                fetched_text = text
            snippet = text[: settings.STAGE2_TEXT_CHAR_LIMIT] if text else None
            s2 = await llm.score_paper_stage2(paper, settings.USER_PROFILE, snippet)
            if s2 is not None:
                final_score = s2.score
                final_model = cfg.stage2_model
                details["stage2"] = {"model": cfg.stage2_model, "had_full_text": bool(text), **s2.model_dump()}
                await logger.log(f"  - Stage 2 ({cfg.stage2_model}): {s2.score}")
            else:
                details["stage2"] = {"model": cfg.stage2_model, "error": "stage-2 scoring failed; kept stage-1 score"}
                await logger.log(f"  - Stage 2 failed for {paper.id}; keeping stage-1 score {s1.score}")

        # ---- Important-author boost
        is_important_author = False
        try:
            with Session(engine) as session:
                authors = paper.authors_list
                if authors:
                    statement = select(Author).where(
                        Author.name.in_(authors),
                        Author.is_important == True
                    )
                    important_authors = session.exec(statement).all()
                    if important_authors:
                        is_important_author = True
                        await logger.log(f"  - Found important author(s): {[a.name for a in important_authors]}")
        except Exception as e:
            await logger.log(f"  - Error checking important authors: {e}")

        if is_important_author and final_score < 90:
            await logger.log(f"  - Boosting score from {final_score} to 90 due to important author.")
            details["boost"] = {"reason": "important_author", "from": final_score, "to": 90}
            final_score = 90

        details["final"] = final_score
        threshold = cfg.score_threshold

        with Session(engine) as session:
            db_paper = session.get(Paper, paper.id)
            if db_paper:
                db_paper.score = final_score
                db_paper.score_stage1 = s1.score
                db_paper.score_model = final_model
                db_paper.score_reason = sanitize_text(json.dumps(details, ensure_ascii=False))
                if fetched_text and not db_paper.full_text:
                    db_paper.full_text = sanitize_text(fetched_text)
                db_paper.status = "FILTERED" if final_score < threshold else "SCORED"
                db_paper.updated_at = datetime.now()
                session.add(db_paper)
                session.commit()

async def process_paper_summary(sem: asyncio.Semaphore, llm: LLMService, paper: Paper):
    async with sem:
        await logger.log(f"Summarizing paper: {paper.id}")

        # Reuse full text cached by stage-2 scoring if present; otherwise fetch the PDF.
        with Session(engine) as session:
            db_paper = session.get(Paper, paper.id)
            full_text = db_paper.full_text if db_paper else None
        if not full_text and paper.pdf_url:
            full_text = await pdf_service.extract_text_from_url(paper.pdf_url)

        aff_data = None
        if full_text:
            await logger.log(f"  - Using full text for {paper.id} ({len(full_text)} chars)")
            # Extract affiliations
            aff_data = await llm.extract_affiliations(paper, full_text)
            if aff_data:
                await logger.log(f"  - Affiliations: {aff_data.main_affiliation}")
            # Summarize with full text
            summary = await llm.summarize_paper(paper, full_text=full_text, user_profile=settings.USER_PROFILE)
        else:
            await logger.log(f"  - Full text not available for {paper.id}")
            summary = await llm.summarize_paper(paper, user_profile=settings.USER_PROFILE)

        with Session(engine) as session:
            db_paper = session.get(Paper, paper.id)
            if db_paper:
                if full_text:
                    db_paper.full_text = sanitize_text(full_text)

                if aff_data:
                    db_paper.affiliations = sanitize_text(json.dumps(aff_data.affiliations))
                    db_paper.main_company = sanitize_text(aff_data.main_company)
                    db_paper.main_university = sanitize_text(aff_data.main_university)
                    db_paper.main_affiliation = sanitize_text(aff_data.main_affiliation)

                if summary:
                    db_paper.summary_personalized = sanitize_text(summary)
                    db_paper.status = "SUMMARIZED"

                db_paper.updated_at = datetime.now()
                session.add(db_paper)
                session.commit()

async def run_worker():
    await logger.log("Starting worker cycle...")
    run_started_at = datetime.now()

    # 1. Fetch
    fetcher = ArxivFetcher(categories=settings.ARXIV_CATEGORIES)
    # 2000 for MVP; usually good enough
    fetched_papers = await asyncio.to_thread(fetcher.fetch_papers, max_results=PAPER_SYNC_LIMIT)
    new_papers = fetcher.filter_new_papers(fetched_papers)
    fetcher.save_papers(new_papers)

    # 1b. Embed the new papers (semantic search / related / clustering). Non-fatal.
    if new_papers:
        try:
            n = await embed_new_papers([p.id for p in new_papers], log=logger.log)
            await logger.log(f"Embedded {n} new paper(s).")
        except Exception as e:
            await logger.log(f"Embedding skipped: {e}")

    notifier = get_notifier()

    # Papers can sit as NEW without today's fetch producing anything: a backfill
    # inserts them directly, and an earlier run may have died mid-scoring. Those
    # still deserve a cycle, so only the genuinely idle case stops early.
    with Session(engine) as session:
        pending_new = session.exec(select(Paper.id).where(Paper.status == "NEW")).first()

    # Nothing new and nothing pending — send rest-day notification (plus any weekly/monthly report that is due) and stop early
    if not new_papers and not pending_new:
        await logger.log("No new papers retrieved.")
        reports = await run_scheduled_reports(run_started_at.date(), None, log=logger.log)
        if notifier:
            await notifier.send_message(
                "😴 No new papers retrieved today. Taking a break!"
            )
            if reports and await notifier.send_messages([report_to_lark(r) for r in reports]):
                for r in reports:
                    mark_pushed(r.id)
        else:
            await logger.log("No notifier configured.")
        return

    llm = LLMService()
    cfg = llm.config
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
    await logger.log(
        f"Models — stage1: {cfg.stage1_model} | stage2: {cfg.stage2_model} (>= {cfg.stage2_threshold}) | "
        f"summary: {cfg.summary_model} (>= {cfg.score_threshold})"
    )

    # 2. Score NEW papers
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "NEW")
        papers_to_score = session.exec(statement).all()

    scored_count = len(papers_to_score)
    above_threshold_count = 0
    stage2_count = 0

    if papers_to_score:
        await logger.log(f"Scoring {len(papers_to_score)} papers...")
        await asyncio.gather(*[process_paper_score(sem, llm, p) for p in papers_to_score])

        # Count how many of the just-scored papers cleared the thresholds
        scored_ids = [p.id for p in papers_to_score]
        with Session(engine) as session:
            above_threshold_count = len(session.exec(select(Paper).where(
                Paper.id.in_(scored_ids),
                Paper.score >= cfg.score_threshold,
            )).all())
            stage2_count = len(session.exec(select(Paper).where(
                Paper.id.in_(scored_ids),
                Paper.score_stage1 >= cfg.stage2_threshold,
            )).all())

    # 3. Summarize SCORED papers (High score)
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "SCORED") # Filtering handled in scoring step
        papers_to_summarize = session.exec(statement).all()

    if papers_to_summarize:
        await logger.log(f"Summarizing {len(papers_to_summarize)} papers...")
        await asyncio.gather(*[process_paper_summary(sem, llm, p) for p in papers_to_summarize])

    # 4. Notify
    with Session(engine) as session:
        statement = select(Paper).where(Paper.status == "SUMMARIZED")
        papers_to_notify = session.exec(statement).all()

    # 4b. Reports (daily for this run's pushed papers; weekly / monthly when due).
    # Generated before sending so they go out in the same batch, right after the digest.
    reports = await run_scheduled_reports(run_started_at.date(), [p.id for p in papers_to_notify], llm=llm, log=logger.log)

    if not notifier:
        await logger.log("No notifier configured.")
        return

    # Always emit a summary header about today's scoring activity
    run_cost = cost_since(run_started_at)
    cost_line = f"   • LLM cost this run: ${run_cost:.3f}\n" if run_cost is not None else ""
    summary_msg = (
        f"📊 Today's scoring\n"
        f"   • Scored: {scored_count} paper(s)\n"
        f"   • Stage-2 reviewed (≥{cfg.stage2_threshold}): {stage2_count}\n"
        f"   • Above threshold (≥{cfg.score_threshold}): {above_threshold_count}\n"
        f"{cost_line}"
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
                digest += f"   ⭐ Score: {p.score}{aff}\n"
                digest += f"   🔗 {p.pdf_url}\n"
                if p.summary_personalized:
                    tldr = p.summary_personalized[:150].replace("\n", " ")
                    digest += f"   💡 {tldr}...\n"
                digest += "\n"
            messages.append(digest)

    # Reports go right after the digest, each as its own card with its own title
    for r in reports:
        messages.append(report_to_lark(r))

    success = await notifier.send_messages(messages)

    if success and papers_to_notify:
        with Session(engine) as session:
            for p in papers_to_notify:
                db_p = session.get(Paper, p.id)
                db_p.status = "PUSHED"
                session.add(db_p)
            session.commit()
    if success:
        for r in reports:
            mark_pushed(r.id)


async def process_single_paper(paper_id: str, force_rescore: bool = False, notify: bool = True):
    """
    Process a single paper: score -> (if good) summarize -> notify (if configured)

    With notify=False the paper is left in SUMMARIZED, so the next scheduled
    run picks it up in the batched digest instead of an individual message.
    """
    await logger.log(f"Processing single paper: {paper_id} (force_rescore={force_rescore}, notify={notify})")

    # Check if paper exists
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)

    if not paper:
        await logger.log(f"Paper {paper_id} not found in DB.")
        return

    llm = LLMService()
    threshold = llm.config.score_threshold
    sem = asyncio.Semaphore(1) # processed singly, so limit doesn't matter much

    # 1. Score
    if force_rescore or paper.status == "NEW" or paper.status == "FILTERED":
        await process_paper_score(sem, llm, paper)

    # Reload to check score
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)

    if not paper: return

    # 2. Summarize (reuse an existing summary instead of regenerating it)
    if paper.score and paper.score >= threshold and paper.summary_personalized:
        if paper.status == "SCORED":
            with Session(engine) as session:
                db_p = session.get(Paper, paper_id)
                if db_p:
                    db_p.status = "SUMMARIZED"
                    session.add(db_p)
                    session.commit()
    elif paper.status == "SCORED" or (paper.score and paper.score >= threshold):
        await process_paper_summary(sem, llm, paper)

    # Reload
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)

    if not paper: return

    # 3. Notify
    if notify and paper.status == "SUMMARIZED":
        notifier = get_notifier()
        if notifier:
            digest = f"*New Paper Added:*\n\n"
            digest += f"📄 *{paper.title}* (Score: {paper.score})\n"
            digest += f"[PDF]({paper.pdf_url})\n"
            digest += f"tl;dr: {paper.summary_personalized[:200]}...\n\n"

            success = await notifier.send_message(digest)

            if success:
                with Session(engine) as session:
                    db_p = session.get(Paper, paper.id)
                    db_p.status = "PUSHED"
                    session.add(db_p)
                    session.commit()


async def resummarize_single_paper(paper_id: str):
    """
    Force re-summarize a single paper regardless of its current status.
    Always re-runs scoring and summarization, skipping notification.
    """
    await logger.log(f"Force re-summarizing paper: {paper_id}")

    with Session(engine) as session:
        paper = session.get(Paper, paper_id)

    if not paper:
        await logger.log(f"Paper {paper_id} not found in DB.")
        return

    llm = LLMService()
    sem = asyncio.Semaphore(1)

    # 1. Re-score
    if paper.user_score is None:
        await process_paper_score(sem, llm, paper)
    else:
        await logger.log(f"  - Skipping re-scoring for {paper.id}, user score present: {paper.user_score}")

    # Reload after scoring
    with Session(engine) as session:
        paper = session.get(Paper, paper_id)
    if not paper:
        return

    # 2. Always summarize (regardless of score)
    await process_paper_summary(sem, llm, paper)

    await logger.log(f"Finished re-summarizing paper: {paper_id}")


if __name__ == "__main__":
    from src.database import init_db
    try:
        init_db()
    except Exception as e:
        print(f"DB Init Error: {e}")
    asyncio.run(run_worker())
