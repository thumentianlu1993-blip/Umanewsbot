"""Contracts for strict lifecycle shadow enrollment manifests.

These tests intentionally exercise management-command boundaries.  The
prepare command is the only supported manifest producer and reconcile must
use the same v2 validation/preflight for dry-run and apply.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import inspect
import json
import os
import shutil
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from stable.models import (
    RaceDataSyncEnrollment,
    RaceEventLiveTracking,
    RaceEventProjectionControl,
    RaceResultSourceIdentity,
    RaceEvent,
    RaceEventLifecycleControl,
    RaceEventLifecycleTransition,
)
from stable.services import race_event_lifecycle_enrollment as enrollment_service
from stable.services.race_event_lifecycle_enrollment import (
    EnrollmentError,
    apply_enrollment,
    build_enrollment_artifacts,
    load_enrollment_manifest,
    preflight_enrollment,
    read_manifest_bytes,
    write_enrollment_artifacts,
)


APPROVED_COMMIT = "a" * 40
DATA_SYNC_MANIFEST = "b" * 64
DATA_SYNC_ENTRY = "c" * 64


def _make_event(*, slug: str, **overrides) -> RaceEvent:
    values = {
        "year": 2026,
        "slug": slug,
        "original_name": "Enrollment Test Race",
        "chinese_name": "纳管测试赛事",
        "country_region": "japan",
        "racecourse": "Test",
        "grade_text": "G1",
        "normalized_grade": "G1",
        "surface": "turf",
        "status": "scheduled",
        "priority": "P0",
        "visibility_status": "published",
        "timezone_name": "Asia/Tokyo",
        "local_date": date(2026, 8, 2),
    }
    values.update(overrides)
    return RaceEvent.objects.create(**values)


def _make_data_sync_control(
    event: RaceEvent, *, schedule_generation: int = 2
) -> RaceEventLifecycleControl:
    source = RaceResultSourceIdentity.objects.create(
        event=event,
        source_key="the_racing_api",
        region_code="japan_jra",
        identity_namespace="the-racing-api-v1",
        external_race_id=f"event-{event.pk}",
    )
    RaceEventProjectionControl.objects.create(
        event=event,
        write_owner="data_sync",
        owner_generation=1,
        owner_manifest_sha256=DATA_SYNC_MANIFEST,
    )
    RaceEventLiveTracking.objects.create(
        event=event,
        tracking_enabled=True,
        next_poll_at=event.race_datetime,
        claim_generation=4,
        lock_version=1,
    )
    RaceDataSyncEnrollment.objects.create(
        event=event,
        source_identity=source,
        state="enrolled",
        standing_policy_digest="d" * 64,
        route_digest="e" * 64,
        event_snapshot_sha256="f" * 64,
        projection_owner_generation=1,
        enrollment_generation=1,
        manifest_sha256=DATA_SYNC_MANIFEST,
        entry_sha256=DATA_SYNC_ENTRY,
    )
    return RaceEventLifecycleControl.objects.create(
        event=event,
        mode="off",
        next_refresh_at=event.race_datetime,
        schedule_generation=schedule_generation,
        manifest_data={
            "race_data_sync": {
                "manifest_sha256": DATA_SYNC_MANIFEST,
                "entry_sha256": DATA_SYNC_ENTRY,
                "owner_generation": 1,
            }
        },
    )


class LifecycleEnrollmentCommandTests(TestCase):
    maxDiff = None

    def _prepare(
        self,
        parent: Path,
        events: list[RaceEvent],
        *,
        us_zones: dict[int, list[str]] | None = None,
        dirname: str = "artifact",
    ) -> tuple[Path, dict, str]:
        # macOS exposes /var as a system symlink. Normal fixtures resolve their
        # trusted temporary parent; the explicit ancestor-symlink contract has
        # a dedicated unresolved-path test below.
        output_dir = parent.resolve() / dirname
        args = [
            "prepare_race_event_lifecycle_enrollment",
            "--event-ids",
            *[str(event.pk) for event in events],
            "--output-dir",
            str(output_dir),
            "--approved-commit",
            APPROVED_COMMIT,
        ]
        for event_id, zones in (us_zones or {}).items():
            for zone in zones:
                args.extend(["--allowed-us-zone", f"{event_id}={zone}"])
        call_command(*args)
        manifest_path = output_dir / "manifest.json"
        raw = manifest_path.read_bytes()
        return manifest_path, json.loads(raw), hashlib.sha256(raw).hexdigest()

    def _reconcile(
        self,
        manifest_path: Path,
        raw_sha: str,
        *,
        apply: bool = False,
    ) -> None:
        args = [
            "reconcile_race_event_lifecycle_controls",
            "--manifest-file",
            str(manifest_path),
            "--manifest-sha256",
            raw_sha,
            "--expected-commit",
            APPROVED_COMMIT,
        ]
        if apply:
            args.extend(["--apply", "--confirm-shadow-enrollment"])
        call_command(*args)

    def _rewrite_manifest(self, path: Path, data: dict) -> str:
        payload = dict(data)
        payload.pop("content_sha256", None)
        canonical_payload = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        data["content_sha256"] = hashlib.sha256(canonical_payload).hexdigest()
        raw = (
            json.dumps(
                data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def assert_command_rejected(self, callback) -> None:
        with self.assertRaises((CommandError, SystemExit)):
            callback()

    def test_prepare_creates_canonical_sorted_v2_manifest_and_summary_read_only(self):
        later_id = _make_event(slug="prepare-later")
        earlier_id = _make_event(slug="prepare-earlier")
        before_events = list(
            RaceEvent.objects.order_by("pk").values_list(
                "pk", "status", "updated_at"
            )
        )

        with TemporaryDirectory() as tmp:
            manifest_path, manifest, raw_sha = self._prepare(
                Path(tmp), [later_id, earlier_id]
            )
            summary = json.loads(
                (manifest_path.parent / "summary.json").read_text(encoding="utf-8")
            )
            raw = manifest_path.read_bytes()

        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["mode"], "shadow")
        self.assertEqual(
            [int(event_id) for event_id in manifest["events"]],
            sorted([later_id.pk, earlier_id.pk]),
        )
        self.assertEqual(manifest["approved_commit"], APPROVED_COMMIT)
        self.assertRegex(manifest["content_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(raw_sha, r"^[0-9a-f]{64}$")
        self.assertTrue(raw.endswith(b"\n"))
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(summary["manifest_raw_sha256"], raw_sha)
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)
        self.assertEqual(
            list(
                RaceEvent.objects.order_by("pk").values_list(
                    "pk", "status", "updated_at"
                )
            ),
            before_events,
        )

    def test_prepare_accepts_non_key_p2_event_and_freezes_false_snapshot(self):
        event = _make_event(
            slug="prepare-non-key-p2",
            priority="P2",
            is_featured=False,
            race_datetime=datetime(
                2026, 8, 2, 6, 0, tzinfo=dt_timezone.utc
            ),
        )

        self.assertFalse(event.is_key_race)
        self.assertEqual(event.visibility_status, "published")
        self.assertEqual(event.status, "scheduled")
        self.assertEqual(event.country_region, "japan")
        self.assertEqual(event.timezone_name, "Asia/Tokyo")
        self.assertEqual(event.local_date, date(2026, 8, 2))
        self.assertEqual(event.manual_lock_flags, {})
        self.assertFalse(
            RaceEventLifecycleControl.objects.filter(event=event).exists()
        )

        with TemporaryDirectory() as tmp:
            _, manifest, _ = self._prepare(Path(tmp), [event])

        snapshot = manifest["events"][str(event.pk)]
        self.assertEqual(snapshot["priority"], "P2")
        self.assertFalse(snapshot["is_featured"])
        self.assertFalse(snapshot["eligibility"]["is_key_race"])
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    def test_prepare_accepts_mixed_key_and_non_key_events_atomically(self):
        key_event = _make_event(
            slug="prepare-mixed-key",
            priority="P1",
            is_featured=False,
            race_datetime=datetime(
                2026, 8, 2, 6, 0, tzinfo=dt_timezone.utc
            ),
        )
        non_key_event = _make_event(
            slug="prepare-mixed-non-key",
            priority="P2",
            is_featured=False,
            race_datetime=datetime(
                2026, 8, 2, 7, 0, tzinfo=dt_timezone.utc
            ),
        )

        self.assertTrue(key_event.is_key_race)
        self.assertFalse(non_key_event.is_key_race)
        self.assertEqual(
            RaceEventLifecycleControl.objects.filter(
                event_id__in=[key_event.pk, non_key_event.pk]
            ).count(),
            0,
        )

        with TemporaryDirectory() as tmp:
            _, manifest, _ = self._prepare(
                Path(tmp), [non_key_event, key_event]
            )

        self.assertEqual(
            [int(event_id) for event_id in manifest["events"]],
            sorted([key_event.pk, non_key_event.pk]),
        )
        self.assertTrue(
            manifest["events"][str(key_event.pk)]["eligibility"]["is_key_race"]
        )
        self.assertFalse(
            manifest["events"][str(non_key_event.pk)]["eligibility"][
                "is_key_race"
            ]
        )
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    def test_non_key_p2_v2_dry_run_reports_would_create_with_zero_writes(self):
        event = _make_event(
            slug="dry-run-non-key-p2",
            priority="P2",
            is_featured=False,
            race_datetime=datetime(
                2026, 8, 2, 6, 0, tzinfo=dt_timezone.utc
            ),
        )
        self.assertFalse(event.is_key_race)

        with TemporaryDirectory() as tmp:
            path, manifest, sha = self._prepare(Path(tmp), [event])
            stdout = StringIO()
            call_command(
                "reconcile_race_event_lifecycle_controls",
                "--manifest-file",
                str(path),
                "--manifest-sha256",
                sha,
                "--expected-commit",
                APPROVED_COMMIT,
                stdout=stdout,
            )

        self.assertFalse(
            manifest["events"][str(event.pk)]["eligibility"]["is_key_race"]
        )
        self.assertIn(f"event={event.pk} result=would_create", stdout.getvalue())
        self.assertIn(
            "[DRY-RUN] schema=v2 total=1 would_create=1 "
            "would_adopt=0 replay=0 error=0",
            stdout.getvalue(),
        )
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    def test_prepare_rejects_duplicate_nonpositive_empty_and_twenty_first_id_before_output(self):
        events = [_make_event(slug=f"limit-{index}") for index in range(21)]
        cases = (
            ("empty", []),
            ("duplicate", [events[0].pk, events[0].pk]),
            ("zero", [0]),
            ("negative", [-1]),
            ("too-many", [event.pk for event in events]),
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            for dirname, ids in cases:
                with self.subTest(dirname=dirname):
                    output = parent / dirname
                    args = [
                        "prepare_race_event_lifecycle_enrollment",
                        "--event-ids",
                        *[str(event_id) for event_id in ids],
                        "--output-dir",
                        str(output),
                        "--approved-commit",
                        APPROVED_COMMIT,
                    ]
                    self.assert_command_rejected(lambda args=args: call_command(*args))
                    self.assertFalse(output.exists())

    def test_prepare_rejects_ineligible_event_as_an_atomic_batch(self):
        valid = _make_event(slug="eligible")
        invalid = _make_event(slug="draft", visibility_status="draft")
        with TemporaryDirectory() as tmp:
            output = Path(tmp).resolve() / "artifact"
            self.assert_command_rejected(
                lambda: self._prepare(Path(tmp), [valid, invalid])
            )
            self.assertFalse(output.exists())
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)

    def test_prepare_does_not_derive_race_datetime_from_local_start_time(self):
        event = _make_event(
            slug="local-time-only",
            local_start_time=time(15, 30),
            race_datetime=None,
        )
        with TemporaryDirectory() as tmp:
            _, manifest, _ = self._prepare(Path(tmp), [event])
        snapshot = manifest["events"][str(event.pk)]
        self.assertEqual(snapshot["local_start_time"], "15:30:00")
        self.assertIsNone(snapshot["race_datetime"])
        self.assertEqual(
            snapshot["predicted_next_refresh_at"],
            "2026-08-02T15:00:00+00:00",
        )

    def test_prepare_requires_per_event_us_allowlist(self):
        event = _make_event(
            slug="us-event",
            country_region="united_states",
            timezone_name="America/New_York",
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            self.assert_command_rejected(lambda: self._prepare(parent, [event]))
            _, manifest, _ = self._prepare(
                parent,
                [event],
                us_zones={event.pk: ["America/New_York"]},
                dirname="valid",
            )
        self.assertEqual(
            manifest["events"][str(event.pk)]["allowed_us_zones"],
            ["America/New_York"],
        )

    def test_cross_digit_event_ids_round_trip_in_numeric_order(self):
        event_ten = _make_event(slug="numeric-ten", pk=10)
        event_nine = _make_event(slug="numeric-nine", pk=9)
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [event_ten, event_nine])
            stdout = StringIO()
            call_command(
                "reconcile_race_event_lifecycle_controls",
                "--manifest-file",
                str(path),
                "--manifest-sha256",
                sha,
                "--expected-commit",
                APPROVED_COMMIT,
                stdout=stdout,
            )
        output = stdout.getvalue()
        self.assertIn("event=9", output)
        self.assertIn("event=10", output)
        self.assertLess(output.index("event=9"), output.index("event=10"))
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)

    def test_v2_dry_run_rejects_unknown_field_even_with_recomputed_hashes(self):
        event = _make_event(slug="strict-schema")
        with TemporaryDirectory() as tmp:
            path, manifest, _ = self._prepare(Path(tmp), [event])
            manifest["unexpected"] = True
            raw_sha = self._rewrite_manifest(path, manifest)
            self.assert_command_rejected(
                lambda: self._reconcile(path, raw_sha)
            )
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)

    def test_v1_apply_is_permanently_rejected_with_zero_writes(self):
        event = _make_event(slug="v1-rejected")
        manifest = {
            "schema_version": 1,
            "events": {
                str(event.pk): {
                    "mode": "shadow",
                    "region": "japan",
                    "eligibility": {
                        "is_key_race": True,
                        "is_published": True,
                        "is_cancelled": False,
                    },
                    "enrollment_schedule_hash": "b" * 64,
                }
            },
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "v1.json"
            raw = json.dumps(manifest, sort_keys=True).encode("utf-8")
            path.write_bytes(raw)
            sha = hashlib.sha256(raw).hexdigest()
            self.assert_command_rejected(
                lambda: call_command(
                    "reconcile_race_event_lifecycle_controls",
                    "--manifest-file",
                    str(path),
                    "--manifest-sha256",
                    sha,
                    "--apply",
                )
            )
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    def test_v2_apply_requires_sha_expected_commit_and_confirmation(self):
        event = _make_event(slug="required-apply-arguments")
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [event])
            cases = (
                (
                    "missing-sha",
                    [
                        "--manifest-file",
                        str(path),
                        "--expected-commit",
                        APPROVED_COMMIT,
                        "--confirm-shadow-enrollment",
                    ],
                ),
                (
                    "missing-expected-commit",
                    [
                        "--manifest-file",
                        str(path),
                        "--manifest-sha256",
                        sha,
                        "--confirm-shadow-enrollment",
                    ],
                ),
                (
                    "missing-confirmation",
                    [
                        "--manifest-file",
                        str(path),
                        "--manifest-sha256",
                        sha,
                        "--expected-commit",
                        APPROVED_COMMIT,
                    ],
                ),
            )
            for label, args in cases:
                with self.subTest(label=label):
                    self.assert_command_rejected(
                        lambda args=args: call_command(
                            "reconcile_race_event_lifecycle_controls",
                            *args,
                            "--apply",
                        )
                    )
                    self.assertEqual(
                        RaceEventLifecycleControl.objects.count(), 0
                    )
                    self.assertEqual(
                        RaceEventLifecycleTransition.objects.count(), 0
                    )

    def test_expired_v2_manifest_is_rejected_by_dry_run(self):
        event = _make_event(slug="expired-manifest")
        with TemporaryDirectory() as tmp:
            path, manifest, _ = self._prepare(Path(tmp), [event])
            manifest["generated_at"] = "2020-01-01T00:00:00+00:00"
            manifest["expires_at"] = "2020-01-02T00:00:00+00:00"
            sha = self._rewrite_manifest(path, manifest)
            self.assert_command_rejected(lambda: self._reconcile(path, sha))
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)

    def test_manifest_symlink_is_rejected(self):
        event = _make_event(slug="symlink-manifest")
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [event])
            symlink = Path(tmp) / "manifest-link.json"
            symlink.symlink_to(path)
            self.assert_command_rejected(
                lambda: self._reconcile(symlink, sha)
            )
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)

    def test_prepare_rejects_non_scheduled_manual_lock_and_missing_local_date(self):
        cases = (
            _make_event(slug="not-scheduled", status="running"),
            _make_event(
                slug="manually-locked",
                manual_lock_flags={"status": True},
            ),
            _make_event(slug="missing-local-date", local_date=None),
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            for index, event in enumerate(cases):
                with self.subTest(event=event.slug):
                    output = parent / f"artifact-{index}"
                    self.assert_command_rejected(
                        lambda event=event, index=index: self._prepare(
                            parent, [event], dirname=f"artifact-{index}"
                        )
                    )
                    self.assertFalse(output.exists())
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)

    def test_prepare_twenty_events_uses_bounded_queries_and_zero_db_writes(self):
        events = [
            _make_event(slug=f"query-bound-{index}")
            for index in range(20)
        ]
        with CaptureQueriesContext(connection) as captured:
            manifest_bytes, summary_bytes = build_enrollment_artifacts(
                event_ids=[event.pk for event in reversed(events)],
                approved_commit=APPROVED_COMMIT,
            )
        query_count = len(captured.captured_queries)

        self.assertLessEqual(
            query_count,
            4,
            f"20-event prepare used {query_count} queries; expected <= 4",
        )
        self.assertEqual(
            query_count,
            2,
            f"expected one event query plus one control query, got {query_count}",
        )
        self.assertTrue(manifest_bytes.endswith(b"\n"))
        self.assertTrue(summary_bytes.endswith(b"\n"))
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    def test_direct_apply_service_rejects_non_strict_false_off_settings(self):
        event = _make_event(slug="direct-apply-settings-gate")
        combinations = (
            (True, "shadow"),
            (True, "off"),
            (False, "shadow"),
            (True, "enforce"),
        )
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [event])
            manifest = load_enrollment_manifest(
                path,
                expected_raw_sha256=sha,
                expected_commit=APPROVED_COMMIT,
            )
            for enabled, mode in combinations:
                with self.subTest(enabled=enabled, mode=mode):
                    with override_settings(
                        RACE_EVENT_LIFECYCLE_ENABLED=enabled,
                        RACE_EVENT_LIFECYCLE_MODE=mode,
                    ):
                        with self.assertRaises(EnrollmentError):
                            apply_enrollment(manifest)
                    self.assertEqual(
                        RaceEventLifecycleControl.objects.count(), 0
                    )
                    self.assertEqual(
                        RaceEventLifecycleTransition.objects.count(), 0
                    )

    def test_preflight_and_apply_do_not_expose_caller_controlled_now(self):
        for operation in (preflight_enrollment, apply_enrollment):
            with self.subTest(operation=operation.__name__):
                self.assertNotIn(
                    "now",
                    inspect.signature(operation).parameters,
                    f"{operation.__name__} lets callers roll back safety time",
                )

    def test_preflight_and_apply_reject_prediction_after_time_boundary(self):
        generated_at = datetime(
            2026, 8, 1, 12, 0, tzinfo=dt_timezone.utc
        )
        race_datetime = generated_at + timedelta(hours=1)
        observed_at = race_datetime + timedelta(minutes=1)
        event = _make_event(
            slug="prediction-time-drift",
            race_datetime=race_datetime,
        )
        with TemporaryDirectory() as tmp:
            manifest_bytes, summary_bytes = build_enrollment_artifacts(
                event_ids=[event.pk],
                approved_commit=APPROVED_COMMIT,
                now=generated_at,
            )
            output = Path(tmp).resolve() / "artifact"
            write_enrollment_artifacts(
                output,
                manifest_bytes=manifest_bytes,
                summary_bytes=summary_bytes,
            )
            path = output / "manifest.json"
            manifest = load_enrollment_manifest(
                path,
                expected_raw_sha256=hashlib.sha256(
                    manifest_bytes
                ).hexdigest(),
                expected_commit=APPROVED_COMMIT,
                now=generated_at,
            )
            with patch(
                "stable.services.race_event_lifecycle_enrollment."
                "django_timezone.now",
                return_value=observed_at,
            ):
                for label, operation in (
                    ("dry-run-preflight", lambda: preflight_enrollment(manifest)),
                    ("apply", lambda: apply_enrollment(manifest)),
                ):
                    with self.subTest(operation=label):
                        with self.assertRaises(EnrollmentError):
                            operation()
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    def test_output_dir_rejects_symlink_in_any_ancestor(self):
        event = _make_event(slug="output-ancestor-symlink")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            real_parent = parent / "real"
            nested = real_parent / "nested"
            nested.mkdir(parents=True)
            symlink_parent = parent / "linked"
            symlink_parent.symlink_to(real_parent, target_is_directory=True)
            requested_output = symlink_parent / "nested" / "artifact"
            resolved_output = nested / "artifact"

            with self.assertRaises(EnrollmentError):
                write_enrollment_artifacts(
                    requested_output,
                    manifest_bytes=manifest_bytes,
                    summary_bytes=summary_bytes,
                )
            self.assertFalse(requested_output.exists())
            self.assertFalse(resolved_output.exists())

    def test_output_dir_rejects_unresolved_macos_temporary_alias(self):
        event = _make_event(slug="unresolved-system-alias")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            unresolved_parent = Path(tmp)
            if unresolved_parent == unresolved_parent.resolve():
                self.skipTest("temporary directory has no symlink ancestor")
            requested_output = unresolved_parent / "artifact"
            resolved_output = unresolved_parent.resolve() / "artifact"
            with self.assertRaises(EnrollmentError):
                write_enrollment_artifacts(
                    requested_output,
                    manifest_bytes=manifest_bytes,
                    summary_bytes=summary_bytes,
                )
            self.assertFalse(requested_output.exists())
            self.assertFalse(resolved_output.exists())

    def test_prepare_command_does_not_resolve_away_temporary_alias(self):
        event = _make_event(slug="command-unresolved-system-alias")
        with TemporaryDirectory() as tmp:
            unresolved_parent = Path(tmp)
            if unresolved_parent == unresolved_parent.resolve():
                self.skipTest("temporary directory has no symlink ancestor")
            requested_output = unresolved_parent / "artifact"
            resolved_output = unresolved_parent.resolve() / "artifact"

            self.assert_command_rejected(
                lambda: call_command(
                    "prepare_race_event_lifecycle_enrollment",
                    "--event-ids",
                    str(event.pk),
                    "--output-dir",
                    str(requested_output),
                    "--approved-commit",
                    APPROVED_COMMIT,
                )
            )
            self.assertFalse(requested_output.exists())
            self.assertFalse(resolved_output.exists())
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    def test_writer_rejects_parent_replaced_by_symlink_after_validation(self):
        event = _make_event(slug="writer-parent-symlink-race")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            parent = root / "parent"
            parent.mkdir()
            moved_parent = root / "parent-moved"
            attacker = root / "attacker"
            attacker.mkdir()
            requested_output = parent / "artifact"
            original_os_mkdir = enrollment_service.os.mkdir
            attack_ran = False
            rejected = False

            def replace_parent_then_mkdir(*args, **kwargs):
                nonlocal attack_ran
                target_name = Path(str(args[0])).name if args else ""
                if (
                    not attack_ran
                    and target_name.startswith(".artifact.tmp-")
                ):
                    attack_ran = True
                    parent.rename(moved_parent)
                    parent.symlink_to(attacker, target_is_directory=True)
                return original_os_mkdir(*args, **kwargs)

            try:
                with patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "os.mkdir",
                    side_effect=replace_parent_then_mkdir,
                ) as mocked_mkdir:
                    supported_dir_fd = set(enrollment_service.os.supports_dir_fd)
                    supported_dir_fd.add(mocked_mkdir)
                    with patch.object(
                        enrollment_service.os,
                        "supports_dir_fd",
                        supported_dir_fd,
                    ):
                        try:
                            write_enrollment_artifacts(
                                requested_output,
                                manifest_bytes=manifest_bytes,
                                summary_bytes=summary_bytes,
                            )
                        except EnrollmentError:
                            rejected = True

                attacker_entries = sorted(
                    str(path.relative_to(attacker))
                    for path in attacker.rglob("*")
                )
                moved_staging = sorted(
                    moved_parent.glob(".artifact.tmp-*")
                )
                probe_prefixes = (
                    ".lifecycle-noreplace-probe-source-",
                    ".lifecycle-noreplace-probe-target-",
                )
                moved_probe_residues = sorted(
                    path
                    for path in moved_parent.iterdir()
                    if path.name.startswith(probe_prefixes)
                )
                moved_non_staging = sorted(
                    path.name
                    for path in moved_parent.iterdir()
                    if (
                        path not in moved_staging
                        and path not in moved_probe_residues
                    )
                )
                moved_staging_entries = {
                    staging.name: sorted(
                        str(path.relative_to(staging))
                        for path in staging.rglob("*")
                    )
                    for staging in moved_staging
                }
                moved_probe_residue_entries = {
                    residue.name: sorted(
                        str(path.relative_to(residue))
                        for path in residue.rglob("*")
                    )
                    for residue in moved_probe_residues
                }
                probe_suffixes = [
                    next(
                        residue.name.removeprefix(prefix)
                        for prefix in probe_prefixes
                        if residue.name.startswith(prefix)
                    )
                    for residue in moved_probe_residues
                ]
                self.assertEqual(
                    {
                        "attack_ran": attack_ran,
                        "rejected": rejected,
                        "attacker_entries": attacker_entries,
                        "moved_staging_count_at_least_one": (
                            len(moved_staging) >= 1
                        ),
                        "moved_non_staging": moved_non_staging,
                        "moved_staging_all_empty": all(
                            not entries
                            for entries in moved_staging_entries.values()
                        ),
                        "probe_residue_names": sorted(
                            residue.name[: -len(suffix)]
                            for residue, suffix in zip(
                                moved_probe_residues,
                                probe_suffixes,
                                strict=True,
                            )
                        ),
                        "probe_residues_are_plain_directories": all(
                            residue.is_dir() and not residue.is_symlink()
                            for residue in moved_probe_residues
                        ),
                        "probe_residue_suffixes_are_high_entropy": all(
                            len(suffix) == 48
                            and all(
                                character in "0123456789abcdef"
                                for character in suffix
                            )
                            for suffix in probe_suffixes
                        ),
                        "probe_residues_all_recursively_empty": all(
                            not entries
                            for entries in moved_probe_residue_entries.values()
                        ),
                        "requested_output_exists": requested_output.exists(),
                    },
                    {
                        "attack_ran": True,
                        "rejected": True,
                        "attacker_entries": [],
                        "moved_staging_count_at_least_one": True,
                        "moved_non_staging": [],
                        "moved_staging_all_empty": True,
                        "probe_residue_names": sorted(probe_prefixes),
                        "probe_residues_are_plain_directories": True,
                        "probe_residue_suffixes_are_high_entropy": True,
                        "probe_residues_all_recursively_empty": True,
                        "requested_output_exists": False,
                    },
                )
            finally:
                if parent.is_symlink():
                    parent.unlink()
                if attacker.exists():
                    shutil.rmtree(attacker)
                if moved_parent.exists() and not parent.exists():
                    moved_parent.rename(parent)

    def test_writer_rejects_staging_name_replaced_before_publish(self):
        event = _make_event(slug="writer-staging-name-race")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve() / "parent"
            parent.mkdir()
            requested_output = parent / "artifact"
            stolen_name = ".artifact.stolen"
            stolen_path = parent / stolen_name
            original_atomic_publish = (
                enrollment_service._atomic_rename_noreplace
            )
            original_os_rename = enrollment_service.os.rename
            original_os_mkdir = enrollment_service.os.mkdir
            attack_ran = False
            rejected = False
            attacker_marker = b"attacker-controlled-marker"

            def replace_staging_then_publish(
                parent_fd, source_name, destination_name
            ):
                nonlocal attack_ran
                if (
                    not attack_ran
                    and source_name.startswith(".artifact.tmp-")
                    and destination_name == "artifact"
                ):
                    attack_ran = True
                    original_os_rename(
                        source_name,
                        stolen_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                    original_os_mkdir(
                        source_name,
                        mode=0o700,
                        dir_fd=parent_fd,
                    )
                    replacement_fd = enrollment_service.os.open(
                        source_name,
                        enrollment_service.os.O_RDONLY
                        | enrollment_service.os.O_DIRECTORY
                        | enrollment_service.os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                    try:
                        marker_fd = enrollment_service.os.open(
                            "attacker.marker",
                            enrollment_service.os.O_WRONLY
                            | enrollment_service.os.O_CREAT
                            | enrollment_service.os.O_EXCL
                            | enrollment_service.os.O_NOFOLLOW,
                            0o600,
                            dir_fd=replacement_fd,
                        )
                        try:
                            enrollment_service.os.write(
                                marker_fd, attacker_marker
                            )
                        finally:
                            enrollment_service.os.close(marker_fd)
                    finally:
                        enrollment_service.os.close(replacement_fd)
                return original_atomic_publish(
                    parent_fd, source_name, destination_name
                )

            try:
                with patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "_atomic_rename_noreplace",
                    side_effect=replace_staging_then_publish,
                ):
                    try:
                        write_enrollment_artifacts(
                            requested_output,
                            manifest_bytes=manifest_bytes,
                            summary_bytes=summary_bytes,
                        )
                    except EnrollmentError:
                        rejected = True

                output_entries = (
                    sorted(
                        str(path.relative_to(requested_output))
                        for path in requested_output.rglob("*")
                    )
                    if requested_output.exists()
                    else []
                )
                stolen_entries = (
                    sorted(
                        str(path.relative_to(stolen_path))
                        for path in stolen_path.rglob("*")
                    )
                    if stolen_path.exists()
                    else []
                )
                quarantines = sorted(
                    parent.glob(".artifact.quarantine-*")
                )
                quarantine_entries = (
                    sorted(
                        str(path.relative_to(quarantines[0]))
                        for path in quarantines[0].rglob("*")
                    )
                    if len(quarantines) == 1
                    else []
                )
                quarantine_marker = (
                    (quarantines[0] / "attacker.marker").read_bytes()
                    if len(quarantines) == 1
                    and (quarantines[0] / "attacker.marker").is_file()
                    else None
                )
                self.assertEqual(
                    {
                        "attack_ran": attack_ran,
                        "rejected": rejected,
                        "output_exists": requested_output.exists(),
                        "output_entries": output_entries,
                        "stolen_entries": stolen_entries,
                        "quarantine_count": len(quarantines),
                        "quarantine_entries": quarantine_entries,
                        "quarantine_marker": quarantine_marker,
                    },
                    {
                        "attack_ran": True,
                        "rejected": True,
                        "output_exists": False,
                        "output_entries": [],
                        "stolen_entries": [],
                        "quarantine_count": 1,
                        "quarantine_entries": ["attacker.marker"],
                        "quarantine_marker": attacker_marker,
                    },
                )
            finally:
                if requested_output.exists():
                    shutil.rmtree(requested_output)
                if stolen_path.exists():
                    shutil.rmtree(stolen_path)
                for quarantine in parent.glob(".artifact.quarantine-*"):
                    shutil.rmtree(quarantine)

    def test_rename_conflict_preserves_concurrent_output_in_place(self):
        event = _make_event(slug="writer-concurrent-output-race")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve() / "parent"
            parent.mkdir()
            requested_output = parent / "artifact"
            original_atomic_publish = (
                enrollment_service._atomic_rename_noreplace
            )
            original_os_mkdir = enrollment_service.os.mkdir
            attack_ran = False
            rejected = False
            competitor_identity = None
            competitor_marker = b"concurrent-owner-marker"

            def create_competitor_before_publish(
                parent_fd, source_name, destination_name
            ):
                nonlocal attack_ran, competitor_identity
                if (
                    not attack_ran
                    and source_name.startswith(".artifact.tmp-")
                    and destination_name == "artifact"
                ):
                    attack_ran = True
                    original_os_mkdir(
                        destination_name,
                        mode=0o700,
                        dir_fd=parent_fd,
                    )
                    competitor_fd = enrollment_service.os.open(
                        destination_name,
                        enrollment_service.os.O_RDONLY
                        | enrollment_service.os.O_DIRECTORY
                        | enrollment_service.os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                    try:
                        metadata = enrollment_service.os.fstat(competitor_fd)
                        competitor_identity = (
                            metadata.st_dev,
                            metadata.st_ino,
                        )
                        marker_fd = enrollment_service.os.open(
                            "competitor.marker",
                            enrollment_service.os.O_WRONLY
                            | enrollment_service.os.O_CREAT
                            | enrollment_service.os.O_EXCL
                            | enrollment_service.os.O_NOFOLLOW,
                            0o600,
                            dir_fd=competitor_fd,
                        )
                        try:
                            enrollment_service.os.write(
                                marker_fd, competitor_marker
                            )
                        finally:
                            enrollment_service.os.close(marker_fd)
                    finally:
                        enrollment_service.os.close(competitor_fd)
                return original_atomic_publish(
                    parent_fd, source_name, destination_name
                )

            try:
                with patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "_atomic_rename_noreplace",
                    side_effect=create_competitor_before_publish,
                ):
                    try:
                        write_enrollment_artifacts(
                            requested_output,
                            manifest_bytes=manifest_bytes,
                            summary_bytes=summary_bytes,
                        )
                    except EnrollmentError:
                        rejected = True

                output_identity = (
                    (
                        requested_output.stat().st_dev,
                        requested_output.stat().st_ino,
                    )
                    if requested_output.is_dir()
                    else None
                )
                output_entries = (
                    sorted(
                        str(path.relative_to(requested_output))
                        for path in requested_output.rglob("*")
                    )
                    if requested_output.is_dir()
                    else []
                )
                marker_content = (
                    (requested_output / "competitor.marker").read_bytes()
                    if (requested_output / "competitor.marker").is_file()
                    else None
                )
                leaked_payloads = sorted(
                    str(path.relative_to(parent))
                    for path in parent.rglob("*")
                    if path.is_file()
                    and path.name in {"manifest.json", "summary.json"}
                )
                quarantines = sorted(parent.glob(".artifact.quarantine-*"))
                self.assertEqual(
                    {
                        "attack_ran": attack_ran,
                        "rejected": rejected,
                        "competitor_identity_preserved": (
                            competitor_identity is not None
                            and output_identity == competitor_identity
                        ),
                        "output_entries": output_entries,
                        "marker_content": marker_content,
                        "quarantine_count": len(quarantines),
                        "leaked_payloads": leaked_payloads,
                    },
                    {
                        "attack_ran": True,
                        "rejected": True,
                        "competitor_identity_preserved": True,
                        "output_entries": ["competitor.marker"],
                        "marker_content": competitor_marker,
                        "quarantine_count": 0,
                        "leaked_payloads": [],
                    },
                )
            finally:
                for child in list(parent.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()

    def test_successful_rename_must_not_overwrite_concurrent_empty_output(self):
        event = _make_event(slug="writer-concurrent-empty-output-race")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve() / "parent"
            parent.mkdir()
            requested_output = parent / "artifact"
            original_atomic_publish = (
                enrollment_service._atomic_rename_noreplace
            )
            original_os_mkdir = enrollment_service.os.mkdir
            attack_ran = False
            rejected = False
            competitor_identity = None

            def create_empty_competitor_before_publish(
                parent_fd, source_name, destination_name
            ):
                nonlocal attack_ran, competitor_identity
                if (
                    not attack_ran
                    and source_name.startswith(".artifact.tmp-")
                    and destination_name == "artifact"
                ):
                    attack_ran = True
                    original_os_mkdir(
                        destination_name,
                        mode=0o700,
                        dir_fd=parent_fd,
                    )
                    metadata = enrollment_service.os.stat(
                        destination_name,
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    competitor_identity = (
                        metadata.st_dev,
                        metadata.st_ino,
                    )
                return original_atomic_publish(
                    parent_fd, source_name, destination_name
                )

            try:
                with patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "_atomic_rename_noreplace",
                    side_effect=create_empty_competitor_before_publish,
                ):
                    try:
                        write_enrollment_artifacts(
                            requested_output,
                            manifest_bytes=manifest_bytes,
                            summary_bytes=summary_bytes,
                        )
                    except EnrollmentError:
                        rejected = True

                output_identity = (
                    (
                        requested_output.stat().st_dev,
                        requested_output.stat().st_ino,
                    )
                    if requested_output.is_dir()
                    else None
                )
                output_entries = (
                    sorted(
                        str(path.relative_to(requested_output))
                        for path in requested_output.rglob("*")
                    )
                    if requested_output.is_dir()
                    else []
                )
                quarantines = sorted(parent.glob(".artifact.quarantine-*"))
                self.assertEqual(
                    {
                        "attack_ran": attack_ran,
                        "rejected": rejected,
                        "competitor_identity_preserved": (
                            competitor_identity is not None
                            and output_identity == competitor_identity
                        ),
                        "output_entries": output_entries,
                        "quarantine_count": len(quarantines),
                    },
                    {
                        "attack_ran": True,
                        "rejected": True,
                        "competitor_identity_preserved": True,
                        "output_entries": [],
                        "quarantine_count": 0,
                    },
                )
            finally:
                for child in list(parent.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()

    def test_atomic_noreplace_runtime_capability_fails_before_payload_write(self):
        event = _make_event(slug="writer-runtime-capability-failure")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve() / "parent"
            parent.mkdir()
            requested_output = parent / "artifact"
            original_write_relative = enrollment_service._write_relative_file
            primitive_calls = 0
            rejected = False

            def unavailable_primitive(*args):
                nonlocal primitive_calls
                primitive_calls += 1
                ctypes.set_errno(errno.ENOSYS)
                return -1

            try:
                with patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "_load_atomic_noreplace_primitive",
                    return_value=(unavailable_primitive, 0),
                ), patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "_write_relative_file",
                    wraps=original_write_relative,
                ) as mocked_payload_write:
                    try:
                        write_enrollment_artifacts(
                            requested_output,
                            manifest_bytes=manifest_bytes,
                            summary_bytes=summary_bytes,
                        )
                    except EnrollmentError:
                        rejected = True

                self.assertEqual(
                    {
                        "primitive_called": primitive_calls >= 1,
                        "rejected": rejected,
                        "payload_write_calls": mocked_payload_write.call_count,
                    },
                    {
                        "primitive_called": True,
                        "rejected": True,
                        "payload_write_calls": 0,
                    },
                )
            finally:
                for child in list(parent.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()

    def test_atomic_noreplace_semantic_probe_rejects_overwrite_primitive_before_write(self):
        event = _make_event(slug="writer-semantic-capability-failure")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve() / "parent"
            parent.mkdir()
            requested_output = parent / "artifact"
            original_os_rename = enrollment_service.os.rename
            original_write_relative = enrollment_service._write_relative_file
            semantic_overwrite_observed = False
            rejected = False

            def overwrite_primitive(
                source_fd,
                source_name,
                destination_fd,
                destination_name,
                flags,
            ):
                nonlocal semantic_overwrite_observed
                source_text = enrollment_service.os.fsdecode(source_name)
                destination_text = enrollment_service.os.fsdecode(
                    destination_name
                )
                destination_before = None
                try:
                    metadata = enrollment_service.os.stat(
                        destination_text,
                        dir_fd=destination_fd,
                        follow_symlinks=False,
                    )
                    destination_before = (
                        metadata.st_dev,
                        metadata.st_ino,
                    )
                except FileNotFoundError:
                    pass
                original_os_rename(
                    source_text,
                    destination_text,
                    src_dir_fd=source_fd,
                    dst_dir_fd=destination_fd,
                )
                if destination_before is not None:
                    metadata = enrollment_service.os.stat(
                        destination_text,
                        dir_fd=destination_fd,
                        follow_symlinks=False,
                    )
                    semantic_overwrite_observed = (
                        metadata.st_dev,
                        metadata.st_ino,
                    ) != destination_before
                return 0

            try:
                with patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "_load_atomic_noreplace_primitive",
                    return_value=(overwrite_primitive, 0),
                ), patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "_write_relative_file",
                    wraps=original_write_relative,
                ) as mocked_payload_write:
                    try:
                        write_enrollment_artifacts(
                            requested_output,
                            manifest_bytes=manifest_bytes,
                            summary_bytes=summary_bytes,
                        )
                    except EnrollmentError:
                        rejected = True

                self.assertEqual(
                    {
                        "semantic_overwrite_observed": (
                            semantic_overwrite_observed
                        ),
                        "rejected": rejected,
                        "payload_write_calls": mocked_payload_write.call_count,
                    },
                    {
                        "semantic_overwrite_observed": True,
                        "rejected": True,
                        "payload_write_calls": 0,
                    },
                )
            finally:
                for child in list(parent.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()

    def test_cleanup_never_rmdirs_a_scanned_owned_name(self):
        event = _make_event(slug="writer-cleanup-rmdir-safety")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve() / "parent"
            parent.mkdir()
            requested_output = parent / "artifact"
            original_os_rmdir = enrollment_service.os.rmdir
            rmdir_calls: list[tuple[tuple, dict]] = []
            writer_error = ""

            def reject_scanned_rmdir(*args, **kwargs):
                rmdir_calls.append((args, kwargs))
                raise AssertionError(
                    "cleanup must not rmdir a name learned by directory scan"
                )

            try:
                with patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "_verify_parent_path",
                    side_effect=EnrollmentError("forced publish failure"),
                ), patch(
                    "stable.services.race_event_lifecycle_enrollment.os.rmdir",
                    side_effect=reject_scanned_rmdir,
                ) as mocked_rmdir:
                    supported_dir_fd = set(enrollment_service.os.supports_dir_fd)
                    supported_dir_fd.add(mocked_rmdir)
                    with patch.object(
                        enrollment_service.os,
                        "supports_dir_fd",
                        supported_dir_fd,
                    ):
                        try:
                            write_enrollment_artifacts(
                                requested_output,
                                manifest_bytes=manifest_bytes,
                                summary_bytes=summary_bytes,
                            )
                        except EnrollmentError as exc:
                            writer_error = f"EnrollmentError: {exc}"
                        except Exception as exc:
                            writer_error = f"{type(exc).__name__}: {exc}"

                owned_staging = sorted(parent.glob(".artifact.tmp-*"))
                staging_entries = {
                    staging.name: sorted(
                        str(path.relative_to(staging))
                        for path in staging.rglob("*")
                    )
                    for staging in owned_staging
                }
                self.assertEqual(
                    {
                        "writer_error": writer_error,
                        "rmdir_call_count": len(rmdir_calls),
                        "output_exists": requested_output.exists(),
                        "staging_count": len(owned_staging),
                        "staging_entries": staging_entries,
                    },
                    {
                        "writer_error": "EnrollmentError: forced publish failure",
                        "rmdir_call_count": 0,
                        "output_exists": False,
                        "staging_count": 1,
                        "staging_entries": {
                            staging.name: [] for staging in owned_staging
                        },
                    },
                )
            finally:
                enrollment_service.os.rmdir = original_os_rmdir
                if requested_output.exists():
                    shutil.rmtree(requested_output)
                for staging in parent.glob(".artifact.tmp-*"):
                    shutil.rmtree(staging)

    def test_post_rename_verification_failure_removes_public_output_name(self):
        event = _make_event(slug="writer-post-rename-verify-failure")
        manifest_bytes, summary_bytes = build_enrollment_artifacts(
            event_ids=[event.pk],
            approved_commit=APPROVED_COMMIT,
        )
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve() / "parent"
            parent.mkdir()
            requested_output = parent / "artifact"
            original_verify = enrollment_service._verify_parent_path
            verify_calls = 0
            rejected = False
            retry_succeeded = False

            def fail_only_after_publish(directory, expected):
                nonlocal verify_calls
                verify_calls += 1
                if verify_calls == 1:
                    return original_verify(directory, expected)
                raise EnrollmentError("forced post-rename verification failure")

            try:
                with patch(
                    "stable.services.race_event_lifecycle_enrollment."
                    "_verify_parent_path",
                    side_effect=fail_only_after_publish,
                ):
                    try:
                        write_enrollment_artifacts(
                            requested_output,
                            manifest_bytes=manifest_bytes,
                            summary_bytes=summary_bytes,
                        )
                    except EnrollmentError:
                        rejected = True

                output_absent_after_failure = not requested_output.exists()
                sensitive_files_after_failure = sorted(
                    str(path.relative_to(parent))
                    for path in parent.rglob("*")
                    if path.is_file()
                    and path.name in {"manifest.json", "summary.json"}
                )
                if output_absent_after_failure:
                    write_enrollment_artifacts(
                        requested_output,
                        manifest_bytes=manifest_bytes,
                        summary_bytes=summary_bytes,
                    )
                    retry_succeeded = (
                        (requested_output / "manifest.json").is_file()
                        and (requested_output / "summary.json").is_file()
                    )

                self.assertEqual(
                    {
                        "verify_calls": verify_calls,
                        "rejected": rejected,
                        "output_absent_after_failure": (
                            output_absent_after_failure
                        ),
                        "sensitive_files_after_failure": (
                            sensitive_files_after_failure
                        ),
                        "retry_succeeded": retry_succeeded,
                    },
                    {
                        "verify_calls": 2,
                        "rejected": True,
                        "output_absent_after_failure": True,
                        "sensitive_files_after_failure": [],
                        "retry_succeeded": True,
                    },
                )
            finally:
                for child in list(parent.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()

    def test_manifest_mutation_during_read_is_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "manifest.json"
            path.write_bytes(b"x" * (128 * 1024))
            original_read = os.read
            mutated = False

            def mutate_after_first_read(descriptor, size):
                nonlocal mutated
                chunk = original_read(descriptor, size)
                if chunk and not mutated:
                    mutated = True
                    with path.open("ab") as manifest_file:
                        manifest_file.write(b"changed-during-read")
                return chunk

            with patch(
                "stable.services.race_event_lifecycle_enrollment.os.read",
                side_effect=mutate_after_first_read,
            ):
                with self.assertRaises(EnrollmentError):
                    read_manifest_bytes(path)
        self.assertTrue(mutated, "test did not mutate the open manifest")

    def test_reconcile_rejects_oversize_manifest_before_reading_contents(self):
        with TemporaryDirectory() as tmp:
            oversized = Path(tmp) / "oversized.json"
            oversized.write_bytes(
                b'{"schema_version":2,"padding":"'
                + b"x" * (1024 * 1024)
                + b'"}'
            )
            with patch.object(
                Path,
                "read_bytes",
                side_effect=AssertionError(
                    "oversized manifest content must not be read"
                ),
            ):
                self.assert_command_rejected(
                    lambda: call_command(
                        "reconcile_race_event_lifecycle_controls",
                        "--manifest-file",
                        str(oversized),
                        "--manifest-sha256",
                        "b" * 64,
                        "--expected-commit",
                        APPROVED_COMMIT,
                    )
                )
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)

    def test_v2_apply_rejects_every_non_strict_false_off_setting(self):
        event = _make_event(slug="closed-gate")
        combinations = (
            (True, "shadow"),
            (True, "off"),
            (False, "shadow"),
            (True, "enforce"),
        )
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [event])
            for enabled, mode in combinations:
                with self.subTest(enabled=enabled, mode=mode):
                    with override_settings(
                        RACE_EVENT_LIFECYCLE_ENABLED=enabled,
                        RACE_EVENT_LIFECYCLE_MODE=mode,
                    ):
                        self.assert_command_rejected(
                            lambda: self._reconcile(path, sha, apply=True)
                        )
                    self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)
                    self.assertEqual(
                        RaceEventLifecycleTransition.objects.count(), 0
                    )

    def test_dry_run_and_apply_both_reject_event_drift(self):
        event = _make_event(slug="drift-parity")
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [event])
            RaceEvent.objects.filter(pk=event.pk).update(status="cancelled")
            self.assert_command_rejected(lambda: self._reconcile(path, sha))
            self.assert_command_rejected(
                lambda: self._reconcile(path, sha, apply=True)
            )
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_apply_creates_entire_batch_as_shadow_generation_one(self):
        first = _make_event(slug="batch-first")
        second = _make_event(slug="batch-second")
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [second, first])
            self._reconcile(path, sha, apply=True)
        controls = list(
            RaceEventLifecycleControl.objects.order_by("event_id").values(
                "event_id", "mode", "schedule_generation"
            )
        )
        self.assertEqual(
            controls,
            [
                {
                    "event_id": first.pk,
                    "mode": "shadow",
                    "schedule_generation": 1,
                },
                {
                    "event_id": second.pk,
                    "mode": "shadow",
                    "schedule_generation": 1,
                },
            ],
        )
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_non_key_p2_apply_creates_shadow_generation_one(self):
        event = _make_event(
            slug="apply-non-key-p2",
            priority="P2",
            is_featured=False,
            race_datetime=datetime(
                2026, 8, 2, 6, 0, tzinfo=dt_timezone.utc
            ),
        )
        self.assertFalse(event.is_key_race)

        with TemporaryDirectory() as tmp:
            path, manifest, sha = self._prepare(Path(tmp), [event])
            self._reconcile(path, sha, apply=True)

        snapshot = manifest["events"][str(event.pk)]
        control = RaceEventLifecycleControl.objects.get(event=event)
        self.assertFalse(snapshot["eligibility"]["is_key_race"])
        self.assertEqual(control.mode, "shadow")
        self.assertEqual(control.schedule_generation, 1)
        self.assertEqual(control.enrollment_manifest_sha256, sha)
        self.assertEqual(
            control.manifest_data["content_sha256"],
            manifest["content_sha256"],
        )
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_closed_data_sync_control_is_adopted_by_exact_cas_and_replays(self):
        event = _make_event(
            slug="adopt-data-sync-control",
            race_datetime=datetime(
                2026, 8, 31, 6, 0, tzinfo=dt_timezone.utc
            ),
            local_date=date(2026, 8, 31),
        )
        control = _make_data_sync_control(event, schedule_generation=2)

        with TemporaryDirectory() as tmp:
            path, manifest, sha = self._prepare(Path(tmp), [event])
            before = list(
                RaceEventLifecycleControl.objects.filter(event=event).values()
            )
            dry_run = preflight_enrollment(
                load_enrollment_manifest(
                    path,
                    expected_raw_sha256=sha,
                    expected_commit=APPROVED_COMMIT,
                )
            )
            self.assertEqual(dry_run.outcomes[event.pk], "would_adopt")
            self.assertEqual(dry_run.would_adopt, 1)
            self.assertEqual(
                list(
                    RaceEventLifecycleControl.objects.filter(event=event).values()
                ),
                before,
            )

            self._reconcile(path, sha, apply=True)
            first_updated_at = control.updated_at
            control.refresh_from_db()
            first_updated_at = control.updated_at
            self._reconcile(path, sha, apply=True)

        snapshot = manifest["events"][str(event.pk)]
        self.assertEqual(
            snapshot["expected_control"]["state"], "data_sync_off"
        )
        control.refresh_from_db()
        self.assertEqual(control.mode, "shadow")
        self.assertEqual(control.schedule_generation, 2)
        self.assertEqual(control.enrollment_manifest_sha256, sha)
        self.assertEqual(control.updated_at, first_updated_at)
        self.assertEqual(
            control.manifest_data["race_data_sync"]["manifest_sha256"],
            DATA_SYNC_MANIFEST,
        )
        self.assertEqual(control.manifest_data["schema_version"], 2)
        self.assertEqual(
            RaceEventProjectionControl.objects.get(event=event).write_owner,
            "data_sync",
        )
        tracking = RaceEventLiveTracking.objects.get(event=event)
        self.assertEqual(tracking.claim_generation, 4)
        self.assertEqual(tracking.lock_version, 1)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_data_sync_claim_drift_rejects_adoption_without_writes(self):
        event = _make_event(
            slug="adopt-data-sync-claim-drift",
            race_datetime=datetime(
                2026, 8, 31, 7, 0, tzinfo=dt_timezone.utc
            ),
            local_date=date(2026, 8, 31),
        )
        control = _make_data_sync_control(event)
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [event])
            tracking = RaceEventLiveTracking.objects.get(event=event)
            tracking.active_attempt_token = "active-token"
            tracking.claim_expires_at = datetime(
                2026, 8, 31, 8, 0, tzinfo=dt_timezone.utc
            )
            tracking.save(
                update_fields=(
                    "active_attempt_token",
                    "claim_expires_at",
                    "updated_at",
                )
            )
            with self.assertRaisesRegex(
                EnrollmentError, "已存在不同或漂移"
            ):
                apply_enrollment(
                    load_enrollment_manifest(
                        path,
                        expected_raw_sha256=sha,
                        expected_commit=APPROVED_COMMIT,
                    )
                )

        control.refresh_from_db()
        self.assertEqual(control.mode, "off")
        self.assertEqual(control.enrollment_manifest_sha256, "")
        self.assertNotIn("schema_version", control.manifest_data)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_adopted_control_claim_generation_drift_rejects_replay(self):
        event = _make_event(
            slug="adopted-control-claim-drift",
            race_datetime=datetime(
                2026, 8, 31, 7, 30, tzinfo=dt_timezone.utc
            ),
            local_date=date(2026, 8, 31),
        )
        _make_data_sync_control(event)
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [event])
            self._reconcile(path, sha, apply=True)
            control = RaceEventLifecycleControl.objects.get(event=event)
            control.claim_generation = 1
            control.save(update_fields=("claim_generation", "updated_at"))

            with self.assertRaisesRegex(
                EnrollmentError, "已存在不同或漂移"
            ):
                apply_enrollment(
                    load_enrollment_manifest(
                        path,
                        expected_raw_sha256=sha,
                        expected_commit=APPROVED_COMMIT,
                    )
                )

        control.refresh_from_db()
        self.assertEqual(control.claim_generation, 1)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_mixed_key_and_non_key_apply_creates_exact_control_set(self):
        key_event = _make_event(
            slug="apply-mixed-key",
            priority="P0",
            is_featured=False,
            race_datetime=datetime(
                2026, 8, 2, 6, 0, tzinfo=dt_timezone.utc
            ),
        )
        non_key_event = _make_event(
            slug="apply-mixed-non-key",
            priority="P2",
            is_featured=False,
            race_datetime=datetime(
                2026, 8, 2, 7, 0, tzinfo=dt_timezone.utc
            ),
        )
        self.assertTrue(key_event.is_key_race)
        self.assertFalse(non_key_event.is_key_race)

        with TemporaryDirectory() as tmp:
            path, manifest, sha = self._prepare(
                Path(tmp), [non_key_event, key_event]
            )
            self._reconcile(path, sha, apply=True)

        self.assertTrue(
            manifest["events"][str(key_event.pk)]["eligibility"]["is_key_race"]
        )
        self.assertFalse(
            manifest["events"][str(non_key_event.pk)]["eligibility"][
                "is_key_race"
            ]
        )
        self.assertEqual(
            list(
                RaceEventLifecycleControl.objects.order_by("event_id").values_list(
                    "event_id", "mode", "schedule_generation"
                )
            ),
            [
                (key_event.pk, "shadow", 1),
                (non_key_event.pk, "shadow", 1),
            ],
        )
        self.assertEqual(RaceEventLifecycleTransition.objects.count(), 0)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_apply_is_atomic_when_one_event_drifts(self):
        valid = _make_event(slug="atomic-valid")
        drifted = _make_event(slug="atomic-drifted")
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [valid, drifted])
            RaceEvent.objects.filter(pk=drifted.pk).update(
                visibility_status="draft"
            )
            self.assert_command_rejected(
                lambda: self._reconcile(path, sha, apply=True)
            )
        self.assertEqual(RaceEventLifecycleControl.objects.count(), 0)

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_same_manifest_replay_is_exactly_idempotent(self):
        event = _make_event(slug="exact-replay")
        with TemporaryDirectory() as tmp:
            path, _, sha = self._prepare(Path(tmp), [event])
            self._reconcile(path, sha, apply=True)
            before = RaceEventLifecycleControl.objects.values().get()
            before_transition_count = RaceEventLifecycleTransition.objects.count()
            self._reconcile(path, sha, apply=True)
        after = RaceEventLifecycleControl.objects.values().get()
        self.assertEqual(after, before)
        self.assertEqual(
            RaceEventLifecycleTransition.objects.count(),
            before_transition_count,
        )

    @override_settings(
        RACE_EVENT_LIFECYCLE_ENABLED=False,
        RACE_EVENT_LIFECYCLE_MODE="off",
    )
    def test_different_manifest_cannot_update_existing_control(self):
        event = _make_event(slug="manifest-conflict")
        with TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            first_path, _, first_sha = self._prepare(
                parent, [event], dirname="first"
            )
            self._reconcile(first_path, first_sha, apply=True)
            before = RaceEventLifecycleControl.objects.values().get()

            second_path = parent / "second.json"
            second_data = json.loads(first_path.read_text(encoding="utf-8"))
            second_data["expires_at"] = "2026-08-02T00:00:00+00:00"
            second_sha = self._rewrite_manifest(second_path, second_data)
            self.assert_command_rejected(
                lambda: self._reconcile(second_path, second_sha, apply=True)
            )

        self.assertEqual(RaceEventLifecycleControl.objects.values().get(), before)
