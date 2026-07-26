"""一次性 lifecycle control 纳管命令。默认 dry-run 零写入。"""

import hashlib
import json
import re
import sys
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Q

from stable.models import RaceEvent, RaceEventStatus
from stable.services.race_event_lifecycle import reconcile_lifecycle_controls

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_VALID_MODES = frozenset({"off", "shadow", "enforce"})
_US_ZONE_RE = re.compile(r"^America/")
MANIFEST_SCHEMA_VERSION = 1


class Command(BaseCommand):
    help = "纳管/同步 RaceEvent lifecycle controls（默认 dry-run）"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--manifest-file")
        parser.add_argument("--manifest-sha256")
        parser.add_argument("--event-ids", nargs="*", type=int)
        parser.add_argument("--auto-discover", action="store_true")
        parser.add_argument("--default-mode", choices=["off", "shadow", "enforce"], default="shadow")
        parser.add_argument("--page-size", type=int, default=500)

    def handle(self, **options):
        apply = options["apply"]
        manifest_file = options.get("manifest_file") or ""
        manifest_sha = (options.get("manifest_sha256") or "").strip()
        event_ids = options["event_ids"]
        auto_discover = options["auto_discover"]
        default_mode = options["default_mode"]
        page_size = options["page_size"]

        if apply:
            if not manifest_file or not manifest_sha:
                self.stderr.write(self.style.ERROR("--apply 需同时提供 --manifest-file 和 --manifest-sha256"))
                sys.exit(1)
            path = Path(manifest_file)
            if not path.is_file():
                self.stderr.write(self.style.ERROR(f"manifest 文件不存在: {manifest_file}"))
                sys.exit(1)
            try:
                raw = path.read_bytes()
            except OSError as e:
                self.stderr.write(self.style.ERROR(f"无法读取 manifest: {e}"))
                sys.exit(1)
            computed = hashlib.sha256(raw).hexdigest()
            if computed != manifest_sha:
                self.stderr.write(self.style.ERROR(
                    f"manifest SHA 不匹配: 提供={manifest_sha} 计算={computed}"
                ))
                sys.exit(1)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                self.stderr.write(self.style.ERROR(f"manifest JSON 解析失败: {e}"))
                sys.exit(1)
            if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
                self.stderr.write(self.style.ERROR(f"schema_version 需为 {MANIFEST_SCHEMA_VERSION}"))
                sys.exit(1)
            events_cfg = data.get("events")
            if not isinstance(events_cfg, dict) or not events_cfg:
                self.stderr.write(self.style.ERROR("manifest.events 为空"))
                sys.exit(1)

            ids, target_modes, us_zones_map, eligibility, schedule_hashes, regions = (
                _validate_and_extract(events_cfg)
            )
            _check_us_timezone_drift(ids, regions, us_zones_map)
            self.stdout.write(f"manifest SHA 核对通过 ✓  {len(ids)} 个赛事 (APPLY)")
            self._run(ids, target_modes, us_zones_map, eligibility, schedule_hashes,
                      manifest_sha, page_size, apply=True)
        else:
            if event_ids:
                ids = list(event_ids)
            elif auto_discover:
                limit = 2000
                ids = list(
                    RaceEvent.objects.filter(visibility_status="published")
                    .filter(Q(priority__in=("P0", "P1")) | Q(is_featured=True))
                    .exclude(status=RaceEventStatus.CANCELLED)
                    .order_by("id").values_list("id", flat=True)[:limit]
                )
                suffix = f"（上限 {limit}）" if len(ids) >= limit else ""
                self.stdout.write(f"自动发现 {len(ids)} 个赛事{suffix} (DRY-RUN)")
            elif manifest_file:
                path = Path(manifest_file)
                if not path.is_file():
                    self.stderr.write(f"manifest 文件不存在: {manifest_file}")
                    sys.exit(1)
                raw = path.read_bytes()
                computed = hashlib.sha256(raw).hexdigest()
                if manifest_sha and manifest_sha != computed:
                    self.stderr.write(self.style.ERROR(
                        f"manifest SHA 不匹配: 提供={manifest_sha} 计算={computed}"
                    ))
                    sys.exit(1)
                data = json.loads(raw)
                events_cfg = data.get("events", {})
                ids = [int(k) for k in events_cfg]
                sha_label = manifest_sha or computed
                self.stdout.write(f"manifest SHA={sha_label} {len(ids)} 个赛事 (DRY-RUN)")
            elif not sys.stdin.isatty():
                raw = sys.stdin.read()
                try:
                    ids = json.loads(raw)
                    if not isinstance(ids, list):
                        self.stderr.write("stdin JSON 必须为数组")
                        sys.exit(1)
                except json.JSONDecodeError as e:
                    self.stderr.write(f"stdin 解析失败: {e}")
                    sys.exit(1)
            else:
                self.stderr.write("请提供 --event-ids / --auto-discover / --manifest-file / stdin")
                return
            if not ids:
                self.stdout.write("无 event IDs")
                return
            target_modes = {str(eid): default_mode for eid in ids}
            self._run(ids, target_modes, {}, {}, {}, manifest_sha or "dry-run", page_size, apply=False)

    def _run(self, ids, target_modes, us_zones_map, eligibility, schedule_hashes,
             manifest_sha, page_size, apply):
        total = len(ids)
        aggr = {"created": 0, "updated": 0, "disabled": 0, "replayed": 0, "ineligible": 0,
                "eligible_transition": 0, "eligible_noop": 0, "eligible_error": 0}
        for offset in range(0, total, page_size):
            page = ids[offset: offset + page_size]
            modes = {str(eid): target_modes.get(str(eid), "shadow") for eid in page}
            for sid, zones in us_zones_map.items():
                modes[f"us_zones:{sid}"] = zones
            for sid, sh in schedule_hashes.items():
                modes[f"schedule_hash:{sid}"] = sh
            stats = reconcile_lifecycle_controls(
                event_ids=page, manifest_sha256=manifest_sha,
                apply=apply, target_modes=modes,
                eligibility_snapshot=eligibility or None,
            )
            for k in aggr:
                aggr[k] += stats.get(k, 0)
            extra = ""
            if not apply:
                t, n, e = stats.get("eligible_transition", 0), stats.get("eligible_noop", 0), stats.get("eligible_error", 0)
                if t or n or e:
                    extra = f"  决策:→{t} 不变:{n} 错:{e}"
            self.stdout.write(
                f"  页{offset//page_size+1}: 建={stats.get('created',0)}"
                f" 更={stats.get('updated',0)} 禁={stats.get('disabled',0)}"
                f" 重放={stats.get('replayed',0)} 不合格={stats.get('ineligible',0)}{extra}"
            )
        label = "APPLY" if apply else "DRY-RUN"
        decision_summary = ""
        if not apply:
            dt, dn, de = aggr["eligible_transition"], aggr["eligible_noop"], aggr["eligible_error"]
            decision_summary = f" decisions:→{dt}不变:{dn}错:{de}"
        self.stdout.write(self.style.SUCCESS(
            f"[{label}] total={total} created={aggr['created']} updated={aggr['updated']}"
            f" disabled={aggr['disabled']} replayed={aggr['replayed']}"
            f" ineligible={aggr['ineligible']}{decision_summary}"
        ))


def _check_us_timezone_drift(event_ids, manifest_regions, us_zones_map):
    for eid in event_ids:
        try:
            event = RaceEvent.objects.only("timezone_name", "country_region").get(id=eid)
        except RaceEvent.DoesNotExist:
            _fail(f"event {eid}: 数据库不存在")
        mreg = manifest_regions.get(eid, "")
        if mreg and mreg != event.country_region:
            _fail(f"event {eid}: manifest region={mreg!r} != DB {event.country_region!r}")
        if event.country_region == "united_states":
            zones = us_zones_map.get(str(eid))
            if not zones:
                _fail(f"event {eid}: 美国赛事需 allowed_us_zones")
            if event.timezone_name not in zones:
                _fail(f"event {eid}: timezone {event.timezone_name!r} 不在 manifest zones {zones} 中")


def _validate_and_extract(events_cfg):
    ids, seen = [], set()
    target_modes, us_zones_map, eligibility, schedule_hashes, regions = {}, {}, {}, {}, {}
    for key, cfg in events_cfg.items():
        try:
            eid = int(key)
        except (ValueError, TypeError):
            _fail(f"key {key!r} 不是整数 event ID")
        if eid <= 0:
            _fail(f"key {key} <= 0")
        if eid in seen:
            _fail(f"event ID {eid} 重复")
        seen.add(eid); ids.append(eid)
        if not isinstance(cfg, dict):
            _fail(f"event {eid}: cfg 需为 object")
        region = cfg.get("region", "")
        if not isinstance(region, str) or not region:
            _fail(f"event {eid}: region 必填")
        regions[eid] = region
        mode = cfg.get("mode", "")
        if mode not in _VALID_MODES:
            _fail(f"event {eid}: mode={mode!r} 需为 shadow|enforce|off")
        target_modes[str(eid)] = mode
        elig = cfg.get("eligibility")
        if not isinstance(elig, dict):
            _fail(f"event {eid}: eligibility 需为 object")
        for fld in ("is_key_race", "is_published", "is_cancelled"):
            if fld not in elig or not isinstance(elig[fld], bool):
                _fail(f"event {eid}: eligibility.{fld} 需为 boolean")
        eligibility[str(eid)] = {fld: elig[fld] for fld in ("is_key_race", "is_published", "is_cancelled")}
        sh = cfg.get("enrollment_schedule_hash", "")
        if not _SHA256_HEX.match(sh):
            _fail(f"event {eid}: enrollment_schedule_hash 需为 64 位 hex")
        schedule_hashes[str(eid)] = sh
        zones = cfg.get("allowed_us_zones")
        if region == "united_states":
            if not isinstance(zones, list) or len(zones) == 0:
                _fail(f"event {eid}: US 赛事 allowed_us_zones 必填非空")
            for z in zones:
                if not isinstance(z, str) or not _US_ZONE_RE.match(z):
                    _fail(f"event {eid}: {z!r} 不是 America/*")
            us_zones_map[str(eid)] = list(zones)
        elif isinstance(zones, list) and len(zones) > 0:
            for z in zones:
                if not isinstance(z, str) or not _US_ZONE_RE.match(z):
                    _fail(f"event {eid}: {z!r} 不是 America/*")
            us_zones_map[str(eid)] = list(zones)
        elif zones is not None:
            _fail(f"event {eid}: allowed_us_zones 需为数组或省略")
    return ids, target_modes, us_zones_map, eligibility, schedule_hashes, regions


def _fail(msg):
    sys.stderr.write(f"manifest 校验: {msg}\n")
    sys.exit(1)
