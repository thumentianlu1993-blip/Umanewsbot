"""
Migration 0055: Add (horse_profile, normalized_finish_position) index.

Only creates the database index. Uses atomic=False and vendor-aware operation
(AddIndexConcurrently for PostgreSQL, plain AddIndex for SQLite) so the index
can be built without locking the table on PostgreSQL.
"""

from django.db import connection, migrations, models


def _get_add_index_operation():
    """Return AddIndexConcurrently on PostgreSQL, plain AddIndex on SQLite."""
    index = models.Index(
        fields=["horse_profile", "normalized_finish_position"],
        name="horse_record_norm_finish_idx",
    )
    if connection.vendor == "postgresql":
        from django.contrib.postgres.operations import AddIndexConcurrently

        return AddIndexConcurrently(
            model_name="horseracerecord",
            index=index,
        )
    return migrations.AddIndex(
        model_name="horseracerecord",
        index=index,
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("stable", "0054_race_field_normalization_schema"),
    ]

    operations = [
        _get_add_index_operation(),
    ]
