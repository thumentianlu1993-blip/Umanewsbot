"""私有首次 pair 归档：只由强 writer 新 created 捕获，不提供历史补录。

行 guard 不认证同凭据 INSERT，也不阻止 owner TRUNCATE/DDL。无 TTL/非 FK
仅是隔离开发合同，不代表已批准生产保留、擦除或弱扫描器自动保护。
"""
from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import connection, models
from django.utils import timezone

from stable.models import (
    ArticleHorseLink, HorseArticlePairReceiptIndex, HorseProfile, NewsArticle, OperationLog,
)
from stable.services.horse_article_binding_diagnostics import _validated_receipt
from stable.services.horse_article_binding_persistence import (
    ACTION, TARGET, HASH, MAX_BYTES, _PARSE_ERRORS, _raw, _sha, _snapshot,
)


INDEX_PROTOCOL = "l02.pair-receipt-index.v1"
INDEX_UNIQUES = frozenset((
    "uq_horse_pair_receipt_pair", "uq_horse_pair_receipt_key", "uq_horse_pair_receipt_log",
))
_REFERENCES = (
    "index_id", "request_key", "operation_log_id", "original_link_id", "original_actor_id",
    "receipt_detail_sha256", "after_sha256",
)
_HEADER = (
    "id", "article_id_snapshot", "profile_id_snapshot", "producer_namespace", "request_id",
    "request_key", "operation_log_id_snapshot", "original_link_id", "original_actor_id",
    "receipt_detail_sha256", "protocol_version", "recorded_at",
)


class PairHistoryInputError(ValueError):
    """精确 pair 必须由两个正整数 PK 指定。"""


class PairReceiptCaptureError(ValueError):
    """实际新 receipt 或其绑定不成立，整笔新写必须回滚。"""


def _positive(value):
    return type(value) is int and 0 < value <= 9_223_372_036_854_775_807


def _stored(condition):
    if not condition:
        raise ValueError("invalid_pair_receipt_archive")


def _length(field):
    return models.Func(models.F(field), function="OCTET_LENGTH", output_field=models.BigIntegerField())


def _key(namespace, request_id):
    for value in (namespace, request_id):
        _stored(type(value) is str and 0 < len(value) <= 255)
    return _sha(_raw(dict(schema="l01.horse-link-request.v1",
                          producer_namespace=namespace, request_id=request_id)))


def _validate_archive(row, detail, article_id, profile_id):
    """纯历史字节校验；历史 actor/log PK 不通过 live 实体重新认证。"""
    for name in ("article_id_snapshot", "profile_id_snapshot", "operation_log_id_snapshot",
                 "original_link_id", "original_actor_id"):
        _stored(_positive(row[name]))
    _stored(row["article_id_snapshot"] == article_id and row["profile_id_snapshot"] == profile_id)
    _stored(row["protocol_version"] == INDEX_PROTOCOL)
    _stored(row["recorded_at"] is not None and timezone.is_aware(row["recorded_at"]))
    for name in ("request_key", "receipt_detail_sha256"):
        _stored(type(row[name]) is str and HASH.fullmatch(row[name]) is not None)
    _stored(row["request_key"] == _key(row["producer_namespace"], row["request_id"]))
    _stored(type(detail) is str)
    data = detail.encode("utf-8")
    _stored(0 < len(data) <= MAX_BYTES and _sha(data) == row["receipt_detail_sha256"])
    # Reuse only the existing pure validator. Its row object contains historical
    # admin identity, deliberately not a live OperationLog/User lookup.
    receipt = _validated_receipt(SimpleNamespace(detail=detail, admin_id=row["original_actor_id"]))
    for name, value in {
        "request_key": row["request_key"], "article_id": article_id, "profile_id": profile_id,
        "link_id": row["original_link_id"], "actor_id": row["original_actor_id"],
    }.items():
        _stored(type(receipt[name]) is type(value) and receipt[name] == value)
    return receipt


def _has_indexed_conflict(article_id, profile_id, request_key):
    """仅新 created 前调用；任何已有 pair/K 档案均不释放或覆盖。"""
    index = HorseArticlePairReceiptIndex.objects.using(connection.alias)
    return (index.filter(article_id_snapshot=article_id, profile_id_snapshot=profile_id).exists()
            or index.filter(request_key=request_key).exists())


def _capture_created_receipt(scope, actor, article, profile, link, log):
    """在原 writer atomic 内验证实际新 PK 原件，并返回实际归档 ORM 实例。

    调用域与数据库凭据仍是信任边界；私有函数名不构成防伪授权。
    DB/driver 错误原样外抛；结构错误用稳定异常使整组新写回滚。
    """
    try:
        _stored(connection.in_atomic_block and not connection.get_autocommit())
        for instance, model in ((actor, get_user_model()), (article, NewsArticle), (profile, HorseProfile),
                                (link, ArticleHorseLink), (log, OperationLog)):
            _stored(isinstance(instance, model) and _positive(instance.pk)
                    and not instance._state.adding and instance._state.db == connection.alias)
        _stored(type(scope) is dict)
        key = _key(scope["producer_namespace"], scope["request_id"])
        _stored(actor.is_authenticated and actor.is_active and actor.is_staff
                and type(scope["actor_ids"]) is list
                and any(type(value) is int and value == actor.pk for value in scope["actor_ids"]))
        _stored(type(scope["article_id"]) is int and scope["article_id"] == article.pk
                and type(scope["profile_id"]) is int and scope["profile_id"] == profile.pk)
        # Bound the actual stored TEXT before fetching it; never reconstruct an
        # archive only from the Python instance used by INSERT.
        logs = OperationLog.objects.using(connection.alias).filter(pk=log.pk)
        header = logs.annotate(detail_bytes=_length("detail")).values(
            "id", "admin_id", "action_type", "target_type", "target_id", "detail_bytes").get()
        _stored(header["action_type"] == ACTION and header["target_type"] == TARGET
                and header["target_id"] == key and header["admin_id"] == actor.pk)
        _stored(type(header["detail_bytes"]) is int and 0 < header["detail_bytes"] <= MAX_BYTES)
        actual_log = logs.get()
        _stored(actual_log.action_type == log.action_type == ACTION
                and actual_log.target_type == log.target_type == TARGET
                and actual_log.target_id == log.target_id == key
                and actual_log.admin_id == log.admin_id == actor.pk
                and actual_log.detail == log.detail)
        _stored(type(actual_log.detail) is str)
        record = dict(article_id_snapshot=article.pk, profile_id_snapshot=profile.pk,
            producer_namespace=scope["producer_namespace"], request_id=scope["request_id"], request_key=key,
            operation_log_id_snapshot=actual_log.pk, original_link_id=link.pk, original_actor_id=actor.pk,
            receipt_detail=actual_log.detail, receipt_detail_sha256=_sha(actual_log.detail.encode("utf-8")),
            protocol_version=INDEX_PROTOCOL, recorded_at=timezone.now())
        receipt = _validate_archive(record, record["receipt_detail"], article.pk, profile.pk)
        _stored(type(scope["identity_id"]) is int and receipt["identity_id"] == scope["identity_id"])
        _stored(receipt["payload_sha256"] == scope["bundle_sha256"])
        actual_link = ArticleHorseLink.objects.using(connection.alias).get(pk=link.pk)
        _stored(_raw(receipt["after"]) == _raw(_snapshot(link)) == _raw(_snapshot(actual_link)))
        _stored(receipt["article_id"] == article.pk and receipt["profile_id"] == profile.pk)
    except (*_PARSE_ERRORS, OperationLog.DoesNotExist, ArticleHorseLink.DoesNotExist) as error:
        raise PairReceiptCaptureError("invalid_new_pair_receipt") from error
    # No inner savepoint or IntegrityError conversion here: the caller must
    # roll back link + log + index together before classifying a unique conflict.
    return HorseArticlePairReceiptIndex.objects.using(connection.alias).create(**record)


def _result(article_id, profile_id):
    return dict(schema_version="l02.pair-receipt-history.v1", state="UNKNOWN_NO_INDEX",
        article_id=article_id, profile_id=profile_id, **dict.fromkeys(_REFERENCES),
        weak_mutation_allowed=False, historical_coverage="indexed_receipt_only",
        historical_request_uniqueness="not_proved", current_write_authority="not_evaluated",
        source_license="not_evaluated", automatic_action="none")


def classify_pair_receipt_history(article_id, profile_id):
    """只读精确 pair 档案，最多两行；UNKNOWN 永不提供写许可。

    不读取 live log/link/actor、registry 或 TTL，不修复、不补账。普通行
    guard 下原件不可变；owner/DDL 破坏不属于生产不可变保证。技术错误不吞。
    """
    if not _positive(article_id) or not _positive(profile_id):
        raise PairHistoryInputError("positive_pair_ids_required")
    result = _result(article_id, profile_id)
    pair = HorseArticlePairReceiptIndex.objects.using(connection.alias).filter(
        article_id_snapshot=article_id, profile_id_snapshot=profile_id)
    headers = list(pair.annotate(detail_bytes=_length("receipt_detail")).order_by("pk")
                   .values(*_HEADER, "detail_bytes")[:2])
    if not headers:
        return result
    if len(headers) != 1:
        result["state"] = "UNKNOWN_CONFLICT"
        return result
    header = headers[0]
    size = header["detail_bytes"]
    if type(size) is not int or not 0 < size <= MAX_BYTES:
        result["state"] = "UNKNOWN_CORRUPT_OR_UNSUPPORTED"
        return result
    # Repeat the exact pair and upper byte bound in the second SELECT; even an
    # owner mutation between reads cannot cause an oversized TEXT fetch.
    records = list(pair.filter(pk=header["id"]).annotate(detail_bytes=_length("receipt_detail"))
                   .filter(detail_bytes__gt=0, detail_bytes__lte=MAX_BYTES).order_by("pk")
                   .values(*_HEADER, "receipt_detail")[:2])
    if len(records) != 1:
        result["state"] = "UNKNOWN_CONFLICT"
        return result
    row = records[0]
    try:
        _stored(_positive(row["id"]))
        _stored(all(row[name] == header[name] for name in _HEADER))
        receipt = _validate_archive(row, row["receipt_detail"], article_id, profile_id)
    except _PARSE_ERRORS:
        result["state"] = "UNKNOWN_CORRUPT_OR_UNSUPPORTED"
        return result
    result.update(state="INDEXED_HISTORY", index_id=row["id"], request_key=row["request_key"],
        operation_log_id=row["operation_log_id_snapshot"], original_link_id=row["original_link_id"],
        original_actor_id=row["original_actor_id"], receipt_detail_sha256=row["receipt_detail_sha256"],
        after_sha256=receipt["after_sha256"])
    return result
