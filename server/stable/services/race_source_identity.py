"""赛事身份解析：名称只召回，强锚点一致才可自动挂接。无网络副作用。"""

from dataclasses import dataclass
from datetime import date, timedelta
from difflib import SequenceMatcher
import html
import unicodedata
import re
from django.db import connection
from django.db.models import Q
from stable import models
from stable.services.race_data_source_adapters import canonical_sha, aware, require_sha

MATCHER_VERSION = "race-identity-v2"


def normalize_name(value):
    return re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", html.unescape(str(value))).casefold()
    ).strip()


def identity_key(observation):
    fields = ("operator", "venue_key", "local_date", "meeting_session", "race_number")
    if any(not observation.get(k) for k in fields):
        return None
    payload = {k: str(observation[k]) for k in fields}
    return dict(
        key_type="occurrence",
        namespace="race-occurrence-v1",
        key_sha256=canonical_sha(payload),
        key_payload=payload,
    )


def event_snapshot(event):
    return canonical_sha(
        {
            k: str(getattr(event, k) or "")
            for k in (
                "id",
                "year",
                "original_name",
                "country_region",
                "racecourse",
                "local_date",
                "timezone_name",
            )
        }
    )


def observation_context(value, route, now):
    if not isinstance(value, dict):
        raise ValueError("observation_invalid")
    for k in (
        "provider",
        "region",
        "identity_namespace",
        "operator",
        "timezone",
        "parser_version",
    ):
        if value.get(k) != getattr(route, k):
            raise ValueError("observation_route_mismatch")
    if not route.valid(now) or not route.permits_url(value.get("canonical_url", "")):
        raise ValueError("observation_route_invalid")
    require_sha(value.get("raw_sha256"))
    fetched = aware(value.get("fetched_at"))
    if not now - timedelta(hours=24) <= fetched <= now + timedelta(minutes=1):
        raise ValueError("observation_stale")
    if (
        not isinstance(value.get("external_race_id"), str)
        or not 1 <= len(value["external_race_id"]) <= 128
    ):
        raise ValueError("external_identity_missing")
    local_date = date.fromisoformat(value["local_date"])
    if value.get("venue_key") not in route.venue_aliases:
        raise ValueError("venue_unreviewed")
    if not isinstance(value.get("raw_names"), list) or not value["raw_names"]:
        raise ValueError("names_missing")
    return local_date


def _event_context(event, value, route):
    aliases = route.venue_aliases[value["venue_key"]]
    return (
        event.country_region == route.country_region
        and str(event.local_date) == value["local_date"]
        and event.timezone_name == value["timezone"]
        and normalize_name(event.racecourse) in {normalize_name(v) for v in aliases}
    )


@dataclass(frozen=True)
class IdentityMatch:
    status: str
    event_id: int | None = None
    reason: str = ""
    candidates: tuple = ()
    evidence: dict | None = None


def _seed_target(value, route):
    """A0 仅接受从数据库旧证据和新解析页重新构建的收据，不信任传入 event_id。"""
    seed = value.get("identity_seed_receipt")
    if not isinstance(seed, dict):
        return None
    event = models.RaceEvent.objects.filter(pk=seed.get("event_id")).first()
    if not event or seed.get("event_snapshot_sha256") != event_snapshot(event):
        return None
    original = seed_evidence(event, candidate_id=seed.get("candidate_id"))
    if not original or canonical_sha(original) != seed.get("previous_evidence_sha256"):
        return None
    chain = seed.get("link_chain")
    if (
        not isinstance(chain, list)
        or not chain
        or any(not route.permits_url(u) for u in chain)
    ):
        return None
    if chain[0] != original.get("canonical_url") or chain[-1] != value.get(
        "canonical_url"
    ):
        return None
    if (
        seed.get("fresh_raw_sha256") != value["raw_sha256"]
        or seed.get("route_digest") != route.digest
    ):
        return None
    if seed.get("verified_fields") != {
        k: value.get(k)
        for k in ("external_race_id", "local_date", "venue_key", "race_number")
    }:
        return None
    if not _event_context(event, value, route):
        return None
    if value.get("result_phase") and value.get("roster_complete") is not True:
        return None
    if normalize_name(event.original_name) not in {
        normalize_name(n) for n in value["raw_names"]
    }:
        # 已验证旧卡的完整名单同时证明同场；弱别名自身不授予 A0。
        old_roster = original.get("roster", [])
        fresh_roster = value.get("roster", [])
        if not old_roster or sorted(old_roster) != sorted(
            (r.get("number", ""), normalize_name(r.get("horse_name", "")))
            for r in fresh_roster
        ):
            return None
    return event.pk


def seed_evidence(event, *, candidate_id=None, route=None):
    from stable.services.race_pre_race import baseline

    qs = event.data_candidates.filter(module="runners", status="pending")
    if candidate_id is not None:
        qs = qs.filter(pk=candidate_id)
    for candidate in qs.order_by("-fetched_at", "-id")[:10]:
        if route and not route.permits_url(candidate.source_url):
            continue
        for key in ("jra_pre_race_v1", "reviewed_pre_race_v1", "pre_race_refresh_v1"):
            meta = (candidate.raw_payload or {}).get(key, {})
            if meta.get("validated") is not True or meta.get("baseline") != baseline(
                event
            ):
                continue
            try:
                require_sha(meta.get("raw_sha256") or meta.get("source_sha256"))
            except (ValueError, KeyError):
                continue
            items = (candidate.candidate_payload or {}).get("items", [])
            if not items or not all(
                isinstance(r, dict) and r.get("horse_name") for r in items
            ):
                continue
            if (
                meta.get("items_sha256")
                and canonical_sha(items) != meta["items_sha256"]
            ):
                continue
            if meta.get("row_count") is not None and meta["row_count"] != len(items):
                continue
            return dict(
                candidate_id=candidate.pk,
                event_snapshot_sha256=event_snapshot(event),
                raw_sha256=meta.get("raw_sha256") or meta.get("source_sha256"),
                canonical_url=candidate.source_url,
                roster=sorted(
                    (str(r.get("horse_number", "")), normalize_name(r["horse_name"]))
                    for r in items
                ),
            )
    return None


def seed_receipt(event, value, *, route, link_chain, candidate_id=None):
    previous = seed_evidence(event, candidate_id=candidate_id)
    if not previous:
        return None
    return dict(
        event_id=event.pk,
        candidate_id=previous["candidate_id"],
        event_snapshot_sha256=event_snapshot(event),
        previous_evidence_sha256=canonical_sha(previous),
        link_chain=link_chain,
        fresh_raw_sha256=value["raw_sha256"],
        fetched_at=value["fetched_at"],
        route_digest=route.digest,
        matcher_version=MATCHER_VERSION,
        verified_fields={
            k: value.get(k)
            for k in ("external_race_id", "local_date", "venue_key", "race_number")
        },
    )


def resolve_observation(value, *, route, now):
    try:
        day = observation_context(value, route, now)
    except (ValueError, KeyError, TypeError) as exc:
        return IdentityMatch("conflict", reason=str(exc))
    targets = set()
    evidence = {
        "matcher_version": MATCHER_VERSION,
        "raw_sha256": value["raw_sha256"],
        "route_digest": route.digest,
    }
    source = models.RaceResultSourceIdentity.objects.filter(
        source_key=value["provider"],
        region_code=value["region"],
        identity_namespace=value["identity_namespace"],
        external_race_id=value["external_race_id"],
    ).first()
    if source:
        targets.add(source.event_id)
        evidence["source_identity_id"] = source.pk
        previous = source.identity_fields.get("multisource_v2", {})
        if any(
            previous.get(k) and previous[k] != value.get(k)
            for k in (
                "operator",
                "venue_key",
                "local_date",
                "meeting_session",
                "race_number",
            )
        ):
            return IdentityMatch("conflict", reason="source_identity_reused")
    key = identity_key(value)
    if key:
        stored = models.RaceEventIdentityKey.objects.filter(
            namespace=key["namespace"], key_sha256=key["key_sha256"]
        ).first()
        if stored:
            if stored.key_payload != key["key_payload"]:
                return IdentityMatch("conflict", reason="identity_hash_collision")
            targets.add(stored.event_id)
            evidence["identity_key_id"] = stored.pk
    names = {normalize_name(name) for name in value["raw_names"]}
    series_names = (
        models.RaceSeriesName.objects.filter(
            is_active=True,
            series__review_status="approved",
            series__country_region=route.country_region,
            normalized_text__in=names,
        )
        .filter(Q(valid_from_year=0) | Q(valid_from_year__lte=day.year))
        .filter(Q(valid_to_year=0) | Q(valid_to_year__gte=day.year))
    )
    for name in series_names:
        if not name.source_refs:
            continue
        for event in models.RaceEvent.objects.filter(
            race_series_id=name.series_id, edition_year=day.year
        ):
            if _event_context(event, value, route):
                targets.add(event.pk)
                evidence["series_name_id"] = name.pk
    seed = _seed_target(value, route)
    if seed:
        targets.add(seed)
        evidence["identity_seed_receipt"] = value["identity_seed_receipt"]
    if len(targets) > 1:
        return IdentityMatch("conflict", reason="strong_identity_disagreement")
    if targets:
        event = models.RaceEvent.objects.get(pk=next(iter(targets)))
        if not _event_context(event, value, route):
            return IdentityMatch("conflict", reason="identity_context_mismatch")
        if (
            key
            and models.RaceEventIdentityKey.objects.filter(
                event=event, namespace=key["namespace"]
            )
            .exclude(key_sha256=key["key_sha256"])
            .exists()
        ):
            return IdentityMatch(
                "conflict", reason="occurrence_correction_requires_review"
            )
        # 既有人工 canonical 映射不能通过自动绑定创建链或忽略原身份。
        links = list(
            models.RaceEventProductCanonicalLink.objects.filter(
                duplicate_event=event, is_active=True
            )
        )
        if links:
            # 既有 source/key 不能无审计搬迁到另一 event，交由固定修复清单。
            return IdentityMatch(
                "conflict", reason="canonical_identity_transfer_required"
            )
        return IdentityMatch("exact", event.pk, evidence=evidence)
    candidates = list(
        models.RaceEvent.objects.filter(
            country_region=route.country_region,
            local_date__range=(day - timedelta(days=1), day + timedelta(days=1)),
        )[:100]
    )
    names = " ".join(normalize_name(n) for n in value["raw_names"])
    candidates.sort(
        key=lambda e: SequenceMatcher(
            None, names, normalize_name(e.original_name)
        ).ratio(),
        reverse=True,
    )
    return IdentityMatch(
        "review_required" if candidates else "unmatched",
        reason="strong_identity_required",
        candidates=tuple(e.pk for e in candidates[:5]),
        evidence=evidence,
    )


def advisory_identity_locks(value):
    """排序锁减少争用，数据库 UNIQUE 仍是唯一性保障。"""
    if connection.vendor != "postgresql":
        return
    key = identity_key(value)
    identifiers = [
        canonical_sha(
            {
                k: value[k]
                for k in (
                    "provider",
                    "region",
                    "identity_namespace",
                    "external_race_id",
                )
            }
        )
    ]
    if key:
        identifiers.append(key["key_sha256"])
    with connection.cursor() as cursor:
        for digest in sorted(identifiers):
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                [int.from_bytes(bytes.fromhex(digest[:16]), "big", signed=True)],
            )
