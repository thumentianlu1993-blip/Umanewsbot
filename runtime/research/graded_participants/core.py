from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

SCHEMA_VERSION = 1
PARSER_VERSION = "graded-participants-v1"
SAFE_STOP_EXIT_CODE = 75
TERMINAL_STATUSES = {"success", "skipped", "not_found", "ambiguous", "permanent_error"}
UMAFANS_HOSTS = {"umafans.run", "www.umafans.run"}

REGION_LABELS = {
    "日本": "japan", "中国香港": "hong_kong", "香港": "hong_kong",
    "美国": "united_states", "英国": "united_kingdom", "法国": "france",
    "澳大利亚": "australia", "澳洲": "australia", "德国": "germany",
    "中东": "middle_east", "中东地区": "middle_east",
    "阿联酋": "middle_east", "阿拉伯联合酋长国": "middle_east",
    "沙特阿拉伯": "middle_east", "沙特": "middle_east",
    "卡塔尔": "middle_east", "巴林": "middle_east",
    "Australia": "australia", "Germany": "germany",
    "Middle East": "middle_east", "United Arab Emirates": "middle_east",
    "UAE": "middle_east", "Saudi Arabia": "middle_east",
    "Qatar": "middle_east", "Bahrain": "middle_east",
}
REGION_OUTPUT = {
    "japan": "日本", "hong_kong": "中国香港", "united_states": "美国",
    "united_kingdom": "英国", "france": "法国", "australia": "澳大利亚",
    "germany": "德国", "middle_east": "中东地区",
}
TARGET_REGIONS = set(REGION_OUTPUT)
TARGET_STANDARD_GRADES = {"G1", "G2", "G3"}
TARGET_JAPAN_GRADES = {
    "G1", "G2", "G3", "J-G1", "J-G2", "J-G3", "JPN1", "JPN2", "JPN3"
}
ENGLISH_OPTIONAL_REGIONS = {"japan", "hong_kong"}
REGION_HINTS = {
    "australia": (
        "flemington", "randwick", "caulfield", "moonee valley", "rosehill",
        "eagle farm", "doomben", "morphettville", "warwick farm", "the valley",
        "弗莱明顿", "兰域", "考菲尔德", "满利谷", "玫瑰岗",
    ),
    "germany": (
        "baden-baden", "baden baden", "hoppegarten", "münchen", "munich",
        "hamburg", "köln", "cologne", "düsseldorf", "dusseldorf",
        "巴登巴登", "霍佩加滕", "慕尼黑", "汉堡", "科隆", "杜塞尔多夫",
    ),
    "middle_east": (
        "meydan", "jebel ali", "abu dhabi", "king abdulaziz", "riyadh",
        "al rayyan", "al uqda", "sakhir", "bahrain international",
        "迈丹", "杰贝阿里", "阿布扎比", "阿卜杜勒阿齐兹国王", "利雅得",
        "赖扬", "乌克达", "萨基尔", "巴林国际",
    ),
}

HAN_RE = re.compile(r"[\u3400-\u9fff]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
LATIN_RE = re.compile(r"[A-Za-z]")
DATE_RE = re.compile(r"\b(19\d{2}|20\d{2})-(\d{2})-(\d{2})\b")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
POSITION_RE = re.compile(r"^\s*(\d+)")
COUNTRY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,3})\)\s*$")
NON_START_TOKENS = {
    "SCR", "SCRATCHED", "退赛", "取消出走", "未出赛", "未实际出赛",
    "NR", "NONRUNNER", "NON-RUNNER", "WD", "WITHDRAWN", "除外",
    "取消", "出走取消", "競走除外", "竞走除外", "発走除外", "发走除外",
}
RESULT_STATUS_ALIASES = {
    "DNF": "did_not_finish", "未完赛": "did_not_finish", "中止": "did_not_finish",
    "PU": "pulled_up", "PULLEDUP": "pulled_up", "PULLED-UP": "pulled_up", "拉停": "pulled_up",
    "F": "fell", "FELL": "fell", "堕马": "fell", "落马": "fell",
    "UR": "unseated_rider", "UNSEATEDRIDER": "unseated_rider",
    "UNSEATED-RIDER": "unseated_rider", "骑师落马": "unseated_rider",
    "BD": "brought_down", "BROUGHTDOWN": "brought_down",
    "BROUGHT-DOWN": "brought_down", "被带倒": "brought_down",
    "DSQ": "disqualified", "DQ": "disqualified", "DISQUALIFIED": "disqualified", "失格": "disqualified",
    "DH": "dead_heat", "DEADHEAT": "dead_heat", "DEAD-HEAT": "dead_heat", "同着": "dead_heat",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_space(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").replace("\u3000", " ").split())


def normalize_identity(value: str) -> str:
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", normalize_space(value).casefold())


def contains_han(value: str) -> bool:
    return bool(HAN_RE.search(value or ""))


def contains_kana(value: str) -> bool:
    return bool(KANA_RE.search(value or ""))


def contains_latin(value: str) -> bool:
    return bool(LATIN_RE.search(value or ""))


def strip_country_suffix(value: str) -> str:
    return COUNTRY_SUFFIX_RE.sub("", normalize_space(value)).strip()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def keys_sha256(keys: Iterable[str]) -> str:
    return sha256_bytes(canonical_json_bytes(sorted(set(str(key) for key in keys))))


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True); raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def atomic_write_text(path: Path, value: str) -> None:
    atomic_write_bytes(path, value.encode("utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader(); writer.writerows(rows)
    atomic_write_bytes(path, b"\xef\xbb\xbf" + handle.getvalue().encode("utf-8"))


def stable_shard(key: str, shard_count: int) -> int:
    if shard_count < 1: raise ValueError("shard_count must be positive")
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16) % shard_count


def normalize_grade(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").upper().strip()
    for source, target in (("III", "3"), ("II", "2"), ("Ⅰ", "1"), ("Ⅱ", "2"), ("Ⅲ", "3")):
        value = value.replace(source, target)
    value = value.replace("・", "-").replace("—", "-").replace("–", "-").replace("−", "-")
    value = re.sub(r"\bGRADE\s*", "G", value); value = re.sub(r"\bGROUP\s*", "G", value)
    value = re.sub(r"\s+", "", value)
    value = value.replace("JPNI", "JPN1").replace("JPNII", "JPN2").replace("JPNIII", "JPN3")
    value = value.replace("JG1", "J-G1").replace("JG2", "J-G2").replace("JG3", "J-G3")
    match = re.search(r"JPN[- ]?([123])", value)
    if match: return f"JPN{match.group(1)}"
    match = re.search(r"J-?G([123])", value)
    if match: return f"J-G{match.group(1)}"
    match = re.search(r"(?:^|[^A-Z])G([123])(?:$|[^0-9])", value)
    return f"G{match.group(1)}" if match else value


def grade_is_in_scope(region: str, grade: str) -> bool:
    return normalize_grade(grade) in (TARGET_JAPAN_GRADES if region == "japan" else TARGET_STANDARD_GRADES)


def normalized_result_token(value: str) -> str:
    return re.sub(r"[\s._/]+", "", unicodedata.normalize("NFKC", value or "").upper().strip())


def normalize_result_status(position_text: str) -> tuple[int | None, str, bool]:
    match = POSITION_RE.match(normalize_space(position_text))
    if match: return int(match.group(1)), "finished", True
    token = normalized_result_token(position_text)
    non_start = {normalized_result_token(item) for item in NON_START_TOKENS}
    if token in non_start:
        aliases = {
            normalized_result_token("SCR"): "scratched", normalized_result_token("SCRATCHED"): "scratched",
            normalized_result_token("退赛"): "scratched", normalized_result_token("NR"): "non_runner",
            normalized_result_token("NONRUNNER"): "non_runner", normalized_result_token("NON-RUNNER"): "non_runner",
            normalized_result_token("未出赛"): "non_runner", normalized_result_token("未实际出赛"): "non_runner",
        }
        return None, aliases.get(token, "withdrawn"), False
    status_map = {normalized_result_token(key): value for key, value in RESULT_STATUS_ALIASES.items()}
    return None, status_map.get(token, "unknown_started"), True


def validate_request_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password: raise ValueError("URL is not allowed")
    if (parsed.hostname or "").casefold() not in UMAFANS_HOSTS: raise ValueError("URL host is not allowed")
    if parsed.port not in {None, 80, 443}: raise ValueError("URL port is not allowed")
    return url


def unique_preserve(values: Iterable[str]) -> list[str]:
    seen: set[str] = set(); output: list[str] = []
    for value in values:
        cleaned = normalize_space(value); key = normalize_identity(cleaned)
        if cleaned and key and key not in seen: seen.add(key); output.append(cleaned)
    return output


def load_region_overrides(path: str) -> dict[str, dict[str, str]]:
    empty = {"labels": {}, "racecourses": {}, "urls": {}}
    if not path: return empty
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict): raise ValueError("region override file must contain an object")
    result = {key: {} for key in empty}
    for category in result:
        raw = payload.get(category, {})
        if not isinstance(raw, dict): raise ValueError(f"region override {category} must be an object")
        for source, region in raw.items():
            if region not in TARGET_REGIONS: raise ValueError(f"unsupported override region: {region}")
            result[category][normalize_space(str(source))] = region
    return result


def classify_region(*, label: str, racecourse: str, race_name_original: str, url: str,
                    overrides: dict[str, dict[str, str]] | None = None) -> str:
    overrides = overrides or {"labels": {}, "racecourses": {}, "urls": {}}
    if url in overrides.get("urls", {}): return overrides["urls"][url]
    if normalize_space(label) in overrides.get("labels", {}): return overrides["labels"][normalize_space(label)]
    if normalize_space(racecourse) in overrides.get("racecourses", {}): return overrides["racecourses"][normalize_space(racecourse)]
    direct = REGION_LABELS.get(normalize_space(label), "")
    if direct: return direct
    if normalize_space(label) not in {"", "其他", "OTHER"}: return ""
    haystack = normalize_space(f"{racecourse} {race_name_original}").casefold()
    matches = [region for region, hints in REGION_HINTS.items() if any(hint.casefold() in haystack for hint in hints)]
    return matches[0] if len(matches) == 1 else ""


def infer_names(display_names: Iterable[str], original_name: str) -> tuple[str, str, str]:
    displays = unique_preserve(display_names); original = normalize_space(original_name)
    name_zh = next((item for item in displays if contains_han(item) and not contains_kana(item)), "")
    name_ja = original if contains_kana(original) else next((item for item in displays if contains_kana(item)), "")
    name_en = ""
    for item in [original, *displays]:
        candidate = strip_country_suffix(item)
        if contains_latin(candidate) and not contains_kana(candidate) and not contains_han(candidate):
            name_en = candidate; break
    return name_zh, name_ja, name_en


def current_tool_version() -> str:
    package_dir = Path(__file__).resolve().parent
    files = [
        package_dir / "core.py", package_dir / "checkpoint.py",
        package_dir / "collector.py", package_dir / "pipeline.py",
        package_dir.parent / "collect_graded_race_participants.py",
    ]
    manifest = {path.name: sha256_bytes(path.read_bytes()) for path in files if path.exists()}
    return sha256_bytes(canonical_json_bytes(manifest))


@dataclass
class ParticipantRow:
    region: str; region_label: str; race_date: str; race_name_zh: str; race_name_original: str
    grade: str; racecourse: str; finish_position: int | None; finish_position_text: str
    result_status: str; horse_number: str; horse_display_name: str; jockey_name: str
    trainer_name: str; finish_time: str; margin: str; odds_popularity: str; race_url: str
    race_page_sha256: str; horse_lookup_key: str; horse_profile_url: str = ""
    horse_original_name: str = ""; horse_birth_year: str = ""; horse_name_zh: str = ""
    horse_name_ja: str = ""; horse_name_en: str = ""; chinese_name_missing: bool = False
    japanese_name_missing: bool = False; english_name_required: bool = False
    english_name_missing: bool = False


@dataclass
class HorseSeed:
    key: str; region: str; display_names: set[str] = field(default_factory=set)
    race_urls: set[str] = field(default_factory=set); participant_occurrences: int = 0
