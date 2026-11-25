"""
LLM usage accounting.

- cost_since(): real spend since a timestamp (used in the daily digest)
- usage_summary(): totals for today / 7d / 30d / all, plus a by-task/by-model breakdown
"""
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any

from sqlalchemy import func
from sqlmodel import Session, select

from src.models import LLMUsage, Paper
from src.services.model_catalog import model_catalog
from src.services.settings_service import (
    TASK_STAGE1, TASK_STAGE2, TASK_SUMMARY, TASK_AFFILIATION, TASK_EMBED, ALL_TASKS, LLMConfig,
)

# Priors for average tokens per call when there is no history yet (prompt, completion)
TOKEN_PRIORS: Dict[str, tuple] = {
    TASK_STAGE1: (1100, 150),
    TASK_STAGE2: (3800, 450),
    TASK_SUMMARY: (22000, 1300),
    TASK_AFFILIATION: (1300, 80),
    TASK_EMBED: (20000, 0),     # one batch of ~64 title+abstract texts
}
# Priors for calls/day when there is no history yet
VOLUME_PRIORS: Dict[str, float] = {
    TASK_STAGE1: 130.0,
    TASK_STAGE2: 20.0,
    TASK_SUMMARY: 4.0,
    TASK_AFFILIATION: 4.0,
    TASK_EMBED: 2.5,    # ~130 papers/day in batches of 64, plus search queries
}
MIN_SAMPLES_FOR_AVG = 5


def _engine():
    from src.database import engine
    return engine


def cost_since(since: datetime, session: Optional[Session] = None) -> Optional[float]:
    def _q(s: Session):
        total = s.exec(select(func.coalesce(func.sum(LLMUsage.cost), 0.0)).where(LLMUsage.created_at >= since)).one()
        return float(total or 0.0)
    try:
        if session is not None:
            return _q(session)
        with Session(_engine()) as s:
            return _q(s)
    except Exception:
        return None


def _period_totals(s: Session, since: Optional[datetime]) -> Dict[str, Any]:
    q = select(
        func.count(LLMUsage.id),
        func.coalesce(func.sum(LLMUsage.prompt_tokens), 0),
        func.coalesce(func.sum(LLMUsage.completion_tokens), 0),
        func.coalesce(func.sum(LLMUsage.cost), 0.0),
    )
    if since is not None:
        q = q.where(LLMUsage.created_at >= since)
    calls, p, c, cost = s.exec(q).one()
    return {"calls": int(calls or 0), "prompt_tokens": int(p or 0), "completion_tokens": int(c or 0), "cost": float(cost or 0.0)}


def usage_summary(session: Session, breakdown_days: int = 30) -> Dict[str, Any]:
    now = datetime.now()
    today = datetime.combine(now.date(), datetime.min.time())
    periods = {
        "today": _period_totals(session, today),
        "last_7d": _period_totals(session, now - timedelta(days=7)),
        "last_30d": _period_totals(session, now - timedelta(days=30)),
        "all_time": _period_totals(session, None),
    }
    since = now - timedelta(days=breakdown_days)
    rows = session.exec(
        select(
            LLMUsage.task, LLMUsage.model,
            func.count(LLMUsage.id),
            func.coalesce(func.sum(LLMUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LLMUsage.completion_tokens), 0),
            func.coalesce(func.sum(LLMUsage.cost), 0.0),
            func.sum(LLMUsage.cost_estimated),
        ).where(LLMUsage.created_at >= since).group_by(LLMUsage.task, LLMUsage.model)
    ).all()
    breakdown = []
    for task, model, calls, p, c, cost, est in rows:
        calls = int(calls or 0)
        breakdown.append({
            "task": task, "model": model, "calls": calls,
            "prompt_tokens": int(p or 0), "completion_tokens": int(c or 0),
            "avg_prompt_tokens": round((p or 0) / calls) if calls else 0,
            "avg_completion_tokens": round((c or 0) / calls) if calls else 0,
            "cost": float(cost or 0.0),
            "cost_per_call": (float(cost or 0.0) / calls) if calls else 0.0,
            "estimated_rows": int(est or 0),
        })
    breakdown.sort(key=lambda r: -r["cost"])
    # Daily series for the last N days (for a small sparkline / table)
    daily_rows = session.exec(
        select(func.date(LLMUsage.created_at), func.count(LLMUsage.id), func.coalesce(func.sum(LLMUsage.cost), 0.0))
        .where(LLMUsage.created_at >= since)
        .group_by(func.date(LLMUsage.created_at))
        .order_by(func.date(LLMUsage.created_at))
    ).all()
    daily = [{"date": str(d), "calls": int(n or 0), "cost": float(c or 0.0)} for d, n, c in daily_rows]
    return {"periods": periods, "breakdown_days": breakdown_days, "breakdown": breakdown, "daily": daily}
