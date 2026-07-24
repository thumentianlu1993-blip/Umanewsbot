from __future__ import annotations

import hashlib
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from stable.adapters.international import HorseRacingNationAdapter
from stable.models import (
    ArticleTranslationStatus,
    AutomationStatus,
    NewsArticle,
    OperationLog,
    PushTarget,
    QQPushDelivery,
    QQPushDeliveryStatus,
    RacingRegion,
    SourceLanguage,
    SourceMode,
    SourceSite,
    WorkflowStatus,
)
from stable.services.news_body_history import (
    ALLOWED_APPROVE_FIELDS,
    APPROVED_MANIFEST_SCHEMA_VERSION,
    CHINESE_ABSENT,
    CHINESE_INPUT_UNVERIFIABLE,
    DECISION_APPROVE_FIELDS,
    DECISION_APPROVE_NO_ACTION,
    DECISION_KEEP_MANUAL,
    DECISION_REJECT,
    SOURCE_BLOCKED,
    SOURCE_CHANGED,
    SOURCE_CLEAN,
    CohortDriftError,
    _MAX_BATCH_SIZE,
    _canonical_sha,
    _sha256,
    apply_batch_inside_transaction,
    build_inventory_row,
    build_receipt,
    build_rollback_artifact,
    compute_before_fingerprint,
    freeze_cohort,
    generate_inventory,
    rollback_batch,
    validate_approved_decisions,
    verify_batch,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "news_content_boundaries"
VALID_SHA = "a" * 64


def fixture_html(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _make_approved_manifest(decisions, *, candidate_sha=VALID_SHA, schema_version=APPROVED_MANIFEST_SCHEMA_VERSION):
    return {"schema_version": schema_version, "candidate_manifest_sha256": candidate_sha, "decisions": decisions}


def _write_json(path, payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _apply_flow(article, manifest, rollback_dir, manifest_sha=VALID_SHA):
    """Helper: full apply flow (build rollback → tx → apply → receipt)."""
    articles_pre = list(NewsArticle.objects.filter(id=article.id).order_by("id"))
    rb_path, rb_sha = build_rollback_artifact(articles_pre, output_dir=rollback_dir)
    with transaction.atomic():
        locked = list(NewsArticle.objects.select_for_update().filter(id=article.id).order_by("id"))
        results, post_fps = apply_batch_inside_transaction(
            articles=locked, approved_manifest=manifest,
            approved_manifest_sha256=manifest_sha, rollback_artifact_sha256=rb_sha)
    receipt_sha = build_receipt(approved_manifest_sha256=manifest_sha, rollback_artifact_sha256=rb_sha,
                                 results=results, post_apply_fingerprints=post_fps,
                                 output_dir=rollback_dir)
    return rb_path, rb_sha, receipt_sha


# ═══════════════════════════ Inventory ═══════════════════════════
class NewsBodyHistoryInventoryTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _article(self, suffix, *, html, body, body_zh="", translated_body_zh="",
                 translation_status=ArticleTranslationStatus.TRANSLATED, published=False, **kw):
        return NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.LATEST,
            source_article_id=f"inv-{suffix}", racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH, title_ja=f"Inv {suffix}",
            body_ja_raw=body, body_ja_normalized=body, original_content_html=html,
            body_zh=body_zh, translated_body_zh=translated_body_zh,
            translation_status=translation_status, published_at=timezone.now(),
            published_to_web_at=timezone.now() if published else None,
            source_url=f"https://horseracingnation.com/news/inv_{suffix}", **kw)

    def test_cohort_freeze(self):
        a = self._article("a", html=fixture_html("hrn_9623.html"), body="b")
        b = self._article("b", html=fixture_html("hrn_normal_article.html"), body="b")
        c = freeze_cohort(max_id=max(a.id, b.id))
        self.assertEqual(c.count, 2)
        self.assertEqual(list(c.sorted_ids), sorted([a.id, b.id]))

    def test_9623_source_clean_chinese_unverifiable(self):
        parsed = HorseRacingNationAdapter().parse_detail_html(fixture_html("hrn_9623.html"),
            url="https://horseracingnation.com/news/t")
        a = self._article("x", html=fixture_html("hrn_9623.html"), body=parsed.body_ja_raw,
                           body_zh="污染", translated_body_zh="旧译", published=True,
                           workflow_status=WorkflowStatus.PUBLISHED)
        self.assertEqual(build_inventory_row(a).source_status, SOURCE_CLEAN)

    def test_missing_html_blocked(self):
        a = self._article("x", html="", body="b")
        self.assertEqual(build_inventory_row(a).source_status, SOURCE_BLOCKED)

    def test_inventory_no_db_write(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b")
        before = a.body_ja_raw
        d = Path(self.temp_dir.name) / "inv"
        generate_inventory(max_id=a.id + 100, output_dir=d)
        a.refresh_from_db()
        self.assertEqual(a.body_ja_raw, before)
        self.assertFalse(OperationLog.objects.exists())

    # ── P1.5: cohort drift ──
    def test_cohort_count_drift(self):
        self._article("x", html=fixture_html("hrn_9623.html"), body="b")
        d = Path(self.temp_dir.name) / "d"
        with self.assertRaises(CohortDriftError):
            generate_inventory(max_id=99999, output_dir=d, expected_count=999)

    def test_cohort_sha_drift(self):
        self._article("x", html=fixture_html("hrn_9623.html"), body="b")
        d = Path(self.temp_dir.name) / "d"
        with self.assertRaises(CohortDriftError):
            generate_inventory(max_id=99999, output_dir=d, expected_id_set_sha256="0" * 64)


# ═══════════════════════════ Review / Validation ═══════════════════
class NewsBodyHistoryReviewTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _article(self, suffix, *, html, body, body_zh="", translated_body_zh="",
                 translation_status=ArticleTranslationStatus.TRANSLATED,
                 manually_edited_fields=None):
        return NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.LATEST,
            source_article_id=f"rv-{suffix}", racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH, title_ja=f"Rv {suffix}",
            body_ja_raw=body, body_ja_normalized=body, original_content_html=html,
            body_zh=body_zh, translated_body_zh=translated_body_zh,
            translated_title_zh="t" if translated_body_zh else "",
            manually_edited_fields=manually_edited_fields or [],
            translation_status=translation_status, published_at=timezone.now(),
            source_url=f"https://horseracingnation.com/news/rv_{suffix}")

    # ── P1: candidate SHA binding ──
    def test_missing_candidate_sha_rejected(self):
        m = {"schema_version": APPROVED_MANIFEST_SCHEMA_VERSION, "decisions": [
            {"article_id": 1, "decision": DECISION_APPROVE_NO_ACTION, "reviewer": "r", "reason": "x", "approved_fields": []}]}
        self.assertTrue(any("candidate_manifest_sha256" in e for e in
                            validate_approved_decisions(m, candidate_manifest_sha256=VALID_SHA)))

    # ── P1: batch size limit ──
    def test_batch_size_limit(self):
        decs = [{"article_id": i, "decision": DECISION_APPROVE_NO_ACTION, "reviewer": "r", "reason": "x", "approved_fields": []}
                for i in range(1, _MAX_BATCH_SIZE + 2)]
        m = _make_approved_manifest(decs, candidate_sha=VALID_SHA)
        self.assertTrue(any("超过上限" in e for e in
                            validate_approved_decisions(m, candidate_manifest_sha256=VALID_SHA)))

    # ── P1: field dependencies ──
    def test_body_zh_without_dep_rejected(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", body_zh="z", translated_body_zh="")
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["body_zh"], "before_fingerprint": fp,
            "exact_output": {"body_zh": "n"}}], candidate_sha=VALID_SHA)
        self.assertTrue(any("缺少依赖字段" in e for e in
                            validate_approved_decisions(m, candidate_manifest_sha256=VALID_SHA)))

    # ── P1: translation status blocks ──
    def test_pending_blocks(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t",
                           translation_status=ArticleTranslationStatus.PENDING)
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "n"}}], candidate_sha=VALID_SHA)
        self.assertTrue(any("禁止 translation_status=pending" in e for e in
                            validate_approved_decisions(m, candidate_manifest_sha256=VALID_SHA)))

    # ── P1: manual field protection ──
    def test_manual_body_zh_protected(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", body_zh="人工",
                           translated_body_zh="t", manually_edited_fields=["body_zh"])
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["body_zh", "translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"body_zh": "n", "translated_body_zh": "n"}}],
            candidate_sha=VALID_SHA)
        errors = validate_approved_decisions(m, candidate_manifest_sha256=VALID_SHA)
        self.assertTrue(any("body_zh 为人工字段" in e for e in errors),
                        f"expected manual field error, got: {errors}")

    def test_manual_protection_passes_when_no_manual_fields(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", body_zh="旧",
                           translated_body_zh="t", manually_edited_fields=[])
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["body_zh", "translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"body_zh": "n", "translated_body_zh": "n"}}],
            candidate_sha=VALID_SHA)
        self.assertEqual(validate_approved_decisions(m, candidate_manifest_sha256=VALID_SHA), [])

    # ── P1: source field prerequisites ──
    def test_source_field_without_evidence_rejected(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="old body",
                           translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        # approve body_ja_raw without source_evidence
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["body_ja_raw", "body_ja_normalized"],
            "before_fingerprint": fp, "exact_output": {"body_ja_raw": "n", "body_ja_normalized": "n"}}],
            candidate_sha=VALID_SHA)
        errors = validate_approved_decisions(m, candidate_manifest_sha256=VALID_SHA)
        self.assertTrue(any("要求 source_status" in e for e in errors),
                        f"expected source_status error, got: {errors}")

    def test_source_field_with_evidence_passes(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="old body",
                           translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x",
            "approved_fields": ["body_ja_raw", "body_ja_normalized"],
            "source_evidence": {"source_status": SOURCE_CHANGED, "body_parse_status": "ok"},
            "before_fingerprint": fp,
            "exact_output": {"body_ja_raw": "n", "body_ja_normalized": "n"}}],
            candidate_sha=VALID_SHA)
        self.assertEqual(validate_approved_decisions(m, candidate_manifest_sha256=VALID_SHA), [])


# ═══════════════════════════ Apply ═══════════════════════════
class NewsBodyHistoryApplyTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _article(self, suffix, *, html, body, body_zh="", translated_body_zh="",
                 translation_status=ArticleTranslationStatus.TRANSLATED,
                 workflow_status=WorkflowStatus.PENDING_REVIEW, published=False, **kw):
        return NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.LATEST,
            source_article_id=f"ap-{suffix}", racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH, title_ja=f"Ap {suffix}",
            body_ja_raw=body, body_ja_normalized=body, original_content_html=html,
            body_zh=body_zh, translated_body_zh=translated_body_zh,
            translated_title_zh="t" if translated_body_zh else "",
            translation_status=translation_status, workflow_status=workflow_status,
            published_at=timezone.now(),
            published_to_web_at=timezone.now() if published else None,
            source_url=f"https://horseracingnation.com/news/ap_{suffix}", **kw)

    # ── P1: candidate SHA is externally validated ──
    def test_apply_requires_candidate_manifest(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_NO_ACTION,
            "reviewer": "r", "reason": "x", "approved_fields": [], "before_fingerprint": fp}],
            candidate_sha=VALID_SHA)
        mp = Path(self.temp_dir.name) / "m.json"
        m_sha = _write_json(mp, m)
        with self.assertRaises(CommandError):
            call_command("apply_news_body_history_batch", "--manifest", str(mp),
                         "--manifest-sha256", m_sha,
                         "--rollback-dir", str(Path(self.temp_dir.name) / "rb"),
                         stdout=StringIO())

    def test_apply_rejects_candidate_sha_mismatch(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_NO_ACTION,
            "reviewer": "r", "reason": "x", "approved_fields": [], "before_fingerprint": fp}],
            candidate_sha=VALID_SHA)
        mp = Path(self.temp_dir.name) / "m.json"; m_sha = _write_json(mp, m)
        cp = Path(self.temp_dir.name) / "c.json"
        cp.write_text(json.dumps({"fake": "candidate"}))
        c_sha = hashlib.sha256(cp.read_bytes()).hexdigest()
        # approved manifest says VALID_SHA but file has different SHA → cross-check fails
        with self.assertRaises(CommandError):
            call_command("apply_news_body_history_batch", "--manifest", str(mp),
                         "--manifest-sha256", m_sha,
                         "--candidate-manifest", str(cp),
                         "--candidate-manifest-sha256", c_sha,
                         "--rollback-dir", str(Path(self.temp_dir.name) / "rb"),
                         stdout=StringIO())

    def test_rollback_artifact_outside_transaction(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        rollback_dir = Path(self.temp_dir.name) / "pretx"
        articles_pre = list(NewsArticle.objects.filter(id=a.id).order_by("id"))
        rb_path, rb_sha = build_rollback_artifact(articles_pre, output_dir=rollback_dir)
        self.assertTrue(rb_path.exists())

    def test_drift_zero_writes(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        before = a.body_ja_raw
        fp = compute_before_fingerprint(a); fp["body_ja_raw"] = "0" * 64
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "n"}}], candidate_sha=VALID_SHA)
        d = Path(self.temp_dir.name) / "rb"
        ap = list(NewsArticle.objects.filter(id=a.id).order_by("id"))
        rb, rs = build_rollback_artifact(ap, output_dir=d)
        with transaction.atomic():
            lk = list(NewsArticle.objects.select_for_update().filter(id=a.id).order_by("id"))
            with self.assertRaises(ValueError):
                apply_batch_inside_transaction(articles=lk, approved_manifest=m,
                    approved_manifest_sha256=VALID_SHA, rollback_artifact_sha256=rs)
        a.refresh_from_db(); self.assertEqual(a.body_ja_raw, before)

    def test_workflow_and_qq_preserved(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t",
                           body_zh="z", workflow_status=WorkflowStatus.PUBLISHED, published=True)
        t = PushTarget.objects.create(name="x", group_id="g")
        QQPushDelivery.objects.create(article=a, target=t, status=QQPushDeliveryStatus.SENT,
                                       message_id="m", sent_at=timezone.now())
        wf_before = a.workflow_status
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "clean"}}],
            candidate_sha=VALID_SHA)
        d = Path(self.temp_dir.name) / "rb"
        _apply_flow(a, m, d)
        a.refresh_from_db()
        self.assertEqual(a.workflow_status, wf_before)
        self.assertEqual(a.translated_body_zh, "clean")

    # ── P1: stale replay rejected ──
    def test_stale_replay_rejected(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "new"}}],
            candidate_sha=VALID_SHA)
        d1 = Path(self.temp_dir.name) / "rb1"
        _apply_flow(a, m, d1)
        a.refresh_from_db(); self.assertEqual(a.translated_body_zh, "new")
        op = OperationLog.objects.filter(action_type="news_body_history_applied").count()

        d2 = Path(self.temp_dir.name) / "rb2"
        ap2 = list(NewsArticle.objects.filter(id=a.id).order_by("id"))
        rb2, rs2 = build_rollback_artifact(ap2, output_dir=d2)
        with transaction.atomic():
            lk = list(NewsArticle.objects.select_for_update().filter(id=a.id).order_by("id"))
            with self.assertRaises(ValueError):
                apply_batch_inside_transaction(articles=lk, approved_manifest=m,
                    approved_manifest_sha256=VALID_SHA, rollback_artifact_sha256=rs2)
        self.assertEqual(OperationLog.objects.filter(action_type="news_body_history_applied").count(), op)


# ═══════════════════════════ Rollback ═══════════════════════════
class NewsBodyHistoryRollbackTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _article(self, suffix, *, html, body, body_zh="", translated_body_zh=""):
        return NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.LATEST,
            source_article_id=f"rb-{suffix}", racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH, title_ja=f"Rb {suffix}",
            body_ja_raw=body, body_ja_normalized=body, original_content_html=html,
            body_zh=body_zh, translated_body_zh=translated_body_zh,
            published_at=timezone.now(),
            source_url=f"https://horseracingnation.com/news/rb_{suffix}")

    def _make_and_apply(self, article, approved_fields, exact_output):
        """Helper: create manifest, write to file, apply, return (rb_path, rb_sha, receipt_sha, manifest_sha)."""
        manifest = _make_approved_manifest([{"article_id": article.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": approved_fields,
            "before_fingerprint": compute_before_fingerprint(article),
            "exact_output": exact_output}], candidate_sha=VALID_SHA)
        manifest_path = Path(self.temp_dir.name) / f"m-{article.id}.json"
        manifest_sha = _write_json(manifest_path, manifest)
        d = Path(self.temp_dir.name) / f"rb-{article.id}"
        rb_path, rb_sha, receipt_sha = _apply_flow(article, manifest, d, manifest_sha=manifest_sha)
        return rb_path, rb_sha, receipt_sha, d

    def test_rollback_restores_with_valid_receipt(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="旧", body_zh="旧中")
        before_t, before_b = a.translated_body_zh, a.body_zh
        rb_path, rb_sha, receipt_sha, d = self._make_and_apply(a,
            ["translated_body_zh", "body_zh"], {"translated_body_zh": "新", "body_zh": "新中"})
        a.refresh_from_db(); self.assertEqual(a.translated_body_zh, "新")

        receipt_path = d / "receipt.json"
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        rollback_batch(rollback_manifest_path=rb_path, rollback_manifest_sha256=rb_sha,
                        receipt_path=receipt_path, receipt_sha256=receipt_file_sha, commit=True)
        a.refresh_from_db()
        self.assertEqual(a.translated_body_zh, before_t)
        self.assertEqual(a.body_zh, before_b)

    # ── P1: rollback CAS rejects external edit ──
    def test_rollback_cas_rejects_external_edit(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="旧")
        rb_path, rb_sha, receipt_sha, d = self._make_and_apply(a,
            ["translated_body_zh"], {"translated_body_zh": "新"})
        a.refresh_from_db(); self.assertEqual(a.translated_body_zh, "新")

        # external edit after apply
        a.body_zh = "外部编辑"; a.save(update_fields=["body_zh", "updated_at"])

        receipt_path = d / "receipt.json"
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        with transaction.atomic():
            with self.assertRaises(ValueError):
                rollback_batch(rollback_manifest_path=rb_path, rollback_manifest_sha256=rb_sha,
                                receipt_path=receipt_path, receipt_sha256=receipt_file_sha, commit=True)
        a.refresh_from_db(); self.assertEqual(a.body_zh, "外部编辑")  # not rolled back

    # ── P1: receipt SHA mismatch rejected ──
    def test_rollback_rejects_wrong_receipt_sha(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="旧")
        rb_path, rb_sha, receipt_sha, d = self._make_and_apply(a,
            ["translated_body_zh"], {"translated_body_zh": "新"})
        receipt_path = d / "receipt.json"
        with self.assertRaises(ValueError):
            rollback_batch(rollback_manifest_path=rb_path, rollback_manifest_sha256=rb_sha,
                            receipt_path=receipt_path, receipt_sha256="0" * 64, commit=True)

    # ── P1: receipt → rollback cross-check ──
    def test_rollback_rejects_receipt_that_references_wrong_rollback(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="旧")
        rb_path, rb_sha, receipt_sha, d = self._make_and_apply(a,
            ["translated_body_zh"], {"translated_body_zh": "新"})

        # tamper receipt to reference wrong rollback SHA
        receipt_path = d / "receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["rollback_artifact_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt))
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

        with self.assertRaises(ValueError):
            rollback_batch(rollback_manifest_path=rb_path, rollback_manifest_sha256=rb_sha,
                            receipt_path=receipt_path, receipt_sha256=receipt_file_sha, commit=True)


# ═══════════════════════════ Verify ═══════════════════════════
class NewsBodyHistoryVerifyTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _article(self, suffix, *, html, body, body_zh="", translated_body_zh=""):
        return NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.LATEST,
            source_article_id=f"vf-{suffix}", racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH, title_ja=f"Vf {suffix}",
            body_ja_raw=body, body_ja_normalized=body, original_content_html=html,
            body_zh=body_zh, translated_body_zh=translated_body_zh,
            published_at=timezone.now(),
            source_url=f"https://horseracingnation.com/news/vf_{suffix}")

    # ── P1: verify trust chain — receipt SHA ──
    def test_verify_rejects_wrong_receipt_sha(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "text"}}], candidate_sha=VALID_SHA)
        manifest_path = Path(self.temp_dir.name) / "vfy-m.json"
        manifest_sha = _write_json(manifest_path, manifest)
        d = Path(self.temp_dir.name) / "rb"
        _apply_flow(a, manifest, d, manifest_sha=manifest_sha)
        receipt_path = d / "receipt.json"

        errors = verify_batch(receipt_path=receipt_path, receipt_sha256="0" * 64,
                               manifest_path=manifest_path, manifest_sha256=manifest_sha,
                               rollback_dir=d, approved_manifest=manifest)
        self.assertTrue(any("receipt 文件 SHA-256" in e for e in errors))

    # ── P1: verify trust chain — manifest SHA ──
    def test_verify_rejects_wrong_manifest_sha(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "text"}}], candidate_sha=VALID_SHA)
        manifest_path = Path(self.temp_dir.name) / "vfy-m.json"
        manifest_sha = _write_json(manifest_path, manifest)
        d = Path(self.temp_dir.name) / "rb"
        _apply_flow(a, manifest, d, manifest_sha=manifest_sha)
        receipt_path = d / "receipt.json"
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

        errors = verify_batch(receipt_path=receipt_path, receipt_sha256=receipt_file_sha,
                               manifest_path=manifest_path, manifest_sha256="0" * 64,
                               rollback_dir=d, approved_manifest=manifest)
        self.assertTrue(any("manifest 文件 SHA-256" in e for e in errors))

    # ── P1: verify trust chain — receipt → manifest cross-check ──
    def test_verify_rejects_receipt_manifest_mismatch(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "text"}}], candidate_sha=VALID_SHA)
        manifest_path = Path(self.temp_dir.name) / "vfy-m.json"
        manifest_sha = _write_json(manifest_path, manifest)
        d = Path(self.temp_dir.name) / "rb"
        _apply_flow(a, manifest, d, manifest_sha=manifest_sha)

        # tamper receipt to reference different manifest SHA
        receipt_path = d / "receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["approved_manifest_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt))
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

        errors = verify_batch(receipt_path=receipt_path, receipt_sha256=receipt_file_sha,
                               manifest_path=manifest_path, manifest_sha256=manifest_sha,
                               rollback_dir=d, approved_manifest=manifest)
        self.assertTrue(any("approved_manifest_sha256 不匹配" in e for e in errors))

    def test_verify_passes_with_valid_chain(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "text"}}], candidate_sha=VALID_SHA)
        # Write manifest to file first, get its actual SHA
        manifest_path = Path(self.temp_dir.name) / "vfy-m.json"
        manifest_sha = _write_json(manifest_path, manifest)

        d = Path(self.temp_dir.name) / "rb"
        rb_path, rb_sha, receipt_sha = _apply_flow(a, manifest, d, manifest_sha=manifest_sha)
        a.refresh_from_db(); self.assertEqual(a.translated_body_zh, "text")

        receipt_path = d / "receipt.json"
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

        errors = verify_batch(receipt_path=receipt_path, receipt_sha256=receipt_file_sha,
                               manifest_path=manifest_path, manifest_sha256=manifest_sha,
                               rollback_dir=d, approved_manifest=manifest)
        self.assertEqual(errors, [])

    def test_verify_detects_field_mismatch(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", body_zh="WRONG",
                           translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["body_zh"],
            "before_fingerprint": fp, "exact_output": {"body_zh": "EXPECTED"}}], candidate_sha=VALID_SHA)
        d = Path(self.temp_dir.name) / "rb"
        ap = list(NewsArticle.objects.filter(id=a.id).order_by("id"))
        rb_path, rb_sha = build_rollback_artifact(ap, output_dir=d)
        # write receipt claiming we applied (but actual DB field is different)
        results = [{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS, "applied": True}]
        build_receipt(approved_manifest_sha256=VALID_SHA, rollback_artifact_sha256=rb_sha,
                       results=results, post_apply_fingerprints={a.id: fp}, output_dir=d)

        receipt_path = d / "receipt.json"
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        manifest_path = Path(self.temp_dir.name) / "vfy-m.json"
        manifest_sha = _write_json(manifest_path, manifest)

        errors = verify_batch(receipt_path=receipt_path, receipt_sha256=receipt_file_sha,
                               manifest_path=manifest_path, manifest_sha256=manifest_sha,
                               rollback_dir=d, approved_manifest=manifest)
        self.assertTrue(any("body_zh" in e for e in errors))


# ═══════════════════════════ Adversarial bypass tests ═══════════════════
class NewsBodyHistoryAdversarialTests(TestCase):
    """RED tests for each reviewer-identified bypass vector."""
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _article(self, suffix, *, html, body, body_zh="", translated_body_zh="",
                 manually_edited_fields=None, translation_status=ArticleTranslationStatus.TRANSLATED):
        return NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.LATEST,
            source_article_id=f"adv-{suffix}", racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH, title_ja=f"Adv {suffix}",
            body_ja_raw=body, body_ja_normalized=body, original_content_html=html,
            body_zh=body_zh, translated_body_zh=translated_body_zh,
            translated_title_zh="t" if translated_body_zh else "",
            manually_edited_fields=manually_edited_fields or [],
            translation_status=translation_status, published_at=timezone.now(),
            source_url=f"https://horseracingnation.com/news/adv_{suffix}")

    # ── P1: legitimate source repair succeeds (not only fakes caught) ──
    def test_legitimate_source_repair_succeeds(self):
        parsed = HorseRacingNationAdapter().parse_detail_html(
            fixture_html("hrn_9623.html"), url="https://horseracingnation.com/news/t")
        # Article has OLD polluted body, but original_content_html parses to CLEAN body
        a = self._article("x", html=fixture_html("hrn_9623.html"),
                           body="OLD POLLUTED BODY WITH NAV FRAMEWORK",
                           translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "legitimate source repair",
            "approved_fields": ["body_ja_raw", "body_ja_normalized"],
            "source_evidence": {"source_status": SOURCE_CHANGED, "body_parse_status": "ok"},
            "before_fingerprint": fp,
            "exact_output": {"body_ja_raw": parsed.body_ja_raw,
                              "body_ja_normalized": parsed.body_ja_normalized}}], candidate_sha=VALID_SHA)
        d = Path(self.temp_dir.name) / "rb"
        ap = list(NewsArticle.objects.filter(id=a.id).order_by("id"))
        rb, rs = build_rollback_artifact(ap, output_dir=d)
        with transaction.atomic():
            lk = list(NewsArticle.objects.select_for_update().filter(id=a.id).order_by("id"))
            results, post_fps = apply_batch_inside_transaction(
                articles=lk, approved_manifest=manifest,
                approved_manifest_sha256=VALID_SHA, rollback_artifact_sha256=rs)
        build_receipt(approved_manifest_sha256=VALID_SHA, rollback_artifact_sha256=rs,
                       results=results, post_apply_fingerprints=post_fps, output_dir=d)
        a.refresh_from_db()
        self.assertEqual(a.body_ja_raw, parsed.body_ja_raw)
        self.assertIn("Pavel's first runners", a.body_ja_raw)
        self.assertNotIn("OLD POLLUTED", a.body_ja_raw)

    # ── P1: duplicate candidate article_id rejected ──
    def test_duplicate_candidate_article_id_rejected(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="old")
        fp = compute_before_fingerprint(a)
        # Two candidate entries with same article_id, conflicting output
        candidate = {"entries": [
            {"article_id": a.id, "approved_fields": ["translated_body_zh"],
             "exact_output": {"translated_body_zh": "CONFLICT A"}},
            {"article_id": a.id, "approved_fields": ["translated_body_zh"],
             "exact_output": {"translated_body_zh": "CONFLICT B"}},
        ]}
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp,
            "exact_output": {"translated_body_zh": "CONFLICT A"}}], candidate_sha=VALID_SHA)
        errors = validate_approved_decisions(manifest, candidate_manifest_sha256=VALID_SHA,
                                              candidate_manifest=candidate)
        self.assertTrue(any("重复" in e for e in errors),
                        f"expected duplicate error, got: {errors}")

    # ── P2: non-list candidate entries returns structured error, not UnboundLocalError ──
    def test_non_list_candidate_entries_rejected(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="old")
        fp = compute_before_fingerprint(a)
        # Candidate entries is an object, not a list
        candidate = {"entries": {"not": "a list"}}
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp,
            "exact_output": {"translated_body_zh": "output"}}], candidate_sha=VALID_SHA)
        errors = validate_approved_decisions(manifest, candidate_manifest_sha256=VALID_SHA,
                                              candidate_manifest=candidate)
        self.assertTrue(any("必须是列表" in e for e in errors),
                        f"expected type error, got: {errors}")

    # ── P1: candidate content binding — unrelated candidate.json rejected ──
    def test_unrelated_candidate_content_rejected(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="old")
        fp = compute_before_fingerprint(a)
        # Candidate manifest with DIFFERENT exact_output
        candidate = {"entries": [{"article_id": a.id, "approved_fields": ["translated_body_zh"],
                     "exact_output": {"translated_body_zh": "WRONG CANDIDATE OUTPUT"}}]}
        # Approved manifest references this candidate's SHA but decision has DIFFERENT exact_output
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp,
            "exact_output": {"translated_body_zh": "DIFFERENT FROM CANDIDATE"}}], candidate_sha=VALID_SHA)
        errors = validate_approved_decisions(manifest, candidate_manifest_sha256=VALID_SHA,
                                              candidate_manifest=candidate)
        self.assertTrue(any("exact_output 与 candidate 不一致" in e for e in errors),
                        f"expected candidate mismatch error, got: {errors}")

    def test_candidate_without_matching_entry_rejected(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="old")
        fp = compute_before_fingerprint(a)
        # Candidate manifest has entry for article 99999, not our article
        candidate = {"entries": [{"article_id": 99999, "approved_fields": ["translated_body_zh"],
                     "exact_output": {"translated_body_zh": "output"}}]}
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp,
            "exact_output": {"translated_body_zh": "output"}}], candidate_sha=VALID_SHA)
        errors = validate_approved_decisions(manifest, candidate_manifest_sha256=VALID_SHA,
                                              candidate_manifest=candidate)
        self.assertTrue(any("无对应条目" in e for e in errors),
                        f"expected missing candidate entry error, got: {errors}")

    # ── P1: manual field list drift in fingerprint ──
    def test_manual_field_list_drift_caught(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", body_zh="人工",
                           translated_body_zh="t", manually_edited_fields=["body_zh"])
        fp = compute_before_fingerprint(a)
        # Tamper: keep correct SHA but clear the list
        fp["manually_edited_fields_list"] = []
        # The SHA is computed from the real list, but list is empty
        # This should cause drift because the list changed
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x",
            "approved_fields": ["translated_body_zh", "body_zh"],
            "before_fingerprint": fp,
            "exact_output": {"translated_body_zh": "n", "body_zh": "n"}}], candidate_sha=VALID_SHA)
        d = Path(self.temp_dir.name) / "rb"
        ap = list(NewsArticle.objects.filter(id=a.id).order_by("id"))
        rb, rs = build_rollback_artifact(ap, output_dir=d)
        with transaction.atomic():
            lk = list(NewsArticle.objects.select_for_update().filter(id=a.id).order_by("id"))
            with self.assertRaises(ValueError):
                apply_batch_inside_transaction(articles=lk, approved_manifest=manifest,
                    approved_manifest_sha256=VALID_SHA, rollback_artifact_sha256=rs)

    # ── P1: source evidence self-proving — re-parse catches fakes ──
    def test_fake_source_evidence_caught_by_reparse(self):
        a = self._article("x", html="", body="old body", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        # Fake source_evidence claiming source_changed + parse_ok, but original_content_html is empty
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x",
            "approved_fields": ["body_ja_raw", "body_ja_normalized"],
            "source_evidence": {"source_status": SOURCE_CHANGED, "body_parse_status": "ok"},
            "before_fingerprint": fp,
            "exact_output": {"body_ja_raw": "new", "body_ja_normalized": "new"}}], candidate_sha=VALID_SHA)
        d = Path(self.temp_dir.name) / "rb"
        ap = list(NewsArticle.objects.filter(id=a.id).order_by("id"))
        rb, rs = build_rollback_artifact(ap, output_dir=d)
        with transaction.atomic():
            lk = list(NewsArticle.objects.select_for_update().filter(id=a.id).order_by("id"))
            with self.assertRaises(ValueError):
                apply_batch_inside_transaction(articles=lk, approved_manifest=manifest,
                    approved_manifest_sha256=VALID_SHA, rollback_artifact_sha256=rs)

    # ── P1: rollback commit without receipt-sha256 rejected ──
    def test_rollback_commit_without_receipt_sha_rejected(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        d = Path(self.temp_dir.name) / "rb"
        ap = list(NewsArticle.objects.filter(id=a.id).order_by("id"))
        rb_path, rb_sha = build_rollback_artifact(ap, output_dir=d)
        # Apply change to generate receipt
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp,
            "exact_output": {"translated_body_zh": "n"}}], candidate_sha=VALID_SHA)
        manifest_path = Path(self.temp_dir.name) / f"m-{a.id}.json"
        manifest_sha = _write_json(manifest_path, manifest)
        _apply_flow(a, manifest, d, manifest_sha=manifest_sha)

        receipt_path = d / "receipt.json"
        # Try rollback commit with receipt but without receipt-sha256
        with self.assertRaises(ValueError):
            rollback_batch(rollback_manifest_path=rb_path, rollback_manifest_sha256=rb_sha,
                            receipt_path=receipt_path, receipt_sha256=None, commit=True)

    # ── P1: verifier detects missing rollback artifact ──
    def test_verify_detects_missing_rollback_artifact(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "text"}}], candidate_sha=VALID_SHA)
        manifest_path = Path(self.temp_dir.name) / "vfy-m.json"
        manifest_sha = _write_json(manifest_path, manifest)
        d = Path(self.temp_dir.name) / "rb"
        _apply_flow(a, manifest, d, manifest_sha=manifest_sha)
        receipt_path = d / "receipt.json"
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

        # Delete the rollback artifact
        (d / "rollback_manifest.json").unlink()

        errors = verify_batch(receipt_path=receipt_path, receipt_sha256=receipt_file_sha,
                               manifest_path=manifest_path, manifest_sha256=manifest_sha,
                               rollback_dir=d, approved_manifest=manifest)
        self.assertTrue(any("rollback manifest 文件不存在" in e for e in errors))

    def test_verify_detects_rollback_sha_mismatch(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "text"}}], candidate_sha=VALID_SHA)
        manifest_path = Path(self.temp_dir.name) / "vfy-m.json"
        manifest_sha = _write_json(manifest_path, manifest)
        d = Path(self.temp_dir.name) / "rb"
        _apply_flow(a, manifest, d, manifest_sha=manifest_sha)
        receipt_path = d / "receipt.json"
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

        # Corrupt the rollback artifact
        (d / "rollback_manifest.json").write_text('{"corrupted": true}')

        errors = verify_batch(receipt_path=receipt_path, receipt_sha256=receipt_file_sha,
                               manifest_path=manifest_path, manifest_sha256=manifest_sha,
                               rollback_dir=d, approved_manifest=manifest)
        self.assertTrue(any("rollback_artifact_sha256 不匹配" in e for e in errors))


# ═══════════════════════════ Commands ═══════════════════════════
class NewsBodyHistoryCommandTests(TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _article(self, suffix, *, html, body, **kw):
        return NewsArticle.objects.create(
            source_site=SourceSite.HORSE_RACING_NATION, source_mode=SourceMode.LATEST,
            source_article_id=f"cm-{suffix}", racing_region=RacingRegion.UNITED_STATES,
            source_language=SourceLanguage.ENGLISH, title_ja=f"Cm {suffix}",
            body_ja_raw=body, body_ja_normalized=body, original_content_html=html,
            published_at=timezone.now(),
            source_url=f"https://horseracingnation.com/news/cm_{suffix}", **kw)

    def test_inventory_command(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b")
        d = Path(self.temp_dir.name) / "inv"
        out = StringIO()
        call_command("inventory_news_body_history", "--max-id", str(a.id + 100),
                     "--output-dir", str(d), stdout=out)
        self.assertEqual(json.loads(out.getvalue())["status"], "ok")
        self.assertTrue((d / "cohort.json").exists())

    def test_apply_command_dry_run(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        m = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_NO_ACTION,
            "reviewer": "r", "reason": "x", "approved_fields": [], "before_fingerprint": fp}],
            candidate_sha=VALID_SHA)
        mp = Path(self.temp_dir.name) / "m.json"; m_sha = _write_json(mp, m)
        cp = Path(self.temp_dir.name) / "c.json"
        c_raw = json.dumps({"candidate": "fake"}).encode("utf-8")
        cp.write_bytes(c_raw)
        c_sha = hashlib.sha256(c_raw).hexdigest()

        # Rewrite manifest with correct candidate sha matching file
        m["candidate_manifest_sha256"] = c_sha
        m_sha = _write_json(mp, m)

        out = StringIO()
        call_command("apply_news_body_history_batch", "--manifest", str(mp),
                     "--manifest-sha256", m_sha,
                     "--candidate-manifest", str(cp),
                     "--candidate-manifest-sha256", c_sha,
                     "--rollback-dir", str(Path(self.temp_dir.name) / "rb"), stdout=out)
        self.assertEqual(json.loads(out.getvalue())["mode"], "dry_run")

    def test_verify_command_ok(self):
        a = self._article("x", html=fixture_html("hrn_9623.html"), body="b", translated_body_zh="t")
        fp = compute_before_fingerprint(a)
        manifest = _make_approved_manifest([{"article_id": a.id, "decision": DECISION_APPROVE_FIELDS,
            "reviewer": "r", "reason": "x", "approved_fields": ["translated_body_zh"],
            "before_fingerprint": fp, "exact_output": {"translated_body_zh": "text"}}], candidate_sha=VALID_SHA)
        # Write manifest FIRST to get its file SHA
        manifest_path = Path(self.temp_dir.name) / "vfy-m.json"
        manifest_sha = _write_json(manifest_path, manifest)

        d = Path(self.temp_dir.name) / "rb"
        _apply_flow(a, manifest, d, manifest_sha=manifest_sha)
        a.refresh_from_db()

        receipt_path = d / "receipt.json"
        receipt_file_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

        out = StringIO()
        call_command("verify_news_body_history_batch",
                     "--receipt", str(receipt_path), "--receipt-sha256", receipt_file_sha,
                     "--manifest", str(manifest_path), "--manifest-sha256", manifest_sha,
                     "--rollback-dir", str(d), stdout=out)
        self.assertEqual(json.loads(out.getvalue())["status"], "ok")
