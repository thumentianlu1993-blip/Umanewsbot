from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.management.commands.build_internal_race_reference_manifest import (
    _load_verified_parser_module,
    _reject_public_output,
    _strict_json_bytes,
)
from stable.services.race_reference_sources import (
    SOURCE_REGISTRY,
    canonical_json_bytes,
    canonical_json_sha256,
    get_reference_parser_contract,
    normalize_reference_payload,
    reference_racecourse_matches,
    validate_reference_manifest,
    validate_source_identity,
)
from stable.services.race_live_racecard_sync import normalize_identity_text


PARSER_MODULES = {
    source_key: get_reference_parser_contract(source_key)["module"]
    for source_key in SOURCE_REGISTRY
}
PATH_PATTERNS = {
    "reference_sporting_life": r"^/racing/results/",
    "reference_zeturf": r"^/fr/course-du-jour/",
    "reference_horse_racing_nation": r"^/entries-results/",
}
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def _is_transport_error(exc: Exception, *, safe_http) -> bool:
    if isinstance(exc, safe_http.SafeHttpError):
        return True
    if isinstance(exc, HTTPError):
        return exc.code in {403, 408, 429} or 500 <= exc.code <= 599
    if isinstance(exc, URLError):
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


def _classify_page_identity(
    *,
    source_key: str,
    parsed_race: object,
    parsed_completeness: object,
    manifest_event: dict,
) -> tuple[str, int, dict]:
    if not isinstance(parsed_race, dict):
        return (
            "source_only",
            0,
            {"reason": "page_race_identity_missing"},
        )
    page_date = parsed_race.get("local_date")
    page_course = parsed_race.get("source_racecourse")
    page_name = str(parsed_race.get("source_race_name") or "").strip()
    try:
        normalized_page_name = normalize_identity_text(page_name)
    except ValueError:
        normalized_page_name = None
    accepted_names = manifest_event["normalized_accepted_race_names"]
    name_matches = (
        normalized_page_name is not None
        and normalized_page_name in accepted_names
    )
    race_identity_complete = (
        isinstance(parsed_completeness, dict)
        and parsed_completeness.get("race_identity") == "complete"
    )
    date_matches = page_date == manifest_event["local_date"]
    course_matches = reference_racecourse_matches(
        source_key=source_key,
        page_value=page_course,
        manifest_value=manifest_event["racecourse"],
    )
    if (
        not race_identity_complete
        or not date_matches
        or not course_matches
        or not name_matches
    ):
        return (
            "source_only",
            0,
            {
                "reason": "page_race_identity_conflict",
                "local_date_matches": date_matches,
                "racecourse_matches": course_matches,
                "race_name_present": bool(page_name),
                "race_name_matches": name_matches,
                "race_identity_complete": race_identity_complete,
            },
        )
    return (
        "matched",
        100,
        {
            "reason": (
                "provider_identity_region_date_racecourse_name_verified"
            ),
            "local_date_matches": True,
            "racecourse_matches": True,
            "race_name_present": True,
            "race_identity_complete": True,
        },
    )


def _write_new(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise CommandError(f"拒绝覆盖 artifact 文件：{path}: {exc}") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def _jsonl_bytes(rows: list[dict]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


class Command(BaseCommand):
    help = "按冻结 manifest 采集赛后内部参考；默认禁止联网且数据库零写"

    def add_arguments(self, parser):
        parser.add_argument("--manifest-file", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--max-requests", type=int)
        parser.add_argument("--timeout-seconds", type=int, default=15)
        parser.add_argument("--allow-network", action="store_true")

    def handle(self, *args, **options):
        if not options["allow_network"]:
            raise CommandError("collect 默认禁止联网；需单独授权后显式传 --allow-network")
        timeout = options["timeout_seconds"]
        if timeout != 15:
            raise CommandError("timeout-seconds 固定为 15，不允许覆盖")

        manifest_path = Path(options["manifest_file"])
        manifest = _strict_json_bytes(manifest_path)
        supplied_sha = options["manifest_sha256"]
        try:
            manifest = validate_reference_manifest(
                manifest,
                manifest_sha256=supplied_sha,
            )
        except ValidationError as exc:
            raise CommandError(f"manifest 无效：{'; '.join(exc.messages)}") from exc
        canonical_manifest = canonical_json_bytes(manifest)
        if manifest_path.read_bytes() != canonical_manifest:
            raise CommandError("manifest 文件不是精确 canonical JSON bytes")
        source_key = manifest["source_key"]
        parser_module, _parser_identity = _load_verified_parser_module(
            source_key,
            manifest_parser=manifest["parser"],
        )

        targets = len(manifest["events"])
        max_requests = (
            targets if options["max_requests"] is None else options["max_requests"]
        )
        if not 1 <= max_requests <= min(targets, 100):
            raise CommandError(
                "max-requests 必须在 1..100 且不得超过 manifest 目标数"
            )

        output_dir = Path(options["output_dir"])
        _reject_public_output(output_dir)
        lock_path = output_dir.with_name(output_dir.name + ".lock")
        if output_dir.exists() or output_dir.is_symlink():
            raise CommandError("output-dir 必须不存在")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = os.open(
                lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as exc:
            raise CommandError(f"无法取得 artifact 外置锁：{lock_path}: {exc}") from exc

        try:
            os.write(lock_fd, f"{os.getpid()}\n".encode("ascii"))
            os.fsync(lock_fd)
            output_dir.mkdir(mode=0o700)
            raw_dir = output_dir / "raw"
            raw_dir.mkdir(mode=0o700)
            _write_new(output_dir / "manifest.json", canonical_manifest)

            safe_http = importlib.import_module("stable.race_event_safe_http")
            observations: list[dict] = []
            ledger: list[dict] = []
            responses: list[dict] = []
            file_entries: list[dict] = []
            attempted_requests = 0
            consecutive_transport_failures = 0

            for event in manifest["events"]:
                if attempted_requests >= max_requests:
                    ledger.append(
                        {
                            "event_id": event["event_id"],
                            "local_date": event["local_date"],
                            "source_url": event["source_url"],
                            "fetched_at": timezone.now().isoformat(),
                            "outcome": "budget_exhausted",
                            "phase": "scheduler",
                            "request_issued": False,
                        }
                    )
                    continue
                if consecutive_transport_failures >= 3:
                    ledger.append(
                        {
                            "event_id": event["event_id"],
                            "local_date": event["local_date"],
                            "source_url": event["source_url"],
                            "fetched_at": timezone.now().isoformat(),
                            "outcome": "circuit_open",
                            "phase": "scheduler",
                            "request_issued": False,
                        }
                    )
                    continue
                fetched_at = timezone.now().isoformat()
                try:
                    context = validate_source_identity(
                        source_key=source_key,
                        country_region=event["country_region"],
                        provider_event_key=event["provider_event_key"],
                        source_url=event["source_url"],
                    )
                except Exception as exc:
                    ledger.append(
                        {
                            "event_id": event["event_id"],
                            "local_date": event["local_date"],
                            "source_url": event["source_url"],
                            "fetched_at": fetched_at,
                            "outcome": "application_error",
                            "phase": "preflight",
                            "request_issued": False,
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:500],
                        }
                    )
                    continue

                attempted_requests += 1
                try:
                    raw, response = safe_http.fetch_https(
                        event["source_url"],
                        allowed_hosts=(SOURCE_REGISTRY[source_key]["host"],),
                        allowed_path_pattern=PATH_PATTERNS[source_key],
                        allowed_content_types=(
                            "text/html",
                            "application/xhtml+xml",
                        ),
                        timeout=timeout,
                        max_bytes=MAX_RESPONSE_BYTES,
                        max_redirects=2,
                        url_validator=lambda candidate_url: validate_source_identity(
                            source_key=source_key,
                            country_region=event["country_region"],
                            provider_event_key=event["provider_event_key"],
                            source_url=candidate_url,
                        ),
                        headers={
                            "User-Agent": (
                                "umanewsbot/1.0 "
                                "(+https://umafans.run; private low-frequency reference)"
                            )
                        },
                    )
                except Exception as exc:
                    transport_error = _is_transport_error(
                        exc,
                        safe_http=safe_http,
                    )
                    ledger.append(
                        {
                            "event_id": event["event_id"],
                            "local_date": event["local_date"],
                            "source_url": event["source_url"],
                            "fetched_at": fetched_at,
                            "outcome": (
                                "transport_error"
                                if transport_error
                                else "application_error"
                            ),
                            "phase": "fetch",
                            "request_issued": True,
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:500],
                        }
                    )
                    if transport_error:
                        consecutive_transport_failures += 1
                    continue

                consecutive_transport_failures = 0
                raw_relative = f"raw/{event['event_id']}.body"
                raw_sha = hashlib.sha256(raw).hexdigest()
                _write_new(output_dir / raw_relative, raw)
                responses.append(
                    {
                        "event_id": event["event_id"],
                        "raw_sha256": raw_sha,
                    }
                )

                try:
                    validate_source_identity(
                        source_key=source_key,
                        country_region=event["country_region"],
                        provider_event_key=event["provider_event_key"],
                        source_url=response["final_url"],
                    )
                    parsed = parser_module.parse_reference_page(
                        raw,
                        response["final_url"],
                        context,
                    )
                    if parsed.get("provider_event_key") != event["provider_event_key"]:
                        raise RuntimeError("parser provider identity mismatch")
                    match_status, match_confidence, identity_evidence = (
                        _classify_page_identity(
                            source_key=source_key,
                            parsed_race=parsed.get("race"),
                            parsed_completeness=parsed.get("completeness"),
                            manifest_event=event,
                        )
                    )
                    payload = {
                        "schema_version": 1,
                        "source_key": source_key,
                        "country_region": event["country_region"],
                        "provider_event_key": event["provider_event_key"],
                        "race": {
                            "source_race_name": parsed["race"][
                                "source_race_name"
                            ],
                            "source_racecourse": parsed["race"][
                                "source_racecourse"
                            ],
                            "local_date": parsed["race"]["local_date"],
                            "source_start_time": parsed["race"][
                                "source_start_time"
                            ],
                        },
                        "runners": parsed["runners"],
                        "completeness": parsed["completeness"],
                    }
                    normalize_reference_payload(payload)
                    observation = {
                        "payload": payload,
                        "provenance": {
                            "source_url": event["source_url"],
                            "final_url": response["final_url"],
                            "source_observed_at": None,
                            "fetched_at": fetched_at,
                            "parser": manifest["parser"],
                            "legacy_payload_sha256": parsed[
                                "legacy_payload_sha256"
                            ],
                            "raw_sha256": raw_sha,
                            "source_cache_ref": raw_relative,
                        },
                        "event_id": (
                            event["event_id"] if match_status == "matched" else None
                        ),
                        "match_status": match_status,
                        "match_confidence": match_confidence,
                        "match_evidence": {
                            "provider_event_key": event["provider_event_key"],
                            "page_race": parsed["race"],
                            "parser_evidence": parsed.get("parser_evidence", {}),
                            **identity_evidence,
                            "manifest_event_snapshot_sha256": event[
                                "event_snapshot_sha256"
                            ],
                        },
                        "classification_version": "race-reference-v1",
                    }
                    observations.append(observation)
                    ledger.append(
                        {
                            "event_id": event["event_id"],
                            "local_date": event["local_date"],
                            "source_url": event["source_url"],
                            "final_url": response["final_url"],
                            "status": response["status"],
                            "redirect_chain": response["redirect_chain"],
                            "raw_sha256": raw_sha,
                            "fetched_at": fetched_at,
                            "outcome": "parsed",
                            "phase": "parse",
                            "request_issued": True,
                        }
                    )
                except Exception as exc:
                    ledger.append(
                        {
                            "event_id": event["event_id"],
                            "local_date": event["local_date"],
                            "source_url": event["source_url"],
                            "final_url": response.get("final_url", ""),
                            "status": response.get("status"),
                            "redirect_chain": response.get(
                                "redirect_chain",
                                [],
                            ),
                            "raw_sha256": raw_sha,
                            "fetched_at": fetched_at,
                            "outcome": "parse_error",
                            "phase": "parse",
                            "request_issued": True,
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:500],
                        }
                    )

            references_bytes = _jsonl_bytes(observations)
            ledger_bytes = _jsonl_bytes(ledger)
            _write_new(output_dir / "references.jsonl", references_bytes)
            _write_new(output_dir / "request_ledger.jsonl", ledger_bytes)

            for path in sorted(
                [
                    *(output_dir / "raw").glob("*.body"),
                    output_dir / "manifest.json",
                    output_dir / "references.jsonl",
                    output_dir / "request_ledger.jsonl",
                ],
                key=lambda item: item.relative_to(output_dir).as_posix(),
            ):
                body = path.read_bytes()
                file_entries.append(
                    {
                        "path": path.relative_to(output_dir).as_posix(),
                        "size": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                    }
                )
            artifact = {
                "schema_version": 1,
                "manifest_sha256": supplied_sha,
                "reference_schema_version": 1,
                "parser": manifest["parser"],
                "files": file_entries,
                "responses": responses,
                "references_jsonl_sha256": hashlib.sha256(
                    references_bytes
                ).hexdigest(),
                "request_ledger_jsonl_sha256": hashlib.sha256(
                    ledger_bytes
                ).hexdigest(),
                "completed_at": timezone.now().isoformat(),
            }
            artifact_bytes = canonical_json_bytes(artifact)
            artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
            _write_new(output_dir / "artifact.json", artifact_bytes)
            _write_new(output_dir / "COMPLETE", f"{artifact_sha}\n".encode("ascii"))
            self.stdout.write(
                self.style.SUCCESS(
                    f"采集完成：targets={targets} requests={attempted_requests} "
                    f"parsed={len(observations)} errors={sum(row['outcome'] != 'parsed' for row in ledger)} "
                    f"artifact_sha256={artifact_sha}"
                )
            )
        finally:
            os.close(lock_fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
