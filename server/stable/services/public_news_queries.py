"""Shared public news qualification; no navigation, personalization or writes."""
from django.conf import settings
from django.db.models import Exists, OuterRef
from stable.models import (
    NewsArticle, WorkflowStatus, ArticleRaceLink, ArticleRaceLinkStatus,
    RaceNewsExposure, RaceNewsExposureChannel, RaceNewsExposureStatus,
)


def public_article_queryset():
    return NewsArticle.objects.filter(
        workflow_status=WorkflowStatus.PUBLISHED,
        published_to_web_at__isnull=False,
    ).order_by('-published_to_web_at', '-id')


def filter_homepage_exposure(queryset):
    """The existing public_news_feed policy; not the featured/manual resolver."""
    maximum = getattr(settings, 'RACE_NEWS_HOMEPAGE_MAX', 2)
    if getattr(settings, 'RACE_NEWS_EXPOSURE_ENABLED', False) and maximum > 0:
        has_race_link = ArticleRaceLink.objects.filter(
            article_id=OuterRef('pk'),
            status__in=(ArticleRaceLinkStatus.AUTO, ArticleRaceLinkStatus.MANUAL),
        )
        has_active_exposure = RaceNewsExposure.objects.filter(
            article_id=OuterRef('pk'), channel=RaceNewsExposureChannel.HOMEPAGE,
            scope_key='site', status=RaceNewsExposureStatus.ACTIVE,
        )
        queryset = queryset.exclude(Exists(has_race_link) & ~Exists(has_active_exposure))
    return queryset
