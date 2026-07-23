from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from unittest import mock, skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import SimpleTestCase, TransactionTestCase

from stable.models import (
    HistoricalRaceEventTarget,
    OperationLog,
    RaceEvent,
    RaceEventStatus,
    RaceEventSurface,
    RaceSeries,
    RaceSeriesRelation,
    RaceSeriesRelationType,
    RacingRegion,
)
from stable.services import race_series_identity_2026_review as review_2026
from stable.services import race_series_identity_review as identity_review


def _classification(
    target_id: int,
    *,
    classification: str,
    reason: str = "",
    event_id: int | None = None,
    candidate_event_ids: list[int] | None = None,
) -> dict:
    candidate_ids = candidate_event_ids or ([] if event_id is None else [event_id])
    candidate_identity = None
    if event_id is not None:
        candidate_identity = {
            "payload": {
                "id": event_id,
                "race_series_id": 20_000 + target_id,
                "series_key": f"source-{target_id}",
                "original_name": f"Race {target_id}",
            },
            "sha256": f"event-{event_id}",
        }
    return {
        "target_id": target_id,
        "target_identity": {
            "payload": {"id": target_id, "race_series_id": 10_000 + target_id},
            "sha256": f"target-{target_id}",
        },
        "country_region": RacingRegion.JAPAN,
        "year": 2026,
        "series_id": 10_000 + target_id,
        "series_key": f"target-{target_id}",
        "expectation_status": "held",
        "resolution_status": "pending",
        "event_id": event_id,
        "candidate_event_identity": candidate_identity,
        "candidate_event_ids": candidate_ids,
        "classification": classification,
        "reason": reason,
        "target_original_name": f"Race {target_id}",
        "target_chinese_name": f"赛事 {target_id}",
    }


def _compatible_dependency(target_id: int, event_id: int) -> dict:
    return {
        "target_id": target_id,
        "source_series_id": 20_000 + target_id,
        "destination_series_id": 10_000 + target_id,
        "event_id": event_id,
        "source_annual_event_ids": [event_id],
        "source_target_ids": [],
        "source_name_ids": [],
        "source_relation_ids": [],
        "destination_year_event_ids": [],
        "event_owner_target_id": None,
        "do_not_merge": False,
        "region_matches": True,
        "year_matches": True,
        "status_compatible": True,
        "detail_consistent": True,
    }


class RaceSeriesIdentity2026EquivalentScaleTests(SimpleTestCase):
    def test_production_equivalent_partition_is_deterministic_and_bounded(self):
        classifications: list[dict] = []
        dependencies: dict[int, dict] = {}
        alias_suggestions: dict[int, list[dict]] = {}
        no_match_target_ids: list[int] = []
        next_id = 1

        for _ in range(684):
            classifications.append(
                _classification(
                    next_id,
                    classification="already_linked",
                    event_id=50_000 + next_id,
                )
            )
            next_id += 1
        for _ in range(226):
            event_id = 50_000 + next_id
            classifications.append(
                _classification(
                    next_id,
                    classification="identity_conflict",
                    reason="series_mismatch",
                    event_id=event_id,
                )
            )
            dependencies[next_id] = _compatible_dependency(next_id, event_id)
            next_id += 1
        for _ in range(11):
            classifications.append(
                _classification(
                    next_id,
                    classification="identity_conflict",
                    reason="ambiguous_name_match",
                    candidate_event_ids=[50_000 + next_id, 60_000 + next_id],
                )
            )
            next_id += 1
        for _ in range(162):
            no_match_target_ids.append(next_id)
            classifications.append(
                _classification(
                    next_id,
                    classification="missing_event",
                    reason="no_series_year_event",
                )
            )
            next_id += 1

        # The production inventory has roughly 1,500 annual events. The base
        # classifications above carry 932 event identities, so distribute 568
        # additional alias suggestions across unresolved rows to exercise the
        # same candidate-volume boundary without requiring production data.
        for offset in range(568):
            target_id = no_match_target_ids[offset % len(no_match_target_ids)]
            alias_suggestions.setdefault(target_id, []).append(
                {
                    "event_id": 100_000 + offset,
                    "event_series_id": 200_000 + offset,
                    "country_region": RacingRegion.JAPAN,
                    "source": "equivalent_scale_fixture",
                }
            )
        for _ in range(2):
            classifications.append(
                _classification(
                    next_id,
                    classification="status_conflict",
                    reason="not_held_target",
                )
            )
            next_id += 1

        started = time.perf_counter()
        first = review_2026.build_review_snapshot(
            classifications=classifications,
            alias_suggestions_by_target=alias_suggestions,
            dependency_facts=dependencies,
        )
        second = review_2026.build_review_snapshot(
            classifications=reversed(classifications),
            alias_suggestions_by_target=alias_suggestions,
            dependency_facts=dependencies,
        )
        elapsed = time.perf_counter() - started

        self.assertEqual(
            first["counts"],
            {
                "already_linked": 684,
                "ambiguous_name_match": 11,
                "no_name_match": 162,
                "not_held": 2,
                "total_targets": 1085,
                "unique_series_mismatch": 226,
            },
        )
        self.assertEqual(len(first["all_rows"]), 1085)
        self.assertEqual(len({row["target_id"] for row in first["all_rows"]}), 1085)
        self.assertEqual(
            sum(len(rows) for rows in first["sheets"].values()),
            401,
        )
        self.assertEqual(
            sum(row["engine_compatible"] for row in first["sheets"]["唯一名称匹配"]),
            226,
        )
        represented_event_ids = {
            event_id
            for row in first["all_rows"]
            for event_id in row["candidate_event_ids"]
        } | {
            suggestion["event_id"]
            for row in first["all_rows"]
            for suggestion in row["supplemental_suggestions"]
        }
        self.assertEqual(len(represented_event_ids), 1500)
        first_sha = hashlib.sha256(
            json.dumps(first, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        second_sha = hashlib.sha256(
            json.dumps(second, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.assertEqual(first_sha, second_sha)
        self.assertLess(elapsed, 5.0, f"two 1,085-target builds took {elapsed:.3f}s")


@skipUnless(
    connection.vendor == "postgresql",
    "requires PostgreSQL; SQLite is not concurrency evidence",
)
class RaceSeriesIdentity2026SnapshotPostgresTests(TransactionTestCase):
    reset_sequences = True

    @staticmethod
    def _series(key: str, name: str) -> RaceSeries:
        return RaceSeries.objects.create(
            key=key,
            country_region=RacingRegion.JAPAN,
            canonical_name_original=name,
        )

    def test_export_keeps_one_repeatable_read_snapshot_across_concurrent_commit(self):
        original_series = self._series("snapshot-original", "Snapshot Original")
        target = HistoricalRaceEventTarget.objects.create(
            race_series=original_series,
            year=2026,
            country_region=RacingRegion.JAPAN,
            original_name="Snapshot Original",
            local_date=date(2026, 5, 1),
        )

        first_read_complete = threading.Event()
        writer_committed = threading.Event()
        result: dict = {}
        failure: list[BaseException] = []
        isolation_levels: list[str] = []
        real_classifier = review_2026.classify_historical_race_event_targets

        def pause_after_target_read(targets):
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                isolation_levels.append(cursor.fetchone()[0])
            first_read_complete.set()
            if not writer_committed.wait(timeout=10):
                raise AssertionError("writer did not commit before export resumed")
            return real_classifier(targets)

        def export_in_thread():
            close_old_connections()
            try:
                with mock.patch.object(
                    review_2026,
                    "classify_historical_race_event_targets",
                    side_effect=pause_after_target_read,
                ):
                    result["snapshot"] = review_2026.export_2026_review_snapshot()
            except BaseException as exc:  # pragma: no cover - surfaced in the parent thread
                failure.append(exc)
            finally:
                close_old_connections()

        worker = threading.Thread(target=export_in_thread, name="race-series-2026-export")
        worker.start()
        self.assertTrue(first_read_complete.wait(timeout=10), "export did not reach snapshot hook")

        concurrent_series = self._series("snapshot-concurrent", "Concurrent Match")
        RaceEvent.objects.create(
            race_series=concurrent_series,
            year=2026,
            slug="concurrent-match-2026",
            original_name="Concurrent Match",
            chinese_name="并发匹配",
            country_region=RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G3",
            surface=RaceEventSurface.TURF,
            local_date=date(2026, 5, 1),
            status=RaceEventStatus.SCHEDULED,
        )
        HistoricalRaceEventTarget.objects.filter(pk=target.pk).update(
            original_name="Concurrent Match"
        )
        inserted_target_series = self._series("snapshot-inserted-target", "Inserted Target")
        HistoricalRaceEventTarget.objects.create(
            race_series=inserted_target_series,
            year=2026,
            country_region=RacingRegion.JAPAN,
            original_name="Inserted Target",
        )
        writer_committed.set()
        worker.join(timeout=15)

        self.assertFalse(worker.is_alive(), "export thread did not finish")
        if failure:
            raise failure[0]
        self.assertEqual(isolation_levels, ["repeatable read"])
        snapshot = result["snapshot"]
        self.assertEqual(snapshot["counts"]["total_targets"], 1)
        self.assertEqual(snapshot["counts"].get("no_name_match"), 1)
        self.assertEqual(snapshot["all_rows"][0]["target_original_name"], "Snapshot Original")
        self.assertEqual(snapshot["all_rows"][0]["candidate_event_ids"], [])

        target.refresh_from_db()
        self.assertEqual(target.original_name, "Concurrent Match")
        self.assertEqual(HistoricalRaceEventTarget.objects.filter(year=2026).count(), 2)
        self.assertEqual(RaceEvent.objects.filter(year=2026).count(), 1)


@skipUnless(
    connection.vendor == "postgresql",
    "requires PostgreSQL; SQLite is not concurrency evidence",
)
class RaceSeriesIdentity2026ConcurrentApplyPostgresTests(TransactionTestCase):
    reset_sequences = True

    @staticmethod
    def _series(key: str) -> RaceSeries:
        return RaceSeries.objects.create(
            key=key,
            country_region=RacingRegion.JAPAN,
            canonical_name_original="Concurrent Identity Race",
            chinese_name="并发身份赛事",
        )

    @staticmethod
    def _event(series: RaceSeries, slug: str) -> RaceEvent:
        return RaceEvent.objects.create(
            race_series=series,
            year=2026,
            slug=slug,
            original_name="Concurrent Identity Race",
            chinese_name="并发身份赛事",
            country_region=RacingRegion.JAPAN,
            racecourse="Tokyo",
            grade_text="G3",
            normalized_grade="G3",
            surface=RaceEventSurface.TURF,
            distance_text="1800",
            local_date=date(2026, 6, 1),
            status=RaceEventStatus.SCHEDULED,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _prepare_manifest(
        self,
        *,
        root: Path,
        label: str,
        target: HistoricalRaceEventTarget,
        event: RaceEvent,
        actor_username: str,
    ) -> dict:
        decisions_path = root / f"{label}-decisions.json"
        repairs_path = root / f"{label}-repairs.json"
        decisions_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "source": "postgres-concurrency-test",
                    "source_sha256": label * 64,
                    "decisions": [
                        {
                            "decision_id": f"{label}:1",
                            "sheet": "唯一名称匹配",
                            "sequence": 1,
                            "decision": "merge_and_link",
                            "target_id": target.pk,
                            "target_series_id": target.race_series_id,
                            "event_id": event.pk,
                            "event_series_id": event.race_series_id,
                            "year": 2026,
                            "country_region": RacingRegion.JAPAN,
                            "confidence": "high",
                            "evidence": {
                                "summary": f"concurrent candidate {label}",
                                "source_urls": [f"https://example.test/{label}"],
                            },
                        }
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        repairs_path.write_text(
            json.dumps(
                {"schema_version": "1.0", "repairs": []},
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        artifact_dir = root / f"artifact-{label}"
        prepared = identity_review.prepare_race_series_identity_review(
            decisions_path=decisions_path,
            field_repairs_path=repairs_path,
            output_dir=artifact_dir,
        )
        approval_path = artifact_dir / "approval.json"
        approval_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "approved",
                    "approved_by": actor_username,
                    "approved_at": "2026-07-23T02:00:00+00:00",
                    "manifest_sha256": prepared["manifest_sha256"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "artifact_dir": artifact_dir,
            "manifest_sha256": prepared["manifest_sha256"],
            "approval_path": approval_path,
            "approval_sha256": self._sha256(approval_path),
        }

    def test_two_prepared_manifests_compete_for_one_target_and_only_one_commits(self):
        actor = get_user_model().objects.create_user(
            username="concurrent-identity-reviewer",
            password="unused",
        )
        destination = self._series("concurrent-destination")
        source_a = self._series("concurrent-source-a")
        source_b = self._series("concurrent-source-b")
        target = HistoricalRaceEventTarget.objects.create(
            race_series=destination,
            year=2026,
            country_region=RacingRegion.JAPAN,
            original_name="Concurrent Identity Race",
            chinese_name="并发身份赛事",
            racecourse="Tokyo",
            grade_text="G3",
            normalized_grade="G3",
            surface=RaceEventSurface.TURF,
            distance_text="1800",
            local_date=date(2026, 6, 1),
        )
        event_a = self._event(source_a, "concurrent-identity-a-2026")
        event_b = self._event(source_b, "concurrent-identity-b-2026")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact_a = self._prepare_manifest(
                root=root,
                label="a",
                target=target,
                event=event_a,
                actor_username=actor.username,
            )
            artifact_b = self._prepare_manifest(
                root=root,
                label="b",
                target=target,
                event=event_b,
                actor_username=actor.username,
            )

            start_gate = threading.Barrier(2, timeout=10)
            real_lock_action_rows = identity_review._lock_action_rows
            outcomes: dict[str, tuple[str, object]] = {}

            def synchronized_lock(actions):
                start_gate.wait()
                return real_lock_action_rows(actions)

            def apply_in_thread(label: str, artifact: dict):
                close_old_connections()
                try:
                    result = identity_review.apply_race_series_identity_review(
                        artifact_dir=artifact["artifact_dir"],
                        expected_manifest_sha256=artifact["manifest_sha256"],
                        approval_path=artifact["approval_path"],
                        expected_approval_sha256=artifact["approval_sha256"],
                        actor=actor,
                    )
                    outcomes[label] = ("success", result)
                except BaseException as exc:  # pragma: no cover - asserted in parent thread
                    outcomes[label] = ("failure", exc)
                finally:
                    close_old_connections()

            with mock.patch.object(
                identity_review,
                "_lock_action_rows",
                side_effect=synchronized_lock,
            ):
                worker_a = threading.Thread(
                    target=apply_in_thread,
                    args=("a", artifact_a),
                    name="identity-apply-a",
                )
                worker_b = threading.Thread(
                    target=apply_in_thread,
                    args=("b", artifact_b),
                    name="identity-apply-b",
                )
                worker_a.start()
                worker_b.start()
                worker_a.join(timeout=20)
                worker_b.join(timeout=20)

            self.assertFalse(worker_a.is_alive(), "first apply thread did not finish")
            self.assertFalse(worker_b.is_alive(), "second apply thread did not finish")
            self.assertEqual(set(outcomes), {"a", "b"})
            successes = {
                label: value
                for label, (state, value) in outcomes.items()
                if state == "success"
            }
            failures = {
                label: value
                for label, (state, value) in outcomes.items()
                if state == "failure"
            }
            self.assertEqual(len(successes), 1, outcomes)
            self.assertEqual(len(failures), 1, outcomes)
            failure_text = str(next(iter(failures.values()))).casefold()
            self.assertRegex(
                failure_text,
                r"drift|dependency|conflict|serialize|concurrent update",
            )

            winning_label = next(iter(successes))
            winning_event = event_a if winning_label == "a" else event_b
            losing_event = event_b if winning_label == "a" else event_a
            winning_source = source_a if winning_label == "a" else source_b
            losing_source = source_b if winning_label == "a" else source_a

            target.refresh_from_db()
            winning_event.refresh_from_db()
            losing_event.refresh_from_db()
            self.assertEqual(target.event_id, winning_event.pk)
            self.assertEqual(winning_event.race_series_id, destination.pk)
            self.assertEqual(losing_event.race_series_id, losing_source.pk)
            self.assertEqual(
                RaceEvent.objects.filter(race_series=destination, year=2026).count(),
                1,
            )
            self.assertEqual(
                RaceSeriesRelation.objects.filter(
                    to_series=destination,
                    relation_type=RaceSeriesRelationType.MERGED_INTO,
                ).count(),
                1,
            )
            self.assertTrue(
                RaceSeriesRelation.objects.filter(
                    from_series=winning_source,
                    to_series=destination,
                    relation_type=RaceSeriesRelationType.MERGED_INTO,
                ).exists()
            )
            self.assertFalse(
                RaceSeriesRelation.objects.filter(
                    from_series=losing_source,
                    to_series=destination,
                    relation_type=RaceSeriesRelationType.MERGED_INTO,
                ).exists()
            )
            logs = OperationLog.objects.filter(
                action_type="race_series_identity_review_applied",
                admin=actor,
            )
            self.assertEqual(logs.count(), 1)
            self.assertEqual(
                logs.get().target_id,
                artifact_a["manifest_sha256"][:16]
                if winning_label == "a"
                else artifact_b["manifest_sha256"][:16],
            )
