from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.publish_ready_backlog import (
    apply_publish_ready_backlog_manifest,
    build_publish_ready_backlog_manifest,
    seal_publish_ready_backlog_review,
)


def _read_json(path_value: str) -> dict:
    path = Path(path_value)
    if not path.is_file():
        raise ValueError(f"文件不存在：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_immutable(path_value: str, payload: dict) -> None:
    path = Path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    except FileExistsError as exc:
        raise ValueError(f"拒绝覆盖已存在的 manifest：{path}") from exc


class Command(BaseCommand):
    help = "生成、审核或按 SHA 应用历史 publish_ready 积压清单；apply 不直接公开或创建 QQ delivery。"

    def add_arguments(self, parser):
        parser.add_argument("--output", default="")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--seal-review", default="")
        parser.add_argument("--decisions", default="")
        parser.add_argument("--reviewer", default="")
        parser.add_argument("--apply-manifest", default="")
        parser.add_argument("--expected-sha256", default="")
        parser.add_argument("--confirm-apply", action="store_true")

    def handle(self, *args, **options):
        try:
            if options["apply_manifest"]:
                if not options["confirm_apply"]:
                    raise ValueError("apply 必须显式提供 --confirm-apply")
                expected_sha = str(options["expected_sha256"] or "").strip().lower()
                if len(expected_sha) != 64:
                    raise ValueError("apply 必须提供 64 位 --expected-sha256")
                result = apply_publish_ready_backlog_manifest(
                    _read_json(options["apply_manifest"]),
                    expected_sha256=expected_sha,
                    limit=options["limit"],
                )
                self.stdout.write(json.dumps({"mode": "apply", **result}, ensure_ascii=False, sort_keys=True))
                return

            if options["seal_review"]:
                if not options["output"] or not options["decisions"]:
                    raise ValueError("seal-review 必须提供 --decisions、--reviewer 和 --output")
                reviewed = seal_publish_ready_backlog_review(
                    _read_json(options["seal_review"]),
                    decisions=_read_json(options["decisions"]),
                    reviewer=options["reviewer"],
                )
                _write_immutable(options["output"], reviewed)
                self.stdout.write(
                    json.dumps(
                        {
                            "mode": "seal-review",
                            "output": options["output"],
                            "manifest_sha256": reviewed["manifest_sha256"],
                            "article_count": len(reviewed["articles"]),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
                return

            manifest = build_publish_ready_backlog_manifest(limit=options["limit"])
            if options["output"]:
                _write_immutable(options["output"], manifest)
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "output": options["output"],
                        "manifest_sha256": manifest["manifest_sha256"],
                        "article_count": len(manifest["articles"]),
                        "database_writes": 0,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc
