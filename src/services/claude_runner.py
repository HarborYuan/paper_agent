"""
Claude API (Anthropic, direct) runner for the verdict pipeline.

- Requests carry a cacheable system prompt (instructions + profile, identical across papers) and a
  per-paper user message; structured output via output_config.format (JSON schema).
- run() sends a list of requests either through the Message Batches API (50% off, async, used by the
  nightly worker) or in real time (on-demand deep reads, single papers). Batch requests that error,
  expire or are still pending after BATCH_MAX_WAIT_MINUTES are retried once in real time.
- Every call is logged to the llmusage table with a cost computed from the Anthropic price list
  (Anthropic does not return cost), halved for batch.
"""
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from src.config import settings

# USD per 1M tokens: (input, output, cache read). Cache writes (5-minute TTL) cost 1.25x input.
PRICES: Dict[str, tuple] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-fable-5-2": (8.00, 40.00, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}
HAIKU_55_LONG = (0.50, 2.50, 0.05)  # Claude Haiku 5.5 prompts over 100K tokens


OPENROUTER_ANTHROPIC_URL = "https://openrouter.ai/api"   # OpenRouter's Anthropic-compatible Messages endpoint


def openrouter_model_id(model: str) -> str:
    """claude-haiku-5-5 -> anthropic/claude-haiku-5.5; claude-sonnet-5 -> anthropic/claude-sonnet-5."""
    if model.startswith("anthropic/"):
        return model
    m = re.match(r"^(claude-[a-z]+)-(\d+)-(\d+)$", model)
    return f"anthropic/{m.group(1)}-{m.group(2)}.{m.group(3)}" if m else f"anthropic/{model}"


def make_client(max_retries: int = 4):
    """Async Anthropic-SDK client for the configured CHAT_PROVIDER."""
    import anthropic
    if settings.CHAT_PROVIDER == "openrouter":
        return anthropic.AsyncAnthropic(api_key=settings.OPENROUTER_API_KEY, base_url=OPENROUTER_ANTHROPIC_URL,
                                        max_retries=max_retries)
    return anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=max_retries)


def is_claude_model(model: Optional[str]) -> bool:
    return bool(model) and model.startswith("claude-")


def estimate_cost(model: str, usage: Dict[str, int], batch: bool = False) -> Optional[float]:
    price = PRICES.get(model)
    if price is None:
        return None
    inp = usage.get("input_tokens", 0)
    cw = usage.get("cache_creation_input_tokens", 0)
    cr = usage.get("cache_read_input_tokens", 0)
    out = usage.get("output_tokens", 0)
    if model == "claude-haiku-5-5" and inp + cw + cr > 100_000:
        price = HAIKU_55_LONG
    p_in, p_out, p_cr = price
    cost = (inp * p_in + cw * p_in * 1.25 + cr * p_cr + out * p_out) / 1_000_000
    return cost * (0.5 if batch else 1.0)


@dataclass
class ClaudeRequest:
    key: str                         # caller-chosen id, unique within one run()
    task: str                        # llmusage task name
    model: str
    system: str                      # stable across papers -> cached
    user: str
    schema: Optional[dict] = None    # JSON schema for structured output
    max_tokens: int = 16000
    effort: Optional[str] = None     # output_config.effort
    paper_id: Optional[str] = None

    def params(self) -> Dict[str, Any]:
        p: Dict[str, Any] = {
            "model": openrouter_model_id(self.model) if settings.CHAT_PROVIDER == "openrouter" else self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": self.user}],
        }
        if self.system:
            p["system"] = [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}]
        oc: Dict[str, Any] = {}
        if self.schema is not None:
            oc["format"] = {"type": "json_schema", "schema": self.schema}
        if self.effort:
            oc["effort"] = self.effort
        if oc:
            p["output_config"] = oc
        return p


@dataclass
class ClaudeResult:
    key: str
    data: Optional[dict] = None
    text: Optional[str] = None
    error: Optional[str] = None
    usage: Dict[str, int] = field(default_factory=dict)
    batch: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and (self.data is not None or self.text is not None)


def _usage_dict(usage: Any) -> Dict[str, int]:
    if usage is None:
        return {}
    d = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
    return {k: int(d.get(k) or 0) for k in ("input_tokens", "output_tokens",
                                             "cache_creation_input_tokens", "cache_read_input_tokens")}


def _parse_message(req: ClaudeRequest, msg: Any, batch: bool) -> ClaudeResult:
    res = ClaudeResult(key=req.key, usage=_usage_dict(getattr(msg, "usage", None)), batch=batch)
    stop = getattr(msg, "stop_reason", None)
    if stop == "refusal":
        res.error = "refusal"
        return res
    if stop == "max_tokens":
        res.error = "max_tokens"
        return res
    text = next((b.text for b in (msg.content or []) if getattr(b, "type", None) == "text"), None)
    res.text = text
    if req.schema is not None:
        try:
            res.data = json.loads(text or "")
        except (json.JSONDecodeError, TypeError) as e:
            res.error = f"invalid JSON: {e}"
    return res


def _record(req: ClaudeRequest, res: ClaudeResult, latency_ms: Optional[int]) -> None:
    """Persist one call to llmusage. Never raises."""
    try:
        from sqlmodel import Session
        from src.database import engine
        from src.models import LLMUsage
        u = res.usage
        prompt = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
        out = u.get("output_tokens", 0)
        with Session(engine) as session:
            session.add(LLMUsage(
                paper_id=req.paper_id, task=req.task,
                model=req.model + (" (batch)" if res.batch else "") + (" (openrouter)" if settings.CHAT_PROVIDER == "openrouter" else ""),
                prompt_tokens=prompt, completion_tokens=out, total_tokens=prompt + out,
                cost=estimate_cost(req.model, u, batch=res.batch), cost_estimated=True,
                latency_ms=latency_ms, success=res.ok,
            ))
            session.commit()
    except Exception as e:  # pragma: no cover - logging must never break the pipeline
        print(f"  - (usage logging failed: {e})")


LogFn = Optional[Callable[[str], Awaitable[None]]]


class ClaudeRunner:
    MAX_POLL_ERRORS = 40   # consecutive failed status checks (~20 min at the default poll) before giving up

    def __init__(self, api_key: Optional[str] = None, use_batch: Optional[bool] = None,
                 max_wait_minutes: Optional[int] = None, poll_seconds: float = 30.0,
                 concurrency: int = 6, client: Any = None):
        self.use_batch = settings.LLM_USE_BATCH if use_batch is None else use_batch
        if settings.CHAT_PROVIDER == "openrouter":
            self.use_batch = False   # OpenRouter has no Message Batches API
        self.max_wait = 60 * (settings.BATCH_MAX_WAIT_MINUTES if max_wait_minutes is None else max_wait_minutes)
        self.poll_seconds = poll_seconds
        self.concurrency = concurrency
        self.client = client if client is not None else make_client()

    async def _log(self, log: LogFn, msg: str) -> None:
        if log:
            await log(msg)
        else:
            print(msg)

    # ------------------------------------------------------------------ real time
    async def _one(self, req: ClaudeRequest) -> ClaudeResult:
        t0 = time.monotonic()
        try:
            # Streaming keeps long outputs (deep reads) clear of HTTP timeouts.
            async with self.client.messages.stream(**req.params()) as stream:
                msg = await stream.get_final_message()
            res = _parse_message(req, msg, batch=False)
        except Exception as e:
            res = ClaudeResult(key=req.key, error=f"{type(e).__name__}: {e}"[:500])
        _record(req, res, int((time.monotonic() - t0) * 1000))
        return res

    async def run_realtime(self, reqs: List[ClaudeRequest]) -> Dict[str, ClaudeResult]:
        sem = asyncio.Semaphore(self.concurrency)

        async def go(r):
            async with sem:
                return await self._one(r)
        results = await asyncio.gather(*(go(r) for r in reqs))
        return {r.key: r for r in results}

    # ------------------------------------------------------------------ batch
    async def run_batch(self, reqs: List[ClaudeRequest], log: LogFn = None) -> Dict[str, ClaudeResult]:
        by_cid = {f"r{i}": r for i, r in enumerate(reqs)}   # custom_id must match ^[a-zA-Z0-9_-]{1,64}$
        batch = await self.client.messages.batches.create(
            requests=[{"custom_id": cid, "params": r.params()} for cid, r in by_cid.items()])
        await self._log(log, f"  - Submitted batch {batch.id} ({len(reqs)} requests, {reqs[0].task if reqs else ''})")
        t0 = time.monotonic()
        errors = 0
        while True:
            try:
                batch = await self.client.messages.batches.retrieve(batch.id)
                errors = 0
            except Exception as e:
                # A network blip must not drop a submitted (and billed) batch for a real-time re-run.
                errors += 1
                if errors == 1:
                    await self._log(log, f"  - Batch {batch.id}: status check failed ({type(e).__name__}: {e}); retrying")
                if errors >= self.MAX_POLL_ERRORS:
                    raise
                await asyncio.sleep(self.poll_seconds)
                continue
            if batch.processing_status == "ended":
                break
            if time.monotonic() - t0 > self.max_wait:
                await self._log(log, f"  - Batch {batch.id} still running after {self.max_wait // 60} min; cancelling")
                try:
                    await self.client.messages.batches.cancel(batch.id)
                except Exception:
                    pass
                # wait briefly for the cancellation to settle so finished results can still be read
                for _ in range(20):
                    await asyncio.sleep(min(self.poll_seconds, 15))
                    batch = await self.client.messages.batches.retrieve(batch.id)
                    if batch.processing_status == "ended":
                        break
                break
            await asyncio.sleep(self.poll_seconds)

        out: Dict[str, ClaudeResult] = {}
        if batch.processing_status == "ended":
            for attempt in range(3):
                try:
                    results = await self.client.messages.batches.results(batch.id)
                    async for entry in results:
                        req = by_cid.get(entry.custom_id)
                        if req is None or req.key in out:
                            continue
                        if entry.result.type == "succeeded":
                            res = _parse_message(req, entry.result.message, batch=True)
                        else:
                            res = ClaudeResult(key=req.key, error=f"batch {entry.result.type}", batch=True)
                        _record(req, res, None)
                        out[req.key] = res
                    break
                except Exception as e:  # results stream cut off: read it again, keeping what arrived
                    await self._log(log, f"  - Batch {batch.id}: reading results failed ({type(e).__name__}: {e})")
                    await asyncio.sleep(min(self.poll_seconds, 15) * (attempt + 1))
        # retry anything missing or failed (except refusals) once in real time
        retry = [r for r in reqs if r.key not in out or (out[r.key].error and out[r.key].error != "refusal")]
        if retry:
            await self._log(log, f"  - Retrying {len(retry)} request(s) in real time")
            out.update(await self.run_realtime(retry))
        return out

    async def run(self, reqs: List[ClaudeRequest], log: LogFn = None,
                  batch: Optional[bool] = None) -> Dict[str, ClaudeResult]:
        if not reqs:
            return {}
        use_batch = self.use_batch if batch is None else batch
        if use_batch:
            try:
                return await self.run_batch(reqs, log)
            except Exception as e:
                await self._log(log, f"  - Batch submission failed ({e}); falling back to real time")
        return await self.run_realtime(reqs)
