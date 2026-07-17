from django.db import migrations


PROJECTION_GUARD_FUNCTION = "stable_validate_race_projection_revision_links"
PROJECTION_GUARD_TRIGGER = "stable_race_projection_revision_links_guard"
REVISION_LINK_FUNCTION = "stable_validate_race_revision_supersedes"
REVISION_LINK_TRIGGER = "stable_race_revision_supersedes_guard"
REVISION_IMMUTABLE_FUNCTION = "stable_protect_race_revision_identity"
REVISION_IMMUTABLE_TRIGGER = "stable_race_revision_identity_immutable_guard"


def install_revision_link_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        f"""
        CREATE OR REPLACE FUNCTION {PROJECTION_GUARD_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            linked_event_id bigint;
            linked_kind varchar(16);
            linked_revision_no bigint;
        BEGIN
            IF NEW.current_racecard_revision_id IS NOT NULL THEN
                SELECT event_id, kind, revision_no
                  INTO linked_event_id, linked_kind, linked_revision_no
                  FROM stable_raceeventrevision
                 WHERE id = NEW.current_racecard_revision_id;
                IF NOT FOUND
                   OR linked_event_id <> NEW.event_id
                   OR linked_kind <> 'racecard'
                   OR linked_revision_no >= NEW.next_racecard_revision_no THEN
                    RAISE EXCEPTION
                        'invalid current racecard revision link for projection control %%', NEW.id
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            IF NEW.last_known_good_racecard_revision_id IS NOT NULL THEN
                SELECT event_id, kind, revision_no
                  INTO linked_event_id, linked_kind, linked_revision_no
                  FROM stable_raceeventrevision
                 WHERE id = NEW.last_known_good_racecard_revision_id;
                IF NOT FOUND
                   OR linked_event_id <> NEW.event_id
                   OR linked_kind <> 'racecard'
                   OR linked_revision_no >= NEW.next_racecard_revision_no THEN
                    RAISE EXCEPTION
                        'invalid last-known-good racecard revision link for projection control %%', NEW.id
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            IF NEW.current_result_revision_id IS NOT NULL THEN
                SELECT event_id, kind, revision_no
                  INTO linked_event_id, linked_kind, linked_revision_no
                  FROM stable_raceeventrevision
                 WHERE id = NEW.current_result_revision_id;
                IF NOT FOUND
                   OR linked_event_id <> NEW.event_id
                   OR linked_kind <> 'result'
                   OR linked_revision_no >= NEW.next_result_revision_no THEN
                    RAISE EXCEPTION
                        'invalid current result revision link for projection control %%', NEW.id
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            IF NEW.last_known_good_result_revision_id IS NOT NULL THEN
                SELECT event_id, kind, revision_no
                  INTO linked_event_id, linked_kind, linked_revision_no
                  FROM stable_raceeventrevision
                 WHERE id = NEW.last_known_good_result_revision_id;
                IF NOT FOUND
                   OR linked_event_id <> NEW.event_id
                   OR linked_kind <> 'result'
                   OR linked_revision_no >= NEW.next_result_revision_no THEN
                    RAISE EXCEPTION
                        'invalid last-known-good result revision link for projection control %%', NEW.id
                        USING ERRCODE = '23514';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    schema_editor.execute(
        f"""
        CREATE CONSTRAINT TRIGGER {PROJECTION_GUARD_TRIGGER}
        AFTER INSERT OR UPDATE OF
            event_id,
            next_racecard_revision_no,
            next_result_revision_no,
            current_racecard_revision_id,
            last_known_good_racecard_revision_id,
            current_result_revision_id,
            last_known_good_result_revision_id
        ON stable_raceeventprojectioncontrol
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION {PROJECTION_GUARD_FUNCTION}();
        """
    )

    schema_editor.execute(
        f"""
        CREATE OR REPLACE FUNCTION {REVISION_LINK_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            linked_event_id bigint;
            linked_kind varchar(16);
            linked_revision_no bigint;
        BEGIN
            IF NEW.supersedes_id IS NULL THEN
                RETURN NEW;
            END IF;

            SELECT event_id, kind, revision_no
              INTO linked_event_id, linked_kind, linked_revision_no
              FROM stable_raceeventrevision
             WHERE id = NEW.supersedes_id;

            IF NOT FOUND
               OR linked_event_id <> NEW.event_id
               OR linked_kind <> NEW.kind
               OR linked_revision_no >= NEW.revision_no THEN
                RAISE EXCEPTION
                    'invalid supersedes revision link for revision %%', NEW.id
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    schema_editor.execute(
        f"""
        CREATE CONSTRAINT TRIGGER {REVISION_LINK_TRIGGER}
        AFTER INSERT OR UPDATE OF event_id, kind, revision_no, supersedes_id
        ON stable_raceeventrevision
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION {REVISION_LINK_FUNCTION}();
        """
    )

    schema_editor.execute(
        f"""
        CREATE OR REPLACE FUNCTION {REVISION_IMMUTABLE_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.event_id IS DISTINCT FROM NEW.event_id
               OR OLD.kind IS DISTINCT FROM NEW.kind
               OR OLD.revision_no IS DISTINCT FROM NEW.revision_no
               OR OLD.phase IS DISTINCT FROM NEW.phase
               OR OLD.content_sha256 IS DISTINCT FROM NEW.content_sha256
               OR OLD.source_authority IS DISTINCT FROM NEW.source_authority
               OR OLD.decision_reason IS DISTINCT FROM NEW.decision_reason
               OR OLD.primary_observation_id IS DISTINCT FROM NEW.primary_observation_id
               OR OLD.supersedes_id IS DISTINCT FROM NEW.supersedes_id
               OR OLD.published_at IS DISTINCT FROM NEW.published_at
               OR OLD.official_confirmed_at IS DISTINCT FROM NEW.official_confirmed_at
               OR OLD.applied_by_id IS DISTINCT FROM NEW.applied_by_id
               OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                RAISE EXCEPTION
                    'race event revision identity is immutable for revision %%', OLD.id
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    schema_editor.execute(
        f"""
        CREATE TRIGGER {REVISION_IMMUTABLE_TRIGGER}
        BEFORE UPDATE ON stable_raceeventrevision
        FOR EACH ROW
        EXECUTE FUNCTION {REVISION_IMMUTABLE_FUNCTION}();
        """
    )


def remove_revision_link_guards(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        f"DROP TRIGGER IF EXISTS {REVISION_IMMUTABLE_TRIGGER} "
        "ON stable_raceeventrevision;"
    )
    schema_editor.execute(
        f"DROP TRIGGER IF EXISTS {REVISION_LINK_TRIGGER} "
        "ON stable_raceeventrevision;"
    )
    schema_editor.execute(
        f"DROP TRIGGER IF EXISTS {PROJECTION_GUARD_TRIGGER} "
        "ON stable_raceeventprojectioncontrol;"
    )
    schema_editor.execute(f"DROP FUNCTION IF EXISTS {REVISION_IMMUTABLE_FUNCTION}();")
    schema_editor.execute(f"DROP FUNCTION IF EXISTS {REVISION_LINK_FUNCTION}();")
    schema_editor.execute(f"DROP FUNCTION IF EXISTS {PROJECTION_GUARD_FUNCTION}();")


class Migration(migrations.Migration):

    dependencies = [
        ("stable", "0038_racelivehostbudget"),
    ]

    operations = [
        migrations.RunPython(
            install_revision_link_guards,
            remove_revision_link_guards,
        ),
    ]
