"""赛事控制不能依赖新闻队列或用时间猜测完赛。"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase

from stable.services.race_event_lifecycle import decide_race_lifecycle
from stable.services.race_data_sync_lifecycle import decide_data_sync_lifecycle


NOW = datetime(2026, 11, 15, 7, tzinfo=timezone.utc)


class WinnerRequiredTests(SimpleTestCase):
    def test_running_without_winner_never_finishes_on_clock(self):
        for elapsed in (30, 60, 1440):
            with self.subTest(elapsed=elapsed):
                decision = decide_race_lifecycle(
                    race_datetime=NOW, timezone_name="Asia/Tokyo",
                    status="running", now=NOW + timedelta(minutes=elapsed), region="japan",
                )
                self.assertEqual(decision.action, "noop")
                self.assertEqual(decision.reason_code, "awaiting_winner")

    def test_late_scheduled_only_advances_to_running(self):
        decision = decide_race_lifecycle(
            race_datetime=NOW, timezone_name="Asia/Tokyo",
            status="scheduled", now=NOW + timedelta(days=1), region="japan",
        )
        self.assertEqual(decision.to_status, "running")

    def test_date_only_does_not_finish_next_day(self):
        decision = decide_race_lifecycle(
            race_datetime=None, local_date=NOW.date(), timezone_name="Asia/Tokyo",
            status="scheduled", now=NOW + timedelta(days=1), region="japan",
        )
        self.assertEqual(decision.action, "noop")

    def test_data_sync_clock_has_same_winner_requirement(self):
        for status in ("scheduled", "running"):
            with self.subTest(status=status):
                decision = decide_data_sync_lifecycle(
                    event=SimpleNamespace(status=status, race_datetime=NOW),
                    now=NOW + timedelta(hours=1),
                )
                self.assertEqual(decision.to_status, "running" if status == "scheduled" else "")
                self.assertGreater(decision.next_refresh_at, NOW + timedelta(hours=1))


class PriorityRoutingTests(SimpleTestCase):
    def test_control_consumable_despite_news_and_discovery_backlogs(self):
        from stable.test_race_coverage_queue import CoverageQueueTests
        with CoverageQueueTests().isolated_app() as (app, _):
            with app.connection_for_write() as connection:
                with connection.channel() as channel:
                    queues = {name: app.amqp.queues[name](channel)
                              for name in ("celery", "race_sync_v2", "race_control")}
                    for queue in queues.values():
                        queue.declare()
                    for name in ("celery", "race_sync_v2"):
                        for _ in range(10):
                            app.send_task("synthetic.slow", queue=name, connection=connection)
                    task = "stable.tasks.select_due_race_data_sync_task"
                    app.send_task(task, connection=connection)
                    message = queues["race_control"].get(no_ack=True)
                    self.assertIsNotNone(message)
                    self.assertEqual(message.headers["task"], task)
                    for name in ("celery", "race_sync_v2"):
                        self.assertEqual(queues[name].queue_declare(passive=True).message_count, 10)

    def test_unconfirmed_result_and_retry_use_reserved_workers(self):
        from stable.services.race_priority import claim_queue, retry_delay
        event = SimpleNamespace(status="finished", result_confirmed_at=None)
        claim = SimpleNamespace(data_kinds=("result",))
        self.assertEqual(claim_queue(claim=claim, event=event), "race_realtime")
        self.assertEqual(claim_queue(claim=claim, event=event, retry=True), "race_realtime_retry")
        event.result_confirmed_at = NOW
        self.assertEqual(claim_queue(claim=claim, event=event), "race_sync_v2")
        self.assertEqual(retry_delay(priority=True, reason="timeout"), timedelta(minutes=1))
        self.assertEqual(retry_delay(priority=True, reason="http_403"), timedelta(hours=1))

    def test_background_budget_retries_at_utc_reset(self):
        from stable.services.race_priority import retry_delay
        self.assertEqual(retry_delay(priority=False, reason="artifact_daily_requests_exceeded", now=NOW),
                         timedelta(hours=17))

    def test_redis_checks_retry_priority_before_any_normal_realtime_queue(self):
        from unittest.mock import Mock
        from kombu.transport.redis import Channel
        from kombu.utils.scheduling import priority_cycle
        from stable.services.race_priority import claim_priority
        claim = SimpleNamespace(data_kinds=("result",))
        event = SimpleNamespace(status="running", result_confirmed_at=None)
        normal = claim_priority(claim=claim, event=event, retry=False)
        retry = claim_priority(claim=claim, event=event, retry=True)
        self.assertLess(retry, normal)
        # 实际 Redis transport 生成的 BRPOP 顺序，包含最坏的队列顺序。
        channel = object.__new__(Channel)
        channel._active_queues = {"race_realtime", "race_realtime_retry"}
        channel.active_fanout_queues = set()
        channel._queue_cycle = priority_cycle(["race_realtime", "race_realtime_retry"])
        channel.priority_steps = [0, 3, 6, 9]
        channel.global_keyprefix = ""
        channel.client = Mock()
        channel._brpop_start(timeout=1)
        keys = channel.client.connection.send_command.call_args.args[1:-1]
        self.assertLess(keys.index(channel._q_for_pri("race_realtime_retry", retry)),
                        keys.index(channel._q_for_pri("race_realtime", normal)))

    def test_control_tasks_use_dedicated_queue(self):
        for task in (
            "select_due_race_data_sync_task", "scan_due_race_event_lifecycle_task",
            "advance_race_data_sync_lifecycle_task", "advance_race_event_lifecycle_task",
            "monitor_race_data_sync_result_slo_task",
        ):
            with self.subTest(task=task):
                self.assertEqual(settings.CELERY_TASK_ROUTES.get("stable.tasks." + task),
                                 {"queue": "race_control"})

    def test_beat_cannot_override_control_route(self):
        from app.settings import build_race_data_sync_beat_schedule
        schedule = build_race_data_sync_beat_schedule(scheduler_enabled=True, lifecycle_apply_enabled=True)
        for key in ("select-due-race-data-sync", "advance-race-data-sync-lifecycle", "monitor-race-data-sync-result-slo"):
            self.assertEqual(schedule[key]["options"]["queue"], "race_control")

    def test_sunday_rush_removed_but_regular_crawl_remains(self):
        self.assertNotIn("crawl-netkeiba-latest-sunday-rush", settings.CELERY_BEAT_SCHEDULE)
        self.assertNotIn("crawl-netkeiba-latest-sunday-rush-end", settings.CELERY_BEAT_SCHEDULE)
        self.assertTrue(any(v["task"] == "stable.tasks.crawl_netkeiba_latest"
                            for v in settings.CELERY_BEAT_SCHEDULE.values()))
