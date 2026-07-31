"""Prepare a strict lifecycle shadow-enrollment artifact without DB writes."""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from stable.services.race_event_lifecycle_enrollment import (
    EnrollmentError,
    build_enrollment_artifacts,
    write_enrollment_artifacts,
)


class Command(BaseCommand):
    help = "只读生成 lifecycle shadow enrollment manifest v2"

    def add_arguments(self, parser):
        parser.add_argument("--event-ids", nargs="*", required=True)
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--approved-commit", required=True)
        parser.add_argument(
            "--allowed-us-zone",
            action="append",
            default=[],
            metavar="EVENT_ID=AMERICA/ZONE",
        )

    def handle(self, **options):
        try:
            event_ids = self._parse_event_ids(options["event_ids"])
            zones = self._parse_us_zones(options["allowed_us_zone"])
            manifest, summary = build_enrollment_artifacts(
                event_ids=event_ids,
                approved_commit=options["approved_commit"],
                allowed_us_zones=zones,
            )
            write_enrollment_artifacts(
                options["output_dir"],
                manifest_bytes=manifest,
                summary_bytes=summary,
            )
        except (EnrollmentError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"已生成 shadow enrollment artifact：{len(event_ids)} 场；"
                f"目录={options['output_dir']}"
            )
        )

    @staticmethod
    def _parse_event_ids(values: list[str]) -> list[int]:
        parsed: list[int] = []
        for value in values:
            try:
                event_id = int(value)
            except (TypeError, ValueError) as exc:
                raise EnrollmentError(f"event ID 不是整数: {value!r}") from exc
            parsed.append(event_id)
        return parsed

    @staticmethod
    def _parse_us_zones(values: list[str]) -> dict[int, list[str]]:
        result: defaultdict[int, list[str]] = defaultdict(list)
        for value in values:
            if not isinstance(value, str) or "=" not in value:
                raise EnrollmentError(
                    f"--allowed-us-zone 格式应为 EVENT_ID=America/Zone: {value!r}"
                )
            event_text, zone = value.split("=", 1)
            try:
                event_id = int(event_text)
            except ValueError as exc:
                raise EnrollmentError(f"US zone event ID 非法: {event_text!r}") from exc
            result[event_id].append(zone)
        return dict(result)
