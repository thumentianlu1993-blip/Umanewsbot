from __future__ import annotations

import importlib.util
import csv
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"


def _load(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(f"{path.stem}_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class HistoricalRaceDetailDirectUrlTests(SimpleTestCase):
    def _event(self, provider: str, url: str) -> dict:
        return {
            "source_refs": json.dumps(
                {
                    "result_url": "https://legacy.example/result",
                    "detail_discovery": {
                        "urls": {
                            "result_url": {
                                "url": url,
                                "source_provider": provider,
                                "source_authority": "third_party_high_access",
                            }
                        }
                    },
                }
            )
        }

    def test_hkjc_adapter_prefers_approved_direct_result_url(self):
        module = _load("prepare_hkjc_race_detail_candidates.py")
        url = "https://racing.hkjc.com/en-us/local/information/localresults?racedate=2025/05/25&Racecourse=ST&RaceNo=8"
        self.assertEqual(module._approved_result_url(self._event("hkjc", url), provider="hkjc"), url)

    def test_sporting_life_adapter_rejects_other_provider_url(self):
        module = _load("prepare_uk_sportinglife_race_detail_candidates.py")
        event = self._event("uk_racingpost", "https://www.racingpost.com/results/fixture")
        self.assertEqual(module._approved_result_url(event, provider="uk_sportinglife"), "")

    def test_irishracing_adapter_requires_region_specific_provider(self):
        module = _load("prepare_irishracing_race_detail_candidates.py")
        url = "https://www.irishracing.com/raceresults/Thu-22nd-Jun-2000/Ascot/1545"

        self.assertEqual(module._approved_result_url(self._event("uk_irishracing", url), provider="uk_irishracing"), url)
        self.assertEqual(module._approved_result_url(self._event("france_irishracing", url), provider="uk_irishracing"), "")

    def test_hrn_adapter_prefers_approved_track_day_url(self):
        module = _load("prepare_us_hrn_race_detail_candidates.py")
        url = "https://entries.horseracingnation.com/entries-results/churchill-downs/2025-09-27"
        self.assertEqual(module._approved_result_url(self._event("us_hrn", url), provider="us_hrn"), url)

    def test_equibase_standard_pdf_parser_builds_complete_modules(self):
        module = _load("prepare_us_equibase_archived_race_detail_candidates.py")
        text = """
CHURCHILL DOWNS - October 29, 2000 - Race 9
STAKES Ack Ack H. Grade 3 - Thoroughbred
Last Raced Pgm Horse Name (Jockey) Wgt M/E PP Start 1/4 1/2 Str Fin Odds Comments
23Sep00 8KD6 8 Chindi (Doocy, Timothy) 113 L 8 7 10 10 41 1/2 11 1/2 6.20 rallied up rail
15Oct00 7KEE4 9 Smolderin Heart (Borel, Calvin) 113 L bf 9 2 22 1/2 23 12 22 22.40 second best
12Oct00 8KEE6 4 Millencolin (Day, Pat) 113 L bs 4 4 4Head 3Head 21/2 32 1/2 3.00 no late gain
8Oct00 7KEE5 1a Mongoose (Bailey, Jerry) 121 b 6 12 112 112 8Head 52 42 3/4 3.70 coupled entry
Fractional Times: 21.90 44.36 1:09.46 Final Time: 1:29.30
Trainers: 8-Hobby,Steve;9-Brennan,Terry;4-Lukas,D.;1a-Mott,William
Owners: 8-CresRan,LLC;
"""

        runners, results, metadata = module._parse_chart_text(text, source_url="https://www.equibase.com/chart")

        self.assertEqual([row["horse_number"] for row in runners], ["1a", "4", "8", "9"])
        self.assertEqual([row["barrier"] for row in runners], ["6", "4", "8", "9"])
        self.assertEqual(runners[2]["horse_name"], "Chindi")
        self.assertEqual(runners[2]["jockey_name"], "Timothy Doocy")
        self.assertEqual(runners[2]["trainer_name"], "Steve Hobby")
        self.assertEqual([row["finish_position"] for row in results], [1, 2, 3, 4])
        self.assertEqual(
            [row["horse_name"] for row in results],
            ["Chindi", "Smolderin Heart", "Millencolin", "Mongoose"],
        )
        self.assertTrue(metadata["runners_complete"])
        self.assertTrue(metadata["results_complete"])
        self.assertEqual(metadata["racecourse_compact"], "CHURCHILL DOWNS")
        self.assertEqual(metadata["local_date_text"], "October 29, 2000")
        self.assertEqual(metadata["race_number"], "9")

    def test_equibase_candidate_rejects_wrong_chart_identity(self):
        module = _load("prepare_us_equibase_archived_race_detail_candidates.py")
        metadata = {
            "racecourse_compact": "CHURCHILL DOWNS",
            "local_date_text": "October 29, 2000",
            "race_number": "9",
        }

        with self.assertRaisesRegex(RuntimeError, "date mismatch"):
            module._validate_chart_identity(
                metadata,
                {"local_date": "2000-10-30", "track_code": "CD", "race_number": "9"},
            )

        with self.assertRaisesRegex(RuntimeError, "racecourse mismatch"):
            module._validate_chart_identity(
                metadata,
                {"local_date": "2000-10-29", "track_code": "GP", "race_number": "9"},
            )

        with self.assertRaisesRegex(RuntimeError, "race number mismatch"):
            module._validate_chart_identity(
                metadata,
                {"local_date": "2000-10-29", "track_code": "CD", "race_number": "8"},
            )

    def test_equibase_pdf_must_match_date_source_cache_capture(self):
        module = _load("prepare_us_equibase_archived_race_detail_candidates.py")
        source_url = "https://tvg.equibase.com/static/chart/2000/usa/cd/fixture.pdf"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "fixture.pdf"
            source.write_bytes(b"%PDF-approved")
            identity = {
                "path": source.name,
                "size": source.stat().st_size,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_url": source_url,
                "cached_at": "2026-07-13T00:00:00Z",
                "protected_by": [],
            }
            manifest = root / "source_cache_manifest.json"
            manifest.write_text(
                json.dumps({"schema_version": "1.0", "files": {source.name: identity}}) + "\n",
                encoding="utf-8",
            )

            identities = module._read_source_cache_identities([manifest])
            approved_manifest = {
                "path": manifest.name,
                "size": manifest.stat().st_size,
                "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            }
            event = {
                "source_refs": json.dumps(
                    {
                        "detail_discovery": {
                            "source_cache_manifest_identity": approved_manifest,
                        }
                    }
                )
            }
            self.assertTrue(module._source_cache_manifest_is_approved(event, [manifest]))
            self.assertEqual(
                module._verified_pdf_body(source, source_url=source_url, identities=identities),
                b"%PDF-approved",
            )

            manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
            self.assertFalse(module._source_cache_manifest_is_approved(event, [manifest]))
            source.write_bytes(b"%PDF-replaced")
            with self.assertRaisesRegex(RuntimeError, "differs from date source cache"):
                module._verified_pdf_body(source, source_url=source_url, identities=identities)

    def _write_event(self, root: Path, *, provider: str, url: str, racecourse: str, name: str) -> Path:
        path = root / "events.csv"
        row = {
            "year": "2025",
            "slug": "fixture-2025",
            "status": "finished",
            "local_date": "2025-09-27",
            "racecourse": racecourse,
            "original_name": name,
            "chinese_name": "测试赛事",
            **self._event(provider, url),
        }
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        return path

    def test_sporting_life_main_flow_skips_date_index_when_direct_url_exists(self):
        module = _load("prepare_uk_sportinglife_race_detail_candidates.py")
        url = "https://www.sportinglife.com/racing/results/2025-06-19/royal-ascot/859381/gold-cup-group-1"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_event(root, provider="uk_sportinglife", url=url, racecourse="Ascot", name="Gold Cup")
            args = SimpleNamespace(events_csv=[str(events)], output_dir=str(root / "out"), allow_network=False, limit=0, timeout_seconds=10, sleep_seconds=0, fail_fast=True)
            with patch.object(module, "_download", return_value="fixture") as download, patch.object(
                module,
                "_parse_detail_page",
                return_value=([{"horse_name": "Runner"}], [{"horse_name": "Winner"}], {"race_title": "Gold Cup"}),
            ):
                summary = module.prepare_candidates(args)
        self.assertEqual(summary["events"], 1)
        self.assertEqual(summary["date_pages"], 0)
        self.assertEqual(download.call_args.args[0], url)

    def test_sporting_life_summary_match_uses_annual_calendar_name(self):
        module = _load("prepare_uk_sportinglife_race_detail_candidates.py")
        event = {
            "original_name": "Historical Sponsor H. Stp",
            "racecourse": "Ascot",
            "normalized_grade": "G3",
            "source_refs": json.dumps(
                {"calendar_discovery": {"race_name": "SODEXOLIVEGOLDCUPHANDICAPCHASE"}}
            ),
        }
        races = [
            {
                "course_name": "Ascot",
                "name": "Sodexo Live! Gold Cup Handicap Chase (Premier Handicap)",
                "race_summary_reference": {"id": 123},
            }
        ]

        matched = module._find_race_summary(event, races)

        self.assertEqual(matched["race_summary_reference"]["id"], 123)

    def test_sporting_life_summary_match_uses_reviewed_series_alias(self):
        module = _load("prepare_uk_sportinglife_race_detail_candidates.py")
        event = {
            "slug": "united_kingdom-GBR_ASCOT_HURST_PARK_HANDICAP_CHASE-2025",
            "original_name": "[Byrne Group] H. Stp",
            "racecourse": "Ascot",
            "normalized_grade": "G3",
            "source_refs": json.dumps(
                {"calendar_discovery": {"race_name": "BYRNEGROUPHANDICAPCHASE"}}
            ),
        }
        races = [
            {
                "course_name": "Ascot",
                "name": "Grundon Waste Management Handicap Chase (Premier Handicap) (GBB Race)",
                "race_summary_reference": {"id": 456},
            },
            {
                "course_name": "Ascot",
                "name": "Sodexo Live! Gold Cup Handicap Chase (Premier Handicap) (GBB Race)",
                "race_summary_reference": {"id": 789},
            },
        ]

        matched = module._find_race_summary(event, races)

        self.assertEqual(matched["race_summary_reference"]["id"], 456)

    def test_sporting_life_summary_match_keeps_aintree_bowl_separate_from_hurdle(self):
        module = _load("prepare_uk_sportinglife_race_detail_candidates.py")
        event = {
            "slug": "united_kingdom-united-kingdom-bowl-stp-2025",
            "original_name": "Bowl Stp.[William Hill]",
            "racecourse": "Aintree",
            "normalized_grade": "G1",
            "source_refs": json.dumps(
                {"calendar_discovery": {"race_name": "WILLIAM HILL BOWL"}}
            ),
        }
        races = [
            {
                "course_name": "Aintree",
                "name": "William Hill Aintree Hurdle (Grade 1) (GBB Race)",
                "race_summary_reference": {"id": 850966},
            },
            {
                "course_name": "Aintree",
                "name": "Brooklands Golden Miller Chronograph Bowl Chase (Grade 1) (GBB Race)",
                "race_summary_reference": {"id": 850965},
            },
        ]

        matched = module._find_race_summary(event, races)

        self.assertEqual(matched["race_summary_reference"]["id"], 850965)

    def test_sporting_life_summary_match_uses_distance_for_same_name_races(self):
        module = _load("prepare_uk_sportinglife_race_detail_candidates.py")
        event = {
            "slug": "united_kingdom-GBR_AINTREE_BRIDLE_ROAD_HANDICAP_HURDLE-2024",
            "original_name": "[Village Hotels] H. Hurdle",
            "racecourse": "Aintree",
            "normalized_grade": "G3",
            "distance_text": "3m",
            "source_refs": json.dumps(
                {"calendar_discovery": {"race_name": "WILLIAM HILL HANDICAP"}}
            ),
        }
        races = [
            {
                "course_name": "Aintree",
                "name": "William Hill Handicap Hurdle (Premier Handicap) (GBB Race)",
                "distance": "2m 4f",
                "race_summary_reference": {"id": 789164},
            },
            {
                "course_name": "Aintree",
                "name": "William Hill Handicap Hurdle (Premier Handicap) (GBB Race)",
                "distance": "3m 149y",
                "race_summary_reference": {"id": 789171},
            },
        ]

        matched = module._find_race_summary(event, races)

        self.assertEqual(matched["race_summary_reference"]["id"], 789171)

    def test_sporting_life_reviewed_aliases_cover_batch006_sponsor_names(self):
        module = _load("prepare_uk_sportinglife_race_detail_candidates.py")
        cases = [
            (
                "united_kingdom-GBR_DONCASTER_GREAT_YORKSHIRE_CHASE-2024",
                "[Great Yorkshire] H. Stp",
                "3m",
                "SBK Great Yorkshire Handicap Chase (Premier Handicap) (GBB Race)",
            ),
            (
                "united_kingdom-united-kingdom-darley-2024",
                "Darley S. [Earthlight]",
                "9f",
                "Space Blues Darley Stakes (Group 3)",
            ),
            (
                "united_kingdom-GBR_CHELTENHAM_DECEMBER_3M2F_HANDICAP_CHASE-2024",
                "[The Favourite from The Sun] H. Stp",
                "3m2f",
                "Sonic The Hedgehog 3 Coming Soon Handicap Chase (Premier Handicap) (GBB Race)",
            ),
        ]
        for index, (slug, original_name, distance, source_name) in enumerate(cases, start=1):
            with self.subTest(slug=slug):
                event = {
                    "slug": slug,
                    "original_name": original_name,
                    "racecourse": "Cheltenham" if "CHELTENHAM" in slug else "Doncaster" if "DONCASTER" in slug else "Newmarket",
                    "normalized_grade": "G3",
                    "distance_text": distance,
                    "source_refs": "{}",
                }
                races = [
                    {
                        "course_name": event["racecourse"],
                        "name": source_name,
                        "distance": distance,
                        "race_summary_reference": {"id": index},
                    }
                ]

                matched = module._find_race_summary(event, races)

                self.assertEqual(matched["race_summary_reference"]["id"], index)

    def test_sporting_life_rejects_detail_url_reuse_across_targets(self):
        module = _load("prepare_uk_sportinglife_race_detail_candidates.py")
        claims = {}
        url = "https://www.sportinglife.com/racing/results/2025-04-03/aintree/850966/fixture#video-player"

        module._claim_detail_url(claims, detail_url=url, slug="aintree-hurdle-2025")

        with self.assertRaisesRegex(RuntimeError, "already assigned"):
            module._claim_detail_url(
                claims,
                detail_url=url.removesuffix("#video-player"),
                slug="aintree-bowl-2025",
            )

    def test_hkjc_main_flow_uses_direct_single_race_page(self):
        module = _load("prepare_hkjc_race_detail_candidates.py")
        url = "https://racing.hkjc.com/en-us/local/information/localresults?racedate=2025/05/25&Racecourse=ST&RaceNo=8"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_event(root, provider="hkjc", url=url, racecourse="Sha Tin", name="Champions & Chater Cup")
            args = SimpleNamespace(events_csv=str(events), output_dir=str(root / "out"), allow_network=False, limit=0, timeout_seconds=10, fail_fast=True)
            with patch.object(module, "_download", return_value="fixture") as download, patch.object(
                module,
                "_parse_local_result_page",
                return_value=([{"horse_name": "Runner"}], [{"horse_name": "Winner", "jockey_name": "Jockey"}], {"row_count": 1, "result_count": 1}),
            ):
                summary = module.prepare_candidates(args)
        self.assertEqual(summary["events"], 1)
        self.assertEqual(download.call_count, 1)
        self.assertIn("/zh-hk/local/information/localresults", download.call_args.args[0])

    def test_hrn_main_flow_skips_date_index_when_track_url_is_approved(self):
        module = _load("prepare_us_hrn_race_detail_candidates.py")
        url = "https://entries.horseracingnation.com/entries-results/churchill-downs/2025-09-27"
        parsed = {
            "race_no": "8",
            "race_title": "Race #8",
            "race_meta": "Ack Ack S.",
            "runners": [{"horse_name": "Runner"}],
            "results": [{"horse_name": "Winner"}],
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = self._write_event(root, provider="us_hrn", url=url, racecourse="Churchill Downs", name="Ack Ack S")
            args = SimpleNamespace(events_csv=str(events), output_dir=str(root / "out"), allow_network=False, limit=0, timeout_seconds=10, sleep_seconds=0, fail_fast=True)
            with patch.object(module, "_download", return_value="fixture") as download, patch.object(
                module, "_parse_track_day", return_value=[parsed]
            ):
                summary = module.prepare_candidates(args)
        self.assertEqual(summary["events"], 1)
        self.assertEqual(summary["date_pages"], 0)
        self.assertEqual(download.call_args.args[0], url)

    def test_cached_detail_download_still_rejects_unapproved_host(self):
        module = _load("prepare_uk_sportinglife_race_detail_candidates.py")
        with TemporaryDirectory() as tmp:
            cached = Path(tmp) / "cached.html"
            cached.write_text("cached", encoding="utf-8")
            with self.assertRaises(module.SafeHttpError):
                module._download(
                    "https://attacker.example/racing/results/fixture",
                    cached,
                    allow_network=False,
                    timeout=10,
                    sleep_seconds=0,
                )

    def test_zeturf_download_uses_safe_https_transport(self):
        module = _load("prepare_france_zeturf_race_detail_candidates.py")
        url = "https://www.zeturf.fr/fr/course-du-jour/2012-10-07/R1C6-longchamp-arc"
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "source.html"
            with patch.object(
                module,
                "fetch_https",
                return_value=(b"<html>fixture</html>", {"final_url": url, "redirect_chain": []}),
            ) as fetch, patch.object(module, "before_network_request"):
                text = module._download(
                    url,
                    destination,
                    allow_network=True,
                    timeout=10,
                    sleep_seconds=0,
                )

        self.assertEqual(text, "<html>fixture</html>")
        self.assertEqual(fetch.call_args.kwargs["allowed_hosts"], {"zeturf.fr"})

    def test_zeturf_old_runner_span_is_parsed(self):
        module = _load("prepare_france_zeturf_race_detail_candidates.py")
        html = """
        <title>27/05/2012 - LONGCHAMP - Prix d'Ispahan: Résultats</title>
        <table class="table-runners"><tbody><tr data-runner="1">
          <td class="numero"><span class="partant">1</span></td>
          <td class="cheval"><div class="first-line"><span class="horse-name">PLANTEUR</span></div>
          <div class="second-line"><span class="jockey">Soumillon C.</span> - <span>Botti M.</span></div></td>
          <td class="weight">58 kg</td><td class="corde">3</td><td class="cote"></td>
        </tr></tbody></table>
        """

        runners, results, metadata = module._parse_page(html, source_url="https://www.zeturf.fr/fixture")

        self.assertEqual(results, [])
        self.assertEqual(runners[0]["horse_name"], "PLANTEUR")
        self.assertEqual(runners[0]["jockey_name"], "Soumillon C.")
        self.assertEqual(runners[0]["trainer_name"], "Botti M.")
        self.assertEqual(metadata["date"], "2012-05-27")

    def test_zeturf_criterium_de_saint_cloud_does_not_match_criterium_international(self):
        module = _load("prepare_france_zeturf_race_detail_candidates.py")

        self.assertFalse(module._race_match("Criterium de Saint-Cloud", "Criterium International"))
        self.assertTrue(module._race_match("Criterium de Saint-Cloud", "Critérium de Saint-Cloud"))

    def test_zeturf_event_match_uses_annual_calendar_name(self):
        module = _load("prepare_france_zeturf_race_detail_candidates.py")
        event = {
            "slug": "france-d-indy-hurdle-2025",
            "original_name": "d'Indy Hurdle",
            "source_refs": json.dumps({"calendar_discovery": {"race_name": "D’INDY"}}),
        }

        self.assertTrue(module._race_matches_event(event, "Prix d'Indy"))

    def test_zeturf_event_match_uses_reviewed_series_alias(self):
        module = _load("prepare_france_zeturf_race_detail_candidates.py")
        event = {
            "slug": "france-chantilly-g-p-de-2025",
            "original_name": "Chantilly (G.P. de)",
            "source_refs": "{}",
        }

        self.assertTrue(module._race_matches_event(event, "Grand Prix de Chantilly"))

    def test_zeturf_discovery_stops_scanning_when_date_is_complete(self):
        module = _load("prepare_france_zeturf_race_detail_candidates.py")
        events = [{
            "slug": "france-test-2025",
            "local_date": "2025-01-01",
            "racecourse": "Auteuil",
            "original_name": "Prix Test",
        }]
        html = "<html><title>01/01/2025 - AUTEUIL - Prix Test: Résultats & Rapports</title></html>"
        args = SimpleNamespace(
            max_r=1,
            max_c=3,
            allow_network=False,
            timeout_seconds=10,
            sleep_seconds=0,
        )
        with TemporaryDirectory() as tmp, patch.object(module, "_download", return_value=html) as download:
            matched, skipped = module._discover_event_pages(events, Path(tmp), args)

        self.assertEqual(set(matched), {"france-test-2025"})
        self.assertEqual(skipped, [])
        self.assertEqual(download.call_count, 2)

    def test_zeturf_discovery_keeps_the_url_that_was_actually_cached(self):
        module = _load("prepare_france_zeturf_race_detail_candidates.py")
        events = [
            {
                "slug": "france-other-2025",
                "local_date": "2025-01-01",
                "racecourse": "Auteuil",
                "original_name": "Prix Other",
            },
            {
                "slug": "france-test-2025",
                "local_date": "2025-01-01",
                "racecourse": "Auteuil",
                "original_name": "Prix Test",
            },
        ]
        html = "<html><title>01/01/2025 - AUTEUIL - Prix Test: Résultats & Rapports</title></html>"
        args = SimpleNamespace(
            max_r=1,
            max_c=1,
            allow_network=False,
            timeout_seconds=10,
            sleep_seconds=0,
        )
        with TemporaryDirectory() as tmp, patch.object(module, "_download", return_value=html):
            matched, _skipped = module._discover_event_pages(events, Path(tmp), args)

        self.assertEqual(
            matched["france-test-2025"]["url"],
            "https://www.zeturf.fr/fr/course-du-jour/2025-01-01/R1C1-auteuil-prix-other",
        )

    def test_irishracing_parser_separates_horse_number_draw_and_non_finishers(self):
        module = _load("prepare_irishracing_race_detail_candidates.py")
        html = """
        <title>irishracing.com | Race Result Ascot, Thu, 22nd Jun, 2000, GOLD CUP (GROUP 1)</title>
        <div class="thisrace">GOLD CUP (GROUP 1) 2m. 4f.</div>
        <div class="row runner-line">
          <div class="sn"><strong>1st</strong></div><div class="extdist"><strong></strong></div>
          <div class="runner"><a href="/horse/Kayf-Tara-GB/155500">Kayf Tara (GB)</a>
            <strong>6, b h 9-2</strong><br>(Drawn 6)<p><strong>SP 11/8fav</strong></p>
          </div>
          <div class="trainer"><a>Saeed Bin Suroor</a></div><div class="jockey">M J Kinane</div>
          <div class="racelinks" horseid="155500" sn="5"></div>
        </div>
        <div class="row runner-line">
          <div class="sn"><strong>PU</strong></div><div class="extdist"><strong></strong></div>
          <div class="runner"><a href="/horse/Stopped-Horse-GB/2">Stopped Horse (GB)</a>
            <strong>7, b g 9-2</strong><p><strong>SP 20/1</strong></p>
          </div>
          <div class="trainer">A Trainer</div><div class="jockey">A Jockey</div>
          <div class="racelinks" horseid="2" sn="2"></div>
        </div>
        """

        runners, results, metadata = module._parse_result_page(
            html,
            source_url="https://www.irishracing.com/raceresults/Thu-22nd-Jun-2000/Ascot/1545",
        )

        self.assertEqual([row["horse_number"] for row in runners], ["2", "5"])
        self.assertEqual(runners[1]["barrier"], "6")
        self.assertEqual(runners[1]["horse_name"], "Kayf Tara")
        self.assertEqual(runners[0]["running_status"], "declared")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["finish_position"], 1)
        self.assertEqual(results[0]["horse_number"], "5")
        self.assertEqual(metadata["racecourse"], "Ascot")
        self.assertEqual(metadata["local_date"], "2000-06-22")

    def test_irishracing_candidate_rejects_wrong_race_identity(self):
        module = _load("prepare_irishracing_race_detail_candidates.py")
        metadata = {
            "racecourse": "Ascot",
            "local_date": "2000-06-22",
            "race_title": "Gold Cup (Group 1)",
        }

        self.assertTrue(
            module._page_matches_event(
                {"racecourse": "Royal Ascot", "local_date": "2000-06-22", "original_name": "Gold Cup S"},
                metadata,
            )
        )
        self.assertFalse(
            module._page_matches_event(
                {"racecourse": "Cheltenham", "local_date": "2000-12-09", "original_name": "Bristol Novices Hurdle"},
                metadata,
            )
        )

    def test_irishracing_results_keep_dead_heat_official_positions_without_duplicate_sort_positions(self):
        module = _load("prepare_irishracing_race_detail_candidates.py")
        html = """
        <title>irishracing.com | Race Result Ascot, Thu, 22nd Jun, 2000, GOLD CUP</title>
        <div class="runner-line"><div class="sn">1st</div><div class="extdist"></div>
          <div class="runner"><a href="/horse/One/1">One</a><strong>4, b h 9-0</strong></div>
          <div class="racelinks" sn="1"></div></div>
        <div class="runner-line"><div class="sn">1st</div><div class="extdist">dh</div>
          <div class="runner"><a href="/horse/Two/2">Two</a><strong>4, b h 9-0</strong></div>
          <div class="racelinks" sn="2"></div></div>
        """

        _runners, results, _metadata = module._parse_result_page(
            html, source_url="https://www.irishracing.com/raceresults/Thu-22nd-Jun-2000/Ascot/1545"
        )

        self.assertEqual([row["finish_position"] for row in results], [1, 2])
        self.assertEqual([row["official_finish_position"] for row in results], [1, 1])

    def test_hkjc_parser_supports_legacy_eleven_column_result_rows(self):
        module = _load("prepare_hkjc_race_detail_candidates.py")
        html = """
        <table><tr><td>名次</td><td>馬號</td><td>馬名</td><td>騎師</td><td>練馬師</td>
        <td>實際 負磅</td><td>排位 體重</td><td>檔位</td><td>頭馬 距離</td><td>完成 時間</td><td>獨贏 賠率</td></tr>
        <tr><td>1</td><td>10</td><td>好跑得 (BT012)</td><td>馬佳善</td><td>大衛希斯</td>
        <td>126</td><td>1026</td><td>11</td><td>---</td><td>1:35.40</td><td>4.4</td></tr></table>
        """

        runners, results, metadata = module._parse_local_result_page(
            html,
            source_url="https://racing.hkjc.com/fixture",
            race_no="8",
            race_title_hant="董事盃",
            converter=None,
        )

        self.assertEqual(metadata, {"row_count": 1, "result_count": 1})
        self.assertEqual(runners[0]["horse_name"], "好跑得")
        self.assertEqual(results[0]["finish_time"], "1:35.40")
        self.assertEqual(results[0]["odds_value"], "4.4")

    def test_hrn_name_matching_ignores_square_bracket_sponsor(self):
        module = _load("prepare_us_hrn_race_detail_candidates.py")

        keys = module._event_match_keys("Davona Dale S. [Fasig-Tipton]")

        race_meta = module._norm("Fasig-Tipton Davona Dale S. Fillies")
        self.assertTrue(any(key and key in race_meta for key in keys))

    def test_netkeiba_parser_orders_runners_by_horse_number_and_results_by_finish(self):
        module = _load("prepare_netkeiba_race_detail_candidates.py")
        html = """
        <div class="mainrace_data"><h1>京成杯</h1></div>
        <table class="race_table_01"><tr><th>着順</th></tr>
        <tr><td>1</td><td>7</td><td>11</td><td><a href="/horse/1/">マイネルビンテージ</a></td>
        <td>牡4</td><td>55</td><td><a href="/jockey/result/recent/1/">柴田善臣</a></td><td>2:04.0</td><td></td>
        <td></td><td></td><td></td><td></td><td></td><td>1-1-1-1</td><td>36.6</td><td>4.4</td><td>2</td><td>480(+4)</td>
        <td></td><td></td><td></td><td><a href="/trainer/result/recent/1/">佐々木晶</a></td></tr>
        <tr><td>2</td><td>2</td><td>2</td><td><a href="/horse/2/">イーグルカフェ</a></td>
        <td>牡4</td><td>55</td><td><a href="/jockey/result/recent/2/">岡部幸雄</a></td><td>2:04.0</td><td>アタマ</td>
        <td></td><td></td><td></td><td></td><td></td><td>12-12-11-10</td><td>35.8</td><td>21.3</td><td>9</td><td>464(+6)</td>
        <td></td><td></td><td></td><td><a href="/trainer/result/recent/2/">小島太</a></td></tr></table>
        """

        runners, results, metadata = module.parse_netkeiba_result_page(
            html, source_url="https://db.netkeiba.com/race/200006010611/"
        )

        self.assertEqual([row["horse_number"] for row in runners], ["2", "11"])
        self.assertEqual([row["horse_name"] for row in results], ["マイネルビンテージ", "イーグルカフェ"])
        self.assertEqual(results[0]["finish_position"], 1)
        self.assertEqual(metadata["race_title"], "京成杯")

    def test_netkeiba_source_cache_rejects_changed_file(self):
        module = _load("prepare_netkeiba_race_detail_candidates.py")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "race.html"
            source.write_bytes(b"changed")
            manifest = root / "source_cache_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "files": {
                            "race.html": {
                                "path": "race.html",
                                "size": 8,
                                "sha256": "0" * 64,
                                "source_url": "https://db.netkeiba.com/race/fixture/",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesMessage(RuntimeError, "identity changed"):
                module.read_cached_source(
                    "https://db.netkeiba.com/race/fixture/", manifest_path=manifest
                )

    def test_detail_packager_binds_target_and_cache_identity(self):
        module = _load("package_historical_race_detail_candidates.py")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.html"
            source.write_bytes(b"source")
            source_url = "https://db.netkeiba.com/race/fixture/"
            identity = {
                "path": "source.html",
                "size": source.stat().st_size,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_url": source_url,
            }
            manifest = root / "source_cache_manifest.json"
            manifest.write_text(
                json.dumps({"schema_version": "1.0", "files": {"source.html": identity}}),
                encoding="utf-8",
            )
            events = root / "events.csv"
            with events.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["target_id", "target_sha256", "inventory_artifact_sha256", "year", "slug", "source_refs"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "target_id": 1,
                        "target_sha256": "a" * 64,
                        "inventory_artifact_sha256": "b" * 64,
                        "year": 2000,
                        "slug": "fixture-2000",
                        "source_refs": json.dumps(
                            {
                                "detail_discovery": {
                                    "urls": {
                                        "result_url": {
                                            "url": source_url,
                                            "source_provider": "netkeiba",
                                        }
                                    }
                                }
                            }
                        ),
                    }
                )
            candidates = root / "candidates.jsonl"
            candidates.write_text(
                json.dumps(
                    {
                        "year": 2000,
                        "slug": "fixture-2000",
                        "source_name": "netkeiba",
                        "source_url": source_url,
                        "modules": {
                            "runners": {"items": [{"horse_name": "Runner", "source_refs": {"primary": source_url}}]},
                            "results": {"items": [{"horse_name": "Runner", "finish_position": 1, "source_refs": {"primary": source_url}}]},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = module.package_candidates(
                event_csv_paths=[events],
                candidate_jsonl_paths=[candidates],
                source_cache_manifest_paths=[manifest],
            )

        record = result["records"][0]
        self.assertEqual(record["target_id"], 1)
        self.assertEqual(record["target_sha256"], "a" * 64)
        self.assertTrue(record["modules"]["results"]["is_complete"])
        self.assertEqual(
            record["modules"]["runners"]["items"][0]["source_refs"]["source_cache_identity"],
            identity,
        )

    def test_detail_packager_rejects_source_not_approved_for_event(self):
        module = _load("package_historical_race_detail_candidates.py")
        event = {
            "source_refs": json.dumps(
                {
                    "detail_discovery": {
                        "urls": {
                            "result_url": {
                                "url": "https://db.netkeiba.com/race/approved/",
                                "source_provider": "netkeiba",
                            }
                        }
                    }
                }
            )
        }

        self.assertFalse(
            module.source_matches_event(
                event,
                source_name="netkeiba",
                source_url="https://db.netkeiba.com/race/other/",
            )
        )

    def test_detail_packager_accepts_nar_and_zone_turf_sources_only_when_approved(self):
        module = _load("package_historical_race_detail_candidates.py")
        cases = (
            (
                "keiba_go_jp",
                "nar",
                "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceNo=9",
            ),
            (
                "zone_turf",
                "zone_turf",
                "https://www.zone-turf.fr/cheval/mission-smart-2088796/",
            ),
        )

        for source_name, provider, source_url in cases:
            event = {
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
                )
            }
            with self.subTest(source_name=source_name):
                self.assertTrue(
                    module.source_matches_event(
                        event,
                        source_name=source_name,
                        source_url=source_url,
                    )
                )
                self.assertFalse(
                    module.source_matches_event(
                        event,
                        source_name=source_name,
                        source_url=f"{source_url}different",
                    )
                )

    def test_detail_packager_accepts_hash_approved_supplemental_source(self):
        module = _load("package_historical_race_detail_candidates.py")
        source_url = "https://www.zeturf.fr/fr/course-du-jour/2012-10-07/R1C6-longchamp-fixture"
        event = {
            "source_refs": json.dumps(
                {
                    "detail_discovery": {
                        "urls": {
                            "result_url": {
                                "url": "https://www.france-galop.com/fr/content/fixture",
                                "source_provider": "france_galop",
                            }
                        },
                        "approved_detail_sources": [
                            {
                                "url": source_url,
                                "source_provider": "zeturf",
                                "source_authority": "third_party_high_access",
                                "artifact_manifest_sha256": "a" * 64,
                                "source_cache_identity": {"sha256": "b" * 64},
                            }
                        ],
                    }
                }
            )
        }

        self.assertTrue(
            module.source_matches_event(event, source_name="zeturf", source_url=source_url)
        )

        event["source_refs"] = event["source_refs"].replace("a" * 64, "x" * 64)
        self.assertFalse(
            module.source_matches_event(event, source_name="zeturf", source_url=source_url)
        )

    def test_detail_packager_rejects_supplemental_cache_different_from_approval(self):
        module = _load("package_historical_race_detail_candidates.py")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_url = "https://www.zeturf.fr/fr/course-du-jour/2012-10-07/R1C6-longchamp-fixture"
            source = root / "source.html"
            source.write_bytes(b"new capture")
            actual_identity = {
                "path": source.name,
                "size": source.stat().st_size,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_url": source_url,
            }
            manifest = root / "source_cache_manifest.json"
            manifest.write_text(
                json.dumps({"schema_version": "1.0", "files": {source.name: actual_identity}}),
                encoding="utf-8",
            )
            events = root / "events.csv"
            with events.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["target_id", "target_sha256", "inventory_artifact_sha256", "year", "slug", "source_refs"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "target_id": 1,
                        "target_sha256": "a" * 64,
                        "inventory_artifact_sha256": "b" * 64,
                        "year": 2012,
                        "slug": "fixture-2012",
                        "source_refs": json.dumps(
                            {
                                "detail_discovery": {
                                    "approved_detail_sources": [
                                        {
                                            "url": source_url,
                                            "source_provider": "zeturf",
                                            "artifact_manifest_sha256": "c" * 64,
                                            "source_cache_identity": {
                                                "source_url": source_url,
                                                "size": 10,
                                                "sha256": "d" * 64,
                                            },
                                        }
                                    ]
                                }
                            }
                        ),
                    }
                )
            candidates = root / "candidate.jsonl"
            candidates.write_text(
                json.dumps(
                    {
                        "year": 2012,
                        "slug": "fixture-2012",
                        "source_name": "zeturf",
                        "source_url": source_url,
                        "modules": {
                            "runners": {"items": [{"horse_name": "Runner"}]},
                            "results": {"items": [{"horse_name": "Winner", "finish_position": 1}]},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "differs from approved capture"):
                module.package_candidates(
                    event_csv_paths=[events],
                    candidate_jsonl_paths=[candidates],
                    source_cache_manifest_paths=[manifest],
                )
