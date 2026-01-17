import httpx
from abc import ABC, abstractmethod
from typing import Optional
from src.config import settings

class Notifier(ABC):
    @abstractmethod
    async def send_message(self, message: str) -> bool:
        pass

class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    async def send_message(self, message: str) -> bool:
        async with httpx.AsyncClient() as client:
            try:
                payload = {
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                }
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                return True
            except Exception as e:
                print(f"Telegram notification failed: {e}")
                return False

class PushoverNotifier(Notifier):
    def __init__(self, user_key: str, api_token: str):
        self.user_key = user_key
        self.api_token = api_token
        self.api_url = "https://api.pushover.net/1/messages.json"

    async def send_message(self, message: str) -> bool:
        async with httpx.AsyncClient() as client:
            try:
                payload = {
                    "token": self.api_token,
                    "user": self.user_key,
                    "message": message,
                    "html": 0 # Use 1 if we change to HTML, but markdown is generally better supported if formatted right, Pushover has limited markdown
                }
                response = await client.post(self.api_url, data=payload)
                response.raise_for_status()
                return True
            except Exception as e:
                print(f"Pushover notification failed: {e}")
                return False

def get_notifier() -> Optional[Notifier]:
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID:
        return TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
    if settings.PUSHOVER_USER_KEY and settings.PUSHOVER_API_TOKEN:
        return PushoverNotifier(settings.PUSHOVER_USER_KEY, settings.PUSHOVER_API_TOKEN)
    return None
