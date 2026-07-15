from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import resource
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
RECORDED_AT = "2026-07-15T00:00:00Z"
INVENTORY_SHA = "a" * 64


def _load(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _canonical(payload) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _target(target_id: int, *, region: str, year: int, name: str, course: str, distance: str) -> dict:
    return {
        "target_id": target_id,
        "target_sha256": hashlib.sha256(f"target-{target_id}".encode()).hexdigest(),
        "artifact_sha256": INVENTORY_SHA,
        "inventory_artifact_sha256": INVENTORY_SHA,
        "series_key": f"{region}-series-{target_id}",
        "year": year,
        "country_region": region,
        "original_name": name,
        "chinese_name": f"赛事{target_id}",
        "racecourse": course,
        "normalized_grade": "G1",
        "grade_text": "G1",
        "surface": "turf",
        "distance_text": distance,
        "source_refs": {},
    }


def _write_selection(path: Path, targets: list[dict]) -> None:
    path.write_bytes(
        _canonical(
            {
                "schema_version": "1.0",
                "inventory_manifest_sha256": INVENTORY_SHA,
                "targets": targets,
            }
        )
    )


def _write_catalog(path: Path, sources: list[dict]) -> None:
    path.write_bytes(_canonical({"schema_version": "1.0", "sources": sources}))


def _source(
    source_id: str,
    *,
    region: str,
    year: int,
    adapter: str,
    url: str,
    parser: str,
    content_format: str = "text",
    options: dict | None = None,
) -> dict:
    return {
        "id": source_id,
        "country_region": region,
        "edition_year": year,
        "adapter_key": adapter,
        "url": url,
        "parser": parser,
        "content_format": content_format,
        "source_authority": "official",
        "options": options or {},
    }


def _write_cache_bundle(
    root: Path,
    sources: list[dict],
    bodies: dict[str, bytes | None],
    targets: list[dict],
) -> tuple[Path, Path]:
    files = {}
    ledger = []
    grouped_sources: dict[tuple[str, str], list[dict]] = {}
    for source in sources:
        grouped_sources.setdefault(
            (source["adapter_key"], source["url"]), []
        ).append(source)
    for (_adapter, _url), request_sources in grouped_sources.items():
        source = request_sources[0]
        request_bodies = {
            bodies.get(item["id"])
            for item in request_sources
            if bodies.get(item["id"]) is not None
        }
        if len(request_bodies) > 1:
            raise AssertionError("fixture assigns different bodies to one request URL")
        body = next(iter(request_bodies), None)
        request_scopes = {
            (item["country_region"], item["edition_year"])
            for item in request_sources
        }
        entry = {
            "adapter_key": source["adapter_key"],
            "source_url": source["url"],
            "requested_at": RECORDED_AT,
            "target_references": [
                {
                    "target_id": target["target_id"],
                    "target_sha256": target["target_sha256"],
                    "series_key": target["series_key"],
                    "edition_year": target["year"],
                    "role": "calendar_source",
                }
                for target in targets
                if (target["country_region"], target["year"]) in request_scopes
            ],
        }
        if body is None:
            entry.update(status="failed", error="fixture unavailable")
        else:
            relative = f"{source['adapter_key']}/{source['id']}.bin"
            manifest_relative = f"outputs/cache/{relative}"
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
            identity = {
                "path": manifest_relative,
                "size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "source_url": source["url"],
                "cached_at": RECORDED_AT,
                "protected_by": [],
            }
            files[manifest_relative] = identity
            entry.update(
                status="succeeded",
                source_cache_identity=identity,
                source_cache_relative_path=relative,
            )
        ledger.append(entry)
    manifest = root / "source-cache-manifest.json"
    manifest.write_bytes(
        _canonical(
            {
                "schema_version": "1.0",
                "root": "/original/runner/artifact",
                "total_bytes": sum(item["size"] for item in files.values()),
                "files": files,
            }
        )
    )
    ledger_path = root / "request-ledger.jsonl"
    ledger_path.write_bytes(b"".join(_canonical(row) for row in ledger))
    return manifest, ledger_path


class HistoricalRaceCalendarRequestTests(SimpleTestCase):
    def setUp(self):
        self.tool = _load("build_historical_race_calendar_requests.py")
        self.cache_tool = _load("cache_historical_race_date_sources.py")

    def test_cache_rejects_fractional_provider_identity_before_network(self):
        base = {
            "adapter_key": "france_galop",
            "target_id": 1,
            "target_sha256": "b" * 64,
            "series_key": "france-alpha",
            "edition_year": 2024,
            "urls": {
                "calendar_source": {
                    "url": "https://www.france-galop.com/files/flat-2024.pdf"
                }
            },
        }
        for field, value in (("target_id", 1.5), ("edition_year", 2024.5)):
            with self.subTest(field=field), TemporaryDirectory() as tmp:
                row = {**base, field: value}
                with self.assertRaisesMessage(
                    self.cache_tool.DateSourceCacheError,
                    "provider row target identity is invalid",
                ):
                    self.cache_tool.cache_provider_rows(
                        [row], output_root=Path(tmp), timeout=1
                    )

    def test_catalog_expands_each_source_for_every_target_and_is_deterministic(self):
        targets = [
            _target(1, region="united_kingdom", year=2024, name="Alpha Stakes", course="Ascot", distance="1m"),
            _target(2, region="united_kingdom", year=2024, name="Beta Chase", course="Aintree", distance="2m4f"),
        ]
        sources = [
            _source(
                "bha-flat-2024",
                region="united_kingdom",
                year=2024,
                adapter="uk_bha",
                url="https://www.britishhorseracing.com/files/flat-2024.pdf",
                parser="bha_flat",
            ),
            _source(
                "bha-jump-2024",
                region="united_kingdom",
                year=2024,
                adapter="uk_bha",
                url="https://www.britishhorseracing.com/files/jump-2024.pdf",
                parser="bha_jump",
                options={"season_start_year": 2023},
            ),
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            catalog = root / "catalog.json"
            _write_selection(selection, targets)
            _write_catalog(catalog, sources)
            first = self.tool.build_calendar_requests(
                selection_path=selection,
                catalog_path=catalog,
                output_dir=root / "first",
            )
            _write_catalog(catalog, list(reversed(sources)))
            second = self.tool.build_calendar_requests(
                selection_path=selection,
                catalog_path=catalog,
                output_dir=root / "second",
            )
            first_rows = (root / "first" / "provider_rows.jsonl").read_bytes()
            second_rows = (root / "second" / "provider_rows.jsonl").read_bytes()

        self.assertEqual(first["target_count"], 2)
        self.assertEqual(first["source_count"], 2)
        self.assertEqual(first["provider_row_count"], 4)
        self.assertEqual(first_rows, second_rows)

    def test_missing_mapping_and_unsafe_url_fail_without_publishing(self):
        target = _target(1, region="france", year=2024, name="Prix Alpha", course="Chantilly", distance="1600m")
        cases = (
            [],
            [
                _source(
                    "unsafe",
                    region="france",
                    year=2024,
                    adapter="france_galop",
                    url="http://www.france-galop.com/calendar.pdf",
                    parser="france_flat",
                )
            ],
            [
                _source(
                    "wrong-host",
                    region="france",
                    year=2024,
                    adapter="france_galop",
                    url="https://attacker.example/calendar.pdf",
                    parser="france_flat",
                )
            ],
            [
                _source(
                    "wrong-port",
                    region="france",
                    year=2024,
                    adapter="france_galop",
                    url="https://www.france-galop.com:8443/calendar.pdf",
                    parser="france_flat",
                )
            ],
        )
        for index, sources in enumerate(cases):
            with self.subTest(index=index), TemporaryDirectory() as tmp:
                root = Path(tmp)
                selection = root / "selection.json"
                catalog = root / "catalog.json"
                output = root / "output"
                _write_selection(selection, [target])
                _write_catalog(catalog, sources)
                with self.assertRaises(self.tool.CalendarRequestError):
                    self.tool.build_calendar_requests(
                        selection_path=selection,
                        catalog_path=catalog,
                        output_dir=output,
                    )
                self.assertFalse(output.exists())

    def test_selection_and_catalog_reject_coerced_or_empty_identity(self):
        base_target = _target(
            1,
            region="france",
            year=2024,
            name="Prix Alpha",
            course="Chantilly",
            distance="1600m",
        )
        base_source = _source(
            "france-flat-2024",
            region="france",
            year=2024,
            adapter="france_galop",
            url="https://www.france-galop.com/files/flat-2024.pdf",
            parser="france_flat",
        )
        cases = (
            ({**base_target, "target_id": True}, base_source),
            ({**base_target, "year": 2024.5}, base_source),
            ({**base_target, "series_key": ""}, base_source),
            (base_target, {**base_source, "edition_year": 2024.5}),
        )
        for index, (target, source) in enumerate(cases):
            with self.subTest(index=index), TemporaryDirectory() as tmp:
                root = Path(tmp)
                selection = root / "selection.json"
                catalog = root / "catalog.json"
                output = root / "output"
                _write_selection(selection, [target])
                _write_catalog(catalog, [source])

                with self.assertRaises(self.tool.CalendarRequestError):
                    self.tool.build_calendar_requests(
                        selection_path=selection,
                        catalog_path=catalog,
                        output_dir=output,
                    )

                self.assertFalse(output.exists())

    def test_duplicate_catalog_url_preserves_sources_but_counts_one_request(self):
        target = _target(
            1,
            region="united_kingdom",
            year=2024,
            name="Alpha Stakes",
            course="Ascot",
            distance="1m",
        )
        sources = [
            _source(
                source_id,
                region="united_kingdom",
                year=2024,
                adapter="uk_bha",
                url="https://www.britishhorseracing.com/files/calendar-2024.pdf",
                parser="bha_flat",
            )
            for source_id in ("bha-primary", "bha-mirror-entry")
        ]
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            catalog = root / "catalog.json"
            _write_selection(selection, [target])
            _write_catalog(catalog, sources)
            result = self.tool.build_calendar_requests(
                selection_path=selection,
                catalog_path=catalog,
                output_dir=root / "output",
            )

        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["provider_row_count"], 2)
        self.assertEqual(result["unique_request_count"], 1)

    def test_hkjc_catalog_requires_integer_season_end_year(self):
        target = _target(
            1,
            region="hong_kong",
            year=2016,
            name="January Cup",
            course="Happy Valley",
            distance="1800",
        )
        for options in ({}, {"season_end_year": True}, {"season_end_year": "2016"}):
            with self.subTest(options=options), TemporaryDirectory() as tmp:
                root = Path(tmp)
                selection = root / "selection.json"
                catalog = root / "catalog.json"
                output = root / "output"
                _write_selection(selection, [target])
                _write_catalog(
                    catalog,
                    [
                        _source(
                            "hkjc-pattern-1516",
                            region="hong_kong",
                            year=2016,
                            adapter="hkjc",
                            url="https://racing.hkjc.com/racing/english/international-racing/pdf/1516HKPatternBook.pdf",
                            parser="hkjc_pattern",
                            options=options,
                        )
                    ],
                )

                with self.assertRaisesRegex(
                    self.tool.CalendarRequestError,
                    "HKJC pattern source requires season_end_year",
                ):
                    self.tool.build_calendar_requests(
                        selection_path=selection,
                        catalog_path=catalog,
                        output_dir=output,
                    )

                self.assertFalse(output.exists())

    def test_france_obstacle_catalog_requires_bounded_date_window(self):
        target = _target(
            1,
            region="france",
            year=2024,
            name="Grand Prix de la Ville de Nice",
            course="Cagnes-sur-Mer",
            distance="4600m",
        )
        invalid_options = (
            {},
            {"date_start": "2023-12-03"},
            {"date_start": "bad", "date_end": "2024-02-18"},
            {"date_start": "2024-02-18", "date_end": "2023-12-03"},
            {"date_start": "2022-12-01", "date_end": "2023-02-28"},
        )
        for options in invalid_options:
            with self.subTest(options=options), TemporaryDirectory() as tmp:
                root = Path(tmp)
                selection = root / "selection.json"
                catalog = root / "catalog.json"
                output = root / "output"
                _write_selection(selection, [target])
                _write_catalog(
                    catalog,
                    [
                        _source(
                            "france-obstacle-winter-2024",
                            region="france",
                            year=2024,
                            adapter="france_galop",
                            url="https://www.france-galop.com/files/winter-2024.pdf",
                            parser="france_obstacle",
                            options=options,
                        )
                    ],
                )

                with self.assertRaisesRegex(
                    self.tool.CalendarRequestError,
                    "France obstacle source requires bounded date window",
                ):
                    self.tool.build_calendar_requests(
                        selection_path=selection,
                        catalog_path=catalog,
                        output_dir=output,
                    )

                self.assertFalse(output.exists())

    def test_hkjc_catalog_requires_both_season_books_for_natural_year(self):
        target = _target(
            1,
            region="hong_kong",
            year=2016,
            name="January Cup",
            course="Happy Valley",
            distance="1800",
        )
        source = _source(
            "hkjc-pattern-1516",
            region="hong_kong",
            year=2016,
            adapter="hkjc",
            url="https://racing.hkjc.com/racing/english/international-racing/pdf/1516HKPatternBook.pdf",
            parser="hkjc_pattern",
            options={"season_end_year": 2016},
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            catalog = root / "catalog.json"
            output = root / "output"
            _write_selection(selection, [target])
            _write_catalog(catalog, [source])

            with self.assertRaisesRegex(
                self.tool.CalendarRequestError,
                "must cover both seasons for natural year 2016",
            ):
                self.tool.build_calendar_requests(
                    selection_path=selection,
                    catalog_path=catalog,
                    output_dir=output,
                )

            self.assertFalse(output.exists())


class HistoricalRaceCalendarPrepareTests(SimpleTestCase):
    def setUp(self):
        self.tool = _load("prepare_historical_race_calendar_inputs.py")

    def _prepare(self, root: Path, targets: list[dict], sources: list[dict], bodies: dict[str, bytes | None]):
        selection = root / "selection.json"
        catalog = root / "catalog.json"
        cache = root / "cache"
        cache.mkdir()
        _write_selection(selection, targets)
        _write_catalog(catalog, sources)
        manifest, ledger = _write_cache_bundle(cache, sources, bodies, targets)
        output = root / "output"
        result = self.tool.prepare_calendar_inputs(
            selection_path=selection,
            catalog_path=catalog,
            source_cache_root=cache,
            source_cache_manifest_path=manifest,
            request_ledger_path=ledger,
            country_region=targets[0]["country_region"],
            year=targets[0]["year"],
            recorded_at=RECORDED_AT,
            output_dir=output,
        )
        return result, output, manifest

    def test_bha_calendar_creates_event_without_fabricating_result_provider(self):
        target = _target(1, region="united_kingdom", year=2024, name="Alpha Stakes", course="Ascot", distance="1m")
        source = _source(
            "bha-flat-2024",
            region="united_kingdom",
            year=2024,
            adapter="uk_bha",
            url="https://www.britishhorseracing.com/files/flat-2024.pdf",
            parser="bha_flat",
        )
        body = b'" 1 ASCOT Jun. 15 ALPHA STAKES (P1.)\n'
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(Path(tmp), [target], [source], {source["id"]: body})
            rows = list(csv.DictReader((output / "events_united_kingdom.csv").open(encoding="utf-8-sig")))
            providers = (output / "provider_rows.jsonl").read_text(encoding="utf-8")

        self.assertEqual(result["complete_count"], 1)
        self.assertEqual(result["gap_count"], 0)
        self.assertEqual(rows[0]["local_date"], "2024-06-15")
        self.assertEqual(providers, "")

    def test_global_ledger_supports_shared_url_across_year_shards(self):
        targets = [
            _target(
                1,
                region="france",
                year=2023,
                name="Grand Prix de Pau Stp",
                course="Pau",
                distance="5300",
            ),
            _target(
                2,
                region="france",
                year=2024,
                name="Grand Prix de Pau Stp",
                course="Pau",
                distance="5300",
            ),
            _target(
                3,
                region="united_kingdom",
                year=2024,
                name="Alpha Stakes",
                course="Ascot",
                distance="1m",
            ),
        ]
        targets[0]["series_key"] = "france-grand-prix-de-pau-stp"
        targets[1]["series_key"] = "france-grand-prix-de-pau-stp"
        shared_url = "https://www.france-galop.com/files/obstacle-summary.pdf"
        sources = [
            _source(
                f"france-summary-{year}",
                region="france",
                year=year,
                adapter="france_galop",
                url=shared_url,
                parser="france_obstacle_summary",
            )
            for year in (2023, 2024)
        ]
        sources.append(
            _source(
                "bha-flat-2024",
                region="united_kingdom",
                year=2024,
                adapter="uk_bha",
                url="https://www.britishhorseracing.com/files/flat-2024.pdf",
                parser="bha_flat",
            )
        )
        france_body = b"""
                   3 ans      4 ans      5 et +      4 ans      5 et +
                                                               GD PX DE PAU
                                                                05/02 (Pau)
                                                               [G3] 5300 24
        """
        bodies = {
            "france-summary-2023": france_body,
            "france-summary-2024": france_body,
            "bha-flat-2024": b'" 1 ASCOT Jun. 15 ALPHA STAKES (P1.)\n',
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            catalog = root / "catalog.json"
            cache = root / "cache"
            cache.mkdir()
            _write_selection(selection, targets)
            _write_catalog(catalog, sources)
            manifest, ledger = _write_cache_bundle(
                cache,
                sources,
                bodies,
                targets,
            )
            output = root / "output"
            result = self.tool.prepare_calendar_inputs(
                selection_path=selection,
                catalog_path=catalog,
                source_cache_root=cache,
                source_cache_manifest_path=manifest,
                request_ledger_path=ledger,
                country_region="france",
                year=2023,
                recorded_at=RECORDED_AT,
                output_dir=output,
            )

        self.assertEqual(result["complete_count"], 1)
        self.assertEqual(result["gap_count"], 0)

    def test_jra_pair_creates_event_and_real_result_provider(self):
        target = _target(
            7,
            region="japan",
            year=2025,
            name="Aichi Hai",
            course="Chukyo",
            distance="1400m",
        )
        target["series_key"] = "japan-aichi-hai"
        sources = [
            _source(
                "jra-schedule-2025",
                region="japan",
                year=2025,
                adapter="jra",
                url="https://japanracing.jp/en/racing/schedule/graded/list/2025.html",
                parser="jra_schedule",
                content_format="html",
            ),
            _source(
                "jra-history-2025",
                region="japan",
                year=2025,
                adapter="jra",
                url="https://www.jra.go.jp/datafile/seiseki/replay/2025/jyusyo.html",
                parser="jra_history",
                content_format="html",
            ),
        ]
        schedule = b"""
        <table><tr><th colspan="7"><span>Mar. 23</span><a>AICHI HAI</a></th></tr>
        <tr><td>G3</td><td>CHUKYO</td><td>1,400/Turf</td><td>4yo&amp;up</td><td>38000000</td>
        <td><a href="javascript:doSubmit('2025','0323','07','02','04','11','7')">o</a></td></tr></table>
        """
        history = """
        <table><tr><th>月日</th><th>レース名</th><th>競馬場</th><th>結果</th></tr>
        <tr><td>3月23日 日曜</td><td>愛知杯</td><td>中京</td>
        <td><a href="/datafile/seiseki/replay/2025/033.html">result</a></td></tr></table>
        """.encode("cp932")
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(
                Path(tmp),
                [target],
                sources,
                {sources[0]["id"]: schedule, sources[1]["id"]: history},
            )
            provider = json.loads(
                (output / "provider_rows.jsonl").read_text(encoding="utf-8")
            )
            rows = list(
                csv.DictReader(
                    (output / "events_japan.csv").open(encoding="utf-8-sig")
                )
            )

        self.assertEqual(result["complete_count"], 1)
        self.assertEqual(result["provider_row_count"], 1)
        self.assertEqual(rows[0]["local_date"], "2025-03-23")
        self.assertEqual(
            provider["urls"]["result_url"]["url"],
            "https://www.jra.go.jp/datafile/seiseki/replay/2025/033.html",
        )

    def test_france_calendar_preserves_metric_distance_without_result_provider(self):
        target = _target(
            8,
            region="france",
            year=2025,
            name="DIANE",
            course="Chantilly",
            distance="2100m",
        )
        source = _source(
            "france-flat-2025",
            region="france",
            year=2025,
            adapter="france_galop",
            url="https://www.france-galop.com/files/flat-2025.pdf",
            parser="france_flat",
        )
        body = b"15-06 Chantilly 1,0 M 3 ans F DIANE Groupe I 2 100\n"
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(
                Path(tmp), [target], [source], {source["id"]: body}
            )
            rows = list(
                csv.DictReader(
                    (output / "events_france.csv").open(encoding="utf-8-sig")
                )
            )
            providers = (output / "provider_rows.jsonl").read_text(encoding="utf-8")

        self.assertEqual(result["complete_count"], 1)
        self.assertEqual(rows[0]["distance_text"], "2100m")
        self.assertEqual(providers, "")

    def test_france_flat_program_prepares_aqps_calendar_row(self):
        target = _target(
            10,
            region="france",
            year=2024,
            name="Richard de Gennes(R)",
            course="Craon",
            distance="2400",
        )
        target["series_key"] = "france-richard-de-gennes"
        source = _source(
            "france-flat-program-sep-oct-2024",
            region="france",
            year=2024,
            adapter="france_galop",
            url="https://www.france-galop.com/files/flat-program-sep-oct-2024.pdf",
            parser="france_flat_program",
        )
        body = b"""
        Index
        A.Q.P.S.
        date hip. age sexe titre du prix Information
        1-09 Craon 37 000 3 ans R. DE GENNES 2 400
        Anglo-Arabes
        """
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(
                Path(tmp), [target], [source], {source["id"]: body}
            )
            rows = list(
                csv.DictReader(
                    (output / "events_france.csv").open(encoding="utf-8-sig")
                )
            )

        self.assertEqual(result["complete_count"], 1)
        self.assertEqual(result["gap_count"], 0)
        self.assertEqual(rows[0]["local_date"], "2024-09-01")
        self.assertEqual(rows[0]["distance_text"], "2400m")

    def test_france_obstacle_prepare_filters_cross_year_source_window(self):
        target = _target(
            9,
            region="france",
            year=2024,
            name="THIS YEAR",
            course="Cagnes-sur-Mer",
            distance="4600m",
        )
        source = _source(
            "france-obstacle-winter-2024",
            region="france",
            year=2024,
            adapter="france_galop",
            url="https://www.france-galop.com/files/winter-2024.pdf",
            parser="france_obstacle",
            options={
                "date_start": "2023-12-03",
                "date_end": "2024-02-18",
                "discipline": "jumps",
            },
        )
        body = b"""
        31-12 Cagnes-sur-Mer 154 000 5 & + THIS YEAR Groupe III 4 600
        7-01 Cagnes-sur-Mer 154 000 5 & + THIS YEAR Groupe III 4 600
        """
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(
                Path(tmp), [target], [source], {source["id"]: body}
            )
            rows = list(
                csv.DictReader(
                    (output / "events_france.csv").open(encoding="utf-8-sig")
                )
            )

        self.assertEqual(result["complete_count"], 1)
        self.assertEqual(result["gap_count"], 0)
        self.assertEqual(rows[0]["local_date"], "2024-01-07")
        self.assertEqual(rows[0]["distance_text"], "4600m")

    def test_france_obstacle_group_summary_prepares_missing_group_row(self):
        target = _target(
            11,
            region="france",
            year=2023,
            name="Christian de Tredern Hurdle",
            course="Auteuil",
            distance="3600",
        )
        target["series_key"] = "france-christian-de-tredern-hurdle"
        source = _source(
            "france-obstacle-summary-2023",
            region="france",
            year=2023,
            adapter="france_galop",
            url="https://www.france-galop.com/files/obstacle-summary-2023.pdf",
            parser="france_obstacle_summary",
        )
        body = b"""
                   3 ans      4 ans      5 et +      4 ans      5 et +
                                         TREDERN
                                       17/06 (Auteuil)
                                       [G3] [F] [4-5 ans]
                                         3600 5
        """
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(
                Path(tmp), [target], [source], {source["id"]: body}
            )
            rows = list(
                csv.DictReader(
                    (output / "events_france.csv").open(encoding="utf-8-sig")
                )
            )

        self.assertEqual(result["complete_count"], 1)
        self.assertEqual(result["gap_count"], 0)
        self.assertEqual(rows[0]["local_date"], "2023-06-17")
        self.assertEqual(rows[0]["distance_text"], "3600m")

    def test_hkjc_cross_year_season_keeps_edition_year_and_metric_unit(self):
        target = _target(
            2,
            region="hong_kong",
            year=2017,
            name="January Cup",
            course="Happy Valley",
            distance="1800",
        )
        source = _source(
            "hkjc-pattern-2017",
            region="hong_kong",
            year=2017,
            adapter="hkjc",
            url="https://racing.hkjc.com/racing/content/english/pattern_race/2016-2017.pdf",
            parser="hkjc_pattern",
            options={"season_end_year": 2017},
        )
        companion = _source(
            "hkjc-pattern-2018",
            region="hong_kong",
            year=2017,
            adapter="hkjc",
            url="https://racing.hkjc.com/racing/content/english/pattern_race/2017-2018.pdf",
            parser="hkjc_pattern",
            options={"season_end_year": 2018},
        )
        body = b"WED 11/01/17 January Cup G3 3yo+ 1800\n"
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(
                Path(tmp),
                [target],
                [source, companion],
                {source["id"]: body, companion["id"]: b"WED 10/01/18 January Cup G3 3yo+ 1800\n"},
            )
            rows = list(csv.DictReader((output / "events_hong_kong.csv").open(encoding="utf-8-sig")))

        self.assertEqual(result["complete_count"], 1)
        self.assertEqual(rows[0]["year"], "2017")
        self.assertEqual(rows[0]["local_date"], "2017-01-11")
        self.assertEqual(rows[0]["distance_text"], "1800m")

    def test_hkjc_natural_year_combines_two_season_books_without_leakage(self):
        targets = [
            _target(
                20,
                region="hong_kong",
                year=2016,
                name="January Cup",
                course="Happy Valley",
                distance="1800",
            ),
            _target(
                21,
                region="hong_kong",
                year=2016,
                name="Jockey Club Cup",
                course="Sha Tin",
                distance="2000",
            ),
        ]
        sources = [
            _source(
                "hkjc-pattern-1516",
                region="hong_kong",
                year=2016,
                adapter="hkjc",
                url="https://racing.hkjc.com/racing/english/international-racing/pdf/1516HKPatternBook.pdf",
                parser="hkjc_pattern",
                options={"season_end_year": 2016},
            ),
            _source(
                "hkjc-pattern-1617",
                region="hong_kong",
                year=2016,
                adapter="hkjc",
                url="https://racing.hkjc.com/racing/english/international-racing/pdf/1617HKPatternBook.pdf",
                parser="hkjc_pattern",
                options={"season_end_year": 2017},
            ),
        ]
        bodies = {
            "hkjc-pattern-1516": (
                b"SUN 15/11/15 Jockey Club Cup G2 3yo+ 2000\n"
                b"WED 06/01/16 January Cup G3 3yo+ 1800\n"
            ),
            "hkjc-pattern-1617": (
                b"SUN 20/11/16 Jockey Club Cup G2 3yo+ 2000\n"
                b"WED 11/01/17 January Cup G3 3yo+ 1800\n"
            ),
        }
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(
                Path(tmp), targets, sources, bodies
            )
            rows = list(
                csv.DictReader(
                    (output / "events_hong_kong.csv").open(encoding="utf-8-sig")
                )
            )

        self.assertEqual(result["complete_count"], 2)
        self.assertEqual(
            {(int(row["target_id"]), row["local_date"]) for row in rows},
            {
                (targets[0]["target_id"], "2016-01-06"),
                (targets[1]["target_id"], "2016-11-20"),
            },
        )

    def test_toba_calendar_emits_real_result_provider_and_event(self):
        target = _target(
            3,
            region="united_states",
            year=2025,
            name="Alpha S",
            course="Del Mar",
            distance="8.5f",
        )
        source = _source(
            "toba-2025",
            region="united_states",
            year=2025,
            adapter="toba",
            url="https://toba.org/yearbook/2025.html",
            parser="toba_yearbook",
            content_format="html",
        )
        body = b"""
        <table><tr><th>Stake</th><th>Track</th><th>Winner</th></tr>
        <tr><td>ALPHA S.</td><td>DMR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&amp;TID=DMR&amp;DT=10/31/2025">Alpha</a></td></tr>
        </table>
        """
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(Path(tmp), [target], [source], {source["id"]: body})
            provider = json.loads((output / "provider_rows.jsonl").read_text(encoding="utf-8"))
            rows = list(csv.DictReader((output / "events_united_states.csv").open(encoding="utf-8-sig")))

        self.assertEqual(result["provider_row_count"], 1)
        self.assertEqual(rows[0]["local_date"], "2025-10-31")
        self.assertIn("equibase.com/yearbook/Result.cfm", provider["urls"]["result_url"]["url"])

    def test_conflicting_direct_providers_become_target_gap(self):
        target = _target(
            9,
            region="united_states",
            year=2025,
            name="Alpha S",
            course="Del Mar",
            distance="8.5f",
        )
        sources = [
            _source(
                f"toba-{suffix}",
                region="united_states",
                year=2025,
                adapter="toba",
                url=f"https://toba.org/yearbook/2025-{suffix}.html",
                parser="toba_yearbook",
                content_format="html",
            )
            for suffix in ("primary", "alternate")
        ]
        bodies = {
            source["id"]: f"""
            <table><tr><th>Stake</th><th>Track</th><th>Winner</th></tr>
            <tr><td>ALPHA S.</td><td>DMR</td><td><a href="http://www.equibase.com/premium/eqbPDFChartPlus.cfm?RACE=9&amp;TID=DMR&amp;DT=10/{day}/2025">Alpha</a></td></tr>
            </table>
            """.encode()
            for source, day in zip(sources, (30, 31), strict=True)
        }
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(
                Path(tmp), [target], sources, bodies
            )
            gap = json.loads((output / "gaps.jsonl").read_text(encoding="utf-8"))
            providers = (output / "provider_rows.jsonl").read_text(encoding="utf-8")

        self.assertEqual(result["complete_count"], 0)
        self.assertEqual(result["gap_count"], 1)
        self.assertEqual(gap["reason_code"], "direct_provider_conflict")
        self.assertEqual(providers, "")

    def test_failed_request_becomes_evidence_gap_and_other_target_continues(self):
        targets = [
            _target(4, region="france", year=2024, name="Prix Alpha", course="Chantilly", distance="1600m"),
            _target(5, region="france", year=2024, name="Prix Beta", course="Chantilly", distance="1800m"),
        ]
        source = _source(
            "france-flat-2024",
            region="france",
            year=2024,
            adapter="france_galop",
            url="https://www.france-galop.com/files/flat-2024.pdf",
            parser="france_flat",
        )
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(Path(tmp), targets, [source], {source["id"]: None})
            gaps = [json.loads(line) for line in (output / "gaps.jsonl").read_text(encoding="utf-8").splitlines()]

        self.assertEqual(result["complete_count"], 0)
        self.assertEqual(result["gap_count"], 2)
        self.assertEqual({gap["reason_code"] for gap in gaps}, {"source_request_failed"})
        self.assertTrue(all(gap["evidence_identity"]["sha256"] for gap in gaps))

    def test_partial_source_failure_keeps_successful_target_complete(self):
        targets = [
            _target(
                13,
                region="united_kingdom",
                year=2024,
                name="Beta Stakes",
                course="Ascot",
                distance="1m",
            ),
            _target(
                14,
                region="united_kingdom",
                year=2024,
                name="Alpha Chase",
                course="Aintree",
                distance="2m4f",
            ),
        ]
        sources = [
            _source(
                "bha-flat-2024",
                region="united_kingdom",
                year=2024,
                adapter="uk_bha",
                url="https://www.britishhorseracing.com/files/flat-2024.pdf",
                parser="bha_flat",
            ),
            _source(
                "bha-jump-2024",
                region="united_kingdom",
                year=2024,
                adapter="uk_bha",
                url="https://www.britishhorseracing.com/files/jump-2024.pdf",
                parser="bha_jump",
                options={"season_start_year": 2023},
            ),
        ]
        with TemporaryDirectory() as tmp:
            result, output, _manifest = self._prepare(
                Path(tmp),
                targets,
                sources,
                {
                    sources[0]["id"]: None,
                    sources[1]["id"]: b"Apr. 4 Aintree AlphaChase 2m4f Prem 75,000\n",
                },
            )
            gap = json.loads((output / "gaps.jsonl").read_text(encoding="utf-8"))
            rows = list(
                csv.DictReader(
                    (output / "events_united_kingdom.csv").open(
                        encoding="utf-8-sig"
                    )
                )
            )

        self.assertEqual(result["complete_count"], 1)
        self.assertEqual(result["gap_count"], 1)
        self.assertEqual(rows[0]["target_id"], "14")
        self.assertEqual(gap["target_id"], 13)
        self.assertEqual(gap["reason_code"], "source_request_failed")

    def test_cache_identity_drift_fails_closed_without_output(self):
        target = _target(6, region="france", year=2024, name="Prix Alpha", course="Chantilly", distance="1600m")
        source = _source(
            "france-flat-2024",
            region="france",
            year=2024,
            adapter="france_galop",
            url="https://www.france-galop.com/files/flat-2024.pdf",
            parser="france_flat",
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            catalog = root / "catalog.json"
            cache = root / "cache"
            cache.mkdir()
            _write_selection(selection, [target])
            _write_catalog(catalog, [source])
            manifest, ledger = _write_cache_bundle(cache, [source], {source["id"]: b"valid"}, [target])
            cached = next(path for path in cache.rglob("*.bin"))
            cached.write_bytes(b"changed")
            output = root / "output"

            with self.assertRaises(self.tool.CalendarPrepareError):
                self.tool.prepare_calendar_inputs(
                    selection_path=selection,
                    catalog_path=catalog,
                    source_cache_root=cache,
                    source_cache_manifest_path=manifest,
                    request_ledger_path=ledger,
                    country_region="france",
                    year=2024,
                    recorded_at=RECORDED_AT,
                    output_dir=output,
                )
            self.assertFalse(output.exists())


class HistoricalRaceCalendarAdditionalTests(SimpleTestCase):
    def setUp(self):
        self.tool = _load("prepare_historical_race_calendar_inputs.py")

    @unittest.skipUnless(
        os.environ.get("RUN_HISTORICAL_PIPELINE_PERF") == "1",
        "set RUN_HISTORICAL_PIPELINE_PERF=1 for the 1250-target calendar contract",
    )
    def test_ten_annual_sources_and_1250_targets_stay_within_contract(self):
        years = range(2016, 2026)
        targets = []
        sources = []
        bodies = {}
        target_id = 1
        for year in years:
            source = _source(
                f"france-flat-{year}",
                region="france",
                year=year,
                adapter="france_galop",
                url=f"https://www.france-galop.com/sites/default/files/{year}/flat-{year}.pdf",
                parser="france_flat",
            )
            sources.append(source)
            lines = []
            for index in range(125):
                race_name = f"RACE {year} {index:03d}"
                targets.append(
                    _target(
                        target_id,
                        region="france",
                        year=year,
                        name=race_name,
                        course="Chantilly",
                        distance="1600m",
                    )
                )
                day = (index % 28) + 1
                month = (index % 12) + 1
                lines.append(
                    f"{day:02d}-{month:02d} Chantilly 1,0 M 3 ans {race_name} Groupe III 1 600"
                )
                target_id += 1
            bodies[source["id"]] = ("\n".join(lines) + "\n").encode()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            started = time.monotonic()
            complete_count = 0
            for year in years:
                year_targets = [target for target in targets if target["year"] == year]
                year_sources = [source for source in sources if source["edition_year"] == year]
                selection = root / f"selection-{year}.json"
                catalog = root / f"catalog-{year}.json"
                _write_selection(selection, year_targets)
                _write_catalog(catalog, year_sources)
                cache = root / f"cache-{year}"
                cache.mkdir()
                manifest, ledger = _write_cache_bundle(
                    cache, year_sources, bodies, year_targets
                )
                result = self.tool.prepare_calendar_inputs(
                    selection_path=selection,
                    catalog_path=catalog,
                    source_cache_root=cache,
                    source_cache_manifest_path=manifest,
                    request_ledger_path=ledger,
                    country_region="france",
                    year=year,
                    recorded_at=RECORDED_AT,
                    output_dir=root / f"output-{year}",
                )
                complete_count += result["complete_count"]
            elapsed = time.monotonic() - started
            rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        self.assertEqual(complete_count, 1250)
        self.assertLessEqual(elapsed, 30)
        self.assertLessEqual((rss_after - rss_before) * 1024, 256 * 1024 * 1024)


    def test_extra_request_ledger_row_fails_closed(self):
        target = _target(
            10,
            region="france",
            year=2024,
            name="Prix Alpha",
            course="Chantilly",
            distance="1600m",
        )
        source = _source(
            "france-flat-2024",
            region="france",
            year=2024,
            adapter="france_galop",
            url="https://www.france-galop.com/files/flat-2024.pdf",
            parser="france_flat",
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            catalog = root / "catalog.json"
            cache = root / "cache"
            cache.mkdir()
            _write_selection(selection, [target])
            _write_catalog(catalog, [source])
            manifest, ledger = _write_cache_bundle(
                cache, [source], {source["id"]: b"valid"}, [target]
            )
            with ledger.open("ab") as handle:
                handle.write(
                    _canonical(
                        {
                            "adapter_key": "france_galop",
                            "source_url": "https://www.france-galop.com/files/extra.pdf",
                            "status": "failed",
                            "target_references": [
                                {"target_id": target["target_id"]}
                            ],
                        }
                    )
                )
            output = root / "output"
            with self.assertRaises(self.tool.CalendarPrepareError):
                self.tool.prepare_calendar_inputs(
                    selection_path=selection,
                    catalog_path=catalog,
                    source_cache_root=cache,
                    source_cache_manifest_path=manifest,
                    request_ledger_path=ledger,
                    country_region="france",
                    year=2024,
                    recorded_at=RECORDED_AT,
                    output_dir=output,
                )
            self.assertFalse(output.exists())


    def test_request_ledger_target_sha_drift_fails_closed(self):
        target = _target(
            12,
            region="france",
            year=2024,
            name="Prix Alpha",
            course="Chantilly",
            distance="1600m",
        )
        source = _source(
            "france-flat-2024",
            region="france",
            year=2024,
            adapter="france_galop",
            url="https://www.france-galop.com/files/flat-2024.pdf",
            parser="france_flat",
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            catalog = root / "catalog.json"
            cache = root / "cache"
            cache.mkdir()
            _write_selection(selection, [target])
            _write_catalog(catalog, [source])
            manifest, ledger = _write_cache_bundle(
                cache, [source], {source["id"]: b"valid"}, [target]
            )
            ledger_row = json.loads(ledger.read_text(encoding="utf-8"))
            ledger_row["target_references"][0]["target_sha256"] = "f" * 64
            ledger.write_bytes(_canonical(ledger_row))
            output = root / "output"
            with self.assertRaisesMessage(
                self.tool.CalendarPrepareError, "complete parser scope"
            ):
                self.tool.prepare_calendar_inputs(
                    selection_path=selection,
                    catalog_path=catalog,
                    source_cache_root=cache,
                    source_cache_manifest_path=manifest,
                    request_ledger_path=ledger,
                    country_region="france",
                    year=2024,
                    recorded_at=RECORDED_AT,
                    output_dir=output,
                )
            self.assertFalse(output.exists())

    def test_request_ledger_fractional_identity_fails_closed(self):
        target = _target(
            12,
            region="france",
            year=2024,
            name="Prix Alpha",
            course="Chantilly",
            distance="1600m",
        )
        source = _source(
            "france-flat-2024",
            region="france",
            year=2024,
            adapter="france_galop",
            url="https://www.france-galop.com/files/flat-2024.pdf",
            parser="france_flat",
        )
        for field, value in (("target_id", 12.5), ("edition_year", 2024.5)):
            with self.subTest(field=field), TemporaryDirectory() as tmp:
                root = Path(tmp)
                selection = root / "selection.json"
                catalog = root / "catalog.json"
                cache = root / "cache"
                cache.mkdir()
                _write_selection(selection, [target])
                _write_catalog(catalog, [source])
                manifest, ledger = _write_cache_bundle(
                    cache, [source], {source["id"]: b"valid"}, [target]
                )
                ledger_row = json.loads(ledger.read_text(encoding="utf-8"))
                ledger_row["target_references"][0][field] = value
                ledger.write_bytes(_canonical(ledger_row))
                with self.assertRaisesMessage(
                    self.tool.CalendarPrepareError,
                    "request ledger target references are invalid",
                ):
                    self.tool.prepare_calendar_inputs(
                        selection_path=selection,
                        catalog_path=catalog,
                        source_cache_root=cache,
                        source_cache_manifest_path=manifest,
                        request_ledger_path=ledger,
                        country_region="france",
                        year=2024,
                        recorded_at=RECORDED_AT,
                        output_dir=root / "output",
                    )

    def test_symlinked_cache_root_fails_closed(self):
        target = _target(
            11,
            region="france",
            year=2024,
            name="Prix Alpha",
            course="Chantilly",
            distance="1600m",
        )
        source = _source(
            "france-flat-2024",
            region="france",
            year=2024,
            adapter="france_galop",
            url="https://www.france-galop.com/files/flat-2024.pdf",
            parser="france_flat",
        )
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection = root / "selection.json"
            catalog = root / "catalog.json"
            cache = root / "cache"
            cache.mkdir()
            _write_selection(selection, [target])
            _write_catalog(catalog, [source])
            manifest, ledger = _write_cache_bundle(
                cache, [source], {source["id"]: b"valid"}, [target]
            )
            linked_cache = root / "linked-cache"
            linked_cache.symlink_to(cache, target_is_directory=True)
            output = root / "output"
            with self.assertRaisesMessage(
                self.tool.CalendarPrepareError, "cache root"
            ):
                self.tool.prepare_calendar_inputs(
                    selection_path=selection,
                    catalog_path=catalog,
                    source_cache_root=linked_cache,
                    source_cache_manifest_path=manifest,
                    request_ledger_path=ledger,
                    country_region="france",
                    year=2024,
                    recorded_at=RECORDED_AT,
                    output_dir=output,
                )
            self.assertFalse(output.exists())
