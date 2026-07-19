from __future__ import annotations

import json
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from stable import models


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SCOPE_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_REGIONS = {
    models.RacingRegion.UNITED_KINGDOM,
    models.RacingRegion.FRANCE,
    models.RacingRegion.HONG_KONG,
    models.RacingRegion.JAPAN,
    models.RacingRegion.UNITED_STATES,
}


class Command(BaseCommand):
    help = "以离线 dry-run + CAS 方式提升一个 race-live publication scope"

    def add_arguments(self, parser):
        parser.add_argument(
            "--scope-type",
            choices=(
                models.RaceLivePublicationScopeType.GLOBAL,
                models.RaceLivePublicationScopeType.REGION,
                models.RaceLivePublicationScopeType.SOURCE,
                models.RaceLivePublicationScopeType.EVENT,
            ),
            required=True,
        )
        parser.add_argument("--scope-key", required=True)
        parser.add_argument(
            "--target-mode",
            choices=(
                models.RaceLivePublicationMode.PROVISIONAL_PUBLIC,
                models.RaceLivePublicationMode.OFFICIAL_PUBLIC,
            ),
            required=True,
        )
        parser.add_argument("--expected-version", type=int, required=True)
        parser.add_argument("--registry-sha256", required=True)
        parser.add_argument("--coverage-sha256", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--confirm", default="")

    def handle(self, *args, **options):
        scope_type = options["scope_type"]
        scope_key = options["scope_key"]
        target_mode = options["target_mode"]
        expected_version = options["expected_version"]
        if (
            settings.RACE_LIVE_SCHEDULER_ENABLED is not False
            or settings.RACE_LIVE_MONITOR_ENABLED is not False
        ):
            raise CommandError(
                "scope transition 要求 scheduler/monitor=false"
            )
        if (
            not isinstance(scope_key, str)
            or _SCOPE_KEY_RE.fullmatch(scope_key) is None
            or expected_version < 1
            or _SHA256_RE.fullmatch(options["registry_sha256"]) is None
            or _SHA256_RE.fullmatch(options["coverage_sha256"]) is None
        ):
            raise CommandError("scope transition 参数不合法")
        if (
            (scope_type == models.RaceLivePublicationScopeType.GLOBAL and scope_key != "global")
            or (
                scope_type == models.RaceLivePublicationScopeType.REGION
                and scope_key not in _REGIONS
            )
            or (
                scope_type == models.RaceLivePublicationScopeType.SOURCE
                and scope_key != "the_racing_api"
            )
            or (
                scope_type == models.RaceLivePublicationScopeType.EVENT
                and not scope_key.isdigit()
            )
        ):
            raise CommandError("scope type/key 不匹配")
        if (
            scope_type == models.RaceLivePublicationScopeType.SOURCE
            and target_mode
            != models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
        ):
            raise CommandError("TRA source scope 不得取得 official 权限")
        if (
            scope_type == models.RaceLivePublicationScopeType.EVENT
            and target_mode
            != models.RaceLivePublicationMode.OFFICIAL_PUBLIC
        ):
            raise CommandError("event provisional 必须使用 event promotion bundle")
        expected_confirmation = (
            f"TRANSITION_RACE_LIVE_SCOPE_{scope_type}_{scope_key}"
        )
        if options["apply"] and options["confirm"] != expected_confirmation:
            raise CommandError(
                f"apply 必须提供 --confirm {expected_confirmation}"
            )

        policy = models.RaceLivePublicationPolicy.objects.filter(
            scope_type=scope_type,
            scope_key=scope_key,
        ).first()
        now = timezone.now()
        if policy is None:
            raise CommandError("publication scope policy 不存在")
        if (
            policy.version != expected_version
            or policy.registry_digest != options["registry_sha256"]
            or policy.coverage_proof_digest != options["coverage_sha256"]
            or policy.valid_until is None
            or timezone.is_naive(policy.valid_until)
            or policy.valid_until <= now
        ):
            raise CommandError("publication scope policy CAS 基线不匹配")
        transition = {
            models.RaceLivePublicationMode.SHADOW: (
                models.RaceLivePublicationMode.PROVISIONAL_PUBLIC
            ),
            models.RaceLivePublicationMode.PROVISIONAL_PUBLIC: (
                models.RaceLivePublicationMode.OFFICIAL_PUBLIC
            ),
        }.get(policy.mode)
        if transition != target_mode:
            raise CommandError("publication scope 只允许逐级提升")
        if scope_type == models.RaceLivePublicationScopeType.EVENT:
            authorization = (
                models.RaceLiveOfficialPublicationAuthorization.objects.filter(
                    event_id=int(scope_key),
                    enabled=True,
                    valid_until__gt=now,
                ).first()
            )
            if authorization is None:
                raise CommandError("event official authorization 尚未启用")

        result = {
            "mode": "apply" if options["apply"] else "dry_run",
            "scope_type": scope_type,
            "scope_key": scope_key,
            "from_mode": policy.mode,
            "target_mode": target_mode,
            "expected_version": expected_version,
            "new_version": expected_version + 1,
            "registry_digest": policy.registry_digest,
            "coverage_proof_digest": policy.coverage_proof_digest,
            "valid_until": policy.valid_until.isoformat(),
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
                    "scope transition apply 要求 scheduler/monitor=false"
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
                    "scope transition apply 要求 active claims=0"
                )
            locked = (
                models.RaceLivePublicationPolicy.objects.select_for_update()
                .filter(pk=policy.pk)
                .first()
            )
            if (
                locked is None
                or locked.mode != policy.mode
                or locked.version != expected_version
                or locked.registry_digest != policy.registry_digest
                or locked.coverage_proof_digest
                != policy.coverage_proof_digest
                or locked.valid_until != policy.valid_until
            ):
                raise CommandError("publication scope policy CAS 漂移")
            locked.mode = target_mode
            locked.version = expected_version + 1
            locked.save(update_fields=("mode", "version", "updated_at"))
            models.OperationLog.objects.create(
                action_type="race_live_publication_scope_transition",
                target_type="race_live_publication_policy",
                target_id=str(locked.pk),
                detail=json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        self.stdout.write(
            json.dumps(result, ensure_ascii=False, sort_keys=True)
        )
