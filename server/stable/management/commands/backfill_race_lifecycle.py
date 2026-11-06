"""默认只读审计；回填绑定完整 manifest SHA，最多 100 场。"""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from stable.services.race_lifecycle_projection import compatibility_manifest, backfill_compatibility, canonical_sha


class Command(BaseCommand):
    help = 'P02 历史兼容审计与幂等回填；生产使用须符合根 AGENTS.md'

    def add_arguments(self, parser):
        parser.add_argument('--event-id', type=int, action='append', default=[])
        parser.add_argument('--after-id', type=int, default=0)
        parser.add_argument('--apply-manifest')
        parser.add_argument('--sha256')

    def handle(self, *args, **options):
        if options['apply_manifest']:
            if not options['sha256'] or options['event_id']:
                raise CommandError('exact_manifest_sha_required')
            raw = Path(options['apply_manifest']).read_bytes()
            if len(raw) > 2 * 1024 * 1024:
                raise CommandError('manifest_size_limit')
            result = backfill_compatibility(json.loads(raw), expected_sha256=options['sha256'], now=timezone.now())
        else:
            if not options['event_id']:
                raise CommandError('explicit_event_ids_required')
            result = compatibility_manifest(event_ids=options['event_id'], after_id=options['after_id'])
            result = dict(manifest=result, manifest_sha256=canonical_sha(result))
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
