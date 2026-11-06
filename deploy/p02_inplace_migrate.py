#!/usr/bin/env python3
"""精确发布包的单事务迁移步骤；宿主先持有发布锁、停写并验证冷备。

本步骤不接收旧恢复proof，不声称完成整库恢复或上线；不提供fake/反向迁移。
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))


def apply(*, database_identity, source_catalog, migration_contract):
    from django.db import connection, transaction
    from django.db.migrations.executor import MigrationExecutor
    from stable.services import release_p02_recovery as contract
    from stable.services import release_p02_schema as schema
    from stable.services.release_p02_executor import assert_closed_settings, migration_lock

    for value in (database_identity, source_catalog, migration_contract):
        if not contract.hex_value(value):
            raise ValueError('exact database/catalog/migration digest required')
    if migration_contract != contract.migration_contract():
        raise ValueError('migration files differ from approved package')
    if connection.in_atomic_block:
        raise ValueError('migration step must own its transaction')
    assert_closed_settings()
    with migration_lock():
        initial = schema.state()
        if (initial['prefix'] != 0 or initial['database_identity_sha256'] != database_identity
                or initial['catalog_sha256'] != source_catalog):
            raise ValueError('source database differs from approved package')
        schema.assert_no_other_clients()
        executor = MigrationExecutor(connection)
        target = ('stable', contract.STEPS[-1])
        plan = executor.migration_plan([target])
        expected = [('stable', name, False) for name in contract.STEPS]
        if [(m.app_label, m.name, backwards) for m, backwards in plan] != expected:
            raise ValueError('migration plan differs from six approved forward migrations')
        if any(not migration.atomic for migration, _ in plan):
            raise ValueError('non-atomic migration refused')
        # 六步处于同一事务；任何DDL或catalog检查失败均整体回滚。
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='5s'")
                cursor.execute("SET LOCAL statement_timeout='120s'")
            schema.assert_no_other_clients()
            executor.migrate([target], plan=plan)
            frozen = schema.catalog_contract()
            if contract.applied_prefix(frozen['source_recorder'], schema.recorder()) != len(contract.STEPS):
                raise ValueError('target migration recorder differs')
            actual = contract.digest(schema.normalized_catalog(schema.collect_catalog(), frozen))
            if actual != frozen['states'][-1]['canonical_catalog_sha256']:
                raise ValueError('target catalog differs; rolling back transaction')
        return {'status': 'schema_complete_only', 'database_identity_sha256': database_identity,
                'catalog_sha256': actual, 'migration_contract_sha256': migration_contract}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-identity', required=True)
    parser.add_argument('--source-catalog', required=True)
    parser.add_argument('--migration-contract', required=True)
    args = parser.parse_args()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')
    import django
    django.setup()
    import json
    print(json.dumps(apply(database_identity=args.database_identity,
                           source_catalog=args.source_catalog,
                           migration_contract=args.migration_contract)))


if __name__ == '__main__':
    main()
