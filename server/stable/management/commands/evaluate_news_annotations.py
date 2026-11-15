"""本地标注导入与评分，禁止模型/网络/数据库访问。"""
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from stable.services.news_annotation_evaluation import (
    import_annotation_package, evaluate_entities, evaluate_translations, compare_entity_reports,
)


class Command(BaseCommand):
    help = '离线导入新闻标注、实体评分、报告比较与事实审阅汇总'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['import','entities','translations','compare'])
        parser.add_argument('--input', required=True)
        parser.add_argument('--predictions')
        parser.add_argument('--checksum-manifest-sha')
        parser.add_argument('--output', required=True)

    def handle(self, *args, **options):
        def read(path):return json.loads(Path(path).read_text())
        try:
            action=options['action']
            if action=='import':
                if not options['checksum_manifest_sha']:raise ValueError('checksum_manifest_sha_required')
                refs,meta=import_annotation_package(options['input'],options['checksum_manifest_sha'])
                result={'references':refs,'metadata':meta}
            else:
                if not options['predictions']:raise ValueError('predictions_required')
                source=read(options['input']);pred=read(options['predictions'])
                if action=='compare':result=compare_entity_reports(source,pred)
                else:result=(evaluate_entities if action=='entities' else evaluate_translations)(source['references'],pred)
            Path(options['output']).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        except (ValueError,TypeError,KeyError,OSError) as error:raise CommandError(str(error)) from error
        self.stdout.write('离线结果已写入 '+options['output'])
