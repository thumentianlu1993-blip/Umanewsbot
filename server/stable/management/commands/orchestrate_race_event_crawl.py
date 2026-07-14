from __future__ import annotations

import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.models import TaskExecutionLog, TaskStatus
from stable.services import race_event_crawl_orchestration as orchestration


class Command(BaseCommand):
    help = "编排 RaceEvent 赛事详情批次抓取、覆盖审计、dry-run 和 apply-check。"

    def add_arguments(self, parser):
        parser.add_argument("--plan", help="编排 plan JSON 路径。")
        parser.add_argument("--stage", required=True, choices=["plan", "prepare", "audit", "dry-run", "apply-check", "resume"])
        parser.add_argument("--run-dir", help="运行目录；默认使用 plan.output_dir 或 runtime/race_event_crawl_runs/<run_id>。")
        parser.add_argument("--state", help="resume 时读取的 state.json。")
        parser.add_argument("--candidate-jsonl", help="候选 JSONL；audit/dry-run/apply-check 阶段使用。")
        parser.add_argument("--series-mapping", help="series mapping JSON；audit 阶段使用。")
        parser.add_argument("--coverage-audit", help="coverage audit JSON；apply-check 阶段使用。")
        parser.add_argument("--dry-run-artifact", help="dry-run 证据文件；apply-check 阶段使用。")
        parser.add_argument("--confirmations", help="人工确认 JSON 文件。")
        parser.add_argument("--production-evidence", help="生产健康、锁和备份证据 JSON 文件。")
        parser.add_argument("--apply-scope", help="apply 范围 JSON 文件。")

    def handle(self, *args, **options):
        stage = options["stage"]
        try:
            if stage == "resume":
                return self._handle_resume(options)
            if not options.get("plan"):
                raise CommandError("需要 --plan 或可恢复 state 才能执行该阶段")
            plan_path = Path(options["plan"])
            if stage == "plan":
                return self._handle_plan(plan_path, options)
            if stage == "prepare":
                return self._handle_prepare(plan_path, options)
            if stage == "audit":
                return self._handle_audit(plan_path, options)
            if stage == "dry-run":
                return self._handle_dry_run(plan_path, options)
            if stage == "apply-check":
                return self._handle_apply_check(plan_path, options)
        except (
            orchestration.PlanValidationError,
            orchestration.AdapterDependencyError,
            orchestration.AdapterExecutionError,
            orchestration.AdapterOutputError,
        ) as exc:
            raise CommandError(str(exc)) from exc

    def _handle_plan(self, plan_path: Path, options):
        state = orchestration.create_run(plan_path, options.get("run_dir"))
        state.completed_stages.append("plan")
        state.stage = "plan"
        state.write()
        self.stdout.write(
            self.style.SUCCESS(
                f"plan 通过：run_dir={state.run_dir} "
                f"expected_targets={state.artifacts.get('expected_target_count')} "
                f"review={state.artifacts.get('expected_targets_review')}"
            )
        )

    def _handle_prepare(self, plan_path: Path, options):
        plan = orchestration.load_plan(plan_path)
        orchestration.validate_plan(plan)
        orchestration.validate_prepare_authorization(plan)
        state = orchestration.create_run(plan_path, options.get("run_dir"))
        results = self._prepare_with_historical_log(plan, state, resume=False)
        self.stdout.write(
            self.style.SUCCESS(
                f"prepare 完成：adapters={len(results)} run_dir={state.run_dir} "
                f"candidates={state.artifacts.get('combined_candidates')}"
            )
        )

    def _handle_audit(self, plan_path: Path, options):
        for name in ["series_mapping"]:
            if not options.get(name):
                raise CommandError(f"audit 阶段需要 --{name.replace('_', '-')}")
        run_dir = options.get("run_dir") or self._run_dir_from_plan(plan_path)
        state = orchestration.create_run(plan_path, run_dir)
        candidate_jsonl = self._candidate_jsonl(options, state)
        state.artifacts["audit_inputs"] = {
            "candidate_jsonl": candidate_jsonl,
            "series_mapping": str(options["series_mapping"]),
        }
        state.write()
        try:
            result = orchestration.audit_coverage(
                plan_path=plan_path,
                candidate_jsonl=candidate_jsonl,
                series_mapping_path=options["series_mapping"],
                run_dir=run_dir,
            )
        except Exception as exc:
            state.stage = "audit_failed"
            state.errors.append({"stage": "audit", "error": str(exc)})
            state.write()
            raise
        if "audit" not in state.completed_stages:
            state.completed_stages.append("audit")
        state.stage = "audit"
        state.artifacts["coverage_audit"] = str(Path(run_dir) / "coverage_audit.json")
        state.write()
        self.stdout.write(json.dumps(result, ensure_ascii=False))

    def _handle_dry_run(self, plan_path: Path, options):
        run_dir = options.get("run_dir") or self._run_dir_from_plan(plan_path)
        state = orchestration.create_run(plan_path, run_dir)
        inputs = {"candidate_jsonl": self._candidate_jsonl(options, state)}
        state.artifacts["dry_run_inputs"] = inputs
        state.write()
        result = self._execute_dry_run(state, inputs)
        self.stdout.write(json.dumps(result, ensure_ascii=False))

    def _handle_apply_check(self, plan_path: Path, options):
        for name in ["coverage_audit", "confirmations", "production_evidence", "apply_scope"]:
            if not options.get(name):
                raise CommandError(f"apply-check 阶段需要 --{name.replace('_', '-')}")
        run_dir = options.get("run_dir") or self._run_dir_from_plan(plan_path)
        state = orchestration.create_run(plan_path, run_dir)
        inputs = {
            "coverage_audit": str(options["coverage_audit"]),
            "dry_run_artifact": str(options.get("dry_run_artifact") or ""),
            "confirmations": str(options["confirmations"]),
            "production_evidence": str(options["production_evidence"]),
            "apply_scope": str(options["apply_scope"]),
            "candidate_jsonl": str(options.get("candidate_jsonl") or ""),
        }
        state.artifacts["apply_check_inputs"] = inputs
        state.write()
        result = self._execute_apply_check(state, inputs)
        self.stdout.write(json.dumps(result, ensure_ascii=False))

    def _execute_dry_run(self, state, inputs):
        try:
            result = orchestration.run_detail_dry_run(
                candidate_jsonl=inputs["candidate_jsonl"],
                run_dir=state.run_dir,
            )
        except Exception as exc:
            state.stage = "dry-run_failed"
            state.errors.append(
                {"stage": "dry-run", "error": str(exc), "recorded_at": timezone.now().isoformat()}
            )
            state.write()
            raise
        if "dry-run" not in state.completed_stages:
            state.completed_stages.append("dry-run")
        state.stage = "dry-run"
        state.artifacts["dry_run"] = result["path"]
        state.write()
        return result

    def _execute_apply_check(self, state, inputs):
        try:
            coverage = self._read_json(inputs["coverage_audit"])
            confirmations = self._read_json(inputs["confirmations"]).get("confirmations", [])
            evidence = self._read_json(inputs["production_evidence"])
            scope = self._read_json(inputs["apply_scope"])
            result = orchestration.evaluate_apply_check(
                run_dir=state.run_dir,
                coverage_audit=coverage,
                dry_run_artifact=inputs.get("dry_run_artifact"),
                confirmations=confirmations,
                production_evidence=evidence,
                apply_scope=scope,
                candidate_jsonl=inputs.get("candidate_jsonl"),
            )
        except Exception as exc:
            state.stage = "apply-check_failed"
            state.errors.append(
                {"stage": "apply-check", "error": str(exc), "recorded_at": timezone.now().isoformat()}
            )
            state.write()
            raise
        if "apply-check" not in state.completed_stages:
            state.completed_stages.append("apply-check")
        state.stage = "apply-check"
        state.artifacts["apply_check"] = str(Path(state.run_dir) / "apply_check.json")
        state.write()
        return result

    def _handle_resume(self, options):
        if not options.get("state"):
            raise CommandError("resume 阶段需要 --state")
        state = orchestration.RunState.read(options["state"])
        plan_path = Path(str(state.artifacts.get("plan") or ""))
        if not plan_path.exists():
            raise CommandError("state 缺少可恢复的 plan artifact")
        plan = orchestration.load_plan(plan_path)
        orchestration.validate_plan(plan)
        orchestration.validate_prepare_authorization(plan)
        original_stage = state.stage
        resume_entry = {
            "started_at": timezone.now().isoformat(),
            "from_stage": original_stage,
            "status": "started",
        }
        state.resume_history.append(resume_entry)
        state.write()
        try:
            results = self._prepare_with_historical_log(plan, state, resume=True)
            resume_audit = original_stage in {
                "audit",
                "audit_failed",
                "dry-run",
                "dry-run_failed",
                "apply-check",
                "apply-check_failed",
            }
            if resume_audit and state.artifacts.get("audit_inputs"):
                audit_inputs = state.artifacts["audit_inputs"]
                orchestration.audit_coverage(
                    plan_path=plan_path,
                    candidate_jsonl=audit_inputs["candidate_jsonl"],
                    series_mapping_path=audit_inputs["series_mapping"],
                    run_dir=state.run_dir,
                )
                if "audit" not in state.completed_stages:
                    state.completed_stages.append("audit")
                state.stage = "audit"
                state.artifacts["coverage_audit"] = str(Path(state.run_dir) / "coverage_audit.json")
            if original_stage in {"dry-run", "dry-run_failed", "apply-check", "apply-check_failed"}:
                dry_run_inputs = state.artifacts.get("dry_run_inputs")
                if not isinstance(dry_run_inputs, dict) or not dry_run_inputs.get("candidate_jsonl"):
                    raise CommandError("state 缺少可恢复的 dry-run 输入")
                self._execute_dry_run(state, dry_run_inputs)
            if original_stage in {"apply-check", "apply-check_failed"}:
                apply_check_inputs = state.artifacts.get("apply_check_inputs")
                if not isinstance(apply_check_inputs, dict):
                    raise CommandError("state 缺少可恢复的 apply-check 输入")
                apply_check_inputs = dict(apply_check_inputs)
                apply_check_inputs["coverage_audit"] = str(Path(state.run_dir) / "coverage_audit.json")
                apply_check_inputs["dry_run_artifact"] = str(Path(state.run_dir) / "dry_run.json")
                self._execute_apply_check(state, apply_check_inputs)
        except Exception as exc:
            resume_entry["status"] = "failed"
            resume_entry["error"] = str(exc)
            resume_entry["finished_at"] = timezone.now().isoformat()
            state.write()
            raise
        resume_entry["status"] = "succeeded"
        resume_entry["to_stage"] = state.stage
        resume_entry["finished_at"] = timezone.now().isoformat()
        state.write()
        self.stdout.write(
            json.dumps(
                {
                    "run_id": state.run_id,
                    "stage": state.stage,
                    "completed_stages": state.completed_stages,
                    "adapters": len(results),
                },
                ensure_ascii=False,
            )
        )

    def _prepare_with_historical_log(self, plan, state, *, resume: bool):
        if not plan.get("historical_inventory_sha256"):
            return orchestration.prepare_adapters(plan, state, resume=resume)
        if str(getattr(settings, "POSTGRES_APPLICATION_NAME", "")).startswith(
            "umanews-historical-runner:"
        ):
            return orchestration.prepare_adapters(plan, state, resume=resume)

        task_name = "historical_race_network_resume" if resume else "historical_race_network_prepare"
        payload = {
            "run_id": str(state.run_id),
            "inventory_sha256": str(plan["historical_inventory_sha256"]),
            "target_count": int(state.artifacts.get("expected_target_count") or 0),
            "regions": sorted(
                {
                    str(region.get("region") or "")
                    for region in plan.get("regions", [])
                    if str(region.get("region") or "")
                }
            ),
            "resume": resume,
            "from_stage": str(state.stage or ""),
        }
        log = TaskExecutionLog.objects.create(
            task_name=task_name,
            status=TaskStatus.STARTED,
            payload=payload,
            detail="历史赛事网络运行已开始。",
            started_at=timezone.now(),
        )
        try:
            results = orchestration.prepare_adapters(plan, state, resume=resume)
        except Exception as exc:
            log.status = TaskStatus.FAILED
            log.detail = self._safe_network_error(exc)
            log.finished_at = timezone.now()
            log.save(update_fields=["status", "detail", "finished_at", "updated_at"])
            raise
        log.status = TaskStatus.SUCCESS
        log.payload = {**payload, "adapter_count": len(results)}
        log.detail = "历史赛事网络运行完成。"
        log.finished_at = timezone.now()
        log.save(update_fields=["status", "payload", "detail", "finished_at", "updated_at"])
        return results

    @staticmethod
    def _safe_network_error(error: Exception) -> str:
        detail = str(error).replace("\x00", " ")
        detail = re.sub(
            r"(?i)\b(api[_-]?key|token|secret|password)\s*[=:]\s*\S+",
            r"\1=[redacted]",
            detail,
        )
        lowered = detail.casefold()
        document_offsets = [
            offset
            for marker in ("<html", "<!doctype html", "%pdf")
            if (offset := lowered.find(marker)) >= 0
        ]
        if document_offsets:
            detail = detail[: min(document_offsets)].rstrip() + " [upstream document omitted]"
        return " ".join(detail.split())[:2000]

    def _run_dir_from_plan(self, plan_path: Path) -> str:
        plan = orchestration.load_plan(plan_path)
        return str(plan.get("output_dir") or Path("runtime") / "race_event_crawl_runs" / str(plan.get("run_id") or "manual"))

    def _candidate_jsonl(self, options, state) -> str:
        candidate = str(options.get("candidate_jsonl") or state.artifacts.get("combined_candidates") or "").strip()
        if not candidate:
            raise CommandError("当前 run 没有可用候选；请先执行 prepare 或显式传入 --candidate-jsonl")
        return candidate

    def _read_json(self, path: str):
        with Path(path).open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
