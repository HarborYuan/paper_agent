"""
Hot lane: papers that are popular right now, pushed in their own digest section whether or not they
match the profile.

- refresh(): pull Hugging Face Daily Papers for the last HOT_LOOKBACK_DAYS days and upsert upvotes /
  GitHub stars into hotsignal. Hot papers missing from the library are added (status NEW) so the normal
  pipeline scores them in the same run.
- pending(): hot (upvotes >= HOT_MIN_UPVOTES or stars >= HOT_MIN_STARS) and not pushed yet, most
  upvoted first, at most HOT_MAX_PER_RUN.
- chatter(): one Claude call with the web_search tool on the pending list — what people say about them.
- section(): the Lark message; mark_pushed() records them so each paper is pushed once.
"""
import asyncio
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx
from sqlmodel import Session, select

from src.config import settings
from src.database import engine
from src.models import HotSignal, Paper

HF_URL = "https://huggingface.co/api/daily_papers"
WEB_SEARCH_COST = 0.01   # USD per search ($10 / 1k)


def _is_hot(sig: HotSignal) -> bool:
    return sig.upvotes >= settings.HOT_MIN_UPVOTES or sig.github_stars >= settings.HOT_MIN_STARS


async def fetch_day(client: httpx.AsyncClient, day: str) -> List[dict]:
    try:
        r = await client.get(HF_URL, params={"date": day})
        return r.json() if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return []


async def refresh(log=None) -> Dict[str, int]:
    """Upsert HF signals for the lookback window; add missing hot papers to the library."""
    today = datetime.now(timezone.utc).date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(settings.HOT_LOOKBACK_DAYS)]
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "paper-agent"}) as c:
        results = await asyncio.gather(*(fetch_day(c, d) for d in days))
    seen, added = 0, []
    with Session(engine) as s:
        for day, items in zip(days, results):
            for it in items:
                p = it.get("paper") or {}
                pid = re.sub(r"v\d+$", "", str(p.get("id") or ""))
                if not re.match(r"^\d{4}\.\d{4,5}$", pid):
                    continue
                seen += 1
                sig = s.get(HotSignal, pid) or HotSignal(paper_id=pid, hf_date=day)
                sig.upvotes = max(sig.upvotes, int(p.get("upvotes") or 0))
                sig.github_stars = max(sig.github_stars, int(p.get("githubStars") or 0))
                sig.ai_summary = p.get("ai_summary") or sig.ai_summary
                sig.github_repo = p.get("githubRepo") or sig.github_repo
                sig.updated_at = datetime.now()
                s.add(sig)
                if _is_hot(sig) and sig.pushed_at is None and not s.get(Paper, pid):
                    added.append(pid)
        s.commit()
    if added:
        from src.services.arxiv import ArxivFetcher
        fetcher = ArxivFetcher(categories=settings.ARXIV_CATEGORIES)
        new = []
        for pid in added:
            try:
                new += await asyncio.to_thread(fetcher.fetch_paper_by_id, pid)
            except Exception as e:  # a missing paper must not break the run
                print(f"  - hot: could not fetch {pid}: {e}")
            await asyncio.sleep(1)
        new = fetcher.filter_new_papers(new)
        added = [p.id for p in new]   # read ids before save: committed instances are expired/detached
        fetcher.save_papers(new)
        if added:
            try:
                from src.services.embedding_service import embed_new_papers
                await embed_new_papers(added)
            except Exception:
                pass
    if log:
        await log(f"Hot lane: {seen} HF entries in {len(days)} days, {len(added)} hot paper(s) added to the library")
    return {"seen": seen, "added": len(added)}


def pending(limit: Optional[int] = None) -> List[HotSignal]:
    with Session(engine) as s:
        sigs = s.exec(select(HotSignal).where(HotSignal.pushed_at == None)).all()  # noqa: E711
    hot = sorted([x for x in sigs if _is_hot(x)], key=lambda x: (-x.upvotes, -x.github_stars))
    return hot[: (settings.HOT_MAX_PER_RUN if limit is None else limit)]


def mark_pushed(paper_ids: List[str]) -> None:
    with Session(engine) as s:
        for pid in paper_ids:
            sig = s.get(HotSignal, pid)
            if sig:
                sig.pushed_at = datetime.now()
                s.add(sig)
        s.commit()


async def chatter(papers: List[Paper], log=None) -> Dict[str, str]:
    """{paper_id: one Chinese sentence on the discussion around it}, via one web_search call. {} on any failure."""
    from src.services import claude_budget
    # server-side web search is a Claude API tool; skipped when chat goes through OpenRouter
    if not papers or not settings.HOT_WEB_SEARCH or settings.CHAT_PROVIDER != "anthropic" or not settings.ANTHROPIC_API_KEY:
        return {}
    if claude_budget.status()["remaining"] < 1.0:
        return {}
    import anthropic
    from src.services.claude_runner import estimate_cost
    from src.models import LLMUsage
    listing = "\n".join(f"- [{p.id}] {p.title}" for p in papers)
    prompt = ("These arXiv papers are trending this week:\n" + listing + "\n\nSearch the web (X/Twitter, blogs, "
              "Hacker News, Reddit, news) for what researchers are saying about each one. Then answer with ONLY a JSON "
              "object mapping each arXiv id to one short Chinese sentence summarizing the discussion (why people care, "
              "praise or criticism). Use an empty string when you find nothing specific. Do not invent discussion.")
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=2)
    from src.services.settings_service import get_llm_config
    model = get_llm_config().stage2_model
    messages = [{"role": "user", "content": prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    searches, text, t0 = 0, "", time.monotonic()
    try:
        for _ in range(3):  # server tools may pause a long turn; resume it
            msg = await client.messages.create(model=model, max_tokens=8000, messages=messages,
                                               tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}])
            u = msg.usage
            for k in usage:
                usage[k] += int(getattr(u, k, 0) or 0)
            stu = getattr(u, "server_tool_use", None)
            searches += int(getattr(stu, "web_search_requests", 0) or 0) if stu else 0
            if msg.stop_reason == "pause_turn":
                messages = [messages[0], {"role": "assistant", "content": msg.content}]
                continue
            text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
            break
    except Exception as e:
        if log:
            await log(f"Hot lane: web search failed ({e})")
        return {}
    finally:
        cost = (estimate_cost(model, usage) or 0) + searches * WEB_SEARCH_COST
        try:
            with Session(engine) as s:
                s.add(LLMUsage(task="hot_chatter", model=model, prompt_tokens=usage["input_tokens"] + usage["cache_read_input_tokens"]
                               + usage["cache_creation_input_tokens"], completion_tokens=usage["output_tokens"],
                               total_tokens=sum(usage.values()), cost=cost, cost_estimated=True,
                               latency_ms=int((time.monotonic() - t0) * 1000), success=bool(text)))
                s.commit()
        except Exception:
            pass
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    out = {re.sub(r"v\d+$", "", k.strip("[] ")): v.strip() for k, v in data.items() if isinstance(v, str) and v.strip()}
    if log:
        await log(f"Hot lane: web search ({searches} searches) found discussion for {len(out)} of {len(papers)} papers")
    return out


def section(sigs: List[HotSignal], papers: Dict[str, Paper], talk: Dict[str, str]) -> Optional[str]:
    """The Lark message for the Hot section (None if nothing to send)."""
    from src.services.paper_views import summary_tldr
    rows = [s for s in sigs if s.paper_id in papers]
    if not rows:
        return None
    labels = {"must_read": "Must Read", "worth_reading": "Worth Reading", "skim": "Skim", "skip": "Skip"}
    out = f"🔥 Hot this week ({len(rows)})\n" + "─" * 30 + "\n\n"
    for i, sig in enumerate(rows, 1):
        p = papers[sig.paper_id]
        try:
            r = json.loads(p.score_reason or "{}")
            v = (r.get("deep") or r.get("stage2") or {}).get("verdict")
        except (json.JSONDecodeError, AttributeError):
            v = None
        pop = f"👍 {sig.upvotes}" + (f" · ⭐ {sig.github_stars} stars" if sig.github_stars else "")
        out += f"{i}. {p.title}\n   {pop}" + (f" · {labels[v]}" if v in labels else "") + "\n"
        tl = summary_tldr(p.summary_personalized, 150) if p.summary_personalized else (sig.ai_summary or "")[:200]
        if tl:
            out += f"   💡 {tl}\n"
        if talk.get(p.id):
            out += f"   💬 {talk[p.id]}\n"
        if settings.PUBLIC_BASE_URL:
            out += f"   📖 {settings.PUBLIC_BASE_URL.rstrip('/')}/read/{p.id}\n"
        out += f"   🔗 https://arxiv.org/abs/{p.id}\n\n"
    return out
