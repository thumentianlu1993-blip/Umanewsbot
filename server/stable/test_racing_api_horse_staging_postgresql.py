from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import mock, skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from stable.models import (
    ExternalDataImportRun,
    ExternalDataSource,
    ExternalHorseHistory,
    ExternalImportStatus,
)
from stable.services import racing_api_horse_staging as staging_service
from stable.test_racing_api_horse_staging import RacingApiHorseStagingTests


@skipUnless(
    connection.vendor == "postgresql",
    "并发 receipt 门禁只在真实 PostgreSQL 上执行",
)
class RacingApiHorseStagingPostgresqlConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def _artifact(self, root: Path) -> tuple[Path, str]:
        builder = RacingApiHorseStagingTests(
            methodName="test_loader_binds_complete_manifest_and_rejects_extra_files"
        )
        return builder._artifact(root)

    def test_same_manifest_concurrency_creates_one_receipt_and_one_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._artifact(Path(temporary))
            rendezvous = Barrier(2)
            original_validate = staging_service._validate_and_plan

            def synchronized_validate(normalized):
                plan = original_validate(normalized)
                rendezvous.wait(timeout=15)
                return plan

            def apply_once():
                close_old_connections()
                try:
                    return staging_service.apply_targeted_artifact(
                        root,
                        approved_manifest_sha256=manifest_sha,
                        allow_write=True,
                    )
                finally:
                    close_old_connections()

            with mock.patch.dict(
                os.environ,
                {"RACING_API_STAGING_WRITE_ENABLED": "true"},
                clear=False,
            ), mock.patch.object(
                staging_service,
                "_validate_and_plan",
                side_effect=synchronized_validate,
            ), ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _index: apply_once(), range(2)))

        self.assertCountEqual(
            [result["status"] for result in results],
            ["applied", "replayed"],
        )
        self.assertEqual(
            ExternalDataImportRun.objects.filter(
                source=ExternalDataSource.THE_RACING_API,
                target_type="targeted_horse_artifact",
                parameters__manifest_sha256=manifest_sha,
                status=ExternalImportStatus.SUCCESS,
            ).count(),
            1,
        )
        self.assertEqual(ExternalHorseHistory.objects.count(), 1)
