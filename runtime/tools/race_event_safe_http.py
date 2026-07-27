#!/usr/bin/env python3
"""Compatibility entrypoint for the stable race-event HTTPS transport."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from urllib.request import build_opener

try:
    _implementation = import_module("stable.race_event_safe_http")
except ModuleNotFoundError:
    server_root = Path(__file__).resolve().parents[2] / "server"
    sys.path.insert(0, str(server_root))
    _implementation = import_module("stable.race_event_safe_http")


def _delegating_build_opener(*args, **kwargs):
    """Keep legacy monkeypatches effective while sharing one implementation."""
    return build_opener(*args, **kwargs)


_implementation.build_opener = _delegating_build_opener

Request = _implementation.Request
SafeHttpError = _implementation.SafeHttpError
ValidatingRedirectHandler = _implementation.ValidatingRedirectHandler
fetch_https = _implementation.fetch_https
validate_https_url = _implementation.validate_https_url

__all__ = _implementation.__all__
