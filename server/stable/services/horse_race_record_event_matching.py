"""Heuristic matching between HorseRaceRecord and RaceEvent.

Production has very few RaceResultSourceIdentity rows for The Racing API, so we
match records to events by race date, racecourse, race name similarity, and the
presence of the horse name in the event's runner table.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from django.db.models import Prefetch

from stable.models import HorseProfile, HorseRaceRecord, RaceEvent, RaceEventRunner


# Common parenthetical suffixes that appear in race names from The Racing API.
RACE_NAME_NOISE_RE = re.compile(
    r"\s*[\(\[]\s*(?:group\s*\d+|grade\s*\d+|handicap|stakes|gbb\s*race|"
    r"listed|conditions|class\s*\d+|mares|fillies|colts|geldings|"
    r"3yo|2yo|4yo|5yo|novice|maiden|hurdle|chase|flat)[\)\]]\s*$",
    re.IGNORECASE,
)

COUNTRY_SUFFIX_RE = re.compile(r"\s+\([A-Z]{2,3}\)$")


def _normalize_race_name(name: str) -> str:
    name = (name or "").strip()
    while RACE_NAME_NOISE_RE.search(name):
        name = RACE_NAME_NOISE_RE.sub("", name).strip()
    return re.sub(r"\s+", " ", name.lower()).strip()


def _normalize_racecourse(course: str) -> str:
    course = (course or "").strip().lower()
    course = re.sub(r"[^a-z0-9]+", "", course)
    return course


def _normalize_horse_name(name: str) -> str:
    name = (name or "").strip()
    name = COUNTRY_SUFFIX_RE.sub("", name).strip()
    return re.sub(r"\s+", " ", name.lower()).strip()


@dataclass
class EventMatch:
    event: RaceEvent
    score: float
    horse_name_match: bool
    race_name_score: float


class RaceEventMatcher:
    """Index RaceEvents by date+course and score candidates for a HorseRaceRecord."""

    def __init__(self, events: list[RaceEvent] | None = None):
        if events is None:
            events = list(
                RaceEvent.objects.filter(local_date__isnull=False)
                .prefetch_related(Prefetch("runners", queryset=RaceEventRunner.objects.all()))
                .order_by("local_date", "id")
            )
        self.events = events
        self._index: dict[tuple[date, str], list[RaceEvent]] = defaultdict(list)
        self._runner_names: dict[int, set[str]] = {}

        for event in events:
            course_key = _normalize_racecourse(event.racecourse)
            if event.local_date and course_key:
                self._index[(event.local_date, course_key)].append(event)

            names: set[str] = set()
            for runner in event.runners.all():
                names.add(_normalize_horse_name(runner.horse_name))
            self._runner_names[event.id] = names

    def _candidate_events(self, record: HorseRaceRecord) -> list[RaceEvent]:
        if not record.race_date:
            return []

        course_key = _normalize_racecourse(record.racecourse)

        # Require a course match when the record provides a course.
        if course_key:
            return list(self._index.get((record.race_date, course_key), []))

        # Only fall back to all events on the same date when the record has no
        # course information.
        return [event for event in self.events if event.local_date == record.race_date]

    def _race_name_score(self, record: HorseRaceRecord, event: RaceEvent) -> float:
        record_name = _normalize_race_name(record.race_name)
        event_name = _normalize_race_name(event.original_name) or _normalize_race_name(event.chinese_name)

        if not record_name or not event_name:
            return 0.0

        if record_name == event_name:
            return 1.0

        # One contains the other (e.g. "Coronation Cup" vs "Betfred Coronation Cup").
        if record_name in event_name or event_name in record_name:
            return 0.85

        return SequenceMatcher(None, record_name, event_name).ratio()

    def _horse_name_match(self, profile: HorseProfile | None, event: RaceEvent) -> bool:
        if profile is None:
            return False
        runner_names = self._runner_names.get(event.id, set())
        if not runner_names:
            return False

        candidate_names = {
            _normalize_horse_name(profile.english_name),
            _normalize_horse_name(profile.original_name),
            _normalize_horse_name(profile.japanese_name),
        }
        candidate_names.discard("")

        return bool(candidate_names & runner_names)

    def find_best_match(
        self,
        record: HorseRaceRecord,
        profile: HorseProfile | None = None,
        threshold: float = 0.6,
    ) -> EventMatch | None:
        """Return the best matching RaceEvent for a record, or None if no match passes the threshold."""
        candidates = self._candidate_events(record)
        if not candidates:
            return None

        if profile is None and record.horse_profile_id:
            profile = record.horse_profile

        best: EventMatch | None = None
        for event in candidates:
            race_name_score = self._race_name_score(record, event)
            horse_name_match = self._horse_name_match(profile, event)

            # Combine scores: horse name presence is a strong confirmation signal.
            if horse_name_match:
                score = 0.6 + 0.4 * race_name_score
            else:
                # Without horse name confirmation we require a very high name match.
                score = race_name_score * 0.8

            if score >= threshold and (best is None or score > best.score):
                best = EventMatch(event=event, score=score, horse_name_match=horse_name_match, race_name_score=race_name_score)

        return best


def match_horse_race_records(
    records: list[HorseRaceRecord],
    matcher: RaceEventMatcher | None = None,
    *,
    threshold: float = 0.6,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Link a list of HorseRaceRecord rows to RaceEvent objects heuristically.

    Returns a summary dict with matched/unmatched counts and per-record details.
    """
    if matcher is None:
        matcher = RaceEventMatcher()

    matched_count = 0
    unmatched_count = 0
    skipped_count = 0
    details: list[dict[str, Any]] = []

    updates: list[HorseRaceRecord] = []

    for record in records:
        if record.event_id:
            skipped_count += 1
            continue

        match = matcher.find_best_match(record, threshold=threshold)
        if match is None:
            unmatched_count += 1
            continue

        record.event = match.event
        updates.append(record)
        matched_count += 1
        details.append(
            {
                "record_id": record.id,
                "event_id": match.event.id,
                "event_name": match.event.original_name or match.event.chinese_name,
                "score": round(match.score, 3),
                "horse_name_match": match.horse_name_match,
                "race_name_score": round(match.race_name_score, 3),
            }
        )

    if not dry_run and updates:
        HorseRaceRecord.objects.bulk_update(updates, ["event", "updated_at"])

    return {
        "matched": matched_count,
        "unmatched": unmatched_count,
        "skipped_already_linked": skipped_count,
        "total": len(records),
        "details": details,
    }
