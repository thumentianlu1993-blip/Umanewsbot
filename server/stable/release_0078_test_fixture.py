"""为历史 0078/0079 合同提供隔离迁移目录；不改变生产准入检查。"""

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
from stable.services import release_0079_recovery


ROOT = Path(__file__).resolve().parents[2]
RECOVERY_MODULES = {
    "0078": (recovery, Path(recovery.__file__).resolve()),
    "0079": (release_0079_recovery, Path(release_0079_recovery.__file__).resolve()),
}
# 保留旧测试导出：记录导入时真实路径，不随历史夹具的 __file__ patch 改变。
RECOVERY_MODULE = RECOVERY_MODULES["0078"][1]

POST_GENERATION_MIGRATIONS = {
    "0078": {"0079_multisource_race_enrollment.py", "0080_translation_retry_budget.py"},
    "0079": {"0080_translation_retry_budget.py"},
}


def copy_historical_migrations(destination, *, generation="0078"):
    # 仅剔除本次已明确新增的迁移。其余文件仍由原固定 SHA 完整校验，
    # 未来新增文件必须显式维护历史夹具，不能自动跳过未知迁移。
    source = ROOT / "server/stable/migrations"
    excluded = POST_GENERATION_MIGRATIONS[generation]
    shutil.copytree(
        source,
        destination,
        ignore=lambda directory, names: (
            [name for name in names if name in excluded]
            if Path(directory) == source
            else []
        ),
    )


def use_historical_migration_contract(
    test_case, *, isolate_django_migrations=False, generation="0078"
):
    module, module_source = RECOVERY_MODULES[generation]
    temporary = tempfile.TemporaryDirectory()
    test_case.addCleanup(temporary.cleanup)
    root = Path(temporary.name)
    services = root / "stable/services"
    services.mkdir(parents=True)
    copy_historical_migrations(root / "stable/migrations", generation=generation)
    module_path = services / module_source.name
    module_path.write_bytes(module_source.read_bytes())
    context = patch.object(module, "__file__", str(module_path))
    context.start()
    test_case.addCleanup(context.stop)
    # 真实执行原始散列校验；不 stub 返回值或改写预期散列。
    module.migration_contract()

    if isolate_django_migrations:
        directory = root / "stable/migrations"
        name = "historical_" + generation + "_migrations_" + uuid.uuid4().hex
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
