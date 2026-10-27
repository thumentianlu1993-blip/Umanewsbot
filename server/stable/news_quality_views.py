"""新闻质量审核台，沿用现有后台 staff 权限。"""
import json
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from stable.models import NewsProcessingRun, NewsPublicationReceipt, HomepageHeadlineSelection, NewsEditorialEvent
from stable.services.news_review import review_action, withdraw_receipt, ReviewConflict


def _staff(request):
    return None if request.user.is_staff else HttpResponseForbidden("仅管理员可访问。")


def _context(request, **kwargs):
    from stable.views import _console_context
    return _console_context(request, **kwargs)


@login_required
@require_GET
@never_cache
def queue(request):
    if (denied := _staff(request)) is not None:
        return denied
    rows = NewsProcessingRun.objects.select_related("article").order_by("-created_at", "-id")
    if state := request.GET.get("state"):
        rows = rows.filter(state=state)
    if region := request.GET.get("region"):
        rows = rows.filter(primary_region=region)
    page = Paginator(rows, 30).get_page(request.GET.get("page"))
    return render(request, "stable/console/news_quality_queue.html", _context(request, page_obj=page))


@login_required
@require_GET
@never_cache
def detail(request, run_id):
    if (denied := _staff(request)) is not None:
        return denied
    run = get_object_or_404(NewsProcessingRun.objects.select_related("article", "event"), pk=run_id)
    receipts = list(run.article.news_receipts.order_by("published_at", "id"))
    evidence = {"editorial": run.editorial_snapshot, "entities": run.entity_snapshot, "quality": run.quality_snapshot}
    events = NewsEditorialEvent.objects.order_by("-updated_at")
    if query := request.GET.get("event_query", "").strip()[:200]:
        events = events.filter(identity_evidence__icontains=query)
    events = events.prefetch_related("receipts")[:20]
    selection = HomepageHeadlineSelection.objects.filter(slot="homepage_primary").first()
    return render(request, "stable/console/news_quality_detail.html", _context(request, run=run,
        receipts=receipts, event_candidates=events, attempts=run.attempts.order_by("id"), evidence=json.dumps(evidence, ensure_ascii=False, indent=2),
        public_receipt_ids=",".join(str(row.pk) for row in receipts if row.visibility == "public"),
        headline_version=selection.version if selection else 0,
        can_manage_headline=request.user.has_perm("stable.change_homepageheadlineselection")))


@login_required
@require_POST
@never_cache
def action(request, run_id):
    if (denied := _staff(request)) is not None:
        return denied
    get_object_or_404(NewsProcessingRun, pk=run_id)
    try:
        run = review_action(run_id, action=request.POST.get("action"), user=request.user,
            reason=request.POST.get("reason", ""), event_id=request.POST.get("event_id") or None,
            receipt_id=request.POST.get("receipt_id") or None,
            receipt_ids=[value.strip() for value in request.POST.get("receipt_ids", "").split(",") if value.strip()])
    except (ReviewConflict, ValidationError, ValueError) as error:
        return HttpResponse(str(error), status=409, content_type="text/plain")
    messages.success(request, "操作已记录。")
    return redirect("console-news-quality-detail", run_id=run.pk)


@login_required
@require_POST
@never_cache
def withdraw(request, receipt_id):
    if (denied := _staff(request)) is not None:
        return denied
    get_object_or_404(NewsPublicationReceipt, pk=receipt_id)
    try:
        receipt = withdraw_receipt(receipt_id, user=request.user, reason=request.POST.get("reason", ""))
    except ReviewConflict as error:
        return HttpResponse(str(error), status=409, content_type="text/plain")
    return redirect("console-news-quality-detail", run_id=receipt.run_id)


class RevisionForm(forms.Form):
    title_zh = forms.CharField(label="中文标题", max_length=500)
    summary_zh = forms.CharField(label="列表摘要", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    body_zh = forms.CharField(label="完整中文正文", widget=forms.Textarea(attrs={"rows": 24}))


@never_cache
def edit_revision(request, article):
    from stable.services.news_pipeline import submit_manual_target
    run = article.active_news_run
    target = run.manual_target or run.translation_snapshot or {"title": article.effective_title, "body": article.effective_body, "summary": article.effective_summary}
    form = RevisionForm(request.POST if request.method == "POST" else None,
        initial={key+"_zh": value for key, value in target.items() if key in {"title", "body", "summary"}})
    if request.method == "POST":
        if request.POST.get("intent", "save") not in {"save", "autosave", "submit_review", "publish"}:
            return HttpResponse("请从审核记录选择具体稿件操作。", status=400)
        if form.is_valid():
            new = submit_manual_target(article, form.cleaned_data, editor=request.user)
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"saved": True, "run_id": new.pk, "workflow_status": "pending_review"})
            messages.success(request, "修订已保存；审校及事实增量检查通过后独立发布。")
            return redirect("console-article-editor", article_id=article.pk)
    return render(request, "stable/console/news_quality_editor.html", _context(request, article=article, run=run, form=form))


@login_required
@require_GET
@never_cache
def report(request):
    from datetime import timedelta
    from django.utils import timezone
    from stable.services.news_quality_report import build_report
    if (denied := _staff(request)) is not None:
        return denied
    end = timezone.now()
    result = build_report(start=end-timedelta(days=7), end=end)
    return render(request, "stable/console/news_quality_report.html", _context(request,
        report=result, regions=result["regions"].items(), details=json.dumps(result, ensure_ascii=False, indent=2, default=str)))
