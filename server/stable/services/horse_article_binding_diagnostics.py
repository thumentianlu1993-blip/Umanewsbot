"""Internal selected-receipt observation, never historical discovery or grant.

Staff read qualification is independent of a binding writer's current permit.
One selected stored record can be self-consistent without authenticating its
source, original authority, request uniqueness or historical completeness.
No caller, scanner, task, registry or public endpoint is installed here.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, models, transaction
from django.utils import timezone

from stable.models import ArticleHorseLink, OperationLog
from stable.services.horse_article_binding_persistence import (
    _decode_receipt, _PARSE_ERRORS, _raw, _snapshot, _validate_receipt_after,
)


MAX_BYTES = 4_194_304
HASH = re.compile(r"[0-9a-f]{64}\Z")
ACTION = "horse_binding_committed"
TARGET = "horse_binding_request"


class DiagnosticInputError(ValueError):
    """The explicit selector has an unsupported type or shape."""


class DiagnosticAccessError(PermissionError):
    """The caller is not an authenticated, actual, current active staff user."""


class DiagnosticTransactionError(RuntimeError):
    """The caller cannot provide an independent top-level PostgreSQL read."""


def _positive_id(value):
    return type(value) is int and value > 0


def _hash(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def _stored(condition):
    if not condition:
        raise ValueError("invalid_selected_receipt")


def _validated_receipt(row):
    """Pure stored-data checks; deliberately no actor/scope/ORM resolution."""
    receipt = _decode_receipt(row)
    _stored(receipt["schema_version"] == "l01.horse-link-receipt.v1")
    _stored(receipt["before"] == "absent")
    for name in ("article_id", "profile_id", "identity_id", "link_id", "actor_id", "payload_revision"):
        _stored(_positive_id(receipt[name]))
    for name in ("request_key", "payload_sha256", "decision_sha256", "after_sha256"):
        _stored(_hash(receipt[name]))
    provider = receipt["provider_ref"]
    _stored(type(provider) is dict and set(provider) == {"source", "namespace", "external_id"})
    for value in provider.values():
        _stored(type(value) is str and 0 < len(value) <= 255)
    # These inputs validate the selected record against itself, not a current
    # permission bundle. Explicit caller selectors are compared separately.
    _validate_receipt_after(row, receipt, receipt["request_key"], receipt["payload_sha256"],
                            receipt["article_id"], receipt["profile_id"], provider)
    after = receipt["after"]
    for name in ("id", "article_id", "horse_profile_id"):
        _stored(_positive_id(after[name]))
    for name in ("confirmed_by_id", "removed_by_id"):
        _stored(after[name] is None or _positive_id(after[name]))
    for name in ("status", "source", "matched_text", "match_reason"):
        value = after[name]
        limit = ArticleHorseLink._meta.get_field(name).max_length
        _stored(type(value) is str and (limit is None or len(value) <= limit))
    _stored(type(after["confidence"]) is int and 0 <= after["confidence"] <= 32767)
    for name in ("created_at", "updated_at", "confirmed_at", "removed_at"):
        value = after[name]
        if value is None:
            _stored(ArticleHorseLink._meta.get_field(name).null)
        else:
            _stored(type(value) is str)
            parsed = datetime.fromisoformat(value)
            _stored(parsed.tzinfo is not None and parsed.utcoffset() is not None)
    return receipt


def _result(receipt_id, key, article_id, profile_id):
    return {
        "schema_version": "l02.selected-horse-binding-diagnostic.v1",
        "receipt_id": receipt_id,
        "expected_request_key": key,
        "article_id": article_id,
        "profile_id": profile_id,
        "selected_receipt_state": "selected_missing",
        "current_pair_state": "not_comparable",
        "current_manual_state": "not_evaluated",
        "original_link_id": None,
        "current_link_id": None,
        "receipt_detail_sha256": None,
        "after_sha256": None,
        "current_sha256": None,
        "changed_fields": [],
        "current_markers": None,
        "observed_at": timezone.now().isoformat(),
        "historical_coverage": "selected_receipt_only",
        "request_uniqueness": "not_checked",
        "current_write_authority": "not_evaluated",
        "source_license": "not_evaluated",
        "automatic_action": "none",
    }


def _current_markers(link):
    metadata = link.metadata
    schema = metadata.get("schema_version") if type(metadata) is dict else None
    return {
        "source_namespace": type(link.source) is str and link.source.startswith("strong_identity."),
        "schema_namespace": type(schema) is str and schema.startswith("l01.horse-link-metadata."),
        "reserved_keys": type(metadata) is dict and "request_key" in metadata
                         and ("payload_sha256" in metadata or "decision_sha256" in metadata),
    }


def diagnose_selected_horse_binding_receipt(
    receipt_id, expected_request_key, expected_article_id, expected_profile_id, actor,
):
    """Observe one explicitly selected receipt and current pair in a RR snapshot.

    Caller must supply the existing authenticated staff principal, not an
    actor ID/JSON assertion. No historical key search, write-admission lookup,
    unique-request assertion or automatic mutation follows this observation.
    Database/driver/timeout errors escape the atomic context unchanged.
    """
    if not all(_positive_id(value) for value in (receipt_id, expected_article_id, expected_profile_id)):
        raise DiagnosticInputError("positive_selector_ids_required")
    if not _hash(expected_request_key):
        raise DiagnosticInputError("exact_request_key_required")
    User = get_user_model()
    # Inspect the actual type, not a lazy proxy's __class__: resolving such a
    # proxy here could perform a user SELECT before the read-only snapshot.
    if not issubclass(type(actor), User) or not _positive_id(actor.pk):
        raise DiagnosticAccessError("authenticated_staff_reader_required")
    if connection.vendor != "postgresql" or connection.in_atomic_block or not connection.get_autocommit():
        raise DiagnosticTransactionError("independent_postgresql_autocommit_required")

    with transaction.atomic(using=connection.alias, durable=True):
        # No SELECT, including the reader lookup, may establish a snapshot
        # before these characteristics. LOCAL changes end at commit/rollback;
        # no manual session reset can mask an original database exception.
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL statement_timeout='2s'")
        if actor.is_authenticated is not True:
            raise DiagnosticAccessError("authenticated_staff_reader_required")
        reader = User.objects.using(connection.alias).filter(pk=actor.pk).only("pk", "is_active", "is_staff").first()
        if reader is None or not reader.is_active or not reader.is_staff:
            raise DiagnosticAccessError("current_active_staff_reader_required")

        result = _result(receipt_id, expected_request_key, expected_article_id, expected_profile_id)
        # Fetch only this PK's header and server-side byte length. A LIMIT on
        # an unindexed request-key query would not provide this read boundary.
        header = (OperationLog.objects.using(connection.alias).filter(pk=receipt_id)
                  .annotate(detail_bytes=models.Func(models.F("detail"), function="OCTET_LENGTH",
                                                     output_field=models.BigIntegerField()))
                  .values("id", "action_type", "target_type", "target_id", "detail_bytes")
                  .first())
        if header is None:
            return result
        if (header["action_type"] != ACTION or header["target_type"] != TARGET
                or header["target_id"] != expected_request_key):
            result["selected_receipt_state"] = "selector_mismatch"
            return result
        size = header["detail_bytes"]
        if type(size) is not int or not 0 <= size <= MAX_BYTES:
            result["selected_receipt_state"] = "invalid_or_unsupported"
            return result

        # Both SELECTs see the same RR snapshot, even if a different session
        # commits deletion/replacement after the header read. No row lock.
        row = (OperationLog.objects.using(connection.alias)
               .only("id", "admin_id", "detail").get(pk=receipt_id))
        result["receipt_detail_sha256"] = hashlib.sha256(row.detail.encode("utf-8")).hexdigest()
        try:
            receipt = _validated_receipt(row)
        except _PARSE_ERRORS:
            result["selected_receipt_state"] = "invalid_or_unsupported"
            return result
        if (receipt["request_key"] != expected_request_key
                or receipt["article_id"] != expected_article_id
                or receipt["profile_id"] != expected_profile_id):
            result["selected_receipt_state"] = "selector_mismatch"
            return result

        result.update(selected_receipt_state="stored_consistent", original_link_id=receipt["link_id"],
                      after_sha256=receipt["after_sha256"], current_pair_state="absent",
                      current_manual_state="no_current_row")
        current = list(ArticleHorseLink.objects.using(connection.alias)
                       .filter(article_id=expected_article_id, horse_profile_id=expected_profile_id)
                       .order_by("pk")[:2])
        if len(current) > 1:
            raise DatabaseError("selected_current_pair_not_unique")
        if not current:
            return result
        link = current[0]
        actual = _snapshot(link)
        # Canonical field bytes preserve JSON type distinctions (True vs 1,
        # for example) that Python container equality would otherwise erase.
        changed = sorted(name for name in actual if _raw(actual[name]) != _raw(receipt["after"][name]))
        state = ("replacement_pk" if link.pk != receipt["link_id"]
                 else "same_pk_drifted" if changed else "same_pk_equal")
        result.update(current_pair_state=state, current_link_id=link.pk,
                      current_manual_state=link.status if link.status in {"manual", "removed"} else "none",
                      current_sha256=hashlib.sha256(_raw(actual)).hexdigest(),
                      changed_fields=changed, current_markers=_current_markers(link))
        return result
