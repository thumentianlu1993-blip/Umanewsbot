from datetime import timedelta
from django.test import TestCase, override_settings
from stable import models
from stable import test_race_multisource_identity as fixtures
from stable.services.race_data_sync_enrollment import attach_multisource_observation
from stable.services.race_data_sync_repair import (
    prepare_multisource_conversion,
    apply_multisource_conversion,
    verify_multisource_conversion,
)


@override_settings(
    UMANEWS_RELEASE_COMMIT="a" * 40,
    RACE_DATA_MULTISOURCE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED=True,
    RACE_DATA_SYNC_LIFECYCLE_APPLY_ENABLED=True,
    RACE_DATA_SYNC_ENABLED_PROVIDERS=("jra",),
    RACE_DATA_SYNC_ENABLED_REGIONS=("japan_jra",),
)
class ConversionTests(TestCase):
    def setUp(self):
        fixtures.IdentityTests.setUp(self)
        fixtures.IdentityTests.anchor(self)
        self.value = fixtures.observation()
        self.assertEqual(
            attach_multisource_observation(
                self.value, policy=self.policy, now=fixtures.NOW
            ).action,
            "acquired",
        )
        self.enrollment = models.RaceDataSyncEnrollment.objects.get(event=self.event)
        self.enrollment.source_bindings.all().delete()
        self.enrollment.authority_version = 1
        self.enrollment.source_set_manifest = {}
        self.enrollment.source_set_generation = 0
        self.enrollment.source_set_digest = ""
        self.enrollment.save()
        self.manifest = prepare_multisource_conversion(
            observations=[self.value],
            policy=self.policy,
            now=fixtures.NOW,
            code_sha="a" * 40,
        )

    def run_manifest(self, apply=False):
        return apply_multisource_conversion(
            manifest=self.manifest,
            expected_sha256=self.manifest["manifest_sha256"],
            policy=self.policy,
            now=fixtures.NOW,
            code_sha="a" * 40,
            apply=apply,
        )

    def test_dry_run_closed_apply_idempotence_and_independent_verify(self):
        source = self.enrollment.source_identity
        old_digest = source.registry_digest
        self.assertEqual(self.run_manifest()[0]["action"], "dry_run")
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.authority_version, 1)
        with override_settings(
            RACE_DATA_SYNC_ENABLED=False,
            RACE_DATA_MULTISOURCE_APPLY_ENABLED=False,
            RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
            RACE_DATA_SYNC_ALLOW_NETWORK=False,
            RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=False,
        ):
            self.assertEqual(self.run_manifest(True)[0]["action"], "converted")
            self.assertEqual(self.run_manifest(True)[0]["action"], "replay")
        self.assertTrue(
            verify_multisource_conversion(manifest=self.manifest)[0]["verified"]
        )
        source.refresh_from_db()
        self.assertEqual(source.registry_digest, old_digest)
        self.assertEqual(
            models.RaceEventProjectionControl.objects.get(
                event=self.event
            ).owner_generation,
            1,
        )

    def test_open_runtime_and_snapshot_drift_and_published_history_block(self):
        with self.assertRaisesMessage(ValueError, "conversion_requires_closed_runtime"):
            self.run_manifest(True)
        self.event.original_name = "Changed"
        self.event.save()
        with self.assertRaisesMessage(ValueError, "conversion_snapshot_drift"):
            self.run_manifest()
        self.event.result_confirmed_at = fixtures.NOW
        self.event.save()
        with self.assertRaisesMessage(ValueError, "conversion_event_ineligible"):
            prepare_multisource_conversion(
                observations=[self.value],
                policy=self.policy,
                now=fixtures.NOW,
                code_sha="a" * 40,
            )

    def test_digest_expiry_and_wrong_code_block(self):
        self.manifest["entries"][0]["before"]["owner_generation"] += 1
        with self.assertRaisesMessage(ValueError, "conversion_manifest_invalid"):
            self.run_manifest()

    def test_apply_failure_rolls_back_single_event(self):
        from unittest.mock import patch

        with override_settings(
            RACE_DATA_SYNC_ENABLED=False,
            RACE_DATA_MULTISOURCE_APPLY_ENABLED=False,
            RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
            RACE_DATA_SYNC_ALLOW_NETWORK=False,
            RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=False,
        ), patch(
            "stable.services.race_data_sync_enrollment._multisource_manifest",
            side_effect=RuntimeError("injected"),
        ):
            with self.assertRaisesMessage(RuntimeError, "injected"):
                self.run_manifest(True)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.authority_version, 1)
        self.assertFalse(self.enrollment.source_bindings.exists())

    def test_lock_wait_expiry_leaves_legacy_unchanged(self):
        from unittest.mock import patch
        from stable.services.race_data_sync_enrollment import _lock_multisource_event

        def delayed(event_id):
            rows = _lock_multisource_event(event_id)
            clock = patch(
                "django.utils.timezone.now",
                return_value=fixtures.NOW + timedelta(minutes=31),
            )
            clock.start()
            self.addCleanup(clock.stop)
            return rows

        with override_settings(
            RACE_DATA_SYNC_ENABLED=False,
            RACE_DATA_MULTISOURCE_APPLY_ENABLED=False,
            RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
            RACE_DATA_SYNC_ALLOW_NETWORK=False,
            RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=False,
        ), patch(
            "stable.services.race_data_sync_enrollment._lock_multisource_event",
            side_effect=delayed,
        ):
            with self.assertRaisesMessage(ValueError, "conversion_manifest_expired"):
                self.run_manifest(True)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.authority_version, 1)

    def test_verify_rejects_binding_and_runtime_sha_drift(self):
        with override_settings(UMANEWS_RELEASE_COMMIT="b" * 40):
            with self.assertRaisesMessage(ValueError, "conversion_code_sha_invalid"):
                self.run_manifest()
        with override_settings(
            RACE_DATA_SYNC_ENABLED=False,
            RACE_DATA_MULTISOURCE_APPLY_ENABLED=False,
            RACE_DATA_SYNC_SCHEDULER_ENABLED=False,
            RACE_DATA_SYNC_ALLOW_NETWORK=False,
            RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED=False,
        ):
            self.run_manifest(True)
        binding = self.enrollment.source_bindings.get()
        binding.contract_digest = "0" * 64
        binding.save()
        self.assertFalse(
            verify_multisource_conversion(manifest=self.manifest)[0]["verified"]
        )
