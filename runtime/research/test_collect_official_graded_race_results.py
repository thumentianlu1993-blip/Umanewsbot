from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from runtime.research import collect_official_graded_race_results as runner


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OfficialGradedResultRunnerTests(unittest.TestCase):
    def manifest(self, root: Path, races: list[dict] | None = None) -> tuple[Path, str]:
        payload = {
            "schema_version": 1,
            "year": 2025,
            "catalog_sha256": "a" * 64,
            "reviewed_mapping_sha256": "b" * 64,
            "races": races
            or [
                {
                    "race_key": "germany-test-g1-2025",
                    "provider": "de_deutscher_galopp",
                    "result_url": "https://www.deutscher-galopp.de/gr/renntage/rennen.php?datum=2025-06-01",
                    "region": "germany",
                    "country": "germany",
                    "grade": "G1",
                    "distance": "2000",
                    "race_name": "Test Preis",
                    "local_date": "2025-06-01",
                }
            ],
        }
        for race in payload["races"]:
            race.setdefault("distance", "2000")
            race.setdefault("race_name", "Test Race")
        path = root / "manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path, digest(path)

    def args(self, manifest: Path, manifest_sha: str, output: Path, **overrides):
        values = {
            "manifest": str(manifest),
            "manifest_sha256": manifest_sha,
            "output_dir": str(output),
            "resume": False,
            "allow_network": True,
            "timeout": 10,
            "request_interval_seconds": 0,
            "time_budget_seconds": 0,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_complete_run_is_cache_bound_and_resume_is_byte_stable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, manifest_sha = self.manifest(root)
            output = root / "output"
            participants = [
                {
                    "provider": "de_deutscher_galopp",
                    "provider_horse_id": "horse-1",
                    "finish_position": 1,
                    "horse_number": "1",
                    "horse_name": "Official Horse",
                    "jockey_name": "Jockey",
                    "trainer_name": "Trainer",
                    "finish_time": "",
                    "margin": "",
                    "participant_status": "finished",
                }
            ]
            with mock.patch.object(
                runner,
                "fetch",
                return_value=(b"official response", "https://www.deutscher-galopp.de/results/2025"),
            ) as fetch, mock.patch.object(
                runner,
                "parse_official_results",
                return_value=participants,
            ):
                first = runner.run(self.args(manifest, manifest_sha, output))
                first_bytes = (output / "final" / "official_participants.jsonl").read_bytes()
                second = runner.run(
                    self.args(manifest, manifest_sha, output, resume=True)
                )

            self.assertEqual(first["race_count"], 1)
            self.assertEqual(first["participant_count"], 1)
            self.assertEqual(first["files"], second["files"])
            self.assertEqual(first_bytes, (output / "final" / "official_participants.jsonl").read_bytes())
            fetch.assert_called_once()
            row = json.loads(first_bytes)
            self.assertEqual(row["source_cache_sha256"], hashlib.sha256(b"official response").hexdigest())
            self.assertEqual(row["provider_horse_id"], "horse-1")

    def test_retryable_failure_checkpoints_and_resumes_exact_item(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, manifest_sha = self.manifest(root)
            output = root / "output"
            args = self.args(manifest, manifest_sha, output)
            with mock.patch.object(
                runner,
                "fetch",
                side_effect=runner.RetryableNetworkError("temporary"),
            ):
                with self.assertRaises(runner.RetryableNetworkError):
                    runner.run(args)
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["items"]["germany-test-g1-2025"]["status"], "retryable_error")

            with mock.patch.object(
                runner,
                "fetch",
                return_value=(b"recovered", "https://www.deutscher-galopp.de/results/2025"),
            ), mock.patch.object(
                runner,
                "parse_official_results",
                return_value=[{"finish_position": 1, "horse_name": "Recovered"}],
            ):
                result = runner.run(self.args(manifest, manifest_sha, output, resume=True))
            self.assertEqual(result["status"], "complete")

    def test_manifest_rejects_geography_mismatch_and_duplicate_url(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            race = {
                "race_key": "bad",
                "provider": "uae_era",
                "result_url": "https://emiratesracing.com/racecard/2025-01-01/1/results",
                "region": "germany",
                "country": "united_arab_emirates",
                "grade": "G1",
                "local_date": "2025-01-01",
            }
            manifest, manifest_sha = self.manifest(root, [race])
            with self.assertRaisesRegex(runner.RunnerError, "geography mismatch"):
                runner.load_manifest(manifest, expected_sha256=manifest_sha)

            race["region"] = "middle_east"
            duplicate = {
                **race,
                "race_key": "bad-2",
                "result_url": (
                    "https://emiratesracing.com/racecard/2025-01-01/1/results?b=2&a=1"
                ),
            }
            race["result_url"] += "?a=1&b=2"
            manifest, manifest_sha = self.manifest(root, [race, duplicate])
            with self.assertRaisesRegex(runner.RunnerError, "duplicated"):
                runner.load_manifest(manifest, expected_sha256=manifest_sha)

    def test_australia_allows_distinct_races_on_one_official_meeting_page(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            url = "https://www.racingaustralia.horse/FreeFields/Results.aspx?Key=2025Apr05%2CNSW%2CRoyal+Randwick"
            races = [
                {
                    "race_key": "au-one",
                    "provider": "au_racing_australia",
                    "result_url": url,
                    "region": "australia",
                    "country": "australia",
                    "grade": "G3",
                    "distance": "1100",
                    "race_name": "Kindergarten Stakes",
                    "source_race_name": "WIDDEN KINDERGARTEN STAKES",
                    "local_date": "2025-04-05",
                },
                {
                    "race_key": "au-two",
                    "provider": "au_racing_australia",
                    "result_url": url,
                    "region": "australia",
                    "country": "australia",
                    "grade": "G3",
                    "distance": "2000",
                    "race_name": "Adrian Knox Stakes",
                    "source_race_name": "TAB ADRIAN KNOX STAKES",
                    "local_date": "2025-04-05",
                },
            ]
            manifest, manifest_sha = self.manifest(root, races)
            normalized, _ = runner.load_manifest(manifest, expected_sha256=manifest_sha)
            self.assertEqual(len(normalized["races"]), 2)

            races[1]["source_race_name"] = "widden-kindergarten stakes"
            races[1]["distance"] = races[0]["distance"]
            manifest, manifest_sha = self.manifest(root, races)
            with self.assertRaisesRegex(runner.RunnerError, "duplicated"):
                runner.load_manifest(manifest, expected_sha256=manifest_sha)

    def test_qrec_bootstrap_uses_ephemeral_public_frontend_config(self):
        class Response:
            def __init__(self, url, body):
                self.url = url
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return self.url

            def read(self, _limit):
                return self.body

        responses = [
            Response("https://qrec.gov.qa/", b'<script src="/_next/static/chunks/pages/_app-test.js"></script>'),
            Response("https://qrec.gov.qa/_next/static/chunks/pages/_app-test.js", b'NEXT_PUBLIC_AUTH_GRANT_TOKEN||"grant-value";NEXT_PUBLIC_API_KEY||"key-value"'),
            Response("https://api.qrec.gov.qa/v1/qrec/token/generate", b'{"access_token":"temporary-token"}'),
        ]
        class Opener:
            def __init__(self):
                self.responses = iter(responses)
                self.call_count = 0

            def open(self, _request, timeout):
                self.call_count += 1
                self.timeout = timeout
                return next(self.responses)

        opener = Opener()
        runner.QREC_AUTH_CACHE.clear()
        try:
            with mock.patch.object(runner.request, "build_opener", return_value=opener):
                headers = runner._qrec_headers(timeout=3)
                cached = runner._qrec_headers(timeout=3)
            self.assertEqual(headers["apiToken"], "temporary-token")
            self.assertEqual(cached, headers)
            self.assertEqual(opener.call_count, 3)
        finally:
            runner.QREC_AUTH_CACHE.clear()

    def test_qrec_bootstrap_redirects_fail_closed_before_credentials_can_follow(self):
        handler = runner.QrecBootstrapRedirectHandler()
        home = runner.request.Request("https://qrec.gov.qa/")
        with self.assertRaisesRegex(runner.RunnerError, "outside official host"):
            handler.redirect_request(home, None, 302, "Found", {}, "https://example.com/app.js")
        token = runner.request.Request("https://api.qrec.gov.qa/v1/qrec/token/generate")
        with self.assertRaisesRegex(runner.RunnerError, "token endpoint redirected"):
            handler.redirect_request(token, None, 302, "Found", {}, "https://qrec.gov.qa/")
        result_handler = runner.StrictRedirectHandler("qa_qrec", 2025)
        data = runner.request.Request(
            "https://api.qrec.gov.qa/v1/qrec/race/data?pageaction=jsonracetab&raceid=27059&lang=en&racedate=2025-12-20"
        )
        with self.assertRaisesRegex(runner.RunnerError, "result endpoint redirected"):
            result_handler.redirect_request(
                data,
                None,
                302,
                "Found",
                {},
                "https://api.qrec.gov.qa/v1/qrec/race/data?pageaction=jsonracetab&raceid=99999&lang=en&racedate=2025-12-20",
            )

    def test_manifest_requires_review_binding_and_same_year_local_date(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, _ = self.manifest(root)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload.pop("reviewed_mapping_sha256")
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(runner.RunnerError, "reviewed mapping"):
                runner.load_manifest(manifest, expected_sha256=digest(manifest))

            payload["reviewed_mapping_sha256"] = "b" * 64
            payload["races"][0]["local_date"] = "2024-12-31"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(runner.RunnerError, "year drift"):
                runner.load_manifest(manifest, expected_sha256=digest(manifest))

    def test_tool_identity_change_invalidates_checkpoint(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, manifest_sha = self.manifest(root)
            output = root / "output"
            output.mkdir()
            identity = runner._checkpoint_identity(manifest_sha, 2025)
            (output / "checkpoint.json").write_text(
                json.dumps({**identity, "tool_version": "old", "items": {}, "provider_request_counts": {}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(runner.RunnerError, "tool_version"):
                runner.run(self.args(manifest, manifest_sha, output, resume=True))

    def test_network_requires_explicit_switch(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, manifest_sha = self.manifest(root)
            with self.assertRaisesRegex(runner.RunnerError, "explicit --allow-network"):
                runner.run(
                    self.args(manifest, manifest_sha, root / "output", allow_network=False)
                )

    def test_request_budget_is_write_ahead_and_cumulative_across_resume(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, manifest_sha = self.manifest(root)
            output = root / "output"
            with mock.patch.object(
                runner,
                "fetch",
                side_effect=runner.RetryableNetworkError("temporary"),
            ):
                with self.assertRaises(runner.RetryableNetworkError):
                    runner.run(self.args(manifest, manifest_sha, output))
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["provider_request_counts"], {"de_deutscher_galopp": 1})

            checkpoint["provider_request_counts"]["de_deutscher_galopp"] = runner.POLICIES[
                "de_deutscher_galopp"
            ].request_budget
            (output / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
            with mock.patch.object(runner, "fetch") as fetch:
                with self.assertRaisesRegex(runner.RunnerError, "budget exhausted"):
                    runner.run(self.args(manifest, manifest_sha, output, resume=True))
            fetch.assert_not_called()

    def test_deterministic_error_resume_never_refetches(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, manifest_sha = self.manifest(root)
            output = root / "output"
            with mock.patch.object(runner, "fetch", return_value=(b"bad", "https://www.deutscher-galopp.de/results/2025")), mock.patch.object(
                runner, "parse_official_results", side_effect=runner.OfficialSourceError("schema drift")
            ):
                with self.assertRaisesRegex(runner.RunnerError, "deterministic parse error"):
                    runner.run(self.args(manifest, manifest_sha, output))
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["provider_request_counts"], {"de_deutscher_galopp": 1})

            with mock.patch.object(runner, "fetch") as fetch:
                with self.assertRaisesRegex(runner.RunnerError, "checkpoint contains deterministic error"):
                    runner.run(self.args(manifest, manifest_sha, output, resume=True))
            fetch.assert_not_called()
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["provider_request_counts"], {"de_deutscher_galopp": 1})

    def test_checkpoint_rejects_unknown_race_provider_and_invalid_count(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, manifest_sha = self.manifest(root)
            output = root / "output"
            output.mkdir()
            base = {
                **runner._checkpoint_identity(manifest_sha, 2025),
                "items": {"outside": {"status": "retryable_error"}},
                "provider_request_counts": {},
            }
            checkpoint = output / "checkpoint.json"
            checkpoint.write_text(json.dumps(base), encoding="utf-8")
            with mock.patch.object(runner, "fetch") as fetch, self.assertRaisesRegex(
                runner.RunnerError, "race outside manifest"
            ):
                runner.run(self.args(manifest, manifest_sha, output, resume=True))
            fetch.assert_not_called()

            base["items"] = {}
            base["provider_request_counts"] = {"uae_era": 1}
            checkpoint.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaisesRegex(runner.RunnerError, "provider outside manifest"):
                runner.run(self.args(manifest, manifest_sha, output, resume=True))

            base["provider_request_counts"] = {"de_deutscher_galopp": -1}
            checkpoint.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaisesRegex(runner.RunnerError, "request count is invalid"):
                runner.run(self.args(manifest, manifest_sha, output, resume=True))

    def test_checkpoint_cache_path_must_match_race_bound_path(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, manifest_sha = self.manifest(root)
            output = root / "output"
            participants = [{"finish_position": 1, "horse_name": "Horse", "participant_status": "finished"}]
            with mock.patch.object(runner, "fetch", return_value=(b"body", "https://www.deutscher-galopp.de/results/2025")), mock.patch.object(
                runner, "parse_official_results", return_value=participants
            ):
                runner.run(self.args(manifest, manifest_sha, output))
            outside = root / "outside.response"
            outside.write_bytes(b"body")
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            checkpoint["items"]["germany-test-g1-2025"]["cache_path"] = "../outside.response"
            (output / "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
            with mock.patch.object(runner, "fetch") as fetch:
                with self.assertRaisesRegex(runner.RunnerError, "escapes output root"):
                    runner.run(self.args(manifest, manifest_sha, output, resume=True))
            fetch.assert_not_called()

    def test_checkpoint_cache_rejects_in_root_symlink_alias(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, manifest_sha = self.manifest(root)
            output = root / "output"
            participants = [{"finish_position": 1, "horse_name": "Horse", "participant_status": "finished"}]
            with mock.patch.object(runner, "fetch", return_value=(b"body", "https://www.deutscher-galopp.de/results/2025")), mock.patch.object(
                runner, "parse_official_results", return_value=participants
            ):
                runner.run(self.args(manifest, manifest_sha, output))
            checkpoint = json.loads((output / "checkpoint.json").read_text(encoding="utf-8"))
            item = checkpoint["items"]["germany-test-g1-2025"]
            cache = output / item["cache_path"]
            decoy = output / "source" / "decoy.response"
            decoy.write_bytes(cache.read_bytes())
            cache.unlink()
            cache.symlink_to(decoy)

            with mock.patch.object(runner, "fetch") as fetch:
                with self.assertRaisesRegex(runner.RunnerError, "contains symlink"):
                    runner.run(self.args(manifest, manifest_sha, output, resume=True))
            fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
