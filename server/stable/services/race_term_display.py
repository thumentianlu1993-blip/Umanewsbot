"""
Race/racecourse term display resolution for public pages.

Provides batch lookup: one query for TermEntry, one for TermAlias,
regardless of how many names are being resolved.

Region-aware: when region context is available the resolver prefers
exact region matches.  When the same name maps to different terms in
different regions (conflict) the original name is preserved rather
than picking arbitrarily.
"""
from __future__ import annotations

from typing import Dict, Optional, Set, Tuple

from stable.models import TermAlias, TermEntry, TermType


def _normalize(name: str) -> str:
    """Normalize a name for lookup purposes."""
    return (name or "").strip()


def resolve_batch_race_terms(
    race_names: Set[Tuple[str, str, str]],
    racecourse_names: Set[Tuple[str, str, str]],
) -> Dict[str, Dict[Tuple[str, str, str], Optional[str]]]:
    """
    Return two separate lookup dicts keyed by (name, region, source_language):

        {"race":      {(name, region, lang): target_zh | None},
         "racecourse": {(name, region, lang): target_zh | None}}

    Race and racecourse terms are resolved independently so a race name
    can never match a racecourse term and vice versa.
    """
    lookups: Dict[str, Dict[Tuple[str, str, str], Optional[str]]] = {
        "race": {},
        "racecourse": {},
    }

    def _resolve_one(
        pairs: Set[Tuple[str, str, str]], tt: str
    ) -> Dict[Tuple[str, str, str], Optional[str]]:
        """Resolve (name, region, source_language) triples.

        Exactly-one candidate rule: if zero or >1 entries share the same
        (name, region, language) triple, the triple stays unresolved (None).
        """
        inner: Dict[Tuple[str, str, str], Optional[str]] = {}
        for triple in pairs:
            inner[triple] = None
        if not pairs:
            return inner
        unique_names = {_normalize(n) for n, _, _ in pairs if _normalize(n)}
        if not unique_names:
            return inner

        # TermEntry — exactly-one candidate per (name, region, language)
        entries = TermEntry.objects.filter(
            is_active=True,
            term_type=tt,
            source_ja__in=unique_names,
        ).values("id", "source_ja", "target_zh", "racing_region", "source_language")
        counts: Dict[Tuple[str, str, str], int] = {}
        ids: Dict[Tuple[str, str, str], str] = {}
        for e in entries:
            k = (
                _normalize(e["source_ja"]),
                e["racing_region"] or "",
                e["source_language"] or "",
            )
            counts[k] = counts.get(k, 0) + 1
            if e["target_zh"]:
                ids[k] = e["target_zh"]
        for name, region, lang in pairs:
            n = _normalize(name)
            key = (n, region, lang)
            if counts.get(key) == 1:
                inner[(name, region, lang)] = ids.get(key)
                continue
            if counts.get(key, 0) > 1:
                continue  # conflict
            # Fallback: global region
            global_key = (n, "", lang)
            if counts.get(global_key) == 1:
                inner[(name, region, lang)] = ids.get(global_key)

        # TermAlias for still-unresolved
        still = {n for n, _, _ in pairs if inner.get((n, _, _)) is None}
        still_fixed = set()
        for n, r, l in pairs:
            if inner[(n, r, l)] is None:
                still_fixed.add(_normalize(n))
        if still_fixed:
            aliases = TermAlias.objects.filter(
                is_active=True,
                term__is_active=True,
                term__term_type=tt,
                text__in=still_fixed,
            ).values(
                "text", "term__target_zh", "term__racing_region",
                "source_language",
            )
            a_counts: Dict[Tuple[str, str, str], int] = {}
            a_ids: Dict[Tuple[str, str, str], str] = {}
            for a in aliases:
                k = (
                    _normalize(a["text"]),
                    a["term__racing_region"] or "",
                    a["source_language"] or "",
                )
                a_counts[k] = a_counts.get(k, 0) + 1
                if a["term__target_zh"]:
                    a_ids[k] = a["term__target_zh"]
            for name, region, lang in pairs:
                if inner[(name, region, lang)] is not None:
                    continue
                n = _normalize(name)
                key = (n, region, lang)
                if a_counts.get(key) == 1:
                    inner[(name, region, lang)] = a_ids.get(key)
                    continue
                if a_counts.get(key, 0) > 1:
                    continue
                global_key = (n, "", lang)
                if a_counts.get(global_key) == 1:
                    inner[(name, region, lang)] = a_ids.get(global_key)
        return inner

    lookups["race"] = _resolve_one(race_names, TermType.RACE)
    lookups["racecourse"] = _resolve_one(racecourse_names, TermType.RACECOURSE)
    return lookups


def display_race_name(
    race_name: str,
    term_lookup: Optional[Dict[Tuple[str, str, str], Optional[str]]] = None,
    region: str = "",
    source_language: str = "",
) -> str:
    """Return the Chinese display name for a race (region + language aware)."""
    if term_lookup:
        n = _normalize(race_name)
        key = (n, region, source_language)
        if key in term_lookup and term_lookup[key]:
            return term_lookup[key]
        global_key = (n, "", source_language)
        if global_key in term_lookup and term_lookup[global_key]:
            return term_lookup[global_key]
    return race_name or ""


def display_racecourse_name(
    racecourse_name: str,
    term_lookup: Optional[Dict[Tuple[str, str, str], Optional[str]]] = None,
    region: str = "",
    source_language: str = "",
) -> str:
    """Return the Chinese display name for a racecourse (region + language aware)."""
    if term_lookup:
        n = _normalize(racecourse_name)
        key = (n, region, source_language)
        if key in term_lookup and term_lookup[key]:
            return term_lookup[key]
        global_key = (n, "", source_language)
        if global_key in term_lookup and term_lookup[global_key]:
            return term_lookup[global_key]
    return racecourse_name or ""


class RaceTermResolver:
    """
    Request-scoped batch term resolver — type-separated, region + language aware.
    """

    def __init__(self, *, mode="legacy") -> None:
        if mode not in {"legacy", "strict_display_v1"}:
            raise ValueError("unknown term display mode")
        self.mode = mode
        self.strict = StrictRaceTermResolver() if mode == "strict_display_v1" else None
        self._race_names: Set[Tuple[str, str, str]] = set()
        self._racecourse_names: Set[Tuple[str, str, str]] = set()
        self._resolved: bool = False
        self._race_lookup: Dict[Tuple[str, str, str], Optional[str]] = {}
        self._racecourse_lookup: Dict[Tuple[str, str, str], Optional[str]] = {}

    def add_race_name(
        self, name: str, region: str = "", source_language: str = ""
    ) -> None:
        normalized = _normalize(name)
        if normalized:
            self._race_names.add((normalized, region, source_language))

    def add_racecourse_name(
        self, name: str, region: str = "", source_language: str = ""
    ) -> None:
        normalized = _normalize(name)
        if normalized:
            self._racecourse_names.add((normalized, region, source_language))

    def resolve(self) -> None:
        if self.strict is not None:
            if not self._resolved:
                for kind, names in ((TermType.RACE, self._race_names), (TermType.RACECOURSE, self._racecourse_names)):
                    for name, region, language in names:
                        self.strict.add(name, kind, region, language)
                self.strict.resolve()
                self._resolved = True
            return
        if self._resolved:
            return
        lookups = resolve_batch_race_terms(
            self._race_names,
            self._racecourse_names,
        )
        self._race_lookup = lookups["race"]
        self._racecourse_lookup = lookups["racecourse"]
        self._resolved = True

    def display_race_name(
        self, name: str, region: str = "", source_language: str = ""
    ) -> str:
        if not self._resolved:
            self.resolve()
        if self.strict is not None:
            return self.strict.field(name, TermType.RACE, region, source_language).text
        return display_race_name(name, self._race_lookup, region, source_language)

    def display_racecourse_name(
        self, name: str, region: str = "", source_language: str = ""
    ) -> str:
        if not self._resolved:
            self.resolve()
        if self.strict is not None:
            return self.strict.field(name, TermType.RACECOURSE, region, source_language).text
        return display_racecourse_name(name, self._racecourse_lookup, region, source_language)


# 新模式先合并主名和别名，再按实体去重；legacy路径保持原样。
import unicodedata
from dataclasses import replace
from django.db.models import Q
from stable.services.race_field_normalization import display_field


def display_identity(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


class StrictRaceTermResolver:
    def __init__(self):
        self.requests = set()
        self.results = {}

    def add(self, value, term_type, region='', language='', year=None):
        self.requests.add((str(value or ''), term_type, region or '', language or '', year))

    def resolve(self):
        for term_type in {r[1] for r in self.requests}:
            requests = [r for r in self.requests if r[1] == term_type and r[0].strip()]
            if not requests:
                continue
            primary_query, alias_query = Q(pk__in=[]), Q(pk__in=[])
            # bounded by rendered page inputs; no full-table Python scan.
            for name in {r[0] for r in requests}:
                for variant in {name.strip(), ' '.join(unicodedata.normalize('NFKC', name).split())}:
                    primary_query |= Q(source_ja__iexact=variant)
                    alias_query |= Q(text__iexact=variant)
            regions = {r[2] for r in requests} | {''}
            candidates = []
            entries = TermEntry.objects.filter(primary_query, term_type=term_type, is_active=True,
                                                racing_region__in=regions).values(
                'id', 'source_ja', 'target_zh', 'racing_region', 'source_language')
            for entry in entries:
                candidates.append((entry['id'], display_identity(entry['source_ja']), entry['target_zh'],
                                   entry['racing_region'], entry['source_language']))
            aliases = TermAlias.objects.filter(alias_query, term__term_type=term_type, is_active=True,
                                                term__is_active=True, term__racing_region__in=regions).values(
                'term_id', 'text', 'term__target_zh', 'term__racing_region', 'source_language')
            for alias in aliases:
                candidates.append((alias['term_id'], display_identity(alias['text']), alias['term__target_zh'],
                                   alias['term__racing_region'], alias['source_language']))
            for req in requests:
                name, _, region, language, year = req
                found = [c for c in candidates if c[1] == display_identity(name) and (not language or c[4] == language)]
                local = [c for c in found if c[3] == region]
                tier = local if local else [c for c in found if c[3] == '']
                by_entity = {c[0]: c for c in tier}
                context = {'type': term_type, 'region': region, 'language': language, 'year': year}
                if len(by_entity) == 1:
                    candidate = next(iter(by_entity.values()))
                    self.results[req] = display_field(name, candidate[2] or name, context=context,
                                                      state='normalized' if candidate[2] else 'preserved',
                                                      reason='formal_term' if candidate[2] else 'untranslated_term')
                else:
                    # 专名冲突保留原名，原因仍记录为 conflict，不选任意实体。
                    self.results[req] = replace(display_field(name, ' '.join(name.split()), state='conflict' if by_entity else 'preserved',
                                                      reason='term_conflict' if by_entity else 'term_missing', context=context), text=' '.join(name.split()))
        return self

    def field(self, value, term_type, region='', language='', year=None):
        key = (str(value or ''), term_type, region or '', language or '', year)
        if not value:
            return display_field(value, state='missing', reason='missing')
        return self.results.get(key, display_field(value, ' '.join(str(value).split()), state='preserved', reason='term_missing'))
