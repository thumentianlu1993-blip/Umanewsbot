from __future__ import annotations

import json
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from stable import models
from stable.services.race_live_publication_transition import (
    RaceLivePublicationTransitionError,
    read_manual_official_route_registry,
)


def _aware_datetime(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CommandError(f"{label} 必须是合法 ISO-8601 时间") from exc
    if timezone.is_naive(parsed):
        raise CommandError(f"{label} 必须包含时区")
    return parsed


class Command(BaseCommand):
    help = "离线校验并以 CAS 方式授权单赛事正式/改判赛果公开"

    def add_arguments(self, parser):
        parser.add_argument("--event-id", type=int, required=True)
        parser.add_argument(
            "--max-phase",
            choices=(
                models.RaceResultPhase.OFFICIAL,
                models.RaceResultPhase.CORRECTED,
            ),
            required=True,
        )
        parser.add_argument("--valid-until", required=True)
        parser.add_argument("--expected-version", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm", default="")

    def handle(self, *args, **options):
        event_id = options["event_id"]
        expected_version = options["expected_version"]
        if event_id <= 0:
            raise CommandError("event-id 必须是正整数")
        if expected_version < 0:
            raise CommandError("expected-version 不得为负数")
        valid_until = _aware_datetime(
            options["valid_until"],
            label="valid-until",
        )
        now = timezone.now()
        if valid_until <= now:
            raise CommandError("valid-until 必须晚于当前时间")
        expected_confirmation = f"AUTHORIZE_OFFICIAL_EVENT_{event_id}"
        if options["apply"] and options["confirm"] != expected_confirmation:
            raise CommandError(
                f"apply 必须提供 --confirm {expected_confirmation}"
            )

        event = models.RaceEvent.objects.filter(pk=event_id).first()
        allowlist = models.RaceLiveEventPublicationAllowlist.objects.filter(
            event_id=event_id,
            source_key="the_racing_api",
        ).first()
        if event is None or allowlist is None:
            raise CommandError("赛事或 TRA publication allowlist 不存在")
        if allowlist.enabled is not True:
            raise CommandError("TRA publication allowlist 未启用")
        if (
            allowlist.official_verification_valid_until is None
            or timezone.is_naive(
                allowlist.official_verification_valid_until
            )
            or allowlist.official_verification_valid_until < valid_until
        ):
            raise CommandError("授权时间超出 official verification allowlist")
        try:
            route_registry, route_registry_digest = (
                read_manual_official_route_registry(
                    route=allowlist.official_verification_route,
                    now=now,
                )
            )
        except RaceLivePublicationTransitionError as exc:
            raise CommandError(str(exc)) from exc
        if route_registry["country_region"] != event.country_region:
            raise CommandError("official route 地区与赛事不匹配")
        route_contract = {
            "route_version": route_registry["parser_version"],
            "contract_digest": route_registry["contract_digest"],
            "terms_evidence_digest": route_registry["terms_evidence"]["sha256"],
        }
        allowlist_contract = {
            "route_version": allowlist.official_verification_route_version,
            "contract_digest": (
                allowlist.official_verification_contract_digest
            ),
            "terms_evidence_digest": (
                allowlist.official_terms_evidence_digest
            ),
        }
        if route_contract != allowlist_contract:
            raise CommandError("official route registry 与 allowlist 不匹配")

        current = (
            models.RaceLiveOfficialPublicationAuthorization.objects.filter(
                event_id=event_id
            ).first()
        )
        current_version = current.version if current else 0
        if current_version != expected_version:
            raise CommandError(
                "official authorization version CAS 不匹配："
                f"expected={expected_version}, current={current_version}"
            )
        desired_values = {
            "source_key": route_registry["source_key"],
            "route": route_registry["route"],
            "route_version": route_registry["parser_version"],
            "route_registry_digest": route_registry_digest,
            "contract_digest": route_registry["contract_digest"],
            "terms_evidence_digest": (
                route_registry["terms_evidence"]["sha256"]
            ),
            "coverage_proof_digest": allowlist.coverage_proof_digest,
            "max_phase": options["max_phase"],
            "enabled": True,
            "valid_until": valid_until,
        }
        replayed = current is not None and all(
            getattr(current, field) == value
            for field, value in desired_values.items()
        )
        result = {
            "mode": "apply" if options["apply"] else "dry_run",
            "event_id": event_id,
            "country_region": event.country_region,
            "source_key": route_registry["source_key"],
            "route": route_registry["route"],
            "route_version": route_registry["parser_version"],
            "route_registry_digest": route_registry_digest,
            "contract_digest": route_registry["contract_digest"],
            "terms_evidence_digest": (
                route_registry["terms_evidence"]["sha256"]
            ),
            "coverage_proof_digest": allowlist.coverage_proof_digest,
            "max_phase": options["max_phase"],
            "valid_until": valid_until.isoformat(),
            "expected_version": expected_version,
            "new_version": (
                expected_version
                if replayed
                else expected_version + 1
            ),
            "replayed": replayed,
        }
        if not options["apply"]:
            self.stdout.write(
                json.dumps(result, ensure_ascii=False, sort_keys=True)
            )
            return

        with transaction.atomic():
            if (
                settings.RACE_LIVE_SCHEDULER_ENABLED is not False
                or settings.RACE_LIVE_MONITOR_ENABLED is not False
            ):
                raise CommandError(
                    "official authorization apply 要求 scheduler/monitor=false"
                )
            list(
                models.RaceEventProjectionControl.objects.select_for_update()
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            active_attempt_tokens = list(
                models.RaceEventLiveTracking.objects.select_for_update()
                .order_by("pk")
                .values_list("active_attempt_token", flat=True)
            )
            if any(active_attempt_tokens):
                raise CommandError(
                    "official authorization apply 要求 active claims=0"
                )
            locked_event = (
                models.RaceEvent.objects.select_for_update()
                .filter(pk=event_id)
                .first()
            )
            locked_allowlist = (
                models.RaceLiveEventPublicationAllowlist.objects.select_for_update()
                .filter(pk=allowlist.pk)
                .first()
            )
            authorization = (
                models.RaceLiveOfficialPublicationAuthorization.objects.select_for_update()
                .filter(event_id=event_id)
                .first()
            )
            if (
                locked_event is None
                or locked_allowlist is None
                or locked_allowlist.updated_at != allowlist.updated_at
                or (authorization.version if authorization else 0)
                != expected_version
            ):
                raise CommandError("official authorization 基线已变化")
            locked_replayed = authorization is not None and all(
                getattr(authorization, field) == value
                for field, value in desired_values.items()
            )
            if locked_replayed != replayed:
                raise CommandError(
                    "official authorization replay 基线已变化"
                )
            values = dict(desired_values)
            values["coverage_proof_digest"] = (
                locked_allowlist.coverage_proof_digest
            )
            values["version"] = (
                expected_version
                if locked_replayed
                else expected_version + 1
            )
            if authorization is None:
                authorization = (
                    models.RaceLiveOfficialPublicationAuthorization.objects.create(
                        event=locked_event,
                        **values,
                    )
                )
            elif not locked_replayed:
                for field, value in values.items():
                    setattr(authorization, field, value)
                authorization.save(
                    update_fields=tuple(values) + ("updated_at",)
                )
            result["authorization_id"] = authorization.pk
            if models.RaceEventRevision.objects.filter(
                event_id=event_id,
                kind=models.RaceEventRevisionKind.RESULT,
                phase__in=(
                    models.RaceResultPhase.OFFICIAL,
                    models.RaceResultPhase.CORRECTED,
                ),
                published_at__isnull=True,
            ).exists():
                from stable.services.race_live_manual_official_evidence import (
                    publish_authorized_staged_official_revision,
                )

                published = publish_authorized_staged_official_revision(
                    event_id=event_id,
                    now=now,
                )
                result["published_revision_id"] = published.pk

        self.stdout.write(
            json.dumps(result, ensure_ascii=False, sort_keys=True)
        )
