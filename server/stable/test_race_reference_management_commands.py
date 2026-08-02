"""Management-command boundaries for Phase B0.1 internal references."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management.base import CommandError
from django.core.management import call_command
from django.test import TestCase

from stable import models as stable_models


def _canonical_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: dict) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class RaceReferenceManagementCommandTests(TestCase):
    def setUp(self):
        self.event = stable_models.RaceEvent.objects.create(
            year=2025,
            slug="reference-cup-2025",
            original_name="Reference Cup",
            chinese_name="参考杯",
            country_region="united_kingdom",
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            status="finished",
            priority="P0",
            visibility_status="published",
            timezone_name="Europe/London",
            local_date=date(2025, 6, 19),
        )
        self.source_url = (
            "https://www.sportinglife.com/racing/results/"
            "2025-06-19/royal-ascot/859381/gold-cup-group-1"
        )

    def _write_targets(self, root: Path) -> Path:
        path = root / "targets.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "event_id": self.event.pk,
                        "provider_event_key": "sl:859381",
                        "source_url": self.source_url,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return path

    def _build_manifest(self, root: Path) -> tuple[Path, dict, str]:
        targets = self._write_targets(root)
        output = root / "manifest.json"
        stdout = StringIO()
        call_command(
            "build_internal_race_reference_manifest",
            source_key="reference_sporting_life",
            targets_file=str(targets),
            output=str(output),
            stdout=stdout,
        )
        manifest = json.loads(output.read_text(encoding="utf-8"))
        return output, manifest, _sha(manifest)

    def _build_multi_manifest(
        self,
        root: Path,
        *,
        event_count: int,
        event_dates: list[date] | None = None,
    ) -> tuple[Path, dict, str]:
        if event_dates is not None:
            self.assertEqual(len(event_dates), event_count)
            self.assertEqual(event_dates[0], self.event.local_date)
        events = [self.event]
        for index in range(1, event_count):
            events.append(
                stable_models.RaceEvent.objects.create(
                    year=2025,
                    slug=f"reference-cup-{index + 1}-2025",
                    original_name=f"Reference Cup {index + 1}",
                    chinese_name=f"参考杯 {index + 1}",
                    country_region="united_kingdom",
                    racecourse="Ascot",
                    grade_text="G1",
                    normalized_grade="G1",
                    surface="turf",
                    status="finished",
                    priority="P0",
                    visibility_status="published",
                    timezone_name="Europe/London",
                    local_date=(
                        event_dates[index]
                        if event_dates is not None
                        else date(2025, 6, 19)
                    ),
                )
            )
        targets = []
        for index, event in enumerate(events):
            race_id = 859381 + index
            targets.append(
                {
                    "event_id": event.pk,
                    "provider_event_key": f"sl:{race_id}",
                    "source_url": (
                        "https://www.sportinglife.com/racing/results/"
                        f"{event.local_date.isoformat()}/royal-ascot/{race_id}/"
                        f"reference-cup-{index + 1}"
                    ),
                }
            )
        targets_path = root / "multi-targets.json"
        targets_path.write_bytes(_canonical_bytes(targets))
        output = root / "multi-manifest.json"
        call_command(
            "build_internal_race_reference_manifest",
            source_key="reference_sporting_life",
            targets_file=str(targets_path),
            output=str(output),
        )
        manifest = json.loads(output.read_text(encoding="utf-8"))
        return output, manifest, _sha(manifest)

    def _write_manifest_with_parser(
        self,
        root: Path,
        manifest: dict,
        *,
        name: str,
        version: str,
    ) -> tuple[Path, dict, str]:
        forged = json.loads(json.dumps(manifest))
        forged["parser"] = {"name": name, "version": version}
        path = root / f"manifest-{name}-{version}.json"
        path.write_bytes(_canonical_bytes(forged))
        return path, forged, _sha(forged)

    def _collect_valid_artifact(
        self,
        root: Path,
        *,
        event_count: int = 1,
        parser_fails: bool = False,
    ) -> tuple[Path, str, Path, str]:
        if event_count == 1:
            manifest_path, manifest, manifest_sha = self._build_manifest(root)
        else:
            manifest_path, manifest, manifest_sha = self._build_multi_manifest(
                root,
                event_count=event_count,
            )
        output_dir = root / "artifact"
        events_by_url = {
            event["source_url"]: event for event in manifest["events"]
        }

        def fetch_side_effect(url, **_kwargs):
            event = events_by_url[url]
            return (
                f"<html>event {event['event_id']}</html>".encode(),
                {
                    "status": 200,
                    "final_url": url,
                    "redirect_chain": [],
                    "headers": {"Content-Type": "text/html"},
                },
            )

        def parser_side_effect(_raw, _source_url, context):
            if parser_fails:
                raise RuntimeError("controlled parser failure")
            race_id = context["race_id"]
            return {
                "provider_event_key": f"sl:{race_id}",
                "race": {
                    "source_race_name": "Reference Cup page",
                    "source_racecourse": "royal-ascot",
                    "local_date": "2025-06-19",
                    "source_start_time": "15:40",
                },
                "runners": [],
                "completeness": {
                    "race_identity": "complete",
                    "runners": "unknown",
                    "results": "partial",
                    "gap_codes": ["results_partial"],
                },
                "legacy_payload_sha256": "1" * 64,
            }

        with patch(
            "stable.race_event_safe_http.fetch_https",
            side_effect=fetch_side_effect,
        ), patch(
            "runtime.tools.race_reference_parsers.sporting_life.parse_reference_page",
            side_effect=parser_side_effect,
        ):
            call_command(
                "collect_internal_race_references",
                manifest_file=str(manifest_path),
                manifest_sha256=manifest_sha,
                output_dir=str(output_dir),
                max_requests=event_count,
                allow_network=True,
            )
        artifact_sha = (output_dir / "COMPLETE").read_text(
            encoding="ascii"
        ).strip()
        return manifest_path, manifest_sha, output_dir, artifact_sha

    def _resign_artifact_ledger(
        self,
        artifact_dir: Path,
        ledger_rows: list[dict],
    ) -> str:
        ledger_body = b"".join(_canonical_bytes(row) + b"\n" for row in ledger_rows)
        ledger_path = artifact_dir / "request_ledger.jsonl"
        ledger_path.write_bytes(ledger_body)
        ledger_sha = hashlib.sha256(ledger_body).hexdigest()

        artifact_path = artifact_dir / "artifact.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["request_ledger_jsonl_sha256"] = ledger_sha
        for entry in artifact["files"]:
            if entry["path"] == "request_ledger.jsonl":
                entry["size"] = len(ledger_body)
                entry["sha256"] = ledger_sha
                break
        artifact_body = _canonical_bytes(artifact)
        artifact_sha = hashlib.sha256(artifact_body).hexdigest()
        artifact_path.write_bytes(artifact_body)
        (artifact_dir / "COMPLETE").write_text(
            artifact_sha + "\n",
            encoding="ascii",
        )
        return artifact_sha

    def _resign_artifact_references(
        self,
        artifact_dir: Path,
        observations: list[dict],
    ) -> str:
        references_body = b"".join(
            _canonical_bytes(observation) + b"\n"
            for observation in observations
        )
        references_path = artifact_dir / "references.jsonl"
        references_path.write_bytes(references_body)
        references_sha = hashlib.sha256(references_body).hexdigest()

        artifact_path = artifact_dir / "artifact.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["references_jsonl_sha256"] = references_sha
        for entry in artifact["files"]:
            if entry["path"] == "references.jsonl":
                entry["size"] = len(references_body)
                entry["sha256"] = references_sha
                break
        artifact_body = _canonical_bytes(artifact)
        artifact_sha = hashlib.sha256(artifact_body).hexdigest()
        artifact_path.write_bytes(artifact_body)
        (artifact_dir / "COMPLETE").write_text(
            artifact_sha + "\n",
            encoding="ascii",
        )
        return artifact_sha

    def _resign_artifact_metadata(
        self,
        artifact_dir: Path,
        **updates,
    ) -> str:
        artifact_path = artifact_dir / "artifact.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact.update(updates)
        artifact_body = _canonical_bytes(artifact)
        artifact_sha = hashlib.sha256(artifact_body).hexdigest()
        artifact_path.write_bytes(artifact_body)
        (artifact_dir / "COMPLETE").write_text(
            artifact_sha + "\n",
            encoding="ascii",
        )
        return artifact_sha

    def _write_complete_artifact(
        self,
        root: Path,
        *,
        manifest_path: Path,
        manifest_sha: str,
    ) -> tuple[Path, str]:
        artifact_dir = root / "artifact"
        (artifact_dir / "raw").mkdir(parents=True)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_event = manifest["events"][0]
        raw_relative = f"raw/{manifest_event['event_id']}.body"
        raw_body = b"<html></html>"
        raw_sha = hashlib.sha256(raw_body).hexdigest()
        generated_at = datetime.fromisoformat(manifest["generated_at"])
        fetched_at = generated_at + timedelta(minutes=1)
        completed_at = fetched_at + timedelta(minutes=1)
        race = {
            "source_race_name": manifest_event["original_name"],
            "source_racecourse": "royal-ascot",
            "local_date": manifest_event["local_date"],
            "source_start_time": "15:40",
        }
        observation = {
            "payload": {
                "schema_version": 1,
                "source_key": manifest["source_key"],
                "country_region": manifest_event["country_region"],
                "provider_event_key": manifest_event["provider_event_key"],
                "race": race,
                "runners": [],
                "completeness": {
                    "race_identity": "complete",
                    "runners": "complete",
                    "results": "complete",
                    "gap_codes": [],
                },
            },
            "provenance": {
                "source_url": manifest_event["source_url"],
                "final_url": manifest_event["source_url"],
                "source_observed_at": None,
                "fetched_at": fetched_at.isoformat(),
                "parser": manifest["parser"],
                "legacy_payload_sha256": "1" * 64,
                "raw_sha256": raw_sha,
                "source_cache_ref": raw_relative,
            },
            "event_id": manifest_event["event_id"],
            "match_status": "matched",
            "match_confidence": 100,
            "match_evidence": {
                "provider_event_key": manifest_event["provider_event_key"],
                "page_race": race,
            },
            "classification_version": "test-v1",
        }
        references_body = _canonical_bytes(observation) + b"\n"
        ledger_body = _canonical_bytes(
            {
                "event_id": manifest_event["event_id"],
                "local_date": manifest_event["local_date"],
                "source_url": manifest_event["source_url"],
                "final_url": manifest_event["source_url"],
                "status": 200,
                "redirect_chain": [],
                "raw_sha256": raw_sha,
                "fetched_at": fetched_at.isoformat(),
                "outcome": "parsed",
                "phase": "parse",
                "request_issued": True,
            }
        ) + b"\n"
        files = {
            raw_relative: raw_body,
            "manifest.json": manifest_path.read_bytes(),
            "references.jsonl": references_body,
            "request_ledger.jsonl": ledger_body,
        }
        file_entries = []
        for relative_path, body in files.items():
            path = artifact_dir / relative_path
            path.write_bytes(body)
            file_entries.append(
                {
                    "path": relative_path,
                    "size": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
        artifact = {
            "schema_version": 1,
            "manifest_sha256": manifest_sha,
            "reference_schema_version": 1,
            "parser": manifest["parser"],
            "files": file_entries,
            "responses": [
                {
                    "event_id": manifest_event["event_id"],
                    "raw_sha256": raw_sha,
                }
            ],
            "references_jsonl_sha256": hashlib.sha256(
                references_body
            ).hexdigest(),
            "request_ledger_jsonl_sha256": hashlib.sha256(ledger_body).hexdigest(),
            "completed_at": completed_at.isoformat(),
        }
        artifact_bytes = _canonical_bytes(artifact)
        artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
        (artifact_dir / "artifact.json").write_bytes(artifact_bytes)
        (artifact_dir / "COMPLETE").write_text(artifact_sha + "\n", encoding="ascii")
        return artifact_dir, artifact_sha

    def _create_report_run(
        self,
        *,
        local_date_from: date,
        local_date_to: date,
        digest_digit: int,
    ):
        observed_at = datetime(2025, 6, 19, 12, 0, tzinfo=dt_timezone.utc)
        return stable_models.RaceReferenceCollectionRun.objects.create(
            source_key="reference_sporting_life",
            country_region="united_kingdom",
            parser_name="sporting_life",
            parser_version="reference-v1",
            scope_manifest_sha256=f"{digest_digit:064x}",
            local_date_from=local_date_from,
            local_date_to=local_date_to,
            target_count=3,
            status="finished",
            trigger_kind="management_command",
            started_at=observed_at,
            finished_at=observed_at,
            artifact_sha256=f"{digest_digit + 1:064x}",
        )

    def _create_report_receipt(
        self,
        *,
        run,
        suffix: int,
        local_date: date,
        match_status: str,
        snapshot_event_id: int,
        event=None,
    ):
        provider_key = f"sl:{859380 + suffix}"
        structured = {
            "schema_version": 1,
            "source_key": "reference_sporting_life",
            "country_region": "united_kingdom",
            "provider_event_key": provider_key,
            "race": {
                "source_race_name": f"Reference Cup {suffix}",
                "source_racecourse": "royal-ascot",
                "local_date": local_date.isoformat(),
                "source_start_time": "15:40",
            },
            "runners": [],
            "completeness": {
                "race_identity": "complete",
                "runners": "complete",
                "results": "complete",
                "gap_codes": [],
            },
        }
        payload = stable_models.RaceReferencePayload.objects.create(
            source_key="reference_sporting_life",
            provider_event_key=provider_key,
            observation_key=f"reference_sporting_life:{provider_key}",
            payload_sha256=f"{suffix + 10:064x}",
            structured_payload=structured,
        )
        return stable_models.RaceReferenceReceipt.objects.create(
            run=run,
            payload=payload,
            source_url=self.source_url,
            final_url=self.source_url,
            source_observed_at=None,
            fetched_at=datetime(
                local_date.year,
                local_date.month,
                local_date.day,
                12,
                5,
                tzinfo=dt_timezone.utc,
            ),
            parser_name="sporting_life",
            parser_version="reference-v1",
            legacy_payload_sha256=f"{suffix + 20:064x}",
            raw_sha256=f"{suffix + 30:064x}",
            source_cache_ref=f"raw/{snapshot_event_id}-{suffix}.body",
            provenance_sha256=f"{suffix + 40:064x}",
            event=event,
            match_status=match_status,
            match_confidence=100 if match_status == "matched" else 0,
            match_evidence={"provider_event_key": provider_key},
            event_snapshot={
                "event_id": snapshot_event_id,
                "local_date": local_date.isoformat(),
            },
            event_snapshot_sha256=f"{suffix + 50:064x}",
            classification_version="test-v1",
            is_partial=False,
            gap_codes=[],
        )

    def test_build_manifest_is_read_only_and_binds_frozen_event_snapshot(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = stable_models.RaceEvent.objects.count()
            output, manifest, manifest_sha = self._build_manifest(root)
            output_sha = hashlib.sha256(output.read_bytes()).hexdigest()

        self.assertEqual(stable_models.RaceEvent.objects.count(), before)
        self.assertEqual(manifest["purpose"], "internal_reference_post_race")
        self.assertEqual(manifest["events"][0]["event_id"], self.event.pk)
        self.assertEqual(manifest["events"][0]["status"], "finished")
        self.assertEqual(len(manifest["events"][0]["event_snapshot_sha256"]), 64)
        self.assertEqual(output_sha, manifest_sha)

    def test_build_fails_closed_when_parser_module_identity_drifts(self):
        parser = importlib.import_module(
            "stable.race_reference_parsers.sporting_life"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "manifest.json"
            with patch.object(
                parser,
                "PARSER_VERSION",
                "drifted-reference-v2",
            ), self.assertRaises(CommandError):
                call_command(
                    "build_internal_race_reference_manifest",
                    source_key="reference_sporting_life",
                    targets_file=str(self._write_targets(root)),
                    output=str(output),
                )

            self.assertFalse(output.exists())

    def test_manifest_validation_rejects_nonempty_forged_parser_identity(self):
        service = importlib.import_module("stable.services.race_reference_sources")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _path, manifest, _manifest_sha = self._build_manifest(root)
            _forged_path, forged, forged_sha = self._write_manifest_with_parser(
                root,
                manifest,
                name="sporting_life",
                version="forged-but-nonempty-v99",
            )

            with self.assertRaises(ValidationError):
                service.validate_reference_manifest(
                    forged,
                    manifest_sha256=forged_sha,
                )

    def test_build_rejects_extra_target_fields_duplicates_and_non_finished_event(self):
        invalid_targets = (
            [
                {
                    "event_id": self.event.pk,
                    "provider_event_key": "sl:859381",
                    "source_url": self.source_url,
                    "extra": True,
                }
            ],
            [
                {
                    "event_id": self.event.pk,
                    "provider_event_key": "sl:859381",
                    "source_url": self.source_url,
                }
            ]
            * 2,
        )
        for index, targets in enumerate(invalid_targets):
            with self.subTest(index=index), TemporaryDirectory() as tmp:
                root = Path(tmp)
                targets_path = root / "targets.json"
                targets_path.write_text(json.dumps(targets), encoding="utf-8")
                with self.assertRaises((CommandError, SystemExit)) as raised:
                    call_command(
                        "build_internal_race_reference_manifest",
                        source_key="reference_sporting_life",
                        targets_file=str(targets_path),
                        output=str(root / "manifest.json"),
                    )
                self.assertNotIn("Unknown command", str(raised.exception))

        self.event.status = "scheduled"
        self.event.save(update_fields={"status"})
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises((CommandError, SystemExit)) as raised:
                call_command(
                    "build_internal_race_reference_manifest",
                    source_key="reference_sporting_life",
                    targets_file=str(self._write_targets(root)),
                    output=str(root / "manifest.json"),
                )
            self.assertNotIn("Unknown command", str(raised.exception))

    def test_collect_without_allow_network_never_opens_socket_or_writes_db(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            output_dir = root / "artifact"
            before = {
                model: model.objects.count()
                for model in (
                    stable_models.RaceEvent,
                    stable_models.RaceEventRunner,
                    stable_models.RaceEventResult,
                    stable_models.RaceEventDataCandidate,
                )
            }
            with patch(
                "socket.create_connection",
                side_effect=AssertionError("offline collect must not access network"),
            ):
                with self.assertRaises((CommandError, SystemExit)):
                    call_command(
                        "collect_internal_race_references",
                        manifest_file=str(manifest_path),
                        manifest_sha256=manifest_sha,
                        output_dir=str(output_dir),
                    )

        self.assertEqual(
            {model: model.objects.count() for model in before},
            before,
        )

    def test_collect_rejects_bad_manifest_sha_and_request_limit_above_targets(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            for supplied_sha, max_requests in (("0" * 64, 1), (manifest_sha, 2)):
                with self.subTest(supplied_sha=supplied_sha, max_requests=max_requests):
                    with self.assertRaises((CommandError, SystemExit)):
                        call_command(
                            "collect_internal_race_references",
                            manifest_file=str(manifest_path),
                            manifest_sha256=supplied_sha,
                            output_dir=str(root / f"artifact-{max_requests}-{supplied_sha[0]}"),
                            max_requests=max_requests,
                            allow_network=True,
                        )

    def test_collect_rejects_forged_manifest_parser_before_network_or_writes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest_path, manifest, _manifest_sha = self._build_manifest(root)
            forged_path, _forged, forged_sha = self._write_manifest_with_parser(
                root,
                manifest,
                name="sporting_life",
                version="forged-but-nonempty-v99",
            )
            output_dir = root / "artifact"
            before = {
                model: model.objects.count()
                for model in (
                    stable_models.RaceReferenceCollectionRun,
                    stable_models.RaceReferencePayload,
                    stable_models.RaceReferenceReceipt,
                )
            }
            with patch(
                "stable.race_event_safe_http.fetch_https",
                side_effect=AssertionError(
                    "forged parser identity must fail before network"
                ),
            ), self.assertRaises(CommandError):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(forged_path),
                    manifest_sha256=forged_sha,
                    output_dir=str(output_dir),
                    max_requests=1,
                    allow_network=True,
                )

            self.assertFalse(output_dir.exists())
            self.assertEqual(
                {model: model.objects.count() for model in before},
                before,
            )

    def test_collect_rechecks_loaded_parser_module_identity_before_network(self):
        parser = importlib.import_module(
            "stable.race_reference_parsers.sporting_life"
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            output_dir = root / "artifact"
            with patch.object(
                parser,
                "PARSER_VERSION",
                "drifted-reference-v2",
            ), patch(
                "stable.race_event_safe_http.fetch_https",
                side_effect=AssertionError(
                    "parser module drift must fail before network"
                ),
            ), self.assertRaises(CommandError):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=1,
                    allow_network=True,
                )

            self.assertFalse(output_dir.exists())

    def test_collect_rejects_timeout_override_other_than_fifteen_before_network(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            output_dir = root / "artifact"
            with patch(
                "stable.race_event_safe_http.fetch_https",
                side_effect=AssertionError(
                    "invalid timeout must fail before network"
                ),
            ) as fetch_mock, self.assertRaises((CommandError, TypeError)):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=1,
                    timeout_seconds=14,
                    allow_network=True,
                )

            fetch_mock.assert_not_called()
            self.assertFalse(output_dir.exists())

    def test_parser_schema_and_identity_errors_do_not_open_transport_circuit(self):
        def parsed_payload(provider_event_key: str) -> dict:
            return {
                "provider_event_key": provider_event_key,
                "race": {
                    "source_race_name": "Reference Cup page",
                    "source_racecourse": "royal-ascot",
                    "local_date": "2025-06-19",
                    "source_start_time": "15:40",
                },
                "runners": [],
                "completeness": {
                    "race_identity": "complete",
                    "runners": "unknown",
                    "results": "partial",
                    "gap_codes": ["results_partial"],
                },
                "legacy_payload_sha256": "1" * 64,
            }

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest, manifest_sha = self._build_multi_manifest(
                root,
                event_count=4,
            )
            output_dir = root / "artifact"
            events_by_url = {
                event["source_url"]: event for event in manifest["events"]
            }

            def fetch_side_effect(url, **_kwargs):
                event = events_by_url[url]
                return (
                    f"<html>event {event['event_id']}</html>".encode(),
                    {
                        "status": 200,
                        "final_url": url,
                        "redirect_chain": [],
                        "headers": {"Content-Type": "text/html"},
                    },
                )

            def parser_side_effect(_raw, _source_url, context):
                race_id = context["race_id"]
                provider_key = f"sl:{race_id}"
                if race_id == 859381:
                    raise RuntimeError("controlled parser failure")
                parsed = parsed_payload(provider_key)
                if race_id == 859382:
                    parsed["runners"] = [{"unexpected": "schema failure"}]
                elif race_id == 859383:
                    parsed["provider_event_key"] = "sl:999999"
                return parsed

            with patch(
                "stable.race_event_safe_http.fetch_https",
                side_effect=fetch_side_effect,
            ) as fetch_mock, patch(
                "runtime.tools.race_reference_parsers.sporting_life.parse_reference_page",
                side_effect=parser_side_effect,
            ):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=4,
                    allow_network=True,
                )

            ledger = [
                json.loads(line)
                for line in (output_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            observations = [
                json.loads(line)
                for line in (output_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]

        self.assertEqual(fetch_mock.call_count, 4)
        self.assertNotIn("circuit_open", [row["outcome"] for row in ledger])
        self.assertEqual(ledger[-1]["outcome"], "parsed")
        self.assertEqual(
            observations[0]["payload"]["provider_event_key"],
            "sl:859384",
        )

    def test_parser_failure_preserves_raw_response_for_offline_record_audit(self):
        raw = b"<html>successful HTTP response but parser failed</html>"
        response = {
            "status": 200,
            "final_url": self.source_url,
            "redirect_chain": [],
            "headers": {"Content-Type": "text/html"},
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            output_dir = root / "artifact"
            with patch(
                "stable.race_event_safe_http.fetch_https",
                return_value=(raw, response),
            ), patch(
                "runtime.tools.race_reference_parsers.sporting_life.parse_reference_page",
                side_effect=RuntimeError("controlled parse failure"),
            ):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=1,
                    allow_network=True,
                )

            raw_relative = f"raw/{self.event.pk}.body"
            artifact = json.loads(
                (output_dir / "artifact.json").read_text(encoding="utf-8")
            )
            ledger = [
                json.loads(line)
                for line in (output_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            observations = [
                line
                for line in (output_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]

            self.assertEqual((output_dir / raw_relative).read_bytes(), raw)
            self.assertIn(
                raw_relative,
                {entry["path"] for entry in artifact["files"]},
            )
            self.assertEqual(
                artifact["responses"],
                [
                    {
                        "event_id": self.event.pk,
                        "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                ],
            )
            self.assertEqual(ledger[0]["outcome"], "parse_error")
            self.assertEqual(
                ledger[0]["raw_sha256"],
                hashlib.sha256(raw).hexdigest(),
            )
            self.assertEqual(observations, [])

            artifact_sha = (output_dir / "COMPLETE").read_text(
                encoding="ascii"
            ).strip()
            call_command(
                "record_internal_race_references",
                manifest_file=str(manifest_path),
                manifest_sha256=manifest_sha,
                artifact_dir=str(output_dir),
                artifact_sha256=artifact_sha,
            )

        self.assertEqual(
            stable_models.RaceReferenceCollectionRun.objects.count(),
            1,
        )
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_record_request_count_counts_every_issued_http_request_outcome(self):
        safe_http = importlib.import_module("stable.race_event_safe_http")

        def parsed_payload(provider_event_key: str) -> dict:
            return {
                "provider_event_key": provider_event_key,
                "race": {
                    "source_race_name": self.event.original_name,
                    "source_racecourse": "royal-ascot",
                    "local_date": "2025-06-19",
                    "source_start_time": "15:40",
                },
                "runners": [],
                "completeness": {
                    "race_identity": "complete",
                    "runners": "unknown",
                    "results": "partial",
                    "gap_codes": ["results_partial"],
                },
                "legacy_payload_sha256": "1" * 64,
            }

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest, manifest_sha = self._build_multi_manifest(
                root,
                event_count=5,
            )
            output_dir = root / "artifact"
            events_by_url = {
                event["source_url"]: event for event in manifest["events"]
            }

            def fetch_side_effect(url, **_kwargs):
                race_id = int(
                    events_by_url[url]["provider_event_key"].removeprefix("sl:")
                )
                if race_id == 859382:
                    raise safe_http.SafeHttpError("controlled transport failure")
                if race_id == 859383:
                    raise ValueError("controlled application failure")
                return (
                    f"<html>event {race_id}</html>".encode(),
                    {
                        "status": 200,
                        "final_url": url,
                        "redirect_chain": [],
                        "headers": {"Content-Type": "text/html"},
                    },
                )

            def parser_side_effect(_raw, _source_url, context):
                race_id = context["race_id"]
                if race_id == 859384:
                    raise RuntimeError("controlled parse failure")
                return parsed_payload(f"sl:{race_id}")

            with patch(
                "stable.race_event_safe_http.fetch_https",
                side_effect=fetch_side_effect,
            ) as fetch_mock, patch(
                "runtime.tools.race_reference_parsers.sporting_life.parse_reference_page",
                side_effect=parser_side_effect,
            ):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=4,
                    allow_network=True,
                )

            ledger = [
                json.loads(line)
                for line in (output_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            self.assertEqual(fetch_mock.call_count, 4)
            self.assertEqual(
                [row["outcome"] for row in ledger],
                [
                    "parsed",
                    "transport_error",
                    "application_error",
                    "parse_error",
                    "budget_exhausted",
                ],
            )

            artifact_sha = (output_dir / "COMPLETE").read_text(
                encoding="ascii"
            ).strip()
            call_command(
                "record_internal_race_references",
                manifest_file=str(manifest_path),
                manifest_sha256=manifest_sha,
                artifact_dir=str(output_dir),
                artifact_sha256=artifact_sha,
            )

        run = stable_models.RaceReferenceCollectionRun.objects.get()
        self.assertEqual(run.request_count, 4)
        self.assertEqual(run.error_count, 4)
        error_summary = run.error_summary
        self.assertEqual(error_summary.get("total"), 4)
        self.assertEqual(
            error_summary.get("by_outcome"),
            {
                "application_error": 1,
                "budget_exhausted": 1,
                "parse_error": 1,
                "transport_error": 1,
            },
        )
        details = error_summary.get("details")
        self.assertIsInstance(details, list)
        self.assertLessEqual(len(details), 20)
        self.assertEqual(
            {detail.get("outcome") for detail in details},
            {
                "application_error",
                "budget_exhausted",
                "parse_error",
                "transport_error",
            },
        )
        for detail in details:
            self.assertIsInstance(detail.get("event_id"), int)
            self.assertIn(detail.get("phase"), {"scheduler", "fetch", "parse"})
            self.assertLessEqual(len(detail.get("error") or ""), 500)

    def test_record_error_summary_freezes_dates_for_multiday_no_receipt_report(self):
        safe_http = importlib.import_module("stable.race_event_safe_http")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_multi_manifest(
                root,
                event_count=2,
                event_dates=[
                    date(2025, 6, 19),
                    date(2025, 6, 20),
                ],
            )
            output_dir = root / "artifact"
            with patch(
                "stable.race_event_safe_http.fetch_https",
                side_effect=safe_http.SafeHttpError(
                    "controlled transport failure"
                ),
            ):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=2,
                    allow_network=True,
                )

            artifact_sha = (output_dir / "COMPLETE").read_text(
                encoding="ascii"
            ).strip()
            call_command(
                "record_internal_race_references",
                manifest_file=str(manifest_path),
                manifest_sha256=manifest_sha,
                artifact_dir=str(output_dir),
                artifact_sha256=artifact_sha,
            )
            run = stable_models.RaceReferenceCollectionRun.objects.get()
            details = run.error_summary["details"]
            self.assertEqual(
                [detail.get("local_date") for detail in details],
                ["2025-06-19", "2025-06-20"],
            )
            self.assertEqual(run.error_count, 2)
            self.assertEqual(run.receipts.count(), 0)

            reports = {}
            for report_date in ("2025-06-19", "2025-06-20"):
                output = root / f"errors-{report_date}.json"
                call_command(
                    "report_internal_race_reference_observation",
                    source_key="reference_sporting_life",
                    date_from=report_date,
                    date_to=report_date,
                    output=str(output),
                )
                reports[report_date] = json.loads(
                    output.read_text(encoding="utf-8")
                )

        for report_date in ("2025-06-19", "2025-06-20"):
            with self.subTest(report_date=report_date):
                coverage = reports[report_date]["coverage"]
                self.assertEqual(coverage["runs"], 1)
                self.assertEqual(coverage["errors"], 1)
                self.assertEqual(coverage["unattributed_errors"], 0)
                self.assertEqual(coverage["receipts"], 0)

    def test_collect_preserves_parser_race_identity_in_semantic_payload_and_writes_no_database_rows(
        self,
    ):
        parsed_race = {
            "source_race_name": "Gold Cup page original",
            "source_racecourse": "royal-ascot",
            "local_date": "2025-06-19",
            "source_start_time": "15:40",
        }
        parsed = {
            "provider_event_key": "sl:859381",
            "race": parsed_race,
            "runners": [
                {
                    "source_runner_key": "sl-horse:1",
                    "horse_number": "1",
                    "draw": "4",
                    "horse_name": "Reference Runner",
                    "jockey_name": "Reference Jockey",
                    "trainer_name": "Reference Trainer",
                    "carried_weight": "9-2",
                    "odds_value": "5/2",
                    "running_status": "declared",
                    "source_reported_finish_position": "1",
                    "margin": "",
                }
            ],
            "completeness": {
                "race_identity": "complete",
                "runners": "complete",
                "results": "complete",
                "gap_codes": [],
            },
            "legacy_payload_sha256": "1" * 64,
            "parser_evidence": {
                "race_id": 859381,
                "identity_verified": True,
            },
        }
        raw = b"<html>controlled Sporting Life result</html>"
        response = {
            "status": 200,
            "final_url": self.source_url,
            "redirect_chain": [],
            "headers": {"Content-Type": "text/html"},
        }
        protected_models = (
            stable_models.RaceReferenceCollectionRun,
            stable_models.RaceReferencePayload,
            stable_models.RaceReferenceReceipt,
            stable_models.RaceEvent,
            stable_models.RaceEventRunner,
            stable_models.RaceEventResult,
            stable_models.RaceEventDataCandidate,
            stable_models.RaceEventRevision,
            stable_models.NewsArticle,
            stable_models.QQPushDelivery,
            stable_models.RaceEventLifecycleTransition,
        )
        before = {model: model.objects.count() for model in protected_models}

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest, manifest_sha = self._build_manifest(root)
            self.assertEqual(manifest["events"][0]["racecourse"], "Ascot")
            self.assertEqual(manifest["events"][0]["original_name"], "Reference Cup")
            output_dir = root / "artifact"
            with patch(
                "stable.race_event_safe_http.fetch_https",
                return_value=(raw, response),
            ) as fetch_mock, patch(
                "runtime.tools.race_reference_parsers.sporting_life.parse_reference_page",
                return_value=parsed,
            ):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=1,
                    allow_network=True,
                )
            self.assertEqual(
                fetch_mock.call_args.kwargs.get("allowed_content_types"),
                ("text/html", "application/xhtml+xml"),
            )
            self.assertEqual(fetch_mock.call_args.kwargs.get("timeout"), 15)
            self.assertEqual(
                fetch_mock.call_args.kwargs.get("max_bytes"),
                4 * 1024 * 1024,
            )
            self.assertEqual(
                fetch_mock.call_args.kwargs.get("max_redirects"),
                2,
            )
            rows = [
                json.loads(line)
                for line in (output_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]

        self.assertEqual(len(rows), 1)
        semantic_race = rows[0]["payload"]["race"]
        self.assertEqual(semantic_race["source_racecourse"], "royal-ascot")
        self.assertEqual(semantic_race["source_race_name"], "Gold Cup page original")
        self.assertEqual(
            rows[0]["match_evidence"]["page_race"],
            parsed_race,
        )
        self.assertEqual(
            {model: model.objects.count() for model in protected_models},
            before,
        )

    def test_collect_does_not_mark_parser_page_identity_mismatch_as_matched(self):
        parsed = {
            "provider_event_key": "sl:859381",
            "race": {
                "source_race_name": "Wrong Venue Cup",
                "source_racecourse": "cheltenham",
                "local_date": "2025-06-19",
                "source_start_time": "15:40",
            },
            "runners": [],
            "completeness": {
                "race_identity": "complete",
                "runners": "unknown",
                "results": "unknown",
                "gap_codes": ["page_identity_conflict"],
            },
            "legacy_payload_sha256": "1" * 64,
            "parser_evidence": {
                "race_id": 859381,
                "page_racecourse": "cheltenham",
            },
        }
        response = {
            "status": 200,
            "final_url": self.source_url,
            "redirect_chain": [],
            "headers": {"Content-Type": "text/html"},
        }
        protected_models = (
            stable_models.RaceReferenceCollectionRun,
            stable_models.RaceReferencePayload,
            stable_models.RaceReferenceReceipt,
            stable_models.RaceEventRunner,
            stable_models.RaceEventResult,
            stable_models.RaceEventDataCandidate,
            stable_models.RaceEventRevision,
            stable_models.NewsArticle,
            stable_models.QQPushDelivery,
            stable_models.RaceEventLifecycleTransition,
        )
        before = {model: model.objects.count() for model in protected_models}

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            output_dir = root / "artifact"
            with patch(
                "stable.race_event_safe_http.fetch_https",
                return_value=(b"<html>wrong page identity</html>", response),
            ), patch(
                "runtime.tools.race_reference_parsers.sporting_life.parse_reference_page",
                return_value=parsed,
            ):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=1,
                    allow_network=True,
                )
            observations = [
                json.loads(line)
                for line in (output_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]

        self.assertFalse(
            any(
                row["match_status"] == "matched"
                and row["match_confidence"] == 100
                for row in observations
            ),
            "page race identity conflict must be error/source_only/unmatched, never matched=100",
        )
        self.assertEqual(
            {model: model.objects.count() for model in protected_models},
            before,
        )

    def test_collect_downgrades_conflicting_race_name_to_source_only(self):
        parsed = {
            "provider_event_key": "sl:859381",
            "race": {
                "source_race_name": "Prince of Wales's Stakes",
                "source_racecourse": "royal-ascot",
                "local_date": "2025-06-19",
                "source_start_time": "15:40",
            },
            "runners": [],
            "completeness": {
                "race_identity": "complete",
                "runners": "complete",
                "results": "complete",
                "gap_codes": [],
            },
            "legacy_payload_sha256": "1" * 64,
        }
        response = {
            "status": 200,
            "final_url": self.source_url,
            "redirect_chain": [],
            "headers": {"Content-Type": "text/html"},
        }

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            output_dir = root / "artifact"
            with patch(
                "stable.race_event_safe_http.fetch_https",
                return_value=(b"<html>different race</html>", response),
            ), patch(
                "runtime.tools.race_reference_parsers.sporting_life.parse_reference_page",
                return_value=parsed,
            ):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=1,
                    allow_network=True,
                )
            observations = [
                json.loads(line)
                for line in (output_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["match_status"], "source_only")
        self.assertIsNone(observations[0]["event_id"])
        self.assertEqual(observations[0]["match_confidence"], 0)
        self.assertFalse(
            any(
                observation["match_status"] == "matched"
                for observation in observations
            )
        )

    def test_collect_accepts_frozen_active_alias_after_identity_normalization(self):
        stable_models.RaceEventAlias.objects.create(
            event=self.event,
            text="Ｋｉｎｇ—George   Stakes",
            source_language="en",
            alias_type="manual-reviewed",
            source="operator",
            is_active=True,
        )
        parsed = {
            "provider_event_key": "sl:859381",
            "race": {
                "source_race_name": "King George Stakes",
                "source_racecourse": "royal-ascot",
                "local_date": "2025-06-19",
                "source_start_time": "15:40",
            },
            "runners": [],
            "completeness": {
                "race_identity": "complete",
                "runners": "complete",
                "results": "complete",
                "gap_codes": [],
            },
            "legacy_payload_sha256": "1" * 64,
        }
        response = {
            "status": 200,
            "final_url": self.source_url,
            "redirect_chain": [],
            "headers": {"Content-Type": "text/html"},
        }

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest, manifest_sha = self._build_manifest(root)
            self.assertIn(
                "king george stakes",
                manifest["events"][0]["normalized_accepted_race_names"],
            )
            output_dir = root / "artifact"
            with patch(
                "stable.race_event_safe_http.fetch_https",
                return_value=(b"<html>accepted alias</html>", response),
            ), patch(
                "runtime.tools.race_reference_parsers.sporting_life.parse_reference_page",
                return_value=parsed,
            ):
                call_command(
                    "collect_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    output_dir=str(output_dir),
                    max_requests=1,
                    allow_network=True,
                )
            observations = [
                json.loads(line)
                for line in (output_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["match_status"], "matched")
        self.assertEqual(observations[0]["event_id"], self.event.pk)
        self.assertEqual(observations[0]["match_confidence"], 100)

    def test_record_command_is_offline_and_rejects_incomplete_artifact(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            artifact_dir = root / "artifact"
            artifact_dir.mkdir()
            (artifact_dir / "artifact.json").write_text("{}", encoding="utf-8")
            with patch(
                "socket.create_connection",
                side_effect=AssertionError("record must always be offline"),
            ):
                with self.assertRaises((CommandError, SystemExit)):
                    call_command(
                        "record_internal_race_references",
                        manifest_file=str(manifest_path),
                        manifest_sha256=manifest_sha,
                        artifact_dir=str(artifact_dir),
                        artifact_sha256="0" * 64,
                    )

        for model_name in (
            "RaceReferenceCollectionRun",
            "RaceReferencePayload",
            "RaceReferenceReceipt",
        ):
            model = getattr(stable_models, model_name)
            self.assertEqual(model.objects.count(), 0)

    def test_record_rejects_forged_manifest_parser_before_artifact_reads_or_writes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest_path, manifest, _manifest_sha = self._build_manifest(root)
            forged_path, _forged, forged_sha = self._write_manifest_with_parser(
                root,
                manifest,
                name="sporting_life",
                version="forged-but-nonempty-v99",
            )
            before = {
                model: model.objects.count()
                for model in (
                    stable_models.RaceReferenceCollectionRun,
                    stable_models.RaceReferencePayload,
                    stable_models.RaceReferenceReceipt,
                )
            }
            with patch(
                "stable.management.commands.record_internal_race_references._read_regular",
                side_effect=AssertionError(
                    "forged parser identity must fail before artifact reads"
                ),
            ), self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(forged_path),
                    manifest_sha256=forged_sha,
                    artifact_dir=str(root / "missing-artifact"),
                    artifact_sha256="0" * 64,
                )

            self.assertEqual(
                {model: model.objects.count() for model in before},
                before,
            )

    def _assert_record_rejects_ledger_variant(self, variant: str) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                manifest_path,
                manifest_sha,
                artifact_dir,
                _artifact_sha,
            ) = self._collect_valid_artifact(root, event_count=2)
            ledger_rows = [
                json.loads(line)
                for line in (artifact_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            if variant == "empty":
                ledger_rows = []
            elif variant == "truncated":
                ledger_rows = ledger_rows[:1]
            elif variant == "duplicate":
                ledger_rows = [ledger_rows[0], ledger_rows[0]]
            else:
                self.fail(f"unknown ledger variant: {variant}")
            artifact_sha = self._resign_artifact_ledger(
                artifact_dir,
                ledger_rows,
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_record_rejects_empty_ledger_after_artifact_resigning(self):
        self._assert_record_rejects_ledger_variant("empty")

    def test_record_rejects_truncated_ledger_after_artifact_resigning(self):
        self._assert_record_rejects_ledger_variant("truncated")

    def test_record_rejects_duplicate_ledger_event_after_artifact_resigning(self):
        self._assert_record_rejects_ledger_variant("duplicate")

    def test_record_rejects_ledger_source_url_different_from_manifest(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                manifest_path,
                manifest_sha,
                artifact_dir,
                _artifact_sha,
            ) = self._collect_valid_artifact(root)
            ledger_rows = [
                json.loads(line)
                for line in (artifact_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            ledger_rows[0]["source_url"] = (
                "https://www.sportinglife.com/racing/results/"
                "2025-06-19/royal-ascot/859382/different-race"
            )
            artifact_sha = self._resign_artifact_ledger(
                artifact_dir,
                ledger_rows,
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)

    def test_record_rejects_parsed_final_url_outside_provider_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                manifest_path,
                manifest_sha,
                artifact_dir,
                _artifact_sha,
            ) = self._collect_valid_artifact(root)
            ledger_rows = [
                json.loads(line)
                for line in (artifact_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            ledger_rows[0]["final_url"] = (
                "https://www.sportinglife.com/racing/results/"
                "2025-06-19/royal-ascot/859382/different-race"
            )
            artifact_sha = self._resign_artifact_ledger(
                artifact_dir,
                ledger_rows,
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)

    def test_record_rejects_parse_error_final_url_outside_provider_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                manifest_path,
                manifest_sha,
                artifact_dir,
                _artifact_sha,
            ) = self._collect_valid_artifact(root, parser_fails=True)
            ledger_rows = [
                json.loads(line)
                for line in (artifact_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            self.assertEqual(ledger_rows[0]["outcome"], "parse_error")
            ledger_rows[0]["final_url"] = (
                "https://www.sportinglife.com/racing/results/"
                "2025-06-19/royal-ascot/859382/different-race"
            )
            artifact_sha = self._resign_artifact_ledger(
                artifact_dir,
                ledger_rows,
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)

    def test_record_rejects_response_without_parse_phase_ledger_event(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                manifest_path,
                manifest_sha,
                artifact_dir,
                _artifact_sha,
            ) = self._collect_valid_artifact(root)
            ledger_rows = [
                json.loads(line)
                for line in (artifact_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            parsed = ledger_rows[0]
            ledger_rows[0] = {
                "event_id": parsed["event_id"],
                "source_url": parsed["source_url"],
                "fetched_at": parsed["fetched_at"],
                "outcome": "transport_error",
                "phase": "fetch",
                "request_issued": True,
                "error_type": "SafeHttpError",
                "error": "resigned response evidence deletion",
            }
            artifact_sha = self._resign_artifact_ledger(
                artifact_dir,
                ledger_rows,
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)

    def test_record_rejects_any_ledger_timestamp_after_artifact_completion(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                manifest_path,
                manifest_sha,
                artifact_dir,
                _artifact_sha,
            ) = self._collect_valid_artifact(root, event_count=2)
            artifact = json.loads(
                (artifact_dir / "artifact.json").read_text(encoding="utf-8")
            )
            completed_at = datetime.fromisoformat(artifact["completed_at"])
            late_fetched_at = (
                completed_at + timedelta(seconds=1)
            ).isoformat()
            ledger_rows = [
                json.loads(line)
                for line in (artifact_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            observations = [
                json.loads(line)
                for line in (artifact_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            self.assertLessEqual(
                datetime.fromisoformat(ledger_rows[0]["fetched_at"]),
                completed_at,
            )
            ledger_rows[1]["fetched_at"] = late_fetched_at
            observations[1]["provenance"]["fetched_at"] = late_fetched_at
            artifact_sha = self._resign_artifact_ledger(
                artifact_dir,
                ledger_rows,
            )
            artifact_sha = self._resign_artifact_references(
                artifact_dir,
                observations,
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_record_rejects_observation_provenance_drift_from_event_evidence(self):
        for variant in ("fetched_at", "final_url", "source_url"):
            with self.subTest(variant=variant), TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, _manifest, manifest_sha = self._build_manifest(
                    root
                )
                artifact_dir, _artifact_sha = self._write_complete_artifact(
                    root,
                    manifest_path=manifest_path,
                    manifest_sha=manifest_sha,
                )
                ledger = json.loads(
                    (artifact_dir / "request_ledger.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()[0]
                )
                observations = [
                    json.loads(line)
                    for line in (artifact_dir / "references.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line
                ]
                provenance = observations[0]["provenance"]
                if variant == "fetched_at":
                    provenance["fetched_at"] = (
                        datetime.fromisoformat(ledger["fetched_at"])
                        + timedelta(seconds=1)
                    ).isoformat()
                else:
                    provenance[variant] = f"{self.source_url}-drift"
                artifact_sha = self._resign_artifact_references(
                    artifact_dir,
                    observations,
                )

                with self.assertRaises(CommandError):
                    call_command(
                        "record_internal_race_references",
                        manifest_file=str(manifest_path),
                        manifest_sha256=manifest_sha,
                        artifact_dir=str(artifact_dir),
                        artifact_sha256=artifact_sha,
                    )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_record_rejects_observations_swapped_between_event_raw_responses(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                manifest_path,
                manifest_sha,
                artifact_dir,
                _artifact_sha,
            ) = self._collect_valid_artifact(root, event_count=2)
            observations = [
                json.loads(line)
                for line in (artifact_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            first_provenance = observations[0]["provenance"]
            second_provenance = observations[1]["provenance"]
            (
                first_provenance["source_cache_ref"],
                second_provenance["source_cache_ref"],
            ) = (
                second_provenance["source_cache_ref"],
                first_provenance["source_cache_ref"],
            )
            (
                first_provenance["raw_sha256"],
                second_provenance["raw_sha256"],
            ) = (
                second_provenance["raw_sha256"],
                first_provenance["raw_sha256"],
            )
            artifact_sha = self._resign_artifact_references(
                artifact_dir,
                observations,
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_record_rejects_parse_error_event_with_observation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                manifest_path,
                manifest_sha,
                artifact_dir,
                _artifact_sha,
            ) = self._collect_valid_artifact(root, event_count=2)
            ledger_rows = [
                json.loads(line)
                for line in (artifact_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            self.assertEqual(ledger_rows[0]["outcome"], "parsed")
            ledger_rows[0].update(
                {
                    "outcome": "parse_error",
                    "error_type": "RuntimeError",
                    "error": "resigned semantic parse failure",
                }
            )
            artifact_sha = self._resign_artifact_ledger(
                artifact_dir,
                ledger_rows,
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_record_rejects_parsed_event_without_observation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (
                manifest_path,
                manifest_sha,
                artifact_dir,
                _artifact_sha,
            ) = self._collect_valid_artifact(root, event_count=2)
            observations = [
                json.loads(line)
                for line in (artifact_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            self.assertEqual(len(observations), 2)
            artifact_sha = self._resign_artifact_references(
                artifact_dir,
                observations[:1],
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_record_rejects_matched_observation_with_conflicting_race_name(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            artifact_dir, _artifact_sha = self._write_complete_artifact(
                root,
                manifest_path=manifest_path,
                manifest_sha=manifest_sha,
            )
            observations = [
                json.loads(line)
                for line in (artifact_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            observations[0]["payload"]["race"]["source_race_name"] = (
                "Prince of Wales's Stakes"
            )
            artifact_sha = self._resign_artifact_references(
                artifact_dir,
                observations,
            )

            with self.assertRaises(CommandError):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 0)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 0)

    def test_record_accepts_active_race_alias_after_identity_normalization(self):
        stable_models.RaceEventAlias.objects.create(
            event=self.event,
            text="Ｋｉｎｇ—George   Stakes",
            source_language="en",
            alias_type="manual-reviewed",
            source="operator",
            is_active=True,
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            artifact_dir, _artifact_sha = self._write_complete_artifact(
                root,
                manifest_path=manifest_path,
                manifest_sha=manifest_sha,
            )
            observations = [
                json.loads(line)
                for line in (artifact_dir / "references.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            observations[0]["payload"]["race"]["source_race_name"] = (
                "King George Stakes"
            )
            artifact_sha = self._resign_artifact_references(
                artifact_dir,
                observations,
            )

            call_command(
                "record_internal_race_references",
                manifest_file=str(manifest_path),
                manifest_sha256=manifest_sha,
                artifact_dir=str(artifact_dir),
                artifact_sha256=artifact_sha,
            )

        receipt = stable_models.RaceReferenceReceipt.objects.get()
        self.assertEqual(receipt.event_id, self.event.pk)
        self.assertEqual(receipt.match_status, "matched")

    def test_record_rejects_extra_file_symlink_or_complete_hash_mismatch(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            for variant in ("extra", "symlink", "complete_mismatch"):
                variant_root = root / variant
                variant_root.mkdir()
                artifact_dir, artifact_sha = self._write_complete_artifact(
                    variant_root,
                    manifest_path=manifest_path,
                    manifest_sha=manifest_sha,
                )
                raw = artifact_dir / "raw" / f"{self.event.pk}.body"
                if variant == "extra":
                    (artifact_dir / "unexpected.txt").write_text("no", encoding="utf-8")
                elif variant == "symlink":
                    raw.unlink()
                    raw.symlink_to(manifest_path)
                elif variant == "complete_mismatch":
                    (artifact_dir / "COMPLETE").write_text("0" * 64 + "\n", encoding="ascii")

                with self.subTest(variant=variant), self.assertRaises((CommandError, SystemExit)):
                    call_command(
                        "record_internal_race_references",
                        manifest_file=str(manifest_path),
                        manifest_sha256=manifest_sha,
                        artifact_dir=str(artifact_dir),
                        artifact_sha256=artifact_sha,
                    )

    def test_record_accepts_exact_file_set_and_exact_replay_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            artifact_dir, artifact_sha = self._write_complete_artifact(
                root,
                manifest_path=manifest_path,
                manifest_sha=manifest_sha,
            )
            for _ in range(2):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 1)
        self.assertEqual(stable_models.RaceReferencePayload.objects.count(), 1)
        self.assertEqual(stable_models.RaceReferenceReceipt.objects.count(), 1)
        receipt = stable_models.RaceReferenceReceipt.objects.get()
        self.assertEqual(receipt.event_id, self.event.pk)
        self.assertEqual(receipt.source_cache_ref, f"raw/{self.event.pk}.body")

    def test_record_run_uses_signed_collection_window_not_delayed_record_time(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, _manifest, manifest_sha = self._build_manifest(root)
            artifact_dir, artifact_sha = self._write_complete_artifact(
                root,
                manifest_path=manifest_path,
                manifest_sha=manifest_sha,
            )
            ledger = json.loads(
                (artifact_dir / "request_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            artifact = json.loads(
                (artifact_dir / "artifact.json").read_text(encoding="utf-8")
            )
            expected_started_at = datetime.fromisoformat(ledger["fetched_at"])
            expected_finished_at = datetime.fromisoformat(
                artifact["completed_at"]
            )
            record_now = expected_finished_at + timedelta(days=5)

            with patch(
                "stable.management.commands.record_internal_race_references.timezone.now",
                return_value=record_now,
            ), patch(
                "stable.services.race_reference_sources.timezone.now",
                return_value=record_now,
            ):
                call_command(
                    "record_internal_race_references",
                    manifest_file=str(manifest_path),
                    manifest_sha256=manifest_sha,
                    artifact_dir=str(artifact_dir),
                    artifact_sha256=artifact_sha,
                )

        run = stable_models.RaceReferenceCollectionRun.objects.get()
        self.assertEqual(run.started_at, expected_started_at)
        self.assertEqual(run.finished_at, expected_finished_at)
        self.assertLessEqual(run.started_at, run.finished_at)
        self.assertNotEqual(run.started_at, record_now)
        self.assertNotEqual(run.finished_at, record_now)

    def test_record_rejects_invalid_signed_collection_window(self):
        variants = ("completed_before_fetch", "naive_completed", "future_completed")
        for index, variant in enumerate(variants, start=1):
            with self.subTest(variant=variant), TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest_path, _manifest, manifest_sha = self._build_manifest(root)
                artifact_dir, _artifact_sha = self._write_complete_artifact(
                    root,
                    manifest_path=manifest_path,
                    manifest_sha=manifest_sha,
                )
                ledger = json.loads(
                    (artifact_dir / "request_ledger.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()[0]
                )
                fetched_at = datetime.fromisoformat(ledger["fetched_at"])
                record_now = fetched_at + timedelta(days=2)
                if variant == "completed_before_fetch":
                    completed_at = (
                        fetched_at - timedelta(seconds=1)
                    ).isoformat()
                elif variant == "naive_completed":
                    completed_at = (
                        fetched_at + timedelta(seconds=1)
                    ).replace(tzinfo=None).isoformat()
                else:
                    completed_at = (
                        record_now + timedelta(days=1)
                    ).isoformat()
                artifact_sha = self._resign_artifact_metadata(
                    artifact_dir,
                    completed_at=completed_at,
                )

                with patch(
                    "stable.management.commands.record_internal_race_references.timezone.now",
                    return_value=record_now,
                ), patch(
                    "stable.services.race_reference_sources.timezone.now",
                    return_value=record_now,
                ), self.assertRaises(CommandError):
                    call_command(
                        "record_internal_race_references",
                        manifest_file=str(manifest_path),
                        manifest_sha256=manifest_sha,
                        artifact_dir=str(artifact_dir),
                        artifact_sha256=artifact_sha,
                    )

        self.assertEqual(stable_models.RaceReferenceCollectionRun.objects.count(), 0)

    def test_report_command_is_internal_file_output_only(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-20",
                event_id=self.event.pk,
                output=str(output),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["source_key"], "reference_sporting_life")
        self.assertEqual(report["event_id"], self.event.pk)
        self.assertIn("coverage", report)
        self.assertIn("partial", report)
        self.assertIn("mismatch", report)

    def test_unknown_completeness_is_reported_partial_not_complete(self):
        service = importlib.import_module("stable.services.race_reference_sources")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path, manifest, manifest_sha = self._build_manifest(root)
            payload = {
                "schema_version": 1,
                "source_key": "reference_sporting_life",
                "country_region": "united_kingdom",
                "provider_event_key": "sl:859381",
                "race": {
                    "source_race_name": self.event.original_name,
                    "source_racecourse": "royal-ascot",
                    "local_date": "2025-06-19",
                    "source_start_time": "15:40",
                },
                "runners": [],
                "completeness": {
                    "race_identity": "complete",
                    "runners": "unknown",
                    "results": "complete",
                    "gap_codes": ["runners_unknown"],
                },
            }
            service.record_reference_collection(
                manifest=manifest,
                manifest_sha256=manifest_sha,
                artifact={
                    "artifact_sha256": "7" * 64,
                    "observations": [
                        {
                            "payload": payload,
                            "provenance": {
                                "source_url": self.source_url,
                                "final_url": self.source_url,
                                "source_observed_at": None,
                                "fetched_at": "2026-07-27T00:00:00+00:00",
                                "parser": manifest["parser"],
                                "legacy_payload_sha256": "1" * 64,
                                "raw_sha256": "2" * 64,
                                "source_cache_ref": f"raw/{self.event.pk}.body",
                            },
                            "event_id": self.event.pk,
                            "match_status": "matched",
                            "match_confidence": 100,
                            "match_evidence": {
                                "provider_event_key": "sl:859381",
                            },
                            "classification_version": "test-v1",
                        }
                    ],
                },
            )
            receipt = stable_models.RaceReferenceReceipt.objects.get()
            output = root / "unknown-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-19",
                event_id=self.event.pk,
                output=str(output),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(receipt.is_partial)
        self.assertEqual(receipt.gap_codes, ["runners_unknown"])
        self.assertEqual(
            receipt.payload.structured_payload["completeness"]["runners"],
            "unknown",
        )
        self.assertEqual(report["partial"]["count"], 1)
        self.assertEqual(
            report["by_region_date"][0]["completeness"],
            {"complete": 0, "partial": 1},
        )

    def test_report_groups_seven_day_metrics_by_region_and_local_date_with_latency(
        self,
    ):
        observed_at = datetime(2025, 6, 19, 12, 0, tzinfo=dt_timezone.utc)
        fetched_at = datetime(2025, 6, 19, 12, 5, tzinfo=dt_timezone.utc)
        run = stable_models.RaceReferenceCollectionRun.objects.create(
            source_key="reference_sporting_life",
            country_region="united_kingdom",
            parser_name="sporting_life",
            parser_version="reference-v1",
            scope_manifest_sha256="a" * 64,
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 19),
            target_count=2,
            status="finished",
            trigger_kind="management_command",
            started_at=observed_at,
            finished_at=fetched_at,
            request_count=2,
            artifact_sha256="b" * 64,
        )
        payloads = []
        for index in range(2):
            structured = {
                "schema_version": 1,
                "source_key": "reference_sporting_life",
                "country_region": "united_kingdom",
                "provider_event_key": f"sl:{859381 + index}",
                "race": {
                    "source_race_name": f"Reference Cup {index + 1}",
                    "source_racecourse": "royal-ascot",
                    "local_date": "2025-06-19",
                    "source_start_time": "15:40",
                },
                "runners": [],
                "completeness": {
                    "race_identity": "complete",
                    "runners": "partial" if index else "complete",
                    "results": "partial" if index else "complete",
                    "gap_codes": ["results_partial"] if index else [],
                },
            }
            payloads.append(
                stable_models.RaceReferencePayload.objects.create(
                    source_key="reference_sporting_life",
                    provider_event_key=structured["provider_event_key"],
                    observation_key=(
                        "reference_sporting_life:"
                        f"{structured['provider_event_key']}"
                    ),
                    payload_sha256=f"{index + 1:064x}",
                    structured_payload=structured,
                )
            )
        for index, payload in enumerate(payloads):
            stable_models.RaceReferenceReceipt.objects.create(
                run=run,
                payload=payload,
                source_url=self.source_url,
                final_url=self.source_url,
                source_observed_at=observed_at if index == 0 else None,
                fetched_at=fetched_at.replace(minute=5 + index),
                parser_name="sporting_life",
                parser_version="reference-v1",
                legacy_payload_sha256=f"{index + 3:064x}",
                raw_sha256=f"{index + 5:064x}",
                source_cache_ref=f"raw/{self.event.pk + index}.body",
                provenance_sha256=f"{index + 7:064x}",
                event=self.event,
                match_status="matched",
                match_confidence=100,
                match_evidence={"provider_event_key": payload.provider_event_key},
                event_snapshot={
                    "event_id": self.event.pk,
                    "local_date": "2025-06-19",
                },
                event_snapshot_sha256=f"{index + 9:064x}",
                classification_version="test-v1",
                is_partial=bool(index),
                gap_codes=["results_partial"] if index else [],
            )
        public_models = (
            stable_models.RaceEventRunner,
            stable_models.RaceEventResult,
            stable_models.RaceEventDataCandidate,
            stable_models.RaceEventRevision,
            stable_models.NewsArticle,
            stable_models.QQPushDelivery,
            stable_models.RaceEventLifecycleTransition,
        )
        before = {model: model.objects.count() for model in public_models}

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "seven-day-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-25",
                output=str(output),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["visibility"], "internal_only")
        self.assertEqual(len(report["by_region_date"]), 1)
        group = report["by_region_date"][0]
        self.assertEqual(group["country_region"], "united_kingdom")
        self.assertEqual(group["local_date"], "2025-06-19")
        self.assertEqual(group["coverage"]["receipts"], 2)
        self.assertEqual(group["coverage"]["matched"], 2)
        self.assertEqual(group["completeness"]["partial"], 1)
        self.assertEqual(
            group["collection_latency_seconds"],
            {
                "known_count": 1,
                "unknown_count": 1,
                "average": 300.0,
            },
        )
        self.assertEqual(
            {model: model.objects.count() for model in public_models},
            before,
        )

    def test_report_event_filter_uses_frozen_snapshot_for_nonmatched_receipts(self):
        run = self._create_report_run(
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 19),
            digest_digit=60,
        )
        receipts = [
            self._create_report_receipt(
                run=run,
                suffix=index,
                local_date=date(2025, 6, 19),
                match_status=status,
                snapshot_event_id=self.event.pk,
                event=None,
            )
            for index, status in enumerate(
                ("unmatched", "ambiguous", "source_only"),
                start=1,
            )
        ]

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "event-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-19",
                event_id=self.event.pk,
                output=str(output),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["coverage"]["receipts"], 3)
        self.assertEqual(report["coverage"]["unmatched"], 1)
        self.assertEqual(report["coverage"]["ambiguous"], 1)
        self.assertEqual(report["coverage"]["source_only"], 1)
        self.assertEqual(
            {row["receipt_id"] for row in report["receipts"]},
            {receipt.pk for receipt in receipts},
        )

    def test_report_marks_duplicate_runs_and_observations_by_frozen_event_date(self):
        first_run = self._create_report_run(
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 19),
            digest_digit=80,
        )
        second_run = self._create_report_run(
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 19),
            digest_digit=82,
        )
        self._create_report_receipt(
            run=first_run,
            suffix=10,
            local_date=date(2025, 6, 19),
            match_status="matched",
            snapshot_event_id=self.event.pk,
            event=self.event,
        )
        self._create_report_receipt(
            run=second_run,
            suffix=11,
            local_date=date(2025, 6, 19),
            match_status="matched",
            snapshot_event_id=self.event.pk,
            event=self.event,
        )

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "duplicate-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-25",
                output=str(output),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        group = report["by_region_date"][0]
        self.assertEqual(group["coverage"]["duplicate_runs"], 1)
        self.assertEqual(group["coverage"]["duplicate_observations"], 1)

    def test_report_counts_duplicate_failed_runs_from_error_details_without_receipts(
        self,
    ):
        same_day_other_event = stable_models.RaceEvent.objects.create(
            year=2025,
            slug="reference-duplicate-other-event-2025",
            original_name="Reference Duplicate Other Event",
            chinese_name="参考重复其他赛事",
            country_region="united_kingdom",
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            status="finished",
            priority="P0",
            visibility_status="published",
            timezone_name="Europe/London",
            local_date=date(2025, 6, 19),
        )
        other_day_event = stable_models.RaceEvent.objects.create(
            year=2025,
            slug="reference-duplicate-other-day-2025",
            original_name="Reference Duplicate Other Day",
            chinese_name="参考重复其他日期",
            country_region="united_kingdom",
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            status="finished",
            priority="P0",
            visibility_status="published",
            timezone_name="Europe/London",
            local_date=date(2025, 6, 20),
        )

        def create_failed_run(
            *,
            event,
            local_date_value: date,
            digest_digit: int,
        ):
            run = self._create_report_run(
                local_date_from=local_date_value,
                local_date_to=local_date_value,
                digest_digit=digest_digit,
            )
            run.status = "failed"
            run.error_count = 1
            run.error_summary = {
                "total": 1,
                "by_outcome": {"transport_error": 1},
                "details": [
                    {
                        "event_id": event.pk,
                        "local_date": local_date_value.isoformat(),
                        "outcome": "transport_error",
                        "phase": "fetch",
                        "error": "transport request failed",
                    }
                ],
            }
            run.save(
                update_fields={"status", "error_count", "error_summary"}
            )
            return run

        create_failed_run(
            event=self.event,
            local_date_value=date(2025, 6, 19),
            digest_digit=120,
        )
        create_failed_run(
            event=self.event,
            local_date_value=date(2025, 6, 19),
            digest_digit=122,
        )
        create_failed_run(
            event=same_day_other_event,
            local_date_value=date(2025, 6, 19),
            digest_digit=124,
        )
        create_failed_run(
            event=other_day_event,
            local_date_value=date(2025, 6, 20),
            digest_digit=126,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = {}
            for report_date in ("2025-06-19", "2025-06-20"):
                output = root / f"duplicate-errors-{report_date}.json"
                call_command(
                    "report_internal_race_reference_observation",
                    source_key="reference_sporting_life",
                    date_from=report_date,
                    date_to=report_date,
                    output=str(output),
                )
                reports[report_date] = json.loads(
                    output.read_text(encoding="utf-8")
                )

        first_day = reports["2025-06-19"]
        self.assertEqual(first_day["coverage"]["runs"], 3)
        self.assertEqual(first_day["coverage"]["errors"], 3)
        self.assertEqual(first_day["coverage"]["receipts"], 0)
        self.assertEqual(len(first_day["by_region_date"]), 1)
        self.assertEqual(
            first_day["by_region_date"][0]["local_date"],
            "2025-06-19",
        )
        self.assertEqual(
            first_day["by_region_date"][0]["coverage"]["duplicate_runs"],
            1,
        )

        second_day = reports["2025-06-20"]
        self.assertEqual(second_day["coverage"]["runs"], 1)
        self.assertEqual(second_day["coverage"]["errors"], 1)
        self.assertEqual(second_day["coverage"]["receipts"], 0)
        self.assertEqual(len(second_day["by_region_date"]), 1)
        self.assertEqual(
            second_day["by_region_date"][0]["coverage"]["duplicate_runs"],
            0,
        )

    def test_report_event_filter_counts_only_runs_with_matching_snapshot_receipt(self):
        target_run = self._create_report_run(
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 19),
            digest_digit=90,
        )
        unrelated_run = self._create_report_run(
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 19),
            digest_digit=92,
        )
        unrelated_event = stable_models.RaceEvent.objects.create(
            year=2025,
            slug="unrelated-reference-cup-2025",
            original_name="Unrelated Reference Cup",
            chinese_name="无关参考杯",
            country_region="united_kingdom",
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            status="finished",
            priority="P0",
            visibility_status="published",
            timezone_name="Europe/London",
            local_date=date(2025, 6, 19),
        )
        self._create_report_receipt(
            run=target_run,
            suffix=20,
            local_date=date(2025, 6, 19),
            match_status="matched",
            snapshot_event_id=self.event.pk,
            event=self.event,
        )
        self._create_report_receipt(
            run=unrelated_run,
            suffix=21,
            local_date=date(2025, 6, 19),
            match_status="matched",
            snapshot_event_id=unrelated_event.pk,
            event=unrelated_event,
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_output = root / "target-event-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-19",
                event_id=self.event.pk,
                output=str(target_output),
            )
            target_report = json.loads(target_output.read_text(encoding="utf-8"))

            empty_output = root / "empty-event-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-19",
                event_id=999999999,
                output=str(empty_output),
            )
            empty_report = json.loads(empty_output.read_text(encoding="utf-8"))

        self.assertEqual(target_report["coverage"]["runs"], 1)
        self.assertEqual(target_report["coverage"]["receipts"], 1)
        self.assertEqual(empty_report["coverage"]["runs"], 0)
        self.assertEqual(empty_report["coverage"]["receipts"], 0)

    def test_report_counts_failed_run_without_receipts_in_filtered_scope(self):
        observed_at = datetime(2025, 6, 19, 12, 0, tzinfo=dt_timezone.utc)
        failed_run = stable_models.RaceReferenceCollectionRun.objects.create(
            source_key="reference_sporting_life",
            country_region="united_kingdom",
            parser_name="sporting_life",
            parser_version="reference-v1",
            scope_manifest_sha256="d" * 64,
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 19),
            target_count=2,
            status="failed",
            trigger_kind="management_command",
            started_at=observed_at,
            finished_at=observed_at,
            request_count=2,
            error_count=2,
            artifact_sha256="e" * 64,
            error_summary={
                "total": 2,
                "by_outcome": {"transport_error": 2},
                "details": [
                    {
                        "event_id": self.event.pk,
                        "outcome": "transport_error",
                        "phase": "fetch",
                        "error": "transport request failed",
                    },
                    {
                        "event_id": self.event.pk + 100000,
                        "outcome": "transport_error",
                        "phase": "fetch",
                        "error": "transport request failed",
                    },
                ],
            },
        )

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "failed-run-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-19",
                output=str(output),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(failed_run.receipts.count(), 0)
        self.assertEqual(report["coverage"]["runs"], 1)
        self.assertEqual(report["coverage"]["failed_runs"], 1)
        self.assertEqual(report["coverage"]["errors"], 2)
        self.assertEqual(report["coverage"]["unattributed_errors"], 0)
        self.assertEqual(report["coverage"]["receipts"], 0)

    def test_report_event_filter_includes_no_receipt_run_for_matching_error_only(self):
        second_event = stable_models.RaceEvent.objects.create(
            year=2025,
            slug="reference-error-filter-second-event-2025",
            original_name="Reference Error Filter Second Event",
            chinese_name="参考错误过滤第二场",
            country_region="united_kingdom",
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            status="finished",
            priority="P0",
            visibility_status="published",
            timezone_name="Europe/London",
            local_date=date(2025, 6, 20),
        )
        observed_at = datetime(2025, 6, 19, 12, 0, tzinfo=dt_timezone.utc)
        run = stable_models.RaceReferenceCollectionRun.objects.create(
            source_key="reference_sporting_life",
            country_region="united_kingdom",
            parser_name="sporting_life",
            parser_version="reference-v1",
            scope_manifest_sha256="1" * 64,
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 20),
            target_count=3,
            status="failed",
            trigger_kind="management_command",
            started_at=observed_at,
            finished_at=observed_at,
            request_count=2,
            error_count=3,
            artifact_sha256="2" * 64,
            error_summary={
                "total": 3,
                "by_outcome": {
                    "parse_error": 1,
                    "transport_error": 2,
                },
                "details": [
                    {
                        "event_id": self.event.pk,
                        "local_date": "2025-06-19",
                        "outcome": "transport_error",
                        "phase": "fetch",
                        "error": "transport request failed",
                    },
                    {
                        "event_id": second_event.pk,
                        "local_date": "2025-06-20",
                        "outcome": "parse_error",
                        "phase": "parse",
                        "error": "response parsing failed",
                    },
                ],
            },
        )

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_output = root / "target-error-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-20",
                event_id=self.event.pk,
                output=str(target_output),
            )
            target_report = json.loads(
                target_output.read_text(encoding="utf-8")
            )

            missing_output = root / "missing-error-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-20",
                event_id=999999999,
                output=str(missing_output),
            )
            missing_report = json.loads(
                missing_output.read_text(encoding="utf-8")
            )

        self.assertEqual(run.receipts.count(), 0)
        self.assertEqual(target_report["coverage"]["runs"], 1)
        self.assertEqual(target_report["coverage"]["errors"], 1)
        self.assertEqual(target_report["coverage"]["unattributed_errors"], 0)
        self.assertEqual(target_report["coverage"]["receipts"], 0)
        self.assertEqual(missing_report["coverage"]["runs"], 0)
        self.assertEqual(missing_report["coverage"]["errors"], 0)
        self.assertEqual(
            missing_report["coverage"]["unattributed_errors"],
            0,
        )

    def test_report_date_filter_uses_each_receipt_frozen_snapshot_local_date(self):
        run = self._create_report_run(
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 20),
            digest_digit=70,
        )
        second_event = stable_models.RaceEvent.objects.create(
            year=2025,
            slug="reference-cup-2025-second-day",
            original_name="Reference Cup Second Day",
            chinese_name="参考杯第二日",
            country_region="united_kingdom",
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            status="finished",
            priority="P0",
            visibility_status="published",
            timezone_name="Europe/London",
            local_date=date(2025, 6, 20),
        )
        in_range = self._create_report_receipt(
            run=run,
            suffix=4,
            local_date=date(2025, 6, 19),
            match_status="matched",
            snapshot_event_id=self.event.pk,
            event=self.event,
        )
        self._create_report_receipt(
            run=run,
            suffix=5,
            local_date=date(2025, 6, 20),
            match_status="matched",
            snapshot_event_id=second_event.pk,
            event=second_event,
        )

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "date-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-19",
                output=str(output),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["coverage"]["receipts"], 1)
        self.assertEqual(
            [row["receipt_id"] for row in report["receipts"]],
            [in_range.pk],
        )
        self.assertEqual(
            [group["local_date"] for group in report["by_region_date"]],
            ["2025-06-19"],
        )

    def test_report_date_filter_attributes_errors_to_event_day_only(self):
        run = self._create_report_run(
            local_date_from=date(2025, 6, 19),
            local_date_to=date(2025, 6, 20),
            digest_digit=74,
        )
        second_event = stable_models.RaceEvent.objects.create(
            year=2025,
            slug="reference-error-cup-2025-second-day",
            original_name="Reference Error Cup Second Day",
            chinese_name="参考错误杯第二日",
            country_region="united_kingdom",
            racecourse="Ascot",
            grade_text="G1",
            normalized_grade="G1",
            surface="turf",
            status="finished",
            priority="P0",
            visibility_status="published",
            timezone_name="Europe/London",
            local_date=date(2025, 6, 20),
        )
        self._create_report_receipt(
            run=run,
            suffix=6,
            local_date=date(2025, 6, 19),
            match_status="matched",
            snapshot_event_id=self.event.pk,
            event=self.event,
        )
        self._create_report_receipt(
            run=run,
            suffix=7,
            local_date=date(2025, 6, 20),
            match_status="matched",
            snapshot_event_id=second_event.pk,
            event=second_event,
        )
        run.error_count = 3
        run.error_summary = {
            "total": 3,
            "by_outcome": {
                "parse_error": 1,
                "transport_error": 2,
            },
            "details": [
                {
                    "event_id": self.event.pk,
                    "local_date": "2025-06-19",
                    "outcome": "transport_error",
                    "phase": "fetch",
                    "error": "transport request failed",
                },
                {
                    "event_id": second_event.pk,
                    "local_date": "2025-06-20",
                    "outcome": "parse_error",
                    "phase": "parse",
                    "error": "response parsing failed",
                },
            ],
        }
        run.save(update_fields={"error_count", "error_summary"})

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "single-day-error-report.json"
            call_command(
                "report_internal_race_reference_observation",
                source_key="reference_sporting_life",
                date_from="2025-06-19",
                date_to="2025-06-19",
                output=str(output),
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(report["coverage"]["runs"], 1)
        self.assertEqual(report["coverage"]["errors"], 1)
        self.assertEqual(report["coverage"]["unattributed_errors"], 1)
        self.assertEqual(report["coverage"]["receipts"], 1)

    def test_default_dev_server_bind_mount_keeps_parser_modules_importable(self):
        repository_root = Path(__file__).resolve().parents[2]
        server_root = repository_root / "server"
        command_module = importlib.import_module(
            "stable.management.commands.collect_internal_race_references"
        )
        for source_key, module_name in command_module.PARSER_MODULES.items():
            with self.subTest(source_key=source_key, module_name=module_name):
                self.assertTrue(
                    module_name.startswith("stable.race_reference_parsers."),
                    "default ./server:/app/server bind mount hides image-only runtime modules",
                )
                relative_module = Path(*module_name.split(".")).with_suffix(".py")
                self.assertTrue((server_root / relative_module).is_file())
                parser = importlib.import_module(module_name)
                self.assertTrue(callable(parser.parse_reference_page))

    def test_default_dev_server_bind_mount_uses_stable_safe_http(self):
        command_module = importlib.import_module(
            "stable.management.commands.collect_internal_race_references"
        )
        command_source = inspect.getsource(command_module)

        self.assertIn(
            'import_module("stable.race_event_safe_http")',
            command_source,
        )
        self.assertNotIn(
            'import_module("runtime.tools.race_event_safe_http")',
            command_source,
        )
        stable_http = importlib.import_module("stable.race_event_safe_http")
        self.assertTrue(callable(stable_http.fetch_https))
        self.assertTrue(issubclass(stable_http.SafeHttpError, RuntimeError))
