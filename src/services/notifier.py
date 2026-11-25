import asyncio

import httpx
from abc import ABC, abstractmethod
from typing import Optional, List, Union, Tuple
from src.config import settings

class Notifier(ABC):
    @abstractmethod
    async def send_message(self, message: str, title: Optional[str] = None) -> bool:
        pass

    async def send_messages(self, messages: List[Union[str, Tuple[str, str]]]) -> bool:
        """
        Send multiple messages sequentially. Each item is either a plain string
        or a (title, text) tuple. Override for batch-aware implementations.
        """
        all_ok = True
        for item in messages:
            if isinstance(item, tuple):
                title, msg = item
            else:
                title, msg = None, item
            ok = await self.send_message(msg, title=title)
            if not ok:
                all_ok = False
        return all_ok

class LarkNotifier(Notifier):
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    DEFAULT_TITLE = "📄 Paper Agent"

    RETRY_DELAYS = (2, 10, 30)

    async def send_message(self, message: str, title: Optional[str] = None) -> bool:
        lines = [line for line in message.strip().split("\n") if line.strip()]
        payload = {
            "msg_type": "post",
            "content": {"post": {"zh_cn": {
                "title": title or self.DEFAULT_TITLE,
                "content": [[{"tag": "text", "text": line + "\n"}] for line in lines],
            }}},
        }
        error = None
        for delay in (0,) + self.RETRY_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()
                # Lark answers HTTP 200 with a non-zero "code" when it rejects a message
                # (too large, rate limited, keyword or IP check failed).
                body = response.json() if response.content else {}
                code = body.get("code", body.get("StatusCode", 0)) if isinstance(body, dict) else 0
                if not code:
                    return True
                error = f"Lark code {code}: {body.get('msg') or body.get('StatusMessage')}"
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
        print(f"Lark notification failed: {error}")
        return False


def get_notifier() -> Optional[Notifier]:
    if settings.LARK_WEBHOOK_URL:
        return LarkNotifier(settings.LARK_WEBHOOK_URL)
    return None


async def alert_arxiv_failure(context: str, error: Exception) -> bool:
    """Push an arXiv-API outage alert to Lark. Returns False when no notifier is configured or the push failed."""
    notifier = get_notifier()
    if not notifier:
        return False
    return await notifier.send_message(
        f"{context} failed: the arXiv API is not responding properly.\n"
        f"Error: {error}\n"
        f"Papers already waiting in the database are still processed; new ones will be picked up by the next "
        f"successful fetch. Check https://status.arxiv.org if this persists.",
        title="⚠️ arXiv API error",
    )
