from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from stable.models import NewsArticle
from stable.services.news_body_history import (
    _SHA256_RE,
    apply_batch_inside_transaction,
    build_receipt,
    build_rollback_artifact,
    validate_approved_decisions,
)


class Command(BaseCommand):
    help = "离线精确写入历史正文修复批次。"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--manifest-sha256", required=True)
        parser.add_argument("--candidate-manifest")
        parser.add_argument("--candidate-manifest-sha256")
        parser.add_argument("--rollback-dir", required=True)
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        manifest_path = Path(options["manifest"])
        manifest_sha256 = (options["manifest_sha256"] or "").lower()
        candidate_path = options.get("candidate_manifest")
        candidate_sha256 = (options.get("candidate_manifest_sha256") or "").lower()
        rollback_dir = Path(options["rollback_dir"])
        commit = bool(options["commit"])

        # Step 1: validate manifest file SHA
        if not _SHA256_RE.fullmatch(manifest_sha256):
            raise CommandError("--manifest-sha256 必须是 64 位十六进制 SHA-256")

        try:
            raw = manifest_path.read_bytes()
        except OSError as exc:
            raise CommandError(f"无法读取批准 manifest: {exc}") from exc

        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha != manifest_sha256:
            raise CommandError("批准 manifest 文件 SHA-256 不匹配")

        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError("批准 manifest 不是有效 UTF-8 JSON") from exc

        # ── P1 fix: candidate manifest SHA trust chain ──
        if not candidate_path:
            raise CommandError("--candidate-manifest 必须提供（批准 manifest 必须绑定 candidate artifact）")
        if not _SHA256_RE.fullmatch(candidate_sha256):
            raise CommandError("--candidate-manifest-sha256 必须是 64 位十六进制 SHA-256")

        try:
            candidate_raw = Path(candidate_path).read_bytes()
        except OSError as exc:
            raise CommandError(f"无法读取 candidate manifest: {exc}") from exc

        actual_candidate_sha = hashlib.sha256(candidate_raw).hexdigest()
        if actual_candidate_sha != candidate_sha256:
            raise CommandError(
                f"candidate manifest 文件 SHA-256 不匹配: "
                f"expected={candidate_sha256[:16]}... actual={actual_candidate_sha[:16]}..."
            )

        # Cross-validate: approved manifest's candidate_manifest_sha256 must equal candidate file SHA
        manifest_candidate_sha = manifest.get("candidate_manifest_sha256", "")
        if manifest_candidate_sha != candidate_sha256:
            raise CommandError(
                f"批准 manifest.candidate_manifest_sha256 与 candidate 文件 SHA 不匹配: "
                f"manifest={manifest_candidate_sha[:16]}... file={candidate_sha256[:16]}..."
            )

        # Parse candidate manifest for content binding
        try:
            candidate_manifest = json.loads(candidate_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError(f"candidate manifest 不是有效 UTF-8 JSON: {exc}") from exc

        # Step 2: validate decisions (with candidate content binding)
        errors = validate_approved_decisions(
            manifest,
            candidate_manifest_sha256=candidate_sha256,
            candidate_manifest=candidate_manifest,
        )
        if errors:
            raise CommandError("批准 manifest 验证失败: " + "; ".join(errors))

        decisions = manifest.get("decisions", [])
        article_ids = sorted([d["article_id"] for d in decisions])

        if not commit:
            articles = list(NewsArticle.objects.filter(id__in=article_ids).order_by("id"))
            from stable.services.news_body_history import compute_before_fingerprint
            dry_run_rows = []
            for article in articles:
                dec = next(d for d in decisions if d["article_id"] == article.id)
                dry_run_rows.append({
                    "article_id": article.id,
                    "decision": dec["decision"],
                    "before_fingerprint": compute_before_fingerprint(article),
                    "approved_fields": dec.get("approved_fields", []),
                })
            self.stdout.write(json.dumps(
                {"mode": "dry_run", "articles": dry_run_rows},
                ensure_ascii=False, indent=2, default=str))
            return

        # Step 3: build rollback artifact BEFORE transaction
        articles_pre = list(NewsArticle.objects.filter(id__in=article_ids).order_by("id"))
        if len(articles_pre) != len(article_ids):
            missing = set(article_ids) - {a.id for a in articles_pre}
            raise CommandError(f"文章不存在: {sorted(missing)}")

        rollback_path, rollback_sha = build_rollback_artifact(articles_pre, output_dir=rollback_dir)

        # Step 4: transaction — lock, validate, write
        with transaction.atomic():
            articles_locked = list(
                NewsArticle.objects.select_for_update()
                .filter(id__in=article_ids).order_by("id")
            )
            results, post_apply_fps = apply_batch_inside_transaction(
                articles=articles_locked,
                approved_manifest=manifest,
                approved_manifest_sha256=manifest_sha256,
                rollback_artifact_sha256=rollback_sha,
            )

        # Step 5: write receipt AFTER transaction
        receipt_sha = build_receipt(
            approved_manifest_sha256=manifest_sha256,
            rollback_artifact_sha256=rollback_sha,
            results=results,
            post_apply_fingerprints=post_apply_fps,
            output_dir=rollback_dir,
        )

        self.stdout.write(json.dumps({
            "mode": "commit",
            "receipt_sha256": receipt_sha,
            "rollback_artifact_sha256": rollback_sha,
            "results": results,
        }, ensure_ascii=False, indent=2, default=str))
