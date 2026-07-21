"""赛事展示名与 race 术语的去让赛清理：默认 dry-run，显式 --commit 才写入。

用法：
  # 只读 dry-run，输出审核 artifact
  python manage.py clean_race_name_handicap_markers --output-dir outputs/handicap-cleanup-<ts>

  # 受控写入（需要 dry-run artifact + 备份身份 + 授权信息）
  python manage.py clean_race_name_handicap_markers --commit \
    --artifact outputs/handicap-cleanup-<ts>/dry-run.json \
    --artifact-sha256 <dry-run.json 文件 SHA-256> \
    --backup-sha256 <64 hex> --backup-size-bytes <bytes> \
    --authorization-ref <ref> --authorization-time <iso>

  # 写后校验
  python manage.py clean_race_name_handicap_markers --verify --artifact ... --artifact-sha256 ...
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services import race_name_handicap_cleanup as cleanup


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = "Remove handicap markers from race display names and race terms (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", default="")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--verify", action="store_true")
        parser.add_argument("--artifact", default="")
        parser.add_argument("--artifact-sha256", default="")
        parser.add_argument("--backup-sha256", default="")
        parser.add_argument("--backup-size-bytes", type=int, default=0)
        parser.add_argument("--authorization-ref", default="")
        parser.add_argument("--authorization-time", default="")

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
            report = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"invalid artifact: {exc}") from exc
        if report.get("schemaVersion") != "race-name-handicap-cleanup-dry-run.v2":
            raise CommandError("unsupported artifact schema")
        content = {
            key: report.get(key)
            for key in ("actions", "review", "kept", "locked")
        }
        expected = report.get("contentSha256")
        digest = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if expected != digest:
            raise CommandError("artifact content identity mismatch")
        return report

    def handle(self, *args, **options):
        if options["commit"] and options["verify"]:
            raise CommandError("--commit and --verify are mutually exclusive")
        if options["commit"]:
            report = self._load_artifact(options)
            if (
                not options["authorization_ref"]
                or not options["authorization_time"]
                or len(options["backup_sha256"]) != 64
                or options["backup_size_bytes"] <= 0
            ):
                raise CommandError(
                    "commit requires authorization and validated backup identity"
                )
            result = cleanup.execute_commit(
                report,
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
            report = self._load_artifact(options)
            outcome = cleanup.verify_applied(report)
            self.stdout.write(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
            return

        report = cleanup.build_dry_run()
        stamp = options["output_dir"] or (
            f"outputs/race-name-handicap-cleanup/"
            f"{timezone.now().strftime('%Y%m%dT%H%M%SZ')}"
        )
        output_dir = Path(stamp)
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / "dry-run.json"
        artifact_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        review_csv_path = output_dir / "review.csv"
        with review_csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["bucket", "kind", "id", "region", "source", "before", "after", "reason"])
            for row in report["actions"]:
                before = row["before"].get("chineseName") or row["before"].get("targetZh")
                after = row["after"].get("chineseName") or row["after"].get("targetZh")
                writer.writerow(
                    ["auto_clean", row["kind"], row["id"], row.get("region", ""), row.get("source", ""), before, after, ""]
                )
            for row in report["review"]:
                before = row["before"].get("chineseName") or row["before"].get("targetZh")
                after = (row.get("after") or {}).get("chineseName") or (row.get("after") or {}).get("targetZh") or ""
                writer.writerow(
                    ["review", row["kind"], row["id"], row.get("region", ""), row.get("source", ""), before, after, row.get("reason", "")]
                )
            for row in report["kept"]:
                before = row["before"].get("chineseName") or row["before"].get("targetZh")
                writer.writerow(
                    ["kept", row["kind"], row["id"], row.get("region", ""), row.get("source", ""), before, before, ""]
                )
            for row in report["locked"]:
                before = row["before"].get("chineseName") or row["before"].get("targetZh")
                writer.writerow(
                    ["locked", row["kind"], row["id"], row.get("region", ""), row.get("source", ""), before, "", "manual lock"]
                )
        summary = {
            "artifact": str(artifact_path),
            "artifactSha256": _sha256_file(artifact_path),
            "reviewCsv": str(review_csv_path),
            "counts": report["counts"],
        }
        self.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True))
