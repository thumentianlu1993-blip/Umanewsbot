"""H01 real-PG diagnostics: default Django tests, never opt-in or skipped.

Only an isolated PostgreSQL 16 test database inside a network-none Linux
container is accepted. All identities and records below are synthetic.
"""
import contextlib
from datetime import date, datetime, timezone
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import time
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as PgConnection, cursor as PgCursor, make_dsn
from django.db import connection, connections
from django.test import TransactionTestCase

from scripts import h01_readonly_count as reader
from stable import models

IMPLEMENTATION_SHA = "4e86466fff0e607d00c4cb8e63cb30c93d1b697b"
NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)


class RecordingCursor:
    def __init__(self, raw, owner):
        self.raw, self.owner = raw, owner

    def execute(self, query, params=None):
        self.owner.statements.append(query)
        if self.owner.before:
            query, params = self.owner.before(query, params)
        try:
            value = self.raw.execute(query, params)
        except psycopg2.Error as error:
            self.owner.error_codes.append(error.pgcode)
            raise
        if self.owner.after:
            self.owner.after(query, params)
        return value

    def fetchmany(self, count):
        return self.raw.fetchmany(count)

    def close(self):
        self.raw.close()


class RecordingConnection:
    def __init__(self, raw, *, before=None, after=None):
        self.raw, self.before, self.after = raw, before, after
        self.pid = raw.get_backend_pid()
        self.statements, self.error_codes = [], []

    def set_session(self, **kwargs):
        self.raw.set_session(**kwargs)

    def cursor(self):
        return RecordingCursor(self.raw.cursor(), self)

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def _observe_backend(params, application, expected_user, channel):
    """Own libpq connection, created after fork; no inherited driver is used."""
    result = dict(seen_active=False, pid=None, query_stopped_at=None,
                  disappeared_at=None, locks_after=None, identity_matches=False)
    database = None
    try:
        database = psycopg2.connect(**params, application_name="h01-observer-" + uuid4().hex)
        database.autocommit = True
        with database.cursor() as cursor:
            cursor.execute("SET statement_timeout = 1000")
            channel.send({"ready": True})
            until = time.monotonic() + 8
            while time.monotonic() < until:
                query = "SELECT pid,datname,usename,state,query,xact_start FROM pg_stat_activity "
                if result["pid"] is None:
                    cursor.execute(query + "WHERE application_name=%s AND pid<>pg_backend_pid()", (application,))
                else:
                    cursor.execute(query + "WHERE pid=%s", (result["pid"],))
                rows = cursor.fetchall()
                if len(rows) > 1:
                    raise AssertionError("ambiguous local backend")
                if rows:
                    pid, dbname, username, state, query, transaction_started = rows[0]
                    if state == "active" and "pg_sleep" in query and transaction_started:
                        result.update(seen_active=True, pid=pid,
                                      identity_matches=dbname == params["dbname"] and username == expected_user)
                        cursor.execute("SELECT count(*) FROM pg_locks WHERE pid=%s AND granted", (pid,))
                        result["locks_before"] = cursor.fetchone()[0]
                        if "active_at" not in result:
                            result["active_at"] = time.monotonic()
                            channel.send({"active_observation": {key: result[key] for key in
                                          ("pid", "identity_matches", "active_at", "locks_before")}})
                    elif result["seen_active"] and result["query_stopped_at"] is None:
                        result["query_stopped_at"] = time.monotonic()
                elif result["seen_active"]:
                    result["disappeared_at"] = time.monotonic()
                    if result["query_stopped_at"] is None:
                        result["query_stopped_at"] = result["disappeared_at"]
                    cursor.execute("SELECT count(*) FROM pg_locks WHERE pid=%s", (result["pid"],))
                    result["locks_after"] = cursor.fetchone()[0]
                    break
                time.sleep(0.02)
        channel.send(result)
    except BaseException:
        channel.send({"observer_failed": True})
    finally:
        if database is not None:
            database.close()
        channel.close()


class BlockingSchemaCursor(PgCursor):
    def execute(self, query, params=None):
        if query == reader.SCHEMA_SQL:
            # Still uses the reader's real server-side timeout. The extra driver
            # block ensures CLI success cannot come from natural query completion.
            try:
                return super().execute("SELECT pg_sleep(10)")
            finally:
                time.sleep(10)
        return super().execute(query, params)


class BlockingSchemaConnection(PgConnection):
    def cursor(self, *args, **kwargs):
        kwargs["cursor_factory"] = BlockingSchemaCursor
        return super().cursor(*args, **kwargs)


class H01CountPostgresTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        if connection.vendor != "postgresql":
            raise RuntimeError("H01 requires actual PostgreSQL; no skip/dummy fallback")
        if not Path("/sys/class/net").exists() or set(os.listdir("/sys/class/net")) != {"lo"}:
            raise RuntimeError("H01 requires a network-none Linux container")
        if os.getuid() == 0 or Path("/var/run/docker.sock").exists():
            raise RuntimeError("H01 requires a non-root container without Docker socket")
        super().setUpClass()

    def setUp(self):
        configured = connection.get_connection_params()
        self.params = {key: configured[key] for key in ("dbname", "user", "password", "host", "port") if key in configured}
        if (self.params.get("host") != "127.0.0.1" or self.params.get("dbname") != "test_bounded_ci"
                or self.params.get("user") != "bounded_ci" or str(self.params.get("port")) != "5432"):
            raise RuntimeError("H01 requires the dedicated local test_bounded_ci database")
        self.params.update(connect_timeout=2, sslmode="disable")
        self.role = "h01_reader_" + uuid4().hex
        self.apps, self.processes = [], []
        self.public_create = False
        self.role_created = False
        self.started_at = time.monotonic()
        self.addCleanup(self._check_case_budget)
        self.addCleanup(self._cleanup_role)
        self.addCleanup(self._cleanup_processes)
        with self._database() as database, database.cursor() as cursor:
            cursor.execute("SELECT current_database(),current_user,current_setting('server_version_num')::int")
            dbname, username, version = cursor.fetchone()
            self.assertEqual(dbname, "test_bounded_ci")
            self.assertEqual(username, self.params["user"])
            self.assertTrue(160000 <= version < 170000)
            cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace n, "
                           "LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a "
                           "WHERE n.nspname='public' AND a.grantee=0 AND a.privilege_type='CREATE')")
            self.public_create = cursor.fetchone()[0]
            self.schema_acl = self._schema_acl(cursor)
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT").format(sql.Identifier(self.role)))
            self.role_created = True
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(self.role)))
            for table in reader.COLUMNS:
                cursor.execute(sql.SQL("GRANT SELECT ON TABLE public.{} TO {}").format(
                    sql.Identifier("stable_" + table), sql.Identifier(self.role)))

    @contextlib.contextmanager
    def _database(self, *, read_role=False, application=None, autocommit=True):
        params = {**self.params, "user": self.role if read_role else self.params["user"]}
        if application:
            params["application_name"] = application
        database = psycopg2.connect(**params)
        database.autocommit = autocommit
        try:
            if autocommit:
                with database.cursor() as cursor:
                    cursor.execute("SET statement_timeout = 1000")
                    cursor.execute("SET lock_timeout = 250")
            yield database
        finally:
            if not database.closed:
                database.rollback()
                database.close()

    def _check_case_budget(self):
        self.assertLess(time.monotonic() - self.started_at, 15, "PG case exceeded its diagnostic budget")

    @staticmethod
    def _schema_acl(cursor):
        cursor.execute("SELECT a.grantee,a.grantor,a.privilege_type,a.is_grantable "
                       "FROM pg_namespace n, "
                       "LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a "
                       "WHERE n.nspname='public' ORDER BY 1,2,3,4")
        return cursor.fetchall()

    def _cleanup_role(self):
        try:
            if self.role_created:
                with self._database() as database, database.cursor() as cursor:
                    cursor.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(self.role)))
                    cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(self.role)))
        finally:
            if self.public_create:
                with self._database() as database, database.cursor() as cursor:
                    cursor.execute("GRANT CREATE ON SCHEMA public TO PUBLIC")
            with self._database() as independent, independent.cursor() as cursor:
                cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace n, "
                               "LATERAL aclexplode(COALESCE(n.nspacl,acldefault('n',n.nspowner))) a "
                               "WHERE n.nspname='public' AND a.grantee=0 AND a.privilege_type='CREATE')")
                self.assertEqual(cursor.fetchone()[0], self.public_create)
                self.assertEqual(self._schema_acl(cursor), self.schema_acl)

    def _cleanup_processes(self):
        for process, channel in self.processes:
            if process.is_alive():
                process.kill()
            process.join(timeout=1)
            self.assertFalse(process.is_alive(), "local observer survived cleanup")
            channel.close()
            process.close()
        # A lingering server-side backend is a failure, even if admin cleanup
        # succeeds. Termination never retroactively turns that failure into PASS.
        if self.apps:
            with self._database() as database, database.cursor() as cursor:
                cursor.execute("SELECT pid FROM pg_stat_activity WHERE application_name=ANY(%s)", (self.apps,))
                pids = [row[0] for row in cursor.fetchall()]
                for pid in pids:
                    cursor.execute("SELECT pg_terminate_backend(%s)", (pid,))
                self.assertEqual(pids, [], "local backend required emergency cleanup")

    def _event(self, name, day=date(2026, 10, 3), region="japan"):
        return models.RaceEvent.objects.create(
            year=day.year if day else 2026, slug="h01-" + name, original_name="Synthetic " + name,
            chinese_name="Synthetic " + name, country_region=region, local_date=day,
            racecourse="Synthetic", grade_text="G1", normalized_grade="G1", surface="turf")

    def _profile(self, name, *, published=None, hidden=None):
        term = models.TermEntry.objects.create(source_ja="Synthetic " + name, term_type="horse")
        return models.HorseProfile.objects.create(primary_term=term, original_name="Synthetic " + name,
                                                  published_at=published, hidden_at=hidden)

    def _seed(self):
        days = [date(2019, 12, 31), date(2020, 1, 1), date(2023, 10, 2), date(2023, 10, 3),
                date(2026, 10, 3), date(2026, 11, 2), date(2026, 11, 3), None]
        events = [self._event(str(index), day) for index, day in enumerate(days)]
        for region in reader.REGIONS[1:]:
            self._event(region, region=region)
        profiles = [self._profile("p1", published=NOW), self._profile("p2"),
                    self._profile("p3", published=NOW, hidden=NOW), self._profile("p4", hidden=NOW),
                    self._profile("record-only"), self._profile("excluded-record"), self._profile("news-only")]
        for index, profile in enumerate([profiles[0], profiles[0], profiles[1], profiles[2], profiles[3], None]):
            models.RaceEventParticipant.objects.create(event=events[1], stable_key="p" + str(index),
                                                       canonical_name="Synthetic", horse_profile=profile)
        for index, (profile, day, precision, start) in enumerate([
            (profiles[0], date(2023, 10, 3), "exact", "started"),
            (profiles[4], date(2026, 10, 3), "exact", "started"),
            (profiles[5], date(2023, 10, 2), "exact", "started"),
            (profiles[5], date(2026, 10, 3), "month", "started"),
            (profiles[5], date(2026, 10, 3), "exact", "unconfirmed"),
        ]):
            models.HorseRaceRecord.objects.create(horse_profile=profile, race_name="Synthetic",
                race_date=day, race_region="japan", race_date_precision=precision, start_status=start,
                idempotency_key="h01-record-" + str(index))
        for index in range(2):
            models.HorseExternalIdentity.objects.create(horse_profile=profiles[index], source="netkeiba",
                namespace="h01", external_id="h01-" + str(index), status="observed")
            models.ExternalHorse.objects.create(source="netkeiba", horse_id="h01-" + str(index))
            models.RaceEventRunner.objects.create(event=events[1], horse_name="Synthetic", external_runner_id="legacy-" + str(index))
        models.RaceEventResult.objects.create(event=events[1], horse_name="Synthetic", finish_position=1)
        news = [(datetime(2026, 7, 4, 15, 59, tzinfo=timezone.utc), False, "auto"),
                (datetime(2026, 7, 4, 16, tzinfo=timezone.utc), False, "auto"),
                (datetime(2026, 10, 3, 15, 59, tzinfo=timezone.utc), False, "auto"),
                (datetime(2026, 10, 3, 16, tzinfo=timezone.utc), False, "auto"),
                (datetime(2026, 7, 4, 16, tzinfo=timezone.utc), True, "auto"),
                (datetime(2026, 7, 4, 16, tzinfo=timezone.utc), False, "candidate")]
        for index, (published, withdrawn, status) in enumerate(news):
            article = models.NewsArticle.objects.create(source_site="netkeiba", source_mode="html", source_article_id="h01-" + str(index),
                title_ja="Synthetic", published_at=published, published_to_web_at=published,
                withdrawn_at=NOW if withdrawn else None, source_url="https://fixture.invalid/" + str(index))
            models.ArticleHorseLink.objects.create(horse_profile=profiles[0], article=article, status=status)
        models.ArticleHorseLink.objects.create(horse_profile=profiles[6], article=article, status="manual")
        return events, profiles

    def _read(self, *, before=None, after=None, seconds=10):
        application = "h01-count-" + uuid4().hex
        self.apps.append(application)
        raw = psycopg2.connect(**{**self.params, "user": self.role}, application_name=application)
        tracked = RecordingConnection(raw, before=before, after=after)
        result = reader.run_counts(tracked, revision=IMPLEMENTATION_SHA, deadline=time.monotonic() + seconds)
        self.assertTrue(raw.closed)
        with self._database() as observer, observer.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE pid=%s", (tracked.pid,))
            self.assertEqual(cursor.fetchone()[0], 0)
        return result, tracked

    def _observe(self, application, expected_user):
        connections.close_all()
        receiver, sender = multiprocessing.get_context("fork").Pipe(duplex=False)
        process = multiprocessing.get_context("fork").Process(
            target=_observe_backend, args=(self.params, application, expected_user, sender))
        process.start()
        sender.close()
        self.processes.append((process, receiver))
        self.apps.append(application)
        self.assertTrue(receiver.poll(2), "observer was not ready")
        self.assertEqual(receiver.recv(), {"ready": True})
        return process, receiver

    def _check_observation(self, process, receiver, deadline):
        self.assertTrue(receiver.poll(0.5), "observer never reported a real active backend")
        first = receiver.recv()
        self.assertIn("active_observation", first)
        print("H01_PG_ACTIVE " + json.dumps(first["active_observation"], sort_keys=True))
        self.assertTrue(receiver.poll(3), "backend did not disappear in observation window")
        result = receiver.recv()
        process.join(timeout=0.5)
        self.assertFalse(process.is_alive())
        self.assertTrue(result.get("seen_active"), "observer never saw a real active query")
        self.assertTrue(result.get("identity_matches"))
        self.assertGreater(result.get("locks_before", 0), 0)
        self.assertIsNotNone(result.get("disappeared_at"))
        self.assertLessEqual(result["disappeared_at"], deadline + 3)
        self.assertEqual(result["locks_after"], 0)
        print("H01_PG_OBSERVER " + json.dumps(result, sort_keys=True))
        return result

    def test_fixed_templates_aggregates_and_select_role(self):
        self._seed()
        result, tracked = self._read()
        self.assertEqual(result["status"], "capacity_preflight_finished")
        self.assertEqual(result["selects"], 12)
        self.assertFalse(result["inventory_complete"])
        rows = {entry["name"]: entry["rows"] for entry in result["queries"]}
        self.assertEqual(len(rows["schema"]), 19)
        self.assertTrue(all(row[1] is True for row in rows["schema"]))
        self.assertEqual(rows["snapshot"][0][1:3], ("on", "repeatable read"))
        self.assertIn(("japan", "G1", 6, 1), rows["event_counts"])
        for region in reader.REGIONS[1:]:
            self.assertIn((region, "G1", 1, 0), rows["event_counts"])
        self.assertIn(("japan", 6, 1), rows["roster_rows"])
        self.assertIn(("japan", 2), rows["legacy_runner_rows"])
        self.assertIn(("japan", 1), rows["legacy_result_rows"])
        self.assertEqual(rows["identity_states"], [("observed", 2)])
        self.assertEqual(sum(row[2] for row in rows["profile_states"]), 5)
        self.assertEqual(sum(row[3] for row in rows["profile_states"]), 1)
        self.assertEqual(rows["staging_source_id_candidates"], [("netkeiba", 2)])
        self.assertEqual(rows["recent_news_links"], [("auto", 2), ("candidate", 1)])
        self.assertEqual(tracked.error_codes, [])
        with self._database(read_role=True) as database, database.cursor() as cursor:
            cursor.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolinherit FROM pg_roles WHERE rolname=current_user")
            self.assertEqual(cursor.fetchone(), (False, False, False, False))
            for table in reader.COLUMNS:
                cursor.execute("SELECT has_table_privilege(current_user,%s,'SELECT'), "
                               "has_table_privilege(current_user,%s,'INSERT,UPDATE,DELETE,TRUNCATE')",
                               ("public.stable_" + table, "public.stable_" + table))
                self.assertEqual(cursor.fetchone(), (True, False))
            cursor.execute("SELECT has_schema_privilege(current_user,'public','CREATE')")
            self.assertFalse(cursor.fetchone()[0])
            for statement in ("INSERT INTO public.stable_raceevent DEFAULT VALUES",
                              "UPDATE public.stable_raceevent SET chinese_name=chinese_name WHERE false",
                              "DELETE FROM public.stable_raceevent WHERE false",
                              "CREATE TABLE public.h01_forbidden(id int)"):
                with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                    cursor.execute(statement)

    def test_repeatable_read_does_not_see_later_commit(self):
        event = self._event("snapshot")
        timeouts = []
        raw_holder = {}
        def after(query, params):
            if query == reader.QUERIES[1][1]:
                with raw_holder["raw"].cursor() as cursor:
                    cursor.execute("SELECT current_setting('statement_timeout'),current_setting('lock_timeout'),current_setting('idle_in_transaction_session_timeout')")
                    timeouts.append(cursor.fetchone())
                with self._database() as writer, writer.cursor() as cursor:
                    cursor.execute("UPDATE public.stable_raceevent SET local_date=DATE '2026-11-03' WHERE id=%s", (event.pk,))
        original = RecordingConnection.__init__
        def record(instance, raw, **kwargs):
            raw_holder["raw"] = raw
            original(instance, raw, **kwargs)
        with patch.object(RecordingConnection, "__init__", record):
            result, _ = self._read(after=after, seconds=2)
        self.assertEqual(result["status"], "capacity_preflight_finished")
        counts = next(entry["rows"] for entry in result["queries"] if entry["name"] == "event_counts")
        self.assertEqual(counts, [("japan", "G1", 1, 0)])
        self.assertEqual(models.RaceEvent.objects.get(pk=event.pk).local_date, date(2026, 11, 3))
        self.assertEqual(len(timeouts), 1)
        self.assertEqual(timeouts[0][1], "250ms")
        for value in (timeouts[0][0], timeouts[0][2]):
            self.assertTrue(value.endswith("ms"))
            self.assertTrue(0 < int(value[:-2]) <= 2000)

    def test_schema_mismatch_and_service_timeouts_fail_closed(self):
        event = self._event("faults")
        with self._database() as administrator, administrator.cursor() as cursor:
            cursor.execute("ALTER TABLE public.stable_raceevent RENAME COLUMN timezone_name TO h01_renamed_timezone")
        try:
            result, tracked = self._read()
            self.assertEqual((result["status"], result["reason"], result["selects"]), ("partial", "schema_mismatch", 1))
            self.assertEqual(result["queries"], [])
            self.assertEqual([query for query in tracked.statements if query.startswith("SELECT") or query.startswith("WITH")], [reader.SCHEMA_SQL])
        finally:
            with self._database() as administrator, administrator.cursor() as cursor:
                cursor.execute("ALTER TABLE public.stable_raceevent RENAME COLUMN h01_renamed_timezone TO timezone_name")
            with self._database() as independent, independent.cursor() as cursor:
                cursor.execute(reader.SCHEMA_SQL)
                restored = cursor.fetchall()
                self.assertEqual(len(restored), 19)
                self.assertTrue(all(row[1] is True for row in restored))
            self.assertEqual(models.RaceEvent.objects.get(pk=event.pk).chinese_name, "Synthetic faults")
        with self._database(autocommit=False) as blocker, blocker.cursor() as cursor:
            cursor.execute("LOCK TABLE public.stable_raceevent IN ACCESS EXCLUSIVE MODE")
            started = time.monotonic()
            result, tracked = self._read()
            self.assertEqual(result["reason"], "database_or_input_error")
            self.assertIn("55P03", tracked.error_codes)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertLess(result["selects"], 12)
        target_sql = next(query for name, query, _ in reader.QUERIES if name == "event_counts")
        def sleep_statement(query, params):
            return ("SELECT pg_sleep(2)", None) if query == target_sql else (query, params)
        started = time.monotonic()
        result, tracked = self._read(before=sleep_statement, seconds=0.4)
        self.assertEqual(result["status"], "partial")
        self.assertIn("57014", tracked.error_codes)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertLess(result["selects"], 12)

    def test_cli_deadline_stops_active_backend(self):
        application = "h01-cli-" + uuid4().hex
        process, receiver = self._observe(application, self.role)
        original_connect = psycopg2.connect
        def connect(*args, **kwargs):
            kwargs["connection_factory"] = BlockingSchemaConnection
            return original_connect(*args, **kwargs)
        dsn = make_dsn(**{**self.params, "user": self.role, "application_name": application})
        digest = hashlib.sha256(Path(reader.__file__).read_bytes()).hexdigest()
        started = time.monotonic()
        deadline = started + 1.5
        with patch.object(reader, "MAX_SECONDS", 1.5), patch.object(psycopg2, "connect", connect), \
                patch.dict(os.environ, {"H01_READONLY_DSN": dsn}), contextlib.redirect_stdout(io.StringIO()) as output:
            status = reader.main(["--execute", "--revision", IMPLEMENTATION_SHA, "--expected-tool-sha256", digest])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue())["reason"], "wall_time")
        self.assertLess(time.monotonic() - started, 2)
        self._check_observation(process, receiver, deadline)

    def test_killed_local_transaction_rolls_back(self):
        event = self._event("rollback")
        # Control: an explicit rollback must also restore the same synthetic row.
        with self._database(autocommit=False) as control, control.cursor() as cursor:
            cursor.execute("UPDATE public.stable_raceevent SET chinese_name='Rollback control' WHERE id=%s", (event.pk,))
        with self._database() as independent, independent.cursor() as cursor:
            cursor.execute("SELECT chinese_name FROM public.stable_raceevent WHERE id=%s", (event.pk,))
            self.assertEqual(cursor.fetchone()[0], "Synthetic rollback")
        application = "h01-rollback-" + uuid4().hex
        process, receiver = self._observe(application, self.params["user"])
        def write_without_commit():
            database = psycopg2.connect(**self.params, application_name=application)
            with database.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = 1000")
                cursor.execute("SET LOCAL idle_in_transaction_session_timeout = 1000")
                cursor.execute("UPDATE public.stable_raceevent SET chinese_name='Uncommitted synthetic' WHERE id=%s", (event.pk,))
                try:
                    cursor.execute("SELECT pg_sleep(10)")
                finally:
                    time.sleep(10)
        started = time.monotonic()
        deadline = started + 1.5
        result = reader._bounded_worker(write_without_commit, deadline=deadline)
        self.assertEqual(result["reason"], "wall_time")
        self.assertLess(time.monotonic() - started, 2)
        self._check_observation(process, receiver, deadline)
        with self._database() as independent, independent.cursor() as cursor:
            cursor.execute("SELECT chinese_name FROM public.stable_raceevent WHERE id=%s", (event.pk,))
            self.assertEqual(cursor.fetchone()[0], "Synthetic rollback")
