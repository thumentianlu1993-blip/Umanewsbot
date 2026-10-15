"""Q03 pure reference facts; no database, client SDK or thread atomicity."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Context:
    generation: str
    scope: str
    epoch: str


@dataclass(frozen=True)
class PublicDTO:
    id: str
    title: str
    summary: str
    public_path: str
    published_at: str
    version: str


@dataclass(frozen=True)
class NetChange:
    news_id: str
    kind: str


@dataclass(frozen=True)
class Marker:
    context: Context
    seq: int
    news_id: str
    kind: str


@dataclass(frozen=True)
class Work:
    marker: Marker
    done: bool = False


@dataclass(frozen=True)
class Content:
    dto: PublicDTO
    revision: int


@dataclass(frozen=True)
class Ticket:
    context: Context
    token: str
    phase: str
    news_id: str | None = None
    trigger: int | None = None


@dataclass(frozen=True)
class RetiredEpoch:
    context: Context
    baseline_id: str | None
    floor: int
    scan_after: int
    applied_through: int
    work: tuple[Work, ...]
    disposition: str
    baseline_scanned: int
    baseline_pending: tuple[str, ...]
    tickets: tuple[Ticket, ...]
    contents: tuple[Content, ...]
    unavailable: tuple[str, ...]
    baseline_pages_done: bool
    baseline_complete: bool
    through: int | None


@dataclass(frozen=True)
class Controller:
    context: Context
    phase: str = 'HANDSHAKE'
    baseline_id: str | None = None
    floor: int = 0
    baseline_scanned: int = 0
    baseline_pages_done: bool = False
    baseline_pending: tuple[str, ...] = ()
    baseline_complete: bool = False
    unavailable: tuple[str, ...] = ()
    contents: tuple[Content, ...] = ()
    owners: tuple[Ticket, ...] = ()
    page_owner: Ticket | None = None
    latest_markers: tuple[tuple[str, int], ...] = ()
    work: tuple[Work, ...] = ()
    scan_after: int = 0
    applied_through: int = 0
    through: int | None = None
    retired: tuple[RetiredEpoch, ...] = ()
    history_gaps: tuple[str, ...] = ()
    used_tokens: tuple[str, ...] = ()


def _number(value):
    if type(value) is not int or value < 0:
        raise ValueError('nonnegative integer sequence required')
    return value


def _dto(value, news_id):
    if not isinstance(value, PublicDTO) or value.id != news_id:
        raise ValueError('persisted public projection for the same news required')
    if any(type(v) is not str for v in vars(value).values()):
        raise ValueError('public projection fields must be strings')
    return value


def classify_final(news_id, before, final):
    """Caller must obtain both projections from persisted transaction facts.

    None means nonpublic in the all-public-detail scope. No model properties or
    fingerprint are computed here; an unsaved/dirty object is not an input.
    """
    for value in (before, final):
        if value is not None:
            _dto(value, news_id)
    if before is None and final is None:
        return None
    if before is None:
        return NetChange(news_id, 'publish')
    if final is None:
        return NetChange(news_id, 'withdraw')
    fields = ('id', 'title', 'summary', 'public_path', 'published_at')
    if any(getattr(before, k) != getattr(final, k) for k in fields):
        return NetChange(news_id, 'correct')
    return None


def begin_baseline(state, baseline_id, floor):
    if state.phase != 'HANDSHAKE' or not baseline_id:
        raise ValueError('new handshake and explicit baseline required')
    floor = _number(floor)
    return replace(state, phase='BASELINE', baseline_id=baseline_id,
                   floor=floor, scan_after=floor, applied_through=floor)


def _new_ticket(state, token, news_id=None, trigger=None):
    if type(token) is not str or not token or token in state.used_tokens:
        raise ValueError('unique request ticket required for this epoch')
    return Ticket(state.context, token, state.phase, news_id, trigger)


def issue_page(state, token):
    if state.phase not in ('BASELINE', 'CATCHUP', 'LIVE'):
        raise ValueError('page cannot be issued before baseline handshake')
    ticket = _new_ticket(state, token)
    return replace(state, page_owner=ticket,
                   used_tokens=state.used_tokens+(token,)), ticket


def issue_detail(state, news_id, token, trigger=None):
    if state.phase == 'BASELINE':
        if trigger is not None or news_id not in state.baseline_pending:
            raise ValueError('only unresolved baseline member may be looked up')
    elif state.phase in ('CATCHUP', 'LIVE'):
        if trigger is None or dict(state.latest_markers).get(news_id) != trigger:
            raise ValueError('detail must belong to the latest delivered marker')
        _number(trigger)
    else:
        raise ValueError('detail cannot apply during handshake')
    ticket = _new_ticket(state, token, news_id, trigger)
    owners = tuple(t for t in state.owners if t.news_id != news_id)+(ticket,)
    return replace(state, owners=owners,
                   used_tokens=state.used_tokens+(token,)), ticket


def _gate(state, ticket):
    if ticket.context != state.context or ticket.phase != state.phase:
        return False
    if ticket.news_id is None:
        return state.page_owner == ticket
    return ticket in state.owners


def _detail_gate(state, ticket):
    if not _gate(state, ticket) or ticket.news_id is None:
        return False
    latest = dict(state.latest_markers).get(ticket.news_id)
    return latest is None or (ticket.trigger is not None and ticket.trigger >= latest)


def baseline_page(state, ticket, member_ids, scanned, done):
    if not _gate(state, ticket) or ticket.news_id is not None or state.phase != 'BASELINE':
        return state
    scanned = _number(scanned)
    if scanned < state.baseline_scanned or state.baseline_pages_done:
        raise ValueError('baseline scan cannot regress or resume a closed page set')
    if type(done) is not bool or len(set(member_ids)) != len(member_ids):
        raise ValueError('invalid baseline page facts')
    finished = {c.dto.id for c in state.contents} | set(state.unavailable)
    pending = tuple(sorted(set(state.baseline_pending) | (set(member_ids)-finished)))
    return replace(state, baseline_scanned=scanned, baseline_pages_done=done,
                   baseline_pending=pending, page_owner=None)


def finish_baseline(state):
    if (state.phase != 'BASELINE' or not state.baseline_pages_done
            or state.baseline_pending or state.owners or state.page_owner):
        return state
    return replace(state, phase='CATCHUP', baseline_complete=True)


def feed_page(state, ticket, through, markers, durable_queue):
    """Return scan+work together; caller must durably commit this whole value.

    A bool here is an integration obligation, never proof of actual persistence.
    Missing sequence/empty future frame cannot masquerade as a complete queue.
    """
    if not _gate(state, ticket) or ticket.news_id is not None or state.phase not in ('CATCHUP', 'LIVE'):
        return state
    through = _number(through)
    if through < state.scan_after:
        raise ValueError('frame endpoint precedes scan checkpoint')
    if state.through is not None and state.scan_after < state.through and through != state.through:
        raise ValueError('through must remain fixed within a frame')
    if not durable_queue:
        raise ValueError('cannot advance a recovery checkpoint without durable work')
    expected = state.scan_after+1
    latest = dict(state.latest_markers)
    work = state.work
    for marker in markers:
        if (not isinstance(marker, Marker) or marker.context != state.context
                or type(marker.seq) is not int or marker.seq != expected
                or marker.seq > through or marker.kind not in ('publish', 'correct', 'withdraw')):
            raise ValueError('invalid or incomplete delivered event prefix')
        expected += 1
        latest[marker.news_id] = marker.seq  # Fence rises before any GET result.
        work += (Work(marker),)
    if not markers and through > state.scan_after:
        raise ValueError('empty page is not completion of an undelivered prefix')
    return replace(state, through=through, scan_after=expected-1, work=work,
                   latest_markers=tuple(sorted(latest.items())), page_owner=None)


def _settle(state, ticket, through_revision):
    work = tuple(replace(w, done=True)
                 if w.marker.news_id == ticket.news_id and w.marker.seq <= through_revision
                 else w for w in state.work)
    applied = state.floor
    for w in work:
        if w.marker.seq != applied+1 or not w.done:
            break
        applied = w.marker.seq
    return replace(state, work=work, applied_through=applied,
                   owners=tuple(t for t in state.owners if t != ticket))


def resolve(state, ticket, response_context, status, dto=None, revision=None):
    """Pure compare-and-apply specification, not a thread-safe callback handler."""
    if response_context != state.context or not _detail_gate(state, ticket):
        return state
    if status not in (200, 404):
        return state  # Error is pending/retry, never withdrawal or epoch switch.
    existing = next((c for c in state.contents if c.dto.id == ticket.news_id), None)
    if status == 200:
        dto = _dto(dto, ticket.news_id)
        revision = _number(revision)
        if ((ticket.trigger is not None and revision < ticket.trigger)
                or (existing is not None and revision < existing.revision)):
            return state
        contents = tuple(c for c in state.contents if c.dto.id != ticket.news_id)+(Content(dto, revision),)
    else:
        # A generic 404 has no hidden revision. Baseline absence only records an
        # unresolved member; event absence cannot erase accepted forward content.
        if existing is not None and (ticket.trigger is None or ticket.trigger < existing.revision):
            return state
        if dto is not None or revision is not None:
            raise ValueError('404 must not disclose hidden projection or revision')
        contents = tuple(c for c in state.contents if c.dto.id != ticket.news_id)
    state = replace(state, contents=contents)
    if state.phase == 'BASELINE':
        unavailable = state.unavailable+(ticket.news_id,) if status == 404 else state.unavailable
        return replace(state, baseline_pending=tuple(n for n in state.baseline_pending if n != ticket.news_id),
                       unavailable=unavailable, owners=tuple(t for t in state.owners if t != ticket))
    return _settle(state, ticket, revision if status == 200 else ticket.trigger)


def finish_ticket(state, ticket):
    if ticket.news_id is None:
        return replace(state, page_owner=None) if _gate(state, ticket) else state
    if not _detail_gate(state, ticket):
        return state
    # Cancellation releases only this owner. Work remains pending until retried.
    return replace(state, owners=tuple(t for t in state.owners if t != ticket))


def rebuild(state, context, reason):
    if context.epoch in {state.context.epoch, *(r.context.epoch for r in state.retired)}:
        raise ValueError('every rebuild/restart requires a fresh epoch')
    if reason not in ('gap', 'restart', 'generation', 'scope'):
        raise ValueError('explicit rebuild boundary required')
    fact = RetiredEpoch(state.context, state.baseline_id, state.floor,
                        state.scan_after, state.applied_through, state.work,
                        'retired_unresolved', state.baseline_scanned,
                        state.baseline_pending,
                        state.owners+((state.page_owner,) if state.page_owner else ()),
                        state.contents, state.unavailable, state.baseline_pages_done,
                        state.baseline_complete, state.through)
    # Old facts keep their original Context/tickets and are never replayed here.
    return Controller(context, retired=state.retired+(fact,),
                      history_gaps=state.history_gaps+(reason,))


def current_complete(state):
    return (state.baseline_complete and state.phase in ('CATCHUP', 'LIVE')
            and state.through is not None and state.scan_after >= state.through
            and state.applied_through >= state.through
            and not state.owners and state.page_owner is None)


def history_complete(state):
    """Only the delivered local frame, never a retention or pre-T0 promise."""
    return (current_complete(state) and not state.history_gaps
            and not any(not w.done for fact in state.retired for w in fact.work))
