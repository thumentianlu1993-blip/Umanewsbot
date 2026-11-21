"""Private persisted R07 diagnostics for an explicitly selected revision pair."""
from dataclasses import dataclass
import hashlib
import json

from django.db import connection, transaction

from stable import models as m
from stable.services.race_result_roster_reconciliation import (
    Outcome, RosterReconciliation, reconcile_result_roster,
)


@dataclass(frozen=True, slots=True)
class ParticipantBinding:
    participant_id: int
    stable_key: str
    racecard_item_id: int | None


@dataclass(frozen=True, slots=True)
class PersistedRosterInspection:
    schema_version: int
    event_id: int
    racecard_revision_id: int
    result_revision_id: int
    material_sha256: str
    participant_bindings: tuple[ParticipantBinding, ...]
    diagnostics: tuple[str, ...]
    ledger: RosterReconciliation


_REVISION_FIELDS = ("id", "event_id", "kind", "phase", "content_sha256")
_ITEM_FIELDS = ("id", "revision_id", "participant_id", "status", "reported_finish_position")


def _items(revision_id: int) -> list[dict]:
    rows = list(m.RaceEventRevisionItem.objects.filter(revision_id=revision_id)
                .order_by("pk").values(*_ITEM_FIELDS, "participant__id",
                                      "participant__event_id", "participant__stable_key")[:101])
    if len(rows) > 100:
        raise ValueError("revision contains more than 100 items")
    return rows


def _materialize(event_id: int, racecard_revision_id: int,
                 result_revision_id: int) -> PersistedRosterInspection:
    revisions = {
        row["id"]: row for row in m.RaceEventRevision.objects.filter(
            pk__in=(racecard_revision_id, result_revision_id)).values(*_REVISION_FIELDS)
    }
    card = revisions.get(racecard_revision_id)
    result = revisions.get(result_revision_id)
    if (card is None or result is None or card["event_id"] != event_id
            or result["event_id"] != event_id or card["kind"] != "racecard"
            or card["phase"] != "racecard" or result["kind"] != "result"):
        raise ValueError("invalid event or revision pair")
    card_rows = _items(racecard_revision_id)
    result_rows = _items(result_revision_id)
    if not card_rows:
        raise ValueError("racecard revision is empty")
    participants = {}
    for row in card_rows + result_rows:
        if row["participant__id"] != row["participant_id"] or row["participant__event_id"] != event_id:
            raise ValueError("participant belongs to a different event")
        participants[row["participant_id"]] = {
            "id": row["participant__id"], "event_id": row["participant__event_id"],
            "stable_key": row["participant__stable_key"],
        }
    card_by_participant = {row["participant_id"]: row["id"] for row in card_rows}
    if len(card_by_participant) != len(card_rows):
        raise ValueError("duplicate racecard participant")
    material = {
        "event_id": event_id, "revisions": [card, result],
        "racecard_items": [{key: row[key] for key in _ITEM_FIELDS} for row in card_rows],
        "result_items": [{key: row[key] for key in _ITEM_FIELDS} for row in result_rows],
        "participants": [participants[pk] for pk in sorted(participants)],
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode()).hexdigest()
    scope_ref = (f"r07:event:{event_id}:racecard:{racecard_revision_id}:"
                 f"result:{result_revision_id}:sha256:{digest}")
    roster_ref = f"db:racecard-revision:{racecard_revision_id}:sha256:{digest}"
    ledger = reconcile_result_roster(
        scope_ref=scope_ref, roster_ref=roster_ref,
        expected_runner_ids=tuple(sorted(card_by_participant)),
        # Neither revision items nor derived HorseRaceRecord fields prove starts.
        participation=(),
        outcomes=tuple(Outcome(row["participant_id"], scope_ref, row["status"],
                               row["reported_finish_position"], f"db:revision-item:{row['id']}")
                       for row in result_rows),
    )
    bindings = tuple(ParticipantBinding(pk, participants[pk]["stable_key"], card_by_participant.get(pk))
                     for pk in sorted(participants))
    return PersistedRosterInspection(
        1, event_id, racecard_revision_id, result_revision_id, digest, bindings,
        ("participation_provenance_unavailable",), ledger,
    )


def load_persisted_roster_reconciliation(
    *, event_id: int, racecard_revision_id: int, result_revision_id: int,
) -> PersistedRosterInspection:
    """Read one PostgreSQL RR snapshot without choosing current/public revisions.

    The material digest binds actual selected fields within this read, not source
    authenticity, freshness, independent participation facts or public eligibility.
    No outer transaction, session change, write, legacy identity fallback or I/O
    beyond the selected ORM reads is supported.
    """
    for value in (event_id, racecard_revision_id, result_revision_id):
        if type(value) is not int or not 1 <= value <= 2**63 - 1:
            raise ValueError("revision and event IDs must be positive database integers")
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("outer transactions are unsupported")
    if connection.vendor != "postgresql":
        raise ValueError("PostgreSQL is required")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return _materialize(event_id, racecard_revision_id, result_revision_id)
