from datetime import date
from django.core.exceptions import ValidationError
from django.test import TestCase
from stable import models
from stable.views import _public_race_calendar_base_queryset


class USDivisionTests(TestCase):
    def make_event(self, slug, **kwargs):
        return models.RaceEvent.objects.create(year=2026,slug=slug, original_name='Glen Cove',
            chinese_name='格伦科夫锦标'+slug,country_region='united_states',racecourse='Belmont Park',
            grade_text='G3',normalized_grade='G3',surface='turf',visibility_status='published',
            local_date=date(2026,10,16),timezone_name='America/New_York',**kwargs)

    def test_separate_occurrences_preserve_annual_entry_and_calendar(self):
        parent=self.make_event('glen-cove')
        first=self.make_event('glen-cove-r5',division_parent=parent)
        second=self.make_event('glen-cove-r8',division_parent=parent)
        self.assertEqual(set(parent.divisions.values_list('id',flat=True)), {first.pk,second.pk})
        for e in [parent,first,second]:
            response=self.client.get(e.public_path)
            self.assertEqual(response.status_code,200)
        response=self.client.get(parent.public_path)
        self.assertContains(response,first.public_path)
        self.assertContains(response,second.public_path)
        self.assertContains(response,'分场赛事')
        self.assertNotContains(response,'id="runners"')
        self.assertNotContains(response,'id="results"')
        self.assertNotContains(response,'赛期已过，资料待补')
        response=self.client.get('/races/',{'year':'2026','month':'10','region':'united_states','tab':'all'},follow=True)
        self.assertContains(response,first.public_path)
        self.assertContains(response,second.public_path)
        self.assertNotContains(response,'href="'+parent.public_path+'"')

    def test_division_cannot_cross_year_region_or_nest(self):
        parent=self.make_event('parent')
        child=self.make_event('child',division_parent=parent)
        for changes in [dict(year=2027),dict(country_region='japan'),dict(division_parent=child),dict(division_parent=parent,race_series_id=123)]:
            obj=models.RaceEvent(year=2026,edition_year=2026,original_name='Glen Cove',country_region='united_states',division_parent=parent)
            for k,v in changes.items():setattr(obj,k,v)
            with self.assertRaises(ValidationError):obj.validate_division()
        parent.division_parent=child
        with self.assertRaises(ValidationError):parent.validate_division()

    def test_approved_annual_alias_does_not_override_division_identity(self):
        from stable.test_race_multisource_identity import policy_payload, observation, NOW
        from stable.services.race_data_source_adapters import parse_multisource_policy
        from stable.services.race_source_identity import resolve_observation, identity_key
        series=models.RaceSeries.objects.create(key='glen-cove',canonical_name_original='Glen Cove',country_region='united_states',review_status='approved')
        models.RaceSeriesName.objects.create(series=series,text='Glen Cove',source_refs={'primary':'https://toba.org/graded-stakes/2026-races/'})
        parent=self.make_event('hub',race_series=series)
        data=policy_payload('us_racing','united_states')
        data['routes'][0].update(country_region='united_states',operator='us',timezone='America/New_York',venue_aliases={'BEL':['Belmont Park']})
        route=parse_multisource_policy(data,now=NOW).routes[0]
        for number in ['5','8']:
            child=self.make_event('race-'+number,division_parent=parent)
            value=observation(provider='us_racing',region='united_states',identity_namespace=route.identity_namespace,
                operator='us',venue_key='BEL',local_date='2026-10-16',timezone='America/New_York',race_number=number,
                raw_names=['Glen Cove'],external_race_id='BEL-2026-10-16-'+number)
            before=resolve_observation(value,route=route,now=NOW)
            self.assertNotEqual(before.status,'exact')
            models.RaceEventIdentityKey.objects.create(event=child,**identity_key(value))
            for _ in range(2):
                match=resolve_observation(value,route=route,now=NOW)
                self.assertEqual((match.status,match.event_id),('exact',child.pk))

    def test_not_run_source_has_consistent_public_status(self):
        from stable.views import _public_race_status_label
        event=self.make_event('not-run',source_refs={'us_not_run':{'source_url':'https://toba.org/graded-stakes/2026-races/'}})
        self.assertEqual(_public_race_status_label(event,date(2026,11,12)),'本年度未举办')

    def test_series_history_includes_both_division_winners(self):
        from stable.views import _series_history_winners
        series=models.RaceSeries.objects.create(key='glen-history',canonical_name_original='Glen Cove',country_region='united_states',review_status='approved')
        parent=self.make_event('history-hub',race_series=series)
        first=self.make_event('history-r5',division_parent=parent)
        second=self.make_event('history-r8',division_parent=parent)
        for event,name in [(first,'First division winner'),(second,'Second division winner')]:
            models.RaceEventResult.objects.create(event=event,finish_position=1,horse_name=name,is_confirmed=True)
        expected={'First division winner','Second division winner'}
        self.assertEqual({row.horse_name for row in _series_history_winners(parent)},expected)
        self.assertEqual({row.horse_name for row in _series_history_winners(first,exclude_result_event_id=first.pk)},{'Second division winner'})
