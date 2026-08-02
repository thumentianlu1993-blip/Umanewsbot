from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.services.news_body_history import _SHA256_RE, verify_batch


class Command(BaseCommand):
    help = "写后验证：SHA 信任链交叉校验 + 逐字段核对。"

    def add_arguments(self, parser):
        parser.add_argument("--receipt", required=True)
        parser.add_argument("--receipt-sha256", required=True)
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--rollback-dir", required=True)

    def handle(self, *args, **options):
        receipt_path = Path(options["receipt"])
        receipt_sha256 = (options["receipt_sha256"] or "").lower()
        manifest_path = Path(options["manifest"])
        manifest_sha256 = (options["manifest_sha256"] or "").lower()
        rollback_dir = Path(options["rollback_dir"])

        if not _SHA256_RE.fullmatch(receipt_sha256):
            raise CommandError("--receipt-sha256 必须是 64 位十六进制 SHA-256")
        if not _SHA256_RE.fullmatch(manifest_sha256):
            raise CommandError("--manifest-sha256 必须是 64 位十六进制 SHA-256")

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError(f"无法读取 manifest: {exc}") from exc

        errors = verify_batch(
            receipt_path=receipt_path,
            receipt_sha256=receipt_sha256,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            rollback_dir=rollback_dir,
            approved_manifest=manifest,
        )
        if errors:
            self.stderr.write(
                json.dumps({"status": "failed", "errors": errors}, ensure_ascii=False, indent=2)
            )
            raise CommandError(f"验证失败: {len(errors)} 项不一致")
        self.stdout.write(json.dumps({"status": "ok"}, ensure_ascii=False, indent=2))
