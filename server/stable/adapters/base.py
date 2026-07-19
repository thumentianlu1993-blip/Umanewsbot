from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from stable.models import RacingRegion, SourceKind, SourceLanguage, SourceMode, SourceSite


@dataclass
class SourceImageDraft:
    original_url: str
    caption_ja: str = ""
    sort_order: int = 0


@dataclass
class SourceArticleStub:
    source_site: SourceSite
    source_mode: SourceMode
    source_article_id: str
    source_url: str
    title_ja: str
    published_at: datetime | None
    rank: int | None = None
    comment_count: int | None = None
    attention_count: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class SourceArticleDetail:
    title_ja: str
    body_ja_raw: str
    body_ja_normalized: str
    published_at: datetime | None
    images: list[SourceImageDraft]
    original_content_html: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class CanonicalNewsDraft:
    source_site: SourceSite
    source_mode: SourceMode
    source_article_id: str
    source_url: str
    title_ja: str
    body_ja_raw: str
    body_ja_normalized: str
    published_at: datetime
    images: list[SourceImageDraft]
    racing_region: str = ""
    source_language: str = ""
    source_kind: str = ""
    original_content_html: str = ""
    comment_count: int | None = None
    attention_count: int | None = None
    rank: int | None = None
    canonical_source_site: SourceSite | str | None = None
    metadata: dict = field(default_factory=dict)


class SourceAdapter(ABC):
    source_site: SourceSite

    @abstractmethod
    def fetch_listing(self, mode: SourceMode, page_or_month: str | int) -> list[SourceArticleStub]:
        raise NotImplementedError

    @abstractmethod
    def fetch_detail(self, source_article_id_or_url: str) -> SourceArticleDetail:
        raise NotImplementedError

    @abstractmethod
    def normalize_source_payload(
        self,
        stub: SourceArticleStub,
        detail: SourceArticleDetail,
    ) -> CanonicalNewsDraft:
        raise NotImplementedError
