from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping
from urllib.parse import SplitResult, urlsplit

from django.core.exceptions import ValidationError


DEPRECATED_CROSS_YEAR_REASONS = {
    "hong_kong_racing_season_spans_calendar_years",
}


def _year(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > 9999:
        raise ValidationError({label: f"{label} 必须是有效年份。"})
    return value


def _local_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ValidationError({"local_date": "local_date 必须是 date、datetime 或 None。"})


def derive_public_year(local_date: date | datetime | None, planned_year: int) -> int:
    """返回公开自然年；已知当地日期永远优先于排期年份。"""

    planned = _year(planned_year, label="planned_year")
    local = _local_date(local_date)
    return local.year if local is not None else planned


def validate_authority_url(value: Any) -> SplitResult:
    """返回已验证的权威证据 URL；所有跨届次入口共用同一合同。"""

    authority_url = str(value or "").strip()
    try:
        parsed = urlsplit(authority_url)
        valid = bool(
            authority_url
            and not any(character.isspace() for character in authority_url)
            and parsed.scheme.casefold() == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValidationError(
            {
                "authority_url": (
                    "authority_url 必须是无凭据、无 fragment 的有效 HTTPS URL。"
                )
            }
        )
    return parsed


def validate_event_years(
    public_year: int,
    edition_year: int,
    local_date: date | datetime | None,
    cross_year_evidence: Mapping[str, Any] | None = None,
) -> None:
    """验证公开自然年和届次年的集中合同。

    Release A 允许数据库旧行的 ``edition_year`` 为空，但新写入调用此 helper
    时必须传入明确届次年。跨届次仅接受绑定实际自然年、非废弃原因、权威 URL
    以及不可含糊的人工批准标记。
    """

    public = _year(public_year, label="public_year")
    edition = _year(edition_year, label="edition_year")
    local = _local_date(local_date)
    if local is not None and public != local.year:
        raise ValidationError(
            {"public_year": "公开赛事年份必须与已知比赛当地日期的自然年一致。"}
        )

    evidence = dict(cross_year_evidence or {})
    reason = str(evidence.get("reason") or "").strip()
    if reason in DEPRECATED_CROSS_YEAR_REASONS:
        raise ValidationError(
            {
                "cross_year_evidence": (
                    "旧香港马季跨年原因已废弃，必须使用自然年重新 prepare。"
                )
            }
        )
    if edition == public:
        return

    actual_year = evidence.get("actual_year")
    try:
        validate_authority_url(evidence.get("authority_url"))
        authority_url_is_valid = True
    except ValidationError:
        authority_url_is_valid = False
    approved = evidence.get("approved") is True
    if (
        isinstance(actual_year, bool)
        or actual_year != public
        or not reason
        or not authority_url_is_valid
        or not approved
    ):
        raise ValidationError(
            {
                "edition_year": (
                    "届次年份与公开自然年不同时，必须提供已批准的权威跨年证据。"
                )
            }
        )


def event_edition_year(event: Any) -> int:
    """Release A 双读：新字段优先，旧行显式回退公开年份。"""

    value = getattr(event, "edition_year", None)
    if value is None:
        value = getattr(event, "year", None)
    return _year(value, label="edition_year")


def _target_cross_year_evidence(target: Any, *, public_year: int) -> dict[str, Any] | None:
    refs = getattr(target, "source_refs", None)
    if not isinstance(refs, Mapping):
        return None
    explicit = refs.get("cross_year_evidence")
    if isinstance(explicit, Mapping):
        return dict(explicit)

    discovery = refs.get("detail_discovery")
    if not isinstance(discovery, Mapping):
        return None
    urls = discovery.get("urls")
    authority_url = ""
    authority = ""
    if isinstance(urls, Mapping):
        for key in (
            "result_url",
            "cancellation_url",
            "actual_runners_url",
            "declared_runners_url",
            "non_runner_url",
        ):
            value = urls.get(key)
            if not isinstance(value, Mapping):
                continue
            candidate_url = str(value.get("url") or "").strip()
            candidate_authority = str(value.get("source_authority") or "").strip()
            if candidate_url and candidate_authority:
                authority_url = candidate_url
                authority = candidate_authority
                break
    return {
        "actual_year": discovery.get("actual_year", public_year),
        "reason": str(discovery.get("cross_year_reason") or "").strip(),
        "authority_url": authority_url,
        "source_authority": authority,
        "approved": discovery.get("approved") is True,
        "approved_by": str(discovery.get("approved_by") or "").strip(),
        "approved_at": str(discovery.get("approved_at") or "").strip(),
        "manifest_sha256": str(discovery.get("manifest_sha256") or "").strip(),
    }


def historical_event_identity(target: Any, local_date: date | datetime | None) -> dict[str, Any]:
    """从历史 target 生成新 RaceEvent 的年份身份字段。"""

    edition_year = _year(getattr(target, "year", None), label="edition_year")
    public_year = derive_public_year(local_date, edition_year)
    evidence = _target_cross_year_evidence(target, public_year=public_year)
    validate_event_years(public_year, edition_year, local_date, evidence)
    return {
        "public_year": public_year,
        "edition_year": edition_year,
        "cross_year_evidence": evidence if edition_year != public_year else None,
    }
