from __future__ import annotations

import hashlib
import importlib
import json
import threading
import csv
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import quote_plus
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from stable.models import RacingRegion
from stable.services import p0_horse_completion_adapters as completion
from stable.test_p0_horse_completion_adapters import (
    _reviewed_candidate_rows,
    _write_reviewed_candidate_csv,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "p0_horse_completion"


@dataclass(frozen=True)
class StubResponse:
    text: str
    status_code: int = 200
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.text)


class ScriptedTransport:
    def __init__(self, responses: list[StubResponse]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> StubResponse:
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected transport request: {url}")
        response = self.responses.pop(0)
        return StubResponse(
            text=response.text,
            status_code=response.status_code,
            url=response.url or url,
            headers=response.headers,
        )


class RejectingTransport:
    def __init__(self):
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> StubResponse:
        self.calls.append(url)
        raise AssertionError("transport must not be called")


def _source_module():
    return importlib.import_module("stable.services.p0_horse_completion_source_clients")


def _request(
    region: str,
    *,
    candidate_key: str = "",
    cache_path: Path | None = None,
    allow_network: bool = True,
    request_interval_seconds: float = 0,
    request_budget: int = 10,
    batch_limit: int = 10,
    horse_name: str = "SOURCE TEST",
    external_horse_id: str = "",
    candidate_source_name: str = "",
    expected_sire_name: str = "",
    expected_dam_name: str = "",
    expected_birth_year: int | None = None,
) -> completion.P0HorseCompletionRequest:
    return completion.P0HorseCompletionRequest(
        candidate_key=candidate_key or f"observation:{region}:event-1:1",
        region=region,
        horse_name=horse_name,
        source_url=f"https://example.test/{region}/search",
        external_horse_id=external_horse_id,
        candidate_source_name=candidate_source_name,
        expected_sire_name=expected_sire_name,
        expected_dam_name=expected_dam_name,
        expected_birth_year=expected_birth_year,
        cache_path=str(cache_path or ""),
        allow_network=allow_network,
        request_interval_seconds=request_interval_seconds,
        request_budget=request_budget,
        batch_limit=batch_limit,
    )


def _fetch(region: str, transport: ScriptedTransport, request):
    source_clients = _source_module()
    client = source_clients.build_p0_horse_completion_source_client(
        region,
        transport=transport,
    )
    return client.fetch(request), client


def _complete_source_payload(region: str) -> dict[str, Any]:
    provider_by_region = {
        RacingRegion.JAPAN: ("japan_jbis", "jbis"),
        RacingRegion.HONG_KONG: ("hong_kong_hkjc", "hkjc"),
        RacingRegion.UNITED_KINGDOM: (
            "united_kingdom_sporting_life",
            "sporting_life",
        ),
        RacingRegion.FRANCE: ("france_geny", "geny"),
        RacingRegion.UNITED_STATES: ("united_states_equibase", "hrn"),
    }
    adapter_key, provider = provider_by_region[region]
    return {
        "schema_version": completion.SOURCE_CACHE_SCHEMA_VERSION,
        "adapter_key": adapter_key,
        "region": region,
        "source": {
            "name": provider,
            "url": f"https://example.test/{provider}/horse/1",
            "external_horse_id": "horse-1",
            "fetched_at": "2026-07-18T00:00:00Z",
        },
        "identity": {
            "horse_name": "SOURCE TEST",
            "sire_name": "Test Sire",
            "dam_name": "Test Dam",
            "birth_year": 2021,
        },
        "basic_profile": {
            "country": "TEST",
            "sex": "male",
            "color": "bay",
            "birth_date": "2021-02-03",
            "owner_name": "Test Owner",
            "trainer_name": "Test Trainer",
            "breeder_name": "Test Breeder",
        },
        "pedigree": {
            "sire": "Test Sire",
            "dam": "Test Dam",
            "sire_sire": "Sire Sire",
            "sire_dam": "Sire Dam",
            "dam_sire": "Dam Sire",
            "dam_dam": "Dam Dam",
        },
        "aliases": [{"name": "SOURCE TEST", "language": "en", "is_original": True}],
        "career": {
            "source_start_count": 1,
            "official_start_count_source": provider,
            "official_start_count_source_url": (
                f"https://example.test/{provider}/horse/1"
            ),
            "official_start_count_verified_at": "2026-07-18T00:00:00Z",
            "record_authority_status": "source_records_verified",
            "records": [
                {
                    "external_race_id": "race-1",
                    "external_result_id": "result-1",
                    "race_name": "Ordinary Race",
                    "race_date": "2025-01-02",
                    "racecourse": "Test Course",
                    "finish": "1",
                    "source_url": "https://example.test/race/1",
                }
            ],
        },
    }


REGION_REQUEST_BUDGETS = {
    RacingRegion.JAPAN: 3,
    RacingRegion.HONG_KONG: 1,
    RacingRegion.UNITED_KINGDOM: 1,
    RacingRegion.FRANCE: 2,
    RacingRegion.UNITED_STATES: 3,
}


def _batch_payload_for_request(
    request: completion.P0HorseCompletionRequest,
) -> dict[str, Any]:
    payload = _complete_source_payload(request.region)
    source_id = request.external_horse_id or hashlib.sha256(
        request.candidate_key.encode("utf-8")
    ).hexdigest()[:16]
    payload["source"]["external_horse_id"] = source_id
    payload["identity"]["horse_name"] = request.horse_name
    payload["aliases"] = [
        {
            "name": request.horse_name,
            "language": "en",
            "is_original": True,
        }
    ]
    return payload


class RecordingBatchSourceClient:
    def __init__(
        self,
        region: str,
        *,
        incomplete_candidate_keys: set[str] | None = None,
    ):
        self.region = region
        self.incomplete_candidate_keys = set(incomplete_candidate_keys or ())
        self.calls: list[completion.P0HorseCompletionRequest] = []
        self.last_request_count = 0

    def fetch(
        self,
        request: completion.P0HorseCompletionRequest,
    ) -> dict[str, Any]:
        if request.region != self.region:
            raise AssertionError("source client must only receive its own region")
        if len(self.calls) >= 10:
            raise AssertionError("one controlled region batch must stop at ten horses")
        self.calls.append(request)
        self.last_request_count = REGION_REQUEST_BUDGETS[self.region]
        payload = _batch_payload_for_request(request)
        if request.candidate_key in self.incomplete_candidate_keys:
            payload["pedigree"].pop("dam_dam")
        return payload


class RecordingBatchSourceClientFactory:
    def __init__(
        self,
        *,
        incomplete_candidate_keys: set[str] | None = None,
    ):
        self.incomplete_candidate_keys = set(incomplete_candidate_keys or ())
        self.clients: dict[str, RecordingBatchSourceClient] = {}
        self.calls: list[str] = []

    def __call__(self, region: str) -> RecordingBatchSourceClient:
        self.calls.append(region)
        if region in self.clients:
            raise AssertionError("a selected region must reuse one source client")
        client = RecordingBatchSourceClient(
            region,
            incomplete_candidate_keys=self.incomplete_candidate_keys,
        )
        self.clients[region] = client
        return client


def _read_batch_payloads(output_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (
            output_dir / "p0_horse_completion_candidates.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_review_manifest(
    path: Path,
    reviewed_csv: Path,
    *,
    artifact_type: str = "p0_horse_candidate_review_manifest",
    decision: str = "confirm_batch_inclusion",
    entry_name: str | None = None,
    sha256: str | None = None,
    size: int | None = None,
    row_count: int = 50,
) -> Path:
    csv_bytes = reviewed_csv.read_bytes()
    csv_name = entry_name or reviewed_csv.name
    payload = {
        "artifact_type": artifact_type,
        "decision": decision,
        "row_count": row_count,
        "files": {
            csv_name: {
                "path": csv_name,
                "sha256": (
                    sha256
                    if sha256 is not None
                    else hashlib.sha256(csv_bytes).hexdigest()
                ),
                "size": size if size is not None else len(csv_bytes),
            }
        },
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manual_review_csv(
    path: Path,
    candidate: dict[str, Any],
) -> Path:
    source_clients = _source_module()
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=source_clients.MANUAL_SUPPLEMENT_CSV_FIELDS,
        )
        writer.writeheader()
        writer.writerow(
            {
                "candidate_key": candidate["candidate_key"],
                "region": candidate["sample_region"],
                "horse_name": candidate["horse_name"],
                "field_group": "basic_profile",
                "field_name": "breeder_name",
                "current_value": "",
                "proposed_value": "Reviewed Breeder",
                "source_name": "reviewed_source",
                "source_url": "https://example.test/reviewed-source",
                "source_external_horse_id": "",
                "evidence_note": "",
                "entered_by": "operator-a",
                "reviewer": "reviewer-b",
                "review_status": "approved",
                "reviewed_at": "2026-07-18T02:00:00Z",
                "review_notes": "",
            }
        )
    return path


JBIS_SEARCH_HTML = """
<html><body>
  <div class="search-result">
    <a href="/horse/0000123456/">ソーステスト</a>
    <span>2021 鹿毛 牡 Test Sire - Test Dam</span>
  </div>
</body></html>
"""

JBIS_PROFILE_HTML = """
<html><body>
  <h1>ソーステスト</h1>
  <dl class="horse-profile">
    <dt>英字表記</dt><dd>SOURCE TEST</dd>
    <dt>生年月日</dt><dd>2021年2月3日</dd>
    <dt>性別</dt><dd>牡</dd>
    <dt>毛色</dt><dd>鹿毛</dd>
    <dt>生産国</dt><dd>日本</dd>
    <dt>馬主</dt><dd>Test Owner</dd>
    <dt>調教師</dt><dd>Test Trainer</dd>
    <dt>生産牧場</dt><dd>Test Breeder</dd>
  </dl>
  <table id="pedigree">
    <tr><td data-role="sire">Test Sire</td><td data-role="sire-sire">Sire Sire</td></tr>
    <tr><td data-role="sire-dam">Sire Dam</td></tr>
    <tr><td data-role="dam">Test Dam</td><td data-role="dam-sire">Dam Sire</td></tr>
    <tr><td data-role="dam-dam">Dam Dam</td></tr>
  </table>
  <a href="/horse/0000123456/record/">競走成績</a>
</body></html>
"""

JBIS_RECORD_HTML = """
<html><body>
  <p class="record-summary">出走 3 回</p>
  <table id="career-records">
    <tr><th>日付</th><th>競馬場</th><th>競走名</th><th>着順</th><th>距離</th></tr>
    <tr data-race-id="JBIS-R1" data-result-id="JBIS-O1">
      <td>2023-11-01</td><td>門別</td><td><a href="/race/JBIS-R1/">新馬戦</a></td><td>1</td><td>1600m</td>
    </tr>
    <tr data-race-id="JBIS-R2" data-result-id="JBIS-O2">
      <td>2024-01-06</td><td>京都</td><td><a href="/race/JBIS-R2/">1勝クラス</a></td><td>2</td><td>1800m</td>
    </tr>
    <tr data-race-id="JBIS-R3" data-result-id="JBIS-O3">
      <td>2024-02-10</td><td>東京</td><td><a href="/race/JBIS-R3/">共同通信杯</a></td><td>5</td><td>1800m</td>
    </tr>
  </table>
</body></html>
"""

HKJC_PROFILE_HTML = """
<html><body>
  <h1>FOREVER SOURCE (H123)</h1>
  <table id="profile">
    <tr><td>Country of Origin / Age</td><td>:</td><td>AUS / 5</td></tr>
    <tr><td>Colour / Sex</td><td>:</td><td>Bay / Gelding</td></tr>
    <tr><td>Date of Birth</td><td>:</td><td>2021-09-12</td></tr>
    <tr><td>Trainer</td><td>:</td><td>Test Trainer</td></tr>
    <tr><td>Owner</td><td>:</td><td>Test Owner</td></tr>
    <tr><td>Breeder</td><td>:</td><td>Test Breeder</td></tr>
    <tr><td>Sire</td><td>:</td><td>Test Sire</td></tr>
    <tr><td>Dam</td><td>:</td><td>Test Dam</td></tr>
    <tr><td>Sire's Sire</td><td>:</td><td>Sire Sire</td></tr>
    <tr><td>Sire's Dam</td><td>:</td><td>Sire Dam</td></tr>
    <tr><td>Dam's Sire</td><td>:</td><td>Dam Sire</td></tr>
    <tr><td>Dam's Dam</td><td>:</td><td>Dam Dam</td></tr>
    <tr><td>No. of 1-2-3-Starts*</td><td>:</td><td>1-1-0-3</td></tr>
  </table>
  <table id="local-records">
    <caption>Local Performances</caption>
    <tr><th>Date</th><th>Race</th><th>Course</th><th>Place</th></tr>
    <tr data-race-id="HK-LOCAL-1" data-result-id="HK-RESULT-1">
      <td>2025-01-01</td><td>Class 4 Handicap</td><td>Sha Tin</td><td>1</td>
    </tr>
    <tr data-race-id="HK-LOCAL-2" data-result-id="HK-RESULT-2">
      <td>2025-02-01</td><td>Class 3 Handicap</td><td>Happy Valley</td><td>2</td>
    </tr>
    <tr data-race-id="HK-LOCAL-3" data-result-id="HK-RESULT-3">
      <td>2025-03-01</td><td>Class 2 Handicap</td><td>Sha Tin</td><td>WV</td>
    </tr>
  </table>
  <table id="overseas-records">
    <caption>Overseas Performances</caption>
    <tr><th>Date</th><th>Race</th><th>Course</th><th>Place</th></tr>
    <tr data-race-id="AUS-RACE-1" data-result-id="AUS-RESULT-1">
      <td>2024-08-10</td><td>Maiden Plate</td><td>Randwick</td><td>3</td>
    </tr>
  </table>
</body></html>
"""


def _sporting_life_next_data(
    *,
    include_all_runs: bool = True,
    horse_id: str = "98765",
    horse_name: str = "SOURCE TEST",
    runs_override: list[dict[str, Any]] | None = None,
) -> str:
    runs = [
        {
            "race_id": "SL-R1",
            "result_id": "SL-O1",
            "date": "2025-05-01",
            "race_name": "Newmarket Maiden Stakes",
            "course": "Newmarket",
            "position": "1",
            "distance": "1m",
        },
        {
            "race_id": "SL-R2",
            "result_id": "SL-O2",
            "date": "2025-06-01",
            "race_name": "York Novice Stakes",
            "course": "York",
            "position": "2",
            "distance": "1m2f",
        },
        {
            "race_id": "SL-R3",
            "result_id": "SL-O3",
            "date": "2025-07-01",
            "race_name": "Ascot Handicap",
            "course": "Ascot",
            "position": "5",
            "distance": "1m2f",
        },
    ]
    if runs_override is not None:
        runs = runs_override
    payload = {
        "props": {
            "pageProps": {
                "horse": {
                    "id": horse_id,
                    "name": horse_name,
                    "country": "GB",
                    "sex": "gelding",
                    "colour": "bay",
                    "date_of_birth": "2021-03-04",
                    "owner": "Test Owner",
                    "trainer": "Test Trainer",
                    "breeder": "Test Breeder",
                    "pedigree": {
                        "sire": "Test Sire",
                        "dam": "Test Dam",
                        "sire_sire": "Sire Sire",
                        "sire_dam": "Sire Dam",
                        "dam_sire": "Dam Sire",
                        "dam_dam": "Dam Dam",
                    },
                    "stats": {"runs": len(runs), "wins": 1},
                    "full_form": runs if include_all_runs else runs[-1:],
                }
            }
        }
    }
    return (
        "<html><body><h1>DOM summary only</h1>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        "</body></html>"
    )


GENY_CAREER_HTML = """
<html><body>
  <h1>Source Test</h1>
  <div class="identite">Hongre de 5 ans, bai, par Test Sire et Test Dam</div>
  <dl>
    <dt>Date de naissance</dt><dd>2021-02-03</dd>
    <dt>Pays</dt><dd>FR</dd>
    <dt>Entraîneur</dt><dd>Test Trainer</dd>
    <dt>Propriétaire</dt><dd>Test Owner</dd>
    <dt>Éleveur</dt><dd>Test Breeder</dd>
    <dt>Père du père</dt><dd>Sire Sire</dd>
    <dt>Mère du père</dt><dd>Sire Dam</dd>
    <dt>Père de la mère</dt><dd>Dam Sire</dd>
    <dt>Mère de la mère</dt><dd>Dam Dam</dd>
    <dt>Nombre de courses</dt><dd>6</dd>
  </dl>
  <table id="carriere">
    <tr><th>Date</th><th>Course</th><th>Hippodrome</th><th>Place</th></tr>
    <tr data-race-id="GENY-R1"><td>2024-01-01</td><td>Prix des Débuts</td><td>Chantilly</td><td>1</td></tr>
    <tr data-race-id="GENY-R2"><td>2024-02-01</td><td>Prix Ordinaire A</td><td>Saint-Cloud</td><td>2</td></tr>
    <tr data-race-id="GENY-R3"><td>2024-03-01</td><td>Prix Ordinaire B</td><td>Deauville</td><td>4</td></tr>
    <tr data-race-id="GENY-R4"><td>2024-04-01</td><td>Prix Ordinaire C</td><td>Longchamp</td><td>5</td></tr>
    <tr data-race-id="GENY-R5"><td>2024-05-01</td><td>Prix Ordinaire D</td><td>Auteuil</td><td>NP</td></tr>
    <tr data-race-id="GENY-R6"><td>2024-06-01</td><td>Prix Ordinaire E</td><td>Chantilly</td><td>3</td></tr>
  </table>
</body></html>
"""

GENY_RECENT_FIVE_HTML = GENY_CAREER_HTML.replace(
    '<tr data-race-id="GENY-R1"><td>2024-01-01</td><td>Prix des Débuts</td><td>Chantilly</td><td>1</td></tr>',
    "",
)

GENY_SEARCH_HTML = """
<html><body><div class="search-results">
  <a href="/cheval/source-test_c123456_h2500000">Source Test</a>
  <span>2021, Test Sire - Test Dam</span>
</div></body></html>
"""

GENY_SEARCH_AMBIGUOUS_HTML = """
<html><body><div class="search-results">
  <a href="/cheval/source-test_c123456_h2500000">Source Test</a>
  <span>2021, Test Sire - Test Dam</span>
  <a href="/cheval/source-test_c654321_h2600000">Source Test</a>
  <span>2022, Other Sire - Other Dam</span>
</div></body></html>
"""

HRN_SEARCH_ONE_HTML = """
<html><body><div class="search-results">
  <a href="/horse/source-test">Source Test</a>
  <span>2021 Test Sire - Test Dam</span>
</div></body></html>
"""

HRN_SEARCH_AMBIGUOUS_HTML = """
<html><body><div class="search-results">
  <a href="/horse/source-test-1">Source Test</a><span>2021 Test Sire - Test Dam</span>
  <a href="/horse/source-test-2">Source Test</a><span>2021 Other Sire - Other Dam</span>
</div></body></html>
"""

HRN_PROFILE_HTML = """
<html><body>
  <h1>Source Test</h1>
  <dl>
    <dt>Foaled</dt><dd>2021-02-03</dd><dt>Country</dt><dd>USA</dd>
    <dt>Sex</dt><dd>Colt</dd><dt>Color</dt><dd>Bay</dd>
    <dt>Owner</dt><dd>Test Owner</dd><dt>Trainer</dt><dd>Test Trainer</dd>
    <dt>Breeder</dt><dd>Test Breeder</dd>
    <dt>Sire</dt><dd>Test Sire</dd><dt>Dam</dt><dd>Test Dam</dd>
    <dt>Sire Sire</dt><dd>Sire Sire</dd><dt>Sire Dam</dt><dd>Sire Dam</dd>
    <dt>Dam Sire</dt><dd>Dam Sire</dd><dt>Dam Dam</dt><dd>Dam Dam</dd>
    <dt>Starts</dt><dd>3</dd>
  </dl>
  <a href="/horse/source-test/results">All Results</a>
</body></html>
"""

HRN_RESULTS_HTML = """
<html><body><table id="all-results">
  <tr><th>Date</th><th>Race</th><th>Track</th><th>Finish</th></tr>
  <tr data-race-id="HRN-R1" data-result-id="HRN-O1"><td>2025-01-01</td><td>Maiden Special Weight</td><td>Gulfstream</td><td>1</td></tr>
  <tr data-race-id="HRN-R2" data-result-id="HRN-O2"><td>2025-02-01</td><td>Allowance Optional Claiming</td><td>Aqueduct</td><td>2</td></tr>
  <tr data-race-id="HRN-R3" data-result-id="HRN-O3"><td>2025-03-01</td><td>Starter Allowance</td><td>Belmont</td><td>DNF</td></tr>
</table></body></html>
"""


def _sporting_life_real_profile_html(*, complete: bool) -> str:
    profile: dict[str, Any] = {
        "horse_reference": {
            "id": "98765",
            "name": "SOURCE TEST",
        },
        "foaled": "2021-03-04",
        "country": "GB",
        "colour": "Bay",
        "sex": {"type": "Gelding"},
        "owner": "Test Owner",
        "trainer": {"name": "Test Trainer"},
        "sire": {"name": "Test Sire"},
        "dam": {"name": "Test Dam"},
        "damsire": {"name": "Dam Sire"},
        "previous_results": [
            {
                "race_reference": {
                    "id": "SL-REAL-R1",
                    "name": "Newmarket Maiden Stakes",
                },
                "result_reference": {"id": "SL-REAL-O1"},
                "date": "2025-05-01",
                "course": {"name": "Newmarket"},
                "position": "1",
                "distance": "1m",
            },
            {
                "race_reference": {
                    "id": "SL-REAL-R2",
                    "name": "York Novice Stakes",
                },
                "result_reference": {"id": "SL-REAL-O2"},
                "date": "2025-06-01",
                "course": {"name": "York"},
                "position": "2",
                "distance": "1m2f",
            },
        ],
        "stats": {"total": {"runs": 2}},
    }
    if complete:
        profile["breeder"] = "Test Breeder"
        profile["pedigree"] = {
            "sire": "Test Sire",
            "dam": "Test Dam",
            "sire_sire": "Sire Sire",
            "sire_dam": "Sire Dam",
            "dam_sire": "Dam Sire",
            "dam_dam": "Dam Dam",
        }
    next_data = {"props": {"pageProps": {"profile": profile}}}
    return (
        "<html><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
        "</body></html>"
    )


def _hkjc_real_retired_profile_html(*, complete: bool) -> str:
    optional_rows = ""
    race_name_attributes = ("", "", "")
    if complete:
        optional_rows = """
          <tr><td>Date of Birth</td><td>:</td><td>2021-09-12</td></tr>
          <tr><td>Breeder</td><td>:</td><td>Test Breeder</td></tr>
          <tr><td>Sire's Sire</td><td>:</td><td>Sire Sire</td></tr>
          <tr><td>Sire's Dam</td><td>:</td><td>Sire Dam</td></tr>
          <tr><td>Dam's Sire</td><td>:</td><td>Dam Sire</td></tr>
          <tr><td>Dam's Dam</td><td>:</td><td>Dam Dam</td></tr>
        """
        race_name_attributes = (
            ' data-race-name="Class 4 Handicap"',
            ' data-race-name="Class 3 Handicap"',
            ' data-race-name="Maiden Plate"',
        )
    return f"""
<html><body>
  <table class="horseProfile">
    <tr><td>
      <table>
        <tr><td>Horse Name</td><td>:</td><td>FOREVER SOURCE (H123)</td></tr>
        <tr><td>Country of Origin / Age</td><td>:</td><td>AUS / 5</td></tr>
        <tr><td>Colour / Sex</td><td>:</td><td>Bay / Gelding</td></tr>
        <tr><td>Status</td><td>:</td><td>Retired</td></tr>
      </table>
    </td></tr>
    <tr><td>
      <table>
        <tr><td>Owner</td><td>:</td><td>Test Owner</td></tr>
        <tr><td>Sire</td><td>:</td><td>Test Sire</td></tr>
        <tr><td>Dam</td><td>:</td><td>Test Dam</td></tr>
        <tr><td>No. of 1-2-3-Starts*</td><td>:</td><td>1-1-0-3</td></tr>
        {optional_rows}
      </table>
    </td></tr>
  </table>
  <table class="bigborder">
    <tr><td colspan="10">Form Records</td></tr>
    <tr>
      <td class="hsubheader">Race<br>Index</td>
      <td class="hsubheader">Pla.</td>
      <td class="hsubheader">Date</td>
      <td class="hsubheader">RC/Track/<br>Course</td>
      <td class="hsubheader">Dist.</td>
      <td class="hsubheader">G</td>
      <td class="hsubheader">Race<br>Class</td>
      <td class="hsubheader">Dr.</td>
      <td class="hsubheader">Rtg.</td>
      <td class="hsubheader">Trainer</td>
    </tr>
    <tr{race_name_attributes[0]}><td>101</td><td>1</td><td>01/01/25</td><td>ST / Turf / C</td><td>1200</td><td>G</td><td>4</td><td>1</td><td>80</td><td>Latest Trainer</td></tr>
    <tr{race_name_attributes[1]}><td>202</td><td>2</td><td>01/02/24</td><td>HV / Turf / A</td><td>1650</td><td>G</td><td>3</td><td>2</td><td>75</td><td>Former Trainer</td></tr>
    <tr{race_name_attributes[2]}><td>303</td><td>3</td><td>10/08/23</td><td>AUS / Turf / R</td><td>1400</td><td>G</td><td>Maiden</td><td>3</td><td>70</td><td>Former Trainer</td></tr>
  </table>
</body></html>
"""


JBIS_REAL_SEARCH_HTML = """
<html><body>
  <table class="data-6-1">
    <tr><th>馬名</th><th>生年</th><th>性</th><th>調教師</th><th>父</th><th>母</th></tr>
    <tr>
      <td><a href="/horse/0000123456/">ソーステスト</a></td>
      <td>2021</td><td>牡</td><td>Test Trainer</td>
      <td>Test Sire</td><td>Test Dam</td>
    </tr>
  </table>
</body></html>
"""

JBIS_REAL_PROFILE_HTML = """
<html><body>
  <div class="data-3-2">
    <h1>ソーステスト</h1><span class="eng-name">SOURCE TEST</span>
  </div>
  <div class="data-4">
    <dl>
      <dt>生年月日</dt><dd>2021年2月3日</dd>
      <dt>性別</dt><dd>牡</dd><dt>毛色</dt><dd>鹿毛</dd>
      <dt>生産国</dt><dd>日本</dd><dt>馬主</dt><dd>Test Owner</dd>
      <dt>調教師</dt><dd>Test Trainer</dd>
      <dt>生産牧場</dt><dd>Test Breeder</dd>
      <dt>英字表記</dt><dd>SOURCE TEST</dd>
    </dl>
    <table class="pedigree">
      <tr><td data-role="sire">Test Sire</td><td data-role="sire-sire">Sire Sire</td></tr>
      <tr><td data-role="sire-dam">Sire Dam</td></tr>
      <tr><td data-role="dam">Test Dam</td><td data-role="dam-sire">Dam Sire</td></tr>
      <tr><td data-role="dam-dam">Dam Dam</td></tr>
    </table>
  </div>
  <a href="/horse/0000123456/record/">競走成績</a>
</body></html>
"""

JBIS_REAL_RECORD_HTML = """
<html><body>
  <h2>3戦中 3戦の成績表示</h2>
  <div class="data-18-1">
    <div class="record-row" data-race-id="JBIS-REAL-R1" data-result-id="JBIS-REAL-O1">
      <div class="date">2023-11-01</div><div class="racecourse">門別</div>
      <div class="race-name"><a href="/race/JBIS-REAL-R1/">新馬戦</a></div>
      <div class="finish">1</div><div class="distance">1600m</div>
    </div>
    <div class="record-row" data-race-id="JBIS-REAL-R2" data-result-id="JBIS-REAL-O2">
      <div class="date">2024-01-06</div><div class="racecourse">京都</div>
      <div class="race-name"><a href="/race/JBIS-REAL-R2/">1勝クラス</a></div>
      <div class="finish">2</div><div class="distance">1800m</div>
    </div>
    <div class="record-row" data-race-id="JBIS-REAL-R3" data-result-id="JBIS-REAL-O3">
      <div class="date">2024-02-10</div><div class="racecourse">東京</div>
      <div class="race-name"><a href="/race/JBIS-REAL-R3/">共同通信杯</a></div>
      <div class="finish">5</div><div class="distance">1800m</div>
    </div>
  </div>
</body></html>
"""

def _jbis_nonstart_record_html(
    *,
    status_cell: str,
    race_name: str = "4歳以上1勝クラス",
    include_status_tail: bool = True,
) -> str:
    status_tail = (
        f"<div>{status_cell}</div><div>482</div><div></div>"
        if include_status_tail
        else ""
    )
    return f"""
<html><body>
  <h2>1戦中 1戦の成績表示</h2>
  <div class="data-6-5">
    <div>
      <div>日付</div><div>競馬場</div><div>競走名</div><div>着順</div>
      <div>人気</div><div>距離</div><div>馬場</div><div>頭数</div>
      <div>馬番</div><div>タイム</div><div>着差</div><div>騎手</div>
      <div>1着馬/2着馬</div><div>馬体重</div><div>備考</div>
    </div>
    <div>
      <div>2025-01-01</div><div>中山</div>
      <div><a href="/race/result/202501010101/">3歳未勝利</a></div>
      <div>1</div><div>1</div><div>芝1600m</div><div>良</div><div>16</div>
      <div>1</div><div>1:34.0</div><div>-0.2</div><div>Test Jockey</div>
      <div>1着馬</div><div>480</div><div></div>
    </div>
    <div>
      <div>2025-02-01</div><div>東京</div>
      <div><a href="/race/result/202502010202/">{race_name}</a></div>
      <div>**</div><div>--</div><div>芝1800m</div><div>良</div><div>16</div>
      <div>2</div><div>--</div><div>--</div><div>Test Jockey</div>
      {status_tail}
    </div>
  </div>
</body></html>
"""


JBIS_EXCLUDED_RECORD_HTML = _jbis_nonstart_record_html(
    status_cell="除外",
)


def _hrn_real_profile_html(
    *,
    horse_name: str,
    complete: bool,
    sire: str = "Test Sire",
    dam: str = "Test Dam",
) -> str:
    complete_fields = ""
    if complete:
        complete_fields = """
      <div><strong>Foaled:</strong> 2021-02-03</div>
      <div><strong>Color:</strong> Bay</div>
      <div><strong>Breeder:</strong> Test Breeder</div>
      <div><strong>Sire Sire:</strong> Sire Sire</div>
      <div><strong>Sire Dam:</strong> Sire Dam</div>
      <div><strong>Dam Sire:</strong> Dam Sire</div>
      <div><strong>Dam Dam:</strong> Dam Dam</div>
        """
    else:
        complete_fields = "<div><strong>Foaled:</strong> 2021</div>"
    return f"""
<html><body>
  <h1>{horse_name}</h1>
  <div class="horse-stats">
    <div><strong>Country:</strong> USA</div>
    <div><strong>Sex:</strong> Colt</div>
    <div><strong>Owner:</strong> Test Owner</div>
    <div><strong>Trainer:</strong> Test Trainer</div>
    <div><strong>Sire:</strong> {sire}</div>
    <div><strong>Dam:</strong> {dam}</div>
    <div><strong>Starts:</strong> 2</div>
    {complete_fields}
  </div>
  <table class="horse-table">
    <tr><th>Date</th><th>Track</th><th>Race</th><th>Finish</th></tr>
    <tr data-race-id="HRN-REAL-R1" data-result-id="HRN-REAL-O1">
      <td>2025-01-01</td><td>Gulfstream</td><td>Maiden Special Weight</td><td>1</td>
    </tr>
    <tr data-race-id="HRN-REAL-R2" data-result-id="HRN-REAL-O2">
      <td>2025-02-01</td><td>Aqueduct</td><td>Allowance Optional Claiming</td><td>2</td>
    </tr>
  </table>
</body></html>
"""


class BarrierSourceClient:
    def __init__(
        self,
        *,
        barrier: threading.Barrier,
        payload: dict[str, Any],
    ):
        self.barrier = barrier
        self.payload = deepcopy(payload)
        self.last_request_count = 1

    def fetch(self, request: completion.P0HorseCompletionRequest) -> dict[str, Any]:
        self.barrier.wait(timeout=5)
        return deepcopy(self.payload)


class P0HorseCompletionSourceClientTests(SimpleTestCase):
    def _write_manual_supplements(
        self,
        path: Path,
        rows: list[dict[str, Any]],
    ) -> None:
        source_clients = _source_module()
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=source_clients.MANUAL_SUPPLEMENT_CSV_FIELDS,
            )
            writer.writeheader()
            writer.writerows(rows)

    def test_reviewed_manual_supplements_fill_only_empty_fields_with_audit_metadata(self):
        source_clients = _source_module()
        candidate_key = "external:sporting_life:1014215"
        rows = [
            {
                "candidate_key": candidate_key,
                "region": RacingRegion.UNITED_KINGDOM,
                "horse_name": "JONBON",
                "field_group": "basic_profile",
                "field_name": "country",
                "current_value": "",
                "proposed_value": "FR",
                "source_name": "pedigree_query",
                "source_url": "https://www.pedigreequery.com/jonbon",
                "source_external_horse_id": "",
                "evidence_note": "Country suffix on pedigree profile.",
                "entered_by": "operator-a",
                "reviewer": "reviewer-b",
                "review_status": "approved",
                "reviewed_at": "2026-07-18T02:00:00Z",
                "review_notes": "Verified against the linked profile.",
            },
            {
                "candidate_key": candidate_key,
                "region": RacingRegion.UNITED_KINGDOM,
                "horse_name": "JONBON",
                "field_group": "basic_profile",
                "field_name": "breeder_name",
                "current_value": "",
                "proposed_value": "Lotfi Kohli",
                "source_name": "pedigree_query",
                "source_url": "https://www.pedigreequery.com/jonbon",
                "source_external_horse_id": "",
                "evidence_note": "Breeder shown on the profile.",
                "entered_by": "operator-a",
                "reviewer": "reviewer-b",
                "review_status": "approved",
                "reviewed_at": "2026-07-18T02:00:00Z",
                "review_notes": "",
            },
        ]
        with TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "manual.csv"
            self._write_manual_supplements(path, rows)
            supplements = source_clients.load_reviewed_manual_supplements(
                path,
                reviewed_candidates=[
                    {
                        "candidate_key": candidate_key,
                        "sample_region": RacingRegion.UNITED_KINGDOM,
                        "horse_name": "JONBON",
                    }
                ],
            )

        primary = _complete_source_payload(RacingRegion.UNITED_KINGDOM)
        primary["identity"]["horse_name"] = "JONBON"
        primary["basic_profile"]["country"] = ""
        primary["basic_profile"]["breeder_name"] = ""
        merged = source_clients.merge_reviewed_manual_supplements(
            primary,
            supplements[candidate_key],
        )

        self.assertEqual(merged["basic_profile"]["country"], "FR")
        self.assertEqual(
            merged["basic_profile"]["breeder_name"],
            "Lotfi Kohli",
        )
        self.assertEqual(merged["career"], primary["career"])
        provenance = merged["field_provenance"]["basic_profile.country"]
        self.assertEqual(provenance["entry_method"], "manual_review")
        self.assertEqual(provenance["entered_by"], "operator-a")
        self.assertEqual(provenance["reviewer"], "reviewer-b")
        self.assertEqual(provenance["field_group"], "basic_profile")
        self.assertEqual(
            merged["supplemental_sources"][0]["evidence_role"],
            "manual_supplement",
        )
        normalized = completion.REGION_ADAPTERS[
            RacingRegion.UNITED_KINGDOM
        ].normalize(
            merged,
            _request(
                RacingRegion.UNITED_KINGDOM,
                candidate_key=candidate_key,
                horse_name="JONBON",
                external_horse_id="horse-1",
                candidate_source_name="sporting_life",
            ),
        )
        manual_evidence = next(
            row
            for row in normalized["source_evidence"]
            if row["evidence_role"] == "manual_supplement"
        )
        self.assertEqual(manual_evidence["entered_by"], "operator-a")
        self.assertEqual(manual_evidence["reviewer"], "reviewer-b")
        self.assertEqual(manual_evidence["field_name"], "country")

    def test_manual_supplement_loader_rejects_self_review_and_unsupported_fields(self):
        source_clients = _source_module()
        candidate_key = "external:hkjc:HK_2016_A093"
        base = {
            "candidate_key": candidate_key,
            "region": RacingRegion.HONG_KONG,
            "horse_name": "EAGLE WAY",
            "field_group": "basic_profile",
            "field_name": "breeder_name",
            "current_value": "",
            "proposed_value": "Test Breeder",
            "source_name": "breednet",
            "source_url": "https://www.breednet.com.au/horse/eagle-way",
            "source_external_horse_id": "",
            "evidence_note": "",
            "entered_by": "same-user",
            "reviewer": "same-user",
            "review_status": "approved",
            "reviewed_at": "2026-07-18T02:00:00Z",
            "review_notes": "",
        }
        candidates = [
            {
                "candidate_key": candidate_key,
                "sample_region": RacingRegion.HONG_KONG,
                "horse_name": "EAGLE WAY",
            }
        ]
        with TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "manual.csv"
            self._write_manual_supplements(path, [base])
            with self.assertRaisesRegex(
                source_clients.P0HorseSourceBlocked,
                "entered_by and reviewer must be different",
            ):
                source_clients.load_reviewed_manual_supplements(
                    path,
                    reviewed_candidates=candidates,
                )

            invalid_field = {
                **base,
                "entered_by": "operator-a",
                "field_group": "career",
                "field_name": "source_start_count",
            }
            self._write_manual_supplements(path, [invalid_field])
            with self.assertRaisesRegex(
                source_clients.P0HorseSourceBlocked,
                "unsupported field_group or field_name",
            ):
                source_clients.load_reviewed_manual_supplements(
                    path,
                    reviewed_candidates=candidates,
                )

    def test_manual_supplement_loader_parses_the_captured_hashed_snapshot(self):
        source_clients = _source_module()
        candidate_key = "external:sporting_life:1014215"
        row = {
            "candidate_key": candidate_key,
            "region": RacingRegion.UNITED_KINGDOM,
            "horse_name": "JONBON",
            "field_group": "basic_profile",
            "field_name": "country",
            "current_value": "",
            "proposed_value": "FR",
            "source_name": "pedigree_query",
            "source_url": "https://www.pedigreequery.com/jonbon",
            "source_external_horse_id": "",
            "evidence_note": "",
            "entered_by": "operator-a",
            "reviewer": "reviewer-b",
            "review_status": "approved",
            "reviewed_at": "2026-07-18T02:00:00Z",
            "review_notes": "",
        }
        with TemporaryDirectory() as temporary_dir:
            path = Path(temporary_dir) / "manual.csv"
            self._write_manual_supplements(path, [row])
            captured_bytes = path.read_bytes()
            path.write_text("tampered after hash\n", encoding="utf-8")

            supplements = source_clients.load_reviewed_manual_supplements(
                path,
                reviewed_candidates=[
                    {
                        "candidate_key": candidate_key,
                        "sample_region": RacingRegion.UNITED_KINGDOM,
                        "horse_name": "JONBON",
                    }
                ],
                captured_bytes=captured_bytes,
            )

        self.assertEqual(len(supplements[candidate_key]), 1)

    def test_manual_supplement_merge_blocks_existing_value_conflicts(self):
        source_clients = _source_module()
        primary = _complete_source_payload(RacingRegion.UNITED_STATES)
        row = {
            "field_group": "basic_profile",
            "field_name": "birth_date",
            "proposed_value": "2021-02-04",
            "source": {
                "name": "manual_source",
                "url": "https://example.test/source",
                "fetched_at": "2026-07-18T02:00:00Z",
                "entry_method": "manual_review",
                "entered_by": "operator-a",
                "reviewer": "reviewer-b",
                "field_group": "basic_profile",
                "field_name": "birth_date",
                "evidence_role": "manual_supplement",
            },
        }

        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            r"source_conflict: basic_profile\.birth_date",
        ):
            source_clients.merge_reviewed_manual_supplements(
                primary,
                [row],
            )

        same_value = deepcopy(row)
        same_value["proposed_value"] = primary["basic_profile"]["birth_date"]
        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            r"manual_target_not_empty: basic_profile\.birth_date",
        ):
            source_clients.merge_reviewed_manual_supplements(
                primary,
                [same_value],
            )

    def test_source_client_applies_reviewed_manual_supplements_before_validation(self):
        source_clients = _source_module()
        candidate_key = "external:sporting_life:1014215"
        primary = _complete_source_payload(RacingRegion.UNITED_KINGDOM)
        primary["identity"]["horse_name"] = "JONBON"
        primary["basic_profile"]["country"] = ""
        primary["basic_profile"]["breeder_name"] = ""
        manual_rows = [
            {
                "field_group": "basic_profile",
                "field_name": field_name,
                "current_value": "",
                "proposed_value": proposed_value,
                "source": {
                    "name": "pedigree_query",
                    "url": "https://www.pedigreequery.com/jonbon",
                    "external_horse_id": "",
                    "fetched_at": "2026-07-18T02:00:00Z",
                    "entry_method": "manual_review",
                    "entered_by": "operator-a",
                    "reviewer": "reviewer-b",
                    "field_group": "basic_profile",
                    "field_name": field_name,
                    "evidence_role": "manual_supplement",
                    "evidence_note": "",
                    "review_notes": "",
                },
            }
            for field_name, proposed_value in (
                ("country", "FR"),
                ("breeder_name", "Lotfi Kohli"),
            )
        ]

        class PartialSportingLifeClient(source_clients._BaseSourceClient):
            region = RacingRegion.UNITED_KINGDOM
            provider_name = "sporting_life"

            def _fetch(self, request):
                return deepcopy(primary)

        with patch.dict(
            source_clients._CLIENTS,
            {RacingRegion.UNITED_KINGDOM: PartialSportingLifeClient},
        ):
            client = source_clients.build_p0_horse_completion_source_client(
                RacingRegion.UNITED_KINGDOM,
                transport=RejectingTransport(),
                manual_supplements_by_candidate={
                    candidate_key: manual_rows,
                },
            )
            payload = client.fetch(
                _request(
                    RacingRegion.UNITED_KINGDOM,
                    candidate_key=candidate_key,
                    horse_name="JONBON",
                    external_horse_id="1014215",
                    candidate_source_name="sporting_life",
                )
            )

        self.assertEqual(payload["basic_profile"]["country"], "FR")
        self.assertEqual(
            payload["basic_profile"]["breeder_name"],
            "Lotfi Kohli",
        )

    def test_cache_hit_applies_manual_supplements_without_rewriting_cache_and_blocks_conflicts(self):
        source_clients = _source_module()
        candidate_key = "external:sporting_life:1014215"
        base_payload = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        base_payload["identity"]["horse_name"] = "JONBON"
        base_payload["identity"]["birth_year"] = None

        def manual_row(value: int) -> dict[str, Any]:
            return {
                "field_group": "identity",
                "field_name": "birth_year",
                "current_value": "",
                "proposed_value": value,
                "source": {
                    "name": "pedigree_query",
                    "url": "https://www.pedigreequery.com/jonbon",
                    "external_horse_id": "",
                    "fetched_at": "2026-07-18T02:00:00Z",
                    "entry_method": "manual_review",
                    "entered_by": "operator-a",
                    "reviewer": "reviewer-b",
                    "field_group": "identity",
                    "field_name": "birth_year",
                    "evidence_role": "manual_supplement",
                    "evidence_note": "",
                    "review_notes": "",
                },
            }

        with TemporaryDirectory() as temporary_dir:
            cache_path = Path(temporary_dir) / "cache.json"
            transport = RejectingTransport()

            class PureSportingLifeClient(
                source_clients._BaseSourceClient
            ):
                region = RacingRegion.UNITED_KINGDOM
                provider_name = "sporting_life"

                def _fetch(self, request):
                    return deepcopy(base_payload)

            with patch.dict(
                source_clients._CLIENTS,
                {
                    RacingRegion.UNITED_KINGDOM: (
                        PureSportingLifeClient
                    )
                },
            ):
                client = (
                    source_clients.build_p0_horse_completion_source_client(
                        RacingRegion.UNITED_KINGDOM,
                        transport=transport,
                        manual_supplements_by_candidate={
                            candidate_key: [manual_row(2021)],
                        },
                    )
                )
            request = _request(
                RacingRegion.UNITED_KINGDOM,
                candidate_key=candidate_key,
                cache_path=cache_path,
                horse_name="JONBON",
                external_horse_id="horse-1",
                candidate_source_name="sporting_life",
            )

            network_completed = (
                completion.run_p0_horse_completion_adapter(
                    request,
                    source_client=client,
                )
            )
            self.assertFalse(
                network_completed["retrieval"]["cache_hit"]
            )
            self.assertEqual(
                network_completed["identity"]["birth_year"],
                2021,
            )
            cached_payload = json.loads(
                cache_path.read_text(encoding="utf-8")
            )
            self.assertIsNone(
                cached_payload["identity"]["birth_year"]
            )
            self.assertNotIn(
                "manual_supplement_outcomes",
                cached_payload,
            )
            self.assertNotIn(
                "supplemental_sources",
                cached_payload,
            )
            self.assertNotIn(
                "manual_supplements",
                cached_payload.get("raw_payload", {}),
            )
            before = cache_path.read_bytes()

            completed = completion.run_p0_horse_completion_adapter(
                request,
                source_client=client,
            )

            self.assertTrue(completed["retrieval"]["cache_hit"])
            self.assertEqual(completed["identity"]["birth_year"], 2021)
            self.assertIn(
                "manual_supplement",
                {
                    row["evidence_role"]
                    for row in completed["source_evidence"]
                },
            )
            self.assertEqual(cache_path.read_bytes(), before)
            self.assertEqual(transport.calls, [])

            conflicting_cache = deepcopy(base_payload)
            conflicting_cache["identity"]["birth_year"] = 2021
            cache_path.write_text(
                json.dumps(conflicting_cache, ensure_ascii=False),
                encoding="utf-8",
            )
            conflict_client = (
                source_clients.build_p0_horse_completion_source_client(
                    RacingRegion.UNITED_KINGDOM,
                    transport=transport,
                    manual_supplements_by_candidate={
                        candidate_key: [manual_row(2022)],
                    },
                )
            )
            with self.assertRaisesRegex(
                source_clients.P0HorseSourceBlocked,
                r"source_conflict: identity\.birth_year",
            ):
                completion.run_p0_horse_completion_adapter(
                    request,
                    source_client=conflict_client,
                )

            already_applied = (
                source_clients.merge_reviewed_manual_supplements(
                    base_payload,
                    [manual_row(2021)],
                )
            )
            replay = source_clients.merge_reviewed_manual_supplements(
                already_applied,
                [manual_row(2021)],
            )
            self.assertEqual(
                replay["manual_supplement_outcomes"][0]["status"],
                "already_applied",
            )
            cache_path.write_text(
                json.dumps(already_applied, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                completion.P0HorseCompletionSourceError,
                "canonical source cache contains manual supplements",
            ):
                completion.run_p0_horse_completion_adapter(
                    request,
                    source_client=client,
                )
            changed_note = manual_row(2021)
            changed_note["source"]["evidence_note"] = (
                "Different evidence note"
            )
            with self.assertRaisesRegex(
                source_clients.P0HorseSourceBlocked,
                r"manual_target_not_empty: identity\.birth_year",
            ):
                source_clients.merge_reviewed_manual_supplements(
                    already_applied,
                    [changed_note],
                )

    def test_canonical_cache_validator_rejects_every_manual_marker(self):
        source_clients = _source_module()
        cases = {
            "top_level_outcomes": lambda payload: payload.update(
                manual_supplement_outcomes=[]
            ),
            "field_provenance": lambda payload: payload.update(
                field_provenance={
                    "identity.birth_year": {
                        "entry_method": "manual_review",
                    }
                }
            ),
            "supplemental_sources": lambda payload: payload.update(
                supplemental_sources=[
                    {"evidence_role": "manual_supplement"}
                ]
            ),
            "raw_manual_rows": lambda payload: payload.update(
                raw_payload={"manual_supplements": []}
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(marker=label):
                payload = _complete_source_payload(
                    RacingRegion.UNITED_KINGDOM
                )
                mutate(payload)
                with self.assertRaisesRegex(
                    source_clients.P0HorseSourceBlocked,
                    "canonical source cache contains manual supplements",
                ):
                    source_clients.validate_p0_horse_source_cache(payload)

    def test_canonical_validator_rechecks_markers_after_json_normalization(self):
        source_clients = _source_module()

        class DeceptiveStr(str):
            __hash__ = str.__hash__

            def __eq__(self, other):
                if str(other) in {
                    "manual_review",
                    "manual_supplement",
                    "manual_supplements",
                    "manual_supplement_outcomes",
                }:
                    return False
                return super().__eq__(other)

        value_marker = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        value_marker["field_provenance"] = {
            "identity.birth_year": {
                "entry_method": DeceptiveStr("manual_review"),
            }
        }
        key_marker = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        key_marker["raw_payload"] = {
            DeceptiveStr("manual_supplements"): []
        }
        for label, payload in (
            ("value_subclass", value_marker),
            ("key_subclass", key_marker),
        ):
            for gate_name, invoke in (
                (
                    "purity_gate",
                    lambda: source_clients
                    .reject_manual_supplements_from_canonical_source_payload(
                        payload
                    ),
                ),
                (
                    "validator",
                    lambda: source_clients.validate_p0_horse_source_cache(
                        payload
                    ),
                ),
            ):
                with self.subTest(
                    case=label,
                    gate=gate_name,
                ), self.assertRaisesRegex(
                    source_clients.P0HorseSourceBlocked,
                    "canonical source cache contains manual supplements",
                ):
                    invoke()

        valid = source_clients.validate_p0_horse_source_cache(
            _complete_source_payload(RacingRegion.UNITED_KINGDOM)
        )
        self.assertEqual(valid["region"], RacingRegion.UNITED_KINGDOM)
        self.assertIs(type(valid["region"]), str)

    def test_canonical_validator_requires_source_total_provenance_and_authority(self):
        source_clients = _source_module()
        cases = {
            "official_start_count_source": (
                "",
                "missing_official_start_count_source",
            ),
            "official_start_count_source_url": (
                "",
                "missing_official_start_count_source_url",
            ),
            "official_start_count_verified_at": (
                "",
                "missing_official_start_count_verified_at",
            ),
            "record_authority_status": (
                "unsupported",
                "invalid_record_authority_status",
            ),
        }
        for field_name, (value, message) in cases.items():
            with self.subTest(field=field_name):
                payload = _complete_source_payload(
                    RacingRegion.UNITED_KINGDOM
                )
                payload["career"][field_name] = value
                with self.assertRaisesRegex(
                    source_clients.P0HorseSourceBlocked,
                    message,
                ):
                    source_clients.validate_p0_horse_source_cache(payload)

        naive_time = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        naive_time["career"]["official_start_count_verified_at"] = (
            "2026-07-18T00:00:00"
        )
        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "missing_official_start_count_verified_at",
        ):
            source_clients.validate_p0_horse_source_cache(naive_time)

    def test_canonical_validator_checks_shape_before_deepcopy(self):
        source_clients = _source_module()
        too_deep = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        deep_root: dict[str, Any] = {}
        cursor = deep_root
        for _index in range(1200):
            child: dict[str, Any] = {}
            cursor["next"] = child
            cursor = child
        too_deep["raw_payload"] = deep_root

        class ExplodingDeepcopy:
            def __deepcopy__(self, memo):
                raise AssertionError("deepcopy must not run")

        class ExplodingDict(dict):
            def __deepcopy__(self, memo):
                raise AssertionError("container deepcopy must not run")

        class MutatingList(list):
            def __deepcopy__(self, memo):
                return [{"entry_method": "manual_review"}]

        non_json = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        non_json["raw_payload"] = {
            "value": ExplodingDeepcopy(),
        }
        dict_subclass = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        dict_subclass["raw_payload"] = ExplodingDict()
        list_subclass = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        list_subclass["raw_payload"] = {
            "value": MutatingList(),
        }
        cases = (
            ("too_deep", too_deep, "exceeds maximum depth"),
            ("non_json", non_json, "contains a non-JSON value"),
            (
                "dict_subclass",
                dict_subclass,
                "contains a non-JSON value",
            ),
            (
                "list_subclass",
                list_subclass,
                "contains a non-JSON value",
            ),
        )
        for label, payload, expected_error in cases:
            with self.subTest(case=label), self.assertRaisesRegex(
                source_clients.P0HorseSourceBlocked,
                expected_error,
            ):
                source_clients.validate_p0_horse_source_cache(payload)

    def test_source_merge_helpers_normalize_inputs_before_copying(self):
        source_clients = _source_module()

        class ExplodingDict(dict):
            def __deepcopy__(self, memo):
                raise AssertionError("merge deepcopy must not run")

        class MutatingList(list):
            def __deepcopy__(self, memo):
                return [{"entry_method": "manual_review"}]

        primary = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        primary["raw_payload"] = {
            "value": ExplodingDict(),
        }
        cases = (
            (
                "manual_primary",
                lambda: source_clients.merge_reviewed_manual_supplements(
                    primary,
                    [],
                ),
            ),
            (
                "automatic_primary",
                lambda: source_clients.merge_p0_horse_source_payloads(
                    primary,
                    [],
                ),
            ),
            (
                "manual_rows",
                lambda: source_clients.merge_reviewed_manual_supplements(
                    _complete_source_payload(
                        RacingRegion.UNITED_KINGDOM
                    ),
                    MutatingList(),
                ),
            ),
            (
                "automatic_rows",
                lambda: source_clients.merge_p0_horse_source_payloads(
                    _complete_source_payload(
                        RacingRegion.UNITED_KINGDOM
                    ),
                    MutatingList(),
                ),
            ),
        )
        for label, invoke in cases:
            with self.subTest(case=label), self.assertRaisesRegex(
                source_clients.P0HorseSourceBlocked,
                "contains a non-JSON value",
            ):
                invoke()

    def test_network_source_payload_with_manual_marker_is_not_cached(self):
        class DeceptiveStr(str):
            def __eq__(self, other):
                if str(other) == "manual_review":
                    return False
                return super().__eq__(other)

        direct_marker = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        direct_marker["field_provenance"] = {
            "basic_profile.breeder_name": {
                "entry_method": "manual_review",
                "evidence_role": "manual_supplement",
            }
        }
        deceptive_marker = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        deceptive_marker["field_provenance"] = {
            "basic_profile.breeder_name": {
                "entry_method": DeceptiveStr("manual_review"),
            }
        }
        tuple_marker = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        tuple_marker["raw_payload"] = {
            "nested": ({"entry_method": "manual_review"},)
        }
        cycle_marker = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        cycle: dict[str, Any] = {}
        cycle["self"] = cycle
        cycle_marker["raw_payload"] = cycle
        deep_marker = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        deep_root: dict[str, Any] = {}
        cursor = deep_root
        for _index in range(
            _source_module().CANONICAL_JSON_MAX_DEPTH + 2
        ):
            child: dict[str, Any] = {}
            cursor["next"] = child
            cursor = child
        deep_marker["raw_payload"] = deep_root
        cases = (
            (
                "direct_marker",
                direct_marker,
                "canonical source cache contains manual supplements",
            ),
            (
                "deceptive_string_marker",
                deceptive_marker,
                "canonical source cache contains manual supplements",
            ),
            (
                "tuple_container",
                tuple_marker,
                "contains a non-JSON value",
            ),
            (
                "cycle",
                cycle_marker,
                "contains a circular reference",
            ),
            (
                "too_deep",
                deep_marker,
                "exceeds maximum depth",
            ),
        )
        for label, mixed_payload, expected_error in cases:
            with self.subTest(case=label), TemporaryDirectory() as temporary_dir:
                cache_path = Path(temporary_dir) / "source-cache.json"

                class MixedSourceClient:
                    last_request_count = 1

                    def fetch(self, request):
                        return deepcopy(mixed_payload)

                with self.assertRaisesRegex(
                    completion.P0HorseCompletionSourceError,
                    expected_error,
                ):
                    completion.run_p0_horse_completion_adapter(
                        _request(
                            RacingRegion.UNITED_KINGDOM,
                            cache_path=cache_path,
                        ),
                        source_client=MixedSourceClient(),
                    )
                self.assertFalse(cache_path.exists())

    def test_source_fusion_fills_only_missing_fields_and_preserves_primary_career(self):
        source_clients = _source_module()
        primary = _complete_source_payload(RacingRegion.UNITED_KINGDOM)
        primary["basic_profile"]["country"] = ""
        primary["basic_profile"]["breeder_name"] = ""
        supplement = {
            "source": {
                "name": "racing_post",
                "url": "https://www.racingpost.com/profile/horse/1/source-test",
                "external_horse_id": "rp-1",
                "fetched_at": "2026-07-18T01:00:00Z",
            },
            "identity": {
                "horse_name": "SOURCE TEST",
                "sire_name": "Test Sire",
                "dam_name": "Test Dam",
                "birth_year": 2021,
            },
            "basic_profile": {
                "country": "FR",
                "breeder_name": "Test Breeder",
            },
            "pedigree": {},
            "raw_payload": {"profile_kind": "supplement"},
        }

        merged = source_clients.merge_p0_horse_source_payloads(
            primary,
            [supplement],
        )

        self.assertEqual(merged["source"], primary["source"])
        self.assertEqual(merged["career"], primary["career"])
        self.assertEqual(merged["basic_profile"]["country"], "FR")
        self.assertEqual(
            merged["basic_profile"]["breeder_name"],
            "Test Breeder",
        )
        self.assertEqual(
            merged["field_provenance"]["basic_profile.country"][
                "source_name"
            ],
            "racing_post",
        )
        self.assertEqual(
            merged["field_provenance"]["basic_profile.owner_name"][
                "source_name"
            ],
            "sporting_life",
        )
        self.assertEqual(
            merged["supplemental_sources"],
            [supplement["source"]],
        )
        normalized = completion.REGION_ADAPTERS[
            RacingRegion.UNITED_KINGDOM
        ].normalize(
            merged,
            _request(
                RacingRegion.UNITED_KINGDOM,
                external_horse_id="horse-1",
                candidate_source_name="sporting_life",
            ),
        )
        self.assertEqual(
            {
                (row["source_name"], row["evidence_role"])
                for row in normalized["source_evidence"]
            },
            {
                ("sporting_life", "completion_source"),
                ("sporting_life", "reviewed_candidate"),
                ("racing_post", "supplemental_completion_source"),
            },
        )

    def test_source_fusion_blocks_nonempty_field_conflicts(self):
        source_clients = _source_module()
        primary = _complete_source_payload(RacingRegion.UNITED_STATES)
        supplement = {
            "source": {
                "name": "equibase",
                "url": "https://www.equibase.com/profiles/Results.cfm?refno=1",
                "external_horse_id": "equibase-1",
                "fetched_at": "2026-07-18T01:00:00Z",
            },
            "identity": {
                "horse_name": "SOURCE TEST",
                "sire_name": "Test Sire",
                "dam_name": "Test Dam",
                "birth_year": 2021,
            },
            "basic_profile": {
                "birth_date": "2021-02-04",
            },
            "pedigree": {},
        }

        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            r"source_conflict: basic_profile\.birth_date",
        ):
            source_clients.merge_p0_horse_source_payloads(
                primary,
                [supplement],
            )

        self.assertEqual(
            primary["basic_profile"]["birth_date"],
            "2021-02-03",
        )

    def test_source_fusion_requires_provider_id_or_complete_four_field_identity(self):
        source_clients = _source_module()
        primary = _complete_source_payload(RacingRegion.UNITED_KINGDOM)
        primary["identity"]["sire_name"] = ""
        supplement = {
            "source": {
                "name": "racing_post",
                "url": "https://www.racingpost.com/profile/horse/1/source-test",
                "external_horse_id": "rp-1",
                "fetched_at": "2026-07-18T01:00:00Z",
            },
            "identity": {
                "horse_name": "SOURCE TEST",
                "sire_name": "Different Same-name Sire",
                "dam_name": "Test Dam",
                "birth_year": 2021,
            },
            "basic_profile": {"country": "FR"},
            "pedigree": {},
        }

        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "supplemental_identity_incomplete",
        ):
            source_clients.merge_p0_horse_source_payloads(
                primary,
                [supplement],
            )

        same_provider = deepcopy(supplement)
        same_provider["source"].update(
            {
                "name": "sporting_life",
                "external_horse_id": "horse-1",
                "url": (
                    "https://www.sportinglife.com/racing/profiles/"
                    "horse/source-test"
                ),
            }
        )
        same_provider["identity"]["sire_name"] = "Test Sire"
        same_provider["basic_profile"]["country"] = primary["basic_profile"]["country"]
        merged = source_clients.merge_p0_horse_source_payloads(
            primary,
            [same_provider],
        )
        self.assertEqual(merged["identity"]["sire_name"], "Test Sire")

    def test_source_fusion_rejects_supplemental_career_or_unapproved_provider(self):
        source_clients = _source_module()
        primary = _complete_source_payload(RacingRegion.HONG_KONG)
        supplement = {
            "source": {
                "name": "unreviewed_source",
                "url": "https://example.test/horse/1",
                "external_horse_id": "other-1",
                "fetched_at": "2026-07-18T01:00:00Z",
            },
            "identity": {"horse_name": "SOURCE TEST"},
            "basic_profile": {},
            "pedigree": {},
            "career": {"source_start_count": 1, "records": [{}]},
        }

        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "supplemental_career_not_allowed",
        ):
            source_clients.merge_p0_horse_source_payloads(
                primary,
                [supplement],
            )

        supplement.pop("career")
        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "supplemental_provider_not_allowed",
        ):
            source_clients.merge_p0_horse_source_payloads(
                primary,
                [supplement],
            )

    def test_source_fusion_and_cache_reject_unusable_urls(self):
        source_clients = _source_module()
        primary = _complete_source_payload(RacingRegion.UNITED_KINGDOM)
        supplement = {
            "source": {
                "name": "sporting_life",
                "url": "https://bad host.example/profile",
                "external_horse_id": "horse-1",
                "fetched_at": "2026-07-18T01:00:00Z",
            },
            "identity": deepcopy(primary["identity"]),
            "basic_profile": {},
            "pedigree": {},
        }
        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "source URL",
        ):
            source_clients.merge_p0_horse_source_payloads(
                primary,
                [supplement],
            )

        invalid_cache_urls = (
            ("source", "url", "https://bad host.example/profile"),
            (
                "career",
                "official_start_count_source_url",
                "https://example.com:not-a-port/profile",
            ),
        )
        for group, field, value in invalid_cache_urls:
            with self.subTest(group=group, field=field):
                payload = _complete_source_payload(
                    RacingRegion.UNITED_KINGDOM
                )
                payload[group][field] = value
                with self.assertRaises(
                    source_clients.P0HorseSourceBlocked
                ):
                    source_clients.validate_p0_horse_source_cache(payload)

        record_url = _complete_source_payload(
            RacingRegion.UNITED_KINGDOM
        )
        record_url["career"]["records"][0]["source_url"] = (
            "https://bad host.example/race"
        )
        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "lacks core evidence",
        ):
            source_clients.validate_p0_horse_source_cache(record_url)

    def test_cache_rejects_structured_hard_fields_and_invalid_dates(self):
        source_clients = _source_module()
        cases = (
            (
                "structured_owner",
                lambda payload: payload["basic_profile"].update(
                    owner_name={"name": "Owner"}
                ),
                "missing_hard_fields",
            ),
            (
                "invalid_birth_date",
                lambda payload: payload["basic_profile"].update(
                    birth_date="2021-99-99"
                ),
                "invalid_hard_field_format",
            ),
            (
                "structured_pedigree",
                lambda payload: payload["pedigree"].update(
                    sire_sire=["Sire Sire"]
                ),
                "missing_two_generation_pedigree",
            ),
            (
                "invalid_race_date",
                lambda payload: payload["career"]["records"][0].update(
                    race_date="not-a-date"
                ),
                "invalid race_date",
            ),
        )
        for label, mutate, message in cases:
            with self.subTest(case=label):
                payload = _complete_source_payload(
                    RacingRegion.UNITED_KINGDOM
                )
                mutate(payload)
                with self.assertRaisesRegex(
                    source_clients.P0HorseSourceBlocked,
                    message,
                ):
                    source_clients.validate_p0_horse_source_cache(payload)

    def test_factory_routes_all_regions_and_network_is_disabled_by_default(self):
        source_clients = _source_module()
        expected_providers = {
            RacingRegion.JAPAN: "jbis",
            RacingRegion.HONG_KONG: "hkjc",
            RacingRegion.UNITED_KINGDOM: "sporting_life",
            RacingRegion.FRANCE: "geny",
            RacingRegion.UNITED_STATES: "hrn",
        }
        for region, expected_provider in expected_providers.items():
            with self.subTest(region=region):
                transport = RejectingTransport()
                client = source_clients.build_p0_horse_completion_source_client(
                    region,
                    transport=transport,
                )
                self.assertEqual(client.region, region)
                self.assertEqual(client.provider_name, expected_provider)
                with self.assertRaises(completion.P0HorseCompletionNetworkDisabled):
                    client.fetch(_request(region, allow_network=False))
                self.assertEqual(transport.calls, [])

    def test_jbis_resolves_name_and_parses_full_profile_pedigree_and_career(self):
        transport = ScriptedTransport(
            [
                StubResponse(JBIS_SEARCH_HTML, url="https://www.jbis.or.jp/search/"),
                StubResponse(
                    JBIS_PROFILE_HTML,
                    url="https://www.jbis.or.jp/horse/0000123456/",
                ),
                StubResponse(
                    JBIS_RECORD_HTML,
                    url="https://www.jbis.or.jp/horse/0000123456/record/",
                ),
            ]
        )
        payload, _client = _fetch(
            RacingRegion.JAPAN,
            transport,
            _request(RacingRegion.JAPAN, horse_name="ソーステスト"),
        )

        self.assertEqual(payload["schema_version"], completion.SOURCE_CACHE_SCHEMA_VERSION)
        self.assertEqual(payload["source"]["name"], "jbis")
        self.assertEqual(payload["source"]["external_horse_id"], "0000123456")
        self.assertEqual(payload["identity"]["horse_name"], "ソーステスト")
        self.assertEqual(payload["identity"]["birth_year"], 2021)
        self.assertTrue(
            set(completion.REQUIRED_BASIC_PROFILE_FIELDS).issubset(
                payload["basic_profile"]
            )
        )
        self.assertTrue(
            set(completion.REQUIRED_PEDIGREE_FIELDS).issubset(payload["pedigree"])
        )
        self.assertEqual(payload["career"]["source_start_count"], 3)
        self.assertEqual(
            payload["career"]["official_start_count_source"],
            "jbis",
        )
        self.assertEqual(
            payload["career"]["official_start_count_source_url"],
            payload["source"]["url"],
        )
        self.assertEqual(
            payload["career"]["official_start_count_verified_at"],
            payload["source"]["fetched_at"],
        )
        self.assertEqual(len(payload["career"]["records"]), 3)
        self.assertEqual(
            [record["external_race_id"] for record in payload["career"]["records"]],
            ["JBIS-R1", "JBIS-R2", "JBIS-R3"],
        )
        self.assertIn("新馬戦", [record["race_name"] for record in payload["career"]["records"]])
        self.assertEqual(len(transport.calls), 3)

    def test_hkjc_parses_identity_two_generation_pedigree_and_local_overseas_form(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    HKJC_PROFILE_HTML,
                    url="https://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=HK_2024_H123",
                )
            ]
        )
        request = _request(
            RacingRegion.HONG_KONG,
            horse_name="FOREVER SOURCE",
            external_horse_id="HK_2024_H123",
            candidate_source_name="hkjc",
        )
        payload, _client = _fetch(RacingRegion.HONG_KONG, transport, request)
        normalized = completion.REGION_ADAPTERS[RacingRegion.HONG_KONG].normalize(
            payload,
            request,
        )

        self.assertEqual(payload["source"]["external_horse_id"], "HK_2024_H123")
        self.assertEqual(len(payload["career"]["records"]), 4)
        self.assertEqual(payload["career"]["source_start_count"], 3)
        self.assertTrue(any(record.get("is_overseas") for record in payload["career"]["records"]))
        self.assertTrue(
            set(completion.REQUIRED_PEDIGREE_FIELDS).issubset(payload["pedigree"])
        )
        statuses = {record["result_status"] for record in normalized["race_records"]}
        self.assertIn("withdrawn", statuses)
        self.assertIn("won", statuses)
        self.assertEqual(normalized["career_history"]["official_or_source_start_count"], 3)
        self.assertEqual(normalized["career_history"]["collected_start_count"], 3)
        self.assertEqual(normalized["career_history"]["overseas_start_count"], 1)
        self.assertEqual(normalized["career_history"]["gap_count"], 0)
        self.assertEqual(
            sum(
                record["start_status"] == "did_not_start"
                for record in normalized["race_records"]
            ),
            1,
        )

    def test_hkjc_real_southern_legend_shape_keeps_three_unique_overseas_starts(self):
        html = (
            FIXTURE_ROOT / "hkjc_southern_legend_overseas.html"
        ).read_text(encoding="utf-8")
        transport = ScriptedTransport(
            [
                StubResponse(
                    html,
                    url=(
                        "https://racing.hkjc.com/racing/information/English/"
                        "Horse/Horse.aspx?HorseId=HK_2017_A252"
                    ),
                )
            ]
        )
        request = _request(
            RacingRegion.HONG_KONG,
            horse_name="SOUTHERN LEGEND",
            external_horse_id="HK_2017_A252",
            candidate_source_name="hkjc",
        )
        client = _source_module()._HKJCClient(transport)

        payload = client.fetch_source_payload(request)
        overseas = [
            record
            for record in payload["career"]["records"]
            if record.get("is_overseas")
        ]

        self.assertEqual(payload["career"]["source_start_count"], 47)
        self.assertEqual(len(overseas), 3)
        self.assertEqual(
            {record["race_date"] for record in overseas},
            {"2018-05-26", "2019-03-30", "2019-05-25"},
        )
        self.assertEqual(len({record["external_race_id"] for record in overseas}), 3)
        self.assertTrue(
            all(
                record["external_race_id"].startswith("hkjc-overseas-")
                for record in overseas
            )
        )

    def test_hkjc_real_beauty_only_shape_deduplicates_tokyo_overseas_row(self):
        html = (
            FIXTURE_ROOT / "hkjc_beauty_only_overseas.html"
        ).read_text(encoding="utf-8")
        transport = ScriptedTransport(
            [
                StubResponse(
                    html,
                    url=(
                        "https://racing.hkjc.com/racing/information/English/"
                        "Horse/Horse.aspx?HorseId=HK_2014_S411"
                    ),
                )
            ]
        )
        request = _request(
            RacingRegion.HONG_KONG,
            horse_name="BEAUTY ONLY",
            external_horse_id="HK_2014_S411",
            candidate_source_name="hkjc",
        )
        client = _source_module()._HKJCClient(transport)

        payload = client.fetch_source_payload(request)
        overseas = [
            record
            for record in payload["career"]["records"]
            if record.get("is_overseas")
        ]

        self.assertEqual(payload["career"]["source_start_count"], 47)
        self.assertEqual(len(overseas), 1)
        self.assertEqual(overseas[0]["race_date"], "2017-06-04")
        self.assertIn("TOKYO", overseas[0]["racecourse"])

    def test_sporting_life_uses_next_data_full_form_and_preserves_ids_and_ordinary_races(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    _sporting_life_next_data(),
                    url="https://www.sportinglife.com/racing/profiles/horse/98765",
                )
            ]
        )
        payload, _client = _fetch(
            RacingRegion.UNITED_KINGDOM,
            transport,
            _request(
                RacingRegion.UNITED_KINGDOM,
                external_horse_id="98765",
                candidate_source_name="sporting_life",
            ),
        )

        records = payload["career"]["records"]
        self.assertEqual(payload["career"]["source_start_count"], 3)
        self.assertEqual(len(records), 3)
        self.assertEqual(
            [record["external_race_id"] for record in records],
            ["SL-R1", "SL-R2", "SL-R3"],
        )
        self.assertEqual(
            [record["external_result_id"] for record in records],
            ["SL-O1", "SL-O2", "SL-O3"],
        )
        self.assertIn("Ascot Handicap", [record["race_name"] for record in records])
        self.assertIn("__NEXT_DATA__", payload["raw_payload"]["profile_html_kind"])

    def test_sporting_life_maps_edwardstone_casualty_reason_to_official_status(self):
        runs = [
            {
                "race_id": f"ED-{index}",
                "result_id": f"ED-R-{index}",
                "date": race_date,
                "race_name": race_name,
                "course": course,
                "position": None,
                "casualty": {"reason": reason},
                "distance": distance,
            }
            for index, (
                race_date,
                race_name,
                course,
                reason,
                distance,
            ) in enumerate(
                [
                    (
                        "2024-12-07",
                        "Betfair Tingle Creek Chase (Grade 1) (GBB Race)",
                        "Sandown",
                        "Fell",
                        "1m 7f 119y",
                    ),
                    (
                        "2024-03-13",
                        "Betway Queen Mother Champion Chase (Grade 1) (GBB Race)",
                        "Cheltenham",
                        "Fell",
                        "1m 7f 199y",
                    ),
                    (
                        "2022-12-27",
                        "Ladbrokes Desert Orchid Chase (Grade 2) (GBB Race)",
                        "Kempton",
                        "UnseatedRider",
                        "2m",
                    ),
                    (
                        "2021-11-05",
                        "Jewson Stan Mellor Memorial Novices' Chase (GBB Race)",
                        "Warwick",
                        "BroughtDown",
                        "2m",
                    ),
                    (
                        "2020-12-29",
                        "attheraces.com Novices' Limited Handicap Chase (GBB Race)",
                        "Doncaster",
                        "UnseatedRider",
                        "2m 78y",
                    ),
                ],
                start=1,
            )
        ]
        transport = ScriptedTransport(
            [
                StubResponse(
                    _sporting_life_next_data(
                        horse_id="1014215",
                        horse_name="EDWARDSTONE",
                        runs_override=runs,
                    ),
                    url=(
                        "https://www.sportinglife.com/racing/profiles/horse/"
                        "1014215"
                    ),
                )
            ]
        )
        request = _request(
            RacingRegion.UNITED_KINGDOM,
            horse_name="EDWARDSTONE",
            external_horse_id="1014215",
            candidate_source_name="sporting_life",
        )

        payload, _client = _fetch(
            RacingRegion.UNITED_KINGDOM,
            transport,
            request,
        )
        normalized = completion.REGION_ADAPTERS[
            RacingRegion.UNITED_KINGDOM
        ].normalize(payload, request)

        by_date = {
            record["race_date"]: record
            for record in normalized["race_records"]
        }
        self.assertEqual(
            {
                race_date: (
                    record["official_result_code"],
                    record["result_status"],
                    record["start_status"],
                )
                for race_date, record in by_date.items()
            },
            {
                "2024-12-07": ("F", "did_not_finish", "started"),
                "2024-03-13": ("F", "did_not_finish", "started"),
                "2022-12-27": ("UR", "did_not_finish", "started"),
                "2021-11-05": ("BD", "did_not_finish", "started"),
                "2020-12-29": ("UR", "did_not_finish", "started"),
            },
        )
        self.assertEqual(
            normalized["career_history"]["collected_start_count"],
            5,
        )
        self.assertEqual(normalized["career_history"]["gap_count"], 0)
        self.assertTrue(
            all(record["casualty_reason_raw"] for record in by_date.values())
        )

    def test_sporting_life_na_result_requires_authoritative_supplement_evidence(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    _sporting_life_next_data(
                        horse_id="1059738",
                        horse_name="TOSCANA DU BERLAIS",
                        runs_override=[
                            {
                                "race_id": "SL-FR-1",
                                "result_id": "SL-FR-R-1",
                                "date": "2024-06-08",
                                "race_name": "Des Drags Chase - Grade 2",
                                "course": "Auteuil",
                                "position": None,
                                "casualty": {},
                                "distance": "2m 5f 191y",
                            }
                        ],
                    ),
                    url=(
                        "https://www.sportinglife.com/racing/profiles/horse/"
                        "1059738"
                    ),
                )
            ]
        )
        request = _request(
            RacingRegion.UNITED_KINGDOM,
            horse_name="TOSCANA DU BERLAIS",
            external_horse_id="1059738",
            candidate_source_name="sporting_life",
        )

        payload = _source_module()._SportingLifeClient(
            transport
        ).fetch_source_payload(request)
        record = payload["career"]["records"][0]
        result_evidence = next(
            evidence
            for evidence in record["field_evidence"]
            if evidence["field_name"] == "result"
        )

        self.assertEqual(record["finish"], "N/A")
        self.assertEqual(
            record["result_evidence_status"],
            "requires_authoritative_supplement",
        )
        self.assertEqual(result_evidence["direct_raw"]["value"], "N/A")
        self.assertEqual(
            result_evidence["direct_raw"]["source_name"],
            "sporting_life",
        )
        self.assertEqual(
            result_evidence["canonical_raw"]["status"],
            "not_collected",
        )
        self.assertEqual(result_evidence["normalized"]["status"], "blocked")
        evidence_by_field = {
            evidence["field_name"]: evidence
            for evidence in record["field_evidence"]
        }
        self.assertEqual(
            evidence_by_field["distance_text"]["direct_raw"]["value"],
            "2m 5f 191y",
        )
        self.assertEqual(
            evidence_by_field["distance_text"]["canonical_raw"]["status"],
            "not_collected",
        )
        self.assertEqual(
            evidence_by_field["distance_text"]["normalized"]["status"],
            "blocked",
        )
        self.assertEqual(
            evidence_by_field["race_classification"]["direct_raw"]["status"],
            "not_collected",
        )

    def test_authoritative_result_supplement_preserves_all_three_evidence_layers(self):
        record = {
            "finish": "N/A",
            "source_url": (
                "https://www.sportinglife.com/racing/profiles/horse/1059738"
            ),
            "result_evidence_status": "requires_authoritative_supplement",
            "field_evidence": [
                {
                    "field_name": "result",
                    "direct_raw": {
                        "value": "N/A",
                        "status": "observed",
                        "source_name": "sporting_life",
                        "source_url": (
                            "https://www.sportinglife.com/racing/profiles/"
                            "horse/1059738"
                        ),
                    },
                    "canonical_raw": {"status": "not_collected"},
                    "normalized": {"status": "blocked"},
                }
            ],
        }

        _source_module()._supplement_record_result_evidence(
            record,
            canonical_value="tbé",
            normalized_result_status="did_not_finish",
            source_name="france_galop",
            source_url=(
                "https://www.france-galop.com/sites/default/files/"
                "2024-07/24obst12.pdf"
            ),
            observed_at="2026-07-19T00:00:00+08:00",
            conversion_rule="france_galop_obstacle_result_map_v1",
        )

        result_evidence = record["field_evidence"][0]
        self.assertEqual(record["direct_result_value"], "N/A")
        self.assertEqual(record["finish"], "tbé")
        self.assertEqual(record["result_status"], "did_not_finish")
        self.assertEqual(record["result_evidence_status"], "canonical_verified")
        self.assertEqual(result_evidence["direct_raw"]["value"], "N/A")
        self.assertEqual(
            result_evidence["canonical_raw"]["source_name"],
            "france_galop",
        )
        self.assertEqual(result_evidence["canonical_raw"]["value"], "tbé")
        self.assertEqual(
            result_evidence["normalized"]["conversion_rule"],
            "france_galop_obstacle_result_map_v1",
        )

    def test_geny_parses_complete_career_instead_of_recent_summary(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    GENY_SEARCH_HTML,
                    url="https://www.geny.com/recherche?query=Source+Test",
                ),
                StubResponse(
                    GENY_CAREER_HTML,
                    url="https://www.geny.com/cheval/source-test_c123456_h2500000",
                )
            ]
        )
        payload, _client = _fetch(
            RacingRegion.FRANCE,
            transport,
            _request(
                RacingRegion.FRANCE,
                horse_name="Source Test",
                candidate_source_name="zeturf",
                external_horse_id="558083",
            ),
        )

        self.assertEqual(payload["source"]["name"], "geny")
        self.assertEqual(
            payload["source"]["external_horse_id"],
            "c123456_h2500000",
        )
        self.assertNotEqual(payload["source"]["external_horse_id"], "558083")
        self.assertEqual(payload["career"]["source_start_count"], 6)
        self.assertEqual(len(payload["career"]["records"]), 6)
        self.assertIn(
            "Prix Ordinaire D",
            [record["race_name"] for record in payload["career"]["records"]],
        )

    def test_geny_rate_limit_login_wall_and_recent_five_fail_closed(self):
        source_clients = _source_module()
        cases = [
            (
                "rate_limited",
                [StubResponse("Too Many Requests", status_code=429)],
                "rate_limited",
            ),
            (
                "login_wall",
                [
                    StubResponse(GENY_SEARCH_HTML),
                    StubResponse(
                        "<html><form id='login'><input name='password'></form></html>"
                    ),
                ],
                "login_wall",
            ),
            (
                "recent_five",
                [StubResponse(GENY_SEARCH_HTML), StubResponse(GENY_RECENT_FIVE_HTML)],
                "partial_career",
            ),
            (
                "ambiguous_identity",
                [StubResponse(GENY_SEARCH_AMBIGUOUS_HTML)],
                "ambiguous_identity",
            ),
        ]
        for label, responses, expected_reason in cases:
            with self.subTest(case=label):
                client = source_clients.build_p0_horse_completion_source_client(
                    RacingRegion.FRANCE,
                    transport=ScriptedTransport(responses),
                )
                with self.assertRaises(source_clients.P0HorseSourceBlocked) as caught:
                    client.fetch(
                        _request(
                            RacingRegion.FRANCE,
                            horse_name="Source Test",
                            candidate_source_name="zeturf",
                            external_horse_id="558083",
                        )
                    )
                self.assertIn(expected_reason, str(caught.exception))

    def test_us_resolves_provider_bound_identity_and_parses_all_results(self):
        transport = ScriptedTransport(
            [
                StubResponse(HRN_SEARCH_ONE_HTML, url="https://www.horseracingnation.com/search"),
                StubResponse(
                    HRN_PROFILE_HTML,
                    url="https://www.horseracingnation.com/horse/source-test",
                ),
                StubResponse(
                    HRN_RESULTS_HTML,
                    url="https://www.horseracingnation.com/horse/source-test/results",
                ),
            ]
        )
        request = _request(
            RacingRegion.UNITED_STATES,
            horse_name="Source Test",
            request_budget=3,
            expected_sire_name="Test Sire",
            expected_dam_name="Test Dam",
            expected_birth_year=2021,
        )
        payload, _client = _fetch(RacingRegion.UNITED_STATES, transport, request)
        normalized = completion.REGION_ADAPTERS[RacingRegion.UNITED_STATES].normalize(
            payload,
            request,
        )

        self.assertEqual(payload["source"]["name"], "hrn")
        self.assertEqual(payload["source"]["external_horse_id"], "source-test")
        self.assertIn("hrn:source-test", normalized["identity_keys"])
        self.assertEqual(payload["career"]["source_start_count"], 3)
        self.assertEqual(len(payload["career"]["records"]), 3)
        self.assertEqual(len(transport.calls), 3)
        self.assertIn(
            "did_not_finish",
            {record["result_status"] for record in normalized["race_records"]},
        )

    def test_us_same_name_ambiguity_fails_closed(self):
        source_clients = _source_module()
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.UNITED_STATES,
            transport=ScriptedTransport([StubResponse(HRN_SEARCH_AMBIGUOUS_HTML)]),
        )
        with self.assertRaises(source_clients.P0HorseSourceBlocked) as caught:
            client.fetch(
                _request(RacingRegion.UNITED_STATES, horse_name="Source Test")
            )
        self.assertIn("ambiguous_identity", str(caught.exception))

    def test_sporting_life_real_profile_shape_reaches_completeness_blocker(self):
        source_clients = _source_module()
        transport = ScriptedTransport(
            [
                StubResponse(
                    _sporting_life_real_profile_html(complete=False),
                    url="https://www.sportinglife.com/racing/profiles/horse/98765",
                )
            ]
        )
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.UNITED_KINGDOM,
            transport=transport,
        )
        request = _request(
            RacingRegion.UNITED_KINGDOM,
            external_horse_id="98765",
            candidate_source_name="sporting_life",
        )

        with self.assertRaises(source_clients.P0HorseSourceBlocked) as caught:
            client.fetch(request)

        reason = str(caught.exception)
        self.assertNotIn("invalid_next_data", reason)
        self.assertRegex(
            reason,
            r"missing_hard_fields|missing_two_generation_pedigree",
        )
        self.assertEqual(len(transport.calls), 1)

    def test_sporting_life_real_profile_shape_converts_previous_results_and_stats(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    _sporting_life_real_profile_html(complete=True),
                    url="https://www.sportinglife.com/racing/profiles/horse/98765",
                )
            ]
        )
        payload, _client = _fetch(
            RacingRegion.UNITED_KINGDOM,
            transport,
            _request(
                RacingRegion.UNITED_KINGDOM,
                external_horse_id="98765",
                candidate_source_name="sporting_life",
            ),
        )

        self.assertEqual(payload["source"]["external_horse_id"], "98765")
        self.assertEqual(payload["career"]["source_start_count"], 2)
        self.assertEqual(len(payload["career"]["records"]), 2)
        self.assertEqual(
            [record["external_race_id"] for record in payload["career"]["records"]],
            ["SL-REAL-R1", "SL-REAL-R2"],
        )
        self.assertEqual(
            [record["external_result_id"] for record in payload["career"]["records"]],
            ["SL-REAL-O1", "SL-REAL-O2"],
        )
        self.assertEqual(payload["basic_profile"]["breeder_name"], "Test Breeder")
        self.assertEqual(payload["pedigree"]["dam_dam"], "Dam Dam")

    def test_hkjc_real_retired_shape_parses_starts_before_completeness_blocker(self):
        source_clients = _source_module()
        transport = ScriptedTransport(
            [
                StubResponse(
                    _hkjc_real_retired_profile_html(complete=False),
                    url="https://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=HK_2024_H123",
                )
            ]
        )
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.HONG_KONG,
            transport=transport,
        )
        request = _request(
            RacingRegion.HONG_KONG,
            horse_name="FOREVER SOURCE",
            external_horse_id="HK_2024_H123",
            candidate_source_name="hkjc",
        )

        with self.assertRaises(source_clients.P0HorseSourceBlocked) as caught:
            client.fetch(request)

        reason = str(caught.exception)
        self.assertNotIn("missing_source_start_count", reason)
        self.assertRegex(
            reason,
            r"identity_incomplete|missing_hard_fields|"
            r"missing_two_generation_pedigree|partial_career",
        )
        self.assertEqual(len(transport.calls), 1)

    def test_hkjc_real_retired_shape_converts_all_form_records_when_complete(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    _hkjc_real_retired_profile_html(complete=True),
                    url="https://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=HK_2024_H123",
                )
            ]
        )
        payload, _client = _fetch(
            RacingRegion.HONG_KONG,
            transport,
            _request(
                RacingRegion.HONG_KONG,
                horse_name="FOREVER SOURCE",
                external_horse_id="HK_2024_H123",
                candidate_source_name="hkjc",
            ),
        )

        self.assertEqual(payload["career"]["source_start_count"], 3)
        self.assertEqual(len(payload["career"]["records"]), 3)
        self.assertEqual(
            [record["external_race_id"] for record in payload["career"]["records"]],
            ["101", "202", "303"],
        )
        self.assertEqual(
            [record["race_name"] for record in payload["career"]["records"]],
            ["Class 4 Handicap", "Class 3 Handicap", "Maiden Plate"],
        )
        self.assertEqual(payload["basic_profile"]["birth_date"], "2021-09-12")
        self.assertEqual(
            payload["basic_profile"]["trainer_name"],
            "Latest Trainer",
        )
        self.assertEqual(payload["pedigree"]["dam_dam"], "Dam Dam")

    def test_jbis_real_result_profile_and_div_record_shapes_are_supported(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    JBIS_REAL_SEARCH_HTML,
                    url="https://www.jbis.or.jp/horse/result/",
                ),
                StubResponse(
                    JBIS_REAL_PROFILE_HTML,
                    url="https://www.jbis.or.jp/horse/0000123456/",
                ),
                StubResponse(
                    JBIS_REAL_RECORD_HTML,
                    url="https://www.jbis.or.jp/horse/0000123456/record/",
                ),
            ]
        )
        payload, _client = _fetch(
            RacingRegion.JAPAN,
            transport,
            _request(RacingRegion.JAPAN, horse_name="ソーステスト"),
        )

        self.assertEqual(
            transport.calls[0]["url"],
            "https://www.jbis.or.jp/horse/result/"
            f"?keyword={quote_plus('ソーステスト')}&match=exact",
        )
        self.assertEqual(payload["source"]["name"], "jbis")
        self.assertEqual(payload["source"]["external_horse_id"], "0000123456")
        self.assertTrue(
            set(completion.REQUIRED_BASIC_PROFILE_FIELDS).issubset(
                payload["basic_profile"]
            )
        )
        self.assertTrue(
            set(completion.REQUIRED_PEDIGREE_FIELDS).issubset(payload["pedigree"])
        )
        self.assertEqual(payload["career"]["source_start_count"], 3)
        self.assertEqual(len(payload["career"]["records"]), 3)
        self.assertEqual(
            [record["external_race_id"] for record in payload["career"]["records"]],
            ["JBIS-REAL-R1", "JBIS-REAL-R2", "JBIS-REAL-R3"],
        )

    def test_jbis_excluded_row_is_preserved_without_counting_as_actual_start(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    JBIS_REAL_SEARCH_HTML,
                    url="https://www.jbis.or.jp/horse/result/",
                ),
                StubResponse(
                    JBIS_REAL_PROFILE_HTML,
                    url="https://www.jbis.or.jp/horse/0000123456/",
                ),
                StubResponse(
                    JBIS_EXCLUDED_RECORD_HTML,
                    url="https://www.jbis.or.jp/horse/0000123456/record/",
                ),
            ]
        )
        source_clients = _source_module()
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.JAPAN,
            transport=transport,
        )
        request = _request(
            RacingRegion.JAPAN,
            horse_name="ソーステスト",
            expected_sire_name="Test Sire",
            expected_dam_name="Test Dam",
            expected_birth_year=2021,
            request_budget=3,
        )

        normalized = completion.run_p0_horse_completion_adapter(
            request,
            source_client=client,
        )

        source_career = normalized["raw_payload"]["career"]
        self.assertEqual(source_career["source_start_count"], 1)
        self.assertEqual(len(source_career["records"]), 2)
        excluded_source = next(
            record
            for record in source_career["records"]
            if record["race_name"] == "4歳以上1勝クラス"
        )
        self.assertNotEqual(excluded_source["finish"], "**")
        self.assertEqual(len(normalized["race_records"]), 2)
        self.assertEqual(
            normalized["career_history"]["official_or_source_start_count"],
            1,
        )
        self.assertEqual(
            normalized["career_history"]["collected_start_count"],
            1,
        )
        self.assertEqual(normalized["career_history"]["gap_count"], 0)
        excluded_record = next(
            record
            for record in normalized["race_records"]
            if record["race_name"] == "4歳以上1勝クラス"
        )
        self.assertIn(
            excluded_record["result_status"],
            completion.NONSTART_STATUSES,
        )
        self.assertEqual(
            excluded_record["start_status"],
            "did_not_start",
        )
        self.assertEqual(len(transport.calls), 3)

    def test_jbis_explicit_cancel_status_cell_maps_to_scratched_nonstart(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    JBIS_REAL_SEARCH_HTML,
                    url="https://www.jbis.or.jp/horse/result/",
                ),
                StubResponse(
                    JBIS_REAL_PROFILE_HTML,
                    url="https://www.jbis.or.jp/horse/0000123456/",
                ),
                StubResponse(
                    _jbis_nonstart_record_html(status_cell="取消"),
                    url="https://www.jbis.or.jp/horse/0000123456/record/",
                ),
            ]
        )
        source_clients = _source_module()
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.JAPAN,
            transport=transport,
        )
        request = _request(
            RacingRegion.JAPAN,
            horse_name="ソーステスト",
            expected_sire_name="Test Sire",
            expected_dam_name="Test Dam",
            expected_birth_year=2021,
            request_budget=3,
        )

        normalized = completion.run_p0_horse_completion_adapter(
            request,
            source_client=client,
        )

        source_career = normalized["raw_payload"]["career"]
        self.assertEqual(source_career["source_start_count"], 1)
        self.assertEqual(len(source_career["records"]), 2)
        cancelled_source = next(
            record
            for record in source_career["records"]
            if record["race_name"] == "4歳以上1勝クラス"
        )
        self.assertEqual(cancelled_source["finish"], "scratched")
        cancelled_record = next(
            record
            for record in normalized["race_records"]
            if record["race_name"] == "4歳以上1勝クラス"
        )
        self.assertEqual(cancelled_record["result_status"], "scratched")
        self.assertEqual(cancelled_record["start_status"], "did_not_start")
        self.assertEqual(len(normalized["race_records"]), 2)
        self.assertEqual(
            normalized["career_history"]["collected_start_count"],
            1,
        )
        self.assertEqual(normalized["career_history"]["gap_count"], 0)

    def test_jbis_unknown_double_asterisk_with_ordinary_status_fails_closed(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    JBIS_REAL_SEARCH_HTML,
                    url="https://www.jbis.or.jp/horse/result/",
                ),
                StubResponse(
                    JBIS_REAL_PROFILE_HTML,
                    url="https://www.jbis.or.jp/horse/0000123456/",
                ),
                StubResponse(
                    _jbis_nonstart_record_html(status_cell="1着馬"),
                    url="https://www.jbis.or.jp/horse/0000123456/record/",
                ),
            ]
        )
        source_clients = _source_module()
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.JAPAN,
            transport=transport,
        )

        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "partial_career",
        ):
            client.fetch(
                _request(
                    RacingRegion.JAPAN,
                    horse_name="ソーステスト",
                    request_budget=3,
                )
            )

    def test_jbis_race_name_keywords_cannot_substitute_for_status_cell(self):
        source_clients = _source_module()
        for race_name in ("除外条件特別", "取消記念"):
            with self.subTest(race_name=race_name):
                transport = ScriptedTransport(
                    [
                        StubResponse(
                            JBIS_REAL_SEARCH_HTML,
                            url="https://www.jbis.or.jp/horse/result/",
                        ),
                        StubResponse(
                            JBIS_REAL_PROFILE_HTML,
                            url="https://www.jbis.or.jp/horse/0000123456/",
                        ),
                        StubResponse(
                            _jbis_nonstart_record_html(
                                status_cell="1着馬",
                                race_name=race_name,
                            ),
                            url=(
                                "https://www.jbis.or.jp/horse/"
                                "0000123456/record/"
                            ),
                        ),
                    ]
                )
                client = (
                    source_clients.build_p0_horse_completion_source_client(
                        RacingRegion.JAPAN,
                        transport=transport,
                    )
                )

                with self.assertRaisesRegex(
                    source_clients.P0HorseSourceBlocked,
                    "partial_career",
                ):
                    client.fetch(
                        _request(
                            RacingRegion.JAPAN,
                            horse_name="ソーステスト",
                            request_budget=3,
                        )
                    )

    def test_jbis_nonstart_status_requires_exact_value_and_present_cell_12(self):
        source_clients = _source_module()
        cases = (
            (
                "status_contains_excluded",
                _jbis_nonstart_record_html(status_cell="競走除外"),
            ),
            (
                "status_contains_cancelled",
                _jbis_nonstart_record_html(status_cell="取消扱い"),
            ),
            (
                "row_has_only_12_direct_cells",
                _jbis_nonstart_record_html(
                    status_cell="",
                    include_status_tail=False,
                ),
            ),
        )
        for label, record_html in cases:
            with self.subTest(case=label):
                transport = ScriptedTransport(
                    [
                        StubResponse(
                            JBIS_REAL_SEARCH_HTML,
                            url="https://www.jbis.or.jp/horse/result/",
                        ),
                        StubResponse(
                            JBIS_REAL_PROFILE_HTML,
                            url="https://www.jbis.or.jp/horse/0000123456/",
                        ),
                        StubResponse(
                            record_html,
                            url=(
                                "https://www.jbis.or.jp/horse/"
                                "0000123456/record/"
                            ),
                        ),
                    ]
                )
                client = (
                    source_clients.build_p0_horse_completion_source_client(
                        RacingRegion.JAPAN,
                        transport=transport,
                    )
                )

                with self.assertRaisesRegex(
                    source_clients.P0HorseSourceBlocked,
                    "partial_career",
                ):
                    client.fetch(
                        _request(
                            RacingRegion.JAPAN,
                            horse_name="ソーステスト",
                            request_budget=3,
                        )
                    )

    def test_hrn_direct_slug_fallback_reaches_completeness_blocker(self):
        source_clients = _source_module()
        cases = (
            ("Bullard", "Bullard"),
            ("Carson's Run", "Carsons_Run"),
        )
        for horse_name, expected_slug in cases:
            with self.subTest(horse_name=horse_name):
                transport = ScriptedTransport(
                    [
                        StubResponse(
                            _hrn_real_profile_html(
                                horse_name=horse_name,
                                complete=False,
                            ),
                            url=(
                                "https://www.horseracingnation.com/horse/"
                                f"{expected_slug}"
                            ),
                        )
                    ]
                )
                client = source_clients.build_p0_horse_completion_source_client(
                    RacingRegion.UNITED_STATES,
                    transport=transport,
                )

                with self.assertRaises(source_clients.P0HorseSourceBlocked) as caught:
                    client.fetch(
                        _request(
                            RacingRegion.UNITED_STATES,
                            horse_name=horse_name,
                            expected_sire_name="Test Sire",
                            expected_dam_name="Test Dam",
                            expected_birth_year=2021,
                        )
                    )

                self.assertEqual(
                    transport.calls[0]["url"],
                    "https://www.horseracingnation.com/horse/" + expected_slug,
                )
                reason = str(caught.exception)
                self.assertNotIn("identity_not_found", reason)
                self.assertRegex(
                    reason,
                    r"missing_hard_fields|missing_two_generation_pedigree",
                )

    def test_hrn_direct_slug_real_stats_and_table_succeed_when_complete(self):
        transport = ScriptedTransport(
            [
                StubResponse(
                    _hrn_real_profile_html(
                        horse_name="Bullard",
                        complete=True,
                    ),
                    url="https://www.horseracingnation.com/horse/Bullard",
                )
            ]
        )
        payload, _client = _fetch(
            RacingRegion.UNITED_STATES,
            transport,
            _request(
                RacingRegion.UNITED_STATES,
                horse_name="Bullard",
                expected_sire_name="Test Sire",
                expected_dam_name="Test Dam",
                expected_birth_year=2021,
            ),
        )

        self.assertEqual(
            transport.calls[0]["url"],
            "https://www.horseracingnation.com/horse/Bullard",
        )
        self.assertEqual(payload["source"]["external_horse_id"], "Bullard")
        self.assertEqual(payload["identity"]["horse_name"], "Bullard")
        self.assertEqual(payload["identity"]["sire_name"], "Test Sire")
        self.assertEqual(payload["identity"]["dam_name"], "Test Dam")
        self.assertEqual(payload["identity"]["birth_year"], 2021)
        self.assertEqual(payload["career"]["source_start_count"], 2)
        self.assertEqual(len(payload["career"]["records"]), 2)
        self.assertEqual(
            [record["external_race_id"] for record in payload["career"]["records"]],
            ["HRN-REAL-R1", "HRN-REAL-R2"],
        )

    def test_hrn_direct_slug_requires_complete_expected_identity(self):
        source_clients = _source_module()
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.UNITED_STATES,
            transport=ScriptedTransport(
                [
                    StubResponse(
                        _hrn_real_profile_html(
                            horse_name="Bullard",
                            complete=True,
                        ),
                        url="https://www.horseracingnation.com/horse/Bullard",
                    )
                ]
            ),
        )

        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "identity_incomplete: request",
        ):
            client.fetch(
                _request(
                    RacingRegion.UNITED_STATES,
                    horse_name="Bullard",
                )
            )

    def test_hrn_direct_slug_rejects_same_name_and_parents_with_wrong_birth_year(self):
        source_clients = _source_module()
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.UNITED_STATES,
            transport=ScriptedTransport(
                [
                    StubResponse(
                        _hrn_real_profile_html(
                            horse_name="Bullard",
                            complete=True,
                        ),
                        url="https://www.horseracingnation.com/horse/Bullard",
                    )
                ]
            ),
        )

        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "identity_mismatch: request birth_year",
        ):
            client.fetch(
                _request(
                    RacingRegion.UNITED_STATES,
                    horse_name="Bullard",
                    expected_sire_name="Test Sire",
                    expected_dam_name="Test Dam",
                    expected_birth_year=2020,
                )
            )

    def test_concurrent_cache_publish_is_no_clobber_and_returns_one_canonical_payload(self):
        payload_a = _complete_source_payload(RacingRegion.UNITED_KINGDOM)
        payload_b = deepcopy(payload_a)
        payload_a["basic_profile"]["owner_name"] = "Owner A"
        payload_a["career"]["records"][0]["race_name"] = "Canonical Race A"
        payload_b["basic_profile"]["owner_name"] = "Owner B"
        payload_b["career"]["records"][0]["race_name"] = "Canonical Race B"
        mismatches: list[dict[str, Any]] = []

        with TemporaryDirectory() as temp_dir:
            for iteration in range(20):
                cache_path = Path(temp_dir) / f"source-cache-{iteration}.json"
                barrier = threading.Barrier(2)
                request = _request(
                    RacingRegion.UNITED_KINGDOM,
                    cache_path=cache_path,
                    external_horse_id="horse-1",
                    candidate_source_name="sporting_life",
                )
                clients = (
                    BarrierSourceClient(barrier=barrier, payload=payload_a),
                    BarrierSourceClient(barrier=barrier, payload=payload_b),
                )

                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [
                        executor.submit(
                            completion.run_p0_horse_completion_adapter,
                            request,
                            source_client=client,
                        )
                        for client in clients
                    ]
                    results = [future.result(timeout=10) for future in futures]

                published = json.loads(cache_path.read_text(encoding="utf-8"))
                published_owner = published["basic_profile"]["owner_name"]
                returned_owners = [
                    result["basic_profile"]["owner_name"] for result in results
                ]
                if returned_owners != [published_owner, published_owner]:
                    mismatches.append(
                        {
                            "iteration": iteration,
                            "published_owner": published_owner,
                            "returned_owners": returned_owners,
                        }
                    )

        self.assertEqual(
            mismatches,
            [],
            "both concurrent callers must re-read the one published cache payload",
        )

    def test_network_fetch_writes_cache_then_offline_run_reuses_it(self):
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "source-cache.json"
            transport = ScriptedTransport(
                [
                    StubResponse(
                        _sporting_life_next_data(),
                        url="https://www.sportinglife.com/racing/profiles/horse/98765",
                    )
                ]
            )
            request = _request(
                RacingRegion.UNITED_KINGDOM,
                cache_path=cache_path,
                external_horse_id="98765",
                candidate_source_name="sporting_life",
            )
            source_clients = _source_module()
            client = source_clients.build_p0_horse_completion_source_client(
                RacingRegion.UNITED_KINGDOM,
                transport=transport,
            )

            first = completion.run_p0_horse_completion_adapter(
                request,
                source_client=client,
            )
            self.assertTrue(cache_path.is_file())
            self.assertEqual(
                json.loads(cache_path.read_text(encoding="utf-8"))["schema_version"],
                completion.SOURCE_CACHE_SCHEMA_VERSION,
            )
            self.assertEqual(
                [path.name for path in cache_path.parent.iterdir()],
                [cache_path.name],
            )

            offline_request = _request(
                RacingRegion.UNITED_KINGDOM,
                cache_path=cache_path,
                allow_network=False,
                external_horse_id="98765",
                candidate_source_name="sporting_life",
            )
            second = completion.run_p0_horse_completion_adapter(offline_request)
            self.assertFalse(first["retrieval"]["cache_hit"])
            self.assertTrue(second["retrieval"]["cache_hit"])
            self.assertEqual(len(transport.calls), 1)

    def test_existing_valid_cache_is_not_replaced_or_refetched(self):
        with TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "source-cache.json"
            original = _complete_source_payload(RacingRegion.JAPAN)
            original["source"]["external_horse_id"] = "already-reviewed"
            cache_path.write_text(
                json.dumps(original, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            before = cache_path.read_bytes()
            transport = RejectingTransport()
            source_clients = _source_module()
            client = source_clients.build_p0_horse_completion_source_client(
                RacingRegion.JAPAN,
                transport=transport,
            )
            request = _request(
                RacingRegion.JAPAN,
                cache_path=cache_path,
                external_horse_id="already-reviewed",
                candidate_source_name="jbis",
            )

            result = completion.run_p0_horse_completion_adapter(
                request,
                source_client=client,
            )

            self.assertTrue(result["retrieval"]["cache_hit"])
            self.assertEqual(cache_path.read_bytes(), before)
            self.assertEqual(transport.calls, [])

    def test_request_budget_and_batch_limit_fail_closed_before_extra_transport(self):
        source_clients = _source_module()
        budget_transport = ScriptedTransport(
            [
                StubResponse(JBIS_SEARCH_HTML),
                StubResponse(JBIS_PROFILE_HTML),
                StubResponse(JBIS_RECORD_HTML),
            ]
        )
        budget_client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.JAPAN,
            transport=budget_transport,
        )
        with self.assertRaises(source_clients.P0HorseSourceBlocked) as caught:
            budget_client.fetch(
                _request(RacingRegion.JAPAN, request_budget=1)
            )
        self.assertIn("request_budget_exceeded", str(caught.exception))
        self.assertEqual(len(budget_transport.calls), 1)

        batch_transport = ScriptedTransport(
            [
                StubResponse(_sporting_life_next_data()),
                StubResponse(_sporting_life_next_data()),
            ]
        )
        batch_client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.UNITED_KINGDOM,
            transport=batch_transport,
        )
        batch_client.fetch(
            _request(
                RacingRegion.UNITED_KINGDOM,
                batch_limit=1,
                external_horse_id="98765",
                candidate_source_name="sporting_life",
            )
        )
        with self.assertRaises(source_clients.P0HorseSourceBlocked) as caught:
            batch_client.fetch(
                _request(
                    RacingRegion.UNITED_KINGDOM,
                    batch_limit=1,
                    external_horse_id="98766",
                    candidate_source_name="sporting_life",
                )
            )
        self.assertIn("batch_limit_exceeded", str(caught.exception))
        self.assertEqual(len(batch_transport.calls), 1)

    def test_source_client_rejects_unapproved_initial_and_redirect_hosts(self):
        source_clients = _source_module()
        initial_transport = ScriptedTransport([])
        initial_client = source_clients._HRNClient(initial_transport)
        request = _request(
            RacingRegion.UNITED_STATES,
            request_budget=2,
        )
        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "unapproved_source_url",
        ):
            initial_client._get("https://example.test/private", request)
        self.assertEqual(initial_transport.calls, [])

        redirect_transport = ScriptedTransport(
            [
                StubResponse(
                    "",
                    status_code=302,
                    headers={"Location": "https://example.test/private"},
                )
            ]
        )
        redirect_client = source_clients._HRNClient(redirect_transport)
        with self.assertRaisesRegex(
            source_clients.P0HorseSourceBlocked,
            "unapproved_source_url",
        ):
            redirect_client._get(
                "https://www.horseracingnation.com/horse/source-test",
                request,
            )
        self.assertEqual(len(redirect_transport.calls), 1)
        self.assertFalse(redirect_transport.calls[0]["allow_redirects"])

    def test_request_interval_applies_between_candidates_while_budget_resets_per_fetch(self):
        source_clients = _source_module()
        events: list[tuple[str, Any]] = []

        class EventTransport(ScriptedTransport):
            def get(self, url: str, **kwargs: Any) -> StubResponse:
                events.append(("get", url))
                return super().get(url, **kwargs)

        transport = EventTransport(
            [
                StubResponse(
                    _sporting_life_next_data(
                        horse_id="98765",
                        horse_name="SOURCE TEST ONE",
                    ),
                    url="https://www.sportinglife.com/racing/profiles/horse/98765",
                ),
                StubResponse(
                    _sporting_life_next_data(
                        horse_id="98766",
                        horse_name="SOURCE TEST TWO",
                    ),
                    url="https://www.sportinglife.com/racing/profiles/horse/98766",
                ),
            ]
        )
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.UNITED_KINGDOM,
            transport=transport,
        )
        first_request = _request(
            RacingRegion.UNITED_KINGDOM,
            candidate_key="external:sporting_life:98765",
            horse_name="SOURCE TEST ONE",
            external_horse_id="98765",
            candidate_source_name="sporting_life",
            request_budget=1,
            request_interval_seconds=8,
        )
        second_request = _request(
            RacingRegion.UNITED_KINGDOM,
            candidate_key="external:sporting_life:98766",
            horse_name="SOURCE TEST TWO",
            external_horse_id="98766",
            candidate_source_name="sporting_life",
            request_budget=1,
            request_interval_seconds=8,
        )

        with (
            patch.object(
                source_clients.time,
                "monotonic",
                side_effect=[100.0, 103.0, 108.0],
            ),
            patch.object(
                source_clients.time,
                "sleep",
                side_effect=lambda seconds: events.append(("sleep", seconds)),
            ) as sleep,
        ):
            first_payload = client.fetch(first_request)
            first_request_count = client.last_request_count
            second_payload = client.fetch(second_request)
            second_request_count = client.last_request_count

        self.assertEqual(first_payload["source"]["external_horse_id"], "98765")
        self.assertEqual(second_payload["source"]["external_horse_id"], "98766")
        self.assertEqual(first_request_count, 1)
        self.assertEqual(second_request_count, 1)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(
            {
                "sleep_calls": [
                    call.args for call in sleep.call_args_list
                ],
                "event_kinds": [event[0] for event in events],
            },
            {
                "sleep_calls": [(5.0,)],
                "event_kinds": ["get", "sleep", "get"],
            },
        )

    def test_failed_transport_counts_attempt_and_throttles_next_candidate(self):
        source_clients = _source_module()
        events: list[tuple[str, Any]] = []

        class ConnectionThenResponseTransport:
            def __init__(self):
                self.calls: list[str] = []

            def get(self, url: str, **kwargs: Any) -> StubResponse:
                self.calls.append(url)
                if len(self.calls) == 1:
                    events.append(("get_error", url))
                    raise ConnectionError("scripted connection failure")
                events.append(("get", url))
                return StubResponse(
                    _sporting_life_next_data(
                        horse_id="98766",
                        horse_name="SOURCE TEST TWO",
                    ),
                    url=(
                        "https://www.sportinglife.com/racing/profiles/"
                        "horse/98766"
                    ),
                )

        transport = ConnectionThenResponseTransport()
        client = source_clients.build_p0_horse_completion_source_client(
            RacingRegion.UNITED_KINGDOM,
            transport=transport,
        )
        first_request = _request(
            RacingRegion.UNITED_KINGDOM,
            candidate_key="external:sporting_life:98765",
            horse_name="SOURCE TEST ONE",
            external_horse_id="98765",
            candidate_source_name="sporting_life",
            request_budget=1,
            request_interval_seconds=8,
        )
        second_request = _request(
            RacingRegion.UNITED_KINGDOM,
            candidate_key="external:sporting_life:98766",
            horse_name="SOURCE TEST TWO",
            external_horse_id="98766",
            candidate_source_name="sporting_life",
            request_budget=1,
            request_interval_seconds=8,
        )

        with (
            patch.object(
                source_clients.time,
                "monotonic",
                side_effect=[100.0, 103.0, 108.0],
            ),
            patch.object(
                source_clients.time,
                "sleep",
                side_effect=lambda seconds: events.append(("sleep", seconds)),
            ) as sleep,
        ):
            with self.assertRaisesRegex(
                source_clients.P0HorseSourceBlocked,
                "transport_error: scripted connection failure",
            ):
                client.fetch(first_request)
            failed_request_count = client.last_request_count
            second_payload = client.fetch(second_request)
            second_request_count = client.last_request_count

        self.assertEqual(second_payload["source"]["external_horse_id"], "98766")
        self.assertEqual(
            {
                "failed_request_count": failed_request_count,
                "second_request_count": second_request_count,
                "transport_calls": len(transport.calls),
                "sleep_calls": [
                    call.args for call in sleep.call_args_list
                ],
                "event_kinds": [event[0] for event in events],
            },
            {
                "failed_request_count": 1,
                "second_request_count": 1,
                "transport_calls": 2,
                "sleep_calls": [(5.0,)],
                "event_kinds": ["get_error", "sleep", "get"],
            },
        )

    def test_all_regions_reject_incomplete_hard_fields_pedigree_or_career(self):
        source_clients = _source_module()
        missing_cases = (
            ("hard_field", lambda payload: payload["basic_profile"].pop("owner_name")),
            ("pedigree", lambda payload: payload["pedigree"].pop("dam_dam")),
            (
                "source_start_count",
                lambda payload: payload["career"].pop("source_start_count"),
            ),
            ("career_records", lambda payload: payload["career"].update(records=[])),
        )
        for region in completion.REVIEWED_CANDIDATE_REGIONS:
            valid_payload = _complete_source_payload(region)
            validated = source_clients.validate_p0_horse_source_cache(valid_payload)
            self.assertEqual(
                validated["schema_version"],
                completion.SOURCE_CACHE_SCHEMA_VERSION,
            )
            for label, mutate in missing_cases:
                with self.subTest(region=region, missing=label):
                    payload = deepcopy(_complete_source_payload(region))
                    mutate(payload)
                    with self.assertRaises(source_clients.P0HorseSourceBlocked):
                        source_clients.validate_p0_horse_source_cache(payload)

    def test_official_zero_start_career_accepts_an_empty_record_list(self):
        source_clients = _source_module()
        payload = _complete_source_payload(RacingRegion.JAPAN)
        payload["career"]["source_start_count"] = 0
        payload["career"]["records"] = []

        validated = source_clients.validate_p0_horse_source_cache(payload)

        self.assertEqual(validated["career"]["source_start_count"], 0)
        self.assertEqual(validated["career"]["records"], [])


class P0HorseReviewedNetworkBatchContractTests(SimpleTestCase):
    command_name = "complete_horse_profiles"

    def _run_authorized_network_batch(
        self,
        *,
        review_manifest_path: Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        expected_manifest_sha256 = _file_sha256(review_manifest_path)
        with override_settings(
            HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True,
            HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                expected_manifest_sha256
            ),
        ):
            return completion.run_reviewed_p0_horse_completion_batch(
                review_manifest_path=review_manifest_path,
                expected_review_manifest_sha256=expected_manifest_sha256,
                allow_network=True,
                **kwargs,
            )

    def test_batch_binds_reviewed_manual_supplements_and_records_input_digest(self):
        source_clients = _source_module()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_rows = _reviewed_candidate_rows()
            reviewed_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(reviewed_csv, candidate_rows)
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            candidate = next(
                row
                for row in candidate_rows
                if row["sample_region"] == RacingRegion.UNITED_KINGDOM
            )
            manual_csv = root / "manual.csv"
            with manual_csv.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as output:
                writer = csv.DictWriter(
                    output,
                    fieldnames=source_clients.MANUAL_SUPPLEMENT_CSV_FIELDS,
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "candidate_key": candidate["candidate_key"],
                        "region": candidate["sample_region"],
                        "horse_name": candidate["horse_name"],
                        "field_group": "identity",
                        "field_name": "birth_year",
                        "current_value": "",
                        "proposed_value": "2021",
                        "source_name": "racing_post",
                        "source_url": "https://www.racingpost.com/profile/horse/1/test",
                        "source_external_horse_id": "1",
                        "evidence_note": "",
                        "entered_by": "operator-a",
                        "reviewer": "reviewer-b",
                        "review_status": "approved",
                        "reviewed_at": "2026-07-18T02:00:00Z",
                        "review_notes": "",
                    }
                )
            manual_sha256 = hashlib.sha256(
                manual_csv.read_bytes()
            ).hexdigest()

            captured: list[dict[str, Any]] = []

            def build_client(
                region: str,
                transport: Any,
                **kwargs: Any,
            ) -> Any:
                captured.append({"region": region, **kwargs})

                class ManualReadyClient(
                    source_clients._BaseSourceClient
                ):
                    provider_name = "sporting_life"

                    def _fetch(self, request):
                        payload = _batch_payload_for_request(
                            request
                        )
                        if request.candidate_key == candidate[
                            "candidate_key"
                        ]:
                            payload["identity"]["birth_year"] = None
                        return payload

                ManualReadyClient.region = region
                return ManualReadyClient(
                    transport,
                    manual_supplements_by_candidate=kwargs[
                        "manual_supplements_by_candidate"
                    ],
                )

            with patch(
                "stable.services.p0_horse_completion_source_clients."
                "build_p0_horse_completion_source_client",
                side_effect=build_client,
            ):
                manifest = self._run_authorized_network_batch(
                    review_manifest_path=review_manifest,
                    reviewed_candidates_csv=reviewed_csv,
                    manual_supplements_csv=manual_csv,
                    cache_dir=root / "cache",
                    output_dir=root / "output",
                    network_regions=(RacingRegion.UNITED_KINGDOM,),
                    generated_at="2026-07-18T02:30:00Z",
                )
                payloads = _read_batch_payloads(root / "output")

        self.assertEqual(len(captured), 1)
        mapped = captured[0]["manual_supplements_by_candidate"]
        self.assertEqual(list(mapped), [candidate["candidate_key"]])
        self.assertEqual(
            mapped[candidate["candidate_key"]][0]["source"]["entry_method"],
            "manual_review",
        )
        self.assertEqual(
            manifest["manual_supplements_input"]["sha256"],
            manual_sha256,
        )
        self.assertEqual(
            manifest["manual_supplements_input"]["approved_field_count"],
            1,
        )
        self.assertEqual(
            manifest["manual_supplements_input"]["outcome_summary"],
            {
                "approved_field_count": 1,
                "applied_field_count": 1,
                "already_applied_field_count": 0,
                "blocked_field_count": 0,
                "ignored_field_count": 0,
                "approved_candidate_count": 1,
                "applied_candidate_count": 1,
                "blocked_candidate_count": 0,
                "ignored_candidate_count": 0,
            },
        )
        completed = next(
            payload
            for payload in payloads
            if payload["candidate_key"] == candidate["candidate_key"]
        )
        self.assertEqual(
            completed["raw_payload"][
                "manual_supplement_outcomes"
            ][0]["status"],
            "applied",
        )

    def test_manual_supplements_must_target_selected_regions_and_default_clients(self):
        candidate_rows = _reviewed_candidate_rows()
        cases = (
            (
                "unselected_region",
                RacingRegion.HONG_KONG,
                (RacingRegion.UNITED_KINGDOM,),
                None,
                "outside selected network regions",
            ),
            (
                "custom_client",
                RacingRegion.UNITED_KINGDOM,
                (RacingRegion.UNITED_KINGDOM,),
                RecordingBatchSourceClientFactory(),
                "default source clients",
            ),
        )
        for (
            label,
            candidate_region,
            selected_regions,
            factory,
            expected_error,
        ) in cases:
            with self.subTest(case=label), TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                reviewed_csv = root / "reviewed.csv"
                _write_reviewed_candidate_csv(
                    reviewed_csv,
                    candidate_rows,
                )
                review_manifest = _write_review_manifest(
                    root / "review_manifest.json",
                    reviewed_csv,
                )
                candidate = next(
                    row
                    for row in candidate_rows
                    if row["sample_region"] == candidate_region
                )
                manual_csv = _write_manual_review_csv(
                    root / "manual.csv",
                    candidate,
                )
                kwargs: dict[str, Any] = {}
                if factory is not None:
                    kwargs["source_client_factory"] = factory

                with self.assertRaisesRegex(
                    completion.P0HorseCompletionBatchError,
                    expected_error,
                ):
                    self._run_authorized_network_batch(
                        review_manifest_path=review_manifest,
                        reviewed_candidates_csv=reviewed_csv,
                        manual_supplements_csv=manual_csv,
                        cache_dir=root / "cache",
                        output_dir=root / "output",
                        network_regions=selected_regions,
                        generated_at="2026-07-18T02:30:00Z",
                        **kwargs,
                    )
                if factory is not None:
                    self.assertEqual(factory.calls, [])

    def test_manual_supplement_source_failure_records_blocked_field_outcome(self):
        source_clients = _source_module()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_rows = _reviewed_candidate_rows()
            reviewed_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                candidate_rows,
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            candidate = next(
                row
                for row in candidate_rows
                if row["sample_region"]
                == RacingRegion.UNITED_KINGDOM
            )
            manual_csv = _write_manual_review_csv(
                root / "manual.csv",
                {
                    **candidate,
                },
            )

            class FailingClient(source_clients._BaseSourceClient):
                region = RacingRegion.UNITED_KINGDOM
                provider_name = "sporting_life"

                def _fetch(self, request):
                    raise source_clients.P0HorseSourceBlocked(
                        "source_unavailable"
                    )

            def build_client(
                region: str,
                transport: Any,
                **kwargs: Any,
            ) -> Any:
                return FailingClient(
                    transport,
                    manual_supplements_by_candidate=kwargs[
                        "manual_supplements_by_candidate"
                    ],
                )

            with patch(
                "stable.services.p0_horse_completion_source_clients."
                "build_p0_horse_completion_source_client",
                side_effect=build_client,
            ):
                manifest = self._run_authorized_network_batch(
                    review_manifest_path=review_manifest,
                    reviewed_candidates_csv=reviewed_csv,
                    manual_supplements_csv=manual_csv,
                    cache_dir=root / "cache",
                    output_dir=root / "output",
                    network_regions=(
                        RacingRegion.UNITED_KINGDOM,
                    ),
                    generated_at="2026-07-18T02:30:00Z",
                )
                payloads = _read_batch_payloads(root / "output")

        outcome_summary = manifest["manual_supplements_input"][
            "outcome_summary"
        ]
        self.assertEqual(outcome_summary["blocked_field_count"], 1)
        self.assertEqual(outcome_summary["applied_field_count"], 0)
        self.assertEqual(outcome_summary["blocked_candidate_count"], 1)
        blocked = next(
            payload
            for payload in payloads
            if payload["candidate_key"] == candidate["candidate_key"]
        )
        outcome = blocked["raw_payload"][
            "manual_supplement_outcomes"
        ][0]
        self.assertEqual(outcome["status"], "blocked")
        self.assertIn(
            "source_cache_or_adapter_error",
            outcome["reason"],
        )

    def test_artifact_publish_reconciles_every_manual_outcome_before_staging(self):
        candidate_key = "external:sporting_life:1014215"
        approved = {
            "field_group": "basic_profile",
            "field_name": "breeder_name",
            "current_value": "",
            "proposed_value": "Reviewed Breeder",
            "source": {
                "name": "reviewed_source",
                "url": "https://example.test/reviewed-source",
                "external_horse_id": "",
                "fetched_at": "2026-07-18T02:00:00Z",
                "entry_method": "manual_review",
                "entered_by": "operator-a",
                "reviewer": "reviewer-b",
                "field_group": "basic_profile",
                "field_name": "breeder_name",
                "evidence_role": "manual_supplement",
                "evidence_note": "Pedigree page",
                "review_notes": "Second-person review complete",
            },
        }
        valid_outcome = {
            **deepcopy(approved),
            "status": "applied",
            "reason": "",
        }
        changed_evidence = deepcopy(valid_outcome)
        changed_evidence["source"]["evidence_note"] = "Different evidence"
        cases = (
            (
                "missing",
                [],
                {candidate_key: [approved]},
                "do not match the approved input",
            ),
            (
                "duplicate",
                [valid_outcome, deepcopy(valid_outcome)],
                {candidate_key: [approved]},
                "duplicate evidence",
            ),
            (
                "unknown_status",
                [{**deepcopy(valid_outcome), "status": "accepted"}],
                {candidate_key: [approved]},
                "invalid status",
            ),
            (
                "changed_evidence",
                [changed_evidence],
                {candidate_key: [approved]},
                "do not match the approved input",
            ),
            (
                "outcome_without_input",
                [valid_outcome],
                {},
                "without approved input",
            ),
        )
        for label, outcomes, expected, error in cases:
            with self.subTest(case=label), TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                output = root / "output"
                with self.assertRaisesRegex(
                    completion.P0HorseCompletionBatchError,
                    error,
                ):
                    completion._publish_reviewed_p0_horse_completion_artifacts(
                        [
                            {
                                "candidate_key": candidate_key,
                                "raw_payload": {
                                    "manual_supplement_outcomes": outcomes,
                                },
                            }
                        ],
                        output=output,
                        reviewed_path=root / "reviewed.csv",
                        reviewed_bytes=b"reviewed",
                        reviewed_sha256=hashlib.sha256(
                            b"reviewed"
                        ).hexdigest(),
                        candidate_count=1,
                        review_manifest_input=None,
                        manual_supplements_input=(
                            {
                                "approved_field_count": sum(
                                    len(rows)
                                    for rows in expected.values()
                                ),
                                "candidate_count": len(expected),
                            }
                            if expected
                            else None
                        ),
                        manual_supplements_by_candidate=expected,
                        allow_network=True,
                        selected_regions=(
                            RacingRegion.UNITED_KINGDOM,
                        ),
                        request_interval_seconds=8.0,
                        generated_at="2026-07-18T02:30:00Z",
                    )
                self.assertFalse(output.exists())

    def test_reviewed_batch_isolates_all_noncanonical_json_payloads_without_cache_residue(self):
        source_clients = _source_module()
        invalid_labels = (
            "tuple",
            "set",
            "non_string_key",
            "nan",
            "infinity",
            "cycle",
            "too_deep",
        )

        def invalid_raw_payload(label: str) -> Any:
            if label == "tuple":
                return ({"entry_method": "manual_review"},)
            if label == "set":
                return {"not-json"}
            if label == "non_string_key":
                return {1: "not-json"}
            if label == "nan":
                return float("nan")
            if label == "infinity":
                return float("inf")
            if label == "cycle":
                cycle: dict[str, Any] = {}
                cycle["self"] = cycle
                return cycle
            root: dict[str, Any] = {}
            cursor = root
            for _index in range(
                source_clients.CANONICAL_JSON_MAX_DEPTH + 2
            ):
                child: dict[str, Any] = {}
                cursor["next"] = child
                cursor = child
            return root

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_rows = _reviewed_candidate_rows()
            reviewed_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                candidate_rows,
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            region_candidates = [
                row
                for row in candidate_rows
                if row["sample_region"]
                == RacingRegion.UNITED_KINGDOM
            ]
            invalid_by_candidate = {
                candidate["candidate_key"]: label
                for candidate, label in zip(
                    region_candidates[: len(invalid_labels)],
                    invalid_labels,
                    strict=True,
                )
            }
            expected_cache_names = {
                completion.p0_horse_completion_cache_path(
                    root / "cache",
                    candidate["candidate_key"],
                ).name
                for candidate in region_candidates
                if candidate["candidate_key"]
                not in invalid_by_candidate
            }

            class InvalidJsonBatchClient:
                def __init__(self, region: str):
                    self.region = region
                    self.calls: list[str] = []
                    self.last_request_count = 0

                def fetch(self, request):
                    self.calls.append(request.candidate_key)
                    self.last_request_count = 1
                    payload = _batch_payload_for_request(request)
                    label = invalid_by_candidate.get(
                        request.candidate_key
                    )
                    if label:
                        payload["raw_payload"] = invalid_raw_payload(
                            label
                        )
                    return payload

            clients: dict[str, InvalidJsonBatchClient] = {}

            def factory(region: str) -> InvalidJsonBatchClient:
                client = InvalidJsonBatchClient(region)
                clients[region] = client
                return client

            manifest = self._run_authorized_network_batch(
                review_manifest_path=review_manifest,
                reviewed_candidates_csv=reviewed_csv,
                cache_dir=root / "cache",
                output_dir=root / "output",
                network_regions=(
                    RacingRegion.UNITED_KINGDOM,
                ),
                source_client_factory=factory,
                generated_at="2026-07-18T03:00:00Z",
            )
            payloads = _read_batch_payloads(root / "output")
            cache_files = sorted(
                path
                for path in (root / "cache").iterdir()
                if path.is_file()
            )

        region_summary = manifest["summary"]["regions"][
            RacingRegion.UNITED_KINGDOM
        ]
        self.assertEqual(region_summary["processed_count"], 10)
        self.assertEqual(region_summary["blocked_count"], 7)
        self.assertEqual(region_summary["complete_candidate_count"], 3)
        self.assertEqual(len(clients[RacingRegion.UNITED_KINGDOM].calls), 10)
        payload_by_key = {
            payload["candidate_key"]: payload
            for payload in payloads
        }
        for candidate_key in invalid_by_candidate:
            self.assertIn(
                "source_cache_or_adapter_error",
                payload_by_key[candidate_key]["failure_reason"],
            )
        self.assertEqual(
            {path.name for path in cache_files},
            expected_cache_names,
        )

    def test_cli_allow_network_is_only_valid_for_reviewed_candidate_dry_run(self):
        invalid_invocations = (
            (
                "--commit",
                "--allow-network",
                "--artifact",
                "/tmp/reviewed-artifact.json",
                "--confirm-reviewed-artifact",
            ),
            ("--dry-run", "--allow-network"),
        )
        with (
            patch(
                "stable.management.commands.complete_horse_profiles."
                "apply_completion_artifact"
            ) as apply_artifact,
            patch(
                "stable.management.commands.complete_horse_profiles."
                "plan_profile_completion"
            ) as legacy_plan,
            patch(
                "stable.management.commands.complete_horse_profiles."
                "run_reviewed_p0_horse_completion_batch"
            ) as reviewed_batch,
        ):
            for invocation in invalid_invocations:
                with self.subTest(invocation=invocation):
                    with self.assertRaisesRegex(
                        CommandError,
                        r"--allow-network.*--dry-run.*--p0-reviewed-candidates",
                    ):
                        call_command(
                            self.command_name,
                            *invocation,
                            stdout=StringIO(),
                            stderr=StringIO(),
                        )

        apply_artifact.assert_not_called()
        legacy_plan.assert_not_called()
        reviewed_batch.assert_not_called()

    def test_cli_and_setting_must_both_enable_network(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            review_manifest_sha256 = _file_sha256(review_manifest)

            with (
                patch(
                    "stable.management.commands.complete_horse_profiles."
                    "run_reviewed_p0_horse_completion_batch"
                ) as reviewed_batch,
                override_settings(
                    HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True,
                    HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                        review_manifest_sha256
                    ),
                ),
            ):
                reviewed_batch.return_value = {
                    "read_only": True,
                    "summary": {"processed_count": 50},
                }
                call_command(
                    self.command_name,
                    "--dry-run",
                    "--p0-reviewed-candidates",
                    str(reviewed_csv),
                    "--region",
                    RacingRegion.JAPAN,
                    "--cache-dir",
                    str(root / "offline-cache"),
                    "--output-dir",
                    str(root / "offline-output"),
                    stdout=StringIO(),
                )
                offline_kwargs = reviewed_batch.call_args.kwargs
                self.assertIs(offline_kwargs["allow_network"], False)
                self.assertEqual(offline_kwargs["network_regions"], ())

            with (
                patch(
                    "stable.management.commands.complete_horse_profiles."
                    "run_reviewed_p0_horse_completion_batch"
                ) as reviewed_batch,
                override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=False),
            ):
                with self.assertRaisesRegex(
                    CommandError,
                    "HORSE_PROFILE_COMPLETION_ALLOW_NETWORK",
                ):
                    call_command(
                        self.command_name,
                        "--dry-run",
                        "--p0-reviewed-candidates",
                        str(reviewed_csv),
                        "--allow-network",
                        "--region",
                        RacingRegion.JAPAN,
                        "--cache-dir",
                        str(root / "disabled-cache"),
                        "--output-dir",
                        str(root / "disabled-output"),
                        stdout=StringIO(),
                        stderr=StringIO(),
                    )
                reviewed_batch.assert_not_called()

            with (
                patch(
                    "stable.management.commands.complete_horse_profiles."
                    "run_reviewed_p0_horse_completion_batch"
                ) as reviewed_batch,
                override_settings(
                    HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True,
                    HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                        review_manifest_sha256
                    ),
                ),
            ):
                reviewed_batch.return_value = {
                    "read_only": True,
                    "summary": {"processed_count": 50},
                }
                call_command(
                    self.command_name,
                    "--dry-run",
                    "--p0-reviewed-candidates",
                    str(reviewed_csv),
                    "--allow-network",
                    "--p0-review-manifest",
                    str(review_manifest),
                    "--p0-review-manifest-sha256",
                    review_manifest_sha256,
                    "--region",
                    RacingRegion.JAPAN,
                    "--cache-dir",
                    str(root / "enabled-cache"),
                    "--output-dir",
                    str(root / "enabled-output"),
                    stdout=StringIO(),
                )
                enabled_kwargs = reviewed_batch.call_args.kwargs
                self.assertIs(enabled_kwargs["allow_network"], True)
                self.assertEqual(
                    enabled_kwargs["network_regions"],
                    (RacingRegion.JAPAN,),
                )
                self.assertEqual(
                    Path(enabled_kwargs["review_manifest_path"]),
                    review_manifest,
                )
                self.assertEqual(
                    enabled_kwargs["expected_review_manifest_sha256"],
                    review_manifest_sha256,
                )

    def test_cli_network_batch_requires_and_forwards_review_manifest(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            review_manifest_sha256 = _file_sha256(review_manifest)
            manual_supplements = root / "manual-supplements.csv"
            manual_supplements.write_text(
                ",".join(_source_module().MANUAL_SUPPLEMENT_CSV_FIELDS)
                + "\n",
                encoding="utf-8",
            )

            with (
                patch(
                    "stable.management.commands.complete_horse_profiles."
                    "run_reviewed_p0_horse_completion_batch"
                ) as reviewed_batch,
                override_settings(
                    HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True,
                    HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                        review_manifest_sha256
                    ),
                ),
            ):
                reviewed_batch.return_value = {
                    "read_only": True,
                    "summary": {"processed_count": 50},
                }
                with self.subTest(case="missing_manifest"):
                    with self.assertRaisesRegex(
                        CommandError,
                        "--p0-review-manifest",
                    ):
                        call_command(
                            self.command_name,
                            "--dry-run",
                            "--p0-reviewed-candidates",
                            str(reviewed_csv),
                            "--allow-network",
                            "--region",
                            RacingRegion.UNITED_KINGDOM,
                            "--cache-dir",
                            str(root / "missing-cache"),
                            "--output-dir",
                            str(root / "missing-output"),
                            stdout=StringIO(),
                            stderr=StringIO(),
                        )
                    reviewed_batch.assert_not_called()

                reviewed_batch.reset_mock()
                with self.subTest(case="manifest_forwarded"):
                    call_command(
                        self.command_name,
                        "--dry-run",
                        "--p0-reviewed-candidates",
                        str(reviewed_csv),
                        "--p0-review-manifest",
                        str(review_manifest),
                        "--p0-review-manifest-sha256",
                        review_manifest_sha256,
                        "--p0-manual-supplements",
                        str(manual_supplements),
                        "--allow-network",
                        "--region",
                        RacingRegion.UNITED_KINGDOM,
                        "--cache-dir",
                        str(root / "valid-cache"),
                        "--output-dir",
                        str(root / "valid-output"),
                        stdout=StringIO(),
                    )
                    forwarded = reviewed_batch.call_args.kwargs
                    self.assertEqual(
                        Path(forwarded["review_manifest_path"]),
                        review_manifest,
                    )
                    self.assertEqual(
                        forwarded["expected_review_manifest_sha256"],
                        review_manifest_sha256,
                    )
                    self.assertEqual(
                        Path(forwarded["manual_supplements_csv"]),
                        manual_supplements,
                    )
                    self.assertIs(forwarded["allow_network"], True)

    def test_cli_requires_and_forwards_expected_review_manifest_sha256(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            expected_sha256 = _file_sha256(review_manifest)

            with (
                patch(
                    "stable.management.commands.complete_horse_profiles."
                    "run_reviewed_p0_horse_completion_batch"
                ) as reviewed_batch,
                override_settings(
                    HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True,
                    HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                        expected_sha256
                    ),
                ),
            ):
                reviewed_batch.return_value = {
                    "read_only": True,
                    "summary": {"processed_count": 50},
                }
                with self.subTest(case="missing_cli_sha"):
                    with self.assertRaisesRegex(
                        CommandError,
                        "--p0-review-manifest-sha256",
                    ):
                        call_command(
                            self.command_name,
                            "--dry-run",
                            "--p0-reviewed-candidates",
                            str(reviewed_csv),
                            "--p0-review-manifest",
                            str(review_manifest),
                            "--allow-network",
                            "--region",
                            RacingRegion.UNITED_KINGDOM,
                            "--cache-dir",
                            str(root / "missing-cache"),
                            "--output-dir",
                            str(root / "missing-output"),
                            stdout=StringIO(),
                            stderr=StringIO(),
                        )
                    reviewed_batch.assert_not_called()

                invalid_sha256_values = (
                    ("both_empty", ""),
                    ("both_uppercase", expected_sha256.upper()),
                    ("both_63_characters", "0" * 63),
                    ("both_non_hex", "g" * 64),
                )
                for label, invalid_sha256 in invalid_sha256_values:
                    reviewed_batch.reset_mock()
                    with (
                        self.subTest(case=label),
                        override_settings(
                            HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                                invalid_sha256
                            )
                        ),
                    ):
                        with self.assertRaises(CommandError):
                            call_command(
                                self.command_name,
                                "--dry-run",
                                "--p0-reviewed-candidates",
                                str(reviewed_csv),
                                "--p0-review-manifest",
                                str(review_manifest),
                                "--p0-review-manifest-sha256",
                                invalid_sha256,
                                "--allow-network",
                                "--region",
                                RacingRegion.UNITED_KINGDOM,
                                "--cache-dir",
                                str(root / f"{label}-cache"),
                                "--output-dir",
                                str(root / f"{label}-output"),
                                stdout=StringIO(),
                                stderr=StringIO(),
                            )
                        reviewed_batch.assert_not_called()

                reviewed_batch.reset_mock()
                with self.subTest(case="server_setting_mismatch"):
                    with override_settings(
                        HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                            "0" * 64
                        )
                    ):
                        with self.assertRaisesRegex(
                            CommandError,
                            "HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256",
                        ):
                            call_command(
                                self.command_name,
                                "--dry-run",
                                "--p0-reviewed-candidates",
                                str(reviewed_csv),
                                "--p0-review-manifest",
                                str(review_manifest),
                                "--p0-review-manifest-sha256",
                                expected_sha256,
                                "--allow-network",
                                "--region",
                                RacingRegion.UNITED_KINGDOM,
                                "--cache-dir",
                                str(root / "mismatch-cache"),
                                "--output-dir",
                                str(root / "mismatch-output"),
                                stdout=StringIO(),
                                stderr=StringIO(),
                            )
                    reviewed_batch.assert_not_called()

                reviewed_batch.reset_mock()
                with self.subTest(case="sha_forwarded"):
                    call_command(
                        self.command_name,
                        "--dry-run",
                        "--p0-reviewed-candidates",
                        str(reviewed_csv),
                        "--p0-review-manifest",
                        str(review_manifest),
                        "--p0-review-manifest-sha256",
                        expected_sha256,
                        "--allow-network",
                        "--region",
                        RacingRegion.UNITED_KINGDOM,
                        "--cache-dir",
                        str(root / "valid-cache"),
                        "--output-dir",
                        str(root / "valid-output"),
                        stdout=StringIO(),
                    )
                    forwarded = reviewed_batch.call_args.kwargs
                    self.assertEqual(
                        forwarded["expected_review_manifest_sha256"],
                        expected_sha256,
                    )

    def test_network_manifest_binding_is_validated_before_source_client_creation(self):
        cases = (
            ("missing_manifest", {}),
            (
                "wrong_artifact_type",
                {"artifact_type": "not_a_review_manifest"},
            ),
            (
                "wrong_decision",
                {"decision": "reject_batch_inclusion"},
            ),
            (
                "csv_basename_missing",
                {"entry_name": "different-reviewed.csv"},
            ),
            (
                "csv_sha_mismatch",
                {"sha256": "0" * 64},
            ),
            (
                "csv_size_mismatch",
                {"size_delta": 1},
            ),
            (
                "row_count_mismatch",
                {"row_count": 49},
            ),
            (
                "csv_tampered_after_manifest",
                {"tamper_csv": True},
            ),
        )
        for label, mutation in cases:
            with self.subTest(case=label), TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                reviewed_csv = root / "reviewed.csv"
                _write_reviewed_candidate_csv(
                    reviewed_csv,
                    _reviewed_candidate_rows(),
                )
                manifest_path: Path | None = None
                if label != "missing_manifest":
                    size = None
                    if "size_delta" in mutation:
                        size = (
                            len(reviewed_csv.read_bytes())
                            + int(mutation["size_delta"])
                        )
                    manifest_path = _write_review_manifest(
                        root / "review_manifest.json",
                        reviewed_csv,
                        artifact_type=str(
                            mutation.get(
                                "artifact_type",
                                "p0_horse_candidate_review_manifest",
                            )
                        ),
                        decision=str(
                            mutation.get(
                                "decision",
                                "confirm_batch_inclusion",
                            )
                        ),
                        entry_name=mutation.get("entry_name"),
                        sha256=mutation.get("sha256"),
                        size=size,
                        row_count=int(mutation.get("row_count", 50)),
                    )
                    if mutation.get("tamper_csv"):
                        reviewed_csv.write_bytes(
                            reviewed_csv.read_bytes() + b"\n"
                        )

                factory = RecordingBatchSourceClientFactory()
                kwargs: dict[str, Any] = {}
                if manifest_path is not None:
                    kwargs["review_manifest_path"] = manifest_path
                    expected_sha256 = _file_sha256(manifest_path)
                else:
                    expected_sha256 = "1" * 64
                kwargs["expected_review_manifest_sha256"] = expected_sha256
                caught: Exception | None = None
                try:
                    with override_settings(
                        HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True,
                        HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                            expected_sha256
                        ),
                    ):
                        completion.run_reviewed_p0_horse_completion_batch(
                            reviewed_candidates_csv=reviewed_csv,
                            cache_dir=root / "cache",
                            output_dir=root / "output",
                            allow_network=True,
                            network_regions=(RacingRegion.UNITED_KINGDOM,),
                            source_client_factory=factory,
                            generated_at="2026-07-18T00:00:00Z",
                            **kwargs,
                        )
                except Exception as exc:
                    caught = exc

                self.assertEqual(
                    {
                        "error_type": (
                            type(caught).__name__
                            if caught is not None
                            else None
                        ),
                        "factory_calls": factory.calls,
                    },
                    {
                        "error_type": "P0HorseCompletionBatchError",
                        "factory_calls": [],
                    },
                )

    def test_valid_review_manifest_explicitly_binds_network_batch(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            factory = RecordingBatchSourceClientFactory()

            manifest = self._run_authorized_network_batch(
                reviewed_candidates_csv=reviewed_csv,
                review_manifest_path=review_manifest,
                cache_dir=root / "cache",
                output_dir=root / "output",
                network_regions=(RacingRegion.UNITED_KINGDOM,),
                source_client_factory=factory,
                generated_at="2026-07-18T00:00:00Z",
            )

        self.assertEqual(factory.calls, [RacingRegion.UNITED_KINGDOM])
        self.assertEqual(manifest["summary"]["processed_count"], 50)
        self.assertIs(manifest["network_allowed"], True)

    def test_manifest_sha_authorization_fails_before_manifest_parse_or_client_creation(
        self,
    ):
        cases = (
            ("both_empty", "", "", False),
            ("both_uppercase", "uppercase", "uppercase", False),
            ("both_63_characters", "0" * 63, "0" * 63, False),
            ("both_non_hex", "g" * 64, "g" * 64, False),
            ("expected_differs_from_setting", None, "0" * 64, False),
            ("manifest_bytes_differ_from_expected", None, None, True),
        )
        for label, setting_value, expected_value, mutate_manifest in cases:
            with self.subTest(case=label), TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                reviewed_csv = root / "reviewed.csv"
                _write_reviewed_candidate_csv(
                    reviewed_csv,
                    _reviewed_candidate_rows(),
                )
                review_manifest = _write_review_manifest(
                    root / "review_manifest.json",
                    reviewed_csv,
                )
                frozen_sha256 = _file_sha256(review_manifest)
                if mutate_manifest:
                    review_manifest.write_bytes(
                        review_manifest.read_bytes() + b"\n"
                    )

                resolved_setting = (
                    frozen_sha256
                    if setting_value is None
                    else (
                        frozen_sha256.upper()
                        if setting_value == "uppercase"
                        else setting_value
                    )
                )
                resolved_expected = (
                    frozen_sha256
                    if expected_value is None
                    else (
                        frozen_sha256.upper()
                        if expected_value == "uppercase"
                        else expected_value
                    )
                )
                manifest_parse_calls: list[bytes] = []
                real_json_loads = json.loads

                def tracking_json_loads(value: Any, *args: Any, **kwargs: Any):
                    is_manifest_text = (
                        isinstance(value, str)
                        and value.lstrip().startswith("{")
                    )
                    if isinstance(value, (bytes, bytearray)) or is_manifest_text:
                        manifest_parse_calls.append(
                            (
                                bytes(value)
                                if isinstance(value, (bytes, bytearray))
                                else value.encode("utf-8")
                            )
                        )
                    return real_json_loads(value, *args, **kwargs)

                caught: Exception | None = None
                try:
                    with (
                        override_settings(
                            HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True,
                            HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                                resolved_setting
                            ),
                        ),
                        patch.object(
                            completion.json,
                            "loads",
                            side_effect=tracking_json_loads,
                        ),
                        patch("requests.Session") as session_factory,
                        patch(
                            "stable.services."
                            "p0_horse_completion_source_clients."
                            "build_p0_horse_completion_source_client"
                        ) as source_client_factory,
                    ):
                        completion.run_reviewed_p0_horse_completion_batch(
                            reviewed_candidates_csv=reviewed_csv,
                            review_manifest_path=review_manifest,
                            expected_review_manifest_sha256=(
                                resolved_expected
                            ),
                            cache_dir=root / "cache",
                            output_dir=root / "output",
                            allow_network=True,
                            network_regions=(RacingRegion.UNITED_KINGDOM,),
                            generated_at="2026-07-18T00:00:00Z",
                        )
                except Exception as exc:
                    caught = exc

                self.assertEqual(
                    {
                        "error_type": (
                            type(caught).__name__
                            if caught is not None
                            else None
                        ),
                        "manifest_parse_calls": len(manifest_parse_calls),
                        "factory_calls": source_client_factory.call_count,
                        "session_calls": session_factory.call_count,
                    },
                    {
                        "error_type": "P0HorseCompletionBatchError",
                        "manifest_parse_calls": 0,
                        "factory_calls": 0,
                        "session_calls": 0,
                    },
                )

    def test_self_consistent_replacement_manifest_is_rejected_by_frozen_sha(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            original_rows = _reviewed_candidate_rows()
            _write_reviewed_candidate_csv(reviewed_csv, original_rows)
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            frozen_manifest_sha256 = _file_sha256(review_manifest)

            replacement_rows = deepcopy(original_rows)
            replacement_rows[0]["review_notes"] = (
                "replacement review artifact with internally consistent hashes"
            )
            _write_reviewed_candidate_csv(reviewed_csv, replacement_rows)
            _write_review_manifest(review_manifest, reviewed_csv)
            replacement_manifest = json.loads(
                review_manifest.read_bytes()
            )
            replacement_csv_bytes = reviewed_csv.read_bytes()
            self.assertEqual(
                replacement_manifest["files"][reviewed_csv.name]["sha256"],
                hashlib.sha256(replacement_csv_bytes).hexdigest(),
            )
            self.assertEqual(
                replacement_manifest["files"][reviewed_csv.name]["size"],
                len(replacement_csv_bytes),
            )
            self.assertNotEqual(
                _file_sha256(review_manifest),
                frozen_manifest_sha256,
            )

            factory = RecordingBatchSourceClientFactory()
            manifest_parse_calls: list[bytes] = []
            real_json_loads = json.loads

            def tracking_json_loads(value: Any, *args: Any, **kwargs: Any):
                is_manifest_text = (
                    isinstance(value, str)
                    and value.lstrip().startswith("{")
                )
                if isinstance(value, (bytes, bytearray)) or is_manifest_text:
                    manifest_parse_calls.append(
                        (
                            bytes(value)
                            if isinstance(value, (bytes, bytearray))
                            else value.encode("utf-8")
                        )
                    )
                return real_json_loads(value, *args, **kwargs)

            caught: Exception | None = None
            try:
                with (
                    override_settings(
                        HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True,
                        HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=(
                            frozen_manifest_sha256
                        ),
                    ),
                    patch.object(
                        completion.json,
                        "loads",
                        side_effect=tracking_json_loads,
                    ),
                ):
                    completion.run_reviewed_p0_horse_completion_batch(
                        reviewed_candidates_csv=reviewed_csv,
                        review_manifest_path=review_manifest,
                        expected_review_manifest_sha256=(
                            frozen_manifest_sha256
                        ),
                        cache_dir=root / "cache",
                        output_dir=root / "output",
                        allow_network=True,
                        network_regions=(RacingRegion.UNITED_KINGDOM,),
                        source_client_factory=factory,
                        generated_at="2026-07-18T00:00:00Z",
                    )
            except Exception as exc:
                caught = exc

        self.assertEqual(
            {
                "error_type": (
                    type(caught).__name__ if caught is not None else None
                ),
                "manifest_parse_calls": len(manifest_parse_calls),
                "factory_calls": factory.calls,
            },
            {
                "error_type": "P0HorseCompletionBatchError",
                "manifest_parse_calls": 0,
                "factory_calls": [],
            },
        )

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_network_batch_requires_at_least_one_explicit_region(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            factory = RecordingBatchSourceClientFactory()

            with self.assertRaisesRegex(
                completion.P0HorseCompletionBatchError,
                "at least one.*region",
            ):
                completion.run_reviewed_p0_horse_completion_batch(
                    reviewed_candidates_csv=reviewed_csv,
                    cache_dir=root / "cache",
                    output_dir=root / "output",
                    allow_network=True,
                    network_regions=(),
                    source_client_factory=factory,
                    generated_at="2026-07-18T00:00:00Z",
                )

        self.assertEqual(factory.calls, [])

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_selected_region_uses_one_client_and_unselected_regions_stay_offline(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            factory = RecordingBatchSourceClientFactory()

            manifest = self._run_authorized_network_batch(
                reviewed_candidates_csv=reviewed_csv,
                review_manifest_path=review_manifest,
                cache_dir=root / "cache",
                output_dir=output_dir,
                network_regions=(RacingRegion.UNITED_KINGDOM,),
                source_client_factory=factory,
                generated_at="2026-07-18T00:00:00Z",
            )
            payloads = _read_batch_payloads(output_dir)

        self.assertEqual(factory.calls, [RacingRegion.UNITED_KINGDOM])
        self.assertEqual(
            len(factory.clients[RacingRegion.UNITED_KINGDOM].calls),
            10,
        )
        selected = [
            row
            for row in payloads
            if row["region"] == RacingRegion.UNITED_KINGDOM
        ]
        unselected = [
            row
            for row in payloads
            if row["region"] != RacingRegion.UNITED_KINGDOM
        ]
        self.assertEqual(len(selected), 10)
        self.assertTrue(
            all(row["retrieval"]["network_request_count"] == 1 for row in selected)
        )
        self.assertTrue(
            all(
                "network_disabled_cache_missing" in row["failure_reason"]
                for row in unselected
            )
        )
        self.assertEqual(
            manifest["network_regions"],
            [RacingRegion.UNITED_KINGDOM],
        )

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_each_region_reuses_one_client_with_real_request_budget_and_ten_horse_cap(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            factory = RecordingBatchSourceClientFactory()

            self._run_authorized_network_batch(
                reviewed_candidates_csv=reviewed_csv,
                review_manifest_path=review_manifest,
                cache_dir=root / "cache",
                output_dir=output_dir,
                network_regions=tuple(completion.REVIEWED_CANDIDATE_REGIONS),
                source_client_factory=factory,
                generated_at="2026-07-18T00:00:00Z",
            )
            payloads = _read_batch_payloads(output_dir)

        self.assertEqual(factory.calls, list(completion.REVIEWED_CANDIDATE_REGIONS))
        self.assertEqual(set(factory.clients), set(REGION_REQUEST_BUDGETS))
        for region, client in factory.clients.items():
            with self.subTest(region=region):
                self.assertEqual(len(client.calls), 10)
                self.assertTrue(
                    all(request.batch_limit == 10 for request in client.calls)
                )
                self.assertTrue(
                    all(
                        request.request_budget == REGION_REQUEST_BUDGETS[region]
                        for request in client.calls
                    )
                )
        self.assertEqual(
            sum(
                row["retrieval"]["network_request_count"]
                for row in payloads
            ),
            100,
        )

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_network_cache_is_atomically_reused_by_a_later_offline_batch(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            cache_dir = root / "cache"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            factory = RecordingBatchSourceClientFactory()

            first = self._run_authorized_network_batch(
                reviewed_candidates_csv=reviewed_csv,
                review_manifest_path=review_manifest,
                cache_dir=cache_dir,
                output_dir=root / "network-output",
                network_regions=(RacingRegion.UNITED_KINGDOM,),
                source_client_factory=factory,
                generated_at="2026-07-18T00:00:00Z",
            )
            second = completion.run_reviewed_p0_horse_completion_batch(
                reviewed_candidates_csv=reviewed_csv,
                cache_dir=cache_dir,
                output_dir=root / "offline-output",
                allow_network=False,
                network_regions=(),
                source_client_factory=RejectingTransport,
                generated_at="2026-07-18T00:01:00Z",
            )
            offline_payloads = _read_batch_payloads(root / "offline-output")

        self.assertEqual(first["summary"]["network_request_count"], 10)
        self.assertEqual(second["summary"]["network_request_count"], 0)
        self.assertEqual(second["summary"]["cache_hit_count"], 10)
        self.assertEqual(second["summary"]["cache_miss_count"], 40)
        cached_region = [
            row
            for row in offline_payloads
            if row["region"] == RacingRegion.UNITED_KINGDOM
        ]
        self.assertTrue(all(row["retrieval"]["cache_hit"] for row in cached_region))
        self.assertTrue(
            all(
                row["retrieval"]["network_request_count"] == 0
                for row in offline_payloads
            )
        )

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_network_manifest_records_selected_regions_and_cache_request_totals(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            reviewed_sha256 = hashlib.sha256(reviewed_csv.read_bytes()).hexdigest()
            factory = RecordingBatchSourceClientFactory()

            manifest = self._run_authorized_network_batch(
                reviewed_candidates_csv=reviewed_csv,
                review_manifest_path=review_manifest,
                cache_dir=root / "cache",
                output_dir=output_dir,
                network_regions=tuple(completion.REVIEWED_CANDIDATE_REGIONS),
                source_client_factory=factory,
                generated_at="2026-07-18T00:00:00Z",
            )
            persisted = json.loads(
                (
                    output_dir / "p0_horse_completion_batch_manifest.json"
                ).read_text(encoding="utf-8")
            )

        self.assertEqual(persisted, manifest)
        self.assertIs(manifest["read_only"], True)
        self.assertIs(manifest["network_allowed"], True)
        self.assertEqual(manifest["database_writes"], 0)
        self.assertEqual(
            manifest["network_regions"],
            list(completion.REVIEWED_CANDIDATE_REGIONS),
        )
        self.assertEqual(
            manifest["reviewed_candidates_input"]["sha256"],
            reviewed_sha256,
        )
        self.assertEqual(manifest["summary"]["processed_count"], 50)
        self.assertEqual(manifest["summary"]["network_request_count"], 100)
        self.assertEqual(manifest["summary"]["cache_hit_count"], 0)
        self.assertEqual(manifest["summary"]["cache_miss_count"], 50)
        for region, request_count in {
            RacingRegion.JAPAN: 30,
            RacingRegion.HONG_KONG: 10,
            RacingRegion.UNITED_KINGDOM: 10,
            RacingRegion.FRANCE: 20,
            RacingRegion.UNITED_STATES: 30,
        }.items():
            with self.subTest(region=region):
                region_summary = manifest["summary"]["regions"][region]
                self.assertEqual(region_summary["processed_count"], 10)
                self.assertEqual(
                    region_summary["network_request_count"],
                    request_count,
                )
                self.assertEqual(region_summary["cache_hit_count"], 0)
                self.assertEqual(region_summary["cache_miss_count"], 10)

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_network_mode_keeps_input_output_identity_and_completeness_gates(self):
        rows = _reviewed_candidate_rows()
        blocked_key = next(
            row["candidate_key"]
            for row in rows
            if row["sample_region"] == RacingRegion.UNITED_KINGDOM
            and row["sample_rank"] == "1"
        )
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            invalid_csv = root / "invalid.csv"
            valid_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(invalid_csv, rows[:-1])
            _write_reviewed_candidate_csv(valid_csv, rows)
            invalid_review_manifest = _write_review_manifest(
                root / "invalid-review-manifest.json",
                invalid_csv,
                row_count=50,
            )
            valid_review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                valid_csv,
            )

            invalid_factory = RecordingBatchSourceClientFactory()
            with self.assertRaises(completion.P0HorseCompletionBatchError):
                self._run_authorized_network_batch(
                    reviewed_candidates_csv=invalid_csv,
                    review_manifest_path=invalid_review_manifest,
                    cache_dir=root / "invalid-cache",
                    output_dir=root / "invalid-output",
                    network_regions=(RacingRegion.UNITED_KINGDOM,),
                    source_client_factory=invalid_factory,
                )
            self.assertEqual(invalid_factory.calls, [])

            nonempty_output = root / "nonempty-output"
            nonempty_output.mkdir()
            (nonempty_output / "keep.txt").write_text("keep", encoding="utf-8")
            nonempty_factory = RecordingBatchSourceClientFactory()
            with self.assertRaisesRegex(
                completion.P0HorseCompletionBatchError,
                "not empty",
            ):
                self._run_authorized_network_batch(
                    reviewed_candidates_csv=valid_csv,
                    review_manifest_path=valid_review_manifest,
                    cache_dir=root / "nonempty-cache",
                    output_dir=nonempty_output,
                    network_regions=(RacingRegion.UNITED_KINGDOM,),
                    source_client_factory=nonempty_factory,
                )
            self.assertEqual(nonempty_factory.calls, [])

            factory = RecordingBatchSourceClientFactory(
                incomplete_candidate_keys={blocked_key},
            )
            output_dir = root / "output"
            manifest = self._run_authorized_network_batch(
                reviewed_candidates_csv=valid_csv,
                review_manifest_path=valid_review_manifest,
                cache_dir=root / "cache",
                output_dir=output_dir,
                network_regions=(RacingRegion.UNITED_KINGDOM,),
                source_client_factory=factory,
                generated_at="2026-07-18T00:00:00Z",
            )
            payloads = _read_batch_payloads(output_dir)

        self.assertEqual(manifest["reviewed_candidates_input"]["candidate_count"], 50)
        self.assertEqual(len(payloads), 50)
        blocked = next(row for row in payloads if row["candidate_key"] == blocked_key)
        self.assertIn("source_cache_or_adapter_error", blocked["failure_reason"])
        later_selected = [
            row
            for row in payloads
            if row["region"] == RacingRegion.UNITED_KINGDOM
            and row["candidate_key"] != blocked_key
        ]
        self.assertEqual(len(later_selected), 9)
        self.assertTrue(
            all("source_cache_or_adapter_error" not in row["failure_reason"] for row in later_selected)
        )
        self.assertEqual(
            len(factory.clients[RacingRegion.UNITED_KINGDOM].calls),
            10,
        )

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_expected_source_blocker_is_classified_and_later_candidates_continue(self):
        source_clients = _source_module()

        class RateLimitedOnceSourceClient:
            def __init__(self):
                self.calls: list[completion.P0HorseCompletionRequest] = []
                self.last_request_count = 0

            def fetch(
                self,
                request: completion.P0HorseCompletionRequest,
            ) -> dict[str, Any]:
                self.calls.append(request)
                self.last_request_count = REGION_REQUEST_BUDGETS[request.region]
                if len(self.calls) == 1:
                    raise source_clients.P0HorseSourceBlocked(
                        "rate_limited: HTTP 429"
                    )
                return _batch_payload_for_request(request)

        client = RateLimitedOnceSourceClient()
        factory_calls: list[str] = []

        def source_client_factory(region: str) -> RateLimitedOnceSourceClient:
            factory_calls.append(region)
            return client

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )

            manifest = self._run_authorized_network_batch(
                reviewed_candidates_csv=reviewed_csv,
                review_manifest_path=review_manifest,
                cache_dir=root / "cache",
                output_dir=output_dir,
                network_regions=(RacingRegion.FRANCE,),
                source_client_factory=source_client_factory,
                generated_at="2026-07-18T00:00:00Z",
            )
            payloads = _read_batch_payloads(output_dir)

        france_payloads = [
            row for row in payloads if row["region"] == RacingRegion.FRANCE
        ]
        blocked = next(
            row
            for row in france_payloads
            if row["candidate_key"] == client.calls[0].candidate_key
        )
        with self.subTest(contract="expected source blocker classification"):
            self.assertEqual(
                [
                    reason
                    for reason in blocked["failure_reason"]
                    if reason
                    in {
                        "source_cache_or_adapter_error",
                        "unexpected_adapter_error",
                    }
                ],
                ["source_cache_or_adapter_error"],
            )
        self.assertEqual(blocked["retrieval"]["network_request_count"], 2)
        self.assertEqual(
            blocked["retrieval"]["error_type"],
            "P0HorseSourceBlocked",
        )
        self.assertEqual(
            blocked["retrieval"]["error_message"],
            "rate_limited: HTTP 429",
        )
        self.assertEqual(factory_calls, [RacingRegion.FRANCE])
        self.assertEqual(len(client.calls), 10)
        self.assertEqual(len(france_payloads), 10)
        self.assertTrue(
            all(
                "unexpected_adapter_error" not in row["failure_reason"]
                for row in france_payloads[1:]
            )
        )
        self.assertEqual(manifest["summary"]["processed_count"], 50)
        self.assertEqual(manifest["summary"]["network_request_count"], 20)

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_invalid_cache_does_not_inherit_previous_candidates_request_count(self):
        rows = _reviewed_candidate_rows()
        region = RacingRegion.UNITED_KINGDOM
        selected_rows = [
            row for row in rows if row["sample_region"] == region
        ]
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            cache_dir = root / "cache"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(reviewed_csv, rows)
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )

            for index, row in enumerate(selected_rows[1:], start=2):
                cache_path = completion.p0_horse_completion_cache_path(
                    cache_dir,
                    row["candidate_key"],
                )
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                payload = _complete_source_payload(region)
                payload["source"]["external_horse_id"] = row[
                    "candidate_key"
                ].split(":", 2)[2]
                payload["identity"]["horse_name"] = row["horse_name"]
                payload["aliases"] = [
                    {
                        "name": row["horse_name"],
                        "language": "en",
                        "is_original": True,
                    }
                ]
                if index == 2:
                    payload["pedigree"].pop("dam_dam")
                cache_path.write_text(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )

            factory = RecordingBatchSourceClientFactory()
            manifest = self._run_authorized_network_batch(
                reviewed_candidates_csv=reviewed_csv,
                review_manifest_path=review_manifest,
                cache_dir=cache_dir,
                output_dir=output_dir,
                network_regions=(region,),
                source_client_factory=factory,
                generated_at="2026-07-18T00:00:00Z",
            )
            payloads = _read_batch_payloads(output_dir)

        selected_payloads = [
            row for row in payloads if row["region"] == region
        ]
        invalid_cache_payload = next(
            row
            for row in selected_payloads
            if row["candidate_key"] == selected_rows[1]["candidate_key"]
        )
        with self.subTest(contract="request count belongs to the current candidate"):
            self.assertEqual(
                {
                    "candidate": invalid_cache_payload["retrieval"][
                        "network_request_count"
                    ],
                    "overall": manifest["summary"]["network_request_count"],
                    "region": manifest["summary"]["regions"][region][
                        "network_request_count"
                    ],
                },
                {
                    "candidate": 0,
                    "overall": 1,
                    "region": 1,
                },
            )
        self.assertEqual(factory.calls, [region])
        self.assertEqual(len(factory.clients[region].calls), 1)
        self.assertIn(
            "source_cache_or_adapter_error",
            invalid_cache_payload["failure_reason"],
        )
        self.assertTrue(
            all(row["retrieval"]["cache_hit"] for row in selected_payloads[2:])
        )
        self.assertEqual(manifest["summary"]["processed_count"], 50)

    def test_reviewed_batch_classifies_overdeep_cache_decode_and_continues(self):
        rows = _reviewed_candidate_rows()
        region = RacingRegion.UNITED_KINGDOM
        selected_rows = [
            row for row in rows if row["sample_region"] == region
        ]
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            cache_dir = root / "cache"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(reviewed_csv, rows)
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )
            for index, row in enumerate(selected_rows):
                cache_path = completion.p0_horse_completion_cache_path(
                    cache_dir,
                    row["candidate_key"],
                )
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                if index == 0:
                    cache_path.write_text(
                        '{"x":' * 1200 + "0" + "}" * 1200,
                        encoding="utf-8",
                    )
                    continue
                payload = _complete_source_payload(region)
                payload["source"]["external_horse_id"] = row[
                    "candidate_key"
                ].split(":", 2)[2]
                payload["identity"]["horse_name"] = row["horse_name"]
                payload["aliases"] = [
                    {
                        "name": row["horse_name"],
                        "language": "en",
                        "is_original": True,
                    }
                ]
                cache_path.write_text(
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
            cache_before = {
                path.name: path.read_bytes()
                for path in sorted(cache_dir.iterdir())
                if path.is_file()
            }

            factory = RecordingBatchSourceClientFactory()
            manifest = self._run_authorized_network_batch(
                reviewed_candidates_csv=reviewed_csv,
                review_manifest_path=review_manifest,
                cache_dir=cache_dir,
                output_dir=output_dir,
                network_regions=(region,),
                source_client_factory=factory,
                generated_at="2026-07-18T03:30:00Z",
            )
            payloads = _read_batch_payloads(output_dir)
            cache_after = {
                path.name: path.read_bytes()
                for path in sorted(cache_dir.iterdir())
                if path.is_file()
            }

        selected_payloads = [
            row for row in payloads if row["region"] == region
        ]
        blocked = next(
            row
            for row in selected_payloads
            if row["candidate_key"]
            == selected_rows[0]["candidate_key"]
        )
        self.assertIn(
            "source_cache_or_adapter_error",
            blocked["failure_reason"],
        )
        self.assertNotIn(
            "unexpected_adapter_error",
            blocked["failure_reason"],
        )
        self.assertEqual(
            blocked["retrieval"]["error_type"],
            "P0HorseCompletionSourceError",
        )
        self.assertEqual(factory.calls, [region])
        self.assertEqual(factory.clients[region].calls, [])
        region_summary = manifest["summary"]["regions"][region]
        self.assertEqual(region_summary["complete_candidate_count"], 9)
        self.assertEqual(region_summary["blocked_count"], 1)
        self.assertEqual(region_summary["cache_hit_count"], 9)
        self.assertEqual(region_summary["network_request_count"], 0)
        self.assertEqual(cache_after, cache_before)

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=False)
    def test_direct_network_batch_setting_gate_runs_before_factory_creation(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            factory = RecordingBatchSourceClientFactory()

            with self.assertRaisesRegex(
                completion.P0HorseCompletionBatchError,
                "HORSE_PROFILE_COMPLETION_ALLOW_NETWORK",
            ):
                completion.run_reviewed_p0_horse_completion_batch(
                    reviewed_candidates_csv=reviewed_csv,
                    cache_dir=root / "cache",
                    output_dir=root / "output",
                    allow_network=True,
                    network_regions=(RacingRegion.UNITED_KINGDOM,),
                    source_client_factory=factory,
                    generated_at="2026-07-18T00:00:00Z",
                )

        self.assertEqual(factory.calls, [])

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_default_factory_builds_one_selected_client_and_offline_reuses_its_cache(self):
        region = RacingRegion.UNITED_KINGDOM
        client = RecordingBatchSourceClient(region)
        session = object()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            cache_dir = root / "cache"
            network_output = root / "network-output"
            offline_output = root / "offline-output"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )

            with (
                patch("requests.Session", return_value=session) as session_factory,
                patch(
                    "stable.services.p0_horse_completion_source_clients."
                    "build_p0_horse_completion_source_client",
                    return_value=client,
                ) as client_builder,
            ):
                network_manifest = (
                    self._run_authorized_network_batch(
                        reviewed_candidates_csv=reviewed_csv,
                        review_manifest_path=review_manifest,
                        cache_dir=cache_dir,
                        output_dir=network_output,
                        network_regions=(region,),
                        generated_at="2026-07-18T00:00:00Z",
                    )
                )
                offline_manifest = (
                    completion.run_reviewed_p0_horse_completion_batch(
                        reviewed_candidates_csv=reviewed_csv,
                        cache_dir=cache_dir,
                        output_dir=offline_output,
                        allow_network=False,
                        network_regions=(),
                        generated_at="2026-07-18T00:01:00Z",
                    )
                )

            network_payloads = _read_batch_payloads(network_output)
            offline_payloads = _read_batch_payloads(offline_output)
            cache_files = sorted(cache_dir.glob("*.json"))
            cached_payloads = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in cache_files
            ]

        session_factory.assert_called_once_with()
        client_builder.assert_called_once_with(region, transport=session)
        self.assertEqual(len(client.calls), 10)
        self.assertEqual(len(cache_files), 10)
        source_clients = _source_module()
        self.assertTrue(
            all(
                source_clients.validate_p0_horse_source_cache(payload)
                for payload in cached_payloads
            )
        )
        network_selected = [
            row for row in network_payloads if row["region"] == region
        ]
        offline_selected = [
            row for row in offline_payloads if row["region"] == region
        ]
        self.assertEqual(len(network_selected), 10)
        self.assertTrue(
            all(not row["failure_reason"] for row in network_selected)
        )
        self.assertTrue(
            all(row["retrieval"]["cache_hit"] for row in offline_selected)
        )
        self.assertEqual(network_manifest["summary"]["network_request_count"], 10)
        self.assertEqual(offline_manifest["summary"]["network_request_count"], 0)
        self.assertEqual(offline_manifest["summary"]["cache_hit_count"], 10)

    @override_settings(HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True)
    def test_batch_accepts_fetch_client_with_read_only_request_count(self):
        region = RacingRegion.UNITED_KINGDOM

        class ReadOnlyRequestCountClient:
            def __init__(self):
                self.calls: list[completion.P0HorseCompletionRequest] = []

            @property
            def last_request_count(self) -> int:
                return 1

            def fetch(
                self,
                request: completion.P0HorseCompletionRequest,
            ) -> dict[str, Any]:
                self.calls.append(request)
                return _batch_payload_for_request(request)

        client = ReadOnlyRequestCountClient()
        factory_calls: list[str] = []

        def source_client_factory(region_name: str) -> ReadOnlyRequestCountClient:
            factory_calls.append(region_name)
            return client

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            cache_dir = root / "cache"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            review_manifest = _write_review_manifest(
                root / "review_manifest.json",
                reviewed_csv,
            )

            manifest = self._run_authorized_network_batch(
                reviewed_candidates_csv=reviewed_csv,
                review_manifest_path=review_manifest,
                cache_dir=cache_dir,
                output_dir=output_dir,
                network_regions=(region,),
                source_client_factory=source_client_factory,
                generated_at="2026-07-18T00:00:00Z",
            )
            payloads = _read_batch_payloads(output_dir)
            cache_files = sorted(cache_dir.glob("*.json"))

        selected_payloads = [
            row for row in payloads if row["region"] == region
        ]
        self.assertEqual(factory_calls, [region])
        self.assertEqual(len(client.calls), 10)
        self.assertEqual(manifest["summary"]["processed_count"], 50)
        self.assertEqual(len(selected_payloads), 10)
        self.assertTrue(
            all(not row["failure_reason"] for row in selected_payloads)
        )
        self.assertEqual(manifest["summary"]["network_request_count"], 10)
        self.assertEqual(
            manifest["summary"]["regions"][region]["network_request_count"],
            10,
        )
        self.assertEqual(len(cache_files), 10)

    def test_batch_artifact_publish_cleans_partial_output_after_write_failure(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )
            original_write = completion._write_bytes
            write_calls: list[Path] = []

            def fail_during_publish(path: Path, content: bytes) -> None:
                write_calls.append(Path(path))
                if len(write_calls) == 3:
                    raise OSError("scripted artifact write failure")
                original_write(path, content)

            caught: Exception | None = None
            with patch.object(
                completion,
                "_write_bytes",
                side_effect=fail_during_publish,
            ):
                try:
                    completion.run_reviewed_p0_horse_completion_batch(
                        reviewed_candidates_csv=reviewed_csv,
                        cache_dir=root / "cache",
                        output_dir=output_dir,
                        allow_network=False,
                        generated_at="2026-07-18T00:00:00Z",
                    )
                except Exception as exc:
                    caught = exc

            output_entries = (
                sorted(path.name for path in output_dir.iterdir())
                if output_dir.is_dir()
                else []
            )
            sibling_residue = sorted(
                path.name
                for path in root.iterdir()
                if path not in {reviewed_csv, output_dir}
            )

        self.assertEqual(
            {
                "error_type": (
                    type(caught).__name__ if caught is not None else None
                ),
                "write_count": len(write_calls),
                "output_entries": output_entries,
                "sibling_residue": sibling_residue,
            },
            {
                "error_type": "OSError",
                "write_count": 3,
                "output_entries": [],
                "sibling_residue": [],
            },
        )

    def test_successful_batch_artifact_publish_is_complete_and_self_consistent(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            reviewed_csv = root / "reviewed.csv"
            output_dir = root / "output"
            _write_reviewed_candidate_csv(
                reviewed_csv,
                _reviewed_candidate_rows(),
            )

            manifest = completion.run_reviewed_p0_horse_completion_batch(
                reviewed_candidates_csv=reviewed_csv,
                cache_dir=root / "cache",
                output_dir=output_dir,
                allow_network=False,
                generated_at="2026-07-18T00:00:00Z",
            )

            expected_files = set(manifest["files"]) | {
                "p0_horse_completion_batch_manifest.json"
            }
            actual_files = {
                path.name for path in output_dir.iterdir() if path.is_file()
            }
            persisted_manifest = json.loads(
                (
                    output_dir / "p0_horse_completion_batch_manifest.json"
                ).read_text(encoding="utf-8")
            )
            file_checks = {
                name: {
                    "size_bytes": len((output_dir / name).read_bytes()),
                    "sha256": hashlib.sha256(
                        (output_dir / name).read_bytes()
                    ).hexdigest(),
                }
                for name in manifest["files"]
            }
            sibling_residue = sorted(
                path.name
                for path in root.iterdir()
                if path not in {reviewed_csv, output_dir}
            )

        self.assertEqual(actual_files, expected_files)
        self.assertEqual(persisted_manifest, manifest)
        self.assertEqual(
            file_checks,
            {
                name: {
                    "size_bytes": metadata["size_bytes"],
                    "sha256": metadata["sha256"],
                }
                for name, metadata in manifest["files"].items()
            },
        )
        self.assertEqual(sibling_residue, [])
