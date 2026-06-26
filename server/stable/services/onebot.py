from __future__ import annotations

import requests
from django.conf import settings


class OneBotRequestError(RuntimeError):
    pass


def _sanitize_error(message: str) -> str:
    token = getattr(settings, "ONEBOT_ACCESS_TOKEN", None)
    if token:
        return message.replace(str(token), "[redacted]")
    return message


def _validate_onebot_response(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise OneBotRequestError("OneBot returned a non-object response")
    status = str(payload.get("status", "")).lower()
    retcode = payload.get("retcode")
    if status and status != "ok":
        raise OneBotRequestError(_sanitize_error(f"OneBot status={status}: {payload}"))
    if retcode not in (None, 0, "0"):
        raise OneBotRequestError(_sanitize_error(f"OneBot retcode={retcode}: {payload}"))
    return payload


class BotPusher:
    def __init__(self) -> None:
        self.base_url = settings.ONEBOT_BASE_URL.rstrip("/")
        self.headers = {}
        if settings.ONEBOT_ACCESS_TOKEN:
            self.headers["Authorization"] = f"Bearer {settings.ONEBOT_ACCESS_TOKEN}"

    def is_online(self) -> tuple[bool, str]:
        try:
            response = requests.get(
                f"{self.base_url}/get_status",
                headers=self.headers,
                timeout=getattr(settings, "ONEBOT_TIMEOUT_SECONDS", 30),
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                detail = "OneBot status check returned invalid JSON"
                if response.text:
                    detail = f"{detail}: {_sanitize_error(response.text[:500])}"
                raise OneBotRequestError(detail) from exc
            payload = _validate_onebot_response(payload)
        except requests.RequestException as exc:
            detail = _sanitize_error(str(exc))
            response = getattr(exc, "response", None)
            if response is not None and response.text:
                detail = f"{detail}: {_sanitize_error(response.text[:500])}"
            return False, f"onebot_status_check_failed: {detail}"
        except OneBotRequestError as exc:
            return False, f"onebot_status_check_failed: {_sanitize_error(str(exc))}"

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if data.get("online") is True:
            return True, ""
        return False, f"onebot_offline: {data}"

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
        try:
            response = requests.post(
                f"{self.base_url}/send_group_msg",
                json={"group_id": group_id, "message": message},
                headers=self.headers,
                timeout=getattr(settings, "ONEBOT_TIMEOUT_SECONDS", 30),
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                detail = "OneBot returned invalid JSON"
                if response.text:
                    detail = f"{detail}: {_sanitize_error(response.text[:500])}"
                raise OneBotRequestError(detail) from exc
            return _validate_onebot_response(payload)
        except requests.RequestException as exc:
            detail = _sanitize_error(str(exc))
            response = getattr(exc, "response", None)
            if response is not None and response.text:
                detail = f"{detail}: {_sanitize_error(response.text[:500])}"
            raise OneBotRequestError(detail) from exc
