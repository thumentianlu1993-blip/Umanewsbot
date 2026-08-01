#!/usr/bin/env python3
"""Add base-name aliases for disambiguated graded-horse TermEntry rows.

When graded horses were imported from theracingapi.horse_profile, horses whose
base name collided with an existing TermEntry had their `source_ja` set to
"Base Name (COUNTRY)" so the term remained unique.  News text normally only
mentions the base name (e.g. "A Bit Of Spirit"), so auto-linking misses these
horses.  This command backfills the base name as an English alias for every
affected horse term.
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from stable.models import HorseProfile, SourceLanguage, TermEntry, TermType
from stable.services.term_admin import sync_term_source_aliases


COUNTRY_SUFFIX_RE = re.compile(r"\s+\(([A-Z]{2,3})\)$")
BATCH_SIZE = 500


def _extract_base_alias(source_ja: str) -> str | None:
    """Return the base name if source_ja ends with a country suffix, else None."""
    if not source_ja:
        return None
    match = COUNTRY_SUFFIX_RE.search(source_ja)
    if not match:
        return None
    return source_ja[: match.start()].strip()


class Command(BaseCommand):
    help = "为带国别后缀的重赏导入马术语添加基础英文名别名。"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="预览变更，不写入数据库。")
        parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="每批处理的术语数。")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        candidate_ids = list(
            TermEntry.objects.filter(
                term_type=TermType.HORSE,
                is_active=True,
                source_ja__regex=r"\s+\([A-Z]{2,3}\)$",
                horse_profile__source_refs__has_key="theracingapi_horse_id",
            )
            .distinct()
            .order_by("id")
            .values_list("id", flat=True)
        )

        total_candidates = len(candidate_ids)
        self.stdout.write(f"找到 {total_candidates} 个需要添加基础名别名的马术语")

        updated = 0
        skipped = 0

        for i in range(0, total_candidates, batch_size):
            batch_ids = candidate_ids[i : i + batch_size]
            terms = list(
                TermEntry.objects.filter(id__in=batch_ids)
                .prefetch_related("source_aliases")
                .order_by("id")
            )

            with transaction.atomic():
                for term in terms:
                    base_alias = _extract_base_alias(term.source_ja)
                    if not base_alias:
                        skipped += 1
                        continue

                    aliases_ja = term.aliases_ja or []
                    if not isinstance(aliases_ja, list):
                        aliases_ja = [aliases_ja]

                    existing_keys = {a.lower().strip() for a in aliases_ja}
                    existing_keys.add(term.source_ja.lower().strip())

                    if base_alias.lower().strip() in existing_keys:
                        skipped += 1
                        continue

                    aliases_ja = [*aliases_ja, base_alias]
                    term.aliases_ja = aliases_ja
                    term.save(update_fields=["aliases_ja", "updated_at"])
                    sync_term_source_aliases(term, SourceLanguage.ENGLISH)
                    updated += 1

                if dry_run:
                    transaction.set_rollback(True)

            self.stdout.write(
                f"[batch] {i + len(batch_ids)}/{total_candidates} updated={updated} skipped={skipped}"
            )

        action = "将更新" if dry_run else "已更新"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} {updated} 个马术语的基础名别名（跳过 {skipped} 个）"
            )
        )
