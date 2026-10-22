"""Reconcile explicit roster, participation and outcome snapshots without I/O.

References are opaque provenance supplied by the caller, not source authority.
The ledger does not generate result rows, infer starts, or qualify publication.
"""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Participation:
    runner_id: int
    scope_ref: str
    start_status: str
    row_ref: str


@dataclass(frozen=True, slots=True)
class Outcome:
    runner_id: int
    scope_ref: str
    status: str
    reported_finish_position: int | None
    row_ref: str


@dataclass(frozen=True, slots=True)
class LedgerRow:
    runner_id: int
    start_status: str
    outcome_status: str | None
    reported_finish_position: int | None
    roster_ref: str | None
    participation_ref: str | None
    result_ref: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RosterReconciliation:
    scope_ref: str
    roster_ref: str
    ledger: tuple[LedgerRow, ...]
    unexpected_rows: tuple[LedgerRow, ...]
    started_ids: tuple[int, ...]
    did_not_start_ids: tuple[int, ...]
    unconfirmed_start_ids: tuple[int, ...]
    unresolved_result_ids: tuple[int, ...]
    unexpected_ids: tuple[int, ...]
    conflict_ids: tuple[int, ...]


_STARTS = frozenset(("started", "did_not_start", "unconfirmed"))
_RANKED = frozenset(("finished", "dead_heat"))
_NONFINISH = frozenset(("did_not_finish", "pulled_up", "unseated_rider", "fell"))
_AMBIGUOUS = frozenset(("disqualified", "refused"))
_NONSTARTER = frozenset(("scratched", "withdrawn", "non_runner"))
_PENDING = frozenset(("declared", "running", "reinstated", "unknown"))
_OUTCOMES = _RANKED | _NONFINISH | _AMBIGUOUS | _NONSTARTER | _PENDING


def _validate_ref(value: object) -> None:
    if type(value) is not str or not 1 <= len(value) <= 256 or value.strip() != value:
        raise ValueError("invalid reference")


def _validate_id(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("invalid runner ID")


def _index_rows(rows: tuple, row_type: type, scope_ref: str) -> dict:
    if type(rows) is not tuple or len(rows) > 100:
        raise ValueError("invalid row sequence")
    indexed = {}
    for row in rows:
        if type(row) is not row_type:
            raise ValueError("invalid row type")
        _validate_id(row.runner_id)
        _validate_ref(row.scope_ref)
        _validate_ref(row.row_ref)
        if row.scope_ref != scope_ref or row.runner_id in indexed:
            raise ValueError("wrong scope or duplicate runner ID")
        if row_type is Participation:
            if type(row.start_status) is not str or row.start_status not in _STARTS:
                raise ValueError("invalid start status")
        else:
            if type(row.status) is not str or row.status not in _OUTCOMES:
                raise ValueError("invalid outcome status")
            position = row.reported_finish_position
            if row.status in _RANKED:
                if type(position) is not int or not 1 <= position <= 100:
                    raise ValueError("invalid ranked position")
            elif position is not None:
                raise ValueError("nonranked outcome has a position")
        indexed[row.runner_id] = row
    return indexed


def _relation(start: str, status: str | None) -> tuple[str, bool, bool]:
    """Return reason, unresolved and conflict; never derive a start fact."""
    if status is None:
        if start == "did_not_start":
            return "known_nonstarter_without_result", False, False
        return "result_missing", True, False
    if status in _PENDING:
        return "result_nonterminal", True, False
    if status in _NONSTARTER:
        if start == "started":
            return "started_nonstarter_conflict", True, True
        if start == "did_not_start":
            return "known_nonstarter_result", False, False
        return "nonstarter_result_start_unconfirmed", False, False
    if start == "did_not_start":
        if status in _AMBIGUOUS:
            return "participation_outcome_relation_unconfirmed", True, False
        return "nonstarter_started_outcome_conflict", True, True
    return "terminal_result", False, False


def _ledger_row(runner_id: int, participation: Participation | None,
                outcome: Outcome | None, roster_ref: str | None,
                reasons: tuple[str, ...]) -> LedgerRow:
    return LedgerRow(
        runner_id,
        participation.start_status if participation is not None else "unconfirmed",
        outcome.status if outcome is not None else None,
        outcome.reported_finish_position if outcome is not None else None,
        roster_ref,
        participation.row_ref if participation is not None else None,
        outcome.row_ref if outcome is not None else None,
        reasons,
    )


def reconcile_result_roster(
    *, scope_ref: str, roster_ref: str, expected_runner_ids: tuple[int, ...],
    participation: tuple[Participation, ...], outcomes: tuple[Outcome, ...],
) -> RosterReconciliation:
    """Build an immutable per-ID diagnostic within the caller's declared scope.

    All inputs, including unexpected IDs, are validated before returning any
    report. Local outcome summaries need not prove whole-race ranking validity.
    Unresolved includes missing terminal outcomes and unsettled relationships;
    it is not a public completeness or source authenticity decision.
    """
    _validate_ref(scope_ref)
    _validate_ref(roster_ref)
    if type(expected_runner_ids) is not tuple or not 1 <= len(expected_runner_ids) <= 100:
        raise ValueError("invalid expected roster")
    expected = set()
    for runner_id in expected_runner_ids:
        _validate_id(runner_id)
        if runner_id in expected:
            raise ValueError("duplicate expected runner ID")
        expected.add(runner_id)
    parts = _index_rows(participation, Participation, scope_ref)
    results = _index_rows(outcomes, Outcome, scope_ref)
    ledger = []
    starts = {"started": [], "did_not_start": [], "unconfirmed": []}
    unresolved = []
    conflicts = []
    for runner_id in sorted(expected):
        part = parts.get(runner_id)
        outcome = results.get(runner_id)
        start = part.start_status if part is not None else "unconfirmed"
        status = outcome.status if outcome is not None else None
        reason, is_unresolved, is_conflict = _relation(start, status)
        reasons = (reason,) if part is not None else ("participation_missing", reason)
        ledger.append(_ledger_row(runner_id, part, outcome, roster_ref, reasons))
        starts[start].append(runner_id)
        if is_unresolved:
            unresolved.append(runner_id)
        if is_conflict:
            conflicts.append(runner_id)
    unexpected = tuple(sorted((parts.keys() | results.keys()) - expected))
    unexpected_rows = tuple(
        _ledger_row(runner_id, parts.get(runner_id), results.get(runner_id),
                    None, ("unexpected_identity",))
        for runner_id in unexpected
    )
    return RosterReconciliation(
        scope_ref, roster_ref, tuple(ledger), unexpected_rows,
        tuple(starts["started"]), tuple(starts["did_not_start"]),
        tuple(starts["unconfirmed"]), tuple(unresolved), unexpected, tuple(conflicts),
    )
