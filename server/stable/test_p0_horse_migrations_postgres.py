from __future__ import annotations

from datetime import date

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, skipUnlessDBFeature


@skipUnlessDBFeature("supports_transactions")
class P0HorseMigrationPostgresTests(TransactionTestCase):
    migrate_from = [("stable", "0048_raceeventrunner_external_runner_identity")]
    migrate_fields = [("stable", "0049_horse_career_history")]
    migrate_backfill = [("stable", "0050_backfill_horse_career_history")]
    migrate_indexes = [("stable", "0051_horse_career_history_indexes")]
    migrate_to = [("stable", "0052_horse_career_source_authority")]

    def setUp(self):
        super().setUp()
        if connection.vendor != "postgresql":
            self.skipTest("requires PostgreSQL migration DDL semantics")
        self._migrate(self.migrate_from)
        old_apps = self._apps(self.migrate_from)
        TermEntry = old_apps.get_model("stable", "TermEntry")
        HorseProfile = old_apps.get_model("stable", "HorseProfile")
        HorseRaceRecord = old_apps.get_model("stable", "HorseRaceRecord")
        term = TermEntry.objects.create(
            term_type="horse",
            source_language="en",
            source_ja="Migration Executor Horse",
            target_zh="迁移执行器马",
            racing_region="united_kingdom",
            is_active=True,
        )
        profile = HorseProfile.objects.create(
            primary_term_id=term.pk,
            original_name="Migration Executor Horse",
            completeness_status="complete_profile_full",
        )
        self.profile_id = profile.pk
        self.started_record_id = HorseRaceRecord.objects.create(
            horse_profile_id=profile.pk,
            race_name="Migration Exact Race",
            race_year=2024,
            race_date=date(2024, 6, 1),
            result_status="won",
            idempotency_key="migration-exact",
        ).pk
        self.nonstart_record_id = HorseRaceRecord.objects.create(
            horse_profile_id=profile.pk,
            race_name="Migration Year Race",
            race_year=2023,
            result_status="scratched",
            idempotency_key="migration-year",
        ).pk

    def tearDown(self):
        self._migrate(self.migrate_to)
        super().tearDown()

    def test_postgres_forward_and_replay_split_data_from_index_ddl(self):
        self._migrate(self.migrate_fields)
        fields_apps = self._apps(self.migrate_fields)
        FieldsProfile = fields_apps.get_model("stable", "HorseProfile")
        FieldsRecord = fields_apps.get_model("stable", "HorseRaceRecord")
        fields_profile = FieldsProfile.objects.get(pk=self.profile_id)
        fields_record = FieldsRecord.objects.get(pk=self.started_record_id)
        self.assertEqual(fields_profile.career_history_status, "not_started")
        self.assertEqual(fields_record.start_status, "unconfirmed")
        self.assertEqual(fields_record.race_date_precision, "unknown")
        self._assert_career_indexes_absent(FieldsProfile, FieldsRecord)

        self._migrate(self.migrate_backfill)
        backfill_apps = self._apps(self.migrate_backfill)
        HorseProfile = backfill_apps.get_model("stable", "HorseProfile")
        HorseRaceRecord = backfill_apps.get_model("stable", "HorseRaceRecord")

        profile = HorseProfile.objects.get(pk=self.profile_id)
        started = HorseRaceRecord.objects.get(pk=self.started_record_id)
        nonstart = HorseRaceRecord.objects.get(pk=self.nonstart_record_id)
        self.assertEqual(profile.career_history_status, "partial")
        self.assertEqual(profile.collected_start_count, 1)
        self.assertEqual(profile.linked_race_event_count, 0)
        self.assertEqual(profile.unlinked_race_record_count, 2)
        self.assertEqual(profile.career_history_gap_count, 1)
        self.assertEqual(
            profile.career_history_gap_reasons,
            ["source_total_unknown"],
        )
        self.assertEqual(started.start_status, "started")
        self.assertEqual(started.race_date_precision, "exact")
        self.assertEqual(nonstart.start_status, "did_not_start")
        self.assertEqual(nonstart.race_date_precision, "year")
        self._assert_career_indexes_absent(HorseProfile, HorseRaceRecord)

        self._migrate(self.migrate_indexes)
        apps_0051 = self._apps(self.migrate_indexes)
        HorseProfile = apps_0051.get_model("stable", "HorseProfile")
        HorseRaceRecord = apps_0051.get_model("stable", "HorseRaceRecord")
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor,
                HorseRaceRecord._meta.db_table,
            )
            profile_indexes = connection.introspection.get_constraints(
                cursor,
                HorseProfile._meta.db_table,
            )
        self.assertTrue(profile_indexes["horse_career_region_idx"]["index"])
        self.assertTrue(constraints["horse_record_start_idx"]["index"])
        self.assertTrue(constraints["horse_record_canon_idx"]["index"])
        self.assertTrue(constraints["uq_horse_record_canonical"]["unique"])

        HorseRaceRecord.objects.filter(pk=self.started_record_id).update(
            canonical_race_key="same-race",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HorseRaceRecord.objects.filter(pk=self.nonstart_record_id).update(
                canonical_race_key="same-race",
            )

        HorseProfile.objects.filter(pk=self.profile_id).update(
            career_history_status="complete",
            completeness_status="complete_profile_full",
        )
        self._migrate(self.migrate_to)
        final_apps = self._apps(self.migrate_to)
        final_profile = final_apps.get_model(
            "stable",
            "HorseProfile",
        ).objects.get(pk=self.profile_id)
        self.assertEqual(final_profile.career_record_authority_status, "unknown")
        self.assertEqual(final_profile.career_history_status, "needs_review")
        self.assertEqual(
            final_profile.completeness_status,
            "complete_pedigree_2gen",
        )

        executor = MigrationExecutor(connection)
        self.assertEqual(
            executor.loader.graph.leaf_nodes("stable"),
            self.migrate_to,
        )

        self._migrate(self.migrate_from)
        self._migrate(self.migrate_to)
        replay_apps = self._apps(self.migrate_to)
        replay_profile = replay_apps.get_model(
            "stable",
            "HorseProfile",
        ).objects.get(pk=self.profile_id)
        self.assertEqual(replay_profile.career_history_status, "partial")
        self.assertEqual(replay_profile.collected_start_count, 1)
        self.assertEqual(replay_profile.career_record_authority_status, "unknown")

    @staticmethod
    def _migrate(targets):
        MigrationExecutor(connection).migrate(targets)

    @staticmethod
    def _apps(targets):
        return MigrationExecutor(connection).loader.project_state(targets).apps

    def _assert_career_indexes_absent(self, HorseProfile, HorseRaceRecord):
        with connection.cursor() as cursor:
            record_constraints = connection.introspection.get_constraints(
                cursor,
                HorseRaceRecord._meta.db_table,
            )
            profile_constraints = connection.introspection.get_constraints(
                cursor,
                HorseProfile._meta.db_table,
            )
        self.assertNotIn("horse_career_region_idx", profile_constraints)
        self.assertNotIn("horse_record_start_idx", record_constraints)
        self.assertNotIn("horse_record_canon_idx", record_constraints)
        self.assertNotIn("uq_horse_record_canonical", record_constraints)
