from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from stable.models import (
    HorseP0Source,
    HorseProfile,
    HorseProfileDataCandidate,
    HorseRaceRecord,
    RaceEvent,
    TaskExecutionLog,
    TermEntry,
    TermTranslationStatus,
    TermType,
)
from stable.services.p0_horse_production_apply import (
    P0ReviewedArtifactError,
    build_profile_mapping_snapshot,
    build_profile_snapshot,
    commit_reviewed_p0_completion_artifact,
    dry_run_reviewed_p0_completion_artifact,
    prepare_reviewed_p0_completion_artifact,
    sha256_file,
    validate_frozen_p0_research_inputs,
)
from stable.services.horse_race_records import upsert_race_record


class P0HorseProductionApplyTests(TestCase):
    maxDiff = None

    def setUp(self):
        self.reviewer = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="unused",
        )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_json(self, name: str, payload: dict) -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def _identity(self, index: int, *, name: str | None = None) -> dict:
        return {
            "horse_name": name or f"Horse {index:02d}",
            "sire_name": f"Sire {index:02d}",
            "dam_name": f"Dam {index:02d}",
            "birth_year": 2010 + index % 10,
        }

    def _record(self, horse_index: int, record_index: int, *, nonstarter: bool = False) -> dict:
        race_date = date(2018, 1, 1) + timedelta(days=horse_index * 40 + record_index)
        result_status = "scratched" if nonstarter else ("won" if record_index == 0 else "unplaced")
        return {
            "external_result_id": f"result-{horse_index:02d}-{record_index:03d}",
            "external_race_id": f"race-{horse_index:02d}-{record_index:03d}",
            "race_date": race_date.isoformat(),
            "race_name": f"Race {horse_index:02d}-{record_index:03d}",
            "racecourse": f"Course {horse_index % 5}",
            "distance_text": "1600m",
            "finish": "SCR" if nonstarter else ("1" if record_index == 0 else "5"),
            "result_status": result_status,
            "start_status": "did_not_start" if nonstarter else "started",
            "source_name": "reviewed_source",
            "source_url": f"https://evidence.example/races/{horse_index}/{record_index}",
            "is_overseas": bool(record_index == 1),
        }

    def _horse(self, index: int, *, name: str | None = None, record_count: int = 2, nonstarter: bool = False) -> dict:
        identity = self._identity(index, name=name)
        records = [
            self._record(index, record_index, nonstarter=nonstarter and record_index == record_count - 1)
            for record_index in range(record_count)
        ]
        actual_count = record_count - int(nonstarter)
        latest_date = max(record["race_date"] for record in records)
        return {
            "schema_version": "p0-horse-research-row.v3",
            "region": ("japan", "hong_kong", "united_kingdom", "france", "united_states")[index % 5],
            "identity": identity,
            "candidate": {
                "candidate_key": f"candidate-{index:02d}",
                "horse_name": identity["horse_name"],
                "aliases": [identity["horse_name"]],
                "identity_keys": [f"provider:{index:02d}"],
                "source_urls": [f"https://candidate.example/horses/{index}"],
            },
            "source": {
                "name": "reviewed_source",
                "url": f"https://evidence.example/horses/{index}",
                "external_horse_id": f"horse-{index:02d}",
                "fetched_at": "2026-07-20T00:00:00Z",
            },
            "aliases": [{"name": identity["horse_name"], "language": "en", "is_original": True}],
            "basic_profile": {
                "country": "JP",
                "sex": "c",
                "color": "bay",
                "birth_date": f"{identity['birth_year']}-01-01",
                "owner_name": f"Owner {index}",
                "trainer_name": f"Trainer {index}",
                "breeder_name": f"Breeder {index}",
            },
            "pedigree": {
                "sire": identity["sire_name"],
                "dam": identity["dam_name"],
                "sire_sire": f"SireSire {index}",
                "sire_dam": f"SireDam {index}",
                "dam_sire": f"DamSire {index}",
                "dam_dam": f"DamDam {index}",
            },
            "career": {
                "records": records,
                "career_record_count": record_count,
                "official_or_source_start_count": actual_count,
                "source_start_count": actual_count,
                "collected_start_count": actual_count,
                "nonstarter_count": int(nonstarter),
                "unconfirmed_count": 0,
                "overseas_start_count": int(record_count > 1),
                "missing_start_count": 0,
                "excess_start_count": 0,
                "gap_count": 0,
                "record_authority_status": "source_records_verified",
                "career_collection_status": "complete",
                "official_start_count_source": "reviewed_source",
                "official_start_count_source_url": f"https://evidence.example/horses/{index}",
                "official_start_count_verified_at": "2026-07-20T00:00:00Z",
                "records_synced_through": latest_date,
            },
            "field_status": {
                "missing_basic_profile_fields": [],
                "missing_pedigree_fields": [],
                "career_gap_count": 0,
            },
            "source_evidence": [
                {
                    "source_name": "reviewed_source",
                    "source_url": f"https://evidence.example/horses/{index}",
                }
            ],
        }

    def _research(self, horses: list[dict]) -> tuple[Path, dict]:
        authority = {
            "schema_version": "p0-horse-us-career-source-authority-review.v1",
            "review_status": "approved",
            "reviewed_by": "project_owner",
            "reviewer_id": self.reviewer.id,
            "approved_at": "2026-07-20T00:00:00Z",
            "decision_source_reference": "codex-task:test-authority",
            "input": {
                "sha256": "a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7"
            },
            "horses": [
                {
                    "identity": horse["identity"],
                    "record_count": len(horse["career"]["records"]),
                }
                for horse in horses
                if horse["region"] == "united_states"
            ],
        }
        authority_path = self._write_json("authority.json", authority)
        research = {
            "schema_version": "p0-horse-research.v3",
            "career_authority_review_application": {
                "schema_version": "p0-horse-us-career-source-authority-application.v1",
                "input_sha256": authority["input"]["sha256"],
                "review_artifact_sha256": sha256_file(authority_path),
                "approved_horse_count": len(authority["horses"]),
                "record_authority_status": "source_records_verified",
            },
            "horses": horses,
        }
        path = self._write_json("research-v3.json", research)
        self.research_sha256 = sha256_file(path)
        return path, authority

    def _create_profile(
        self,
        identity: dict,
        *,
        profile_id: int | None = None,
        alias_only: bool = False,
    ) -> HorseProfile:
        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language="en",
            source_ja=(f"Alias holder {identity['horse_name']}" if alias_only else identity["horse_name"]),
            target_zh="",
            translation_status=TermTranslationStatus.PENDING,
            is_active=True,
        )
        if alias_only:
            term.source_aliases.create(source_language="en", text=identity["horse_name"])
        create_kwargs = {
            "primary_term": term,
            "original_name": term.source_ja,
            "english_name": term.source_ja,
            "racing_region": "japan",
        }
        if profile_id is not None:
            create_kwargs["id"] = profile_id
        return HorseProfile.objects.create(**create_kwargs)

    def _mapping(self, horses: list[dict], resolutions: list[dict]) -> Path:
        rows = []
        for horse, resolution in zip(horses, resolutions):
            identity = horse["identity"]
            row = {
                "identity": identity,
                "decision": resolution["decision"],
                "decision_evidence": {
                    "reviewed_by": "project_owner",
                    "approved_at": "2026-07-20T00:00:00Z",
                    "decision_source_reference": "codex-task:test-profile-mapping",
                    "reason": resolution.get("reason", "explicit reviewed mapping"),
                },
                "module_reviews": {
                    module: {
                        "status": "approved",
                        "confidence": 100,
                        "reviewed_by": "project_owner",
                        "approved_at": "2026-07-20T00:00:00Z",
                        "decision_source_reference": "codex-task:test-module-review",
                    }
                    for module in ("profile", "pedigree", "race_record", "major_wins")
                },
                "completion_decision": {
                    "racing_career_status": "retired",
                    "records_synced_through": horse["career"]["records_synced_through"],
                    "reviewed_by": "project_owner",
                    "approved_at": "2026-07-20T00:00:00Z",
                    "decision_source_reference": "codex-task:test-career-state",
                },
                "database_mapping_snapshot": build_profile_mapping_snapshot(identity),
            }
            if resolution["decision"] == "bind_existing":
                profile = resolution["profile"]
                row.update(
                    {
                        "profile_id": profile.id,
                        "profile_snapshot": build_profile_snapshot(profile),
                        "name_evidence": identity["horse_name"],
                        "rejected_profile_ids": resolution.get("rejected_profile_ids", []),
                        "rejection_reason": resolution.get("rejection_reason", ""),
                    }
                )
            rows.append(row)
        mapping = {
            "schema_version": "p0-horse-profile-mapping-decisions.v1",
            "review_status": "approved",
            "reviewed_by": "project_owner",
            "reviewer_id": self.reviewer.id,
            "approved_at": "2026-07-20T00:00:00Z",
            "decision_source_reference": "codex-task:test-profile-mapping",
            "research_v3_sha256": self.research_sha256,
            "production_snapshot_sha256": hashlib.sha256(
                json.dumps(
                    [
                        {
                            "identity_key": hashlib.sha256(
                                "|".join(
                                    (
                                        row["identity"]["horse_name"].casefold(),
                                        row["identity"]["sire_name"].casefold(),
                                        row["identity"]["dam_name"].casefold(),
                                        str(row["identity"]["birth_year"]),
                                    )
                                ).encode("utf-8")
                            ).hexdigest(),
                            "database_mapping_snapshot": row[
                                "database_mapping_snapshot"
                            ],
                        }
                        for row in sorted(
                            rows,
                            key=lambda item: hashlib.sha256(
                                "|".join(
                                    (
                                        item["identity"]["horse_name"].casefold(),
                                        item["identity"]["sire_name"].casefold(),
                                        item["identity"]["dam_name"].casefold(),
                                        str(item["identity"]["birth_year"]),
                                    )
                                ).encode("utf-8")
                            ).hexdigest(),
                        )
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "rows": rows,
        }
        return self._write_json("mapping.json", mapping)

    def _prepare(self, horses: list[dict], resolutions: list[dict]) -> tuple[Path, dict]:
        research_path, _ = self._research(horses)
        authority_path = self.root / "authority.json"
        mapping_path = self._mapping(horses, resolutions)
        artifact = prepare_reviewed_p0_completion_artifact(
            research_v3_path=research_path,
            authority_manifest_path=authority_path,
            authority_manifest_sha256=sha256_file(authority_path),
            profile_mapping_decisions_path=mapping_path,
            reviewer_id=self.reviewer.id,
        )
        artifact_path = self._write_json("reviewed-artifact.json", artifact)
        return artifact_path, artifact

    def _release(self, artifact_path: Path, artifact: dict | None = None) -> tuple[Path, str]:
        artifact = artifact or json.loads(artifact_path.read_text(encoding="utf-8"))
        release_manifest = {
            "schema_version": "p0_horse_production_release_manifest.v1",
            "bindings": {
                "research_v3_sha256": artifact["inputs"]["research_v3"]["sha256"],
                "authority_manifest_sha256": artifact["inputs"]["authority_manifest"]["sha256"],
                "profile_mapping_decisions_sha256": artifact["inputs"][
                    "profile_mapping_decisions"
                ]["sha256"],
                "production_snapshot_sha256": artifact["production_snapshot_sha256"],
                "final_artifact_sha256": sha256_file(artifact_path),
            },
            "approved_by": "external_project_owner",
            "approved_at": "2026-07-20T00:00:00Z",
            "decision_reference": "codex-task:test-independent-production-release",
            "executor_reviewer_id": self.reviewer.id,
        }
        release_path = self._write_json("release-manifest.json", release_manifest)
        return release_path, sha256_file(release_path)

    def _dry_run(self, artifact_path: Path) -> dict:
        release_path, release_sha = self._release(artifact_path)
        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ):
            return dry_run_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=sha256_file(artifact_path),
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
            )

    def _commit(self, artifact_path: Path) -> dict:
        release_path, release_sha = self._release(artifact_path)
        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ):
            return commit_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=sha256_file(artifact_path),
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
                confirm_reviewed_artifact=True,
            )

    def test_release_gate_rejects_operator_made_manifest_when_trusted_allowlist_is_empty(self):
        horse = self._horse(0)
        artifact_path, artifact = self._prepare(
            [horse],
            [{"decision": "create_new"}],
        )
        release_manifest = {
            "schema_version": "p0_horse_production_release_manifest.v1",
            "bindings": {
                "research_v3_sha256": artifact["inputs"]["research_v3"]["sha256"],
                "authority_manifest_sha256": artifact["inputs"]["authority_manifest"]["sha256"],
                "profile_mapping_decisions_sha256": artifact["inputs"][
                    "profile_mapping_decisions"
                ]["sha256"],
                "production_snapshot_sha256": artifact["production_snapshot_sha256"],
                "final_artifact_sha256": sha256_file(artifact_path),
            },
            "approved_by": "project_owner",
            "approved_at": "2026-07-20T00:00:00Z",
            "decision_reference": "codex-task:test-release-decision",
            "executor_reviewer_id": self.reviewer.id,
        }
        release_path = self._write_json("release-manifest.json", release_manifest)

        with self.assertRaisesRegex(P0ReviewedArtifactError, "trusted allowlist"):
            dry_run_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=sha256_file(artifact_path),
                release_manifest_path=release_path,
                release_manifest_sha256=sha256_file(release_path),
            )

    def test_release_gate_rejects_trusted_manifest_with_binding_or_role_drift(self):
        horse = self._horse(0)
        artifact_path, artifact = self._prepare(
            [horse],
            [{"decision": "create_new"}],
        )
        release_path, _ = self._release(artifact_path, artifact)
        release = json.loads(release_path.read_text(encoding="utf-8"))
        release["bindings"]["production_snapshot_sha256"] = "0" * 64
        release_path = self._write_json("release-manifest.json", release)
        release_sha = sha256_file(release_path)
        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ), self.assertRaisesRegex(P0ReviewedArtifactError, "bindings"):
            dry_run_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=sha256_file(artifact_path),
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
            )

        release["bindings"]["production_snapshot_sha256"] = artifact[
            "production_snapshot_sha256"
        ]
        release["approved_by"] = self.reviewer.username
        release_path = self._write_json("release-manifest.json", release)
        release_sha = sha256_file(release_path)
        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ), self.assertRaisesRegex(P0ReviewedArtifactError, "separate"):
            dry_run_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=sha256_file(artifact_path),
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
            )

    def test_prepare_requires_explicit_mapping_and_rejects_name_only_or_missing_reviewer(self):
        horse = self._horse(0)
        research_path, _ = self._research([horse])
        authority_path = self.root / "authority.json"
        with self.assertRaisesRegex(P0ReviewedArtifactError, "mapping"):
            prepare_reviewed_p0_completion_artifact(
                research_v3_path=research_path,
                authority_manifest_path=authority_path,
                authority_manifest_sha256=sha256_file(authority_path),
                profile_mapping_decisions_path=None,
                reviewer_id=self.reviewer.id,
            )

        profile = self._create_profile(horse["identity"])
        mapping_path = self._mapping(
            [horse],
            [{"decision": "bind_existing", "profile": profile}],
        )
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        del mapping["rows"][0]["profile_id"]
        self._write_json("mapping.json", mapping)
        with self.assertRaisesRegex(P0ReviewedArtifactError, "profile_id"):
            prepare_reviewed_p0_completion_artifact(
                research_v3_path=research_path,
                authority_manifest_path=authority_path,
                authority_manifest_sha256=sha256_file(authority_path),
                profile_mapping_decisions_path=mapping_path,
                reviewer_id=self.reviewer.id,
            )

        with self.assertRaisesRegex(P0ReviewedArtifactError, "reviewer"):
            prepare_reviewed_p0_completion_artifact(
                research_v3_path=research_path,
                authority_manifest_path=authority_path,
                authority_manifest_sha256=sha256_file(authority_path),
                profile_mapping_decisions_path=mapping_path,
                reviewer_id=999999,
            )

    def test_prepare_rejects_sha_identity_duplicate_race_url_module_and_snapshot_drift(self):
        horse = self._horse(0)
        profile = self._create_profile(horse["identity"])
        research_path, _ = self._research([horse])
        authority_path = self.root / "authority.json"
        mapping_path = self._mapping(
            [horse],
            [{"decision": "bind_existing", "profile": profile}],
        )
        kwargs = {
            "research_v3_path": research_path,
            "authority_manifest_path": authority_path,
            "authority_manifest_sha256": sha256_file(authority_path),
            "profile_mapping_decisions_path": mapping_path,
            "reviewer_id": self.reviewer.id,
        }

        with self.assertRaisesRegex(P0ReviewedArtifactError, "SHA"):
            prepare_reviewed_p0_completion_artifact(
                **{**kwargs, "authority_manifest_sha256": "0" * 64}
            )

        duplicate_identity = copy.deepcopy(json.loads(research_path.read_text()))
        duplicate_identity["horses"].append(copy.deepcopy(duplicate_identity["horses"][0]))
        self._write_json("research-v3.json", duplicate_identity)
        with self.assertRaisesRegex(P0ReviewedArtifactError, "identity"):
            prepare_reviewed_p0_completion_artifact(**kwargs)

        self._research([horse])
        duplicate_race = copy.deepcopy(horse)
        duplicate_race["career"]["records"][1] = copy.deepcopy(
            duplicate_race["career"]["records"][0]
        )
        self._research([duplicate_race])
        with self.assertRaisesRegex(P0ReviewedArtifactError, "duplicate race"):
            prepare_reviewed_p0_completion_artifact(**kwargs)

        invalid_url = copy.deepcopy(horse)
        invalid_url["source"]["url"] = "javascript:bad"
        self._research([invalid_url])
        self._mapping(
            [invalid_url],
            [{"decision": "bind_existing", "profile": profile}],
        )
        with self.assertRaisesRegex(P0ReviewedArtifactError, "URL"):
            prepare_reviewed_p0_completion_artifact(**kwargs)

        self._research([horse])
        self._mapping(
            [horse],
            [{"decision": "bind_existing", "profile": profile}],
        )
        mapping = json.loads(mapping_path.read_text())
        mapping["rows"][0]["module_reviews"]["pedigree"]["status"] = "pending"
        self._write_json("mapping.json", mapping)
        with self.assertRaisesRegex(P0ReviewedArtifactError, "approved"):
            prepare_reviewed_p0_completion_artifact(**kwargs)

        self._mapping([horse], [{"decision": "bind_existing", "profile": profile}])
        profile.owner_name = "drift"
        profile.save(update_fields=["owner_name"])
        with self.assertRaisesRegex(P0ReviewedArtifactError, "snapshot"):
            prepare_reviewed_p0_completion_artifact(**kwargs)

    def test_prepare_rejects_create_when_strong_identity_exists_and_bind_manual_lock_conflicts(self):
        horse = self._horse(0)
        profile = self._create_profile(horse["identity"])
        profile.sire_text = horse["identity"]["sire_name"]
        profile.dam_text = horse["identity"]["dam_name"]
        profile.birth_date = date(horse["identity"]["birth_year"], 1, 1)
        profile.save(update_fields=["sire_text", "dam_text", "birth_date"])
        with self.assertRaisesRegex(P0ReviewedArtifactError, "create_new"):
            self._prepare([horse], [{"decision": "create_new"}])

        profile.manual_lock_flags = {"owner_name": True}
        profile.owner_name = "Protected owner"
        profile.save(update_fields=["manual_lock_flags", "owner_name"])
        with self.assertRaisesRegex(P0ReviewedArtifactError, "manual lock"):
            self._prepare(
                [horse],
                [{"decision": "bind_existing", "profile": profile}],
            )

    def test_dry_run_performs_validation_and_writes_nothing(self):
        horse = self._horse(0)
        artifact_path, _ = self._prepare([horse], [{"decision": "create_new"}])
        before = {
            "profiles": HorseProfile.objects.count(),
            "terms": TermEntry.objects.count(),
            "records": HorseRaceRecord.objects.count(),
            "sources": HorseP0Source.objects.count(),
            "candidates": HorseProfileDataCandidate.objects.count(),
            "logs": TaskExecutionLog.objects.count(),
        }
        report = self._dry_run(artifact_path)
        self.assertEqual(report["database_write_count"], 0)
        self.assertEqual(report["validated_horse_count"], 1)
        self.assertEqual(report["planned_profile_creates"], 1)
        self.assertEqual(report["planned_race_record_creates"], 2)
        self.assertEqual(
            before,
            {
                "profiles": HorseProfile.objects.count(),
                "terms": TermEntry.objects.count(),
                "records": HorseRaceRecord.objects.count(),
                "sources": HorseP0Source.objects.count(),
                "candidates": HorseProfileDataCandidate.objects.count(),
                "logs": TaskExecutionLog.objects.count(),
            },
        )

        unapproved = json.loads(artifact_path.read_text())
        unapproved["rows"][0]["module_reviews"]["profile"]["status"] = "pending"
        self._write_json("reviewed-artifact.json", unapproved)
        with self.assertRaisesRegex(P0ReviewedArtifactError, "formally approved"):
            self._dry_run(artifact_path)

        artifact_path, _ = self._prepare([horse], [{"decision": "create_new"}])
        horse["career"]["records"][1]["external_result_id"] = horse["career"]["records"][0][
            "external_result_id"
        ]
        artifact = json.loads(artifact_path.read_text())
        artifact["rows"][0]["race_records_payload"] = horse["career"]["records"]
        self._write_json("reviewed-artifact.json", artifact)
        with self.assertRaisesRegex(P0ReviewedArtifactError, "duplicate race"):
            self._dry_run(artifact_path)

    def test_dry_run_rejects_profile_and_input_snapshot_drift_after_prepare(self):
        horse = self._horse(0)
        profile = self._create_profile(horse["identity"])
        artifact_path, _ = self._prepare(
            [horse],
            [{"decision": "bind_existing", "profile": profile}],
        )
        profile.owner_name = "changed after prepare"
        profile.save(update_fields=["owner_name"])
        with self.assertRaisesRegex(P0ReviewedArtifactError, "snapshot drift"):
            self._dry_run(artifact_path)

        profile.owner_name = ""
        profile.save(update_fields=["owner_name"])
        mapping_path = self.root / "mapping.json"
        mapping_path.write_bytes(mapping_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(P0ReviewedArtifactError, "profile_mapping_decisions.*SHA"):
            self._dry_run(artifact_path)

    def test_commit_rolls_back_on_mid_batch_exception(self):
        horses = [self._horse(0), self._horse(1)]
        artifact_path, _ = self._prepare(
            horses,
            [{"decision": "create_new"}, {"decision": "create_new"}],
        )
        before = {
            "profiles": HorseProfile.objects.count(),
            "terms": TermEntry.objects.count(),
            "records": HorseRaceRecord.objects.count(),
            "sources": HorseP0Source.objects.count(),
            "logs": TaskExecutionLog.objects.count(),
        }
        with mock.patch(
            "stable.services.p0_horse_production_apply._apply_artifact_row",
            side_effect=[None, RuntimeError("injected failure")],
        ), self.assertRaisesRegex(RuntimeError, "injected failure"):
            self._commit(artifact_path)
        self.assertEqual(before["profiles"], HorseProfile.objects.count())
        self.assertEqual(before["terms"], TermEntry.objects.count())
        self.assertEqual(before["records"], HorseRaceRecord.objects.count())
        self.assertEqual(before["sources"], HorseP0Source.objects.count())
        self.assertEqual(before["logs"], TaskExecutionLog.objects.count())

    def test_frozen_fifty_batch_24_bind_25_create_and_explicit_ambiguous_decision(self):
        record_counts = [28 if index < 11 else 29 for index in range(50)]
        horses = [
            self._horse(
                index,
                name="Stradivarius" if index == 49 else None,
                record_count=record_counts[index],
                nonstarter=index < 7,
            )
            for index in range(50)
        ]
        resolutions = []
        for index in range(24):
            resolutions.append(
                {
                    "decision": "bind_existing",
                    "profile": self._create_profile(horses[index]["identity"]),
                }
            )
        resolutions.extend({"decision": "create_new"} for _ in range(25))
        selected = self._create_profile(horses[49]["identity"], profile_id=19439)
        rejected = self._create_profile(horses[49]["identity"], profile_id=21276)
        resolutions.append(
            {
                "decision": "bind_existing",
                "profile": selected,
                "reason": "explicitly selected production profile 19439",
                "rejected_profile_ids": [rejected.id],
                "rejection_reason": "profile 21276 rejected by reviewed mapping decision",
            }
        )

        artifact_path, artifact = self._prepare(horses, resolutions)
        self.assertEqual(artifact["summary"]["bind_existing_count"], 25)
        self.assertEqual(artifact["summary"]["create_new_count"], 25)
        self.assertEqual(artifact["summary"]["race_record_count"], 1439)
        self.assertEqual(artifact["summary"]["actual_start_count"], 1432)
        self.assertEqual(artifact["summary"]["nonstarter_count"], 7)

        first = self._commit(artifact_path)
        second = self._commit(artifact_path)
        self.assertEqual(first["strict_complete_count"], 50)
        self.assertEqual(second["race_records_created"], 0)
        self.assertEqual(HorseProfile.objects.count(), 51)
        self.assertEqual(HorseRaceRecord.objects.count(), 1439)
        self.assertEqual(
            sum(profile.collected_start_count for profile in HorseProfile.objects.exclude(pk=rejected.id)),
            1432,
        )
        self.assertEqual(HorseP0Source.objects.count(), 50)
        self.assertEqual(
            HorseProfileDataCandidate.objects.filter(status="applied").count(),
            200,
        )
        self.assertEqual(RaceEvent.objects.count(), 0)
        self.assertEqual(
            HorseProfile.objects.get(pk=resolutions[1]["profile"].pk).racing_region,
            "japan",
        )
        self.assertEqual(
            HorseProfile.objects.get(pk=selected.pk).source_refs[
                "p0_reviewed_identity"
            ],
            {
                **horses[49]["identity"],
                "deterministic_identity_key": artifact["rows"][49][
                    "deterministic_identity_key"
                ],
            },
        )
        self.assertEqual(
            TaskExecutionLog.objects.filter(
                task_name="apply_reviewed_p0_horse_completion",
                status="success",
            ).count(),
            2,
        )

    def test_create_new_ignores_same_name_non_horse_term(self):
        horse = self._horse(0)
        non_horse = TermEntry.objects.create(
            term_type=TermType.JOCKEY,
            source_language="en",
            source_ja=horse["identity"]["horse_name"],
            target_zh="",
            translation_status=TermTranslationStatus.PENDING,
            is_active=True,
        )
        artifact_path, _ = self._prepare([horse], [{"decision": "create_new"}])

        self._commit(artifact_path)

        profile = HorseProfile.objects.get()
        self.assertNotEqual(profile.primary_term_id, non_horse.id)
        self.assertEqual(profile.primary_term.term_type, TermType.HORSE)
        self.assertEqual(TermEntry.objects.filter(term_type=TermType.JOCKEY).count(), 1)

    def test_commit_claims_only_artifact_records_including_unchanged(self):
        horse = self._horse(0)
        profile = self._create_profile(horse["identity"])
        claimed = upsert_race_record(profile, horse["career"]["records"][0]).record
        unrelated_payload = self._record(0, -1, nonstarter=True)
        unrelated = upsert_race_record(profile, unrelated_payload).record
        artifact_path, _ = self._prepare(
            [horse],
            [{"decision": "bind_existing", "profile": profile}],
        )

        self._commit(artifact_path)

        claimed.refresh_from_db()
        unrelated.refresh_from_db()
        self.assertIsNotNone(claimed.completion_run_id)
        self.assertIsNone(unrelated.completion_run_id)

    def test_json_inputs_are_read_once_and_symlinks_are_rejected(self):
        horse = self._horse(0)
        artifact_path, artifact = self._prepare([horse], [{"decision": "create_new"}])
        release_path, release_sha = self._release(artifact_path, artifact)
        artifact_sha = sha256_file(artifact_path)
        original_reader = __import__(
            "stable.services.p0_horse_production_apply",
            fromlist=["_read_regular_file_once"],
        )._read_regular_file_once
        reads: dict[str, int] = {}

        def counted_reader(path, *, label):
            reads[str(path)] = reads.get(str(path), 0) + 1
            return original_reader(path, label=label)

        with mock.patch(
            "stable.services.p0_horse_production_apply."
            "TRUSTED_P0_HORSE_PRODUCTION_RELEASE_MANIFEST_SHA256",
            (release_sha,),
        ), mock.patch(
            "stable.services.p0_horse_production_apply._read_regular_file_once",
            side_effect=counted_reader,
        ):
            dry_run_reviewed_p0_completion_artifact(
                artifact_path=artifact_path,
                artifact_sha256=artifact_sha,
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
            )
        self.assertEqual(set(reads.values()), {1})

        symlink = self.root / "artifact-symlink.json"
        symlink.symlink_to(artifact_path)
        with self.assertRaisesRegex(P0ReviewedArtifactError, "symlink"):
            dry_run_reviewed_p0_completion_artifact(
                artifact_path=symlink,
                artifact_sha256=artifact_sha,
                release_manifest_path=release_path,
                release_manifest_sha256=release_sha,
            )

    def test_command_requires_exact_artifact_sha_and_confirmation(self):
        horse = self._horse(0)
        artifact_path, artifact = self._prepare([horse], [{"decision": "create_new"}])
        release_path, release_sha = self._release(artifact_path, artifact)
        with self.assertRaisesRegex(Exception, "SHA"):
            call_command(
                "apply_reviewed_p0_horse_completion",
                "--dry-run",
                "--artifact",
                str(artifact_path),
                "--artifact-sha256",
                "0" * 64,
                "--release-manifest",
                str(release_path),
                "--release-manifest-sha256",
                release_sha,
            )
        with self.assertRaisesRegex(Exception, "confirm-reviewed-artifact"):
            call_command(
                "apply_reviewed_p0_horse_completion",
                "--commit",
                "--artifact",
                str(artifact_path),
                "--artifact-sha256",
                sha256_file(artifact_path),
                "--release-manifest",
                str(release_path),
                "--release-manifest-sha256",
                release_sha,
            )

    def test_prepare_command_writes_new_atomic_directory_and_refuses_overwrite(self):
        horse = self._horse(0)
        research_path, _ = self._research([horse])
        authority_path = self.root / "authority.json"
        mapping_path = self._mapping([horse], [{"decision": "create_new"}])
        output = self.root / "formal-package"
        call_command(
            "apply_reviewed_p0_horse_completion",
            "--prepare",
            "--research-v3",
            str(research_path),
            "--authority-manifest",
            str(authority_path),
            "--authority-manifest-sha256",
            sha256_file(authority_path),
            "--profile-mapping-decisions",
            str(mapping_path),
            "--reviewer-id",
            str(self.reviewer.id),
            "--output",
            str(output),
        )
        artifact_path = output / "reviewed_p0_horse_completion_artifact.json"
        manifest_path = output / "manifest.json"
        self.assertTrue(artifact_path.is_file())
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["artifact"]["sha256"], sha256_file(artifact_path))
        self.assertEqual(manifest["database_write_count"], 0)
        with self.assertRaisesRegex(Exception, "must be new"):
            call_command(
                "apply_reviewed_p0_horse_completion",
                "--prepare",
                "--research-v3",
                str(research_path),
                "--authority-manifest",
                str(authority_path),
                "--authority-manifest-sha256",
                sha256_file(authority_path),
                "--profile-mapping-decisions",
                str(mapping_path),
                "--reviewer-id",
                str(self.reviewer.id),
                "--output",
                str(output),
            )

    def test_repository_frozen_v3_and_authority_validate_to_exact_batch_totals(self):
        repository_root = Path(__file__).resolve().parents[2]
        artifact_root = (
            repository_root
            / "runtime"
            / "horse_profile_completion"
            / "pedigree-research-20260719"
        )
        authority_path = artifact_root / "reviewed_us_career_source_authority_v1.json"
        summary = validate_frozen_p0_research_inputs(
            research_v3_path=artifact_root / "p0_horse_research_50_enriched_v3.json",
            authority_manifest_path=authority_path,
            authority_manifest_sha256=(
                "29091d69573bab907cda2e9a081ae4684838b92d1f9b052a7601b6109a541077"
            ),
        )
        self.assertEqual(
            summary,
            {
                "horse_count": 50,
                "race_record_count": 1439,
                "actual_start_count": 1432,
                "nonstarter_count": 7,
            },
        )

    def test_desensitized_production_snapshot_and_mapping_prepare_real_frozen_fifty(self):
        repository_root = Path(__file__).resolve().parents[2]
        fixture_root = (
            repository_root
            / "server"
            / "stable"
            / "fixtures"
            / "p0_horse_production"
        )
        snapshot_path = fixture_root / "desensitized_profile_snapshot_58f00961.json"
        mapping_fixture_path = (
            fixture_root / "desensitized_mapping_decisions_58f00961.json"
        )
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        mapping_fixture = json.loads(
            mapping_fixture_path.read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot["production_head"], "58f00961")
        self.assertEqual(mapping_fixture["production_head"], "58f00961")
        self.assertEqual(
            mapping_fixture["production_snapshot_sha256"],
            sha256_file(snapshot_path),
        )
        self.assertEqual(len(snapshot["rows"]), 50)
        self.assertEqual(len(mapping_fixture["rows"]), 50)
        self.assertEqual(
            sum(row["decision"] == "bind_existing" for row in mapping_fixture["rows"]),
            25,
        )
        self.assertEqual(
            sum(row["decision"] == "create_new" for row in mapping_fixture["rows"]),
            25,
        )
        strad = next(
            row
            for row in mapping_fixture["rows"]
            if row["identity"]["horse_name"] == "Stradivarius"
        )
        self.assertEqual(strad["profile_id"], 19439)
        self.assertEqual(strad["rejected_profile_ids"], [21276])
        self.assertIn("official HKJC overseas term", strad["rejection_reason"])
        self.assertIn("community term", strad["rejection_reason"])

        artifact_root = (
            repository_root
            / "runtime"
            / "horse_profile_completion"
            / "pedigree-research-20260719"
        )
        research_path = artifact_root / "p0_horse_research_50_enriched_v3.json"
        authority_path = artifact_root / "reviewed_us_career_source_authority_v1.json"
        research = json.loads(research_path.read_text(encoding="utf-8"))
        research_rows = {
            row["identity"]["horse_name"]: row for row in research["horses"]
        }
        self.assertEqual(set(research_rows), {
            row["identity"]["horse_name"] for row in mapping_fixture["rows"]
        })
        resolutions = []
        ordered_horses = []
        for fixture_row in mapping_fixture["rows"]:
            horse = copy.deepcopy(research_rows[fixture_row["identity"]["horse_name"]])
            horse["identity"] = fixture_row["identity"]
            horse["career"]["records_synced_through"] = max(
                record["race_date"] for record in horse["career"]["records"]
            )
            ordered_horses.append(horse)
            if fixture_row["decision"] == "create_new":
                resolutions.append({"decision": "create_new"})
                continue
            profile = self._create_profile(
                fixture_row["identity"],
                profile_id=fixture_row["profile_id"],
            )
            resolution = {
                "decision": "bind_existing",
                "profile": profile,
            }
            if fixture_row["identity"]["horse_name"] == "Stradivarius":
                rejected = self._create_profile(
                    fixture_row["identity"],
                    profile_id=fixture_row["rejected_profile_ids"][0],
                )
                resolution.update(
                    {
                        "rejected_profile_ids": [rejected.id],
                        "rejection_reason": fixture_row["rejection_reason"],
                    }
                )
            resolutions.append(resolution)
        self.research_sha256 = sha256_file(research_path)
        mapping_path = self._mapping(ordered_horses, resolutions)
        artifact = prepare_reviewed_p0_completion_artifact(
            research_v3_path=research_path,
            authority_manifest_path=authority_path,
            authority_manifest_sha256=sha256_file(authority_path),
            profile_mapping_decisions_path=mapping_path,
            reviewer_id=self.reviewer.id,
        )
        self.assertEqual(artifact["inputs"]["research_v3"]["sha256"], snapshot["research_v3_sha256"])
        self.assertEqual(artifact["summary"]["bind_existing_count"], 25)
        self.assertEqual(artifact["summary"]["create_new_count"], 25)
        self.assertEqual(artifact["summary"]["race_record_count"], 1439)
        self.assertEqual(artifact["summary"]["actual_start_count"], 1432)
        self.assertEqual(artifact["summary"]["nonstarter_count"], 7)
        self.assertEqual(artifact["release_status"], "candidate_pending_independent_release")
