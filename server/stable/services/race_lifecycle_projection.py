"""P02 公开 epoch。复用现有来源/发布准入，不从候选名单授予权限。"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from stable import models
from stable.services.race_data_source_adapters import canonical_sha

KINDS = ("racecard", "result")
ATTRS = ("revision_id", "maturity", "visibility", "reason", "deadline_at", "evidence")


def cohort(event_id):
    return event_id in getattr(settings, "RACE_LIFECYCLE_V2_EVENT_IDS", ())


def writable(event_id):
    return cohort(event_id) and getattr(settings, "RACE_LIFECYCLE_V2_WRITE_ENABLED", False) is True


def governed(event_id):
    """一旦建立新状态，关闭 writer 后仍不得恢复时钟事实推断。"""
    return writable(event_id) or models.RaceLifecyclePublicState.objects.filter(event_id=event_id).exists()


def _policy_digest(enrollment, now):
    from stable.services.race_events import _load_race_data_sync_standing_policy_digest
    if enrollment and enrollment.authority_version == 2:
        from stable.services.race_data_source_adapters import load_multisource_policy
        return load_multisource_policy(now=now).digest
    digest = _load_race_data_sync_standing_policy_digest()
    if not digest:
        raise ValueError("epoch_policy_unavailable")
    return digest


def _snapshot(state):
    result = {"schedule_generation": state.schedule_generation, "policy_digest": state.policy_digest}
    for kind in KINDS:
        result[kind] = {}
        for attr in ATTRS:
            value = getattr(state, f"{kind}_{attr}")
            if attr == "deadline_at":
                value = value.isoformat() if value else None
            result[kind][attr] = value
    return result


def _result_authority(event, control, revision, observation, now, published_at, loaded=None):
    """使用当次 observation 与当前合同复验；不修改不可变 revision 的 primary 指针。"""
    from stable.services.race_events import _resolve_data_sync_publication_from_loaded_rows
    source = observation.source_identity
    if (source.event_id != event.pk or source.valid_until is None or source.valid_until <= now
            or source.identity_fields.get("publication_revoked")
            or source.identity_fields.get("identity_invalidated")):
        return False
    enrollment = loaded["enrollment"] if loaded is not None else models.RaceDataSyncEnrollment.objects.filter(event=event).first()
    if enrollment is None:
        return False
    provenance = observation.field_provenance
    publication = SimpleNamespace(
        reason="data_sync_result", published_at=published_at,
        authorization_kind="official_route", official_authorization_version=0,
        allowlist_version=2 if enrollment.authority_version == 2 else 1,
        registry_digest=provenance.get("registry_digest"),
        coverage_proof_digest=observation.normalized_sha256,
        policy_versions=[["race_data_sync_contract", provenance.get("contract_version"), 1]],
    )
    # 替代身份仅用于准入校验，展示内容仍来自真实不可变 revision。
    checked_revision = SimpleNamespace(
        pk=revision.pk, event_id=event.pk, kind="result", phase=observation.result_phase,
        primary_observation_id=observation.pk, source_authority=provenance.get("source_class"))
    if enrollment.authority_version == 2:
        from stable.services.race_data_source_adapters import load_multisource_policy
        from stable.services.race_data_sync_admission import binding_admission_reason
        policy = load_multisource_policy(now=now)
        binding = loaded["bindings"].get(source.pk) if loaded is not None else models.RaceDataSyncSourceBinding.objects.select_related(
            "source_identity__event", "enrollment").filter(
                enrollment=enrollment, source_identity=source, state="active").first()
        route = policy.route_for(dict(provider=source.source_key, region=source.region_code,
                                      identity_namespace=source.identity_namespace))
        if (not binding or enrollment.standing_policy_digest != policy.digest
                or binding_admission_reason(binding=binding, route=route, now=now,
                                            capability="result", check_runtime=False)):
            return False
    lifecycle = loaded["lifecycle"] if loaded is not None else models.RaceEventLifecycleControl.objects.filter(event=event).first()
    membership = loaded["membership"] if loaded is not None else models.RaceEventLifecycleEnforceMembership.objects.select_related("registry").filter(
        event=event, state="active", registry__state="active", registry__is_active=True).first()
    decision = _resolve_data_sync_publication_from_loaded_rows(
        event=event, control=control, revision=checked_revision,
        publication=publication, observation=observation, source=source,
        enrollment=enrollment, enrollment_source=enrollment.source_identity,
        lifecycle=lifecycle, lifecycle_membership=membership,
        standing_policy_digest=_policy_digest(enrollment, now), now=now,
        loaded_admission=loaded, allow_provisional=True,
        binding_retired=(source.pk in loaded["retired"]) if loaded is not None else None)
    return decision.visible


def _commit_state(*, state, control, now, reason):
    """调用方已经按既有锁图锁住 lifecycle/event/control；无网络 I/O。"""
    if not connection.in_atomic_block:
        raise ValueError("epoch_transaction_required")
    snapshot = _snapshot(state)
    digest = canonical_sha(snapshot)
    prior = models.RaceLifecycleEpochPublication.objects.filter(
        event_id=state.event_id, epoch=state.epoch).first() if state.pk else None
    if prior and prior.snapshot_sha256 == digest:
        return prior
    if prior:
        for kind in KINDS:
            _record_expired_publication(prior, kind, now)
    previous = state.epoch if state.pk else 0
    state.epoch = previous + 1
    key = canonical_sha(dict(previous_epoch=previous, snapshot=digest,
                             owner=control.owner_generation))
    authorization = dict(
        owner=control.write_owner, generation=control.owner_generation,
        manifest=control.owner_manifest_sha256, policy_digest=state.policy_digest)
    publication = models.RaceLifecycleEpochPublication.objects.create(
        event_id=state.event_id, epoch=state.epoch, previous_epoch=previous,
        schedule_generation=state.schedule_generation, idempotency_key=key,
        racecard_revision_id=state.racecard_revision_id, result_revision_id=state.result_revision_id,
        writer_owner=control.write_owner, writer_generation=control.owner_generation,
        snapshot=snapshot, snapshot_sha256=digest, authorization=authorization,
        admitted_at=now, published_at=now, reason=reason)
    state.save()
    from stable.services.race_lifecycle_metrics import load_input
    metric_input = load_input(state.event_id, now=now).to_dict()
    grade = str(state.event.normalized_grade or "").upper().replace("-", "")
    key_race = grade in ("G1", "GI", "JPN1", "JPNI", "JG1") or (state.event.source_refs or {}).get("lifecycle_priority") == "key"
    models.RaceLifecycleReceipt.objects.create(
        idempotency_key=canonical_sha(["publish", state.event_id, state.epoch]),
        target_key=f"canonical:{state.event_id}", event_id=state.event_id,
        kind="publish", schedule_generation=state.schedule_generation,
        epoch=state.epoch, occurred_at=now, recorded_at=now,
        payload={"snapshot": snapshot, "publication_id": publication.pk, "input": metric_input, "threshold_seconds": 300 if key_race else 600},
        evidence_refs=[f"epoch:{publication.pk}"])
    for consumer in ("cache", "probe"):
        models.RaceLifecycleDelivery.objects.create(
            event_id=state.event_id, epoch=state.epoch, consumer=consumer,
            next_attempt_at=now, payload_sha256=digest)
    if getattr(settings, "RACE_LIFECYCLE_DELIVERY_ENABLED", False):
        transaction.on_commit(_wake_delivery)
    return publication


def _wake_delivery():
    import logging
    from stable.tasks import deliver_race_lifecycle_outbox_task
    try:
        deliver_race_lifecycle_outbox_task.delay()
    except Exception:
        # 发布已提交，持久 outbox 由周期扫描恢复；不输出连接参数。
        logging.getLogger(__name__).warning("lifecycle_delivery_wakeup_failed")


def module_deadline(event, kind):
    from datetime import datetime, time
    from zoneinfo import ZoneInfo
    if event.race_datetime is not None:
        return event.race_datetime + timedelta(minutes=-30 if kind == "racecard" else 60)
    if event.local_date and event.timezone_name:
        return datetime.combine(event.local_date + timedelta(days=1), time(1),
                                tzinfo=ZoneInfo(event.timezone_name))
    return None


def _card_authority(event, control, observation, now, loaded=None):
    from stable.services.race_data_sync_control import resolve_source_route_admission
    from stable.services.race_data_sync_pipeline import resolve_race_data_provider_route
    from stable.services.race_data_sync_admission import binding_admission_reason
    from stable.services.race_data_source_adapters import load_multisource_policy
    source = observation.source_identity
    enrollment = loaded["enrollment"] if loaded is not None else models.RaceDataSyncEnrollment.objects.filter(event=event).first()
    if (not enrollment or control.write_owner != "data_sync"
            or enrollment.state != "enrolled" or source.event_id != event.pk
            or enrollment.projection_owner_generation != control.owner_generation
            or enrollment.manifest_sha256 != control.owner_manifest_sha256
            or source.identity_fields.get("publication_revoked")
            or source.identity_fields.get("identity_invalidated")
            or event.visibility_status != "published" or any((event.manual_lock_flags or {}).values())):
        return False
    if enrollment.authority_version == 2:
        policy = load_multisource_policy(now=now)
        binding = loaded["bindings"].get(source.pk) if loaded is not None else models.RaceDataSyncSourceBinding.objects.select_related(
            "source_identity__event", "enrollment").filter(enrollment=enrollment, source_identity=source).first()
        route = policy.route_for(dict(provider=source.source_key, region=source.region_code,
                                      identity_namespace=source.identity_namespace))
        return bool(binding and enrollment.standing_policy_digest == policy.digest
                    and not binding_admission_reason(binding=binding, route=route, now=now,
                                                     capability="racecard", check_runtime=False))
    route = resolve_race_data_provider_route(provider=source.source_key, region=source.region_code,
                                            identity_namespace=source.identity_namespace, data_kinds=("racecard",))
    if not route or source.pk != enrollment.source_identity_id:
        return False
    reason, _ = resolve_source_route_admission(source=source, route_digest=route.route_digest,
                                              data_kinds=("racecard",), now=now)
    provenance = observation.field_provenance
    return not reason and all((
        provenance.get("registry_digest") == route.registry_digest,
        provenance.get("contract_digest") == route.contract_digest,
        provenance.get("provider") == source.source_key,
        provenance.get("source_class") == route.entry.source_class,
    ))


def card_preflight(*, event, control, lifecycle, observation, now):
    """在旧可变名单写入之前拒绝部分资料、回退和跨来源争议。"""
    if not writable(event.pk):
        return ""
    if not _card_authority(event, control, observation, now):
        return "epoch_card_not_authorized"
    if observation.field_provenance.get("roster_complete") is not True:
        return "epoch_card_incomplete"
    state = models.RaceLifecyclePublicState.objects.select_for_update().filter(event=event).first()
    if not state or not state.racecard_revision_id:
        return ""
    previous = models.RaceResultObservation.objects.select_related("source_identity").filter(
        pk=state.racecard_evidence.get("observation_id")).first()
    if not previous:
        return "epoch_card_evidence_missing"
    current_time = previous.source_updated_at or previous.observed_at
    incoming_time = observation.source_updated_at or observation.observed_at
    if incoming_time < current_time:
        return "epoch_card_stale"
    if state.racecard_maturity == "confirmed" and observation.normalized_payload.get("declaration_status") != "confirmed":
        return "epoch_card_maturity_regression"
    if state.racecard_visibility == 'verifying':
        conflict = models.RaceResultObservation.objects.filter(pk=state.racecard_evidence.get('conflict_observation_id')).first()
        conflict_time = (conflict.source_updated_at or conflict.observed_at) if conflict else current_time
        if not (observation.field_provenance.get('card_correction_marker') is True
                and incoming_time > max(current_time, conflict_time)):
            return 'epoch_card_conflict_unresolved'
    def facts(obs):
        return sorted(tuple(str(row.get(key, "")) for key in
            ("number", "horse_name", "draw", "jockey_name", "trainer_name", "carried_weight", "status"))
            for row in obs.normalized_payload.get("participants", []))
    if (previous.source_identity_id != observation.source_identity_id and facts(previous) != facts(observation)
            and observation.field_provenance.get("card_correction_marker") is not True):
        hide_conflict(event=event, control=control, lifecycle=lifecycle, observation=observation, now=now, kind="racecard")
        return "epoch_card_conflict"
    return ""


def capture_card(*, event, control, lifecycle, observation, now):
    if not writable(event.pk) or not control.current_racecard_revision_id:
        return None
    if lifecycle is None or not _card_authority(event, control, observation, now):
        raise ValueError("epoch_card_not_authorized")
    state = models.RaceLifecyclePublicState.objects.select_for_update().filter(event=event).first()
    if state is None:
        state = models.RaceLifecyclePublicState(event=event, epoch=0)
    declared = observation.normalized_payload.get("declaration_status")
    confirmed = declared == "confirmed" and observation.field_provenance.get("roster_complete") is True
    policy_digest = _policy_digest(models.RaceDataSyncEnrollment.objects.get(event=event), now)
    if (state.pk and state.racecard_visibility == 'visible' and state.racecard_revision_id == control.current_racecard_revision_id
            and state.racecard_maturity == ('confirmed' if confirmed else 'predicted')
            and state.schedule_generation == lifecycle.schedule_generation and state.policy_digest == policy_digest):
        previous = models.RaceResultObservation.objects.select_related('source_identity').filter(pk=state.racecard_evidence.get('observation_id')).first()
        publication = models.RaceLifecycleEpochPublication.objects.filter(event=event,epoch=state.epoch).first()
        if (publication and previous and publication.authorization.get('manifest') == control.owner_manifest_sha256
                and publication.writer_generation == control.owner_generation and _card_authority(event,control,previous,now)):
            return publication
    state.schedule_generation = lifecycle.schedule_generation
    state.policy_digest = policy_digest
    state.racecard_revision_id = control.current_racecard_revision_id
    state.racecard_maturity = "confirmed" if confirmed else "predicted"
    state.racecard_visibility = "visible"
    state.racecard_reason = "qualified_card" if confirmed else "predicted_card"
    state.racecard_deadline_at = None if confirmed else module_deadline(event, "racecard")
    state.racecard_evidence = dict(observation_id=observation.pk,
                                  normalized_sha256=observation.normalized_sha256,
                                  source_id=observation.source_identity_id)
    return _commit_state(state=state, control=control, now=now, reason="racecard")


def capture_result(*, event, control, lifecycle, revision, observation, now):
    if not writable(event.pk):
        return None
    if not _result_authority(event, control, revision, observation, now, now):
        raise ValueError("epoch_result_not_authorized")
    state = models.RaceLifecyclePublicState.objects.select_for_update().filter(event=event).first()
    if state is None:
        state = models.RaceLifecyclePublicState(event=event, epoch=0)
    state.schedule_generation = lifecycle.schedule_generation
    state.policy_digest = _policy_digest(models.RaceDataSyncEnrollment.objects.get(event=event), now)
    state.result_revision = revision
    provisional = observation.result_phase == "provisional"
    state.result_maturity = "provisional" if provisional else "corrected" if observation.result_phase == "corrected" else "confirmed"
    state.result_visibility = "visible"
    state.result_reason = "qualified_result"
    state.result_deadline_at = module_deadline(event, "result") if provisional else None
    state.result_evidence = {
        "observation_id": observation.pk, "normalized_sha256": observation.normalized_sha256,
        "source_id": observation.source_identity_id}
    publication = _commit_state(state=state, control=control, now=now, reason="result")
    if not provisional and lifecycle.first_result_confirmed_at is None:
        lifecycle.first_result_confirmed_at = now
        lifecycle.correction_until = now + timedelta(days=7)
        lifecycle.next_correction_at = now + timedelta(minutes=15)
        lifecycle.save(update_fields=("first_result_confirmed_at", "correction_until",
                                      "next_correction_at", "updated_at"))
    return publication


def refresh_result_authority(*, event, control, lifecycle, revision, observation, now, explicit=False):
    """同事实仅在成熟度或授权变化时新建 epoch；每次抓取不是新的业务发布。"""
    state = models.RaceLifecyclePublicState.objects.filter(event=event).first()
    if state and state.result_visibility == 'verifying' and not explicit:
        return None
    maturity = 'provisional' if observation.result_phase == 'provisional' else 'corrected' if observation.result_phase == 'corrected' else 'confirmed'
    needs = not state or state.result_maturity != maturity or (explicit and state.result_visibility == 'verifying')
    if state:
        publication = models.RaceLifecycleEpochPublication.objects.filter(event=event,epoch=state.epoch).first()
        old = models.RaceResultObservation.objects.select_related('source_identity').filter(pk=state.result_evidence.get('observation_id')).first()
        try:
            needs = needs or (not publication or not old or publication.authorization.get('manifest') != control.owner_manifest_sha256
                or publication.writer_generation != control.owner_generation
                or state.policy_digest != _policy_digest(models.RaceDataSyncEnrollment.objects.get(event=event),now)
                or not _result_authority(event,control,revision,old,now,publication.published_at))
        except (ValueError,TypeError,KeyError,OSError):
            needs = True
    if needs:
        return capture_result(event=event,control=control,lifecycle=lifecycle,revision=revision,observation=observation,now=now)
    return None


def hide_conflict(*, event, control, lifecycle, observation, now, kind="result"):
    if not writable(event.pk):
        return None
    state = models.RaceLifecyclePublicState.objects.select_for_update().filter(event=event).first()
    if state is None:
        return None
    setattr(state, f"{kind}_visibility", "verifying")
    setattr(state, f"{kind}_reason", "source_conflict")
    evidence = dict(getattr(state, f"{kind}_evidence"))
    evidence["conflict_observation_id"] = observation.pk
    setattr(state, f"{kind}_evidence", evidence)
    state.schedule_generation = lifecycle.schedule_generation
    return _commit_state(state=state, control=control, now=now, reason="source_conflict")


def capture_schedule(*, event, control, lifecycle, now):
    """已通过来源裁决的改期；旧 epoch 的已到期失败由 commit 保存。"""
    if not writable(event.pk) or lifecycle is None:
        return None
    state = models.RaceLifecyclePublicState.objects.select_for_update().filter(event=event).first()
    if state is None:
        return None
    state.schedule_generation = lifecycle.schedule_generation
    state.policy_digest = _policy_digest(models.RaceDataSyncEnrollment.objects.get(event=event), now)
    for kind in KINDS:
        maturity = getattr(state, f'{kind}_maturity')
        deadline = module_deadline(event, kind) if maturity in ('predicted', 'provisional') else None
        if event.status in ('cancelled', 'postponed'):
            deadline = None
        setattr(state, f'{kind}_deadline_at', deadline)
    return _commit_state(state=state, control=control, now=now, reason='source_schedule')


def load_public_batch(event_ids):
    """批量读取一个页面的 epoch、凭据、授权和内容，禁止每场读取 reverse manager。"""
    from django.db.models import F
    states = list(models.RaceLifecyclePublicState.objects.filter(event_id__in=event_ids).select_related(
        "event__projection_control", "racecard_revision", "result_revision"))
    if not states:
        return {}
    ids = [s.event_id for s in states]
    publications = {p.event_id: p for p in models.RaceLifecycleEpochPublication.objects.filter(
        event_id__in=ids, epoch=F("event__lifecycle_public_state__epoch"))}
    enrollments = {e.event_id: e for e in models.RaceDataSyncEnrollment.objects.filter(
        event_id__in=ids).select_related("source_identity")}
    lifecycles = {r.event_id: r for r in models.RaceEventLifecycleControl.objects.filter(event_id__in=ids)}
    memberships = {r.event_id: r for r in models.RaceEventLifecycleEnforceMembership.objects.filter(
        event_id__in=ids, state="active", registry__state="active", registry__is_active=True).select_related("registry")}
    bindings = list(models.RaceDataSyncSourceBinding.objects.filter(enrollment__event_id__in=ids).select_related(
        "source_identity__event", "enrollment"))
    observation_ids = [getattr(s, f"{kind}_evidence").get("observation_id") for s in states for kind in KINDS]
    observation_ids.extend(s.result_revision.primary_observation_id for s in states if s.result_revision)
    observations = {r.pk: r for r in models.RaceResultObservation.objects.filter(pk__in=observation_ids).select_related("source_identity")}
    revision_ids = [getattr(s, f"{kind}_revision_id") for s in states for kind in KINDS]
    items = {}
    for item in models.RaceEventRevisionItem.objects.filter(revision_id__in=revision_ids).select_related("participant").order_by("internal_order"):
        items.setdefault(item.revision_id, []).append(item)
    return {s.event_id: dict(state=s, publication=publications.get(s.event_id), event=s.event,
        projection=getattr(s.event, "projection_control", None), lifecycle=lifecycles.get(s.event_id),
        enrollment=enrollments.get(s.event_id), membership=memberships.get(s.event_id),
        legacy_active=bool(memberships.get(s.event_id)),
        bindings={b.source_identity_id: b for b in bindings if b.enrollment.event_id == s.event_id and b.state == "active"},
        retired={b.source_identity_id for b in bindings if b.enrollment.event_id == s.event_id and b.state == "retired"},
        observations=observations, items=items) for s in states}


def _valid_loaded(loaded, now):
    state, publication = loaded["state"], loaded["publication"]
    control, lifecycle = loaded["projection"], loaded["lifecycle"]
    return bool(publication and control and lifecycle
        and publication.epoch == state.epoch
        and state.schedule_generation == lifecycle.schedule_generation
        and publication.writer_generation == control.owner_generation
        and publication.writer_owner == control.write_owner
        and publication.authorization.get("manifest") == control.owner_manifest_sha256
        and publication.snapshot_sha256 == canonical_sha(_snapshot(state))
        and publication.snapshot_sha256 == canonical_sha(publication.snapshot)
        and state.policy_digest == _policy_digest(loaded["enrollment"], now))


def _module_visible(loaded, kind, now):
    state = loaded["state"]
    if loaded["event"].status in ("cancelled", "postponed"):
        return "updating"
    visibility = getattr(state, f"{kind}_visibility")
    deadline = getattr(state, f"{kind}_deadline_at")
    try:
        if not _valid_loaded(loaded, now) or (deadline and now >= deadline):
            return "updating"
        if visibility != "visible":
            return visibility
        evidence = getattr(state, f"{kind}_evidence")
        obs = loaded["observations"].get(evidence.get("observation_id"))
        revision = getattr(state, f"{kind}_revision")
        if (not obs or obs.source_identity.event_id != state.event_id or not revision
            or revision.event_id != state.event_id or revision.kind != kind
            or obs.normalized_sha256 != evidence.get("normalized_sha256")):
            return "updating"
        if kind == "result":
            allowed = _result_authority(state.event, loaded["projection"], revision, obs, now,
                                        loaded["publication"].published_at, loaded=loaded)
        else:
            allowed = _card_authority(state.event, loaded["projection"], obs, now, loaded=loaded)
        return "visible" if allowed else "updating"
    except (ValueError, TypeError, KeyError, OSError):
        return "updating"


def result_reads(event_ids, now, *, batch=None):
    from stable.services.race_events import RaceLivePublicReadDecision
    batch = load_public_batch(event_ids) if batch is None else batch
    decisions = {}
    for event_id, loaded in batch.items():
        state = loaded["state"]
        visibility = _module_visible(loaded, "result", now)
        decisions[event_id] = RaceLivePublicReadDecision(
            visible=visibility == "visible", reason="lifecycle_" + visibility,
            revision_id=state.result_revision_id,
            phase=state.result_revision.phase if state.result_revision else "",
            effective_mode="official_public" if visibility == "visible" else "off")
    return decisions


def result_read(event_id, now):
    return result_reads([event_id], now).get(event_id)


def _item_row(item, *, kind, event, maturity, horse_name):
    common = dict(event=event, horse_name=horse_name,
                  horse_number=item.horse_number, jockey_name=item.jockey_name,
                  trainer_name=item.trainer_name, carried_weight=item.carried_weight,
                  barrier=item.barrier, running_status=item.status,
                  odds_value=item.field_provenance.get("odds_value", ""),
                  popularity=item.field_provenance.get("popularity"))
    if kind == "result":
        row = models.RaceEventResult(
            **common, finish_position=item.internal_order,
            reported_finish_position=item.reported_finish_position,
            official_finish_position=item.official_finish_position,
            is_confirmed=maturity in ("confirmed", "corrected"),
            finish_time=item.finish_time, margin=item.margin)
    else:
        row = models.RaceEventRunner(**common, sort_order=item.internal_order)
    return row


def public_modules(event_id, *, now, loaded=None):
    loaded = load_public_batch([event_id]).get(event_id) if loaded is None else loaded
    if loaded is None:
        return None
    state = loaded["state"]
    result = dict(state=state, publication=loaded["publication"], racecard=[], result=[], visibility={})
    for kind in KINDS:
        visibility = _module_visible(loaded, kind, now)
        result["visibility"][kind] = visibility
        if visibility == "visible":
            items = loaded["items"].get(getattr(state, f"{kind}_revision_id"), [])
            # 使用仲裁后保存的名字；不能从未应用的候选字段或可变 participant 回填。
            # 历史结果缺 display_name 时只读取该内容 revision 自己的不可变原始证据；
            # 当次授权 observation 可以更新，不能因此换掉旧内容的名字或隐藏整表。
            original = loaded['observations'].get(state.result_revision.primary_observation_id) if kind == 'result' else None
            fallback = {r.get('number'): r.get('horse_name') for r in original.normalized_payload.get('participants', [])} if original else {}
            names = {item.horse_number: item.field_provenance.get('display_name') or fallback.get(item.horse_number) for item in items}
            if len(names) != len(items) or any(not names.get(i.horse_number) for i in items):
                result["visibility"][kind] = "updating"
                continue
            result[kind] = [_item_row(item, kind=kind, event=state.event,
                maturity=getattr(state, f"{kind}_maturity"), horse_name=names[item.horse_number]) for item in items]
    return result


def public_row_token(kind, row):
    return canonical_sha(dict(kind=kind, number=row.horse_number, name=row.horse_name,
        jockey=row.jockey_name, status=row.running_status,
        position=getattr(row, "reported_finish_position", None)))


def decorate_context(context, *, now):
    """旧布局共用入口；无 epoch 的历史页面保留原路径。"""
    event = context.get("event")
    if event is None or not isinstance(event, models.RaceEvent):
        return False
    modules = public_modules(event.pk, now=now)
    if modules is None:
        return False
    state, publication = modules["state"], modules["publication"]
    context["runners"] = modules["racecard"]
    context["results"] = modules["result"]
    context["runner_preview"] = None
    context["top_results"] = modules["result"][:5]
    context["winner"] = next((r for r in modules["result"] if r.is_confirmed and r.official_finish_position == 1), None)
    labels = {"updating": "资料更新中", "verifying": "资料核实中"}
    context["lifecycle_card_notice"] = labels.get(modules["visibility"]["racecard"], "")
    context["lifecycle_result_notice"] = labels.get(modules["visibility"]["result"], "")
    context["runner_section_label"] = "确定名单" if state.racecard_maturity == "confirmed" else "预想名单"
    context["result_section_label"] = "已确认赛果" if state.result_maturity in ("confirmed", "corrected") else "待确认赛果"
    context["public_probe_projection"] = {"complete": False}
    row_tokens = {}
    for kind in KINDS:
        row_tokens[kind] = []
        for row in modules[kind]:
            token = public_row_token(kind, row)
            row.lifecycle_row_token = token
            row_tokens[kind].append(token)
    context["lifecycle_marker"] = dict(
        event_id=event.pk, epoch=state.epoch, schedule_generation=state.schedule_generation,
        snapshot_sha256=publication.snapshot_sha256 if publication else "",
        visibility=modules["visibility"], row_tokens=row_tokens, racecard_revision=state.racecard_revision_id,
        result_revision=state.result_revision_id)
    return True


def visible_cells(modules):
    """与公开格式合同一致的展示值，用于比对外部 DOM 的真实单元格。"""
    from stable.views import _attach_result_display_positions, _attach_race_term_display_names
    from stable.services.race_information_display import prepare_context
    from stable.templatetags.race_information import race_field
    event = modules['state'].event
    context = dict(event=event,runners=modules['racecard'],results=modules['result'])
    _attach_result_display_positions(context['results'])
    _attach_race_term_display_names([(event,context['runners']),(event,context['results'])])
    prepare_context(context)
    output = {}
    for kind in KINDS:
        output[kind] = []
        for row in modules[kind]:
            shared = [race_field(row,'horse_number',row.horse_number or '-'),
                race_field(row,'horse_name',row.display_horse_name),
                race_field(row,'jockey_name',row.display_jockey_name or '-'),
                race_field(row,'trainer_name',row.trainer_name or '-')]
            odds = str(race_field(row,'odds',row.odds_value or '-'))+' / '+str(race_field(row,'popularity',row.popularity or '-'))
            if kind == 'result':
                cells = [race_field(row,'position',row.display_finish_position),*shared,
                    race_field(row,'finish_time',row.finish_time or '-'),race_field(row,'margin',row.margin or '-'),odds]
            else:
                cells = [race_field(row,'barrier',row.barrier) if row.barrier and row.barrier != '0' else '—',*shared,
                    race_field(row,'weight',row.carried_weight or '-'),odds,race_field(row,'status',row.get_running_status_display())]
            output[kind].append([' '.join(str(cell).split()) for cell in cells])
    return output


def claim_deliveries(*, now, limit=100):
    """短事务锁定 due pending 或失去租约的 running，不执行网络。"""
    import secrets
    from django.db.models import Q
    if timezone.is_naive(now) or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("delivery_bounds")
    with transaction.atomic():
        rows = list(models.RaceLifecycleDelivery.objects.select_for_update(skip_locked=True).filter(
            Q(status="pending", next_attempt_at__lte=now)
            | Q(status="running", lease_expires_at__lte=now)
        ).order_by("next_attempt_at", "pk")[:limit])
        for row in rows:
            row.status = "running"
            row.lease_token = secrets.token_hex(24)
            row.lease_expires_at = now + timedelta(seconds=120)
            row.attempts += 1
            row.save(update_fields=("status", "lease_token", "lease_expires_at", "attempts", "updated_at"))
        return rows


def _delivery_lease(row, now):
    if timezone.is_naive(now):
        raise ValueError("delivery_time")
    return models.RaceLifecycleDelivery.objects.filter(
        pk=row.pk, event_id=row.event_id, epoch=row.epoch, consumer=row.consumer,
        status="running", lease_token=row.lease_token, lease_expires_at__gt=now)


def renew_delivery(row, *, now):
    return bool(_delivery_lease(row, now).update(
        lease_expires_at=now + timedelta(seconds=120), updated_at=now))


def finish_delivery(row, *, now, error=""):
    if error and (len(error) > 64 or not all(c.isalnum() or c == "_" for c in error)):
        error = "delivery_failed"
    return bool(_delivery_lease(row, now).update(
        status="pending" if error else "done", lease_token="", lease_expires_at=None,
        next_attempt_at=now + timedelta(seconds=min(900, 30 * 2 ** min(row.attempts, 5))),
        last_error=error, updated_at=now))


def execute_delivery(row, *, now, fetcher=None):
    if not _delivery_lease(row, now).exists():
        raise ValueError("delivery_lease_lost")
    if row.consumer == "cache" or row.consumer in ("cache_racecard_deadline", "cache_result_deadline"):
        # 不能吞掉 Redis 失效异常然后 ack。
        from django.core.cache import cache
        from stable.services.race_event_public_cache import (
            RACE_SITEMAP_COUNT_CACHE_KEY, RACE_CALENDAR_YEARS_CACHE_KEY)
        cache.delete_many([RACE_SITEMAP_COUNT_CACHE_KEY, RACE_CALENDAR_YEARS_CACHE_KEY])
        return
    if row.consumer not in ("probe", "probe_racecard_deadline", "probe_result_deadline"):
        raise ValueError("delivery_consumer_unknown")
    publication = models.RaceLifecycleEpochPublication.objects.filter(
        event_id=row.event_id, epoch=row.epoch, snapshot_sha256=row.payload_sha256).first()
    state = models.RaceLifecyclePublicState.objects.filter(event_id=row.event_id).first()
    if not publication or not state:
        raise ValueError("delivery_publication_missing")
    if state.epoch > row.epoch:
        return  # 不用旧探针盖掉新的公开版本；新 epoch 有独立 outbox。
    from urllib.parse import urlsplit
    import json
    import re
    origin = getattr(settings, "RACE_LIFECYCLE_PUBLIC_ORIGIN", "")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")
            or parsed.port not in (None, 443)):
        raise ValueError("probe_origin_unconfigured")
    if fetcher is None:
        import requests

        def fetcher(url):
            response = requests.get(url, timeout=10, allow_redirects=False, stream=True)
            try:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("probe_http_status")
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError("probe_response_limit")
                return body.decode("utf-8")
            finally:
                response.close()
    event = models.RaceEvent.objects.get(pk=row.event_id)
    html = fetcher(origin.rstrip("/") + event.get_absolute_url())
    markers = re.findall(r'<script[^>]*id="race-lifecycle-marker"[^>]*>(.*?)</script>', html, re.S)
    if len(markers) != 1:
        raise ValueError("probe_marker_missing")
    marker = json.loads(markers[0])
    if (marker.get("event_id") != row.event_id or marker.get("epoch") != row.epoch
            or marker.get("snapshot_sha256") != publication.snapshot_sha256):
        raise ValueError("probe_version_mismatch")
    from bs4 import BeautifulSoup
    document = BeautifulSoup(html, "html.parser")
    modules = public_modules(row.event_id, now=timezone.now())
    if (not modules or modules["state"].epoch != row.epoch
            or marker.get("visibility") != modules["visibility"]):
        raise ValueError("probe_visibility_mismatch")
    rendered = visible_cells(modules)
    for kind, section in (("racecard", "runners"), ("result", "results")):
        tokens = [element.get("data-lifecycle-row") for element in document.select(f"#{section} tbody tr")]
        expected = marker.get("row_tokens", {}).get(kind)
        actual = [public_row_token(kind, item) for item in modules[kind]]
        if expected != tokens or tokens != actual:
            raise ValueError("probe_rows_mismatch")
        cells = [[' '.join(cell.get_text(' ',strip=True).split()) for cell in element.find_all('td',recursive=False)]
                 for element in document.select(f'#{section} tbody tr')]
        if cells != rendered[kind]:
            raise ValueError('probe_visible_content_mismatch')
    observed = timezone.now()
    with transaction.atomic():
        if not _delivery_lease(row, observed).select_for_update().exists():
            raise ValueError('delivery_lease_lost')
        receipt, _ = models.RaceLifecycleReceipt.objects.get_or_create(
            idempotency_key=canonical_sha(["probe", row.event_id, row.epoch, row.consumer]),
            defaults=dict(target_key=f"canonical:{row.event_id}", event_id=row.event_id,
                          kind="probe", schedule_generation=state.schedule_generation,
                          epoch=row.epoch, occurred_at=observed, recorded_at=observed,
                          payload=marker, evidence_refs=[f"epoch:{publication.pk}"]))
    
        from stable.services.race_lifecycle_metrics import record_probe_repairs
        record_probe_repairs(receipt, publication=publication, now=observed)


def source_capacity_report(*, targets, proofs, budgets):
    """只计算全库存所需额度；来源 proof 由固定 manifest 提供，不自行推断授权。"""
    import math
    from stable.services.race_data_source_adapters import REGIONS
    if not isinstance(targets, list) or len(targets) > 1000 or len({t['key'] for t in targets}) != len(targets):
        raise ValueError("capacity_targets_invalid")
    hosts, gaps, selected = {}, {}, {}
    for target in targets:
        key = target['key']
        if target.get('region') not in REGIONS or type(target.get('key_race')) is not bool:
            raise ValueError("capacity_target_region_or_priority")
        candidates = [p for p in proofs if p.get('region') == target['region']
            and all(p.get(k) is True for k in ('identity', 'confirmed_card', 'complete_result', 'correction'))
            and p.get('evidence_refs') and p.get('discovery') == 'full']
        if not candidates:
            gaps[key] = ['source_capabilities_missing']
            continue
        verified = [p for p in candidates if p.get('runtime_verified') is True]
        candidates = verified or candidates
        selected[key] = candidates
        for proof in candidates:
            requests = proof.get('requests_per_fetch')
            if type(requests) is not int or not 1 <= requests <= 10:
                raise ValueError("capacity_request_cost")
            host = proof['host']
            bucket = hosts.setdefault(host, {'base_per_hour': 0, 'required_per_hour': 0, 'capacity_ok': False})
            # 每个可切换来源都覆盖全部追踪库存，不能借用另一 host 的空闲额度。
            bucket['base_per_hour'] += requests * (3600 / (60 if target['key_race'] else 120) + 4)
        if not verified:
            gaps[key] = ['source_runtime_unverified']
    for host, bucket in hosts.items():
        limit = budgets.get(host)
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("capacity_budget_invalid")
        bucket['required_per_hour'] = math.ceil(bucket['base_per_hour'] / 0.7)
        bucket['approved_per_hour'] = limit
        bucket['capacity_ok'] = limit is not None and limit >= bucket['required_per_hour']
    for key, proofs_for_target in selected.items():
        if any(not hosts[proof['host']]['capacity_ok'] for proof in proofs_for_target):
            gaps.setdefault(key, []).append('request_capacity_gap')
    return dict(targets=len(targets), ready=len(targets)-len(gaps), gaps=gaps, hosts=hosts,
                strategy='full_fetch', reserve=0.3, manifest_sha256=canonical_sha(dict(targets=targets, proofs=proofs, budgets=budgets)))


def capacity_manifest(*, now):
    """无已核验容量证据时拒绝提高真实轮询频率。"""
    import hashlib
    import json
    from pathlib import Path
    path = getattr(settings, 'RACE_LIFECYCLE_CAPACITY_FILE', '')
    expected = getattr(settings, 'RACE_LIFECYCLE_CAPACITY_SHA256', '')
    if not path or not expected:
        raise ValueError('capacity_manifest_missing')
    raw = Path(path).read_bytes()
    if len(raw) > 2 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('capacity_manifest_digest')
    value = json.loads(raw)
    from stable.services.race_data_source_adapters import aware
    if not aware(value['valid_from']) <= now < aware(value['valid_until']):
        raise ValueError('capacity_manifest_expired')
    report = source_capacity_report(targets=value['targets'], proofs=value['proofs'], budgets=value['budgets'])
    if report['ready'] != report['targets'] or not report['targets']:
        raise ValueError('capacity_not_ready')
    keys = {t['key'] for t in value['targets']}
    if not {f'canonical:{pk}' for pk in getattr(settings, 'RACE_LIFECYCLE_V2_EVENT_IDS', ())} <= keys:
        raise ValueError('capacity_cohort_incomplete')
    return value

def _compatibility_entry(control):
    revision = control.current_result_revision
    return dict(event_id=control.event_id, writer=control.write_owner, generation=control.owner_generation,
        manifest=control.owner_manifest_sha256, result_revision_id=control.current_result_revision_id,
        observation_id=revision.primary_observation_id if revision else None,
        content_sha256=revision.content_sha256 if revision else '',
        published_at=revision.published_at.isoformat() if revision and revision.published_at else None)


def compatibility_manifest(*, event_ids, after_id=0):
    """只读、有界游标审计；没有既有授权 publication 的赛事不制造确认。"""
    if type(after_id) is not int or after_id < 0 or len(event_ids) > 1000:
        raise ValueError('compatibility_bounds')
    rows = list(models.RaceEventProjectionControl.objects.filter(event_id__in=event_ids,
        event_id__gt=after_id).select_related('current_result_revision').order_by('event_id')[:100])
    return dict(schema_version='p02.compatibility.v1', after_id=after_id,
        last_id=rows[-1].event_id if rows else after_id, entries=[_compatibility_entry(r) for r in rows])


def backfill_compatibility(manifest, *, expected_sha256, now):
    if (canonical_sha(manifest) != expected_sha256 or manifest.get('schema_version') != 'p02.compatibility.v1'
        or not isinstance(manifest.get('entries'), list) or len(manifest['entries']) > 100):
        raise ValueError('compatibility_manifest_invalid')
    result = dict(applied=[], replayed=[], gaps={})
    from stable.services.race_event_lifecycle_enforce import lock_current_runtime_registry_membership
    for entry in manifest['entries']:
        event_id = entry['event_id']
        if not writable(event_id):
            raise ValueError('compatibility_cohort_disabled')
        with transaction.atomic():
            lock_current_runtime_registry_membership(event_id=event_id, now=now)
            lifecycle = models.RaceEventLifecycleControl.objects.select_for_update().filter(event_id=event_id).first()
            event = models.RaceEvent.objects.select_for_update().get(pk=event_id)
            control = models.RaceEventProjectionControl.objects.select_for_update().get(event_id=event_id)
            state = models.RaceLifecyclePublicState.objects.select_for_update().filter(event_id=event_id).first()
            if state:
                receipt = models.RaceLifecycleReceipt.objects.filter(kind='backfill', event_id=event_id,
                    idempotency_key=canonical_sha(['backfill', expected_sha256, event_id])).first()
                if not receipt:
                    result['gaps'][str(event_id)] = 'epoch_already_exists'
                else:
                    result['replayed'].append(event_id)
                continue
            if _compatibility_entry(control) != entry:
                raise ValueError('compatibility_input_drift')
            revision = control.current_result_revision
            if not lifecycle or not revision or not hasattr(revision, 'publication'):
                result['gaps'][str(event_id)] = 'historical_authority_missing'
                continue
            observation = revision.primary_observation
            if not observation or not _result_authority(event, control, revision, observation, now, now):
                result['gaps'][str(event_id)] = 'current_authority_missing'
                continue
            # 只能使用保留的首次正式发布证据，不能从导入时间重开七天窗口。
            first = models.RaceEventRevisionPublication.objects.filter(revision__event_id=event_id,
                revision__kind='result', revision__phase__in=('official', 'corrected')).order_by('published_at').first()
            if first and lifecycle.first_result_confirmed_at is None:
                lifecycle.first_result_confirmed_at = first.published_at
                lifecycle.correction_until = first.published_at + timedelta(days=7)
                lifecycle.next_correction_at = now if now < lifecycle.correction_until else None
                lifecycle.save(update_fields=('first_result_confirmed_at', 'correction_until', 'next_correction_at', 'updated_at'))
            publication = capture_result(event=event, control=control, lifecycle=lifecycle,
                                         revision=revision, observation=observation, now=now)
            models.RaceLifecycleReceipt.objects.create(kind='backfill', event_id=event_id,
                idempotency_key=canonical_sha(['backfill', expected_sha256, event_id]), target_key=f'canonical:{event_id}',
                occurred_at=None, recorded_at=now, epoch=publication.epoch, schedule_generation=lifecycle.schedule_generation,
                payload={'manifest_sha256': expected_sha256, 'input': entry}, evidence_refs=[f'epoch:{publication.pk}'])
            result['applied'].append(event_id)
    return result

def _record_expired_publication(publication, kind, now):
    from stable.services.race_data_source_adapters import aware
    value = publication.snapshot[kind].get('deadline_at')
    if not value or aware(value) > now:
        return False
    deadline = aware(value)
    _, created = models.RaceLifecycleReceipt.objects.get_or_create(
        idempotency_key=canonical_sha(['deadline', publication.event_id, publication.epoch, kind]),
        defaults=dict(kind='deadline', event_id=publication.event_id, target_key=f'canonical:{publication.event_id}',
            schedule_generation=publication.schedule_generation, epoch=publication.epoch,
            occurred_at=deadline, recorded_at=now, deadline_at=deadline,
            payload={'module': kind, 'stage': 'temporary_material_expired'}, evidence_refs=[f'epoch:{publication.pk}']))
    if created:
        for consumer in ('cache', 'probe'):
            models.RaceLifecycleDelivery.objects.get_or_create(event_id=publication.event_id, epoch=publication.epoch,
                consumer=f'{consumer}_{kind}_deadline', defaults=dict(next_attempt_at=now, payload_sha256=publication.snapshot_sha256))
    return created


def record_due_deadlines(*, now, limit=100):
    """deadline 到达留下不可变违约记录；请求时隐藏不依赖本任务存活。"""
    if timezone.is_naive(now) or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('deadline_bounds')
    count = 0
    # 已记录的版本在数据库中排除，避免前 100 个过期版本永久饿死后续赛事。
    from django.db.models import Exists, OuterRef
    for kind in KINDS:
        done = models.RaceLifecycleReceipt.objects.filter(kind='deadline', event_id=OuterRef('event_id'),
            epoch=OuterRef('epoch'), payload__module=kind)
        ids = list(models.RaceLifecyclePublicState.objects.annotate(deadline_recorded=Exists(done)).filter(
            deadline_recorded=False, **{f'{kind}_deadline_at__lte': now}).order_by(
                f'{kind}_deadline_at', 'event_id').values_list('event_id', flat=True)[:limit])
        for event_id in ids:
            with transaction.atomic():
                state = models.RaceLifecyclePublicState.objects.select_for_update().get(event_id=event_id)
                deadline = getattr(state, f'{kind}_deadline_at')
                if not deadline or deadline > now:
                    continue
                pub = models.RaceLifecycleEpochPublication.objects.get(event_id=event_id, epoch=state.epoch)
                count += int(_record_expired_publication(pub, kind, now))
    from stable.services.race_lifecycle_metrics import record_scope_deadlines
    return count + record_scope_deadlines(now=now, limit=limit)

def capacity_allows_source(manifest, *, event, source):
    from urllib.parse import urlsplit
    target = next((t for t in manifest.get('targets', []) if t['key'] == f'canonical:{event.pk}'), None)
    grade = str(event.normalized_grade or '').upper().replace('-', '')
    key = grade in ('G1', 'GI', 'JPN1', 'JPNI', 'JG1') or (event.source_refs or {}).get('lifecycle_priority') == 'key'
    report = source_capacity_report(targets=manifest['targets'], proofs=manifest['proofs'], budgets=manifest['budgets'])
    host = urlsplit(source.canonical_url).hostname
    return bool(report['hosts'].get(host, {}).get('capacity_ok') and target and target['region'] == source.region_code and (not key or target['key_race'])
        and any(p.get('runtime_verified') is True and p.get('region') == source.region_code
            and p.get('provider') == source.source_key and p.get('host') == urlsplit(source.canonical_url).hostname
            for p in manifest.get('proofs', [])))
