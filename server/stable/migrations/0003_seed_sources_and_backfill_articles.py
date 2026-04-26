from django.db import migrations
from django.utils.text import slugify


def seed_sources_and_backfill(apps, schema_editor):
    NewsSource = apps.get_model("stable", "NewsSource")
    NewsArticle = apps.get_model("stable", "NewsArticle")

    source_payloads = [
        {
            "name": "netkeiba 新着顺",
            "homepage_url": "https://news.netkeiba.com/",
            "feed_url": "https://news.netkeiba.com/?pid=news_backnumber&page=1",
            "source_type": "builtin",
            "language": "ja",
            "adapter_key": "netkeiba",
            "source_site": "netkeiba",
            "source_mode": "latest",
            "enabled": True,
            "crawl_interval_minutes": 60,
            "notes": "每小时抓取新增新闻；周日重赏时间段 5 分钟一抓。",
            "priority": 100,
        },
        {
            "name": "netkeiba 访问量榜",
            "homepage_url": "https://news.netkeiba.com/",
            "feed_url": "https://news.netkeiba.com/?pid=news_backnumber&rf=access",
            "source_type": "builtin",
            "language": "ja",
            "adapter_key": "netkeiba",
            "source_site": "netkeiba",
            "source_mode": "access",
            "enabled": True,
            "crawl_interval_minutes": 720,
            "notes": "每 12 小时抓取前 20 条。",
            "priority": 90,
        },
        {
            "name": "netkeiba 注目数榜",
            "homepage_url": "https://news.netkeiba.com/",
            "feed_url": "https://news.netkeiba.com/?pid=news_backnumber&rf=attention",
            "source_type": "builtin",
            "language": "ja",
            "adapter_key": "netkeiba",
            "source_site": "netkeiba",
            "source_mode": "attention",
            "enabled": True,
            "crawl_interval_minutes": 720,
            "notes": "每 12 小时抓取前 20 条。",
            "priority": 80,
        },
        {
            "name": "JRA 官方新闻",
            "homepage_url": "https://www.jra.go.jp/news/",
            "feed_url": "https://www.jra.go.jp/news/",
            "source_type": "builtin",
            "language": "ja",
            "adapter_key": "jra",
            "source_site": "jra",
            "source_mode": "official",
            "enabled": True,
            "crawl_interval_minutes": 720,
            "notes": "每 12 小时扫描当前月和上月的新稿。",
            "priority": 95,
        },
    ]

    source_map = {}
    for payload in source_payloads:
        source, _ = NewsSource.objects.update_or_create(
            source_site=payload["source_site"],
            source_mode=payload["source_mode"],
            defaults=payload,
        )
        source_map[(payload["source_site"], payload["source_mode"])] = source.id

    for article in NewsArticle.objects.all():
        if not article.translated_title_zh and article.title_zh:
            article.translated_title_zh = article.title_zh
        if not article.translated_body_zh and article.body_zh:
            article.translated_body_zh = article.body_zh
        if not article.translated_summary_zh and article.push_summary_zh:
            article.translated_summary_zh = article.push_summary_zh
        if not article.summary_zh and article.push_summary_zh:
            article.summary_zh = article.push_summary_zh
        if not article.workflow_status or article.workflow_status == "pending_translation":
            if article.translated_body_zh or article.translated_title_zh or article.body_zh:
                article.workflow_status = "pending_edit"
        if not article.source_note:
            article.source_note = article.source_site
        if not article.public_slug:
            base = slugify(article.title_zh or article.title_ja, allow_unicode=True)[:80] or "article"
            article.public_slug = f"{base}-{article.pk}"
        if not article.source_config_id:
            article.source_config_id = source_map.get((article.source_site, article.source_mode))
        article.save()


class Migration(migrations.Migration):
    dependencies = [
        ("stable", "0002_crawljob_newsarticle_crawl_status_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_sources_and_backfill, migrations.RunPython.noop),
    ]
