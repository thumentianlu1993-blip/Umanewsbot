"""固定美国发布包的本地回放、获准apply与CAS恢复。"""
import hashlib,json
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from django.db import connection,transaction
from stable.services.us_release import execute,snapshot,baseline_matches
from stable.services.france_release import read_bound


class Command(BaseCommand):
    help='校验固定美国manifest；默认事务回滚，生产只读检查使用 --check-baseline。'

    def add_arguments(self,parser):
        parser.add_argument('--manifest',required=True)
        parser.add_argument('--sha256',required=True)
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--restore',action='store_true')
        parser.add_argument('--check-baseline',action='store_true')

    def handle(self,*args,**options):
        try:
            path=Path(options['manifest'])
            if options['check_baseline']:
                if options['apply'] or options['restore']:raise ValueError('check_is_read_only')
                raw=path.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=options['sha256']:raise ValueError('manifest_digest')
                manifest=json.loads(raw);before=read_bound(path.parent,manifest['baseline'])
                ids=[r['id'] for r in before['RaceEvent']]
                with transaction.atomic():
                    if connection.vendor=='postgresql':
                        with connection.cursor() as cursor:
                            cursor.execute('SET TRANSACTION READ ONLY')
                            cursor.execute("SET LOCAL statement_timeout='20s'")
                    if not baseline_matches(snapshot(ids),before,[r['event_id'] for r in manifest.get('rebind',[])]):raise ValueError('baseline_drift')
                result={'action':'baseline_verified','event_count':len(ids),'manifest_sha256':options['sha256']}
            else:
                result=execute(path,options['sha256'],apply=options['apply'],restore=options['restore'])
        except (ValueError,KeyError,TypeError,OSError) as exc:raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result,ensure_ascii=False))
