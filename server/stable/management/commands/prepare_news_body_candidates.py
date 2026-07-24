from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stable.adapters.international import INTERNATIONAL_ADAPTERS
from stable.models import NewsArticle
from stable.services.news_body_history import _canonical_sha, _sha256, compute_before_fingerprint
from stable.services.terms import resolve_article_entities
from stable.services.translation import get_translation_provider


class Command(BaseCommand):
    help = "生成翻译候选 (pure provider + detached DTO, 不写数据库)."

    def add_arguments(self, parser):
        parser.add_argument("--article-id", dest="article_ids", action="append", type=int, required=True)
        parser.add_argument("--output-dir", required=True)
        parser.add_argument("--max-articles", type=int, default=10)

    def handle(self, *args, **options):
        article_ids = list(dict.fromkeys(options["article_ids"]))
        output_dir = Path(options["output_dir"])
        max_articles = options["max_articles"]

        if len(article_ids) > max_articles:
            raise CommandError(f"最多 {max_articles} 篇, 收到 {len(article_ids)} 篇")

        output_dir.mkdir(parents=True, exist_ok=True)

        articles = list(NewsArticle.objects.filter(id__in=article_ids).order_by("id"))
        if len(articles) != len(article_ids):
            found = {a.id for a in articles}
            missing = sorted(set(article_ids) - found)
            raise CommandError(f"文章不存在: {missing}")

        provider = get_translation_provider()
        entries = []
        errors_list = []

        for article in articles:
            self.stdout.write(f"Processing article {article.id}...")
            entry = self._prepare_one(article, provider)
            if entry.get("error"):
                errors_list.append(entry)
            entries.append(entry)

        candidate_manifest = {
            "schema_version": 1,
            "generated_at": str(__import__("django").utils.timezone.now()),
            "entries": entries,
        }
        candidate_path = output_dir / "candidate_manifest.json"
        raw = json.dumps(candidate_manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        candidate_path.write_bytes(raw)
        candidate_sha = hashlib.sha256(raw).hexdigest()

        self.stdout.write(json.dumps({
            "status": "ok",
            "candidate_manifest_sha256": candidate_sha,
            "total": len(entries),
            "errors": len(errors_list),
            "output_dir": str(output_dir),
        }, ensure_ascii=False, indent=2))

    def _prepare_one(self, article, provider):
        entry = {
            "article_id": article.id,
            "source_site": article.source_site,
            "source_status": None,
            "approved_fields": [],
            "exact_output": {},
            "before_fingerprint": compute_before_fingerprint(article),
            "error": None,
        }

        adapter_class = INTERNATIONAL_ADAPTERS.get(article.source_site)
        if adapter_class is None:
            entry["error"] = f"unsupported source: {article.source_site}"
            return entry

        if not article.original_content_html:
            entry["error"] = "missing original_content_html"
            entry["source_status"] = "blocked"
            return entry

        try:
            detail = adapter_class().parse_detail_html(
                article.original_content_html, url=article.source_url)
        except Exception as exc:
            entry["error"] = f"parse error: {exc}"
            entry["source_status"] = "blocked"
            return entry

        parse_status = str(detail.metadata.get("body_parse_status") or "unknown")
        if parse_status != "ok" or not detail.body_ja_normalized:
            entry["error"] = f"parse failed: {parse_status}"
            entry["source_status"] = "blocked"
            return entry

        clean_body = detail.body_ja_raw or ""
        clean_body_norm = detail.body_ja_normalized or ""

        before_body_sha = _sha256(article.body_ja_raw)
        after_body_sha = _sha256(clean_body)
        source_changed = before_body_sha != after_body_sha
        entry["source_status"] = "source_changed" if source_changed else "source_clean"

        if source_changed:
            entry["approved_fields"].extend(["body_ja_raw", "body_ja_normalized"])
            entry["exact_output"]["body_ja_raw"] = clean_body
            entry["exact_output"]["body_ja_normalized"] = clean_body_norm
            entry["source_evidence"] = {
                "source_status": "source_changed",
                "body_parse_status": "ok",
            }
            source_for_translation = clean_body_norm
        else:
            source_for_translation = article.body_ja_normalized or article.body_ja_raw

        # Call translation API with clean source (swap body fields temporarily)
        _old_raw, _old_norm = article.body_ja_raw, article.body_ja_normalized
        article.body_ja_raw = clean_body
        article.body_ja_normalized = clean_body_norm
        try:
            try:
                resolution = resolve_article_entities(
                    article.title_ja, source_for_translation,
                    source_language=article.source_language)
            except Exception:
                resolution = None
            try:
                if resolution is not None:
                    result = provider.translate(article, entity_resolution=resolution)
                else:
                    result = provider.translate(article)
            except Exception as exc:
                entry["error"] = f"translation failed: {exc}"
                return entry
        finally:
            article.body_ja_raw, article.body_ja_normalized = _old_raw, _old_norm

        if result is None:
            entry["error"] = "translation returned None"
            return entry

        translated_body = result.body_zh or ""
        if not translated_body.strip():
            entry["error"] = "translation returned empty body"
            return entry

        entry["approved_fields"].append("translated_body_zh")
        entry["exact_output"]["translated_body_zh"] = translated_body
        entry["provider"] = getattr(provider, "name", "unknown")
        entry["model"] = getattr(result, "metadata", {}).get("model", "unknown")

        manual_fields = list(article.manually_edited_fields or [])
        if "body_zh" not in manual_fields:
            entry["approved_fields"].append("body_zh")
            entry["exact_output"]["body_zh"] = translated_body

        push_summary = getattr(result, "push_summary_zh", "") or ""
        if push_summary:
            entry["approved_fields"].append("translated_summary_zh")
            entry["exact_output"]["translated_summary_zh"] = push_summary
            if "summary_zh" not in manual_fields:
                entry["approved_fields"].append("summary_zh")
                entry["exact_output"]["summary_zh"] = push_summary
            if "push_summary_zh" not in manual_fields:
                entry["approved_fields"].append("push_summary_zh")
                entry["exact_output"]["push_summary_zh"] = push_summary

        entry["candidate_sha256"] = _canonical_sha(entry["exact_output"])
        return entry
