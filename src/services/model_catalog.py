"""
OpenRouter model catalog: ids, display names, list prices, context length,
and whether JSON response_format is supported. Cached in-process.

Used for:
  - the model picker in the Settings page
  - cost estimation (list price x expected tokens)
  - fallback cost computation when the provider does not report `usage.cost`
  - deciding whether to request response_format=json_object for a model
"""
import time
import re
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

import httpx


CATALOG_TTL_SECONDS = 6 * 3600
# The catalog (ids + list prices) always comes from OpenRouter's public endpoint — it needs no key
# and is the only source with pricing. For non-OpenRouter providers it is used for pricing only.
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# A small curated shortlist surfaced at the top of the picker (only those present in the catalog).
RECOMMENDED_IDS = [
    "openai/gpt-4o-mini",
    "openai/gpt-5-mini",
    "openai/gpt-5.4-mini",
    "google/gemini-3.7-flash",
    "google/gemini-2.5-flash",
    "deepseek/deepseek-v4-flash",
    "anthropic/claude-haiku-4.5",
    "anthropic/claude-sonnet-5",
    "openai/gpt-5.4",
    "x-ai/grok-4.3",
]


@dataclass
class ModelInfo:
    id: str
    name: str
    prompt_price_per_m: float       # USD per 1M prompt tokens
    completion_price_per_m: float   # USD per 1M completion tokens
    context_length: Optional[int]
    supports_json: bool
    recommended: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class ModelCatalog:
    def __init__(self):
        self._models: Dict[str, ModelInfo] = {}
        self._fetched_at: float = 0.0
        self._last_error: Optional[str] = None

    @property
    def models_url(self) -> str:
        return OPENROUTER_MODELS_URL

    def _is_fresh(self) -> bool:
        return bool(self._models) and (time.time() - self._fetched_at) < CATALOG_TTL_SECONDS

    async def refresh(self, force: bool = False) -> bool:
        if self._is_fresh() and not force:
            return True
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(self.models_url)
                resp.raise_for_status()
                data = resp.json().get("data", [])
        except Exception as e:
            self._last_error = str(e)
            return False

        parsed: Dict[str, ModelInfo] = {}
        for m in data:
            mid = m.get("id")
            if not mid:
                continue
            pricing = m.get("pricing") or {}
            try:
                p_in = float(pricing.get("prompt") or 0) * 1_000_000
                p_out = float(pricing.get("completion") or 0) * 1_000_000
            except (TypeError, ValueError):
                p_in, p_out = 0.0, 0.0
            supported = m.get("supported_parameters") or []
            parsed[mid] = ModelInfo(
                id=mid,
                name=m.get("name") or mid,
                prompt_price_per_m=round(p_in, 4),
                completion_price_per_m=round(p_out, 4),
                context_length=m.get("context_length"),
                supports_json=("response_format" in supported) or ("structured_outputs" in supported),
                recommended=mid in RECOMMENDED_IDS,
            )
        if parsed:
            self._models = parsed
            self._fetched_at = time.time()
            self._last_error = None
            return True
        return False

    def get(self, model_id: str) -> Optional[ModelInfo]:
        return self._models.get(model_id)

    def get_for_pricing(self, model_id: str) -> Optional[ModelInfo]:
        """
        Price lookup tolerant of provider naming: exact id first, then 'openai/<id>'
        (legacy OpenAI deployments use bare ids like 'gpt-4o-mini').
        """
        if not model_id:
            return None
        info = self._models.get(model_id)
        if info is None and "/" not in model_id:
            info = self._models.get(f"openai/{model_id}")
        return info

    def supports_json(self, model_id: str) -> bool:
        """True if known to support JSON mode; also True when unknown (optimistic, caller retries on failure)."""
        info = self._models.get(model_id)
        return True if info is None else info.supports_json

    def estimate_cost(self, model_id: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
        info = self.get_for_pricing(model_id)
        if not info:
            return None
        return (prompt_tokens * info.prompt_price_per_m + completion_tokens * info.completion_price_per_m) / 1_000_000

    def list(self, q: Optional[str] = None, limit: Optional[int] = None) -> List[ModelInfo]:
        items = list(self._models.values())
        if q:
            terms = [t for t in re.split(r"\s+", q.strip().lower()) if t]
            items = [m for m in items if all(t in m.id.lower() or t in m.name.lower() for t in terms)]
        # recommended first, then alphabetical
        items.sort(key=lambda m: (not m.recommended, m.id))
        return items[:limit] if limit else items

    def status(self) -> dict:
        return {
            "count": len(self._models),
            "fetched_at": self._fetched_at or None,
            "fresh": self._is_fresh(),
            "last_error": self._last_error,
            "source": self.models_url,
        }


model_catalog = ModelCatalog()
