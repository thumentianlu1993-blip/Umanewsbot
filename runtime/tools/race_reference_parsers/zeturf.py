"""Compatibility wrapper for the single stable ZEturf parser."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

try:
    implementation = import_module("stable.race_reference_parsers.zeturf")
except ModuleNotFoundError:
    server_root = Path(__file__).resolve().parents[3] / "server"
    sys.path.insert(0, str(server_root))
    implementation = import_module("stable.race_reference_parsers.zeturf")

sys.modules[__name__] = implementation
