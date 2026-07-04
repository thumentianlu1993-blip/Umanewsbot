from __future__ import annotations

import re
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand
from django.utils import timezone

from stable.models import TaskExecutionLog, TaskStatus


FIELD_HINTS = {
    "status": re.compile(r"(live|running|in[- ]?play|race status|正在|进行中|出走状态)", re.I),
    "scratch": re.compile(r"(scratch|scratched|withdrawn|non[- ]?runner|退赛|取消出走)", re.I),
    "odds": re.compile(r"(odds|win odds|popular|favourite|赔率|热门)", re.I),
    "result": re.compile(r"(result|finish|placing|margin|赛果|名次|马身)", re.I),
}


class Command(BaseCommand):
    help = "只读调研指定 URL 是否存在赛中/动态字段，不写入 RaceEvent。"

    def add_arguments(self, parser):
        parser.add_argument("--url", action="append", required=True, help="要调研的公开页面或接口，可重复。")
        parser.add_argument("--timeout", type=int, default=15, help="请求超时时间。")

    def handle(self, *args, **options):
        started_at = timezone.now()
        samples = []
        failures = []
        for url in options["url"]:
            try:
                request = Request(url, headers={"User-Agent": "UmaFansBot/1.0"})
                with urlopen(request, timeout=options["timeout"]) as response:
                    body = response.read(60000).decode("utf-8", errors="ignore")
                hints = []
                for name, pattern in FIELD_HINTS.items():
                    match = pattern.search(body)
                    if match:
                        start = max(match.start() - 80, 0)
                        end = min(match.end() + 80, len(body))
                        hints.append({"field": name, "sample": body[start:end]})
                samples.append({"url": url, "status": "success", "hints": hints})
            except (OSError, URLError, UnicodeDecodeError) as exc:
                failures.append({"url": url, "error": str(exc)})
        status = TaskStatus.SUCCESS if samples else TaskStatus.FAILED
        TaskExecutionLog.objects.create(
            task_name="research_live_race_fields",
            status=status,
            payload={"samples": samples, "failures": failures},
            detail=f"只读赛中字段调研完成：success={len(samples)} failure={len(failures)}",
            started_at=started_at,
            finished_at=timezone.now(),
        )
        self.stdout.write(f"调研完成：success={len(samples)} failure={len(failures)}")
        for sample in samples:
            self.stdout.write(f"- {sample['url']} hints={len(sample['hints'])}")
        for failure in failures:
            self.stdout.write(f"- {failure['url']} failed={failure['error']}")
