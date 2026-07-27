from __future__ import annotations

import importlib
import json
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import RaceEvent
from stable.services.race_live_racecard_sync import (
    get_normalized_accepted_race_names,
)
from stable.services.race_reference_sources import (
    SOURCE_REGISTRY,
    canonical_json_bytes,
    canonical_json_sha256,
    get_reference_parser_contract,
    validate_reference_manifest,
    validate_source_identity,
)


PARSER_BY_SOURCE = {
    source_key: {
        "name": get_reference_parser_contract(source_key)["name"],
        "version": get_reference_parser_contract(source_key)["version"],
    }
    for source_key in SOURCE_REGISTRY
}
TARGET_FIELDS = {"event_id", "provider_event_key", "source_url"}
SNAPSHOT_FIELDS = (
    "event_id",
    "slug",
    "country_region",
    "local_date",
    "timezone_name",
    "racecourse",
    "original_name",
    "normalized_accepted_race_names",
    "status",
)


def _load_verified_parser_module(
    source_key: str,
    *,
    manifest_parser: object,
):
    contract = get_reference_parser_contract(source_key)
    expected_identity = {
        "name": contract["name"],
        "version": contract["version"],
    }
    if manifest_parser != expected_identity:
        raise CommandError(
            "manifest parser identity 与冻结 source contract 不一致"
        )
    try:
        parser_module = importlib.import_module(contract["module"])
    except ImportError as exc:
        raise CommandError(
            f"无法导入冻结 parser module：{contract['module']}"
        ) from exc
    actual_identity = {
        "name": getattr(parser_module, "PARSER_NAME", None),
        "version": getattr(parser_module, "PARSER_VERSION", None),
    }
    if actual_identity != expected_identity:
        raise CommandError(
            "已加载 parser module identity 与冻结 source contract 不一致"
        )
    if not callable(getattr(parser_module, "parse_reference_page", None)):
        raise CommandError("已加载 parser module 缺少 parse_reference_page")
    return parser_module, expected_identity


def _strict_json_bytes(path: Path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CommandError(f"无法读取 JSON 文件：{path}: {exc}") from exc

    def pairs_hook(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"重复 JSON 字段：{key}")
            value[key] = item
        return value

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"非法 JSON 常量：{token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CommandError(f"JSON 文件无效：{path}: {exc}") from exc


def _atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise CommandError(f"拒绝写入符号链接：{path}")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise CommandError(f"拒绝覆盖已存在的输出：{path}") from exc
        os.unlink(temporary)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _reject_public_output(path: Path) -> None:
    resolved = path.resolve(strict=False)
    for configured in (
        getattr(settings, "STATIC_ROOT", None),
        getattr(settings, "MEDIA_ROOT", None),
    ):
        if not configured:
            continue
        public_root = Path(configured).resolve(strict=False)
        if resolved == public_root or public_root in resolved.parents:
            raise CommandError("内部参考产物不得写入公开 static/media 目录")


class Command(BaseCommand):
    help = "从显式目标文件构建赛后内部参考 manifest（只读数据库）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-key",
            required=True,
            choices=tuple(PARSER_BY_SOURCE),
        )
        parser.add_argument("--targets-file", required=True)
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        source_key = options["source_key"]
        _parser_module, parser_identity = _load_verified_parser_module(
            source_key,
            manifest_parser=PARSER_BY_SOURCE[source_key],
        )
        targets_path = Path(options["targets_file"])
        targets = _strict_json_bytes(targets_path)
        if not isinstance(targets, list) or not 1 <= len(targets) <= 100:
            raise CommandError("targets 必须是包含 1..100 项的 JSON 数组")

        event_ids: list[int] = []
        provider_keys: set[str] = set()
        normalized_targets: list[dict] = []
        for index, target in enumerate(targets):
            if not isinstance(target, dict) or set(target) != TARGET_FIELDS:
                raise CommandError(f"targets[{index}] 字段不符合精确合同")
            event_id = target["event_id"]
            if (
                isinstance(event_id, bool)
                or not isinstance(event_id, int)
                or event_id <= 0
                or event_id in event_ids
            ):
                raise CommandError("event_id 必须为不重复的正整数")
            provider_key = target["provider_event_key"]
            if provider_key in provider_keys:
                raise CommandError("provider_event_key 不得重复")
            try:
                validate_source_identity(
                    source_key=source_key,
                    country_region=SOURCE_REGISTRY[source_key]["region"],
                    provider_event_key=provider_key,
                    source_url=target["source_url"],
                )
            except ValidationError as exc:
                raise CommandError(
                    f"targets[{index}] 来源身份无效：{'; '.join(exc.messages)}"
                ) from exc
            event_ids.append(event_id)
            provider_keys.add(provider_key)
            normalized_targets.append(target)

        events = (
            RaceEvent.objects.filter(pk__in=event_ids)
            .select_related("race_series", "major_race_event")
            .prefetch_related("aliases", "race_series__names")
        )
        events_by_id = {event.pk: event for event in events}
        if set(events_by_id) != set(event_ids):
            missing = sorted(set(event_ids) - set(events_by_id))
            raise CommandError(f"赛事不存在：{missing}")

        manifest_events = []
        for target in normalized_targets:
            event = events_by_id[target["event_id"]]
            snapshot = {
                "event_id": event.pk,
                "slug": event.slug,
                "country_region": event.country_region,
                "local_date": (
                    event.local_date.isoformat() if event.local_date else None
                ),
                "timezone_name": event.timezone_name,
                "racecourse": event.racecourse,
                "original_name": event.original_name,
                "normalized_accepted_race_names": sorted(
                    get_normalized_accepted_race_names(event)
                ),
                "status": event.status,
            }
            manifest_events.append(
                {
                    **snapshot,
                    "provider_event_key": target["provider_event_key"],
                    "source_url": target["source_url"],
                    "event_snapshot_sha256": canonical_json_sha256(snapshot),
                }
            )

        manifest = {
            "schema_version": 1,
            "purpose": "internal_reference_post_race",
            "source_key": source_key,
            "reference_schema_version": 1,
            "parser": parser_identity,
            "generated_at": timezone.now().isoformat(),
            "events": manifest_events,
        }
        try:
            validate_reference_manifest(manifest)
        except ValidationError as exc:
            raise CommandError(
                f"manifest 构建失败：{'; '.join(exc.messages)}"
            ) from exc
        body = canonical_json_bytes(manifest)
        output = Path(options["output"])
        _reject_public_output(output)
        if output.exists() or output.is_symlink():
            raise CommandError("output 必须是不存在的新文件")
        _atomic_write(output, body)
        digest = canonical_json_sha256(manifest)
        self.stdout.write(
            self.style.SUCCESS(
                f"manifest 已生成：events={len(manifest_events)} sha256={digest}"
            )
        )
