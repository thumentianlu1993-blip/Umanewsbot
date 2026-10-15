"""A01–A08 synthetic reference semantics; no Django setup or resource access."""
import sys
import unittest

# Installed before importing the implementation, fixtures or application setup.
# Process-wide audit protection is intentionally limited to this standalone suite.
GUARD_ATTEMPTS = []


def deny_resources(event, args):
    forbidden = event.startswith('socket.') or event in (
        'sqlite3.connect', 'subprocess.Popen', 'os.system')
    forbidden |= (event == 'import' and args[0].split('.')[0] in
                  {'django', 'psycopg', 'psycopg2'})
    if forbidden:
        GUARD_ATTEMPTS.append(event)
        raise RuntimeError('C151 standalone resource guard: '+event)


if __name__ == '__main__':
    sys.addaudithook(deny_resources)
from stable.services import news_feed_semantics as f


C = f.Context('g1', 'public-detail', 'e1')
DTO = f.PublicDTO('7', 'synthetic title', '', '/news/7/',
                  '2026-10-15T00:00:00Z', 'synthetic-projection-version')
OTHER = f.PublicDTO('8', 'other synthetic', 'summary', '/news/8/',
                    '2026-10-15T00:00:00Z', 'other-version')


def baseline(context=C, floor=100):
    return f.begin_baseline(f.Controller(context), 'baseline-id', floor)


def members(state, ids=('7',), done=True, scanned=7):
    state, ticket = f.issue_page(state, 'page-'+str(scanned))
    return f.baseline_page(state, ticket, ids, scanned, done)


def positive(state, news='7', revision=1, dto=DTO, trigger=None, token='lookup'):
    state, ticket = f.issue_detail(state, news, token, trigger)
    return f.resolve(state, ticket, state.context, 200, dto, revision), ticket


def caught_up(context=C, floor=0):
    state = members(baseline(context, floor), (), scanned=0)
    return f.finish_baseline(state)


class NetChangeTests(unittest.TestCase):
    def test_A01_publish_correct_withdraw_republish_only_final_public_fields(self):
        changed = f.PublicDTO('7', 'correction', '', '/news/7/', DTO.published_at,
                              'new-projection-version')
        self.assertEqual(f.classify_final('7', None, DTO), f.NetChange('7', 'publish'))
        self.assertEqual(f.classify_final('7', DTO, changed), f.NetChange('7', 'correct'))
        self.assertEqual(f.classify_final('7', changed, None), f.NetChange('7', 'withdraw'))
        # A later publication must emit again even with the original fingerprint.
        self.assertEqual(f.classify_final('7', None, DTO), f.NetChange('7', 'publish'))
        self.assertEqual(vars(f.classify_final('7', DTO, None)),
                         {'news_id': '7', 'kind': 'withdraw'})

    def test_A01_homepage_removal_internal_updates_and_same_minute_are_no_change(self):
        # Qualification and minute projection already persisted upstream; homepage
        # membership and internal state are deliberately absent from this input.
        self.assertIsNone(f.classify_final('7', DTO, DTO))
        version_only = f.PublicDTO('7', DTO.title, '', DTO.public_path,
                                  DTO.published_at, 'unrelated-observation')
        self.assertIsNone(f.classify_final('7', DTO, version_only))

    def test_A02_publish_then_withdraw_in_transaction_has_no_final_event(self):
        self.assertIsNone(f.classify_final('7', None, None))

    def test_A02_dirty_object_and_mismatched_news_projection_are_rejected(self):
        class Dirty:
            @property
            def effective_title(self):
                raise AssertionError('dirty property must never be read')
        with self.assertRaises(ValueError):
            f.classify_final('7', None, Dirty())
        with self.assertRaises(ValueError):
            f.classify_final('7', DTO, OTHER)


class FenceTests(unittest.TestCase):
    def test_A04_retired_epoch_nonce_can_never_be_reused_on_later_restart(self):
        first = baseline()
        second = f.rebuild(first, f.Context('g1', C.scope, 'e2'), 'restart')
        with self.assertRaises(ValueError):
            f.rebuild(second, C, 'restart')

    def test_A03_ticket_nonce_reuse_and_wrong_phase_are_not_apply_authority(self):
        from dataclasses import replace
        state = members(baseline())
        state, ticket = f.issue_detail(state, '7', 'detail-once')
        self.assertEqual(f.resolve(state, replace(ticket, phase='LIVE'), C,
                                   200, DTO, 1), state)
        state = f.resolve(state, ticket, C, 200, DTO, 1)
        with self.assertRaises(ValueError):
            f.issue_page(state, 'detail-once')

    def test_A03_old_generation_results_errors_cleanup_and_pages_have_zero_effect(self):
        old = members(baseline(), ('7',))
        old, ticket = f.issue_detail(old, '7', 'old')
        old, page = f.issue_page(old, 'old-page')
        new = f.rebuild(old, f.Context('g2', 'public-detail', 'e2'), 'generation')
        new = members(f.begin_baseline(new, 'new-baseline', 1))
        new, _ = positive(new, revision=1)
        self.assertEqual(new.contents, (f.Content(DTO, 1),))
        for status, dto, revision in [(200, DTO, 98), (404, None, None),
                                      (503, None, None)]:
            self.assertEqual(f.resolve(new, ticket, C, status, dto, revision), new)
        self.assertEqual(f.finish_ticket(new, ticket), new)
        self.assertEqual(f.baseline_page(new, page, (), 999, True), new)
        self.assertEqual(new.scan_after, 1)

    def test_A04_same_generation_epoch_scope_and_restart_retire_old_tickets(self):
        old = members(baseline())
        old, ticket = f.issue_detail(old, '7', 'old')
        for context, reason in [(f.Context('g1', 'public-detail', 'e2'), 'gap'),
                                (f.Context('g1', 'other-scope', 'e2'), 'scope'),
                                (f.Context('g1', 'public-detail', 'e3'), 'restart')]:
            with self.subTest(reason=reason):
                new = f.rebuild(old, context, reason)
                self.assertEqual((new.phase, new.owners, new.contents),
                                 ('HANDSHAKE', (), ()))
                self.assertEqual(len(new.retired), 1)
                self.assertEqual(new.retired[-1].context, C)
                self.assertEqual(f.resolve(new, ticket, C, 200, DTO, 1000), new)
        with self.assertRaises(ValueError):
            f.rebuild(old, C, 'restart')

    def test_A05_marker_immediately_fences_old_200_even_forward_revision(self):
        state = caught_up(floor=39)
        state, page = f.issue_page(state, 'feed40')
        state = f.feed_page(state, page, 40, (f.Marker(C, 40, '7', 'publish'),), True)
        state, old = f.issue_detail(state, '7', 'old', 40)
        state, page = f.issue_page(state, 'feed41')
        state = f.feed_page(state, page, 41, (f.Marker(C, 41, '7', 'withdraw'),), True)
        self.assertEqual(f.resolve(state, old, C, 200, DTO, 999), state)
        state, current = f.issue_detail(state, '7', 'new', 41)
        self.assertEqual(f.finish_ticket(state, old), state)
        state = f.resolve(state, current, C, 404)
        self.assertEqual((state.contents, state.applied_through), ((), 41))

    def test_A05_old_404_cannot_remove_republication_or_release_retry_owner(self):
        state = caught_up(floor=39)
        state, page = f.issue_page(state, 'feed')
        state = f.feed_page(state, page, 40, (f.Marker(C, 40, '7', 'withdraw'),), True)
        state, old = f.issue_detail(state, '7', 'old', 40)
        state, page = f.issue_page(state, 'feed-next')
        state = f.feed_page(state, page, 41, (f.Marker(C, 41, '7', 'publish'),), True)
        state, retry = f.issue_detail(state, '7', 'retry', 41)
        self.assertEqual(f.resolve(state, old, C, 404), state)
        self.assertEqual(f.finish_ticket(state, old), state)
        self.assertEqual(state.owners, (retry,))
        state = f.resolve(state, retry, C, 200, DTO, 41)
        self.assertEqual(state.contents, (f.Content(DTO, 41),))

    def test_A05_response_context_phase_and_lower_replica_revision_do_not_apply(self):
        state = caught_up(floor=0)
        state, page = f.issue_page(state, 'feed')
        state = f.feed_page(state, page, 1, (f.Marker(C, 1, '7', 'publish'),), True)
        state, ticket = f.issue_detail(state, '7', 'detail', 1)
        for ctx, rev in [(f.Context('g2', C.scope, C.epoch), 100), (C, 0)]:
            self.assertEqual(f.resolve(state, ticket, ctx, 200, DTO, rev), state)
        state = f.resolve(state, ticket, C, 200, DTO, 1)
        self.assertEqual(state.contents, (f.Content(DTO, 1),))
        self.assertEqual(f.resolve(state, ticket, C, 404), state)


class BaselineTests(unittest.TestCase):
    def test_A04_retirement_preserves_baseline_negative_and_completed_facts(self):
        state = members(baseline())
        state, ticket = f.issue_detail(state, '7', 'missing')
        state = f.resolve(state, ticket, C, 404)
        state = f.finish_baseline(state)
        state, page = f.issue_page(state, 'empty-frame')
        state = f.feed_page(state, page, 100, (), True)
        new = f.rebuild(state, f.Context('g1', C.scope, 'e2'), 'restart')
        fact = new.retired[-1]
        self.assertEqual(getattr(fact, 'unavailable', None), ('7',))
        self.assertEqual(getattr(fact, 'through', None), 100)
        self.assertTrue(getattr(fact, 'baseline_complete', False))

    def test_A06_H_is_floor_not_object_revision_forward_content_is_allowed(self):
        for revision in [1, 110]:
            with self.subTest(revision=revision):
                state = members(baseline(floor=100))
                state, _ = positive(state, revision=revision)
                self.assertEqual(state.contents, (f.Content(DTO, revision),))
                self.assertEqual((state.scan_after, state.applied_through), (100, 100))
                self.assertEqual(f.finish_baseline(state).phase, 'CATCHUP')

    def test_A06_empty_or_omitted_page_and_duplicate_404_do_not_delete_positive(self):
        state = members(baseline(), done=False)
        state, ticket = positive(state, revision=110)
        self.assertEqual(f.resolve(state, ticket, C, 404), state)
        with self.assertRaises(ValueError):
            f.issue_detail(state, '7', 'negative-after-success')
        state = members(state, (), done=True, scanned=8)
        self.assertEqual(state.contents, (f.Content(DTO, 110),))
        self.assertEqual(f.finish_baseline(state).phase, 'CATCHUP')

    def test_A06_negative_lookup_has_no_hidden_revision_and_pending_blocks_barrier(self):
        state = members(baseline())
        self.assertEqual(f.finish_baseline(state), state)
        state, ticket = f.issue_detail(state, '7', 'missing')
        self.assertEqual(f.finish_baseline(state), state)
        state = f.resolve(state, ticket, C, 404)
        self.assertEqual((state.contents, state.unavailable, state.applied_through),
                         ((), ('7',), 100))
        state = f.finish_baseline(state)
        self.assertEqual(state.phase, 'CATCHUP')
        self.assertEqual(f.resolve(state, ticket, C, 200, DTO, 110), state)

    def test_A06_page_ticket_phase_and_context_cannot_advance_new_baseline(self):
        state = baseline()
        state, page = f.issue_page(state, 'old-page')
        new = f.begin_baseline(f.rebuild(state, f.Context('g1', C.scope, 'e2'), 'gap'),
                               'new', 1)
        self.assertEqual(f.baseline_page(new, page, (), 999, True), new)
        state = f.baseline_page(state, page, (), 7, True)
        state = f.finish_baseline(state)
        self.assertEqual(f.baseline_page(state, page, ('7',), 999, True), state)
        self.assertEqual(state.baseline_scanned, 7)


class CheckpointTests(unittest.TestCase):
    def test_A01_same_projection_republication_is_a_new_position_not_digest_dedup(self):
        state = caught_up(floor=0)
        for seq, kind, status in [(1, 'publish', 200), (2, 'withdraw', 404),
                                   (3, 'publish', 200)]:
            state, page = f.issue_page(state, 'page-'+str(seq))
            state = f.feed_page(state, page, seq, (f.Marker(C, seq, '7', kind),), True)
            state, ticket = f.issue_detail(state, '7', 'detail-'+str(seq), seq)
            state = f.resolve(state, ticket, C, status,
                              DTO if status == 200 else None,
                              seq if status == 200 else None)
        self.assertEqual(state.contents, (f.Content(DTO, 3),))
        self.assertEqual((state.scan_after, state.applied_through), (3, 3))
        self.assertEqual(tuple(w.marker.kind for w in state.work),
                         ('publish', 'withdraw', 'publish'))

    def frame(self):
        state = caught_up(floor=97)
        state, page = f.issue_page(state, 'feed')
        return f.feed_page(state, page, 100,
                           (f.Marker(C, 98, '7', 'publish'),
                            f.Marker(C, 99, '8', 'publish'),
                            f.Marker(C, 100, '8', 'correct')), True)

    def test_A07_scan100_pending98_503_never_means_applied100(self):
        state = self.frame()
        state, pending = f.issue_detail(state, '7', 'pending98', 98)
        self.assertEqual(f.resolve(state, pending, C, 503), state)
        state, other = f.issue_detail(state, '8', 'other100', 100)
        state = f.resolve(state, other, C, 200, OTHER, 110)
        self.assertEqual((state.scan_after, state.applied_through), (100, 97))
        self.assertFalse(f.current_complete(state))
        state = f.resolve(state, pending, C, 200, DTO, 98)
        self.assertEqual(state.applied_through, 100)
        self.assertTrue(f.current_complete(state))

    def test_A07_restart_preserves_old_pending_facts_never_restores_scan100(self):
        old = self.frame()
        old, ticket = f.issue_detail(old, '7', 'pending98', 98)
        new = f.rebuild(old, f.Context('g1', C.scope, 'e2'), 'restart')
        self.assertEqual((new.scan_after, new.applied_through, new.owners), (0, 0, ()))
        self.assertEqual(len(new.retired), 1)
        fact = new.retired[-1]
        self.assertEqual((fact.scan_after, fact.applied_through), (100, 97))
        self.assertEqual(fact.work, old.work)
        self.assertTrue(any(w.marker.seq == 98 and not w.done for w in fact.work))
        self.assertEqual(fact.disposition, 'retired_unresolved')
        self.assertEqual(f.resolve(new, ticket, C, 200, DTO, 100), new)
        self.assertEqual(old.scan_after, 100)

    def test_A08_new_baseline_current_complete_does_not_close_old_history_gap(self):
        old = self.frame()
        new = f.rebuild(old, f.Context('g2', C.scope, 'e2'), 'generation')
        new = members(f.begin_baseline(new, 'new-baseline', 1), (), scanned=0)
        new = f.finish_baseline(new)
        new, page = f.issue_page(new, 'empty-frame')
        new = f.feed_page(new, page, 1, (), True)
        self.assertTrue(f.current_complete(new))
        self.assertFalse(f.history_complete(new))
        self.assertIn('generation', new.history_gaps)
        self.assertEqual(new.retired[-1].work, old.work)

    def test_A08_missing_sequence_fake_complete_and_nondurable_checkpoint_rejected(self):
        state = caught_up(floor=97)
        state, page = f.issue_page(state, 'feed')
        for markers, durable in [((f.Marker(C, 100, '7', 'publish'),), True),
                                 ((), True),
                                 ((f.Marker(C, 98, '7', 'publish'),), False)]:
            with self.subTest(markers=markers, durable=durable):
                with self.assertRaises(ValueError):
                    f.feed_page(state, page, 100, markers, durable)
                self.assertEqual((state.scan_after, state.applied_through), (97, 97))

    def test_A08_old_feed_page_and_forged_marker_context_are_rejected(self):
        state = caught_up(floor=97)
        state, page = f.issue_page(state, 'old-feed')
        new = f.rebuild(state, f.Context('g2', C.scope, 'e2'), 'gap')
        self.assertEqual(f.feed_page(new, page, 100, (), True), new)
        with self.assertRaises(ValueError):
            f.feed_page(state, page, 98,
                        (f.Marker(f.Context('g2', C.scope, 'e2'), 98, '7', 'publish'),), True)


if __name__ == '__main__':
    result = unittest.main(exit=False)
    print('C151 resource guard attempts:', len(GUARD_ATTEMPTS), flush=True)
    sys.exit(0 if result.result.wasSuccessful() and not GUARD_ATTEMPTS else 1)
