"""稿件级公开页面；只读冻结回执，不读取新的待审文本。"""
import json
import logging
import uuid
from urllib.parse import urlencode
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from stable.models import NewsPublicationReceipt, NewsFeedSnapshot
from stable.services.news_feed import visible_entries, create_snapshot, snapshot_page
from stable.services.news_public_read import display_article

logger = logging.getLogger("stable.news_exposure")


def _no_cache(response):
    response["Cache-Control"] = "private, no-store, max-age=0"
    return response


@require_GET
@never_cache
def receipt_detail(request, receipt_id):
    receipt = get_object_or_404(NewsPublicationReceipt, pk=receipt_id, visibility="public")
    entry = get_object_or_404(visible_entries(), receipt=receipt)
    return entry_detail(request, entry)


@require_GET
@never_cache
def entry_detail(request, entry):
    from stable import views
    receipt = entry.receipt if entry.kind == "p01" else None
    article = display_article(entry)
    nav = views._public_detail_nav(request, allowed={"news"}, default="news")
    for link in article.public_race_links:
        link.event.public_list_detail_url = link.event.public_path
    previous = visible_entries().filter(Q(sort_time__lt=entry.sort_time) | Q(sort_time=entry.sort_time, feed_seq__lt=entry.feed_seq)).order_by("-sort_time", "-feed_seq").first()
    following = visible_entries().filter(Q(sort_time__gt=entry.sort_time) | Q(sort_time=entry.sort_time, feed_seq__gt=entry.feed_seq)).order_by("sort_time", "feed_seq").first()
    related = visible_entries().filter(primary_region=entry.primary_region).exclude(pk=entry.pk).order_by("-sort_time", "-feed_seq")[:4]
    original = NewsPublicationReceipt.objects.filter(pk=receipt.previous_receipt_id, visibility="public").first() if receipt else None
    return _no_cache(views._render_race_information(request, "stable/public/detail.html", {
        "article": article, **nav, "horse_links": article.public_horse_links, "race_links": article.public_race_links,
        "prev_article": display_article(previous) if previous else None,
        "next_article": display_article(following) if following else None,
        "related_articles": [display_article(row) for row in related], "original_receipt": original,
        "is_correction_story": bool(receipt and receipt.kind == "correction_story"),
    }))


@require_GET
@never_cache
def feed(request):
    from stable import views
    from django.utils import timezone
    now = timezone.now()
    generation = request.GET.get("generation")
    if not generation:
        if request.GET.get("cursor"):
            return _no_cache(HttpResponse("分页链接已失效，请返回首页。", status=400))
        from stable.services.news_pipeline import policy_sha
        snapshot = NewsFeedSnapshot.objects.filter(expires_at__gt=now, policy_sha=policy_sha()).order_by("-cutoff_at", "-id").first()
        if snapshot is None:
            return _no_cache(HttpResponse("新闻列表正在准备，请稍后刷新。", status=503, headers={"Retry-After": "60"}))
        generation = snapshot.generation
    try:
        generation = uuid.UUID(str(generation))
        page = snapshot_page(generation, cursor=request.GET.get("cursor"), size=views.PUBLIC_FEED_PAGE_SIZE, now=now)
    except (ValueError, TypeError):
        return _no_cache(HttpResponse('分页链接已失效，请<a href="/">返回首页</a>。', status=410))
    snapshot = page["snapshot"]
    featured_ids = snapshot.hot_entry_ids + ([snapshot.headline_entry_id] if snapshot.headline_entry_id else [])
    featured = {row.pk: row for row in visible_entries().filter(pk__in=featured_ids)}
    # 头条和热门只在首屏出现，连续翻页不重复曝光同一稿件。
    first_page = not request.GET.get("cursor")
    headline = featured.get(snapshot.headline_entry_id) if first_page else None
    hot = [featured[pk] for pk in snapshot.hot_entry_ids if pk in featured] if first_page else []
    today_races, fallback = views._public_today_races()
    next_key_race = views._public_next_key_race()
    next_url = "?"+urlencode({"generation": str(generation), "cursor": page["next_cursor"]}) if page["next_cursor"] else ""
    followed = views._public_followed_entries(request, limit=4)
    response = views._render_race_information(request, "stable/public/feed.html", {
        "p01_feed": True, "feed_articles": [display_article(row) for row in page["entries"]],
        "headline_article": display_article(headline) if headline else None,
        "hot_articles": [{"article": display_article(row)} for row in hot], "followed_entries": followed,
        "today_races": today_races, "today_races_is_fallback": fallback, "next_key_race": next_key_race,
        "public_next_url": next_url, "public_previous_url": "/?"+urlencode({"generation": str(generation)}) if not first_page else "",
    })
    response["X-News-Generation"] = str(generation)
    response["X-News-Exposure"] = str(uuid.uuid4())
    shown = page["entries"] + ([headline] if headline else []) + hot
    logger.info(json.dumps({"event": "news_feed_response", "response_id": response["X-News-Exposure"],
        "generation": str(generation), "at": now.isoformat(), "status": response.status_code,
        "entries": [{"id": row.pk, "region": row.primary_region} for row in shown],
        "followed_entry_ids": [row["article"].public_entry_id for row in followed]}, separators=(",", ":")))
    return _no_cache(response)


@require_GET
@never_cache
def archive(request):
    query = request.GET.get("q", "").strip()[:200]
    region = request.GET.get("region", "").strip()
    from stable.services.news_feed import archive_page
    try:
        page = archive_page(query=query, region=region, cursor=request.GET.get("cursor"))
    except ValueError:
        return _no_cache(HttpResponse("档案分页链接失效，请重新检索。", status=410))
    return _no_cache(render(request, "stable/public/news_archive.html", {
        "articles": [display_article(row) for row in page["entries"]], "query": query, "region": region,
        "next_cursor": page["next_cursor"], "next_url": "?"+urlencode({"q": query, "region": region, "cursor": page["next_cursor"]}) if page["next_cursor"] else ""}))
