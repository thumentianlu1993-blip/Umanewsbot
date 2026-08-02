from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from django.apps import apps
from django.db import IntegrityError, connection, transaction
from django.utils import timezone


class HistoricalCalendarWriteBlocked(RuntimeError):
    pass


_verified_repair_identity: ContextVar[tuple[str, str] | None] = ContextVar(
    "verified_historical_calendar_repair_identity", default=None
)
_GATE_LOCK_ID = 0x4849535443414C


def _lock_writer_admission() -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock_shared(%s)", [_GATE_LOCK_ID])


def _lock_gate_transition() -> None:
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_GATE_LOCK_ID])


def assert_historical_calendar_write_admitted() -> None:
    """Admission check for every RaceEvent/target/path writer.

    PostgreSQL writers take the transaction-scoped shared lock before checking the
    live row. A gate transition takes the exclusive counterpart, so an already
    admitted writer drains first and a waiter re-checks after it acquires the lock.
    """

    _lock_writer_admission()
    gate_model = apps.get_model("stable", "HistoricalRaceCalendarMaintenanceGate")
    active = gate_model.objects.filter(status="active").only(
        "manifest_sha256", "action_scope_sha256"
    ).first()
    if active is None:
        return
    if _verified_repair_identity.get() == (
        active.manifest_sha256,
        active.action_scope_sha256,
    ):
        return
    raise HistoricalCalendarWriteBlocked(
        "historical race calendar maintenance gate is active"
    )


@contextmanager
def _verified_repair_writer(
    *, manifest_sha256: str, action_scope_sha256: str
) -> Iterator[None]:
    """Private, exact-scope bypass used only by the verified repair transaction."""

    token = _verified_repair_identity.set((manifest_sha256, action_scope_sha256))
    try:
        yield
    finally:
        _verified_repair_identity.reset(token)


def require_exact_active_gate(
    *, manifest_sha256: str, action_scope_sha256: str, actor: Any
):
    gate_model = apps.get_model("stable", "HistoricalRaceCalendarMaintenanceGate")
    queryset = gate_model.objects
    if connection.in_atomic_block:
        queryset = queryset.select_for_update()
    try:
        return queryset.get(
            status="active",
            manifest_sha256=manifest_sha256,
            action_scope_sha256=action_scope_sha256,
            actor=actor,
        )
    except gate_model.DoesNotExist as exc:
        raise HistoricalCalendarWriteBlocked(
            "exact active historical calendar maintenance gate is required"
        ) from exc


@transaction.atomic
def enter_historical_calendar_maintenance(
    *, manifest_sha256: str, action_scope_sha256: str, actor: Any
):
    _lock_gate_transition()
    gate_model = apps.get_model("stable", "HistoricalRaceCalendarMaintenanceGate")
    if gate_model.objects.filter(status="active").exists():
        raise IntegrityError("a historical calendar maintenance gate is already active")
    return gate_model.objects.create(
        manifest_sha256=manifest_sha256,
        action_scope_sha256=action_scope_sha256,
        actor=actor,
        status="active",
        entered_at=timezone.now(),
    )


@transaction.atomic
def exit_historical_calendar_maintenance(
    *,
    gate: Any,
    actor: Any,
    manifest_sha256: str,
    action_scope_sha256: str,
):
    _lock_gate_transition()
    gate_model = apps.get_model("stable", "HistoricalRaceCalendarMaintenanceGate")
    current = gate_model.objects.select_for_update().get(pk=gate.pk)
    if (
        current.status != "active"
        or current.actor_id != actor.pk
        or current.manifest_sha256 != manifest_sha256
        or current.action_scope_sha256 != action_scope_sha256
    ):
        raise HistoricalCalendarWriteBlocked(
            "maintenance gate exit identity does not match"
        )
    current.status = "exited"
    current.exited_at = timezone.now()
    current.exited_by = actor
    current.save(update_fields={"status", "exited_at", "exited_by", "updated_at"})
    return current
