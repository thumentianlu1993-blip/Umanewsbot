"""Independent literal contracts for the offline R07 reconciliation ledger."""
from dataclasses import FrozenInstanceError, fields, replace
from enum import Enum
import unittest

from stable.services.race_result_roster_reconciliation import (
    LedgerRow, Outcome, Participation, RosterReconciliation, reconcile_result_roster,
)


class RosterReconciliationTests(unittest.TestCase):
    def call(self, **changes):
        args = dict(scope_ref="s", roster_ref="roster", expected_runner_ids=(1,),
                    participation=(), outcomes=())
        args.update(changes)
        return reconcile_result_roster(**args)

    def test_literal_complete_report_preserves_three_layers(self):
        actual = self.call(
            scope_ref="race:sample:v1", roster_ref="roster:sample:raw",
            expected_runner_ids=(1, 2, 3, 4),
            participation=(
                Participation(1, "race:sample:v1", "did_not_start", "p:1"),
                Participation(3, "race:sample:v1", "started", "p:3"),
                Participation(4, "race:sample:v1", "did_not_start", "p:4"),
            ),
            outcomes=(
                Outcome(3, "race:sample:v1", "did_not_finish", None, "r:3"),
                Outcome(4, "race:sample:v1", "disqualified", None, "r:4"),
            ),
        )
        expected = RosterReconciliation(
            "race:sample:v1", "roster:sample:raw",
            (
                LedgerRow(1, "did_not_start", None, None, "roster:sample:raw", "p:1", None,
                          ("known_nonstarter_without_result",)),
                LedgerRow(2, "unconfirmed", None, None, "roster:sample:raw", None, None,
                          ("participation_missing", "result_missing")),
                LedgerRow(3, "started", "did_not_finish", None, "roster:sample:raw", "p:3", "r:3",
                          ("terminal_result",)),
                LedgerRow(4, "did_not_start", "disqualified", None, "roster:sample:raw", "p:4", "r:4",
                          ("participation_outcome_relation_unconfirmed",)),
            ), (), (3,), (1, 4), (2,), (2, 4), (), (),
        )
        self.assertEqual(actual, expected)

    def test_all_eighteen_cells_and_fifteen_wire_statuses(self):
        # Literal specification, never imported from implementation constants/helpers.
        cases = (
            ("started", ((None, None),), "result_missing", (1,), ()),
            ("started", (("finished", 1), ("dead_heat", 1)), "terminal_result", (), ()),
            ("started", (("did_not_finish", None), ("pulled_up", None), ("unseated_rider", None), ("fell", None)), "terminal_result", (), ()),
            ("started", (("disqualified", None), ("refused", None)), "terminal_result", (), ()),
            ("started", (("scratched", None), ("withdrawn", None), ("non_runner", None)), "started_nonstarter_conflict", (1,), (1,)),
            ("started", (("declared", None), ("running", None), ("reinstated", None), ("unknown", None)), "result_nonterminal", (1,), ()),
            ("did_not_start", ((None, None),), "known_nonstarter_without_result", (), ()),
            ("did_not_start", (("finished", 1), ("dead_heat", 1)), "nonstarter_started_outcome_conflict", (1,), (1,)),
            ("did_not_start", (("did_not_finish", None), ("pulled_up", None), ("unseated_rider", None), ("fell", None)), "nonstarter_started_outcome_conflict", (1,), (1,)),
            ("did_not_start", (("disqualified", None), ("refused", None)), "participation_outcome_relation_unconfirmed", (1,), ()),
            ("did_not_start", (("scratched", None), ("withdrawn", None), ("non_runner", None)), "known_nonstarter_result", (), ()),
            ("did_not_start", (("declared", None), ("running", None), ("reinstated", None), ("unknown", None)), "result_nonterminal", (1,), ()),
            ("unconfirmed", ((None, None),), "result_missing", (1,), ()),
            ("unconfirmed", (("finished", 1), ("dead_heat", 1)), "terminal_result", (), ()),
            ("unconfirmed", (("did_not_finish", None), ("pulled_up", None), ("unseated_rider", None), ("fell", None)), "terminal_result", (), ()),
            ("unconfirmed", (("disqualified", None), ("refused", None)), "terminal_result", (), ()),
            ("unconfirmed", (("scratched", None), ("withdrawn", None), ("non_runner", None)), "nonstarter_result_start_unconfirmed", (), ()),
            ("unconfirmed", (("declared", None), ("running", None), ("reinstated", None), ("unknown", None)), "result_nonterminal", (1,), ()),
        )
        for start, outcomes, reason, unresolved, conflicts in cases:
            for status, position in outcomes:
                with self.subTest(start=start, status=status):
                    supplied = () if status is None else (Outcome(1, "s", status, position, "r"),)
                    actual = self.call(participation=(Participation(1, "s", start, "p"),), outcomes=supplied)
                    self.assertEqual(actual, RosterReconciliation(
                        "s", "roster", (LedgerRow(1, start, status, position, "roster", "p",
                                                 None if status is None else "r", (reason,)),), (),
                        (1,) if start == "started" else (),
                        (1,) if start == "did_not_start" else (),
                        (1,) if start == "unconfirmed" else (), unresolved, (), conflicts,
                    ))

    def test_missing_participation_is_not_an_inferred_start(self):
        for status, position, reason, unresolved in (
            (None, None, "result_missing", (1,)),
            ("finished", 1, "terminal_result", ()),
            ("dead_heat", 1, "terminal_result", ()),
            ("did_not_finish", None, "terminal_result", ()),
            ("disqualified", None, "terminal_result", ()),
            ("refused", None, "terminal_result", ()),
            ("non_runner", None, "nonstarter_result_start_unconfirmed", ()),
            ("running", None, "result_nonterminal", (1,)),
        ):
            with self.subTest(status=status):
                rows = () if status is None else (Outcome(1, "s", status, position, "r"),)
                self.assertEqual(self.call(outcomes=rows), RosterReconciliation(
                    "s", "roster", (LedgerRow(1, "unconfirmed", status, position, "roster", None,
                        None if status is None else "r", ("participation_missing", reason)),),
                    (), (), (), (1,), unresolved, (), (),
                ))

    def test_eleven_roster_ten_results_distinguishes_nonstarter_and_unknown(self):
        outcomes = tuple(Outcome(i, "s", "finished", i, f"r:{i}") for i in range(1, 11))
        known = self.call(expected_runner_ids=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
                          participation=(Participation(11, "s", "did_not_start", "p:11"),), outcomes=outcomes)
        self.assertEqual(known.ledger[-1], LedgerRow(11, "did_not_start", None, None, "roster", "p:11", None,
                                                   ("known_nonstarter_without_result",)))
        self.assertEqual(known.unresolved_result_ids, ())
        self.assertEqual(known.did_not_start_ids, (11,))
        for part in ((), (Participation(11, "s", "started", "p:11"),),
                     (Participation(11, "s", "unconfirmed", "p:11"),)):
            with self.subTest(part=part):
                result = self.call(expected_runner_ids=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
                                   participation=part, outcomes=outcomes)
                self.assertEqual(result.unresolved_result_ids, (11,))
                self.assertIsNone(result.ledger[-1].result_ref)
        self.assertEqual(len(outcomes), 10)
        self.assertEqual(outcomes[-1], Outcome(10, "s", "finished", 10, "r:10"))

    def test_same_count_wrong_identity_keeps_missing_and_unexpected(self):
        outcomes = tuple(Outcome(i, "s", "finished", i, f"r:{i}") for i in range(1, 11)) + (
            Outcome(99, "s", "finished", 11, "r:99"),)
        result = self.call(expected_runner_ids=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11), outcomes=outcomes)
        self.assertEqual(result.unresolved_result_ids, (11,))
        self.assertEqual(result.unexpected_ids, (99,))
        self.assertEqual(result.unexpected_rows, (LedgerRow(99, "unconfirmed", "finished", 11,
                         None, None, "r:99", ("unexpected_identity",)),))
        self.assertEqual(tuple(row.runner_id for row in result.ledger), (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11))

    def test_top_three_summary_does_not_shrink_denominator(self):
        result = self.call(expected_runner_ids=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11), outcomes=(
            Outcome(1, "s", "finished", 1, "r:1"), Outcome(2, "s", "finished", 2, "r:2"),
            Outcome(3, "s", "finished", 3, "r:3")))
        self.assertEqual(result.unresolved_result_ids, (4, 5, 6, 7, 8, 9, 10, 11))
        self.assertEqual(result.started_ids, ())
        self.assertEqual(len(result.ledger), 11)

    def test_ties_partial_ranks_and_permutations_preserve_inputs(self):
        parts = (Participation(3, "s", "started", "p:3"), Participation(1, "s", "started", "p:1"))
        outcomes = (Outcome(3, "s", "finished", 3, "r:3"), Outcome(2, "s", "dead_heat", 1, "r:2"),
                    Outcome(1, "s", "dead_heat", 1, "r:1"))
        before = (parts, outcomes)
        expected = RosterReconciliation("s", "roster", (
            LedgerRow(1, "started", "dead_heat", 1, "roster", "p:1", "r:1", ("terminal_result",)),
            LedgerRow(2, "unconfirmed", "dead_heat", 1, "roster", None, "r:2", ("participation_missing", "terminal_result")),
            LedgerRow(3, "started", "finished", 3, "roster", "p:3", "r:3", ("terminal_result",)),
        ), (), (1, 3), (), (2,), (), (), ())
        self.assertEqual(self.call(expected_runner_ids=(3, 2, 1), participation=parts, outcomes=outcomes), expected)
        self.assertEqual(self.call(expected_runner_ids=(2, 1, 3), participation=parts[::-1], outcomes=outcomes[::-1]), expected)
        self.assertEqual((parts, outcomes), before)
        # A local summary need not start at 1 or independently prove the full tie group.
        self.assertEqual(self.call(outcomes=(Outcome(1, "s", "dead_heat", 7, "r"),)).ledger[0].reported_finish_position, 7)

    def test_all_nonstarters_without_results_do_not_generate_results(self):
        self.assertEqual(self.call(expected_runner_ids=(2, 1), participation=(
            Participation(2, "s", "did_not_start", "p:2"), Participation(1, "s", "did_not_start", "p:1"))),
            RosterReconciliation("s", "roster", (
                LedgerRow(1, "did_not_start", None, None, "roster", "p:1", None, ("known_nonstarter_without_result",)),
                LedgerRow(2, "did_not_start", None, None, "roster", "p:2", None, ("known_nonstarter_without_result",)),
            ), (), (), (1, 2), (), (), (), ()))

    def test_unexpected_union_preserves_both_refs_without_adjudication(self):
        result = self.call(participation=(Participation(9, "s", "did_not_start", "p:9"),
                                         Participation(8, "s", "started", "p:8")),
                           outcomes=(Outcome(9, "s", "finished", 1, "r:9"), Outcome(7, "s", "refused", None, "r:7")))
        self.assertEqual(result.unexpected_rows, (
            LedgerRow(7, "unconfirmed", "refused", None, None, None, "r:7", ("unexpected_identity",)),
            LedgerRow(8, "started", None, None, None, "p:8", None, ("unexpected_identity",)),
            LedgerRow(9, "did_not_start", "finished", 1, None, "p:9", "r:9", ("unexpected_identity",)),
        ))
        self.assertEqual(result.unexpected_ids, (7, 8, 9))
        self.assertEqual(result.started_ids, ())
        self.assertEqual(result.conflict_ids, ())
        self.assertEqual(result.unresolved_result_ids, (1,))

    def test_outputs_are_frozen_slotted_hashable_and_have_only_contract_fields(self):
        result = self.call(outcomes=(Outcome(1, "s", "finished", 1, "r"),))
        self.assertEqual(tuple(f.name for f in fields(result)), (
            "scope_ref", "roster_ref", "ledger", "unexpected_rows", "started_ids", "did_not_start_ids",
            "unconfirmed_start_ids", "unresolved_result_ids", "unexpected_ids", "conflict_ids"))
        self.assertEqual(tuple(f.name for f in fields(result.ledger[0])), (
            "runner_id", "start_status", "outcome_status", "reported_finish_position", "roster_ref",
            "participation_ref", "result_ref", "reasons"))
        for obj, attr, value in ((result, "scope_ref", "other"), (result.ledger[0], "runner_id", 8),
                                 (Participation(1, "s", "started", "p"), "start_status", "unconfirmed"),
                                 (Outcome(1, "s", "finished", 1, "r"), "status", "unknown")):
            with self.subTest(obj=obj):
                self.assertFalse(hasattr(obj, "__dict__"))
                with self.assertRaises(FrozenInstanceError):
                    setattr(obj, attr, value)
                self.assertIsInstance(hash(obj), int)
        for seq in (result.ledger, result.unexpected_rows, result.started_ids, result.did_not_start_ids,
                    result.unconfirmed_start_ids, result.unresolved_result_ids, result.unexpected_ids,
                    result.conflict_ids, result.ledger[0].reasons):
            self.assertIs(type(seq), tuple)

    def test_rejects_bad_top_level_shapes_ids_bounds_and_refs(self):
        class IntSubclass(int):
            pass
        class StringSubclass(str):
            pass
        class TupleSubclass(tuple):
            pass
        bad = (
            {"expected_runner_ids": ()}, {"expected_runner_ids": (1, 1)},
            {"expected_runner_ids": tuple(range(1, 102))}, {"expected_runner_ids": [1]},
            {"expected_runner_ids": TupleSubclass((1,))}, {"participation": []}, {"outcomes": []},
        )
        for value in (True, False, 0, -1, "1", 1.0, None, IntSubclass(1)):
            bad += ({"expected_runner_ids": (value,)},)
        for key in ("scope_ref", "roster_ref"):
            for value in (None, 1, "", " ", " s", "s\n", "x" * 257, StringSubclass("s")):
                bad += ({key: value},)
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.call(**changes)

    def test_rejects_bad_rows_including_unexpected_and_duplicates(self):
        class PartSubclass(Participation):
            pass
        class OutcomeSubclass(Outcome):
            pass
        class StartEnum(str, Enum):
            STARTED = "started"
        valid_part = Participation(1, "s", "started", "p")
        valid_outcome = Outcome(1, "s", "finished", 1, "r")
        for key, rows in (
            ("participation", (None, {}, valid_outcome, PartSubclass(1, "s", "started", "p"))),
            ("outcomes", (None, {}, valid_part, OutcomeSubclass(1, "s", "finished", 1, "r"))),
        ):
            for row in rows:
                with self.subTest(key=key, row=row), self.assertRaises(ValueError):
                    self.call(**{key: (row,)})
        for key, row in (("participation", valid_part), ("outcomes", valid_outcome)):
            for value in (True, 0, -1, "1", 1.0, None):
                with self.subTest(key=key, runner_id=value), self.assertRaises(ValueError):
                    self.call(**{key: (replace(row, runner_id=value),)})
            for field in ("scope_ref", "row_ref"):
                for value in (None, "", " s", "s ", "x" * 257, 1):
                    with self.subTest(key=key, field=field, value=value), self.assertRaises(ValueError):
                        self.call(**{key: (replace(row, **{field: value}),)})
            with self.assertRaises(ValueError):
                self.call(**{key: (row, row)})
            with self.assertRaises(ValueError):
                self.call(**{key: tuple(replace(row, runner_id=i) for i in range(1, 102))})
            with self.assertRaises(ValueError):
                self.call(**{key: (replace(row, runner_id=99, scope_ref="other"),)})
        for value in (None, "", "STARTED", " started", "cancelled", StartEnum.STARTED):
            with self.subTest(start=value), self.assertRaises(ValueError):
                self.call(participation=(replace(valid_part, start_status=value),))
        for value in (None, "", "FINISHED", " finished", "cancelled", 1):
            with self.subTest(status=value), self.assertRaises(ValueError):
                self.call(outcomes=(replace(valid_outcome, status=value),))

    def test_rejects_invalid_positions_without_silently_normalizing(self):
        for status in ("finished", "dead_heat"):
            for pos in (None, True, False, "1", 1.0, 0, -1, 101):
                with self.subTest(status=status, pos=pos), self.assertRaises(ValueError):
                    self.call(outcomes=(Outcome(1, "s", status, pos, "r"),))
        for status in ("did_not_finish", "pulled_up", "unseated_rider", "fell", "disqualified", "refused",
                       "scratched", "withdrawn", "non_runner", "declared", "running", "reinstated", "unknown"):
            for pos in (1, True, "1", 0):
                with self.subTest(status=status, pos=pos), self.assertRaises(ValueError):
                    self.call(outcomes=(Outcome(1, "s", status, pos, "r"),))
        self.assertEqual(self.call(outcomes=(Outcome(1, "s", "finished", 100, "r"),)).ledger[0].reported_finish_position, 100)

    def test_valid_maxima_and_duplicate_refs_do_not_claim_source_independence(self):
        scope = "s" * 256
        parts = tuple(Participation(i, scope, "did_not_start", "same") for i in range(1, 101))
        outcomes = tuple(Outcome(i, scope, "non_runner", None, "same") for i in range(1, 101))
        result = self.call(scope_ref=scope, roster_ref="r" * 256, expected_runner_ids=tuple(range(1, 101)),
                           participation=parts, outcomes=outcomes)
        self.assertEqual(len(result.ledger), 100)
        self.assertEqual(result.unresolved_result_ids, ())
        self.assertEqual(result.ledger[-1], LedgerRow(100, "did_not_start", "non_runner", None,
                          "r" * 256, "same", "same", ("known_nonstarter_result",)))
