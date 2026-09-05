from __future__ import annotations

from datetime import datetime
import hashlib
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable import models
from stable.services.race_data_sync_pipeline import (
    _EVENT_REGION_BY_CONTRACT_REGION,
    build_race_data_provider_roster,
    resolve_race_data_provider_route,
)


def _iso(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CommandError(f"{label} 必须是 ISO-8601 时间") from exc
    if timezone.is_naive(parsed):
        raise CommandError(f"{label} 必须包含时区")
    return parsed


class Command(BaseCommand):
    help = "按当前已启用 provider roster 渲染一次全局 standing policy（只输出，不写文件）"

    def add_arguments(self, parser):
        parser.add_argument("--policy-id", required=True)
        parser.add_argument("--approved-by", required=True)
        parser.add_argument("--approved-at", required=True)
        parser.add_argument("--valid-from", required=True)
        parser.add_argument("--valid-until", required=True)
        parser.add_argument("--digest-only", action="store_true")

    def handle(self, **options):
        approved_at = _iso(options["approved_at"], "--approved-at")
        valid_from = _iso(options["valid_from"], "--valid-from")
        valid_until = _iso(options["valid_until"], "--valid-until")
        if valid_until <= valid_from:
            raise CommandError("standing policy 有效期无效")
        routes = []
        roster = build_race_data_provider_roster()
        for entry in roster.entries:
            if not entry.enabled_data_kinds:
                continue
            for contract_region in entry.regions:
                country_region = _EVENT_REGION_BY_CONTRACT_REGION.get(
                    contract_region
                )
                if country_region is None:
                    continue
                for identity_namespace in entry.identity_namespaces:
                    route = resolve_race_data_provider_route(
                        provider=entry.provider,
                        region=contract_region,
                        identity_namespace=identity_namespace,
                        data_kinds=entry.enabled_data_kinds,
                    )
                    if route is None:
                        continue
                    routes.append(
                        {
                            "country_region": country_region,
                            "provider": entry.provider,
                            "region_code": contract_region,
                            "identity_namespace": identity_namespace,
                            "route_digest": route.route_digest,
                            "data_kinds": list(entry.enabled_data_kinds),
                            "enrollment_eligible": (
                                tuple(sorted(set(entry.enabled_data_kinds)))
                                == tuple(sorted(models.RaceDataSyncDataKind.values))
                            ),
                        }
                    )
        if not routes:
            raise CommandError("当前配置没有可运行的 provider route")
        routes.sort(
            key=lambda row: (
                row["country_region"],
                row["provider"],
                row["region_code"],
                row["identity_namespace"],
            )
        )
        tiebreak_counters: dict[str, int] = {}
        for wanted in (True, False):
            for route_row in routes:
                if route_row["enrollment_eligible"] is not wanted:
                    continue
                region = route_row["country_region"]
                tiebreak_counters[region] = tiebreak_counters.get(region, 0) + 1
                route_row["tiebreak_order"] = tiebreak_counters[region]
        payload = {
            "schema_version": 2,
            "policy_id": options["policy_id"],
            "approved_by": options["approved_by"],
            "approved_at": approved_at.isoformat(),
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "routes": routes,
            "visibility_statuses": [models.RaceEventVisibility.PUBLISHED],
            "new_enrollment_statuses": [
                models.RaceEventStatus.POSTPONED,
                models.RaceEventStatus.SCHEDULED,
            ],
            "continuation_statuses": [
                models.RaceEventStatus.FINISHED,
                models.RaceEventStatus.POSTPONED,
                models.RaceEventStatus.RUNNING,
                models.RaceEventStatus.SCHEDULED,
            ],
        }
        rendered = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        if options["digest_only"]:
            self.stdout.write(hashlib.sha256(rendered.encode()).hexdigest())
        else:
            self.stdout.write(rendered, ending="")
