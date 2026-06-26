from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from stable.models import SourceLanguage, TermCandidate, TermCandidateStatus, TermEntry
from stable.services.operations import log_operation
from stable.services.term_admin import (
    find_term_by_source_alias,
    source_text_identity,
    split_aliases,
    sync_term_source_aliases,
    upsert_term_source_alias,
    validate_term_payload,
)
from stable.services.term_discovery import match_formal_terms, normalize_japanese_term


def _review(candidate: TermCandidate, user, status: str, notes: str = "") -> None:
    candidate.status = status
    candidate.reviewed_by = user
    candidate.reviewed_at = timezone.now()
    candidate.review_notes = notes


def _ensure_pending(candidate: TermCandidate) -> None:
    if candidate.status != TermCandidateStatus.PENDING:
        raise ValueError("只有待审核候选可以执行此操作。")


@transaction.atomic
def accept_candidate(candidate: TermCandidate, payload: dict, user) -> TermEntry:
    candidate = TermCandidate.objects.select_for_update().get(pk=candidate.pk)
    _ensure_pending(candidate)
    normalized, errors = validate_term_payload(payload)
    if errors:
        raise ValueError("；".join(message for messages in errors.values() for message in messages))
    same_type, _ = match_formal_terms(
        normalized["term_type"],
        normalized["source_ja"],
        normalized["source_language"],
    )
    if same_type:
        raise ValueError(f"正式术语或别名已存在，请改为合并：{same_type[0].source_ja}")
    normalized_key = normalize_japanese_term(normalized["source_ja"])
    if TermCandidate.objects.exclude(pk=candidate.pk).filter(
        term_type=normalized["term_type"],
        source_language=normalized["source_language"],
        normalized_key=normalized_key,
    ).exists():
        raise ValueError("修改后的术语已存在候选，请先合并候选。")
    term = TermEntry.objects.create(**normalized)
    sync_term_source_aliases(term, normalized["source_language"])
    candidate.term_type = normalized["term_type"]
    candidate.source_language = normalized["source_language"]
    candidate.source_ja = normalized["source_ja"]
    candidate.normalized_key = normalized_key
    candidate.target_zh = normalized["target_zh"]
    candidate.aliases_ja = normalized["aliases_ja"]
    candidate.aliases_zh = normalized["aliases_zh"]
    candidate.suggested_target_zh = normalized["target_zh"]
    candidate.accepted_term = term
    _review(candidate, user, TermCandidateStatus.ACCEPTED, payload.get("review_notes", ""))
    candidate.save()
    log_operation(action_type="term_candidate_accepted", target_type="term_candidate", target_id=candidate.pk, detail=f"接受术语候选 {term.source_ja} -> {term.target_zh}", admin=user)
    return term


@transaction.atomic
def merge_candidate(
    candidate: TermCandidate,
    user,
    *,
    target_candidate: TermCandidate | None = None,
    target_term: TermEntry | None = None,
    add_as_alias: bool = False,
    notes: str = "",
) -> None:
    candidate = TermCandidate.objects.select_for_update().get(pk=candidate.pk)
    _ensure_pending(candidate)
    if bool(target_candidate) == bool(target_term):
        raise ValueError("必须且只能选择一个合并目标。")
    if target_candidate:
        target_candidate = TermCandidate.objects.select_for_update().get(pk=target_candidate.pk)
        if target_candidate.pk == candidate.pk:
            raise ValueError("不能合并到自身。")
        _ensure_pending(target_candidate)
        if target_candidate.source_language != candidate.source_language:
            raise ValueError("不同原文语言的候选不能直接互相合并，请先接受或选择一个正式术语概念后按语言别名合并。")
        candidate.merged_into_candidate = target_candidate
        detail = f"合并术语候选 {candidate.source_ja} -> 候选 {target_candidate.source_ja}"
    else:
        target_term = TermEntry.objects.select_for_update().get(pk=target_term.pk)
        if add_as_alias:
            existing = find_term_by_source_alias(
                term_type=target_term.term_type,
                source_language=candidate.source_language or SourceLanguage.JAPANESE,
                source_text=candidate.source_ja,
                exclude_term_id=target_term.pk,
            )
            if existing:
                raise ValueError(f"该原文已属于正式术语 #{existing.pk}，不能合并为当前术语别名。")
            upsert_term_source_alias(
                target_term,
                source_language=candidate.source_language or SourceLanguage.JAPANESE,
                text=candidate.source_ja,
                is_active=target_term.is_active,
            )
            if (candidate.source_language or SourceLanguage.JAPANESE) == target_term.source_language:
                aliases = split_aliases(target_term.aliases_ja)
                existing_keys = {source_text_identity(value) for value in [target_term.source_ja, *aliases]}
                if source_text_identity(candidate.source_ja) not in existing_keys:
                    aliases.append(candidate.source_ja)
                    target_term.aliases_ja = aliases
                    target_term.save(update_fields=["aliases_ja", "updated_at"])
        candidate.merged_into_term = target_term
        detail = f"合并术语候选 {candidate.source_ja} -> 正式术语 {target_term.source_ja}"
    _review(candidate, user, TermCandidateStatus.MERGED, notes)
    candidate.save()
    log_operation(action_type="term_candidate_merged", target_type="term_candidate", target_id=candidate.pk, detail=detail, admin=user)


@transaction.atomic
def set_candidate_status(candidate: TermCandidate, user, status: str, notes: str = "") -> None:
    if status not in {TermCandidateStatus.REJECTED, TermCandidateStatus.IGNORED}:
        raise ValueError("不支持的审核状态。")
    candidate = TermCandidate.objects.select_for_update().get(pk=candidate.pk)
    _ensure_pending(candidate)
    _review(candidate, user, status, notes)
    candidate.save()
    log_operation(action_type=f"term_candidate_{status}", target_type="term_candidate", target_id=candidate.pk, detail=f"{candidate.get_status_display()}术语候选 {candidate.source_ja}", admin=user)
