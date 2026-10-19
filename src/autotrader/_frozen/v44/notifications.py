from __future__ import annotations

import httpx

from autotrader.config import Settings


class NotificationEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def notify(self, title: str, body: str) -> None:
        if not self.settings.telegram_bot_token or not self.settings.telegram_chat_id:
            return
        safe_body = body.replace(self.settings.telegram_bot_token.get_secret_value(), "[redacted]")
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"https://api.telegram.org/bot{self.settings.telegram_bot_token.get_secret_value()}/sendMessage",
                json={"chat_id": self.settings.telegram_chat_id, "text": f"{title}\n{safe_body}"},
            )

