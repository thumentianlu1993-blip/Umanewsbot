"""历史新闻译名影响的只读候选清单，不执行实体替换。"""
import re

from stable.models import NewsArticle, TermEntry, TermType, WorkflowStatus
from stable.services.horse_name_policy import hkjc_name_is_verified


def historical_horse_name_impact():
    names = {}
    terms = TermEntry.objects.filter(term_type=TermType.HORSE).only(
        'id', 'target_zh', 'aliases_zh', 'source_ja', 'notes', 'is_active', 'translation_status')
    for term in terms.iterator(chunk_size=1000):
        official_target = (term.is_active and term.translation_status == 'translated'
                           and hkjc_name_is_verified(term.target_zh, term.notes))
        for name in [term.target_zh, *(term.aliases_zh or [])]:
            name = (name or '').strip()
            if official_target and name == (term.target_zh or '').strip():
                continue
            if name and re.search(r'[\u3400-\u9fff]', name):
                names.setdefault(name, set()).add(term.pk)
    # 按首字分桶，允许重叠名称命中；不以子串命中冒充实体身份确认。
    by_initial = {}
    for name in names:
        by_initial.setdefault(name[0], []).append(name)
    fields = ('effective_title', 'effective_summary', 'effective_body')
    articles = NewsArticle.objects.filter(
        workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at__isnull=False,
    ).order_by('pk')
    for article in articles.iterator(chunk_size=200):
        matches = []
        metadata = article.translation_metadata or {}
        entities = metadata.get('entities') or []
        glossary = metadata.get('terms') or []
        for field in fields:
            text = getattr(article, field) or ''
            candidates = (name for initial in set(text) for name in by_initial.get(initial, []))
            for name in sorted(candidate for candidate in candidates if candidate in text):
                evidence = []
                if any(isinstance(entity, dict) and entity.get('entity_type') == 'horse'
                       and entity.get('term_id') in names[name] for entity in entities):
                    evidence.append('translation_entity')
                if any(isinstance(term, dict) and term.get('term_type') == 'horse'
                       and term.get('target_zh') == name for term in glossary):
                    evidence.append('translation_glossary')
                matches.append({'field': field, 'name': name, 'term_ids': sorted(names[name]),
                                'evidence': evidence})
        if matches:
            yield {'article_id': article.pk, 'public_slug': article.public_slug,
                   'title': article.effective_title, 'classification': ('translation_metadata_match' if any(m['evidence'] for m in matches)
                                      else 'potential_text_match'), 'matches': matches}
