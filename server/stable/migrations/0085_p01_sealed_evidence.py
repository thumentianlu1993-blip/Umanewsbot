"""已核账模型回执与已发布 run 的内容证据只能追加财务更正，不能重写。"""
from django.db import migrations

SQL = r"""
CREATE FUNCTION p01_sealed_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE keys text[]; old_j jsonb; new_j jsonb;
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'P01 attempt cannot be deleted'; END IF;
  IF TG_TABLE_NAME = 'stable_newsprocessingrun' THEN
    IF OLD.state <> 'published' THEN RETURN NEW; END IF;
    keys := ARRAY['state','event_id','event_version','priority','primary_region','clean_snapshot','editorial_snapshot','entity_snapshot','translation_snapshot','quality_snapshot'];
  ELSE
    keys := ARRAY['run_id','stage','seq','claim_uuid','generation','input_sha'];
    IF (OLD.usage->'input') IS DISTINCT FROM (NEW.usage->'input') THEN
      RAISE EXCEPTION 'P01 attempt input cannot change';
    END IF;
    IF OLD.provider <> '' THEN
      keys := keys || ARRAY['provider','model','prompt_version','reservation','month_budget_id','day_budget_id'];
      IF (OLD.usage->'price') IS DISTINCT FROM (NEW.usage->'price') OR (OLD.usage->'currency') IS DISTINCT FROM (NEW.usage->'currency') THEN
        RAISE EXCEPTION 'P01 reserved request policy cannot change';
      END IF;
    END IF;
    IF OLD.settlement_version > 0 THEN
      keys := keys || ARRAY['state','result','output_sha','completed_at'];
      IF NEW.settlement_version < OLD.settlement_version THEN RAISE EXCEPTION 'P01 settlement version cannot decrease'; END IF;
    END IF;
  END IF;
  SELECT jsonb_object_agg(key,value) INTO old_j FROM jsonb_each(to_jsonb(OLD)) WHERE key = ANY(keys);
  SELECT jsonb_object_agg(key,value) INTO new_j FROM jsonb_each(to_jsonb(NEW)) WHERE key = ANY(keys);
  IF old_j IS DISTINCT FROM new_j THEN RAISE EXCEPTION 'P01 sealed evidence changed'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER p01_attempt_evidence_immutable BEFORE UPDATE OR DELETE ON stable_newsstageattempt FOR EACH ROW EXECUTE FUNCTION p01_sealed_evidence_guard();
CREATE TRIGGER p01_published_run_evidence_immutable BEFORE UPDATE ON stable_newsprocessingrun FOR EACH ROW EXECUTE FUNCTION p01_sealed_evidence_guard();
"""
REVERSE = """
DROP TRIGGER IF EXISTS p01_published_run_evidence_immutable ON stable_newsprocessingrun;
DROP TRIGGER IF EXISTS p01_attempt_evidence_immutable ON stable_newsstageattempt;
DROP FUNCTION IF EXISTS p01_sealed_evidence_guard();
"""


def apply(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL, params=None)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("stable", "0084_p01_immutable_publication")]
    operations = [migrations.RunPython(apply, reverse)]
