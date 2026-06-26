from __future__ import annotations

import json
import re
from dataclasses import dataclass

from django.conf import settings
from openai import OpenAI

from stable.models import (
    AutomationLog,
    AutomationPhase,
    AutomationResult,
    AutomationStatus,
    ContentCategory,
    NewsArticle,
    SourceLanguage,
)
from stable.services.terms import apply_term_mappings, resolve_terms_for_language


STYLE_GUIDE = (
    "写成中文资讯站稿件：标题直接给信息点，首段先交代最重要事实；"
    "正文保持克制、准确、自然，少翻译腔；不使用营销号语气，不加感叹号堆砌；"
    "不得改动马名、赛事名、骑手、调教师、日期、数字、名次、赔率和引语事实。"
)


@dataclass
class RewriteResult:
    title_zh: str
    summary_zh: str
    body_zh: str
    confidence: int
    metadata: dict


class RewriteProvider:
    name = "base"

    def rewrite(self, article: NewsArticle) -> RewriteResult:
        raise NotImplementedError


def _first_sentence(text: str, max_length: int = 160) -> str:
    normalized = " ".join((text or "").split())
    if not normalized:
        return ""
    for mark in ["。", "！", "？", ";", "；"]:
        index = normalized.find(mark)
        if 0 < index <= max_length:
            return normalized[: index + 1]
    return normalized[:max_length]


def _category_instruction(category: str) -> str:
    instructions = {
        ContentCategory.FLASH: "快讯类：用短标题和短首段，突出发生了什么。",
        ContentCategory.PRE_RACE: "赛前前瞻：突出赛事、时间、参赛马和看点。",
        ContentCategory.POST_RACE: "赛果/复盘：突出结果、名次、关键表现和后续影响。",
        ContentCategory.OFFICIAL: "官方公告：保持公告口径，语言克制，不扩大解读。",
        ContentCategory.INTERVIEW: "采访/人物：保留引语边界，避免替受访者加工观点。",
        ContentCategory.OTHER: "其他：保守改写，优先准确和自然。",
    }
    return instructions.get(category, instructions[ContentCategory.OTHER])


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _loads_rewrite_payload(raw_content: str) -> dict:
    try:
        return json.loads(raw_content or "{}")
    except json.JSONDecodeError:
        cleaned = _CONTROL_CHARS_RE.sub("", raw_content or "{}")
        return json.loads(cleaned)


class FallbackRewriteProvider(RewriteProvider):
    name = "fallback"

    def rewrite(self, article: NewsArticle) -> RewriteResult:
        title = article.translated_title_zh or article.title_zh or article.title_ja
        body = article.translated_body_zh or article.body_zh or article.body_ja_normalized or article.body_ja_raw
        summary = article.translated_summary_zh or article.summary_zh or _first_sentence(body)
        source_language = article.source_language or SourceLanguage.JAPANESE
        confidence = (
            62
            if article.content_category
            in {
                ContentCategory.FLASH,
                ContentCategory.OFFICIAL,
                ContentCategory.PRE_RACE,
                ContentCategory.POST_RACE,
            }
            else 55
        )
        return RewriteResult(
            title_zh=apply_term_mappings(title.strip(), source_language=source_language),
            summary_zh=apply_term_mappings(summary.strip(), source_language=source_language),
            body_zh=apply_term_mappings(body.strip(), source_language=source_language),
            confidence=confidence,
            metadata={"provider": self.name, "model": "fallback", "category": article.content_category},
        )


class OpenAICompatibleRewriteProvider(RewriteProvider):
    name = "openai-compatible-rewrite"

    def __init__(self, *, api_key: str, base_url: str, provider_name: str | None = None) -> None:
        self.name = provider_name or self.name
        self.client = OpenAI(api_key=api_key, base_url=base_url.strip())

    def _messages(self, article: NewsArticle) -> list[dict]:
        source_text = article.body_ja_normalized or article.body_ja_raw
        base_body = article.translated_body_zh or article.body_zh
        terms = resolve_terms_for_language(
            source_text,
            article.source_language or SourceLanguage.JAPANESE,
            settings.TRANSLATION_TERM_LIMIT,
        )
        glossary_lines = [
            f"- [{term.term_type}] {term.matched_text or term.source_ja} => {term.target_zh}"
            + (f"（备注：{term.notes}）" if term.notes else "")
            for term in terms
        ]
        prompt = (
            f"稿件类型：{article.content_category or ContentCategory.OTHER}\n"
            f"类型要求：{_category_instruction(article.content_category or ContentCategory.OTHER)}\n"
            f"风格要求：{STYLE_GUIDE}\n\n"
            f"术语表：\n{chr(10).join(glossary_lines) if glossary_lines else '无'}\n\n"
            f"原文标题：{article.title_ja}\n"
            f"基准中文标题：{article.translated_title_zh or article.title_zh}\n\n"
            f"原文正文：\n{source_text}\n\n"
            f"基准中文翻译：\n{base_body}\n\n"
            "请输出 JSON，只包含 rewrite_title_zh、rewrite_summary_zh、rewrite_body_zh、rewrite_confidence 四个键。"
            "rewrite_confidence 为 0-100 的整数。"
        )
        return [
            {
                "role": "system",
                "content": (
                    "你是一名中文赛马资讯编辑。你的任务是把忠实翻译稿整理为中文资讯稿。"
                    "你只能改表达，不能改事实；必须保留关键实体、数字、日期、名次和引语事实。"
                ),
            },
            {"role": "user", "content": prompt},
        ]

    def rewrite(self, article: NewsArticle) -> RewriteResult:
        response = self.client.chat.completions.create(
            model=getattr(settings, "REWRITE_MODEL", settings.TRANSLATION_MODEL),
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=self._messages(article),
            max_tokens=getattr(settings, "REWRITE_MAX_TOKENS", 2600),
            timeout=getattr(settings, "REWRITE_TIMEOUT_SECONDS", settings.TRANSLATION_TIMEOUT_SECONDS),
        )
        choice = response.choices[0]
        payload = _loads_rewrite_payload(choice.message.content or "{}")
        title = (payload.get("rewrite_title_zh") or "").strip()
        summary = (payload.get("rewrite_summary_zh") or "").strip()
        body = (payload.get("rewrite_body_zh") or "").strip()
        confidence = int(payload.get("rewrite_confidence") or 0)
        if not title or not body:
            raise ValueError("Rewrite response missing required fields")
        source_language = article.source_language or SourceLanguage.JAPANESE
        return RewriteResult(
            title_zh=apply_term_mappings(title, source_language=source_language),
            summary_zh=apply_term_mappings(summary or _first_sentence(body), source_language=source_language),
            body_zh=apply_term_mappings(body, source_language=source_language),
            confidence=max(0, min(100, confidence)),
            metadata={
                "provider": self.name,
                "model": getattr(settings, "REWRITE_MODEL", settings.TRANSLATION_MODEL),
                "raw": payload,
                "finish_reason": getattr(choice, "finish_reason", ""),
            },
        )


class SiliconFlowRewriteProvider(OpenAICompatibleRewriteProvider):
    name = "siliconflow"

    def __init__(self) -> None:
        super().__init__(
            api_key=settings.SILICONFLOW_API_KEY,
            base_url=(settings.SILICONFLOW_BASE_URL or "https://api.siliconflow.cn/v1").strip(),
            provider_name=self.name,
        )


def get_rewrite_provider() -> RewriteProvider:
    provider = (getattr(settings, "REWRITE_PROVIDER", "") or settings.TRANSLATION_PROVIDER or "").lower()
    if provider == "siliconflow" and settings.SILICONFLOW_API_KEY:
        return SiliconFlowRewriteProvider()
    if provider in {"openai", "openai-compatible"} and settings.OPENAI_API_KEY:
        return OpenAICompatibleRewriteProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url=(settings.OPENAI_BASE_URL or "https://api.openai.com/v1").strip(),
        )
    return FallbackRewriteProvider()


def rewrite_article(article: NewsArticle) -> RewriteResult:
    provider = get_rewrite_provider()
    return provider.rewrite(article)


def apply_rewrite_result(article: NewsArticle, result: RewriteResult) -> None:
    article.base_translation_zh = article.base_translation_zh or article.translated_body_zh or article.body_zh
    article.rewrite_title_zh = result.title_zh
    article.rewrite_summary_zh = result.summary_zh
    article.rewrite_body_zh = result.body_zh
    article.rewrite_confidence = result.confidence
    article.automation_status = AutomationStatus.REWRITTEN
    article.automation_error_message = ""
    article.translation_metadata = {
        **(article.translation_metadata or {}),
        "rewrite": result.metadata,
    }
    article.save(
        update_fields=[
            "base_translation_zh",
            "rewrite_title_zh",
            "rewrite_summary_zh",
            "rewrite_body_zh",
            "rewrite_confidence",
            "automation_status",
            "automation_error_message",
            "translation_metadata",
            "updated_at",
        ]
    )
    AutomationLog.objects.create(
        article=article,
        phase=AutomationPhase.REWRITE,
        result=AutomationResult.SUCCESS,
        score=article.score_total,
        confidence=result.confidence,
        reason=f"改写完成：{result.metadata.get('provider', 'unknown')}",
        payload=result.metadata,
    )
