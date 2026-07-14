from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from stable.models import SourceLanguage

from .terms import ArticleEntityResolution


_SEX_TARGETS = {
    "牡": "公马",
    "牝": "母马",
    "騸": "阉马",
    "せん": "阉马",
}

_YEARLING_INSIDE_SEX_RE = re.compile(
    r"[「『](?P<mare>[^「」『』\r\n]{1,80}?)の(?P<year>20\d{2})"
    r"[（(](?P<sex>牡|牝|騸|せん)(?:[、,][ \t　]*(?:父)?(?P<sire>[^()（）「」『』\r\n]{1,80}?))?[）)]"
    r"[」』]"
)
_YEARLING_OUTSIDE_SEX_RE = re.compile(
    r"[「『](?P<mare>[^「」『』\r\n]{1,80}?)の(?P<year>20\d{2})[」』]"
    r"(?:[（(](?P<sex>牡|牝|騸|せん)(?:[、,][ \t　]*(?:父)?(?P<sire>[^()（）「」『』\r\n]{1,80}?))?[）)])?"
)
_WORKOUT_RE = re.compile(
    r"(?P<furlongs>\d+)ハロン(?P<total_whole>\d+)秒(?P<total_tenth>\d+)"
    r"[―ー\-–—](?P<last_whole>\d+)秒(?P<last_tenth>\d+)"
)
_INTERVIEW_RE = re.compile(
    r"(?m)(?P<prefix>^[ \t　]*)"
    r"(?P<jockey>[一-龥々〆ヵヶぁ-んァ-ヴーA-Za-z・･ \t　]{2,40}?)騎手"
    r"[（(](?P<horse>[^=＝()（）\r\n]{1,80}?)[=＝](?P<finish>\d+着)[）)]"
)
_UNDECIDED_JOCKEY_RE = re.compile(
    r"(?m)(?P<row>^[^\r\n]*[ァ-ヴー]{3,}[^\r\n]*?)(?P<spacing>[ \t　]+)○○(?=[ \t　]*$)"
)
_FORMAT_PLACEHOLDER_RE = re.compile(r"__UMA_FORMAT_\d+__")
_SEED_TERM_PLACEHOLDER_RE = re.compile(r"__UMA_SEED_\d+__")
_SEED_TERM_MARKER = "japanese_racing_translation_seed"


@dataclass(frozen=True)
class JapaneseFormatItem:
    placeholder: str
    rule: str
    field_name: str
    source_text: str
    target_text: str
    start: int
    end: int
    consumed_entity_keys: tuple[tuple[str, int, int], ...] = ()

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["consumed_entity_keys"] = [list(item) for item in self.consumed_entity_keys]
        return payload


@dataclass(frozen=True)
class JapaneseFormatPlan:
    protected_title: str
    protected_body: str
    items: tuple[JapaneseFormatItem, ...] = ()

    @property
    def consumed_entity_keys(self) -> set[tuple[str, int, int]]:
        return {
            key
            for item in self.items
            for key in item.consumed_entity_keys
        }

    def as_dicts(self) -> list[dict]:
        return [item.as_dict() for item in self.items]


@dataclass(frozen=True)
class JapaneseSeedTermItem:
    placeholder: str
    field_name: str
    source_text: str
    target_text: str
    start: int
    end: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class JapaneseSeedTermPlan:
    protected_title: str
    protected_body: str
    items: tuple[JapaneseSeedTermItem, ...] = ()

    @property
    def consumed_entity_keys(self) -> set[tuple[str, int, int]]:
        return {(item.field_name, item.start, item.end) for item in self.items}

    def as_dicts(self) -> list[dict]:
        return [item.as_dict() for item in self.items]


@dataclass(frozen=True)
class _FormatCandidate:
    rule: str
    field_name: str
    start: int
    end: int
    source_text: str
    target_text: str
    consumed_entity_keys: tuple[tuple[str, int, int], ...] = field(default_factory=tuple)
    priority: int = 0


def _exact_entity_target(
    resolution: ArticleEntityResolution,
    *,
    field_name: str,
    start: int,
    end: int,
    source_text: str,
) -> str:
    for entity in resolution.entities:
        if (
            entity.field_name == field_name
            and entity.start == start
            and entity.end == end
            and entity.matched_text == source_text
            and entity.entity_type in {"horse", "person"}
            and (entity.target_zh or "").strip()
        ):
            return entity.target_zh.strip()
    return source_text


def _consumed_entity_keys(
    resolution: ArticleEntityResolution,
    *,
    field_name: str,
    start: int,
    end: int,
) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        sorted(
            {
                (entity.field_name, entity.start, entity.end)
                for entity in resolution.entities
                if entity.field_name == field_name and entity.start >= start and entity.end <= end
            }
        )
    )


def _yearling_candidate(
    text: str,
    match: re.Match,
    *,
    field_name: str,
    resolution: ArticleEntityResolution,
) -> _FormatCandidate:
    mare = match.group("mare")
    mare_target = _exact_entity_target(
        resolution,
        field_name=field_name,
        start=match.start("mare"),
        end=match.end("mare"),
        source_text=mare,
    )
    target = f"「{mare_target}{match.group('year')}」"
    sex = match.groupdict().get("sex")
    sire = (match.groupdict().get("sire") or "").strip()
    if sex:
        details = [_SEX_TARGETS[sex]]
        if sire:
            sire_start = match.start("sire")
            leading = len(match.group("sire")) - len(match.group("sire").lstrip())
            sire_start += leading
            sire_target = _exact_entity_target(
                resolution,
                field_name=field_name,
                start=sire_start,
                end=sire_start + len(sire),
                source_text=sire,
            )
            details.append(f"父{sire_target}")
        target += f"（{'，'.join(details)}）"
    return _FormatCandidate(
        rule="yearling_lot",
        field_name=field_name,
        start=match.start(),
        end=match.end(),
        source_text=match.group(),
        target_text=target,
        consumed_entity_keys=_consumed_entity_keys(
            resolution,
            field_name=field_name,
            start=match.start(),
            end=match.end(),
        ),
        priority=100,
    )


def _collect_candidates(
    text: str,
    *,
    field_name: str,
    resolution: ArticleEntityResolution,
) -> list[_FormatCandidate]:
    candidates: list[_FormatCandidate] = []
    for pattern in (_YEARLING_INSIDE_SEX_RE, _YEARLING_OUTSIDE_SEX_RE):
        for match in pattern.finditer(text):
            candidates.append(
                _yearling_candidate(text, match, field_name=field_name, resolution=resolution)
            )
    for match in _WORKOUT_RE.finditer(text):
        candidates.append(
            _FormatCandidate(
                rule="workout_time",
                field_name=field_name,
                start=match.start(),
                end=match.end(),
                source_text=match.group(),
                target_text=(
                    f"{match.group('furlongs')}F "
                    f"{match.group('total_whole')}.{match.group('total_tenth')}，末脚 "
                    f"{match.group('last_whole')}.{match.group('last_tenth')}"
                ),
                priority=80,
            )
        )
    for match in _INTERVIEW_RE.finditer(text):
        jockey = match.group("jockey").strip()
        horse = match.group("horse").strip()
        jockey_start = match.start("jockey") + (len(match.group("jockey")) - len(match.group("jockey").lstrip()))
        horse_start = match.start("horse") + (len(match.group("horse")) - len(match.group("horse").lstrip()))
        jockey_target = _exact_entity_target(
            resolution,
            field_name=field_name,
            start=jockey_start,
            end=jockey_start + len(jockey),
            source_text=jockey,
        )
        horse_target = _exact_entity_target(
            resolution,
            field_name=field_name,
            start=horse_start,
            end=horse_start + len(horse),
            source_text=horse,
        )
        candidates.append(
            _FormatCandidate(
                rule="post_race_interview",
                field_name=field_name,
                start=match.start(),
                end=match.end(),
                source_text=match.group(),
                target_text=(
                    f"{match.group('prefix')}{jockey_target}骑手"
                    f"({match.group('finish')} {horse_target})"
                ),
                consumed_entity_keys=_consumed_entity_keys(
                    resolution,
                    field_name=field_name,
                    start=match.start(),
                    end=match.end(),
                ),
                priority=70,
            )
        )
    for match in _UNDECIDED_JOCKEY_RE.finditer(text):
        candidates.append(
            _FormatCandidate(
                rule="undecided_jockey",
                field_name=field_name,
                start=match.end("spacing"),
                end=match.end(),
                source_text="○○",
                target_text="骑手未定",
                priority=60,
            )
        )
    return candidates


def _select_non_overlapping(candidates: list[_FormatCandidate]) -> list[_FormatCandidate]:
    selected: list[_FormatCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (item.start, -item.end, -item.priority, item.rule)):
        if any(candidate.start < current.end and candidate.end > current.start for current in selected):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: item.start)


def _apply_field_placeholders(text: str, items: list[JapaneseFormatItem]) -> str:
    protected = text or ""
    for item in sorted(items, key=lambda current: current.start, reverse=True):
        protected = protected[: item.start] + item.placeholder + protected[item.end :]
    return protected


def build_japanese_format_plan(
    title_text: str,
    body_text: str,
    resolution: ArticleEntityResolution,
) -> JapaneseFormatPlan:
    title = title_text or ""
    body = body_text or ""
    if resolution.source_language != SourceLanguage.JAPANESE:
        return JapaneseFormatPlan(title, body)

    selected_by_field = {
        "title": _select_non_overlapping(
            _collect_candidates(title, field_name="title", resolution=resolution)
        ),
        "body": _select_non_overlapping(
            _collect_candidates(body, field_name="body", resolution=resolution)
        ),
    }
    items: list[JapaneseFormatItem] = []
    index = 1
    for field_name in ("title", "body"):
        for candidate in selected_by_field[field_name]:
            items.append(
                JapaneseFormatItem(
                    placeholder=f"__UMA_FORMAT_{index}__",
                    rule=candidate.rule,
                    field_name=candidate.field_name,
                    source_text=candidate.source_text,
                    target_text=candidate.target_text,
                    start=candidate.start,
                    end=candidate.end,
                    consumed_entity_keys=candidate.consumed_entity_keys,
                )
            )
            index += 1
    title_items = [item for item in items if item.field_name == "title"]
    body_items = [item for item in items if item.field_name == "body"]
    return JapaneseFormatPlan(
        protected_title=_apply_field_placeholders(title, title_items),
        protected_body=_apply_field_placeholders(body, body_items),
        items=tuple(items),
    )


def japanese_format_placeholder_violations(
    title_zh: str,
    body_zh: str,
    plan: JapaneseFormatPlan,
) -> list[dict]:
    values = {"title": title_zh or "", "body": body_zh or ""}
    expected = {
        field_name: {
            item.placeholder
            for item in plan.items
            if item.field_name == field_name
        }
        for field_name in values
    }
    violations: list[dict] = []
    for field_name, value in values.items():
        observed = _FORMAT_PLACEHOLDER_RE.findall(value)
        for placeholder in sorted(set(observed) | expected[field_name]):
            count = observed.count(placeholder)
            if placeholder not in expected[field_name]:
                reason = "wrong_or_unexpected_field"
            elif count == 0:
                reason = "missing"
            elif count > 1:
                reason = "duplicated"
            else:
                continue
            violations.append(
                {
                    "placeholder": placeholder,
                    "field_name": field_name,
                    "reason": reason,
                    "count": count,
                }
            )
    return violations


def restore_japanese_format_placeholders(
    text: str,
    plan: JapaneseFormatPlan,
    *,
    field_name: str | None = None,
) -> str:
    restored = text or ""
    for item in plan.items:
        if field_name is None or item.field_name == field_name:
            restored = restored.replace(item.placeholder, item.target_text)
    return restored


def build_japanese_seed_term_plan(
    title_text: str,
    body_text: str,
    resolution: ArticleEntityResolution,
    format_plan: JapaneseFormatPlan,
) -> JapaneseSeedTermPlan:
    seeded_terms = {
        (term.matched_text.casefold(), term.target_zh)
        for term in resolution.accepted_terms
        if _SEED_TERM_MARKER in (term.notes or "").casefold()
        and (term.matched_text or "").strip()
        and (term.target_zh or "").strip()
    }
    format_spans = {
        field_name: [(item.start, item.end) for item in format_plan.items if item.field_name == field_name]
        for field_name in ("title", "body")
    }
    candidates = []
    for entity in resolution.entities:
        if (entity.matched_text.casefold(), entity.target_zh) not in seeded_terms:
            continue
        if any(entity.start < end and entity.end > start for start, end in format_spans[entity.field_name]):
            continue
        candidates.append(entity)

    selected = []
    for entity in sorted(
        candidates,
        key=lambda item: (
            0 if item.field_name == "title" else 1,
            item.start,
            -item.end,
            -item.priority,
        ),
    ):
        if any(
            entity.field_name == current.field_name
            and entity.start < current.end
            and entity.end > current.start
            for current in selected
        ):
            continue
        selected.append(entity)

    items = tuple(
        JapaneseSeedTermItem(
            placeholder=f"__UMA_SEED_{index}__",
            field_name=entity.field_name,
            source_text=entity.matched_text,
            target_text=entity.target_zh,
            start=entity.start,
            end=entity.end,
        )
        for index, entity in enumerate(
            sorted(
                selected,
                key=lambda item: (0 if item.field_name == "title" else 1, item.start, -item.end),
            ),
            start=1,
        )
    )

    def protect(field_name: str, text: str) -> str:
        replacements = [
            (item.start, item.end, item.placeholder)
            for item in format_plan.items
            if item.field_name == field_name
        ]
        replacements.extend(
            (item.start, item.end, item.placeholder)
            for item in items
            if item.field_name == field_name
        )
        protected = text or ""
        for start, end, placeholder in sorted(replacements, reverse=True):
            protected = protected[:start] + placeholder + protected[end:]
        return protected

    return JapaneseSeedTermPlan(
        protected_title=protect("title", title_text or ""),
        protected_body=protect("body", body_text or ""),
        items=items,
    )


def japanese_seed_term_placeholder_violations(
    title_zh: str,
    body_zh: str,
    plan: JapaneseSeedTermPlan,
) -> list[dict]:
    values = {"title": title_zh or "", "body": body_zh or ""}
    expected = {
        field_name: {item.placeholder for item in plan.items if item.field_name == field_name}
        for field_name in values
    }
    violations: list[dict] = []
    for field_name, value in values.items():
        observed = _SEED_TERM_PLACEHOLDER_RE.findall(value)
        for placeholder in sorted(set(observed) | expected[field_name]):
            count = observed.count(placeholder)
            if placeholder not in expected[field_name]:
                reason = "wrong_or_unexpected_field"
            elif count == 0:
                reason = "missing"
            elif count > 1:
                reason = "duplicated"
            else:
                continue
            violations.append(
                {
                    "placeholder": placeholder,
                    "field_name": field_name,
                    "reason": reason,
                    "count": count,
                }
            )
    return violations


def restore_japanese_seed_term_placeholders(
    text: str,
    plan: JapaneseSeedTermPlan,
    *,
    field_name: str | None = None,
) -> str:
    restored = text or ""
    for item in plan.items:
        if field_name is None or item.field_name == field_name:
            search_from = 0
            while True:
                start = restored.find(item.placeholder, search_from)
                if start < 0:
                    break
                suffix_start = start + len(item.placeholder)
                suffix = restored[suffix_start:]
                overlap = _seed_term_boundary_overlap(item.target_text, suffix)
                restored = (
                    restored[:start]
                    + item.target_text
                    + suffix[overlap:]
                )
                search_from = start + len(item.target_text)
    return restored


def _seed_term_boundary_overlap(target_text: str, following_text: str) -> int:
    """Return only unambiguous overlap introduced beside a seed placeholder."""

    max_overlap = min(len(target_text), len(following_text))
    for length in range(max_overlap, 1, -1):
        if target_text[-length:] == following_text[:length]:
            return length

    # `公开级` + `级别` is a common model expansion around the protected term.
    # Other one-character overlaps may be legitimate, e.g. `拍卖会` + `会场`.
    if target_text.endswith("级") and following_text.startswith("级别"):
        return 1
    return 0
