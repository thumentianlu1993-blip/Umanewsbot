"""法国数据发布包默认dry-run；仅使用SHA固定的本地来源证据。"""
import json
from django.core.management.base import BaseCommand,CommandError
from stable.services.france_release import execute


class Command(BaseCommand):
    help='核验并事务回放法国数据发布包；默认回滚，--apply才保留'
    def add_arguments(self,parser):
        parser.add_argument('--manifest',required=True)
        parser.add_argument('--expected-sha256',required=True)
        parser.add_argument('--approved-by-id',type=int)
        parser.add_argument('--apply',action='store_true')
    def handle(self,*args,**options):
        try:result=execute(options['manifest'],options['expected_sha256'],apply=options['apply'],approved_by_id=options['approved_by_id'])
        except (ValueError,KeyError,TypeError,OSError) as exc:raise CommandError(str(exc)) from None
        self.stdout.write(json.dumps(result,ensure_ascii=False))
