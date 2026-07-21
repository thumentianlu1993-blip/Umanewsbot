"""赛事展示名与 race 术语的去让赛清理服务。

规则（用户 2026-07-21 锁定）：以原文名的括号形式为准——
- 原文中 handicap/让赛 被括号圈住：视为赛事补充说明，中文展示名删除该标记；
- 原文中 handicap/让赛 未被括号圈住：视为赛事名组成部分，保留；
- 唯一例外：京成杯秋季让赛 一律改为用户逐字锁定的 京成杯秋季赛。

删除机制只删不补：仅删除四种中文标记及直接包裹该标记的中英文括号。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from django.db import transaction
from django.utils import timezone

HANDICAP_MARKERS = ("让赛", "讓賽", "让步赛", "讓步賽")
LOCKED_NAME_OVERRIDES = {
    "京成杯秋季让赛": "京成杯秋季赛",
}

_MARKER_RE = re.compile("|".join(re.escape(m) for m in HANDICAP_MARKERS))
_BRACKETED_MARKER_RE = re.compile(
    r"[（(]\s*(?:让赛|讓賽|让步赛|讓步賽)\s*[）)]"
)
_BRACKETED_ORIGINAL_MARKER_RE = re.compile(
    r"[（(]\s*(?:handicap|h|让赛|讓賽|让步赛|讓步賽)\s*[）)]",
    re.IGNORECASE,
)
_CJK_RE = re.compile(r"[一-鿿]")


class CleanupError(RuntimeError):
    pass


def contains_marker(value: str) -> bool:
    return any(marker in (value or "") for marker in HANDICAP_MARKERS)


def clean_display_name(value: str) -> str:
    """删除中文展示名中的让赛标记；只删不补。"""
    text = value or ""
    if text in LOCKED_NAME_OVERRIDES:
        return LOCKED_NAME_OVERRIDES[text]
    cleaned = text
    while True:
        bracket = _BRACKETED_MARKER_RE.search(cleaned)
        if not bracket:
            break
        start = bracket.start()
        remove_start = start - 1 if start > 0 and cleaned[start - 1] == " " else start
        cleaned = cleaned[:remove_start] + cleaned[bracket.end():]
    return _MARKER_RE.sub("", cleaned)


def has_bracketed_marker_in_original(original: str) -> bool:
    """原文名中 handicap/让赛 是否被括号圈住（补充说明形式）。"""
    return bool(_BRACKETED_ORIGINAL_MARKER_RE.search(original or ""))


def should_clean(original: str, display_name: str) -> bool:
    """是否应清理该展示名：原文括号标记，或京成杯锁定例外。"""
    if (display_name or "") in LOCKED_NAME_OVERRIDES:
        return True
    return has_bracketed_marker_in_original(original)


def classify_object(
    original: str,
    display_name: str,
    seen_names: set[tuple[str, str]],
    region: str = "",
) -> str:
    """分桶：auto_clean / review / kept。"""
    if not should_clean(original, display_name):
        return "kept"
    cleaned = clean_display_name(display_name)
    if (
        not cleaned
        or not _has_cjk(cleaned)
        or contains_marker(cleaned)
        or (region, cleaned) in seen_names
    ):
        return "review"
    return "auto_clean"


def _has_cjk(value: str) -> bool:
    return bool(_CJK_RE.search(value or ""))


def _marker_query(field: str):
    from django.db.models import Q

    query = Q()
    for marker in HANDICAP_MARKERS:
        query |= Q(**{f"{field}__contains": marker})
    return query


def build_dry_run() -> dict[str, Any]:
    from stable.models import RaceEvent, RaceSeries, TermEntry

    actions: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    locked: list[dict[str, Any]] = []

    calendar_objects: list[tuple[str, Any, str]] = []
    for series in RaceSeries.objects.filter(_marker_query("chinese_name")).order_by("id"):
        calendar_objects.append(
            ("series", series, series.canonical_name_original)
        )
    for event in RaceEvent.objects.filter(_marker_query("chinese_name")).order_by("id"):
        calendar_objects.append(("event", event, event.original_name))
    for kind, instance, original in calendar_objects:
        before_value = instance.chinese_name
        if not should_clean(original, before_value):
            kept.append(
                {
                    "kind": kind,
                    "id": instance.id,
                    "original": original,
                    "before": {"chineseName": before_value},
                    "reason": "original marker is not bracketed",
                }
            )
            continue
        if (instance.manual_lock_flags or {}).get("chinese_name"):
            locked.append(
                {
                    "kind": kind,
                    "id": instance.id,
                    "before": {"chineseName": before_value},
                    "manualLockFlags": instance.manual_lock_flags,
                }
            )
            continue
        after_value = clean_display_name(before_value)
        if not after_value or not _has_cjk(after_value) or contains_marker(after_value):
            review.append(
                {
                    "kind": kind,
                    "id": instance.id,
                    "before": {"chineseName": before_value},
                    "after": {"chineseName": after_value},
                    "reason": "cleaned name fails validation",
                }
            )
            continue
        actions.append(
            {
                "kind": kind,
                "id": instance.id,
                "before": {"chineseName": before_value},
                "after": {"chineseName": after_value},
                "beforeRow": {
                    "chinese_name": before_value,
                    "manual_lock_flags": instance.manual_lock_flags or {},
                },
            }
        )

    seen: set[tuple[str, str]] = set()
    deferred_review: list[dict[str, Any]] = []
    terms = (
        TermEntry.objects.filter(
            _marker_query("target_zh"), term_type="race", is_active=True
        )
        .order_by("racing_region", "id")
    )
    for term in terms:
        if not should_clean(term.source_ja, term.target_zh):
            kept.append(
                {
                    "kind": "term",
                    "id": term.id,
                    "region": term.racing_region,
                    "source": term.source_ja,
                    "before": {"targetZh": term.target_zh},
                    "reason": "original marker is not bracketed",
                }
            )
            continue
        cleaned = clean_display_name(term.target_zh)
        if not cleaned or not _has_cjk(cleaned) or contains_marker(cleaned):
            review.append(
                {
                    "kind": "term",
                    "id": term.id,
                    "region": term.racing_region,
                    "source": term.source_ja,
                    "before": {"targetZh": term.target_zh},
                    "after": {"targetZh": cleaned},
                    "reason": "cleaned name fails validation",
                }
            )
            continue
        key = (term.racing_region, cleaned)
        if key in seen:
            deferred_review.append(
                {
                    "kind": "term",
                    "id": term.id,
                    "region": term.racing_region,
                    "source": term.source_ja,
                    "before": {"targetZh": term.target_zh},
                    "after": {"targetZh": cleaned},
                    "reason": "same-region duplicate after cleanup",
                }
            )
            continue
        seen.add(key)
        actions.append(
            {
                "kind": "term",
                "id": term.id,
                "region": term.racing_region,
                "source": term.source_ja,
                "before": {"targetZh": term.target_zh},
                "after": {"targetZh": cleaned},
            }
        )
    review.extend(deferred_review)

    content = {
        "actions": actions,
        "review": review,
        "kept": kept,
        "locked": locked,
    }
    return {
        "schemaVersion": "race-name-handicap-cleanup-dry-run.v2",
        "generatedAt": timezone.now().isoformat().replace("+00:00", "Z"),
        "contentSha256": _sha256_json(content),
        "counts": {
            "autoClean": len(actions),
            "review": len(review),
            "kept": len(kept),
            "locked": len(locked),
        },
        **content,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def execute_commit(
    report: dict[str, Any],
    *,
    audit_context: dict[str, Any],
) -> dict[str, Any]:
    from stable.models import OperationLog, RaceEvent, RaceSeries, TermEntry

    if report.get("schemaVersion") != "race-name-handicap-cleanup-dry-run.v2":
        raise CleanupError("unsupported dry-run schema")
    locked_rows = report.get("locked") or []
    if locked_rows:
        raise CleanupError(
            f"manual lock targets must be resolved before commit: {locked_rows}"
        )
    actions = list(report.get("actions") or [])
    batch_id = str(report.get("contentSha256") or "")[:64]
    if not batch_id:
        raise CleanupError("dry-run artifact is missing contentSha256")

    model_by_kind = {"series": RaceSeries, "event": RaceEvent, "term": TermEntry}
    field_by_kind = {
        "series": "chinese_name",
        "event": "chinese_name",
        "term": "target_zh",
    }
    name_key_by_kind = {
        "series": "chineseName",
        "event": "chineseName",
        "term": "targetZh",
    }

    with transaction.atomic():
        existing = OperationLog.objects.filter(
            action_type="race_name_handicap_markers_removed",
            target_type="race_name_handicap_cleanup_batch",
            target_id=batch_id,
        )
        if existing.exists():
            raise CleanupError(f"batch already applied: {batch_id}")
        locked_instances: dict[tuple[str, int], Any] = {}
        for kind, model in model_by_kind.items():
            ids = sorted(int(row["id"]) for row in actions if row["kind"] == kind)
            found = list(model.objects.select_for_update().filter(id__in=ids))
            by_id = {row.id: row for row in found}
            if sorted(by_id) != ids:
                raise CleanupError(f"{kind} target set changed since dry-run")
            for object_id, instance in by_id.items():
                locked_instances[(kind, object_id)] = instance
        for row in actions:
            kind = row["kind"]
            instance = locked_instances[(kind, int(row["id"]))]
            field = field_by_kind[kind]
            name_key = name_key_by_kind[kind]
            if getattr(instance, field) != row["before"][name_key]:
                raise CleanupError(
                    f"before CAS mismatch: {kind} id={row['id']}"
                )
            if kind in {"series", "event"}:
                flags = (instance.manual_lock_flags or {}).get("chinese_name")
                expected_flags = (row.get("beforeRow") or {}).get("manual_lock_flags") or {}
                if (instance.manual_lock_flags or {}) != expected_flags:
                    raise CleanupError(
                        f"manual lock flags CAS mismatch: {kind} id={row['id']}"
                    )
                if flags:
                    raise CleanupError(f"manual lock: {kind} id={row['id']}")
        applied_at = timezone.now()
        for row in actions:
            kind = row["kind"]
            instance = locked_instances[(kind, int(row["id"]))]
            field = field_by_kind[kind]
            setattr(instance, field, row["after"][name_key_by_kind[kind]])
            instance.updated_at = applied_at
        for kind, model in model_by_kind.items():
            instances = [
                locked_instances[(k, object_id)]
                for (k, object_id) in sorted(locked_instances)
                if k == kind
            ]
            if instances:
                model.objects.bulk_update(
                    instances, [field_by_kind[kind], "updated_at"], batch_size=500
                )
        detail = {
            "schemaVersion": "race-name-handicap-cleanup-operation-log.v1",
            "artifactSha256": audit_context.get("artifactSha256", ""),
            "backupSha256": audit_context.get("backupSha256", ""),
            "backupSizeBytes": audit_context.get("backupSizeBytes", 0),
            "operator": audit_context.get("operator", ""),
            "authorizationRef": audit_context.get("authorizationRef", ""),
            "authorizationTime": audit_context.get("authorizationTime", ""),
            "counts": {
                "autoClean": len(actions),
                "review": len(report.get("review") or []),
                "kept": len(report.get("kept") or []),
                "locked": len(locked_rows),
            },
            "appliedAt": applied_at.isoformat().replace("+00:00", "Z"),
        }
        OperationLog.objects.create(
            admin=None,
            action_type="race_name_handicap_markers_removed",
            target_type="race_name_handicap_cleanup_batch",
            target_id=batch_id,
            detail=_canonical_json(detail),
        )
    return {
        "mode": "commit",
        "batchId": batch_id,
        "written": len(actions),
    }


def verify_applied(report: dict[str, Any]) -> dict[str, Any]:
    from stable.models import RaceEvent, RaceSeries, TermEntry

    model_by_kind = {"series": RaceSeries, "event": RaceEvent, "term": TermEntry}
    field_by_kind = {
        "series": "chinese_name",
        "event": "chinese_name",
        "term": "target_zh",
    }
    name_key_by_kind = {
        "series": "chineseName",
        "event": "chineseName",
        "term": "targetZh",
    }
    for row in report.get("actions") or []:
        kind = row["kind"]
        instance = model_by_kind[kind].objects.get(id=int(row["id"]))
        expected = row["after"][name_key_by_kind[kind]]
        actual = getattr(instance, field_by_kind[kind])
        if actual != expected:
            raise CleanupError(
                f"verify failed: {kind} id={row['id']} expected={expected!r} actual={actual!r}"
            )
        if contains_marker(actual):
            raise CleanupError(f"verify failed: marker remains at {kind} id={row['id']}")
    for bucket in ("kept", "review"):
        for row in report.get(bucket) or []:
            kind = row["kind"]
            instance = model_by_kind[kind].objects.get(id=int(row["id"]))
            expected = row["before"][name_key_by_kind[kind]]
            actual = getattr(instance, field_by_kind[kind])
            if actual != expected:
                raise CleanupError(
                    f"verify failed: {bucket} object changed: {kind} id={row['id']}"
                )
    return {
        "ok": True,
        "written": len(report.get("actions") or []),
        "kept": len(report.get("kept") or []),
        "review": len(report.get("review") or []),
    }
