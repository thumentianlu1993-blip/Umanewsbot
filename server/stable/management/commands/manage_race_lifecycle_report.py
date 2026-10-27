"""导入固定 SHA 的独立审核报告，或回读已保存的报告。"""
import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from stable.services.race_lifecycle_metrics import persist_report, read_report, assemble_report, register_scope
from stable.services.race_data_source_adapters import aware


class Command(BaseCommand):
    help = 'P02 严格 R01 证据报告；导入不会将未知项补成成功'

    def add_arguments(self, parser):
        parser.add_argument('--receipt')
        parser.add_argument('--input')
        parser.add_argument('--sha256')
        parser.add_argument('--register-scope', action='store_true')

    def handle(self, *args, **options):
        key = options['receipt']
        if key and options['input']:
            raise CommandError('choose_receipt_or_input')
        if not key:
            if not options['input'] or not options['sha256']:
                raise CommandError('input_and_sha256_required')
            raw = Path(options['input']).read_bytes()
            if len(raw) > 2 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != options['sha256']:
                raise CommandError('report_digest_mismatch')
            value = json.loads(raw)
            if options['register_scope']:
                from django.utils import timezone
                from stable.services.race_data_source_adapters import canonical_sha
                receipt = register_scope(value, expected_sha256=canonical_sha(value), now=timezone.now())
                self.stdout.write(json.dumps({'scope_receipt': receipt.idempotency_key}))
                return
            if set(value) == {'event_id', 'epoch', 'module', 'candidate_sha256', 'as_of'}:
                from stable.services.race_lifecycle_metrics import measure_epoch_latency
                value['as_of'] = aware(value['as_of'])
                self.stdout.write(json.dumps(measure_epoch_latency(**value), ensure_ascii=False, sort_keys=True))
                return
            if set(value) == {'scope', 'window', 'as_of'}:
                document = assemble_report(scope=value['scope'], window=value['window'], as_of=aware(value['as_of']))
                key = persist_report(document.to_dict(), expected_scope_sha256=document.expected_scope_sha256,
                    expected_candidate_sha256=document.expected_candidate_sha256,
                    expected_coverage_sha256=document.expected_coverage_sha256).idempotency_key
            else:
                key = persist_report(value['document'], **value['anchors']).idempotency_key
        self.stdout.write(json.dumps(dict(receipt=key, report=read_report(key)), ensure_ascii=False, sort_keys=True))
