from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass

from django.utils import timezone

from stable.models import RacingRegion, SourceLanguage, TermAlias, TermAliasType, TermEntry, TermType
from stable.services.race_grades import normalize_race_grade


VALID_TERM_TYPES = {value for value, _label in TermType.choices}
VALID_TERM_REGIONS = {"", *{value for value, _label in RacingRegion.choices}}
EXPECTED_CSV_HEADERS = {
    "term_type",
    "source_language",
    "racing_region",
    "source_ja",
    "target_zh",
    "aliases_ja",
    "aliases_zh",
    "priority",
    "is_active",
    "notes",
    "race_grade",
}
CSV_CANDIDATE_ENCODINGS = (
    "utf-8-sig",
    "utf-8",
    "utf-16",
    "utf-16-le",
    "utf-16-be",
    "gb18030",
    "cp932",
    "shift_jis",
    "big5",
)
VALID_BOOL_TRUE = {"1", "true", "yes", "y", "on", "启用", "是"}
VALID_BOOL_FALSE = {"0", "false", "no", "n", "off", "停用", "否"}
SUPPORTED_TERM_SOURCE_LANGUAGES = {
    SourceLanguage.JAPANESE,
    SourceLanguage.ENGLISH,
    SourceLanguage.CHINESE_TRADITIONAL,
}


@dataclass
class ImportPreviewRow:
    line_no: int
    status: str
    payload: dict
    errors: list[str]
    existing_id: int | None = None


def split_aliases(raw: str | list | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        values = raw
    else:
        values = re.split(r"[\r\n|,，、]+", str(raw))
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        value = str(item).strip()
        key = source_text_identity(value)
        if not value or key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized


def serialize_aliases(values: list[str]) -> str:
    return "\n".join(values or [])


def term_source_texts(source_ja: str, aliases_ja: list[str]) -> list[str]:
    values = [source_ja, *(aliases_ja or [])]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = (value or "").strip()
        key = source_text_identity(normalized)
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def source_text_identity(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold()


def source_aliases_for_primary(source_ja: str, aliases_ja: list[str]) -> list[str]:
    primary_key = source_text_identity(source_ja)
    aliases: list[str] = []
    seen: set[str] = {primary_key} if primary_key else set()
    for alias in aliases_ja or []:
        value = (alias or "").strip()
        key = source_text_identity(value)
        if not value or key in seen:
            continue
        seen.add(key)
        aliases.append(value)
    return aliases


def find_term_by_source_alias(
    *,
    term_type: str,
    source_language: str,
    source_text: str,
    exclude_term_id: int | None = None,
) -> TermEntry | None:
    text = (source_text or "").strip()
    if not term_type or not source_language or not text:
        return None
    alias_queryset = TermAlias.objects.select_related("term").filter(
        term__term_type=term_type,
        source_language=source_language,
        text__iexact=text,
    )
    if exclude_term_id:
        alias_queryset = alias_queryset.exclude(term_id=exclude_term_id)
    alias = alias_queryset.first()
    if alias:
        return alias.term
    entry_queryset = TermEntry.objects.filter(
        term_type=term_type,
        source_language=source_language,
        source_ja__iexact=text,
    )
    if exclude_term_id:
        entry_queryset = entry_queryset.exclude(pk=exclude_term_id)
    return entry_queryset.first()


def resolve_term_import_target(
    *,
    term_type: str,
    source_language: str,
    source_ja: str,
    aliases_ja: list[str],
) -> tuple[TermEntry | None, list[str]]:
    existing = find_term_by_source_alias(
        term_type=term_type,
        source_language=source_language,
        source_text=source_ja,
    )
    conflict_errors: list[str] = []
    for alias in source_aliases_for_primary(source_ja, aliases_ja):
        alias_owner = find_term_by_source_alias(
            term_type=term_type,
            source_language=source_language,
            source_text=alias,
        )
        if alias_owner is None:
            continue
        if existing is not None and alias_owner.pk == existing.pk:
            continue
        conflict_errors.append(
            f"原文别名“{alias}”已属于术语 ID：{alias_owner.pk}，不能用于另一条术语。"
        )
    return existing, conflict_errors


def sync_term_source_alias_values(
    term: TermEntry,
    *,
    source_language: str,
    source_text: str,
    aliases: list[str],
    is_active: bool,
) -> None:
    language = source_language or SourceLanguage.JAPANESE
    primary = (source_text or "").strip()
    desired = [(primary, TermAliasType.PRIMARY), *[(alias, TermAliasType.ALIAS) for alias in aliases]]
    seen: set[str] = set()
    keep_ids: list[int] = []
    existing_aliases = list(
        TermAlias.objects.filter(term=term, source_language=language).order_by("alias_type", "text", "pk")
    )
    for text, alias_type in desired:
        normalized = (text or "").strip()
        key = source_text_identity(normalized)
        if not normalized or key in seen:
            continue
        seen.add(key)
        alias = next((item for item in existing_aliases if item.text == normalized), None)
        if alias is None:
            alias = next((item for item in existing_aliases if source_text_identity(item.text) == key), None)
        created = alias is None
        if created:
            alias = TermAlias.objects.create(
                term=term,
                source_language=language,
                text=normalized,
                alias_type=alias_type,
                is_active=is_active,
            )
            existing_aliases.append(alias)
        updates = []
        if alias.text != normalized:
            alias.text = normalized
            updates.append("text")
        if alias.alias_type != alias_type:
            alias.alias_type = alias_type
            updates.append("alias_type")
        if alias.is_active != is_active:
            alias.is_active = is_active
            updates.append("is_active")
        if updates and not created:
            alias.save(update_fields=[*updates, "updated_at"])
        keep_ids.append(alias.pk)
    TermAlias.objects.filter(term=term, source_language=language).exclude(pk__in=keep_ids).delete()


def upsert_term_source_alias(
    term: TermEntry,
    *,
    source_language: str,
    text: str,
    alias_type: str = TermAliasType.ALIAS,
    is_active: bool | None = None,
) -> TermAlias | None:
    language = source_language or SourceLanguage.JAPANESE
    normalized = (text or "").strip()
    if not normalized:
        return None
    alias = (
        TermAlias.objects.filter(term=term, source_language=language, text__iexact=normalized)
        .order_by("alias_type", "text", "pk")
        .first()
    )
    if alias is None:
        return TermAlias.objects.create(
            term=term,
            source_language=language,
            text=normalized,
            alias_type=alias_type,
            is_active=term.is_active if is_active is None else is_active,
        )
    updates = []
    if alias.text != normalized:
        alias.text = normalized
        updates.append("text")
    if alias.alias_type != alias_type:
        alias.alias_type = alias_type
        updates.append("alias_type")
    desired_active = term.is_active if is_active is None else is_active
    if alias.is_active != desired_active:
        alias.is_active = desired_active
        updates.append("is_active")
    if updates:
        alias.save(update_fields=[*updates, "updated_at"])
    return alias


def sync_term_source_aliases(term: TermEntry, source_language: str | None = None) -> None:
    sync_term_source_alias_values(
        term,
        source_language=source_language or term.source_language or SourceLanguage.JAPANESE,
        source_text=term.source_ja,
        aliases=split_aliases(term.aliases_ja),
        is_active=term.is_active,
    )


def sync_all_term_alias_active(term: TermEntry) -> None:
    TermAlias.objects.filter(term=term).update(is_active=term.is_active, updated_at=timezone.now())


def parse_bool(raw, default: bool = True) -> bool:
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        return raw
    normalized = str(raw).strip().lower()
    if normalized in VALID_BOOL_TRUE:
        return True
    if normalized in VALID_BOOL_FALSE:
        return False
    raise ValueError("布尔值格式不合法")


def _count_cjk_characters(text: str) -> int:
    return sum(
        1
        for char in text
        if (
            "\u4e00" <= char <= "\u9fff"
            or "\u3040" <= char <= "\u30ff"
            or "\u31f0" <= char <= "\u31ff"
        )
    )


def _count_kana_characters(text: str) -> int:
    return sum(1 for char in text if ("\u3040" <= char <= "\u30ff" or "\u31f0" <= char <= "\u31ff"))


def _count_halfwidth_katakana(text: str) -> int:
    return sum(1 for char in text if "\uff61" <= char <= "\uff9f")


def _score_decoded_csv(text: str) -> tuple[int, int]:
    if not text.strip():
        return (-10_000, 0)
    try:
        headers = next(csv.reader(io.StringIO(text)))
    except Exception:
        headers = []
    normalized_headers = {header.strip().lower().lstrip("\ufeff") for header in headers if header.strip()}
    header_matches = len(normalized_headers & EXPECTED_CSV_HEADERS)

    replacement_penalty = text.count("\ufffd") * 100
    mojibake_markers = ("锛", "銆", "鈥", "鈩", "ï", "Ã", "Â", "¤", "�")
    mojibake_penalty = sum(text.count(marker) for marker in mojibake_markers) * 8
    control_penalty = sum(1 for char in text if ord(char) < 32 and char not in "\r\n\t") * 30
    cjk_bonus = min(_count_cjk_characters(text), 400)
    kana_bonus = _count_kana_characters(text) * 40
    halfwidth_katakana_penalty = _count_halfwidth_katakana(text) * 50
    score = (
        header_matches * 1000
        + cjk_bonus
        + kana_bonus
        - replacement_penalty
        - mojibake_penalty
        - control_penalty
        - halfwidth_katakana_penalty
    )
    return score, header_matches


def decode_csv_bytes(raw: bytes) -> tuple[str, str]:
    candidates: list[tuple[int, int, str, str]] = []
    for encoding in CSV_CANDIDATE_ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text.startswith("\ufeff"):
            text = text.lstrip("\ufeff")
        score, header_matches = _score_decoded_csv(text)
        candidates.append((score, header_matches, encoding, text))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        _score, _matches, encoding, text = candidates[0]
        return text, encoding

    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def validate_term_payload(
    payload: dict,
    instance_id: int | None = None,
    allow_existing: bool = False,
) -> tuple[dict, dict[str, list[str]]]:
    errors: dict[str, list[str]] = {}

    term_type = (payload.get("term_type") or "").strip()
    source_language = (payload.get("source_language") or SourceLanguage.JAPANESE).strip()
    racing_region = (payload.get("racing_region") or "").strip()
    source_ja = (payload.get("source_ja") or "").strip()
    target_zh = (payload.get("target_zh") or "").strip()
    notes = (payload.get("notes") or "").strip()
    aliases_ja = source_aliases_for_primary(source_ja, split_aliases(payload.get("aliases_ja")))
    aliases_zh = split_aliases(payload.get("aliases_zh"))
    race_grade_raw = (payload.get("race_grade") or "").strip()

    if not term_type:
        errors.setdefault("term_type", []).append("术语类型不能为空。")
    elif term_type not in VALID_TERM_TYPES:
        errors.setdefault("term_type", []).append("术语类型不合法。")

    if source_language not in SUPPORTED_TERM_SOURCE_LANGUAGES:
        errors.setdefault("source_language", []).append("原文语言不合法。")

    if racing_region not in VALID_TERM_REGIONS:
        errors.setdefault("racing_region", []).append("地区不合法。")

    if not source_ja:
        errors.setdefault("source_ja", []).append("原文不能为空。")

    if not target_zh and term_type != TermType.HORSE:
        errors.setdefault("target_zh", []).append("中文译词不能为空。")
    translation_status = "translated" if target_zh else "pending"

    try:
        priority = int(payload.get("priority") if payload.get("priority") not in (None, "") else 0)
    except (TypeError, ValueError):
        errors.setdefault("priority", []).append("优先级必须是整数。")
        priority = 0

    try:
        is_active = parse_bool(payload.get("is_active"), default=True)
    except ValueError:
        errors.setdefault("is_active", []).append("启用状态格式不合法。")
        is_active = True

    race_grade = normalize_race_grade(race_grade_raw)
    if race_grade_raw and not race_grade:
        errors.setdefault("race_grade", []).append("比赛等级不合法。")
    if term_type and term_type != TermType.RACE and race_grade:
        errors.setdefault("race_grade", []).append("只有赛事术语可以设置比赛等级。")
        race_grade = ""

    if term_type and source_ja and not allow_existing:
        for source_text in term_source_texts(source_ja, aliases_ja):
            existing = find_term_by_source_alias(
                term_type=term_type,
                source_language=source_language,
                source_text=source_text,
                exclude_term_id=instance_id,
            )
            if existing:
                errors.setdefault("source_ja", []).append(
                    f"同一术语类型和原文语言下已存在相同原文或别名“{source_text}”，已有术语 ID：{existing.pk}。"
                )
                break

    normalized = {
        "term_type": term_type,
        "source_language": source_language,
        "racing_region": racing_region,
        "source_ja": source_ja,
        "target_zh": target_zh,
        "translation_status": translation_status,
        "aliases_ja": aliases_ja,
        "aliases_zh": aliases_zh,
        "race_grade": race_grade,
        "priority": priority,
        "is_active": is_active,
        "notes": notes,
    }
    return normalized, errors


def parse_csv_content(*, csv_file=None, csv_text: str = "") -> tuple[list[dict], str]:
    if csv_file is not None:
        raw = csv_file.read()
        if isinstance(raw, bytes):
            text, detected_encoding = decode_csv_bytes(raw)
        else:
            text = str(raw)
            detected_encoding = "text"
    else:
        text = csv_text
        detected_encoding = "text"
    stream = io.StringIO(text)
    reader = csv.DictReader(stream)
    return list(reader), detected_encoding


def preview_term_import(*, csv_file=None, csv_text: str = "", import_mode: str = "create") -> dict:
    rows, detected_encoding = parse_csv_content(csv_file=csv_file, csv_text=csv_text)
    previews: list[ImportPreviewRow] = []
    create_count = 0
    update_count = 0
    error_count = 0

    for index, row in enumerate(rows, start=2):
        normalized, field_errors = validate_term_payload(
            {
                "term_type": row.get("term_type"),
                "source_language": row.get("source_language") or row.get("language"),
                "racing_region": row.get("racing_region") or row.get("region"),
                "source_ja": row.get("source_ja"),
                "target_zh": row.get("target_zh"),
                "aliases_ja": row.get("aliases_ja"),
                "aliases_zh": row.get("aliases_zh"),
                "priority": row.get("priority"),
                "is_active": row.get("is_active"),
                "notes": row.get("notes"),
                "race_grade": row.get("race_grade"),
            },
            allow_existing=import_mode == "upsert",
        )
        existing = None
        conflict_errors: list[str] = []
        if normalized["term_type"] and normalized["source_ja"]:
            existing, conflict_errors = resolve_term_import_target(
                term_type=normalized["term_type"],
                source_language=normalized["source_language"],
                source_ja=normalized["source_ja"],
                aliases_ja=normalized["aliases_ja"],
            )

        flat_errors = [message for messages in field_errors.values() for message in messages]
        flat_errors.extend(conflict_errors)
        status = "create"
        if existing and import_mode == "create":
            flat_errors.append(f"第 {index} 行与已有术语重复，已有术语 ID：{existing.pk}。")
        elif existing and import_mode == "upsert":
            status = "update"

        if flat_errors:
            status = "error"
            error_count += 1
        elif status == "create":
            create_count += 1
        else:
            update_count += 1

        previews.append(
            ImportPreviewRow(
                line_no=index,
                status=status,
                payload=normalized,
                errors=flat_errors,
                existing_id=existing.pk if existing else None,
            )
        )

    return {
        "rows": [row.__dict__ for row in previews],
        "summary": {
            "total": len(previews),
            "create_count": create_count,
            "update_count": update_count,
            "error_count": error_count,
        },
        "detected_encoding": detected_encoding,
        "can_commit": bool(previews) and error_count == 0,
        "import_mode": import_mode,
    }


def commit_term_import(preview_rows: list[dict], import_mode: str) -> dict:
    success_count = 0
    update_count = 0
    skipped_count = 0
    failed_rows: list[dict] = []

    for row in preview_rows:
        if row.get("status") == "error":
            skipped_count += 1
            failed_rows.append({"line_no": row.get("line_no"), "errors": row.get("errors", [])})
            continue

        payload = row.get("payload", {})
        existing, conflict_errors = resolve_term_import_target(
            term_type=payload.get("term_type"),
            source_language=payload.get("source_language") or SourceLanguage.JAPANESE,
            source_ja=payload.get("source_ja"),
            aliases_ja=payload.get("aliases_ja") or [],
        )
        if conflict_errors:
            skipped_count += 1
            failed_rows.append({"line_no": row.get("line_no"), "errors": conflict_errors})
            continue

        if existing and import_mode == "create":
            skipped_count += 1
            failed_rows.append({"line_no": row.get("line_no"), "errors": ["新增模式下不允许覆盖已有术语。"]})
            continue

        if existing and import_mode == "upsert":
            entry = existing
            update_count += 1
        else:
            entry = TermEntry()
            success_count += 1

        payload_language = payload.get("source_language") or SourceLanguage.JAPANESE
        payload_source = payload.get("source_ja", "")
        should_replace_primary_source = not existing or (
            entry.source_language == payload_language
            and source_text_identity(entry.source_ja) == source_text_identity(payload_source)
        )

        if should_replace_primary_source:
            entry.term_type = payload.get("term_type", "")
            entry.source_language = payload_language
            entry.racing_region = payload.get("racing_region", "")
            entry.source_ja = payload_source
        entry.target_zh = payload.get("target_zh", "")
        entry.translation_status = payload.get("translation_status") or ("translated" if entry.target_zh else "pending")
        entry.aliases_zh = payload.get("aliases_zh", [])
        entry.race_grade = payload.get("race_grade", "")
        entry.priority = payload.get("priority", 0)
        entry.is_active = payload.get("is_active", True)
        entry.notes = payload.get("notes", "")
        if should_replace_primary_source:
            entry.aliases_ja = payload.get("aliases_ja", [])
        entry.save()
        if should_replace_primary_source:
            sync_term_source_aliases(entry, entry.source_language)
        else:
            sync_term_source_alias_values(
                entry,
                source_language=payload_language,
                source_text=payload_source,
                aliases=payload.get("aliases_ja", []),
                is_active=entry.is_active,
            )

    return {
        "total": len(preview_rows),
        "success_count": success_count,
        "update_count": update_count,
        "skipped_count": skipped_count,
        "failed_rows": failed_rows,
    }


def preview_to_session_value(preview: dict) -> str:
    return json.dumps(preview, ensure_ascii=False)


def preview_from_session_value(raw: str) -> dict:
    return json.loads(raw)
