"""固定范围、多来源 legacy 转换工具；默认只读，apply 必须关闭运行开关。"""

import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from stable.services.race_data_source_adapters import load_multisource_policy
from stable.services.race_data_sync_repair import (
    prepare_multisource_conversion,
    apply_multisource_conversion,
    verify_multisource_conversion,
)


class Command(BaseCommand):
    help = "多来源登记固定清单 prepare/dry-run/apply/verify；不联网、不修正历史发布"

    def add_arguments(self, parser):
        parser.add_argument(
            "operation", choices=("prepare", "dry-run", "apply", "verify")
        )
        parser.add_argument(
            "--input",
            required=True,
            help="绝对路径，prepare为新观测数组，其余为已冻结manifest",
        )
        parser.add_argument("--input-sha256", required=True, help="输入文件字节SHA256")
        parser.add_argument(
            "--code-sha", required=True, help="当前受审40位代码SHA；须与manifest一致"
        )

    def handle(self, *args, **options):
        try:
            path = Path(options["input"])
            if (
                not path.is_absolute()
                or path.is_symlink()
                or path.stat().st_size > 2 * 1024 * 1024
            ):
                raise ValueError("input_path_invalid")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != options["input_sha256"]:
                raise ValueError("input_sha_mismatch")
            value = json.loads(raw)
            now = timezone.now()
            if options["operation"] == "verify":
                result = verify_multisource_conversion(manifest=value)
                if not all(r["verified"] for r in result):
                    raise ValueError("conversion_verify_failed")
            else:
                policy = load_multisource_policy(now=now)
                if options["operation"] == "prepare":
                    result = prepare_multisource_conversion(
                        observations=value,
                        policy=policy,
                        now=now,
                        code_sha=options["code_sha"],
                    )
                else:
                    result = apply_multisource_conversion(
                        manifest=value,
                        expected_sha256=value["manifest_sha256"],
                        policy=policy,
                        now=now,
                        code_sha=options["code_sha"],
                        apply=options["operation"] == "apply",
                    )
        except (ValueError, KeyError, TypeError, OSError) as exc:
            # 不输出源正文/凭据或完整传输异常。
            code = str(exc)
            if not __import__("re").fullmatch("[a-z_]{1,64}", code):
                code = "conversion_failed"
            raise CommandError(code) from None
        self.stdout.write(
            json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
        )
