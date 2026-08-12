from __future__ import annotations

import requests

from .config import settings

API_BASE = "https://api.telegram.org/bot{token}/"


class TelegramClient:
    def __init__(self) -> None:
        self.base = API_BASE.format(token=settings.telegram_bot_token)
        self.chat_id = settings.telegram_chat_id

    def send_message(self, text: str) -> bool:
        resp = requests.post(
            self.base + "sendMessage",
            json={"chat_id": self.chat_id, "text": text},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[telegram] send failed: HTTP {resp.status_code}: {resp.text[:300]}")
            return False
        return True