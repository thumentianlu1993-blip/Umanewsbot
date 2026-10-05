from __future__ import annotations

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import mock, skipUnless

from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase

from stable.models import (
    ExternalDataImportRun,
    ExternalDataSource,
    ExternalHorseHistory,
    ExternalImportStatus,
)
from stable.services import racing_api_horse_staging as staging_service
from stable.test_racing_api_horse_staging import RacingApiHorseStagingTests


def _assert_worker_sessions_closed(test_case, worker_pids):
    """只观测已绑定的线程PID；不终止会话，允许正常断开的短暂异步延迟。"""
    test_case.assertTrue(worker_pids, "no worker backend PID recorded")
    deadline = time.monotonic() + 2
    while True:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pid, datname, state FROM pg_stat_activity WHERE pid = ANY(%s)",
                [sorted(set(worker_pids))],
            )
            lingering = cursor.fetchall()
        if not lingering or time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    test_case.assertEqual(lingering, [], "worker PostgreSQL sessions still alive")


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
            worker_pids: list[int] = []
            original_validate = staging_service._validate_and_plan

            def synchronized_validate(normalized, **kwargs):
                plan = original_validate(normalized, **kwargs)
                rendezvous.wait(timeout=15)
                return plan

            def apply_once():
                close_old_connections()
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        worker_pids.append(cursor.fetchone()[0])
                    return staging_service.apply_targeted_artifact(
                        root,
                        approved_manifest_sha256=manifest_sha,
                        allow_write=True,
                    )
                finally:
                    connections.close_all()

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
        self.assertEqual(len(set(worker_pids)), 2)
        _assert_worker_sessions_closed(self, worker_pids)
