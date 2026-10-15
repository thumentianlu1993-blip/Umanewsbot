"""Private Q03 single-news commit primitive; actual PG GREEN still required.

Explicit callers only. This does not bootstrap T0, adapt other writers, implement
feed delivery or authorize activation. Disabled mode preserves the old path.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import get_ident

from django.conf import settings
from django.db import connections, transaction

from stable.models import NewsArticle, NewsFeedChange, NewsFeedClock, NewsFeedState
from stable.services.news_feed_semantics import PublicDTO, classify_final
from stable.services.public_news_snapshot import NewsNotFound, project_news

_SCOPE = 'public-detail'
_MAX_SEQ = 2**63 - 1
_ACTIVE_UNIT = ContextVar('q03_news_capture_unit', default=None)


class NewsFeedCaptureError(RuntimeError):
    pass


class FeedCaptureBoundaryError(NewsFeedCaptureError):
    pass


@dataclass
class _Unit:
    database: object
    backend: object
    outer: object
    thread: int
    news_id: int
    clock: NewsFeedClock
    state: NewsFeedState
    before: PublicDTO | None
    clock_signature: tuple
    state_signature: tuple
    poison: BaseException | None = None


def _clock_signature(clock):
    return (clock.scope, clock.generation, clock.initialized, clock.last_seq)


def _state_signature(state):
    return (state.pk, state.scope_id, state.generation, state.news_id,
            state.current_visible, state.ever_public, state.revision_seq,
            state.fingerprint)


def _projection(article):
    if article is None:
        return None
    try:
        return PublicDTO(**project_news(article))
    except NewsNotFound:
        return None


def _article(database, news_id):
    return (NewsArticle.objects.using(database.alias).select_for_update()
            .filter(pk=news_id).first())


def _require_owner(unit, database):
    if (unit.thread != get_ident() or unit.database is not database
            or database.connection is not unit.backend
            or not database.in_atomic_block
            or len(database.atomic_blocks) != 1
            or database.atomic_blocks[0] is not unit.outer
            or database.savepoint_ids):
        raise FeedCaptureBoundaryError('capture requires its own outer transaction')
    if database.needs_rollback:
        raise NewsFeedCaptureError('capture transaction is already marked for rollback')


def _prepare(database, outer, news_id):
    # The first business row lock must be Clock, never Article/Run/Budget.
    try:
        clock = (NewsFeedClock.objects.using(database.alias).select_for_update()
                 .get(scope=_SCOPE))
    except NewsFeedClock.DoesNotExist as error:
        raise NewsFeedCaptureError('capture clock is not initialized') from error
    if (not clock.initialized or type(clock.last_seq) is not int
            or not 0 <= clock.last_seq <= _MAX_SEQ):
        raise NewsFeedCaptureError('capture clock is not usable')
    before = _projection(_article(database, news_id))
    state = (NewsFeedState.objects.using(database.alias).select_for_update()
             .filter(scope_id=_SCOPE, generation=clock.generation, news_id=news_id).first())
    if state is None:
        if before is not None:
            raise NewsFeedCaptureError('public source is missing its T0/captured state')
        # This is a current hidden fact, not inferred pre-T0 publication history.
        state = NewsFeedState.objects.using(database.alias).create(
            scope_id=_SCOPE, generation=clock.generation, news_id=news_id,
            current_visible=False, ever_public=False, revision_seq=0, fingerprint=None)
    visible = before is not None
    fingerprint = before.version if visible else None
    if (state.scope_id != _SCOPE or state.generation != clock.generation
            or state.news_id != news_id or state.current_visible != visible
            or state.fingerprint != fingerprint
            or type(state.revision_seq) is not int
            or not 0 <= state.revision_seq <= clock.last_seq
            or (visible and not state.ever_public)
            or (not state.ever_public and state.revision_seq != 0)):
        raise NewsFeedCaptureError('persisted source and capture state disagree')
    return _Unit(database, database.connection, outer, get_ident(), news_id,
                 clock, state, before, _clock_signature(clock), _state_signature(state))


def _capture_final(unit):
    database = unit.database
    _require_owner(unit, database)
    if unit.poison is not None:
        raise NewsFeedCaptureError('nested capture failed; entire unit must roll back') from unit.poison
    # Detect unexpected same-unit changes to the coordination facts. The Clock
    # lock remains held; neither these reads nor the final projection commits.
    try:
        clock = NewsFeedClock.objects.using(database.alias).get(scope=_SCOPE)
        state = NewsFeedState.objects.using(database.alias).get(pk=unit.state.pk)
    except (NewsFeedClock.DoesNotExist, NewsFeedState.DoesNotExist) as error:
        raise NewsFeedCaptureError('capture coordination fact disappeared') from error
    if (_clock_signature(clock) != unit.clock_signature
            or _state_signature(state) != unit.state_signature):
        raise NewsFeedCaptureError('capture coordination facts changed inside the unit')
    final = _projection(_article(database, unit.news_id))  # Fresh persisted values, not dirty caller memory.
    change = classify_final(str(unit.news_id), unit.before, final)
    if change is None:
        return
    if clock.last_seq == _MAX_SEQ:
        raise NewsFeedCaptureError('capture sequence exhausted')
    position = clock.last_seq + 1  # Transactional row column, not a DB sequence/MAX.
    clock.last_seq = position
    clock.save(using=database.alias, update_fields=['last_seq'])
    state.current_visible = final is not None
    state.ever_public = state.ever_public or final is not None
    state.fingerprint = final.version if final is not None else None
    state.revision_seq = position
    state.save(using=database.alias, update_fields=[
        'current_visible', 'ever_public', 'fingerprint', 'revision_seq'])
    # Preserve SQL/driver exceptions and callback failures; the outer atomic
    # rolls Article/OperationLog/State/Change/counter back together.
    NewsFeedChange.objects.using(database.alias).create(
        scope_id=_SCOPE, generation=clock.generation, seq=position,
        news_id=unit.news_id, kind=change.kind)


@contextmanager
def capture_news_change(news_id, using='default'):
    active = _ACTIVE_UNIT.get()
    enabled = getattr(settings, 'NEWS_FEED_CAPTURE_ENABLED', False)
    if active is not None:
        try:
            database = connections[using]
            if not enabled or using != active.database.alias or type(news_id) is not int or news_id != active.news_id:
                raise FeedCaptureBoundaryError('reentry must retain the same enabled news/connection')
            _require_owner(active, database)
            if active.poison is not None:
                raise NewsFeedCaptureError('capture unit has already failed') from active.poison
            yield  # No nested atomic/savepoint or intermediate capture.
        except BaseException as error:
            if active.poison is None:
                active.poison = error
            raise
        return
    if not enabled:
        yield  # No connection lookup, SQL or extra atomic in the old path.
        return
    if type(news_id) is not int or not 0 < news_id <= _MAX_SEQ:
        raise FeedCaptureBoundaryError('capture requires a positive int64 news ID')
    database = connections[using]
    if (database.vendor != 'postgresql' or database.in_atomic_block
            or not database.get_autocommit()):
        raise FeedCaptureBoundaryError('capture requires PostgreSQL and no unrelated outer transaction')
    outer = transaction.atomic(using=using, durable=True)
    with outer:
        unit = _prepare(database, outer, news_id)
        _require_owner(unit, database)
        token = _ACTIVE_UNIT.set(unit)
        try:
            yield
            _capture_final(unit)
        finally:
            # Restore BEFORE atomic.__exit__: existing headline on_commit must
            # never inherit a unit whose Clock lock/transaction has ended.
            _ACTIVE_UNIT.reset(token)
