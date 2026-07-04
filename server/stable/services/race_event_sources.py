from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

from django.core.management.base import CommandError


RACE_EVENT_SOURCE_CONFIGS: dict[str, dict] = {
    "json": {
        "label": "Generic JSON",
        "description": "从本地 JSON 文件或返回 JSON 的 URL 读取赛事候选资料。",
    },
    "jra": {
        "label": "JRA official",
        "description": "日本官方赛事资料入口占位；第一版通过 payload 文件或后续指定 URL 接入。",
    },
    "hkjc": {
        "label": "HKJC official",
        "description": "香港官方赛事资料入口占位；第一版通过 payload 文件或后续指定 URL 接入。",
    },
    "racing_post": {
        "label": "Racing Post",
        "description": "英国/国际赛事资料入口占位；第一版通过 payload 文件或后续指定 URL 接入。",
    },
}


def read_candidate_payload(*, source_key: str, payload_path: str = "", url: str = "", timeout: int = 20) -> dict:
    if source_key not in RACE_EVENT_SOURCE_CONFIGS:
        raise CommandError(f"未知赛事候选来源：{source_key}")
    if payload_path:
        path = Path(payload_path).expanduser()
        if not path.exists():
            raise CommandError(f"候选 JSON 文件不存在：{path}")
        return json.loads(path.read_text(encoding="utf-8-sig"))
    if url:
        request = Request(url, headers={"User-Agent": "UmaFansBot/1.0"})
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
        return json.loads(body)
    raise CommandError("必须提供 --payload-file 或 --url。")


def normalize_candidate_modules(payload: dict) -> dict[str, dict]:
    if "modules" in payload and isinstance(payload["modules"], dict):
        payload = payload["modules"]
    return {str(key): value for key, value in payload.items() if isinstance(value, (dict, list))}
