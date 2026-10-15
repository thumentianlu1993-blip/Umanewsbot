"""Q03 news snapshot DTO/cursor core; no routes, ORM execution or change feed.

Page callers must supply an ordered, already eligibility/exposure-filtered SQL
window. These helpers do not establish homepage exposure or caller authority.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from itertools import islice
import json
import re

from django.core import signing
from django.http import QueryDict

PAGE_SIZE = 12
CURSOR_MAX_BYTES = 2048
CURSOR_SALT = 'stable.public_news_snapshot.v1'
_MAX_ID = 2**63 - 1


class InvalidRequest(ValueError):
    def __init__(self, code='invalid_request'):
        self.code = code
        super().__init__(code)


class NewsNotFound(LookupError):
    """No currently public detail projection; no hidden reason is exposed."""


class SnapshotDataError(ValueError):
    """A source window violates the core contract, not an empty public result."""


def _utc(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise SnapshotDataError('aware publication datetime required')
    try:
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise SnapshotDataError('publication datetime outside supported range') from error


def _key(value):
    if not isinstance(value, tuple) or len(value) != 2:
        raise SnapshotDataError('publication key must have timestamp and id')
    stamp, pk = value
    if type(pk) is not int or not 0 < pk <= _MAX_ID:
        raise SnapshotDataError('positive int64 source id required')
    return (_utc(stamp), pk)


@dataclass(frozen=True)
class CursorBoundary:
    upper: tuple[datetime, int]
    after: tuple[datetime, int]

    def __post_init__(self):
        object.__setattr__(self, 'upper', _key(self.upper))
        object.__setattr__(self, 'after', _key(self.after))
        if self.after > self.upper:
            raise SnapshotDataError('cursor after exceeds upper bound')

    def allows(self, key):
        key = _key(key)
        return key <= self.upper and key < self.after


@dataclass(frozen=True)
class SnapshotPage:
    results: tuple[dict, ...]
    next_cursor: str | None


def _is_public(article):
    return (getattr(article, 'workflow_status', None) == 'published'
            and getattr(article, 'published_to_web_at', None) is not None)


def article_order_key(article):
    """Original precision, never the minute-rounded display timestamp."""
    return _key((article.published_to_web_at, article.pk))


def project_news(article):
    # This must precede reading content and any future conditional-GET handling.
    if not _is_public(article):
        raise NewsNotFound()
    stamp, pk = article_order_key(article)
    payload = {
        'id': str(pk),
        'title': article.effective_title,
        'summary': article.effective_summary,
        'public_path': article.public_path,
        'published_at': stamp.replace(second=0, microsecond=0).isoformat().replace('+00:00', 'Z'),
    }
    if any(type(value) is not str for value in payload.values()):
        raise SnapshotDataError('public projection values must be strings')
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    payload['version'] = 'news-v1-' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return payload


def parse_news_id(value):
    if type(value) is not str or not re.fullmatch(r'[1-9][0-9]{0,18}', value):
        raise InvalidRequest()
    pk = int(value)
    if pk > _MAX_ID:
        raise InvalidRequest()
    return pk


def _serialize_key(key):
    stamp, pk = key
    return [stamp.isoformat(timespec='microseconds').replace('+00:00', 'Z'), pk]


def encode_cursor(boundary):
    if not isinstance(boundary, CursorBoundary):
        raise SnapshotDataError('cursor boundary required')
    return signing.dumps({
        'version': 1, 'scope': 'news-feed',
        'upper': _serialize_key(boundary.upper), 'after': _serialize_key(boundary.after),
    }, salt=CURSOR_SALT)


def _decode_key(value):
    if type(value) is not list or len(value) != 2 or type(value[0]) is not str:
        raise SnapshotDataError('invalid cursor key')
    stamp = datetime.fromisoformat(value[0])
    key = _key((stamp, value[1]))
    if _serialize_key(key)[0] != value[0]:
        raise SnapshotDataError('noncanonical cursor datetime')
    return key


def decode_cursor(token):
    if type(token) is not str or not token or not token.isascii() or len(token) > CURSOR_MAX_BYTES:
        raise InvalidRequest('invalid_cursor')
    try:
        # No new age/retention promise; signed pagination tokens are not grants.
        payload = signing.loads(token, salt=CURSOR_SALT)
        if (type(payload) is not dict or set(payload) != {'version', 'scope', 'upper', 'after'}
                or type(payload['version']) is not int or payload['version'] != 1
                or payload['scope'] != 'news-feed'):
            raise SnapshotDataError('cursor scope/version/schema mismatch')
        return CursorBoundary(_decode_key(payload['upper']), _decode_key(payload['after']))
    except (signing.BadSignature, ValueError, TypeError, UnicodeError, OverflowError) as error:
        raise InvalidRequest('invalid_cursor') from error


def parse_snapshot_params(params):
    if not isinstance(params, QueryDict) or set(params) - {'cursor'}:
        raise InvalidRequest()
    if not params:
        return None
    tokens = params.getlist('cursor')
    if len(tokens) != 1 or not tokens[0]:
        raise InvalidRequest()
    return decode_cursor(tokens[0])


def build_snapshot_page(ordered_eligible_rows, *, boundary=None):
    """Pack only a prefiltered keyset window; consume at most twelve plus one.

    ORM eligibility/exposure and SQL boundary integration remain a separate step.
    A malformed window fails rather than silently calling it empty/complete.
    """
    if boundary is not None and not isinstance(boundary, CursorBoundary):
        raise SnapshotDataError('cursor boundary required')
    rows = list(islice(ordered_eligible_rows, PAGE_SIZE + 1))
    if not rows:
        return SnapshotPage((), None)
    keys = []
    seen_pks = set()
    for row in rows:
        if not _is_public(row):
            raise SnapshotDataError('source window contains non-public row')
        key = article_order_key(row)
        if key[1] in seen_pks:
            raise SnapshotDataError('source window contains duplicate news id')
        seen_pks.add(key[1])
        if (keys and key >= keys[-1]) or (boundary is not None and not boundary.allows(key)):
            raise SnapshotDataError('source window ordering/boundary mismatch')
        keys.append(key)
    results = tuple(project_news(row) for row in rows[:PAGE_SIZE])
    next_cursor = None
    if len(rows) > PAGE_SIZE:
        upper = boundary.upper if boundary is not None else keys[0]
        next_cursor = encode_cursor(CursorBoundary(upper, keys[PAGE_SIZE-1]))
    return SnapshotPage(results, next_cursor)
