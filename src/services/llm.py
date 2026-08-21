import json
import re
import time
import asyncio
from typing import Optional, Dict, Any, List
from openai import AsyncOpenAI
from pydantic import BaseModel
from src.config import settings
from src.models import Paper, LLMUsage
from src.services.prompt_service import prompt_service
from src.services.settings_service import (
    get_llm_config, LLMConfig,
    TASK_STAGE1, TASK_STAGE2, TASK_SUMMARY, TASK_AFFILIATION, TASK_REPORT,
)
from src.services.model_catalog import model_catalog
from src.utils import sanitize_text

class ScoreResponse(BaseModel):
    score: int
    relevance: int
    novelty: int
    clarity: int
    risk_flags: List[str] = []
    one_line_reason: str = ""

class Stage2ScoreResponse(BaseModel):
    score: int
    relevance: int
    novelty: int
    quality: int
    clarity: int
    risk_flags: List[str] = []
    strengths: List[str] = []
    weaknesses: List[str] = []
    one_line_reason: str = ""

class AffiliationResponse(BaseModel):
    affiliations: List[str]
    main_company: Optional[str]
    main_university: Optional[str]
    main_affiliation: Optional[str]

SUMMARY_FULL_TEXT_CHAR_LIMIT = 300_000


def _clamp_int(v, lo=0, hi=100) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return lo


def extract_json_object(content: str) -> Dict[str, Any]:
    """
    Robustly pull a JSON object out of a model reply: handles ```json fences,
    leading prose, and trailing commentary. Raises ValueError if nothing parses.
    """
    if content is None:
        raise ValueError("empty content")
    text = content.strip()
    # Strip code fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find the first balanced {...} block
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in model output")


def _record_usage(task: str, model: str, paper_id: Optional[str], usage: Any,
                  latency_ms: int, success: bool) -> None:
    """Persist one LLM call's token usage + cost. Never raises."""
    try:
        prompt_tokens = completion_tokens = total_tokens = 0
        cost = None
        if usage is not None:
            try:
                udict = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
            except Exception:
                udict = {}
            prompt_tokens = int(udict.get("prompt_tokens") or 0)
            completion_tokens = int(udict.get("completion_tokens") or 0)
            total_tokens = int(udict.get("total_tokens") or (prompt_tokens + completion_tokens))
            raw_cost = udict.get("cost")
            if raw_cost is not None:
                try:
                    cost = float(raw_cost)
                except (TypeError, ValueError):
                    cost = None
        cost_estimated = False
        if cost is None and (prompt_tokens or completion_tokens):
            est = model_catalog.estimate_cost(model, prompt_tokens, completion_tokens)
            if est is not None:
                cost = est
                cost_estimated = True
        from sqlmodel import Session
        from src.database import engine
        with Session(engine) as session:
            session.add(LLMUsage(
                paper_id=paper_id, task=task, model=model,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                total_tokens=total_tokens, cost=cost, cost_estimated=cost_estimated,
                latency_ms=latency_ms, success=success,
            ))
            session.commit()
    except Exception as e:
        print(f"  - (usage logging failed: {e})")


class LLMService:
    """
    Thin wrapper over an OpenAI-compatible chat endpoint (OpenRouter by default).
    Model per task comes from runtime settings (UI) with env defaults.
    """
    def __init__(self, config: Optional[LLMConfig] = None):
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key or "missing-api-key",
            base_url=settings.llm_base_url,
            default_headers={
                # OpenRouter attribution headers (harmless for other providers)
                "HTTP-Referer": "https://github.com/HarborYuan/paper_agent",
                "X-Title": "Paper Agent",
            },
        )
        self.config = config or get_llm_config()
        self.is_openrouter = "openrouter.ai" in (settings.llm_base_url or "")
        # Back-compat attribute (older code/tests referenced .model)
        self.model = self.config.stage1_model

    # ------------------------------------------------------------------ model resolution
    def resolve_model(self, model: str) -> str:
        """
        Map a catalog model id to what the configured provider expects.
        - OpenRouter: ids are used as-is ("openai/gpt-4o-mini").
        - Legacy OpenAI-compatible endpoint: strip the "openai/" vendor prefix; a model from another
          vendor cannot be served there, so fall back to the stage-1 model (with a warning).
        """
        if self.is_openrouter or not model:
            return model
        if model.startswith("openai/"):
            return model[len("openai/"):]
        if "/" in model:
            fallback = self.config.stage1_model
            fallback = fallback[len("openai/"):] if fallback.startswith("openai/") else fallback
            print(f"  - Model '{model}' is not available on a non-OpenRouter endpoint; using '{fallback}' instead")
            return fallback
        return model

    # ------------------------------------------------------------------ core call
    async def _chat(self, task: str, prompt: str, *, json_mode: bool, temperature: float,
                    paper_id: Optional[str] = None, model: Optional[str] = None,
                    max_tokens: Optional[int] = None) -> Optional[str]:
        catalog_model = model or self.config.model_for_task(task)   # id as shown in Settings / catalog
        model = self.resolve_model(catalog_model)                     # id the provider expects
        messages = [{"role": "user", "content": prompt}]
        base_kwargs: Dict[str, Any] = {"model": model, "messages": messages}
        if max_tokens:
            base_kwargs["max_tokens"] = max_tokens
        extra_body: Dict[str, Any] = {}
        if self.is_openrouter:
            # Ask OpenRouter to include real cost in `usage`
            extra_body["usage"] = {"include": True}

        attempts: List[Dict[str, Any]] = []
        full = dict(base_kwargs)
        full["temperature"] = temperature
        if json_mode and model_catalog.supports_json(catalog_model):
            full["response_format"] = {"type": "json_object"}
        attempts.append(full)
        # Fallback: minimal parameter set (some models reject temperature / response_format)
        attempts.append(dict(base_kwargs))

        last_err: Optional[Exception] = None
        for i, kwargs in enumerate(attempts):
            t0 = time.monotonic()
            try:
                response = await self.client.chat.completions.create(**kwargs, extra_body=extra_body or None)
                latency = int((time.monotonic() - t0) * 1000)
                _record_usage(task, catalog_model, paper_id, getattr(response, "usage", None), latency, True)
                content = response.choices[0].message.content if response.choices else None
                return content
            except Exception as e:
                last_err = e
                latency = int((time.monotonic() - t0) * 1000)
                msg = str(e)
                # Only retry with the minimal param set on 4xx-style parameter errors
                retryable = i == 0 and len(attempts) > 1 and any(
                    k in msg.lower() for k in ("response_format", "temperature", "unsupported", "not support", "invalid", "400", "404")
                )
                if retryable:
                    print(f"  - LLM call ({task}, {model}) failed with '{msg[:120]}'; retrying with minimal params")
                    continue
                _record_usage(task, catalog_model, paper_id, None, latency, False)
                break
        print(f"Error in LLM call ({task}, model={model}, paper={paper_id}): {last_err}")
        return None

    # ------------------------------------------------------------------ stage 1
    async def score_paper(self, paper: Paper, user_profile: str) -> Optional[ScoreResponse]:
        """
        Stage 1: cheap screening on title/abstract.
        """
        prompt = prompt_service.render_prompt("scoring.jinja2", paper=paper, user_profile=user_profile)
        content = await self._chat(TASK_STAGE1, prompt, json_mode=True, temperature=0.0, paper_id=paper.id)
        if content is None:
            return None
        try:
            data = extract_json_object(content)
            return ScoreResponse(
                score=_clamp_int(data.get("score")),
                relevance=_clamp_int(data.get("relevance"), 0, 5),
                novelty=_clamp_int(data.get("novelty"), 0, 5),
                clarity=_clamp_int(data.get("clarity"), 0, 5),
                risk_flags=[str(x) for x in (data.get("risk_flags") or [])],
                one_line_reason=str(data.get("one_line_reason") or ""),
            )
        except Exception as e:
            print(f"Error parsing stage-1 score for {paper.id}: {e}")
            return None

    # ------------------------------------------------------------------ stage 2
    async def score_paper_stage2(self, paper: Paper, user_profile: str,
                                 text_snippet: Optional[str]) -> Optional[Stage2ScoreResponse]:
        """
        Stage 2: careful review with a stronger model, given an excerpt of the paper body.
        """
        authors = paper.authors_list
        authors_str = ", ".join(authors[:8]) + (f" (+{len(authors) - 8} more)" if len(authors) > 8 else "")
        snippet = sanitize_text(text_snippet) if text_snippet else None
        limit = settings.STAGE2_TEXT_CHAR_LIMIT
        if snippet and len(snippet) > limit:
            snippet = snippet[:limit]
        prompt = prompt_service.render_prompt(
            "scoring_stage2.jinja2",
            paper=paper, user_profile=user_profile, authors_str=authors_str,
            text_snippet=snippet, score_threshold=self.config.score_threshold,
        )
        content = await self._chat(TASK_STAGE2, prompt, json_mode=True, temperature=0.0, paper_id=paper.id)
        if content is None:
            return None
        try:
            data = extract_json_object(content)
            return Stage2ScoreResponse(
                score=_clamp_int(data.get("score")),
                relevance=_clamp_int(data.get("relevance"), 0, 5),
                novelty=_clamp_int(data.get("novelty"), 0, 5),
                quality=_clamp_int(data.get("quality"), 0, 5),
                clarity=_clamp_int(data.get("clarity"), 0, 5),
                risk_flags=[str(x) for x in (data.get("risk_flags") or [])],
                strengths=[str(x) for x in (data.get("strengths") or [])],
                weaknesses=[str(x) for x in (data.get("weaknesses") or [])],
                one_line_reason=str(data.get("one_line_reason") or ""),
            )
        except Exception as e:
            print(f"Error parsing stage-2 score for {paper.id}: {e}")
            return None

    # ------------------------------------------------------------------ summary
    async def summarize_paper(self, paper: Paper, full_text: Optional[str] = None,
                              user_profile: Optional[str] = None) -> Optional[str]:
        """
        Generate a structured summary for a high-scoring paper.
        """
        if full_text:
            full_text = sanitize_text(full_text)

        # Truncate to keep the prompt under the model's context window.
        if full_text and len(full_text) > SUMMARY_FULL_TEXT_CHAR_LIMIT:
            print(
                f"  - Truncating full_text for {paper.id} from {len(full_text)} "
                f"to {SUMMARY_FULL_TEXT_CHAR_LIMIT} chars to fit context window."
            )
            full_text = full_text[:SUMMARY_FULL_TEXT_CHAR_LIMIT]

        prompt = prompt_service.render_prompt(
            "summarization.jinja2",
            paper=paper,
            full_text=full_text,
            language=settings.SUMMARY_LANGUAGE,
            user_profile=user_profile,
        )
        return await self._chat(TASK_SUMMARY, prompt, json_mode=False, temperature=0.3, paper_id=paper.id)

    # ------------------------------------------------------------------ reports
    async def generate_report(self, prompt: str, ref: Optional[str] = None) -> Optional[str]:
        """Free-form markdown report (daily / weekly / monthly trend summary)."""
        return await self._chat(TASK_REPORT, prompt, json_mode=False, temperature=0.4, paper_id=ref)

    # ------------------------------------------------------------------ affiliation
    async def extract_affiliations(self, paper: Paper, full_text: str) -> Optional[AffiliationResponse]:
        """
        Extract affiliations from paper text.
        We use the first ~4000 chars of full text as it usually contains the header/affiliations.
        """
        if full_text:
            full_text = sanitize_text(full_text) or ""

        text_snippet = full_text[:4000]
        prompt = prompt_service.render_prompt("affiliation.jinja2", text_snippet=text_snippet)
        content = await self._chat(TASK_AFFILIATION, prompt, json_mode=True, temperature=0.0, paper_id=paper.id)
        if content is None:
            return None
        try:
            data = extract_json_object(content)
            return AffiliationResponse(
                affiliations=[str(x) for x in (data.get("affiliations") or [])],
                main_company=data.get("main_company"),
                main_university=data.get("main_university"),
                main_affiliation=data.get("main_affiliation"),
            )
        except Exception as e:
            print(f"Error parsing affiliations for {paper.id}: {e}")
            return None
