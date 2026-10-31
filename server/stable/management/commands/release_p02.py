"""P02镜像内预检与唯一DDL入口；不调用旧代际或裸migrate命令。"""

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from stable.services import release_p02_recovery as c
from stable.services import release_p02_schema as schema
from stable.services import release_p02_executor as engine


def runtime_bindings():
    bindings = json.loads(os.environ.get("P02_RELEASE_BINDINGS", "{}"))
    c.validate_bindings(bindings, bindings)
    if Path("/app/.umanews-release-commit").read_text().strip() != bindings["candidate_commit"]:
        raise ValueError("P02 candidate image code revision differs")
    return bindings


security_snapshot = schema.security_snapshot

class Command(BaseCommand):
    help = "P02关闭态schema预检/迁移；必须由同候选宿主协调器调用。"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("state", "closed", "apply", "restore-proof", "readonly"))
        parser.add_argument("--directory", type=Path)
        parser.add_argument("--intent-sha256", default="")

    def handle(self, *args, **options):
        try:
            bindings = runtime_bindings()
            engine.assert_closed_settings()
            action = options["action"]
            if action == "apply":
                if options["directory"] is None:
                    raise ValueError("P02 original intent directory is required")
                result = engine.apply(options["directory"], options["intent_sha256"], bindings)
            else:
                result = schema.state()
                # 恢复演练连接必须是独立库；其身份由宿主与原库比较，不能冒充原库。
                if action != "restore-proof" and result["database_identity_sha256"] != bindings["database_identity_sha256"]:
                    raise ValueError("P02 actual database identity differs")
                if action in {"closed", "restore-proof"}:
                    schema.assert_no_other_clients()
                    result.update(counts_sha256=c.digest(schema.counts()), security_sha256=security_snapshot())
                if action == "readonly":
                    with connection.cursor() as cursor:
                        cursor.execute("SHOW default_transaction_read_only")
                        if cursor.fetchone()[0] != "on":
                            raise ValueError("P02 probe database connection is not readonly")
                    result["readonly"] = True
            self.stdout.write(c.encoded(result).decode())
        except (ValueError, OSError, KeyError, TypeError) as exc:
            # 不输出连接串、底层SQL参数或任何子进程原始输出。
            raise CommandError("P02 container release contract refused") from exc
