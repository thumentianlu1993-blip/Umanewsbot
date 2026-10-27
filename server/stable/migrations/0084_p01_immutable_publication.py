"""防止旧 writer / 直接 ORM 绕过不可变公开内容合同。"""
from django.db import migrations

SQL = r"""
CREATE FUNCTION p01_immutable_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE old_j jsonb; new_j jsonb; keys text[];
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'P01 immutable record cannot be deleted';
  END IF;
  IF TG_TABLE_NAME = 'stable_newspublicationreceipt' THEN
    old_j := to_jsonb(OLD) - ARRAY['visibility', 'visibility_evidence'];
    new_j := to_jsonb(NEW) - ARRAY['visibility', 'visibility_evidence'];
  ELSIF TG_TABLE_NAME = 'stable_newspublicentry' THEN
    old_j := to_jsonb(OLD) - 'superseded_at'; new_j := to_jsonb(NEW) - 'superseded_at';
  ELSIF TG_TABLE_NAME = 'stable_newsprocessingrun' THEN
    keys := ARRAY['article_id','input_sha','policy_sha','target_revision_sha','source_snapshot','manual_target','editor_provenance','parent_run_id','generation'];
    SELECT jsonb_object_agg(key, value) INTO old_j FROM jsonb_each(to_jsonb(OLD)) WHERE key = ANY(keys);
    SELECT jsonb_object_agg(key, value) INTO new_j FROM jsonb_each(to_jsonb(NEW)) WHERE key = ANY(keys);
  ELSIF TG_TABLE_NAME = 'stable_newsarticle' THEN
    IF NOT EXISTS (SELECT 1 FROM stable_newspublicationreceipt WHERE article_id = OLD.id) THEN RETURN NEW; END IF;
    keys := ARRAY['title_ja','body_ja_raw','body_ja_normalized','original_content_html','original_author',
      'source_site','source_article_id','source_url','source_language','published_at','published_at_verified','published_at_evidence',
      'title_zh','body_zh','summary_zh','translated_title_zh','translated_body_zh','translated_summary_zh',
      'rewrite_title_zh','rewrite_body_zh','rewrite_summary_zh','push_summary_zh','base_translation_zh',
      'manually_edited_fields','published_to_web_at','public_slug'];
    SELECT jsonb_object_agg(key, value) INTO old_j FROM jsonb_each(to_jsonb(OLD)) WHERE key = ANY(keys);
    SELECT jsonb_object_agg(key, value) INTO new_j FROM jsonb_each(to_jsonb(NEW)) WHERE key = ANY(keys);
  ELSE
    old_j := to_jsonb(OLD); new_j := to_jsonb(NEW);
  END IF;
  IF old_j IS DISTINCT FROM new_j THEN RAISE EXCEPTION 'P01 immutable content changed: %', TG_TABLE_NAME; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER p01_receipt_immutable BEFORE UPDATE OR DELETE ON stable_newspublicationreceipt FOR EACH ROW EXECUTE FUNCTION p01_immutable_guard();
CREATE TRIGGER p01_entry_immutable BEFORE UPDATE OR DELETE ON stable_newspublicentry FOR EACH ROW EXECUTE FUNCTION p01_immutable_guard();
CREATE TRIGGER p01_run_input_immutable BEFORE UPDATE OR DELETE ON stable_newsprocessingrun FOR EACH ROW EXECUTE FUNCTION p01_immutable_guard();
CREATE TRIGGER p01_article_immutable BEFORE UPDATE ON stable_newsarticle FOR EACH ROW EXECUTE FUNCTION p01_immutable_guard();
CREATE TRIGGER p01_snapshot_immutable BEFORE UPDATE ON stable_newsfeedsnapshot FOR EACH ROW EXECUTE FUNCTION p01_immutable_guard();
"""
REVERSE = """
DROP TRIGGER IF EXISTS p01_snapshot_immutable ON stable_newsfeedsnapshot;
DROP TRIGGER IF EXISTS p01_article_immutable ON stable_newsarticle;
DROP TRIGGER IF EXISTS p01_run_input_immutable ON stable_newsprocessingrun;
DROP TRIGGER IF EXISTS p01_entry_immutable ON stable_newspublicentry;
DROP TRIGGER IF EXISTS p01_receipt_immutable ON stable_newspublicationreceipt;
DROP FUNCTION IF EXISTS p01_immutable_guard();
"""


def apply(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


def reverse(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):
    dependencies = [("stable", "0083_p01_news_quality")]
    operations = [migrations.RunPython(apply, reverse)]
