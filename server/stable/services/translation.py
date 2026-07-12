from __future__ import annotations

import json
import re
from dataclasses import dataclass

from django.conf import settings
from openai import OpenAI

from stable.models import NewsArticle, SourceLanguage, TranslationRun

from .terms import (
    apply_term_mappings,
    recognize_horse_names,
    resolve_terms_for_language,
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

    def translate(self, article: NewsArticle) -> TranslationResult:
        raise NotImplementedError


class DummyTranslationProvider(TranslationProvider):
    name = "dummy"

    def translate(self, article: NewsArticle) -> TranslationResult:
        body = article.body_ja_normalized or article.body_ja_raw
        source_language = article.source_language or SourceLanguage.JAPANESE
        mapped_title = apply_term_mappings(article.title_ja, source_language=source_language)
        mapped_body = apply_term_mappings(body, source_language=source_language)
        return TranslationResult(
            title_zh=f"[未配置真实翻译模型] {mapped_title}",
            body_zh=mapped_body,
            push_summary_zh=mapped_body[:140],
            metadata={"provider": self.name, "model": "dummy"},
        )


def _article_term_text(article: NewsArticle) -> str:
    return "\n".join(
        part
        for part in [
            article.title_ja or "",
            article.body_ja_normalized or article.body_ja_raw or "",
        ]
        if part
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
            "若原文中出现 __UMA_KEEP_数字__ 形式的占位符，请在译文中原样复制该占位符，不要翻译或删除。"
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

        if self._ends_with_complete_sentence(source) and not self._ends_with_complete_sentence(target):
            return True
        if source_list_count >= 2 and target_list_count < source_list_count:
            return True
        if len(source) >= 600 and len(target) < max(320, int(len(source) * 0.58)):
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
        protected = text or ""
        placeholders: dict[str, str] = {}
        for index, name in enumerate(sorted(unknown_horse_names, key=len, reverse=True), start=1):
            placeholder = f"__UMA_KEEP_{index}__"
            protected = protected.replace(name, placeholder)
            placeholders[placeholder] = name
        return protected, placeholders

    @staticmethod
    def _restore_unknown_horse_placeholders(text: str, placeholders: dict[str, str]) -> str:
        restored = text or ""
        for placeholder, name in placeholders.items():
            restored = restored.replace(placeholder, name)
        return restored

    @staticmethod
    def _usage_to_dict(usage) -> dict:
        if usage is None:
            return {}
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if isinstance(usage, dict):
            return usage
        return {"repr": repr(usage)}

    def translate(self, article: NewsArticle) -> TranslationResult:
        terms = resolve_terms_for_language(
            _article_term_text(article),
            article.source_language or SourceLanguage.JAPANESE,
            settings.TRANSLATION_TERM_LIMIT,
        )
        glossary_lines = [
            f"- [{term.term_type}] {term.matched_text or term.source_ja} => {term.target_zh}"
            + (f"（备注：{term.notes}）" if term.notes else "")
            for term in terms
            if (term.target_zh or "").strip()
        ]
        source_text = article.body_ja_normalized or article.body_ja_raw
        unknown_horse_limit = max(1, int(settings.TRANSLATION_UNKNOWN_HORSE_LIMIT))
        recognized_horses = recognize_horse_names(
            article.title_ja,
            source_text,
            limit=None,
            source_language=article.source_language or SourceLanguage.JAPANESE,
        )
        unknown_horse_names = [
            item.matched_text or item.name_ja
            for item in recognized_horses
            if item.needs_preserve and (item.matched_text or item.name_ja)
        ][:unknown_horse_limit]
        protected_title, title_placeholders = self._protect_unknown_horse_names(article.title_ja, unknown_horse_names)
        protected_body, body_placeholders = self._protect_unknown_horse_names(source_text, unknown_horse_names)
        horse_placeholders = {**title_placeholders, **body_placeholders}
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

            title_zh = self._restore_unknown_horse_placeholders((payload.get("title_zh") or "").strip(), horse_placeholders)
            body_zh = self._restore_unknown_horse_placeholders((payload.get("body_zh") or "").strip(), horse_placeholders)
            push_summary_zh = self._restore_unknown_horse_placeholders((payload.get("push_summary_zh") or "").strip(), horse_placeholders)

            last_metadata = {
                "provider": self.name,
                "model": settings.TRANSLATION_MODEL,
                "terms": serialize_terms(terms),
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
                "raw": payload,
                "finish_reason": getattr(choice, "finish_reason", ""),
                "usage": self._usage_to_dict(getattr(response, "usage", None)),
                "attempt": attempt,
                "max_attempts": max_attempts,
            }

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

            source_language = article.source_language or SourceLanguage.JAPANESE
            return TranslationResult(
                title_zh=apply_term_mappings(title_zh, source_language=source_language),
                body_zh=apply_term_mappings(body_zh, source_language=source_language),
                push_summary_zh=apply_term_mappings(push_summary_zh or body_zh[:160], source_language=source_language)[:300],
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
    terms = resolve_terms_for_language(
        _article_term_text(article),
        article.source_language or SourceLanguage.JAPANESE,
        settings.TRANSLATION_TERM_LIMIT,
    )
    run = TranslationRun.objects.create(
        article=article,
        provider_name=provider.name,
        model_name=getattr(settings, "TRANSLATION_MODEL", ""),
        terms_used=serialize_terms(terms),
        prompt_excerpt=source_text[:800],
        raw_response={},
        status="started",
    )
    try:
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
