"""为历史 0078 合同提供隔离的迁移目录；不改变生产准入检查。"""

from pathlib import Path
import shutil
import importlib
import sys
import uuid
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from stable.services import release_0078_recovery as recovery


ROOT = Path(__file__).resolve().parents[2]
RECOVERY_MODULE = Path(recovery.__file__).resolve()


def copy_historical_migrations(destination):
    # 仅剔除本次已明确新增的迁移。其余文件仍由原固定 SHA 完整校验，
    # 未来新增文件必须显式维护历史夹具，不能自动跳过未知迁移。
    source = ROOT / "server/stable/migrations"
    shutil.copytree(
        source,
        destination,
        ignore=lambda directory, names: (
            ["0079_multisource_race_enrollment.py"]
            if Path(directory) == source
            else []
        ),
    )


def use_historical_migration_contract(test_case, *, isolate_django_migrations=False):
    temporary = tempfile.TemporaryDirectory()
    test_case.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    services = root / "stable/services"
    services.mkdir(parents=True)
    copy_historical_migrations(root / "stable/migrations")
    module_path = services / RECOVERY_MODULE.name
    module_path.write_bytes(RECOVERY_MODULE.read_bytes())
    context = patch.object(recovery, "__file__", str(module_path))
    context.start()
    test_case.addCleanup(context.stop)
    # 真实执行原始散列校验；不 stub 返回值或改写预期散列。
    recovery.migration_contract()

    if isolate_django_migrations:
        directory = root / "stable/migrations"
        name = "historical_0078_migrations_" + uuid.uuid4().hex
        shutil.copytree(directory, root / name)
        sys.path.insert(0, str(root))
        test_case.addCleanup(lambda: sys.path.remove(str(root)))
        importlib.import_module(name)

        def clear_modules():
            for key in list(sys.modules):
                if key == name or key.startswith(name + "."):
                    del sys.modules[key]

        test_case.addCleanup(clear_modules)
        override = override_settings(MIGRATION_MODULES={**settings.MIGRATION_MODULES, "stable": name})
        override.enable()
        test_case.addCleanup(override.disable)
