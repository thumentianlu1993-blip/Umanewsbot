from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError


COVERAGE_KEYS = ("races", "entries", "results", "horses")
IGNORED_ARTIFACT_TYPES = {"global_racing_batch_command", "global_racing_batch_commands"}


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


class Command(BaseCommand):
    help = "离线汇总全球赛马数据库导入 dry-run JSON 输出，用于进入 commit 前审计。"

    def add_arguments(self, parser):
        parser.add_argument("--input-dir", required=True, help="包含 plan/dry-run JSON 输出的目录")
        parser.add_argument("--pattern", default="*.json", help="文件匹配模式，默认 *.json")
        parser.add_argument(
            "--fail-on-incomplete",
            action="store_true",
            help="发现 incomplete、不可解析、非 dry-run 或 plan 覆盖不一致时以 CommandError 失败",
        )
        parser.add_argument(
            "--proof-only",
            action="store_true",
            help="按少量真实 dry-run proof 口径审计；允许受限 incomplete，但要求有成功请求且不写表。",
        )
        parser.add_argument(
            "--expected-sources",
            help="逗号分隔的期望 source 清单；proof-only 审计会要求这些来源都存在。",
        )
        parser.add_argument(
            "--expected-request-types",
            help="逗号分隔的 source:type|type 清单；proof-only 审计会要求对应来源包含这些请求类型。",
        )

    def handle(self, *args, **options):
        input_dir = Path(options["input_dir"])
        if not input_dir.exists() or not input_dir.is_dir():
            raise CommandError(f"input-dir does not exist or is not a directory: {input_dir}")

        files = sorted(path for path in input_dir.glob(options["pattern"]) if path.is_file())
        if not files:
            raise CommandError(f"no files matched {options['pattern']} in {input_dir}")

        expected_sources = self._expected_sources(options.get("expected_sources"))
        expected_request_types = self._expected_request_types(options.get("expected_request_types"))
        summary = self._summarize_files(
            files,
            input_dir=input_dir,
            expected_sources=expected_sources,
            expected_request_types=expected_request_types,
        )
        summary["audit_parameters"] = {
            "input_dir": str(input_dir),
            "pattern": options["pattern"],
            "proof_only": bool(options["proof_only"]),
            "fail_on_incomplete": bool(options["fail_on_incomplete"]),
            "expected_sources": sorted(expected_sources or set()),
            "expected_request_types": {
                source: sorted(request_types)
                for source, request_types in sorted((expected_request_types or {}).items())
            },
        }
        if options["fail_on_incomplete"] and options["proof_only"] and not summary["proof_ready"]:
            raise CommandError("incomplete global racing proof outputs: " + ", ".join(summary["proof_blocking_reasons"]))
        if options["fail_on_incomplete"] and not options["proof_only"] and not summary["commit_candidate_ready"]:
            raise CommandError("incomplete global racing import outputs: " + ", ".join(summary["blocking_reasons"]))

        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))

    def _summarize_files(
        self,
        files: list[Path],
        *,
        input_dir: Path,
        expected_sources: set[str] | None = None,
        expected_request_types: dict[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        file_summaries: list[dict[str, Any]] = []
        incomplete_files: list[dict[str, Any]] = []
        invalid_files: list[dict[str, Any]] = []
        non_dry_run_files: list[dict[str, Any]] = []
        proof_plan_files: list[dict[str, Any]] = []
        proof_empty_request_files: list[dict[str, Any]] = []
        proof_non_success_response_files: list[dict[str, Any]] = []
        proof_empty_coverage_files: list[dict[str, Any]] = []
        proof_disallowed_stop_files: list[dict[str, Any]] = []
        incomplete_plan_files: list[dict[str, Any]] = []
        non_dry_run_plan_files: list[dict[str, Any]] = []
        limited_plan_files: list[dict[str, Any]] = []
        empty_plan_request_files: list[dict[str, Any]] = []
        non_success_plan_response_files: list[dict[str, Any]] = []
        empty_batch_request_files: list[dict[str, Any]] = []
        non_success_batch_response_files: list[dict[str, Any]] = []
        empty_batch_coverage_files: list[dict[str, Any]] = []
        incomplete_horse_detail_files: list[dict[str, Any]] = []
        missing_source_files: list[dict[str, Any]] = []
        would_write_formal_table_files: list[dict[str, Any]] = []
        planned_items: set[str] = set()
        covered_items: set[str] = set()
        planned_item_counts: dict[str, int] = {}
        covered_item_counts: dict[str, int] = {}
        proof_sources: dict[str, dict[str, Any]] = {}
        proof_request_types_by_source: dict[str, set[str]] = {}
        sources: set[str] = set()
        coverage_totals = {key: 0 for key in COVERAGE_KEYS}
        total_requests = 0
        proof_total_requests = 0
        proof_successful_response_count = 0
        plan_file_count = 0
        batch_file_count = 0
        ignored_artifact_files: list[dict[str, Any]] = []

        for path in files:
            rel_path = str(path.relative_to(input_dir))
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                item = {"path": rel_path, "error": str(exc)}
                invalid_files.append(item)
                file_summaries.append({"path": rel_path, "valid": False, "error": str(exc)})
                continue

            if not isinstance(payload, dict):
                item = {"path": rel_path, "error": "top-level JSON is not an object"}
                invalid_files.append(item)
                file_summaries.append({"path": rel_path, "valid": False, "error": item["error"]})
                continue

            artifact_type = _string(payload.get("artifact_type"))
            if artifact_type in IGNORED_ARTIFACT_TYPES:
                ignored_artifact_files.append({"path": rel_path, "artifact_type": artifact_type})
                continue

            completion = payload.get("completion") if isinstance(payload.get("completion"), dict) else {}
            coverage = payload.get("coverage_stats") if isinstance(payload.get("coverage_stats"), dict) else {}
            requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
            source = _string(payload.get("source"))
            successful_responses = self._successful_response_count(requests)
            is_plan = bool(payload.get("plan_only")) or completion.get("stop_reason") == "plan_only"
            is_complete = completion.get("is_complete") is True
            dry_run = payload.get("dry_run")
            if source:
                sources.add(source)
                proof_request_types_by_source.setdefault(source, set()).update(self._request_target_types(requests))
                self._add_proof_source_summary(
                    proof_sources,
                    source,
                    path=rel_path,
                    is_complete=is_complete,
                    stop_reason=_string(completion.get("stop_reason")),
                    coverage=coverage,
                    requests=requests,
                    successful_responses=successful_responses,
                )
            else:
                missing_source_files.append({"path": rel_path})
            if payload.get("would_write_formal_tables") is True:
                would_write_formal_table_files.append({"path": rel_path})
            proof_successful_response_count += successful_responses
            proof_total_requests += len(requests)
            item = {
                "path": rel_path,
                "valid": True,
                "source": payload.get("source"),
                "target_type": payload.get("target_type"),
                "dry_run": dry_run,
                "plan_only": is_plan,
                "is_complete": is_complete,
                "stop_reason": completion.get("stop_reason"),
                "coverage_stats": {key: int(coverage.get(key) or 0) for key in COVERAGE_KEYS},
                "request_count": len(requests),
            }
            file_summaries.append(item)

            if is_plan:
                proof_plan_files.append({"path": rel_path})
            if not requests:
                proof_empty_request_files.append({"path": rel_path})
            if len(requests) and successful_responses != len(requests):
                proof_non_success_response_files.append({"path": rel_path})
            if int(coverage.get("races") or 0) <= 0 or int(coverage.get("horses") or 0) <= 0:
                proof_empty_coverage_files.append({"path": rel_path})
            proof_stop_reason = _string(completion.get("stop_reason"))
            if not is_complete and proof_stop_reason not in {"limit_horses_reached", "limit_races_reached", "limit_tracks_reached"}:
                proof_disallowed_stop_files.append({"path": rel_path, "stop_reason": proof_stop_reason or "missing_completion"})

            if is_plan:
                plan_file_count += 1
                plan_items = self._planned_item_list(payload)
                planned_items.update(plan_items)
                for planned_item in plan_items:
                    planned_item_counts[planned_item] = planned_item_counts.get(planned_item, 0) + 1
                if dry_run is not True:
                    non_dry_run_plan_files.append({"path": rel_path, "dry_run": dry_run})
                if not requests:
                    empty_plan_request_files.append({"path": rel_path})
                if len(requests) and successful_responses != len(requests):
                    non_success_plan_response_files.append({"path": rel_path})
                if not is_complete:
                    incomplete_plan_files.append(
                        {
                            "path": rel_path,
                            "stop_reason": completion.get("stop_reason") or "missing_completion",
                        }
                    )
                if self._is_limited_plan_completion(completion):
                    limited_plan_files.append(
                        {
                            "path": rel_path,
                            "limit_tracks": completion.get("limit_tracks"),
                            "limit_races": completion.get("limit_races"),
                            "limit_horses": completion.get("limit_horses"),
                        }
                    )
                continue

            batch_file_count += 1
            batch_covered_items = self._covered_item_list(payload)
            covered_items.update(batch_covered_items)
            for covered_item in batch_covered_items:
                covered_item_counts[covered_item] = covered_item_counts.get(covered_item, 0) + 1
            total_requests += len(requests)
            for key in COVERAGE_KEYS:
                coverage_totals[key] += int(coverage.get(key) or 0)

            if not requests:
                empty_batch_request_files.append({"path": rel_path})
            if len(requests) and successful_responses != len(requests):
                non_success_batch_response_files.append({"path": rel_path})
            empty_coverage_keys = self._empty_coverage_keys(coverage)
            if empty_coverage_keys:
                empty_batch_coverage_files.append({"path": rel_path, "empty_keys": empty_coverage_keys})
            if dry_run is not True:
                non_dry_run_files.append({"path": rel_path, "dry_run": dry_run})
            if not is_complete:
                incomplete_files.append(
                    {
                        "path": rel_path,
                        "stop_reason": completion.get("stop_reason") or "missing_completion",
                    }
                )
            horse_detail_gap = self._horse_detail_gap(completion)
            if horse_detail_gap:
                incomplete_horse_detail_files.append({"path": rel_path, **horse_detail_gap})

        missing_planned_items = sorted(planned_items - covered_items)
        extra_covered_items = sorted(covered_items - planned_items) if planned_items else []
        duplicate_planned_items = sorted(item for item, count in planned_item_counts.items() if count > 1)
        duplicate_covered_items = sorted(item for item, count in covered_item_counts.items() if count > 1)
        sorted_sources = sorted(sources)
        expected_source_list = sorted(expected_sources or set())
        missing_expected_sources = sorted((expected_sources or set()) - sources)
        expected_request_types = expected_request_types or {}
        missing_proof_request_types = self._missing_proof_request_types(proof_request_types_by_source, expected_request_types)
        has_audited_files = bool(file_summaries)
        proof_ready = (
            has_audited_files
            and not invalid_files
            and not missing_source_files
            and not non_dry_run_files
            and not would_write_formal_table_files
            and not missing_expected_sources
            and not missing_proof_request_types
            and not proof_plan_files
            and not proof_empty_request_files
            and not proof_non_success_response_files
            and not proof_empty_coverage_files
            and not proof_disallowed_stop_files
        )
        commit_candidate_ready = (
            batch_file_count > 0
            and plan_file_count > 0
            and bool(planned_items)
            and len(sources) == 1
            and not missing_source_files
            and not would_write_formal_table_files
            and not incomplete_plan_files
            and not non_dry_run_plan_files
            and not limited_plan_files
            and not empty_plan_request_files
            and not non_success_plan_response_files
            and not empty_batch_request_files
            and not non_success_batch_response_files
            and not empty_batch_coverage_files
            and not incomplete_files
            and not incomplete_horse_detail_files
            and not invalid_files
            and not non_dry_run_files
            and not missing_planned_items
            and not extra_covered_items
            and not duplicate_planned_items
            and not duplicate_covered_items
        )
        summary = {
            "commit_candidate_ready": commit_candidate_ready,
            "file_count": len(files),
            "audited_file_count": len(file_summaries),
            "ignored_artifact_file_count": len(ignored_artifact_files),
            "source_count": len(sources),
            "sources": sorted_sources,
            "expected_sources": expected_source_list,
            "missing_expected_sources": missing_expected_sources,
            "expected_request_types": {source: sorted(types) for source, types in sorted(expected_request_types.items())},
            "proof_sources": self._sorted_proof_sources(proof_sources),
            "proof_request_types_by_source": {source: sorted(types) for source, types in sorted(proof_request_types_by_source.items())},
            "missing_proof_request_types": missing_proof_request_types,
            "plan_file_count": plan_file_count,
            "batch_file_count": batch_file_count,
            "incomplete_file_count": len(incomplete_files),
            "invalid_file_count": len(invalid_files),
            "non_dry_run_file_count": len(non_dry_run_files),
            "proof_ready": proof_ready,
            "proof_file_count": len(files),
            "proof_request_count": proof_total_requests,
            "proof_successful_response_count": proof_successful_response_count,
            "proof_plan_file_count": len(proof_plan_files),
            "proof_empty_request_file_count": len(proof_empty_request_files),
            "proof_non_success_response_file_count": len(proof_non_success_response_files),
            "proof_empty_coverage_file_count": len(proof_empty_coverage_files),
            "proof_disallowed_stop_file_count": len(proof_disallowed_stop_files),
            "incomplete_plan_file_count": len(incomplete_plan_files),
            "non_dry_run_plan_file_count": len(non_dry_run_plan_files),
            "limited_plan_file_count": len(limited_plan_files),
            "empty_plan_request_file_count": len(empty_plan_request_files),
            "non_success_plan_response_file_count": len(non_success_plan_response_files),
            "empty_batch_request_file_count": len(empty_batch_request_files),
            "non_success_batch_response_file_count": len(non_success_batch_response_files),
            "empty_batch_coverage_file_count": len(empty_batch_coverage_files),
            "incomplete_horse_detail_file_count": len(incomplete_horse_detail_files),
            "missing_source_file_count": len(missing_source_files),
            "would_write_formal_table_file_count": len(would_write_formal_table_files),
            "planned_item_count": len(planned_items),
            "covered_planned_item_count": len(planned_items & covered_items),
            "missing_planned_item_count": len(missing_planned_items),
            "extra_covered_item_count": len(extra_covered_items),
            "duplicate_planned_item_count": len(duplicate_planned_items),
            "duplicate_covered_item_count": len(duplicate_covered_items),
            "total_requests": total_requests,
            "coverage_totals": coverage_totals,
            "ignored_artifact_files": ignored_artifact_files,
            "incomplete_files": incomplete_files,
            "invalid_files": invalid_files,
            "non_dry_run_files": non_dry_run_files,
            "proof_plan_files": proof_plan_files,
            "proof_empty_request_files": proof_empty_request_files,
            "proof_non_success_response_files": proof_non_success_response_files,
            "proof_empty_coverage_files": proof_empty_coverage_files,
            "proof_disallowed_stop_files": proof_disallowed_stop_files,
            "incomplete_plan_files": incomplete_plan_files,
            "non_dry_run_plan_files": non_dry_run_plan_files,
            "limited_plan_files": limited_plan_files,
            "empty_plan_request_files": empty_plan_request_files,
            "non_success_plan_response_files": non_success_plan_response_files,
            "empty_batch_request_files": empty_batch_request_files,
            "non_success_batch_response_files": non_success_batch_response_files,
            "empty_batch_coverage_files": empty_batch_coverage_files,
            "incomplete_horse_detail_files": incomplete_horse_detail_files,
            "missing_source_files": missing_source_files,
            "would_write_formal_table_files": would_write_formal_table_files,
            "missing_planned_items": missing_planned_items,
            "extra_covered_items": extra_covered_items,
            "duplicate_planned_items": duplicate_planned_items,
            "duplicate_covered_items": duplicate_covered_items,
            "files": file_summaries,
        }
        summary["blocking_reasons"] = self._blocking_reasons(summary)
        summary["proof_blocking_reasons"] = self._proof_blocking_reasons(summary)
        summary["handoff_decision"] = self._handoff_decision(summary)
        summary["handoff_decision_reasons"] = self._handoff_decision_reasons(summary)
        return summary

    def _handoff_decision(self, summary: dict[str, Any]) -> str:
        if summary["commit_candidate_ready"]:
            return "commit_candidate_ready"
        if summary["proof_ready"]:
            return "proof_only_ready_not_commit_candidate"
        return "incomplete_not_ready"

    def _handoff_decision_reasons(self, summary: dict[str, Any]) -> list[str]:
        decision = summary["handoff_decision"]
        if decision == "commit_candidate_ready":
            return ["commit audit passed"]
        if decision == "proof_only_ready_not_commit_candidate":
            return [
                "proof-only audit passed",
                "commit audit still blocked",
                "complete 60-day crawl and commit gate remain required",
            ]
        return ["proof or commit audit blocked"]

    def _proof_blocking_reasons(self, summary: dict[str, Any]) -> list[str]:
        return [
            *(item["path"] for item in summary["invalid_files"]),
            *(f"missing source {item['path']}" for item in summary["missing_source_files"]),
            *(f"missing expected proof source {source}" for source in summary["missing_expected_sources"]),
            *(f"missing proof request type {item}" for item in summary["missing_proof_request_types"]),
            *(item["path"] for item in summary["non_dry_run_files"]),
            *(f"would write formal tables {item['path']}" for item in summary["would_write_formal_table_files"]),
            *(f"plan-only proof {item['path']}" for item in summary["proof_plan_files"]),
            *(f"empty proof requests {item['path']}" for item in summary["proof_empty_request_files"]),
            *(f"non-success proof response {item['path']}" for item in summary["proof_non_success_response_files"]),
            *(f"empty proof coverage {item['path']}" for item in summary["proof_empty_coverage_files"]),
            *(f"disallowed proof stop {item['path']}" for item in summary["proof_disallowed_stop_files"]),
        ]

    def _expected_sources(self, value: Any) -> set[str] | None:
        if value is None:
            return None
        sources = {item.strip() for item in str(value).split(",") if item.strip()}
        return sources or None

    def _expected_request_types(self, value: Any) -> dict[str, set[str]] | None:
        if value is None:
            return None
        expected: dict[str, set[str]] = {}
        for item in str(value).split(","):
            if not item.strip() or ":" not in item:
                continue
            source, raw_types = item.split(":", 1)
            source = source.strip()
            request_types = {request_type.strip() for request_type in raw_types.split("|") if request_type.strip()}
            if source and request_types:
                expected[source] = request_types
        return expected or None

    def _request_target_types(self, requests: list[Any]) -> set[str]:
        return {
            str(request.get("target_type")).strip()
            for request in requests
            if isinstance(request, dict) and str(request.get("target_type")).strip()
        }

    def _add_proof_source_summary(
        self,
        proof_sources: dict[str, dict[str, Any]],
        source: str,
        *,
        path: str,
        is_complete: bool,
        stop_reason: str,
        coverage: dict[str, Any],
        requests: list[Any],
        successful_responses: int,
    ) -> None:
        summary = proof_sources.setdefault(
            source,
            {
                "file_count": 0,
                "complete_file_count": 0,
                "incomplete_file_count": 0,
                "files": [],
                "request_count": 0,
                "successful_response_count": 0,
                "coverage_totals": {key: 0 for key in COVERAGE_KEYS},
                "request_types": set(),
                "stop_reasons": set(),
            },
        )
        summary["file_count"] += 1
        if is_complete:
            summary["complete_file_count"] += 1
        else:
            summary["incomplete_file_count"] += 1
        if stop_reason:
            summary["stop_reasons"].add(stop_reason)
        summary["files"].append(path)
        summary["request_count"] += len(requests)
        summary["successful_response_count"] += successful_responses
        summary["request_types"].update(self._request_target_types(requests))
        for key in COVERAGE_KEYS:
            summary["coverage_totals"][key] += int(coverage.get(key) or 0)

    def _sorted_proof_sources(self, proof_sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            source: {
                "files": sorted(summary["files"]),
                "file_count": summary["file_count"],
                "complete_file_count": summary["complete_file_count"],
                "incomplete_file_count": summary["incomplete_file_count"],
                "request_count": summary["request_count"],
                "successful_response_count": summary["successful_response_count"],
                "coverage_totals": summary["coverage_totals"],
                "request_types": sorted(summary["request_types"]),
                "stop_reasons": sorted(summary["stop_reasons"]),
            }
            for source, summary in sorted(proof_sources.items())
        }

    def _missing_proof_request_types(self, actual: dict[str, set[str]], expected: dict[str, set[str]]) -> list[str]:
        missing: list[str] = []
        for source, request_types in sorted(expected.items()):
            actual_types = actual.get(source, set())
            for request_type in sorted(request_types - actual_types):
                missing.append(f"{source}:{request_type}")
        return missing

    def _blocking_reasons(self, summary: dict[str, Any]) -> list[str]:
        reasons = [
            *(["missing plan file"] if summary["plan_file_count"] == 0 else []),
            *(["missing batch file"] if summary["batch_file_count"] == 0 else []),
            *(["empty plan items"] if summary["plan_file_count"] > 0 and summary["planned_item_count"] == 0 else []),
            *(f"incomplete plan {item['path']}" for item in summary["incomplete_plan_files"]),
            *(f"non-dry-run plan {item['path']}" for item in summary["non_dry_run_plan_files"]),
            *(f"limited plan {item['path']}" for item in summary["limited_plan_files"]),
            *(f"empty plan requests {item['path']}" for item in summary["empty_plan_request_files"]),
            *(f"non-success plan response {item['path']}" for item in summary["non_success_plan_response_files"]),
            *(f"empty batch requests {item['path']}" for item in summary["empty_batch_request_files"]),
            *(f"non-success batch response {item['path']}" for item in summary["non_success_batch_response_files"]),
            *(f"empty batch coverage {item['path']}" for item in summary["empty_batch_coverage_files"]),
            *(f"missing source {item['path']}" for item in summary["missing_source_files"]),
            *(["mixed sources " + ",".join(summary["sources"])] if summary["source_count"] > 1 else []),
            *(f"would write formal tables {item['path']}" for item in summary["would_write_formal_table_files"]),
            *(item["path"] for item in summary["incomplete_files"]),
            *(f"incomplete horse details {item['path']}" for item in summary["incomplete_horse_detail_files"]),
            *(item["path"] for item in summary["invalid_files"]),
            *(item["path"] for item in summary["non_dry_run_files"]),
            *(f"missing planned {item}" for item in summary["missing_planned_items"] if summary["batch_file_count"] > 0),
            *(f"extra covered {item}" for item in summary["extra_covered_items"]),
            *(f"duplicate planned {item}" for item in summary["duplicate_planned_items"]),
            *(f"duplicate covered {item}" for item in summary["duplicate_covered_items"]),
        ]
        return reasons

    def _successful_response_count(self, requests: list[Any]) -> int:
        successes = 0
        for request in requests:
            if not isinstance(request, dict):
                continue
            try:
                status_code = int(request.get("status_code") or 0)
            except (TypeError, ValueError):
                continue
            if 200 <= status_code < 400:
                successes += 1
        return successes

    def _is_limited_plan_completion(self, completion: dict[str, Any]) -> bool:
        if completion.get("coverage_scope_limited") is True:
            return True
        return any(completion.get(key) is not None for key in ("limit_tracks", "limit_races", "limit_horses"))

    def _horse_detail_gap(self, completion: dict[str, Any]) -> dict[str, Any] | None:
        unique_horses = completion.get("unique_horses_found")
        if unique_horses is None:
            return None
        try:
            unique_count = int(unique_horses)
        except (TypeError, ValueError):
            return None
        if unique_count <= 0:
            return None
        if _string(completion.get("horse_profile_source")) in {"race_detail_rows", "geny_partants_rows"}:
            return None
        fetched_raw = completion.get("horse_profiles_fetched")
        try:
            fetched_count = int(fetched_raw)
        except (TypeError, ValueError):
            fetched_count = 0
        if fetched_count >= unique_count:
            return None
        return {
            "unique_horses_found": unique_count,
            "horse_profiles_fetched": fetched_count,
            "horse_profile_source": _string(completion.get("horse_profile_source")),
        }

    def _empty_coverage_keys(self, coverage: dict[str, Any]) -> list[str]:
        empty_keys: list[str] = []
        for key in COVERAGE_KEYS:
            try:
                value = int(coverage.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value <= 0:
                empty_keys.append(key)
        return empty_keys

    def _planned_items(self, payload: dict[str, Any]) -> set[str]:
        return set(self._planned_item_list(payload))

    def _planned_item_list(self, payload: dict[str, Any]) -> list[str]:
        ordered_items: list[str] = []
        batches = payload.get("batches") if isinstance(payload.get("batches"), list) else []
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            batch_items = self._first_available_item_list(batch, ("race_ids", "partants_urls", "race_urls"))
            ordered_items.extend(batch_items)
        return ordered_items

    def _covered_items(self, payload: dict[str, Any]) -> set[str]:
        return set(self._covered_item_list(payload))

    def _covered_item_list(self, payload: dict[str, Any]) -> list[str]:
        completion = payload.get("completion") if isinstance(payload.get("completion"), dict) else {}
        items = self._first_available_item_list(completion, ("race_ids_selected", "race_ids", "partants_urls", "race_urls"))
        if items:
            return items

        target_id = payload.get("target_id")
        if isinstance(target_id, str) and target_id and ".." not in target_id:
            return [item.strip() for item in target_id.split(",") if item.strip()]

        requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
        request_items = [
            str(request.get("target_id")).strip()
            for request in requests
            if isinstance(request, dict)
            and request.get("target_type") in {"race", "partants", "track_day"}
            and str(request.get("target_id")).strip()
        ]
        return request_items

    def _first_available_items(self, payload: dict[str, Any], keys: tuple[str, ...]) -> set[str]:
        return set(self._first_available_item_list(payload, keys))

    def _first_available_item_list(self, payload: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
        for key in keys:
            values = payload.get(key)
            if isinstance(values, list):
                items = [str(value).strip() for value in values if str(value).strip()]
                if items:
                    return items
            if isinstance(values, str) and values.strip():
                return [item.strip() for item in values.split(",") if item.strip()]
        return []
