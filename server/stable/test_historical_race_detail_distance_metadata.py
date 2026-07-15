from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest import skipUnless

from django.test import SimpleTestCase


TOOLS = Path(__file__).resolve().parents[2] / "runtime" / "tools"
CACHE_RUN_ROOT_VALUE = os.environ.get("HISTORICAL_DETAIL_DISTANCE_CACHE_RUN_ROOT", "")
CACHE_RUN_ROOT = Path(CACHE_RUN_ROOT_VALUE) if CACHE_RUN_ROOT_VALUE else None


def _load(name: str):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(f"{path.stem}_distance_metadata_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(TOOLS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _cached_source(smoke_name: str) -> tuple[str, bytes]:
    assert CACHE_RUN_ROOT is not None
    cache_root = (CACHE_RUN_ROOT / smoke_name / "source-cache").resolve()
    manifest = json.loads((cache_root / "source_cache_manifest.json").read_text(encoding="utf-8"))
    identities = list(manifest["files"].values())
    if len(identities) != 1:
        raise AssertionError(f"expected one cached source for {smoke_name}, got {len(identities)}")
    identity = identities[0]
    source_path = (cache_root / identity["path"]).resolve()
    source_path.relative_to(cache_root)
    body = source_path.read_bytes()
    if len(body) != int(identity["size"]):
        raise AssertionError(f"cache size mismatch: {source_path}")
    if hashlib.sha256(body).hexdigest() != identity["sha256"]:
        raise AssertionError(f"cache sha256 mismatch: {source_path}")
    return identity["source_url"], body


@skipUnless(CACHE_RUN_ROOT is not None, "real cache root not configured")
class HistoricalRaceDetailDistanceMetadataRealCacheTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cached = _load("prepare_cached_historical_race_details.py")
        cls.sporting_life = _load("prepare_uk_sportinglife_race_detail_candidates.py")

    def test_jra_2005_legacy_page_preserves_distance_unit(self):
        source_url, body = _cached_source("smoke-japan-50556")

        _runners, _results, metadata = self.cached.parse_jra_detail(body, source_url=source_url)

        self.assertEqual(metadata["distance_text"], "1600ｍ")

    def test_sporting_life_race_118984_preserves_distance_units(self):
        source_url, body = _cached_source("smoke-united_kingdom-56980")

        _runners, _results, metadata = self.sporting_life._parse_detail_page(
            body.decode("utf-8", errors="replace"),
            source_url=source_url,
        )

        self.assertEqual(metadata["race_id"], 118984)
        self.assertEqual(metadata["distance_text"], "2m 4f 0y")

    def test_equibase_yearbook_result_preserves_distance_unit(self):
        source_url, body = _cached_source("smoke-united_states-70844")

        _runners, _results, metadata = self.cached.parse_equibase_yearbook(
            body.decode("utf-8", errors="replace"),
            source_url=source_url,
        )

        self.assertEqual(metadata["distance_text"], "One Mile")
