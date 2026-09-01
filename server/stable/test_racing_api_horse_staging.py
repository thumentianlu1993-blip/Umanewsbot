from __future__ import annotations

import datetime
import hashlib
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from stable.models import (
    ExternalDataImportRun,
    ExternalDataSource,
    ExternalHorse,
    ExternalHorseHistory,
    ExternalRace,
    ExternalRaceResult,
    HorseExternalIdentity,
    HorseNameVariant,
    HorseProfile,
    HorseRaceRecord,
    RaceEvent,
    RaceEventResult as CanonicalRaceEventResult,
)
from stable.services import racing_api_horse_staging as staging_service
from stable.services.racing_api_horse_staging import (
    RacingApiStagingError,
    apply_targeted_artifact,
    apply_targeted_materialization,
    apply_targeted_materialization_collection,
    dry_run_targeted_artifact,
    dry_run_targeted_materialization,
    dry_run_targeted_materialization_collection,
    load_targeted_artifact,
    load_targeted_materialization,
    verify_targeted_materialization,
    verify_targeted_materialization_collection,
)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


class RacingApiHorseStagingTests(TestCase):
    def _reseal_run(self, root: Path, manifest: dict | None = None) -> str:
        manifest_path = root / "run-manifest.json"
        if manifest is None:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        normalized_path = root / manifest["normalized"]["path"]
        manifest["normalized"].update(
            {
                "sha256": hashlib.sha256(normalized_path.read_bytes()).hexdigest(),
                "size": normalized_path.stat().st_size,
            }
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (root / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
        return manifest_sha

    def _artifact(self, root: Path, *, with_parents: bool = False) -> tuple[Path, str]:
        race = {
            "race_id": "rac_arc_1999",
            "date": "1999-10-03",
            "region": "FR",
            "course": "Longchamp (FR)",
            "course_id": "crs_longchamp",
            "race_name": "Prix de l'Arc de Triomphe",
            "type": "Flat",
            "class": "Group 1",
            "pattern": "G1",
            "dist": "1m4f",
            "surface": "Turf",
            "going": "Very Soft",
            "runners": [
                {
                    "horse_id": "hrs_1024",
                    "horse": "Montjeu (IRE)",
                    "position": "1",
                    "number": "7",
                    "jockey": "M Kinane",
                    "trainer": "J Hammond",
                },
                {
                    "horse_id": "hrs_2048",
                    "horse": "El Condor Pasa (USA)",
                    "position": "2",
                    "number": "4",
                },
                {
                    "horse_id": "hrs_4096",
                    "horse": "Withdrawn Horse (IRE)",
                    "position": "NR",
                    "number": "9",
                },
            ],
        }
        normalized = {
            "schema_version": "targeted-horse-export.v1",
            "database_writes": 0,
            "seed_id": "proof-1999-arc-winner-montjeu",
            "horse_id": "hrs_1024",
            "identity_mode": "provider_stable_id_from_target_race",
            "profile": {
                "provider": "the_racing_api",
                "profile_kind": "pro",
                "horse_id": "hrs_1024",
                "raw_name": "Montjeu (IRE)",
                "name": "Montjeu",
                "country_suffix": "IRE",
                "dob": "1996-04-04",
                "sex": "horse",
                "sex_code": "H",
                "colour": "bay",
                "colour_code": "B",
                "breeder": "Sir James Goldsmith",
                "sire": "Sadler's Wells (USA)",
                "sire_id": "sir_100",
                "dam": "Floripedes (FR)",
                "dam_id": "dam_200",
                "damsire": "Top Ville (IRE)",
                "damsire_id": "dsi_300",
                "parent_profile_ids": ["hrs_100", "hrs_200", "hrs_300"],
                "payload_sha256": "a" * 64,
            },
            "career": {
                "provider_row_count": 1,
                "unique_race_count": 1,
                "page_count": 1,
                "races": [race],
            },
            "target_race": {
                **race,
                "actual_starters": race["runners"][:2],
                "excluded_non_runner_count": 1,
                "source_mode": "targeted_horse",
            },
        }
        if with_parents:
            normalized["parent_profiles"] = [
                {
                    "provider": "the_racing_api",
                    "profile_kind": "pro",
                    "horse_id": "hrs_100",
                    "raw_name": "Sadler's Wells (USA)",
                    "name": "Sadler's Wells",
                    "country_suffix": "USA",
                    "dob": "",
                    "sex": "",
                    "sex_code": "",
                    "colour": "",
                    "colour_code": "",
                    "breeder": "",
                    "sire": "Northern Dancer (CAN)",
                    "sire_id": "sir_101",
                    "dam": "Fairy Bridge (USA)",
                    "dam_id": "dam_102",
                    "damsire": "Bold Reason (USA)",
                    "damsire_id": "dsi_103",
                    "parent_profile_ids": ["hrs_101", "hrs_102", "hrs_103"],
                    "payload_sha256": "b" * 64,
                },
                {
                    "provider": "the_racing_api",
                    "profile_kind": "pro",
                    "horse_id": "hrs_200",
                    "raw_name": "Floripedes (FR)",
                    "name": "Floripedes",
                    "country_suffix": "FR",
                    "dob": "",
                    "sex": "",
                    "sex_code": "",
                    "colour": "",
                    "colour_code": "",
                    "breeder": "",
                    "sire": "Top Ville (IRE)",
                    "sire_id": "sir_300",
                    "dam": "Toute Cy (FR)",
                    "dam_id": "dam_301",
                    "damsire": "Tennyson (FR)",
                    "damsire_id": "dsi_302",
                    "parent_profile_ids": ["hrs_300", "hrs_301", "hrs_302"],
                    "payload_sha256": "c" * 64,
                },
            ]
        profile_payloads = []
        for normalized_profile in [
            normalized["profile"],
            *normalized.get("parent_profiles", []),
        ]:
            payload = {
                "id": normalized_profile["horse_id"],
                "name": normalized_profile["raw_name"],
                "dob": normalized_profile["dob"],
                "sex": normalized_profile["sex"],
                "sex_code": normalized_profile["sex_code"],
                "colour": normalized_profile["colour"],
                "colour_code": normalized_profile["colour_code"],
                "breeder": normalized_profile["breeder"],
                "sire": normalized_profile["sire"],
                "sire_id": normalized_profile["sire_id"],
                "dam": normalized_profile["dam"],
                "dam_id": normalized_profile["dam_id"],
                "damsire": normalized_profile["damsire"],
                "damsire_id": normalized_profile["damsire_id"],
            }
            normalized_profile["payload_sha256"] = hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            profile_payloads.append(payload)
        normalized_path = root / "normalized" / "targeted-horse-export.json"
        normalized_path.parent.mkdir(parents=True)
        normalized_path.write_bytes(_canonical(normalized))
        normalized_sha = hashlib.sha256(normalized_path.read_bytes()).hexdigest()
        response_identities = []
        wrappers = [
            (
                f"https://api.theracingapi.com/v1/horses/{payload['id']}/pro",
                payload,
                True,
            )
            for payload in profile_payloads
        ]
        wrappers.append(
            (
                "https://api.theracingapi.com/v1/horses/hrs_1024/"
                "results?limit=100&skip=0",
                {
                    "limit": 100,
                    "skip": 0,
                    "total": 1,
                    "query": [
                        ["limit", "100"],
                        ["skip", "0"],
                        ["horse_id", "hrs_1024"],
                    ],
                    "results": [race],
                },
                False,
            )
        )
        for ordinal, (url, payload, allow_not_found) in enumerate(wrappers, 1):
            wrapper = {
                "allow_not_found": allow_not_found,
                "captured_at": "2026-08-31T11:27:27+00:00",
                "not_found": False,
                "payload": payload,
                "url": url,
            }
            response_path = root / "cache" / f"response-{ordinal:04d}.json"
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_bytes(_canonical(wrapper))
            response_identities.append(
                {
                    "path": str(response_path.relative_to(root)),
                    "sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
                    "size": response_path.stat().st_size,
                    "url": url,
                }
            )
        manifest = {
            "schema_version": "targeted-horse-run.v1",
            "status": "complete",
            "database_writes": 0,
            "source_batch_manifest_sha256": "f" * 64,
            "source_content_pool_manifest_sha256": "e" * 64,
            "materialization_mode": "expanded_compact",
            "responses": response_identities,
            "normalized": {
                "path": "normalized/targeted-horse-export.json",
                "sha256": normalized_sha,
                "size": normalized_path.stat().st_size,
            },
        }
        manifest_path = root / "run-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (root / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
        return root, manifest_sha

    def _materialization(self, root: Path) -> tuple[Path, str]:
        materialization = root / "materialization"
        materialization.mkdir()
        source_batch_sha = "f" * 64
        specifications = (
            ("seed-a", "hrs_1024", "Montjeu (IRE)", "Montjeu", "IRE"),
            (
                "seed-b",
                "hrs_2048",
                "El Condor Pasa (USA)",
                "El Condor Pasa",
                "USA",
            ),
        )
        rows = []
        for ordinal, (seed_id, horse_id, raw_name, name, suffix) in enumerate(
            specifications, 1
        ):
            run = materialization / f"run-{ordinal:05d}"
            self._artifact(run)
            normalized_path = run / "normalized/targeted-horse-export.json"
            normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
            normalized["seed_id"] = seed_id
            normalized["horse_id"] = horse_id
            normalized["profile"].update(
                {
                    "horse_id": horse_id,
                    "raw_name": raw_name,
                    "name": name,
                    "country_suffix": suffix,
                }
            )
            profile_response_path = run / "cache/response-0001.json"
            profile_wrapper = json.loads(
                profile_response_path.read_text(encoding="utf-8")
            )
            profile_wrapper["url"] = (
                f"https://api.theracingapi.com/v1/horses/{horse_id}/pro"
            )
            profile_wrapper["payload"].update(
                {
                    "id": horse_id,
                    "name": raw_name,
                }
            )
            normalized["profile"]["payload_sha256"] = hashlib.sha256(
                json.dumps(
                    profile_wrapper["payload"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            profile_response_path.write_bytes(_canonical(profile_wrapper))
            results_response_path = run / "cache/response-0002.json"
            results_wrapper = json.loads(
                results_response_path.read_text(encoding="utf-8")
            )
            results_wrapper["url"] = (
                f"https://api.theracingapi.com/v1/horses/{horse_id}/"
                "results?limit=100&skip=0"
            )
            results_wrapper["payload"]["query"][2][1] = horse_id
            results_response_path.write_bytes(_canonical(results_wrapper))
            normalized_path.write_bytes(_canonical(normalized))
            manifest_path = run / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_batch_manifest_sha256"] = source_batch_sha
            for identity, response_path, response_url in (
                (
                    manifest["responses"][0],
                    profile_response_path,
                    profile_wrapper["url"],
                ),
                (
                    manifest["responses"][1],
                    results_response_path,
                    results_wrapper["url"],
                ),
            ):
                identity.update(
                    {
                        "sha256": hashlib.sha256(
                            response_path.read_bytes()
                        ).hexdigest(),
                        "size": response_path.stat().st_size,
                        "url": response_url,
                    }
                )
            manifest["normalized"].update(
                {
                    "sha256": hashlib.sha256(
                        normalized_path.read_bytes()
                    ).hexdigest(),
                    "size": normalized_path.stat().st_size,
                }
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            (run / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")
            rows.append(
                {
                    "ordinal": ordinal,
                    "seed_id": seed_id,
                    "horse_id": horse_id,
                    "path": run.name,
                    "manifest_sha256": manifest_sha,
                    "materialization_mode": "expanded_compact",
                }
            )
        manifest = {
            "schema_version": "targeted-horse-batch-materialization.v1",
            "status": "complete",
            "database_writes": 0,
            "source_batch_manifest_sha256": source_batch_sha,
            "source_content_pool_manifest_sha256": "e" * 64,
            "recompute_normalized": False,
            "selected_seed_count": len(rows),
            "materialized": rows,
        }
        manifest_path = materialization / "materialization-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (materialization / "COMPLETE").write_text(
            manifest_sha + "\n", encoding="ascii"
        )
        return materialization, manifest_sha

    def test_loader_binds_complete_manifest_and_rejects_extra_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._artifact(Path(temporary))
            loaded = load_targeted_artifact(root, approved_manifest_sha256=manifest_sha)
            self.assertEqual(loaded["normalized"]["horse_id"], "hrs_1024")
            self.assertEqual(len(loaded["responses"]), 2)

            (root / "unexpected.txt").write_text("drift", encoding="utf-8")
            with self.assertRaisesRegex(RacingApiStagingError, "undeclared file"):
                load_targeted_artifact(root, approved_manifest_sha256=manifest_sha)

    def test_staging_loaders_reject_ambiguous_content_addressed_json(self):
        with self.subTest(kind="run-manifest"), tempfile.TemporaryDirectory() as temporary:
            root, _manifest_sha = self._artifact(Path(temporary))
            manifest_path = root / "run-manifest.json"
            manifest_bytes = manifest_path.read_bytes().replace(
                b'"status": "complete"',
                b'"status": "complete",\n  "status": "complete"',
                1,
            )
            manifest_path.write_bytes(manifest_bytes)
            manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
            (root / "COMPLETE").write_text(
                manifest_sha + "\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(
                RacingApiStagingError,
                "duplicate JSON key",
            ):
                load_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                )

        with self.subTest(kind="normalized"), tempfile.TemporaryDirectory() as temporary:
            root, _manifest_sha = self._artifact(Path(temporary))
            normalized_path = root / "normalized/targeted-horse-export.json"
            normalized_bytes = normalized_path.read_bytes().replace(
                b'"database_writes":0',
                b'"database_writes":NaN',
                1,
            )
            normalized_path.write_bytes(normalized_bytes)
            manifest_path = root / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["normalized"]["sha256"] = hashlib.sha256(
                normalized_bytes
            ).hexdigest()
            manifest["normalized"]["size"] = len(normalized_bytes)
            manifest_bytes = (
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            manifest_path.write_bytes(manifest_bytes)
            manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
            (root / "COMPLETE").write_text(
                manifest_sha + "\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(
                RacingApiStagingError,
                "non-finite JSON constant: NaN",
            ):
                load_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                )

        with self.subTest(kind="materialization"), tempfile.TemporaryDirectory() as temporary:
            root, _manifest_sha = self._materialization(Path(temporary))
            manifest_path = root / "materialization-manifest.json"
            manifest_bytes = manifest_path.read_bytes().replace(
                b'"status": "complete"',
                b'"status": "complete",\n  "status": "complete"',
                1,
            )
            manifest_path.write_bytes(manifest_bytes)
            manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
            (root / "COMPLETE").write_text(
                manifest_sha + "\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(
                RacingApiStagingError,
                "duplicate JSON key",
            ):
                load_targeted_materialization(
                    root,
                    approved_manifest_sha256=manifest_sha,
                )

    def test_loader_reads_each_content_addressed_file_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._artifact(Path(temporary))
            original = staging_service._read_file_bytes_once
            with mock.patch.object(
                staging_service,
                "_read_file_bytes_once",
                wraps=original,
            ) as reader:
                load_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                )

            opened = [Path(call.args[0]).resolve() for call in reader.call_args_list]
            for artifact_file in (
                root / "run-manifest.json",
                root / "COMPLETE",
                root / "normalized/targeted-horse-export.json",
                root / "cache/response-0001.json",
                root / "cache/response-0002.json",
            ):
                self.assertEqual(opened.count(artifact_file.resolve()), 1)

    def test_loader_rejects_response_count_and_aggregate_size_limits(self):
        with self.subTest(limit="response-count"), tempfile.TemporaryDirectory() as temporary:
            root, _manifest_sha = self._artifact(Path(temporary))
            manifest_path = root / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["responses"] = [manifest["responses"][0]] * 257
            manifest_sha = self._reseal_run(root, manifest)

            with self.assertRaisesRegex(RacingApiStagingError, "count exceeds"):
                load_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                )

        with self.subTest(limit="aggregate-bytes"), tempfile.TemporaryDirectory() as temporary:
            root, _manifest_sha = self._artifact(Path(temporary))
            manifest_path = root / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            oversized_identity = dict(manifest["responses"][0])
            oversized_identity["size"] = staging_service.MAX_ARTIFACT_JSON_BYTES
            manifest["responses"] = [oversized_identity] * 4
            manifest_sha = self._reseal_run(root, manifest)

            with self.assertRaisesRegex(RacingApiStagingError, "JSON size exceeds"):
                load_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                )

    def test_materialization_rejects_more_than_five_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, _manifest_sha = self._materialization(Path(temporary))
            manifest_path = root / "materialization-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["materialized"] = [manifest["materialized"][0]] * 6
            manifest["selected_seed_count"] = 6
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            (root / "COMPLETE").write_text(
                manifest_sha + "\n",
                encoding="ascii",
            )

            with self.assertRaisesRegex(RacingApiStagingError, "run count exceeds"):
                load_targeted_materialization(
                    root,
                    approved_manifest_sha256=manifest_sha,
                )

    def test_provider_evidence_mismatches_fail_closed_before_any_write(self):
        mutations = (
            "empty-responses",
            "forged-normalized-profile",
            "unapproved-url",
            "provider-id-drift",
            "payload-hash-drift",
            "career-drift",
            "identity-mode-drift",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root, _manifest_sha = self._artifact(Path(temporary))
                manifest_path = root / "run-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                normalized_path = root / "normalized/targeted-horse-export.json"
                normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
                if mutation == "empty-responses":
                    manifest["responses"] = []
                    for response_path in (root / "cache").glob("*.json"):
                        response_path.unlink()
                elif mutation == "forged-normalized-profile":
                    normalized["profile"]["breeder"] = "Forged Breeder"
                    normalized_path.write_bytes(_canonical(normalized))
                elif mutation in {"unapproved-url", "provider-id-drift"}:
                    response_path = root / manifest["responses"][0]["path"]
                    wrapper = json.loads(response_path.read_text(encoding="utf-8"))
                    if mutation == "unapproved-url":
                        wrapper["url"] = (
                            "https://example.invalid/v1/horses/hrs_1024/pro"
                        )
                    else:
                        wrapper["url"] = (
                            "https://api.theracingapi.com/v1/horses/hrs_999/pro"
                        )
                        wrapper["payload"]["id"] = "hrs_999"
                    response_path.write_bytes(_canonical(wrapper))
                    manifest["responses"][0].update(
                        {
                            "url": wrapper["url"],
                            "sha256": hashlib.sha256(
                                response_path.read_bytes()
                            ).hexdigest(),
                            "size": response_path.stat().st_size,
                        }
                    )
                elif mutation == "payload-hash-drift":
                    normalized["profile"]["payload_sha256"] = "d" * 64
                    normalized_path.write_bytes(_canonical(normalized))
                elif mutation == "career-drift":
                    normalized["career"]["races"][0]["race_name"] = "Forged Race"
                    normalized_path.write_bytes(_canonical(normalized))
                elif mutation == "identity-mode-drift":
                    normalized["identity_mode"] = "target_occurrence"
                    normalized_path.write_bytes(_canonical(normalized))
                manifest_sha = self._reseal_run(root, manifest)

                with self.assertRaises(RacingApiStagingError):
                    dry_run_targeted_artifact(
                        root,
                        approved_manifest_sha256=manifest_sha,
                    )

                self.assertEqual(ExternalDataImportRun.objects.count(), 0)
                self.assertEqual(ExternalHorse.objects.count(), 0)
                self.assertEqual(ExternalRace.objects.count(), 0)
                self.assertEqual(ExternalRaceResult.objects.count(), 0)
                self.assertEqual(ExternalHorseHistory.objects.count(), 0)
                self.assertEqual(HorseNameVariant.objects.count(), 0)
                self.assertEqual(HorseProfile.objects.count(), 0)
                self.assertEqual(RaceEvent.objects.count(), 0)
                self.assertEqual(CanonicalRaceEventResult.objects.count(), 0)
                self.assertEqual(HorseRaceRecord.objects.count(), 0)

    def test_materialization_batch_dry_run_and_apply_are_complete_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._materialization(Path(temporary))
            loaded = load_targeted_materialization(
                root, approved_manifest_sha256=manifest_sha
            )
            dry_run = dry_run_targeted_materialization(
                root, approved_manifest_sha256=manifest_sha
            )
            self.assertEqual(len(loaded["runs"]), 2)
            self.assertEqual(dry_run["status"], "batch_dry_run")
            self.assertEqual(dry_run["database_writes"], 0)
            self.assertEqual(dry_run["run_count"], 2)
            self.assertEqual(dry_run["unique_target_horse_count"], 2)
            self.assertEqual(ExternalHorse.objects.count(), 0)

            with self.assertRaisesRegex(RacingApiStagingError, "write gate"):
                apply_targeted_materialization(
                    root, approved_manifest_sha256=manifest_sha
                )
            with mock.patch.dict(
                "os.environ", {"RACING_API_STAGING_WRITE_ENABLED": "true"}
            ):
                first = apply_targeted_materialization(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )
                second = apply_targeted_materialization(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )

            self.assertEqual(first["status"], "applied")
            self.assertEqual(second["status"], "replayed")
            self.assertEqual(first["run_count"], 2)
            self.assertEqual(
                [row["status"] for row in second["results"]],
                ["replayed", "replayed"],
            )
            self.assertEqual(ExternalDataImportRun.objects.count(), 2)
            self.assertEqual(ExternalHorseHistory.objects.count(), 2)

            verified = verify_targeted_materialization(
                root,
                approved_manifest_sha256=manifest_sha,
            )
            self.assertEqual(verified["status"], "verified")
            self.assertEqual(verified["database_writes"], 0)
            self.assertEqual(verified["run_count"], 2)
            self.assertEqual(verified["canonical_identity_count"], 0)
            self.assertEqual(verified["verified_rows"]["external_horses"], 2)
            self.assertEqual(verified["verified_rows"]["external_races"], 1)

            horse = ExternalHorse.objects.get(
                source=ExternalDataSource.THE_RACING_API,
                horse_id="hrs_1024",
            )
            self.assertEqual(horse.trainer_name, "J Hammond")
            self.assertEqual(
                horse.record_summary,
                "starts=1;wins=1;seconds=0;thirds=0",
            )
            self.assertEqual(
                horse.profile_snapshot["career"],
                {
                    "provider_row_count": 1,
                    "unique_race_count": 1,
                    "page_count": 1,
                    "started_count": 1,
                    "win_count": 1,
                    "second_count": 0,
                    "third_count": 0,
                    "provider_pagination_complete": True,
                    "authority_status": "provider_available",
                    "authority_basis": "",
                },
            )
            horse.breeder_name = "Drifted Breeder"
            horse.save(update_fields=["breeder_name", "updated_at"])
            with self.assertRaisesRegex(RacingApiStagingError, "ExternalHorse field drift"):
                verify_targeted_materialization(
                    root,
                    approved_manifest_sha256=manifest_sha,
                )

    def test_materialization_batch_apply_rolls_back_all_runs_on_late_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._materialization(Path(temporary))
            original_apply = apply_targeted_artifact
            call_count = 0

            def fail_second(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise RacingApiStagingError("synthetic late batch failure")
                return original_apply(*args, **kwargs)

            with mock.patch.dict(
                "os.environ", {"RACING_API_STAGING_WRITE_ENABLED": "true"}
            ), mock.patch(
                "stable.services.racing_api_horse_staging.apply_targeted_artifact",
                side_effect=fail_second,
            ), self.assertRaisesRegex(
                RacingApiStagingError, "synthetic late batch failure"
            ):
                apply_targeted_materialization(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )

            self.assertEqual(ExternalHorse.objects.count(), 0)
            self.assertEqual(ExternalRace.objects.count(), 0)
            self.assertEqual(ExternalRaceResult.objects.count(), 0)
            self.assertEqual(ExternalHorseHistory.objects.count(), 0)

    def test_collection_preflights_then_applies_and_verifies_exact_parts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._materialization(Path(temporary))
            bindings = [(root, manifest_sha)]
            dry_run = dry_run_targeted_materialization_collection(bindings)
            self.assertEqual(dry_run["status"], "collection_dry_run")
            self.assertEqual(dry_run["database_writes"], 0)
            self.assertEqual(dry_run["materialization_count"], 1)
            self.assertEqual(dry_run["horse_count"], 2)

            with self.assertRaisesRegex(RacingApiStagingError, "write gate"):
                apply_targeted_materialization_collection(bindings)
            with mock.patch.dict(
                "os.environ", {"RACING_API_STAGING_WRITE_ENABLED": "true"}
            ):
                applied = apply_targeted_materialization_collection(
                    bindings,
                    allow_write=True,
                )
            verified = verify_targeted_materialization_collection(bindings)

            self.assertEqual(applied["status"], "applied")
            self.assertGreater(applied["database_writes"], 0)
            self.assertEqual(verified["status"], "verified")
            self.assertEqual(verified["database_writes"], 0)
            self.assertEqual(
                applied["collection_binding_sha256"],
                verified["collection_binding_sha256"],
            )

    def test_collection_rejects_duplicate_part_before_any_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._materialization(Path(temporary))
            with self.assertRaisesRegex(
                RacingApiStagingError,
                "path is invalid",
            ):
                dry_run_targeted_materialization_collection(
                    [(root, manifest_sha), (root, manifest_sha)]
                )
        self.assertEqual(ExternalDataImportRun.objects.count(), 0)

    def test_materialization_member_drift_is_rejected_before_batch_dry_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._materialization(Path(temporary))
            (root / "unexpected.txt").write_text("drift", encoding="utf-8")
            with self.assertRaisesRegex(
                RacingApiStagingError, "top-level member drift"
            ):
                dry_run_targeted_materialization(
                    root, approved_manifest_sha256=manifest_sha
                )

    def test_dry_run_is_zero_write_and_apply_is_explicit_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._artifact(Path(temporary))

            report = dry_run_targeted_artifact(root, approved_manifest_sha256=manifest_sha)
            self.assertEqual(report["database_writes"], 0)
            self.assertEqual(report["planned"]["external_horses"], 1)
            self.assertEqual(report["planned"]["external_races"], 1)
            self.assertEqual(report["planned"]["external_results"], 1)
            self.assertEqual(report["scope_stable_ids"], ["hrs_1024"])
            self.assertEqual(report["planned"]["out_of_scope_horse_writes"], 0)
            self.assertEqual(ExternalHorse.objects.count(), 0)

            with self.assertRaisesRegex(RacingApiStagingError, "write gate"):
                apply_targeted_artifact(root, approved_manifest_sha256=manifest_sha)

            with mock.patch.dict("os.environ", {"RACING_API_STAGING_WRITE_ENABLED": "true"}):
                first = apply_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )
                second = apply_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )

            self.assertEqual(first["status"], "applied")
            self.assertEqual(second["status"], "replayed")
            self.assertEqual(ExternalHorse.objects.count(), 1)
            self.assertEqual(ExternalRace.objects.count(), 1)
            self.assertEqual(ExternalRaceResult.objects.count(), 1)
            self.assertEqual(ExternalHorseHistory.objects.count(), 1)
            self.assertEqual(HorseNameVariant.objects.count(), 1)

    def test_staging_does_not_auto_bind_canonical_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._artifact(Path(temporary))
            with mock.patch.dict("os.environ", {"RACING_API_STAGING_WRITE_ENABLED": "true"}):
                apply_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )

            horse = ExternalHorse.objects.get(
                source=ExternalDataSource.THE_RACING_API,
                horse_id="hrs_1024",
            )
            self.assertEqual(horse.breeder_name, "Sir James Goldsmith")
            self.assertEqual(horse.sire_external_id, "hrs_100")
            self.assertEqual(HorseExternalIdentity.objects.count(), 0)
            self.assertTrue(horse.name_variants.filter(name_text="Montjeu (IRE)").exists())
            self.assertEqual(HorseProfile.objects.count(), 0)
            self.assertEqual(RaceEvent.objects.count(), 0)
            self.assertEqual(CanonicalRaceEventResult.objects.count(), 0)
            self.assertEqual(HorseRaceRecord.objects.count(), 0)

    def test_existing_v1_receipt_is_upgraded_once_with_page_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._artifact(Path(temporary), with_parents=True)
            with mock.patch.dict(
                "os.environ", {"RACING_API_STAGING_WRITE_ENABLED": "true"}
            ):
                first = apply_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )
                horse = ExternalHorse.objects.get(
                    source=ExternalDataSource.THE_RACING_API,
                    horse_id="hrs_1024",
                )
                horse.profile_snapshot = {}
                horse.owner_name = ""
                horse.trainer_name = ""
                horse.record_summary = ""
                horse.save(
                    update_fields=[
                        "profile_snapshot",
                        "owner_name",
                        "trainer_name",
                        "record_summary",
                        "updated_at",
                    ]
                )
                upgraded = apply_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )
                replayed = apply_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )

        horse.refresh_from_db()
        self.assertEqual(first["status"], "applied")
        self.assertEqual(upgraded["status"], "applied")
        self.assertEqual(replayed["status"], "replayed")
        self.assertEqual(horse.trainer_name, "J Hammond")
        self.assertEqual(
            horse.profile_snapshot["pedigree_two_generation"]["dam_dam"],
            "Toute Cy (FR)",
        )
        self.assertEqual(
            ExternalDataImportRun.objects.filter(
                target_type="targeted_horse_profile_snapshot_v1"
            ).count(),
            1,
        )

    def test_runner_only_observation_does_not_erase_existing_profile_fields(self):
        existing = ExternalHorse.objects.create(
            source=ExternalDataSource.THE_RACING_API,
            horse_id="hrs_2048",
            horse_name="El Condor Pasa (USA)",
            horse_name_en="El Condor Pasa",
            normalized_horse_name="el condor pasa",
            birth_date=datetime.date(1995, 3, 17),
            breeder_name="Takashi Watanabe",
            father_name="Kingmambo",
            mother_name="Saddlers Gal",
            sire_external_id="hrs_kingmambo",
            raw_payload={"profile_kind": "pro"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._artifact(Path(temporary))
            with mock.patch.dict("os.environ", {"RACING_API_STAGING_WRITE_ENABLED": "true"}):
                apply_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )

        existing.refresh_from_db()
        self.assertEqual(existing.birth_date, datetime.date(1995, 3, 17))
        self.assertEqual(existing.breeder_name, "Takashi Watanabe")
        self.assertEqual(existing.father_name, "Kingmambo")
        self.assertEqual(existing.sire_external_id, "hrs_kingmambo")
        self.assertEqual(existing.raw_payload, {"profile_kind": "pro"})

    def test_parent_profiles_remain_provenance_without_expanding_horse_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_sha = self._artifact(Path(temporary), with_parents=True)
            report = dry_run_targeted_artifact(root, approved_manifest_sha256=manifest_sha)
            self.assertEqual(report["planned"]["external_horses"], 1)
            with mock.patch.dict("os.environ", {"RACING_API_STAGING_WRITE_ENABLED": "true"}):
                apply_targeted_artifact(
                    root,
                    approved_manifest_sha256=manifest_sha,
                    allow_write=True,
                )

        self.assertFalse(
            ExternalHorse.objects.filter(
                source=ExternalDataSource.THE_RACING_API,
                horse_id__in=["hrs_100", "hrs_200"],
            ).exists()
        )
        target = ExternalHorse.objects.get(
            source=ExternalDataSource.THE_RACING_API,
            horse_id="hrs_1024",
        )
        self.assertEqual(target.sire_external_id, "hrs_100")
        self.assertEqual(target.dam_external_id, "hrs_200")
        pedigree = target.profile_snapshot["pedigree_two_generation"]
        self.assertEqual(pedigree["sire_sire"], "Northern Dancer (CAN)")
        self.assertEqual(pedigree["sire_dam"], "Fairy Bridge (USA)")
        self.assertEqual(pedigree["dam_sire"], "Top Ville (IRE)")
        self.assertEqual(pedigree["dam_dam"], "Toute Cy (FR)")
        self.assertEqual(
            target.profile_snapshot["major_wins"],
            [
                {
                    "race_id": "rac_arc_1999",
                    "race_date": "1999-10-03",
                    "race_name": "Prix de l'Arc de Triomphe",
                    "grade": "G1",
                    "course": "Longchamp (FR)",
                    "region": "FR",
                }
            ],
        )
        self.assertEqual(HorseExternalIdentity.objects.count(), 0)

    def test_target_non_runner_history_is_not_counted_as_an_actual_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, _manifest_sha = self._artifact(Path(temporary))
            normalized_path = root / "normalized/targeted-horse-export.json"
            normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
            non_runner_race = {
                **normalized["career"]["races"][0],
                "race_id": "rac_arc_2000_nr",
                "date": "2000-10-01",
                "runners": [
                    {
                        "horse_id": "hrs_1024",
                        "horse": "Montjeu (IRE)",
                        "position": "NR",
                        "number": "7",
                    }
                ],
            }
            normalized["career"]["races"].append(non_runner_race)
            normalized["career"]["provider_row_count"] = 2
            normalized["career"]["unique_race_count"] = 2
            results_path = root / "cache/response-0002.json"
            results_wrapper = json.loads(results_path.read_text(encoding="utf-8"))
            results_wrapper["payload"].update(
                {
                    "total": 2,
                    "results": normalized["career"]["races"],
                }
            )
            results_path.write_bytes(_canonical(results_wrapper))
            normalized_path.write_bytes(_canonical(normalized))
            manifest_path = root / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["responses"][1].update(
                {
                    "sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(),
                    "size": results_path.stat().st_size,
                }
            )
            manifest["normalized"]["sha256"] = hashlib.sha256(
                normalized_path.read_bytes()
            ).hexdigest()
            manifest["normalized"]["size"] = normalized_path.stat().st_size
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            (root / "COMPLETE").write_text(manifest_sha + "\n", encoding="ascii")

            report = dry_run_targeted_artifact(
                root, approved_manifest_sha256=manifest_sha
            )

            self.assertEqual(report["planned"]["external_races"], 2)
            self.assertEqual(report["planned"]["external_results"], 1)
            self.assertEqual(report["planned"]["external_histories"], 1)
