from __future__ import annotations

import hashlib
import importlib.util
import inspect
import os
from pathlib import Path
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase


REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_BUILDER = REPO_ROOT / "scripts" / "build_race_live_rollback_env.py"
ONE_SHOT_WRAPPER = (
    REPO_ROOT / "scripts" / "run_race_live_rollback_one_shot.py"
)


def _load_script(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"无法加载 {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class RaceLiveFilteredRollbackEnvironmentTests(SimpleTestCase):
    maxDiff = None

    def _source_env(self) -> str:
        return "\n".join(
            (
                "POSTGRES_DB=umanews",
                "POSTGRES_USER=umanews",
                "POSTGRES_PASSWORD=database-secret-value",
                "POSTGRES_HOST=db",
                "POSTGRES_PORT=5432",
                "POSTGRES_CONNECT_TIMEOUT=5",
                "POSTGRES_SSLMODE=prefer",
                "THE_RACING_API_PASSWORD=must-not-copy",
                "EMAIL_HOST_PASSWORD=must-not-copy",
                "RACE_LIVE_ALERT_NOTIFY_EMAILS=must-not-copy@example.test",
                "CELERY_BROKER_URL=redis://redis:6379/0",
                "",
            )
        )

    def test_generator_outputs_only_db_allowlist_and_fixed_safe_runtime(self):
        self.assertTrue(
            ENV_BUILDER.is_file(),
            "filtered rollback env 生成器尚未实现",
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "production.env"
            output = root / "rollback.filtered.env"
            digest_file = root / "rollback.filtered.env.sha256"
            source.write_text(self._source_env(), encoding="utf-8")
            source.chmod(0o600)

            completed = subprocess.run(
                (
                    sys.executable,
                    str(ENV_BUILDER),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--sha256-output",
                    str(digest_file),
                ),
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                env={"PATH": os.environ.get("PATH", "")},
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(output.is_file())
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            values = _parse_env(output)
            for key in (
                "POSTGRES_DB",
                "POSTGRES_USER",
                "POSTGRES_PASSWORD",
                "POSTGRES_HOST",
                "POSTGRES_PORT",
                "POSTGRES_CONNECT_TIMEOUT",
                "POSTGRES_SSLMODE",
            ):
                self.assertEqual(
                    values[key],
                    _parse_env(source)[key],
                )
            self.assertEqual(values["DEBUG"], "false")
            self.assertEqual(values["DB_ENGINE"], "postgres")
            self.assertEqual(values["POSTGRES_CONN_MAX_AGE"], "0")
            self.assertEqual(values["CELERY_BROKER_URL"], "memory://")
            self.assertEqual(
                values["CELERY_RESULT_BACKEND"],
                "cache+memory://",
            )
            self.assertEqual(
                values["EMAIL_BACKEND"],
                "django.core.mail.backends.dummy.EmailBackend",
            )
            self.assertEqual(values["RACE_LIVE_RUNNER_MODE"], "disabled")
            self.assertEqual(
                values["RACE_LIVE_SCHEDULER_ENABLED"],
                "false",
            )
            self.assertEqual(values["RACE_LIVE_MONITOR_ENABLED"], "false")
            forbidden = (
                "THE_RACING_API_",
                "RACE_LIVE_TRA_SECRET_ENV_FILE",
                "EMAIL_HOST",
                "RACE_LIVE_ALERT_NOTIFY_EMAILS",
                "AUTOMATION_WARNING_NOTIFY_EMAILS",
                "TRANSLATION_FAILURE_NOTIFY_EMAILS",
            )
            self.assertFalse(
                any(
                    key == prefix or key.startswith(prefix)
                    for key in values
                    for prefix in forbidden
                )
            )
            actual_digest = hashlib.sha256(output.read_bytes()).hexdigest()
            self.assertEqual(
                digest_file.read_text(encoding="utf-8").split()[0],
                actual_digest,
            )
            combined_output = completed.stdout + completed.stderr
            self.assertNotIn("database-secret-value", combined_output)
            self.assertNotIn("must-not-copy", combined_output)

    def test_generator_rejects_duplicate_empty_and_expanding_db_values(self):
        self.assertTrue(
            ENV_BUILDER.is_file(),
            "filtered rollback env 生成器尚未实现",
        )
        invalid_suffixes = (
            "\nPOSTGRES_HOST=second-db\n",
            "\nPOSTGRES_SSLMODE=\n",
            "\nPOSTGRES_PASSWORD=${DB_PASSWORD}\n",
            "\nPOSTGRES_USER=$(id)\n",
        )
        for suffix in invalid_suffixes:
            with self.subTest(suffix=suffix):
                with TemporaryDirectory() as directory:
                    root = Path(directory)
                    source = root / "production.env"
                    output = root / "rollback.filtered.env"
                    digest_file = root / "rollback.filtered.env.sha256"
                    source.write_text(
                        self._source_env() + suffix,
                        encoding="utf-8",
                    )
                    source.chmod(0o600)
                    completed = subprocess.run(
                        (
                            sys.executable,
                            str(ENV_BUILDER),
                            "--input",
                            str(source),
                            "--output",
                            str(output),
                            "--sha256-output",
                            str(digest_file),
                        ),
                        cwd=REPO_ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                        env={"PATH": os.environ.get("PATH", "")},
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertFalse(output.exists())
                    self.assertFalse(digest_file.exists())


class RaceLiveRollbackOneShotWrapperTests(SimpleTestCase):
    def _module(self):
        self.assertTrue(
            ONE_SHOT_WRAPPER.is_file(),
            "pre-Django rollback one-shot wrapper 尚未实现",
        )
        return _load_script(
            ONE_SHOT_WRAPPER,
            "race_live_rollback_one_shot_contract",
        )

    def test_immutable_image_id_accepts_only_full_local_sha256_id(self):
        module = self._module()
        validator = getattr(module, "validate_immutable_image_id", None)
        self.assertTrue(
            callable(validator),
            "immutable Docker image ID validator 尚未实现",
        )
        valid = "sha256:" + ("a" * 64)
        self.assertEqual(validator(valid), valid)
        for value in (
            "umanewsbot:prod",
            "umanewsbot@sha256:" + ("a" * 64),
            "sha256:" + ("a" * 63),
            "SHA256:" + ("a" * 64),
            "",
        ):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError, PermissionError)):
                    validator(value)

    def test_pre_django_environment_validator_rejects_secrets_and_real_celery(self):
        module = self._module()
        validator = getattr(
            module,
            "validate_pre_django_environment",
            None,
        )
        self.assertTrue(
            callable(validator),
            "pre-Django secret-free environment validator 尚未实现",
        )
        safe = {
            "POSTGRES_DB": "umanews",
            "POSTGRES_USER": "umanews",
            "POSTGRES_PASSWORD": "db-password-is-required",
            "POSTGRES_HOST": "db",
            "POSTGRES_PORT": "5432",
            "POSTGRES_CONNECT_TIMEOUT": "5",
            "POSTGRES_SSLMODE": "prefer",
            "DB_ENGINE": "postgres",
            "DEBUG": "false",
            "SECRET_KEY": "fixed-race-live-rollback-validation-key",
            "POSTGRES_CONN_MAX_AGE": "0",
            "POSTGRES_APPLICATION_NAME": "race-live-rollback-one-shot",
            "CELERY_BROKER_URL": "memory://",
            "CELERY_RESULT_BACKEND": "cache+memory://",
            "EMAIL_BACKEND": "django.core.mail.backends.dummy.EmailBackend",
            "RACE_LIVE_RUNNER_MODE": "disabled",
            "RACE_LIVE_SCHEDULER_ENABLED": "false",
            "RACE_LIVE_MONITOR_ENABLED": "false",
        }
        self.assertIsNone(validator(safe))

        unsafe_cases = (
            {"THE_RACING_API_PASSWORD": "source-secret"},
            {"RACE_LIVE_TRA_SECRET_ENV_FILE": "/run/secrets/tra.env"},
            {"EMAIL_HOST_PASSWORD": "smtp-secret"},
            {"RACE_LIVE_ALERT_NOTIFY_EMAILS": "ops@example.test"},
            {"CELERY_BROKER_URL": "redis://redis:6379/0"},
            {"CELERY_RESULT_BACKEND": "redis://redis:6379/0"},
            {"RACE_LIVE_RUNNER_MODE": "the_racing_api_free"},
            {"RACE_LIVE_SCHEDULER_ENABLED": "true"},
            {"RACE_LIVE_MONITOR_ENABLED": "true"},
            {"DB_ENGINE": "sqlite"},
            {"SECRET_KEY": "some-other-nonempty-secret"},
        )
        for override in unsafe_cases:
            with self.subTest(override=override):
                values = dict(safe)
                values.update(override)
                with self.assertRaises((TypeError, ValueError, PermissionError)):
                    validator(values)

    def test_main_checks_secure_files_then_runs_exact_command_from_server(self):
        module = self._module()
        image_id = "sha256:" + ("a" * 64)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            env_path = root / "rollback.filtered.env"
            env_path.write_text(
                "\n".join(
                    (
                        "POSTGRES_DB=umanews",
                        "POSTGRES_USER=umanews",
                        "POSTGRES_PASSWORD=db-password",
                        "POSTGRES_HOST=db",
                        "POSTGRES_PORT=5432",
                        "POSTGRES_CONNECT_TIMEOUT=5",
                        "POSTGRES_SSLMODE=prefer",
                        "DB_ENGINE=postgres",
                        "DEBUG=false",
                        "SECRET_KEY=fixed-race-live-rollback-validation-key",
                        "POSTGRES_CONN_MAX_AGE=0",
                        "POSTGRES_APPLICATION_NAME=race-live-rollback-one-shot",
                        "CELERY_BROKER_URL=memory://",
                        "CELERY_RESULT_BACKEND=cache+memory://",
                        "EMAIL_BACKEND=django.core.mail.backends.dummy.EmailBackend",
                        "RACE_LIVE_RUNNER_MODE=disabled",
                        "RACE_LIVE_SCHEDULER_ENABLED=false",
                        "RACE_LIVE_MONITOR_ENABLED=false",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            env_path.chmod(0o600)
            env_digest = hashlib.sha256(env_path.read_bytes()).hexdigest()
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                (
                    '{"event_id":924,'
                    f'"filtered_env_sha256":"{env_digest}",'
                    f'"reviewed_release_image_id":"{image_id}"'
                    "}"
                ),
                encoding="utf-8",
            )
            manifest_path.chmod(0o600)
            manifest_digest = hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest()
            calls = []
            isolated_environ = {}

            result = module.main(
                [
                    "--env-file",
                    str(env_path),
                    "--manifest",
                    str(manifest_path),
                    "--actual-image-id",
                    image_id,
                    "--expected-filtered-env-sha256",
                    env_digest,
                    "--expected-manifest-sha256",
                    manifest_digest,
                    "--command",
                    "validate",
                ],
                environ=isolated_environ,
                django_setup=lambda: calls.append(
                    ("setup", Path.cwd())
                ),
                command_runner=lambda *args, **kwargs: calls.append(
                    ("command", args, kwargs, Path.cwd())
                ),
            )

            self.assertEqual(result, 0)
            self.assertEqual(
                isolated_environ["DJANGO_SETTINGS_MODULE"],
                "app.settings",
            )
            expected_server = REPO_ROOT / "server"
            self.assertEqual(
                calls,
                [
                    ("setup", expected_server),
                    (
                        "command",
                        ("validate_race_live_rollback_target",),
                        {
                            "manifest": str(manifest_path),
                            "expected_manifest_sha256": manifest_digest,
                        },
                        expected_server,
                    ),
                ],
            )

            for mutation in (
                "env-mode",
                "manifest-symlink",
                "manifest-digest",
            ):
                with self.subTest(mutation=mutation):
                    calls.clear()
                    if mutation == "env-mode":
                        env_path.chmod(0o644)
                        selected_manifest = manifest_path
                    else:
                        env_path.chmod(0o600)
                        if mutation == "manifest-symlink":
                            selected_manifest = root / "manifest-link.json"
                            selected_manifest.symlink_to(manifest_path)
                        else:
                            selected_manifest = manifest_path
                    expected_manifest_digest = (
                        "d" * 64
                        if mutation == "manifest-digest"
                        else manifest_digest
                    )
                    with self.assertRaises(
                        (ValueError, PermissionError)
                    ):
                        module.main(
                            [
                                "--env-file",
                                str(env_path),
                                "--manifest",
                                str(selected_manifest),
                                "--actual-image-id",
                                image_id,
                                "--expected-filtered-env-sha256",
                                env_digest,
                                "--expected-manifest-sha256",
                                expected_manifest_digest,
                                "--command",
                                "validate",
                            ],
                            environ={},
                            django_setup=lambda: calls.append("setup"),
                            command_runner=lambda *args, **kwargs: calls.append(
                                "command"
                            ),
                        )
                    self.assertEqual(calls, [])

    def test_wrapper_runs_preflight_before_importing_or_initializing_django(self):
        module = self._module()
        main = getattr(module, "main", None)
        self.assertTrue(callable(main), "rollback one-shot main 尚未实现")
        source = inspect.getsource(main)
        preflight_index = source.find("validate_pre_django_environment(")
        django_markers = tuple(
            index
            for marker in (
                "DJANGO_SETTINGS_MODULE",
                "django.setup(",
                "execute_from_command_line(",
                "call_command(",
            )
            if (index := source.find(marker)) >= 0
        )
        self.assertGreaterEqual(preflight_index, 0)
        self.assertTrue(django_markers, "wrapper 未显式加载受控 Django 命令")
        self.assertLess(preflight_index, min(django_markers))

    def test_manifest_identity_contract_binds_image_and_filtered_env(self):
        module = self._module()
        validator = getattr(
            module,
            "validate_rollback_manifest_identity",
            None,
        )
        self.assertTrue(
            callable(validator),
            "rollback manifest identity validator 尚未实现",
        )
        manifest = {
            "reviewed_release_image_id": "sha256:" + ("a" * 64),
            "filtered_env_sha256": "b" * 64,
        }
        self.assertIsNone(
            validator(
                manifest=manifest,
                actual_image_id="sha256:" + ("a" * 64),
                expected_filtered_env_sha256="b" * 64,
                expected_manifest_sha256="c" * 64,
            )
        )
        for key, value in (
            ("actual_image_id", "sha256:" + ("d" * 64)),
            ("expected_filtered_env_sha256", "d" * 64),
        ):
            kwargs = {
                "manifest": manifest,
                "actual_image_id": "sha256:" + ("a" * 64),
                "expected_filtered_env_sha256": "b" * 64,
                "expected_manifest_sha256": "c" * 64,
            }
            kwargs[key] = value
            with self.subTest(key=key):
                with self.assertRaises((TypeError, ValueError, PermissionError)):
                    validator(**kwargs)
