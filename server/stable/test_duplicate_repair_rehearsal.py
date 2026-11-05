"""仅用合成行验证离线修复规划，不连接生产或第三方。"""
import copy
import unittest

from stable.services.duplicate_repair_rehearsal import build_plan, digest


def fixture():
    news = dict(source_site="sample", source_article_id="a", source_url="https://example.invalid/a",
                title_ja="same", workflow_status="ignored", published_to_web_at=None,
                public_slug="", body_zh="keep", created_at="2026-01-01", last_seen_at="2026-01-02")
    term = dict(term_type="horse", source_language="ja", normalized_key="name", source_ja="name",
                target_zh="", suggested_target_zh="", aliases_ja=[], aliases_zh=[], status="pending",
                accepted_term_id=None, merged_into_term_id=None, merged_into_candidate_id=None,
                first_seen_at="2026-01-01", last_seen_at="2026-01-02", confidence=60,
                occurrence_count=99, article_count=99, detection_reasons=[], reviewed_at=None)
    return {
        "stable_newsarticle": [dict(news, id=10), dict(news, id=11, body_zh="different")],
        "stable_termcandidate": [dict(term, id=20, status="rejected", reviewed_at="2026-01-03"), dict(term, id=21)],
        "stable_termcandidateevidence": [
            dict(id=30, candidate_id=20, article_id=100, occurrence_count=2, confidence=70,
                 contexts=["one"], source_fields=["title"], detectors=["a"], reasons=[]),
            dict(id=31, candidate_id=21, article_id=100, occurrence_count=2, confidence=70,
                 contexts=["two"], source_fields=["body"], detectors=["a"], reasons=[]),
        ],
        "stable_windowcandidatedecision": [
            dict(id=40, article_id=10, window_id=50, status="blocked", score=0, rank=None, payload={}),
            dict(id=41, article_id=11, window_id=50, status="blocked", score=0, rank=None, payload={"old": 11}),
        ],
        "stable_productionwindow": [dict(id=50, status="succeeded", lease_expires_at=None)],
        "stable_newssnapshot": [dict(id=60, article_id=11, snapshot_metadata={"article_id": 11})],
        "stable_qqpushdelivery": [],
    }


class DuplicateRepairPlanTests(unittest.TestCase):
    def test_preserves_content_history_and_review_decisions(self):
        before = fixture(); unchanged = copy.deepcopy(before)
        plan = build_plan(before, {10}, {20})
        after = plan["after"]
        self.assertEqual(before, unchanged)
        self.assertEqual(after["stable_newsarticle"], [before["stable_newsarticle"][0]])
        self.assertEqual(after["stable_termcandidate"][0]["status"], "rejected")
        self.assertEqual(after["stable_termcandidate"][0]["occurrence_count"], 2)
        self.assertEqual(after["stable_termcandidate"][0]["article_count"], 1)
        evidence = after["stable_termcandidateevidence"][0]
        self.assertEqual(evidence["contexts"], ["one", "two"])
        self.assertEqual(evidence["source_fields"], ["title", "body"])
        self.assertEqual(after["stable_newssnapshot"][0]["article_id"], 10)
        self.assertEqual(after["stable_newssnapshot"][0]["snapshot_metadata"], {"article_id": 11})
        self.assertEqual(len(after["stable_windowcandidatedecision"]), 1)
        self.assertEqual(plan["before_sha256"], digest(before))

    def test_unknown_anchor_rejected(self):
        with self.assertRaises(ValueError): build_plan(fixture(), {999}, {20})

    def test_source_identity_variation_rejected(self):
        data = fixture(); data["stable_newsarticle"][1]["source_url"] += "different"
        with self.assertRaises(ValueError): build_plan(data, {10}, {20})

    def test_published_loser_rejected(self):
        data = fixture(); data["stable_newsarticle"][1]["published_to_web_at"] = "2026-01-01"
        with self.assertRaises(ValueError): build_plan(data, {10}, {20})

    def test_draft_slug_is_not_a_publication_receipt(self):
        data = fixture(); data["stable_newsarticle"][1]["public_slug"] = "allocated-on-save"
        self.assertEqual(len(build_plan(data, {10}, {20})["after"]["stable_newsarticle"]), 1)

    def test_conflicting_term_name_rejected(self):
        data = fixture(); data["stable_termcandidate"][1]["target_zh"] = "不能自行决定"
        with self.assertRaises(ValueError): build_plan(data, {10}, {20})

    def test_evidence_count_conflict_rejected(self):
        data = fixture(); data["stable_termcandidateevidence"][1]["occurrence_count"] = 4
        with self.assertRaises(ValueError): build_plan(data, {10}, {20})

    def test_active_window_rejected(self):
        data = fixture(); data["stable_productionwindow"][0]["status"] = "running"
        with self.assertRaises(ValueError): build_plan(data, {10}, {20})

    def test_finished_expired_lease_is_historical_not_active(self):
        data = fixture(); data["stable_productionwindow"][0].update(
            lease_expires_at="2026-01-01T00:10:00+00:00", finished_at="2026-01-01T00:01:00+00:00")
        build_plan(data, {10}, {20}, observed_at="2026-02-01T00:00:00+00:00")
        with self.assertRaises(ValueError):
            build_plan(data, {10}, {20}, observed_at="2026-01-01T00:05:00+00:00")

    def test_unknown_reference_rejected(self):
        data = fixture(); data["stable_mediaasset"] = [dict(id=70, article_id=11)]
        with self.assertRaises(ValueError): build_plan(data, {10}, {20})

    def test_rejected_status_requires_explicit_anchor(self):
        with self.assertRaises(ValueError): build_plan(fixture(), {10}, set())

    def test_delivery_is_never_requeued_or_moved(self):
        data = fixture(); data["stable_qqpushdelivery"] = [dict(id=80, article_id=10, status="sent")]
        self.assertEqual(build_plan(data, {10}, {20})["after"]["stable_qqpushdelivery"], data["stable_qqpushdelivery"])
        data["stable_qqpushdelivery"][0]["article_id"] = 11
        with self.assertRaises(ValueError): build_plan(data, {10}, {20})


if __name__ == "__main__": unittest.main()
