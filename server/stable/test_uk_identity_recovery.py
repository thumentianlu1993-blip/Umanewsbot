"""已审核英国目录冷启动；不预置来源身份，不访问真实网络。"""
import json
from copy import deepcopy
from django.test import TestCase, override_settings
from stable import models
from stable import test_uk_workflow as workflow
from stable.services.france_field_repair import frozen
from stable.services.race_source_identity import resolve_observation
from stable.services.race_data_source_adapters import fetch_bound_observation, run_multisource_claim
from stable.services.race_data_sync_enrollment import discover_multisource_events
from stable.services.race_data_sync_control import claim_multisource_events

NOW = workflow.NOW


@override_settings(**workflow.UKWorkflowTests._overridden_settings)
class UKIdentityRecoveryTests(TestCase):
    def setUp(self):
        workflow.UKWorkflowTests.setUp(self)
        self.source.delete()
        series = models.RaceSeries.objects.create(key='reviewed-uk-example', country_region='united_kingdom',
            canonical_name_original='Example Stakes', review_status='approved')
        self.event.race_series = series
        self.event.source_refs = {
            'uk_target_v1': {'external_race_id': '', 'name_keys': ['examplestakes'],
                'reviewed_date': str(self.event.local_date), 'reviewed_course': self.event.racecourse, 'catalog_index': 1},
            'uk_catalogue_v1': {'source_url': 'https://media.britishhorseracing.com/bha/example.pdf',
                'source_sha256': 'c' * 64, 'physical_page': 1, 'name': 'Example Stakes'}}
        self.event.save()
        self.manifest = 'd' * 64
        self.target = models.HistoricalRaceEventTarget.objects.create(event=self.event, race_series=series,
            year=2026, country_region='united_kingdom', local_date=self.event.local_date,
            racecourse=self.event.racecourse, resolution_status='imported',
            source_refs={'uk_release_manifest': self.manifest})
        self.save_receipt()

    def save_receipt(self):
        self.saved = {'event_ids': [self.event.pk], 'report': {'events': [{'event_id': self.event.pk}]},
            'after': {'RaceEvent': frozen(list(models.RaceEvent.objects.filter(pk=self.event.pk).values())),
                'HistoricalRaceEventTarget': frozen(list(models.HistoricalRaceEventTarget.objects.filter(pk=self.target.pk).values()))}}
        self.receipt, _ = models.OperationLog.objects.update_or_create(action_type='uk_release_data',
            target_type='manifest', target_id=self.manifest, defaults={'detail': json.dumps(self.saved)})

    def fetch(self, url, **kwargs):
        if '/results/' in url:
            return json.dumps(self.result)
        if '/v1/racecards/pro?' in url:
            return json.dumps({'racecards': [self.card], 'total': 1})
        return json.dumps(self.card)

    def observation(self):
        return fetch_bound_observation(event=self.event, route=self.route, now=NOW, fetcher=self.fetch)

    def test_released_catalogue_without_series_name_recovers_through_natural_entry(self):
        from stable.services.race_events import resolve_race_live_public_read
        from stable.services.race_public_coverage import reconcile_public_race_coverage
        self.assertFalse(self.event.source_identities.exists())
        self.assertFalse(self.event.race_series.names.exists())
        self.assertFalse(self.event.identity_keys.exists())
        report = discover_multisource_events(now=NOW, policy=self.policy, fetcher=self.fetch)
        self.assertTrue(self.event.source_identities.exists(), report['outcomes'])
        claims = claim_multisource_events(event_ids=[self.event.pk], now=NOW, historical=True)
        self.assertEqual(len(claims), 1)
        outcome = run_multisource_claim(claim=claims[0], now=NOW, fetcher=self.fetch)
        self.assertTrue(outcome['processed'], outcome)
        self.event.refresh_from_db()
        self.assertEqual(self.event.results.count(), 2)
        self.assertIsNotNone(self.event.result_confirmed_at)
        self.assertTrue(resolve_race_live_public_read(event_id=self.event.pk, now=NOW).visible)
        report = reconcile_public_race_coverage(now=NOW)
        self.assertFalse(next(row for row in report['entries'] if row['event_id'] == self.event.pk)['issue'])

    def test_target_marker_without_committed_receipt_cannot_grant_identity(self):
        self.receipt.delete()
        self.assertNotEqual(resolve_observation(self.observation(), route=self.route, now=NOW).status, 'exact')

    def test_restored_release_cannot_grant_identity(self):
        models.OperationLog.objects.create(action_type='uk_release_restore', target_type='manifest', target_id=self.manifest)
        self.assertNotEqual(resolve_observation(self.observation(), route=self.route, now=NOW).status, 'exact')

    def test_current_target_name_keys_cannot_replace_reviewed_receipt(self):
        value = self.observation()
        self.event.source_refs['uk_target_v1']['name_keys'] = ['otherstakes']
        self.event.save()
        value['raw_names'] = ['Other Stakes']
        self.assertNotEqual(resolve_observation(value, route=self.route, now=NOW).status, 'exact')

    def test_unreviewed_or_changed_catalogue_is_not_a_strong_anchor(self):
        value = self.observation()
        original = deepcopy(self.event.source_refs)
        for key in ('source_sha256', 'source_url'):
            with self.subTest(key=key):
                self.event.source_refs = deepcopy(original)
                self.event.source_refs['uk_catalogue_v1'][key] = 'e' * 64 if key == 'source_sha256' else 'https://example.com/changed'
                self.event.save()
                self.assertNotEqual(resolve_observation(value, route=self.route, now=NOW).status, 'exact')
        self.event.source_refs = original
        self.event.save()
        self.event.race_series.review_status = 'pending'
        self.event.race_series.save()
        self.assertNotEqual(resolve_observation(value, route=self.route, now=NOW).status, 'exact')

    def test_other_day_venue_or_unreviewed_name_cannot_claim_target(self):
        value = self.observation()
        for updates in ({'local_date': '2026-10-31'}, {'venue_key': 'unknown'}, {'raw_names': ['Different Stakes']}):
            with self.subTest(updates=updates):
                self.assertNotEqual(resolve_observation({**value, **updates}, route=self.route, now=NOW).status, 'exact')

    def test_release_receipt_must_include_target_and_event(self):
        value = self.observation()
        for part in ('RaceEvent', 'HistoricalRaceEventTarget'):
            with self.subTest(part=part):
                saved = deepcopy(self.saved)
                saved['after'][part] = []
                self.receipt.detail = json.dumps(saved)
                self.receipt.save()
                self.assertNotEqual(resolve_observation(value, route=self.route, now=NOW).status, 'exact')

    def test_preexisting_source_for_other_event_disagrees_with_catalogue(self):
        value = self.observation()
        other = models.RaceEvent.objects.create(year=2026, edition_year=2026, slug='other-uk-2026',
            original_name='Other Race', country_region='united_kingdom', racecourse='Newmarket',
            local_date=self.event.local_date, timezone_name='Europe/London', visibility_status='published')
        self.source.pk = None
        self.source.event = other
        self.source.save()
        decision = resolve_observation(value, route=self.route, now=NOW)
        self.assertEqual(decision.reason, 'strong_identity_disagreement')
        self.assertFalse(self.event.source_identities.exists())

    def test_two_reviewed_targets_matching_same_source_are_rejected(self):
        other = models.RaceEvent.objects.get(pk=self.event.pk)
        other.pk = None
        other.slug = 'second-approved-uk-2026'
        other.race_series = models.RaceSeries.objects.create(key='second-uk-example',
            country_region='united_kingdom', canonical_name_original='Second Example', review_status='approved')
        other.save()
        target = models.HistoricalRaceEventTarget.objects.create(event=other, race_series=other.race_series,
            year=2026, country_region='united_kingdom', local_date=other.local_date,
            racecourse=other.racecourse, resolution_status='imported', source_refs={'uk_release_manifest': self.manifest})
        self.saved['event_ids'].append(other.pk)
        self.saved['report']['events'].append({'event_id': other.pk})
        self.saved['after']['RaceEvent'] += frozen(list(models.RaceEvent.objects.filter(pk=other.pk).values()))
        self.saved['after']['HistoricalRaceEventTarget'] += frozen(list(models.HistoricalRaceEventTarget.objects.filter(pk=target.pk).values()))
        self.receipt.detail = json.dumps(self.saved)
        self.receipt.save()
        self.assertEqual(resolve_observation(self.observation(), route=self.route, now=NOW).reason,
            'strong_identity_disagreement')

    def test_receipt_does_not_bypass_manual_lock_or_apply_switch(self):
        from stable.services.race_data_sync_enrollment import attach_multisource_observation
        value = self.observation()
        self.event.manual_lock_flags = {'identity': True}
        self.event.save()
        decision = attach_multisource_observation(value, policy=self.policy, now=NOW)
        self.assertEqual(decision.reason_code, 'manual_or_visibility_block')
        self.assertFalse(self.event.source_identities.exists())
        self.event.manual_lock_flags = {}
        self.event.save()
        with self.settings(RACE_DATA_MULTISOURCE_APPLY_ENABLED=False):
            self.assertEqual(attach_multisource_observation(value, policy=self.policy, now=NOW).reason_code,
                'multisource_apply_disabled')
        self.assertFalse(self.event.source_identities.exists())

    def test_receipt_does_not_bypass_expired_source_route(self):
        from datetime import timedelta
        self.assertNotEqual(resolve_observation(self.observation(), route=self.route,
            now=NOW + timedelta(days=900)).status, 'exact')

    def test_reviewed_chase_names_accept_source_steeple_chase_without_new_alias(self):
        self.event.original_name = 'Betfair Lancashire Chase'
        self.event.source_refs['uk_target_v1']['name_keys'] = ['betfairchase', 'lancashirechase']
        self.event.save()
        self.save_receipt()
        for payload in (self.card, self.result):
            payload['race_name'] = 'Betfair Steeple Chase (Grade 1)'
        match = resolve_observation(self.observation(), route=self.route, now=NOW)
        self.assertEqual(match.status, 'exact')
        self.assertEqual(match.event_id, self.event.pk)
        self.assertEqual(match.evidence['uk_catalogue_receipts'][self.event.pk]['manifest_sha256'], self.manifest)

    def test_cross_midnight_discovery_still_uses_original_reviewed_date(self):
        from datetime import timedelta
        from unittest.mock import patch
        later = NOW + timedelta(days=1)
        with patch('django.utils.timezone.now', return_value=later):
            report = discover_multisource_events(now=later, policy=self.policy, fetcher=self.fetch)
            self.assertTrue(self.event.source_identities.exists(), report['outcomes'])
            claims = claim_multisource_events(event_ids=[self.event.pk], now=later, historical=True)
            self.assertEqual(len(claims), 1)
            self.assertTrue(run_multisource_claim(claim=claims[0], now=later, fetcher=self.fetch)['processed'])
        self.event.refresh_from_db()
        self.assertEqual(self.event.results.count(), 2)

    def test_ambiguous_source_cards_remain_blocked_before_identity_admission(self):
        duplicate = deepcopy(self.card)
        duplicate['race_id'] = 'rac_456'
        def fetch(url, **kwargs):
            if '/v1/racecards/pro?' in url:
                return json.dumps({'racecards': [self.card, duplicate], 'total': 2})
            return self.fetch(url, **kwargs)
        report = discover_multisource_events(now=NOW, policy=self.policy, fetcher=fetch)
        self.assertFalse(self.event.source_identities.exists(), report['outcomes'])
        self.assertFalse(self.event.results.exists())
