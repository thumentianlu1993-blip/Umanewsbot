from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import timedelta
from pathlib import Path, PurePosixPath

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from stable.management.commands.build_internal_race_reference_manifest import (
    _strict_json_bytes,
)
from stable.services.race_reference_sources import (
    canonical_json_bytes,
    record_reference_collection,
    validate_reference_manifest,
    validate_source_identity,
)


ARTIFACT_FIELDS = {
    "schema_version",
    "manifest_sha256",
    "reference_schema_version",
    "parser",
    "files",
    "responses",
    "references_jsonl_sha256",
    "request_ledger_jsonl_sha256",
    "completed_at",
}
FILE_FIELDS = {"path", "size", "sha256"}
SHA256_CHARS = frozenset("0123456789abcdef")
LEDGER_COMMON_FIELDS = {
    "event_id",
    "local_date",
    "source_url",
    "fetched_at",
    "outcome",
    "phase",
    "request_issued",
}
LEDGER_ERROR_FIELDS = {"error_type", "error"}
LEDGER_RESPONSE_FIELDS = {
    "final_url",
    "status",
    "redirect_chain",
    "raw_sha256",
}
MAX_COMPLETED_AT_CLOCK_SKEW = timedelta(minutes=5)


def _sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _require_sha(value, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in SHA256_CHARS for char in value)
    ):
        raise CommandError(f"{label} 必须是小写 64 位 SHA-256")
    return value


def _read_regular(path: Path) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise CommandError(f"artifact 文件不可读：{path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise CommandError(f"artifact 路径必须是普通文件且不能是符号链接：{path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CommandError(f"artifact 文件打开失败：{path}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != info.st_dev
            or opened.st_ino != info.st_ino
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_size != info.st_size
        ):
            raise CommandError(f"artifact 文件身份在打开时发生变化：{path}")
        chunks = []
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        body = b"".join(chunks)
        after_fd = os.fstat(descriptor)
        try:
            after_path = path.lstat()
        except OSError as exc:
            raise CommandError(f"artifact 文件在读取后消失：{path}") from exc
        identities = (
            (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            ),
            (
                after_fd.st_dev,
                after_fd.st_ino,
                after_fd.st_mode,
                after_fd.st_size,
                after_fd.st_mtime_ns,
                after_fd.st_ctime_ns,
            ),
            (
                after_path.st_dev,
                after_path.st_ino,
                after_path.st_mode,
                after_path.st_size,
                after_path.st_mtime_ns,
                after_path.st_ctime_ns,
            ),
        )
        if identities[0] != identities[1] or identities[0] != identities[2]:
            raise CommandError(f"artifact 文件在读取期间发生变化：{path}")
        if len(body) != opened.st_size:
            raise CommandError(f"artifact 文件读取长度漂移：{path}")
        return body
    finally:
        os.close(descriptor)


def _strict_json_body(body: bytes, label: str):
    def pairs_hook(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"重复字段：{key}")
            value[key] = item
        return value

    try:
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"非法 JSON 常量：{token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise CommandError(f"{label} 不是 strict JSON：{exc}") from exc


def _build_error_summary(ledger_rows: list[dict]) -> dict:
    """Return bounded diagnostics without retaining provider bodies or secrets."""
    safe_messages = {
        "application_error": "application request failed",
        "budget_exhausted": "request budget exhausted",
        "circuit_open": "transport circuit open",
        "parse_error": "response parsing failed",
        "transport_error": "transport request failed",
    }
    by_outcome: dict[str, int] = {}
    details = []
    for row in ledger_rows:
        outcome = row["outcome"]
        if outcome == "parsed":
            continue
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if len(details) >= 20:
            continue
        message = safe_messages.get(outcome, "collection failed")[:500]
        detail = {
            "event_id": row["event_id"],
            "local_date": row["local_date"],
            "outcome": outcome,
            "phase": row["phase"],
            "error": message,
        }
        details.append(detail)
    return {
        "total": sum(by_outcome.values()),
        "by_outcome": dict(sorted(by_outcome.items())),
        "details": details,
    }


class Command(BaseCommand):
    help = "离线校验并记录内部参考 artifact；命令不包含任何网络入口"

    def add_arguments(self, parser):
        parser.add_argument("--manifest-file", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--artifact-dir", required=True)
        parser.add_argument("--artifact-sha256", required=True)

    def handle(self, *args, **options):
        manifest_path = Path(options["manifest_file"])
        manifest = _strict_json_bytes(manifest_path)
        manifest_sha = _require_sha(
            options["manifest_sha256"], "manifest-sha256"
        )
        try:
            manifest = validate_reference_manifest(
                manifest,
                manifest_sha256=manifest_sha,
            )
        except ValidationError as exc:
            raise CommandError(f"manifest 无效：{'; '.join(exc.messages)}") from exc
        canonical_manifest = canonical_json_bytes(manifest)
        if _read_regular(manifest_path) != canonical_manifest:
            raise CommandError("manifest 文件不是 canonical JSON bytes")

        artifact_dir = Path(options["artifact_dir"])
        try:
            root_info = artifact_dir.lstat()
        except OSError as exc:
            raise CommandError(f"artifact-dir 不存在：{exc}") from exc
        if not stat.S_ISDIR(root_info.st_mode):
            raise CommandError("artifact-dir 必须为真实目录且不能是符号链接")

        allowed_raw = {
            f"raw/{event['event_id']}.body" for event in manifest["events"]
        }
        required_files = {
            "manifest.json",
            "references.jsonl",
            "request_ledger.jsonl",
            "artifact.json",
            "COMPLETE",
        }
        actual_files: set[str] = set()
        for root, directories, files in os.walk(artifact_dir, followlinks=False):
            root_path = Path(root)
            for name in directories:
                path = root_path / name
                if path.is_symlink():
                    raise CommandError(f"artifact 包含符号链接目录：{path}")
                relative = path.relative_to(artifact_dir).as_posix()
                if relative != "raw":
                    raise CommandError(f"artifact 包含额外目录：{relative}")
            for name in files:
                path = root_path / name
                relative = path.relative_to(artifact_dir).as_posix()
                actual_files.add(relative)
                _read_regular(path)
        actual_raw = {
            path for path in actual_files if path.startswith("raw/")
        }
        if (
            not actual_raw <= allowed_raw
            or not required_files <= actual_files
            or actual_files - actual_raw != required_files
        ):
            raise CommandError(
                "artifact 文件集合不匹配："
                f"missing={sorted(required_files - actual_files)} "
                f"extra={sorted(actual_files - required_files - allowed_raw)}"
            )

        artifact_body = _read_regular(artifact_dir / "artifact.json")
        artifact = _strict_json_body(artifact_body, "artifact.json")
        if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_FIELDS:
            raise CommandError("artifact.json 字段不符合精确合同")
        if (
            isinstance(artifact.get("schema_version"), bool)
            or artifact.get("schema_version") != 1
        ):
            raise CommandError("artifact schema_version 必须为 1")
        if (
            isinstance(artifact.get("reference_schema_version"), bool)
            or artifact.get("reference_schema_version") != 1
        ):
            raise CommandError("artifact reference_schema_version 必须为 1")
        if artifact.get("manifest_sha256") != manifest_sha:
            raise CommandError("artifact 未绑定提供的 manifest SHA")
        if artifact.get("parser") != manifest["parser"]:
            raise CommandError("artifact parser 与 manifest 不一致")
        completed_at = artifact.get("completed_at")
        if not isinstance(completed_at, str):
            raise CommandError("artifact completed_at 必须为 aware ISO-8601")
        parsed_completed_at = parse_datetime(completed_at)
        if parsed_completed_at is None or timezone.is_naive(parsed_completed_at):
            raise CommandError("artifact completed_at 必须为 aware ISO-8601")
        if (
            parsed_completed_at
            > timezone.now() + MAX_COMPLETED_AT_CLOCK_SKEW
        ):
            raise CommandError("artifact completed_at 超出允许的未来时钟偏差")
        if artifact_body != canonical_json_bytes(artifact):
            raise CommandError("artifact.json 不是 canonical JSON bytes")
        artifact_sha = _require_sha(
            options["artifact_sha256"], "artifact-sha256"
        )
        if _sha256_bytes(artifact_body) != artifact_sha:
            raise CommandError("artifact SHA-256 不匹配")
        complete = _read_regular(artifact_dir / "COMPLETE")
        if complete != f"{artifact_sha}\n".encode("ascii"):
            raise CommandError("COMPLETE marker 与 artifact SHA 不一致")

        if _read_regular(artifact_dir / "manifest.json") != canonical_manifest:
            raise CommandError("artifact 中 manifest 与调用者 manifest 不一致")

        listed_paths: set[str] = set()
        files = artifact.get("files")
        if not isinstance(files, list):
            raise CommandError("artifact.files 必须为数组")
        expected_listed = actual_files - {"artifact.json", "COMPLETE"}
        for index, entry in enumerate(files):
            if not isinstance(entry, dict) or set(entry) != FILE_FIELDS:
                raise CommandError(f"artifact.files[{index}] 字段无效")
            relative = entry["path"]
            pure = PurePosixPath(relative) if isinstance(relative, str) else None
            if (
                pure is None
                or pure.is_absolute()
                or ".." in pure.parts
                or pure.as_posix() != relative
                or relative in listed_paths
                or relative not in expected_listed
            ):
                raise CommandError(f"artifact.files[{index}] 路径无效")
            listed_paths.add(relative)
            body = _read_regular(artifact_dir / relative)
            if (
                isinstance(entry["size"], bool)
                or not isinstance(entry["size"], int)
                or entry["size"] != len(body)
                or _require_sha(entry["sha256"], "file sha256")
                != _sha256_bytes(body)
            ):
                raise CommandError(f"artifact 文件大小或 SHA 漂移：{relative}")
        if listed_paths != expected_listed:
            raise CommandError("artifact.files 清单不完整")

        references_body = _read_regular(artifact_dir / "references.jsonl")
        ledger_body = _read_regular(artifact_dir / "request_ledger.jsonl")
        if (
            _require_sha(
                artifact["references_jsonl_sha256"],
                "references_jsonl_sha256",
            )
            != _sha256_bytes(references_body)
            or _require_sha(
                artifact["request_ledger_jsonl_sha256"],
                "request_ledger_jsonl_sha256",
            )
            != _sha256_bytes(ledger_body)
        ):
            raise CommandError("JSONL 摘要不匹配")

        observations = []
        for line_no, line in enumerate(references_body.splitlines(), start=1):
            if not line:
                raise CommandError("references.jsonl 不允许空行")
            observations.append(
                _strict_json_body(line, f"references.jsonl:{line_no}")
            )

        responses = artifact.get("responses")
        if not isinstance(responses, list):
            raise CommandError("artifact.responses 必须为数组")
        response_ids: set[int] = set()
        response_sha_by_event: dict[int, str] = {}
        for index, response in enumerate(responses):
            if (
                not isinstance(response, dict)
                or set(response) != {"event_id", "raw_sha256"}
            ):
                raise CommandError(f"artifact.responses[{index}] 字段无效")
            event_id = response["event_id"]
            if (
                isinstance(event_id, bool)
                or not isinstance(event_id, int)
                or event_id in response_ids
                or f"raw/{event_id}.body" not in allowed_raw
            ):
                raise CommandError("artifact.responses event_id 无效或重复")
            response_ids.add(event_id)
            raw = _read_regular(artifact_dir / f"raw/{event_id}.body")
            response_sha = _require_sha(
                response["raw_sha256"],
                "response raw_sha256",
            )
            if response_sha != _sha256_bytes(raw):
                raise CommandError("artifact response raw SHA 不匹配")
            response_sha_by_event[event_id] = response_sha
        if response_ids != {
            int(path.removeprefix("raw/").removesuffix(".body"))
            for path in actual_raw
        }:
            raise CommandError("artifact.responses 与 raw 文件集合不一致")

        for index, observation in enumerate(observations):
            if not isinstance(observation, dict):
                raise CommandError(f"references[{index}] 必须为 object")
            provenance = observation.get("provenance")
            if not isinstance(provenance, dict):
                raise CommandError(f"references[{index}].provenance 必须为 object")
            raw_relative = provenance.get("source_cache_ref")
            if raw_relative not in actual_raw:
                raise CommandError(
                    f"references[{index}] 引用未绑定的 raw 文件"
                )
            raw_body = _read_regular(artifact_dir / raw_relative)
            if provenance.get("raw_sha256") != _sha256_bytes(raw_body):
                raise CommandError(f"references[{index}] raw_sha256 不匹配")

        ledger_rows = []
        ledger_event_ids: set[int] = set()
        manifest_event_ids = {
            event["event_id"] for event in manifest["events"]
        }
        manifest_by_event_id = {
            event["event_id"]: event for event in manifest["events"]
        }
        parse_response_ledger_ids: set[int] = set()
        parsed_ledger_ids: set[int] = set()
        parse_error_ledger_ids: set[int] = set()
        ledger_fetched_at_values = []
        parsed_ledger_evidence_by_event: dict[int, dict] = {}
        for line_no, line in enumerate(ledger_body.splitlines(), start=1):
            if not line:
                raise CommandError("request_ledger.jsonl 不允许空行")
            row = _strict_json_body(line, f"request_ledger.jsonl:{line_no}")
            if not isinstance(row, dict):
                raise CommandError("request ledger 行必须为 object")
            outcome = row.get("outcome")
            phase = row.get("phase")
            request_issued = row.get("request_issued")
            if outcome in {"budget_exhausted", "circuit_open"}:
                expected_fields = LEDGER_COMMON_FIELDS
                expected_phase = "scheduler"
                expected_request_issued = False
            elif outcome == "transport_error":
                expected_fields = LEDGER_COMMON_FIELDS | LEDGER_ERROR_FIELDS
                expected_phase = "fetch"
                expected_request_issued = True
            elif outcome == "application_error":
                expected_fields = LEDGER_COMMON_FIELDS | LEDGER_ERROR_FIELDS
                if phase == "preflight":
                    expected_phase = "preflight"
                    expected_request_issued = False
                elif phase == "fetch":
                    expected_phase = "fetch"
                    expected_request_issued = True
                else:
                    raise CommandError("application_error ledger phase 无效")
            elif outcome == "parsed":
                expected_fields = (
                    LEDGER_COMMON_FIELDS | LEDGER_RESPONSE_FIELDS
                )
                expected_phase = "parse"
                expected_request_issued = True
            elif outcome == "parse_error":
                expected_fields = (
                    LEDGER_COMMON_FIELDS
                    | LEDGER_RESPONSE_FIELDS
                    | LEDGER_ERROR_FIELDS
                )
                expected_phase = "parse"
                expected_request_issued = True
            else:
                raise CommandError("request ledger outcome 无效")
            if set(row) != expected_fields:
                raise CommandError(
                    f"request_ledger.jsonl:{line_no} 字段不符合精确合同"
                )
            if (
                phase != expected_phase
                or request_issued is not expected_request_issued
            ):
                raise CommandError(
                    f"request_ledger.jsonl:{line_no} 请求阶段或issued标记无效"
                )
            event_id = row.get("event_id")
            if (
                isinstance(event_id, bool)
                or not isinstance(event_id, int)
                or event_id not in manifest_event_ids
                or event_id in ledger_event_ids
            ):
                raise CommandError("request ledger event_id 无效或重复")
            ledger_event_ids.add(event_id)
            manifest_event = manifest_by_event_id[event_id]
            if row.get("local_date") != manifest_event["local_date"]:
                raise CommandError(
                    "request ledger local_date 与 manifest event 不一致"
                )
            if row.get("source_url") != manifest_event["source_url"]:
                raise CommandError(
                    "request ledger source_url 与 manifest event 不一致"
                )
            fetched_at = row.get("fetched_at")
            parsed_fetched_at = (
                parse_datetime(fetched_at)
                if isinstance(fetched_at, str)
                else None
            )
            if (
                parsed_fetched_at is None
                or timezone.is_naive(parsed_fetched_at)
            ):
                raise CommandError("request ledger fetched_at 必须为aware时间")
            ledger_fetched_at_values.append(parsed_fetched_at)
            if outcome in {"parsed", "parse_error"}:
                if (
                    response_sha_by_event.get(event_id)
                    != _require_sha(
                        row["raw_sha256"],
                        "ledger raw_sha256",
                    )
                    or not isinstance(row["final_url"], str)
                    or isinstance(row["status"], bool)
                    or not isinstance(row["status"], int)
                    or not isinstance(row["redirect_chain"], list)
                ):
                    raise CommandError("request ledger response证据无效")
                try:
                    validate_source_identity(
                        source_key=manifest["source_key"],
                        country_region=manifest_event["country_region"],
                        provider_event_key=manifest_event[
                            "provider_event_key"
                        ],
                        source_url=row["final_url"],
                    )
                except ValidationError as exc:
                    raise CommandError(
                        "request ledger final_url 来源身份无效"
                    ) from exc
                parse_response_ledger_ids.add(event_id)
                if outcome == "parsed":
                    parsed_ledger_ids.add(event_id)
                    parsed_ledger_evidence_by_event[event_id] = {
                        "source_url": row["source_url"],
                        "final_url": row["final_url"],
                        "fetched_at": parsed_fetched_at,
                    }
                else:
                    parse_error_ledger_ids.add(event_id)
            if outcome in {
                "transport_error",
                "application_error",
                "parse_error",
            } and (
                not isinstance(row.get("error_type"), str)
                or not isinstance(row.get("error"), str)
            ):
                raise CommandError("request ledger error证据无效")
            ledger_rows.append(row)
        if ledger_event_ids != manifest_event_ids:
            raise CommandError(
                "request ledger event集合与 manifest events 不一致"
            )
        if response_ids != parse_response_ledger_ids:
            raise CommandError(
                "artifact.responses 与 parse阶段 ledger events 不一致"
            )
        if not ledger_fetched_at_values:
            raise CommandError("request ledger 必须包含至少一条签名时间")
        collection_started_at = min(ledger_fetched_at_values)
        collection_latest_at = max(ledger_fetched_at_values)
        if collection_latest_at > parsed_completed_at:
            raise CommandError("artifact completed_at 早于 ledger fetched_at")

        manifest_by_provider_key = {
            event["provider_event_key"]: event
            for event in manifest["events"]
        }
        observation_event_ids = []
        for index, observation in enumerate(observations):
            payload = observation.get("payload")
            provenance = observation.get("provenance")
            if not isinstance(payload, dict) or not isinstance(provenance, dict):
                raise CommandError(
                    f"references[{index}] 缺少有效 payload/provenance"
                )
            manifest_event = manifest_by_provider_key.get(
                payload.get("provider_event_key")
            )
            if manifest_event is None:
                raise CommandError(
                    f"references[{index}] provider event 不在 manifest"
                )
            event_id = manifest_event["event_id"]
            observation_event_ids.append(event_id)
            expected_raw_ref = f"raw/{event_id}.body"
            ledger_evidence = parsed_ledger_evidence_by_event.get(event_id)
            provenance_fetched_at = (
                parse_datetime(provenance.get("fetched_at"))
                if isinstance(provenance.get("fetched_at"), str)
                else None
            )
            if (
                ledger_evidence is None
                or provenance.get("source_url")
                != manifest_event["source_url"]
                or provenance.get("final_url")
                != ledger_evidence["final_url"]
                or provenance_fetched_at is None
                or timezone.is_naive(provenance_fetched_at)
                or provenance_fetched_at != ledger_evidence["fetched_at"]
                or provenance.get("source_cache_ref")
                != expected_raw_ref
                or provenance.get("raw_sha256")
                != response_sha_by_event.get(event_id)
                or event_id not in parsed_ledger_ids
            ):
                raise CommandError(
                    f"references[{index}] provenance 未绑定对应 event ledger"
                )
        observation_event_id_set = set(observation_event_ids)
        if len(observation_event_ids) != len(observation_event_id_set):
            raise CommandError("每个 parsed event 必须恰好有一条 observation")
        if observation_event_id_set & parse_error_ledger_ids:
            raise CommandError("parse_error event 不得包含 observation")
        if observation_event_id_set != parsed_ledger_ids:
            raise CommandError(
                "observations event集合必须与成功 parsed ledger events 一致"
            )

        service_artifact = {
            "artifact_sha256": artifact_sha,
            "observations": observations,
            "request_count": sum(
                row["request_issued"] for row in ledger_rows
            ),
            "cache_hit_count": 0,
            "error_count": sum(
                row.get("outcome") != "parsed" for row in ledger_rows
            ),
            "summary": {
                "artifact_file_count": len(files),
                "observation_count": len(observations),
            },
            "error_summary": _build_error_summary(ledger_rows),
        }
        try:
            result = record_reference_collection(
                manifest=manifest,
                manifest_sha256=manifest_sha,
                artifact=service_artifact,
                collection_started_at=collection_started_at,
                collection_finished_at=parsed_completed_at,
            )
        except ValidationError as exc:
            raise CommandError(f"record 拒绝：{'; '.join(exc.messages)}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"record 完成：run_id={result['run_id']} "
                f"receipts={result['receipt_count']} replayed={result['replayed']}"
            )
        )
