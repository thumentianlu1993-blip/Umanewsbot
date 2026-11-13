"""公开赛事五地区边界：关联入口、分页与缓存均在过滤后计算。"""
from datetime import date
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from stable import models as m, views
from stable import test_public_navigation_and_attribution as fixtures
from stable.services.race_event_public_cache import public_race_calendar_years

ALLOWED = ('japan', 'hong_kong', 'france', 'united_states', 'united_kingdom')
HIDDEN = ('australia', 'germany', 'ireland', 'middle_east', 'other')


@override_settings(ALLOWED_HOSTS=['testserver'])
class FiveRegionPublicTests(TestCase):
    make_article = fixtures.PublicNavigationAndAttributionTests.make_article
    make_profile = fixtures.PublicNavigationAndAttributionTests.make_profile

    def setUp(self):
        cache.clear()
        self.today = timezone.localdate(timezone=views.BEIJING)

    def event(self, region, **extra):
        values = dict(year=self.today.year, slug=f'{region}-{m.RaceEvent.objects.count()}',
                      original_name=f'Event {region} {m.RaceEvent.objects.count()}',
                      country_region=region, local_date=self.today, grade_text='G1',
                      normalized_grade=m.RaceGrade.G1, priority='P0',
                      visibility_status='published', data_quality_status='complete')
        values.update(extra)
        return m.RaceEvent.objects.create(**values)

    def test_calendar_tabs_and_manual_region_queries(self):
        events = [self.event(r) for r in ALLOWED + HIDDEN]
        for region in ('', *ALLOWED, *HIDDEN):
            with self.subTest(region=region):
                response = self.client.get('/races/', {'tab': 'all', 'year': self.today.year, 'region': region})
                self.assertEqual(response.status_code, 200)
                self.assertEqual({r['value'] for r in response.context['region_tabs']}, {'', *ALLOWED})
                for event in events:
                    if event.country_region in HIDDEN:
                        self.assertNotContains(response, event.original_name)
        self.assertEqual(m.RaceEvent.objects.count(), 10)

    def test_allowed_details_and_hidden_canonical_and_legacy_paths(self):
        for region in ALLOWED + HIDDEN:
            event = self.event(region)
            legacy = m.RaceEventPublicPath.objects.create(event=event, year=event.year, slug=event.slug+'-old', path_kind='legacy')
            with self.subTest(region=region):
                self.assertEqual(self.client.get(event.public_path).status_code, 200 if region in ALLOWED else 404)
                self.assertEqual(self.client.get(f'/races/{legacy.year}/{legacy.slug}/').status_code, 301 if region in ALLOWED else 404)

    def test_homepage_and_focus_filter_before_limits(self):
        hidden = [self.event('ireland') for _ in range(5)]
        allowed = self.event('japan')
        rows, _ = views._public_today_races()
        self.assertEqual([r['event'].pk for r in rows], [allowed.pk])
        self.assertEqual(views._public_next_key_race(), allowed)
        for events in (None, [*hidden, allowed]):
            self.assertEqual([e.pk for e in views._public_weekly_focus_events(events=events, today=self.today)], [allowed.pk])

    def test_years_and_sitemap_exclude_hidden_and_ignore_previous_cache(self):
        visible = self.event('france', year=2021, local_date=date(2021, 5, 1))
        self.event('ireland', year=1990, local_date=date(1990, 5, 1))
        cache.set('race-events:public:calendar-years:v2', [1990, 2021])
        cache.set('race-events:public:sitemap-count:v1', 999)
        self.assertEqual(public_race_calendar_years(), [2021])
        self.assertEqual(list(views._race_sitemap_queryset()), [visible])
        from stable.services.race_event_public_cache import public_race_sitemap_count
        self.assertEqual(public_race_sitemap_count(views._race_sitemap_queryset()), 1)

    def test_news_links_hide_races_but_keep_news(self):
        article = self.make_article('ie-news', 'Irish news remains', racing_region='ireland')
        allowed, hidden = self.event('japan'), self.event('ireland')
        for event in (allowed, hidden):
            m.ArticleRaceLink.objects.create(article=article, event=event, status='manual')
        row = views._public_published_articles().get(pk=article.pk)
        self.assertEqual([link.event_id for link in row.public_race_links], [allowed.pk])
        response = self.client.get(f'/news/{article.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, hidden.public_path)
        self.assertContains(response, allowed.public_path)

    def test_career_associations_filter_before_pagination_and_major_wins(self):
        profile = self.make_profile(racing_region='ireland')
        jp, uk, hidden = self.event('japan'), self.event('united_kingdom'), self.event('ireland')
        jr = m.RaceEventResult.objects.create(event=jp, horse_name='JP', finish_position=1)
        hr = m.RaceEventResult.objects.create(event=hidden, horse_name='IE', finish_position=1)
        cases = [(jp, None, 'ireland', True), (None, jr, 'ireland', True),
                 (jp, jr, '', True), (None, None, 'france', True),
                 (hidden, None, 'japan', False), (None, hr, 'japan', False),
                 (jp, hr, 'japan', False), (uk, jr, 'japan', False),
                 (None, None, '', False), (None, None, 'ireland', False)]
        visible = []
        for i, (event, result, region, show) in enumerate(cases):
            record = m.HorseRaceRecord.objects.create(horse_profile=profile, event=event, result=result,
                race_name=f'Career {i}', race_region=region, finish_position='1', normalized_grade='g2' if show else 'g1')
            if show:
                visible.append(record.pk)
        response = self.client.get(f'/horses/{profile.pk}/')
        self.assertEqual(response.status_code, 200)
        page = response.context['race_records_page']
        self.assertEqual(page.paginator.count, 4)
        self.assertEqual({r.pk for r in page.object_list}, set(visible))
        self.assertEqual({r.pk for r in response.context['major_wins']}, set(visible))
        self.assertEqual(profile.race_records.count(), 10)

    def test_detail_hides_division_parent_and_children(self):
        hidden = self.event('ireland')
        child = self.event('japan')
        m.RaceEvent.objects.filter(pk=child.pk).update(division_parent=hidden)  # 旧导入异常关联
        response = self.client.get(child.public_path)
        self.assertNotContains(response, hidden.public_path)
        allowed = self.event('france')
        hidden_child = self.event('germany')
        m.RaceEvent.objects.filter(pk=hidden_child.pk).update(division_parent=allowed)
        response = self.client.get(allowed.public_path)
        self.assertNotContains(response, hidden_child.public_path)

    def test_hidden_series_result_does_not_suppress_allowed_fallback(self):
        series = m.RaceSeries.objects.create(key='scope-series', canonical_name_original='Series', country_region='japan', review_status='approved')
        current = self.event('japan', race_series=series)
        hidden = self.event('ireland', race_series=series, year=2020, local_date=date(2020, 5, 1))
        m.RaceEventResult.objects.create(event=hidden, horse_name='Hidden winner', finish_position=1, is_confirmed=True)
        fallback = m.RaceEventHistoryWinner.objects.create(event=current, winner_year=2020, horse_name='Visible fallback')
        self.assertEqual(views._series_history_winners(current), [fallback])
        self.assertNotContains(self.client.get(current.public_path), hidden.public_path)

    def test_hidden_canonical_recommendation_and_draft_allowed_detail(self):
        from django.contrib.auth import get_user_model
        actor = get_user_model().objects.create_user(username="scope-reviewer")
        allowed, hidden = self.event('japan'), self.event('ireland')
        m.RaceEventProductCanonicalLink.objects.create(
            duplicate_event=allowed, canonical_event=hidden, is_active=True,
            identity_sha256='1' * 64, manifest_sha256='2' * 64,
            approved_by=actor, approved_at=timezone.now())
        response = self.client.get(allowed.public_path)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, hidden.public_path)
        self.assertIsNone(response.context['canonical_product_event'])
        draft = self.event('japan', visibility_status='draft')
        self.assertEqual(self.client.get(draft.public_path).status_code, 404)

    def test_career_hidden_rows_cannot_consume_first_page(self):
        profile = self.make_profile()
        for i in range(55):
            m.HorseRaceRecord.objects.create(horse_profile=profile, race_name=f'Hidden {i}',
                race_region='ireland', race_date=date(2025, 1, 1))
        visible = m.HorseRaceRecord.objects.create(horse_profile=profile, race_name='Visible older race',
            race_region='japan', race_date=date(2020, 1, 1))
        response = self.client.get(f'/horses/{profile.pk}/')
        page = response.context['race_records_page']
        self.assertEqual(page.paginator.count, 1)
        self.assertEqual(list(page.object_list), [visible])
