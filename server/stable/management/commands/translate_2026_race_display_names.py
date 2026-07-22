"""2026 赛历赛事中文展示名补齐：默认 dry-run，显式 --commit 才写入。

用法：
  # 只读 dry-run，输出审核 artifact（dry-run.json + review.csv）
  python manage.py translate_2026_race_display_names --output-dir outputs/translate-2026-<ts>

  # 用户审核定稿后，从定稿 CSV 构建 manifest（SHA-256 锁定）
  python manage.py translate_2026_race_display_names --build-manifest \
    --reviewed-csv outputs/translate-2026-<ts>/reviewed.csv \
    --output-dir outputs/translate-2026-<ts>

  # 受控写入（需要 manifest artifact + 备份身份 + 授权信息）
  python manage.py translate_2026_race_display_names --commit \
    --artifact outputs/translate-2026-<ts>/manifest.json \
    --artifact-sha256 <manifest.json 文件 SHA-256> \
    --backup-sha256 <64 hex> --backup-size-bytes <bytes> \
    --authorization-ref <ref> --authorization-time <iso>

  # 写后校验
  python manage.py translate_2026_race_display_names --verify --artifact ... --artifact-sha256 ...
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services import race_display_name_translation_2026 as translation


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = (
        "Fill Chinese display names for published 2026 race events "
        "(dry-run by default; --commit writes only from a reviewed manifest)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default="")
        parser.add_argument("--build-manifest", action="store_true")
        parser.add_argument("--reviewed-csv", default="")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--verify", action="store_true")
        parser.add_argument("--artifact", default="")
        parser.add_argument("--artifact-sha256", default="")
        parser.add_argument("--backup-sha256", default="")
        parser.add_argument("--backup-size-bytes", type=int, default=0)
        parser.add_argument("--authorization-ref", default="")
        parser.add_argument("--authorization-time", default="")

    def _default_output_dir(self) -> Path:
        stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
        return Path(f"outputs/race-display-name-translation-2026/{stamp}")

    def _load_artifact(self, options) -> dict:
        if not options["artifact"] or not options["artifact_sha256"]:
            raise CommandError("--artifact and --artifact-sha256 are required")
        artifact_path = Path(options["artifact"]).resolve()
        actual = _sha256_file(artifact_path)
        if actual != options["artifact_sha256"]:
            raise CommandError(
                f"artifact sha mismatch: {actual} != {options['artifact_sha256']}"
            )
        try:
            manifest = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"invalid artifact: {exc}") from exc
        if manifest.get("schemaVersion") != translation.MANIFEST_SCHEMA:
            raise CommandError("unsupported artifact schema")
        content = {
            key: manifest.get(key) for key in ("actions", "veto")
        }
        expected = manifest.get("contentSha256")
        digest = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if expected != digest:
            raise CommandError("artifact content identity mismatch")
        return manifest

    def handle(self, *args, **options):
        if options["commit"] and options["verify"]:
            raise CommandError("--commit and --verify are mutually exclusive")
        if options["build_manifest"] and (options["commit"] or options["verify"]):
            raise CommandError(
                "--build-manifest cannot be combined with --commit/--verify"
            )
        if options["commit"]:
            manifest = self._load_artifact(options)
            if (
                not options["authorization_ref"]
                or not options["authorization_time"]
                or len(options["backup_sha256"]) != 64
                or options["backup_size_bytes"] <= 0
            ):
                raise CommandError(
                    "commit requires authorization and validated backup identity"
                )
            result = translation.execute_commit(
                manifest,
                audit_context={
                    "artifactSha256": options["artifact_sha256"],
                    "backupSha256": options["backup_sha256"],
                    "backupSizeBytes": options["backup_size_bytes"],
                    "operator": "mentianlu_via_codex",
                    "authorizationRef": options["authorization_ref"],
                    "authorizationTime": options["authorization_time"],
                },
            )
            self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return
        if options["verify"]:
            manifest = self._load_artifact(options)
            outcome = translation.verify_applied(manifest)
            self.stdout.write(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
            return
        if options["build_manifest"]:
            if not options["reviewed_csv"]:
                raise CommandError("--build-manifest requires --reviewed-csv")
            reviewed_path = Path(options["reviewed_csv"])
            try:
                # utf-8-sig：兼容 Excel 定稿 CSV 的 UTF-8 BOM（否则首列名带 ﻿）
                with reviewed_path.open(encoding="utf-8-sig", newline="") as handle:
                    rows = list(csv.DictReader(handle))
            except OSError as exc:
                raise CommandError(f"cannot read reviewed csv: {exc}") from exc
            manifest = translation.build_manifest(rows)
            output_dir = Path(options["output_dir"]) if options["output_dir"] else self._default_output_dir()
            output_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = output_dir / "manifest.json"
            artifact_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            summary = {
                "artifact": str(artifact_path),
                "artifactSha256": _sha256_file(artifact_path),
                "counts": manifest["counts"],
            }
            self.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return

        report = translation.build_dry_run()
        output_dir = Path(options["output_dir"]) if options["output_dir"] else self._default_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / "dry-run.json"
        artifact_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        review_csv_path = output_dir / "review.csv"
        with review_csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(translation.REVIEW_CSV_HEADER)
            for row in report["candidates"]:
                writer.writerow(
                    [
                        "candidates",
                        row["id"],
                        row["region"],
                        row["originalName"],
                        row["before"],
                        row["level"],
                        row["matchedOn"],
                        row["suggestedName"],
                        "",
                        "",
                    ]
                )
            for row in report["manual"]:
                writer.writerow(
                    [
                        "manual",
                        row["id"],
                        row["region"],
                        row["originalName"],
                        row["before"],
                        row.get("level", ""),
                        row.get("matchedOn", ""),
                        "",
                        row["reason"],
                        "",
                    ]
                )
        summary = {
            "artifact": str(artifact_path),
            "artifactSha256": _sha256_file(artifact_path),
            "reviewCsv": str(review_csv_path),
            "counts": report["counts"],
        }
        self.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True))
