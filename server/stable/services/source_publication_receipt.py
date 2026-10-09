"""私有 v2 publication 材料 codec；DB 标记不代表新增来源认证或权限。"""
from datetime import datetime
import json

EVIDENCE_MAX_BYTES = 4096
STRING_FIELDS = frozenset({"source", "method", "source_url", "timezone", "raw", "previous_published_at"})
EVIDENCE_FIELDS = STRING_FIELDS | {"repair_run_id", "verified"}


class PublicationReceiptInvalid(ValueError):
    pass


def _invalid(reason="publication_evidence_invalid"):
    raise PublicationReceiptInvalid(reason)


def _utf8(value):
    try:
        return value.encode("utf-8")
    except UnicodeError as exc:
        raise PublicationReceiptInvalid("publication_evidence_invalid") from exc


def validate_evidence(value):
    # Flat builtin object: no arrays/nested controls/custom hooks/implicit coercions.
    if type(value) is not dict or len(value) > 8 or any(type(k) is not str for k in value):
        _invalid()
    if set(value) - EVIDENCE_FIELDS:
        _invalid()
    for key, item in value.items():
        if key in STRING_FIELDS:
            if type(item) is not str:
                _invalid()
            if len(item) > 512 or len(_utf8(item)) > 1024:
                _invalid("publication_evidence_oversized")
        elif key == "repair_run_id":
            if type(item) is not int or not 0 <= item < 2**63:
                _invalid()
        elif item is not None and type(item) is not bool:
            _invalid()
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PublicationReceiptInvalid("publication_evidence_invalid") from exc
    if len(encoded) > EVIDENCE_MAX_BYTES:
        _invalid("publication_evidence_oversized")
    return value


def decode_projection(encoded):
    # SQL Substr(Cast(JSONField AS text), 1, MAX+1) bounds transfer before decoding.
    if type(encoded) is not str:
        _invalid()
    if len(_utf8(encoded)) > EVIDENCE_MAX_BYTES:
        _invalid("publication_evidence_oversized")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                _invalid()
            value[key] = item
        return value
    try:
        return validate_evidence(json.loads(encoded, object_pairs_hook=unique))
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        if isinstance(exc, PublicationReceiptInvalid):
            raise
        raise PublicationReceiptInvalid("publication_evidence_invalid") from exc


def validate_receipt(value):
    if type(value) is not dict or set(value) != {"published_at", "verified", "evidence_status", "evidence"}:
        _invalid()
    if value["verified"] is not None and type(value["verified"]) is not bool:
        _invalid()
    stamp = value["published_at"]
    if type(stamp) is not str or len(stamp) > 64:
        _invalid()
    try:
        published = datetime.fromisoformat(stamp)
        if published.utcoffset() is None or published.isoformat() != stamp:
            _invalid()
    except (ValueError, TypeError) as exc:
        raise PublicationReceiptInvalid("publication_evidence_invalid") from exc
    evidence = validate_evidence(value["evidence"])
    if type(value["evidence_status"]) is not str or value["evidence_status"] != ("projected" if evidence else "empty"):
        _invalid()
    return value


def from_projection(published_at, verified, encoded):
    if type(published_at) is not datetime:
        _invalid()
    evidence = decode_projection(encoded)
    return validate_receipt({"published_at": published_at.isoformat(), "verified": verified,
                             "evidence_status": "projected" if evidence else "empty", "evidence": evidence})
