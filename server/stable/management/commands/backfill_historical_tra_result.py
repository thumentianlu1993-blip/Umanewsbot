"""按精确manifest执行一场TRA历史补采；默认只做只读核验。"""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from stable.services.race_data_historical_request import (
    execute_request, validate_manifest, read_live_entry, validate_live_entry, require_result_write_flags,
)


class Command(BaseCommand):
    help = '一次性TRA历史补采；每场只允许一次请求，实际执行须精确发布授权。'

    def add_arguments(self, parser):
        parser.add_argument('--manifest', required=True)
        parser.add_argument('--manifest-sha256', required=True)
        parser.add_argument('--event-id', type=int, required=True)
        parser.add_argument('--receipt-directory', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            # 镜像构建时写入，不接受调用者自报代码SHA。
            code = Path('/app/.umanews-release-commit').read_text().strip()
            raw = Path(options['manifest']).read_bytes()
            kwargs = dict(raw=raw, expected_sha256=options['manifest_sha256'],
                expected_code_sha=code, receipt_directory=Path(options['receipt_directory']))
            event_id = options['event_id']
            require_result_write_flags()
            if options['apply']:
                status = execute_request(**kwargs, event_id=event_id)
            else:
                now = timezone.now()
                manifest = validate_manifest(**kwargs, now=now)
                current, _ = read_live_entry(event_id=event_id, now=now)
                validate_live_entry(manifest, event_id=event_id, current=current)
                status = 'dry_run'
            self.stdout.write(json.dumps({'event_id': event_id, 'status': status}))
        except Exception as exc:
            # 不输出provider或凭据异常内容；详细状态保留于私有收据。
            raise CommandError('historical_backfill_failed:' + type(exc).__name__) from None
