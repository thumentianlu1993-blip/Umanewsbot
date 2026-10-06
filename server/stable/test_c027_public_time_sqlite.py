"""公开时间表达式在新SQLite连接上的真实编译/执行回归；无项目数据库。"""
import unittest
from django.db.backends.sqlite3.base import DatabaseWrapper
from stable.models import RaceEvent
from stable.services.race_public_time import annotate_public_time


class PublicTimeFreshSqliteConnectionTests(unittest.TestCase):
    def test_cold_connection_compiles_and_preserves_known_and_unknown_clock(self):
        db = DatabaseWrapper(dict(ENGINE="django.db.backends.sqlite3", NAME=":memory:",
            TIME_ZONE=None, AUTOCOMMIT=True, ATOMIC_REQUESTS=False, CONN_MAX_AGE=0,
            CONN_HEALTH_CHECKS=False, OPTIONS={}, TEST={}), alias="c027-isolated-sqlite")
        try:
            self.assertIsNone(db.connection)
            query = annotate_public_time(RaceEvent.objects.all()).order_by("pk").values_list(
                "public_date", "public_start_time", "public_instant").query
            sql, params = query.get_compiler(connection=db).as_sql()
            with db.cursor() as cursor:
                cursor.execute("CREATE TABLE stable_raceevent (id integer, race_datetime text, local_date text, local_start_time text, timezone_name text)")
                cursor.execute("INSERT INTO stable_raceevent VALUES (1,NULL,'2026-10-10',NULL,'Europe/Berlin')")
                cursor.execute("INSERT INTO stable_raceevent VALUES (2,'2026-10-10 06:30:00','2026-10-10','14:30:00','Asia/Shanghai')")
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            self.assertEqual(rows[0], ("2026-10-10", None, None))
            self.assertEqual(rows[1], ("2026-10-10", "14:30:00", "2026-10-10 06:30:00"))
        finally:
            db.close()
