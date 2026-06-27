from __future__ import annotations

import shlex
from pathlib import PurePosixPath
from typing import Any


class GlobalRacingPlanError(ValueError):
    pass


SOURCE_BATCH_CONFIG = {
    "hkjc": {
        "management_command": "import_hkjc_external_data",
        "target_key": "race_ids",
        "target_flag": "--race-ids",
        "extra_args": [],
        "output_prefix": "hkjc",
    },
    "sporting_life": {
        "management_command": "import_uk_external_data",
        "target_key": "race_urls",
        "target_flag": "--race-urls",
        "extra_args": [],
        "output_prefix": "uk",
    },
    "geny_france": {
        "management_command": "import_france_external_data",
        "target_key": "partants_urls",
        "target_flag": "--partants-urls",
        "extra_args": ["--source", "geny"],
        "output_prefix": "france-geny",
    },
    "horse_racing_nation": {
        "management_command": "import_us_external_data",
        "target_key": "race_ids",
        "target_flag": "--race-ids",
        "extra_args": [],
        "output_prefix": "us-hrn",
    },
}


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def build_plan_batch_command(
    plan: dict[str, Any],
    *,
    batch_number: int,
    limit_horses: int | None = None,
    commit: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    if plan.get("plan_only") is not True:
        raise GlobalRacingPlanError("plan payload must be plan_only=true")
    if batch_number <= 0:
        raise GlobalRacingPlanError("batch number must be positive")

    source = _string(plan.get("source"))
    config = SOURCE_BATCH_CONFIG.get(source)
    if not config:
        raise GlobalRacingPlanError(f"unsupported global racing source: {source or 'missing'}")

    batch = _select_batch(plan, batch_number=batch_number)
    target_key = config["target_key"]
    targets = [_string(item) for item in batch.get(target_key, []) if _string(item)]
    if not targets:
        raise GlobalRacingPlanError(f"batch {batch_number} has no {target_key} target list")

    management_command = config["management_command"]
    args = [management_command, *config["extra_args"], config["target_flag"], ",".join(targets), "--allow-network"]
    if limit_horses is not None:
        if limit_horses <= 0:
            raise GlobalRacingPlanError("limit_horses must be positive")
        args.extend(["--limit-horses", str(limit_horses)])
    if commit:
        args.append("--commit")

    suggested_output_file = _suggested_output_file(config["output_prefix"], batch_number=batch_number, commit=commit)
    command_line = shlex.join(["python", "server/manage.py", *args])
    rendered = {
        "artifact_type": "global_racing_batch_command",
        "source": source,
        "management_command": management_command,
        "batch_number": batch_number,
        "target_key": target_key,
        "targets": targets,
        "target_count": len(targets),
        "dry_run": not commit,
        "suggested_output_file": suggested_output_file,
        "args": args,
        "command_line": command_line,
    }
    output_path = _suggested_output_path(output_dir, suggested_output_file=suggested_output_file)
    if output_path:
        rendered["suggested_output_path"] = output_path
        rendered["tee_command_line"] = f"{command_line} | tee {shlex.quote(output_path)}"
    return rendered


def build_plan_batch_commands(
    plan: dict[str, Any],
    *,
    limit_horses: int | None = None,
    commit: bool = False,
    output_dir: str | None = None,
) -> list[dict[str, Any]]:
    batch_numbers = _batch_numbers(plan)
    return [
        build_plan_batch_command(
            plan,
            batch_number=batch_number,
            limit_horses=limit_horses,
            commit=commit,
            output_dir=output_dir,
        )
        for batch_number in batch_numbers
    ]


def _batch_numbers(plan: dict[str, Any]) -> list[int]:
    if plan.get("plan_only") is not True:
        raise GlobalRacingPlanError("plan payload must be plan_only=true")
    batches = plan.get("batches")
    if not isinstance(batches, list) or not batches:
        raise GlobalRacingPlanError("plan payload must contain a non-empty batches list")
    batch_numbers: list[int] = []
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        current = batch.get("batch_index", batch.get("batch_no"))
        try:
            batch_numbers.append(int(current))
        except (TypeError, ValueError):
            continue
    if not batch_numbers:
        raise GlobalRacingPlanError("plan payload does not contain numbered batches")
    return batch_numbers


def _suggested_output_file(output_prefix: str, *, batch_number: int, commit: bool) -> str:
    mode = "commit" if commit else "dryrun"
    return f"{output_prefix}-batch-{batch_number:03d}-{mode}.json"


def _suggested_output_path(output_dir: str | None, *, suggested_output_file: str) -> str:
    normalized_dir = _string(output_dir).rstrip("/")
    if not normalized_dir:
        return ""
    return str(PurePosixPath(normalized_dir) / suggested_output_file)


def _select_batch(plan: dict[str, Any], *, batch_number: int) -> dict[str, Any]:
    batches = plan.get("batches")
    if not isinstance(batches, list):
        raise GlobalRacingPlanError("plan payload must contain a batches list")
    for batch in batches:
        if not isinstance(batch, dict):
            continue
        current = batch.get("batch_index", batch.get("batch_no"))
        try:
            current_number = int(current)
        except (TypeError, ValueError):
            continue
        if current_number == batch_number:
            return batch
    raise GlobalRacingPlanError(f"batch {batch_number} was not found in plan")
