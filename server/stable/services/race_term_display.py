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

    def __init__(self) -> None:
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
        return display_race_name(name, self._race_lookup, region, source_language)

    def display_racecourse_name(
        self, name: str, region: str = "", source_language: str = ""
    ) -> str:
        if not self._resolved:
            self.resolve()
        return display_racecourse_name(name, self._racecourse_lookup, region, source_language)
