from __future__ import annotations

import requests
from django.conf import settings


class BotPusher:
    def __init__(self) -> None:
        self.base_url = settings.ONEBOT_BASE_URL.rstrip("/")
        self.headers = {}
        if settings.ONEBOT_ACCESS_TOKEN:
            self.headers["Authorization"] = f"Bearer {settings.ONEBOT_ACCESS_TOKEN}"

    def send_group_message(self, group_id: str, text: str, image_url: str | None = None) -> dict:
        if image_url:
            try:
                return self._post_message(
                    group_id,
                    [
                        {"type": "text", "data": {"text": text + "\n"}},
                        {"type": "image", "data": {"file": image_url}},
                    ],
                )
            except Exception:
                return self._post_message(group_id, [{"type": "text", "data": {"text": text}}])
        return self._post_message(group_id, [{"type": "text", "data": {"text": text}}])

    def _post_message(self, group_id: str, message: list[dict]) -> dict:
        response = requests.post(
            f"{self.base_url}/send_group_msg",
            json={"group_id": group_id, "message": message},
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
