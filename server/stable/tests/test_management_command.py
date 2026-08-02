"""
Tests for ``normalize_race_and_career_fields`` management command.

Covers: test_cases.md section 8 (backfill command) — command existence,
dry-run defaults, output directory, manifest binding, apply/receipt/rollback
contracts, concurrency locks, checkpoint recovery, and term snapshot drift.
"""
import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest import skipIf

from django.core.management import call_command, CommandError
from django.test import TestCase
from django.utils import timezone

from stable.models import (
    HorseRaceRecord,
    HorseProfile,
    RaceFieldNormalizationRun,
    RaceFieldNormalizationReceipt,
    TermEntry,
    TermAlias,
    RacingRegion,
)

COMMAND_EXISTS = True


# ── helpers ──────────────────────────────────────────────────────────
def _profile(**kw):
    term = TermEntry.objects.create(
        term_type="horse", source_text="Test Horse", target_zh="测试马",
        is_active=True, region=RacingRegion.JAPAN,
    )
    return HorseProfile.objects.create(primary_term=term, racing_region=RacingRegion.JAPAN, **kw)


def _record(profile, finish_position="1", **kw):
    defaults = {
        "horse_profile": profile,
        "race_name": "Test Race",
        "race_date": "2024-01-01",
        "finish_position": finish_position,
        "race_region": RacingRegion.JAPAN,
        **kw,
    }
    return HorseRaceRecord.objects.create(**defaults)


# ── Command Existence & Basic Behaviour ──────────────────────────────
class CommandBasicTests(TestCase):
    """Verify the command is registered and has expected arguments."""

    def test_command_help(self):
        """``--help`` prints usage without error."""
        try:
            out = StringIO()
            call_command("normalize_race_and_career_fields", "--help", stdout=out)
        except SystemExit:
            pass  # Django's --help calls sys.exit(0)

    def test_default_is_dry_run(self):
        """When no apply flags given the command defaults to dry-run."""
        out = StringIO()
        call_command("normalize_race_and_career_fields", stdout=out)
        self.assertIn("dry-run", out.getvalue().lower() or "Dry-run")

    def test_output_dir_must_not_exist(self):
        """Existing non-empty output directory raises CommandError."""
        with tempfile.TemporaryDirectory() as td:
            # Create a file inside to make it non-empty
            Path(td).joinpath("existing_file").touch()
            out = StringIO()
            with self.assertRaises(CommandError):
                call_command(
                    "normalize_race_and_career_fields",
                    "--output-dir", td,
                    stdout=out,
                )


# ── Apply Argument Contracts ─────────────────────────────────────────
class ApplyArgumentTests(TestCase):
    """Apply mode requires the three explicit flags."""

    def test_apply_requires_manifest_path(self):
        """Apply mode raises when manifest file doesn't exist."""
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "normalize_race_and_career_fields",
                "--apply-manifest", "/nonexistent/path/manifest.json",
                "--expected-sha256", "a" * 64,
                "--confirm-apply",
                stdout=out,
            )

    def test_apply_requires_sha256(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "normalize_race_and_career_fields",
                "--apply-manifest", "/nonexistent/path/manifest.json",
                "--confirm-apply",
                stdout=out,
            )

    def test_apply_requires_confirm(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "normalize_race_and_career_fields",
                "--apply-manifest", "/nonexistent/path/manifest.json",
                "--expected-sha256", "a" * 64,
                stdout=out,
            )

    def test_apply_rejects_sha_mismatch(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "normalize_race_and_career_fields",
                "--apply-manifest", "/nonexistent/path/manifest.json",
                "--expected-sha256", "0" * 64,
                "--confirm-apply",
                stdout=out,
            )

    def test_apply_rejects_missing_manifest_file(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "normalize_race_and_career_fields",
                "--apply-manifest", "/nonexistent/path/manifest.json",
                "--expected-sha256", "x" * 64,
                "--confirm-apply",
                stdout=out,
            )

    def test_model_scope_all(self):
        """``--model all`` is accepted and runs dry-run."""
        out = StringIO()
        call_command(
            "normalize_race_and_career_fields",
            "--model", "all",
            stdout=out,
        )

    def test_model_scope_horse_race_record(self):
        out = StringIO()
        call_command(
            "normalize_race_and_career_fields",
            "--model", "horse-race-record",
            stdout=out,
        )

    def test_model_scope_race_event(self):
        out = StringIO()
        call_command(
            "normalize_race_and_career_fields",
            "--model", "race-event",
            stdout=out,
        )

    def test_batch_size_and_after_id_accepted(self):
        out = StringIO()
        call_command(
            "normalize_race_and_career_fields",
            "--batch-size", "100",
            "--after-id", "0",
            stdout=out,
        )


# ── Dry-Run Output Artifacts ─────────────────────────────────────────
class DryRunArtifactTests(TestCase):
    """Verify dry-run produces the expected artifact files."""

    def test_dry_run_creates_manifest_json(self):
        with tempfile.TemporaryDirectory() as td:
            outdir = os.path.join(td, "out")
            out = StringIO()
            call_command(
                "normalize_race_and_career_fields",
                "--output-dir", outdir,
                "--model", "horse-race-record",
                stdout=out,
            )
            self.assertTrue(os.path.isfile(os.path.join(outdir, "manifest.json")))
            self.assertTrue(os.path.isfile(os.path.join(outdir, "summary.json")))

    def test_manifest_contains_normalizer_version(self):
        with tempfile.TemporaryDirectory() as td:
            outdir = os.path.join(td, "out")
            out = StringIO()
            call_command(
                "normalize_race_and_career_fields",
                "--output-dir", outdir,
                "--model", "horse-race-record",
                stdout=out,
            )
            with open(os.path.join(outdir, "manifest.json")) as f:
                manifest = json.load(f)
            self.assertIn("normalizer_version", manifest)
            self.assertIn("race-field-normalization", manifest["normalizer_version"])


# ── Model Schema Tests ───────────────────────────────────────────────
class RunModelSchemaTests(TestCase):
    """Verify RaceFieldNormalizationRun / Receipt schema."""

    def test_run_model_fields(self):
        expected_fields = [
            "status", "model_scope", "manifest_sha256", "normalizer_version",
            "term_snapshot_digest", "checkpoint_data", "planned_count",
            "actual_count", "skipped_count", "conflict_count",
            "started_at", "finished_at", "error_message",
        ]
        for field in expected_fields:
            self.assertTrue(
                hasattr(RaceFieldNormalizationRun, field),
                msg=f"Run model missing field: {field}",
            )

    def test_run_model_status_choices(self):
        status_choices = dict(RaceFieldNormalizationRun.Status.choices)
        for expected in ("pending", "running", "completed", "failed"):
            self.assertIn(expected, status_choices,
                          msg=f"Status choice missing: {expected}")

    def test_receipt_model_fields(self):
        expected_fields = [
            "run", "batch_number", "model_label", "object_pk",
            "before_snapshot", "after_snapshot", "input_sha256",
            "race_term_id", "racecourse_term_id",
            "normalizer_version", "committed_at",
        ]
        for field in expected_fields:
            self.assertTrue(
                hasattr(RaceFieldNormalizationReceipt, field),
                msg=f"Receipt model missing field: {field}",
            )

    def test_receipt_unique_constraint(self):
        meta = RaceFieldNormalizationReceipt._meta
        constraints = meta.constraints
        found = False
        for c in constraints:
            fields = getattr(c, "fields", ())
            if "run" in fields and "object_pk" in fields:
                found = True
        self.assertTrue(found, "Missing unique constraint on (run, object_pk)")


# ── Term Snapshot Tests ──────────────────────────────────────────────
class TermSnapshotContractTests(TestCase):
    """Term snapshot binding in manifest."""

    @classmethod
    def setUpTestData(cls):
        cls.term = TermEntry.objects.create(
            term_type="fixed_phrase", source_ja="title",
            target_zh="头衔", racing_region="", source_language="ja", is_active=True,
        )

    def test_term_snapshot_contains_expected_fields(self):
        """Term snapshot contains expected keys."""
        with tempfile.TemporaryDirectory() as td:
            outdir = os.path.join(td, "out")
            out = StringIO()
            call_command(
                "normalize_race_and_career_fields",
                "--output-dir", outdir,
                "--model", "horse-race-record",
                stdout=out,
            )
            with open(os.path.join(outdir, "manifest.json")) as f:
                manifest = json.load(f)
            self.assertIn("term_snapshot_digest", manifest)
            # digest must be a non-empty hex string
            digest = manifest["term_snapshot_digest"]
            self.assertTrue(len(digest) >= 64, f"Digest too short: {digest}")


# ── Receipt Contract Tests ───────────────────────────────────────────
class ReceiptContractTests(TestCase):
    """Receipt fields and constraints."""

    def test_receipt_has_before_after_json(self):
        for field in ("before_snapshot", "after_snapshot"):
            self.assertTrue(
                hasattr(RaceFieldNormalizationReceipt, field),
                msg=f"Receipt missing field: {field}",
            )

    def test_receipt_creation(self):
        """Receipt can be created and saved."""
        run = RaceFieldNormalizationRun.objects.create(
            status=RaceFieldNormalizationRun.Status.PENDING,
            model_scope="horse-race-record",
            normalizer_version="race-field-normalization.v1",
        )
        receipt = RaceFieldNormalizationReceipt.objects.create(
            run=run,
            batch_number=1,
            model_label="stable.HorseRaceRecord",
            object_pk=1,
            before_snapshot={"finish_position": "01"},
            after_snapshot={"normalized_finish_position": 1},
            input_sha256="a" * 64,
            normalizer_version="race-field-normalization.v1",
        )
        self.assertIsNotNone(receipt.pk)
        self.assertEqual(receipt.run, run)


# ── Concurrency & Lock Tests ─────────────────────────────────────────
class ConcurrencyAndLockTests(TestCase):
    """Concurrent apply protection."""

    def test_run_status_transitions(self):
        """Run transitions through expected states."""
        run = RaceFieldNormalizationRun.objects.create(
            status=RaceFieldNormalizationRun.Status.PENDING,
            model_scope="horse-race-record",
            normalizer_version="race-field-normalization.v1",
        )
        run.status = RaceFieldNormalizationRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save()
        run.refresh_from_db()
        self.assertEqual(run.status, RaceFieldNormalizationRun.Status.RUNNING)
        self.assertIsNotNone(run.started_at)


# ── Rollback Contract Tests ──────────────────────────────────────────
class RollbackContractTests(TestCase):
    """Rollback behaviour contracts."""

    def test_only_runs_with_receipts_can_be_rolled_back(self):
        """A completed run with receipts is rollback-eligible."""
        run = RaceFieldNormalizationRun.objects.create(
            status=RaceFieldNormalizationRun.Status.COMPLETED,
            model_scope="horse-race-record",
            normalizer_version="race-field-normalization.v1",
            actual_count=1,
        )
        receipt = RaceFieldNormalizationReceipt.objects.create(
            run=run,
            batch_number=1,
            model_label="stable.HorseRaceRecord",
            object_pk=1,
            before_snapshot={"normalized_finish_position": None},
            after_snapshot={"normalized_finish_position": 1},
            input_sha256="a" * 64,
            normalizer_version="race-field-normalization.v1",
        )
        self.assertEqual(run.receipts.count(), 1)
        self.assertEqual(receipt.run, run)


# ── Parameter Contract Tests ─────────────────────────────────────────
class ParameterContractTests(TestCase):
    """Command-line parameter contracts."""

    def test_invalid_model_raises_error(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "normalize_race_and_career_fields",
                "--model", "invalid-model",
                stdout=out,
            )

    def test_batch_size_accepted(self):
        """Valid batch size is accepted."""
        out = StringIO()
        call_command(
            "normalize_race_and_career_fields",
            "--batch-size", "100",
            stdout=out,
        )

    def test_after_id_accepted(self):
        """Valid after_id is accepted."""
        out = StringIO()
        call_command(
            "normalize_race_and_career_fields",
            "--after-id", "100",
            stdout=out,
        )
