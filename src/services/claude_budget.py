"""
Spend guard for the Claude API key.

Spend = sum of llmusage.cost for Claude models since the start of the current billing cycle
(CLAUDE_BUDGET_RESET_DAY). Costs are list-price estimates written by claude_runner (batch halved),
so they track the Console bill closely but not exactly; keep CLAUDE_MONTHLY_BUDGET a bit under the
real credit to leave headroom.
"""
from datetime import datetime
from typing import Dict

from sqlalchemy import func
from sqlmodel import Session, select

from src.config import settings

# Rough per-request costs (batch prices) used to size a stage before submitting it.
EST = {"screen": 0.0003, "review": 0.015, "deep": 0.08}


def cycle_start(now: datetime = None) -> datetime:
    now = now or datetime.now()
    day = max(1, min(28, int(settings.CLAUDE_BUDGET_RESET_DAY)))
    start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
    if start > now:  # reset day not reached yet this month -> cycle began last month
        y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        start = start.replace(year=y, month=m)
    return start


def spent(now: datetime = None) -> float:
    from src.database import engine
    from src.models import LLMUsage
    with Session(engine) as s:
        v = s.exec(select(func.sum(LLMUsage.cost)).where(
            LLMUsage.created_at >= cycle_start(now), LLMUsage.model.like("claude-%"))).one()
    return float(v or 0.0)


def status(now: datetime = None) -> Dict[str, float]:
    sp = spent(now)
    budget = float(settings.CLAUDE_MONTHLY_BUDGET)
    return {"budget": budget, "spent": round(sp, 4), "remaining": round(budget - sp, 4),
            "cycle_start": cycle_start(now).isoformat()}


def affordable(kind: str, n: int) -> int:
    """How many of n requests of this kind fit in the remaining budget."""
    rem = status()["remaining"]
    if rem <= 0:
        return 0
    return max(0, min(n, int(rem // EST[kind])))
