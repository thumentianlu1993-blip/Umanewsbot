"""本轮冻结资料包的事务回填验收，不接触网络或通知。"""
import copy
import importlib.util
import json
import tempfile
from datetime import date
from pathlib import Path

from django.conf import settings
from django.test import TestCase, TransactionTestCase
from django.db import connection, close_old_connections, transaction
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from unittest import skipUnless
from django.utils import timezone

from stable import models as m


class BackfillFixture:
    def setUp(self):
        path = Path(settings.BASE_DIR).parent / 'scripts/backfill_reviewed_race_gaps.py'
        spec = importlib.util.spec_from_file_location('gap_patch', path)
        self.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.s)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.event = m.RaceEvent.objects.create(
            year=2026, slug='gap-test', original_name='Test Stakes',
            country_region='japan', racecourse='東京', local_date=date(2026, 7, 19),
            timezone_name='Asia/Tokyo', visibility_status='published', status='scheduled',
        )
        self.old = m.RaceEventResult.objects.create(
            event=self.event, finish_position=1, horse_number='1', horse_name='Alpha',
            jockey_name='Existing Jockey', finish_time='1:20.0', odds_value='4.0',
            source_refs={'original': 'preserved'}, is_confirmed=False,
        )
        self.source_rows = [dict(horse_name='Alpha', horse_number='1',
                                reported_finish_position=1, running_status='finished')]

    def package(self, *, authority='official', provider='jra', source_rows=None):
        source_rows = copy.deepcopy(source_rows if source_rows is not None else self.source_rows)
        before = self.s.snapshot(self.event.pk)
        rows = []
        for i, source in enumerate(source_rows, 1):
            old = next((r for r in before['results'] if
                        (r['horse_name'], r['horse_number']) ==
                        (source['horse_name'], source['horse_number'])), None)
            row = {f: copy.deepcopy(old[f]) if old else self.s.result_default(f)
                   for f in self.s.RESULT_FIELDS}
            row.update(source, id=old['id'] if old else None, finish_position=i,
                       official_finish_position=source['reported_finish_position']
                       if authority == 'official' else None, is_confirmed=True)
            rows.append(row)
        evidence = b'<html>complete source snapshot</html>'
        (self.root / 'source.html').write_bytes(evidence)
        source = dict(provider=provider, authority=authority,
                      url='https://www.jra.go.jp/datafile/seiseki/replay/2026/063.html'
                      if provider == 'jra' else 'https://www.sportinglife.com/racing/results/2026-07-19/test/123/test',
                      path='source.html', sha256=self.s.bytes_sha(evidence),
                      event_id=self.event.pk, local_date='2026-07-19', racecourse='東京',
                      title='Test Stakes', rows=source_rows)
        entry = dict(event_id=self.event.pk, before_sha256=self.s.digest(before),
                     before=before, results=rows, source=source,
                     confirmed_at=timezone.now().isoformat())
        manifest = dict(schema_version=1, reviewer='test-reviewer', events=[entry])
        return manifest

    def run_package(self, package, *, apply=True, fault_hook=None):
        data = json.dumps(package, ensure_ascii=False, sort_keys=True, default=str).encode()
        path = self.root / 'manifest.json'
        path.write_bytes(data)
        return self.s.execute(path, self.s.bytes_sha(data), apply=apply, fault_hook=fault_hook)


class ReviewedGapBackfillTests(BackfillFixture, TestCase):
    def test_dry_run_zero_writes_then_in_place_preserves_full_fields(self):
        package = self.package()
        before = self.s.snapshot(self.event.pk)
        self.assertEqual(self.run_package(package, apply=False)['events'][0]['status'], 'dry_run')
        self.assertEqual(self.s.snapshot(self.event.pk), before)
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'applied')
        self.old.refresh_from_db()
        self.assertTrue(self.old.is_confirmed)
        self.assertEqual(self.old.jockey_name, 'Existing Jockey')
        self.assertEqual(self.old.odds_value, '4.0')
        self.assertEqual(self.old.source_refs['original'], 'preserved')
        self.assertEqual(self.event.results.count(), 1)
        self.assertEqual(self.event.runners.count(), 0)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, 'finished')
        self.assertIsNone(self.event.race_datetime)

    def test_replay_and_full_field_drift_verification(self):
        package = self.package()
        self.run_package(package)
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'already_applied')
        m.RaceEventResult.objects.filter(pk=self.old.pk).update(jockey_name='Drift')
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'blocked')

    def test_result_field_drift_after_freeze_blocks(self):
        package = self.package()
        m.RaceEventResult.objects.filter(pk=self.old.pk).update(finish_time='1:19.0')
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'blocked')
        self.old.refresh_from_db()
        self.assertFalse(self.old.is_confirmed)

    def test_all_managed_owners_block_even_if_baseline_includes_them(self):
        for owner in ['live', 'data_sync', 'historical', 'manual_paused']:
            with self.subTest(owner=owner):
                m.RaceEventProjectionControl.objects.update_or_create(
                    event=self.event, defaults={'write_owner': owner})
                self.assertEqual(self.run_package(self.package())['events'][0]['status'], 'blocked')
        self.assertFalse(m.OperationLog.objects.filter(action_type='reviewed_gap_backfill').exists())

    def test_lifecycle_and_manual_flags_block(self):
        m.RaceEventLifecycleControl.objects.create(event=self.event)
        self.assertEqual(self.run_package(self.package())['events'][0]['status'], 'blocked')
        m.RaceEventLifecycleControl.objects.filter(event=self.event).delete()
        self.event.manual_lock_flags = {'results': True}
        self.event.save(update_fields=['manual_lock_flags'])
        self.assertEqual(self.run_package(self.package())['events'][0]['status'], 'blocked')

    def test_field_authority_lock_blocks(self):
        m.RaceEventFieldAuthority.objects.create(event=self.event, subject_type='event',
            subject_key='', field_name='status', manual_lock=True)
        self.assertEqual(self.run_package(self.package())['events'][0]['status'], 'blocked')

    def test_third_party_never_official(self):
        package = self.package(authority='official', provider='sporting_life')
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'blocked')
        package = self.package(authority='human_reviewed_reference', provider='sporting_life')
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'applied')
        self.old.refresh_from_db()
        self.assertIsNone(self.old.official_finish_position)

    def test_ties_nonfinish_and_new_row_are_not_fake_positions(self):
        rows = [self.source_rows[0], dict(horse_name='Beta', horse_number='2',
            reported_finish_position=1, running_status='dead_heat'),
            dict(horse_name='Gamma', horse_number='3', reported_finish_position=None,
                 running_status='pulled_up')]
        package = self.package(source_rows=rows)
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'applied')
        self.assertEqual(list(self.event.results.values_list('reported_finish_position', flat=True)), [1, 1, None])

    def test_position_swap_preserves_ids_and_rollback_is_atomic(self):
        second = m.RaceEventResult.objects.create(event=self.event, finish_position=2,
            horse_number='2', horse_name='Beta', is_confirmed=False)
        rows = [dict(horse_name='Beta', horse_number='2', reported_finish_position=1,
                     running_status='finished'), dict(self.source_rows[0], reported_finish_position=2)]
        package = self.package(source_rows=rows)
        before = self.s.snapshot(self.event.pk)
        def fail(**kwargs):
            raise RuntimeError('injected')
        self.assertEqual(self.run_package(package, fault_hook=fail)['events'][0]['status'], 'blocked')
        self.assertEqual(self.s.snapshot(self.event.pk), before)
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'applied')
        self.assertEqual(list(self.event.results.values_list('id', flat=True)), [second.pk, self.old.pk])

    def test_partial_roster_duplicate_unknown_or_wrong_identity_block(self):
        for mutate in [lambda e: e['source']['rows'].clear(),
                       lambda e: e['results'].append(copy.deepcopy(e['results'][0])),
                       lambda e: e['results'][0].update(running_status='unknown'),
                       lambda e: e['source'].update(local_date='2026-07-20'),
                       lambda e: e['results'][0].update(horse_name='Different'),
                       lambda e: e['results'][0].update(reported_finish_position=None)]:
            package = self.package(); mutate(package['events'][0])
            self.assertEqual(self.run_package(package)['events'][0]['status'], 'blocked')

    def test_bad_manifest_sha_or_changed_cached_source_blocks(self):
        package = self.package()
        path = self.root / 'manifest.json'; path.write_text(json.dumps(package, default=str))
        with self.assertRaises(ValueError):
            self.s.execute(path, 'a' * 64)
        (self.root / 'source.html').write_text('tampered')
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'blocked')

    def test_missing_old_row_blocks_and_does_not_leave_stale_result(self):
        package = self.package(); package['events'][0]['results'][0]['id'] = None
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'blocked')
        self.assertEqual(self.event.results.count(), 1)

    def test_no_winner_invalid_competition_ranks_and_stale_semantics_block(self):
        cases = [
            [dict(self.source_rows[0], reported_finish_position=None, running_status='pulled_up')],
            [dict(self.source_rows[0], reported_finish_position=2),
             dict(horse_name='Beta', horse_number='2', reported_finish_position=2, running_status='finished')],
            [self.source_rows[0], dict(horse_name='Beta', horse_number='2', reported_finish_position=2, running_status='finished'),
             dict(horse_name='Gamma', horse_number='3', reported_finish_position=2, running_status='dead_heat'),
             dict(horse_name='Delta', horse_number='4', reported_finish_position=3, running_status='finished')],
        ]
        for rows in cases:
            self.assertEqual(self.run_package(self.package(source_rows=rows))['events'][0]['status'], 'blocked')
        package = self.package(authority='human_reviewed_reference', provider='sporting_life')
        package['events'][0]['results'][0]['source_refs']['official_finish_position'] = 1
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'blocked')

    def test_dnf_old_rank_moved_to_history_has_correct_public_display(self):
        self.old.source_refs = {'official_finish_position': 1, 'original': 'preserved'}
        self.old.save(update_fields=['source_refs'])
        rows = [dict(horse_name='Beta', horse_number='2', reported_finish_position=1,
                     running_status='finished'),
                dict(self.source_rows[0], reported_finish_position=None, running_status='pulled_up')]
        package = self.package(source_rows=rows)
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'blocked')
        refs = package['events'][0]['results'][1]['source_refs']
        refs['backfill_previous_semantics'] = {'official_finish_position': refs.pop('official_finish_position')}
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'applied')
        response = self.client.get('/races/2026/gap-test/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['winner'].horse_name, 'Beta')
        self.assertEqual(response.context['results'][1].display_finish_position, '中止')
        self.old.refresh_from_db()
        self.assertEqual(self.old.source_refs['original'], 'preserved')


@skipUnless(connection.vendor == 'postgresql', 'requires PostgreSQL row locks')
class ReviewedGapBackfillPostgresTests(BackfillFixture, TransactionTestCase):
    def race_mutation(self, mutate):
        package = self.package()
        started = Event()
        def apply():
            close_old_connections()
            try:
                started.set()
                return self.run_package(package)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                event = m.RaceEvent.objects.select_for_update().get(pk=self.event.pk)
                future = pool.submit(apply)
                self.assertTrue(started.wait(5))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.3)
                mutate(event)
            report = future.result(timeout=10)
        self.assertEqual(report['events'][0]['status'], 'blocked')
        self.old.refresh_from_db()
        self.assertFalse(self.old.is_confirmed)
        self.assertFalse(m.OperationLog.objects.filter(action_type='reviewed_gap_backfill').exists())

    def test_owner_taken_while_waiting_blocks(self):
        self.race_mutation(lambda e: m.RaceEventProjectionControl.objects.create(event=e, write_owner='data_sync'))

    def test_field_lock_taken_while_waiting_blocks(self):
        self.race_mutation(lambda e: m.RaceEventFieldAuthority.objects.create(
            event=e, subject_type='event', subject_key='', field_name='status', manual_lock=True))

    def test_result_updated_while_waiting_blocks(self):
        self.race_mutation(lambda e: m.RaceEventResult.objects.filter(event=e).update(finish_time='drift'))


class RetiredShadowFixture(BackfillFixture):
    def setUp(self):
        super().setUp()
        self.old.delete()
        self.event.delete()
        self.event = m.RaceEvent.objects.create(id=948, year=2026, slug='retired-test',
            original_name='Test Stakes', country_region='japan', racecourse='東京',
            local_date=date(2026, 7, 19), timezone_name='Asia/Tokyo',
            visibility_status='published', status='scheduled')
        self.old = m.RaceEventResult.objects.create(event=self.event, finish_position=1,
            horse_number='1', horse_name='Alpha', is_confirmed=False)
        self.ctrl = m.RaceEventLifecycleControl.objects.create(event=self.event, mode='shadow')
        now = timezone.now()
        self.registry = m.RaceEventLifecycleEnforceRegistry.objects.create(
            root_sha256='a'*64, generation=1, membership_sha256='b'*64, member_count=1,
            state='retired', is_active=False, approved_commit='c'*40, scope_sha256='d'*64,
            census_cutoff=now, apply_expires_at=now, runtime_valid_until=now)
        self.member = m.RaceEventLifecycleEnforceMembership.objects.create(
            registry=self.registry, event=self.event, state='retired', entry_sha256='e'*64,
            source_enrollment_sha256='f'*64, schedule_generation=0, schedule_hash='0'*64,
            country_region='japan', timezone_name='Asia/Tokyo')


class RetiredShadowBackfillTests(RetiredShadowFixture, TestCase):
    def test_retired_shadow_results_only_and_full_replay(self):
        package = self.package(); before = self.s.protected(self.s.snapshot(948))
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'applied')
        self.assertEqual(self.s.protected(self.s.snapshot(948)), before)
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'already_applied')

    def test_active_membership_registry_due_claim_or_pointer_rejects(self):
        changes = [(self.member, {'state':'active'}), (self.registry, {'is_active':True}),
            (self.registry, {'state':'active'}), (self.ctrl, {'next_refresh_at':timezone.now()}),
            (self.ctrl, {'claim_token':'active'}), (self.ctrl, {'claim_expires_at':timezone.now()}),
            (self.ctrl, {'manifest_data':{'enforce_registry': {'root':'active'}}}),
            (self.ctrl, {'manifest_data':{'race_data_sync': {'enabled':True}}}),
            (self.ctrl, {'manual_pause_reason':'hold'}), (self.ctrl, {'mode':'off'})]
        for obj, values in changes:
            old = {k:getattr(obj,k) for k in values}
            type(obj).objects.filter(pk=obj.pk).update(**values)
            self.assertEqual(self.run_package(self.package())['events'][0]['status'], 'blocked')
            type(obj).objects.filter(pk=obj.pk).update(**old)
        self.member.delete()
        self.assertEqual(self.run_package(self.package())['events'][0]['status'], 'blocked')

    def test_membership_drift_after_freeze_rejects(self):
        package = self.package()
        m.RaceEventLifecycleEnforceMembership.objects.filter(pk=self.member.pk).update(entry_sha256='1'*64)
        self.assertEqual(self.run_package(package)['events'][0]['status'], 'blocked')


@skipUnless(connection.vendor == 'postgresql', 'requires PostgreSQL advisory lock')
class RetiredShadowConcurrencyTests(RetiredShadowFixture, TransactionTestCase):
    def test_registry_activation_barrier_then_revalidation(self):
        from stable.services.race_event_lifecycle_enforce import _advisory_lock as acquire_registry_exclusive_advisory_lock
        package=self.package(); started=Event()
        def apply():
            close_old_connections()
            try:
                started.set()
                return self.run_package(package)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                acquire_registry_exclusive_advisory_lock()
                future=pool.submit(apply)
                self.assertTrue(started.wait(5))
                with self.assertRaises(TimeoutError): future.result(timeout=0.3)
                m.RaceEventLifecycleEnforceRegistry.objects.filter(pk=self.registry.pk).update(is_active=True,state='active')
            self.assertEqual(future.result(timeout=10)['events'][0]['status'], 'blocked')
        self.old.refresh_from_db(); self.assertFalse(self.old.is_confirmed)
