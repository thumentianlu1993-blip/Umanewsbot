"""Real persisted R07 caller contracts; no ORM or reconciliation mocks."""
from dataclasses import FrozenInstanceError
from io import StringIO
import hashlib
import json
from threading import Event, Thread
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections, transaction
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from stable import models as m
from stable.services.race_result_roster_orm import load_persisted_roster_reconciliation


# Authored from the independent literal fixture specification, before adapter code.
DIGEST = "8740c6b5eb371f1ce59281158f55900ec73cd09751116e9eccefa7349cb2aead"
SCOPE = "r07:event:101:racecard:201:result:202:sha256:" + DIGEST
ROSTER = "db:racecard-revision:201:sha256:" + DIGEST


# Independent complete literals; fixed digests were sealed before these fixture edits.
CARD_HASH_MATERIAL = {'event_id': 101,
 'revisions': [{'id': 211,
                'event_id': 101,
                'kind': 'racecard',
                'phase': 'racecard',
                'content_sha256': 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd'},
               {'id': 202,
                'event_id': 101,
                'kind': 'result',
                'phase': 'provisional',
                'content_sha256': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'}],
 'racecard_items': [{'id': 411,
                     'revision_id': 211,
                     'participant_id': 301,
                     'status': 'declared',
                     'reported_finish_position': None},
                    {'id': 412,
                     'revision_id': 211,
                     'participant_id': 302,
                     'status': 'declared',
                     'reported_finish_position': None},
                    {'id': 413,
                     'revision_id': 211,
                     'participant_id': 303,
                     'status': 'declared',
                     'reported_finish_position': None}],
 'result_items': [{'id': 404,
                   'revision_id': 202,
                   'participant_id': 301,
                   'status': 'finished',
                   'reported_finish_position': 1},
                  {'id': 405,
                   'revision_id': 202,
                   'participant_id': 302,
                   'status': 'non_runner',
                   'reported_finish_position': None}],
 'participants': [{'id': 301, 'event_id': 101, 'stable_key': 'p:301'},
                  {'id': 302, 'event_id': 101, 'stable_key': 'p:302'},
                  {'id': 303, 'event_id': 101, 'stable_key': 'p:303'}]}
CARD_HASH_DIGEST = '3a5654edea8b87552a477b8c93697efa3cb87fb4879a3a149c5251bf187ae48b'

RESULT_PHASE_MATERIAL = {'event_id': 101,
 'revisions': [{'id': 201,
                'event_id': 101,
                'kind': 'racecard',
                'phase': 'racecard',
                'content_sha256': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'},
               {'id': 212,
                'event_id': 101,
                'kind': 'result',
                'phase': 'official',
                'content_sha256': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'}],
 'racecard_items': [{'id': 401,
                     'revision_id': 201,
                     'participant_id': 301,
                     'status': 'declared',
                     'reported_finish_position': None},
                    {'id': 402,
                     'revision_id': 201,
                     'participant_id': 302,
                     'status': 'declared',
                     'reported_finish_position': None},
                    {'id': 403,
                     'revision_id': 201,
                     'participant_id': 303,
                     'status': 'declared',
                     'reported_finish_position': None}],
 'result_items': [{'id': 414,
                   'revision_id': 212,
                   'participant_id': 301,
                   'status': 'finished',
                   'reported_finish_position': 1},
                  {'id': 415,
                   'revision_id': 212,
                   'participant_id': 302,
                   'status': 'non_runner',
                   'reported_finish_position': None}],
 'participants': [{'id': 301, 'event_id': 101, 'stable_key': 'p:301'},
                  {'id': 302, 'event_id': 101, 'stable_key': 'p:302'},
                  {'id': 303, 'event_id': 101, 'stable_key': 'p:303'}]}
RESULT_PHASE_DIGEST = '11cdb6e9770f118390ce863f51c73cf20b5adc8eb81148d5b32b8b797d4a53ec'



def expected_envelope():
    return {
        "schema_version": 1, "event_id": 101, "racecard_revision_id": 201,
        "result_revision_id": 202, "material_sha256": DIGEST,
        "participant_bindings": [
            {"participant_id": 301, "stable_key": "p:301", "racecard_item_id": 401},
            {"participant_id": 302, "stable_key": "p:302", "racecard_item_id": 402},
            {"participant_id": 303, "stable_key": "p:303", "racecard_item_id": 403},
        ],
        "diagnostics": ["participation_provenance_unavailable"],
        "ledger": {
            "scope_ref": SCOPE, "roster_ref": ROSTER,
            "ledger": [
                {"runner_id": 301, "start_status": "unconfirmed", "outcome_status": "finished",
                 "reported_finish_position": 1, "roster_ref": ROSTER, "participation_ref": None,
                 "result_ref": "db:revision-item:404", "reasons": ["participation_missing", "terminal_result"]},
                {"runner_id": 302, "start_status": "unconfirmed", "outcome_status": "non_runner",
                 "reported_finish_position": None, "roster_ref": ROSTER, "participation_ref": None,
                 "result_ref": "db:revision-item:405", "reasons": ["participation_missing", "nonstarter_result_start_unconfirmed"]},
                {"runner_id": 303, "start_status": "unconfirmed", "outcome_status": None,
                 "reported_finish_position": None, "roster_ref": ROSTER, "participation_ref": None,
                 "result_ref": None, "reasons": ["participation_missing", "result_missing"]},
            ], "unexpected_rows": [], "started_ids": [], "did_not_start_ids": [],
            "unconfirmed_start_ids": [301, 302, 303], "unresolved_result_ids": [303],
            "unexpected_ids": [], "conflict_ids": [],
        },
    }


class PersistedRosterInputTests(SimpleTestCase):
    def test_invalid_ids_fail_before_any_database_query(self):
        for key in ("event_id", "racecard_revision_id", "result_revision_id"):
            for value in (True, False, 0, -1, "101", 1.0, None):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    load_persisted_roster_reconciliation(**(
                        {"event_id": 101, "racecard_revision_id": 201, "result_revision_id": 202} | {key: value}))


class PersistedRosterPostgresTests(TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql", "Use the allocated isolated PostgreSQL runner")
        self.event = m.RaceEvent.objects.create(pk=101, year=2026, slug="a114-fixture",
            original_name="Local R07 Fixture", country_region="japan", racecourse="Tokyo")
        self.card = m.RaceEventRevision.objects.create(pk=201, event=self.event, kind="racecard",
            revision_no=1, phase="racecard", content_sha256="a" * 64)
        self.result = m.RaceEventRevision.objects.create(pk=202, event=self.event, kind="result",
            revision_no=1, phase="provisional", content_sha256="b" * 64)
        for pk in (301, 302, 303):
            m.RaceEventParticipant.objects.create(pk=pk, event=self.event, stable_key=f"p:{pk}", canonical_name="Same Name")
        for pk, participant, order in ((401, 301, 1), (402, 302, 2), (403, 303, 3)):
            m.RaceEventRevisionItem.objects.create(pk=pk, revision=self.card, participant_id=participant,
                internal_order=order, status="declared")
        m.RaceEventRevisionItem.objects.create(pk=404, revision=self.result, participant_id=301,
            internal_order=1, status="finished", reported_finish_position=1)
        m.RaceEventRevisionItem.objects.create(pk=405, revision=self.result, participant_id=302,
            internal_order=2, status="non_runner")

    def load(self, **changes):
        return load_persisted_roster_reconciliation(**(
            {"event_id": 101, "racecard_revision_id": 201, "result_revision_id": 202} | changes))

    def command(self, *args, **options):
        output = StringIO()
        call_command("audit_race_data_sync", "--roster-event-id", "101", "--racecard-revision-id", "201",
                     "--result-revision-id", "202", *args, stdout=output, **options)
        return json.loads(output.getvalue())

    def state(self):
        return tuple((model.__name__, tuple(model.objects.order_by("pk").values_list())) for model in (
            m.RaceEvent, m.RaceEventRevision, m.RaceEventRevisionItem, m.RaceEventParticipant,
            m.RaceEventRunner, m.RaceEventResult, m.HorseRaceRecord, m.RaceEventProjectionControl))

    def test_real_command_exact_literal_envelope_and_zero_business_write(self):
        before = self.state()
        with CaptureQueriesContext(connection) as queries:
            report = self.command()
        self.assertEqual(report, expected_envelope())
        self.assertEqual(self.state(), before)
        self.assertTrue(any("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in q["sql"] for q in queries))
        self.assertFalse(any(q["sql"].lstrip().upper().startswith(("INSERT ", "UPDATE ", "DELETE ", "REPLACE ")) for q in queries))
        self.assertNotIn("raw_payload", json.dumps(report))
        self.assertEqual(set(report), {"schema_version", "event_id", "racecard_revision_id", "result_revision_id",
                                      "material_sha256", "participant_bindings", "diagnostics", "ledger"})

    def test_first_business_query_runs_repeatable_read_read_only(self):
        observed = []
        def inspect(execute, sql, params, many, context):
            if not observed and sql.lstrip().upper().startswith("SELECT "):
                observed.append("reading")
                with connection.cursor() as cursor:
                    cursor.execute("SHOW transaction_isolation")
                    isolation = cursor.fetchone()[0]
                    cursor.execute("SHOW transaction_read_only")
                    read_only = cursor.fetchone()[0]
                observed[:] = [(isolation, read_only)]
            return execute(sql, params, many, context)
        with connection.execute_wrapper(inspect):
            self.assertEqual(self.command(), expected_envelope())
        self.assertEqual(observed, [("repeatable read", "on")])
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            self.assertEqual(cursor.fetchone()[0], "off")
            cursor.execute("SHOW transaction_isolation")
            self.assertEqual(cursor.fetchone()[0], "read committed")

    def test_rejects_outer_transaction_non_autocommit_and_wrong_backend(self):
        with transaction.atomic(), self.assertRaises(ValueError):
            self.load()
        connection.set_autocommit(False)
        try:
            with self.assertRaises(ValueError):
                self.load()
        finally:
            connection.rollback()
            connection.set_autocommit(True)
        # Only backend metadata is replaced to test the guard; no ORM/core is mocked.
        with patch.object(connection, "vendor", "sqlite"), CaptureQueriesContext(connection) as queries:
            with self.assertRaises(ValueError):
                self.load()
        self.assertEqual(len(queries), 0)

    def test_historical_selected_pair_ignores_current_control_pointer(self):
        newer = m.RaceEventRevision.objects.create(event=self.event, kind="result", revision_no=2,
                                                   phase="official", content_sha256="c" * 64)
        m.RaceEventRevisionItem.objects.create(revision=newer, participant_id=303,
                                              internal_order=1, status="finished", reported_finish_position=99)
        control = m.RaceEventProjectionControl.objects.create(
            event=self.event, current_result_revision=newer,
            next_result_revision_no=newer.revision_no + 1)
        control.refresh_from_db()
        self.assertEqual(control.current_result_revision_id, newer.pk)
        self.assertEqual(control.next_result_revision_no, 3)
        self.assertEqual(self.command(), expected_envelope())

    def test_horse_record_explicit_or_derived_start_is_never_a_participation_producer(self):
        term = m.TermEntry.objects.create(term_type="horse", source_ja="A114 Control")
        profile = m.HorseProfile.objects.create(primary_term=term, original_name="Same Name")
        m.RaceEventParticipant.objects.filter(pk=301).update(horse_profile=profile)
        m.HorseRaceRecord.objects.create(event=self.event, horse_profile=profile, race_name="Local R07 Fixture",
            start_status="started", result_status="disqualified", raw_payload={"start_status": "started"})
        self.assertEqual(self.command(), expected_envelope())

    def test_eleven_ten_and_equal_count_wrong_id_keep_real_denominator(self):
        self.card.items.all().delete()
        self.result.items.all().delete()
        for order, pk in enumerate(range(501, 512), 1):
            m.RaceEventParticipant.objects.create(pk=pk, event=self.event, stable_key=f"p:{pk}", canonical_name="Same Name")
            m.RaceEventRevisionItem.objects.create(revision=self.card, participant_id=pk, internal_order=order, status="declared")
            if order <= 10:
                m.RaceEventRevisionItem.objects.create(revision=self.result, participant_id=pk, internal_order=order,
                                                      status="finished", reported_finish_position=order)
        report = self.command()["ledger"]
        self.assertEqual([row["runner_id"] for row in report["ledger"]], [501, 502, 503, 504, 505, 506, 507, 508, 509, 510, 511])
        self.assertEqual(report["unresolved_result_ids"], [511])
        m.RaceEventParticipant.objects.create(pk=599, event=self.event, stable_key="p:599", canonical_name="Same Name")
        extra = m.RaceEventRevisionItem.objects.create(revision=self.result, participant_id=599, internal_order=11,
                                                      status="finished", reported_finish_position=11)
        report = self.command()
        self.assertEqual(report["ledger"]["unresolved_result_ids"], [511])
        self.assertEqual(report["ledger"]["unexpected_ids"], [599])
        self.assertEqual(report["ledger"]["unexpected_rows"], [{"runner_id": 599, "start_status": "unconfirmed",
            "outcome_status": "finished", "reported_finish_position": 11, "roster_ref": None,
            "participation_ref": None, "result_ref": f"db:revision-item:{extra.pk}", "reasons": ["unexpected_identity"]}])
        self.assertEqual(report["participant_bindings"][-1], {"participant_id": 599, "stable_key": "p:599", "racecard_item_id": None})

    def test_top_three_empty_and_nonfinish_statuses_are_preserved(self):
        self.card.items.all().delete()
        self.result.items.all().delete()
        for order, pk in enumerate(range(601, 612), 1):
            m.RaceEventParticipant.objects.create(pk=pk, event=self.event, stable_key=f"p:{pk}", canonical_name="Same Name")
            m.RaceEventRevisionItem.objects.create(revision=self.card, participant_id=pk, internal_order=order, status="declared")
            if order <= 3:
                m.RaceEventRevisionItem.objects.create(revision=self.result, participant_id=pk, internal_order=order,
                                                      status="finished", reported_finish_position=order)
        self.assertEqual(self.command()["ledger"]["unresolved_result_ids"], [604, 605, 606, 607, 608, 609, 610, 611])
        self.result.items.all().delete()
        self.assertEqual(self.command()["ledger"]["unresolved_result_ids"], [601, 602, 603, 604, 605, 606, 607, 608, 609, 610, 611])
        for order, pk, status in ((1, 601, "non_runner"), (2, 602, "did_not_finish"), (3, 603, "disqualified")):
            m.RaceEventRevisionItem.objects.create(revision=self.result, participant_id=pk, internal_order=order, status=status)
        rows = self.command()["ledger"]["ledger"][:3]
        self.assertEqual([(r["runner_id"], r["start_status"], r["outcome_status"], r["reported_finish_position"])
                          for r in rows], [(601, "unconfirmed", "non_runner", None),
                                          (602, "unconfirmed", "did_not_finish", None), (603, "unconfirmed", "disqualified", None)])

    def test_tied_original_positions_and_unrelated_same_name_never_remap_identity(self):
        m.RaceEventRevisionItem.objects.filter(pk=404).update(status="dead_heat")
        m.RaceEventRevisionItem.objects.filter(pk=405).update(status="dead_heat", reported_finish_position=1)
        m.RaceEventRevisionItem.objects.create(revision=self.result, participant_id=303, internal_order=3,
                                              status="finished", reported_finish_position=3)
        other = m.RaceEvent.objects.create(year=2026, slug="a114-other", original_name="Local R07 Fixture",
                                          country_region="japan", racecourse="Tokyo")
        m.RaceEventParticipant.objects.create(event=other, stable_key="p:301", canonical_name="Same Name")
        m.RaceEventRunner.objects.create(event=self.event, horse_name="Same Name", horse_number="1")
        m.RaceEventResult.objects.create(event=self.event, horse_name="Same Name", horse_number="1", finish_position=1)
        result = self.command()["ledger"]
        self.assertEqual([(r["runner_id"], r["reported_finish_position"]) for r in result["ledger"]], [(301, 1), (302, 1), (303, 3)])
        self.assertEqual(result["unexpected_ids"], [])
        self.assertEqual(result["started_ids"], [])

    def test_invalid_revision_scope_kind_phase_and_item_event_rejected(self):
        for args in ({"event_id": 99999}, {"racecard_revision_id": 99999}, {"result_revision_id": 99999},
                     {"racecard_revision_id": 202}, {"result_revision_id": 201}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.load(**args)
        # Each immutable identity is set at INSERT, never rewritten for a negative case.
        wrong_phase = m.RaceEventRevision.objects.create(pk=211, event=self.event, kind="racecard",
            revision_no=2, phase="provisional", content_sha256="c" * 64)
        for item_id, participant_id, order in ((417, 301, 1), (418, 302, 2), (419, 303, 3)):
            m.RaceEventRevisionItem.objects.create(pk=item_id, revision=wrong_phase,
                participant_id=participant_id, internal_order=order, status="declared")
        with self.assertRaises(ValueError):
            self.load(racecard_revision_id=wrong_phase.pk)
        other = m.RaceEvent.objects.create(pk=102, year=2026, slug="a114-wrong-event", original_name="Other",
                                          country_region="japan", racecourse="Tokyo")
        wrong_event = m.RaceEventRevision.objects.create(pk=212, event=other, kind="result",
            revision_no=1, phase="provisional", content_sha256="d" * 64)
        with self.assertRaises(ValueError):
            self.load(result_revision_id=wrong_event.pk)
        wrong_kind = m.RaceEventRevision.objects.create(pk=213, event=self.event, kind="result",
            revision_no=2, phase="provisional", content_sha256="e" * 64)
        with self.assertRaises(ValueError):
            self.load(racecard_revision_id=wrong_kind.pk)
        foreign_participant = m.RaceEventParticipant.objects.create(pk=304, event=other,
            stable_key="p:304", canonical_name="Same Name")
        cross_event_result = m.RaceEventRevision.objects.create(pk=214, event=self.event, kind="result",
            revision_no=3, phase="provisional", content_sha256="f" * 64)
        m.RaceEventRevisionItem.objects.create(pk=416, revision=cross_event_result,
            participant=foreign_participant, internal_order=1, status="non_runner")
        with self.assertRaises(ValueError):
            self.load(result_revision_id=cross_event_result.pk)

    def test_legacy_rows_do_not_replace_empty_card_and_invalid_rank_is_not_fixed(self):
        m.RaceEventResult.objects.create(event=self.event, horse_name="Same Name", finish_position=1)
        m.RaceEventRunner.objects.create(event=self.event, horse_name="Same Name")
        m.RaceEventRevisionItem.objects.filter(pk=404).update(reported_finish_position=None)
        with self.assertRaises(ValueError):
            self.load()
        self.card.items.all().delete()
        with self.assertRaises(ValueError):
            self.load()

    def test_card_and_result_limits_are_rejected_without_truncation(self):
        self.card.items.all().delete()
        self.result.items.all().delete()
        for order in range(1, 102):
            participant = m.RaceEventParticipant.objects.create(event=self.event, stable_key=f"limit:{order}", canonical_name="Same")
            m.RaceEventRevisionItem.objects.create(revision=self.card, participant=participant, internal_order=order, status="declared")
        with self.assertRaises(ValueError):
            self.load()
        self.card.items.order_by("-internal_order").first().delete()
        self.assertEqual(len(self.load().ledger.ledger), 100)
        for order, participant in enumerate(m.RaceEventParticipant.objects.filter(event=self.event).order_by("pk")[:101], 1):
            m.RaceEventRevisionItem.objects.create(revision=self.result, participant=participant, internal_order=order,
                                                  status="non_runner")
        with self.assertRaises(ValueError):
            self.load()

    def test_material_digest_covers_read_values_not_only_stored_revision_hash(self):
        self.assertEqual(self.load().material_sha256, DIGEST)
        for model, pk, field, value, restore in (
            (m.RaceEventRevisionItem, 404, "reported_finish_position", 2, 1),
            (m.RaceEventRevisionItem, 405, "status", "refused", "non_runner"),
            (m.RaceEventRevisionItem, 401, "status", "withdrawn", "declared"),
            (m.RaceEventParticipant, 301, "stable_key", "changed", "p:301"),
        ):
            with self.subTest(field=field, pk=pk):
                model.objects.filter(pk=pk).update(**{field: value})
                self.assertNotEqual(self.load().material_sha256, DIGEST)
                model.objects.filter(pk=pk).update(**{field: restore})
                self.assertEqual(self.load().material_sha256, DIGEST)


        # Exact expected hashes bind every literal field, including phase/content hash;
        # comparing only against DIGEST would also change when the selected IDs change.
        with self.subTest(field="content_sha256", revision_id=211):
            self.assertEqual(hashlib.sha256(json.dumps(CARD_HASH_MATERIAL, sort_keys=True,
                separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(), CARD_HASH_DIGEST)
            alternate_card = m.RaceEventRevision.objects.create(pk=211, event=self.event, kind="racecard",
                revision_no=2, phase="racecard", content_sha256="d" * 64)
            m.RaceEventRevisionItem.objects.create(pk=411, revision=alternate_card, participant_id=301,
                internal_order=1, status="declared")
            m.RaceEventRevisionItem.objects.create(pk=412, revision=alternate_card, participant_id=302,
                internal_order=2, status="declared")
            m.RaceEventRevisionItem.objects.create(pk=413, revision=alternate_card, participant_id=303,
                internal_order=3, status="declared")
            hash_case = self.load(racecard_revision_id=211)
            self.assertEqual(hash_case.material_sha256, CARD_HASH_DIGEST)
            self.assertEqual(hash_case.ledger.scope_ref,
                             "r07:event:101:racecard:211:result:202:sha256:" + CARD_HASH_DIGEST)
            self.assertEqual([(b.participant_id, b.stable_key, b.racecard_item_id)
                              for b in hash_case.participant_bindings],
                             [(301, "p:301", 411), (302, "p:302", 412), (303, "p:303", 413)])

        with self.subTest(field="phase", revision_id=212):
            self.assertEqual(hashlib.sha256(json.dumps(RESULT_PHASE_MATERIAL, sort_keys=True,
                separators=(",", ":"), ensure_ascii=False).encode()).hexdigest(), RESULT_PHASE_DIGEST)
            alternate_result = m.RaceEventRevision.objects.create(pk=212, event=self.event, kind="result",
                revision_no=2, phase="official", content_sha256="b" * 64)
            m.RaceEventRevisionItem.objects.create(pk=414, revision=alternate_result, participant_id=301,
                internal_order=1, status="finished", reported_finish_position=1)
            m.RaceEventRevisionItem.objects.create(pk=415, revision=alternate_result, participant_id=302,
                internal_order=2, status="non_runner")
            phase_case = self.load(result_revision_id=212)
            self.assertEqual(phase_case.material_sha256, RESULT_PHASE_DIGEST)
            self.assertEqual(phase_case.ledger.scope_ref,
                             "r07:event:101:racecard:201:result:212:sha256:" + RESULT_PHASE_DIGEST)
            self.assertEqual([(row.runner_id, row.outcome_status, row.reported_finish_position, row.result_ref)
                              for row in phase_case.ledger.ledger],
                             [(301, "finished", 1, "db:revision-item:414"),
                              (302, "non_runner", None, "db:revision-item:415"),
                              (303, None, None, None)])

    def test_repeatable_read_keeps_old_snapshot_during_independent_writer_commit(self):
        snapshot_read, writer_finished = Event(), Event()
        writer_errors = []
        def writer():
            try:
                if not snapshot_read.wait(15):
                    raise AssertionError("reader did not establish snapshot")
                m.RaceEventRevisionItem.objects.filter(pk=404).update(reported_finish_position=2)
            except BaseException as exc:
                writer_errors.append(exc)
            finally:
                connections["default"].close()
                writer_finished.set()
        notified = []
        def after_first_select(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if not notified and sql.lstrip().upper().startswith("SELECT "):
                notified.append(True)
                snapshot_read.set()
                if not writer_finished.wait(15):
                    raise AssertionError("writer did not finish")
            return result
        thread = Thread(target=writer)
        thread.start()
        try:
            with connection.execute_wrapper(after_first_select):
                actual = self.command()
        finally:
            snapshot_read.set()
            thread.join(20)
        self.assertFalse(thread.is_alive())
        self.assertEqual(writer_errors, [])
        self.assertEqual(actual, expected_envelope())
        later = self.command()
        self.assertNotEqual(later["material_sha256"], DIGEST)
        self.assertEqual(later["ledger"]["ledger"][0]["reported_finish_position"], 2)

    @override_settings(RACE_DATA_SYNC_FUTURE_HORIZON_DAYS=0,
        RACE_DATA_RAW_ARTIFACT_ROOTS=("/not-created/a114",), RACE_DATA_SYNC_FUTURE_STANDING_POLICY_FILE="/not-created/a114/policy")
    def test_new_mode_returns_before_unrelated_configuration_capacity_and_policy(self):
        self.assertEqual(self.command(), expected_envelope())

    def test_command_requires_all_ids_and_rejects_mixed_legacy_modes(self):
        for args in (("--roster-event-id", "101"),
                     ("--racecard-revision-id", "201", "--result-revision-id", "202")):
            with self.subTest(args=args), self.assertRaises(CommandError):
                call_command("audit_race_data_sync", *args, stdout=StringIO())
        for flag, value in (("--cutoff", "2026-10-17T00:00:00Z"), ("--horizon-days", "1"),
                            ("--standing-policy-file", "/unused"), ("--standing-policy-sha256", "a" * 64)):
            with self.subTest(flag=flag), self.assertRaises(CommandError):
                self.command(flag, value)
        for value in (0, -1, True):
            with self.subTest(value=value), self.assertRaises(CommandError):
                self.command(roster_event_id=value)

    def test_adapter_envelope_and_nested_outputs_are_frozen(self):
        actual = self.load()
        self.assertIs(type(actual.participant_bindings), tuple)
        self.assertIs(type(actual.diagnostics), tuple)
        self.assertIs(type(actual.ledger.ledger), tuple)
        for obj, field, value in ((actual, "event_id", 999), (actual.participant_bindings[0], "stable_key", "other"),
                                   (actual.ledger.ledger[0], "start_status", "started")):
            with self.assertRaises(FrozenInstanceError):
                setattr(obj, field, value)
            self.assertFalse(hasattr(obj, "__dict__"))
        self.assertIsInstance(hash(actual), int)
