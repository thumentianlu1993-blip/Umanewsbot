#!/usr/bin/env python3
"""新增地区官方赛果的离线解析与 URL 策略；本模块不访问网络。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlparse

POS = re.compile(r"^(\d+)(?:st|nd|rd|th|\.)?$", re.I)
HORSE_ID = re.compile(r"/hors?e?s?/([^/?#]+)", re.I)
AGED_NAME = re.compile(r"^(.*?)\s+\d+\s+YO\b", re.I)


@dataclass(frozen=True)
class Policy:
    region: str
    country: str
    hosts: tuple[str, ...]
    request_budget: int


POLICIES = {
    "au_racing_australia": Policy("australia", "australia", ("www.racingaustralia.horse", "t.racingaustralia.horse"), 800),
    "de_deutscher_galopp": Policy("germany", "germany", ("www.deutscher-galopp.de",), 500),
    "uae_era": Policy("middle_east", "united_arab_emirates", ("emiratesracing.com", "www.emiratesracing.com"), 500),
    "sa_jcsa": Policy("middle_east", "saudi_arabia", ("www.jcsa.sa", "jcsa.sa"), 500),
    "qa_qrec": Policy("middle_east", "qatar", ("www.qrec.gov.qa", "qrec.gov.qa"), 500),
    "bh_btc": Policy("middle_east", "bahrain", ("bahrainturfclub.com", "www.bahrainturfclub.com"), 500),
}


class OfficialSourceError(ValueError):
    pass


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def validate_provider_url(provider: str, url: str, *, year: int) -> str:
    if provider not in POLICIES:
        raise OfficialSourceError(f"unknown provider: {provider}")
    parsed = urlparse(clean(url))
    if parsed.scheme != "https" or parsed.hostname not in POLICIES[provider].hosts:
        raise OfficialSourceError(f"provider URL is outside allowlist: {provider}")
    if str(year) not in url:
        raise OfficialSourceError(f"provider URL lacks requested year: {provider}")
    return parsed.geturl()


def derive_data_url(provider: str, page_url: str, *, year: int) -> str:
    parsed = urlparse(validate_provider_url(provider, page_url, year=year))
    if provider == "uae_era":
        match = re.fullmatch(r"/racecard/(\d{4}-\d{2}-\d{2})/(\d+)/results", parsed.path)
        if not match:
            raise OfficialSourceError("invalid ERA results page path")
        return f"https://emiratesracing.com/ajax/racecard-results?date={match[1]}&race={match[2]}"
    if provider == "sa_jcsa":
        match = re.fullmatch(r"/(?:en/)?races/(\d{8})/(\d+)", parsed.path)
        if not match:
            raise OfficialSourceError("invalid JCSA results page path")
        return f"https://www.jcsa.sa/api/meeting-info/en/{match[1]}/{match[2]}/Results/True"
    return parsed.geturl()


@dataclass
class Cell:
    text: str
    hrefs: list[str]


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.depth=0; self.in_cell=False; self.text=[]; self.hrefs=[]; self.row=[]; self.table=[]; self.tables=[]
    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if not self.depth: self.table=[]
            self.depth += 1
        elif self.depth and tag == "tr": self.row=[]
        elif self.depth and tag in {"td", "th"}: self.in_cell=True; self.text=[]; self.hrefs=[]
        elif self.in_cell and tag == "a" and dict(attrs).get("href"): self.hrefs.append(dict(attrs)["href"])
    def handle_data(self, data):
        if self.in_cell: self.text.append(data)
    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.in_cell: self.row.append(Cell(clean("".join(self.text)), self.hrefs)); self.in_cell=False
        elif tag == "tr" and self.depth and self.row: self.table.append(self.row); self.row=[]
        elif tag == "table" and self.depth:
            self.depth -= 1
            if not self.depth: self.tables.append(self.table); self.table=[]


def tables(html: str):
    parser=Tables(); parser.feed(html); return parser.tables


def pos(value: str):
    match=POS.fullmatch(clean(value)); return int(match[1]) if match else None


NONSTARTER_STATUSES = {"NR", "SCR", "SCRATCHED", "WD", "WITHDRAWN"}
DISQUALIFIED_STATUSES = {"DQ", "DSQ", "DISQUALIFIED"}
DID_NOT_FINISH_STATUSES = {
    "BD", "BROUGHT DOWN", "DNF", "F", "FELL", "PU", "PULLED UP",
    "RO", "RAN OUT", "UR", "UNSEATED RIDER",
}


def placing(value: str):
    """Return (finish_position, participant_status), or None for a nonstarter."""
    value = clean(value)
    position = pos(value)
    if position is not None:
        return position, "finished"
    status = value.upper().rstrip(".")
    if status in NONSTARTER_STATUSES:
        return None
    if status in DISQUALIFIED_STATUSES:
        return None, "disqualified"
    if status in DID_NOT_FINISH_STATUSES:
        return None, "did_not_finish"
    raise OfficialSourceError(f"unknown official result status: {value or '<blank>'}")


def horse_id(cell: Cell):
    for href in cell.hrefs:
        match=HORSE_ID.search(href)
        if match: return match[1]
    return ""


def row(provider, finish, name, *, participant_status="finished", number="", cell=None, jockey="", trainer="", time="", margin=""):
    return {"provider":provider,"provider_horse_id":horse_id(cell or Cell("",[])),"finish_position":finish,"horse_number":number,"horse_name":clean(name),"jockey_name":clean(jockey),"trainer_name":clean(trainer),"finish_time":clean(time),"margin":clean(margin),"participant_status":participant_status}


def finish(provider, result):
    if not result: raise OfficialSourceError(f"{provider} response contains no actual starter rows")
    if any(not x["horse_name"] for x in result): raise OfficialSourceError(f"{provider} response contains empty horse name")
    return result


def header_parser(provider: str, html: str, aliases: dict[str, tuple[str,...]], builder: Callable):
    for table in tables(html):
        if not table: continue
        heads=[c.text.casefold() for c in table[0]]; indexes={}
        for key, names in aliases.items():
            for name in names:
                if name.casefold() in heads: indexes[key]=heads.index(name.casefold()); break
        if not {"position","horse"} <= indexes.keys(): continue
        result=[]
        for raw in table[1:]:
            offset=max(0,len(raw)-len(heads)); values={k:raw[i+offset] for k,i in indexes.items() if i+offset<len(raw)}
            item=builder(values)
            if item: result.append(item)
        if result: return finish(provider,result)
    raise OfficialSourceError(f"{provider} result table schema not found")


def parse_au(html):
    aliases={"position":("Finish","Place"),"number":("No.","No"),"horse":("Horse",),"trainer":("Trainer",),"jockey":("Jockey",),"margin":("Margin",)}
    def build(v):
        result=placing(v["position"].text)
        return None if result is None else row("au_racing_australia",result[0],v["horse"].text,participant_status=result[1],number=v.get("number",Cell("",[])).text,cell=v["horse"],jockey=v.get("jockey",Cell("",[])).text,trainer=v.get("trainer",Cell("",[])).text,margin=v.get("margin",Cell("",[])).text)
    return header_parser("au_racing_australia",html,aliases,build)


def parse_de(html):
    aliases={"position":("Pl.",),"horse":("Name",),"number":("Nr.",),"margin":("Abstand",),"trainer":("Trainer",),"jockey":("Reiter",)}
    def build(v):
        result=placing(v["position"].text)
        return None if result is None else row("de_deutscher_galopp",result[0],v["horse"].text,participant_status=result[1],number=v["number"].text,cell=v["horse"],jockey=v["jockey"].text,trainer=v["trainer"].text,margin=v["margin"].text)
    return header_parser("de_deutscher_galopp",html,aliases,build)


def parse_era(html):
    result=[]
    for table in tables(html):
        for cells in table:
            match=AGED_NAME.match(cells[4].text) if len(cells)>=16 else None
            if not match: continue
            result_status=placing(cells[0].text)
            if result_status is None: continue
            details=cells[5].text
            get=lambda pattern: clean((m.group(1) if (m:=re.search(pattern,details)) else ""))
            result.append(row("uae_era",result_status[0],match[1],participant_status=result_status[1],number=cells[3].text.split(" ",1)[0],cell=cells[4],jockey=get(r"Jockey:\s*(.*?)\s+Rating:"),trainer=get(r"Trainer:\s*(.*?)\s+Weight:"),time=get(r"Time:\s*(.*?)\s+Trainer:"),margin=cells[1].text))
    return finish("uae_era",result)


def parse_sa(html):
    result=[]
    for table in tables(html):
        if not table or [c.text for c in table[0]][:2] != ["Place", "Horse Name"]: continue
        for cells in table[1:]:
            # JCSA desktop rows insert a silk cell after Place although the header
            # represents it through colspan, so later columns are shifted by one.
            if len(cells) < 8: continue
            result_status=placing(cells[0].text); shift=1 if len(cells)>len(table[0]) else 0
            horse=cells[1+shift]; text=horse.text
            if result_status is None: continue
            jockey=re.search(r"\sJ\s(.*?)\sT\s",text); trainer=re.search(r"\sT\s(.*?)\sO\s",text)
            result.append(row("sa_jcsa",result_status[0],text.split(" J ",1)[0],participant_status=result_status[1],cell=horse,jockey=jockey[1] if jockey else "",trainer=trainer[1] if trainer else "",time=cells[5+shift].text,margin=cells[6+shift].text))
    return finish("sa_jcsa",result)


def parse_qa(payload):
    candidate=payload
    if "<" in payload:
        match=re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',payload,re.I|re.S)
        if not match: raise OfficialSourceError("qa_qrec page lacks __NEXT_DATA__")
        candidate=unescape(match.group(1))
    try: root=json.loads(candidate)
    except json.JSONDecodeError as exc: raise OfficialSourceError("qa_qrec response is not JSON") from exc
    arrays=[]
    def visit(value):
        if isinstance(value,dict):
            result=value.get("result")
            if isinstance(result,list) and any(isinstance(item,dict) and item.get("horseName") for item in result): arrays.append(result)
            for nested in value.values(): visit(nested)
        elif isinstance(value,list):
            for nested in value: visit(nested)
    visit(root)
    unique={json.dumps(items,ensure_ascii=False,sort_keys=True):items for items in arrays}
    if len(unique)!=1: raise OfficialSourceError("qa_qrec response lacks one unambiguous result array")
    items=next(iter(unique.values()))
    result=[]
    for item in items:
        result_status=placing(clean(item.get("fp") or item.get("finishPosition")))
        if result_status is None: continue
        result.append(row("qa_qrec",result_status[0],item.get("horseName"),participant_status=result_status[1],number=item.get("horseNo",""),jockey=item.get("jockeyName",""),trainer=item.get("trainerName",""),time=item.get("time",""),margin=item.get("margin","")) | {"provider_horse_id":clean(item.get("horseId"))})
    return finish("qa_qrec",result)


def parse_bh(html):
    aliases={"position":("Position Pos.","Position"),"horse":("Horse Name",),"jockey":("Jockey",),"trainer":("Trainer",),"time":("Time",),"margin":("Margin",)}
    def build(v):
        result=placing(v["position"].text); match=AGED_NAME.match(v["horse"].text)
        return None if result is None or not match else row("bh_btc",result[0],match[1],participant_status=result[1],cell=v["horse"],jockey=v["jockey"].text,trainer=v["trainer"].text,time=v["time"].text,margin=v["margin"].text)
    return header_parser("bh_btc",html,aliases,build)


PARSERS={"au_racing_australia":parse_au,"de_deutscher_galopp":parse_de,"uae_era":parse_era,"sa_jcsa":parse_sa,"qa_qrec":parse_qa,"bh_btc":parse_bh}


def parse_official_results(provider: str, payload: str):
    if provider not in PARSERS: raise OfficialSourceError(f"unknown provider: {provider}")
    return PARSERS[provider](payload)
