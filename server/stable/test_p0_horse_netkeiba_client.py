"""Tests for the netkeiba horse client (add-netkeiba-horse-client)."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase

from stable.models import RacingRegion
from stable.services import p0_horse_completion_adapters as completion
from stable.services import p0_horse_completion_source_clients as source_clients

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "p0_horse_completion"
HORSE_HTML = (FIXTURE_ROOT / "netkeiba_horse_2022110137.html").read_text(encoding="utf-8")
RESULT_HTML = (FIXTURE_ROOT / "netkeiba_result_2022110137.html").read_text(encoding="utf-8")
PED_HTML = (FIXTURE_ROOT / "netkeiba_ped_2022110137.html").read_text(encoding="utf-8")


@dataclass(frozen=True)
class StubResponse:
    text: str
    status_code: int = 200
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


class FixtureTransport:
    def __init__(self, *, profile=HORSE_HTML, result=RESULT_HTML, pedigree=PED_HTML):
        self.pages = {
            "/horse/result/": result,
            "/horse/ped/": pedigree,
            "/horse/": profile,
        }
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> StubResponse:
        self.calls.append(url)
        for marker, text in sorted(self.pages.items(), key=lambda item: -len(item[0])):
            if marker in url:
                return StubResponse(text=text, url=url)
        raise AssertionError(f"unexpected transport request: {url}")


def _request(**overrides) -> completion.P0HorseCompletionRequest:
    defaults: dict[str, Any] = {
        "candidate_key": "profile:1",
        "region": RacingRegion.JAPAN,
        "horse_name": "ドラゴンウェルズ",
        "source_url": "https://db.netkeiba.com/horse/2022110137/",
        "external_horse_id": "2022110137",
        "candidate_source_name": "netkeiba",
        "expected_sire_name": "",
        "expected_dam_name": "",
        "expected_birth_year": None,
        "cache_path": "",
        "allow_network": True,
        "request_interval_seconds": 0,
        "request_budget": 4,
        "batch_limit": 10,
    }
    defaults.update(overrides)
    return completion.P0HorseCompletionRequest(**defaults)


def _fetch(transport=None, **overrides):
    client = source_clients._NetkeibaClient(transport or FixtureTransport())
    return client.fetch_source_payload(_request(**overrides))


class NetkeibaEncodingTests(SimpleTestCase):
    def test_euc_jp_content_decoded_when_charset_missing(self):
        """netkeiba serves EUC-JP without charset; .text would be mojibake."""

        @dataclass(frozen=True)
        class ByteResponse:
            content: bytes
            text: str
            status_code: int = 200
            url: str = ""
            headers: dict = field(default_factory=dict)

        class ByteTransport:
            def get(self, url, **kwargs):
                if "/horse/result/" in url:
                    return ByteResponse(
                        content=RESULT_HTML.encode("euc-jp"),
                        text=RESULT_HTML.encode("euc-jp").decode("latin-1"),
                        url=url,
                    )
                if "/horse/ped/" in url:
                    return ByteResponse(
                        content=PED_HTML.encode("euc-jp"),
                        text=PED_HTML.encode("euc-jp").decode("latin-1"),
                        url=url,
                    )
                return ByteResponse(
                    content=HORSE_HTML.encode("euc-jp"),
                    text=HORSE_HTML.encode("euc-jp").decode("latin-1"),
                    url=url,
                )

        payload = _fetch(ByteTransport())
        self.assertEqual(payload["identity"]["horse_name"], "ドラゴンウェルズ")
        self.assertEqual(payload["basic_profile"]["color"], "芦毛")
        self.assertEqual(len(payload["career"]["records"]), 13)


class NetkeibaCacheGuardTests(SimpleTestCase):
    def _cache_payload(self, source_name: str) -> dict:
        payload = json.loads(
            (FIXTURE_ROOT / "japan_netkeiba.json").read_text(encoding="utf-8")
        )
        payload["source"]["name"] = source_name
        return payload

    def _current_netkeiba_cache_payload(self) -> dict:
        payload = self._cache_payload("netkeiba")
        payload["source"]["parser_version"] = source_clients.NETKEIBA_PARSER_VERSION
        return payload

    def test_cross_source_cache_treated_as_miss(self):
        import tempfile

        from stable.services import p0_horse_completion_adapters as adapters

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "cache.json"
            cache_path.write_text(
                json.dumps(self._cache_payload("jbis"), ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(completion.P0HorseCompletionNetworkDisabled):
                completion.run_p0_horse_completion_adapter(
                    _request(cache_path=str(cache_path), allow_network=False),
                    source_client=None,
                )

    def test_matching_source_cache_served(self):
        import tempfile

        from stable.services import p0_horse_completion_adapters as adapters

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "cache.json"
            cache_path.write_text(
                json.dumps(self._current_netkeiba_cache_payload(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = completion.run_p0_horse_completion_adapter(
                _request(cache_path=str(cache_path), allow_network=False),
                source_client=None,
            )
            self.assertTrue(result["retrieval"]["cache_hit"])

    def test_legacy_or_wrong_netkeiba_parser_version_is_cache_miss(self):
        import tempfile

        for parser_version in (None, "netkeiba-parser.invalid"):
            with (
                self.subTest(parser_version=parser_version),
                tempfile.TemporaryDirectory() as tmp,
            ):
                payload = self._cache_payload("netkeiba")
                if parser_version is None:
                    payload["source"].pop("parser_version", None)
                else:
                    payload["source"]["parser_version"] = parser_version
                cache_path = Path(tmp) / "cache.json"
                cache_path.write_text(
                    json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                )
                with self.assertRaises(completion.P0HorseCompletionNetworkDisabled):
                    completion.run_p0_horse_completion_adapter(
                        _request(cache_path=str(cache_path), allow_network=False),
                        source_client=None,
                    )

    def test_stale_cache_is_atomically_replaced_by_current_network_payload(self):
        import tempfile

        stale_payload = self._cache_payload("netkeiba")
        stale_payload["source"]["parser_version"] = "netkeiba-parser.old"
        stale_payload["basic_profile"]["owner_name"] = "旧缓存马主"
        current_payload = self._current_netkeiba_cache_payload()
        current_payload["basic_profile"]["owner_name"] = "新抓取马主"

        class CurrentPayloadClient:
            last_request_count = 3

            def fetch_source_payload(self, request):
                return deepcopy(current_payload)

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "cache.json"
            cache_path.write_text(
                json.dumps(stale_payload, ensure_ascii=False), encoding="utf-8"
            )
            result = completion.run_p0_horse_completion_adapter(
                _request(cache_path=str(cache_path), allow_network=True),
                source_client=CurrentPayloadClient(),
            )
            persisted = json.loads(cache_path.read_text(encoding="utf-8"))
            temporary_files = list(Path(tmp).glob(".*.tmp"))

        self.assertFalse(result["retrieval"]["cache_hit"])
        self.assertEqual(result["basic_profile"]["owner_name"], "新抓取马主")
        self.assertEqual(persisted["basic_profile"]["owner_name"], "新抓取马主")
        self.assertEqual(
            persisted["source"]["parser_version"],
            source_clients.NETKEIBA_PARSER_VERSION,
        )
        self.assertEqual(temporary_files, [])

    def test_concurrent_stale_replacement_returns_one_current_canonical_payload(self):
        import tempfile

        stale_payload = self._cache_payload("netkeiba")
        stale_payload["source"]["parser_version"] = "netkeiba-parser.old"
        payloads = []
        for owner in ("并发马主 A", "并发马主 B"):
            payload = self._current_netkeiba_cache_payload()
            payload["basic_profile"]["owner_name"] = owner
            payloads.append(payload)

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "cache.json"
            cache_path.write_text(
                json.dumps(stale_payload, ensure_ascii=False), encoding="utf-8"
            )
            barrier = threading.Barrier(2)

            class BarrierPayloadClient:
                last_request_count = 3

                def __init__(self, payload):
                    self.payload = payload

                def fetch_source_payload(self, request):
                    barrier.wait(timeout=10)
                    return deepcopy(self.payload)

            request = _request(cache_path=str(cache_path), allow_network=True)
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        completion.run_p0_horse_completion_adapter,
                        request,
                        source_client=BarrierPayloadClient(payload),
                    )
                    for payload in payloads
                ]
                results = [future.result(timeout=10) for future in futures]
            persisted = json.loads(cache_path.read_text(encoding="utf-8"))
            temporary_files = list(Path(tmp).glob(".*.tmp"))

        persisted_owner = persisted["basic_profile"]["owner_name"]
        self.assertEqual(
            [result["basic_profile"]["owner_name"] for result in results],
            [persisted_owner, persisted_owner],
        )
        self.assertEqual(
            persisted["source"]["parser_version"],
            source_clients.NETKEIBA_PARSER_VERSION,
        )
        self.assertEqual(temporary_files, [])

    def test_parser_guard_does_not_change_jbis_or_other_region_cache(self):
        import tempfile

        payloads = [
            self._cache_payload("jbis"),
            json.loads(
                (FIXTURE_ROOT / "united_kingdom.json").read_text(encoding="utf-8")
            ),
        ]
        for payload in payloads:
            source = payload["source"]
            identity = payload["identity"]
            request = _request(
                region=payload["region"],
                candidate_source_name=source["name"],
                external_horse_id=source["external_horse_id"],
                horse_name=identity["horse_name"],
                expected_sire_name=identity["sire_name"],
                expected_dam_name=identity["dam_name"],
                expected_birth_year=identity["birth_year"],
            )
            with (
                self.subTest(region=request.region),
                tempfile.TemporaryDirectory() as tmp,
            ):
                cache_path = Path(tmp) / "cache.json"
                cache_path.write_text(json.dumps(payload), encoding="utf-8")
                result = completion.run_p0_horse_completion_adapter(
                    completion.P0HorseCompletionRequest(
                        **{
                            **request.__dict__,
                            "cache_path": str(cache_path),
                            "allow_network": False,
                        }
                    ),
                    source_client=None,
                )
                self.assertTrue(result["retrieval"]["cache_hit"])


class NetkeibaClientHappyPathTests(SimpleTestCase):
    def test_full_payload_validates(self):
        payload = _fetch()
        validated = source_clients.validate_p0_horse_source_cache(payload)
        self.assertEqual(validated["source"]["name"], "netkeiba")
        self.assertEqual(validated["source"]["external_horse_id"], "2022110137")
        self.assertEqual(
            validated["source"]["parser_version"],
            source_clients.NETKEIBA_PARSER_VERSION,
        )
        self.assertEqual(
            validated["identity"],
            {
                "horse_name": "ドラゴンウェルズ",
                "sire_name": "Frosted",
                "dam_name": "Little Dipper",
                "birth_year": 2022,
            },
        )
        basic = validated["basic_profile"]
        self.assertEqual(basic["country"], "美国")
        self.assertEqual(basic["sex"], "牡")
        self.assertEqual(basic["color"], "芦毛")
        self.assertEqual(basic["birth_date"], "2022-03-26")
        self.assertEqual(basic["owner_name"], "窪田芳郎")
        self.assertEqual(basic["trainer_name"], "藤原英昭")
        self.assertEqual(basic["breeder_name"], "Willow Oaks Stable LLC")
        pedigree = validated["pedigree"]
        self.assertEqual(pedigree["sire"], "Frosted")
        self.assertEqual(pedigree["sire_sire"], "Tapit")
        self.assertEqual(pedigree["sire_dam"], "Fast Cookie")
        self.assertEqual(pedigree["dam"], "Little Dipper")
        self.assertEqual(pedigree["dam_sire"], "エスケンデレヤ")
        self.assertEqual(pedigree["dam_dam"], "Eternal Grace")
        self.assertEqual(
            validated["aliases"],
            [
                {"name": "ドラゴンウェルズ", "language": "ja", "is_original": True},
                {"name": "Dragon Welds", "language": "en", "is_original": False},
            ],
        )

    def test_career_records_and_count_reconcile(self):
        payload = _fetch()
        career = payload["career"]
        self.assertEqual(career["source_start_count"], 13)
        self.assertEqual(len(career["records"]), 13)
        first = career["records"][0]
        self.assertEqual(first["race_date"], "2026-04-15")
        self.assertEqual(first["racecourse"], "大井")
        self.assertEqual(first["race_name"], "東京スプリント競走(JpnIII)")
        self.assertEqual(first["finish"], "1")
        self.assertEqual(first["distance_text"], "ダ1200")
        self.assertEqual(first["jockey_name"], "戸崎圭太")
        self.assertEqual(first["finish_time"], "1:10.7")
        self.assertFalse(first["is_overseas"])
        self.assertTrue(first["source_url"].startswith("https://db.netkeiba.com/race/"))
        self.assertNotIn("career_count_mismatch", payload["raw_payload"])

    def test_fetches_three_pages_in_order(self):
        transport = FixtureTransport()
        _fetch(transport)
        self.assertEqual(len(transport.calls), 3)
        self.assertIn("/horse/2022110137/", transport.calls[0])
        self.assertIn("/horse/result/2022110137/", transport.calls[1])
        self.assertIn("/horse/ped/2022110137/", transport.calls[2])

    def test_country_suffix_stripped_from_page_name(self):
        profile = HORSE_HTML.replace(
            "<h1>ドラゴンウェルズ</h1>", "<h1>ドラゴンウェルズ(USA)</h1>"
        )
        payload = _fetch(FixtureTransport(profile=profile))
        self.assertEqual(payload["identity"]["horse_name"], "ドラゴンウェルズ")


class NetkeibaClientFailClosedTests(SimpleTestCase):
    def test_non_netkeiba_candidate_rejected(self):
        with self.assertRaises(source_clients.P0HorseSourceBlocked):
            _fetch(candidate_source_name="jbis")

    def test_non_digit_id_rejected(self):
        with self.assertRaises(source_clients.P0HorseSourceBlocked):
            _fetch(external_horse_id="jp-001")

    def test_missing_profile_table_blocked(self):
        with self.assertRaises(source_clients.P0HorseSourceBlocked):
            _fetch(FixtureTransport(profile=RESULT_HTML))

    def test_missing_pedigree_table_blocked(self):
        with self.assertRaises(source_clients.P0HorseSourceBlocked):
            _fetch(FixtureTransport(pedigree=HORSE_HTML))

    def test_missing_result_table_blocked(self):
        with self.assertRaises(source_clients.P0HorseSourceBlocked):
            _fetch(FixtureTransport(result=HORSE_HTML))

    def test_count_mismatch_surfaces_for_adapter_gap(self):
        profile = HORSE_HTML.replace("13戦6勝", "14戦6勝")
        payload = _fetch(FixtureTransport(profile=profile))
        # the adapter reconciles official count vs record rows into an
        # explicit career gap; the client reports both numbers faithfully
        self.assertEqual(payload["career"]["source_start_count"], 14)
        self.assertEqual(len(payload["career"]["records"]), 13)


class NetkeibaRecordSemanticsTests(SimpleTestCase):
    def _record_row(self, venue: str, finish: str) -> str:
        cells = [
            "2026/04/15", venue, "晴", "11", "テスト戦", "", "14", "1", "1",
            "4.0", "2", finish, "騎手太郎", "56", "ダ1200", "", "良", "-9",
            "1:10.7", "-0.2",
        ]
        return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"

    def _payload_with_row(self, venue: str, finish: str):
        html = RESULT_HTML.replace("</table>", self._record_row(venue, finish) + "</table>", 1)
        return _fetch(FixtureTransport(result=html))

    def test_overseas_row_flagged(self):
        payload = self._payload_with_row("ドーヴィル", "1")
        self.assertTrue(payload["career"]["records"][-1]["is_overseas"])

    def test_nar_venue_with_numeric_prefix_not_overseas(self):
        payload = self._payload_with_row("2大井8", "1")
        self.assertFalse(payload["career"]["records"][-1]["is_overseas"])

    def test_obstacle_distance_preserved_raw(self):
        payload = self._payload_with_row("3中山1", "1")
        record = payload["career"]["records"][-1]
        self.assertEqual(record["racecourse"], "3中山1")
        html = RESULT_HTML.replace(
            "</table>", self._record_row("3中山1", "1").replace("ダ1200", "障2850") + "</table>", 1
        )
        payload = _fetch(FixtureTransport(result=html))
        self.assertEqual(payload["career"]["records"][-1]["distance_text"], "障2850")

    def test_status_mapping_and_nonstart_exclusion(self):
        cases = {
            "取": "scratched",
            "除": "withdrawn",
            "中": "did_not_finish",
            "失": "disqualified",
        }
        html = RESULT_HTML
        for finish in cases:
            html = html.replace(
                "</table>", self._record_row("大井", finish) + "</table>", 1
            )
        payload = _fetch(FixtureTransport(result=html))
        records = payload["career"]["records"]
        self.assertEqual(
            [record["result_status"] for record in records[-4:]],
            ["scratched", "withdrawn", "did_not_finish", "disqualified"],
        )

    def test_deleted_title_status_is_parsed_independently(self):
        profile = HORSE_HTML.replace("現役　牡4歳　芦毛", "抹消　牡　黒鹿毛")
        payload = _fetch(FixtureTransport(profile=profile))
        self.assertEqual(payload["basic_profile"]["sex"], "牡")
        self.assertEqual(payload["basic_profile"]["color"], "黒鹿毛")

    def test_unknown_title_status_still_blocks(self):
        profile = HORSE_HTML.replace("現役　牡4歳　芦毛", "不明　牡　黒鹿毛")
        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked, "title_status"
        ):
            _fetch(FixtureTransport(profile=profile))

    def test_uncertain_mizusawa_row_remains_partial_career_blocker(self):
        import tempfile

        row = self._record_row("水沢", "").replace(
            "2026/04/15", "2025/03/17"
        ).replace("テスト戦", "C1")
        result_html = RESULT_HTML.replace("</table>", row + "</table>", 1)
        payload = _fetch(FixtureTransport(result=result_html))
        record = payload["career"]["records"][-1]
        self.assertEqual(record["race_date"], "2025-03-17")
        self.assertEqual(record["racecourse"], "水沢")
        self.assertEqual(record["race_name"], "C1")
        self.assertEqual(record["finish"], "")
        self.assertEqual(record["result_status"], "")
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "cache.json"
            cache_path.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                completion.P0HorseCompletionSourceError,
                "partial_career: record 14 lacks core evidence",
            ):
                completion.run_p0_horse_completion_adapter(
                    _request(cache_path=str(cache_path), allow_network=False),
                    source_client=None,
                )

    def test_partial_expected_identity_lists_each_missing_candidate_field(self):
        payload = _fetch()
        with self.assertRaises(completion.P0HorseCompletionSourceError) as raised:
            completion._require_expected_identity_matches_payload(
                _request(expected_sire_name="Frosted"),
                payload["identity"],
                payload["aliases"],
                payload["source"]["name"],
                payload["source"]["external_horse_id"],
            )
        message = str(raised.exception)
        self.assertIn("expected_dam_name", message)
        self.assertIn("expected_birth_year", message)

    def test_year_only_birth_date_blocked(self):
        profile = HORSE_HTML.replace("2022年3月26日", "2022年")
        with self.assertRaises(source_clients.P0HorseSourceBlocked):
            _fetch(FixtureTransport(profile=profile))

    def test_missing_color_blocked(self):
        profile = HORSE_HTML.replace("現役　牡4歳　芦毛", "現役　牡4歳")
        with self.assertRaises(source_clients.P0HorseSourceBlocked):
            _fetch(FixtureTransport(profile=profile))

    def test_unknown_country_mark_blocked(self):
        profile = HORSE_HTML.replace("<td>米</td>", "<td>智</td>")
        with self.assertRaises(source_clients.P0HorseSourceBlocked):
            _fetch(FixtureTransport(profile=profile))

    def test_domestic_prefecture_maps_to_japan(self):
        profile = HORSE_HTML.replace("<td>米</td>", "<td>北海道</td>")
        payload = _fetch(FixtureTransport(profile=profile))
        self.assertEqual(payload["basic_profile"]["country"], "日本")

    def test_adapter_name_mismatch_fails_closed(self):
        payload = _fetch()
        with self.assertRaises(completion.P0HorseCompletionSourceError):
            completion._require_expected_identity_matches_payload(
                _request(horse_name="完全不同的马"),
                payload["identity"],
                payload["aliases"],
                payload["source"]["name"],
                payload["source"]["external_horse_id"],
            )

    def test_adapter_provider_bound_passes_with_suffixed_page(self):
        profile = HORSE_HTML.replace(
            "<h1>ドラゴンウェルズ</h1>", "<h1>ドラゴンウェルズ(USA)</h1>"
        )
        payload = _fetch(FixtureTransport(profile=profile))
        # must not raise: provider-bound identity + stripped page name
        completion._require_expected_identity_matches_payload(
            _request(),
            payload["identity"],
            payload["aliases"],
            payload["source"]["name"],
            payload["source"]["external_horse_id"],
        )


class NetkeibaQueuePreferenceTests(SimpleTestCase):
    def test_dispatcher_routes_by_candidate_source(self):
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.JAPAN,
            transport=FixtureTransport(),
        )
        self.assertIsInstance(client, source_clients._JapanDispatcherClient)
        payload = client.fetch_source_payload(_request())
        self.assertEqual(payload["source"]["name"], "netkeiba")
        self.assertEqual(client.last_request_count, 3)

    def test_dispatcher_keeps_jbis_for_non_netkeiba(self):
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.JAPAN,
            transport=FixtureTransport(),
        )
        with self.assertRaises(source_clients.P0HorseSourceBlocked):
            # jbis path with a fixture transport that cannot serve the JBIS
            # search flow fails closed, proving dispatch did not go netkeiba
            client.fetch_source_payload(
                _request(candidate_source_name="jbis", external_horse_id="")
            )


class NetkeibaSelectNamespaceTests(__import__("django.test", fromlist=["TestCase"]).TestCase):
    def _profile(self, *, keys):
        from stable.models import (
            HorseProfile,
            RacingRegion,
            SourceLanguage,
            TermEntry,
            TermType,
        )

        term = TermEntry.objects.create(
            term_type=TermType.HORSE,
            source_language=SourceLanguage.JAPANESE,
            source_ja="テストマ",
            target_zh="",
            racing_region=RacingRegion.JAPAN,
            is_active=True,
        )
        return HorseProfile.objects.create(
            primary_term=term,
            original_name="テストマ",
            racing_region=RacingRegion.JAPAN,
            source_refs={"horse_identity_keys": keys},
        )

    def _candidate(self, profile):
        from stable.services.p0_horse_completion_batch import (
            _candidate_from_queue_item,
        )
        from stable.services.p0_horse_profiles import P0QueueItem

        item = P0QueueItem(
            profile_id=profile.pk,
            profile=profile,
            region=RacingRegion.JAPAN,
        )
        return _candidate_from_queue_item(
            item,
            include_complete=False,
            allow_in_flight=False,
            in_flight_ids=set(),
        )

    def test_netkeiba_preferred_over_jbis(self):
        profile = self._profile(keys=["jbis:0001234567", "netkeiba:2022110137"])
        self.assertEqual(self._candidate(profile)["source_namespace"], "netkeiba")

    def test_jbis_only_key_keeps_jbis(self):
        profile = self._profile(keys=["jbis:0001234567"])
        self.assertEqual(self._candidate(profile)["source_namespace"], "jbis")

    def test_non_netkeiba_multi_key_keeps_identity_order(self):
        # without a netkeiba key the first key in identity order wins,
        # deterministically (no frozenset iteration)
        profile = self._profile(keys=["nar:999", "jbis:0001234567"])
        self.assertEqual(self._candidate(profile)["source_namespace"], "nar")
        profile2 = self._profile(keys=["jbis:0001234567", "nar:999"])
        self.assertEqual(self._candidate(profile2)["source_namespace"], "jbis")
