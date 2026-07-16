from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from stable.models import (
    HistoricalBatchLock,
    HistoricalBatchPhase,
    HistoricalBatchRun,
    HistoricalBatchRunStatus,
    HistoricalRaceDetailImportReceipt,
    HistoricalRaceDetailImportReceiptStatus,
    HistoricalRaceEventTarget,
    HistoricalRaceExpectationStatus,
    HistoricalRaceResolutionStatus,
    OperationLog,
    RaceEvent,
    RaceEventDataCandidate,
    RaceSeries,
    RaceSeriesReviewStatus,
    RacingRegion,
)
from stable.services.historical_race_batches import materialize_historical_event, target_identity
from stable.services.historical_race_detail_chunk_import import (
    HistoricalRaceDetailChunkError,
    import_historical_race_detail_chunk,
    reconcile_historical_race_detail_receipt,
    resolve_source_provider,
    validate_distance_text,
    verify_historical_race_detail_chunk,
)
from stable.services.historical_batch_runner import (
    _READ_MANAGEMENT_COMMANDS,
    _WRITE_MANAGEMENT_COMMANDS,
    _validate_apply_bindings,
    RunnerPlanError,
    validate_runner_plan,
)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _identity(path: Path, *, relative_to: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
    }


class ChunkArtifact:
    def __init__(
        self,
        root: Path,
        targets: list[HistoricalRaceEventTarget],
        *,
        layer: str = "historical_through_2024",
        cutoff: str | None = None,
        invalid_last_result: bool = False,
    ):
        self.root = root
        self.chunk_id = f"{layer}-0001"
        self.chunk_dir = root / "layers" / layer / "chunks" / self.chunk_id
        self.chunk_dir.mkdir(parents=True)
        self.rows = []
        for index, target in enumerate(targets):
            local_date = date(target.year, 1, 2).isoformat()
            source_url = f"https://db.netkeiba.com/race/{target.year}050101{index + 1:02d}/"
            source_body = f"result-{target.pk}".encode()
            source_path = self.chunk_dir / "sources" / f"target-{target.pk}.html"
            source_path.parent.mkdir(exist_ok=True)
            source_path.write_bytes(source_body)
            source_identity = {
                **_identity(source_path, relative_to=self.chunk_dir),
                "source_url": source_url,
                "cached_at": "2026-07-15T00:00:00Z",
                "protected_by": ["test"],
            }
            invalid_result = invalid_last_result and index == len(targets) - 1
            modules = {
                "runners": {
                    "is_complete": True,
                    "items": [
                        {
                            "horse_number": "1",
                            "horse_name": f"Horse {target.pk}",
                            "jockey_name": "Jockey",
                            "trainer_name": "Trainer",
                            "source_refs": {"result": source_url},
                        }
                    ],
                    "source_cache_identity": source_identity,
                },
                "results": {
                    "is_complete": True,
                    "items": [
                        {
                            "finish_position": 1,
                            "official_finish_position": 1,
                            "horse_number": "1",
                            "horse_name": f"Horse {target.pk}",
                            "jockey_name": "Jockey",
                            "trainer_name": "Trainer",
                            "source_refs": {"result": source_url},
                        },
                        *(
                            [
                                {
                                    "finish_position": 1,
                                    "official_finish_position": 2,
                                    "horse_number": "2",
                                    "horse_name": "Invalid duplicate",
                                    "source_refs": {"result": source_url},
                                }
                            ]
                            if invalid_result
                            else []
                        ),
                    ],
                    "source_cache_identity": source_identity,
                },
            }
            self.rows.append(
                {
                    "pending_target": {
                        "target_id": target.pk,
                        "target_sha256": target_identity(target)["target_sha256"],
                        "year": target.year,
                        "series_key": target.race_series.key,
                        "region": target.country_region,
                        "resolution_status": "pending",
                    },
                    "source_plan_artifact_sha256": "a" * 64,
                    "approved_inventory_artifact_sha256": target.artifact_sha256,
                    "local_date": local_date,
                    "status": "finished",
                    "source_refs": {
                        "calendar_discovery": {
                            "calendar_source_provider": "netkeiba",
                            "calendar_source_url": source_url,
                        }
                    },
                    "distance_text": "1600m",
                    "distance_provenance": {
                        "source": "netkeiba_result_parser_v1",
                        "source_url": source_url,
                        "original_text": "1600m",
                    },
                    "modules": modules,
                    "source": {
                        "name": "netkeiba",
                        "provider": "netkeiba",
                        "url": source_url,
                    },
                    "calendar_evidence": {
                        "kind": "verified_detail_source_date",
                        "source_url": source_url,
                        "local_date": local_date,
                    },
                    "cache_identities": [source_identity],
                    "package_identity": {"path": "package.json", "sha256": "1" * 64, "size": 1},
                    "source_fragment_identity": {"path": "fragment.json", "sha256": "2" * 64, "size": 1},
                    "staged_event_identity": {"path": "staged.csv", "sha256": "3" * 64, "size": 1},
                    "source_cache_manifest_identity": {"path": "cache.json", "sha256": "4" * 64, "size": 1},
                    "candidate_identity": {"path": "candidate.jsonl", "sha256": "5" * 64, "size": 1},
                    "approved_source_cache_identity": source_identity,
                }
            )

        candidates_path = self.chunk_dir / "candidates.jsonl"
        candidates_path.write_bytes(b"".join(_canonical_bytes(row) for row in self.rows))
        artifacts = [_identity(candidates_path, relative_to=self.chunk_dir)]
        for row in self.rows:
            source_path = self.chunk_dir / row["approved_source_cache_identity"]["path"]
            artifacts.append(row["approved_source_cache_identity"])
        chunk_manifest = {
            "artifact_kind": "historical_race_detail_source_bundle_chunk",
            "schema_version": "2.0",
            "chunk_id": self.chunk_id,
            "layer": layer,
            "cutoff_date": cutoff,
            "target_count": len(self.rows),
            "target_ids": [target.pk for target in targets],
            "source_object_count": len(self.rows),
            "source_object_bytes": sum(row["approved_source_cache_identity"]["size"] for row in self.rows),
            "candidates": artifacts[0],
            "artifacts": artifacts,
        }
        self.chunk_manifest_path = self.chunk_dir / "manifest.json"
        self.chunk_manifest_path.write_bytes(_canonical_bytes(chunk_manifest))
        self.chunk_sha = hashlib.sha256(self.chunk_manifest_path.read_bytes()).hexdigest()

        chunk_summary = {
            "chunk_id": self.chunk_id,
            "path": candidates_path.relative_to(root).as_posix(),
            "target_count": len(self.rows),
            "target_ids": [target.pk for target in targets],
            "candidates": _identity(candidates_path, relative_to=root),
            "manifest": _identity(self.chunk_manifest_path, relative_to=root),
        }
        bundle_manifest = {
            "artifact_kind": "historical_race_detail_source_bundle",
            "schema_version": "2.0",
            "approved_inventory_artifact_sha256": targets[0].artifact_sha256,
            "layers": {
                layer: {
                    "record_count": len(self.rows),
                    "gap_count": 0,
                    "chunk_count": 1,
                    "chunks": [chunk_summary],
                }
            },
        }
        self.bundle_manifest_path = root / "manifest.json"
        self.bundle_manifest_path.write_bytes(_canonical_bytes(bundle_manifest))
        self.bundle_sha = hashlib.sha256(self.bundle_manifest_path.read_bytes()).hexdigest()

        approval = {
            "artifact_kind": "historical_race_detail_chunk_approval",
            "schema_version": "2.0",
            "status": "approved",
            "approved_by": "chunk-reviewer",
            "approved_at": "2026-07-15T01:00:00Z",
            "bundle_manifest_sha256": self.bundle_sha,
            "layer": layer,
            "cutoff_date": cutoff,
            "chunk_id": self.chunk_id,
            "chunk_manifest_sha256": self.chunk_sha,
            "candidates_sha256": artifacts[0]["sha256"],
            "target_count": len(self.rows),
            "target_ids": [target.pk for target in targets],
        }
        self.approval_path = root / "approval.json"
        self.approval_path.write_bytes(_canonical_bytes(approval))
        self.approval_sha = hashlib.sha256(self.approval_path.read_bytes()).hexdigest()

    def kwargs(self, *, runner_run_id: str, dry_run: bool = False) -> dict:
        run = HistoricalBatchRun.objects.get(run_id=runner_run_id)
        command = (
            "verify_historical_race_detail_chunk"
            if run.phase == HistoricalBatchPhase.VERIFY
            else "import_historical_race_detail_chunk"
        )
        step_id = f"{command}-{self.chunk_id}"
        argv = [
            "python",
            "manage.py",
            command,
            "--bundle-dir",
            str(self.root),
            "--chunk-manifest",
            str(self.chunk_manifest_path),
            "--approval",
            str(self.approval_path),
            "--expected-bundle-sha256",
            self.bundle_sha,
            "--expected-chunk-sha256",
            self.chunk_sha,
            "--expected-approval-sha256",
            self.approval_sha,
            "--runner-run-id",
            runner_run_id,
        ]
        if dry_run:
            argv.append("--dry-run")
        plan = {
            "batch_id": run.batch_id,
            "phase": run.phase,
            "artifact_root": str(self.root.resolve()),
            "steps": [
                {
                    "id": step_id,
                    "argv": argv,
                    "inputs": [
                        {
                            "path": str(self.bundle_manifest_path),
                            "sha256": self.bundle_sha,
                        },
                        {
                            "path": str(self.chunk_manifest_path),
                            "sha256": self.chunk_sha,
                        },
                        {
                            "path": str(self.approval_path),
                            "sha256": self.approval_sha,
                        },
                    ],
                }
            ],
        }
        plan_path = self.root / f"runner-plan-{runner_run_id}.json"
        plan_path.write_bytes(_canonical_bytes(plan))
        owner_token = f"owner-token:{runner_run_id}"
        owner_sha256 = hashlib.sha256(owner_token.encode("utf-8")).hexdigest()
        lease_expires_at = timezone.now() + timedelta(minutes=5)
        HistoricalBatchRun.objects.filter(pk=run.pk).update(
            artifact_root=str(self.root.resolve()),
            plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            current_step=step_id,
            owner_token_sha256=owner_sha256,
            heartbeat_at=timezone.now(),
            lease_expires_at=lease_expires_at,
        )
        HistoricalBatchLock.objects.filter(key="global").update(
            locked_by_run=run,
            owner_token_sha256=owner_sha256,
            heartbeat_at=timezone.now(),
            lease_expires_at=lease_expires_at,
        )
        os.environ.update(
            {
                "HISTORICAL_RUNNER_OWNER_TOKEN": owner_token,
                "HISTORICAL_RUNNER_PLAN_PATH": str(plan_path),
                "HISTORICAL_RUNNER_STEP_ID": step_id,
            }
        )
        return {
            "bundle_dir": self.root,
            "chunk_manifest_path": self.chunk_manifest_path,
            "approval_path": self.approval_path,
            "expected_bundle_sha256": self.bundle_sha,
            "expected_chunk_sha256": self.chunk_sha,
            "expected_approval_sha256": self.approval_sha,
            "runner_run_id": runner_run_id,
            "dry_run": dry_run,
            "today": date(2026, 7, 16),
        }


class HistoricalRaceDetailChunkImportTests(TestCase):
    def setUp(self):
        self.addCleanup(os.environ.pop, "HISTORICAL_RUNNER_OWNER_TOKEN", None)
        self.addCleanup(os.environ.pop, "HISTORICAL_RUNNER_PLAN_PATH", None)
        self.addCleanup(os.environ.pop, "HISTORICAL_RUNNER_STEP_ID", None)
        self.runner_context = TemporaryDirectory()
        self.addCleanup(self.runner_context.cleanup)
        self.user = get_user_model().objects.create_user(username="chunk-reviewer")
        self.run = HistoricalBatchRun.objects.create(
            run_id="chunk-apply-run",
            batch_id="detail-chunk",
            phase=HistoricalBatchPhase.APPLY,
            status=HistoricalBatchRunStatus.RUNNING,
            network_enabled=False,
            write_enabled=True,
            image_id="sha256:" + "1" * 64,
            image_revision="a" * 40,
            artifact_root="/tmp/detail-chunk",
            plan_sha256="2" * 64,
            owner_token_sha256="3" * 64,
            heartbeat_at=timezone.now(),
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )
        HistoricalBatchLock.objects.create(
            key="global",
            locked_by_run=self.run,
            owner_token_sha256="3" * 64,
            acquired_at=timezone.now(),
            heartbeat_at=timezone.now(),
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )

    def _bind_reconcile_runner(self, receipt_id: str) -> None:
        root = Path(self.runner_context.name)
        step_id = f"reconcile-{receipt_id}"
        argv = [
            "python",
            "manage.py",
            "reconcile_historical_race_detail_receipt",
            "--receipt-id",
            receipt_id,
            "--runner-run-id",
            self.run.run_id,
            "--approved-by",
            self.user.username,
            "--reason",
            "verified transaction rollback after parser failure",
        ]
        plan = {
            "batch_id": self.run.batch_id,
            "phase": self.run.phase,
            "artifact_root": str(root.resolve()),
            "steps": [{"id": step_id, "argv": argv, "inputs": []}],
        }
        plan_path = root / "reconcile-plan.json"
        plan_path.write_bytes(_canonical_bytes(plan))
        owner_token = f"owner-token:{self.run.run_id}"
        owner_sha256 = hashlib.sha256(owner_token.encode("utf-8")).hexdigest()
        lease_expires_at = timezone.now() + timedelta(minutes=5)
        HistoricalBatchRun.objects.filter(pk=self.run.pk).update(
            artifact_root=str(root.resolve()),
            plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            current_step=step_id,
            owner_token_sha256=owner_sha256,
            lease_expires_at=lease_expires_at,
        )
        HistoricalBatchLock.objects.filter(key="global").update(
            locked_by_run=self.run,
            owner_token_sha256=owner_sha256,
            lease_expires_at=lease_expires_at,
        )
        os.environ.update(
            {
                "HISTORICAL_RUNNER_OWNER_TOKEN": owner_token,
                "HISTORICAL_RUNNER_PLAN_PATH": str(plan_path),
                "HISTORICAL_RUNNER_STEP_ID": step_id,
            }
        )

    def _switch_to_verify_runner(self) -> HistoricalBatchRun:
        verify_run = HistoricalBatchRun.objects.create(
            run_id="chunk-verify-run",
            batch_id="detail-chunk",
            phase=HistoricalBatchPhase.VERIFY,
            status=HistoricalBatchRunStatus.RUNNING,
            network_enabled=False,
            write_enabled=False,
            image_id="sha256:" + "1" * 64,
            image_revision="a" * 40,
            artifact_root="/tmp/detail-chunk",
            plan_sha256="2" * 64,
            owner_token_sha256="4" * 64,
            heartbeat_at=timezone.now(),
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )
        HistoricalBatchLock.objects.filter(key="global").update(
            locked_by_run=verify_run,
            owner_token_sha256="4" * 64,
            heartbeat_at=timezone.now(),
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )
        return verify_run

    def _target(self, *, year: int = 2024, suffix: str = "one") -> HistoricalRaceEventTarget:
        series = RaceSeries.objects.create(
            key=f"japan-chunk-{suffix}-{year}",
            country_region=RacingRegion.JAPAN,
            canonical_name_original=f"Chunk Race {suffix}",
            chinese_name="分块测试赛",
            review_status=RaceSeriesReviewStatus.APPROVED,
        )
        return HistoricalRaceEventTarget.objects.create(
            race_series=series,
            year=year,
            country_region=RacingRegion.JAPAN,
            expectation_status=HistoricalRaceExpectationStatus.HELD,
            resolution_status=HistoricalRaceResolutionStatus.PENDING,
            original_name=f"Chunk Race {suffix}",
            chinese_name="分块测试赛",
            racecourse="Tokyo",
            grade_text="G1",
            artifact_sha256="b" * 64,
        )

    def test_success_and_replay_preserve_one_completed_receipt(self):
        target = self._target()
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            result = import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))
            replay = import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))

        target.refresh_from_db()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(replay["status"], "replayed")
        serialized_audit = json.dumps(
            {
                "result": result,
                "replay": replay,
                "receipt": HistoricalRaceDetailImportReceipt.objects.get().completion_payload,
                "logs": list(
                    OperationLog.objects.values(
                        "action_type", "target_type", "target_id", "detail"
                    )
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        self.assertNotIn("owner-token:chunk-apply-run", serialized_audit)
        self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.IMPORTED)
        self.assertEqual(target.event.runners.count(), 1)
        self.assertEqual(target.event.results.count(), 1)
        self.assertEqual(
            HistoricalRaceDetailImportReceipt.objects.filter(
                status=HistoricalRaceDetailImportReceiptStatus.COMPLETED
            ).count(),
            1,
        )

    def test_dry_run_leaves_receipt_and_business_tables_unchanged(self):
        target = self._target()
        before_sha = target_identity(target)["target_sha256"]
        before = {
            "events": RaceEvent.objects.count(),
            "candidates": RaceEventDataCandidate.objects.count(),
            "logs": OperationLog.objects.count(),
            "receipts": HistoricalRaceDetailImportReceipt.objects.count(),
        }
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            result = import_historical_race_detail_chunk(
                **artifact.kwargs(runner_run_id=self.run.run_id, dry_run=True)
            )

        target.refresh_from_db()
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(target_identity(target)["target_sha256"], before_sha)
        self.assertEqual(
            before,
            {
                "events": RaceEvent.objects.count(),
                "candidates": RaceEventDataCandidate.objects.count(),
                "logs": OperationLog.objects.count(),
                "receipts": HistoricalRaceDetailImportReceipt.objects.count(),
            },
        )

    def test_late_failure_rolls_back_business_writes_but_keeps_started_receipt(self):
        targets = [self._target(suffix="first"), self._target(suffix="second")]
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), targets, invalid_last_result=True)
            with self.assertRaises(HistoricalRaceDetailChunkError) as dry_error:
                import_historical_race_detail_chunk(
                    **artifact.kwargs(runner_run_id=self.run.run_id, dry_run=True)
                )
            self.assertEqual(HistoricalRaceDetailImportReceipt.objects.count(), 0)
            with self.assertRaises(HistoricalRaceDetailChunkError) as apply_error:
                import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))

        self.assertEqual(str(dry_error.exception), str(apply_error.exception))

        for target in targets:
            target.refresh_from_db()
            self.assertEqual(target.resolution_status, HistoricalRaceResolutionStatus.PENDING)
            self.assertIsNone(target.event_id)
        receipt = HistoricalRaceDetailImportReceipt.objects.get()
        self.assertEqual(receipt.status, HistoricalRaceDetailImportReceiptStatus.STARTED)
        self.assertEqual(RaceEvent.objects.count(), 0)
        self.assertEqual(RaceEventDataCandidate.objects.count(), 0)

    def test_target_drift_source_tamper_and_existing_event_fail_closed(self):
        target = self._target()
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            target.notes = "drift"
            target.save(update_fields={"notes"})
            # Notes are outside target identity, so drift a bound field instead.
            target.original_name = "Drifted"
            target.save(update_fields={"original_name"})
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))

    def test_artifact_paths_and_runner_lease_fail_closed(self):
        target = self._target(suffix="path")
        with TemporaryDirectory() as tmp, TemporaryDirectory() as outside:
            artifact = ChunkArtifact(Path(tmp), [target])
            outside_manifest = Path(outside) / "manifest.json"
            outside_manifest.write_bytes(artifact.chunk_manifest_path.read_bytes())
            kwargs = artifact.kwargs(runner_run_id=self.run.run_id)
            kwargs["chunk_manifest_path"] = outside_manifest
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**kwargs)

            kwargs = artifact.kwargs(runner_run_id=self.run.run_id)
            HistoricalBatchLock.objects.filter(key="global").update(
                lease_expires_at=timezone.now() - timedelta(seconds=1)
            )
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**kwargs)

    def test_runner_gate_requires_matching_private_owner_token(self):
        target = self._target(suffix="wrong-owner-token")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            kwargs = artifact.kwargs(runner_run_id=self.run.run_id)
            with patch.dict(
                os.environ,
                {"HISTORICAL_RUNNER_OWNER_TOKEN": "forged-owner-token"},
                clear=False,
            ), self.assertRaisesRegex(HistoricalRaceDetailChunkError, "owner token"):
                import_historical_race_detail_chunk(**kwargs)

        target = self._target(suffix="missing-owner-token")
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            artifact = ChunkArtifact(Path(tmp), [target])
            kwargs = artifact.kwargs(runner_run_id=self.run.run_id)
            os.environ.pop("HISTORICAL_RUNNER_OWNER_TOKEN", None)
            with self.assertRaisesRegex(HistoricalRaceDetailChunkError, "owner token"):
                import_historical_race_detail_chunk(**kwargs)

    def test_runner_gate_rejects_bundle_outside_run_artifact_root(self):
        target = self._target(suffix="wrong-artifact-root")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            kwargs = artifact.kwargs(runner_run_id=self.run.run_id)
            HistoricalBatchRun.objects.filter(pk=self.run.pk).update(
                artifact_root=self.runner_context.name
            )
            with self.assertRaisesRegex(HistoricalRaceDetailChunkError, "artifact root"):
                import_historical_race_detail_chunk(**kwargs)

    def test_runner_gate_rejects_forged_run_id_and_lease_takeover(self):
        target = self._target(suffix="forged-run")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            kwargs = artifact.kwargs(runner_run_id=self.run.run_id)
            forged = HistoricalBatchRun.objects.create(
                run_id="forged-chunk-run",
                batch_id=self.run.batch_id,
                phase=HistoricalBatchPhase.APPLY,
                status=HistoricalBatchRunStatus.RUNNING,
                network_enabled=False,
                write_enabled=True,
                image_id=self.run.image_id,
                image_revision=self.run.image_revision,
                artifact_root=str(artifact.root),
                plan_sha256=self.run.plan_sha256,
                owner_token_sha256=self.run.owner_token_sha256,
                current_step=self.run.current_step,
                lease_expires_at=timezone.now() + timedelta(minutes=5),
            )
            forged_kwargs = {**kwargs, "runner_run_id": forged.run_id}
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**forged_kwargs)

            takeover_token_sha = hashlib.sha256(b"takeover-owner").hexdigest()
            HistoricalBatchLock.objects.filter(key="global").update(
                locked_by_run=forged,
                owner_token_sha256=takeover_token_sha,
                lease_expires_at=timezone.now() + timedelta(minutes=5),
            )
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**kwargs)

    def test_apply_fence_selects_global_lock_for_update(self):
        target = self._target(suffix="transaction-fence")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            manager = HistoricalBatchLock.objects
            with patch.object(
                manager,
                "select_for_update",
                wraps=manager.select_for_update,
            ) as select_for_update:
                result = import_historical_race_detail_chunk(
                    **artifact.kwargs(runner_run_id=self.run.run_id)
                )

        self.assertEqual(result["status"], "completed")
        self.assertGreaterEqual(select_for_update.call_count, 1)

    def test_source_tamper_and_existing_event_conflict_fail_closed(self):
        target = self._target(suffix="tamper")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            source = artifact.chunk_dir / artifact.rows[0]["approved_source_cache_identity"]["path"]
            source.write_bytes(b"tampered")
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))

        target = self._target(suffix="existing")
        RaceEvent.objects.create(
            race_series=target.race_series,
            year=target.year,
            original_name=target.original_name,
            chinese_name=target.chinese_name,
            country_region=target.country_region,
            racecourse=target.racecourse,
            grade_text=target.grade_text,
            surface="",
        )
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))

    def test_current_year_due_gate_and_historical_year_gate(self):
        current = self._target(year=2026, suffix="due")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(
                Path(tmp), [current], layer="current_year_due", cutoff="2026-07-15"
            )
            result = import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))
            self.assertEqual(result["status"], "completed")

        invalid = self._target(year=2025, suffix="wrong-history")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [invalid])
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))

    def test_manual_distance_lock_is_reported_and_preserves_complete_value(self):
        target = self._target(suffix="manual")
        original_materialize = materialize_historical_event

        def locked_materialize(*args, **kwargs):
            event = original_materialize(*args, **kwargs)
            event.manual_lock_flags = {"distance_text": True}
            event.save(update_fields={"manual_lock_flags"})
            return event

        with TemporaryDirectory() as tmp, patch(
            "stable.services.historical_race_detail_chunk_import.materialize_historical_event",
            side_effect=locked_materialize,
        ):
            artifact = ChunkArtifact(Path(tmp), [target])
            result = import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))

        scope = result["completion_payload"]["targets"][0]
        target.refresh_from_db()
        self.assertEqual(target.event.distance_text, "1600m")
        self.assertIn("distance_text", scope["manual_locked_fields"])
        self.assertTrue(scope["basic_complete"])

    def test_verifier_checks_receipt_provenance_without_writing(self):
        target = self._target(suffix="verify")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))
            verify_run = self._switch_to_verify_runner()
            verify_kwargs = artifact.kwargs(runner_run_id=verify_run.run_id)
            report = verify_historical_race_detail_chunk(
                **verify_kwargs
            )
            before_logs = OperationLog.objects.count()
            target.refresh_from_db()
            target.event.source_refs = {"tampered": True}
            target.event.save(update_fields={"source_refs"})
            bad = verify_historical_race_detail_chunk(
                **verify_kwargs
            )

        self.assertEqual(report["error_count"], 0)
        self.assertGreater(bad["error_count"], 0)
        self.assertEqual(OperationLog.objects.count(), before_logs)

    def test_verifier_uses_receipt_candidate_ids_and_ignores_later_pending_candidate(self):
        target = self._target(suffix="receipt-candidates")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            result = import_historical_race_detail_chunk(
                **artifact.kwargs(runner_run_id=self.run.run_id)
            )
            candidate_receipts = result["completion_payload"]["targets"][0][
                "data_candidates"
            ]
            self.assertEqual(
                {row["module"] for row in candidate_receipts},
                {"runners", "results"},
            )
            self.assertEqual(len({row["id"] for row in candidate_receipts}), 2)

            target.refresh_from_db()
            RaceEventDataCandidate.objects.create(
                event=target.event,
                module="results",
                source_name="later-review",
                status="pending",
                candidate_payload={"items": []},
                raw_payload={"unrelated": True},
            )
            RaceEventDataCandidate.objects.create(
                event=target.event,
                module="runners",
                source_name="later-applied-review",
                status="applied",
                candidate_payload={"items": []},
                raw_payload={"unrelated": True},
            )
            verify_run = self._switch_to_verify_runner()
            report = verify_historical_race_detail_chunk(
                **artifact.kwargs(runner_run_id=verify_run.run_id)
            )

            replaced_id = candidate_receipts[0]["id"]
            original = RaceEventDataCandidate.objects.get(pk=replaced_id)
            original_payload = original.candidate_payload
            original_raw = original.raw_payload
            RaceEventDataCandidate.objects.filter(pk=original.pk).update(
                candidate_payload={"items": [{"tampered": True}]},
                raw_payload={**original_raw, "tampered": True},
            )
            tampered = verify_historical_race_detail_chunk(
                **artifact.kwargs(runner_run_id=verify_run.run_id)
            )
            RaceEventDataCandidate.objects.filter(pk=original.pk).update(
                candidate_payload=original_payload,
                raw_payload=original_raw,
            )
            original.refresh_from_db()
            replacement_values = {
                "event": original.event,
                "module": original.module,
                "source_name": original.source_name,
                "source_url": original.source_url,
                "status": original.status,
                "candidate_payload": original.candidate_payload,
                "raw_payload": original.raw_payload,
            }
            original.delete()
            replacement = RaceEventDataCandidate.objects.create(**replacement_values)
            self.assertNotEqual(replacement.pk, replaced_id)
            replaced = verify_historical_race_detail_chunk(
                **artifact.kwargs(runner_run_id=verify_run.run_id)
            )

        self.assertEqual(report["error_count"], 0)
        self.assertGreater(tampered["error_count"], 0)
        self.assertGreater(replaced["error_count"], 0)

    def test_reconcile_only_abandons_clean_started_receipt(self):
        targets = [self._target(suffix="reconcile-a"), self._target(suffix="reconcile-b")]
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), targets, invalid_last_result=True)
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))
        receipt = HistoricalRaceDetailImportReceipt.objects.get()
        self._bind_reconcile_runner(receipt.receipt_id)
        result = reconcile_historical_race_detail_receipt(
            receipt_id=receipt.receipt_id,
            runner_run_id=self.run.run_id,
            approved_by=self.user.username,
            reason="verified transaction rollback after parser failure",
        )
        receipt.refresh_from_db()
        self.assertEqual(result["status"], "abandoned")
        self.assertEqual(receipt.status, HistoricalRaceDetailImportReceiptStatus.ABANDONED)

        target = self._target(suffix="mixed")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target], invalid_last_result=True)
            with self.assertRaises(HistoricalRaceDetailChunkError):
                import_historical_race_detail_chunk(**artifact.kwargs(runner_run_id=self.run.run_id))
        target.resolution_status = HistoricalRaceResolutionStatus.READY
        target.save(update_fields={"resolution_status"})
        started = HistoricalRaceDetailImportReceipt.objects.get(status="started")
        self._bind_reconcile_runner(started.receipt_id)
        with self.assertRaises(HistoricalRaceDetailChunkError):
            reconcile_historical_race_detail_receipt(
                receipt_id=started.receipt_id,
                runner_run_id=self.run.run_id,
                approved_by=self.user.username,
                reason="must reject mixed state",
            )

    def test_distance_contract_accepts_raw_units_and_rejects_unknown(self):
        accepted = (
            "1600m",
            "１６００ｍ",
            "2.4km",
            "2m4f",
            "3m 210y",
            "One Mile",
            "Seven Furlongs",
            "About Six And One Half Furlongs",
        )
        for value in accepted:
            with self.subTest(value=value):
                self.assertEqual(validate_distance_text(value), value)
        for value in ("", "unknown", "about long distance"):
            with self.subTest(value=value), self.assertRaises(HistoricalRaceDetailChunkError):
                validate_distance_text(value)

    def test_real_sporting_life_provider_alias_resolves_to_shared_provider(self):
        self.assertEqual(
            resolve_source_provider("sporting_life", "sporting_life"),
            "uk_sportinglife",
        )
        with self.assertRaises(HistoricalRaceDetailChunkError):
            resolve_source_provider("sporting_life", "zeturf")

    def test_runner_phase_allowlists_expose_only_the_expected_chunk_commands(self):
        self.assertIn("import_historical_race_detail_chunk", _WRITE_MANAGEMENT_COMMANDS)
        self.assertIn("reconcile_historical_race_detail_receipt", _WRITE_MANAGEMENT_COMMANDS)
        self.assertNotIn("verify_historical_race_detail_chunk", _WRITE_MANAGEMENT_COMMANDS)
        self.assertIn("verify_historical_race_detail_chunk", _READ_MANAGEMENT_COMMANDS)
        self.assertNotIn("import_historical_race_detail_chunk", _READ_MANAGEMENT_COMMANDS)
        self.assertNotIn("reconcile_historical_race_detail_receipt", _READ_MANAGEMENT_COMMANDS)

    def test_runner_plan_binds_bundle_chunk_and_approval_sha_arguments(self):
        target = self._target(suffix="runner-binding")
        with TemporaryDirectory() as tmp:
            artifact = ChunkArtifact(Path(tmp), [target])
            step = {
                "id": "detail-chunk-apply",
                "argv": [
                    "python",
                    "manage.py",
                    "import_historical_race_detail_chunk",
                    "--bundle-dir",
                    str(artifact.root),
                    "--chunk-manifest",
                    str(artifact.chunk_manifest_path),
                    "--approval",
                    str(artifact.approval_path),
                    "--expected-bundle-sha256",
                    artifact.bundle_sha,
                    "--expected-chunk-sha256",
                    artifact.chunk_sha,
                    "--expected-approval-sha256",
                    artifact.approval_sha,
                    "--runner-run-id",
                    self.run.run_id,
                ],
                "inputs": [
                    {"path": str(artifact.bundle_manifest_path), "sha256": artifact.bundle_sha},
                    {"path": str(artifact.chunk_manifest_path), "sha256": artifact.chunk_sha},
                    {"path": str(artifact.approval_path), "sha256": artifact.approval_sha},
                ],
                "approval": {
                    "status": "approved",
                    "path": str(artifact.approval_path),
                    "sha256": artifact.approval_sha,
                },
                "expected_sha256": artifact.chunk_sha,
            }
            _validate_apply_bindings(
                step=step,
                command="import_historical_race_detail_chunk",
                artifact_root=artifact.root.resolve(),
            )
            step["argv"][step["argv"].index("--expected-approval-sha256") + 1] = "0" * 64
            with self.assertRaises(RunnerPlanError):
                _validate_apply_bindings(
                    step=step,
                    command="import_historical_race_detail_chunk",
                    artifact_root=artifact.root.resolve(),
                )

    def test_apply_runner_plan_accepts_detail_chunk_dry_run_without_weakening_identity(self):
        target = self._target(suffix="runner-dry-run")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = ChunkArtifact(root / "artifacts", [target])
            step = {
                "id": "detail-chunk-dry-run",
                "kind": "management",
                "argv": [
                    "python",
                    "manage.py",
                    "import_historical_race_detail_chunk",
                    "--bundle-dir",
                    str(artifact.root),
                    "--chunk-manifest",
                    str(artifact.chunk_manifest_path),
                    "--approval",
                    str(artifact.approval_path),
                    "--expected-bundle-sha256",
                    artifact.bundle_sha,
                    "--expected-chunk-sha256",
                    artifact.chunk_sha,
                    "--expected-approval-sha256",
                    artifact.approval_sha,
                    "--runner-run-id",
                    self.run.run_id,
                    "--dry-run",
                ],
                "inputs": [
                    {"path": str(artifact.bundle_manifest_path), "sha256": artifact.bundle_sha},
                    {"path": str(artifact.chunk_manifest_path), "sha256": artifact.chunk_sha},
                    {"path": str(artifact.approval_path), "sha256": artifact.approval_sha},
                ],
                "outputs": [],
                "approval": {
                    "status": "approved",
                    "path": str(artifact.approval_path),
                    "sha256": artifact.approval_sha,
                },
                "expected_sha256": artifact.chunk_sha,
            }
            plan = {
                "schema_version": "1.0",
                "batch_id": self.run.batch_id,
                "phase": HistoricalBatchPhase.APPLY,
                "network_enabled": False,
                "write_enabled": True,
                "image_id": "sha256:" + "1" * 64,
                "image_revision": "a" * 40,
                "artifact_root": str(artifact.root),
                "tool_root": str(root / "tools"),
                "tool_manifest": {},
                "steps": [step],
            }

            self.assertEqual(validate_runner_plan(plan)["phase"], HistoricalBatchPhase.APPLY)

            step["inputs"] = [
                identity
                for identity in step["inputs"]
                if identity["path"] != str(artifact.chunk_manifest_path)
            ]
            with self.assertRaises(RunnerPlanError):
                validate_runner_plan(plan)
