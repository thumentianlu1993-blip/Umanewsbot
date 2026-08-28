from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.scheduled_race_result_review import (
    StaleClaimManifestDrift,
    StaleClaimReconciliationBlocked,
    build_stale_claim_reconciliation_preview,
    reconcile_expired_review_claims,
)


class Command(BaseCommand):
    help = "预览过期赛果审核 claim，或按精确 SHA 将无产物 claim 收口为 failed。"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-manifest-sha256", default="")

    def handle(self, *args, **options):
        now = timezone.now()
        expected = str(options["expected_manifest_sha256"] or "").strip().lower()
        if not options["apply"]:
            preview = build_stale_claim_reconciliation_preview(now=now)
            self.stdout.write(
                json.dumps(
                    {"mode": "preview", **preview},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise CommandError("apply 必须提供 64 位 --expected-manifest-sha256")
        try:
            receipt = reconcile_expired_review_claims(
                now=now,
                reason_code="stale_claim_reconciled",
                expected_manifest_sha256=expected,
                include_all_claimed=True,
            )
        except (StaleClaimManifestDrift, StaleClaimReconciliationBlocked) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                {"mode": "apply", **receipt},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
