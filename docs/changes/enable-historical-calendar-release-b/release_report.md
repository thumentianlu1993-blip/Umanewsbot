# Release B 首次生产发布报告

## 结果

`2026-08-08` 首次生产发布未完成。发布在 Django migration consistency gate 确定性停止；
生产服务已经恢复，本轮没有新 migration、历史回填或年度参赛马全量运行。

## Git 发布

- feature commit：`5561d1da5dbd988be02ae54f965e5eeac18d8aa0`
- PR：`#69`
- merge commit：`ba9c0f00bc435c806864fa7a27f00dce545f1efc`
- 最终 review：`APPROVED`
- fingerprint：`7be81a18315015d953a74d67c90619a0ee6d016b86a554242854c17b7f34333b`
- content manifest：`69799241bb7490fd7f189d12dc28980174984fcdf5886a07c540fe185ca5482a`

## 恢复点

- 数据库：`backups/db/pre-release-b-prereq-832cc074-20260808T020900Z.dump`
- 大小：`408607125` bytes
- mode：`0600`
- TOC：`1304`
- SHA-256：`e0cd6899ea0f5dcc1a06dbde075ed9cdf6874965d2ddcd70e662a77d28e05cab`
- 旧镜像：`sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`
- rollback tag：`umanewsbot:rollback-pre-release-b-prereq-20260808T020900Z`

## 阻断证据

生产 migration recorder 包含：

- `stable.0067_historical_calendar_release_a`
- `stable.0070_horse_identity_evidence_commit_receipt`

但缺少当前 graph 中 `0070` 所依赖的：

- `stable.0068_race_data_sync_pipeline_a_field_audit`
- `stable.0069_race_data_sync_pipeline_a_ledger_guards`

前置 `main@832cc074` release task 在任何新 migration 前抛出
`django.db.migrations.exceptions.InconsistentMigrationHistory`。本轮未改 recorder，也未使用
`--fake`。

## 恢复验收

- web/worker/beat 恢复到同一旧镜像。
- Nginx 保持运行。
- 本机与公网 HTTP healthz 正常。
- `HISTORICAL_RACE_BACKFILL_ENABLED=false`。
- `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。
- 未进入 v2 census、maintenance、apply 或 verifier。
- 未触发 2025 full-network workflow。

## 下一门禁

先独立审计 `0068/0069/0070` 的真实 schema 与 receipt，再设计并审核 migration history 修复；
取得新的发布授权后，才可从头重试 Release B。
