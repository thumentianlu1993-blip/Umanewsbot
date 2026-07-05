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
        parser.add_argument("--source", action="append", default=[], help="来源，可重复传入：hkjc、hkjc_overseas、wpstud。")
        parser.add_argument("--region", action="append", default=[], help="预留地区过滤参数；首版输出仍按香港优先、日本最后排序。")
        parser.add_argument("--input-dir", help="本地 fixture 或缓存 HTML 目录；未触网时默认读取内置 fixture。")
        parser.add_argument("--output-dir", help="输出目录；默认 runtime/termbase_seed/<timestamp>/。")
        parser.add_argument("--allow-network", action="store_true", help="允许访问 HKJC 或 WP Stud 网络页面。")
        parser.add_argument("--limit-pages", type=int, help="每个来源最多抓取页面数。")
        parser.add_argument("--limit-horses", type=int, help="HKJC 详情页最多抽取马匹数；用于安全小批抓取。")
        parser.add_argument("--hkjc-letter", action="append", default=[], help="HKJC 本地马匹按首字母拆批抓取，可重复传入 A-Z。")
        parser.add_argument("--hkjc-local-results-start-date", help="HKJC 本地赛果术语抽取开始日期，例如 2024-01-01。")
        parser.add_argument("--hkjc-local-results-end-date", help="HKJC 本地赛果术语抽取结束日期；不传则使用今天。")
        parser.add_argument("--hkjc-local-results-skip-races", type=int, default=0, help="HKJC 本地赛果术语抽取跳过前 N 场，用于分批续跑。")
        parser.add_argument("--hkjc-overseas-start-date", help="HKJC overseas 术语抽取开始日期，例如 2024-01-01。")
        parser.add_argument("--hkjc-overseas-end-date", help="HKJC overseas 术语抽取结束日期；不传则使用今天。")
        parser.add_argument("--hkjc-skip-horse-details", action="store_true", help="抓取 HKJC 时跳过本地马匹详情页；适合只补本地赛果术语的批次。")
        parser.add_argument("--limit-meetings", type=int, help="HKJC overseas 自动发现时最多处理 meeting 数。")
        parser.add_argument("--limit-races", type=int, help="HKJC overseas 自动发现时最多处理 race card 数；默认 3。")
        parser.add_argument(
            "--hkjc-overseas-race",
            action="append",
            default=[],
            help="精确指定 HKJC overseas Race Card，可重复传入：RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>。",
        )
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
            limit_horses=options["limit_horses"],
            hkjc_local_results_start_date=options["hkjc_local_results_start_date"] or "",
            hkjc_local_results_end_date=options["hkjc_local_results_end_date"] or "",
            hkjc_local_results_skip_races=options["hkjc_local_results_skip_races"] or 0,
            hkjc_overseas_start_date=options["hkjc_overseas_start_date"] or "",
            hkjc_overseas_end_date=options["hkjc_overseas_end_date"] or "",
            hkjc_skip_horse_details=options["hkjc_skip_horse_details"],
            hkjc_letters=tuple(letter.strip().upper() for letter in options["hkjc_letter"] if letter and letter.strip()),
            limit_meetings=options["limit_meetings"],
            limit_races=options["limit_races"],
            hkjc_overseas_races=tuple(options["hkjc_overseas_race"]),
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
