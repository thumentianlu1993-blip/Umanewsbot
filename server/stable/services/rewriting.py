from __future__ import annotations

import json
import inspect
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
from stable.services.terms import (
    ArticleEntityResolution,
    apply_contextual_horse_placeholders,
    apply_generated_text_contextual_mappings,
    resolve_article_entities,
    resolve_article_entities_for_article,
)


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

    def rewrite(
        self,
        article: NewsArticle,
        *,
        entity_resolution: ArticleEntityResolution | None = None,
    ) -> RewriteResult:
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
        ContentCategory.NEWS: "新闻：标题直接给信息点，首段先交代最重要事实。",
        ContentCategory.PREVIEW: "赛前展望：突出赛事、时间、参赛马和看点。",
        ContentCategory.RESULT_BRIEF: "赛果简报：突出结果、名次、关键表现和后续影响。",
        ContentCategory.OFFICIAL_NOTICE: "官方通知：保持公告口径，语言克制，不扩大解读。",
        ContentCategory.RACECARD_UPDATE: "出赛/排位更新：突出赛事、名单变化和时间节点。",
        ContentCategory.TIPS: "赛前预测/投注倾向：保留判断来源，不扩大确定性。",
        ContentCategory.FEATURE: "特写：保留人物和背景信息，避免替受访者加工观点。",
        ContentCategory.SALES_BREEDING: "育马/拍卖/机构：突出交易、血统、机构动作和影响范围。",
        ContentCategory.FLASH: "快讯类：用短标题和短首段，突出发生了什么。",
        ContentCategory.PRE_RACE: "赛前前瞻：突出赛事、时间、参赛马和看点。",
        ContentCategory.POST_RACE: "赛果/复盘：突出结果、名次、关键表现和后续影响。",
        ContentCategory.OFFICIAL: "官方公告：保持公告口径，语言克制，不扩大解读。",
        ContentCategory.INTERVIEW: "采访/人物：保留引语边界，避免替受访者加工观点。",
        ContentCategory.OTHER: "其他：保守改写，优先准确和自然。",
    }
    return instructions.get(category, instructions[ContentCategory.NEWS])


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _loads_rewrite_payload(raw_content: str) -> dict:
    try:
        return json.loads(raw_content or "{}")
    except json.JSONDecodeError:
        cleaned = _CONTROL_CHARS_RE.sub("", raw_content or "{}")
        return json.loads(cleaned)


class FallbackRewriteProvider(RewriteProvider):
    name = "fallback"

    def rewrite(
        self,
        article: NewsArticle,
        *,
        entity_resolution: ArticleEntityResolution | None = None,
    ) -> RewriteResult:
        title = article.translated_title_zh or article.title_zh or article.title_ja
        body = article.translated_body_zh or article.body_zh or article.body_ja_normalized or article.body_ja_raw
        summary = article.translated_summary_zh or article.summary_zh or _first_sentence(body)
        source_language = article.source_language or SourceLanguage.JAPANESE
        resolution = entity_resolution or resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized or article.body_ja_raw,
            source_language=source_language,
        )
        confidence = (
            62
            if article.content_category
            in {
                ContentCategory.FLASH,
                ContentCategory.OFFICIAL,
                ContentCategory.PRE_RACE,
                ContentCategory.POST_RACE,
                ContentCategory.NEWS,
                ContentCategory.PREVIEW,
                ContentCategory.RESULT_BRIEF,
                ContentCategory.OFFICIAL_NOTICE,
            }
            else 55
        )
        return RewriteResult(
            title_zh=apply_generated_text_contextual_mappings(title.strip(), resolution),
            summary_zh=apply_generated_text_contextual_mappings(summary.strip(), resolution),
            body_zh=apply_generated_text_contextual_mappings(body.strip(), resolution),
            confidence=confidence,
            metadata={"provider": self.name, "model": "fallback", "category": article.content_category},
        )


class OpenAICompatibleRewriteProvider(RewriteProvider):
    name = "openai-compatible-rewrite"

    def __init__(self, *, api_key: str, base_url: str, provider_name: str | None = None) -> None:
        self.name = provider_name or self.name
        self.client = OpenAI(api_key=api_key, base_url=base_url.strip())

    @staticmethod
    def _unknown_horse_placeholders(resolution: ArticleEntityResolution) -> dict[str, str]:
        names = {
            item.matched_text
            for item in resolution.entities
            if item.entity_type in {"horse", "unknown_horse"}
            and item.needs_preserve
            and item.classification in {"", "confirmed_horse"}
            and item.matched_text
        }
        return {
            f"__UMA_KEEP_{index}__": name
            for index, name in enumerate(sorted(names, key=lambda item: (-len(item), item)), start=1)
        }

    @staticmethod
    def _apply_placeholders(text: str, placeholders: dict[str, str]) -> str:
        protected = text or ""
        for placeholder, name in placeholders.items():
            protected = protected.replace(name, placeholder)
        return protected

    @staticmethod
    def _restore_placeholders(text: str, placeholders: dict[str, str]) -> str:
        restored = text or ""
        for placeholder, name in placeholders.items():
            restored = restored.replace(placeholder, name)
        return restored

    def _messages(
        self,
        article: NewsArticle,
        *,
        entity_resolution: ArticleEntityResolution | None = None,
        placeholders: dict[str, str] | None = None,
    ) -> list[dict]:
        source_text = article.body_ja_normalized or article.body_ja_raw
        base_body = article.translated_body_zh or article.body_zh
        resolution = entity_resolution or resolve_article_entities(
            article.title_ja,
            source_text,
            source_language=article.source_language or SourceLanguage.JAPANESE,
        )
        terms = resolution.accepted_terms[: settings.TRANSLATION_TERM_LIMIT]
        placeholders = placeholders if placeholders is not None else self._unknown_horse_placeholders(resolution)
        protected_title = apply_contextual_horse_placeholders(
            article.title_ja,
            resolution,
            placeholders,
            field_name="title",
        )
        protected_source_text = apply_contextual_horse_placeholders(
            source_text,
            resolution,
            placeholders,
            field_name="body",
        )
        # Generated/base Chinese fields do not share source coordinates.
        # They must not inherit source occurrence ordinals or global replaces.
        protected_base_title = article.translated_title_zh or article.title_zh
        protected_base_body = base_body
        glossary_lines = [
            f"- [{term.term_type}] {term.matched_text or term.source_ja} => {term.target_zh}"
            + (f"（备注：{term.notes}）" if term.notes else "")
            for term in terms
            if (term.target_zh or "").strip()
        ]
        prompt = (
            f"稿件类型：{article.content_category or ContentCategory.OTHER}\n"
            f"类型要求：{_category_instruction(article.content_category or ContentCategory.OTHER)}\n"
            f"风格要求：{STYLE_GUIDE}\n\n"
            f"术语表：\n{chr(10).join(glossary_lines) if glossary_lines else '无'}\n\n"
            f"完整未知马名占位符：{', '.join(placeholders) if placeholders else '无'}（必须原样保留）\n\n"
            f"原文标题：{protected_title}\n"
            f"基准中文标题：{protected_base_title}\n\n"
            f"原文正文：\n{protected_source_text}\n\n"
            f"基准中文翻译：\n{protected_base_body}\n\n"
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

    def rewrite(
        self,
        article: NewsArticle,
        *,
        entity_resolution: ArticleEntityResolution | None = None,
    ) -> RewriteResult:
        resolution = entity_resolution or resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized or article.body_ja_raw,
            source_language=article.source_language or SourceLanguage.JAPANESE,
        )
        placeholders = self._unknown_horse_placeholders(resolution)
        response = self.client.chat.completions.create(
            model=getattr(settings, "REWRITE_MODEL", settings.TRANSLATION_MODEL),
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=self._messages(article, entity_resolution=resolution, placeholders=placeholders),
            max_tokens=getattr(settings, "REWRITE_MAX_TOKENS", 2600),
            timeout=getattr(settings, "REWRITE_TIMEOUT_SECONDS", settings.TRANSLATION_TIMEOUT_SECONDS),
        )
        choice = response.choices[0]
        payload = _loads_rewrite_payload(choice.message.content or "{}")
        title = self._restore_placeholders((payload.get("rewrite_title_zh") or "").strip(), placeholders)
        summary = self._restore_placeholders((payload.get("rewrite_summary_zh") or "").strip(), placeholders)
        body = self._restore_placeholders((payload.get("rewrite_body_zh") or "").strip(), placeholders)
        confidence = int(payload.get("rewrite_confidence") or 0)
        if not title or not body:
            raise ValueError("Rewrite response missing required fields")
        return RewriteResult(
            title_zh=apply_generated_text_contextual_mappings(title, resolution),
            summary_zh=apply_generated_text_contextual_mappings(summary or _first_sentence(body), resolution),
            body_zh=apply_generated_text_contextual_mappings(body, resolution),
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
    resolution = resolve_article_entities_for_article(article)
    if "entity_resolution" in inspect.signature(provider.rewrite).parameters:
        return provider.rewrite(article, entity_resolution=resolution)
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
