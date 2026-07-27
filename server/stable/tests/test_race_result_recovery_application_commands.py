from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import date
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from stable import models


class RaceResultRecoveryApplyCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username=f"recovery-command-{self._testMethodName}",
            password="unused",
            is_staff=True,
        )

    def _event(self, slug):
        return models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=slug,
            chinese_name=slug,
            country_region=models.RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G1",
            surface=models.RaceEventSurface.TURF,
            timezone_name="Asia/Tokyo",
            local_date=date(2026, 7, 20),
            visibility_status=models.RaceEventVisibility.PUBLISHED,
        )

    @staticmethod
    def _write_json(path: Path, payload) -> str:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        path.write_bytes(body)
        return hashlib.sha256(body).hexdigest()

    def test_apply_persists_nine_approved_canonical_links_idempotently(self):
        links = []
        for index in range(9):
            duplicate = self._event(f"duplicate-{index}")
            canonical = self._event(f"canonical-{index}")
            links.append(
                {
                    "duplicate_event_id": duplicate.pk,
                    "canonical_event_id": canonical.pk,
                    "identity_sha256": f"{index + 1:x}" * 64,
                }
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            approval_path = root / "approval.json"
            registry_path = root / "routes.json"
            manifest_sha = self._write_json(
                manifest_path,
                {"schema_version": 1, "events": [], "canonical_links": links},
            )
            approval_sha = self._write_json(
                approval_path,
                {
                    "schema_version": 1,
                    "manifest_sha256": manifest_sha,
                    "event_ids": [],
                    "canonical_links": links,
                },
            )
            registry_sha = self._write_json(
                registry_path, {"schema_version": 1, "routes": {}}
            )
            args = (
                "--manifest",
                str(manifest_path),
                "--manifest-sha256",
                manifest_sha,
                "--approval",
                str(approval_path),
                "--approval-sha256",
                approval_sha,
                "--route-registry",
                str(registry_path),
                "--route-registry-sha256",
                registry_sha,
                "--ledger-root",
                str(root / "ledgers"),
                "--applied-by-id",
                str(self.user.pk),
                "--confirm-apply",
            )
            call_command("apply_race_result_recovery", *args, stdout=StringIO())
            call_command("apply_race_result_recovery", *args, stdout=StringIO())

        self.assertEqual(
            models.RaceEventProductCanonicalLink.objects.filter(
                is_active=True
            ).count(),
            9,
        )
