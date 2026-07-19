from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Iterable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from stable.models import (
    ArticleHorseLink,
    ArticleHorseLinkStatus,
    HorseCompletionFailureReason,
    HorseFollow,
    HorseProfile,
    HorseProfileCandidateStatus,
    HorseProfileCompleteness,
    HorseProfileDataCandidate,
    HorseProfileModule,
    HorseProfileStatus,
    HorseRaceRecord,
    HorseRaceResultStatus,
    NewsArticle,
    RaceGrade,
    SourceLanguage,
    TaskExecutionLog,
    TaskStatus,
    TermEntry,
    TermType,
    WorkflowStatus,
)
from stable.services.internal_controls import filter_news_for_current_site
from stable.services.operations import log_operation
from stable.services.horse_race_records import upsert_race_record
from stable.services.terms import ArticleEntityResolution, resolve_article_entities, source_term_matches_text


User = get_user_model()

FOLLOW_COOKIE_NAME = "horse_follower"
FOLLOW_COOKIE_SALT = "stable.horse_follow"
FOLLOW_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365

PEDIGREE_TEXT_FIELDS = (
    "sire_text",
    "dam_text",
    "sire_sire_text",
    "sire_dam_text",
    "dam_sire_text",
    "dam_dam_text",
)

BASIC_PROFILE_FIELDS = (
    "display_name_zh",
    "original_name",
    "english_name",
    "japanese_name",
    "racing_region",
    "country",
    "sex",
    "color",
    "birth_date",
    "owner_name",
    "trainer_name",
    "breeder_name",
    "intro",
    "source_refs",
)

GRADE_RANKING = {
    RaceGrade.G1: 10,
    RaceGrade.JPN1: 10,
    RaceGrade.JG1: 10,
    RaceGrade.G2: 20,
    RaceGrade.JPN2: 20,
    RaceGrade.JG2: 20,
    RaceGrade.G3: 30,
    RaceGrade.JPN3: 30,
    RaceGrade.JG3: 30,
    RaceGrade.LISTED: 40,
    RaceGrade.OPEN: 50,
    RaceGrade.THREE_WIN: 60,
    RaceGrade.TWO_WIN: 70,
    RaceGrade.ONE_WIN: 80,
    RaceGrade.NEWCOMER: 90,
    RaceGrade.MAIDEN: 90,
    RaceGrade.LOCAL_GRADE: 35,
    RaceGrade.OTHER: 100,
    "": 100,
}

AMBIGUOUS_ENGLISH_TERMS = {
    "ace",
    "agent",
    "air",
    "class",
    "content",
    "link",
    "major",
    "oaks",
    "race",
    "star",
    "the",
}


@dataclass
class ArticleHorseMatch:
    article: NewsArticle
    status: str
    confidence: int
    matched_text: str
    reason: str


def _task_log(task_name: str, status: str, payload: dict | None = None, detail: str = "") -> TaskExecutionLog:
    now = timezone.now()
    return TaskExecutionLog.objects.create(
        task_name=task_name,
        status=status,
        payload=payload or {},
        detail=detail,
        started_at=now,
        finished_at=now,
    )


def _clamp_confidence(value: Any, default: int = 0) -> int:
    try:
        return max(0, min(int(value), 100))
    except (TypeError, ValueError):
        return default


def signed_follow_token() -> str:
    token = secrets.token_urlsafe(32)
    return signing.dumps(token, salt=FOLLOW_COOKIE_SALT)


def token_hash_from_raw(raw_token: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}:{raw_token}".encode("utf-8")).hexdigest()


def token_hash_from_cookie(cookie_value: str) -> str:
    raw_token = signing.loads(cookie_value, salt=FOLLOW_COOKIE_SALT, max_age=FOLLOW_COOKIE_MAX_AGE_SECONDS)
    return token_hash_from_raw(raw_token)


def set_follow_cookie(response, signed_token: str) -> None:
    response.set_cookie(
        FOLLOW_COOKIE_NAME,
        signed_token,
        max_age=FOLLOW_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="Lax",
        secure=bool(getattr(settings, "SESSION_COOKIE_SECURE", False)),
    )


def _display_snapshot_from_term(term: TermEntry) -> dict[str, str]:
    aliases = list(term.source_aliases.filter(is_active=True).order_by("source_language", "alias_type", "text"))
    english_name = ""
    japanese_name = ""
    for alias in aliases:
        if alias.source_language == SourceLanguage.ENGLISH and not english_name:
            english_name = alias.text
        elif alias.source_language == SourceLanguage.JAPANESE and not japanese_name:
            japanese_name = alias.text
    if term.source_language == SourceLanguage.ENGLISH and not english_name:
        english_name = term.source_ja
    if term.source_language == SourceLanguage.JAPANESE and not japanese_name:
        japanese_name = term.source_ja
    return {
        "display_name_zh": term.target_zh,
        "original_name": term.source_ja,
        "english_name": english_name,
        "japanese_name": japanese_name,
        "racing_region": term.racing_region or "japan",
    }


def calculate_completeness(profile: HorseProfile) -> str:
    if all((getattr(profile, field) or "").strip() for field in PEDIGREE_TEXT_FIELDS):
        return HorseProfileCompleteness.COMPLETE_PEDIGREE_2GEN
    if any((getattr(profile, field) or "").strip() for field in PEDIGREE_TEXT_FIELDS):
        return HorseProfileCompleteness.PARTIAL_PEDIGREE
    if any(
        (
            profile.country,
            profile.sex,
            profile.color,
            profile.birth_date,
            profile.owner_name,
            profile.trainer_name,
            profile.breeder_name,
            profile.intro,
        )
    ):
        return HorseProfileCompleteness.PROFILE_ONLY
    return HorseProfileCompleteness.EMPTY


def update_completeness(profile: HorseProfile, *, save: bool = True) -> str:
    from stable.services.p0_horse_profiles import evaluate_full_profile_completeness

    should_check_full_profile = (
        profile.completeness_status == HorseProfileCompleteness.COMPLETE_PROFILE_FULL
        or profile.p0_sources.filter(status="active").exists()
    )
    full_evaluation = evaluate_full_profile_completeness(profile) if should_check_full_profile else None
    completeness = (
        HorseProfileCompleteness.COMPLETE_PROFILE_FULL
        if full_evaluation and full_evaluation.is_complete
        else calculate_completeness(profile)
    )
    profile.completeness_status = completeness
    if save:
        profile.save(update_fields=["completeness_status", "updated_at"])
    return completeness


def generate_p0_horse_profiles(*, limit: int | None = None) -> dict[str, Any]:
    queryset = (
        TermEntry.objects.filter(term_type=TermType.HORSE, is_active=True)
        .exclude(target_zh="")
        .prefetch_related("source_aliases")
        .order_by("-priority", "id")
    )
    if limit:
        queryset = queryset[:limit]
    created = 0
    existing = 0
    profile_ids: list[int] = []
    for term in queryset:
        defaults = _display_snapshot_from_term(term)
        profile, was_created = HorseProfile.objects.get_or_create(primary_term=term, defaults=defaults)
        if was_created:
            created += 1
            profile_ids.append(profile.pk)
        else:
            existing += 1
    _task_log(
        "horse_profile_p0_generation",
        TaskStatus.SUCCESS,
        payload={"created": created, "existing": existing, "profile_ids": profile_ids[:100]},
        detail=f"P0 马匹资料生成完成：created={created} existing={existing}",
    )
    return {"created": created, "existing": existing, "profile_ids": profile_ids}


def transition_review_status(
    profile: HorseProfile,
    status: str,
    *,
    user: User | None = None,
    note: str = "",
) -> HorseProfile:
    now = timezone.now()
    profile.review_status = status
    profile.review_notes = note or profile.review_notes
    update_fields = ["review_status", "review_notes", "updated_at"]
    if status == HorseProfileStatus.PUBLISHED:
        profile.published_at = now
        profile.published_by = user
        update_fields.extend(["published_at", "published_by"])
    if status == HorseProfileStatus.HIDDEN:
        profile.hidden_at = now
        profile.hidden_by = user
        update_fields.extend(["hidden_at", "hidden_by"])
    profile.save(update_fields=update_fields)
    log_operation(
        action_type="horse_profile_status_changed",
        target_type="horse_profile",
        target_id=profile.pk,
        detail=f"马匹资料状态改为 {status}；备注：{note}",
        admin=user,
    )
    return profile


def get_descendant_horse_ids(profile: HorseProfile, *, depth: int = 2, public_only: bool = False) -> set[int]:
    seen: set[int] = set()
    frontier = {profile.pk}
    for _level in range(max(0, depth)):
        if not frontier:
            break
        queryset = HorseProfile.objects.filter(Q(sire_horse_profile_id__in=frontier) | Q(dam_horse_profile_id__in=frontier))
        if public_only:
            queryset = queryset.filter(review_status=HorseProfileStatus.PUBLISHED)
        next_ids = set(queryset.values_list("id", flat=True))
        next_ids -= seen
        seen.update(next_ids)
        frontier = next_ids
    return seen


def get_descendant_horses(profile: HorseProfile, *, depth: int = 2, public_only: bool = False) -> QuerySet[HorseProfile]:
    ids = get_descendant_horse_ids(profile, depth=depth, public_only=public_only)
    return HorseProfile.objects.filter(pk__in=ids).order_by("racing_region", "display_name_zh", "id")


def race_grade_rank(record: HorseRaceRecord) -> int:
    return GRADE_RANKING.get(record.normalized_grade or "", 100)


def major_win_records(profile: HorseProfile) -> QuerySet[HorseRaceRecord]:
    manual_ids = list(profile.race_records.filter(is_major_win=True).values_list("id", flat=True))
    wins = list(profile.race_records.filter(result_status=HorseRaceResultStatus.WON))
    if not wins:
        return profile.race_records.filter(id__in=manual_ids).order_by("major_win_order", "-race_date", "id")
    best_rank = min(race_grade_rank(record) for record in wins)
    calculated_ids = [record.pk for record in wins if race_grade_rank(record) == best_rank]
    return profile.race_records.filter(id__in=sorted(set(manual_ids + calculated_ids))).order_by("major_win_order", "-race_date", "id")


def _profile_match_terms(profile: HorseProfile) -> list[tuple[str, str]]:
    values = [
        (profile.display_name_zh, ""),
        (profile.original_name, profile.primary_term.source_language),
        (profile.english_name, SourceLanguage.ENGLISH),
        (profile.japanese_name, SourceLanguage.JAPANESE),
    ]
    for term in profile.primary_term.all_japanese_terms():
        values.append((term, profile.primary_term.source_language))
    for alias in profile.primary_term.source_aliases.all():
        if alias.is_active:
            values.append((alias.text, alias.source_language))
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for text, language in values:
        normalized = (text or "").strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append((normalized, language or ""))
    return sorted(result, key=lambda item: len(item[0]), reverse=True)


def _is_ambiguous_english(term: str) -> bool:
    normalized = (term or "").strip().casefold()
    return len(normalized) <= 3 or normalized in AMBIGUOUS_ENGLISH_TERMS


def _article_text(article: NewsArticle, *fields: str) -> str:
    return "\n".join(str(getattr(article, field, "") or "") for field in fields)


def _match_article(article: NewsArticle, profile: HorseProfile, terms: list[tuple[str, str]]) -> ArticleHorseMatch | None:
    title_summary = _article_text(article, "title_ja", "title_zh", "translated_title_zh", "summary_zh", "translated_summary_zh")
    body = _article_text(article, "body_ja_normalized", "body_ja_raw", "body_zh", "translated_body_zh")
    for term, language in terms:
        if source_term_matches_text(title_summary, term, language):
            if language == SourceLanguage.ENGLISH and _is_ambiguous_english(term):
                return ArticleHorseMatch(article, ArticleHorseLinkStatus.CANDIDATE, 60, term, "标题命中短英文或歧义英文马名")
            return ArticleHorseMatch(article, ArticleHorseLinkStatus.AUTO, 95, term, "标题或摘要命中马匹正式名/别名")
    for term, language in terms:
        if source_term_matches_text(body, term, language):
            return ArticleHorseMatch(article, ArticleHorseLinkStatus.CANDIDATE, 65, term, "正文命中马匹正式名/别名")
    return None


def reconcile_article_horse_links(
    article: NewsArticle,
    resolution: ArticleEntityResolution,
    *,
    commit: bool = True,
) -> dict[str, list]:
    horse_entities = [item for item in resolution.entities if item.entity_type in {"horse", "unknown_horse"}]
    term_ids = {item.term_id for item in horse_entities if item.term_id}
    candidate_names = {
        value.strip()
        for item in horse_entities
        for value in (item.canonical_text, item.matched_text, item.target_zh)
        if value and value.strip()
    }
    profile_filter = Q(primary_term_id__in=term_ids)
    for name in sorted(candidate_names):
        profile_filter |= (
            Q(original_name__iexact=name)
            | Q(english_name__iexact=name)
            | Q(japanese_name__iexact=name)
            | Q(display_name_zh__iexact=name)
        )
    profiles = list(
        HorseProfile.objects.filter(profile_filter, review_status=HorseProfileStatus.PUBLISHED)
        .select_related("primary_term")
        .order_by("id")
    ) if term_ids or candidate_names else []
    desired: dict[int, dict] = {}
    for profile in profiles:
        matches = [
            item
            for item in horse_entities
            if item.term_id == profile.primary_term_id
            or any(
                value and value.casefold() in {
                    profile.original_name.casefold(),
                    profile.english_name.casefold(),
                    profile.japanese_name.casefold(),
                    profile.display_name_zh.casefold(),
                }
                for value in (item.canonical_text, item.matched_text, item.target_zh)
            )
        ]
        if not matches:
            continue
        match = sorted(matches, key=lambda item: (item.field_name != "title", item.start, -item.confidence))[0]
        status = ArticleHorseLinkStatus.AUTO if match.field_name == "title" else ArticleHorseLinkStatus.CANDIDATE
        desired[profile.id] = {
            "status": status,
            "source": "contextual_entity_resolution",
            "confidence": match.confidence,
            "matched_text": match.matched_text[:255],
            "match_reason": ",".join(match.evidence),
            "metadata": {"entity": match.as_dict()},
        }

    existing = list(ArticleHorseLink.objects.filter(article=article).order_by("id"))
    existing_by_profile = {item.horse_profile_id: item for item in existing}
    protected = [item for item in existing if item.status in {ArticleHorseLinkStatus.MANUAL, ArticleHorseLinkStatus.REMOVED}]
    delete_links = [
        item
        for item in existing
        if item.status in {ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.CANDIDATE}
        and item.horse_profile_id not in desired
    ]
    create_payloads = [
        {"horse_profile_id": profile_id, **payload}
        for profile_id, payload in desired.items()
        if profile_id not in existing_by_profile
    ]
    update_payloads = [
        {"link_id": existing_by_profile[profile_id].id, "horse_profile_id": profile_id, **payload}
        for profile_id, payload in desired.items()
        if profile_id in existing_by_profile
        and existing_by_profile[profile_id].status not in {ArticleHorseLinkStatus.MANUAL, ArticleHorseLinkStatus.REMOVED}
    ]
    result = {
        "create": create_payloads,
        "update": update_payloads,
        "delete_ids": [item.id for item in delete_links],
        "protected_ids": [item.id for item in protected],
        "protected": [{"link_id": item.id, "status": item.status} for item in protected],
    }
    if not commit:
        return result
    if delete_links:
        ArticleHorseLink.objects.filter(id__in=result["delete_ids"]).delete()
    for payload in create_payloads:
        profile_id = payload["horse_profile_id"]
        defaults = {key: value for key, value in payload.items() if key != "horse_profile_id"}
        ArticleHorseLink.objects.create(article=article, horse_profile_id=profile_id, **defaults)
    for payload in update_payloads:
        link_id = payload["link_id"]
        defaults = {key: value for key, value in payload.items() if key not in {"link_id", "horse_profile_id"}}
        defaults["updated_at"] = timezone.now()
        ArticleHorseLink.objects.filter(pk=link_id).update(**defaults)
    return result


def scan_article_horse_links(
    *,
    article: NewsArticle | None = None,
    profile: HorseProfile | None = None,
    limit: int = 500,
    commit: bool = True,
) -> dict[str, int]:
    if article is not None and profile is None:
        resolution = resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized or article.body_ja_raw,
            source_language=article.source_language or SourceLanguage.JAPANESE,
        )
        reconciled = reconcile_article_horse_links(article, resolution, commit=commit)
        result = {
            "created": len(reconciled["create"]),
            "updated": len(reconciled["update"]),
            "deleted": len(reconciled["delete_ids"]),
            "candidate": sum(item["status"] == ArticleHorseLinkStatus.CANDIDATE for item in [*reconciled["create"], *reconciled["update"]]),
            "skipped_removed": sum(item["status"] == ArticleHorseLinkStatus.REMOVED for item in reconciled["protected"]),
            "skipped_manual": sum(item["status"] == ArticleHorseLinkStatus.MANUAL for item in reconciled["protected"]),
        }
        _task_log("horse_article_link_scan", TaskStatus.SUCCESS, payload=result, detail=f"马匹新闻关联扫描完成：{result}")
        return result
    profiles = HorseProfile.objects.filter(review_status=HorseProfileStatus.PUBLISHED).select_related("primary_term").prefetch_related("primary_term__source_aliases")
    if profile is not None:
        profiles = profiles.filter(pk=profile.pk)
    articles = NewsArticle.objects.filter(workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at__isnull=False)
    if article is not None:
        articles = articles.filter(pk=article.pk)
    articles = articles.order_by("-published_to_web_at", "-id")[:limit]
    created = updated = candidate = skipped_removed = skipped_manual = 0
    for profile_item in profiles:
        terms = _profile_match_terms(profile_item)
        if not terms:
            continue
        for article_item in articles:
            match = _match_article(article_item, profile_item, terms)
            if match is None:
                continue
            if match.status == ArticleHorseLinkStatus.CANDIDATE:
                candidate += 1
            existing = ArticleHorseLink.objects.filter(horse_profile=profile_item, article=article_item).first()
            if existing and existing.status == ArticleHorseLinkStatus.REMOVED:
                skipped_removed += 1
                continue
            if existing and existing.status == ArticleHorseLinkStatus.MANUAL:
                skipped_manual += 1
                continue
            if not commit:
                continue
            _, was_created = ArticleHorseLink.objects.update_or_create(
                horse_profile=profile_item,
                article=article_item,
                defaults={
                    "status": match.status,
                    "source": "auto_match",
                    "confidence": match.confidence,
                    "matched_text": match.matched_text[:255],
                    "match_reason": match.reason,
                    "metadata": {},
                },
            )
            created += int(was_created)
            updated += int(not was_created)
    result = {
        "created": created,
        "updated": updated,
        "candidate": candidate,
        "skipped_removed": skipped_removed,
        "skipped_manual": skipped_manual,
    }
    _task_log("horse_article_link_scan", TaskStatus.SUCCESS, payload=result, detail=f"马匹新闻关联扫描完成：{result}")
    return result


def build_candidate_diff(profile: HorseProfile, module: str, payload: dict) -> dict:
    if module == HorseProfileModule.PROFILE:
        return {
            field: {
                "changed": getattr(profile, field, None) != payload.get(field),
                "current": getattr(profile, field, None),
                "candidate": payload.get(field),
                "locked": bool((profile.manual_lock_flags or {}).get(field)),
            }
            for field in BASIC_PROFILE_FIELDS
            if field in payload
        }
    if module == HorseProfileModule.PEDIGREE:
        return {
            field: {
                "changed": getattr(profile, field, None) != payload.get(field),
                "current": getattr(profile, field, None),
                "candidate": payload.get(field),
                "locked": bool((profile.manual_lock_flags or {}).get(field)),
            }
            for field in PEDIGREE_TEXT_FIELDS
            if field in payload
        }
    return {"payload": {"changed": True, "current": {}, "candidate": payload}}


def save_data_candidate(
    *,
    profile: HorseProfile,
    module: str,
    source_name: str,
    candidate_payload: dict,
    source_url: str = "",
    raw_payload: dict | None = None,
    confidence: int = 0,
) -> HorseProfileDataCandidate:
    return HorseProfileDataCandidate.objects.create(
        profile=profile,
        module=module,
        source_name=source_name,
        source_url=source_url,
        confidence=_clamp_confidence(confidence),
        candidate_payload=candidate_payload,
        diff_payload=build_candidate_diff(profile, module, candidate_payload),
        raw_payload=raw_payload or {},
    )


def apply_data_candidate(candidate: HorseProfileDataCandidate, *, user: User | None = None) -> dict[str, Any]:
    if candidate.status != HorseProfileCandidateStatus.PENDING:
        raise ValueError("only pending horse profile candidates can be applied")
    profile = candidate.profile
    payload = candidate.candidate_payload or {}
    manual_lock_flags = profile.manual_lock_flags or {}
    updated_fields: list[str] = []
    skipped_locked: list[str] = []
    with transaction.atomic():
        if candidate.module in {HorseProfileModule.PROFILE, HorseProfileModule.PEDIGREE}:
            allowed_fields = BASIC_PROFILE_FIELDS if candidate.module == HorseProfileModule.PROFILE else PEDIGREE_TEXT_FIELDS
            for field in allowed_fields:
                if field not in payload:
                    continue
                if manual_lock_flags.get(field) or manual_lock_flags.get(candidate.module):
                    skipped_locked.append(field)
                    continue
                value = payload[field]
                if getattr(profile, field, None) != value:
                    setattr(profile, field, value)
                    updated_fields.append(field)
            if updated_fields:
                update_completeness(profile, save=False)
                profile.save(update_fields=[*updated_fields, "completeness_status", "updated_at"])
        elif candidate.module == HorseProfileModule.RACE_RECORD:
            items = payload.get("items") if isinstance(payload, dict) else []
            action_counts: dict[str, int] = {}
            for item in items or []:
                if not item.get("race_name"):
                    continue
                record_payload = {
                    **item,
                    "source_name": item.get("source_name") or candidate.source_name,
                    "source_url": item.get("source_url") or candidate.source_url,
                }
                upsert = upsert_race_record(profile, record_payload)
                action_counts[upsert.action] = action_counts.get(upsert.action, 0) + 1
            updated_fields.append(f"race_records:{action_counts}")
        else:
            updated_fields.append("aliases:review_required")
        candidate.status = HorseProfileCandidateStatus.APPLIED
        candidate.applied_by = user
        candidate.applied_at = timezone.now()
        candidate.result_summary = f"updated={updated_fields} skipped_locked={skipped_locked}"
        candidate.save(update_fields=["status", "applied_by", "applied_at", "result_summary", "updated_at"])
    log_operation(
        action_type="horse_candidate_applied",
        target_type="horse_profile",
        target_id=profile.pk,
        detail=f"应用马匹候选资料 candidate={candidate.pk} module={candidate.module} updated={updated_fields} skipped_locked={skipped_locked}",
        admin=user,
    )
    return {"updated_fields": updated_fields, "skipped_locked": skipped_locked}


def follow_horse(token_hash: str, profile: HorseProfile, *, include_descendants: bool = True) -> HorseFollow:
    follow, _ = HorseFollow.objects.update_or_create(
        token_hash=token_hash,
        horse_profile=profile,
        defaults={"include_descendants": include_descendants, "descendant_depth": 2},
    )
    return follow


def unfollow_horse(token_hash: str, profile: HorseProfile) -> int:
    deleted, _ = HorseFollow.objects.filter(token_hash=token_hash, horse_profile=profile).delete()
    return deleted


def followed_horse_ids(token_hash: str, *, include_descendants: bool = True) -> set[int]:
    follows = list(
        HorseFollow.objects.filter(token_hash=token_hash, horse_profile__review_status=HorseProfileStatus.PUBLISHED).select_related("horse_profile")
    )
    ids = {follow.horse_profile_id for follow in follows}
    if include_descendants:
        for follow in follows:
            if follow.include_descendants:
                ids.update(get_descendant_horse_ids(follow.horse_profile, depth=follow.descendant_depth, public_only=True))
    return ids


def followed_articles(token_hash: str, *, limit: int = 20) -> list[dict[str, Any]]:
    horse_ids = followed_horse_ids(token_hash, include_descendants=True)
    if not horse_ids:
        return []
    article_queryset = filter_news_for_current_site(NewsArticle.objects.all())
    links = (
        ArticleHorseLink.objects.filter(
            horse_profile_id__in=horse_ids,
            horse_profile__review_status=HorseProfileStatus.PUBLISHED,
            status__in=[ArticleHorseLinkStatus.AUTO, ArticleHorseLinkStatus.MANUAL],
            article__workflow_status=WorkflowStatus.PUBLISHED,
            article__published_to_web_at__isnull=False,
            article__in=article_queryset,
        )
        .select_related("article", "horse_profile")
        .order_by("-article__published_to_web_at", "-article_id")[:limit]
    )
    seen_articles: set[int] = set()
    entries: list[dict[str, Any]] = []
    for link in links:
        if link.article_id in seen_articles:
            continue
        seen_articles.add(link.article_id)
        entries.append({"article": link.article, "horse_profile": link.horse_profile, "link": link})
    return entries


def classify_completion_payload(payload: dict) -> str:
    pedigree = payload.get("pedigree") if isinstance(payload.get("pedigree"), dict) else payload
    if all((pedigree.get(field) or "").strip() for field in PEDIGREE_TEXT_FIELDS):
        return HorseProfileCompleteness.COMPLETE_PEDIGREE_2GEN
    if any((pedigree.get(field) or "").strip() for field in PEDIGREE_TEXT_FIELDS):
        return HorseProfileCompleteness.PARTIAL_PEDIGREE
    return HorseCompletionFailureReason.PROFILE_ONLY
