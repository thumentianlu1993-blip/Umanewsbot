#!/usr/bin/env python3
"""历史缺口详情候选绑定器：把地区详情候选绑定到生产 target 身份。

输入各地区工具产出的候选 JSONL（按 target_id 或 year/slug 标识）与绑定表
（target_id → {target_sha256, inventory_artifact_sha256}，由生产侧在 apply 前生成），
输出 `import_historical_race_event_candidates` 契约的最终 JSONL：
target_id / target_sha256 / inventory_artifact_sha256 / source_name / source_url / modules。

纪律：缺绑定、SHA 非法、模块 items 为空均 fail closed；runners/results 缺 is_complete
标记时补齐为 true 并要求 items 非空；不重排、不修改任何条目字段。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _require_sha256(value: object, *, label: str, line_number: int) -> str:
    text = str(value or "")
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"第 {line_number} 行 {label} 非法")
    return text


def _complete_module(module: object, *, label: str, line_number: int) -> dict:
    if not isinstance(module, dict):
        raise ValueError(f"第 {line_number} 行模块 {label} 必须是对象")
    items = module.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"第 {line_number} 行模块 {label} 的 items 为空")
    if module.get("is_complete") is False:
        raise ValueError(f"第 {line_number} 行模块 {label} 显式标记 is_complete=false，拒绝翻转")
    completed = dict(module)
    completed["is_complete"] = True
    return completed


def bind_candidate_rows(
    candidates_path: Path,
    binding: dict[str, dict],
    *,
    slug_map: dict[str, int] | None = None,
) -> list[dict]:
    """返回绑定后的最终导入行（不落盘；落盘由调用方/CLI 负责）。"""
    rows_out = []
    seen_targets: set[int] = set()
    with Path(candidates_path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            target_id = record.get("target_id")
            if target_id is None:
                year = record.get("year")
                slug = record.get("slug")
                key = f"{year}/{slug}"
                if slug_map is None or key not in slug_map:
                    raise ValueError(f"第 {line_number} 行缺 target_id 且 {key} 无映射")
                target_id = slug_map[key]
            target_id = int(target_id)
            if target_id in seen_targets:
                raise ValueError(f"第 {line_number} 行 target_id={target_id} 重复候选，拒绝")
            seen_targets.add(target_id)
            bound = binding.get(str(target_id))
            if not bound:
                raise ValueError(f"第 {line_number} 行 target_id={target_id} 缺少绑定")
            source_name = str(record.get("source_name") or "").strip()
            source_url = str(record.get("source_url") or "").strip()
            if not source_name or not source_url:
                raise ValueError(f"第 {line_number} 行缺 source_name/source_url")
            modules = record.get("modules") or {}
            normalized_modules = {}
            for label in ("runners", "results"):
                if label in modules:
                    normalized_modules[label] = _complete_module(
                        modules[label], label=label, line_number=line_number
                    )
            if "results" not in normalized_modules:
                raise ValueError(f"第 {line_number} 行缺 results 模块")
            rows_out.append(
                {
                    "target_id": int(target_id),
                    "target_sha256": _require_sha256(
                        bound.get("target_sha256"), label="target_sha256", line_number=line_number
                    ),
                    "inventory_artifact_sha256": _require_sha256(
                        bound.get("inventory_artifact_sha256"),
                        label="inventory_artifact_sha256",
                        line_number=line_number,
                    ),
                    "source_name": str(record.get("source_name") or ""),
                    "source_url": str(record.get("source_url") or ""),
                    "modules": normalized_modules,
                }
            )
    if not rows_out:
        raise ValueError("没有可绑定的候选行")
    return rows_out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--binding-json", required=True)
    parser.add_argument("--slug-map-json", default="", help="可选：'year/slug' → target_id 映射")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    binding = json.loads(Path(args.binding_json).read_text(encoding="utf-8"))
    slug_map = (
        json.loads(Path(args.slug_map_json).read_text(encoding="utf-8"))
        if args.slug_map_json
        else None
    )
    rows = bind_candidate_rows(Path(args.candidates), binding, slug_map=slug_map)
    output = Path(args.output)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"bound={len(rows)} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
