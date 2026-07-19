from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from stable.models import SourceSite


PERMISSION_APPROVED = "approved"
PERMISSION_UNKNOWN = "unknown"
PERMISSION_BLOCKED = "blocked"
PERMISSION_EXPIRED = "expired"
TECHNICAL_ACCESS_ACCEPTED = "accepted"
TECHNICAL_ACCESS_BLOCKED = "blocked"
INTERNAL_ONLY_USAGE_SCOPE = "internal_only"
LEGACY_PERMISSION_UNREGISTERED = "legacy_permission_unregistered"


@dataclass(frozen=True)
class SourcePermissionRecord:
    canonical_source_site: str
    technical_access: str
    usage_scope: str
    public_publish_allowed: bool
    terms_risk: str
    allowed_hosts: tuple[str, ...]
    evidence_url: str
    reviewed_at: str
    legacy_reason_contract: bool = False

    @property
    def status(self) -> str:
        """兼容旧 probe/审计字段；值只表示技术访问状态。"""

        return self.technical_access

    @property
    def notes(self) -> str:
        """兼容旧后台展示字段；不得解释为第三方授权。"""

        return self.terms_risk


@dataclass(frozen=True)
class SourcePermissionDecision:
    canonical_source_site: str
    status: str
    reason: str
    allowed: bool
    record: SourcePermissionRecord | None = None
    request_budget: "SourceRequestBudget | None" = None


@dataclass
class SourceRequestBudget:
    canonical_source_site: str
    listing_limit: int = 1
    detail_limit: int = 2
    ledger: list[dict] = field(default_factory=list)
    _used: dict[str, int] = field(
        default_factory=lambda: {"listing": 0, "detail": 0}
    )

    @property
    def request_count(self) -> int:
        return sum(self._used.values())

    def consume(self, kind: str, url: str) -> None:
        normalized_kind = str(kind or "").strip().lower()
        limits = {
            "listing": max(0, int(self.listing_limit)),
            "detail": max(0, int(self.detail_limit)),
        }
        if normalized_kind not in limits:
            raise ValueError("source_request_budget_invalid_kind")
        if self.ledger and self.ledger[-1].get("status") == "started":
            self.ledger[-1]["status"] = "redirected"
        if self._used[normalized_kind] >= limits[normalized_kind]:
            raise RuntimeError("source_request_budget_exhausted")
        self._used[normalized_kind] += 1
        self.ledger.append(
            {
                "kind": normalized_kind,
                "canonical_host": (
                    urlsplit(str(url or "")).hostname or ""
                ).rstrip(".").casefold(),
                "url": str(url or ""),
                "attempt_ordinal": self._used[normalized_kind],
                "status": "started",
            }
        )

    def mark_last(self, status: str) -> None:
        if self.ledger:
            self.ledger[-1]["status"] = str(status or "unknown")


SOURCE_PERMISSION_REGISTRY: dict[str, SourcePermissionRecord] = {
    SourceSite.TDN: SourcePermissionRecord(
        canonical_source_site=SourceSite.TDN,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk=(
            "公开内容技术链路已验证；既有用户协议风险保留，且不代表公开再发布授权。"
        ),
        allowed_hosts=("www.thoroughbreddailynews.com", "thoroughbreddailynews.com"),
        evidence_url="https://www.thoroughbreddailynews.com/tdn-user-agreement/",
        reviewed_at="2026-07-20",
    ),
    SourceSite.HRI_NEWS: SourcePermissionRecord(
        canonical_source_site=SourceSite.HRI_NEWS,
        technical_access=TECHNICAL_ACCESS_BLOCKED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="列表可达但详情缺少可验证发布时间；技术链路按失败关闭。",
        allowed_hosts=("www.hri.ie", "hri.ie"),
        evidence_url="https://www.hri.ie/",
        reviewed_at="2026-07-20",
    ),
    SourceSite.WOODBINE_NEWS: SourcePermissionRecord(
        canonical_source_site=SourceSite.WOODBINE_NEWS,
        technical_access=TECHNICAL_ACCESS_BLOCKED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="列表可达但详情缺少可验证发布时间；技术链路按失败关闭。",
        allowed_hosts=("woodbine.com", "www.woodbine.com"),
        evidence_url="https://woodbine.com/",
        reviewed_at="2026-07-20",
    ),
    SourceSite.EMIRATES_RACING_AUTHORITY: SourcePermissionRecord(
        canonical_source_site=SourceSite.EMIRATES_RACING_AUTHORITY,
        technical_access=TECHNICAL_ACCESS_BLOCKED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="列表可达但详情缺少可验证发布时间；技术链路按失败关闭。",
        allowed_hosts=("emiratesracing.com", "www.emiratesracing.com"),
        evidence_url="https://emiratesracing.com/",
        reviewed_at="2026-07-20",
    ),
    SourceSite.JCSA_NEWS: SourcePermissionRecord(
        canonical_source_site=SourceSite.JCSA_NEWS,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk=(
            "技术链路已验证；仅限内部使用，不代表取得再发布授权。"
        ),
        allowed_hosts=("jcsa.sa", "www.jcsa.sa"),
        evidence_url="https://jcsa.sa/en/news/",
        reviewed_at="2026-07-20",
    ),
    SourceSite.RACING_VICTORIA_NEWS: SourcePermissionRecord(
        canonical_source_site=SourceSite.RACING_VICTORIA_NEWS,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk=(
            "技术链路已验证；仅限内部使用，不代表取得再发布授权。"
        ),
        allowed_hosts=("www.racingvictoria.com.au", "racingvictoria.com.au"),
        evidence_url="https://www.racingvictoria.com.au/news",
        reviewed_at="2026-07-20",
    ),
    SourceSite.RTE_RACING: SourcePermissionRecord(
        canonical_source_site=SourceSite.RTE_RACING,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="仅限认证后的内部采集；公开发布与外部分发禁止。",
        allowed_hosts=("www.rte.ie", "rte.ie"),
        evidence_url="https://www.rte.ie/feeds/rss/?index=/sport/racing/",
        reviewed_at="2026-07-19",
    ),
    SourceSite.IRISHRACING_NEWS: SourcePermissionRecord(
        canonical_source_site=SourceSite.IRISHRACING_NEWS,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="仅限认证后的内部采集；既有条款风险仍需保留审计。",
        allowed_hosts=("www.irishracing.com", "irishracing.com"),
        evidence_url="https://www.irishracing.com/news",
        reviewed_at="2026-07-19",
    ),
    SourceSite.CANADIAN_THOROUGHBRED: SourcePermissionRecord(
        canonical_source_site=SourceSite.CANADIAN_THOROUGHBRED,
        technical_access=TECHNICAL_ACCESS_BLOCKED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="匿名探测落入登录或 CAPTCHA 挑战；技术链路按失败关闭。",
        allowed_hosts=("canadianthoroughbred.com", "www.canadianthoroughbred.com"),
        evidence_url="https://canadianthoroughbred.com/news/",
        reviewed_at="2026-07-20",
    ),
    SourceSite.ASSINIBOIA_DOWNS_NEWS: SourcePermissionRecord(
        canonical_source_site=SourceSite.ASSINIBOIA_DOWNS_NEWS,
        technical_access=TECHNICAL_ACCESS_BLOCKED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="匿名详情探测触发访问挑战；技术链路按失败关闭。",
        allowed_hosts=("asdowns.com", "www.asdowns.com"),
        evidence_url="https://asdowns.com/feed/",
        reviewed_at="2026-07-20",
    ),
    SourceSite.DUBAI_RACING_CLUB: SourcePermissionRecord(
        canonical_source_site=SourceSite.DUBAI_RACING_CLUB,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="既有条款要求书面许可；本记录不代表公开发布授权。",
        allowed_hosts=("dubairacingclub.com", "www.dubairacingclub.com"),
        evidence_url="https://dubairacingclub.com/feed/",
        reviewed_at="2026-07-19",
    ),
    SourceSite.THE_NATIONAL_RACING: SourcePermissionRecord(
        canonical_source_site=SourceSite.THE_NATIONAL_RACING,
        technical_access=TECHNICAL_ACCESS_BLOCKED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="匿名探测落入登录或 CAPTCHA 挑战；技术链路按失败关闭。",
        allowed_hosts=("www.thenationalnews.com", "thenationalnews.com"),
        evidence_url="https://www.thenationalnews.com/sport/horse-racing/",
        reviewed_at="2026-07-20",
    ),
    SourceSite.SPA_HORSE_RACING: SourcePermissionRecord(
        canonical_source_site=SourceSite.SPA_HORSE_RACING,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="既有条款限制自动处理与复制；不允许公开发布。",
        allowed_hosts=(
            "www.spa.gov.sa",
            "spa.gov.sa",
            "portalapi.spa.gov.sa",
        ),
        evidence_url="https://www.spa.gov.sa/en/search?search=horse%20racing",
        reviewed_at="2026-07-20",
    ),
    SourceSite.ARAB_NEWS_RACING: SourcePermissionRecord(
        canonical_source_site=SourceSite.ARAB_NEWS_RACING,
        technical_access=TECHNICAL_ACCESS_BLOCKED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="匿名请求返回 HTTP 403；技术链路按失败关闭。",
        allowed_hosts=("www.arabnews.com", "arabnews.com"),
        evidence_url="https://www.arabnews.com/tags/horse-racing",
        reviewed_at="2026-07-20",
    ),
    SourceSite.JUST_HORSE_RACING: SourcePermissionRecord(
        canonical_source_site=SourceSite.JUST_HORSE_RACING,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="既有条款要求书面许可；本记录只允许内部使用。",
        allowed_hosts=(
            "www.justhorseracing.com.au",
            "justhorseracing.com.au",
        ),
        evidence_url="https://www.justhorseracing.com.au/feed",
        reviewed_at="2026-07-19",
    ),
    SourceSite.THE_STRAIGHT: SourcePermissionRecord(
        canonical_source_site=SourceSite.THE_STRAIGHT,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="未取得公开再发布授权；只允许内部使用。",
        allowed_hosts=("thestraight.com.au", "www.thestraight.com.au"),
        evidence_url="https://thestraight.com.au/feed/",
        reviewed_at="2026-07-19",
    ),
    SourceSite.RACING_NSW_NEWS: SourcePermissionRecord(
        canonical_source_site=SourceSite.RACING_NSW_NEWS,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="未取得公开再发布授权；只允许内部使用。",
        allowed_hosts=("www.racingnsw.com.au", "racingnsw.com.au"),
        evidence_url="https://www.racingnsw.com.au/feed/",
        reviewed_at="2026-07-19",
    ),
    SourceSite.TASRACING_NEWS: SourcePermissionRecord(
        canonical_source_site=SourceSite.TASRACING_NEWS,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="未取得公开再发布授权；只允许内部使用。",
        allowed_hosts=("tasracing.com.au", "www.tasracing.com.au"),
        evidence_url="https://tasracing.com.au/news/rss.xml",
        reviewed_at="2026-07-19",
    ),
    SourceSite.BLOODHORSE: SourcePermissionRecord(
        canonical_source_site=SourceSite.BLOODHORSE,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="技术链路已验证；仅限内部使用，不代表取得再发布授权。",
        allowed_hosts=("www.bloodhorse.com", "bloodhorse.com"),
        evidence_url="https://www.bloodhorse.com/horse-racing/articles",
        reviewed_at="2026-07-20",
    ),
    SourceSite.HORSE_RACING_NATION: SourcePermissionRecord(
        canonical_source_site=SourceSite.HORSE_RACING_NATION,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="技术链路已验证；仅限内部使用，不代表取得再发布授权。",
        allowed_hosts=("www.horseracingnation.com", "horseracingnation.com"),
        evidence_url="https://www.horseracingnation.com/news",
        reviewed_at="2026-07-20",
    ),
    SourceSite.SKY_SPORTS_RACING: SourcePermissionRecord(
        canonical_source_site=SourceSite.SKY_SPORTS_RACING,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="技术链路已验证；仅限内部使用，不代表取得再发布授权。",
        allowed_hosts=("www.skysports.com", "skysports.com"),
        evidence_url="https://www.skysports.com/racing/news",
        reviewed_at="2026-07-20",
    ),
    SourceSite.SPORTING_LIFE: SourcePermissionRecord(
        canonical_source_site=SourceSite.SPORTING_LIFE,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="技术链路已验证；仅限内部使用，不代表取得再发布授权。",
        allowed_hosts=("www.sportinglife.com", "sportinglife.com"),
        evidence_url="https://www.sportinglife.com/racing/news",
        reviewed_at="2026-07-20",
    ),
    SourceSite.BHA: SourcePermissionRecord(
        canonical_source_site=SourceSite.BHA,
        technical_access=TECHNICAL_ACCESS_ACCEPTED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="技术链路已验证；仅限内部使用，不代表取得再发布授权。",
        allowed_hosts=(
            "www.britishhorseracing.com",
            "britishhorseracing.com",
        ),
        evidence_url="https://www.britishhorseracing.com/press-releases/",
        reviewed_at="2026-07-20",
    ),
    SourceSite.PAULICK_REPORT: SourcePermissionRecord(
        canonical_source_site=SourceSite.PAULICK_REPORT,
        technical_access=TECHNICAL_ACCESS_BLOCKED,
        usage_scope=INTERNAL_ONLY_USAGE_SCOPE,
        public_publish_allowed=False,
        terms_risk="匿名请求受访问限制；技术链路按失败关闭。",
        allowed_hosts=("paulickreport.com", "www.paulickreport.com"),
        evidence_url="https://paulickreport.com/news/",
        reviewed_at="2026-07-20",
    ),
}

# 旧第二轮回归把此集合用作“变更前受管来源快照”；保留其精确语义。
MANAGED_PERMISSION_SOURCES = frozenset(
    {
        SourceSite.TDN,
        SourceSite.HRI_NEWS,
        SourceSite.WOODBINE_NEWS,
        SourceSite.EMIRATES_RACING_AUTHORITY,
        SourceSite.JCSA_NEWS,
        SourceSite.RACING_VICTORIA_NEWS,
    }
)
MANAGED_CANONICAL_SOURCE_SITES = MANAGED_PERMISSION_SOURCES
INTERNAL_DIRECT_SOURCE_SITES = frozenset(SOURCE_PERMISSION_REGISTRY)
THIRD_BATCH_DIRECT_SOURCE_SITES = frozenset(
    {
        SourceSite.RTE_RACING,
        SourceSite.IRISHRACING_NEWS,
        SourceSite.CANADIAN_THOROUGHBRED,
        SourceSite.ASSINIBOIA_DOWNS_NEWS,
        SourceSite.DUBAI_RACING_CLUB,
        SourceSite.THE_NATIONAL_RACING,
        SourceSite.SPA_HORSE_RACING,
        SourceSite.ARAB_NEWS_RACING,
        SourceSite.JUST_HORSE_RACING,
        SourceSite.THE_STRAIGHT,
        SourceSite.RACING_NSW_NEWS,
        SourceSite.TASRACING_NEWS,
    }
)


def canonical_source_site_for_adapter(adapter) -> str:
    return str(
        getattr(adapter, "canonical_source_site", None)
        or getattr(adapter, "source_site", "")
        or ""
    ).strip()


def resolve_source_permission(adapter) -> SourcePermissionDecision:
    canonical = canonical_source_site_for_adapter(adapter)
    record = SOURCE_PERMISSION_REGISTRY.get(canonical)
    if record is None:
        return SourcePermissionDecision(
            canonical_source_site=canonical,
            status=LEGACY_PERMISSION_UNREGISTERED,
            reason=LEGACY_PERMISSION_UNREGISTERED,
            allowed=True,
        )

    declared_hosts = {
        str(host).strip().rstrip(".").casefold()
        for host in (getattr(adapter, "allowed_hosts", ()) or ())
        if str(host).strip()
    }
    record_hosts = {
        host.rstrip(".").casefold() for host in record.allowed_hosts
    }
    if declared_hosts and not declared_hosts.issubset(record_hosts):
        return SourcePermissionDecision(
            canonical_source_site=canonical,
            status=PERMISSION_UNKNOWN,
            reason=(
                "permission_host_mismatch"
                if record.legacy_reason_contract
                else "technical_host_mismatch"
            ),
            allowed=False,
            record=record,
        )

    if record.technical_access in {
        TECHNICAL_ACCESS_BLOCKED,
        PERMISSION_EXPIRED,
    }:
        return SourcePermissionDecision(
            canonical_source_site=canonical,
            status=record.status,
            reason=(
                "permission_blocked_preflight"
                if record.legacy_reason_contract
                else "technical_access_blocked"
            ),
            allowed=False,
            record=record,
        )
    if record.technical_access == PERMISSION_UNKNOWN:
        return SourcePermissionDecision(
            canonical_source_site=canonical,
            status=record.status,
            reason="permission_unknown_research_only",
            allowed=False,
            record=record,
        )
    if record.technical_access != TECHNICAL_ACCESS_ACCEPTED:
        return SourcePermissionDecision(
            canonical_source_site=canonical,
            status=record.status,
            reason="technical_access_invalid",
            allowed=False,
            record=record,
        )
    if (
        record.usage_scope != INTERNAL_ONLY_USAGE_SCOPE
        or record.public_publish_allowed is not False
    ):
        return SourcePermissionDecision(
            canonical_source_site=canonical,
            status=record.status,
            reason="technical_usage_scope_invalid",
            allowed=False,
            record=record,
        )
    return SourcePermissionDecision(
        canonical_source_site=canonical,
        status=record.status,
        reason="internal_only_technical_access",
        allowed=True,
        record=record,
    )


def preflight_source_access(
    adapter,
    *,
    research_mode: bool = False,
) -> SourcePermissionDecision:
    decision = resolve_source_permission(adapter)
    if decision.status != PERMISSION_UNKNOWN:
        return decision
    if not research_mode:
        return decision
    if not bool(getattr(adapter, "supports_research_request_budget", False)):
        return SourcePermissionDecision(
            canonical_source_site=decision.canonical_source_site,
            status=decision.status,
            reason="research_budget_unsupported",
            allowed=False,
            record=decision.record,
        )
    budget = SourceRequestBudget(
        canonical_source_site=decision.canonical_source_site,
    )
    attach_budget = getattr(adapter, "attach_request_budget", None)
    if not callable(attach_budget):
        return SourcePermissionDecision(
            canonical_source_site=decision.canonical_source_site,
            status=decision.status,
            reason="research_budget_unsupported",
            allowed=False,
            record=decision.record,
        )
    attach_budget(budget)
    return SourcePermissionDecision(
        canonical_source_site=decision.canonical_source_site,
        status=decision.status,
        reason="permission_unknown_research_only",
        allowed=True,
        record=decision.record,
        request_budget=budget,
    )


def permission_audit_reason_for_source(source) -> str:
    from stable.adapters.international import INTERNATIONAL_ADAPTERS

    adapter_class = INTERNATIONAL_ADAPTERS.get(str(source.adapter_key or ""))
    if adapter_class is None:
        return LEGACY_PERMISSION_UNREGISTERED
    return resolve_source_permission(adapter_class()).reason
