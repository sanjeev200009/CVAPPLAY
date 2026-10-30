from __future__ import annotations

import requests

from .config import settings

API_BASE = "https://api.telegram.org/bot{token}/"


class TelegramClient:
    def __init__(self) -> None:
        self.base = API_BASE.format(token=settings.telegram_bot_token)
        self.chat_id = settings.telegram_chat_id

    def send_message(self, text: str, reply_to_message_id: int | None = None) -> bool:
        payload = {"chat_id": self.chat_id, "text": text}
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        try:
            resp = requests.post(
                self.base + "sendMessage",
                json=payload,
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[telegram] send failed: HTTP {resp.status_code}: {resp.text[:300]}")
                return False
            return True
        except Exception as exc:
            print(f"[telegram] send error: {exc}")
            return False

    def reply_message(self, text: str, reply_to_message_id: int) -> bool:
        return self.send_message(text=text, reply_to_message_id=reply_to_message_id)

    def get_updates(self, offset: int | None = None, timeout: int = 15) -> list[dict]:
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        resp = requests.get(
            self.base + "getUpdates",
            params=params,
            timeout=timeout + 10,
        )
        if resp.status_code == 200:
            return resp.json().get("result", [])
        return []