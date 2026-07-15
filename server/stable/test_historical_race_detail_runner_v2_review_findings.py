from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from stable.test_historical_race_detail_runner_v2_contract import (
    FIXTURES,
    STAGES,
    V2_LAUNCHER,
    _complete_candidate,
    _load_tool,
    _load_v2,
    _materialize_descriptor,
    _validate_descriptor,
)


class HistoricalDetailRunnerV2ReviewFindingTests(SimpleTestCase):
    def test_request_policy_accepts_equibase_query_with_strict_parameter_schema(self):
        module = _load_v2()
        host = "www.equibase.com"
        valid = (
            "https://www.equibase.com/yearbook/Result.cfm?"
            "cy=USA&de=D&rd=2024-05-04&rn=9&tk=CD"
        )
        policy = {
            "max_requests": 2,
            "minimum_interval_seconds": 0,
            "allowed_hosts": [host],
            "redirect_hosts": [host],
            "url_patterns": {host: [r"^/yearbook/Result\.cfm$"]},
            "query_patterns": {
                host: {
                    "parameters": {
                        "cy": r"USA",
                        "de": r"D",
                        "rd": r"20[0-9]{2}-[0-9]{2}-[0-9]{2}",
                        "rn": r"[1-9]|1[0-9]",
                        "tk": r"[A-Z]{2,4}",
                    },
                    "required_keys": ["cy", "de", "rd", "rn", "tk"],
                }
            },
        }
        descriptor = {"request_policy": policy}
        rejected = (
            valid + "&download=1",
            valid.replace("&tk=CD", "&tk=CD&tk=CD"),
            valid.replace("cy=USA", "=USA"),
            valid.replace("&tk=CD", ""),
            valid.replace("https://", "https://user@"),
            valid.replace(host, host + ":443"),
            valid + "#result",
        )
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(module.RunnerV2Error):
                module.validate_request(descriptor, [], url=url, redirect_chain=[])

        result = module.validate_request(
            descriptor,
            [],
            url=valid,
            redirect_chain=[valid.replace("rn=9", "rn=10")],
        )
        self.assertEqual(result["url"], valid)
        self.assertEqual(len(result["redirect_chain"]), 1)

        unbounded = copy.deepcopy(policy)
        unbounded["query_patterns"][host]["parameters"]["tk"] = ".*"
        with self.assertRaises(module.RunnerV2Error):
            module.validate_request_policy(unbounded)

        jra = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
        no_query_descriptor = {
            "request_policy": {
                "max_requests": 1,
                "minimum_interval_seconds": 0,
                "allowed_hosts": ["www.jra.go.jp"],
                "redirect_hosts": ["www.jra.go.jp"],
                "url_patterns": {
                    "www.jra.go.jp": [r"^/datafile/seiseki/replay/2005/99\.html$"]
                },
            }
        }
        self.assertEqual(
            module.validate_request(no_query_descriptor, [], url=jra, redirect_chain=[])["url"],
            jra,
        )

    def test_controlled_http_accepts_ledger_hkjc_query_for_initial_and_redirect(self):
        module = _load_tool("historical_race_detail_http.py")
        host = "racing.hkjc.com"
        first = (
            "https://racing.hkjc.com/en-us/local/information/localresults?"
            "racedate=2016%2F01%2F01&Racecourse=ST&RaceNo=8"
        )
        redirected = first.replace("RaceNo=8", "RaceNo=9")
        policy = {
            "max_requests": 2,
            "max_requests_per_host": 2,
            "minimum_interval_seconds": 0,
            "allowed_hosts": [host],
            "redirect_hosts": [host],
            "url_patterns": {host: [r"^/en-us/local/information/localresults$"]},
            "query_patterns": {
                host: {
                    "parameters": {
                        "racedate": r"20[0-9]{2}/[0-9]{2}/[0-9]{2}",
                        "Racecourse": r"ST|HV",
                        "RaceNo": r"[1-9]|1[0-2]",
                    },
                    "required_keys": ["racedate", "Racecourse", "RaceNo"],
                }
            },
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = module.ControlledRequestSession(
                policy=policy,
                shard_id="hong-kong-race-pages-01",
                shard_state_path=root / "shard-budget.json",
                host_state_root=root / "hosts",
            )
            with self.assertRaises(module.ControlledHTTPError):
                session.reserve_initial(first + "&lang=en")
            session.reserve_initial(first)
            session.reserve_redirect(redirected)
            with self.assertRaises(module.ControlledHTTPError):
                session.validate_final_url(first + "&lang=en")
            shard_state = json.loads((root / "shard-budget.json").read_text(encoding="utf-8"))

        self.assertEqual(shard_state["request_count"], 2)
        self.assertEqual(session.reserved_urls, [first, redirected])

    def test_parse_dispatches_real_hkjc_sportinglife_and_zeturf_offline_parsers(self):
        adapters = _load_tool("historical_race_detail_adapters.py")
        cases = (
            (
                "hong_kong",
                "hkjc",
                "hkjc_results_all_zh_hk",
                "https://racing.hkjc.com/racing/information/English/Racing/LocalResults.aspx?RaceNo=8",
                "hkjc-minimal.html",
            ),
            (
                "united_kingdom",
                "sporting_life",
                "sporting_life",
                "https://www.sportinglife.com/racing/results/2000-06-22/ascot/12345/gold-cup",
                "sportinglife-minimal.html",
            ),
            (
                "france",
                "zeturf",
                "zeturf",
                "https://www.zeturf.fr/fr/course-du-jour/2012-05-27/R1C5-longchamp-prix-d-ispahan",
                "zeturf-minimal.html",
            ),
        )
        for region, provider, source_name, source_url, fixture_name in cases:
            with self.subTest(region=region), TemporaryDirectory() as tmp:
                root = Path(tmp)
                events = root / "events.csv"
                source_fragment = root / "source-fragment.json"
                cache_root = root / "cache"
                run_root = root / "run"
                cache_root.mkdir()
                run_root.mkdir()
                with events.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=["target_id", "year", "slug", "status", "source_refs"],
                    )
                    writer.writeheader()
                    writer.writerow(
                        {
                            "target_id": "71001",
                            "year": "2012",
                            "slug": f"{region}-fixture",
                            "status": "finished",
                            "source_refs": json.dumps(
                                {
                                    "detail_discovery": {
                                        "urls": {
                                            "result_url": {
                                                "url": source_url,
                                                "source_provider": provider,
                                            }
                                        }
                                    }
                                }
                            ),
                        }
                    )
                source_fragment.write_text(
                    json.dumps(
                        {
                            "requests": [
                                {
                                    "target_id": "71001",
                                    "source_provider": provider,
                                    "source_name": source_name,
                                    "source_url": source_url,
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                source = cache_root / "source.html"
                source.write_bytes((FIXTURES / fixture_name).read_bytes())
                manifest = cache_root / "source_cache_manifest.json"
                manifest.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "root": str(cache_root),
                            "files": {
                                source.name: {
                                    "path": source.name,
                                    "size": source.stat().st_size,
                                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                    "source_url": source_url,
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                artifact = adapters.parse_cached_sources(
                    {
                        "region": region,
                        "adapter_inputs": {
                            "events_csv": str(events),
                            "source_fragment": str(source_fragment),
                        },
                    },
                    cache_artifact={"source_cache_manifest": str(manifest)},
                    run_root=run_root,
                )
                candidates = adapters.read_candidates(Path(artifact["candidate_jsonl"]))

                self.assertEqual(artifact["candidate_count"], 1)
                self.assertGreater(artifact["runner_count"], 0)
                self.assertGreater(artifact["result_count"], 0)
                self.assertEqual(candidates[0]["source_name"], source_name)

        self.assertTrue(
            {"jra", "hkjc", "sporting_life", "uk_irishracing", "zeturf", "france_irishracing", "equibase", "nsa"}
            <= set(adapters.supported_parse_providers())
        )

    def test_package_consumes_and_binds_only_validated_candidate_jsonl(self):
        module = _load_v2()
        source_url = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_root = root / "plan"
            run_root = root / "run"
            stage_root = run_root / "stages"
            cache_root = run_root / "source-cache"
            for path in (plan_root, stage_root, cache_root):
                path.mkdir(parents=True, exist_ok=True)
            events = plan_root / "events.csv"
            with events.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "target_id",
                        "target_sha256",
                        "inventory_artifact_sha256",
                        "year",
                        "slug",
                        "source_refs",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "target_id": "50556",
                        "target_sha256": "2" * 64,
                        "inventory_artifact_sha256": "4" * 64,
                        "year": "2005",
                        "slug": "japan-daily-hai-nisai-2005",
                        "source_refs": json.dumps(
                            {
                                "detail_discovery": {
                                    "urls": {
                                        "result_url": {
                                            "url": source_url,
                                            "source_provider": "jra",
                                        }
                                    }
                                }
                            }
                        ),
                    }
                )
            source = cache_root / "source.html"
            source.write_bytes(b"verified cache")
            cache_manifest = cache_root / "source_cache_manifest.json"
            cache_manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "files": {
                            source.name: {
                                "path": source.name,
                                "size": source.stat().st_size,
                                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                "source_url": source_url,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            def parsed_candidate(horse_name):
                refs = {"primary": source_url}
                return {
                    "year": 2005,
                    "slug": "japan-daily-hai-nisai-2005",
                    "source_name": "jra_official_result_page",
                    "source_url": source_url,
                    "modules": {
                        "runners": {"items": [{"horse_number": "1", "horse_name": horse_name, "source_refs": refs}]},
                        "results": {"items": [{"finish_position": 1, "horse_number": "1", "horse_name": horse_name, "source_refs": refs}]},
                    },
                }

            raw_path = run_root / "parsed-candidates.jsonl"
            validated_path = run_root / "validated-candidates.jsonl"
            raw_path.write_text(json.dumps(parsed_candidate("Raw Winner")) + "\n", encoding="utf-8")
            validated_path.write_text(
                json.dumps(parsed_candidate("Validated Winner")) + "\n", encoding="utf-8"
            )
            (stage_root / "validate.json").write_text(
                json.dumps(
                    {
                        "stage": "validate",
                        "candidate_jsonl": str(raw_path),
                        "validated_candidate_jsonl": str(validated_path),
                    }
                ),
                encoding="utf-8",
            )
            (stage_root / "cache.json").write_text(
                json.dumps(
                    {
                        "stage": "cache",
                        "source_cache_manifest": str(cache_manifest),
                    }
                ),
                encoding="utf-8",
            )
            result = module._execute_internal_stage(
                {
                    "region": "japan",
                    "mounts": [{"role": "plan", "path": str(plan_root)}],
                    "adapter_inputs": {"events_csv": str(events)},
                },
                stage="package",
                stage_root=stage_root,
                run_root=run_root,
            )
            package = json.loads(Path(result["package_manifest"]).read_text(encoding="utf-8"))
            validated_size = validated_path.stat().st_size
            validated_sha256 = hashlib.sha256(validated_path.read_bytes()).hexdigest()

        self.assertEqual(
            package["records"][0]["modules"]["results"]["items"][0]["horse_name"],
            "Validated Winner",
        )
        self.assertEqual(package["candidate_identity"]["path"], str(validated_path))
        self.assertEqual(package["candidate_identity"]["size"], validated_size)
        self.assertEqual(package["candidate_identity"]["sha256"], validated_sha256)

    def test_v1_migration_rejects_candidate_wrapped_for_another_target(self):
        module = _load_v2()
        with TemporaryDirectory() as tmp:
            evidence_root = Path(tmp)
            target_sha = "6" * 64
            other_target_sha = "7" * 64
            candidate = _complete_candidate()
            candidate["target_id"] = "61001"
            candidate["target_sha256"] = other_target_sha
            candidate["source_mappings"][0]["target_id"] = "61001"
            evidence_payload = {
                "schema_version": "1.0",
                "plan_id": "detail-crawl-1998-2026-v1",
                "shard_id": "united_kingdom-2013-v1",
                "target_id": "61000",
                "target_sha256": target_sha,
                "candidate": candidate,
            }
            evidence_path = evidence_root / "61000.json"
            evidence_path.write_text(json.dumps(evidence_payload), encoding="utf-8")
            source = {
                "schema_version": "1.0",
                "plan_id": evidence_payload["plan_id"],
                "shard_id": evidence_payload["shard_id"],
                "region": "united_kingdom",
                "plan_manifest_identity": {},
                "targets": [
                    {
                        "target_id": "61000",
                        "target_sha256": target_sha,
                        "completion_evidence_identity": {
                            "path": evidence_path.name,
                            "size": evidence_path.stat().st_size,
                            "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                        },
                    }
                ],
                "complete_target_ids": ["61000"],
                "gap_target_ids": [],
                "cache_entries": [],
            }
            target_set_sha = module.hash_v1_target_set(source["targets"])
            plan_manifest = evidence_root / "plan-manifest.json"
            plan_manifest.write_text(
                json.dumps(
                    {
                        "plan_id": source["plan_id"],
                        "shard_id": source["shard_id"],
                        "target_set_sha256": target_set_sha,
                    }
                ),
                encoding="utf-8",
            )
            source["plan_manifest_identity"] = {
                "path": plan_manifest.name,
                "size": plan_manifest.stat().st_size,
                "sha256": hashlib.sha256(plan_manifest.read_bytes()).hexdigest(),
            }
            descriptor = {
                "schema_version": "2.0",
                "plan_id": "detail-crawl-1998-2026-v2",
                "shard_id": "united_kingdom-2013-v2",
                "region": "united_kingdom",
                "targets": copy.deepcopy(source["targets"]),
                "v1_source_identity": {
                    "plan_id": source["plan_id"],
                    "shard_id": source["shard_id"],
                    "plan_manifest_identity": source["plan_manifest_identity"],
                    "target_set_sha256": target_set_sha,
                },
            }

            with self.assertRaises(module.RunnerV2Error):
                module.migrate_v1_progress(source, descriptor, evidence_root=evidence_root)

    def test_dispatch_runs_real_internal_pipeline_and_writes_package_checkpoint(self):
        module = _load_v2()
        with TemporaryDirectory() as tmp:
            descriptor, paths = _materialize_descriptor(Path(tmp))
            source_url = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
            source_body = paths["plan_root"] / "jra-2005-99.html"
            source_body.write_bytes((FIXTURES / "jra-2005-replay-legacy.html").read_bytes())
            target = descriptor["targets"][0]
            descriptor["targets"] = [target]
            with paths["events_file"].open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "target_id",
                        "target_sha256",
                        "inventory_artifact_sha256",
                        "year",
                        "slug",
                        "status",
                        "date",
                        "course",
                        "distance",
                        "source_refs",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "target_id": target["target_id"],
                        "target_sha256": target["target_sha256"],
                        "inventory_artifact_sha256": "4" * 64,
                        "year": 2005,
                        "slug": "japan-daily-hai-nisai-2005",
                        "status": "finished",
                        "date": "2005-10-15",
                        "course": "Kyoto",
                        "distance": "1600m",
                        "source_refs": json.dumps(
                            {
                                "detail_discovery": {
                                    "urls": {
                                        "result_url": {
                                            "url": source_url,
                                            "source_provider": "jra",
                                            "source_authority": "official",
                                        }
                                    }
                                }
                            }
                        ),
                    }
                )
            source_fragment = {
                "schema_version": "2.0",
                "requests": [
                    {
                        "target_id": target["target_id"],
                        "target_sha256": target["target_sha256"],
                        "region": "japan",
                        "source_provider": "jra",
                        "source_name": "jra_official_result_page",
                        "source_url": source_url,
                        "fixture_identity": {
                            "path": str(source_body),
                            "size": source_body.stat().st_size,
                            "sha256": hashlib.sha256(source_body.read_bytes()).hexdigest(),
                        },
                    }
                ],
            }
            paths["source_file"].write_text(json.dumps(source_fragment), encoding="utf-8")
            for identity in descriptor["identities"]:
                if identity["role"] == "events_csv":
                    identity["size"] = paths["events_file"].stat().st_size
                    identity["sha256"] = hashlib.sha256(paths["events_file"].read_bytes()).hexdigest()
                elif identity["role"] == "source_fragment":
                    identity["size"] = paths["source_file"].stat().st_size
                    identity["sha256"] = hashlib.sha256(paths["source_file"].read_bytes()).hexdigest()
            descriptor["adapter_inputs"] = {
                "events_csv": str(paths["events_file"]),
                "source_fragment": str(paths["source_file"]),
            }
            paths["descriptor_file"].write_text(
                json.dumps(descriptor, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            normalized = _validate_descriptor(module, descriptor, paths)

            artifacts = {}
            for stage in STAGES:
                result = module.dispatch_stage(
                    normalized,
                    stage=stage,
                    run_root=paths["run_root"],
                    actual_image_digest=descriptor["image"]["digest"],
                    actual_image_revision=descriptor["image"]["revision"],
                )
                artifacts[stage] = json.loads(
                    Path(result["artifact_path"]).read_text(encoding="utf-8")
                )

            cache_manifest = json.loads(
                Path(artifacts["cache"]["source_cache_manifest"]).read_text(encoding="utf-8")
            )
            candidates = [
                json.loads(line)
                for line in Path(artifacts["parse"]["candidate_jsonl"])
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            package_manifest = json.loads(
                Path(artifacts["package"]["package_manifest"]).read_text(encoding="utf-8")
            )
            checkpoint = json.loads(paths["run_root"].joinpath("checkpoint.json").read_text())
        self.assertEqual(len(cache_manifest["files"]), 1)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0]["modules"]["runners"]["items"]), 11)
        self.assertEqual(len(candidates[0]["modules"]["results"]["items"]), 11)
        self.assertEqual(len(package_manifest["records"]), 1)
        self.assertEqual(set(checkpoint["stages"].values()), {"complete"})
        for region in module.REGIONS:
            for stage in STAGES:
                spec = module.get_adapter_spec(region, stage)
                self.assertEqual(spec["execution"], "internal_callable")
                self.assertNotIn("argv", spec)

    def test_controlled_http_reserves_initial_and_redirect_requests_atomically(self):
        module = _load_tool("historical_race_detail_http.py")
        policy = {
            "max_requests": 2,
            "max_requests_per_host": 2,
            "minimum_interval_seconds": 0,
            "allowed_hosts": ["www.jra.go.jp"],
            "redirect_hosts": ["www.jra.go.jp"],
            "url_patterns": {
                "www.jra.go.jp": [r"^/datafile/seiseki/replay/2005/[0-9]{2}\.html$"],
            },
        }
        first = "https://www.jra.go.jp/datafile/seiseki/replay/2005/98.html"
        second = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = module.ControlledRequestSession(
                policy=policy,
                shard_id="japan-2005-jra-01",
                shard_state_path=root / "shard-budget.json",
                host_state_root=root / "hosts",
            )
            session.reserve_initial(first)
            with self.assertRaises(module.ControlledHTTPError):
                session.reserve_redirect("https://attacker.example/final")
            session.reserve_redirect(second)
            with self.assertRaises(module.ControlledHTTPError):
                session.reserve_redirect(first)

            shard_state = json.loads((root / "shard-budget.json").read_text(encoding="utf-8"))
            host_state = json.loads(
                (root / "hosts" / "www.jra.go.jp.last-start.json").read_text(encoding="utf-8")
            )
            host_rows = (root / "hosts" / "www.jra.go.jp.requests.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        self.assertEqual(shard_state["request_count"], 2)
        self.assertEqual(host_state["request_count"], 2)
        self.assertEqual(len(host_rows), 2)

    def test_jra_download_uses_controlled_http_client(self):
        module = _load_tool("prepare_jra_race_detail_candidates.py")
        source_url = "https://www.jra.go.jp/datafile/seiseki/replay/2005/99.html"
        context = {
            "request_policy": {
                "max_requests": 1,
                "minimum_interval_seconds": 0,
                "allowed_hosts": ["www.jra.go.jp"],
                "redirect_hosts": ["www.jra.go.jp"],
                "url_patterns": {"www.jra.go.jp": [r"^/datafile/seiseki/replay/2005/99\.html$"]},
            },
            "shard_id": "japan-2005-jra-01",
            "shard_state_path": "/run/shard-budget.json",
            "host_state_root": "/run/host-lock",
        }
        with TemporaryDirectory() as tmp, patch.object(
            module,
            "controlled_http_get",
            return_value=b"controlled-body",
        ) as controlled_get, patch.object(module, "write_source_cache"):
            body = module._download(
                source_url,
                Path(tmp) / "source.html",
                allow_network=True,
                timeout=10,
                request_context=context,
            )

        self.assertEqual(body, b"controlled-body")
        controlled_get.assert_called_once()
        self.assertEqual(controlled_get.call_args.kwargs["shard_id"], context["shard_id"])

    def test_launcher_rejects_descriptor_image_mismatch_before_docker_run(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            descriptor, paths = _materialize_descriptor(root)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            docker_log = root / "docker.log"
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\nexit 0\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            wrong_digest = "sha256:" + "9" * 64
            env = dict(os.environ)
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["DOCKER_LOG"] = str(docker_log)

            result = subprocess.run(
                [
                    "sh",
                    str(V2_LAUNCHER),
                    "--image",
                    wrong_digest,
                    "--descriptor",
                    str(paths["descriptor_file"]),
                    "--repo-root",
                    str(paths["repo_root"]),
                    "--plan-root",
                    str(paths["plan_root"]),
                    "--run-root",
                    str(paths["run_root"]),
                    "--host-lock-root",
                    str(paths["host_lock_root"]),
                    "--stage",
                    "discover",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertRegex((result.stdout + result.stderr).lower(), r"image.*mismatch|digest.*mismatch")
        self.assertFalse(docker_log.exists(), "wrong image must be rejected before docker run")
        launcher_text = V2_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("--entrypoint", launcher_text)
        self.assertIn("--actual-image-digest", launcher_text)
        self.assertIn("--actual-image-revision", launcher_text)

    def test_v1_migration_rejects_cross_shard_forged_complete_evidence(self):
        module = _load_v2()
        target_sha = "6" * 64
        evidence = b'{"target_id":"61000","status":"complete"}\n'
        evidence_identity = {
            "path": "evidence/61000.json",
            "size": len(evidence),
            "sha256": hashlib.sha256(evidence).hexdigest(),
        }
        source = {
            "schema_version": "1.0",
            "plan_id": "detail-crawl-1998-2026-v1",
            "shard_id": "united_kingdom-2013-v1",
            "region": "united_kingdom",
            "plan_manifest_identity": {},
            "targets": [
                {
                    "target_id": "61000",
                    "target_sha256": target_sha,
                    "completion_evidence_identity": evidence_identity,
                },
                {"target_id": "61001", "target_sha256": "8" * 64},
            ],
            "complete_target_ids": ["61000"],
            "gap_target_ids": ["61001"],
            "cache_entries": [],
        }
        target_set_sha = module.hash_v1_target_set(source["targets"])
        descriptor = {
            "schema_version": "2.0",
            "plan_id": "detail-crawl-1998-2026-v2",
            "shard_id": "united_kingdom-2013-v2",
            "region": "united_kingdom",
            "targets": copy.deepcopy(source["targets"]),
            "v1_source_identity": {
                "plan_id": source["plan_id"],
                "shard_id": "different-v1-shard",
                "plan_manifest_identity": source["plan_manifest_identity"],
                "target_set_sha256": target_set_sha,
            },
        }

        with TemporaryDirectory() as tmp:
            evidence_root = Path(tmp)
            manifest = evidence_root / "plan-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            source["plan_manifest_identity"] = {
                "path": manifest.name,
                "size": manifest.stat().st_size,
                "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            }
            descriptor["v1_source_identity"]["plan_manifest_identity"] = copy.deepcopy(
                source["plan_manifest_identity"]
            )
            with self.assertRaises(module.RunnerV2Error):
                module.migrate_v1_progress(source, descriptor, evidence_root=evidence_root)

    def test_v1_migration_reads_and_binds_real_evidence_under_approved_root(self):
        module = _load_v2()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_root = root / "evidence"
            evidence_root.mkdir()
            target_sha = "6" * 64
            evidence_path = evidence_root / "61000.json"
            evidence_payload = {
                "schema_version": "1.0",
                "plan_id": "detail-crawl-1998-2026-v1",
                "shard_id": "united_kingdom-2013-v1",
                "target_id": "61000",
                "target_sha256": target_sha,
                "candidate": _complete_candidate(),
            }
            evidence_payload["candidate"]["target_id"] = "61000"
            evidence_payload["candidate"]["source_mappings"][0]["target_id"] = "61000"
            evidence_path.write_text(json.dumps(evidence_payload), encoding="utf-8")
            evidence_identity = {
                "path": evidence_path.name,
                "size": evidence_path.stat().st_size,
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            }
            source = {
                "schema_version": "1.0",
                "plan_id": evidence_payload["plan_id"],
                "shard_id": evidence_payload["shard_id"],
                "region": "united_kingdom",
                "plan_manifest_identity": {},
                "targets": [
                    {
                        "target_id": "61000",
                        "target_sha256": target_sha,
                        "completion_evidence_identity": evidence_identity,
                    }
                ],
                "complete_target_ids": ["61000"],
                "gap_target_ids": [],
                "cache_entries": [],
            }
            target_set_sha = module.hash_v1_target_set(source["targets"])
            plan_manifest = evidence_root / "plan-manifest.json"
            plan_manifest.write_text(
                json.dumps(
                    {
                        "plan_id": source["plan_id"],
                        "shard_id": source["shard_id"],
                        "target_set_sha256": target_set_sha,
                    }
                ),
                encoding="utf-8",
            )
            source["plan_manifest_identity"] = {
                "path": plan_manifest.name,
                "size": plan_manifest.stat().st_size,
                "sha256": hashlib.sha256(plan_manifest.read_bytes()).hexdigest(),
            }
            descriptor = {
                "schema_version": "2.0",
                "plan_id": "detail-crawl-1998-2026-v2",
                "shard_id": "united_kingdom-2013-v2",
                "region": "united_kingdom",
                "targets": copy.deepcopy(source["targets"]),
                "v1_source_identity": {
                    "plan_id": source["plan_id"],
                    "shard_id": source["shard_id"],
                    "plan_manifest_identity": source["plan_manifest_identity"],
                    "target_set_sha256": target_set_sha,
                },
            }

            migrated = module.migrate_v1_progress(
                source,
                descriptor,
                evidence_root=evidence_root,
            )
            self.assertEqual(migrated["target_states"][0]["state"], "complete")

            evidence_path.unlink()
            with self.assertRaises(module.RunnerV2Error):
                module.migrate_v1_progress(source, descriptor, evidence_root=evidence_root)

            outside = root / "outside.json"
            outside.write_text(json.dumps(evidence_payload), encoding="utf-8")
            source["targets"][0]["completion_evidence_identity"]["path"] = "../outside.json"
            with self.assertRaises(module.RunnerV2Error):
                module.migrate_v1_progress(source, descriptor, evidence_root=evidence_root)

            source["targets"][0]["completion_evidence_identity"]["path"] = "61000.json"
            evidence_path.symlink_to(outside)
            with self.assertRaises(module.RunnerV2Error):
                module.migrate_v1_progress(source, descriptor, evidence_root=evidence_root)

    def test_complete_allows_scratches_and_missing_numbers_with_stable_source_match(self):
        module = _load_v2()
        candidate = _complete_candidate()
        source_url = candidate["event"]["source_url"]
        candidate["runners"] = [
            {
                "horse_number": "1",
                "horse_name": "Winner",
                "source_refs": {"primary": source_url},
            },
            {
                "horse_number": "2",
                "horse_name": "Scratched Horse",
                "running_status": "scratched",
                "source_refs": {"primary": source_url},
            },
            {
                "horse_number": "",
                "horse_name": " Ｔest   Horse ",
                "source_refs": {"primary": source_url},
            },
        ]
        candidate["results"] = [
            {
                "finish_position": 1,
                "horse_number": "1",
                "horse_name": "Winner",
                "source_refs": {"primary": source_url},
            },
            {
                "finish_position": 2,
                "horse_number": "",
                "horse_name": "test horse",
                "source_refs": {"primary": source_url},
            },
        ]
        candidate["winner"] = {"horse_number": "1", "horse_name": "Winner"}

        normalized = module.validate_complete_target(candidate, seen_source_urls=set())

        self.assertEqual(len(normalized["runners"]), 3)
        self.assertEqual(len(normalized["results"]), 2)

    def test_complete_rejects_unmatched_runner_without_approved_exception_status(self):
        module = _load_v2()
        candidate = _complete_candidate()
        candidate["runners"].append(
            {
                "horse_number": "9",
                "horse_name": "Ordinary Declared Runner",
                "running_status": "declared",
            }
        )

        with self.assertRaises(module.RunnerV2Error):
            module.validate_complete_target(candidate, seen_source_urls=set())
