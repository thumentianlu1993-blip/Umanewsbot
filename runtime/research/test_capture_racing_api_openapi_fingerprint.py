#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT = Path(__file__).with_name("capture_racing_api_openapi_fingerprint.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("capture_openapi_fingerprint", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CaptureRacingApiOpenapiFingerprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def document(self) -> dict:
        paths = {}
        for index, path in enumerate(self.module.SELECTED_PATHS):
            paths[path] = {
                "get": {
                    "tags": ["Horses", *sorted(self.module.EXPECTED_OPERATION_PLANS[path])],
                    "description": (
                        "Rate Limit 5 requests per second; historical results add-on"
                        if path == "/v1/results"
                        else "Rate Limit 5 requests per second"
                    ),
                    "operationId": f"operation_{index}",
                }
            }
        return {
            "openapi": "3.1.0",
            "info": {"title": "The Racing API", "version": "1.4.4"},
            "paths": paths,
            "components": {
                "schemas": {
                    name: {"type": "object", "title": name}
                    for name in self.module.SELECTED_SCHEMAS
                }
            },
        }

    def test_capture_writes_private_exact_fingerprint_and_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "openapi.json"
            raw.write_text(json.dumps(self.document()), encoding="utf-8")
            output = root / "fingerprint.json"
            review = root / "review.json"
            result = self.module.capture(
                raw_openapi_path=raw,
                generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                output_path=output,
                review_path=review,
            )
            fingerprint = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(fingerprint["openapi_version"], "1.4.4")
            self.assertEqual(
                fingerprint["selected_schema"]["names"],
                list(self.module.SELECTED_SCHEMAS),
            )
            self.assertTrue(result["historical_bulk_add_on_declared"])
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(review.stat().st_mode), 0o600)

    def test_missing_schema_and_rate_limit_drift_fail_closed(self):
        document = self.document()
        document["components"]["schemas"].pop("Horse")
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "openapi.json"
            raw.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema is missing"):
                self.module.build_fingerprint(
                    raw_openapi_path=raw,
                    generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                )
        document = self.document()
        document["paths"]["/v1/results"]["get"]["description"] = "Rate Limit 1 request per second"
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / "openapi.json"
            raw.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "entitlement/rate"):
                self.module.build_fingerprint(
                    raw_openapi_path=raw,
                    generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                )

    def test_duplicate_keys_non_finite_and_existing_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "openapi.json"
            raw.write_text('{"openapi":"3.1.0","openapi":"3.1.0"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                self.module.build_fingerprint(
                    raw_openapi_path=raw,
                    generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                )
            raw.write_text(json.dumps(self.document()), encoding="utf-8")
            output = root / "fingerprint.json"
            output.write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not already exist"):
                self.module.capture(
                    raw_openapi_path=raw,
                    generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                    output_path=output,
                    review_path=root / "review.json",
                )


if __name__ == "__main__":
    unittest.main()
