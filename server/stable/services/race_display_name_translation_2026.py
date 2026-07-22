"""2026 赛历赛事中文展示名补齐服务（一次性批次）。

规则见 docs/changes/translate-2026-race-display-names/（方案已 APPROVED）：

- 目标集：RaceEvent visibility_status=published、year=2026、chinese_name 非空且不含 CJK。
- 规范化键：lowercase 后去 [^a-z0-9]；空键（如纯假名名）不参与匹配。
- 冠名剥离（保守）：尾缀 [...] 括号段、Presented by ... 起至结尾一律可剥；
  前缀只剥显式名单；剥离结果为空或等于原名视为未剥离。
- 候选分级（逐级命中即停）：L0 系列中文名继承 -> L1 术语库 -> L2 历史译名
  （先全名后去冠名基名）-> L3 needs_translation（候选留空，人工/Claude 填写）。
- 让赛守卫与去让赛 change 同语义：原文去括号标记后仍含 handicap 词或四种中文
  让赛标记 -> manual；候选含四种让赛标记 -> manual。
- manual_lock_flags.chinese_name 锁定 -> manual 桶（导出即拦截），commit 硬拒绝。

写入骨架（SHA/canonical-json、manifest 校验、单事务 CAS、OperationLog 幂等、
bulk_update、verify）整份 fork 自已上线的去让赛模块 race_name_handicap_cleanup
（design F-008：一次性批次接受 fork 而不抽公共模块，批次完成后随 change 归档）。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from django.db import transaction
from django.utils import timezone

TARGET_YEAR = 2026

DRY_RUN_SCHEMA = "race-display-name-translation-2026-dry-run.v1"
MANIFEST_SCHEMA = "race-display-name-translation-2026-manifest.v1"
OPERATION_LOG_SCHEMA = "race-display-name-translation-2026-operation-log.v1"
OPERATION_ACTION_TYPE = "race_display_name_translation_2026_applied"
OPERATION_TARGET_TYPE = "race_display_name_translation_2026_batch"

HANDICAP_MARKERS = ("让赛", "讓賽", "让步赛", "讓步賽")

# 冠名前缀显式名单：来自 573 场目标赛事 2026-07-22 实际盘点（design.md 匹配规则 2），
# 随 artifact 公示；名单外前缀一律不剥（如 Jane Seymour 为人名非冠名）。
# 匹配大小写不敏感（BetMGM/Betmgm 同源），按长度降序排列保证长前缀优先。
SPONSOR_PREFIXES = (
    "Dornan Engineering",
    "William Hill",
    "Trustatrader",
    "Virgin Bet",
    "Sky Bet",
    "Betfair",
    "BetMGM",
    "Unibet",
    "Coral",
    "JCB",
    "AIS",
    "SBK",
)

REVIEW_CSV_HEADER = [
    "bucket",
    "id",
    "region",
    "original_name",
    "before",
    "level",
    "matched_on",
    "suggested_name",
    "reason",
    "final_name",
]

# 审核工作簿 decision 列取值（可选列；strip+lower 后比较，中文值不受 lower 影响）。
# 否决类值与非空且不等于 before 的 final_name 同时出现属矛盾，manifest 构建硬拒绝，
# 防止用户标了否决却未清空 final_name 导致静默写入。
VETO_DECISIONS = frozenset(
    {"veto", "reject", "keep", "否决", "保持", "保持原值", "不通过", "ng"}
)
APPROVE_DECISIONS = frozenset(
    {"approve", "approved", "ok", "yes", "通过", "确认", ""}
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]")
_CJK_RE = re.compile(r"[一-鿿]")
_TRAILING_BRACKET_RE = re.compile(r"\s*\[[^\]]*\]\s*$")
_PRESENTED_BY_RE = re.compile(r"\s+presented\s+by\s.*$", re.IGNORECASE)
_BRACKETED_ORIGINAL_MARKER_RE = re.compile(
    r"[（(]\s*(?:handicap|h|让赛|讓賽|让步赛|讓步賽)\s*[）)]",
    re.IGNORECASE,
)
_UNBRACKETED_HANDICAP_WORD_RE = re.compile(r"\bhandicap\b", re.IGNORECASE)
_UNBRACKETED_HCAP_RE = re.compile(r"h['’]?cap\b", re.IGNORECASE)
_UNBRACKETED_BARE_H_RE = re.compile(r"(?:^|\s)h\.?(?=\s|$)", re.IGNORECASE)


class TranslationError(RuntimeError):
    pass


def normalize_key(value: str) -> str:
    """规范化匹配键：lowercase 后去除 [^a-z0-9]；纯假名/中文名归为空键。"""
    return _NON_ALNUM_RE.sub("", (value or "").lower())


def has_cjk(value: str) -> bool:
    return bool(_CJK_RE.search(value or ""))


def contains_handicap_marker(value: str) -> bool:
    return any(marker in (value or "") for marker in HANDICAP_MARKERS)


def has_unbracketed_handicap_marker(original: str) -> bool:
    """原文去括号标记后是否仍含 handicap 词或四种中文让赛标记（去让赛同语义）。"""
    remainder = _BRACKETED_ORIGINAL_MARKER_RE.sub("", original or "")
    if _UNBRACKETED_HANDICAP_WORD_RE.search(remainder):
        return True
    return contains_handicap_marker(remainder)


def _has_unbracketed_handicap_indicator(original: str) -> bool:
    """原文的未括号让赛指标 = 去让赛 has_unbracketed_marker_in_original 的超集。

    在其判定（去括号后 \\bhandicap\\b 与四种中文标记）之上，额外识别英文缩写
    形式 H'Cap/H’Cap/HCap（大小写不敏感）与边界处的裸 H/H. 缩写。语义：此类原文
    的让赛标记是赛事名组成部分（去让赛锁定规则：未括号 = 保留，先例 两岁马让赛
    kept），因此对应的中文定稿名可保留「让赛」——build_manifest 让赛标记校验的
    唯一放行例外（用户裁决 id 666：Betvictor EBF Nov. H’Cap Hurdle → 新手让赛跨栏锦标）。
    """
    remainder = _BRACKETED_ORIGINAL_MARKER_RE.sub("", original or "")
    return bool(
        _UNBRACKETED_HANDICAP_WORD_RE.search(remainder)
        or _UNBRACKETED_HCAP_RE.search(remainder)
        or _UNBRACKETED_BARE_H_RE.search(remainder)
        or contains_handicap_marker(remainder)
    )


def strip_sponsor(name: str) -> tuple[str, bool]:
    """保守冠名剥离：返回 (基名, 是否剥离)。

    - 尾缀 [...] 括号段、Presented by ...（大小写不敏感）起至结尾一律可剥；
    - 前缀只剥 SPONSOR_PREFIXES 显式名单；
    - 剥离结果为空或等于原名视为未剥离。
    """
    original = (name or "").strip()
    current = original
    while True:
        stripped = _TRAILING_BRACKET_RE.sub("", current)
        stripped = _PRESENTED_BY_RE.sub("", stripped).rstrip()
        if stripped == current:
            break
        current = stripped
    lowered = current.lower()
    for prefix in SPONSOR_PREFIXES:
        head = prefix.lower()
        if (
            lowered.startswith(head)
            and len(current) > len(prefix)
            and current[len(prefix)].isspace()
        ):
            current = current[len(prefix):].lstrip()
            break
    current = current.strip()
    if not current or current == original:
        return original, False
    return current, True


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _target_events() -> list[Any]:
    from stable.models import RaceEvent

    events = (
        RaceEvent.objects.filter(
            visibility_status="published", year=TARGET_YEAR
        )
        .exclude(chinese_name="")
        .select_related("race_series")
        .order_by("id")
    )
    return [event for event in events if not has_cjk(event.chinese_name)]


def _build_term_index() -> dict[str, dict[str, Any]]:
    from stable.models import TermEntry

    index: dict[str, dict[str, Any]] = {}
    terms = (
        TermEntry.objects.filter(
            term_type="race",
            is_active=True,
            translation_status="translated",
        )
        .exclude(target_zh="")
        .order_by("id")
    )
    for term in terms:
        aliases = term.aliases_ja if isinstance(term.aliases_ja, list) else []
        for text in [term.source_ja, *aliases]:
            key = normalize_key(text)
            if not key:
                continue
            entry = index.setdefault(key, {"values": set(), "sources": []})
            entry["values"].add(term.target_zh)
            entry["sources"].append(text)
    return index


def _build_history_index() -> dict[str, dict[str, Any]]:
    from stable.models import RaceEvent

    index: dict[str, dict[str, Any]] = {}
    events = (
        RaceEvent.objects.filter(visibility_status="published")
        .exclude(year=TARGET_YEAR)
        .exclude(chinese_name="")
        .order_by("id")
    )
    for event in events:
        if not has_cjk(event.chinese_name):
            continue
        key = normalize_key(event.original_name)
        if not key:
            continue
        entry = index.setdefault(key, {"values": set(), "sources": []})
        entry["values"].add(event.chinese_name)
        entry["sources"].append(event.original_name)
    return index


def _classify_event(
    event: Any,
    term_index: dict[str, dict[str, Any]],
    history_index: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """单场分桶：返回 (bucket, row)，bucket ∈ {candidates, manual}。"""
    base = {
        "id": event.id,
        "region": event.country_region,
        "originalName": event.original_name,
        "before": event.chinese_name,
        "beforeRow": {
            "chinese_name": event.chinese_name,
            "manual_lock_flags": event.manual_lock_flags or {},
        },
    }
    if (event.manual_lock_flags or {}).get("chinese_name"):
        return "manual", {**base, "reason": "manual lock: chinese_name"}
    if has_unbracketed_handicap_marker(event.original_name):
        return "manual", {
            **base,
            "reason": "unbracketed handicap marker in original",
        }

    base_name, stripped = strip_sponsor(event.original_name)
    keys: list[str] = []
    full_key = normalize_key(event.original_name)
    if full_key:
        keys.append(full_key)
    if stripped:
        base_key = normalize_key(base_name)
        if base_key and base_key not in keys:
            keys.append(base_key)

    # L0 系列中文名继承
    series = event.race_series
    if series is not None and has_cjk(series.chinese_name):
        if contains_handicap_marker(series.chinese_name):
            return "manual", {
                **base,
                "level": "series",
                "matchedOn": series.canonical_name_original,
                "reason": "series candidate contains handicap marker",
            }
        return "candidates", {
            **base,
            "level": "series",
            "matchedOn": series.canonical_name_original,
            "suggestedName": series.chinese_name,
        }

    # L1 / L2 共用查找：先全名后去冠名基名；同键多译名歧义转人工。
    for level, index, label in (
        ("term", term_index, "term"),
        ("history", history_index, "history"),
    ):
        for key in keys:
            hit = index.get(key)
            if not hit:
                continue
            matched_on = "; ".join(sorted(set(hit["sources"])))
            values = hit["values"]
            if len(values) > 1:
                return "manual", {
                    **base,
                    "level": level,
                    "matchedOn": matched_on,
                    "reason": f"ambiguous {label} translations",
                }
            candidate = next(iter(values))
            if contains_handicap_marker(candidate):
                return "manual", {
                    **base,
                    "level": level,
                    "matchedOn": matched_on,
                    "reason": f"{label} candidate contains handicap marker",
                }
            return "candidates", {
                **base,
                "level": level,
                "matchedOn": matched_on,
                "suggestedName": candidate,
            }

    # L3 needs_translation：候选留空，由后续人工/Claude 填写。
    return "candidates", {
        **base,
        "level": "needs_translation",
        "matchedOn": "",
        "suggestedName": "",
    }


def build_dry_run() -> dict[str, Any]:
    term_index = _build_term_index()
    history_index = _build_history_index()
    candidates: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    for event in _target_events():
        bucket, row = _classify_event(event, term_index, history_index)
        (candidates if bucket == "candidates" else manual).append(row)
    levels: dict[str, int] = {}
    for row in candidates:
        levels[row["level"]] = levels.get(row["level"], 0) + 1
    content = {"candidates": candidates, "manual": manual}
    return {
        "schemaVersion": DRY_RUN_SCHEMA,
        "generatedAt": timezone.now().isoformat().replace("+00:00", "Z"),
        "contentSha256": _sha256_json(content),
        "counts": {
            "candidates": len(candidates),
            "manual": len(manual),
            "total": len(candidates) + len(manual),
            "levels": levels,
        },
        **content,
    }


def build_manifest(reviewed_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """从用户定稿 CSV 行 + 当前库内 before（生产只读导出等价物）构建 manifest。

    校验：行数、id 集合、before 一致；写入值非空含 CJK 且无让赛标记；
    锁定事件拒绝写入。final_name 为空或等于 before 的行记为 veto（保持原值）。
    """
    targets = {event.id: event for event in _target_events()}
    rows = list(reviewed_rows)
    if len(rows) != len(targets):
        raise TranslationError(
            f"reviewed row count mismatch: {len(rows)} != {len(targets)}"
        )
    ids = [int(row["id"]) for row in rows]
    if set(ids) != set(targets):
        raise TranslationError("reviewed id set mismatch with target export")
    actions: list[dict[str, Any]] = []
    veto: list[dict[str, Any]] = []
    for row in rows:
        event = targets[int(row["id"])]
        before = event.chinese_name
        if (row.get("before") or "") != before:
            raise TranslationError(f"before drift: event id={event.id}")
        before_row = {
            "chinese_name": before,
            "manual_lock_flags": event.manual_lock_flags or {},
        }
        final = (row.get("final_name") or "").strip()
        decision = (row.get("decision") or "").strip().lower()
        if decision in VETO_DECISIONS and final and final != before:
            raise TranslationError(
                f"decision/final_name conflict: event id={event.id} "
                f"decision={row.get('decision')!r} final_name={row.get('final_name')!r}"
            )
        if not final or final == before:
            veto.append(
                {
                    "id": event.id,
                    "before": {"chineseName": before},
                    "beforeRow": before_row,
                }
            )
            continue
        if (event.manual_lock_flags or {}).get("chinese_name"):
            raise TranslationError(f"manual lock: event id={event.id}")
        if not has_cjk(final):
            raise TranslationError(f"final name has no CJK: event id={event.id}")
        if contains_handicap_marker(final):
            # 例外：原文让赛标记为赛事名组成部分（未括号 handicap/H'Cap/裸 H），
            # 按去让赛锁定规则中文名可保留「让赛」；否则维持拒绝。
            if not _has_unbracketed_handicap_indicator(event.original_name):
                raise TranslationError(
                    f"final name contains handicap marker: event id={event.id}"
                )
        actions.append(
            {
                "id": event.id,
                "before": {"chineseName": before},
                "after": {"chineseName": final},
                "beforeRow": before_row,
            }
        )
    content = {"actions": actions, "veto": veto}
    return {
        "schemaVersion": MANIFEST_SCHEMA,
        "generatedAt": timezone.now().isoformat().replace("+00:00", "Z"),
        "contentSha256": _sha256_json(content),
        "counts": {
            "written": len(actions),
            "veto": len(veto),
            "total": len(actions) + len(veto),
        },
        **content,
    }


def execute_commit(
    manifest: dict[str, Any],
    *,
    audit_context: dict[str, Any],
) -> dict[str, Any]:
    from stable.models import OperationLog, RaceEvent

    if manifest.get("schemaVersion") != MANIFEST_SCHEMA:
        raise TranslationError("unsupported manifest schema")
    actions = list(manifest.get("actions") or [])
    batch_id = str(manifest.get("contentSha256") or "")[:64]
    if not batch_id:
        raise TranslationError("manifest is missing contentSha256")

    with transaction.atomic():
        existing = OperationLog.objects.filter(
            action_type=OPERATION_ACTION_TYPE,
            target_type=OPERATION_TARGET_TYPE,
            target_id=batch_id,
        )
        if existing.exists():
            raise TranslationError(f"batch already applied: {batch_id}")
        ids = sorted(int(row["id"]) for row in actions)
        found = list(RaceEvent.objects.select_for_update().filter(id__in=ids))
        by_id = {row.id: row for row in found}
        if sorted(by_id) != ids:
            raise TranslationError("target set changed since manifest")
        for row in actions:
            instance = by_id[int(row["id"])]
            if instance.chinese_name != row["before"]["chineseName"]:
                raise TranslationError(f"before CAS mismatch: event id={row['id']}")
            expected_flags = (row.get("beforeRow") or {}).get("manual_lock_flags") or {}
            if (instance.manual_lock_flags or {}) != expected_flags:
                raise TranslationError(
                    f"manual lock flags CAS mismatch: event id={row['id']}"
                )
            if (instance.manual_lock_flags or {}).get("chinese_name"):
                raise TranslationError(f"manual lock: event id={row['id']}")
        applied_at = timezone.now()
        for row in actions:
            instance = by_id[int(row["id"])]
            instance.chinese_name = row["after"]["chineseName"]
            instance.updated_at = applied_at
        if actions:
            # RaceEvent.save() 会在 update_fields 强制附加 slug/series_key
            # （models.py 1095-1106），写入只允许 bulk_update 这两列。
            RaceEvent.objects.bulk_update(
                [by_id[int(row["id"])] for row in actions],
                ["chinese_name", "updated_at"],
                batch_size=500,
            )
        detail = {
            "schemaVersion": OPERATION_LOG_SCHEMA,
            "artifactSha256": audit_context.get("artifactSha256", ""),
            "backupSha256": audit_context.get("backupSha256", ""),
            "backupSizeBytes": audit_context.get("backupSizeBytes", 0),
            "operator": audit_context.get("operator", ""),
            "authorizationRef": audit_context.get("authorizationRef", ""),
            "authorizationTime": audit_context.get("authorizationTime", ""),
            "counts": {
                "written": len(actions),
                "veto": len(manifest.get("veto") or []),
            },
            "appliedAt": applied_at.isoformat().replace("+00:00", "Z"),
        }
        OperationLog.objects.create(
            admin=None,
            action_type=OPERATION_ACTION_TYPE,
            target_type=OPERATION_TARGET_TYPE,
            target_id=batch_id,
            detail=_canonical_json(detail),
        )
    return {
        "mode": "commit",
        "batchId": batch_id,
        "written": len(actions),
    }


def verify_applied(manifest: dict[str, Any]) -> dict[str, Any]:
    from stable.models import RaceEvent

    if manifest.get("schemaVersion") != MANIFEST_SCHEMA:
        raise TranslationError("unsupported manifest schema")
    actions = list(manifest.get("actions") or [])
    veto = list(manifest.get("veto") or [])
    for row in actions:
        instance = RaceEvent.objects.get(id=int(row["id"]))
        expected = row["after"]["chineseName"]
        actual = instance.chinese_name
        if actual != expected:
            raise TranslationError(
                f"verify failed: event id={row['id']} expected={expected!r} actual={actual!r}"
            )
        if contains_handicap_marker(actual):
            # 与 build_manifest 同一例外：原文让赛标记为赛事名组成部分
            # （未括号 handicap/H'Cap/裸 H）时，写入值可保留「让赛」。
            if not _has_unbracketed_handicap_indicator(instance.original_name):
                raise TranslationError(
                    f"verify failed: handicap marker remains at event id={row['id']}"
                )
        if not has_cjk(actual):
            raise TranslationError(
                f"verify failed: written value has no CJK at event id={row['id']}"
            )
    for row in veto:
        instance = RaceEvent.objects.get(id=int(row["id"]))
        expected = row["before"]["chineseName"]
        actual = instance.chinese_name
        if actual != expected:
            raise TranslationError(
                f"verify failed: veto object changed: event id={row['id']}"
            )
    return {
        "ok": True,
        "written": len(actions),
        "veto": len(veto),
    }
