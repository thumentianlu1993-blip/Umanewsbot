"""单赛事匿名结果的内部只读快照；永不签发公开来源/响应/SLA proof。"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone as dt_timezone
import hashlib
import json
import re

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from stable import models as m
from stable.services import race_events

MAX_ROWS = 200
MAX_BYTES = 256 * 1024
_PATH = re.compile(r"/races/[0-9]{4}/[a-zA-Z0-9_-]{1,160}/\Z")


@dataclass(frozen=True)
class PublicResultRow:
    participant_id: int
    external_runner_id: str
    finish_position: int
    horse_name: str
    jockey_name: str
    horse_number: str
    official_finish_position: int | None
    is_confirmed: bool
    finish_time: str
    margin: str
    barrier: str
    trainer_name: str
    carried_weight: str
    running_status: str


@dataclass(frozen=True)
class PublicResultReadSnapshot:
    status: str
    reason: str
    event_id: int
    canonical_subject: str
    as_of: datetime
    snapshot_started_at: datetime
    snapshot_finished_at: datetime
    revalidated_at: datetime | None = None
    revision_id: int | None = None
    content_sha256: str = ""
    rows: tuple[PublicResultRow, ...] = ()
    version_fence: str = ""
    missing: tuple[str, ...] = ("source_proof_unbound", "execution_unbound", "f01_generations_unbound", "clock_unknown")
    real_source_proof: str = "unverified"
    response_binding: str = "unverified"
    sla: str = "unverified"
    projection_complete: bool = False


class _TooLarge(ValueError):
    pass


def _bytes(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v)).encode()
    if len(data) > MAX_BYTES:
        raise _TooLarge()
    return data


def _records(queryset):
    # 围栏仅在内部哈希，不返回模型或任意 raw/审计人数据；查询严格有界。
    excluded = {"raw_payload", "raw_artifact_path", "reviewed_by", "applied_by", "created_by"}
    fields = [f.attname for f in queryset.model._meta.concrete_fields if f.name not in excluded]
    values = list(queryset.order_by("pk").values(*fields)[:MAX_ROWS + 1])
    if len(values) > MAX_ROWS:
        raise _TooLarge()
    _bytes(values)
    return values


def _read_fence(event_id, as_of):
    """每次从数据库及现有可信 settings/policy loader 新读，禁止缓存 ORM。"""
    event = m.RaceEvent.objects.filter(pk=event_id).first()
    control = m.RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    revision_id = control.current_result_revision_id if control else None
    sources = m.RaceResultSourceIdentity.objects.filter(event_id=event_id)
    source_keys = list(sources.values_list("source_key", flat=True)[:MAX_ROWS + 1])
    scopes = Q(scope_type="global", scope_key="global") | Q(scope_type="event", scope_key=str(event_id))
    if event:
        scopes |= Q(scope_type="region", scope_key=event.country_region)
    scopes |= Q(scope_type="source", scope_key__in=source_keys)
    revision = m.RaceEventRevision.objects.filter(pk=revision_id).first()
    queries = [m.RaceEvent.objects.filter(pk=event_id),
        m.RaceEventPublicPath.objects.filter(event_id=event_id),
        m.RaceEventProductCanonicalLink.objects.filter(Q(duplicate_event_id=event_id)|Q(canonical_event_id=event_id)),
        m.RaceEventProjectionControl.objects.filter(event_id=event_id),
        m.RaceEventRevision.objects.filter(pk=revision_id),
        m.RaceEventRevisionPublication.objects.filter(revision_id=revision_id),
        m.RaceEventRevisionItem.objects.filter(revision_id=revision_id),
        m.RaceResultObservation.objects.filter(pk=revision.primary_observation_id if revision else None),
        sources, m.RaceEventParticipant.objects.filter(event_id=event_id),
        m.RaceEventParticipantSourceIdentity.objects.filter(participant__event_id=event_id),
        m.RaceEventResult.objects.filter(event_id=event_id),
        m.RaceLivePublicationPolicy.objects.filter(scopes),
        m.RaceLiveEventPublicationAllowlist.objects.filter(event_id=event_id),
        m.RaceLiveOfficialPublicationAuthorization.objects.filter(event_id=event_id),
        m.RaceDataSyncEnrollment.objects.filter(event_id=event_id),
        m.RaceDataSyncSourceBinding.objects.filter(enrollment__event_id=event_id),
        m.RaceEventLifecycleControl.objects.filter(event_id=event_id),
        m.RaceEventLifecycleEnforceMembership.objects.filter(event_id=event_id)]
    rows = [(q.model.__name__, _records(q)) for q in queries]
    # 配置和文件资格沿现有 loader，绝不接受 request 路径或自行读取 artifact。
    config = {name: getattr(settings, name) for name in dir(settings) if name.startswith(
        ("RACE_LIVE_", "RACE_DATA_SYNC_", "RACE_DATA_MULTISOURCE_", "RACE_EVENT_LIFECYCLE_"))}
    policy = race_events._load_race_data_sync_standing_policy()
    decision = race_events.resolve_race_live_public_read(event_id=event_id, now=as_of)
    return hashlib.sha256(_bytes((rows, config, policy, decision))).hexdigest()


def _materialize(event_id, canonical_subject, as_of):
    started = timezone.now()
    snapshot = PublicResultReadSnapshot("unverified", "missing_lineage", event_id, canonical_subject, as_of, started, started)
    fence = _read_fence(event_id, as_of)
    event = m.RaceEvent.objects.filter(pk=event_id).first()
    if not event or event.visibility_status != "published":
        return replace(snapshot, status="not_public", reason="event_not_public", version_fence=fence)
    canonical = m.RaceEventPublicPath.objects.filter(event_id=event_id, path_kind="canonical").first()
    if not canonical or reverse("public-race-detail", kwargs={"year":canonical.year,"slug":canonical.slug}) != canonical_subject:
        return replace(snapshot, reason="canonical_unbound", version_fence=fence)
    if m.RaceEventProductCanonicalLink.objects.filter(duplicate_event_id=event_id, is_active=True).exists():
        return replace(snapshot, reason="canonical_unbound", version_fence=fence)
    gate = race_events.resolve_race_live_public_read(event_id=event_id, now=as_of)
    if not gate.visible:
        incomplete = gate.reason in {"control_missing", "current_result_revision_missing", "primary_observation_missing", "source_identity_missing", "publication_audit_missing"}
        return replace(snapshot, status="unverified" if incomplete else "not_public", reason=gate.reason, version_fence=fence)
    revision = m.RaceEventRevision.objects.select_related("primary_observation__source_identity").get(pk=gate.revision_id)
    observation = revision.primary_observation
    source = observation.source_identity
    # 存储 hash 与 normalized 原文也须一致，hash 字段不能独自冒充内容。
    if race_events.build_race_live_canonical_sha256(normalized_payload=observation.normalized_payload) != revision.content_sha256:
        return replace(snapshot, reason="observation_content_mismatch", version_fence=fence)
    items = list(m.RaceEventRevisionItem.objects.filter(revision=revision).select_related("participant").order_by("internal_order")[:MAX_ROWS + 1])
    results = list(m.RaceEventResult.objects.filter(event_id=event_id).order_by("finish_position", "pk")[:MAX_ROWS + 1])
    identities = list(m.RaceEventParticipantSourceIdentity.objects.filter(source_identity=source,
        participant__event_id=event_id).values_list("external_runner_id", "participant_id")[:MAX_ROWS + 1])
    if any(len(x) > MAX_ROWS for x in (items, results, identities)):
        raise _TooLarge()
    identity_map = dict(identities)
    item_map = {item.participant_id:item for item in items}
    if len(identity_map) != len(identities) or len(item_map) != len(items) or len(items) != len(results) or not items:
        return replace(snapshot, reason="ambiguous_row_identity", version_fence=fence)
    rows = []; seen = set()
    for result in results:
        refs = result.source_refs if isinstance(result.source_refs, dict) else {}
        runner = refs.get("external_runner_id")
        participant_id = identity_map.get(runner) if isinstance(runner, str) and runner else None
        item = item_map.get(participant_id)
        if refs.get("source_key") != source.source_key or refs.get("external_race_id") != source.external_race_id or not item or participant_id in seen:
            return replace(snapshot, reason="ambiguous_row_identity", version_fence=fence)
        seen.add(participant_id)
        equal_fields = ("official_finish_position", "horse_number", "jockey_name", "trainer_name", "finish_time", "margin", "barrier", "carried_weight")
        if (item.participant.event_id != event_id or result.horse_name != item.participant.canonical_name
            or result.running_status != item.status or result.finish_position != item.internal_order
            or any(getattr(result,k) != getattr(item,k) for k in equal_fields)):
            return replace(snapshot, reason="projection_mismatch", version_fence=fence)
        rows.append(PublicResultRow(participant_id,runner,result.finish_position,result.horse_name,result.jockey_name,
            result.horse_number,result.official_finish_position,result.is_confirmed,result.finish_time,result.margin,
            result.barrier,result.trainer_name,result.carried_weight,result.running_status))
    missing = snapshot.missing + (("source_time_unknown",) if observation.source_updated_at is None else ())
    _bytes([r.__dict__ for r in rows])
    return replace(snapshot, status="read_boundary_loaded",reason="read_boundary_loaded",revision_id=revision.pk,
        content_sha256=revision.content_sha256,rows=tuple(rows),missing=missing,version_fence=fence,snapshot_finished_at=timezone.now())


def _begin_read():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")


def load_public_result_snapshot(*, event_id, canonical_subject, audience, as_of):
    if type(event_id) is not int or event_id <= 0 or audience != "anonymous" or not isinstance(as_of, datetime) or timezone.is_naive(as_of):
        raise ValueError("invalid public result scope")
    if not isinstance(canonical_subject,str) or not _PATH.fullmatch(canonical_subject):
        raise ValueError("invalid canonical subject")
    as_of = as_of.astimezone(dt_timezone.utc)
    now = timezone.now()
    empty = PublicResultReadSnapshot("unverified","outer_transaction_unsupported",event_id,canonical_subject,as_of,now,now)
    if connection.in_atomic_block or not connection.get_autocommit():
        return empty
    if connection.vendor != "postgresql":
        return replace(empty,reason="postgresql_required")
    try:
        with transaction.atomic():
            _begin_read()  # 必须先于本事务第一条业务 SQL；不改变 session/global 隔离。
            snapshot = _materialize(event_id, canonical_subject, as_of)
        with transaction.atomic():
            _begin_read()  # 已退出旧 RR，重新获得可见 writer 提交的新快照。
            fence = _read_fence(event_id,timezone.now())
        checked = timezone.now()
        if snapshot.version_fence != fence:
            return replace(snapshot,status="unverified",reason="input_changed",rows=(),revalidated_at=checked)
        return replace(snapshot,revalidated_at=checked)
    except _TooLarge:
        return replace(empty,reason="snapshot_too_large")
