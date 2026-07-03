from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from stable.services.term_admin import preview_term_import
from stable.services.termbase_seed import (
    DeferredSourceError,
    SeedFetchOptions,
    TermbaseSeedError,
    build_seed_result,
    collect_seed_records,
    default_output_dir,
    write_seed_files,
)


class Command(BaseCommand):
    help = "从 HKJC 与 WP Stud 准备人工审核用中文术语种子 CSV，不写正式术语库。"

    def add_arguments(self, parser):
        parser.add_argument("--source", action="append", default=[], help="来源，可重复传入：hkjc、wpstud。")
        parser.add_argument("--region", action="append", default=[], help="预留地区过滤参数；首版输出仍按香港优先、日本最后排序。")
        parser.add_argument("--input-dir", help="本地 fixture 或缓存 HTML 目录；未触网时默认读取内置 fixture。")
        parser.add_argument("--output-dir", help="输出目录；默认 runtime/termbase_seed/<timestamp>/。")
        parser.add_argument("--allow-network", action="store_true", help="允许访问 HKJC 或 WP Stud 网络页面。")
        parser.add_argument("--limit-pages", type=int, help="每个来源最多抓取页面数。")
        parser.add_argument("--max-requests", type=int, default=20, help="本次触网最大请求数。")
        parser.add_argument("--request-interval-seconds", type=float, default=3, help="触网请求间隔秒数。")
        parser.add_argument("--timeout-seconds", type=float, default=15, help="单次请求超时秒数。")

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"]).expanduser() if options["output_dir"] else default_output_dir()
        input_dir = Path(options["input_dir"]).expanduser() if options["input_dir"] else None
        fetch_options = SeedFetchOptions(
            allow_network=options["allow_network"],
            max_requests=options["max_requests"],
            request_interval_seconds=options["request_interval_seconds"],
            timeout_seconds=options["timeout_seconds"],
            limit_pages=options["limit_pages"],
        )
        try:
            records, requests_info, failures = collect_seed_records(
                sources=options["source"],
                input_dir=input_dir,
                options=fetch_options,
            )
        except DeferredSourceError as exc:
            raise CommandError(str(exc)) from exc
        except TermbaseSeedError as exc:
            raise CommandError(str(exc)) from exc

        result = build_seed_result(records, requests_info=requests_info, failures=failures)
        paths = write_seed_files(result, output_dir)

        dry_run_error_count = None
        dry_run_warning = ""
        try:
            preview = preview_term_import(
                csv_text=Path(paths["candidates_path"]).read_text(encoding="utf-8-sig"),
                import_mode="upsert",
            )
            dry_run_error_count = preview["summary"]["error_count"]
        except DatabaseError as exc:
            dry_run_warning = f"术语导入预检需要已迁移数据库，本次仅生成种子文件：{exc}"
        summary = {
            **result.summary,
            **paths,
            "dry_run_error_count": dry_run_error_count,
            "dry_run_warning": dry_run_warning,
            "message": "已生成术语种子文件；请人工审核后再通过 import_terms --dry-run 和正式导入流程处理。",
        }
        Path(paths["summary_path"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
