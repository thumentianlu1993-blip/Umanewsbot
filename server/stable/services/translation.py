from __future__ import annotations

import json
from dataclasses import dataclass

from django.conf import settings
from openai import OpenAI

from stable.models import NewsArticle, TranslationRun

from .terms import resolve_terms, serialize_terms


@dataclass
class TranslationResult:
    title_zh: str
    body_zh: str
    push_summary_zh: str
    metadata: dict


class TranslationProvider:
    name = "base"

    def translate(self, article: NewsArticle) -> TranslationResult:
        raise NotImplementedError


class DummyTranslationProvider(TranslationProvider):
    name = "dummy"

    def translate(self, article: NewsArticle) -> TranslationResult:
        body = article.body_ja_normalized or article.body_ja_raw
        return TranslationResult(
            title_zh=f"[未配置模型] {article.title_ja}",
            body_zh=body,
            push_summary_zh=body[:140],
            metadata={"provider": self.name},
        )


class OpenAICompatibleTranslationProvider(TranslationProvider):
    name = "openai-compatible"

    def __init__(self) -> None:
        kwargs = {"api_key": settings.OPENAI_API_KEY}
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL
        self.client = OpenAI(**kwargs)

    def translate(self, article: NewsArticle) -> TranslationResult:
        terms = resolve_terms(article.body_ja_normalized or article.body_ja_raw, settings.TRANSLATION_TERM_LIMIT)
        glossary_lines = [
            f"- [{term.term_type}] {term.source_ja} => {term.target_zh}"
            + (f"（备注：{term.notes}）" if term.notes else "")
            for term in terms
        ]
        prompt = (
            "你是一名熟悉日本赛马行业的专业译者，请把以下日文赛马新闻翻译成自然、准确、简体中文。"
            "必须优先遵守术语表中的译法。输出 JSON，键为 title_zh, body_zh, push_summary_zh。\n\n"
            f"术语表：\n{'\n'.join(glossary_lines) if glossary_lines else '无可用术语。'}\n\n"
            f"标题：{article.title_ja}\n\n正文：\n{article.body_ja_normalized or article.body_ja_raw}"
        )
        response = self.client.chat.completions.create(
            model=settings.TRANSLATION_MODEL,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "你负责把日本赛马新闻译成简体中文，忠于原文，不编造，不省略关键事实。",
                },
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
        return TranslationResult(
            title_zh=payload.get("title_zh", article.title_ja),
            body_zh=payload.get("body_zh", article.body_ja_normalized or article.body_ja_raw),
            push_summary_zh=payload.get("push_summary_zh", "")[:300],
            metadata={
                "provider": self.name,
                "model": settings.TRANSLATION_MODEL,
                "terms": serialize_terms(terms),
                "raw": payload,
            },
        )


def get_translation_provider() -> TranslationProvider:
    if settings.TRANSLATION_PROVIDER in {"openai", "openai-compatible"} and settings.OPENAI_API_KEY:
        return OpenAICompatibleTranslationProvider()
    return DummyTranslationProvider()


def translate_article(article: NewsArticle) -> TranslationResult:
    provider = get_translation_provider()
    terms = resolve_terms(article.body_ja_normalized or article.body_ja_raw, settings.TRANSLATION_TERM_LIMIT)
    try:
        result = provider.translate(article)
        TranslationRun.objects.create(
            article=article,
            provider_name=provider.name,
            model_name=settings.TRANSLATION_MODEL,
            terms_used=serialize_terms(terms),
            prompt_excerpt=(article.body_ja_normalized or article.body_ja_raw)[:800],
            raw_response=result.metadata,
            status="success",
        )
        return result
    except Exception as exc:
        TranslationRun.objects.create(
            article=article,
            provider_name=provider.name,
            model_name=settings.TRANSLATION_MODEL,
            terms_used=serialize_terms(terms),
            prompt_excerpt=(article.body_ja_normalized or article.body_ja_raw)[:800],
            raw_response={},
            status="failed",
            error_message=str(exc),
        )
        raise
