"""
LLM usage accounting + cost estimation.

- cost_since(): real spend since a timestamp (used in the daily digest)
- usage_summary(): totals for today / 7d / 30d / all, plus a by-task/by-model breakdown
- estimate(): projected per-day / per-month cost for a candidate model selection,
  using observed average tokens per task (falls back to priors) and observed daily volumes.
"""
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any

from sqlalchemy import func
from sqlmodel import Session, select

from src.models import LLMUsage, Paper
from src.services.model_catalog import model_catalog
from src.services.settings_service import (
    TASK_STAGE1, TASK_STAGE2, TASK_SUMMARY, TASK_AFFILIATION, ALL_TASKS, LLMConfig,
)

# Priors for average tokens per call when there is no history yet (prompt, completion)
TOKEN_PRIORS: Dict[str, tuple] = {
    TASK_STAGE1: (1100, 150),
    TASK_STAGE2: (3800, 450),
    TASK_SUMMARY: (22000, 1300),
    TASK_AFFILIATION: (1300, 80),
}
# Priors for calls/day when there is no history yet
VOLUME_PRIORS: Dict[str, float] = {
    TASK_STAGE1: 130.0,
    TASK_STAGE2: 20.0,
    TASK_SUMMARY: 4.0,
    TASK_AFFILIATION: 4.0,
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


def _avg_tokens_per_task(session: Session, days: int = 30) -> Dict[str, Dict[str, Any]]:
    """Observed average prompt/completion tokens per task (successful calls only), with priors as fallback."""
    since = datetime.now() - timedelta(days=days)
    rows = session.exec(
        select(
            LLMUsage.task,
            func.count(LLMUsage.id),
            func.avg(LLMUsage.prompt_tokens),
            func.avg(LLMUsage.completion_tokens),
        ).where(LLMUsage.created_at >= since, LLMUsage.success == True, LLMUsage.total_tokens > 0)
        .group_by(LLMUsage.task)
    ).all()
    observed = {t: (int(n or 0), float(p or 0), float(c or 0)) for t, n, p, c in rows}
    out = {}
    for task in ALL_TASKS:
        n, p, c = observed.get(task, (0, 0.0, 0.0))
        if n >= MIN_SAMPLES_FOR_AVG:
            out[task] = {"prompt": round(p), "completion": round(c), "source": "observed", "samples": n}
        else:
            pp, cc = TOKEN_PRIORS[task]
            out[task] = {"prompt": pp, "completion": cc, "source": "prior", "samples": n}
    return out


def _daily_volumes(session: Session, cfg: LLMConfig, days: int = 14) -> Dict[str, Dict[str, Any]]:
    """
    Expected calls/day per task, derived from the paper table over the last N days
    (papers/day, share passing stage-2 threshold, share passing score threshold).
    """
    since = datetime.now() - timedelta(days=days)
    total = session.exec(select(func.count(Paper.id)).where(Paper.created_at >= since)).one() or 0
    scored = session.exec(select(func.count(Paper.id)).where(Paper.created_at >= since, Paper.score.is_not(None))).one() or 0
    # Stage-2 share: prefer observed score_stage1 >= threshold; fall back to final score >= threshold
    s2_obs = session.exec(select(func.count(Paper.id)).where(Paper.created_at >= since, Paper.score_stage1 >= cfg.stage2_threshold)).one() or 0
    s2_fallback = session.exec(select(func.count(Paper.id)).where(Paper.created_at >= since, Paper.score >= cfg.stage2_threshold)).one() or 0
    above = session.exec(select(func.count(Paper.id)).where(Paper.created_at >= since, Paper.score >= cfg.score_threshold)).one() or 0
    active_days = session.exec(select(func.count(func.distinct(func.date(Paper.created_at)))).where(Paper.created_at >= since)).one() or 0

    if total and active_days:
        per_day = total / active_days
        stage2_per_day = (s2_obs if s2_obs else s2_fallback) / active_days
        summary_per_day = above / active_days
        src = "observed"
    else:
        per_day = VOLUME_PRIORS[TASK_STAGE1]
        stage2_per_day = VOLUME_PRIORS[TASK_STAGE2]
        summary_per_day = VOLUME_PRIORS[TASK_SUMMARY]
        src = "prior"
    return {
        TASK_STAGE1: {"calls_per_day": round(per_day, 1), "source": src},
        TASK_STAGE2: {"calls_per_day": round(stage2_per_day, 1), "source": src},
        TASK_SUMMARY: {"calls_per_day": round(summary_per_day, 1), "source": src},
        TASK_AFFILIATION: {"calls_per_day": round(summary_per_day, 1), "source": src},
        "_meta": {"window_days": days, "papers": int(total), "scored": int(scored), "active_days": int(active_days)},
    }


def estimate(session: Session, cfg: LLMConfig) -> Dict[str, Any]:
    """Project cost for the given model selection."""
    tokens = _avg_tokens_per_task(session)
    volumes = _daily_volumes(session, cfg)
    per_task: List[Dict[str, Any]] = []
    total_per_day = 0.0
    missing_prices: List[str] = []
    for task in ALL_TASKS:
        model = cfg.model_for_task(task)
        info = model_catalog.get_for_pricing(model)
        tk = tokens[task]
        calls = volumes[task]["calls_per_day"]
        if info:
            cost_per_call = (tk["prompt"] * info.prompt_price_per_m + tk["completion"] * info.completion_price_per_m) / 1_000_000
            price_in, price_out = info.prompt_price_per_m, info.completion_price_per_m
        else:
            cost_per_call = None
            price_in = price_out = None
            if model not in missing_prices:
                missing_prices.append(model)
        cost_per_day = (cost_per_call * calls) if cost_per_call is not None else None
        if cost_per_day is not None:
            total_per_day += cost_per_day
        per_task.append({
            "task": task, "model": model,
            "price_in_per_m": price_in, "price_out_per_m": price_out,
            "avg_prompt_tokens": tk["prompt"], "avg_completion_tokens": tk["completion"],
            "tokens_source": tk["source"], "token_samples": tk["samples"],
            "calls_per_day": calls, "volume_source": volumes[task]["source"],
            "cost_per_call": cost_per_call, "cost_per_day": cost_per_day,
        })
    return {
        "config": cfg.to_dict(),
        "per_task": per_task,
        "total_per_day": total_per_day,
        "total_per_month": total_per_day * 30,
        "missing_prices": missing_prices,
        "volumes_meta": volumes["_meta"],
        "catalog": model_catalog.status(),
    }
