from __future__ import annotations

import json
import inspect
import math
import re
from dataclasses import dataclass

from django.conf import settings
from openai import OpenAI

from stable.models import NewsArticle, SourceLanguage, TermType, TranslationRun

from .japanese_racing_translation import (
    build_japanese_format_plan,
    build_japanese_seed_term_plan,
    japanese_format_placeholder_violations,
    japanese_seed_term_placeholder_violations,
    restore_japanese_format_placeholders,
    restore_japanese_seed_term_placeholders,
)
from .terms import (
    ArticleEntityResolution,
    apply_contextual_term_mappings,
    recognized_horses_from_resolution,
    resolve_article_entities,
    serialize_recognized_horse_names,
    serialize_terms,
)


@dataclass
class TranslationResult:
    title_zh: str
    body_zh: str
    push_summary_zh: str
    metadata: dict


class TranslationResponseError(ValueError):
    def __init__(self, message: str, *, metadata: dict | None = None) -> None:
        super().__init__(message)
        self.metadata = metadata or {}


class TranslationProvider:
    name = "base"

    def translate(
        self,
        article: NewsArticle,
        *,
        entity_resolution: ArticleEntityResolution | None = None,
    ) -> TranslationResult:
        raise NotImplementedError


def _translation_terms(resolution: ArticleEntityResolution) -> list:
    limit = max(0, int(settings.TRANSLATION_TERM_LIMIT))
    selected = list(resolution.accepted_terms[:limit])
    for term in resolution.accepted_terms:
        if "japanese_racing_translation_seed" not in (term.notes or "").casefold():
            continue
        if term not in selected:
            selected.append(term)
    return selected


class DummyTranslationProvider(TranslationProvider):
    name = "dummy"

    def translate(
        self,
        article: NewsArticle,
        *,
        entity_resolution: ArticleEntityResolution | None = None,
    ) -> TranslationResult:
        body = article.body_ja_normalized or article.body_ja_raw
        source_language = article.source_language or SourceLanguage.JAPANESE
        resolution = entity_resolution or resolve_article_entities(
            article.title_ja,
            body,
            source_language=source_language,
        )
        format_plan = build_japanese_format_plan(article.title_ja, body, resolution)
        seed_term_plan = build_japanese_seed_term_plan(article.title_ja, body, resolution, format_plan)
        mapped_title = apply_contextual_term_mappings(seed_term_plan.protected_title, resolution)
        mapped_body = apply_contextual_term_mappings(seed_term_plan.protected_body, resolution)
        mapped_title = restore_japanese_seed_term_placeholders(mapped_title, seed_term_plan, field_name="title")
        mapped_body = restore_japanese_seed_term_placeholders(mapped_body, seed_term_plan, field_name="body")
        mapped_title = restore_japanese_format_placeholders(mapped_title, format_plan, field_name="title")
        mapped_body = restore_japanese_format_placeholders(mapped_body, format_plan, field_name="body")
        return TranslationResult(
            title_zh=f"[未配置真实翻译模型] {mapped_title}",
            body_zh=mapped_body,
            push_summary_zh=mapped_body[:140],
            metadata={
                "provider": self.name,
                "model": "dummy",
                "terms": serialize_terms(resolution.accepted_terms),
                "entities": [item.as_dict() for item in resolution.entities],
                "suppressed_entities": [item.as_dict() for item in resolution.suppressed_candidates],
                "machine_horse_tags": resolution.machine_horse_tags,
                "japanese_format_normalizations": format_plan.as_dicts(),
                "japanese_seed_term_normalizations": seed_term_plan.as_dicts(),
            },
        )


class OpenAICompatibleTranslationProvider(TranslationProvider):
    name = "openai-compatible"
    _SENTENCE_END_RE = re.compile(r"[。！？!?；;…]$")
    _LIST_MARKER_RE = re.compile(r"(?m)^\s*[■◆●▪•]")

    def __init__(self, *, api_key: str, base_url: str, provider_name: str | None = None) -> None:
        self.name = provider_name or self.name
        kwargs = {
            "api_key": api_key,
            "base_url": base_url.strip(),
        }
        self.client = OpenAI(**kwargs)

    def _build_prompt(
        self,
        article: NewsArticle,
        glossary_lines: list[str],
        unknown_horse_lines: list[str],
        *,
        retry_hint: str = "",
        source_title: str | None = None,
        source_body: str | None = None,
    ) -> str:
        return (
            "你是一名熟悉赛马行业的专业翻译编辑。"
            "请把下面的赛马新闻逐段完整翻译成自然、准确、专业的简体中文。"
            "请优先遵守术语表中的译法，不要杜撰信息，不要省略关键事实，不要把原文改写成摘要。"
            "如果原文包含排行榜、分点、小标题或项目符号，译文必须保留相同的顺序和完整信息。"
            "如果识别到马名但术语表没有提供中文译名，必须保留该马名的原始写法，不得音译、意译或自行猜译。"
            "未被术语表或占位符保护的普通片假名是正文词汇，必须按上下文译成中文，不得保留原文。"
            "若原文中出现 __UMA_KEEP_数字__ 形式的占位符，请在译文中原样复制该占位符，不要翻译或删除。"
            "若原文中出现 __UMA_TERM_数字__ 形式的人名占位符，也必须在译文中原样复制，系统会按术语表还原。"
            "若原文中出现 __UMA_FORMAT_数字__ 形式的固定格式占位符，也必须在对应标题或正文中原样复制，系统会还原为规范格式。"
            "若原文中出现 __UMA_SEED_数字__ 形式的种子术语占位符，也必须在对应标题或正文中原样复制，系统会还原为指定译法。"
            "输出必须是 JSON 对象，且只包含 title_zh、body_zh、push_summary_zh 三个键。"
            f"{retry_hint}"
            "\n\n"
            f"术语表：\n{chr(10).join(glossary_lines) if glossary_lines else '无可用术语'}\n\n"
            f"未收录中文译名、必须保留原始写法的疑似马名/占位符：\n{chr(10).join(unknown_horse_lines) if unknown_horse_lines else '无'}\n\n"
            f"原文标题：{source_title if source_title is not None else article.title_ja}\n\n"
            f"原文正文：\n{source_body if source_body is not None else article.body_ja_normalized or article.body_ja_raw}"
        )

    def _build_messages(
        self,
        article: NewsArticle,
        glossary_lines: list[str],
        unknown_horse_lines: list[str],
        *,
        retry_hint: str = "",
        source_title: str | None = None,
        source_body: str | None = None,
    ) -> list[dict]:
        prompt = self._build_prompt(
            article,
            glossary_lines,
            unknown_horse_lines,
            retry_hint=retry_hint,
            source_title=source_title,
            source_body=source_body,
        )
        return [
            {
                "role": "system",
                "content": (
                    "你负责把赛马新闻翻译成简体中文。"
                    "译文要忠于原文，保留赛事、马名、骑手、机构、时间与公告口径。"
                    "凡是术语表未提供中文译名的马名，一律保留原始写法。"
                    "不得省略段落，不得省略榜单条目，不得输出半截句子。"
                ),
            },
            {"role": "user", "content": prompt},
        ]

    def _request_completion(self, messages: list[dict]):
        return self.client.chat.completions.create(
            model=settings.TRANSLATION_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=messages,
            max_tokens=settings.TRANSLATION_MAX_TOKENS,
            timeout=settings.TRANSLATION_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _count_sentences(text: str) -> int:
        return sum(text.count(char) for char in "。！？!?；;")

    @staticmethod
    def _count_nonempty_lines(text: str) -> int:
        return sum(1 for line in (text or "").splitlines() if line.strip())

    def _ends_with_complete_sentence(self, text: str) -> bool:
        stripped = (text or "").rstrip()
        if not stripped:
            return False
        last_char = stripped[-1]
        if self._SENTENCE_END_RE.search(last_char):
            return True
        if last_char in "」』）》】”\"'）】":
            inner = stripped[:-1].rstrip()
            return bool(inner and self._SENTENCE_END_RE.search(inner[-1]))
        return False

    def _looks_incomplete(self, source_text: str, body_zh: str) -> bool:
        source = (source_text or "").strip()
        target = (body_zh or "").strip()
        if not target:
            return True
        source_sentence_count = self._count_sentences(source)
        target_sentence_count = self._count_sentences(target)
        source_list_count = len(self._LIST_MARKER_RE.findall(source))
        target_list_count = len(self._LIST_MARKER_RE.findall(target))
        source_line_count = self._count_nonempty_lines(source)
        target_line_count = self._count_nonempty_lines(target)
        has_line_coverage = source_line_count >= 5 and target_line_count >= max(
            4,
            math.ceil(source_line_count * 0.8),
        )

        if self._ends_with_complete_sentence(source) and not self._ends_with_complete_sentence(target):
            return True
        if source_list_count >= 2 and target_list_count < source_list_count:
            return True
        if len(source) >= 600 and len(target) < max(320, int(len(source) * 0.58)) and not has_line_coverage:
            if target_sentence_count < max(4, int(source_sentence_count * 0.7)):
                return True
        return False

    @staticmethod
    def _missing_unknown_horse_names(title_zh: str, body_zh: str, unknown_horse_names: list[str]) -> list[str]:
        if not unknown_horse_names:
            return []
        translated_text = "\n".join([title_zh or "", body_zh or ""])
        return [name for name in unknown_horse_names if name not in translated_text]

    @staticmethod
    def _protect_unknown_horse_names(text: str, unknown_horse_names: list[str]) -> tuple[str, dict[str, str]]:
        placeholders = {
            f"__UMA_KEEP_{index}__": name
            for index, name in enumerate(sorted(set(unknown_horse_names), key=lambda item: (-len(item), item)), start=1)
        }
        return OpenAICompatibleTranslationProvider._protect_with_placeholders(text, placeholders), placeholders

    @staticmethod
    def _protect_with_placeholders(text: str, placeholders: dict[str, str]) -> str:
        protected = text or ""
        for placeholder, name in placeholders.items():
            protected = protected.replace(name, placeholder)
        return protected

    @staticmethod
    def _restore_unknown_horse_placeholders(text: str, placeholders: dict[str, str]) -> str:
        restored = text or ""
        for placeholder, name in placeholders.items():
            restored = restored.replace(placeholder, name)
        return restored

    @staticmethod
    def _person_term_placeholders(terms: list) -> tuple[dict[str, str], dict[str, str]]:
        mappings: dict[str, str] = {}
        conflicts: set[str] = set()
        for term in terms:
            if term.term_type not in {TermType.JOCKEY, TermType.TRAINER, TermType.OWNER}:
                continue
            source = (term.matched_text or term.source_ja or "").strip()
            target = (term.target_zh or "").strip()
            if not source or not target:
                continue
            if source in mappings and mappings[source] != target:
                conflicts.add(source)
                continue
            mappings[source] = target
        for source in conflicts:
            mappings.pop(source, None)
        source_placeholders: dict[str, str] = {}
        target_placeholders: dict[str, str] = {}
        for index, (source, target) in enumerate(
            sorted(mappings.items(), key=lambda item: (-len(item[0]), item[0], item[1])),
            start=1,
        ):
            placeholder = f"__UMA_TERM_{index}__"
            source_placeholders[placeholder] = source
            target_placeholders[placeholder] = target
        return source_placeholders, target_placeholders

    @staticmethod
    def _usage_to_dict(usage) -> dict:
        if usage is None:
            return {}
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if isinstance(usage, dict):
            return usage
        return {"repr": repr(usage)}

    def translate(
        self,
        article: NewsArticle,
        *,
        entity_resolution: ArticleEntityResolution | None = None,
    ) -> TranslationResult:
        source_text = article.body_ja_normalized or article.body_ja_raw
        source_language = article.source_language or SourceLanguage.JAPANESE
        resolution = entity_resolution or resolve_article_entities(
            article.title_ja,
            source_text,
            source_language=source_language,
        )
        format_plan = build_japanese_format_plan(article.title_ja, source_text, resolution)
        seed_term_plan = build_japanese_seed_term_plan(article.title_ja, source_text, resolution, format_plan)
        terms = _translation_terms(resolution)
        person_source_placeholders, person_target_placeholders = self._person_term_placeholders(terms)
        person_placeholder_by_source = {
            source: placeholder for placeholder, source in person_source_placeholders.items()
        }
        glossary_lines = [
            f"- [{term.term_type}] "
            f"{person_placeholder_by_source.get((term.matched_text or term.source_ja or '').strip(), term.matched_text or term.source_ja)}"
            f" => {term.target_zh}"
            + (f"（备注：{term.notes}）" if term.notes else "")
            for term in terms
            if (term.target_zh or "").strip()
        ]
        unknown_horse_limit = max(1, int(settings.TRANSLATION_UNKNOWN_HORSE_LIMIT))
        recognized_horses = recognized_horses_from_resolution(resolution)
        consumed_entity_keys = format_plan.consumed_entity_keys | seed_term_plan.consumed_entity_keys
        unknown_horse_names = list(
            dict.fromkeys(
                item.matched_text
                for item in resolution.entities
                if item.entity_type in {"horse", "unknown_horse"}
                and item.needs_preserve
                and item.matched_text
                and (item.field_name, item.start, item.end) not in consumed_entity_keys
            )
        )[:unknown_horse_limit]
        _, horse_placeholders = self._protect_unknown_horse_names("", unknown_horse_names)
        protected_title = self._protect_with_placeholders(seed_term_plan.protected_title, horse_placeholders)
        protected_body = self._protect_with_placeholders(seed_term_plan.protected_body, horse_placeholders)
        protected_title = self._protect_with_placeholders(protected_title, person_source_placeholders)
        protected_body = self._protect_with_placeholders(protected_body, person_source_placeholders)
        unknown_horse_lines = [
            f"- {placeholder} => {name}（译文中先原样复制占位符，系统会还原为日文马名）"
            for placeholder, name in horse_placeholders.items()
        ]
        max_attempts = max(1, int(getattr(settings, "TRANSLATION_MAX_ATTEMPTS", 2)))
        retry_hint = ""
        last_metadata: dict | None = None

        for attempt in range(1, max_attempts + 1):
            response = self._request_completion(
                self._build_messages(
                    article,
                    glossary_lines,
                    unknown_horse_lines,
                    retry_hint=retry_hint,
                    source_title=protected_title,
                    source_body=protected_body,
                )
            )
            choice = response.choices[0]
            content = choice.message.content or "{}"
            payload = json.loads(content)

            mapped_title = apply_contextual_term_mappings((payload.get("title_zh") or "").strip(), resolution)
            mapped_body = apply_contextual_term_mappings((payload.get("body_zh") or "").strip(), resolution)
            mapped_summary = apply_contextual_term_mappings((payload.get("push_summary_zh") or "").strip(), resolution)

            last_metadata = {
                "provider": self.name,
                "model": settings.TRANSLATION_MODEL,
                "terms": serialize_terms(terms),
                "entities": [item.as_dict() for item in resolution.entities],
                "suppressed_entities": [item.as_dict() for item in resolution.suppressed_candidates],
                "accepted_term_ids": sorted(resolution.accepted_term_ids),
                "machine_horse_tags": resolution.machine_horse_tags,
                "unknown_horse_names": unknown_horse_names,
                "recognized_horse_names": serialize_recognized_horse_names(recognized_horses),
                "external_horse_names": [
                    item.matched_text or item.name_ja
                    for item in recognized_horses
                    if item.source == "external_alias"
                ],
                "external_horse_aliases": [
                    {
                        "matched_text": item.matched_text,
                        "name_ja": item.name_ja,
                        "external_horse_ids": item.external_horse_ids,
                    }
                    for item in recognized_horses
                    if item.source == "external_alias"
                ],
                "unknown_horse_placeholders": horse_placeholders,
                "japanese_format_normalizations": format_plan.as_dicts(),
                "japanese_seed_term_normalizations": seed_term_plan.as_dicts(),
                "person_term_placeholders": {
                    placeholder: {"source": source, "target": person_target_placeholders[placeholder]}
                    for placeholder, source in person_source_placeholders.items()
                },
                "raw": payload,
                "finish_reason": getattr(choice, "finish_reason", ""),
                "usage": self._usage_to_dict(getattr(response, "usage", None)),
                "attempt": attempt,
                "max_attempts": max_attempts,
            }

            format_violations = japanese_format_placeholder_violations(
                mapped_title,
                mapped_body,
                format_plan,
            )
            if format_violations:
                last_metadata["japanese_format_placeholder_violations"] = format_violations
                retry_hint = (
                    "\n\n注意：上一版遗漏、重复或跨字段放置了固定格式占位符。"
                    "请在原占位符所属的标题或正文中各原样复制一次 __UMA_FORMAT_数字__ 占位符。"
                )
                if attempt < max_attempts:
                    continue
                raise TranslationResponseError(
                    "Translation response changed required format placeholder",
                    metadata=last_metadata,
                )

            seed_term_violations = japanese_seed_term_placeholder_violations(
                mapped_title,
                mapped_body,
                seed_term_plan,
            )
            if seed_term_violations:
                last_metadata["japanese_seed_term_placeholder_violations"] = seed_term_violations
                retry_hint = (
                    "\n\n注意：上一版遗漏、重复或跨字段放置了种子术语占位符。"
                    "请在原占位符所属的标题或正文中各原样复制一次 __UMA_SEED_数字__ 占位符。"
                )
                if attempt < max_attempts:
                    continue
                raise TranslationResponseError(
                    "Translation response changed required seed term placeholder",
                    metadata=last_metadata,
                )

            title_zh = self._restore_unknown_horse_placeholders(mapped_title, horse_placeholders)
            body_zh = self._restore_unknown_horse_placeholders(mapped_body, horse_placeholders)
            push_summary_zh = self._restore_unknown_horse_placeholders(mapped_summary, horse_placeholders)
            title_zh = self._restore_unknown_horse_placeholders(title_zh, person_target_placeholders)
            body_zh = self._restore_unknown_horse_placeholders(body_zh, person_target_placeholders)
            push_summary_zh = self._restore_unknown_horse_placeholders(push_summary_zh, person_target_placeholders)
            title_zh = restore_japanese_seed_term_placeholders(title_zh, seed_term_plan, field_name="title")
            body_zh = restore_japanese_seed_term_placeholders(body_zh, seed_term_plan, field_name="body")
            push_summary_zh = restore_japanese_seed_term_placeholders(push_summary_zh, seed_term_plan)
            title_zh = restore_japanese_format_placeholders(title_zh, format_plan, field_name="title")
            body_zh = restore_japanese_format_placeholders(body_zh, format_plan, field_name="body")
            push_summary_zh = restore_japanese_format_placeholders(push_summary_zh, format_plan)

            if not title_zh or not body_zh:
                retry_hint = "\n\n注意：上一版输出缺少必要字段，请从头完整重译全文。"
                if attempt < max_attempts:
                    continue
                raise TranslationResponseError("Translation response missing required fields", metadata=last_metadata)

            if self._looks_incomplete(source_text, body_zh):
                retry_hint = "\n\n注意：上一版输出疑似未完整结束。请从头完整翻译全文，不要总结，不要省略最后一段，并确保 body_zh 以完整句子结束。"
                if attempt < max_attempts:
                    continue
                raise TranslationResponseError("Translation response appears incomplete", metadata=last_metadata)

            missing_unknown_horse_names = self._missing_unknown_horse_names(title_zh, body_zh, unknown_horse_names)
            if missing_unknown_horse_names:
                last_metadata["missing_unknown_horse_names"] = missing_unknown_horse_names
                retry_hint = (
                    "\n\n注意：上一版把部分未收录中文译名的马名翻掉了。"
                    "请保留对应占位符，不要自行翻译或删除。"
                    f"缺失的原始马名：{'、'.join(missing_unknown_horse_names)}。"
                )
                if attempt < max_attempts:
                    continue
                last_metadata["warning"] = "Translation response changed unknown horse names; accepted with warning"

            translated_text = "\n".join([title_zh or "", body_zh or ""])
            missing_person_targets = sorted(
                {target for target in person_target_placeholders.values() if target not in translated_text}
            )
            if missing_person_targets:
                last_metadata["missing_person_term_targets"] = missing_person_targets
                retry_hint = (
                    "\n\n注意：上一版没有保留部分人名术语占位符。"
                    "请原样复制所有 __UMA_TERM_数字__ 占位符，不要音译或删除。"
                )
                if attempt < max_attempts:
                    continue
                raise TranslationResponseError(
                    "Translation response changed required person terms",
                    metadata=last_metadata,
                )

            return TranslationResult(
                title_zh=title_zh,
                body_zh=body_zh,
                push_summary_zh=(push_summary_zh or body_zh[:160])[:300],
                metadata=last_metadata,
            )

        raise TranslationResponseError("Translation attempts exhausted", metadata=last_metadata or {})


class SiliconFlowTranslationProvider(OpenAICompatibleTranslationProvider):
    name = "siliconflow"

    def __init__(self) -> None:
        base_url = (settings.SILICONFLOW_BASE_URL or "").strip() or "https://api.siliconflow.cn/v1"
        super().__init__(
            api_key=settings.SILICONFLOW_API_KEY,
            base_url=base_url,
            provider_name=self.name,
        )


def get_translation_provider() -> TranslationProvider:
    if settings.TRANSLATION_PROVIDER == "siliconflow" and settings.SILICONFLOW_API_KEY:
        return SiliconFlowTranslationProvider()
    if settings.TRANSLATION_PROVIDER in {"openai", "openai-compatible"} and settings.OPENAI_API_KEY:
        return OpenAICompatibleTranslationProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=(settings.OPENAI_BASE_URL or "").strip() or "https://api.openai.com/v1",
        )
    return DummyTranslationProvider()


def translate_article(article: NewsArticle) -> TranslationResult:
    provider = get_translation_provider()
    source_text = article.body_ja_normalized or article.body_ja_raw
    resolution = resolve_article_entities(
        article.title_ja,
        source_text,
        source_language=article.source_language or SourceLanguage.JAPANESE,
    )
    terms = _translation_terms(resolution)
    run = article.translation_runs.filter(status="started").order_by("-created_at", "-id").first()
    if run is None:
        run = TranslationRun.objects.create(
            article=article,
            provider_name=provider.name,
            model_name=getattr(settings, "TRANSLATION_MODEL", ""),
            terms_used=serialize_terms(terms),
            prompt_excerpt=source_text[:800],
            raw_response={},
            status="started",
        )
    else:
        run.provider_name = provider.name
        run.model_name = getattr(settings, "TRANSLATION_MODEL", "")
        run.terms_used = serialize_terms(terms)
        run.prompt_excerpt = source_text[:800]
        run.save(update_fields=["provider_name", "model_name", "terms_used", "prompt_excerpt", "updated_at"])
    try:
        if "entity_resolution" in inspect.signature(provider.translate).parameters:
            result = provider.translate(article, entity_resolution=resolution)
        else:
            result = provider.translate(article)
        run.status = "success"
        run.model_name = result.metadata.get("model") or run.model_name
        run.raw_response = result.metadata
        run.error_message = ""
        run.save(update_fields=["status", "model_name", "raw_response", "error_message", "updated_at"])
        return result
    except Exception as exc:
        run.status = "failed"
        if getattr(exc, "metadata", None):
            run.raw_response = getattr(exc, "metadata")
        run.error_message = str(exc)
        run.save(update_fields=["status", "raw_response", "error_message", "updated_at"])
        raise
