from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from io import StringIO
import json

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test import override_settings
from django.test.utils import CaptureQueriesContext


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
