"""P02 T03/T05/T11：从真实既有 writer 到 epoch 的集成回归。"""
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings
from stable import models
from stable.services import race_events
from stable.services.race_data_sync_results import apply_data_sync_result_observation
from stable import test_race_data_sync_results as fixtures
NOW = fixtures.NOW


@override_settings(**fixtures.RaceDataSyncResultApplicationTests._overridden_settings)
@override_settings(RACE_DATA_SYNC_ENABLED=True, RACE_DATA_SYNC_RESULT_APPLY_ENABLED=True,
                   RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED=True, RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED=True,
                   RACE_LIFECYCLE_V2_WRITE_ENABLED=True)
class LifecyclePublicationTests(TestCase):
    _source = fixtures.RaceDataSyncResultApplicationTests._source
    def _observation(self, source, source_class, rows, *, observed_at=NOW, race_status='complete', result_phase='official', provenance_overrides=None):
        payload = dict(external_race_id=source.external_race_id, off_time=self.event.race_datetime.isoformat(),
            region='japan_jra', course='Tokyo', race_name='Data Sync Result', race_status=race_status, participants=rows)
        entry = next(entry for entry in self.roster.entries if entry.provider == source.source_key)
        provenance = dict(provider=source.source_key, region=source.region_code, source_class=source_class,
            registry_digest=self.roster.registry_digest, contract_version=entry.contract_version,
            contract_digest=entry.contract_digest, automation_allowed=True)
        provenance.update(provenance_overrides or {})
        return race_events.record_race_result_observation(source_identity_id=source.pk, observed_at=observed_at,
            source_updated_at=observed_at, parser_version='test-v1', raw_sha256=fixtures._sha(payload),
            result_phase=result_phase, normalized_payload=payload, field_provenance=provenance,
            parse_warnings=[], permission_classification='synthetic', acquisition_key=provenance.get('acquisition_key','')).observation
    _rows = staticmethod(fixtures.RaceDataSyncResultApplicationTests._rows)
    _public_enrollment = fixtures.RaceDataSyncResultApplicationTests._public_enrollment

    def setUp(self):
        fixtures.RaceDataSyncResultApplicationTests.setUp(self)
        self._public_enrollment()
        cohort = override_settings(RACE_LIFECYCLE_V2_EVENT_IDS=(self.event.pk,))
        cohort.enable()
        self.addCleanup(cohort.disable)
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def apply(self, observation, now=NOW):
        return apply_data_sync_result_observation(
            observation_id=observation.pk, expected_event_id=self.event.pk,
            now=now, project_current=True, correction_apply_enabled=True)

    def test_real_result_writer_persists_atomic_epoch_and_outbox(self):
        obs = self._observation(self.source, "licensed_api", self._rows())
        outcome = self.apply(obs)
        self.assertTrue(outcome.projected, outcome)
        state = models.RaceLifecyclePublicState.objects.filter(event=self.event).first()
        self.assertIsNotNone(state, "真实结果 writer 尚未持久化公开 epoch")
        self.assertEqual((state.epoch, state.result_maturity, state.result_revision_id),
                         (1, "confirmed", outcome.revision_id))
        pub = models.RaceLifecycleEpochPublication.objects.get(event=self.event, epoch=1)
        self.assertEqual(pub.result_revision_id, outcome.revision_id)
        self.assertEqual(models.RaceLifecycleDelivery.objects.filter(event=self.event).count(), 2)
        self.apply(obs)
        self.assertEqual(models.RaceLifecycleEpochPublication.objects.count(), 1)
        self.assertTrue(race_events.resolve_race_live_public_read(event_id=self.event.pk, now=NOW).visible)

    def test_conflicting_qualified_result_hides_existing_table_without_overwriting(self):
        first = self.apply(self._observation(self.source, "licensed_api", self._rows()))
        source2 = self._source("jra", "official_operator", "other")
        changed = self._rows()
        changed[0]["reported_finish_position"], changed[1]["reported_finish_position"] = 2, 1
        self.apply(self._observation(source2, "official_operator", changed, observed_at=NOW + timedelta(seconds=1)),
                   NOW + timedelta(seconds=1))
        decision = race_events.resolve_race_live_public_read(event_id=self.event.pk, now=NOW + timedelta(seconds=2))
        self.assertFalse(decision.visible, "来源冲突仍公开旧冠军")
        bulk = race_events.resolve_race_live_public_reads(event_ids=[self.event.pk], now=NOW + timedelta(seconds=2))
        self.assertFalse(bulk[self.event.pk].visible, "日历批量入口泄漏冲突冠军")
        self.control.refresh_from_db()
        self.assertEqual(self.control.current_result_revision_id, first.revision_id)

    def test_return_to_previous_content_creates_new_authorized_epoch(self):
        first_obs = self._observation(self.source, "licensed_api", self._rows(),
                                     result_phase="corrected", provenance_overrides={"correction_marker": True})
        first = self.apply(first_obs)
        changed = self._rows()
        changed[0]["reported_finish_position"], changed[1]["reported_finish_position"] = 2, 1
        second_obs = self._observation(self.source, "licensed_api", changed,
                                      observed_at=NOW + timedelta(seconds=1), result_phase="corrected",
                                      provenance_overrides={"correction_marker": True})
        self.apply(second_obs, NOW + timedelta(seconds=1))
        restored_obs = self._observation(
            self.source, "licensed_api", self._rows(), observed_at=NOW + timedelta(seconds=2),
            result_phase="corrected", provenance_overrides={"correction_marker": True, "acquisition_key": "c" * 64})
        restored = self.apply(restored_obs, NOW + timedelta(seconds=2))
        self.assertTrue(restored.projected)
        state = models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual((state.epoch, state.result_revision_id), (3, first.revision_id))
        self.assertEqual(models.RaceEventRevisionPublication.objects.count(), 2)
        self.assertEqual(models.RaceLifecycleEpochPublication.objects.count(), 3)
        self.apply(restored_obs, NOW + timedelta(seconds=3))
        self.assertEqual(models.RaceLifecycleEpochPublication.objects.count(), 3)

    @override_settings(RACE_DATA_SYNC_ENABLED_DATA_KINDS=("result", "racecard"))
    def test_same_card_content_confirmation_survives_restart_and_deadline(self):
        from stable.services.race_data_sync_pipeline import reconcile_racecard_observation, _ROSTER_ALLOWED_FIELDS
        from stable.services.race_data_source_adapters import canonical_sha
        self.event.race_datetime = NOW + timedelta(minutes=30)
        self.event.save()
        def card(maturity):
            payload = dict(schema_version=1, external_race_id=self.source.external_race_id,
                           off_time=self.event.race_datetime.isoformat(), region="japan_jra",
                           course="Tokyo", race_name="Data Sync Result", race_status="scheduled",
                           declaration_status=maturity,
                           participants=[dict(external_runner_id="horse-1", horse_name="Alpha", number="1",
                                              draw="1", jockey_name="Rider", trainer_name="Trainer",
                                              carried_weight="57", status="declared")])
            entry = next(x for x in self.roster.entries if x.provider == "the_racing_api")
            return models.RaceResultObservation.objects.create(
                source_identity=self.source, observed_at=NOW, source_updated_at=NOW,
                parser_version="test-v1", raw_sha256=canonical_sha(payload), normalized_sha256=canonical_sha(payload),
                result_phase="racecard", normalized_payload=payload,
                field_provenance=dict(provider="the_racing_api", region="japan_jra", source_class="licensed_api",
                    registry_digest=self.roster.registry_digest, contract_version=entry.contract_version,
                    contract_digest=entry.contract_digest, automation_allowed=True,
                    allowed_fields=list(_ROSTER_ALLOWED_FIELDS), roster_complete=True))
        for maturity in ("predicted", "confirmed"):
            obs = card(maturity)
            outcome = reconcile_racecard_observation(
                observation_id=obs.pk, expected_event_id=self.event.pk,
                allow_schedule_apply=False, allow_racecard_apply=True, task_id="card", run_id="card")
            self.assertIn(outcome.status, ("applied", "replayed"), outcome)
            state = models.RaceLifecyclePublicState.objects.filter(event=self.event).first()
            self.assertIsNotNone(state, "名单 writer 未保存成熟度")
            self.assertEqual(state.racecard_maturity, maturity)
            if maturity == "predicted":
                revision = state.racecard_revision_id
                self.assertEqual(state.racecard_deadline_at, NOW)
                page = self.client.get(self.event.get_absolute_url())
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, "Alpha")
                self.assertContains(page, "资料更新中")
            else:
                self.assertEqual(state.epoch, 2)
                self.assertEqual(state.racecard_revision_id, revision)
                self.assertIsNone(state.racecard_deadline_at)
                page = self.client.get(self.event.get_absolute_url())
                self.assertContains(page, "Alpha")
                self.assertContains(page, 'id="race-lifecycle-marker"')
                self.assertIn("no-store", page["Cache-Control"])

    def test_explicit_same_content_correction_recovers_conflict(self):
        self.apply(self._observation(self.source, "licensed_api", self._rows()))
        source2 = self._source("jra", "official_operator", "other")
        changed = self._rows()
        changed[0]["reported_finish_position"], changed[1]["reported_finish_position"] = 2, 1
        self.apply(self._observation(source2, "official_operator", changed,
                    observed_at=NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
        corrected = self._observation(self.source, "licensed_api", self._rows(),
            observed_at=NOW + timedelta(seconds=2), result_phase="corrected",
            provenance_overrides={"correction_marker": True})
        self.apply(corrected, NOW + timedelta(seconds=2))
        self.assertTrue(race_events.resolve_race_live_public_read(
            event_id=self.event.pk, now=NOW + timedelta(seconds=2)).visible)
        state = models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual(state.result_maturity, "corrected")
        self.assertEqual(state.result_evidence["observation_id"], corrected.pk)

    def test_calendar_uses_immutable_epoch_content(self):
        from stable.views import _group_race_events_by_date
        self.apply(self._observation(self.source, "licensed_api", self._rows()))
        models.RaceEventResult.objects.filter(event=self.event).update(horse_name="MUTABLE_LEAK")
        self.event.refresh_from_db()
        self.event.public_projection_write_owner = "data_sync"
        _group_race_events_by_date([self.event], today=NOW.date())
        self.assertTrue(self.event.top_results)
        self.assertNotIn("MUTABLE_LEAK", [r.horse_name for r in self.event.top_results])

    def test_provisional_hides_at_deadline_and_confirmation_restores(self):
        pending = self._observation(self.source, "licensed_api", self._rows(), result_phase="provisional", race_status="pending")
        outcome = self.apply(pending)
        self.assertTrue(outcome.projected, "已授权的完整待确认结果未进入 epoch")
        self.event.refresh_from_db()
        self.assertNotEqual(self.event.status, "finished")
        before = race_events.resolve_race_live_public_read(event_id=self.event.pk, now=NOW)
        self.assertTrue(before.visible)
        from stable.services.race_lifecycle_projection import public_modules
        self.assertFalse(public_modules(self.event.pk, now=NOW)["result"][0].is_confirmed)
        deadline = self.event.race_datetime + timedelta(minutes=60)
        self.assertFalse(race_events.resolve_race_live_public_read(event_id=self.event.pk, now=deadline).visible)
        confirmed = self._observation(self.source, "licensed_api", self._rows(), observed_at=NOW + timedelta(seconds=1))
        self.assertTrue(self.apply(confirmed, NOW + timedelta(seconds=1)).projected)
        self.assertTrue(race_events.resolve_race_live_public_read(event_id=self.event.pk, now=deadline).visible)

    def test_loaded_batch_does_not_query_per_event_and_revocation_fails_closed(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from stable.services.race_lifecycle_projection import load_public_batch, result_reads, public_modules
        self.apply(self._observation(self.source, "licensed_api", self._rows()))
        batch = load_public_batch([self.event.pk])
        with CaptureQueriesContext(connection) as queries:
            for _ in range(20):
                self.assertTrue(result_reads([self.event.pk], NOW, batch=batch)[self.event.pk].visible)
                self.assertTrue(public_modules(self.event.pk, now=NOW, loaded=batch[self.event.pk])["result"])
        self.assertEqual(len(queries), 0)
        self.source.identity_fields['publication_revoked'] = True
        self.source.save()
        self.assertFalse(race_events.resolve_race_live_public_read(event_id=self.event.pk, now=NOW).visible)

    def test_transaction_failure_rolls_back_epoch_and_legacy_projection(self):
        obs = self._observation(self.source, 'licensed_api', self._rows())
        with patch('stable.models.RaceLifecycleDelivery.objects.create', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                self.apply(obs)
        self.assertFalse(models.RaceLifecyclePublicState.objects.exists())
        self.assertFalse(models.RaceLifecycleEpochPublication.objects.exists())
        self.assertFalse(models.RaceEventResult.objects.filter(event=self.event).exists())
        self.control.refresh_from_db()
        self.assertIsNone(self.control.current_result_revision_id)

    def test_historical_audit_backfill_is_bound_and_idempotent(self):
        from stable.services import race_lifecycle_projection as service
        with override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=False):
            result = self.apply(self._observation(self.source, 'licensed_api', self._rows()))
        self.assertTrue(result.projected)
        self.assertFalse(models.RaceLifecyclePublicState.objects.exists())
        audit = getattr(service, 'compatibility_manifest', None)
        self.assertTrue(callable(audit), '缺少分批兼容审计入口')
        manifest = audit(event_ids=[self.event.pk], after_id=0)
        self.assertEqual(manifest['last_id'], self.event.pk)
        result = service.backfill_compatibility(manifest, expected_sha256=service.canonical_sha(manifest), now=NOW)
        self.assertEqual(result['applied'], [self.event.pk])
        result = service.backfill_compatibility(manifest, expected_sha256=service.canonical_sha(manifest), now=NOW)
        self.assertEqual(result['replayed'], [self.event.pk])
        self.assertEqual(models.RaceLifecycleEpochPublication.objects.count(), 1)

    def test_real_loader_preserves_maturity_and_unknown_source_clock(self):
        from stable.services.race_lifecycle_metrics import load_input
        self.apply(self._observation(self.source, 'licensed_api', self._rows()))
        document = load_input(self.event.pk, now=NOW).to_dict()
        self.assertEqual(document['snapshot']['materials'][0]['maturity'], 'confirmed')
        self.assertEqual(document['snapshot']['evidence'][0]['source_time']['precision'], 'unknown')
        self.assertIsNone(document['snapshot']['evidence'][0]['source_time']['published_at'])

    def test_deadline_worker_records_failure_once_and_requests_external_probe(self):
        from stable.services import race_lifecycle_projection as service
        self.apply(self._observation(self.source, 'licensed_api', self._rows(), result_phase='provisional', race_status='pending'))
        deadline = self.event.race_datetime + timedelta(minutes=60)
        worker = getattr(service, 'record_due_deadlines', None)
        self.assertTrue(callable(worker), '截止义务尚未进入持久账本')
        self.assertEqual(worker(now=deadline), 1)
        self.assertEqual(worker(now=deadline + timedelta(minutes=1)), 0)
        receipt = models.RaceLifecycleReceipt.objects.get(kind='deadline')
        self.assertEqual(receipt.deadline_at, deadline)
        self.assertEqual(receipt.occurred_at, deadline)
        self.assertTrue(models.RaceLifecycleDelivery.objects.filter(consumer='probe_result_deadline').exists())
        later = self._observation(self.source, 'licensed_api', self._rows(), observed_at=deadline + timedelta(minutes=2))
        self.apply(later, deadline + timedelta(minutes=2))
        self.assertEqual(models.RaceLifecycleReceipt.objects.filter(kind='deadline').count(), 1)

    def test_late_confirmation_preserves_deadline_when_worker_was_down(self):
        self.apply(self._observation(self.source, 'licensed_api', self._rows(), result_phase='provisional', race_status='pending'))
        later = self.event.race_datetime + timedelta(minutes=61)
        self.apply(self._observation(self.source, 'licensed_api', self._rows(), observed_at=later), later)
        self.assertEqual(models.RaceLifecycleReceipt.objects.filter(kind='deadline').count(), 1,
                         '修复覆盖了后台停机时已经发生的超时')

    def test_publication_saves_f01_input_for_historical_metrics(self):
        self.apply(self._observation(self.source, 'licensed_api', self._rows()))
        receipt = models.RaceLifecycleReceipt.objects.get(kind='publish')
        self.assertIn('input', receipt.payload, '历史计量缺少当时的版本输入')
        from stable.services.content_contracts import parse_input
        document = parse_input(receipt.payload['input']).to_dict()
        self.assertEqual(document['snapshot']['materials'][0]['maturity'], 'confirmed')

    def test_persisted_deadline_enters_strict_report_without_counting_publication_as_audit(self):
        from stable.services import race_lifecycle_metrics as metrics
        self.apply(self._observation(self.source, 'licensed_api', self._rows(), result_phase='provisional', race_status='pending'))
        publication = models.RaceLifecycleReceipt.objects.get(kind='publish')
        later = self.event.race_datetime + timedelta(minutes=61)
        self.apply(self._observation(self.source, 'licensed_api', self._rows(), observed_at=later), later)
        build = getattr(metrics, 'assemble_report', None)
        self.assertTrue(callable(build), '数据库截止记录未接入严格 R01 报告')
        version = publication.payload['input']
        window = dict(id='day', start=metrics.stamp(NOW-timedelta(hours=1)), end=metrics.stamp(later+timedelta(hours=1)))
        scope = dict(schema_version='r01.scope.v1', scope_ref='synthetic:scope', candidate_sha256='a'*64,
            targets=[dict(key=f'canonical:{self.event.pk}', event_id=self.event.pk, region='japan_jra',
                material_availability='unknown', required_intervals=[{k:window[k] for k in ('start','end')}],
                audit_fields=['identity','result'], versions=[version], current_input_version=version['input_version'])],
            aliases=[], complete_denominator=True)
        report = build(scope=scope, window=window, as_of=later+timedelta(minutes=1))
        summary = metrics.contracts.summarize(report)
        self.assertEqual(summary['targets'], 1)
        self.assertEqual(summary['stalled_targets'], 1)
        self.assertEqual(summary['audited'], 0)
        self.assertFalse(summary['measurement_complete'])

    @override_settings(RACE_LIFECYCLE_PUBLIC_ORIGIN='https://races.example.test')
    def test_probe_verifies_actual_epoch_rows_and_repair_keeps_deadline_history(self):
        from stable.services import race_lifecycle_projection as projection
        self.apply(self._observation(self.source, 'licensed_api', self._rows()))
        state = models.RaceLifecyclePublicState.objects.get(event=self.event)
        models.RaceLifecycleReceipt.objects.create(idempotency_key='d'*64, kind='deadline',
            event=self.event, target_key=f'canonical:{self.event.pk}', epoch=state.epoch,
            occurred_at=NOW-timedelta(minutes=1), recorded_at=NOW-timedelta(minutes=1),
            deadline_at=NOW-timedelta(minutes=1), payload={'module':'result', 'stage':'required_material_missing'})
        delivery = next(r for r in projection.claim_deliveries(now=NOW) if r.consumer == 'probe')
        page = self.client.get(self.event.get_absolute_url()).content.decode()
        # 修改 marker 与 DOM 中的 token 不能使自报数据冒充当前正确版本。
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(page, 'html.parser')
        import json
        marker = soup.find(id='race-lifecycle-marker')
        value = json.loads(marker.string)
        value['row_tokens']['result'][0] = 'forged'
        marker.string = json.dumps(value)
        soup.select('#results tbody tr')[0]['data-lifecycle-row'] = 'forged'
        with self.assertRaisesRegex(ValueError, 'probe_rows_mismatch'):
            projection.execute_delivery(delivery, now=NOW, fetcher=lambda _:str(soup))
        tampered = BeautifulSoup(page, 'html.parser')
        tampered.select('#results tbody tr')[0].select('td')[2].string = 'WRONG_VISIBLE_HORSE'
        with self.assertRaisesRegex(ValueError, 'probe_visible_content_mismatch'):
            projection.execute_delivery(delivery, now=NOW, fetcher=lambda _:str(tampered))
        projection.execute_delivery(delivery, now=NOW, fetcher=lambda _:page)
        self.assertEqual(models.RaceLifecycleReceipt.objects.filter(kind='probe').count(), 1)
        self.assertEqual(models.RaceLifecycleReceipt.objects.filter(kind='repair').count(), 1)
        self.assertEqual(models.RaceLifecycleReceipt.objects.filter(kind='deadline').count(), 1)
        projection.execute_delivery(delivery, now=NOW, fetcher=lambda _:page)
        self.assertEqual(models.RaceLifecycleReceipt.objects.filter(kind='repair').count(), 1)

    def test_schedule_change_recomputes_only_future_deadlines(self):
        from django.db import transaction
        from stable.services import race_lifecycle_projection as projection
        self.apply(self._observation(self.source, 'licensed_api', self._rows(), result_phase='provisional', race_status='pending'))
        old = models.RaceLifecyclePublicState.objects.get(event=self.event).result_deadline_at
        lifecycle = models.RaceEventLifecycleControl.objects.get(event=self.event)
        self.event.race_datetime += timedelta(hours=2)
        self.event.save()
        lifecycle.schedule_generation += 1
        lifecycle.save()
        function = getattr(projection, 'capture_schedule', None)
        self.assertTrue(callable(function), '改期未重算未到期义务')
        with transaction.atomic():
            function(event=self.event, control=self.control, lifecycle=lifecycle, now=NOW)
        state = models.RaceLifecyclePublicState.objects.get(event=self.event)
        self.assertEqual(state.result_deadline_at, old + timedelta(hours=2))
        self.assertEqual(state.schedule_generation, lifecycle.schedule_generation)
        self.assertFalse(models.RaceLifecycleReceipt.objects.filter(kind='deadline').exists())
        with transaction.atomic():
            self.event.status='cancelled'
            self.event.save()
            lifecycle.schedule_generation += 1
            lifecycle.save()
            function(event=self.event, control=self.control, lifecycle=lifecycle, now=old+timedelta(hours=3))
        state.refresh_from_db()
        self.assertIsNone(state.result_deadline_at)
        self.assertFalse(projection.public_modules(self.event.pk, now=old+timedelta(hours=3))['result'])
        self.assertTrue(models.RaceLifecycleReceipt.objects.filter(kind='deadline').exists())

    @override_settings(RACE_LIFECYCLE_PUBLIC_ORIGIN='https://races.example.test')
    def test_orm_latency_uses_external_probe_without_inventing_source_clock(self):
        from stable.services import race_lifecycle_metrics as metrics, race_lifecycle_projection as projection
        self.apply(self._observation(self.source, 'licensed_api', self._rows()))
        function = getattr(metrics, 'measure_epoch_latency', None)
        self.assertTrue(callable(function), '实际公开探针尚未接入 R01 时延合同')
        args = dict(event_id=self.event.pk, epoch=1, module='result', candidate_sha256='a'*64, as_of=NOW)
        report = function(**args)
        self.assertEqual(report['measurement']['status'], 'visibility_unverified')
        row = next(r for r in projection.claim_deliveries(now=NOW) if r.consumer=='probe')
        projection.execute_delivery(row, now=NOW, fetcher=lambda _:self.client.get(self.event.get_absolute_url()).content.decode())
        report = function(**args)
        self.assertEqual(report['measurement']['status'], 'source_time_unknown')
        self.assertIsNone(report['measurement']['upper_microseconds'])

    def test_home_and_other_event_series_history_use_epoch_and_hide_conflict(self):
        from stable.views import _public_today_races, _series_history_winners
        from django.db import transaction
        from stable.services.race_lifecycle_projection import hide_conflict
        self.apply(self._observation(self.source, 'licensed_api', self._rows()))
        series = models.RaceSeries.objects.create(key='epoch-series', country_region='japan', canonical_name_original='Epoch')
        self.event.refresh_from_db()
        self.event.race_series = series
        self.event.save()
        other = models.RaceEvent.objects.create(year=2027, slug='other-epoch', original_name='Other', race_series=series)
        models.RaceEventResult.objects.filter(event=self.event).update(horse_name='MUTABLE_LEAK')
        home, _ = _public_today_races()
        entry = next(r for r in home if r['event'].pk==self.event.pk)
        self.assertEqual(entry['winner'], self._rows()[0]['horse_name'])
        history = _series_history_winners(other)
        self.assertTrue(history)
        self.assertNotIn('MUTABLE_LEAK', [r.horse_name for r in history])
        with transaction.atomic():
            hide_conflict(event=self.event, control=self.control,
                lifecycle=models.RaceEventLifecycleControl.objects.get(event=self.event),
                observation=self._observation(self.source, 'licensed_api', self._rows()), now=NOW)
        self.assertEqual(_series_history_winners(other), [])

    def _card(self, *, name='Alpha', at=NOW, correction=False, status='scheduled', schedule_correction=False):
        from stable.services.race_data_sync_pipeline import _ROSTER_ALLOWED_FIELDS
        payload=dict(schema_version=1,external_race_id=self.source.external_race_id,
            off_time=self.event.race_datetime.isoformat(),region='japan_jra',course='Tokyo',
            race_name='Data Sync Result',race_status=status,declaration_status='confirmed',
            participants=[dict(external_runner_id='horse-1',horse_name=name,number='1',draw='1',
                jockey_name='Rider',trainer_name='Trainer',carried_weight='57',status='declared',odds='2.5',popularity=1)])
        entry=next(e for e in self.roster.entries if e.provider==self.source.source_key)
        return race_events.record_race_result_observation(source_identity_id=self.source.pk,observed_at=at,
            source_updated_at=at,parser_version='test-v1',raw_sha256=fixtures._sha(payload),result_phase='racecard',
            normalized_payload=payload,field_provenance=dict(provider=self.source.source_key,region='japan_jra',
                source_class='licensed_api',registry_digest=self.roster.registry_digest,contract_version=entry.contract_version,
                contract_digest=entry.contract_digest,automation_allowed=True,allowed_fields=list(_ROSTER_ALLOWED_FIELDS),
                roster_complete=True,card_correction_marker=correction,schedule_correction_marker=schedule_correction),parse_warnings=[],permission_classification='synthetic',
            acquisition_key=fixtures._sha([at.isoformat(),correction])).observation

    @override_settings(RACE_DATA_SYNC_ENABLED_DATA_KINDS=('result','racecard'))
    def test_card_replay_does_not_clear_conflict_and_locked_name_never_leaks(self):
        from stable.services.race_data_sync_pipeline import reconcile_racecard_observation
        from stable.services import race_lifecycle_projection as projection
        from django.db import transaction
        def apply(obs):
            return reconcile_racecard_observation(observation_id=obs.pk,expected_event_id=self.event.pk,
                allow_schedule_apply=False,allow_racecard_apply=True,task_id='card',run_id='card')
        original=self._card();apply(original)
        runner=models.RaceEventRunner.objects.get(event=self.event,external_runner_id='horse-1')
        runner.manual_lock_flags={'horse_name':True};runner.save()
        apply(self._card(name='FORBIDDEN_NAME',at=NOW+timedelta(seconds=1)))
        public=projection.public_modules(self.event.pk,now=NOW+timedelta(seconds=1))
        self.assertEqual(public['racecard'][0].horse_name,'Alpha')
        self.assertEqual(public['racecard'][0].odds_value,'2.5')
        self.assertEqual(public['racecard'][0].popularity,'1')
        state=models.RaceLifecyclePublicState.objects.get(event=self.event)
        latest=models.RaceResultObservation.objects.get(pk=state.racecard_evidence['observation_id'])
        conflict=self._card(name='CONFLICT',at=NOW+timedelta(seconds=2))
        with transaction.atomic():
            projection.hide_conflict(event=self.event,control=self.control,
                lifecycle=models.RaceEventLifecycleControl.objects.get(event=self.event),observation=conflict,
                now=NOW+timedelta(seconds=2),kind='racecard')
        apply(latest)
        state.refresh_from_db();self.assertEqual(state.racecard_visibility,'verifying')
        apply(self._card(at=NOW+timedelta(seconds=3),correction=True))
        state.refresh_from_db();self.assertEqual(state.racecard_visibility,'visible')

    @override_settings(RACE_LIFECYCLE_PUBLIC_ORIGIN='https://races.example.test')
    def test_new_scope_version_is_not_fulfilled_by_old_visible_probe(self):
        from copy import deepcopy
        from stable.services import race_lifecycle_metrics as metrics, race_lifecycle_projection as projection
        from stable.services.content_contracts import build_input
        self.apply(self._observation(self.source,'licensed_api',self._rows()))
        row=next(r for r in projection.claim_deliveries(now=NOW) if r.consumer=='probe')
        projection.execute_delivery(row,now=NOW,fetcher=lambda _:self.client.get(self.event.get_absolute_url()).content.decode())
        old=models.RaceLifecycleReceipt.objects.get(kind='publish').payload['input']
        snapshot=deepcopy(old['snapshot']);snapshot['materials'][0]['revision_ref']='expected:new-correction'
        future=build_input(snapshot,evaluated_at=metrics.stamp(NOW),policy_ref=old['policy_ref'],generations=old['input_version']['generations']).to_dict()
        key=f'canonical:{self.event.pk}'
        window=dict(id='new-version',start=metrics.stamp(NOW),end=metrics.stamp(NOW+timedelta(hours=1)))
        scope=dict(schema_version='r01.scope.v1',scope_ref='synthetic:new-scope',candidate_sha256='a'*64,
            targets=[dict(key=key,event_id=self.event.pk,region='japan_jra',material_availability='unknown',
                required_intervals=[{k:window[k] for k in ('start','end')}],audit_fields=['result'],versions=[old,future],current_input_version=future['input_version'])],aliases=[],complete_denominator=True)
        manifest=dict(scope=scope,window=window,obligations=[dict(target_key=key,module='result',
            deadline_at=metrics.stamp(NOW+timedelta(minutes=5)),evidence_refs=['synthetic:expected-version'])])
        metrics.register_scope(manifest,expected_sha256=projection.canonical_sha(manifest),now=NOW)
        self.assertEqual(metrics.record_scope_deadlines(now=NOW+timedelta(minutes=5)),1)
        self.assertFalse(models.RaceLifecycleReceipt.objects.filter(kind='obligation_met').exists())


    @override_settings(RACE_DATA_SYNC_ENABLED_DATA_KINDS=('result','racecard','race_time'))
    def test_cancelled_status_recovers_only_from_explicit_newer_source_correction(self):
        from stable.services.race_data_sync_pipeline import reconcile_racecard_observation
        def apply(obs):
            return reconcile_racecard_observation(observation_id=obs.pk,expected_event_id=self.event.pk,
                allow_schedule_apply=True,allow_racecard_apply=False,task_id='schedule',run_id='schedule')
        first=apply(self._card(status='cancelled'))
        self.event.refresh_from_db();self.assertEqual(self.event.status,'cancelled',first)
        before=models.RaceEventLifecycleControl.objects.get(event=self.event).schedule_generation
        apply(self._card(at=NOW+timedelta(seconds=1)))
        self.event.refresh_from_db();self.assertEqual(self.event.status,'cancelled')
        apply(self._card(at=NOW+timedelta(seconds=2),schedule_correction=True))
        self.event.refresh_from_db();self.assertEqual(self.event.status,'scheduled')
        self.assertGreater(models.RaceEventLifecycleControl.objects.get(event=self.event).schedule_generation,before)

    def test_historical_revision_keeps_names_after_new_authorizing_observation(self):
        from django.db import transaction
        from stable.services import race_lifecycle_projection as projection
        original=self._observation(self.source,'licensed_api',self._rows())
        create_item=models.RaceEventRevisionItem.objects.create
        def historical_item(**values):
            values['field_provenance'].pop('display_name',None)
            return create_item(**values)
        with override_settings(RACE_LIFECYCLE_V2_WRITE_ENABLED=False), patch(
                'stable.models.RaceEventRevisionItem.objects.create',side_effect=historical_item):
            result=self.apply(original)
        revision=models.RaceEventRevision.objects.get(pk=result.revision_id)
        self.assertTrue(all('display_name' not in item.field_provenance for item in revision.items.all()))
        newer=self._observation(self.source,'licensed_api',self._rows(),observed_at=NOW+timedelta(seconds=1),
            provenance_overrides={'acquisition_key':'9'*64})
        self.control.refresh_from_db();self.event.refresh_from_db()
        with transaction.atomic():
            projection.capture_result(event=self.event,control=self.control,
                lifecycle=models.RaceEventLifecycleControl.objects.get(event=self.event),revision=revision,
                observation=newer,now=NOW+timedelta(seconds=1))
        modules=projection.public_modules(self.event.pk,now=NOW+timedelta(seconds=1))
        self.assertEqual(modules['visibility']['result'],'visible')
        self.assertEqual([row.horse_name for row in modules['result']],['Alpha','Beta'])

    @override_settings(RACE_LIFECYCLE_PUBLIC_ORIGIN='https://races.example.test')
    def _check_frozen_result_successor(self, *, provisional=False, wrong_generation=False):
        from stable.services import race_lifecycle_metrics as metrics, race_lifecycle_projection as projection
        if provisional:
            self.apply(self._observation(self.source,'licensed_api',self._rows(),result_phase='provisional',race_status='pending'))
        initial=metrics.load_input(self.event.pk,now=NOW).to_dict()
        if not provisional:
            self.assertEqual(initial['snapshot']['materials'],[])
        if wrong_generation:
            from stable.services.content_contracts import build_input
            generations=dict(initial['input_version']['generations'])
            generations['schedule']+=1
            initial=build_input(initial['snapshot'],evaluated_at=initial['evaluated_at'],
                policy_ref=initial['policy_ref'],generations=generations).to_dict()
        key=f'canonical:{self.event.pk}'
        window=dict(id='first-result',start=metrics.stamp(NOW),end=metrics.stamp(NOW+timedelta(hours=1)))
        scope=dict(schema_version='r01.scope.v1',scope_ref='synthetic:first-result',candidate_sha256='a'*64,
            targets=[dict(key=key,event_id=self.event.pk,region='japan_jra',material_availability='unknown',
                required_intervals=[{k:window[k] for k in ('start','end')}],audit_fields=['result'],
                versions=[initial],current_input_version=initial['input_version'])],aliases=[],complete_denominator=True)
        manifest=dict(scope=scope,window=window,obligations=[dict(target_key=key,module='result',
            deadline_at=metrics.stamp(NOW+timedelta(minutes=5)),evidence_refs=['synthetic:missing-result'])])
        metrics.register_scope(manifest,expected_sha256=projection.canonical_sha(manifest),now=NOW)
        at=NOW+timedelta(minutes=1)
        self.apply(self._observation(self.source,'licensed_api',self._rows(),observed_at=at),at)
        with patch('django.utils.timezone.now',return_value=at):
            epoch=models.RaceLifecyclePublicState.objects.get(event=self.event).epoch
            row=next(r for r in projection.claim_deliveries(now=at) if r.consumer=='probe' and r.epoch==epoch)
            projection.execute_delivery(row,now=at,fetcher=lambda _:self.client.get(self.event.get_absolute_url()).content.decode())
        self.assertEqual(metrics.record_scope_deadlines(now=NOW+timedelta(minutes=5)),int(wrong_generation))
        self.assertEqual(models.RaceLifecycleReceipt.objects.filter(kind='obligation_met').count(),int(not wrong_generation))

    def test_frozen_missing_result_is_fulfilled_by_first_confirmed_successor(self):
        self._check_frozen_result_successor()

    def test_frozen_provisional_result_is_fulfilled_by_confirmed_successor(self):
        self._check_frozen_result_successor(provisional=True)

    def test_frozen_missing_result_cannot_be_fulfilled_across_generation(self):
        self._check_frozen_result_successor(wrong_generation=True)
