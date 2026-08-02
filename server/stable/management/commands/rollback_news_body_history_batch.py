from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from stable.services.news_body_history import _SHA256_RE, rollback_batch


class Command(BaseCommand):
    help = "使用预写 rollback manifest + receipt 精确恢复历史正文批次（CAS + 信任链校验）。"

    def add_arguments(self, parser):
        parser.add_argument("--rollback-manifest", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--receipt")
        parser.add_argument("--receipt-sha256")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        rollback_path = Path(options["rollback_manifest"])
        rollback_sha256 = (options["manifest_sha256"] or "").lower()
        receipt_path = Path(options["receipt"]) if options.get("receipt") else None
        receipt_sha256 = (options.get("receipt_sha256") or "").lower() if options.get("receipt_sha256") else None
        commit = bool(options["commit"])

        if not _SHA256_RE.fullmatch(rollback_sha256):
            raise CommandError("--manifest-sha256 必须是 64 位十六进制 SHA-256")

        if receipt_sha256 and not _SHA256_RE.fullmatch(receipt_sha256):
            raise CommandError("--receipt-sha256 必须是 64 位十六进制 SHA-256")

        # P1 fix: --receipt in commit mode requires --receipt-sha256
        if commit and receipt_path is not None and receipt_sha256 is None:
            raise CommandError("--commit 与 --receipt 同时使用必须提供 --receipt-sha256")

        if commit:
            with transaction.atomic():
                result = rollback_batch(
                    rollback_manifest_path=rollback_path,
                    rollback_manifest_sha256=rollback_sha256,
                    receipt_path=receipt_path,
                    receipt_sha256=receipt_sha256,
                    commit=True,
                )
        else:
            result = rollback_batch(
                rollback_manifest_path=rollback_path,
                rollback_manifest_sha256=rollback_sha256,
                receipt_path=receipt_path,
                receipt_sha256=receipt_sha256,
                commit=False,
            )

        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
