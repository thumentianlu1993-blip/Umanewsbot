"""D055：公开赛果发布时间的独立真实 Client 合同源码，尚未执行。

故障模型：缺失时间、使用 read_now/观察/保存时间、依赖默认时区、
隐藏修订泄漏发布时间。仅 mock 时钟；公开许可、ORM、路由、模板都真实。
原 probe v7 全 envelope 原件不变；本模块不证明其新时间值兼容性。
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser
import re
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from stable import models as stable_models
from stable.services import race_events
from stable.services.horse_profiles import FOLLOW_COOKIE_NAME


class _Node:
    def __init__(self, tag, attrs=(), parent=None):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.parts = []

    def text(self):
        return "".join(part if isinstance(part, str) else part.text() for part in self.parts)

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()

    def inside(self, ancestor):
        parent = self.parent
        while parent is not None:
            if parent is ancestor:
                return True
            parent = parent.parent
        return False

class _Document(HTMLParser):
    """仅解析实际响应，保留段落与 form 的真实祖先关系。"""

    VOID_TAGS = frozenset(
        "area base br col embed hr img input link meta param source track wbr".split()
    )

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]
        self.nodes = []
        self.feed(html)
        self.close()

    def _start(self, tag, attrs):
        node = _Node(tag, attrs, self.stack[-1])
        self.stack[-1].parts.append(node)
        self.nodes.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._start(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].parts.append(data)

@override_settings(ALLOWED_HOSTS=["testserver"], TIME_ZONE="America/New_York", USE_TZ=True)
class U04ResultPublicationTimeTests(TestCase):
    # 手工换算：20 日 20:15 UTC = 21 日 04:15 北京；与所有其它时钟不同。
    PUBLISHED_AT = datetime(2026, 7, 20, 20, 15, tzinfo=dt_timezone.utc)
    READ_NOW = datetime(2026, 7, 21, 9, 40, tzinfo=dt_timezone.utc)
    OBSERVED_AT = datetime(2026, 7, 20, 19, 5, tzinfo=dt_timezone.utc)
    RACE_AT = datetime(2026, 7, 19, 12, 30, tzinfo=dt_timezone.utc)
    UPDATED_AT = datetime(2026, 7, 21, 7, 22, tzinfo=dt_timezone.utc)
    EXPECTED_TEXT = "赛果发布于2026-07-21 04:15（北京时间）"
    SNAPSHOT_MODELS = (
        stable_models.RaceEvent, stable_models.RaceEventResult,
        stable_models.RaceEventRevision, stable_models.RaceEventRevisionPublication,
        stable_models.RaceResultObservation, stable_models.RaceResultSourceIdentity,
        stable_models.RaceEventProjectionControl, stable_models.RaceEventLiveTracking,
        stable_models.RaceLivePublicationPolicy,
        stable_models.RaceLiveEventPublicationAllowlist,
        stable_models.RaceLiveOfficialPublicationAuthorization,
        stable_models.RaceLiveOfficialMarkerContract,
        stable_models.RaceLiveOfficialMarkerEvidence, stable_models.HorseFollow,
    )

    def _event_with_revision(self, slug, phase, *, published=True, stale=False):
        event = stable_models.RaceEvent.objects.create(
            year=2026,
            slug=slug,
            original_name=slug,
            chinese_name=slug,
            country_region=stable_models.RacingRegion.UNITED_KINGDOM,
            racecourse="Ascot",
            grade_text="G1",
            surface=stable_models.RaceEventSurface.TURF,
            status=stable_models.RaceEventStatus.FINISHED,
            visibility_status=stable_models.RaceEventVisibility.PUBLISHED,
        )
        source = stable_models.RaceResultSourceIdentity.objects.create(
            event=event,
            source_key=f"read_fixture_{slug}",
            external_race_id=f"read-race-{slug}",
            review_status=stable_models.RaceLiveReviewStatus.APPROVED,
            result_authority=(
                stable_models.RaceResultSourceAuthority.OFFICIAL
                if phase != "provisional"
                else stable_models.RaceResultSourceAuthority.SUPPLEMENTAL
            ),
            terms_status=(
                stable_models.RaceSourceTermsStatus.MANUAL
                if phase != "provisional"
                else stable_models.RaceSourceTermsStatus.APPROVED
            ),
            automation_allowed=phase == "provisional",
            valid_until=self.READ_NOW + timedelta(days=30),
            evidence_sha256="d" * 64 if phase != "provisional" else "f" * 64,
            registry_digest="e" * 64 if phase != "provisional" else "a" * 64,
        )
        payload = {
            "external_race_id": source.external_race_id,
            "participants": [
                {
                    "external_runner_id": "read-runner-1",
                    "official_finish_position": 1,
                    "status": "finished",
                }
            ],
        }
        observation = stable_models.RaceResultObservation.objects.create(
            source_identity=source,
            observed_at=self.OBSERVED_AT,
            parser_version="read-fixture-v1",
            raw_sha256=slug[0] * 64,
            normalized_sha256=race_events.build_race_live_canonical_sha256(
                normalized_payload=payload,
            ),
            result_phase=phase,
            normalized_payload=payload,
        )
        if phase != "provisional":
            marker_contract = (
                stable_models.RaceLiveOfficialMarkerContract.objects.create(
                    country_region=event.country_region,
                    source_key=source.source_key,
                    parser_version="read-fixture-v1",
                    allowed_marker_types=["official_result"],
                    contract_digest="c" * 64,
                    valid_until=self.READ_NOW + timedelta(days=30),
                    review_status=stable_models.RaceLiveReviewStatus.APPROVED,
                )
            )
            stable_models.RaceLiveOfficialMarkerEvidence.objects.create(
                observation=observation,
                contract=marker_contract,
                marker_type="official_result",
                contract_digest="c" * 64,
                parser_version="read-fixture-v1",
                raw_sha256=observation.raw_sha256,
                source_timestamp=self.OBSERVED_AT,
            )
        revision = stable_models.RaceEventRevision.objects.create(
            event=event,
            kind=stable_models.RaceEventRevisionKind.RESULT,
            revision_no=1,
            phase=phase,
            content_sha256=observation.normalized_sha256,
            source_authority=source.result_authority,
            primary_observation=observation,
            published_at=self.PUBLISHED_AT if published else None,
            conflict_status=stable_models.RaceEventRevisionConflictStatus.NONE,
        )
        stable_models.RaceEventProjectionControl.objects.create(
            event=event,
            current_result_revision=revision,
            last_known_good_result_revision=revision,
            next_result_revision_no=2,
        )
        state = {
            "provisional": stable_models.RaceEventLiveState.PROVISIONAL_RESULT,
            "official": stable_models.RaceEventLiveState.OFFICIAL_RESULT,
            "corrected": stable_models.RaceEventLiveState.CORRECTED_RESULT,
        }[phase]
        stable_models.RaceEventLiveTracking.objects.create(
            event=event,
            state=state,
            stale_at=self.READ_NOW - timedelta(minutes=1) if stale else None,
        )
        if published:
            required_mode = (
                stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                if phase == "provisional"
                else stable_models.RaceLivePublicationMode.OFFICIAL_PUBLIC
            )
            global_policy, _ = stable_models.RaceLivePublicationPolicy.objects.get_or_create(
                scope_type=stable_models.RaceLivePublicationScopeType.GLOBAL,
                scope_key="global",
                defaults={
                    "mode": stable_models.RaceLivePublicationMode.OFFICIAL_PUBLIC,
                    "registry_digest": "a" * 64,
                    "coverage_proof_digest": "b" * 64,
                    "valid_until": self.READ_NOW + timedelta(days=30),
                },
            )
            region_policy, _ = stable_models.RaceLivePublicationPolicy.objects.get_or_create(
                scope_type=stable_models.RaceLivePublicationScopeType.REGION,
                scope_key=event.country_region,
                defaults={
                    "mode": stable_models.RaceLivePublicationMode.OFFICIAL_PUBLIC,
                    "registry_digest": "a" * 64,
                    "coverage_proof_digest": "b" * 64,
                    "valid_until": self.READ_NOW + timedelta(days=30),
                },
            )
            policy_source = source
            if phase != "provisional":
                policy_source = (
                    stable_models.RaceResultSourceIdentity.objects.create(
                        event=event,
                        source_key="the_racing_api",
                        external_race_id=f"tra-{slug}",
                        review_status=(
                            stable_models.RaceLiveReviewStatus.APPROVED
                        ),
                        result_authority=(
                            stable_models.RaceResultSourceAuthority.SUPPLEMENTAL
                        ),
                        terms_status=(
                            stable_models.RaceSourceTermsStatus.APPROVED
                        ),
                        automation_allowed=True,
                        valid_until=self.READ_NOW + timedelta(days=30),
                        evidence_sha256="f" * 64,
                        registry_digest="a" * 64,
                    )
                )
            source_policy, _ = stable_models.RaceLivePublicationPolicy.objects.get_or_create(
                scope_type=stable_models.RaceLivePublicationScopeType.SOURCE,
                scope_key=policy_source.source_key,
                defaults={
                    "mode": (
                        required_mode
                        if phase == "provisional"
                        else stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                    ),
                    "registry_digest": "a" * 64,
                    "coverage_proof_digest": "b" * 64,
                    "valid_until": self.READ_NOW + timedelta(days=30),
                },
            )
            event_policy = stable_models.RaceLivePublicationPolicy.objects.create(
                scope_type=stable_models.RaceLivePublicationScopeType.EVENT,
                scope_key=str(event.pk),
                mode=required_mode,
                registry_digest="a" * 64,
                coverage_proof_digest="b" * 64,
                valid_until=self.READ_NOW + timedelta(days=30),
            )
            allowlist = stable_models.RaceLiveEventPublicationAllowlist.objects.create(
                event=event,
                source_key=policy_source.source_key,
                max_mode=(
                    required_mode
                    if phase == "provisional"
                    else stable_models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
                ),
                coverage_proof_digest="b" * 64,
                official_verification_route="read_fixture_verification",
                official_verification_route_version="read-v1",
                official_verification_contract_digest="c" * 64,
                official_terms_evidence_digest="d" * 64,
                official_verification_valid_until=self.READ_NOW + timedelta(days=30),
                enabled=True,
            )
            if phase != "provisional":
                stable_models.RaceLiveOfficialPublicationAuthorization.objects.create(
                    event=event,
                    source_key=source.source_key,
                    route="read_fixture_verification",
                    route_version="read-v1",
                    route_registry_digest="e" * 64,
                    contract_digest="c" * 64,
                    terms_evidence_digest="d" * 64,
                    coverage_proof_digest="b" * 64,
                    max_phase=(
                        stable_models.RaceResultPhase.CORRECTED
                        if phase == "corrected"
                        else stable_models.RaceResultPhase.OFFICIAL
                    ),
                    enabled=True,
                    valid_until=self.READ_NOW + timedelta(days=30),
                )
            stable_models.RaceEventRevisionPublication.objects.create(
                revision=revision,
                published_at=self.PUBLISHED_AT,
                reason="test_fixture",
                policy_versions=[
                    [policy.scope_type, policy.scope_key, policy.version]
                    for policy in (
                        global_policy,
                        region_policy,
                        source_policy,
                        event_policy,
                    )
                ],
                allowlist_version=allowlist.version,
                registry_digest=(
                    "a" * 64 if phase == "provisional" else "e" * 64
                ),
                coverage_proof_digest="b" * 64,
                authorization_kind=(
                    "provisional_policy"
                    if phase == "provisional"
                    else "official_route"
                ),
                official_authorization_version=(
                    0 if phase == "provisional" else 1
                ),
            )
        stable_models.RaceEventResult.objects.create(
            event=event,
            finish_position=1,
            official_finish_position=1,
            horse_name="Fixture Winner",
            is_confirmed=phase != "provisional",
        )
        # 即使 shadow 也真实存在物化行，GET 必须通过公开许可隐藏它。
        stable_models.RaceEvent.objects.filter(pk=event.pk).update(
            race_datetime=self.RACE_AT, updated_at=self.UPDATED_AT,
        )
        event.refresh_from_db()
        return event

    def _snapshot(self):
        # 只证明列明的 14 张合成业务表完整字段/行集合；不是全库审计。
        return {
            model._meta.label: list(model.objects.using("default").order_by("pk").values())
            for model in self.SNAPSHOT_MODELS
        }

    def _get(self, event, *, active_timezone="Pacific/Honolulu"):
        path = reverse("public-race-detail", args=[event.year, event.slug])
        self.assertEqual(path, event.public_path, "前件：canonical 路由与公开 path 相同")
        before = self._snapshot()
        cookie = self.client.cookies.get(FOLLOW_COOKIE_NAME)
        cookie_before = cookie.value if cookie is not None else None
        writes = []

        def capture(execute, sql, params, many, context):
            # 仅 default 连接直接 SQL 命令；不捕获其它连接/触发器/外部副作用。
            verb = re.match(r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|TRUNCATE)\b", sql, re.I)
            if verb:
                writes.append(verb.group(1).upper())
            return execute(sql, params, many, context)

        with patch("stable.views.timezone.now", return_value=self.READ_NOW):
            with timezone.override(active_timezone), connection.execute_wrapper(capture):
                response = self.client.get(path)
        self.assertEqual(response.status_code, 200, "前件：真实 GET 200，不能把重定向当 RED")
        self.assertEqual(response.resolver_match.url_name, "public-race-detail")
        self.assertTemplateUsed(response, "stable/public/race_detail.html")
        self.assertEqual(response.context["event"].pk, event.pk)
        self.assertEqual(self._snapshot(), before, "GET 改变了列明业务表的字段或行集合")
        self.assertEqual(writes, [], "GET 含 default 连接直接写 SQL")
        self.assertNotIn(FOLLOW_COOKIE_NAME, response.cookies)
        cookie = self.client.cookies.get(FOLLOW_COOKIE_NAME)
        self.assertEqual(cookie.value if cookie is not None else None, cookie_before)
        document = _Document(response.content.decode(response.charset))
        heroes = [n for n in document.nodes if n.tag == "section" and n.has_class("race-hero")]
        self.assertEqual(len(heroes), 1)
        return response, document, heroes[0]

    def _visible_result(self, event, phase, *, stale=False, active_timezone="Pacific/Honolulu"):
        # 不 mock visible：先真实运行与视图同一时刻的许可判定。
        decision = race_events.resolve_race_live_public_read(event_id=event.pk, now=self.READ_NOW)
        self.assertIs(decision.visible, True, "前件：真实授权必须准许，不能用权限错误伪 RED")
        self.assertEqual(decision.phase, phase)
        response, document, hero = self._get(event, active_timezone=active_timezone)
        status = response.context["live_result_status"]
        self.assertIsNotNone(status)
        self.assertEqual(status["phase"], phase)
        self.assertEqual(status["published_at"], self.PUBLISHED_AT)
        self.assertTrue(timezone.is_aware(status["published_at"]))
        self.assertNotEqual(status["published_at"], self.READ_NOW)
        self.assertNotIn(status["published_at"], (self.OBSERVED_AT, event.updated_at, event.race_datetime))
        self.assertIs(status["is_stale"], stale)
        rows = list(response.context["results"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].horse_name, "Fixture Winner")
        self.assertContains(response, "<h2>赛果</h2>", html=True)
        self.assertContains(response, 'href="#results"')
        self.assertContains(response, "Fixture Winner")
        for forbidden in ("暂定赛果", "正式赛果", "赛果已更正", "赛果待复核", "补充来源", "官方来源"):
            self.assertNotContains(response, forbidden)
        if phase == "provisional":
            self.assertNotContains(response, "WINNER · 冠军")
            self.assertContains(response, "赛果待确认")
        else:
            self.assertContains(response, "WINNER · 冠军")
        warnings = [n for n in document.nodes if n.tag == "aside" and n.has_class("race-result-status")]
        self.assertEqual(len(warnings), int(stale))
        if stale:
            self.assertEqual(warnings[0].text(), "数据可能已过期")
            self.assertEqual(warnings[0].attrs.get("role"), "status")
            self.assertTrue(warnings[0].inside(hero))
        return response, document, hero

    def _assert_publication(self, response, document, hero):
        paragraphs = [n for n in document.nodes if n.tag == "p" and n.inside(hero)
                      and "赛果发布于" in n.text()]
        # 固定 689dad27 此处预期缺文案 RED；所有真实 GET 前件及副作用保护在前。
        self.assertEqual(len(paragraphs), 1, "U04：hero 应恰好展示一条公开修订发布时间")
        self.assertEqual(paragraphs[0].text(), self.EXPECTED_TEXT)
        self.assertEqual(response.content.decode(response.charset).count(self.EXPECTED_TEXT), 1)
        self.assertEqual(hero.text().count("赛果发布于"), 1)
        self.assertEqual(response.content.decode(response.charset).count("赛果发布于"), 1)
        self.assertFalse(any(n.tag == "a" and (n.inside(paragraphs[0]) or paragraphs[0].inside(n))
                             for n in document.nodes))
        # 独立字面值排除 read_now / observed_at / updated_at / race_datetime 回填。
        for wrong in ("2026-07-21 17:40", "2026-07-21 03:05", "2026-07-21 15:22", "2026-07-19 20:30"):
            self.assertNotIn(wrong, paragraphs[0].text())

    def _assert_hidden_time(self, response, document, hero):
        self.assertIsNone(response.context["live_result_status"])
        html = response.content.decode(response.charset)
        for forbidden in ("赛果发布于", self.EXPECTED_TEXT, "2026-07-20T20:15", "2026-07-20 20:15", "2026-07-21 04:15"):
            self.assertNotIn(forbidden, html)
        self.assertNotIn("赛果发布于", hero.text())

    def test_provisional_publication_time_uses_authorized_revision(self):
        event = self._event_with_revision("a1a1a1a1", "provisional")
        self._assert_publication(*self._visible_result(event, "provisional"))

    def test_official_publication_time_uses_authorized_revision(self):
        event = self._event_with_revision("b2b2b2b2", "official")
        self._assert_publication(*self._visible_result(event, "official"))

    def test_corrected_publication_time_uses_authorized_revision(self):
        event = self._event_with_revision("c3c3c3c3", "corrected")
        self._assert_publication(*self._visible_result(event, "corrected"))

    def test_beijing_rollover_ignores_active_and_default_timezones(self):
        event = self._event_with_revision("d4d4d4d4", "official")
        for active in ("Pacific/Honolulu", "Europe/London"):
            with self.subTest(active_timezone=active):
                self._assert_publication(*self._visible_result(event, "official", active_timezone=active))

    def test_stale_preserves_publication_instant_and_original_warning(self):
        event = self._event_with_revision("e5e5e5e5", "official", stale=True)
        self._assert_publication(*self._visible_result(event, "official", stale=True))

    def test_unpublished_shadow_with_real_materialized_row_leaks_no_time(self):
        event = self._event_with_revision("f6f6f6f6", "provisional", published=False)
        revision = stable_models.RaceEventRevision.objects.get(event=event)
        self.assertIsNone(revision.published_at)
        self.assertTrue(stable_models.RaceEventResult.objects.filter(event=event).exists())
        self.assertFalse(race_events.resolve_race_live_public_read(event_id=event.pk, now=self.READ_NOW).visible)
        result = self._get(event)
        self.assertEqual(list(result[0].context["results"]), [])
        self.assertNotContains(result[0], "Fixture Winner")
        self._assert_hidden_time(*result)

    def test_explicit_policy_off_hides_actual_published_revision_and_time(self):
        event = self._event_with_revision("a7a7a7a7", "official")
        self._visible_result(event, "official")
        revision = stable_models.RaceEventRevision.objects.get(event=event)
        self.assertEqual(revision.published_at, self.PUBLISHED_AT)
        policy = stable_models.RaceLivePublicationPolicy.objects.get(
            scope_type=stable_models.RaceLivePublicationScopeType.GLOBAL, scope_key="global",
        )
        policy.mode = stable_models.RaceLivePublicationMode.OFF
        policy.version += 1
        policy.save(update_fields=("mode", "version", "updated_at"))
        self.assertFalse(race_events.resolve_race_live_public_read(event_id=event.pk, now=self.READ_NOW).visible)
        result = self._get(event)
        self.assertEqual(list(result[0].context["results"]), [])
        self.assertNotContains(result[0], "Fixture Winner")
        self._assert_hidden_time(*result)

    def test_historical_results_without_revision_invent_no_publication_time(self):
        event = stable_models.RaceEvent.objects.create(
            year=2026, slug="b8b8b8b8", chinese_name="D055历史公开结果",
            original_name="D055 Historical", country_region=stable_models.RacingRegion.UNITED_KINGDOM,
            status=stable_models.RaceEventStatus.FINISHED,
            visibility_status=stable_models.RaceEventVisibility.PUBLISHED,
            race_datetime=self.RACE_AT,
        )
        stable_models.RaceEvent.objects.filter(pk=event.pk).update(updated_at=self.UPDATED_AT)
        event.refresh_from_db()
        row = stable_models.RaceEventResult.objects.create(
            event=event, finish_position=1, official_finish_position=1,
            horse_name="D055 Historical Winner", is_confirmed=True,
        )
        self.assertFalse(stable_models.RaceEventRevision.objects.filter(event=event).exists())
        result = self._get(event)
        self.assertEqual([r.pk for r in result[0].context["results"]], [row.pk])
        self.assertContains(result[0], "D055 Historical Winner")
        self.assertContains(result[0], "WINNER · 冠军")
        self.assertContains(result[0], 'href="#results"')
        self._assert_hidden_time(*result)
