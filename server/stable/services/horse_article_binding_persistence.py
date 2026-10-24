"""内部单pair机制；默认无注册handle，无公开入口或生产来源许可。

设置由受信调用域提供，不接受HTTP/任务参数注册。OperationLog仅为服务协议
receipt，非授权registry。父锁仅串行化合作adapter，历史保留须由调用域保证。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from stable.models import ArticleHorseLink, HorseExternalIdentity, HorseProfile, NewsArticle, OperationLog
from stable.services import content_contracts as f01
from stable.services.article_entity_binding import BindingInputError, plan_article_entity_bindings

MAX_BYTES = 4_194_304
ACTION = "horse_binding_committed"
TARGET = "horse_binding_request"
SOURCE = "strong_identity.v1"
HASH = re.compile(r"[0-9a-f]{64}\Z")
_SCOPE_KEYS = frozenset(("bundle_path", "bundle_sha256", "producer_namespace", "request_id", "article_id",
    "profile_id", "identity_id", "actor_ids", "not_before", "expires_at", "revoked", "contract_refs", "responsibility"))
_BUNDLE_KEYS = frozenset(("schema_version", "producer_namespace", "request_id", "payload_revision", "article_id",
    "profile_id", "identity_id", "expected", "resolution_payload", "article_input", "identity_inputs", "relation_inputs",
    "source_document_base64", "identity_artifact_base64", "relationship_artifacts_base64", "contexts"))
_RECEIPT_KEYS = frozenset(("schema_version", "request_key", "payload_sha256", "payload_revision", "article_id",
    "profile_id", "identity_id", "provider_ref", "decision_sha256", "link_id", "before", "after", "after_sha256", "actor_id"))


class BindingAdmissionError(ValueError):
    """Only stable codes leave the internal admission boundary."""


def _require(value):
    if not value:
        raise BindingAdmissionError("binding_admission")


def _raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _pairs(values):
    result = {}
    for key, value in values:
        _require(key not in result)
        result[key] = value
    return result


def _read(data):
    _require(type(data) is bytes and len(data) <= MAX_BYTES)
    result = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                        parse_constant=lambda _: _require(False))
    _require(_raw(result) == data)
    return result


def _time(value):
    _require(type(value) is str)
    result = datetime.fromisoformat(value)
    _require(result.tzinfo is not None and result.utcoffset() is not None)
    return result


def _id(value):
    _require(type(value) is int and value > 0)
    return value


def _text(value):
    _require(type(value) is str and 0 < len(value) <= 255)
    return value


def _decoded(value):
    _require(type(value) is str and len(value) <= MAX_BYTES)
    data = base64.b64decode(value, validate=True)
    _require(base64.b64encode(data).decode("ascii") == value)
    return data


def _snapshot(instance):
    def encoded(value):
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise BindingAdmissionError("snapshot_type")
    return json.loads(json.dumps({f.attname: getattr(instance, f.attname) for f in instance._meta.concrete_fields},
                                 default=encoded, ensure_ascii=False, allow_nan=False))


def _bundle_file(scope):
    path = Path(scope["bundle_path"])
    _require(path.is_absolute() and type(scope["bundle_sha256"]) is str and HASH.fullmatch(scope["bundle_sha256"]))
    # The configured parent directory is part of the server-owned trust boundary.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022)
        _require(info.st_size <= MAX_BYTES)
        data = stream.read(MAX_BYTES + 1)
    _require(len(data) <= MAX_BYTES and _sha(data) == scope["bundle_sha256"])
    return _read(data), _sha(data)


def _admit(handle_id, actor):
    """Re-read server configuration and actual user. No caller-supplied permit."""
    _require(type(handle_id) is str and 0 < len(handle_id) <= 128)
    registry = getattr(settings, "HORSE_ARTICLE_BINDING_HANDLES", {})
    _require(type(registry) is dict and handle_id in registry)
    # Detached value, not a writable alias into configuration.
    scope = _read(_raw(registry[handle_id]))
    _require(type(scope) is dict and set(scope) == _SCOPE_KEYS)
    _require(scope["revoked"] is False)
    _text(scope["producer_namespace"]); _text(scope["request_id"])
    for peer in registry.values():
        if (type(peer) is dict and peer.get("producer_namespace") == scope["producer_namespace"]
                and peer.get("request_id") == scope["request_id"]):
            # A logical request must never acquire two different parent locks.
            _require(all(peer.get(name) == scope[name] and type(peer.get(name)) is int
                         for name in ("article_id", "profile_id", "identity_id")))
    for name in ("article_id", "profile_id", "identity_id"):
        _id(scope[name])
    _require(type(scope["actor_ids"]) is list and bool(scope["actor_ids"]))
    for actor_id in scope["actor_ids"]:
        _id(actor_id)
    _require(getattr(actor, "is_authenticated", False) and type(getattr(actor, "pk", None)) is int)
    current_actor = get_user_model().objects.get(pk=actor.pk)
    _require(current_actor.is_active and current_actor.is_staff and current_actor.pk in scope["actor_ids"])
    now = timezone.now()
    _require(_time(scope["not_before"]) <= now < _time(scope["expires_at"]))
    owners = scope["responsibility"]
    _require(type(owners) is dict and set(owners) == {"identity_producer", "relationship_owner", "write_owner"})
    for value in owners.values():
        _text(value)
    _require(type(scope["contract_refs"]) is list and bool(scope["contract_refs"]))
    bundle, digest = _bundle_file(scope)
    _require(type(bundle) is dict and set(bundle) == _BUNDLE_KEYS)
    _require(bundle["schema_version"] == "l01.horse-link-bundle.v1")
    for name in ("producer_namespace", "request_id", "article_id", "profile_id", "identity_id"):
        _require(type(bundle[name]) is type(scope[name]) and bundle[name] == scope[name])
    _id(bundle["payload_revision"])
    _require(type(bundle["expected"]) is dict and set(bundle["expected"]) == {"article", "profile", "identity", "pair"})
    _require(all(type(bundle["expected"][name]) is dict for name in ("article", "profile", "identity")))
    _require(type(bundle["identity_inputs"]) is list and len(bundle["identity_inputs"]) == 1)
    _require(type(bundle["relation_inputs"]) is list and len(bundle["relation_inputs"]) == 1)
    _require(type(bundle["contexts"]) is list and len(bundle["contexts"]) == 1)
    _require(type(bundle["relationship_artifacts_base64"]) is dict and len(bundle["relationship_artifacts_base64"]) == 1)
    for doc in [bundle["article_input"], *bundle["identity_inputs"], *bundle["relation_inputs"]]:
        for evidence in doc["snapshot"]["evidence"]:
            contract = evidence["contract_ref"]
            _require(contract in scope["contract_refs"] and contract["revoked"] is False)
            _require(_time(evidence["observed_at"]) <= now < _time(contract["valid_until"]))
    key = _sha(_raw(dict(schema="l01.horse-link-request.v1", producer_namespace=scope["producer_namespace"],
                         request_id=scope["request_id"])))
    return scope, bundle, digest, key, current_actor


def _identity_current(bundle, identity):
    _require(identity.status == "verified" and identity.horse_profile_id == bundle["profile_id"])
    _require(identity.verified_by_id is not None and identity.verified_at is not None and identity.evidence_url)
    material = _decoded(bundle["identity_artifact_base64"])
    provider = dict(source=identity.source, namespace=identity.namespace, external_id=identity.external_id)
    _require(_read(material) == {**provider, "horse_profile_id": identity.horse_profile_id})
    _require(identity.payload_sha256 == _sha(material))
    doc = bundle["identity_inputs"][0]
    _require(doc["snapshot"]["entity"]["source_refs"] == [provider])
    _require(any(e["capability"] == "identity" and e["artifact_sha256"] == identity.payload_sha256
                 and e["locator"] == "/external_id"
                 for e in doc["snapshot"]["evidence"]))
    return provider


def _decision(bundle, provider):
    article = f01.parse_input(_raw(bundle["article_input"]).decode("utf-8"))
    identities = [f01.parse_input(_raw(value).decode("utf-8")) for value in bundle["identity_inputs"]]
    relations = [f01.parse_input(_raw(value).decode("utf-8")) for value in bundle["relation_inputs"]]
    _require(article.to_dict()["snapshot"]["entity"]["canonical_id"] == "article:"+str(bundle["article_id"]))
    _require(identities[0].to_dict()["snapshot"]["entity"]["canonical_id"] == "horse:"+str(bundle["profile_id"]))
    artifacts = {}
    for digest, value in bundle["relationship_artifacts_base64"].items():
        _require(type(digest) is str and HASH.fullmatch(digest))
        data = _decoded(value)
        _require(_sha(data) == digest)
        artifacts[digest] = data
    source = _decoded(bundle["source_document_base64"])
    result = plan_article_entity_bindings(bundle["resolution_payload"], article_input=article, identity_inputs=identities,
        relation_inputs=relations, source_document=source, relationship_artifacts=artifacts, contexts=bundle["contexts"])
    _require(not result["candidates"] and len(result["proposed_bindings"]) == 1)
    proposal = result["proposed_bindings"][0]
    _require(proposal["role"] == "horse_subject" and proposal["target"]["kind"] == "horse")
    _require(proposal["target"]["canonical_id"] == "horse:"+str(bundle["profile_id"]))
    _require(proposal["target"]["source_ref"] == provider)
    return result, proposal


def _inputs_match(bundle, article, profile, identity):
    expected = bundle["expected"]
    if any(_snapshot(instance) != expected[name] for name, instance in
           (("article", article), ("profile", profile), ("identity", identity))):
        return False
    source = _read(_decoded(bundle["source_document_base64"]))
    if source != {"title": article.title_ja, "body": article.body_ja_normalized or article.body_ja_raw}:
        return False
    if bundle["resolution_payload"] != (article.translation_metadata or {}).get("article_entity_resolution"):
        return False
    return (article.workflow_status == "published" and article.published_to_web_at is not None
            and profile.review_status == "published" and bundle["resolution_payload"]["source_language"] ==
            (article.source_language or "ja"))


def _receipt(rows, key, bundle, payload_sha, provider):
    if not rows:
        return None
    _require(len(rows) == 1)
    row = rows[0]
    receipt = _read(row.detail.encode("utf-8"))
    _require(type(receipt) is dict and set(receipt) == _RECEIPT_KEYS)
    wanted = dict(schema_version="l01.horse-link-receipt.v1", request_key=key, payload_sha256=payload_sha,
        payload_revision=bundle["payload_revision"], article_id=bundle["article_id"], profile_id=bundle["profile_id"],
        identity_id=bundle["identity_id"], provider_ref=provider, before="absent")
    for name, value in wanted.items():
        _require(type(receipt[name]) is type(value) and receipt[name] == value)
    _id(receipt["link_id"]); _id(receipt["actor_id"])
    _require(type(receipt["decision_sha256"]) is str and HASH.fullmatch(receipt["decision_sha256"]))
    _require(row.admin_id == receipt["actor_id"])
    _require(type(receipt["after"]) is dict and receipt["after_sha256"] == _sha(_raw(receipt["after"])))
    _require(set(receipt["after"]) == {f.attname for f in ArticleHorseLink._meta.concrete_fields})
    _require(receipt["after"]["id"] == receipt["link_id"] and receipt["after"]["article_id"] == bundle["article_id"]
             and receipt["after"]["horse_profile_id"] == bundle["profile_id"] and receipt["after"]["status"] == "auto"
             and receipt["after"]["source"] == SOURCE)
    metadata = receipt["after"]["metadata"]
    _require(type(metadata) is dict and metadata.get("schema_version") == "l01.horse-link-metadata.v1")
    for name, value in {"request_key": key, "payload_sha256": payload_sha,
                        "provider_ref": provider, "decision_sha256": receipt["decision_sha256"]}.items():
        _require(metadata.get(name) == value)
    return row, receipt


def _result(status, link=None, receipt=None):
    result = {"status": status}
    if link is not None:
        result["link_id"] = link.pk
    if receipt is not None:
        row, value = receipt
        result.update(link_id=value["link_id"], receipt_id=row.pk)
    return result


def _classify(link, receipt, matches):
    if link is not None and link.status in {"manual", "removed"}:
        return _result("protected_current", link, receipt)
    if receipt is not None:
        old = receipt[1]
        if link is None:
            return _result("historical_applied_missing", receipt=receipt)
        same = link.pk == old["link_id"] and _snapshot(link) == old["after"]
        return _result("replayed" if same and matches else "historical_applied_drifted", receipt=receipt)
    if link is not None:
        return _result("existing_pair_conflict", link)
    if not matches:
        return _result("stale_first_apply")
    return None


# Parsing failures are admission/decision rejections; database errors are never
# swallowed into a business result. No logger writes on rejection or replay.
_PARSE_ERRORS = (BindingAdmissionError, BindingInputError, ValueError, TypeError, KeyError,
                 UnicodeError, RecursionError, OverflowError, binascii.Error)


def commit_strong_horse_binding(handle_id, actor):
    """Internal mechanism only. No registry default, HTTP adapter or scheduler.

    Current authority is re-read under the parent lock. Settings/file ownership
    and retained receipts are server-domain assumptions, not a production grant
    or a claim of atomic revocation by nonparticipating identity/permission writers.
    """
    try:
        initial = _admit(handle_id, actor)
    except (*_PARSE_ERRORS, OSError, get_user_model().DoesNotExist):
        return _result("blocked_current_authority")
    initial_scope, bundle, payload_sha, key, current_actor = initial
    with transaction.atomic():
        article = NewsArticle.objects.select_for_update().filter(pk=bundle["article_id"]).first()
        profile = HorseProfile.objects.select_for_update().filter(pk=bundle["profile_id"]).first()
        identity = HorseExternalIdentity.objects.select_for_update().filter(pk=bundle["identity_id"]).first()
        if article is None or profile is None or identity is None:
            return _result("blocked_current_authority")
        try:
            scope, current_bundle, current_sha, current_key, current_actor = _admit(handle_id, actor)
            _require(scope == initial_scope and current_bundle == bundle and current_sha == payload_sha and current_key == key)
            provider = _identity_current(bundle, identity)
        except (*_PARSE_ERRORS, OSError, get_user_model().DoesNotExist):
            return _result("blocked_current_authority")
        rows = list(OperationLog.objects.filter(action_type=ACTION, target_type=TARGET, target_id=key).order_by("pk"))
        try:
            receipt = _receipt(rows, key, bundle, payload_sha, provider)
        except _PARSE_ERRORS:
            return _result("history_conflict")
        pair = dict(article_id=article.pk, horse_profile_id=profile.pk)
        link = ArticleHorseLink.objects.select_for_update().filter(**pair).first()
        try:
            matches = _inputs_match(bundle, article, profile, identity)
        except _PARSE_ERRORS:
            matches = False
        state = _classify(link, receipt, matches)
        if state is not None and state["status"] != "replayed":
            return state
        if receipt is None and bundle["expected"]["pair"] != "absent":
            return _result("stale_first_apply")
        try:
            decision, proposal = _decision(bundle, provider)
        except _PARSE_ERRORS:
            return _result("historical_applied_drifted", receipt=receipt) if receipt else _result("blocked_decision")
        decision_sha = _sha(_raw(decision))
        if receipt is not None:
            if receipt[1]["decision_sha256"] != decision_sha:
                return _result("historical_applied_drifted", receipt=receipt)
            return state
        metadata = dict(schema_version="l01.horse-link-metadata.v1", request_key=key, payload_sha256=payload_sha,
            decision_sha256=decision_sha, provider_ref=provider, occurrence=proposal["occurrence"], evidence=proposal["evidence"])
        try:
            # Catch outside the savepoint; the outer transaction remains usable.
            with transaction.atomic():
                link = ArticleHorseLink.objects.create(**pair, status="auto", source=SOURCE, confidence=0,
                    matched_text=proposal["occurrence"]["matched_text"][:255], match_reason="bound horse_subject evidence",
                    metadata=metadata)
        except IntegrityError as error:
            if getattr(getattr(error.__cause__, "diag", None), "constraint_name", None) != "uq_article_horse_link":
                raise
            # Re-run current authority and history classification, never INSERT again.
            try:
                recovered = _admit(handle_id, actor)
                _require(recovered[0] == scope and recovered[2] == payload_sha)
                _identity_current(bundle, identity)
            except (*_PARSE_ERRORS, OSError, get_user_model().DoesNotExist):
                return _result("blocked_current_authority")
            rows = list(OperationLog.objects.filter(action_type=ACTION, target_type=TARGET, target_id=key).order_by("pk"))
            try:
                receipt = _receipt(rows, key, bundle, payload_sha, provider)
            except _PARSE_ERRORS:
                return _result("history_conflict")
            link = ArticleHorseLink.objects.select_for_update().filter(**pair).first()
            replay_matches = matches and (receipt is None or receipt[1]["decision_sha256"] == decision_sha)
            return _classify(link, receipt, replay_matches) or _result("concurrent_state_changed")
        after = _snapshot(link)
        data = dict(schema_version="l01.horse-link-receipt.v1", request_key=key, payload_sha256=payload_sha,
            payload_revision=bundle["payload_revision"], article_id=article.pk, profile_id=profile.pk,
            identity_id=identity.pk, provider_ref=provider, decision_sha256=decision_sha, link_id=link.pk,
            before="absent", after=after, after_sha256=_sha(_raw(after)), actor_id=current_actor.pk)
        # Failure here escapes: outer atomic rolls back both link and receipt.
        log = OperationLog.objects.create(admin=current_actor, action_type=ACTION, target_type=TARGET,
                                          target_id=key, detail=_raw(data).decode("utf-8"))
        return _result("created", link, (log, data))
