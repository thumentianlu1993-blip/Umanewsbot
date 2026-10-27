"""有来源证据的事件身份与重大事实增量。"""
from stable.services.news_pipeline import digest
from stable.services.news_content import ContentBlocked


def identity_key(kind, fields, *, source_scope="", aliases=None):
    return "news-event-v1:" + kind + ":" + digest(fields)


def validate_editorial(clean, response, *, source_scope, candidates=(), aliases=None):
    return response
