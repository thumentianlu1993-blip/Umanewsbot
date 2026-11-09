"""已授权旧登记交接：保留证据、整包事务和默认拒绝。"""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from stable import models
from stable import test_france_automation as france_tests
from stable.test_france_automation import ROOT, NOW
from stable.services.france_release import execute, event_baseline, series_baseline


def snapshot(event):
    value = {'event_id': event.pk}
    for key, model in [('projection', models.RaceEventProjectionControl),
                       ('tracking', models.RaceEventLiveTracking),
                       ('enrollment', models.RaceDataSyncEnrollment),
                       ('lifecycle', models.RaceEventLifecycleControl)]:
        value[key] = model.objects.filter(event=event).values().first()
    value['checkpoints'] = list(models.RaceEventLiveProviderCheckpoint.objects.filter(
        tracking__event=event).order_by('pk').values())
    return json.loads(json.dumps(value, default=str))


@override_settings(**france_tests.FranceResultWorkflowTests._overridden_settings)
class FranceLegacyHandoffTests(TestCase):
    def setUp(self):
        france_tests.FranceResultWorkflowTests.setUp(self)

    def prepare(self, owner='historical'):
        source = models.RaceResultSourceIdentity.objects.create(
            event=self.event, source_key='zeturf', region_code='france',
            identity_namespace='legacy', external_race_id='old-race',
            canonical_url='https://www.zeturf.fr/fr/course/old',
            host='www.zeturf.fr', registry_digest='a' * 64)
        models.RaceEventProjectionControl.objects.create(event=self.event,
            write_owner=owner, owner_generation=4, owner_manifest_sha256='b' * 64)
        enrollment = models.RaceDataSyncEnrollment.objects.create(event=self.event,
            source_identity=source, authority_version=1,
            state='retired' if owner == 'historical' else 'enrolled',
            standing_policy_digest='c' * 64, route_digest='d' * 64,
            event_snapshot_sha256='e' * 64, projection_owner_generation=3 if owner == 'historical' else 4,
            enrollment_generation=3 if owner == 'historical' else 4,
            manifest_sha256='f' * 64, entry_sha256='1' * 64,
            retired_at=NOW if owner == 'historical' else None)
        tracking = models.RaceEventLiveTracking.objects.create(event=self.event,
            tracking_enabled=owner == 'data_sync', claim_generation=7,
            checkpoint_payload={'old_evidence': 'preserve'})
        models.RaceEventLiveProviderCheckpoint.objects.create(tracking=tracking,
            source_key='zeturf', data_kind='result', last_observation_hash='2' * 64)
        models.RaceEventLifecycleControl.objects.create(event=self.event,
            manifest_data={'old_evidence': {'manifest': 'b' * 64}})
        models.OperationLog.objects.create(action_type='historical_old', target_type='event',
            target_id=str(self.event.pk), detail='old audit retained')
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'manifest.json'
        archive = json.loads((ROOT / 'historical.json').read_text())
        archive = {k: [d for d in docs if '/1695527-' in d['url']] for k, docs in archive.items()}
        raw = json.dumps(archive).encode(); self.path.with_name('archive.json').write_bytes(raw)
        self.before = snapshot(self.event)
        self.manifest = dict(schema_version=1, action='france_release_data',
            policy_digest=self.policy.digest,
            archive=dict(file='archive.json', sha256=hashlib.sha256(raw).hexdigest(), observed_at=NOW.isoformat()),
            items=[dict(event_id=self.event.pk, event_baseline=event_baseline(self.event),
                series_id=self.event.race_series_id, series_baseline=series_baseline(self.event.race_series),
                fields={}, names=["Prix de l'Avenir"], source_url=self.base+'arrivee-rapports', result_rows=6)],
            legacy_handoffs=[self.before])
        self.old_source = list(models.RaceResultSourceIdentity.objects.filter(pk=source.pk).values())
        self.old_checkpoint = list(models.RaceEventLiveProviderCheckpoint.objects.filter(source_key='zeturf').values())
        return enrollment

    def run_release(self, apply=False):
        raw = json.dumps(self.manifest).encode(); self.path.write_bytes(raw)
        return execute(self.path, hashlib.sha256(raw).hexdigest(), now=NOW, apply=apply)

    def test_historical_dry_run_apply_replay_preserves_registration_and_history(self):
        enrollment = self.prepare()
        self.assertEqual(self.run_release()['action'], 'dry_run_rolled_back')
        self.assertEqual(snapshot(self.event), self.before)
        self.assertFalse(models.OperationLog.objects.filter(action_type='france_legacy_handoff').exists())
        self.assertEqual(self.run_release(True)['result_rows'], 6)
        enrollment.refresh_from_db()
        self.assertEqual((enrollment.authority_version, enrollment.state, enrollment.enrollment_generation), (2, 'enrolled', 5))
        self.assertNotEqual(enrollment.source_identity_id, self.old_source[0]['id'])
        self.assertIsNone(enrollment.retired_at)
        self.assertEqual(list(models.RaceResultSourceIdentity.objects.filter(pk=self.old_source[0]['id']).values()), self.old_source)
        self.assertEqual(list(models.RaceEventLiveProviderCheckpoint.objects.filter(source_key='zeturf').values()), self.old_checkpoint)
        self.assertTrue(models.OperationLog.objects.filter(action_type='historical_old', detail='old audit retained').exists())
        audit = json.loads(models.OperationLog.objects.get(action_type='france_legacy_handoff').detail)
        self.assertEqual(audit['before'], self.before)
        self.assertEqual(audit['after']['enrollment']['id'], enrollment.pk)
        after = snapshot(self.event)
        self.assertEqual(self.run_release(True)['action'], 'replay')
        self.assertEqual(snapshot(self.event), after)
        self.assertEqual(models.OperationLog.objects.filter(action_type='france_legacy_handoff').count(), 1)

    def test_active_v1_conversion_and_default_discovery_rejects(self):
        enrollment = self.prepare('data_sync')
        from stable.services.race_data_source_adapters import fetch_bound_observation
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        value = fetch_bound_observation(event=self.event, route=self.policy.routes[0], now=NOW,
            fetcher=lambda url, **kw: (ROOT/('avenir-result.html' if url.endswith('arrivee-rapports') else 'avenir-card.html')).read_text())
        self.assertEqual(attach_multisource_observation(value, policy=self.policy, now=NOW).reason_code, 'legacy_conversion_required')
        self.assertEqual(snapshot(self.event), self.before)
        self.assertEqual(self.run_release(True)['action'], 'applied')
        enrollment.refresh_from_db(); self.assertEqual(enrollment.enrollment_generation, 5)

    def test_default_release_rejects_old_owner(self):
        self.prepare(); self.manifest.pop('legacy_handoffs')
        with self.assertRaisesMessage(ValueError, 'owner_conflict'): self.run_release(True)
        self.assertEqual(snapshot(self.event), self.before)

    def test_late_failure_rolls_back_handoff_and_all_new_evidence(self):
        self.prepare()
        from stable.services import france_release
        original = france_release.run_multisource_claim
        def fail_after_publication(**kwargs):
            self.assertTrue(original(**kwargs)['processed'])
            raise ValueError('late_failure')
        with patch.object(france_release, 'run_multisource_claim', side_effect=fail_after_publication):
            with self.assertRaisesMessage(ValueError, 'late_failure'): self.run_release(True)
        self.assertEqual(snapshot(self.event), self.before)
        self.assertEqual(models.RaceResultSourceIdentity.objects.count(), 1)
        self.assertFalse(models.RaceDataSyncSourceBinding.objects.exists())
        self.assertFalse(self.event.results.exists())
        self.assertFalse(models.OperationLog.objects.filter(action_type='france_legacy_handoff').exists())

    def test_state_generation_and_checkpoint_drift_rejected(self):
        self.prepare()
        for model, field, value in [(models.RaceEventProjectionControl, 'owner_generation', 6),
                                    (models.RaceDataSyncEnrollment, 'state', 'paused'),
                                    (models.RaceEventLiveTracking, 'claim_generation', 9)]:
            obj = model.objects.get(event=self.event); old = getattr(obj, field)
            model.objects.filter(pk=obj.pk).update(**{field: value})
            with self.assertRaisesMessage(ValueError, 'handoff_snapshot_drift'): self.run_release(True)
            model.objects.filter(pk=obj.pk).update(**{field: old})
        models.RaceEventLiveProviderCheckpoint.objects.update(last_observation_hash='3' * 64)
        with self.assertRaisesMessage(ValueError, 'handoff_snapshot_drift'): self.run_release(True)

    def test_current_manual_pause_and_claim_rejected_even_with_matching_snapshot(self):
        self.prepare()
        models.RaceEventLifecycleControl.objects.filter(event=self.event).update(manual_pause_reason='manual')
        self.manifest['legacy_handoffs'] = [snapshot(self.event)]
        with self.assertRaisesMessage(ValueError, 'manual_lock'): self.run_release(True)
        models.RaceEventLifecycleControl.objects.filter(event=self.event).update(manual_pause_reason='')
        models.RaceEventLiveTracking.objects.filter(event=self.event).update(active_attempt_token='claim')
        self.manifest['legacy_handoffs'] = [snapshot(self.event)]
        with self.assertRaisesMessage(ValueError, 'handoff_active_claim'): self.run_release(True)
        models.RaceEventLiveTracking.objects.filter(event=self.event).update(active_attempt_token='')
        models.RaceEventLifecycleControl.objects.filter(event=self.event).update(claim_token='lifecycle-claim')
        self.manifest['legacy_handoffs'] = [snapshot(self.event)]
        with self.assertRaisesMessage(ValueError, 'handoff_active_claim'): self.run_release(True)

    def test_unconsumed_or_duplicate_handoff_rejected(self):
        self.prepare(); self.manifest['legacy_handoffs'].append(self.before)
        with self.assertRaisesMessage(ValueError, 'handoff_scope'): self.run_release(True)
        self.manifest['legacy_handoffs'] = [self.before]; self.manifest['items'][0]['result_rows'] = 0
        with self.assertRaisesMessage(ValueError, 'handoff_scope'): self.run_release(True)

    def test_crosswalk_cannot_use_number_to_replace_a_different_horse_or_manual_row(self):
        self.prepare()
        from stable.services.race_data_source_adapters import fetch_bound_observation
        value = fetch_bound_observation(event=self.event, route=self.policy.routes[0], now=NOW,
            fetcher=lambda url, **kw: (ROOT/('avenir-result.html' if url.endswith('arrivee-rapports') else 'avenir-card.html')).read_text())
        mapping = {}
        for index, row in enumerate(value['roster'], 1):
            runner = models.RaceEventRunner.objects.create(event=self.event, sort_order=index,
                horse_number=row['number'], horse_name=row['horse_name'])
            mapping[row['external_runner_id']] = runner.pk
        # 发布器使用的是归档文档hash，完整fixture复用同一内容、不同载体。
        from stable.services.race_data_source_adapters import canonical_sha
        document = next(d for d in json.loads(self.path.with_name('archive.json').read_text())['results'])
        crosswalk = dict(source_external_race_id=value['external_race_id'], source_raw_sha256=canonical_sha(document), runners=mapping)
        self.manifest['legacy_handoffs'][0]['runner_crosswalk'] = crosswalk
        first = self.event.runners.first(); name = first.horse_name
        first.horse_name = 'Unrelated horse'; first.save()
        self.manifest['items'][0]['event_baseline'] = event_baseline(self.event)
        with self.assertRaisesMessage(ValueError, 'attach_handoff_runner_identity'): self.run_release(True)
        self.assertEqual(models.RaceResultSourceIdentity.objects.count(), 1)
        first.horse_name = name; first.manual_lock_flags = {'horse_name': True}; first.save()
        self.manifest['items'][0]['event_baseline'] = event_baseline(self.event)
        with self.assertRaisesMessage(ValueError, 'attach_handoff_runner_identity'): self.run_release(True)
        self.assertEqual(models.RaceDataSyncEnrollment.objects.get(event=self.event).authority_version, 1)

    def test_successful_handoff_does_not_authorize_later_same_number_horse_change(self):
        self.prepare()
        from datetime import timedelta
        from stable.services.race_data_source_adapters import canonical_sha, fetch_bound_observation, run_multisource_claim
        from stable.services.race_data_sync_control import claim_multisource_events
        def original_fetch(url, **kwargs):
            return (ROOT/('avenir-result.html' if url.endswith('arrivee-rapports') else 'avenir-card.html')).read_text()
        value = fetch_bound_observation(event=self.event, route=self.policy.routes[0], now=NOW, fetcher=original_fetch)
        mapping = {}
        for index, row in enumerate(value['roster'], 1):
            runner = models.RaceEventRunner.objects.create(event=self.event, sort_order=index,
                horse_number=row['number'], horse_name=row['horse_name'])
            mapping[row['external_runner_id']] = runner.pk
        doc = json.loads(self.path.with_name('archive.json').read_text())['results'][0]
        self.manifest['legacy_handoffs'][0]['runner_crosswalk'] = dict(
            source_external_race_id=value['external_race_id'], source_raw_sha256=canonical_sha(doc), runners=mapping)
        self.manifest['items'][0]['event_baseline'] = event_baseline(self.event)
        self.assertEqual(self.run_release(True)['action'], 'applied')
        original = list(self.event.results.order_by('pk').values())
        horse = value['roster'][0]['horse_name']; later = NOW + timedelta(hours=1)
        def changed_fetch(url, **kwargs):
            text = original_fetch(url)
            self.assertIn(horse, text)
            return text.replace(horse, 'Unrelated replacement horse')
        from stable.services.race_data_sync_results import _source_runner_id
        source = models.RaceDataSyncEnrollment.objects.get(event=self.event).source_identity
        for direct in (False, True):
            for external_id, pk in mapping.items():
                runner = models.RaceEventRunner.objects.get(pk=pk)
                refs = dict(runner.source_refs); refs.pop('geny', None)
                if refs.get('source_key') == 'geny':
                    refs.pop('source_key'); refs.pop('external_runner_id', None)
                if direct: refs['geny'] = external_id
                runner.source_refs = refs; runner.save(update_fields=('source_refs',))
                self.assertEqual(_source_runner_id(runner=runner, source=source), external_id if direct else '')
            if direct: later += timedelta(hours=1)
            with patch('django.utils.timezone.now', return_value=later):
                claims = claim_multisource_events(event_ids=[self.event.pk], now=later, historical=True)
                self.assertEqual(len(claims), 1)
                result = run_multisource_claim(claim=claims[0], now=later, fetcher=changed_fetch)
            self.assertFalse(result['processed'], result)
            self.assertEqual(result['reason'], 'result_roster_incomplete')
            self.assertEqual(list(self.event.results.order_by('pk').values()), original)
