"""免费公开地区页面的纯解析边界；无网络、无数据库、无权限推断。

结果表仅提供观测，完整性仍须由已核验出马表独立证明。缺失马号保持为空。
"""

from collections import Counter
from datetime import datetime
import hashlib
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

REGIONS = {
    "hkjc": "hong_kong",
    "racing_australia": "australia",
    "era": "united_arab_emirates",
    "jcsa": "saudi_arabia",
    "galopp_statistik": "germany",
}


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def horse_name(value):
    return re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", value).strip()


def row(
    *,
    name,
    number="",
    external="",
    raw="",
    result=True,
    barrier="",
    jockey="",
    trainer="",
    weight="",
    margin="",
    finish_time="",
):
    match = re.fullmatch(r"(\d+)(?:st|nd|rd|th|\.)?", raw.strip(), re.I)
    pos = int(match[1]) if match else None
    status = (
        "finished"
        if pos
        else {
            "SCR": "scratched",
            "SB": "scratched",
            "NR": "withdrawn",
            "NS": "withdrawn",
            "WV": "withdrawn",
            "DQ": "disqualified",
            "DISQ": "disqualified",
            "FF": "fell",
            "LR": "unseated_rider",
            "UR": "unseated_rider",
            "DNF": "did_not_finish",
            "PU": "pulled_up",
        }.get(raw.upper(), "unknown" if result else "declared")
    )
    return dict(
        external_runner_id=external or "number:" + number,
        horse_name=horse_name(name),
        number=number,
        barrier=barrier,
        jockey_name=jockey,
        trainer_name=trainer,
        carried_weight=weight,
        reported_finish_position=pos,
        status=status,
        raw_status=raw,
        margin=margin,
        finish_time=finish_time,
        field_provenance={},
    )


def local_start(day, clock, zone, fmt="%H:%M"):
    dt = datetime.strptime(day + " " + clock, "%Y-%m-%d " + fmt)
    return dt.replace(tzinfo=ZoneInfo(zone)).isoformat()


def _australia(soup, url, context, route):
    key = parse_qs(urlsplit(url).query).get("Key", [""])[0].split(",")
    if len(key) != 3:
        raise ValueError("au_identity_missing")
    day = datetime.strptime(key[0], "%Y%b%d").date().isoformat()
    head = soup.select_one("div.top h2")
    date_node = head.select_one(".race-venue-date") if head else None
    if not date_node:
        raise ValueError("au_header_missing")
    actual = datetime.strptime(text(date_node), "%A, %d %B %Y").date().isoformat()
    venue = text(head).replace(text(date_node), "").split(":")[0].strip()
    if actual != day or venue.casefold() != key[2].casefold():
        raise ValueError("au_header_url_mismatch")
    number = str(
        context.get("race_number")
        or parse_qs(urlsplit(url).query).get("raceno", [""])[0]
    )
    targets = []
    for table in soup.select("table.race-title"):
        m = re.match(
            r"Race\s+(\d+)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)\s+(.+)",
            text(table.select_one("th span")),
            re.I,
        )
        if m and str(int(m[1])) == number:
            targets.append((table, m))
    if len(targets) != 1:
        raise ValueError("au_race_context_required")
    table, m = targets[0]
    strip = table.find_next_sibling("table")
    # 页面另有 payout 表；必须找到本场第一张名单，不能越过下一场场头。
    if not strip or "race-strip-fields" not in strip.get("class", []):
        strip = table.find_next("table", class_="race-strip-fields")
        if not strip or strip.find_previous("table", class_="race-title") != table:
            raise ValueError("au_roster_missing")
    trs = strip.select("tr")
    headers = [text(c).lower() for c in trs[0].find_all(["td", "th"])]
    is_result = urlsplit(url).path.endswith("/Results.aspx")
    is_card = urlsplit(url).path.endswith("/Acceptances.aspx")
    if not is_result and not is_card:
        raise ValueError("au_page_kind_invalid")
    required = (
        {"finish", "no.", "horse", "bar."} if is_result else {"no", "horse", "barrier"}
    )
    if not required <= set(headers):
        raise ValueError("au_columns_missing")
    rows = []
    for tr in trs[1:]:
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        if len(cells) < len(headers):
            raise ValueError("au_row_partial")
        values = dict(zip(headers, map(text, cells)))
        a = tr.select_one("td.horse a[href]")
        code = (
            parse_qs(urlsplit(a["href"]).query).get("horsecode", [""])[0] if a else ""
        )
        raw = (
            (values["finish"] or ("SCR" if "Scratched" in tr.get("class", []) else ""))
            if is_result
            else ("SCR" if "Scratched" in tr.get("class", []) else "")
        )
        rows.append(
            row(
                name=values["horse"],
                number=values["no." if is_result else "no"],
                # RA horsecode 是随页面阶段变化的编码；同场仅用马号作为行键。
                external="",
                raw=raw,
                result=is_result,
                barrier=values["bar." if is_result else "barrier"],
                jockey=values.get("jockey", ""),
                trainer=values.get("trainer", ""),
                weight=values.get("weight", ""),
                margin=values.get("margin", ""),
            )
        )
    return dict(
        local_date=day,
        racecourse=venue,
        race_number=number,
        meeting_session=key[1],
        external_race_id=f"ra:{key[1]}:{key[2]}:{day}:{number}",
        raw_names=[m[3]],
        roster=rows,
        result_phase="official" if is_result else "",
        declaration_status=(
            "confirmed"
            if is_card and "FinalFields Last Published" in text(soup)
            else "unknown"
        ),
        off_time=local_start(day, re.sub(r"\s", "", m[2]), route.timezone, "%I:%M%p"),
    )


def _era(soup, url, context, route):
    q = parse_qs(urlsplit(url).query)
    full = re.fullmatch(
        r"/racecard/(\d{4}-\d{2}-\d{2})/(\d+)/(?:declarations|results|entries)",
        urlsplit(url).path,
    )
    if full:
        q = {"date": [full[1]], "race": [full[2]]}
    day = q.get("date", [""])[0]
    datetime.strptime(day, "%Y-%m-%d")
    number = str(q.get("race", [context.get("race_number", "")])[0])
    headings = []
    for h in soup.select("h2.racecard__heading"):
        m = re.match(r"Race\s+(\d+)\s*-\s*(.+)", text(h))
        if m and str(int(m[1])) == number:
            headings.append((h, m))
    if len(headings) != 1:
        raise ValueError("era_header_context_required")
    h, m = headings[0]
    block = h.find_parent("div", class_="racecard__top-panel") or h.parent
    stats = [
        text(x)
        for x in block.select(
            ".racecard__stats-list--primary .racecard__stats-list-item"
        )
    ]
    if "Thoroughbred" not in stats or "Purebred Arabian" in stats:
        raise ValueError("unsupported_race_type")
    # 不把当前 route 中唯一马场当成页面证据。
    images = " ".join(x.get("src", "") for x in block.select("img"))
    venue_match = re.search(
        r"(meydan|jebel-ali|abu-dhabi|sharjah|al-ain)", images, re.I
    )
    if not venue_match:
        raise ValueError("era_venue_missing")
    venue = venue_match[1].replace("-", " ").title()
    links = " ".join(a.get("href", "") for a in block.select("a[href]"))
    dates = set(
        re.findall(r"/racecard/(\d{4}-\d{2}-\d{2})/" + re.escape(number) + r"/", links)
    )
    if dates != {day}:
        raise ValueError("era_date_mismatch")
    tablebox = block.find_next_sibling("div", class_="racecard-table")
    table = tablebox.select_one("table") if tablebox else None
    if not table:
        raise ValueError("era_roster_missing")
    result = "racecard-table__table--results" in table.get("class", [])
    rows = []
    for tr in table.select("tbody tr.racecard-table__tr"):
        a = tr.select_one(".racecard-table__horse-name a")
        tds = tr.find_all("td", recursive=False)
        number_node = (
            tr.select_one(".racecard-table__saddle-cloth-number")
            if result
            else (tds[0] if len(tds) >= 2 else None)
        )
        if not a or not number_node:
            raise ValueError("era_row_partial")
        values = {}
        for item in tr.select(".racecard-table__main-grid-item"):
            strong = item.find("strong")
            if strong:
                holder = strong.find_parent("div").find_next_sibling("div")
                values[text(strong).rstrip(":")] = text(holder)
        tds = tr.find_all("td", recursive=False)
        raw = text(tds[0]) if result and tds else ""
        rows.append(
            row(
                name=text(a),
                number=text(number_node),
                external=a.get("href", ""),
                raw=raw,
                result=result,
                barrier=text(
                    tr.select_one(".racecard-table__stall-number") if result else tds[1]
                ).strip("()"),
                jockey=values.get("Jockey", ""),
                trainer=values.get("Trainer", ""),
                weight=values.get("Weight", ""),
                finish_time=values.get("Time", ""),
                margin=text(tr.select_one("td.text-nowrap")),
            )
        )
    clock = next((s for s in stats if re.fullmatch(r"\d{2}:\d{2}", s)), None)
    value = dict(
        local_date=day,
        racecourse=venue,
        race_number=number,
        meeting_session="single",
        external_race_id=f"era:{day}:{venue}:{number}",
        raw_names=[m[2]],
        roster=rows,
        result_phase="official" if result else "",
        declaration_status=(
            "confirmed"
            if not result
            and "Official" in text(soup.select_one("#tab-" + number + "-declarations"))
            else "unknown"
        ),
    )
    if clock:
        value["off_time"] = local_start(day, clock, route.timezone)
    return value


def _jcsa(soup, url, context, route):
    match = re.fullmatch(
        r"/api/meeting-info/en/(\d{8})/(\d+)/(Results|Declared)/True",
        urlsplit(url).path,
    )
    if not match:
        raise ValueError("jcsa_url_invalid")
    day = datetime.strptime(match[1], "%Y%m%d").date().isoformat()
    number = str(int(match[2]))
    if (
        context.get("local_date") != day
        or context.get("race_number") != number
        or not context.get("raw_names")
        or not context.get("racecourse")
    ):
        raise ValueError("jcsa_verified_context_required")
    is_result = match[3] == "Results"
    heading = "Place" if is_result else "Saddle Cloth (Gate)"
    tables = [
        t
        for t in soup.select("table")
        if heading in text(t.find("thead")) and "Horse Name" in text(t.find("thead"))
    ]
    if len(tables) != 1:
        raise ValueError("jcsa_table_missing")
    rows = []
    for tr in tables[0].select("tbody tr.meeting-info-horse-item"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != (9 if is_result else 7):
            raise ValueError("jcsa_row_partial")
        a = tds[2].select_one('a[href^="/en/horses/"]')
        if not a:
            raise ValueError("jcsa_horse_missing")
        cloth = (
            re.fullmatch(r"(\d+)\s*\((\d+|NR)\)", text(tds[0]))
            if not is_result
            else None
        )
        if not is_result and not cloth:
            raise ValueError("jcsa_cloth_missing")
        rows.append(
            row(
                name=a.get("title") or text(a),
                external=a["href"],
                number=cloth[1] if cloth else "",
                barrier=cloth[2] if cloth and cloth[2] != "NR" else "",
                raw=text(tds[0]) if is_result else "NR" if cloth[2] == "NR" else "",
                result=is_result,
                jockey=text(tds[2].select_one('a[href^="/en/jockeys/"]')),
                trainer=text(tds[2].select_one('a[href^="/en/trainers/"]')),
                weight=text(tds[4]),
                finish_time=text(tds[6]) if is_result else "",
                margin=text(tds[7]) if is_result else "",
            )
        )
    # '-' 不能确定是退赛、取消资格还是尚未出成绩；保存观测，不晋级正式模块。
    return dict(
        local_date=day,
        racecourse=context["racecourse"],
        race_number=number,
        meeting_session="single",
        external_race_id=f"jcsa:{day}:{number}",
        raw_names=context["raw_names"],
        roster=rows,
        result_phase=(
            "official"
            if is_result and all(r["status"] != "unknown" for r in rows)
            else ""
        ),
        declaration_status="confirmed" if not is_result else "unknown",
    )


_MONTHS = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def _galopp_card(soup, url, context, route):
    q = parse_qs(urlsplit(url).query)
    heads = soup.select(".container-rennort-und-datum .rennortDatum")
    if len(heads) != 3:
        raise ValueError("galopp_card_header_missing")
    m = re.fullmatch(r"(\d+)\.\s+(\w+)\s+(\d{4})", text(heads[2]))
    if not m or m[2] not in _MONTHS:
        raise ValueError("galopp_date_missing")
    day = datetime(int(m[3]), _MONTHS.index(m[2]) + 1, int(m[1])).date().isoformat()
    number = text(soup.select_one(".nr-des-rennens"))
    if q.get("Datum") != [day] or q.get("Nummer") != [number]:
        raise ValueError("galopp_card_identity_mismatch")
    rows = []
    for cell in soup.select(".pferdename.startfeld"):
        tr = cell.find_parent("div", class_="uebersicht-row")
        a = cell.select_one("a[href]")
        if not tr or not a:
            raise ValueError("galopp_card_partial")
        rows.append(
            row(
                name=text(a),
                external=a["href"],
                number=text(tr.select_one(".nummer")),
                barrier=text(tr.select_one(".box")).strip("()"),
                result=False,
                jockey=text(tr.select_one(".jockey")),
                trainer=text(tr.select_one(".trainer")),
                weight=text(tr.select_one(".gewicht")).replace(",", "."),
            )
        )
    return dict(
        local_date=day,
        racecourse=text(heads[0]),
        race_number=number,
        meeting_session="single",
        external_race_id=f"galopp:{day}:{text(heads[0])}:{number}",
        raw_names=[text(soup.select_one(".titel-des-rennens"))],
        roster=rows,
        result_phase="",
        declaration_status="unknown",
        off_time=local_start(day, text(soup.select_one(".uhrzeit")), route.timezone),
    )


def _galopp(soup, url, context, route):
    if urlsplit(url).path == "/RennenDetails.php":
        return _galopp_card(soup, url, context, route)
    if urlsplit(url).path != "/DisplayErgebnis.php":
        raise ValueError("galopp_url_invalid")
    rid = parse_qs(urlsplit(url).query).get("id", [""])[0]
    if not rid.isdigit():
        raise ValueError("galopp_id_missing")
    head = soup.select(".renntagKopf .ZeitundOrt")
    if len(head) != 2:
        raise ValueError("galopp_header_missing")
    m = re.fullmatch(r"(\d+)\.\s+(\w+)\s+(\d{4})", text(head[0]))
    if not m or m[2] not in _MONTHS:
        raise ValueError("galopp_date_missing")
    day = datetime(int(m[3]), _MONTHS.index(m[2]) + 1, int(m[1])).date().isoformat()
    number = text(soup.select_one(".nr-des-rennens"))
    title = text(soup.select_one(".titel-des-rennens"))
    rows = []
    for tr in soup.select(".table-result-row"):
        a = tr.select_one(".horsename a[href]")
        crew = tr.select(".trainer-box")
        if not a:
            raise ValueError("galopp_horse_missing")
        rows.append(
            row(
                name=text(a),
                external=a.get("href", ""),
                raw=text(tr.select_one(".place")),
                barrier=text(tr.select_one(".startbox")).strip("()"),
                jockey=text(crew[0]) if crew else "",
                trainer=text(crew[1]) if len(crew) > 1 else "",
                weight=text(tr.select_one(".weight")).replace(",", ".") + "kg",
                margin=text(tr.select_one(".abstand")),
            )
        )
    return dict(
        local_date=day,
        racecourse=text(head[1]),
        race_number=number,
        meeting_session="single",
        external_race_id=f"galopp:{day}:{text(head[1])}:{number}",
        raw_names=[title],
        roster=rows,
        result_phase="official",
        off_time=local_start(day, text(soup.select_one(".uhrzeit")), route.timezone),
    )


def parse_regional_observation(page, *, url, route, now, context=None):
    if (
        route.provider not in REGIONS
        or route.region != REGIONS[route.provider]
        or not route.valid(now)
        or not route.permits_url(url)
    ):
        raise ValueError("regional_route_invalid")
    parser = {
        "hkjc": _hkjc_card,
        "racing_australia": _australia,
        "era": _era,
        "jcsa": _jcsa,
        "galopp_statistik": _galopp,
    }[route.provider]
    value = parser(BeautifulSoup(str(page), "html.parser"), url, context or {}, route)
    from stable.services.race_source_identity import normalize_name

    course = value.pop("racecourse", "")
    venues = [
        k
        for k, names in route.venue_aliases.items()
        if normalize_name(course) in {normalize_name(n) for n in names}
    ]
    if len(venues) != 1:
        raise ValueError("venue_unreviewed")
    rows = value["roster"]
    ids = [r["external_runner_id"] for r in rows]
    if (
        not rows
        or len(rows) > 40
        or len(set(ids)) != len(ids)
        or any(not r["horse_name"] or not r["external_runner_id"] for r in rows)
        or not value["race_number"].isdigit()
        or not all(value["raw_names"])
    ):
        raise ValueError("regional_roster_invalid")
    numbers = [r["number"] for r in rows if r["number"]]
    if any(not n.isdigit() or int(n) < 1 for n in numbers) or len(set(numbers)) != len(
        numbers
    ):
        raise ValueError("regional_numbers_invalid")
    if value["result_phase"] and any(r["status"] == "unknown" for r in rows):
        raise ValueError("regional_status_unknown")
    counts = Counter(
        r["reported_finish_position"] for r in rows if r["reported_finish_position"]
    )
    for r in rows:
        if counts[r["reported_finish_position"]] > 1:
            r["status"] = "dead_heat"
    sha = getattr(page, "raw_sha256", hashlib.sha256(str(page).encode()).hexdigest())
    for r in rows:
        r["field_provenance"] = {"source_url": url, "raw_sha256": sha}
    value.update(
        provider=route.provider,
        region=route.region,
        identity_namespace=route.identity_namespace,
        canonical_url=url,
        fetched_at=now.isoformat(),
        raw_sha256=sha,
        parser_version=route.parser_version,
        operator=route.operator,
        venue_key=venues[0],
        timezone=route.timezone,
        roster_complete=not bool(value["result_phase"])
        and value.get("declaration_status") == "confirmed",
    )
    return value


def merge_jcsa_rosters(result, card):
    """仅按同源稳定 ID 联接同场数据；未知 '-' 只有明确 NR 才能补成退赛。"""
    from copy import deepcopy
    from stable.services.race_source_identity import normalize_name

    for key in (
        "provider",
        "region",
        "identity_namespace",
        "external_race_id",
        "local_date",
        "venue_key",
        "race_number",
    ):
        if result.get(key) != card.get(key):
            raise ValueError("jcsa_join_identity_mismatch")
    if card.get("declaration_status") != "confirmed" or not card.get("roster_complete"):
        raise ValueError("jcsa_join_card_incomplete")
    by_id = {r["external_runner_id"]: r for r in card["roster"]}
    if (
        len(by_id) != len(card["roster"])
        or len(result["roster"]) != len(by_id)
        or {r["external_runner_id"] for r in result["roster"]} != set(by_id)
    ):
        raise ValueError("jcsa_join_roster_mismatch")
    value = deepcopy(result)
    proof = card.get("roster_page_evidence") or {
        "source_url": card["canonical_url"],
        "raw_sha256": card["raw_sha256"],
    }
    for r in value["roster"]:
        prior = by_id[r["external_runner_id"]]
        if normalize_name(r["horse_name"]) != normalize_name(prior["horse_name"]):
            raise ValueError("jcsa_join_horse_mismatch")
        if prior["status"] == "withdrawn":
            if r["reported_finish_position"] is not None:
                raise ValueError("jcsa_join_status_conflict")
            if r["raw_status"] not in ("-", "NR"):
                raise ValueError("jcsa_join_status_conflict")
            r["status"] = "withdrawn"
            r["field_provenance"]["status"] = proof
        if r["status"] == "unknown":
            raise ValueError("jcsa_join_status_unknown")
        r["number"] = prior["number"]
        r["barrier"] = prior["barrier"]
        r["field_provenance"]["number"] = proof
        r["field_provenance"]["barrier"] = proof
    value.update(result_phase="official", roster_complete=True, roster_evidence=proof)
    return value


def decode_public_html(raw, *, encoding, provider):
    """德国旧页的无效注释字节不属于业务数据；正文仍严格解码，原始 SHA 保留原字节。"""
    if provider == "galopp_statistik":
        raw = re.sub(rb"<!--.*?-->", b"", raw, flags=re.S)
    return raw.decode(encoding)


def galopp_result_link(page, *, url, route):
    from urllib.parse import urljoin

    q = parse_qs(urlsplit(url).query)
    day = datetime.strptime(q.get("Datum", [""])[0], "%Y-%m-%d")
    label = day.strftime("%d.%m.%y") + " " + q.get("Ort", [""])[0]
    links = set()
    for a in BeautifulSoup(str(page), "html.parser").select("a[href]"):
        link = urljoin(url, a["href"])
        if (
            text(a) == label
            and urlsplit(link).path == "/DisplayErgebnis.php"
            and route.permits_url(link)
        ):
            links.add(link)
    if len(links) != 1:
        raise ValueError("galopp_result_link_ambiguous")
    return links.pop()


def merge_numbered_rosters(result, card):
    from copy import deepcopy
    from stable.services.race_source_identity import normalize_name

    for key in (
        "provider",
        "region",
        "identity_namespace",
        "external_race_id",
        "local_date",
        "venue_key",
        "race_number",
    ):
        if result.get(key) != card.get(key):
            raise ValueError("regional_join_identity_mismatch")
    by_id = {r["external_runner_id"]: r for r in card["roster"]}
    if (
        not by_id
        or len(by_id) != len(card["roster"])
        or len(result["roster"]) != len(by_id)
        or {r["external_runner_id"] for r in result["roster"]} != set(by_id)
    ):
        raise ValueError("regional_join_roster_mismatch")
    value = deepcopy(result)
    proof = card.get("roster_page_evidence") or {
        "source_url": card["canonical_url"],
        "raw_sha256": card["raw_sha256"],
    }
    for r in value["roster"]:
        prior = by_id[r["external_runner_id"]]
        if prior["status"] in ("withdrawn", "scratched") and (
            r["reported_finish_position"] is not None
            or r["status"] not in ("withdrawn", "scratched")
        ):
            raise ValueError("regional_join_status_conflict")
        if normalize_name(r["horse_name"]) != normalize_name(prior["horse_name"]):
            raise ValueError("regional_join_horse_mismatch")
        if not prior["number"].isdigit() or int(prior["number"]) < 1:
            raise ValueError("regional_join_number_missing")
        if r["number"] and r["number"] != prior["number"]:
            raise ValueError("regional_join_number_mismatch")
        r["number"] = prior["number"]
        r["field_provenance"]["number"] = proof
    value.update(roster_complete=True, roster_evidence=proof)
    return value


def _hkjc_card(soup, url, context, route):
    q = {k.lower(): v for k, v in parse_qs(urlsplit(url).query).items()}
    day = datetime.strptime(q.get("racedate", [""])[0], "%Y/%m/%d").date()
    number = q.get("raceno", [""])[0]
    code = q.get("racecourse", [""])[0]
    candidates = [
        x for x in soup.select("div.f_fs13") if re.match(r"Race\s+\d+\s+-", text(x))
    ]
    if len(candidates) != 1:
        raise ValueError("hkjc_card_header_missing")
    lines = list(candidates[0].stripped_strings)
    m = re.fullmatch(r"Race\s+(\d+)\s*-\s*(.+)", lines[0])
    meta = (
        re.fullmatch(r"(.+), (Sha Tin|Happy Valley), (\d{2}:\d{2})", lines[1])
        if len(lines) > 1
        else None
    )
    if (
        not m
        or not meta
        or m[1] != number
        or datetime.strptime(meta[1], "%A, %B %d, %Y").date() != day
    ):
        raise ValueError("hkjc_card_identity_mismatch")
    if {"Sha Tin": "ST", "Happy Valley": "HV"}[meta[2]] != code:
        raise ValueError("hkjc_course_mismatch")
    table = soup.select_one("table.starter")
    if not table:
        raise ValueError("hkjc_card_missing")
    headers = [
        text(c)
        for c in table.select("thead tr")[0].find_all(["td", "th"], recursive=False)
    ]
    required = {"Horse No.", "Horse", "Wt.", "Jockey", "Draw", "Trainer", "Brand No."}
    if not required <= set(headers):
        raise ValueError("hkjc_card_columns_missing")
    rows = []
    for tr in table.select("tbody tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) != len(headers):
            raise ValueError("hkjc_card_partial")
        values = dict(zip(headers, map(text, cells)))
        horse = cells[headers.index("Horse")].select_one("a[href]")
        if not horse:
            raise ValueError("hkjc_card_horse_missing")
        hid = {
            k.lower(): v for k, v in parse_qs(urlsplit(horse["href"]).query).items()
        }.get("horseid", [""])[0]
        if not hid:
            raise ValueError("hkjc_card_horse_missing")
        rows.append(
            row(
                name=text(horse),
                number=values["Horse No."],
                external=hid,
                barrier=values["Draw"],
                jockey=values["Jockey"],
                trainer=values["Trainer"],
                weight=values["Wt."] + "lb",
                result=False,
                raw="WV" if re.search(r"\bWithdrawn\b", text(tr), re.I) else "",
            )
        )
    return dict(
        local_date=day.isoformat(),
        racecourse=meta[2],
        race_number=number,
        meeting_session="single",
        external_race_id=f"HK{day:%Y%m%d}{code}{int(number):02d}",
        raw_names=[m[2]],
        roster=rows,
        declaration_status="confirmed",
        result_phase="",
        off_time=local_start(day.isoformat(), meta[3], route.timezone),
    )


def era_ajax_url(page, *, url, route, kind):
    """读取页面公开 data-src，核验与当前完整 URL 的日期和场次一致。"""
    from urllib.parse import urljoin

    match = re.fullmatch(
        r"/racecard/(\d{4}-\d{2}-\d{2})/(\d+)/(?:declarations|results|entries)",
        urlsplit(url).path,
    )
    if not match:
        raise ValueError("era_page_identity_missing")
    nodes = BeautifulSoup(str(page), "html.parser").select(f"#panel-{kind}[data-src]")
    if len(nodes) != 1:
        raise ValueError("era_ajax_missing")
    target = urljoin("https://" + urlsplit(url).netloc + "/ajax/", nodes[0]["data-src"])
    q = parse_qs(urlsplit(target).query)
    if (
        not route.permits_url(target)
        or urlsplit(target).path != "/ajax/racecard-" + kind
        or q.get("date") != [match[1]]
        or q.get("race") != [match[2]]
    ):
        raise ValueError("era_ajax_identity_mismatch")
    return target


def parse_era_joined_page(page, rows_page, *, url, rows_url, route, now):
    from stable.services.race_pre_race import JraPage

    soup = BeautifulSoup(str(page), "html.parser")
    top = soup.select_one(".racecard__top-panel")
    tabs = soup.select_one('[data-module="racecard-tabs"]')
    if not top or not tabs:
        raise ValueError("era_page_header_missing")
    combined = (
        str(top)
        + '<div class="racecard-table">'
        + str(rows_page)
        + "</div>"
        + str(tabs)
    )
    sha = getattr(page, "raw_sha256", hashlib.sha256(str(page).encode()).hexdigest())
    value = parse_regional_observation(
        JraPage(combined, sha, now), url=url, route=route, now=now
    )
    row_sha = getattr(
        rows_page, "raw_sha256", hashlib.sha256(str(rows_page).encode()).hexdigest()
    )
    for r in value["roster"]:
        r["field_provenance"] = {"source_url": rows_url, "raw_sha256": row_sha}
    value["roster_page_evidence"] = {"source_url": rows_url, "raw_sha256": row_sha}
    return value


def enrich_jcsa_metadata(value, page, *, url, route):
    from copy import deepcopy

    if not route.permits_url(url):
        raise ValueError("source_url_rejected")
    path = re.fullmatch(r"/en/races/(\d{8})/(\d+)/results", urlsplit(url).path)
    if (
        not path
        or datetime.strptime(path[1], "%Y%m%d").date().isoformat()
        != value["local_date"]
        or path[2] != value["race_number"]
    ):
        raise ValueError("jcsa_header_identity_mismatch")
    soup = BeautifulSoup(str(page), "html.parser")
    labels = [h for h in soup.select("h2") if text(h) == "R" + value["race_number"]]
    dates = []
    clocks = []
    for h in soup.select("h4"):
        content = re.sub(r"(\d+)(?:st|nd|rd|th)", r"\1", text(h))
        try:
            dates.append(datetime.strptime(content, "%A, %d %B %Y").date().isoformat())
        except ValueError:
            pass
        if re.fullmatch(r"\d{2}:\d{2}[ap]m", content, re.I):
            clocks.append(content.upper())
    sections = soup.select("section.meeting-info[data-race-date][data-race-number]")
    if (
        len(labels) != 1
        or dates != [value["local_date"]]
        or len(clocks) != 1
        or not sections
        or any(
            x["data-race-date"] != path[1] or x["data-race-number"] != path[2]
            for x in sections
        )
    ):
        raise ValueError("jcsa_header_identity_mismatch")
    title = text(labels[0].find_next("h2"))
    if not title:
        raise ValueError("jcsa_header_name_missing")
    result = deepcopy(value)
    result.update(
        off_time=local_start(value["local_date"], clocks[0], route.timezone, "%I:%M%p"),
        raw_names=[title],
        metadata_evidence={
            "source_url": url,
            "raw_sha256": getattr(
                page, "raw_sha256", hashlib.sha256(str(page).encode()).hexdigest()
            ),
        },
    )
    return result
