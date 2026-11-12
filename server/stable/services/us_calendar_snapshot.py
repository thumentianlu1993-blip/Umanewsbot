"""人工下载的 TOBA 年度目录：只读、双摘要绑定，不提供网络回退。"""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .race_pre_race import SourceBytes

MAX_BYTES = 8 * 1024 * 1024
URL_PATTERN = r'https://toba\.org/graded-stakes/([0-9]{4})-races/'


def calendar_year(url):
    match = re.fullmatch(URL_PATTERN, url)
    return int(match[1]) if match else None


def _read(path, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('us_calendar_snapshot_size')
    return raw


def _timestamp(value, now):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.utcoffset() is None or stamp > now:
            raise ValueError('us_calendar_snapshot_manifest')
    except (ValueError, TypeError):
        raise ValueError('us_calendar_snapshot_time') from None
    return stamp


def load_snapshot(url, *, manifest_file, manifest_sha256, now):
    year = calendar_year(url)
    if year is None:
        raise ValueError('us_calendar_snapshot_url')
    path = Path(manifest_file)
    if not manifest_file or not re.fullmatch(r'[0-9a-f]{64}', manifest_sha256 or '') or path.is_symlink():
        raise ValueError('us_calendar_snapshot_config')
    raw = _read(path, 128 * 1024)
    if hashlib.sha256(raw).hexdigest() != manifest_sha256:
        raise ValueError('us_calendar_snapshot_manifest_digest')
    try:
        value = json.loads(raw)
        if value['schema_version'] != 1 or not isinstance(value['calendars'], list):
            raise ValueError('us_calendar_snapshot_manifest')
        entries = value['calendars']
        years = [e['year'] for e in entries]
        if len(years) != len(set(years)):
            raise ValueError('us_calendar_snapshot_manifest')
        for entry in entries:
            if type(entry['year']) is not int or calendar_year(entry['url']) != entry['year']:
                raise ValueError('us_calendar_snapshot_manifest')
        selected = [e for e in entries if e['year'] == year and e['url'] == url]
        if len(selected) != 1:
            raise ValueError('us_calendar_snapshot_manifest')
        entry = selected[0]
        relative = Path(entry['file'])
        source = path.parent / relative
        if relative.is_absolute() or '..' in relative.parts or source.is_symlink() or not source.resolve().is_relative_to(path.parent.resolve()):
            raise ValueError('us_calendar_snapshot_manifest')
        observed = _timestamp(entry['captured_at'], now)
        body = _read(source, MAX_BYTES)
        if hashlib.sha256(body).hexdigest() != entry['sha256']:
            raise ValueError('us_calendar_snapshot_raw_digest')
    except (KeyError, TypeError, AttributeError, UnicodeError, json.JSONDecodeError):
        raise ValueError('us_calendar_snapshot_manifest') from None
    return SourceBytes(body, observed_at=observed)


def prepare_snapshot(source, destination, *, year, captured_at, now):
    """离线解析通过后写入新目录；激活仍需绑定返回清单的 SHA。"""
    from .us_racing_sources import parse_toba_calendar
    if type(year) is not int or not 1000 <= year <= 9999:
        raise ValueError('us_calendar_snapshot_year')
    observed = _timestamp(captured_at.isoformat(), now)
    url = f'https://toba.org/graded-stakes/{year}-races/'
    raw = _read(Path(source), MAX_BYTES)
    parse_toba_calendar(raw, url=url)
    digest = hashlib.sha256(raw).hexdigest()
    value = dict(schema_version=1, calendars=[dict(year=year, url=url, file=digest+'.html',
        sha256=digest, captured_at=observed.isoformat())])
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=False)
    (root/(digest+'.html')).write_bytes(raw)
    (root/'index.json').write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    return value
