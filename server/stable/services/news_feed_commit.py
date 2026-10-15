"""C153 PRIVATE RED CANDIDATE ONLY -- must never merge or activate.

This deliberately incomplete unit locks the actual Article and permits normal
business saves, but DOES NOT lock Clock or capture State/Change/counter. The
approved PG tests must expose these missing behaviors as business FAILs later.
Schema preparation is normal; this unit is not a GREEN implementation.
"""
from contextlib import contextmanager

from django.conf import settings
from django.db import transaction

from stable.models import NewsArticle


class NewsFeedCaptureError(RuntimeError):
    pass


class FeedCaptureBoundaryError(NewsFeedCaptureError):
    pass


@contextmanager
def capture_news_change(news_id, using='default'):
    if not getattr(settings, 'NEWS_FEED_CAPTURE_ENABLED', False):
        yield
        return
    # Intentionally wrong for RED: Article before Clock, ordinary atomic rather
    # than the approved durable/outer/reentry/poison/final-capture implementation.
    with transaction.atomic(using=using):
        NewsArticle.objects.using(using).select_for_update().filter(pk=news_id).first()
        yield
