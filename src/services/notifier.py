import httpx
from abc import ABC, abstractmethod
from typing import Optional, List
from src.config import settings

class Notifier(ABC):
    @abstractmethod
    async def send_message(self, message: str) -> bool:
        pass

    async def send_messages(self, messages: List[str]) -> bool:
        """Send multiple messages sequentially. Override for batch-aware implementations."""
        all_ok = True
        for msg in messages:
            ok = await self.send_message(msg)
            if not ok:
                all_ok = False
        return all_ok

class LarkNotifier(Notifier):
    MAX_PAPERS_PER_MESSAGE = 10  # Lark webhook has content size limits

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    async def send_message(self, message: str) -> bool:
        async with httpx.AsyncClient() as client:
            try:
                lines = message.strip().split("\n")
                content_lines = []
                for line in lines:
                    if not line.strip():
                        continue
                    content_lines.append([{"tag": "text", "text": line + "\n"}])

                payload = {
                    "msg_type": "post",
                    "content": {
                        "post": {
                            "zh_cn": {
                                "title": "📄 Paper Agent",
                                "content": content_lines
                            }
                        }
                    }
                }
                response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()
                return True
            except Exception as e:
                print(f"Lark notification failed: {e}")
                return False

def get_notifier() -> Optional[Notifier]:
    if settings.LARK_WEBHOOK_URL:
        return LarkNotifier(settings.LARK_WEBHOOK_URL)
    return None
