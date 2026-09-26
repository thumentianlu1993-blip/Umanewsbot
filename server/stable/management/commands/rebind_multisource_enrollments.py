"""SHA-bound rebind of enrolled multisource v2 enrollments onto the current policy.

policy 扩版（venue/有效期变化）后，既有登记的 binding/enrollment digest 会漂移
并被 claim/admission fail-closed。本命令按 manifest 逐场换绑到当前 policy 的新
route digest；默认 dry-run，--apply 才写入。identity 不变、不重建、不重抓网络。
"""
import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stable.services.race_data_source_adapters import load_multisource_policy
from stable.services.race_data_sync_enrollment import rebind_multisource_enrollment


class Command(BaseCommand):
    help = "多来源 v2 登记换绑到当前 policy；默认 dry-run，--apply 才写入。"

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--sha256", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, **options):
        try:
            raw = Path(options["manifest"]).read_bytes()
            if len(raw) > 65536 or hashlib.sha256(raw).hexdigest() != options["sha256"]:
                raise ValueError("rebind_manifest_sha_mismatch")
            manifest = json.loads(raw)
            if (
                not isinstance(manifest, dict)
                or manifest.get("schema_version") != 1
                or not isinstance(manifest.get("events"), list)
                or not 1 <= len(manifest["events"]) <= 50
            ):
                raise ValueError("invalid_rebind_manifest")
            now = timezone.now()
            policy = load_multisource_policy(now=now)
            if policy.digest != manifest.get("policy_digest"):
                raise ValueError("rebind_policy_digest_mismatch")
            results = []
            for row in manifest["events"]:
                if not isinstance(row, dict) or not isinstance(row.get("event_id"), int):
                    raise ValueError("invalid_rebind_manifest_row")
                results.append(
                    rebind_multisource_enrollment(
                        event_id=row["event_id"],
                        policy=policy,
                        now=now,
                        expected_route_digest=row.get("old_route_digest", ""),
                        apply=options["apply"],
                    )
                )
                if row.get("new_route_digest") and results[-1].get("new_route_digest") != row["new_route_digest"]:
                    raise ValueError("rebind_target_drift")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(
            {"mode": "apply" if options["apply"] else "dry_run", "results": results},
            ensure_ascii=False, sort_keys=True,
        ))
