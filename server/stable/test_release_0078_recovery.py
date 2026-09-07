"""0078 release contracts. No production services or external requests."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

from django.test import SimpleTestCase
from django.core.management import CommandError, call_command

from stable.services import historical_calendar_release_b_schema as schema
from stable.services import release_0078_recovery as recovery
from stable.services import historical_calendar_release_b_handoff as handoff


ROOT = Path(__file__).resolve().parents[2]
LEAF_0077 = "stable.0077_racing_api_horse_identity_staging"
LEAF_0078 = "stable.0078_externalhorse_profile_snapshot"


class Release0078SchemaContractTests(SimpleTestCase):
    def test_current_leaf_needs_no_ddl(self):
        self.assertEqual(schema.TARGET, ("stable", "0078_externalhorse_profile_snapshot"))
        self.assertEqual(schema.ALLOWED_FORWARD_STATES[(LEAF_0078,)], [])

    def test_upgrade_is_only_0078(self):
        self.assertEqual(
            schema.ALLOWED_FORWARD_STATES[(LEAF_0077,)],
            ["0078_externalhorse_profile_snapshot"],
        )

    def test_snapshot_catalog_requires_exact_postgresql_column(self):
        column = {
            "table_name": "stable_externalhorse", "column_name": "profile_snapshot",
            "type": "jsonb", "not_null": True, "identity": "",
            "generated": "", "default_expr": "",
        }
        validate = schema.validate_externalhorse_profile_snapshot_catalog_contract
        self.assertEqual(validate(contract={"columns": [column]}, migration_applied=True), [])
        for field, value in (
            ("type", "json"), ("not_null", False), ("identity", "a"),
            ("generated", "s"), ("default_expr", "'{}'::jsonb"),
        ):
            with self.subTest(field=field):
                wrong = {**column, field: value}
                self.assertTrue(validate(contract={"columns": [wrong]}, migration_applied=True))
        self.assertTrue(validate(contract={"columns": []}, migration_applied=True))
        self.assertTrue(validate(contract={"columns": [column, copy.copy(column)]}, migration_applied=True))
        missing_evidence = {key: value for key, value in column.items() if key != "generated"}
        self.assertTrue(validate(contract={"columns": [missing_evidence]}, migration_applied=True))

    def test_unrecorded_snapshot_column_is_drift(self):
        validate = schema.validate_externalhorse_profile_snapshot_catalog_contract
        self.assertEqual(validate(contract={"columns": []}, migration_applied=False), [])
        self.assertTrue(validate(contract={"columns": [{
            "table_name": "stable_externalhorse", "column_name": "profile_snapshot",
        }]}, migration_applied=False))

    def test_published_migration_bytes_are_unchanged(self):
        source = (ROOT / "server/stable/migrations/0078_externalhorse_profile_snapshot.py").read_bytes()
        blob = b"blob " + str(len(source)).encode("ascii") + b"\0" + source
        self.assertEqual(hashlib.sha1(blob).hexdigest(), "3cfa1b7d0431e2c8bfe6ff21d1651ff97f14233d")

    def test_real_rollback_policy_refuses_before_git_or_service_calls(self):
        spec = importlib.util.spec_from_file_location(
            "rollback_0078_test", ROOT / "deploy/verify_rollback_target_migration.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module.subprocess, "run") as process:
            with self.assertRaisesRegex(ValueError, "0078.*generic application rollback is disabled"):
                module.verify("a" * 40)
        process.assert_not_called()

    def test_reviewed_tail_keeps_all_three_migrations(self):
        spec = importlib.util.spec_from_file_location(
            "rollback_0078_tail_test", ROOT / "deploy/verify_rollback_target_migration.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual({Path(path).name[:4] for path in module.REVIEWED_TAIL_PATHS}, {"0076", "0077", "0078"})


class Release0078MigrationFileContractTests(TestCase):
    def test_v5_django_verifier_requires_same_exact_admission_semantics(self):
        preflight = {"ok": True, "migration_leaf_set": [LEAF_0078], "migration_plan": [],
                     "database_identity_sha256": "d" * 64}
        with patch.object(handoff, "collect_writer_activity", return_value={"ok": True, "counts": {}, "flags": {}}):
            payload = handoff.build_preflight_artifact(
                preflight=preflight, candidate_commit="b" * 40,
                candidate_image_id="sha256:" + "c" * 64,
                compose_file="docker-compose.prod.yml", deployment_lock_token_sha256="e" * 64,
                artifact_path="/isolated/preflight.json", handoff_action="deploy")
        cases = (
            {"preflight": {**preflight, "ok": False}},
            {"preflight": {**preflight, "migration_leaf_set": ["stable.0076_alter_externaldataimporterror_racing_region_and_more"]}},
            {"preflight": {**preflight, "migration_plan": ["0079_unreviewed"]}},
            {"preflight": {**preflight, "database_identity_sha256": "f" * 64}},
            {"writer_activity": {"ok": False, "counts": {"external_import_started": 1}, "flags": {}}},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                corrupt = {**payload, **changes}
                corrupt["artifact_sha256"] = handoff.canonical_artifact_sha256(corrupt)
                with patch.object(handoff, "_read_trusted_json", return_value=(corrupt, [])):
                    result = handoff.verify_preflight_artifact(
                        path=Path("/isolated/preflight.json"), expected_artifact_sha256=corrupt["artifact_sha256"],
                        expected_bindings={"candidate_commit": "b" * 40})
                self.assertFalse(result["ok"], result)

    def test_all_migration_files_and_contents_are_pinned(self):
        self.assertEqual(recovery.migration_contract(), "50c421f3167a8c2c8f1613a0597ad7ee196c249fc18bf7eed0de7b9cd2f80906")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            services = root / "stable/services"
            services.mkdir(parents=True)
            shutil.copytree(ROOT / "server/stable/migrations", root / "stable/migrations")
            module_path = services / "release_0078_recovery.py"
            module_path.write_bytes(Path(recovery.__file__).read_bytes())
            spec = importlib.util.spec_from_file_location("isolated_0078_contract", module_path)
            isolated = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(isolated)
            for name in ("0079_unreviewed.py", "0078_alias.py", "0001_inserted.py", "nested/0078_hidden.py"):
                with self.subTest(name=name):
                    path = root / "stable/migrations" / name
                    path.parent.mkdir(exist_ok=True)
                    path.write_text("# unreviewed\n", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "contract drift"):
                        isolated.migration_contract()
                    path.unlink()
            path = root / "stable/migrations/0078_externalhorse_profile_snapshot.py"
            path.write_bytes(path.read_bytes() + b"\n# changed dependency or content\n")
            with self.assertRaisesRegex(ValueError, "contract drift"):
                isolated.migration_contract()


@skipUnless(os.name == "posix", "requires real POSIX file identity and permissions; run the Linux contract job")
class Release0078ArtifactTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "release-0078-recovery"
        self.root.mkdir(mode=0o700)
        self.release_id = "a" * 64
        self.directory = self.root / self.release_id
        self.directory.mkdir(mode=0o700)
        backup_dir = self.directory / "backup"
        backup_dir.mkdir(mode=0o700)
        self.backup = backup_dir / "synthetic.dump"
        self.backup.write_bytes(b"synthetic bytes; database restore has a separate PG16 test")
        self.backup.chmod(0o600)
        self.bindings = {
            "release_id": self.release_id, "origin_handoff_sha256": self.release_id,
            "candidate_commit": "b" * 40, "candidate_image_id": "sha256:" + "c" * 64,
            "database_identity_sha256": "d" * 64, "compose_file": "docker-compose.prod.yml",
        }
        self.services = {name: name in {"web", "worker", "beat", "nginx"} for name in ("web", "worker", "beat", "race_live_worker", "race_sync_v2_worker", "nginx")}
        self.manifest = {
            "schema_version": "release-0078-verified-backup-recovery/v1", **self.bindings,
            "source_leaf": LEAF_0078, "target_leaf": LEAF_0078, "operation": "same-schema",
            "migration_contract_sha256": "50c421f3167a8c2c8f1613a0597ad7ee196c249fc18bf7eed0de7b9cd2f80906",
            "backup_path": str(self.backup), "backup_file": recovery.file_evidence(self.backup)[1],
            "pg_restore_list_sha256": "e" * 64, "pg_restore_list_line_count": 10,
            "restore_services": self.services, "config_sha256": "f" * 64, "initial_lock_sha256": "1" * 64,
            "compose_project": "isolated0078",
        }
        self.manifest_path = self.directory / "manifest.json"

    def write_manifest(self, **changes):
        self.manifest_path.unlink(missing_ok=True)
        return recovery.publish_once(self.manifest_path, {**self.manifest, **changes})["sha256"]

    def prepared_fields(self):
        sha = self.write_manifest()
        path = self.directory / "intent.json"
        payload = {"schema_version": "release-0078-prepared-intent/v1", **self.bindings,
                   "manifest_sha256": sha, "source_leaf": self.manifest["source_leaf"],
                   "restore_services": self.services, "config_sha256": "f" * 64, "initial_lock_sha256": "1" * 64}
        identity = recovery.publish_once(path, payload)
        recovery.publish_once(self.root / "active.json", {"release_id": self.release_id, "intent_path": str(path), "intent_file": identity})
        return {"release_0078_recovery_manifest_path": str(self.manifest_path), "release_0078_recovery_manifest_sha256": sha,
                "release_0078_recovery_origin_handoff_sha256": self.release_id,
                "release_0078_intent_path": str(path), "release_0078_intent_sha256": identity["sha256"]}

    def artifact(self, live, fields):
        path = self.directory / "closed.json"
        with patch.object(handoff, "collect_writer_activity", return_value={"ok": True, "counts": {}, "flags": {}}):
            payload = handoff.build_preflight_artifact(
                preflight=live, candidate_commit="b" * 40, candidate_image_id="sha256:" + "c" * 64,
                compose_file="docker-compose.prod.yml", deployment_lock_token_sha256="e" * 64,
                artifact_path=str(path), handoff_action="forward-resume" if fields else "deploy", **fields)
        handoff.publish_preflight_artifact(path=path, payload=payload)
        return path, payload

    def test_actual_v5_management_commands_create_and_complete_exact_ddl_marker(self):
        live = {"ok": True, "migration_leaf_set": [LEAF_0078], "migration_plan": [], "database_identity_sha256": "d" * 64}
        fields = self.prepared_fields()
        path, payload = self.artifact(live, fields)
        marker = Path(self.tmp.name) / "restricted-recovery.json"
        ensure_module = "stable.management.commands.ensure_historical_calendar_recovery_intent"
        complete_module = "stable.management.commands.complete_historical_calendar_restricted_recovery"
        common = {"marker_path": str(marker), "artifact_path": str(path), "artifact_sha256": payload["artifact_sha256"],
                  "candidate_commit": "b" * 40, "candidate_image_id": "sha256:" + "c" * 64,
                  "database_identity_sha256": "d" * 64, "attempt_mode": "required",
                  "provenance_artifact_sha256": self.release_id}
        out = StringIO()
        with patch(ensure_module + ".database_vendor_contract", return_value={"ok": True}), \
             patch(ensure_module + ".collect_handoff_preflight", return_value=live), \
             patch.object(handoff, "collect_handoff_preflight", return_value=live), \
             patch.object(handoff, "collect_writer_activity", return_value={"ok": True}):
            call_command("ensure_historical_calendar_recovery_intent", stdout=out, **common)
        result = json.loads(out.getvalue())
        stored, identity = recovery.read_json(marker)
        self.assertEqual(stored["schema_version"], "migration-history-repair-restricted-recovery/v3")
        self.assertEqual(stored["target_leaf_set"], [LEAF_0078])
        self.assertEqual(stored["release_0078_manifest_sha256"], fields["release_0078_recovery_manifest_sha256"])
        self.assertEqual((result["marker_device"], result["marker_inode"]), (identity["device"], identity["inode"]))
        with patch(complete_module + ".database_vendor_contract", return_value={"ok": True}), \
             patch(complete_module + ".collect_handoff_preflight", return_value=live):
            call_command("complete_historical_calendar_restricted_recovery", stdout=StringIO(), **common,
                         expected_marker_device=result["marker_device"], expected_marker_inode=result["marker_inode"])
        self.assertFalse(marker.exists())
        receipt = recovery.completed_marker(marker.parent, recovery.marker_binding(payload))
        self.assertIsNotNone(receipt)
        self.assertTrue((self.root / "active.json").exists(), "schema completion must not erase host service recovery intent")

    def test_admission_only_or_fresh_active_writers_cannot_create_ddl_marker(self):
        live = {"ok": True, "migration_leaf_set": [LEAF_0078], "migration_plan": [], "database_identity_sha256": "d" * 64}
        path, payload = self.artifact(live, {})
        marker = Path(self.tmp.name) / "restricted-recovery.json"
        module = "stable.management.commands.ensure_historical_calendar_recovery_intent"
        for active in (False, True):
            with self.subTest(active=active), \
                 patch(module + ".database_vendor_contract", return_value={"ok": True}), \
                 patch(module + ".collect_handoff_preflight", return_value=live), \
                 patch.object(handoff, "collect_handoff_preflight", return_value=live), \
                 patch.object(handoff, "collect_writer_activity", return_value={"ok": not active}):
                with self.assertRaises(CommandError):
                    call_command("ensure_historical_calendar_recovery_intent", marker_path=str(marker),
                                 artifact_path=str(path), artifact_sha256=payload["artifact_sha256"],
                                 candidate_commit="b" * 40, candidate_image_id="sha256:" + "c" * 64,
                                 database_identity_sha256="d" * 64, attempt_mode="required", stdout=StringIO())
                self.assertFalse(marker.exists())

    def test_same_schema_requires_present_unchanged_backup(self):
        sha = self.write_manifest()
        self.assertEqual(recovery.verify_manifest(self.manifest_path, sha, self.bindings)["operation"], "same-schema")
        original = self.backup.read_bytes()
        # Keep the old inode allocated; immediate unlink/recreate may reuse
        # it on Linux and would not actually exercise identity replacement.
        self.backup.rename(self.backup.with_suffix(".preserved"))
        with self.assertRaises(OSError):
            recovery.verify_manifest(self.manifest_path, sha, self.bindings)
        self.backup.write_bytes(original)
        self.backup.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "file identity changed"):
            recovery.verify_manifest(self.manifest_path, sha, self.bindings)

    def test_manifest_rejects_wrong_database_candidate_source_and_other_release(self):
        for changes in (
            {"database_identity_sha256": "2" * 64}, {"candidate_commit": "3" * 40},
            {"candidate_image_id": "sha256:" + "4" * 64}, {"source_leaf": "stable.0076_other"},
            {"source_leaf": LEAF_0077}, {"release_id": "5" * 64},
            {"schema_version": "release-0077-verified-backup-recovery/v1"},
        ):
            with self.subTest(changes=changes):
                sha = self.write_manifest(**changes)
                with self.assertRaises(ValueError):
                    recovery.verify_manifest(self.manifest_path, sha, self.bindings)

    def test_admission_v4_and_0077_target_are_rejected(self):
        path = self.directory / "origin.json"
        payload = {
            "schema_version": "migration-history-repair-preflight/v5", "target_leaf_set": [LEAF_0078],
            "migration_contract_sha256": "50c421f3167a8c2c8f1613a0597ad7ee196c249fc18bf7eed0de7b9cd2f80906",
            "database_identity_sha256": "d" * 64, "writer_activity": {"ok": True},
            "preflight": {"ok": True, "database_identity_sha256": "d" * 64, "migration_leaf_set": [LEAF_0078], "migration_plan": []},
        }
        for changes in ({}, {"schema_version": "migration-history-repair-preflight/v4"}, {"target_leaf_set": [LEAF_0077]}):
            value = {**payload, **changes}
            sha = recovery.digest(value)
            value["artifact_sha256"] = sha
            path.unlink(missing_ok=True)
            recovery.publish_once(path, value)
            if not changes:
                recovery.verify_admission(path, sha, {})
            else:
                with self.assertRaisesRegex(ValueError, "binding mismatch"):
                    recovery.verify_admission(path, sha, {})

    def test_private_files_symlinks_and_no_clobber(self):
        path = self.directory / "proof.json"
        identity = recovery.publish_once(path, {"proof": True})
        self.assertEqual(recovery.publish_once(path, {"proof": True}), identity)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            recovery.publish_once(path, {"proof": False})
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "mode-0600"):
            recovery.read_json(path)
        path.unlink()
        path.symlink_to(self.backup)
        with self.assertRaises(OSError):
            recovery.read_json(path)

    def test_writable_or_symlink_ancestor_is_rejected(self):
        path = self.directory / "proof.json"
        recovery.publish_once(path, {"proof": True})
        self.root.chmod(0o770)
        try:
            with self.assertRaisesRegex(ValueError, "ancestor is writable"):
                recovery.read_json(path)
        finally:
            self.root.chmod(0o700)
        link = Path(self.tmp.name) / "linked"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            recovery.read_json(link / self.release_id / "proof.json")

    def test_intent_and_active_pointer_bind_exact_file_identity(self):
        sha = self.write_manifest()
        path = self.directory / "intent.json"
        payload = {"schema_version": "release-0078-prepared-intent/v1", **self.bindings,
                   "manifest_sha256": sha, "source_leaf": LEAF_0078,
                   "restore_services": self.services, "config_sha256": "f" * 64, "initial_lock_sha256": "1" * 64}
        identity = recovery.publish_once(path, payload)
        pointer = self.root / "active.json"
        recovery.publish_once(pointer, {"release_id": self.release_id, "intent_path": str(path), "intent_file": identity})
        self.assertEqual(recovery.verify_intent(path, identity["sha256"], self.bindings)[0], payload)
        # A retry's new lock is not part of this immutable artifact's identity.
        with patch.dict(os.environ, {"DEPLOYMENT_LOCK_TOKEN": "new-unrelated-lease"}):
            recovery.verify_intent(path, identity["sha256"], self.bindings)
        pointer.unlink()
        recovery.publish_once(pointer, {"release_id": "0" * 64, "intent_path": str(path), "intent_file": identity})
        with self.assertRaisesRegex(ValueError, "active pointer identity"):
            recovery.verify_intent(path, identity["sha256"], self.bindings)
