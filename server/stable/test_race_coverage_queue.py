"""监控必须在新闻队列积压时仍能被已有赛事 worker 领取。"""
from contextlib import contextmanager
import os
from pathlib import Path
import runpy
from unittest.mock import patch

from celery import Celery
from django.test import SimpleTestCase
from kombu.transport import memory


TASK = "stable.tasks.monitor_public_race_coverage_task"


class CoverageQueueTests(SimpleTestCase):
    @contextmanager
    def isolated_app(self):
        env = {
            "RACE_DATA_COVERAGE_ALERTS_ENABLED": "true",
            "RACE_DATA_SYNC_ENABLED": "false",
            "RACE_DATA_SYNC_SCHEDULER_ENABLED": "false",
            "RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED": "false",
        }
        # 隔离贯穿配置加载、发布、消费和清理。dotenv 1.1.0 不识别
        # DOTENV_DISABLED；不能只设变量，也不能仅依赖 broker 构造参数。
        with (
            patch.dict(os.environ, env, clear=True),
            patch("dotenv.load_dotenv", return_value=False),
            patch("socket.socket.connect", side_effect=AssertionError("network forbidden")),
            patch.object(memory.Channel, "queues", {}),
            patch.object(memory.Transport, "global_state", type(memory.Transport.global_state)()),
        ):
            settings = runpy.run_path(str(Path(__file__).parents[1] / "app/settings.py"))
            app = Celery(
                "coverage-queue-test", broker="memory://", set_as_current=False
            )
            app.conf.update(task_routes=settings["CELERY_TASK_ROUTES"])
            try:
                yield app, settings
            finally:
                app.close()

    def test_external_broker_environment_cannot_escape_memory_transport(self):
        with patch.dict(os.environ, {
            "CELERY_BROKER_URL": "redis://synthetic.invalid:65530/15",
            "CELERY_BROKER_WRITE_URL": "redis://synthetic.invalid:65531/15",
        }):
            with self.isolated_app() as (app, _):
                with app.connection_for_write() as connection:
                    self.assertEqual(connection.transport.driver_type, "memory")

    def test_real_dotenv_loader_is_never_called(self):
        with patch("dotenv.load_dotenv", side_effect=AssertionError("dotenv forbidden")):
            with self.isolated_app():
                pass

    def assert_monitor_survives_news_backlog(self, *, from_beat):
        with self.isolated_app() as (app, settings):
            options = (
                settings["CELERY_BEAT_SCHEDULE"]["monitor-public-race-coverage"]["options"]
                if from_beat else {}
            )
            with app.connection_for_write() as connection:
                # 任何队列操作前先拒绝非内存传输；测试没有 purge 调用。
                self.assertEqual(connection.transport.driver_type, "memory")
                channel = connection.channel()
                try:
                    news = app.amqp.queues["celery"](channel)
                    race = app.amqp.queues["race_sync_v2"](channel)
                    news.declare()
                    race.declare()
                    for _ in range(100):
                        app.send_task("synthetic.slow_news", queue="celery", connection=connection)
                    app.send_task(TASK, connection=connection, **options)
                    message = race.get(no_ack=True)
                    self.assertIsNotNone(message, "coverage is stranded behind ordinary news tasks")
                    self.assertEqual(message.headers["task"], TASK)
                    self.assertEqual(news.queue_declare(passive=True).message_count, 100)
                finally:
                    channel.close()

    def test_beat_monitor_is_consumable_while_news_backlogged_and_writers_disabled(self):
        self.assert_monitor_survives_news_backlog(from_beat=True)

    def test_direct_monitor_dispatch_uses_the_same_isolated_queue(self):
        self.assert_monitor_survives_news_backlog(from_beat=False)
