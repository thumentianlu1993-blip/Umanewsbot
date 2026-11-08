import json

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from stable.services.horse_name_impact import historical_horse_name_impact


class Command(BaseCommand):
    help = '只读列出已发布新闻中可能受 HKJC 马名展示策略影响的标题/摘要/正文，不修改文章。'

    def handle(self, *args, **options):
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    cursor.execute("SET LOCAL statement_timeout = '30s'")
            rows = list(historical_horse_name_impact())
        self.stdout.write(json.dumps({'schema': 'hkjc-horse-name-impact.v1', 'read_only': True,
                                      'potential_article_count': len(rows),
                                      'metadata_supported_article_count': sum(row['classification'] == 'translation_metadata_match' for row in rows),
                                      'articles': rows}, ensure_ascii=False))
