from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import stat
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from billiard.exceptions import SoftTimeLimitExceeded
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from stable.services import p0_racecard_url_discovery as discovery


REPO_ROOT = Path(__file__).resolve().parents[2]


class P0RacecardUrlDiscoveryModuleContractTests(SimpleTestCase):
    def test_discovery_service_module_exists(self):
        self.assertIsNotNone(
            importlib.util.find_spec(
                "stable.services.p0_racecard_url_discovery"
            ),
            "P0 official racecard URL discovery service is not implemented",
        )


class P0RacecardUrlDiscoveryConfigurationTests(SimpleTestCase):
    def test_feature_is_default_off_with_persistent_artifact_root(self):
        self.assertIs(settings.P0_RACECARD_URL_DISCOVERY_ENABLED, False)
        self.assertEqual(
            settings.P0_RACECARD_URL_DISCOVERY_ARTIFACT_ROOT,
            "/app/runtime/upcoming_racecard_urls",
        )

    def test_beat_runs_at_0630_and_1830_asia_shanghai(self):
        self.assertEqual(settings.CELERY_TIMEZONE, "Asia/Shanghai")
        entry = settings.CELERY_BEAT_SCHEDULE["discover-p0-racecard-urls"]
        self.assertEqual(entry["task"], "stable.tasks.discover_p0_racecard_urls_task")
        schedule = entry["schedule"]
        self.assertEqual(schedule.minute, {30})
        self.assertEqual(schedule.hour, {6, 18})

    def test_task_uses_the_worker_default_celery_queue(self):
        self.assertNotIn(
            "stable.tasks.discover_p0_racecard_urls_task",
            settings.CELERY_TASK_ROUTES,
        )
        annotation = settings.CELERY_TASK_ANNOTATIONS[
            "stable.tasks.discover_p0_racecard_urls_task"
        ]
        self.assertGreater(annotation["time_limit"], annotation["soft_time_limit"])
        worker_script = (REPO_ROOT / "deploy/docker/start-worker.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('CELERY_WORKER_QUEUES:-celery', worker_script)

    def test_production_worker_mounts_the_persistent_document_directory(self):
        compose = (REPO_ROOT / "docker-compose.prod.lowcost.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "./runtime/upcoming_racecard_urls:"
            "/app/runtime/upcoming_racecard_urls:rw",
            compose,
        )

    def test_example_environment_keeps_discovery_disabled(self):
        example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("P0_RACECARD_URL_DISCOVERY_ENABLED=false", example)
        self.assertIn(
            "P0_RACECARD_URL_DISCOVERY_ARTIFACT_ROOT="
            "/app/runtime/upcoming_racecard_urls",
            example,
        )
        self.assertIn(
            "P0_RACECARD_URL_DISCOVERY_REGISTRY_SHA256="
            + settings.P0_RACECARD_URL_DISCOVERY_REGISTRY_SHA256,
            example,
        )


def _event(**overrides):
    values = {
        "id": 1,
        "year": 2026,
        "slug": "test-race",
        "series_key": "test-race",
        "original_name": "Test Race",
        "chinese_name": "测试赛",
        "country_region": "japan",
        "racecourse": "Tokyo",
        "race_datetime": datetime(2026, 7, 27, 0, 0, tzinfo=dt_timezone.utc),
        "timezone_name": "Asia/Tokyo",
        "local_date": date(2026, 7, 27),
        "priority": "P0",
        "status": "scheduled",
        "visibility_status": "draft",
        "source_refs": {"jra": {"race_id": "202605010111"}},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _route(**overrides):
    values = {
        "provider": "jra",
        "region": "japan",
        "source_namespace": "jra",
        "track_codes": [],
        "allowed_hosts": ["www.jra.go.jp"],
        "allowed_path_prefixes": ["/JRADB/accessD.html"],
        "automation_allowed": True,
        "access_mode": "automated_official_url_discovery",
        "robots_allowed": True,
        "contract_version": "test-v1",
        "valid_until": "2027-01-01T00:00:00Z",
        "identity_fields": ["race_id"],
        "url_template": "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde100520260501011120260727/{race_id}",
        "identity_marker_template": 'data-race-id="{race_id}"',
        "not_published_marker": "RACECARD_NOT_PUBLISHED",
    }
    values.update(overrides)
    return values


def _head_route(**overrides):
    values = _route(
        provider="equibase",
        region="united_states",
        source_namespace="equibase",
        allowed_hosts=["tvg.equibase.com"],
        allowed_path_prefixes=["/static/entry/"],
        identity_source="event_root_fields",
        identity_fields=["track_code", "local_date_mmddyy"],
        url_template=(
            "https://tvg.equibase.com/static/entry/"
            "RaceCardIndex{track_code}{local_date_mmddyy}USA-EQB.html"
        ),
        request_url_template=(
            "https://tvg.equibase.com/static/entry/"
            "RaceCardIndex{track_code}{local_date_mmddyy}USA-EQB.html"
        ),
        identity_marker_template="",
        not_published_marker="",
        verification_method="head_exact_path",
        verification_scope="track_date_racecard_index",
        robots_evidence_origin="https://tvg.equibase.com",
        robots_evidence_status=404,
        robots_evidence_observed_at="2026-07-27T05:06:02Z",
        robots_evidence_sha256=(
            "dc1d54dab6ec8c00f70137927504e4f222c8395f10760b6beecfcfa94e08249f"
        ),
        max_requests_per_run=2,
        min_interval_seconds=5,
    )
    values.update(overrides)
    digest_payload = {
        key: value for key, value in values.items() if key != "contract_digest"
    }
    values["contract_digest"] = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return values


class P0RacecardWindowTests(SimpleTestCase):
    def test_strict_p0_half_open_window_and_bounded_orphans(self):
        started = datetime(2026, 12, 30, 0, 0, tzinfo=dt_timezone.utc)
        events = [
            _event(id=1, race_datetime=started),
            _event(id=2, race_datetime=started + timedelta(days=7)),
            _event(id=3, priority="P1", race_datetime=started),
            _event(id=4, status="cancelled", race_datetime=started),
            _event(
                id=5,
                year=2027,
                race_datetime=None,
                local_date=None,
                status="postponed",
            ),
            _event(
                id=6,
                year=2025,
                race_datetime=None,
                local_date=None,
            ),
            _event(
                id=7,
                year=2026,
                race_datetime=None,
                local_date=date(2026, 12, 30),
                timezone_name="Europe/London",
            ),
        ]
        inventory = discovery.enumerate_event_snapshots(
            events, run_started_at=started, max_targets=20
        )
        self.assertEqual([row.event_id for row in inventory.future], [1, 7])
        self.assertEqual([row.event_id for row in inventory.orphans], [5])
        self.assertEqual(
            inventory.future[1].inclusion_basis, "local_date_superset"
        )

    def test_unaware_start_and_target_overflow_fail_closed(self):
        with self.assertRaises(discovery.DiscoveryInvariantError):
            discovery.enumerate_event_snapshots(
                [_event()], run_started_at=datetime(2026, 1, 1), max_targets=10
            )
        with self.assertRaises(discovery.TargetLimitExceeded):
            discovery.enumerate_event_snapshots(
                [_event(id=1), _event(id=2)],
                run_started_at=datetime(
                    2026, 7, 27, tzinfo=dt_timezone.utc
                ),
                max_targets=1,
            )


class P0RacecardOutcomeTests(SimpleTestCase):
    def test_closed_outcomes_and_complete_state_transitions(self):
        checked = "2026-07-27T00:00:00+00:00"
        old = {
            "url": "https://www.jra.go.jp/JRADB/accessD.html?old=1",
            "persisted_status": "confirmed",
            "last_confirmed_at": checked,
        }
        for outcome in discovery.DiscoveryOutcome:
            result = discovery.DiscoveryResult(
                outcome=outcome,
                checked_at=checked,
                provider="jra",
                provider_contract_version="test-v1",
                url=(
                    "https://www.jra.go.jp/JRADB/accessD.html?new=1"
                    if outcome
                    in {
                        discovery.DiscoveryOutcome.FOUND,
                        discovery.DiscoveryOutcome.LISTING_REACHABLE,
                    }
                    else None
                ),
                reason=outcome.value,
            )
            merged = discovery.merge_discovery_state(old, result)
            if outcome is discovery.DiscoveryOutcome.FOUND:
                self.assertEqual(merged["persisted_status"], "confirmed")
                self.assertIn("new=1", merged["url"])
            elif outcome is discovery.DiscoveryOutcome.LISTING_REACHABLE:
                self.assertEqual(
                    merged["persisted_status"], "listing_reachable"
                )
                self.assertIn("new=1", merged["url"])
            elif outcome in discovery.ERROR_OUTCOMES:
                self.assertEqual(
                    merged["persisted_status"], "previous_url_unverified"
                )
                self.assertIn("old=1", merged["url"])
            else:
                self.assertEqual(
                    merged["persisted_status"], "previous_url_unverified"
                )
                self.assertIn("old=1", merged["url"])
        with self.assertRaises(ValueError):
            discovery.DiscoveryResult(
                outcome="invented",
                checked_at=checked,
                provider="jra",
                provider_contract_version="v1",
                reason="invented",
            )

    def test_no_previous_error_and_not_published_are_distinct(self):
        checked = "2026-07-27T00:00:00+00:00"
        error = discovery.merge_discovery_state(
            None,
            discovery.DiscoveryResult(
                outcome=discovery.DiscoveryOutcome.SOURCE_ERROR,
                checked_at=checked,
                provider="jra",
                provider_contract_version="v1",
                reason="source_error",
            ),
        )
        unavailable = discovery.merge_discovery_state(
            None,
            discovery.DiscoveryResult(
                outcome=discovery.DiscoveryOutcome.NOT_PUBLISHED,
                checked_at=checked,
                provider="jra",
                provider_contract_version="v1",
                reason="not_published",
            ),
        )
        self.assertEqual(error["persisted_status"], "error_without_previous")
        self.assertEqual(unavailable["persisted_status"], "not_available")
        self.assertEqual(error["provider"], "jra")
        self.assertEqual(error["checked_provider"], "jra")
        self.assertEqual(
            error["provider_contract_version"],
            error["checked_provider_contract_version"],
        )


class P0RacecardProviderTests(SimpleTestCase):
    def test_equibase_track_date_head_distinguishes_published_and_missing(self):
        event = discovery.EventSnapshot.from_event(
            _event(
                id=430,
                country_region="united_states",
                local_date=date(2026, 8, 1),
                source_refs={"track_code": "DMR"},
            )
        )
        expected_url = (
            "https://tvg.equibase.com/static/entry/"
            "RaceCardIndexDMR080126USA-EQB.html"
        )
        published_transport = Mock(
            return_value=discovery.TransportResponse(
                status_code=200,
                final_url=expected_url,
                body=b"HEAD must not inspect this body",
            )
        )
        published = discovery.discover_event_url(
            event,
            routes=[_head_route()],
            transport=published_transport,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(published.outcome, discovery.DiscoveryOutcome.FOUND)
        self.assertEqual(published.url, expected_url)
        self.assertEqual(
            published_transport.call_args.kwargs["method"], "HEAD"
        )

        missing_transport = Mock(
            return_value=discovery.TransportResponse(
                status_code=404,
                final_url=expected_url,
                body=b"",
            )
        )
        missing = discovery.discover_event_url(
            event,
            routes=[_head_route()],
            transport=missing_transport,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            missing.outcome, discovery.DiscoveryOutcome.NOT_PUBLISHED
        )

    def test_bha_date_fragment_is_listing_reachable_not_confirmed_racecard(self):
        event = discovery.EventSnapshot.from_event(
            _event(
                id=929,
                country_region="united_kingdom",
                local_date=date(2026, 7, 28),
                source_refs={},
            )
        )
        route = _head_route(
            provider="bha",
            region="united_kingdom",
            source_namespace="bha",
            allowed_hosts=["www.britishhorseracing.com"],
            allowed_path_prefixes=["/racing/fixtures/upcoming/"],
            identity_source="event_fields",
            identity_fields=["event_id", "local_date_yyyymmdd"],
            url_template=(
                "https://www.britishhorseracing.com/racing/fixtures/upcoming/"
                "#!/?fromdate={local_date_yyyymmdd}"
                "&todate={local_date_yyyymmdd}&pagenum=1"
            ),
            request_url_template=(
                "https://www.britishhorseracing.com/racing/fixtures/upcoming/"
            ),
            verification_method="head_application_entry",
            verification_scope="date_listing",
            robots_evidence_origin="https://www.britishhorseracing.com",
            robots_evidence_status=200,
            robots_evidence_observed_at="2026-07-27T04:45:00Z",
            robots_evidence_sha256=(
                "05216315099509ab55563fadd64456fa154c46c227c31bc67beb01d3cffc883a"
            ),
            max_requests_per_run=1,
            min_interval_seconds=10,
        )
        request_url = (
            "https://www.britishhorseracing.com/racing/fixtures/upcoming/"
        )
        transport = Mock(
            return_value=discovery.TransportResponse(
                status_code=200,
                final_url=request_url,
                body=b"",
            )
        )
        result = discovery.discover_event_url(
            event,
            routes=[route],
            transport=transport,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            result.outcome, discovery.DiscoveryOutcome.LISTING_REACHABLE
        )
        self.assertEqual(
            result.url,
            request_url
            + "#!/?fromdate=20260728&todate=20260728&pagenum=1",
        )
        self.assertEqual(transport.call_args.args[0], request_url)
        self.assertEqual(transport.call_args.kwargs["method"], "HEAD")
        self.assertEqual(
            result.verification_method, "head_application_entry"
        )
        self.assertEqual(result.verification_scope, "date_listing")
        self.assertEqual(result.source_url, request_url)
        state = discovery.merge_discovery_state(None, result)
        self.assertEqual(state["persisted_status"], "listing_reachable")
        row = discovery._event_document_row(event, result, None)
        self.assertEqual(
            row["verification_method"], "head_application_entry"
        )
        self.assertEqual(row["verification_scope"], "date_listing")
        self.assertEqual(row["source_url"], request_url)
        self.assertEqual(
            row["checked_verification_method"],
            "head_application_entry",
        )

    def test_head_contract_origin_or_digest_mismatch_blocks_before_transport(self):
        event = discovery.EventSnapshot.from_event(
            _event(
                country_region="united_states",
                local_date=date(2026, 8, 1),
                source_refs={"track_code": "DMR"},
            )
        )
        transport = Mock()
        bad_digest = _head_route()
        bad_digest["contract_digest"] = "0" * 64
        for route in (
            _head_route(
                robots_evidence_origin="https://www.equibase.com"
            ),
            bad_digest,
        ):
            with self.subTest(route=route["robots_evidence_origin"]):
                result = discovery.discover_event_url(
                    event,
                    routes=[route],
                    transport=transport,
                    checked_at=datetime(
                        2026, 7, 27, tzinfo=dt_timezone.utc
                    ),
                )
                self.assertEqual(
                    result.outcome,
                    discovery.DiscoveryOutcome.POLICY_BLOCKED,
                )
        transport.assert_not_called()

    @patch(
        "stable.services.p0_racecard_url_discovery.http.client.HTTPSConnection"
    )
    @patch("stable.services.p0_racecard_url_discovery.ssl.create_default_context")
    @patch("stable.services.p0_racecard_url_discovery.socket.create_connection")
    @patch(
        "stable.services.p0_racecard_url_discovery._public_dns_addresses",
        return_value=("203.0.113.10",),
    )
    def test_safe_head_transport_reads_zero_body_deduplicates_and_paces_host(
        self,
        _dns,
        create_connection,
        create_context,
        https_connection,
    ):
        class HeadResponse:
            status = 200

            def read(self, *_args, **_kwargs):
                raise AssertionError("HEAD response body must never be read")

        raw_socket = Mock()
        tls_socket = Mock()
        create_connection.return_value = raw_socket
        create_context.return_value.wrap_socket.return_value = tls_socket
        created_connections = []

        def make_connection(*_args, **_kwargs):
            connection = Mock()
            connection.getresponse.return_value = HeadResponse()
            created_connections.append(connection)
            return connection

        https_connection.side_effect = make_connection
        monotonic = Mock(side_effect=[100.0, 100.0, 105.0])
        sleeper = Mock()
        transport = discovery.SafeHttpTransport(
            total_request_budget=3,
            per_host_request_budget=2,
            monotonic=monotonic,
            sleeper=sleeper,
        )
        route = _head_route()
        dmr_url = (
            "https://tvg.equibase.com/static/entry/"
            "RaceCardIndexDMR080126USA-EQB.html"
        )
        cnl_url = (
            "https://tvg.equibase.com/static/entry/"
            "RaceCardIndexCNL080126USA-EQB.html"
        )
        first = transport(
            dmr_url,
            route=route,
            timeout_seconds=5,
            max_response_bytes=1,
            method="HEAD",
        )
        replay = transport(
            dmr_url,
            route=route,
            timeout_seconds=5,
            max_response_bytes=1,
            method="HEAD",
        )
        second = transport(
            cnl_url,
            route=route,
            timeout_seconds=5,
            max_response_bytes=1,
            method="HEAD",
        )
        self.assertEqual(first.body, b"")
        self.assertEqual(replay, first)
        self.assertEqual(second.body, b"")
        self.assertEqual(len(created_connections), 2)
        self.assertEqual(
            [call.args[0] for call in created_connections[0].request.call_args_list],
            ["HEAD"],
        )
        self.assertEqual(
            [call.args[0] for call in created_connections[1].request.call_args_list],
            ["HEAD"],
        )
        sleeper.assert_called_once_with(5.0)

    def test_provider_selection_is_unique_and_disabled_route_has_zero_transport(self):
        event = discovery.EventSnapshot.from_event(_event())
        transport = Mock()
        result = discovery.discover_event_url(
            event,
            routes=[_route(automation_allowed=False)],
            transport=transport,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(result.outcome, discovery.DiscoveryOutcome.ADAPTER_DISABLED)
        transport.assert_not_called()

        conflict = discovery.discover_event_url(
            event,
            routes=[_route(), _route(contract_version="test-v2")],
            transport=transport,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            conflict.outcome, discovery.DiscoveryOutcome.IDENTITY_CONFLICT
        )
        transport.assert_not_called()

        unsafe_identity = discovery.EventSnapshot.from_event(
            _event(
                source_refs={
                    "jra": {"race_id": "race-1\nAuthorization: secret"}
                }
            )
        )
        rejected = discovery.discover_event_url(
            unsafe_identity,
            routes=[_route()],
            transport=transport,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            rejected.outcome, discovery.DiscoveryOutcome.IDENTITY_MISSING
        )
        transport.assert_not_called()

    def test_found_requires_positive_identity_marker_and_plain_404_is_unverified(self):
        event = discovery.EventSnapshot.from_event(_event())
        positive = Mock(
            return_value=discovery.TransportResponse(
                status_code=200,
                final_url=(
                    "https://www.jra.go.jp/JRADB/accessD.html?"
                    "CNAME=pw01dde100520260501011120260727/202605010111"
                ),
                body=b'<main data-race-id="202605010111">card</main>',
            )
        )
        result = discovery.discover_event_url(
            event,
            routes=[_route()],
            transport=positive,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(result.outcome, discovery.DiscoveryOutcome.FOUND)
        self.assertEqual(positive.call_count, 1)

        plain_404 = Mock(
            return_value=discovery.TransportResponse(
                status_code=404,
                final_url="https://www.jra.go.jp/JRADB/accessD.html",
                body=b"not found",
            )
        )
        missing = discovery.discover_event_url(
            event,
            routes=[_route()],
            transport=plain_404,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            missing.outcome, discovery.DiscoveryOutcome.PATH_UNVERIFIED
        )

    def test_only_explicit_official_marker_means_not_published(self):
        event = discovery.EventSnapshot.from_event(_event())
        response = Mock(
            return_value=discovery.TransportResponse(
                status_code=200,
                final_url="https://www.jra.go.jp/JRADB/accessD.html",
                body=b"RACECARD_NOT_PUBLISHED",
            )
        )
        result = discovery.discover_event_url(
            event,
            routes=[_route()],
            transport=response,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            result.outcome, discovery.DiscoveryOutcome.NOT_PUBLISHED
        )

    def test_expired_contract_and_redirect_outside_allowlist_are_policy_blocked(self):
        event = discovery.EventSnapshot.from_event(_event())
        transport = Mock()
        expired = discovery.discover_event_url(
            event,
            routes=[_route(valid_until="2026-07-26T00:00:00Z")],
            transport=transport,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            expired.outcome, discovery.DiscoveryOutcome.POLICY_BLOCKED
        )
        transport.assert_not_called()

        terms_blocked = discovery.discover_event_url(
            event,
            routes=[
                _route(
                    access_mode="terms_blocked_pending_review",
                    robots_allowed=False,
                )
            ],
            transport=transport,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            terms_blocked.outcome,
            discovery.DiscoveryOutcome.POLICY_BLOCKED,
        )
        transport.assert_not_called()

        redirect = Mock(
            return_value=discovery.TransportResponse(
                status_code=200,
                final_url="https://evil.test/racecard",
                body=b'<main data-race-id="202605010111"></main>',
            )
        )
        blocked = discovery.discover_event_url(
            event,
            routes=[_route()],
            transport=redirect,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            blocked.outcome, discovery.DiscoveryOutcome.POLICY_BLOCKED
        )

    def test_transport_exception_details_never_escape_fixed_result(self):
        event = discovery.EventSnapshot.from_event(_event())
        secret = "token=DO_NOT_PERSIST"
        result = discovery.discover_event_url(
            event,
            routes=[_route()],
            transport=Mock(side_effect=RuntimeError(secret)),
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        encoded = json.dumps(result.__dict__, ensure_ascii=False)
        self.assertEqual(result.outcome, discovery.DiscoveryOutcome.SOURCE_ERROR)
        self.assertNotIn(secret, encoded)

    def test_route_url_validation_rejects_ssrf_shapes(self):
        route = _route()
        for url in (
            "http://www.jra.go.jp/JRADB/accessD.html",
            "https://user@www.jra.go.jp/JRADB/accessD.html",
            "https://www.jra.go.jp:8443/JRADB/accessD.html",
            "https://127.0.0.1/JRADB/accessD.html",
            "https://evil.test/JRADB/accessD.html",
            "https://www.jra.go.jp/other",
        ):
            with self.subTest(url=url):
                with self.assertRaises(discovery.RoutePolicyError):
                    discovery.validate_official_url(url, route)

    def test_route_path_rejects_traversal_and_encoded_separator_bypasses(self):
        route = _route(
            allowed_path_prefixes=["/JRADB/"],
        )
        unsafe_paths = (
            "/JRADB/../admin",
            "/JRADB/./accessD.html",
            "/JRADB/%2e%2e/admin",
            "/JRADB/%252e%252e/admin",
            "/JRADB/%2fadmin",
            "/JRADB/%252fadmin",
            "/JRADB/%ffadmin",
            r"/JRADB/\..\admin",
        )
        for path in unsafe_paths:
            with self.subTest(path=path):
                with self.assertRaises(discovery.RoutePolicyError):
                    discovery.validate_official_url(
                        f"https://www.jra.go.jp{path}", route
                    )
        self.assertEqual(
            discovery.validate_official_url(
                "https://www.jra.go.jp/JRADB/accessD.html?"
                "CNAME=official%20query",
                route,
            ),
            "https://www.jra.go.jp/JRADB/accessD.html?"
            "CNAME=official%20query",
        )

    @patch("stable.services.p0_racecard_url_discovery.socket.getaddrinfo")
    def test_private_dns_and_exhausted_budget_fail_before_http(self, getaddrinfo):
        getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 443))
        ]
        with self.assertRaises(discovery.RoutePolicyError):
            discovery._public_dns_addresses("www.jra.go.jp")

        getaddrinfo.reset_mock()
        transport = discovery.SafeHttpTransport(total_request_budget=0)
        with self.assertRaises(discovery.RoutePolicyError):
            transport(
                "https://www.jra.go.jp/JRADB/accessD.html",
                route=_route(),
                timeout_seconds=1,
                max_response_bytes=100,
            )
        getaddrinfo.assert_not_called()

    @patch("stable.services.p0_racecard_url_discovery.socket.getaddrinfo")
    def test_all_non_global_dns_addresses_are_rejected(self, getaddrinfo):
        for address in (
            "100.64.0.1",
            "192.0.2.1",
            "169.254.1.1",
            "2001:db8::1",
        ):
            with self.subTest(address=address):
                getaddrinfo.return_value = [
                    (2, 1, 6, "", (address, 443))
                ]
                with self.assertRaises(discovery.RoutePolicyError):
                    discovery._public_dns_addresses("www.jra.go.jp")

    def test_service_propagates_soft_time_limit(self):
        event = discovery.EventSnapshot.from_event(_event())
        with self.assertRaises(SoftTimeLimitExceeded):
            discovery.discover_event_url(
                event,
                routes=[_route()],
                transport=Mock(
                    side_effect=SoftTimeLimitExceeded(
                        "secret transport detail"
                    )
                ),
                checked_at=datetime(
                    2026, 7, 27, tzinfo=dt_timezone.utc
                ),
            )

    def test_registry_has_all_required_provider_adapters_and_reviewed_head_routes(self):
        routes = discovery.load_route_registry(
            REPO_ROOT
            / "runtime/policies/p0_racecard_urls/official_url_routes_v1.json"
        )
        self.assertEqual(
            {route["provider"] for route in routes},
            {"jra", "nar", "hkjc", "bha", "france_galop", "equibase"},
        )
        by_provider = {route["provider"]: route for route in routes}
        self.assertTrue(by_provider["bha"]["automation_allowed"])
        self.assertTrue(by_provider["equibase"]["automation_allowed"])
        self.assertEqual(
            by_provider["equibase"]["allowed_hosts"],
            ["tvg.equibase.com"],
        )
        self.assertEqual(
            by_provider["equibase"]["robots_evidence_origin"],
            "https://tvg.equibase.com",
        )
        self.assertEqual(
            by_provider["equibase"]["verification_method"],
            "head_exact_path",
        )
        self.assertFalse(by_provider["france_galop"]["automation_allowed"])
        self.assertFalse(by_provider["jra"]["automation_allowed"])
        self.assertFalse(by_provider["nar"]["automation_allowed"])
        self.assertFalse(by_provider["hkjc"]["automation_allowed"])
        for provider in ("bha", "equibase"):
            route = by_provider[provider]
            expected_digest = hashlib.sha256(
                json.dumps(
                    {
                        key: value
                        for key, value in route.items()
                        if key != "contract_digest"
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(route["contract_digest"], expected_digest)
        with self.assertRaises(discovery.RoutePolicyError):
            discovery.load_route_registry(
                REPO_ROOT
                / "runtime/policies/p0_racecard_urls/official_url_routes_v1.json",
                expected_sha256="0" * 64,
            )

    def test_six_provider_identity_contracts_can_prove_exact_fixture_links(self):
        cases = (
            ("jra", "japan", "www.jra.go.jp", "/JRADB/accessD.html"),
            (
                "nar",
                "japan",
                "www.keiba.go.jp",
                "/KeibaWeb/TodayRaceInfo/DebaTable",
            ),
            (
                "hkjc",
                "hong_kong",
                "racing.hkjc.com",
                "/racing/information/English/Racing/RaceCard.aspx",
            ),
            (
                "bha",
                "united_kingdom",
                "www.britishhorseracing.com",
                "/racing/fixtures/racecard",
            ),
            (
                "france_galop",
                "france",
                "www.france-galop.com",
                "/en/racing/racecard",
            ),
            (
                "equibase",
                "united_states",
                "www.equibase.com",
                "/static/entry/racecard.html",
            ),
        )
        for provider, region, host, path in cases:
            with self.subTest(provider=provider):
                race_id = f"{provider}-official-1"
                event = discovery.EventSnapshot.from_event(
                    _event(
                        country_region=region,
                        source_refs={provider: {"race_id": race_id}},
                    )
                )
                url = f"https://{host}{path}?race_id={race_id}"
                route = _route(
                    provider=provider,
                    region=region,
                    source_namespace=provider,
                    allowed_hosts=[host],
                    allowed_path_prefixes=[path],
                    identity_fields=["race_id"],
                    url_template=f"https://{host}{path}?race_id={{race_id}}",
                    identity_marker_template="OFFICIAL:{race_id}",
                )
                transport = Mock(
                    return_value=discovery.TransportResponse(
                        status_code=200,
                        final_url=url,
                        body=f"OFFICIAL:{race_id}".encode(),
                    )
                )
                result = discovery.discover_event_url(
                    event,
                    routes=[route],
                    transport=transport,
                    checked_at=datetime(
                        2026, 7, 27, tzinfo=dt_timezone.utc
                    ),
                )
                self.assertEqual(
                    result.outcome, discovery.DiscoveryOutcome.FOUND
                )
                self.assertEqual(result.url, url)

    def test_template_without_positive_marker_is_only_unverified(self):
        event = discovery.EventSnapshot.from_event(_event())
        response = Mock(
            return_value=discovery.TransportResponse(
                status_code=200,
                final_url=(
                    "https://www.jra.go.jp/JRADB/accessD.html?"
                    "CNAME=pw01dde100520260501011120260727/202605010111"
                ),
                body=b"<main>race name only</main>",
            )
        )
        result = discovery.discover_event_url(
            event,
            routes=[_route(identity_marker_template="")],
            transport=response,
            checked_at=datetime(2026, 7, 27, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(
            result.outcome, discovery.DiscoveryOutcome.CANDIDATE_UNVERIFIED
        )


class P0RacecardGenerationTests(SimpleTestCase):
    def _payload(self, started: str, *, url: str | None = None):
        return {
            "schema_version": 1,
            "generated_at": started,
            "run_started_at": started,
            "window": {
                "start": started,
                "end": "2026-08-03T00:00:00+00:00",
                "timezone": "Asia/Shanghai",
            },
            "coverage": {"future_expected": 1, "orphans": 0},
            "providers": [],
            "events": [
                {
                    "event_id": 1,
                    "local_date": "2026-07-27",
                    "country_region": "japan",
                    "name_zh": "测试赛",
                    "discovery_outcome": "found" if url else "not_published",
                    "persisted_status": "confirmed" if url else "not_available",
                    "url": url,
                }
            ],
        }

    def test_generation_is_sha_bound_and_current_is_atomic_relative_symlink(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = discovery.publish_generation(
                root,
                self._payload(
                    "2026-07-27T00:00:00+00:00",
                    url="https://www.jra.go.jp/JRADB/accessD.html?id=1",
                ),
            )
            current = root / "current"
            self.assertTrue(current.is_symlink())
            self.assertEqual(
                os.readlink(current), f"generations/{result.generation_id}"
            )
            manifest = json.loads(
                (current / "manifest.json").read_text(encoding="utf-8")
            )
            discovery.verify_generation(current)
            self.assertEqual(
                stat.S_IMODE((current / "latest.md").stat().st_mode), 0o640
            )
            self.assertEqual(
                stat.S_IMODE(current.resolve().stat().st_mode), 0o750
            )
            self.assertEqual(
                manifest["generation_id"], result.generation_id
            )
            self.assertIn("测试赛", (current / "latest.md").read_text())

    def test_stale_run_cannot_replace_newer_generation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            newer = self._payload("2026-07-28T00:00:00+00:00")
            older = self._payload("2026-07-27T00:00:00+00:00")
            first = discovery.publish_generation(root, newer)
            with self.assertRaises(discovery.StaleRunError):
                discovery.publish_generation(root, older)
            self.assertEqual(
                os.readlink(root / "current"),
                f"generations/{first.generation_id}",
            )

    def test_non_current_symlink_and_unsafe_root_are_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "generations").mkdir()
            (root / "generations" / "evil").symlink_to("/tmp")
            with self.assertRaises(discovery.ArtifactSafetyError):
                discovery.publish_generation(
                    root, self._payload("2026-07-27T00:00:00+00:00")
                )

    def test_crash_points_keep_current_on_a_complete_generation(self):
        phases = (
            "after_markdown_fsync",
            "after_json_fsync",
            "after_generation_fsync",
            "after_generation_rename",
            "before_current_replace",
            "after_current_replace",
        )
        for phase in phases:
            with self.subTest(phase=phase), TemporaryDirectory() as directory:
                root = Path(directory)
                old = discovery.publish_generation(
                    root, self._payload("2026-07-27T00:00:00+00:00")
                )

                def crash(current_phase):
                    if current_phase == phase:
                        raise RuntimeError("simulated_crash")

                with self.assertRaises(RuntimeError):
                    discovery.publish_generation(
                        root,
                        self._payload("2026-07-28T00:00:00+00:00"),
                        phase_hook=crash,
                    )
                current = (root / "current").resolve()
                discovery.verify_generation(current)
                self.assertIn(current.name, {old.generation_id} | {
                    path.name
                    for path in (root / "generations").iterdir()
                    if path.is_dir() and len(path.name) == 64
                })

    def test_only_current_and_previous_complete_generations_are_retained(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ids = []
            for day in (27, 28, 29):
                result = discovery.publish_generation(
                    root,
                    self._payload(
                        f"2026-07-{day:02d}T00:00:00+00:00"
                    ),
                )
                ids.append(result.generation_id)
            retained = {
                path.name
                for path in (root / "generations").iterdir()
                if path.is_dir() and not path.name.startswith(".tmp-")
            }
            self.assertEqual(retained, set(ids[-2:]))

    def test_raw_fixture_content_is_not_written_to_bundle(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            secret = "horse-name SECRET_COOKIE header-value"
            discovery.publish_generation(
                root, self._payload("2026-07-27T00:00:00+00:00")
            )
            stored = b"".join(
                path.read_bytes()
                for path in (root / "current").resolve().iterdir()
                if path.is_file()
            )
            self.assertNotIn(secret.encode(), stored)


class P0RacecardSummaryTests(SimpleTestCase):
    def _row(self, **overrides):
        row = {
            "persisted_status": "previous_url_unverified",
            "discovery_outcome": "source_error",
            "country_region": "japan",
            "provider": "jra",
            "checked_provider": "jra",
        }
        row.update(overrides)
        return row

    def test_preserved_url_error_outcomes_still_count_as_current_errors(self):
        rows = [
            self._row(discovery_outcome=outcome.value)
            for outcome in discovery.ERROR_OUTCOMES
        ]
        summary = discovery._summary(rows)
        self.assertEqual(summary["preserved_previous"], 4)
        self.assertEqual(summary["errors"], 4)

    def test_empty_checked_provider_never_falls_back_to_confirmed_provider(self):
        rows = [
            self._row(
                discovery_outcome="identity_missing",
                persisted_status="not_available",
                checked_provider="",
            ),
            self._row(
                discovery_outcome="identity_conflict",
                checked_provider="",
            ),
        ]
        summary = discovery._summary(rows)
        self.assertEqual(summary["by_provider"], {"unresolved": 2})
        self.assertNotIn("jra", summary["by_provider"])

    def test_listing_reachable_is_counted_separately_from_not_available(self):
        summary = discovery._summary(
            [
                self._row(
                    persisted_status="listing_reachable",
                    discovery_outcome="listing_reachable",
                    country_region="united_kingdom",
                    provider="bha",
                    checked_provider="bha",
                )
            ]
        )
        self.assertEqual(summary["listing_reachable"], 1)
        self.assertEqual(summary["found"], 0)
        self.assertEqual(summary["not_available"], 0)


class P0RacecardTrustRenderingTests(SimpleTestCase):
    def test_markdown_distinguishes_exact_index_from_date_listing(self):
        canonical = {
            "generated_at": "2026-07-27T05:20:33+00:00",
            "window": {
                "start": "2026-07-27T05:20:24+00:00",
                "end": "2026-08-03T05:20:24+00:00",
                "start_zh": "2026-07-27T13:20:24+08:00",
                "end_zh": "2026-08-03T13:20:24+08:00",
                "timezone": "Asia/Shanghai",
            },
            "coverage": {"future_expected": 2, "orphans": 0},
            "events": [
                {
                    "event_id": 430,
                    "local_date": "2026-08-01",
                    "country_region": "united_states",
                    "name_zh": "美国测试赛",
                    "provider": "equibase",
                    "checked_provider": "equibase",
                    "url": (
                        "https://tvg.equibase.com/static/entry/"
                        "RaceCardIndexDMR080126USA-EQB.html"
                    ),
                    "discovery_outcome": "found",
                    "reason": "found",
                },
                {
                    "event_id": 929,
                    "local_date": "2026-07-28",
                    "country_region": "united_kingdom",
                    "name_zh": "英国测试赛",
                    "provider": "bha",
                    "checked_provider": "bha",
                    "url": (
                        "https://www.britishhorseracing.com/"
                        "racing/fixtures/upcoming/#!/?fromdate=20260728"
                    ),
                    "discovery_outcome": "listing_reachable",
                    "reason": "listing_reachable",
                },
            ],
        }
        markdown = discovery._markdown_bytes(
            canonical, "0" * 64
        ).decode("utf-8")
        self.assertIn("[已确认出马索引]", markdown)
        self.assertIn("[官方日期索引（需人工确认）]", markdown)
        self.assertNotIn("[官方页面]", markdown)


class P0RacecardProvenanceTests(SimpleTestCase):
    def test_preserved_url_keeps_trust_provenance_and_audits_new_check(self):
        checked = "2026-07-27T05:20:33+00:00"
        previous = {
            "persisted_status": "confirmed",
            "url": (
                "https://tvg.equibase.com/static/entry/"
                "RaceCardIndexDMR080126USA-EQB.html"
            ),
            "provider": "equibase",
            "provider_event_id": "track_code=DMR",
            "provider_contract_version": "equibase-v1",
            "verification_method": "head_exact_path",
            "verification_scope": "track_date_racecard_index",
            "source_url": (
                "https://tvg.equibase.com/static/entry/"
                "RaceCardIndexDMR080126USA-EQB.html"
            ),
            "last_confirmed_at": checked,
        }
        result = discovery.DiscoveryResult(
            outcome=discovery.DiscoveryOutcome.SOURCE_ERROR,
            checked_at=checked,
            provider="bha",
            provider_event_id="event_id=430",
            provider_contract_version="bha-v1",
            verification_method="head_application_entry",
            verification_scope="date_listing",
            source_url=(
                "https://www.britishhorseracing.com/"
                "racing/fixtures/upcoming/"
            ),
            reason="source_error",
        )
        merged = discovery.merge_discovery_state(previous, result)
        self.assertEqual(
            merged["verification_method"], "head_exact_path"
        )
        self.assertEqual(
            merged["verification_scope"],
            "track_date_racecard_index",
        )
        self.assertEqual(
            merged["checked_verification_method"],
            "head_application_entry",
        )
        self.assertEqual(
            merged["checked_verification_scope"], "date_listing"
        )
        self.assertEqual(
            merged["checked_source_url"], result.source_url
        )


class P0RacecardServiceIntegrationTests(SimpleTestCase):
    def test_fake_transport_run_replaces_then_preserves_latest_confirmed_url(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "artifacts"
            registry = base / "registry.json"
            registry.write_text(
                json.dumps({"schema_version": 1, "routes": [_route()]}),
                encoding="utf-8",
            )
            first_url = (
                "https://www.jra.go.jp/JRADB/accessD.html?"
                "CNAME=pw01dde100520260501011120260727/202605010111"
            )
            first = Mock(
                return_value=discovery.TransportResponse(
                    status_code=200,
                    final_url=first_url,
                    body=b'<main data-race-id="202605010111"></main>',
                )
            )
            summary = discovery.run_p0_racecard_url_discovery(
                events=[
                    _event(
                        race_datetime=datetime(
                            2026, 7, 27, 2, tzinfo=dt_timezone.utc
                        )
                    )
                ],
                run_started_at=datetime(
                    2026, 7, 27, tzinfo=dt_timezone.utc
                ),
                artifact_root=root,
                registry_path=registry,
                transport=first,
            )
            self.assertEqual(summary["future_expected"], 1)
            self.assertEqual(summary["found"], 1)

            second = Mock(
                return_value=discovery.TransportResponse(
                    status_code=404,
                    final_url=first_url,
                    body=b"ordinary missing page",
                )
            )
            second_summary = discovery.run_p0_racecard_url_discovery(
                events=[
                    _event(
                        race_datetime=datetime(
                            2026, 7, 27, 2, tzinfo=dt_timezone.utc
                        )
                    )
                ],
                run_started_at=datetime(
                    2026, 7, 27, 1, tzinfo=dt_timezone.utc
                ),
                artifact_root=root,
                registry_path=registry,
                transport=second,
            )
            current = discovery.read_current_payload(root)
            self.assertIsNotNone(current)
            self.assertEqual(
                current["window"]["start_zh"],
                "2026-07-27T09:00:00+08:00",
            )
            row = current["events"][0]
            self.assertEqual(row["url"], first_url)
            self.assertEqual(
                row["persisted_status"], "previous_url_unverified"
            )
            self.assertEqual(second_summary["preserved_previous"], 1)

    def test_newer_failed_run_merges_against_current_inside_publish_lock(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "artifacts"
            registry = base / "registry.json"
            registry.write_text(
                json.dumps({"schema_version": 1, "routes": [_route()]}),
                encoding="utf-8",
            )
            official_url = (
                "https://www.jra.go.jp/JRADB/accessD.html?"
                "CNAME=pw01dde100520260501011120260727/202605010111"
            )
            event = _event(
                race_datetime=datetime(
                    2026, 7, 27, 2, tzinfo=dt_timezone.utc
                )
            )
            newer_transport_entered = threading.Event()
            release_newer_transport = threading.Event()
            newer_result = {}

            def newer_failed_transport(*args, **kwargs):
                newer_transport_entered.set()
                self.assertTrue(release_newer_transport.wait(timeout=10))
                return discovery.TransportResponse(
                    status_code=404,
                    final_url=official_url,
                    body=b"ordinary missing page",
                )

            def run_newer():
                try:
                    newer_result["summary"] = (
                        discovery.run_p0_racecard_url_discovery(
                            events=[event],
                            run_started_at=datetime(
                                2026, 7, 27, 1, tzinfo=dt_timezone.utc
                            ),
                            artifact_root=root,
                            registry_path=registry,
                            transport=newer_failed_transport,
                        )
                    )
                except BaseException as exc:
                    newer_result["exception"] = exc

            newer_thread = threading.Thread(target=run_newer)
            newer_thread.start()
            self.assertTrue(newer_transport_entered.wait(timeout=10))

            discovery.run_p0_racecard_url_discovery(
                events=[event],
                run_started_at=datetime(
                    2026, 7, 27, tzinfo=dt_timezone.utc
                ),
                artifact_root=root,
                registry_path=registry,
                transport=Mock(
                    return_value=discovery.TransportResponse(
                        status_code=200,
                        final_url=official_url,
                        body=b'<main data-race-id="202605010111"></main>',
                    )
                ),
            )
            release_newer_transport.set()
            newer_thread.join(timeout=10)
            self.assertFalse(newer_thread.is_alive())
            if "exception" in newer_result:
                raise newer_result["exception"]

            current = discovery.read_current_payload(root)
            self.assertIsNotNone(current)
            row = current["events"][0]
            self.assertEqual(row["url"], official_url)
            self.assertEqual(
                row["persisted_status"], "previous_url_unverified"
            )
            self.assertEqual(
                newer_result["summary"]["preserved_previous"], 1
            )

    def test_preserved_url_keeps_confirmed_provenance_and_audits_new_check(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "artifacts"
            first_registry = base / "registry-v1.json"
            second_registry = base / "registry-v2.json"
            first_registry.write_text(
                json.dumps({"schema_version": 1, "routes": [_route()]}),
                encoding="utf-8",
            )
            second_registry.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "routes": [
                            _route(
                                provider="jra_mirror",
                                contract_version="test-v2",
                            )
                        ],
                    }
                ),
                encoding="utf-8",
            )
            official_url = (
                "https://www.jra.go.jp/JRADB/accessD.html?"
                "CNAME=pw01dde100520260501011120260727/202605010111"
            )
            event = _event(
                race_datetime=datetime(
                    2026, 7, 27, 2, tzinfo=dt_timezone.utc
                )
            )
            discovery.run_p0_racecard_url_discovery(
                events=[event],
                run_started_at=datetime(
                    2026, 7, 27, tzinfo=dt_timezone.utc
                ),
                artifact_root=root,
                registry_path=first_registry,
                transport=Mock(
                    return_value=discovery.TransportResponse(
                        status_code=200,
                        final_url=official_url,
                        body=b'<main data-race-id="202605010111"></main>',
                    )
                ),
            )
            confirmed = discovery.read_current_payload(root)["events"][0]
            self.assertEqual(confirmed["provider"], "jra")
            self.assertEqual(confirmed["checked_provider"], "jra")
            self.assertEqual(
                confirmed["provider_event_id"],
                confirmed["checked_provider_event_id"],
            )
            self.assertEqual(
                confirmed["provider_contract_version"],
                confirmed["checked_provider_contract_version"],
            )
            checked_summary = discovery.run_p0_racecard_url_discovery(
                events=[event],
                run_started_at=datetime(
                    2026, 7, 27, 1, tzinfo=dt_timezone.utc
                ),
                artifact_root=root,
                registry_path=second_registry,
                transport=Mock(
                    return_value=discovery.TransportResponse(
                        status_code=500,
                        final_url=official_url,
                        body=b"provider failure",
                    )
                ),
            )

            current = discovery.read_current_payload(root)
            self.assertIsNotNone(current)
            row = current["events"][0]
            self.assertEqual(row["persisted_status"], "previous_url_unverified")
            self.assertEqual(row["url"], official_url)
            self.assertEqual(row["provider"], "jra")
            self.assertEqual(
                row["provider_event_id"], "race_id=202605010111"
            )
            self.assertEqual(
                row["provider_contract_version"], "test-v1"
            )
            self.assertEqual(row["checked_provider"], "jra_mirror")
            self.assertEqual(
                row["checked_provider_event_id"], "race_id=202605010111"
            )
            self.assertEqual(
                row["checked_provider_contract_version"], "test-v2"
            )
            self.assertEqual(row["discovery_outcome"], "source_error")
            self.assertEqual(row["reason"], "source_error")
            self.assertEqual(
                row["last_checked_at"], "2026-07-27T01:00:00+00:00"
            )
            self.assertEqual(
                checked_summary["by_provider"], {"jra_mirror": 1}
            )


class P0RacecardTaskTests(SimpleTestCase):
    @override_settings(P0_RACECARD_URL_DISCOVERY_ENABLED=False)
    @patch("stable.tasks.TaskExecutionLog.objects.create")
    def test_disabled_task_has_no_database_or_service_side_effect(self, create):
        from stable.tasks import discover_p0_racecard_urls_task

        with patch(
            "stable.tasks.run_p0_racecard_url_discovery"
        ) as runner:
            result = discover_p0_racecard_urls_task()
        self.assertEqual(result, {"enabled": False})
        runner.assert_not_called()
        create.assert_not_called()

    @override_settings(
        P0_RACECARD_URL_DISCOVERY_ENABLED=True,
        P0_RACECARD_URL_DISCOVERY_REQUEST_BUDGET=1,
        P0_RACECARD_URL_DISCOVERY_MAX_TARGETS=10,
    )
    @patch("stable.models.RaceEvent.objects.filter")
    @patch("stable.tasks.TaskExecutionLog.objects.create")
    @patch("stable.tasks.run_p0_racecard_url_discovery")
    def test_enabled_task_logs_only_allowlisted_counts(
        self, runner, create, race_filter
    ):
        from stable.tasks import discover_p0_racecard_urls_task

        race_filter.return_value.iterator.return_value = iter([])
        log = Mock()
        create.return_value = log
        runner.return_value = {
            "future_expected": 1,
            "orphans": 0,
            "found": 1,
            "listing_reachable": 3,
            "not_available": 0,
            "preserved_previous": 0,
            "blocked": 0,
            "errors": 0,
            "by_region": {"japan": 1},
            "by_provider": {"jra": 1},
            "generation_id": "a" * 64,
        }
        result = discover_p0_racecard_urls_task()
        self.assertTrue(result["enabled"])
        self.assertNotIn("generation_id", log.payload)
        self.assertEqual(log.payload["listing_reachable"], 3)
        self.assertEqual(log.detail, "completed")
        log.save.assert_called_once()

    @override_settings(P0_RACECARD_URL_DISCOVERY_ENABLED=True)
    @patch("stable.models.RaceEvent.objects.filter")
    @patch("stable.tasks.TaskExecutionLog.objects.create")
    @patch("stable.tasks.run_p0_racecard_url_discovery")
    def test_failure_drops_exception_text_from_return_and_log(
        self, runner, create, race_filter
    ):
        from stable.tasks import discover_p0_racecard_urls_task

        race_filter.return_value.iterator.return_value = iter([])
        secret = "https://user:password@example.test/?token=secret"
        runner.side_effect = RuntimeError(secret)
        log = Mock()
        create.return_value = log
        result = discover_p0_racecard_urls_task()
        encoded = json.dumps(
            {"result": result, "payload": log.payload, "detail": log.detail}
        )
        self.assertNotIn(secret, encoded)
        self.assertEqual(result["error_code"], "discovery_batch_failed")
        self.assertEqual(log.payload["listing_reachable"], 0)

    @override_settings(P0_RACECARD_URL_DISCOVERY_ENABLED=True)
    @patch("stable.models.RaceEvent.objects.filter")
    @patch("stable.tasks.TaskExecutionLog.objects.create")
    @patch("stable.tasks.run_p0_racecard_url_discovery")
    def test_overlapping_publish_returns_already_running(
        self, runner, create, race_filter
    ):
        from stable.tasks import discover_p0_racecard_urls_task

        race_filter.return_value.iterator.return_value = iter([])
        runner.side_effect = discovery.PublishLockBusyError("private detail")
        log = Mock()
        create.return_value = log
        result = discover_p0_racecard_urls_task()
        self.assertEqual(result["reason"], "already_running")
        self.assertEqual(log.detail, "already_running")
        self.assertEqual(log.status, "success")
        self.assertEqual(log.payload["listing_reachable"], 0)

    @override_settings(P0_RACECARD_URL_DISCOVERY_ENABLED=True)
    @patch("stable.models.RaceEvent.objects.filter")
    @patch("stable.tasks.TaskExecutionLog.objects.create")
    @patch("stable.tasks.run_p0_racecard_url_discovery")
    def test_task_records_fixed_failure_then_propagates_soft_time_limit(
        self, runner, create, race_filter
    ):
        from stable.tasks import discover_p0_racecard_urls_task

        race_filter.return_value.iterator.return_value = iter([])
        secret = "secret timeout detail"
        runner.side_effect = SoftTimeLimitExceeded(secret)
        log = Mock()
        create.return_value = log
        with self.assertRaises(SoftTimeLimitExceeded):
            discover_p0_racecard_urls_task()
        encoded = json.dumps(
            {"payload": log.payload, "detail": log.detail}
        )
        self.assertNotIn(secret, encoded)
        self.assertEqual(log.status, "failed")
        self.assertEqual(log.detail, "soft_time_limit_exceeded")
        self.assertEqual(log.payload["listing_reachable"], 0)
        log.save.assert_called_once()

    @override_settings(P0_RACECARD_URL_DISCOVERY_ENABLED=True)
    @patch("stable.models.RaceEvent.objects.filter")
    @patch("stable.tasks.TaskExecutionLog.objects.create")
    @patch("stable.tasks.run_p0_racecard_url_discovery")
    def test_log_save_failure_does_not_mask_soft_time_limit(
        self, runner, create, race_filter
    ):
        from stable.tasks import discover_p0_racecard_urls_task

        race_filter.return_value.iterator.return_value = iter([])
        timeout = SoftTimeLimitExceeded("original soft timeout")
        runner.side_effect = timeout
        log = Mock()
        log.save.side_effect = RuntimeError("log database unavailable")
        create.return_value = log
        with self.assertRaises(SoftTimeLimitExceeded) as caught:
            discover_p0_racecard_urls_task()
        self.assertIs(caught.exception, timeout)
