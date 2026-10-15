"""Q03 ORM bridge only; no HTTP, auth, cache or change-feed contract."""
from django.db.models import Q
from stable.models import NewsArticle
from .public_news_queries import public_article_queryset, filter_homepage_exposure
from .public_news_snapshot import (
    PAGE_SIZE, NewsNotFound, build_snapshot_page, parse_news_id,
    parse_snapshot_params, project_news,
)


def load_news_page(params):
    boundary = parse_snapshot_params(params)
    queryset = filter_homepage_exposure(public_article_queryset())
    if boundary is not None:
        upper_time, upper_id = boundary.upper
        after_time, after_id = boundary.after
        queryset = queryset.filter(
            Q(published_to_web_at__lt=upper_time)
            | Q(published_to_web_at=upper_time, pk__lte=upper_id)
        ).filter(
            Q(published_to_web_at__lt=after_time)
            | Q(published_to_web_at=after_time, pk__lt=after_id)
        )
    return build_snapshot_page(queryset[:PAGE_SIZE + 1], boundary=boundary)


def load_news_detail(news_id):
    pk = parse_news_id(news_id)
    try:
        article = public_article_queryset().get(pk=pk)
    except NewsArticle.DoesNotExist:
        raise NewsNotFound() from None
    return project_news(article)
