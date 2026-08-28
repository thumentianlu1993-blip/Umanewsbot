from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from io import StringIO
import json
from pathlib import Path
import tempfile

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from stable.services.race_data_sync_pipeline import _ROSTER_ALLOWED_FIELDS


ROOT = Path(__file__).resolve().parents[2]


class RaceDataSyncAuditCommandTests(TestCase):
    @override_settings(
        RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE="",
        RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256="",
    )
    def test_audit_is_machine_readable_and_zero_write(self):
        output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command(
                "audit_race_data_sync",
                cutoff=datetime(
                    2026, 8, 28, 8, 0, tzinfo=dt_timezone.utc
                ).isoformat(),
                stdout=output,
            )
        report = json.loads(output.getvalue())
        self.assertFalse(report["would_write"])
        self.assertEqual(report["standing_policy"]["status"], "not_configured")
        self.assertEqual(report["capacity"]["status"], "invalid")
        self.assertEqual(report["configuration_status"], "blocked")
        mutating = (
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "REPLACE ",
            "ALTER ",
            "CREATE ",
            "DROP ",
        )
        self.assertFalse(
            [
                query["sql"]
                for query in queries.captured_queries
                if query["sql"].lstrip().upper().startswith(mutating)
            ]
        )

    @override_settings(
        RACE_DATA_SYNC_ENABLED=True,
        RACE_DATA_SYNC_ENABLED_PROVIDERS=("the_racing_api",),
        RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
        RACE_DATA_SYNC_ENABLED_FIELDS=("off_time",),
        RACE_DATA_SYNC_ENABLED_DATA_KINDS=("race_time", "racecard", "result"),
        RACE_LIVE_TRA_REGISTRY_SHA256="a" * 64,
    )
    def test_standing_policy_renderer_outputs_current_route_without_writes(self):
        output = StringIO()
        with CaptureQueriesContext(connection) as queries:
            call_command(
                "render_race_data_sync_standing_policy",
                policy_id="global-v1",
                approved_by="user-objective-2026-08-28",
                approved_at="2026-08-28T00:00:00+00:00",
                valid_from="2026-08-28T00:00:00+00:00",
                valid_until="2027-08-28T00:00:00+00:00",
                stdout=output,
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["policy_id"], "global-v1")
        self.assertEqual(payload["routes"][0]["provider"], "the_racing_api")
        self.assertEqual(payload["routes"][0]["region_code"], "japan_jra")
        self.assertFalse(queries.captured_queries)

    def test_closed_runtime_with_frozen_configuration_is_ready(self):
        with tempfile.TemporaryDirectory() as artifact_root, self.settings(
            RACE_DATA_SYNC_ENABLED=False,
            RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
            RACE_DATA_SYNC_ALLOW_NETWORK=False,
            RACE_DATA_SYNC_ENABLED_PROVIDERS=(
                "the_racing_api",
                "sporting_life",
                "zeturf",
                "horse_racing_nation",
            ),
            RACE_DATA_SYNC_ENABLED_REGIONS=(
                "france",
                "hong_kong",
                "ireland",
                "japan_jra",
                "japan_nar",
                "united_kingdom",
                "united_states",
            ),
            RACE_DATA_SYNC_ENABLED_FIELDS=_ROSTER_ALLOWED_FIELDS,
            RACE_DATA_SYNC_ENABLED_DATA_KINDS=(
                "race_time",
                "racecard",
                "result",
            ),
            RACE_LIVE_TRA_REGISTRY_SHA256=(
                "3bac3b644c631ed165b8430343822b2c70c5a88c5036b63dcb557c83c0e0a6da"
            ),
            RACE_DATA_SYNC_REFERENCE_REGISTRY_SHA256=(
                "740a93774927765f9c848cc97e4b87b78ab36d473c4c3e2e644d56a6f856cff2"
            ),
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE=str(
                ROOT / "runtime/policies/race_data_sync/standing_policy.json"
            ),
            RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256=(
                "07013655d4e0ae4bd5688b9a5dc447d759c0effa4b5393ec198f48bf961a1888"
            ),
            RACE_DATA_RAW_MAX_COMPRESSED_BYTES=2 * 1024 * 1024,
            RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES=8 * 1024 * 1024,
            RACE_DATA_RAW_DAILY_PROVIDER_REGION_BYTES=1024 * 1024 * 1024,
            RACE_DATA_RAW_DAILY_PROVIDER_REGION_REQUESTS=192,
            RACE_DATA_RAW_ROOT_HIGH_WATER_BYTES=512 * 1024 * 1024,
            RACE_DATA_RAW_ROOT_LOW_WATER_BYTES=256 * 1024 * 1024,
            RACE_DATA_RAW_MIN_FREE_DISK_BYTES=1,
            RACE_DATA_RAW_CLEANUP_MAX_ROWS=100,
            RACE_DATA_RAW_CLEANUP_MAX_BYTES=64 * 1024 * 1024,
            RACE_DATA_RAW_HOLD_ALERT_BYTES=256 * 1024 * 1024,
            RACE_DATA_RAW_ARTIFACT_ROOTS=(artifact_root,),
        ):
            output = StringIO()
            call_command(
                "audit_race_data_sync",
                cutoff="2026-08-28T08:00:00+00:00",
                stdout=output,
            )

        report = json.loads(output.getvalue())
        self.assertFalse(report["runtime"]["enabled"])
        self.assertEqual(report["capacity"]["status"], "valid")
        self.assertEqual(report["standing_policy"]["route_drift"], [])
        self.assertEqual(report["configuration_status"], "ready")
