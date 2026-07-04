from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import RaceEvent, RaceEventModule, TaskExecutionLog, TaskStatus
from stable.services.race_event_sources import RACE_EVENT_SOURCE_CONFIGS, normalize_candidate_modules, read_candidate_payload
from stable.services.race_events import save_data_candidate


class Command(BaseCommand):
    help = "从指定来源拉取年度赛事候选资料并写入候选池，不覆盖公开字段。"

    def add_arguments(self, parser):
        parser.add_argument("--event-id", type=int, help="RaceEvent ID。")
        parser.add_argument("--year", type=int, help="年度。与 --slug 配合定位赛事。")
        parser.add_argument("--slug", help="赛事 slug。与 --year 配合定位赛事。")
        parser.add_argument("--source", choices=sorted(RACE_EVENT_SOURCE_CONFIGS), default="json", help="候选来源 key。")
        parser.add_argument("--payload-file", help="本地候选 JSON 文件。")
        parser.add_argument("--url", help="返回候选 JSON 的来源 URL。")
        parser.add_argument("--confidence", type=int, default=80, help="候选默认置信度。")

    def _get_event(self, options) -> RaceEvent:
        if options.get("event_id"):
            return RaceEvent.objects.get(pk=options["event_id"])
        if options.get("year") and options.get("slug"):
            return RaceEvent.objects.get(year=options["year"], slug=options["slug"])
        raise CommandError("必须提供 --event-id，或同时提供 --year 与 --slug。")

    def handle(self, *args, **options):
        started_at = timezone.now()
        event = self._get_event(options)
        source_key = options["source"]
        try:
            payload = read_candidate_payload(
                source_key=source_key,
                payload_path=options.get("payload_file") or "",
                url=options.get("url") or "",
            )
            modules = normalize_candidate_modules(payload)
            created = 0
            for module, module_payload in modules.items():
                if module not in RaceEventModule.values:
                    self.stdout.write(f"跳过未知模块：{module}")
                    continue
                save_data_candidate(
                    event=event,
                    module=module,
                    source_name=source_key,
                    source_url=options.get("url") or "",
                    candidate_payload=module_payload,
                    raw_payload=payload,
                    confidence=options["confidence"],
                )
                created += 1
        except Exception as exc:
            TaskExecutionLog.objects.create(
                task_name="fetch_race_event_candidates",
                status=TaskStatus.FAILED,
                payload={"event_id": event.pk, "source": source_key},
                detail=str(exc),
                started_at=started_at,
                finished_at=timezone.now(),
            )
            raise
        TaskExecutionLog.objects.create(
            task_name="fetch_race_event_candidates",
            status=TaskStatus.SUCCESS,
            payload={"event_id": event.pk, "source": source_key, "created": created},
            detail=f"赛事候选抓取完成：{event} source={source_key} created={created}",
            started_at=started_at,
            finished_at=timezone.now(),
        )
        self.stdout.write(self.style.SUCCESS(f"候选资料已写入：event={event.pk} created={created}"))
