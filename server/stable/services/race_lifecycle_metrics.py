"""P02 持久计量入口：严格复用 R01，不把发布或同一 parser 当独立审计。"""
from django.db import transaction
from django.utils import timezone
from stable import models
from stable.services import race_timeliness_contracts as contracts
from stable.services.race_data_source_adapters import canonical_sha


def persist_report(value, **anchors):
    document = contracts.parse_report(value, **anchors)
    payload = dict(document=document.to_dict(), anchors=anchors)
    key = canonical_sha(['r01-report', payload])
    with transaction.atomic():
        receipt, _ = models.RaceLifecycleReceipt.objects.get_or_create(
            idempotency_key=key, defaults=dict(kind='report', target_key=value['scope']['scope_ref'],
                occurred_at=None, recorded_at=timezone.now(), payload=payload,
                evidence_refs=[value['scope']['scope_ref']], rule_version='r01.report.v1'))
    return receipt


def read_report(key):
    receipt = models.RaceLifecycleReceipt.objects.get(idempotency_key=key, kind='report')
    payload = receipt.payload
    if canonical_sha(['r01-report', payload]) != key:
        raise ValueError('report_digest_mismatch')
    return contracts.summarize(contracts.parse_report(payload['document'], **payload['anchors']))


def delivery_health(*, now):
    """运维补偿统计独立于业务成功率；无外部 probe 不能算公开成功。"""
    from django.db.models import Count, Q
    return models.RaceLifecycleDelivery.objects.aggregate(
        pending=Count('pk', filter=Q(status='pending')),
        expired_running=Count('pk', filter=Q(status='running', lease_expires_at__lte=now)),
        retrying=Count('pk', filter=Q(attempts__gt=1) & ~Q(status='done')),
        probes_done=Count('pk', filter=Q(consumer='probe', status='done')))

def stamp(value):
    from datetime import timezone as utc
    return value.astimezone(utc.utc).isoformat().replace('+00:00', 'Z') if value else None


def load_input(event_id, *, now):
    """实际 ORM → F01 loader；只映射已有证据，不用抓取时刻补首发。"""
    from stable.services.content_contracts import build_input
    from stable.services.race_lifecycle_projection import load_public_batch, _module_visible
    loaded = load_public_batch([event_id]).get(event_id)
    event = loaded['event'] if loaded else models.RaceEvent.objects.get(pk=event_id)
    state = loaded['state'] if loaded else None
    evidence, materials = [], []
    for kind in ('racecard', 'result') if state else ():
        ref = getattr(state, f'{kind}_evidence')
        obs = loaded['observations'].get(ref.get('observation_id'))
        revision = getattr(state, f'{kind}_revision')
        if not obs or not revision:
            continue
        source = obs.source_identity
        capability = 'roster' if kind == 'racecard' else 'result'
        evidence_id = f'observation:{obs.pk}'
        provenance = obs.field_provenance
        source_time = provenance.get('source_time') or dict(precision='unknown', published_at=None,
                                                           last_absent_at=None, first_seen_at=None)
        evidence.append(dict(evidence_id=evidence_id, provider_key=source.source_key,
            source_class=provenance['source_class'], independence_key=source.source_key,
            capability=capability, artifact_sha256=obs.normalized_sha256,
            locator=f'observation:{obs.pk}', observed_at=stamp(obs.observed_at), source_time=source_time,
            contract_ref=dict(route_digest=provenance['registry_digest'], contract_digest=provenance['contract_digest'],
                proof_digest=source.evidence_sha256, valid_until=stamp(source.valid_until),
                revoked=bool(source.identity_fields.get('publication_revoked') or source.identity_fields.get('identity_invalidated')))))
        visibility = _module_visible(loaded, kind, now)
        maturity = getattr(state, f'{kind}_maturity')
        items = loaded['items'].get(revision.pk, [])
        materials.append(dict(capability=capability, maturity=maturity, completeness='complete',
            validation='passed' if visibility == 'visible' else 'conflict' if visibility == 'verifying' else 'pending',
            revision_ref=f'epoch:{state.epoch}:{kind}:{revision.pk}',
            supersedes_ref=f'epoch:{loaded["publication"].previous_epoch}' if maturity == 'corrected' else None,
            evidence_refs=[evidence_id], data=dict(participants=[dict(stable_key=f'participant:{i.participant_id}',
                horse_ref=f'participant:{i.participant_id}', status=i.status) for i in items])))
    policy = f'p02:{loaded["publication"].snapshot_sha256}' if loaded and loaded['publication'] else 'p02:missing'
    projection = loaded['projection'] if loaded else models.RaceEventProjectionControl.objects.filter(event_id=event_id).first()
    lifecycle = loaded['lifecycle'] if loaded else models.RaceEventLifecycleControl.objects.filter(event_id=event_id).first()
    enrollment = loaded['enrollment'] if loaded else models.RaceDataSyncEnrollment.objects.filter(event_id=event_id).first()
    snapshot = dict(entity=dict(kind='race_event', canonical_id=str(event_id), identity_state='verified',
            source_refs=[], candidate_ids=[], evidence_refs=[]), materials=materials, evidence=evidence,
        protection=dict(paused=any((event.manual_lock_flags or {}).values()), fields=[], modules=[],
            reason='', actor_ref=None, changed_at=None), policy_ref=policy)
    return build_input(snapshot, evaluated_at=stamp(now), policy_ref=policy,
        generations=dict(owner=projection.owner_generation if projection else None,
                         schedule=lifecycle.schedule_generation if lifecycle else None,
                         enrollment=enrollment.enrollment_generation if enrollment else None,
                         source_set=enrollment.source_set_generation if enrollment else None))

def assemble_report(*, scope, window, as_of, external_records=()):
    """按冻结目标集合连接持久版本与义务账本；DB 发布不充当外部可见或正确性审计。"""
    import copy
    scope = copy.deepcopy(scope)
    targets = {target['key']: target for target in scope['targets']}
    if len(targets) != len(scope['targets']) or len(targets) > contracts.MAX_TARGETS:
        raise ValueError('report_scope_bounds')
    receipts = list(models.RaceLifecycleReceipt.objects.filter(
        target_key__in=targets, recorded_at__lte=as_of,
        kind__in=('publish', 'deadline', 'audit', 'repair')).order_by('recorded_at', 'pk')[:contracts.MAX_RECORDS+1])
    if len(receipts) > contracts.MAX_RECORDS:
        raise ValueError('report_receipts_limit')
    version_by_epoch = {}
    gaps = ['independent_coverage_unverified']
    for receipt in receipts:
        if receipt.kind != 'publish':
            continue
        document = receipt.payload.get('input')
        if document is None:
            gaps.append(f'missing_input:{receipt.idempotency_key}')
            continue
        target = targets[receipt.target_key]
        if document['input_version'] not in [v['input_version'] for v in target['versions']]:
            target['versions'].append(document)
        target['current_input_version'] = document['input_version']
        version_by_epoch[(receipt.target_key, receipt.epoch)] = document['input_version']
    records = list(copy.deepcopy(external_records))
    for receipt in receipts:
        if receipt.kind == 'publish':
            continue
        if receipt.kind != 'deadline':
            row = receipt.payload.get('r01_record')
            if row:
                records.append(row)
            elif receipt.kind == 'repair' and receipt.payload.get('resolved_deadline'):
                old = next((r for r in receipts if r.idempotency_key == receipt.payload['resolved_deadline']), None)
                old_version = (version_by_epoch.get((old.target_key, old.epoch)) or old.payload.get('input_version')) if old else None
                current_version = version_by_epoch.get((receipt.target_key, receipt.epoch))
                if old_version and current_version:
                    ref = old.idempotency_key
                    records.append(dict(record_id=receipt.idempotency_key, target_key=receipt.target_key,
                        input_version=current_version, occurred_at=stamp(receipt.occurred_at), recorded_at=stamp(receipt.recorded_at),
                        kind='repair', reason_code='public_confirmed_recovery', evidence_refs=receipt.evidence_refs,
                        payload=dict(resolves=[ref], resolved_versions={ref:old_version}, resolved_fields={ref:[]})))
                else:
                    gaps.append(f'unmapped_repair:{receipt.idempotency_key}')
            else:
                gaps.append(f'unmapped_receipt:{receipt.idempotency_key}')
            continue
        version = version_by_epoch.get((receipt.target_key, receipt.epoch)) or receipt.payload.get('input_version')
        if version is None:
            gaps.append(f'missing_version:{receipt.idempotency_key}')
            continue
        records.append(dict(record_id=receipt.idempotency_key, target_key=receipt.target_key,
            input_version=version, occurred_at=stamp(receipt.occurred_at), recorded_at=stamp(receipt.recorded_at),
            kind='deadline', reason_code='temporary_material_expired', evidence_refs=receipt.evidence_refs,
            payload=dict(deadline_at=stamp(receipt.deadline_at), stage=receipt.payload['stage'])))
    scope_sha = canonical_sha(scope)
    coverage = dict(scope_sha256=scope_sha, expected_record_ids=sorted({r['record_id'] for r in records}),
        proof_ref=None, complete=False, gaps=sorted(set(gaps)), window=window, as_of=stamp(as_of))
    value = dict(scope=scope, window=window, as_of=stamp(as_of), records=records, coverage=coverage, effective_intervals=[])
    return contracts.parse_report(value, expected_scope_sha256=scope_sha,
        expected_candidate_sha256=scope['candidate_sha256'], expected_coverage_sha256=canonical_sha(coverage))


def business_counts(document):
    summary = contracts.summarize(document)
    n, e = summary['targets'], summary['information_error_targets']
    d, late = summary['required_targets'], summary['stalled_targets']
    unknown = summary['unreviewed_targets'] + summary['partial_audit_targets']
    return dict(N=n, E=e, U=unknown, D=d, L=late, error_rate=e/n if n else None,
        stalled_rate=late/d if d else None,
        accepted=bool(summary['measurement_complete'] and not summary['blocking'] and not unknown and n and d and e/n < .01 and late/d < .03))

def register_scope(manifest, *, expected_sha256, now):
    """冻结目标与明确的业务期限；未匹配 canonical 的目标也保留。"""
    from stable.services.race_data_source_adapters import aware
    if canonical_sha(manifest) != expected_sha256 or set(manifest) != {'scope', 'window', 'obligations'}:
        raise ValueError('scope_manifest_invalid')
    scope, window = manifest['scope'], manifest['window']
    coverage = dict(scope_sha256=canonical_sha(scope), expected_record_ids=[], proof_ref=None, complete=False,
        gaps=['scope_only'], window=window, as_of=stamp(now))
    contracts.parse_report(dict(scope=scope, window=window, as_of=stamp(now), records=[], coverage=coverage,
        effective_intervals=[]), expected_scope_sha256=canonical_sha(scope),
        expected_candidate_sha256=scope['candidate_sha256'], expected_coverage_sha256=canonical_sha(coverage))
    targets = {target['key']: target for target in scope['targets']}
    if len(manifest['obligations']) > contracts.MAX_RECORDS:
        raise ValueError('scope_obligations_limit')
    for obligation in manifest['obligations']:
        if (set(obligation) != {'target_key', 'module', 'deadline_at', 'evidence_refs'}
            or obligation['target_key'] not in targets or obligation['module'] not in ('racecard', 'result')
            or not obligation['evidence_refs']):
            raise ValueError('scope_obligation_invalid')
        aware(obligation['deadline_at'])
    with transaction.atomic():
        receipt, _ = models.RaceLifecycleReceipt.objects.get_or_create(idempotency_key=canonical_sha(['scope', expected_sha256]),
            defaults=dict(kind='scope', target_key=scope['scope_ref'], occurred_at=None, recorded_at=now,
                          payload=manifest, evidence_refs=[scope['scope_ref']]))
        for obligation in manifest['obligations']:
            target = targets[obligation['target_key']]
            frozen = next(version for version in target['versions'] if version['input_version'] == target['current_input_version'])
            capability = 'roster' if obligation['module'] == 'racecard' else 'result'
            material = next((item for item in frozen['snapshot']['materials'] if item['capability'] == capability), None)
            # 已指定确定版本必须精确履约；缺资料或临时资料允许同代际的首次确定后继。
            successor_allowed = material is None or material['maturity'] in ('unknown', 'predicted', 'provisional')
            models.RaceLifecycleReceipt.objects.get_or_create(idempotency_key=canonical_sha(['obligation', expected_sha256, obligation]),
                defaults=dict(kind='obligation', target_key=obligation['target_key'], event_id=target['event_id'],
                    occurred_at=None, recorded_at=now, deadline_at=aware(obligation['deadline_at']),
                    payload=dict(module=obligation['module'], scope_sha256=expected_sha256,
                                 input_version=target['current_input_version'], successor_allowed=successor_allowed),
                    evidence_refs=obligation['evidence_refs']))
    return receipt


def obligation_publications(obligation):
    """精确版本，或在冻结之后、同实体同代际的确定后继；不跨改期/授权换代。"""
    from django.db.models import Q, Subquery
    version = obligation.payload['input_version']
    matching = Q(payload__input__input_version=version)
    generations = version['generations']
    if obligation.payload.get('successor_allowed') and all(value is not None for value in generations.values()):
        matching |= Q(recorded_at__gt=obligation.recorded_at,
            payload__input__input_version__generations=generations,
            payload__input__snapshot__entity__canonical_id=str(obligation.event_id),
            payload__input__snapshot__entity__identity_state='verified')
    versions = models.RaceLifecycleReceipt.objects.filter(matching, kind='publish', event_id=obligation.event_id).values('epoch')
    return models.RaceLifecycleEpochPublication.objects.filter(event_id=obligation.event_id,
        epoch__in=Subquery(versions),
        **{f"snapshot__{obligation.payload['module']}__maturity__in": ('confirmed', 'corrected')})


def record_scope_deadlines(*, now, limit=100):
    from django.db.models import Exists, OuterRef
    from django.db.models.fields.json import KeyTextTransform
    completed = models.RaceLifecycleReceipt.objects.annotate(obligation_ref=KeyTextTransform('obligation', 'payload')).filter(kind__in=('deadline', 'obligation_met'),
        obligation_ref=OuterRef('idempotency_key'))
    obligations = list(models.RaceLifecycleReceipt.objects.annotate(completed=Exists(completed)).filter(
        kind='obligation', deadline_at__lte=now, completed=False).order_by('deadline_at', 'pk')[:limit])
    count = 0
    for obligation in obligations:
        module = obligation.payload['module']
        met = False
        if obligation.event_id:
            from django.db.models import Subquery
            confirmed = obligation_publications(obligation).filter(published_at__lte=obligation.deadline_at).values('epoch')
            met = models.RaceLifecycleReceipt.objects.filter(kind='probe',event_id=obligation.event_id,
                occurred_at__gte=obligation.recorded_at, occurred_at__lte=obligation.deadline_at, epoch__in=Subquery(confirmed),
                payload__visibility__contains={module:'visible'}).exists()
        _, created = models.RaceLifecycleReceipt.objects.get_or_create(idempotency_key=canonical_sha(['obligation-result', obligation.idempotency_key]),
            defaults=dict(kind='obligation_met' if met else 'deadline', target_key=obligation.target_key,
                event_id=obligation.event_id, occurred_at=obligation.deadline_at, recorded_at=now,
                deadline_at=obligation.deadline_at, evidence_refs=obligation.evidence_refs,
                payload=dict(obligation=obligation.idempotency_key, module=module, stage='required_material_missing',
                             input_version=obligation.payload['input_version'])))
        count += int(created and not met)
    return count


def record_probe_repairs(probe, *, publication, now):
    """外部实际可见的确定资料关闭对应模块超时，不伪造事实审核或抹除历史。"""
    from django.db.models import Exists, OuterRef
    from django.db.models.fields.json import KeyTextTransform
    repaired = models.RaceLifecycleReceipt.objects.annotate(resolved=KeyTextTransform('resolved_deadline', 'payload')).filter(
        kind='repair', resolved=OuterRef('idempotency_key'))
    deadlines = models.RaceLifecycleReceipt.objects.annotate(repaired=Exists(repaired)).filter(
        event_id=probe.event_id, kind='deadline', repaired=False, deadline_at__lte=probe.occurred_at,
        recorded_at__lte=now).order_by('pk')[:100]
    for deadline in deadlines:
        module = deadline.payload.get('module')
        if (module not in ('racecard', 'result') or probe.payload['visibility'].get(module) != 'visible'
                or publication.snapshot[module]['maturity'] not in ('confirmed', 'corrected')):
            continue
        if deadline.payload.get('obligation'):
            obligation = models.RaceLifecycleReceipt.objects.get(idempotency_key=deadline.payload['obligation'], kind='obligation')
            if not obligation_publications(obligation).filter(pk=publication.pk).exists():
                continue
        models.RaceLifecycleReceipt.objects.get_or_create(
            idempotency_key=canonical_sha(['repair-deadline', deadline.idempotency_key]),
            defaults=dict(kind='repair', target_key=deadline.target_key, event_id=probe.event_id,
                occurred_at=probe.occurred_at, recorded_at=now, epoch=probe.epoch,
                payload=dict(resolved_deadline=deadline.idempotency_key, module=module),
                evidence_refs=[f'probe:{probe.pk}', f'epoch:{publication.pk}']))


def measure_epoch_latency(*, event_id, epoch, module, candidate_sha256, as_of):
    """固定发布版本与外部探针进入 R01；未知时钟保持未知，不用入库时间冒充首发。"""
    if module not in ('racecard', 'result'):
        raise ValueError('latency_module')
    published = models.RaceLifecycleReceipt.objects.get(kind='publish', event_id=event_id, epoch=epoch)
    publication = models.RaceLifecycleEpochPublication.objects.get(event_id=event_id, epoch=epoch)
    document = published.payload['input']
    capability = 'roster' if module == 'racecard' else 'result'
    evidence = next((e for e in document['snapshot']['evidence'] if e['capability']==capability), None)
    if evidence is None:
        return dict(measurement={'status':'material_missing'}, epoch=epoch, module=module)
    observation = models.RaceResultObservation.objects.get(pk=publication.snapshot[module]['evidence']['observation_id'])
    context = dict(candidate_sha256=candidate_sha256, target_key=f'canonical:{event_id}', capability=capability,
        document=document, source_evidence_id=evidence['evidence_id'], material_content_sha256=observation.normalized_sha256,
        public_version=f'epoch:{epoch}:{publication.snapshot_sha256}', permission_version=canonical_sha(publication.authorization),
        threshold_seconds=published.payload.get('threshold_seconds', 600),
        source_clock_trusted=observation.field_provenance.get('source_clock_trusted') is True,
        as_of=stamp(as_of))
    receipt = models.RaceLifecycleReceipt.objects.filter(kind='probe', event_id=event_id, epoch=epoch,
        occurred_at__lte=as_of, recorded_at__lte=as_of, payload__visibility__contains={module:'visible'}).order_by('occurred_at','pk').first()
    probe = None
    if receipt:
        probe = dict(external=True, target_key=context['target_key'], input_version=document['input_version'],
            material_content_sha256=context['material_content_sha256'], public_version=context['public_version'],
            permission_version=context['permission_version'], first_visible_at=stamp(receipt.occurred_at),
            last_not_visible_at=None, stable_interval=False, evidence_refs=[f'probe:{receipt.pk}'],
            clock_trusted=receipt.payload.get('clock_trusted') is True)
    value = dict(context=context, probe=probe)
    parsed = contracts.parse_latency(value, expected_context_sha256=canonical_sha(context))
    return dict(epoch=epoch, module=module, input=value, context_sha256=canonical_sha(context),
                measurement=contracts.evaluate_latency(parsed))
