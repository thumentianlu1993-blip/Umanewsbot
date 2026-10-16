"""C175：C174获审的新闻→赛事返回链测试候选；尚未执行，不能标实际RED。

仅正常固定Git树、Linux network-none Django CI承载；不继承旧整类、改codec或启动服务。
"""
from datetime import datetime, timedelta
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from django.test import TestCase, override_settings

from stable.models import (
    ArticleHorseLink, ArticleHorseLinkStatus, ArticleRaceLink, ArticleRaceLinkStatus,
    HomepageHeadlineSelection, HorseProfile, HorseProfileStatus, NewsArticle,
    RaceEvent, RaceEventStatus, RaceEventVisibility, RaceNewsExposure,
    RaceNewsExposureChannel, RaceNewsExposureStatus, RacingRegion, SourceLanguage,
    SourceMode, SourceSite, TermEntry, TermType, WorkflowStatus,
)
from stable.views import (
    PUBLIC_FEED_PAGE_SIZE, PUBLIC_NAV_REQUEST_LINE_LIMIT, PUBLIC_NAV_TTL,
    _public_nav_token, _public_read_nav,
)


@override_settings(RACE_NEWS_EXPOSURE_ENABLED=True)
class ArticleRaceReturnNavigationTests(TestCase):
    """每条主链由真实page2 HTML取文章href；两个同路径入口分别定位。"""

    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 10, 16, 12, tzinfo=ZoneInfo('Asia/Shanghai'))
        clock = patch('django.utils.timezone.now', return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.articles = []
        for rank in range(PUBLIC_FEED_PAGE_SIZE + 1):
            title = f'【合成导航】第{rank + 1}篇'
            when = self.now - timedelta(minutes=rank + 1)
            self.articles.append(NewsArticle.objects.create(
                source_site=SourceSite.NETKEIBA, source_mode=SourceMode.LATEST,
                source_language=SourceLanguage.JAPANESE, racing_region=RacingRegion.JAPAN,
                source_article_id=f'c175-synthetic-{rank}', title_ja=title,
                title_zh=title, translated_title_zh=title, body_ja_raw='Synthetic only',
                body_ja_normalized='Synthetic only', body_zh=title+'正文',
                translated_body_zh=title+'正文', summary_zh=title+'摘要',
                translated_summary_zh=title+'摘要', workflow_status=WorkflowStatus.PUBLISHED,
                published_at=when, published_to_web_at=when, score_total=0,
                source_url=f'https://example.invalid/c175/{rank}', tags_json=['合成导航'],
            ))
        self.article = self.articles[-1]
        self.headline = self.articles[0]
        HomepageHeadlineSelection.objects.update_or_create(
            slot=HomepageHeadlineSelection.SLOT_HOMEPAGE_PRIMARY,
            defaults={'article': self.headline},
        )
        self.event = self._make_event('c175-target')
        self.link = ArticleRaceLink.objects.create(
            event=self.event, article=self.article, status=ArticleRaceLinkStatus.MANUAL,
        )
        self.exposure = RaceNewsExposure.objects.create(
            event=self.event, article=self.article, channel=RaceNewsExposureChannel.HOMEPAGE,
            scope_key='site', slot=1, status=RaceNewsExposureStatus.ACTIVE,
        )
        term = TermEntry.objects.create(
            term_type=TermType.HORSE, source_language=SourceLanguage.JAPANESE,
            source_ja='C175 Synthetic Horse', target_zh='【合成导航】马匹',
            racing_region=RacingRegion.JAPAN, is_active=True,
        )
        self.horse = HorseProfile.objects.create(
            primary_term=term, display_name_zh=term.target_zh, original_name=term.source_ja,
            racing_region=RacingRegion.JAPAN, review_status=HorseProfileStatus.PUBLISHED,
        )
        ArticleHorseLink.objects.create(
            article=self.article, horse_profile=self.horse, status=ArticleHorseLinkStatus.MANUAL,
        )

    def _make_event(self, slug, **changes):
        day = self.now.date() + timedelta(days=1)
        fields = dict(
            year=day.year, slug=slug, original_name='C175 Synthetic Race',
            chinese_name='【合成导航】赛事', country_region=RacingRegion.JAPAN,
            racecourse='合成赛场', timezone_name='Asia/Shanghai', local_date=day,
            local_start_time=None, grade_text='G2', normalized_grade='G2',
            status=RaceEventStatus.SCHEDULED, visibility_status=RaceEventVisibility.PUBLISHED,
        )
        fields.update(changes)
        return RaceEvent.objects.create(**fields)

    def _soup(self, response):
        self.assertEqual(response.status_code, 200, '主控：页面应正常加载，不能将fixture错误作RED')
        return BeautifulSoup(response.content.decode(), 'html.parser')

    def _local_href(self, anchor):
        self.assertIsNotNone(anchor)
        href = anchor['href']  # HTML parser已解码&amp;，不手工拼被测链接。
        parsed = urlsplit(href)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.fragment), ('', '', ''))
        self.assertTrue(parsed.path.startswith('/'))
        return href

    def _article_from_page_two(self):
        listing = self.client.get('/?page=2')
        soup = self._soup(listing)
        self.assertEqual(listing.context['page_obj'].number, 2, '主控：确实在第2页')
        self.assertEqual([x.pk for x in listing.context['page_obj']], [self.article.pk])
        self.assertEqual([x.pk for x in listing.context['feed_articles']], [self.article.pk])
        self.assertEqual(listing.context['headline_article'].pk, self.headline.pk)
        anchors = [a for a in soup.select('section.feed[aria-label="最新新闻"] .feed-card-title a')
                   if urlsplit(a.get('href', '')).path == self.article.public_path
                   and a.get_text(strip=True) == self.article.effective_title]
        self.assertEqual(len(anchors), 1, '主控：只定位最新新闻区的目标文章，不借头条/热榜')
        article_href = self._local_href(anchors[0])
        query = parse_qs(urlsplit(article_href).query)
        self.assertEqual(set(query), {'return_nav'})
        self.assertEqual(len(query['return_nav']), 1)
        token = query['return_nav'][0]
        self.assertEqual(_public_read_nav(token, {'news'}), ('news', {'page': '2'}))
        detail = self.client.get(article_href)
        self._soup(detail)
        self.assertEqual(detail.context['article'].pk, self.article.pk)
        self.assertEqual(detail.context['public_nav_token'], token)
        return detail, token

    def _entry(self, detail, role, event=None):
        selector = {'chip': '.mention-ribbon .entity-chip.race', 'teaser': 'a.race-teaser'}[role]
        target = event or self.event
        anchors = [a for a in self._soup(detail).select(selector)
                   if urlsplit(a.get('href', '')).path == target.public_path]
        self.assertEqual(len(anchors), 1, f'主控：{role}独立存在且指向目标实体')
        return self._local_href(anchors[0])

    def _back_href(self, response):
        anchors = self._soup(response).select('nav.article-actions a')
        self.assertGreaterEqual(len(anchors), 1)
        return self._local_href(anchors[0])

    def _assert_round_trip(self, role):
        detail, token = self._article_from_page_two()
        entry = self._entry(detail, role)
        # 真实RED应出于此处缺失来源，不得是上面的正常加载/目标可见前件失败。
        self.assertEqual(parse_qs(urlsplit(entry).query), {'return_nav': [token]},
                         f'{role}应保留从真实第2页文章href得到的news令牌')
        race = self.client.get(entry)
        self._soup(race)
        self.assertEqual(race.context['event'].pk, self.event.pk)
        back = self._back_href(race)
        self.assertEqual(urlsplit(back).path, '/')
        self.assertEqual(parse_qs(urlsplit(back).query), {'return_nav': [token]})
        self.assertEqual(_public_read_nav(token, {'news'}), ('news', {'page': '2'}))
        returned = self.client.get(back)
        soup = self._soup(returned)
        self.assertEqual(returned.context['page_obj'].number, 2)
        self.assertEqual([x.pk for x in returned.context['feed_articles']], [self.article.pk])
        targets = [a for a in soup.select('section.feed[aria-label="最新新闻"] .feed-card-title a')
                   if urlsplit(a.get('href', '')).path == self.article.public_path]
        self.assertEqual(len(targets), 1)
        # 列表会重新signing.dumps；新签名时间可变，只比较验证后的新闻分页语义。
        renewed = parse_qs(urlsplit(self._local_href(targets[0])).query)
        self.assertEqual(set(renewed), {'return_nav'})
        self.assertEqual(len(renewed['return_nav']), 1)
        self.assertEqual(_public_read_nav(renewed['return_nav'][0], {'news'}),
                         ('news', {'page': '2'}))

    def test_fixture_control_page_two_article_and_both_event_entries_are_visible(self):
        detail, _token = self._article_from_page_two()
        for role in ('chip', 'teaser'):
            self.assertEqual(urlsplit(self._entry(detail, role)).path, self.event.public_path)
        race = self.client.get(self.event.public_path)
        self._soup(race)
        self.assertEqual(race.context['event'].pk, self.event.pk)
        self.assertEqual(urlsplit(self._back_href(race)).path, '/races/')

    def test_news_page2_article_race_chip_returns_same_page(self):
        for exposure_enabled in (True, False):
            with self.subTest(exposure_enabled=exposure_enabled), self.settings(
                    RACE_NEWS_EXPOSURE_ENABLED=exposure_enabled):
                self._assert_round_trip('chip')

    def test_news_page2_article_race_teaser_returns_same_page(self):
        for exposure_enabled in (True, False):
            with self.subTest(exposure_enabled=exposure_enabled), self.settings(
                    RACE_NEWS_EXPOSURE_ENABLED=exposure_enabled):
                self._assert_round_trip('teaser')

    def test_invalid_news_navigation_uses_existing_bare_public_path(self):
        _detail, token = self._article_from_page_two()
        with patch('django.core.signing.time.time', return_value=time.time()-PUBLIC_NAV_TTL-2):
            expired = _public_nav_token('news', {'page': '2'})
        other_kind = _public_nav_token('horses', {'q': '合成'})
        tampered = token[:-1] + ('A' if token[-1] != 'A' else 'B')
        cases = [
            ('absent', []), ('empty', [('return_nav', '')]),
            ('tampered', [('return_nav', tampered)]), ('expired', [('return_nav', expired)]),
            ('duplicate', [('return_nav', token), ('return_nav', token)]),
            ('cross-kind', [('return_nav', other_kind)]),
            ('input-budget', [('return_nav', 'x'*(PUBLIC_NAV_REQUEST_LINE_LIMIT+1))]),
        ]
        for label, query in cases:
            with self.subTest(case=label):
                href = self.article.public_path + ('?'+urlencode(query) if query else '')
                response = self.client.get(href)
                self._soup(response)
                self.assertEqual(response.context['public_nav_token'], '')
                for role in ('chip', 'teaser'):
                    self.assertEqual(self._entry(response, role), self.event.public_path)

    def test_candidate_removed_or_hidden_targets_add_no_public_entry(self):
        for status in (ArticleRaceLinkStatus.CANDIDATE, ArticleRaceLinkStatus.REMOVED):
            with self.subTest(status=status):
                self.link.status = status
                self.link.save(update_fields=['status'])
                detail, _token = self._article_from_page_two()
                self.assertEqual(self._soup(detail).select('.entity-chip.race, a.race-teaser'), [])
        self.link.status = ArticleRaceLinkStatus.MANUAL
        self.link.save(update_fields=['status'])
        self.event.visibility_status = RaceEventVisibility.HIDDEN
        self.event.save(update_fields=['visibility_status'])
        detail, _token = self._article_from_page_two()
        self.assertEqual(self._soup(detail).select('.entity-chip.race, a.race-teaser'), [])
        self.assertEqual(self.client.get(self.event.public_path).status_code, 404)

    def test_same_name_distinct_editions_keep_identity_and_rename_keeps_path(self):
        previous_day = self.event.local_date.replace(year=self.event.year-1)
        prior = self._make_event('c175-prior', year=previous_day.year, local_date=previous_day)
        ArticleRaceLink.objects.create(
            event=prior, article=self.article, status=ArticleRaceLinkStatus.MANUAL,
        )
        detail, _token = self._article_from_page_two()
        self.assertEqual(len(self._soup(detail).select('.entity-chip.race')), 2)
        for event in (self.event, prior):
            self.assertEqual(urlsplit(self._entry(detail, 'chip', event)).path, event.public_path)
            chip = [a for a in self._soup(detail).select('.entity-chip.race')
                    if urlsplit(a['href']).path == event.public_path][0]
            self.assertIn(str(event.year), chip.get_text())
        before = self.event.public_path
        self.event.chinese_name = '【合成导航】更名赛事'
        self.event.save(update_fields=['chinese_name'])
        self.assertEqual(self.event.public_path, before)
        changed, _token = self._article_from_page_two()
        self.assertEqual(urlsplit(self._entry(changed, 'chip')).path, before)
        self.assertIn(self.event.chinese_name, self._soup(changed).get_text())

    def test_horse_entry_retains_bare_path_and_horses_only_return_contract(self):
        detail, token = self._article_from_page_two()
        anchors = self._soup(detail).select('.mention-ribbon .entity-chip:not(.race)')
        self.assertEqual(len(anchors), 1)
        self.assertEqual(self._local_href(anchors[0]), self.horse.public_path)
        response = self.client.get(self.horse.public_path, {'return_nav': token})
        self._soup(response)
        self.assertEqual(response.context['profile'].pk, self.horse.pk)
        self.assertEqual(response.context['public_nav_token'], '')
        self.assertEqual(urlsplit(self._back_href(response)).path, '/horses/')

    def test_news_page_and_legal_slug_stay_within_existing_request_line_budget(self):
        max_slug = 'a'*RaceEvent._meta.get_field('slug').max_length
        long_event = self._make_event(max_slug)
        self.link.event = long_event
        self.link.save(update_fields=['event'])
        self.exposure.event = long_event
        self.exposure.save(update_fields=['event'])
        self.event = long_event
        detail, actual_token = self._article_from_page_two()
        # 主链仍取实际page2；10位page只测合法codec/预算，不伪称有十亿页。
        largest_page_token = _public_nav_token('news', {'page': '9999999999'})
        self.assertEqual(_public_read_nav(largest_page_token, {'news'}),
                         ('news', {'page': '9999999999'}))
        for token in (actual_token, largest_page_token):
            with self.subTest(token_source='actual' if token == actual_token else 'max-page'):
                response = self.client.get(self.article.public_path, {'return_nav': token})
                self._soup(response)
                self.assertEqual(response.context['public_nav_token'], token)
                self.assertLessEqual(len(token.encode('ascii')), PUBLIC_NAV_REQUEST_LINE_LIMIT)
                # 输入、返回首页、目标赛事三个长度分开；不造超schema slug或改预算。
                paths = [response.context['public_return_url']]
                for role in ('chip', 'teaser'):
                    entry = self._entry(response, role)
                    self.assertEqual(urlsplit(entry).path, self.event.public_path)
                    paths.append(entry)
                    race = self.client.get(entry)
                    self._soup(race)
                    self.assertEqual(race.context['event'].pk, self.event.pk)
                    paths.append(self._back_href(race))
                for href in paths:
                    self.assertTrue(href)
                    self.assertLessEqual(len(('GET '+href+' HTTP/1.1\r\n').encode('ascii')),
                                         PUBLIC_NAV_REQUEST_LINE_LIMIT)
