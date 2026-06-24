from __future__ import annotations

from stable.models import NewsSource, SourceMode, SourceSite, SourceType


BUILTIN_SOURCE_DEFINITIONS = [
    {
        "name": "netkeiba 新着顺",
        "homepage_url": "https://news.netkeiba.com/",
        "feed_url": "https://news.netkeiba.com/?pid=news_backnumber&page=1",
        "source_type": SourceType.BUILTIN,
        "language": "ja",
        "adapter_key": "netkeiba",
        "source_site": SourceSite.NETKEIBA,
        "source_mode": SourceMode.LATEST,
        "enabled": True,
        "crawl_interval_minutes": 60,
        "notes": "每小时抓取新增新闻；周日重赏时间段 5 分钟一抓。",
        "priority": 100,
    },
    {
        "name": "netkeiba 访问量榜",
        "homepage_url": "https://news.netkeiba.com/",
        "feed_url": "https://news.netkeiba.com/?pid=news_backnumber&rf=access",
        "source_type": SourceType.BUILTIN,
        "language": "ja",
        "adapter_key": "netkeiba",
        "source_site": SourceSite.NETKEIBA,
        "source_mode": SourceMode.ACCESS,
        "enabled": True,
        "crawl_interval_minutes": 60,
        "notes": "每小时抓取访问量榜前 20 条。",
        "priority": 90,
    },
    {
        "name": "netkeiba 注目数榜",
        "homepage_url": "https://news.netkeiba.com/",
        "feed_url": "https://news.netkeiba.com/?pid=news_backnumber&rf=attention",
        "source_type": SourceType.BUILTIN,
        "language": "ja",
        "adapter_key": "netkeiba",
        "source_site": SourceSite.NETKEIBA,
        "source_mode": SourceMode.ATTENTION,
        "enabled": True,
        "crawl_interval_minutes": 60,
        "notes": "每小时错峰抓取注目数榜前 20 条。",
        "priority": 80,
    },
    {
        "name": "JRA 官方新闻",
        "homepage_url": "https://www.jra.go.jp/news/",
        "feed_url": "https://www.jra.go.jp/news/",
        "source_type": SourceType.BUILTIN,
        "language": "ja",
        "adapter_key": "jra",
        "source_site": SourceSite.JRA,
        "source_mode": SourceMode.OFFICIAL,
        "enabled": True,
        "crawl_interval_minutes": 720,
        "notes": "每 12 小时扫描当前月和上月的新稿。",
        "priority": 95,
    },
]


def sync_builtin_sources() -> list[NewsSource]:
    sources: list[NewsSource] = []
    for payload in BUILTIN_SOURCE_DEFINITIONS:
        source, _created = NewsSource.objects.update_or_create(
            source_site=payload["source_site"],
            source_mode=payload["source_mode"],
            defaults=payload,
        )
        sources.append(source)
    return sources


def find_builtin_source(source_site: str, source_mode: str) -> NewsSource | None:
    return (
        NewsSource.objects.filter(
            source_site=source_site,
            source_mode=source_mode,
            deleted_at__isnull=True,
        )
        .order_by("-enabled", "-priority", "id")
        .first()
    )
