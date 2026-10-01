"""监控必须在新闻队列积压时仍能被已有赛事 worker 领取。"""
import os
from pathlib import Path
import runpy
from unittest.mock import patch

from celery import Celery
from django.test import SimpleTestCase


TASK = "stable.tasks.monitor_public_race_coverage_task"


class CoverageQueueTests(SimpleTestCase):
    def settings_snapshot(self):
        # 只加载代码配置，强制禁用 dotenv；不连接任何业务服务。
        with patch.dict(os.environ, {
            "DOTENV_DISABLED": "1",
            "RACE_DATA_COVERAGE_ALERTS_ENABLED": "true",
            "RACE_DATA_SYNC_ENABLED": "false",
            "RACE_DATA_SYNC_SCHEDULER_ENABLED": "false",
            "RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED": "false",
        }):
            return runpy.run_path(str(Path(__file__).parents[1] / "app/settings.py"))

    def assert_monitor_survives_news_backlog(self, *, from_beat):
        settings = self.settings_snapshot()
        app = Celery("coverage-queue-test", broker="memory://")
        app.conf.update(task_routes=settings["CELERY_TASK_ROUTES"])
        options = (
            settings["CELERY_BEAT_SCHEDULE"]["monitor-public-race-coverage"]["options"]
            if from_beat else {}
        )
        try:
            with app.connection_for_write() as connection:
                channel = connection.channel()
                news = app.amqp.queues["celery"](channel)
                race = app.amqp.queues["race_sync_v2"](channel)
                news.declare()
                race.declare()
                news.purge()
                race.purge()
                try:
                    for _ in range(100):
                        app.send_task("synthetic.slow_news", queue="celery", connection=connection)
                    app.send_task(TASK, connection=connection, **options)
                    # 现有赛事 worker 只领取 race_sync_v2，不应需要先清理新闻。
                    message = race.get(no_ack=True)
                    self.assertIsNotNone(message, "coverage is stranded behind ordinary news tasks")
                    self.assertEqual(message.headers["task"], TASK)
                    self.assertEqual(news.queue_declare(passive=True).message_count, 100)
                finally:
                    news.purge()
                    race.purge()
                    channel.close()
        finally:
            app.close()

    def test_beat_monitor_is_consumable_while_news_backlogged_and_writers_disabled(self):
        self.assert_monitor_survives_news_backlog(from_beat=True)

    def test_direct_monitor_dispatch_uses_the_same_isolated_queue(self):
        self.assert_monitor_survives_news_backlog(from_beat=False)
