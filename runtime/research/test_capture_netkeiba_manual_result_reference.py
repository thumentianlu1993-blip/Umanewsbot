#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


SCRIPT = Path(__file__).with_name("capture_netkeiba_manual_result_reference.py")


def load_tool():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("capture_netkeiba", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CaptureNetkeibaManualResultReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_tool()

    def test_parses_exact_winner_from_result_table(self):
        body = b"""
        <html><head><title>Irish Champion Stakes (G1) Full Result | 14 SEP 2024 R5</title></head>
        <body><span class='RaceName_main'>Irish Champion Stakes</span>
        <span class='Icon_GradeType Icon_GradeType1'>G1</span>
        <table class='ResultsByRaceDetail'><tbody>
        <tr><td>1</td><td></td><td>5</td><td>Economics</td></tr>
        <tr><td>2</td><td></td><td>3</td><td>Auguste Rodin</td></tr>
        </tbody></table></body></html>
        """
        parsed = self.module.parse_result(
            body,
            expected_race_name="Irish Champion Stakes",
            expected_date=date(2024, 9, 14),
            expected_grade="G1",
            expected_winner="Economics",
        )
        self.assertEqual(parsed["winner_name"], "Economics")
        self.assertEqual(parsed["parsed_result_rows"], 2)

    def test_network_gate_fails_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            with self.assertRaisesRegex(ValueError, "network gate"):
                self.module.capture_reference(
                    url="https://en.netkeiba.com/db/race/2024B1091405/",
                    expected_race_name="Irish Champion Stakes",
                    expected_date=date(2024, 9, 14),
                    expected_grade="G1",
                    expected_winner="Economics",
                    output_dir=output,
                    allow_network=False,
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
