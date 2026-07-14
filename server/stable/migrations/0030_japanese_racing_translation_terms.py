from django.db import migrations


SEED_MARKER = "japanese_racing_translation_seed"
NON_HORSE_MARKER = "non_horse_common_word"

COMMON_TERMS = (
    ("レコード", "记录"),
    ("セレクトセール", "精选拍卖会"),
    ("セール", "拍卖会"),
    ("セッション", "场次"),
    ("スピード", "速度"),
    ("タイプ", "类型"),
    ("コーナー", "弯道"),
    ("ペース", "步速"),
    ("オープン", "公开级"),
    ("スムーズ", "顺畅"),
    ("トップハンデ", "最高负磅"),
    ("ハイペース", "快步速"),
    ("スパイク", "钉鞋"),
)

CONCEPTS = (
    {
        "source": "社台",
        "target": "社台",
        "term_type": "org",
        "priority": 80,
        "aliases": (("ja", "社台", "primary"), ("en", "Shadai", "alias")),
        "non_horse": False,
    },
    {
        "source": "ノーザンホースパーク",
        "target": "北方马公园",
        "term_type": "org",
        "priority": 80,
        "aliases": (
            ("ja", "ノーザンホースパーク", "primary"),
            ("en", "Northern Horse Park", "alias"),
        ),
        "non_horse": False,
    },
    *(
        {
            "source": source,
            "target": target,
            "term_type": "fixed_phrase",
            "priority": 40,
            "aliases": (("ja", source, "primary"),),
            "non_horse": True,
        }
        for source, target in COMMON_TERMS
    ),
)


def _matching_owner_ids(TermEntry, TermAlias, concept):
    owner_ids = set()
    for language, text, _alias_type in concept["aliases"]:
        owner_ids.update(
            TermEntry.objects.filter(
                source_language=language,
                source_ja__iexact=text,
            ).values_list("id", flat=True)
        )
        owner_ids.update(
            TermAlias.objects.filter(
                source_language=language,
                text__iexact=text,
            ).values_list("term_id", flat=True)
        )
    return owner_ids


def _ensure_concept(TermEntry, TermAlias, concept):
    owner_ids = _matching_owner_ids(TermEntry, TermAlias, concept)
    if len(owner_ids) > 1:
        raise RuntimeError(
            f"术语种子冲突：{concept['source']} 的来源名/别名属于多个概念 {sorted(owner_ids)}"
        )

    term = TermEntry.objects.filter(pk=next(iter(owner_ids))).first() if owner_ids else None
    if term is None:
        term = TermEntry.objects.create(
            term_type=concept["term_type"],
            source_language="ja",
            racing_region="japan",
            source_ja=concept["source"],
            target_zh=concept["target"],
            translation_status="translated",
            notes=SEED_MARKER + (f"\n{NON_HORSE_MARKER}" if concept["non_horse"] else ""),
            is_active=True,
            priority=concept["priority"],
        )
    else:
        if term.term_type != concept["term_type"]:
            raise RuntimeError(
                f"术语种子冲突：{concept['source']} 类型为 {term.term_type}，预期 {concept['term_type']}"
            )
        if term.target_zh and term.target_zh != concept["target"]:
            raise RuntimeError(
                f"术语种子冲突：{concept['source']} 中文为 {term.target_zh}，预期 {concept['target']}"
            )
        if term.racing_region not in {"", "japan"}:
            raise RuntimeError(
                f"术语种子冲突：{concept['source']} 地区为 {term.racing_region}，预期 japan 或全局"
            )
        changed = []
        if not term.target_zh:
            term.target_zh = concept["target"]
            changed.append("target_zh")
        if getattr(term, "translation_status", "translated") != "translated":
            term.translation_status = "translated"
            changed.append("translation_status")
        if not term.is_active:
            term.is_active = True
            changed.append("is_active")
        required_markers = [SEED_MARKER]
        if concept["non_horse"]:
            required_markers.append(NON_HORSE_MARKER)
        notes = term.notes or ""
        for marker in required_markers:
            if marker not in notes.casefold():
                notes = f"{notes}\n{marker}".strip()
        if notes != (term.notes or ""):
            term.notes = notes
            changed.append("notes")
        if changed:
            term.save(update_fields=[*changed, "updated_at"])

    for language, text, alias_type in concept["aliases"]:
        conflicting_primary = TermEntry.objects.filter(
            source_language=language,
            source_ja__iexact=text,
        ).exclude(pk=term.pk)
        conflicting_alias = TermAlias.objects.filter(
            source_language=language,
            text__iexact=text,
        ).exclude(term_id=term.pk)
        if conflicting_primary.exists() or conflicting_alias.exists():
            raise RuntimeError(f"术语别名冲突：{language}:{text} 已属于另一概念")
        alias = TermAlias.objects.filter(
            term_id=term.pk,
            source_language=language,
            text__iexact=text,
        ).first()
        if alias is None:
            TermAlias.objects.create(
                term_id=term.pk,
                source_language=language,
                text=text,
                alias_type=alias_type,
                is_active=True,
            )
        else:
            changed = []
            if alias.alias_type != alias_type:
                alias.alias_type = alias_type
                changed.append("alias_type")
            if not alias.is_active:
                alias.is_active = True
                changed.append("is_active")
            if changed:
                alias.save(update_fields=[*changed, "updated_at"])


def seed_japanese_racing_translation_terms(apps, schema_editor):
    TermEntry = apps.get_model("stable", "TermEntry")
    TermAlias = apps.get_model("stable", "TermAlias")
    for concept in CONCEPTS:
        _ensure_concept(TermEntry, TermAlias, concept)


def unseed_japanese_racing_translation_terms(apps, schema_editor):
    # These entries may be used or edited immediately after deployment. Keeping
    # them is safer than deleting operational terminology during a code rollback.
    return None


class Migration(migrations.Migration):
    dependencies = [("stable", "0029_france_freshness_translation_attribution")]

    operations = [
        migrations.RunPython(
            seed_japanese_racing_translation_terms,
            unseed_japanese_racing_translation_terms,
        )
    ]
