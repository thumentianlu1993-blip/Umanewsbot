"""多来源协议与独立于 legacy roster 的版本化准入策略。

策略只能由固定 SHA 文件加载；站点存在或解析器存在均不授予网络权限。
"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from django.conf import settings

KINDS = ("race_time", "racecard", "result")
REGIONS = (
    "japan_jra",
    "japan_nar",
    "hong_kong",
    "united_kingdom",
    "ireland",
    "france",
    "united_states",
)


def canonical_sha(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def aware(value):
    value = (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, str)
        else value
    )
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("aware_timestamp_required")
    return value


def require_sha(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("invalid_sha256")
    return value


@dataclass(frozen=True)
class SourceRoute:
    payload: dict
    digest: str

    def __getattr__(self, key):
        try:
            return self.payload[key]
        except KeyError:
            raise AttributeError(key) from None

    def permits_url(self, url):
        try:
            p = urlsplit(url)
            return (
                p.scheme == "https"
                and not p.username
                and not p.password
                and not p.fragment
                and p.port in (None, 443)
                and p.hostname in self.allowed_hosts
                and not re.search(r"%2f|%5c|%2e|\\|/\.\.", p.path, re.I)
                and any(
                    p.path.startswith(prefix) for prefix in self.allowed_path_prefixes
                )
            )
        except (ValueError, TypeError):
            return False

    def valid(self, now):
        return aware(self.valid_from) <= now < aware(self.valid_until)


@dataclass(frozen=True)
class MultisourcePolicy:
    payload: dict
    digest: str
    routes: tuple

    def route_for(self, observation):
        return next(
            (
                r
                for r in self.routes
                if all(
                    observation.get(k) == getattr(r, k)
                    for k in ("provider", "region", "identity_namespace")
                )
            ),
            None,
        )

    def valid(self, now):
        return (
            aware(self.payload["valid_from"])
            <= now
            < aware(self.payload["valid_until"])
        )


def parse_multisource_policy(value, *, now):
    aware(now)
    if (
        not isinstance(value, dict)
        or set(value)
        != {"schema_version", "policy_id", "valid_from", "valid_until", "routes"}
        or value["schema_version"] != 3
    ):
        raise ValueError("multisource_policy_schema")
    if not value["policy_id"] or not aware(value["valid_from"]) <= now < aware(
        value["valid_until"]
    ):
        raise ValueError("multisource_policy_expired")
    routes = []
    seen = set()
    required = {
        "provider",
        "region",
        "country_region",
        "identity_namespace",
        "operator",
        "source_class",
        "capabilities",
        "allowed_hosts",
        "allowed_path_prefixes",
        "parser_version",
        "contract_digest",
        "proof_digest",
        "terms_sha256",
        "automation_allowed",
        "proof_network_allowed",
        "valid_from",
        "valid_until",
        "tiebreak_order",
        "venue_aliases",
        "timezone",
    }
    if not isinstance(value["routes"], list) or not 1 <= len(value["routes"]) <= 64:
        raise ValueError("multisource_policy_routes")
    for raw in value["routes"]:
        if (
            not isinstance(raw, dict)
            or not required <= set(raw)
            or set(raw) - required - {"discovery_urls"}
        ):
            raise ValueError("multisource_route_schema")
        row = json.loads(json.dumps(raw))
        ZoneInfo(row["timezone"])
        key = tuple(row[k] for k in ("provider", "region", "identity_namespace"))
        if key in seen or row["region"] not in REGIONS:
            raise ValueError("multisource_route_duplicate_or_region")
        seen.add(key)
        for k in ("provider", "identity_namespace", "operator", "parser_version"):
            if not isinstance(row[k], str) or not re.fullmatch(
                r"[a-zA-Z0-9_.:-]{1,64}", row[k]
            ):
                raise ValueError("multisource_route_identifier")
        if (
            row["provider"] == "the_racing_api"
            and row["source_class"] != "licensed_api"
        ):
            raise ValueError("multisource_tra_source_class")
        if row["source_class"] not in (
            "official_operator",
            "licensed_api",
            "trusted_publisher",
        ):
            raise ValueError("multisource_source_class")
        if (
            row["automation_allowed"] is not True
            or row["proof_network_allowed"] is not True
        ):
            raise ValueError("multisource_route_not_approved")
        for k in ("contract_digest", "proof_digest", "terms_sha256"):
            require_sha(row[k])
        if not aware(row["valid_from"]) < aware(row["valid_until"]):
            raise ValueError("multisource_route_validity")
        if not isinstance(row["tiebreak_order"], int) or isinstance(
            row["tiebreak_order"], bool
        ):
            raise ValueError("multisource_route_order")
        if (
            not isinstance(row["capabilities"], list)
            or len(set(row["capabilities"])) != len(row["capabilities"])
            or any(k not in KINDS for k in row["capabilities"])
        ):
            raise ValueError("multisource_capabilities")
        if not row["allowed_hosts"] or any(
            not re.fullmatch(r"[a-z0-9.-]+", x) or "." not in x
            for x in row["allowed_hosts"]
        ):
            raise ValueError("multisource_hosts")
        if not row["allowed_path_prefixes"] or any(
            not x.startswith("/") or x == "/" for x in row["allowed_path_prefixes"]
        ):
            raise ValueError("multisource_paths")
        if (
            not isinstance(row["venue_aliases"], dict)
            or not row["venue_aliases"]
            or any(
                not isinstance(v, list) or not v for v in row["venue_aliases"].values()
            )
        ):
            raise ValueError("multisource_venues")
        row["capabilities"] = sorted(row["capabilities"])
        route = SourceRoute(row, canonical_sha(row))
        urls = row.get("discovery_urls", [])
        if (
            not isinstance(urls, list)
            or len(urls) > 4
            or any(not route.permits_url(u) for u in urls)
        ):
            raise ValueError("multisource_discovery_urls")
        routes.append(route)
    return MultisourcePolicy(
        json.loads(json.dumps(value)), canonical_sha(value), tuple(routes)
    )


def load_multisource_policy(*, now):
    from stable.services.race_data_sync_control import _read_reviewed_json
    from pathlib import Path

    if not Path(
        getattr(settings, "RACE_DATA_MULTISOURCE_POLICY_FILE", "")
    ).is_absolute():
        raise ValueError("multisource_policy_absolute_path_required")
    expected = require_sha(getattr(settings, "RACE_DATA_MULTISOURCE_POLICY_SHA256", ""))
    value, digest = _read_reviewed_json(
        getattr(settings, "RACE_DATA_MULTISOURCE_POLICY_FILE", ""),
        label="multisource_policy",
    )
    if digest != expected:
        raise ValueError("multisource_policy_sha_mismatch")
    return parse_multisource_policy(value, now=now)


_JRA_VENUE_CODES = {
    "01": "札幌",
    "02": "函館",
    "03": "福島",
    "04": "新潟",
    "05": "東京",
    "06": "中山",
    "07": "中京",
    "08": "京都",
    "09": "阪神",
    "10": "小倉",
}


def jra_cname_identity(url):
    """CNAME首组01/10是展示模式；强身份保留其余全部定长赛事字段。"""
    from urllib.parse import parse_qs

    parsed = urlsplit(url)
    values = parse_qs(parsed.query, keep_blank_values=True).get("CNAME", [])
    kind = {"/JRADB/accessD.html": "dde", "/JRADB/accessS.html": "sde"}.get(parsed.path)
    match = (
        re.fullmatch(
            rf"pw01{kind}(\d{{2}})(\d{{2}})(\d{{4}})(\d{{2}})(\d{{2}})(\d{{2}})(\d{{8}})/[A-Fa-f0-9]{{2}}",
            values[0],
        )
        if kind and len(values) == 1
        else None
    )
    if not match or match[1] not in {"01", "10"}:
        raise ValueError("jra_identity_invalid")
    return match


def jra_race_key(url):
    return "".join(jra_cname_identity(url).groups()[1:])


def parse_jra_observation(page, *, url, route, now):
    """从真实 JRADB 页头和 CNAME 一起证明身份，绝不拼造结果 URL 后缀。"""
    from bs4 import BeautifulSoup
    from stable.race_reference_parsers.jra import _parse_barrier
    from datetime import date

    if not route.permits_url(url):
        raise ValueError("source_url_rejected")
    match = jra_cname_identity(url)
    html = str(page)
    if not html.rstrip().lower().endswith("</html>") or "</body>" not in html.lower():
        raise ValueError("document_truncated")
    soup = BeautifulSoup(html, "html.parser")
    headers = soup.select(".race_header")
    if len(headers) != 1:
        raise ValueError("jra_header_invalid")
    header = headers[0]
    text = header.get_text(" ", strip=True)
    day = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    meeting = re.search(r"(\d+)回(.+?)(\d+)日", text)
    number = header.select_one(".race_number img[alt]")
    race_no = re.fullmatch(r"(\d+)レース", number.get("alt", "")) if number else None
    if not day or not meeting or not race_no:
        raise ValueError("jra_header_identity_missing")
    local_date = date(*map(int, day.groups()))
    if (
        local_date.strftime("%Y%m%d") != match[7]
        or local_date.year != int(match[3])
        or _JRA_VENUE_CODES.get(match[2]) != meeting[2].strip()
        or int(race_no[1]) != int(match[6])
        or int(meeting[1]) != int(match[4])
        or int(meeting[3]) != int(match[5])
    ):
        raise ValueError("jra_header_url_disagreement")
    venue = [
        key for key, names in route.venue_aliases.items() if meeting[2].strip() in names
    ]
    if len(venue) != 1:
        raise ValueError("venue_unreviewed")
    title = header.select_one(".race_name")
    if title is None:
        raise ValueError("jra_name_missing")
    raw_sha = getattr(page, "raw_sha256", hashlib.sha256(html.encode()).hexdigest())
    value = dict(
        provider=route.provider,
        region=route.region,
        identity_namespace=route.identity_namespace,
        external_race_id=jra_race_key(url),
        canonical_url=url,
        fetched_at=now.isoformat(),
        raw_sha256=raw_sha,
        parser_version=route.parser_version,
        operator=route.operator,
        venue_key=venue[0],
        local_date=local_date.isoformat(),
        timezone=route.timezone,
        meeting_session=f"{match[4]}-{match[5]}",
        race_number=str(int(race_no[1])),
        raw_names=[title.get_text(" ", strip=True)],
    )
    start = re.search(r"(\d{1,2})時(\d{1,2})分", text)
    if start:
        value["off_time"] = datetime(
            local_date.year,
            local_date.month,
            local_date.day,
            int(start[1]),
            int(start[2]),
            tzinfo=ZoneInfo(route.timezone),
        ).isoformat()
    table = header.find_parent("table")
    rows = []
    is_result = urlsplit(url).path.endswith("accessS.html")
    if not table or not table.select("tbody > tr"):
        raise ValueError("jra_roster_missing")
    for tr in table.select("tbody > tr"):

        def field(selector):
            node = tr.select_one(selector)
            return node.get_text(" ", strip=True) if node else ""

        name = field("td.horse .name") or field("td.horse")
        number = field("td.num")
        if not name or not number.isdigit():
            raise ValueError("jra_roster_partial")
        place = field("td.place")
        status = "declared"
        position = None
        if is_result:
            if place.isdigit():
                position = int(place)
                status = "finished"
            else:
                status = {
                    "取消": "scratched",
                    "除外": "scratched",
                    "中止": "did_not_finish",
                    "失格": "disqualified",
                }.get(place, "unknown")
                if status == "unknown":
                    raise ValueError("jra_result_status_unknown")
        rows.append(
            dict(
                external_runner_id="number:" + number,
                horse_name=name,
                number=number,
                barrier=_parse_barrier(tr.select_one("td.waku")),
                jockey_name=field("td.jockey .jockey") or field("td.jockey"),
                trainer_name=field("td.trainer") or field("td.horse .trainer"),
                carried_weight=field("td.weight") or field("td.jockey .weight"),
                reported_finish_position=position,
                status=status,
                raw_status=place,
                finish_time=field("td.time"),
                margin=field("td.margin"),
                field_provenance={"source_url": url, "raw_sha256": raw_sha},
            )
        )
    if len(rows) > 30 or len({r["number"] for r in rows}) != len(rows):
        raise ValueError("jra_roster_invalid")
    if is_result:
        counts = {
            p: sum(r["reported_finish_position"] == p for r in rows)
            for p in {r["reported_finish_position"] for r in rows}
            if p
        }
        for row in rows:
            if counts.get(row["reported_finish_position"], 0) > 1:
                row["status"] = "dead_heat"
        # Complete server-rendered result table with every terminal row, not a winner summary.
        if not soup.select("th") or not any(
            r["reported_finish_position"] == 1 for r in rows
        ):
            raise ValueError("jra_result_incomplete")
    value.update(
        roster=rows,
        result_phase="official" if is_result else "",
        roster_complete=not is_result,
    )
    return value


def jra_result_links(page, *, url, route):
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    soup = BeautifulSoup(str(page), "html.parser")
    links = []
    for a in soup.select("a"):
        link = urljoin(url, a.get("href", ""))
        action = re.search(
            r"doAction\('([^']+)'\s*,\s*'([^']+)'\)", a.get("onclick", "")
        )
        if action:
            link = urljoin(url, action[1]) + "?CNAME=" + action[2]
        if (
            urlsplit(link).path.endswith("accessS.html")
            and route.permits_url(link)
            and link not in links
        ):
            links.append(link)
    return links


def fetch_source_page(url, *, route, now):
    from stable.services.race_pre_race import _fetch_bounded_html

    def enabled():
        return (
            (
                getattr(settings, "RACE_DATA_MULTISOURCE_APPLY_ENABLED", False)
                or getattr(settings, "RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED", False)
            )
            and settings.RACE_DATA_SYNC_ENABLED
            and settings.RACE_DATA_SYNC_ALLOW_NETWORK
            and route.provider in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
            and route.region in settings.RACE_DATA_SYNC_ENABLED_REGIONS
            and route.valid(__import__("django.utils.timezone", fromlist=["now"]).now())
        )

    def validate(value):
        if not route.permits_url(value):
            raise ValueError("source_url_rejected")

    return _fetch_bounded_html(
        url,
        now=now,
        provider=route.provider,
        region=route.region,
        validator=validate,
        enabled=enabled,
    )


def binding_roster(*, binding, route):
    """给既有字段/结果 writer 提供同形只读合同，不修改 legacy roster。"""
    from types import SimpleNamespace

    entry = SimpleNamespace(
        provider=route.provider,
        regions=(route.region,),
        identity_namespaces=(route.identity_namespace,),
        data_kinds=tuple(route.capabilities),
        source_class=route.source_class,
        contract_version=route.parser_version,
        contract_digest=route.contract_digest,
        terminal_markers=("complete",),
        adapter_status="implemented",
        transport_enabled=True,
        apply_enabled=True,
    )
    return SimpleNamespace(registry_digest=route.digest, entries=(entry,)), entry


def claim_binding(claim, *, now):
    from stable import models

    authority = claim.checkpoint_plan[0]["authority"]
    binding = models.RaceDataSyncSourceBinding.objects.select_related(
        "source_identity"
    ).get(pk=authority["binding_id"])
    policy = load_multisource_policy(now=now)
    source = binding.source_identity
    route = policy.route_for(
        dict(
            provider=source.source_key,
            region=source.region_code,
            identity_namespace=source.identity_namespace,
        )
    )
    if route is None or route.digest != binding.route_digest:
        raise ValueError("binding_route_missing")
    return binding, route


def publication_authority(*, binding, enrollment):
    return dict(
        binding_manifest=binding.binding_manifest,
        binding_manifest_sha256=binding.binding_manifest_sha256,
        source_set_manifest=enrollment.source_set_manifest,
        source_set_digest=enrollment.source_set_digest,
    )


def fetch_bound_observation(*, event, route, now, fetcher=None, kind="result"):
    """从受审旧卡或来源身份开始；seed和结果都重新核验当前页，事务外取数。"""
    from stable.services.race_source_identity import seed_evidence, seed_receipt

    source = event.source_identities.filter(
        source_key=route.provider,
        region_code=route.region,
        identity_namespace=route.identity_namespace,
    ).first()
    previous = seed_evidence(event, route=route)
    if route.provider == "the_racing_api":
        value = fetch_tra_observation(
            event=event, route=route, now=now, kind=kind, fetcher=fetcher
        )
        chain = [value["canonical_url"]]
    else:
        url = (
            source.canonical_url
            if source
            else previous["canonical_url"] if previous else ""
        )
        fetcher = fetcher or fetch_source_page
        if not url:
            url = discover_source_url(
                event=event, route=route, now=now, fetcher=fetcher
            )
        if not route.permits_url(url):
            raise ValueError("source_url_rejected")
        page = fetcher(url, route=route, now=now)
        chain = [url]
        if route.provider == "jra":
            value = parse_jra_observation(page, url=url, route=route, now=now)
            if kind == "result" and not value.get("result_phase"):
                links = jra_result_links(page, url=url, route=route)
                # 对每个真实链接解析完整赛事键，忽略展示模式但不忽略任一赛事字段。
                card_id = jra_race_key(url)
                matched = []
                for link in links:
                    try:
                        if jra_race_key(link) == card_id:
                            matched.append(link)
                    except ValueError:
                        continue
                links = matched
                if len(links) == 1:
                    url = links[0]
                    chain.append(url)
                    page = fetcher(url, route=route, now=now)
                    result = parse_jra_observation(page, url=url, route=route, now=now)
                    if result["external_race_id"] != value["external_race_id"]:
                        raise ValueError("linked_result_identity_mismatch")
                    value = result
        elif route.provider == "nar":
            linked = (
                linked_result_url(page, url=url, route=route)
                if kind == "result"
                else ""
            )
            if linked:
                url = linked
                chain.append(url)
                page = fetcher(url, route=route, now=now)
            value = parse_nar_observation(page, url=url, route=route, now=now)
        elif route.provider == "hkjc":
            value = parse_hkjc_observation(page, url=url, route=route, now=now)
        else:
            linked = (
                linked_result_url(page, url=url, route=route)
                if kind == "result"
                else ""
            )
            if linked:
                url = linked
                chain.append(url)
                page = fetcher(url, route=route, now=now)
            value = parse_reference_observation(
                page, url=url, route=route, now=now, event=event
            )
    if value.get("result_phase"):
        # 无正式名单时，完整性必须有独立的已核验参赛集合；结果表自身不能证明没有漏掉最后一行。
        from stable.services.race_source_identity import normalize_name

        expected = previous.get("roster", []) if previous else []
        if not expected and event.runners.exists():
            expected = [
                (r.horse_number, normalize_name(r.horse_name))
                for r in event.runners.all()
            ]
        actual = [
            (r["number"], normalize_name(r["horse_name"]))
            for r in value.get("roster", [])
        ]
        value["roster_complete"] = bool(
            expected
            and (
                sorted(expected) == sorted(actual)
                or (
                    source is not None
                    and event.runners.exists()
                    and sorted(n for n, _ in expected) == sorted(n for n, _ in actual)
                )
            )
        )
    if previous and not source:
        value["identity_seed_receipt"] = seed_receipt(
            event,
            value,
            route=route,
            link_chain=chain,
            candidate_id=previous["candidate_id"],
        )
    return value


def parse_reference_observation(page, *, url, route, now, event=None):
    """已存在参考解析器的统一身份入口；partial 永远不提升为正式结果。"""
    from stable.race_reference_parsers import sporting_life, zeturf, horse_racing_nation
    from stable.services.race_source_identity import normalize_name

    parsers = {
        "sporting_life": sporting_life,
        "zeturf": zeturf,
        "horse_racing_nation": horse_racing_nation,
    }
    parser = parsers.get(route.provider)
    if parser is None:
        raise ValueError("source_parser_proof_required")
    if route.provider == "sporting_life" and "/racecard/" in urlsplit(url).path:
        return parse_sporting_card_observation(
            page, url=url, route=route, now=now, event=event
        )
    match = parser._URL_RE.fullmatch(urlsplit(url).path)
    if not route.permits_url(url) or match is None:
        raise ValueError("source_url_rejected")
    if route.provider == "sporting_life":
        context = {"race_id": int(match["race_id"])}
    elif route.provider == "zeturf":
        if re.search(
            r"\b(trot|attelé|attel[eé]|mont[eé])\b",
            (
                __import__("bs4")
                .BeautifulSoup(str(page), "html.parser")
                .title.get_text()
                if __import__("bs4").BeautifulSoup(str(page), "html.parser").title
                else ""
            ),
            re.I,
        ):
            raise ValueError("unsupported_race_type")
        context = dict(
            local_date=match["date"],
            meeting=int(match["meeting"]),
            race=int(match["race"]),
        )
    else:
        if event is None:
            raise ValueError("hrn_race_context_required")
        races = parser._parse_track_day(str(page), source_url=url)
        names = {
            normalize_name(event.original_name),
            normalize_name(event.chinese_name),
        }
        candidates = [
            r for r in races if normalize_name(r.get("race_title", "")) in names
        ]
        existing = event.source_identities.filter(
            source_key=route.provider, region_code=route.region
        ).first()
        if existing:
            old = existing.identity_fields.get("multisource_v2", {})
            candidates = [
                r for r in races if str(r.get("race_no")) == old.get("race_number")
            ]
        if len(candidates) != 1:
            raise ValueError("hrn_race_context_ambiguous")
        context = dict(
            track_slug=match["track"],
            local_date=match["date"],
            race=int(candidates[0]["race_no"]),
        )
    semantic = parser.parse_reference_page(str(page).encode(), url, context)
    race = semantic["race"]
    venues = [
        key
        for key, names in route.venue_aliases.items()
        if normalize_name(race["source_racecourse"])
        in {normalize_name(n) for n in names}
    ]
    if len(venues) != 1:
        raise ValueError("venue_unreviewed")
    phase = "official" if semantic["completeness"]["results"] == "complete" else ""
    rows = []
    positions = {}
    for row in semantic["runners"]:
        raw = row["source_reported_finish_position"]
        pos = int(raw) if raw.isdigit() else None
        if pos:
            positions[pos] = positions.get(pos, 0) + 1
        status = (
            "finished"
            if pos
            else {"withdrawn": "withdrawn", "declared": "unknown"}.get(
                row["running_status"], row["running_status"]
            )
        )
        rows.append(
            dict(
                external_runner_id=row["source_runner_key"],
                horse_name=row["horse_name"],
                number=row["horse_number"],
                barrier=row["draw"],
                jockey_name=row["jockey_name"],
                trainer_name=row["trainer_name"],
                carried_weight=row["carried_weight"],
                reported_finish_position=pos,
                status=status,
                raw_status=row["running_status"],
                margin=row["margin"],
                finish_time="",
                field_provenance={},
            )
        )
    for row in rows:
        if positions.get(row["reported_finish_position"], 0) > 1:
            row["status"] = "dead_heat"
    # Complete ordering alone is not an official source phase: require explicit source marker.
    if route.provider == "sporting_life":
        summary = (
            parser._next_data(str(page))
            .get("props", {})
            .get("pageProps", {})
            .get("race", {})
            .get("race_summary", {})
        )
        if str(summary.get("race_stage", "")).lower() not in (
            "result",
            "results",
            "weighedin",
            "weighed_in",
        ):
            phase = ""
    elif route.provider == "horse_racing_nation":
        phase = ""  # 现有 payout+also-rans 合同明确 partial，不冒充完整名次。
    elif not re.search(r"arriv[eé]e\s+(?:officielle|d[eé]finitive)", str(page), re.I):
        phase = ""
    return dict(
        provider=route.provider,
        region=route.region,
        identity_namespace=route.identity_namespace,
        external_race_id=semantic["provider_event_key"],
        canonical_url=url,
        fetched_at=now.isoformat(),
        raw_sha256=getattr(
            page, "raw_sha256", hashlib.sha256(str(page).encode()).hexdigest()
        ),
        parser_version=route.parser_version,
        operator=route.operator,
        venue_key=venues[0],
        local_date=race["local_date"],
        timezone=route.timezone,
        meeting_session=str(context.get("meeting", "")),
        race_number=str(context.get("race", "")),
        raw_names=[race["source_race_name"]],
        roster=rows,
        result_phase=phase,
        roster_complete=semantic["completeness"]["runners"] == "complete",
    )


def run_multisource_claim(*, claim, now, fetcher=None):
    """共享 Celery 入口；网络外采，末端 writer 锁内重新核验同一 claim。"""
    from django.db import transaction
    from django.utils import timezone
    from stable.services.race_data_sync_control import (
        lock_and_validate_race_data_sync_claim_for_apply,
        finish_multisource_claim,
    )
    from stable.services.race_events import record_race_result_observation
    from stable.services.race_data_sync_results import (
        apply_data_sync_result_observation,
    )

    with transaction.atomic():
        decision, locked = lock_and_validate_race_data_sync_claim_for_apply(
            claim=claim, now=now
        )
    if locked is None:
        return {"processed": False, "reason": decision.reason_code}
    if not settings.RACE_DATA_SYNC_ALLOW_NETWORK:
        return {"processed": False, "reason": "network_disabled"}
    binding, route = claim_binding(claim, now=now)
    try:
        value = fetch_bound_observation(
            event=locked.event,
            route=route,
            now=now,
            fetcher=fetcher,
            kind="result" if "result" in claim.data_kinds else "racecard",
        )
        from stable.services.race_source_identity import resolve_observation

        match = resolve_observation(value, route=route, now=now)
        if match.status != "exact" or match.event_id != claim.event_id:
            raise ValueError("identity_conflict")
        if value["external_race_id"] != binding.source_identity.external_race_id:
            raise ValueError("source_identity_changed")
        applied = []
        hashes = {}
        provenance = dict(
            provider=route.provider,
            region=route.region,
            source_class=route.source_class,
            source_url=value["canonical_url"],
            registry_digest=route.digest,
            contract_version=route.parser_version,
            contract_digest=route.contract_digest,
            automation_allowed=True,
            roster_complete=value.get("roster_complete") is True,
            # corrected 只由受审 parser 的明确 amended/corrected/revised 标记产生。
            correction_marker=value.get("result_phase") == "corrected",
            multisource_authority=publication_authority(
                binding=binding, enrollment=locked.enrollment
            ),
        )
        if "result" in claim.data_kinds:
            for row in value["roster"]:
                row["field_provenance"] = {
                    **row.get("field_provenance", {}),
                    "multisource_source_set_digest": locked.enrollment.source_set_digest,
                }
            if value.get("result_phase") not in (
                "official",
                "corrected",
            ) or not value.get("roster_complete"):
                raise ValueError("not_published")
            payload = dict(
                external_race_id=value["external_race_id"],
                off_time=value.get("off_time", ""),
                region=route.region,
                course=value["venue_key"],
                race_name=value["raw_names"][0],
                race_status="complete",
                participants=value["roster"],
            )
            recorded = record_race_result_observation(
                source_identity_id=binding.source_identity_id,
                observed_at=now,
                source_updated_at=None,
                parser_version=route.parser_version,
                raw_sha256=value["raw_sha256"],
                result_phase=value["result_phase"],
                normalized_payload=payload,
                field_provenance=provenance,
                parse_warnings=[],
                permission_classification="multisource_approved",
            )
            if recorded.observation is None:
                raise ValueError("observation_rejected")
            projected = apply_data_sync_result_observation(
                observation_id=recorded.observation.pk,
                expected_event_id=claim.event_id,
                now=timezone.now(),
                project_current=bool(
                    settings.RACE_DATA_SYNC_RESULT_APPLY_ENABLED
                    and settings.RACE_DATA_SYNC_RESULT_PUBLIC_ENABLED
                ),
                correction_apply_enabled=settings.RACE_DATA_SYNC_CORRECTION_APPLY_ENABLED,
                claim_guard=claim,
            )
            if projected.action not in ("applied", "replayed"):
                raise ValueError(projected.reason_code or "result_not_applied")
            applied.append("result")
            hashes["result"] = value["raw_sha256"]
        # Schedule/card uses the existing audited writer, with exact capabilities from the claim.
        remaining = set(claim.data_kinds) - {"result"}
        if remaining:
            from stable.services.race_data_sync_pipeline import (
                normalize_racecard_observation,
                reconcile_racecard_observation,
                _ROSTER_ALLOWED_FIELDS,
            )

            card = dict(
                multisource_source_set_digest=locked.enrollment.source_set_digest,
                schema_version=1,
                external_race_id=value["external_race_id"],
                off_time=value.get("off_time", ""),
                region=route.region,
                course=value["venue_key"],
                race_name=value["raw_names"][0],
                race_status=locked.event.status,
                participants=[
                    dict(
                        external_runner_id=r["external_runner_id"],
                        horse_name=r["horse_name"],
                        number=r["number"],
                        draw=r["barrier"],
                        jockey_name=r["jockey_name"],
                        trainer_name=r["trainer_name"],
                        carried_weight=r["carried_weight"],
                        **(
                            {
                                "status": (
                                    "scratched"
                                    if r["status"]
                                    in ("scratched", "withdrawn", "non_runner")
                                    else "declared"
                                )
                            }
                            if r.get("status_reported", True)
                            else {}
                        ),
                    )
                    for r in value["roster"]
                ],
            )
            normalized = normalize_racecard_observation(
                payload=card,
                contract={
                    "schema_version": 1,
                    "data_kind": "racecard",
                    "provider": route.provider,
                    "region": route.region,
                    "source_class": route.source_class,
                    "registry_digest": route.digest,
                    "contract_version": route.parser_version,
                    "contract_digest": route.contract_digest,
                    "automation_allowed": True,
                    "allowed_fields": list(_ROSTER_ALLOWED_FIELDS),
                },
                observed_at=now,
                source_updated_at=None,
                parser_version=route.parser_version,
                raw_sha256=value["raw_sha256"],
                source_url=value["canonical_url"],
                task_id=claim.attempt_token,
                run_id=claim.attempt_token,
            )
            recorded = record_race_result_observation(
                source_identity_id=binding.source_identity_id,
                observed_at=now,
                source_updated_at=None,
                parser_version=route.parser_version,
                raw_sha256=value["raw_sha256"],
                result_phase="racecard",
                normalized_payload=normalized.normalized_payload,
                field_provenance={
                    **{
                        k: v.isoformat() if isinstance(v, datetime) else v
                        for k, v in normalized.provenance.items()
                    },
                    **provenance,
                },
                parse_warnings=[],
                permission_classification="multisource_approved",
            )
            result = reconcile_racecard_observation(
                observation_id=recorded.observation.pk,
                expected_event_id=claim.event_id,
                allow_schedule_apply="race_time" in remaining
                and settings.RACE_DATA_SYNC_SCHEDULE_APPLY_ENABLED,
                allow_racecard_apply="racecard" in remaining
                and settings.RACE_DATA_SYNC_RACECARD_APPLY_ENABLED,
                task_id=claim.attempt_token,
                run_id=claim.attempt_token,
                claim_guard=claim,
            )
            if result.status not in ("applied", "replayed"):
                raise ValueError(result.reason or "racecard_not_applied")
            for kind in remaining:
                applied.append(kind)
                hashes[kind] = value["raw_sha256"]
            if result.claim_invalidated:
                return {
                    "processed": True,
                    "reason": "schedule_claim_invalidated",
                    "applied_kinds": applied,
                }
        decision = finish_multisource_claim(
            claim=claim, now=timezone.now(), success=True, observation_hashes=hashes
        )
        return {
            "processed": decision.action == "complete",
            "reason": decision.reason_code,
            "applied_kinds": applied,
        }
    except (ValueError, RuntimeError, OSError) as exc:
        reason = str(exc)
        if not re.fullmatch("[a-z0-9_-]{1,64}", reason):
            reason = "source_parse_failed"
        decision = finish_multisource_claim(
            claim=claim,
            now=timezone.now(),
            success=False,
            reason_code=reason,
            retry_at=getattr(exc, "retry_after", None),
        )
        return {"processed": False, "reason": reason, "claim_action": decision.action}


def parse_nar_observation(page, *, url, route, now):
    from urllib.parse import parse_qs
    from datetime import date
    from bs4 import BeautifulSoup
    from types import SimpleNamespace
    from stable.services.race_pre_race_sources import _nar
    from stable.services.race_source_identity import normalize_name

    if (
        not route.permits_url(url)
        or route.operator != "nar"
        or route.region != "japan_nar"
    ):
        raise ValueError("nar_route_mismatch")
    params = parse_qs(urlsplit(url).query)
    try:
        day = datetime.strptime(params["k_raceDate"][0], "%Y/%m/%d").date()
        race_no = str(int(params["k_raceNo"][0]))
        baba = str(int(params["k_babaCode"][0]))
    except (KeyError, ValueError, IndexError):
        raise ValueError("nar_identity_missing") from None
    soup = BeautifulSoup(str(page), "html.parser")
    text = soup.get_text(" ", strip=True)
    header = re.search(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日（.）\s*(.+?)\s*第(\d+)競走", text
    )
    if (
        not header
        or date(*map(int, header.groups()[:3])) != day
        or str(int(header[5])) != race_no
    ):
        raise ValueError("nar_identity_mismatch")
    venues = [
        key
        for key, names in route.venue_aliases.items()
        if normalize_name(header[4]).replace(" ", "")
        in {normalize_name(n).replace(" ", "") for n in names}
    ]
    if len(venues) != 1:
        raise ValueError("venue_unreviewed")
    # Course-code crosswalk is explicit in policy key; do not infer JRA/NAR from names.
    if venues[0] != f"nar:{baba}":
        raise ValueError("nar_course_code_mismatch")
    title = soup.select_one(".raceName, .race_name, h2")
    if title is None:
        raise ValueError("nar_name_missing")
    is_result = urlsplit(url).path.endswith("RaceMarkTable")
    rows = []
    if is_result:
        table = soup.select_one("section.gradeTable table")
        if not table:
            raise ValueError("not_published")
        for tr in table.select("tr.tBorder"):
            cells = [
                c.get_text(" ", strip=True)
                for c in tr.find_all(["td", "th"], recursive=False)
            ]
            if len(cells) < 16:
                raise ValueError("nar_result_partial")
            place = cells[0]
            pos = int(place) if place.isdigit() else None
            status = (
                "finished"
                if pos
                else {
                    "取消": "withdrawn",
                    "出走取消": "withdrawn",
                    "除外": "scratched",
                    "競走除外": "scratched",
                    "中止": "did_not_finish",
                    "失格": "disqualified",
                }.get(place, "unknown")
            )
            rows.append(
                dict(
                    external_runner_id="number:" + cells[2],
                    number=cells[2],
                    horse_name=cells[3],
                    barrier=cells[1],
                    jockey_name=cells[7],
                    trainer_name=cells[8],
                    carried_weight=cells[6],
                    reported_finish_position=pos,
                    status=status,
                    raw_status=place,
                    finish_time=cells[10],
                    margin=cells[11],
                    field_provenance={},
                )
            )
    else:
        items = _nar(
            soup,
            SimpleNamespace(
                local_date=day,
                timezone_name=route.timezone,
                racecourse=header[4].replace(" ", ""),
            ),
            url,
        )
        rows = [
            dict(
                external_runner_id="number:" + r["horse_number"],
                number=r["horse_number"],
                horse_name=r["horse_name"],
                barrier=r["barrier"],
                jockey_name=r["jockey_name"],
                trainer_name=r["trainer_name"],
                carried_weight=r["carried_weight"],
                reported_finish_position=None,
                status=r["running_status"],
                raw_status="",
                finish_time="",
                margin="",
                field_provenance={},
            )
            for r in items
        ]
    if (
        not rows
        or len(rows) > 30
        or any(
            not r["number"].isdigit() or not r["horse_name"] or r["status"] == "unknown"
            for r in rows
        )
        or len({r["number"] for r in rows}) != len(rows)
    ):
        raise ValueError("nar_roster_invalid")
    for row in rows:
        if (
            row["reported_finish_position"]
            and sum(
                r["reported_finish_position"] == row["reported_finish_position"]
                for r in rows
            )
            > 1
        ):
            row["status"] = "dead_heat"
    value = dict(
        provider=route.provider,
        region=route.region,
        identity_namespace=route.identity_namespace,
        external_race_id=f"nar:{day.isoformat()}:{baba}:{race_no}",
        canonical_url=url,
        fetched_at=now.isoformat(),
        raw_sha256=getattr(
            page, "raw_sha256", hashlib.sha256(str(page).encode()).hexdigest()
        ),
        parser_version=route.parser_version,
        operator="nar",
        venue_key=venues[0],
        local_date=day.isoformat(),
        timezone=route.timezone,
        meeting_session="single",
        race_number=race_no,
        raw_names=[title.get_text(" ", strip=True)],
        roster=rows,
        result_phase="official" if is_result else "",
        roster_complete=True,
    )
    start = re.search(r"(\d{1,2}):(\d{2})\s*発走", text)
    if start:
        value["off_time"] = datetime(
            day.year,
            day.month,
            day.day,
            int(start[1]),
            int(start[2]),
            tzinfo=ZoneInfo(route.timezone),
        ).isoformat()
    return value


def parse_hkjc_observation(page, *, url, route, now):
    from urllib.parse import parse_qs
    from bs4 import BeautifulSoup
    from stable.services.external_hkjc_data import HKJCHTMLParser
    from stable.services.race_source_identity import normalize_name

    if not route.permits_url(url) or route.region != "hong_kong":
        raise ValueError("hkjc_route_mismatch")
    params = {k.lower(): v for k, v in parse_qs(urlsplit(url).query).items()}
    try:
        day = datetime.strptime(
            params["racedate"][0].replace("/", "-"), "%Y-%m-%d"
        ).date()
        course = params["racecourse"][0].upper()
        number = str(int(params["raceno"][0]))
    except (KeyError, IndexError, ValueError):
        raise ValueError("hkjc_identity_missing") from None
    soup = BeautifulSoup(str(page), "html.parser")
    text = soup.get_text(" ", strip=True)
    if not re.search(r"\bRACE\s+" + re.escape(number) + r"\b", text, re.I) or not any(
        v in text
        for v in (day.strftime("%d/%m/%Y"), day.strftime("%Y/%m/%d"), day.isoformat())
    ):
        raise ValueError("hkjc_page_identity_missing")
    parsed = HKJCHTMLParser().parse_race_result(
        str(page),
        race_date=day.isoformat(),
        racecourse=course,
        race_no=number,
        source_url=url,
    )
    venues = [
        key
        for key, names in route.venue_aliases.items()
        if normalize_name(parsed["venue"]) in {normalize_name(n) for n in names}
    ]
    if len(venues) != 1 or venues[0] != f"hkjc:{course}":
        raise ValueError("hkjc_course_mismatch")
    # Count actual rows, not only parser-accepted rows; partial result tables fail closed.
    tables = [
        t
        for t in soup.select("table")
        if "Pla." in t.get_text() and "Horse No." in t.get_text()
    ]
    if len(tables) != 1 or len(tables[0].select("tr")) - 1 != len(parsed["results"]):
        raise ValueError("hkjc_result_partial")
    rows = []
    for r in parsed["results"]:
        raw = r["finish_position"]
        pos = int(raw) if str(raw).isdigit() else None
        status = (
            "finished"
            if pos
            else {
                "WV": "withdrawn",
                "PU": "pulled_up",
                "UR": "unseated_rider",
                "DISQ": "disqualified",
                "DNF": "did_not_finish",
            }.get(raw, "unknown")
        )
        if status == "unknown":
            raise ValueError("hkjc_status_unknown")
        rows.append(
            dict(
                external_runner_id=r["horse_id"] or "number:" + r["horse_number"],
                number=r["horse_number"],
                horse_name=r["horse_name_en"],
                barrier=r["barrier"],
                jockey_name=r["jockey"],
                trainer_name=r["trainer"],
                carried_weight=r["weight"],
                reported_finish_position=pos,
                status=status,
                raw_status=raw,
                finish_time=r["finish_time"],
                margin=r["margin"],
                field_provenance={},
            )
        )
    if not rows or len({r["number"] for r in rows}) != len(rows):
        raise ValueError("hkjc_roster_invalid")
    for row in rows:
        if (
            row["reported_finish_position"]
            and sum(
                r["reported_finish_position"] == row["reported_finish_position"]
                for r in rows
            )
            > 1
        ):
            row["status"] = "dead_heat"
    return dict(
        provider=route.provider,
        region=route.region,
        identity_namespace=route.identity_namespace,
        external_race_id=parsed["race_id"],
        canonical_url=url,
        fetched_at=now.isoformat(),
        raw_sha256=getattr(
            page, "raw_sha256", hashlib.sha256(str(page).encode()).hexdigest()
        ),
        parser_version=route.parser_version,
        operator=route.operator,
        venue_key=venues[0],
        local_date=day.isoformat(),
        timezone=route.timezone,
        meeting_session="single",
        race_number=number,
        raw_names=[parsed["race_name"]],
        roster=rows,
        result_phase="official",
        roster_complete=True,
    )


def parse_sporting_card_observation(page, *, url, route, now, event):
    from stable.services.race_pre_race_sources import parse_bound_card
    from stable.race_reference_parsers.sporting_life import _next_data
    from stable.services.race_source_identity import normalize_name

    if event is None or not route.permits_url(url):
        raise ValueError("source_url_rejected")
    summary = _next_data(str(page))["props"]["pageProps"]["race"]["race_summary"]
    rows = parse_bound_card(str(page), event=event, url=url)["items"]
    course_value = summary.get("course") or {}
    course = summary.get("course_name") or (
        course_value.get("name") or course_value.get("display_name")
        if isinstance(course_value, dict)
        else str(course_value)
    )
    # Racecard path supplies the venue slug; page/date/race-ID remain validated by the existing parser.
    match = re.search(
        r"/racing/racecards/(\d{4}-\d{2}-\d{2})/([^/]+)/racecard/(\d+)/",
        urlsplit(url).path,
    )
    if not match:
        raise ValueError("sporting_card_identity_missing")
    venues = [
        key
        for key, names in route.venue_aliases.items()
        if normalize_name(course or match[2]).replace("-", " ")
        in {normalize_name(n).replace("-", " ") for n in names}
    ]
    if len(venues) != 1:
        raise ValueError("venue_unreviewed")
    roster = [
        dict(
            external_runner_id=str(
                r.get("source_refs", {}).get("horse_id")
                or "number:" + r["horse_number"]
            ),
            horse_name=r["horse_name"],
            number=r["horse_number"],
            barrier=r["barrier"],
            jockey_name=r["jockey_name"],
            trainer_name=r["trainer_name"],
            carried_weight=r["carried_weight"],
            reported_finish_position=None,
            status=r["running_status"],
            raw_status="",
            finish_time="",
            margin="",
            field_provenance={},
        )
        for r in rows
    ]
    value = dict(
        provider=route.provider,
        region=route.region,
        identity_namespace=route.identity_namespace,
        external_race_id=f"sl:{int(match[3])}",
        canonical_url=url,
        fetched_at=now.isoformat(),
        raw_sha256=getattr(
            page, "raw_sha256", hashlib.sha256(str(page).encode()).hexdigest()
        ),
        parser_version=route.parser_version,
        operator=route.operator,
        venue_key=venues[0],
        local_date=match[1],
        timezone=route.timezone,
        meeting_session="",
        race_number="",
        raw_names=[summary.get("name") or ""],
        roster=roster,
        result_phase="",
        roster_complete=True,
    )
    # Only explicit ISO instant with zone can populate off_time; date/clock strings alone cannot.
    raw = summary.get("start_time") or summary.get("off_time")
    try:
        instant = aware(raw)
        if instant.astimezone(ZoneInfo(route.timezone)).date().isoformat() == match[1]:
            value["off_time"] = instant.isoformat()
    except (TypeError, ValueError):
        pass
    return value


def discover_source_url(*, event, route, now, fetcher):
    """独立来源发现：旧 URL 仅作取数提示，不能据此自动授予赛事身份。

    列表只读策略审核过的精确 URL；名称仅选择至多一个详情请求，后续
    resolve_observation 仍须 A/B/C 强证据。无分页完成证明不宣称全站覆盖。
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    from stable.services.race_source_identity import normalize_name

    refs = event.source_refs if isinstance(event.source_refs, dict) else {}
    references = refs.get("reference_urls", [])
    hints = [refs.get("primary", "")] + (
        references if isinstance(references, list) else []
    )
    urls = [u for u in hints if isinstance(u, str) and route.permits_url(u)]
    if len(set(urls)) == 1:
        return urls[0]
    names = {normalize_name(n) for n in (event.original_name, event.chinese_name) if n}
    indexes = route.payload.get("discovery_urls", [])
    if not indexes:
        raise ValueError("source_identity_missing")
    # Rotate a fixed bounded list with local date; no constructed source endpoints.
    url = indexes[event.local_date.toordinal() % len(indexes)]
    page = fetcher(url, route=route, now=now)
    candidates = set()
    for link in BeautifulSoup(str(page), "html.parser").select("a[href]"):
        target = urljoin(url, link.get("href", ""))
        if (
            normalize_name(link.get_text(" ", strip=True)) in names
            and route.permits_url(target)
            and target != url
        ):
            candidates.add(target)
    if len(candidates) != 1:
        raise ValueError(
            "source_discovery_ambiguous" if candidates else "source_not_found"
        )
    return candidates.pop()


def fetch_tra_observation(*, event, route, now, kind, fetcher=None):
    """TRA 与其他来源同等进入身份解析；沿用既有凭据、许可、预算和免费窗口。"""
    import time
    from django.utils import timezone
    from stable.services.race_data_sync_providers import (
        _fetch_json,
        _get_or_fetch_shared_snapshot,
        _registry_region,
        _result_payload,
        _ProviderSyncError,
    )
    from stable.services.race_live_source_proof import (
        read_the_racing_api_automation_registry,
        build_the_racing_api_route_url,
        _read_secret,
        the_racing_api_transport,
    )
    from stable.services.race_live_fixtures import (
        parse_the_racing_api_live_racecards_payload,
        parse_the_racing_api_live_results_payload,
    )
    from stable.services.race_source_identity import normalize_name

    source = event.source_identities.filter(
        source_key=route.provider,
        region_code=route.region,
        identity_namespace=route.identity_namespace,
    ).first()
    registry, _ = read_the_racing_api_automation_registry(
        registry_file=settings.RACE_LIVE_TRA_REGISTRY_FILE,
        expected_registry_sha256=route.proof_digest,
        now=now,
    )
    region = _registry_region(
        event_region=event.country_region, contract_region=route.region
    )
    offset = (event.local_date - now.astimezone(ZoneInfo(route.timezone)).date()).days
    result = kind == "result" and offset <= 0
    if result and source:
        name = "result_by_id"
        params = dict(race_id=source.external_race_id, limit=0, skip=0)
    elif result and offset == 0:
        name = "results_today_free"
        params = dict(limit=50, skip=0)
    elif offset in (0, 1):
        name = "racecards_free"
        params = dict(day="today" if offset == 0 else "tomorrow", limit=500, skip=0)
        result = False
    else:
        raise ValueError("awaiting_source_window")
    url = build_the_racing_api_route_url(
        registry=registry, route_name=name, region=region, **params
    )
    if not route.permits_url(url):
        raise ValueError("source_url_rejected")
    if fetcher:
        response = fetcher(url, route=route, now=now)
        payload = json.loads(response) if isinstance(response, str) else response
        raw_sha = canonical_sha(payload)
    else:
        username, password = _read_secret(settings.RACE_LIVE_TRA_SECRET_ENV_FILE)

        def fetch():
            current = timezone.now()
            if (
                not (
                    settings.RACE_DATA_MULTISOURCE_APPLY_ENABLED
                    or settings.RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED
                )
                or not settings.RACE_DATA_SYNC_ENABLED
                or not settings.RACE_DATA_SYNC_ALLOW_NETWORK
                or not route.valid(current)
                or route.provider not in settings.RACE_DATA_SYNC_ENABLED_PROVIDERS
                or route.region not in settings.RACE_DATA_SYNC_ENABLED_REGIONS
            ):
                raise ValueError("network_disabled")
            from stable.services.race_events import ensure_race_live_host_budget_floor

            ensure_race_live_host_budget_floor(
                host="api.theracingapi.com", minimum_interval_ms=2000
            )
            body, sha = _fetch_json(
                transport=the_racing_api_transport,
                endpoint_name=name,
                url=url,
                username=username,
                password=password,
                now=current,
                clock=timezone.now,
                sleeper=time.sleep,
                allow_not_found=True,
            )
            return {"response": body, "raw_sha256": sha}, 1, 1

        try:
            cached, _ = _get_or_fetch_shared_snapshot(
                provider=route.provider,
                region=route.region,
                scope_key="multisource:" + canonical_sha(url),
                data_kind="result" if result else "racecard",
                registry_digest=route.digest,
                run_id=canonical_sha({"url": url, "now": now.isoformat()}),
                now=now,
                proposed_requests=1,
                clock=timezone.now,
                sleeper=time.sleep,
                fetcher=fetch,
                waiter_max_polls=0,
            )
        except _ProviderSyncError as exc:
            raise ValueError(exc.reason_code) from None
        payload = cached["response"]
        raw_sha = cached["raw_sha256"]
    if payload.get("_not_found"):
        raise ValueError("not_found")
    if name == "result_by_id":
        payload = {"results": [payload]}
    snapshot = (
        parse_the_racing_api_live_results_payload
        if result
        else parse_the_racing_api_live_racecards_payload
    )(payload)
    names = {normalize_name(event.original_name), normalize_name(event.chinese_name)}
    candidates = []
    for race in snapshot.races:
        if source and race["external_race_id"] != source.external_race_id:
            continue
        if not source and normalize_name(race["race_name"]) not in names:
            continue
        venues = [
            key
            for key, aliases in route.venue_aliases.items()
            if normalize_name(race["course"]) in {normalize_name(n) for n in aliases}
        ]
        if (
            len(venues) != 1
            or aware(race["off_time"]).astimezone(ZoneInfo(route.timezone)).date()
            != event.local_date
        ):
            continue
        expected_region = registry["allowed_region_codes"][region]
        if str(race["region"]).casefold() != str(expected_region).casefold():
            continue
        candidates.append((race, venues[0]))
    if len(candidates) != 1:
        raise ValueError("source_discovery_ambiguous" if candidates else "not_found")
    race, venue = candidates[0]
    phase = ""
    if result:
        marker = race["race_status"].casefold()
        if marker in ("official", "complete", "completed", "result"):
            phase = "official"
        elif marker in ("amended", "corrected", "revised"):
            phase = "corrected"
        rows = _result_payload(
            normalized_race=race,
            region=route.region,
            event=event,
            source_key=route.provider,
        )["participants"]
    else:
        rows = [
            dict(
                external_runner_id=r["external_runner_id"],
                horse_name=r["horse_name"],
                number=r["number"],
                barrier=r["draw"],
                jockey_name=r["jockey_name"],
                trainer_name=r.get("trainer_name", ""),
                carried_weight=r.get("carried_weight", ""),
                status=r.get("status", "declared"),
                status_reported="status" in r,
                raw_status="",
                reported_finish_position=None,
                finish_time="",
                margin="",
                field_provenance={},
            )
            for r in race["participants"]
        ]
    return dict(
        provider=route.provider,
        region=route.region,
        identity_namespace=route.identity_namespace,
        external_race_id=race["external_race_id"],
        canonical_url=url,
        fetched_at=now.isoformat(),
        raw_sha256=raw_sha,
        parser_version=route.parser_version,
        operator=route.operator,
        venue_key=venue,
        local_date=event.local_date.isoformat(),
        timezone=route.timezone,
        meeting_session="",
        race_number="",
        raw_names=[race["race_name"]],
        off_time=race["off_time"],
        roster=rows,
        result_phase=phase,
        roster_complete=not result,
    )


def linked_result_url(page, *, url, route):
    """只跟随原页真实链接，且其日期/场次或来源race ID必须保持一致。"""
    from urllib.parse import urljoin, parse_qs
    from bs4 import BeautifulSoup

    targets = set()
    old = parse_qs(urlsplit(url).query)
    for a in BeautifulSoup(str(page), "html.parser").select("a[href]"):
        target = urljoin(url, a["href"])
        if target == url or not route.permits_url(target):
            continue
        if route.provider == "nar" and urlsplit(target).path.endswith("RaceMarkTable"):
            new = parse_qs(urlsplit(target).query)
            if all(
                new.get(k) == old.get(k) and old.get(k)
                for k in ("k_raceDate", "k_raceNo", "k_babaCode")
            ):
                targets.add(target)
        elif route.provider == "sporting_life":
            from stable.race_reference_parsers.sporting_life import _URL_RE

            before = re.search(
                r"/racecards/(\d{4}-\d{2}-\d{2})/([^/]+)/racecard/(\d+)/",
                urlsplit(url).path,
            )
            after = _URL_RE.fullmatch(urlsplit(target).path)
            if (
                before
                and after
                and before.groups()
                == (after["date"], after["course"], after["race_id"])
            ):
                targets.add(target)
    if len(targets) > 1:
        raise ValueError("linked_result_ambiguous")
    return next(iter(targets), "")
