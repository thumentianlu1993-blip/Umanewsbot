import json
import tempfile
from pathlib import Path
from io import StringIO

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TransactionTestCase
from django.db import connection, DatabaseError
from stable.management.commands.preview_race_information_normalization import read_only_database


class OfflinePreviewTests(SimpleTestCase):
    def test_offline_read_only_cursor_hash_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'source.jsonl';out=folder/'report'
            source.write_text('\n'.join(json.dumps({'id':i,'grade_text':'GI','distance_text':'1 mile','raw_payload':{'secret':'not-for-report'}}) for i in [1,2,3]))
            call_command('preview_race_information_normalization',input=str(source),after_id=1,limit=1,output=str(out),code_sha='a'*40,stdout=StringIO())
            summary=json.loads((out/'summary.json').read_text())
            self.assertEqual((summary['rows'],summary['last_pk'],summary['database_writes']),(1,2,0))
            report=(out/'diff.jsonl').read_text()
            self.assertIn('1英里（约1609米）',report)
            self.assertNotIn('secret',report)
            self.assertTrue(summary['completed'])
            with self.assertRaises(CommandError):
                call_command('preview_race_information_normalization',input=str(source),output=str(out),code_sha='a'*40)

    def test_explicit_database_scope_required(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(CommandError):
                call_command('preview_race_information_normalization',from_db=True,output=folder+'/report',code_sha='a'*40)

    def test_partial_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);source=path/'source.jsonl';source.write_text('{broken')
            with self.assertRaises(CommandError):
                call_command('preview_race_information_normalization',input=str(source),output=str(path/'out'),code_sha='a'*40)
            self.assertFalse(json.loads((path/'out'/'summary.json').read_text())['completed'])

    def test_horse_record_preview_matches_page_and_redacts_display(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder); source=folder/'input.jsonl'; out=folder/'out'
            source.write_text(json.dumps({'id':1,'race_date':'2026-09-18','finish_position':'4','normalized_result_status':'dead_heat',
                'racecourse':'https://example.test/path?token=synthetic-secret#value'}))
            call_command('preview_race_information_normalization',input=str(source),model='horse_record',output=str(out),code_sha='a'*40,stdout=StringIO())
            report=(out/'diff.jsonl').read_text();fields=json.loads(report)['fields']
            self.assertNotIn('synthetic-secret',report)
            self.assertEqual(fields['date']['display'],'2026-09-18')
            self.assertEqual(fields['position']['display'],'并列第4')
            self.assertEqual(fields['position']['raw'],'4')

    def test_report_redacts_all_url_forms_and_retains_original_record_name(self):
        for url in ['HTTPS://example.test/path?token=synthetic-secret',
                    'https://synthetic-user:synthetic-secret@example.test/path',
                    'https://example.test/path#synthetic-secret']:
            with self.subTest(url=url), tempfile.TemporaryDirectory() as folder:
                folder=Path(folder);source=folder/'in.jsonl';out=folder/'out'
                source.write_text(json.dumps({'id':1,'race_name':'Sample Race','racecourse':url}))
                call_command('preview_race_information_normalization',input=str(source),model='horse_record',output=str(out),code_sha='a'*40,stdout=StringIO())
                report=(out/'diff.jsonl').read_text()
                self.assertNotIn('synthetic-secret',report)
                self.assertNotIn('synthetic-user',report)
                self.assertEqual(json.loads(report)['fields']['name']['raw'],'Sample Race')


class ReadOnlyGuardTests(TransactionTestCase):
    def test_session_guard_rejects_writes(self):
        with self.assertRaises(DatabaseError):
            with read_only_database('default'):
                with connection.cursor() as cursor:
                    cursor.execute("CREATE TABLE forbidden_write (id integer)")
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                cursor.execute('PRAGMA query_only')
                self.assertEqual(cursor.fetchone()[0], 0)
            else:
                cursor.execute('SHOW transaction_read_only')
                self.assertEqual(cursor.fetchone()[0], 'off')
