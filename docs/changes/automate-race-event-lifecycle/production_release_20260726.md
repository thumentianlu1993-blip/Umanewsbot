# 赛事生命周期阶段 A 生产关闭部署与 dry-run 记录

## 1. 发布身份与授权边界

- 生产 revision：
  `ef54a1836dd1fe1840f2d4765ebb73a1d130c645`。
- `web / worker / beat` 镜像：
  `sha256:fcede6ec9b6a45a0336405260176e881c920da735219d2026cbacb562c6b08a2`。
- 显式生产配置：
  `RACE_EVENT_LIFECYCLE_ENABLED=false`、
  `RACE_EVENT_LIFECYCLE_MODE=off`。
- 本次只部署阶段 A schema/code 并执行一次只读 dry-run；没有启用 shadow/enforce，
  没有创建 lifecycle control，没有推进赛事状态，没有调用 provider，也没有修改赛事或新闻数据。
- `race_live_worker` 和 `race_live` 积压不在授权范围内，保持原状，未启动、清理或重放。

## 2. 恢复点

- 数据库备份：
  `/opt/umanewsbot/backups/db/pre-race-event-lifecycle-20260726_173335.sql.gz`。
- 大小：`254691249` bytes。
- SHA-256：
  `a4c7f0e55f43826223b926842a5922dad7f73fd48b179e1ccb1b6632434b5453`。
- `gzip -t` 和 `PostgreSQL database dump complete` 标记均通过。
- 环境备份：
  `/opt/umanewsbot/.env.backup.pre-lifecycle-20260726_173521`。
- 仓库 `deploy/backup_db.sh` 在低成本生产模式下无法解析 Compose 内的 `db` 主机名，
  且宿主机缺少 OSS Python 依赖；失败产物已保留为
  `backups/db/rds_horse_news_20260726_173309.sql.gz.invalid`。最终恢复点由现有 PostgreSQL
  容器内只读 `pg_dump` 生成并独立校验。

## 3. 迁移与部署

- 应用迁移：
  - `stable.0058_add_race_event_lifecycle`
  - `stable.0059_add_lifecycle_manifest_data`
- 迁移只创建四张 lifecycle 表，并向新建 control 表增加 `manifest_data`；没有数据迁移。
- 部署发现 `deploy/docker/start-web.sh` 与 `deploy/deploy_lowcost.sh` 会并发执行
  `migrate --noinput`。一个进程成功应用 `0058/0059`，另一个收到 `DuplicateTable` 后退出；
  web 依靠重启策略再次启动并确认 `No migrations to apply`。
- 事后核对迁移记录完整、四类模型可查询、数据库无等待锁；重新执行 collectstatic，并恢复
  新版 worker/beat。后续含 migration 的部署必须先修复为单一 migration 执行入口。

## 4. 生产 dry-run

- 执行时间：`2026-07-26 17:44:39 +08:00`。
- 证据目录：
  `/opt/umanewsbot/runtime/deploy/race-event-lifecycle-dry-run-20260726_174439/`。
- 冻结范围：本地赛事日期 `2026-07-19` 至 `2026-08-09`，已发布且
  `priority in (P0, P1)` 或 `is_featured=true`，排除 cancelled。
- 没有使用 `--auto-discover`：当前实现会按 ID 取最多 2000 条，但不遵守 rollout 的日期窗口。
- 使用精确 `--event-ids`，`--page-size 100`，未传 `--apply`，没有 manifest apply。
- 范围共 `35` 场，全部缺少 `race_datetime`：
  - 英国 `10`
  - 法国 `3`
  - 美国 `22`（`America/New_York=18`、`America/Los_Angeles=4`）
- 决策结果：
  `transition=7 / noop=28 / error=0 / ineligible=0`。
- 当前窗口没有日本或香港重点赛事，因此本轮没有取得这两个地区的生产 dry-run 样本；
  不以窗口外历史赛事冒充当前观察证据。

## 5. 零写与验收证据

- dry-run 前后赛事范围摘要完全一致：
  `state_sha256=0dc0e02eb7f498e1c38686790efde6ba1f6fac91dcbef3f7f953fdb5777eec6b`。
- `pre.json` 与 `post.json` 逐字节一致，文件 SHA-256 均为：
  `23d9022f6cdc34be1553d9a1502fd50918d5db8c31a1281400c466cda76f31da`。
- `dry-run.out` SHA-256：
  `7c79ae59b16bd042da870e6b0cdf7db33110b5f6d6f48da91ac54ec5ef74da87`。
- dry-run 前后以下记录数均为 `0`：
  - `RaceEventLifecycleControl`
  - `RaceEventLifecycleTransition`
  - `RaceEventFieldChange`
  - `RaceEventFieldAuthority`
- 普通 Celery 队列验收时为 `0`，没有 active 或 queued lifecycle task；`race_live` 队列为
  `2259`，按授权未处理。
- Django check、Celery ping、数据库等待锁检查通过；生产内外 `/healthz/`、首页、
  `/races/` 均返回 HTTP 200。

## 6. 下一门禁

- 当前可以进入 dry-run 结果人工审核和 shadow manifest 准备，不能直接启用 shadow。
- shadow 前必须：
  1. 修复并 review 双重 migration 执行入口；
  2. 明确日本、香港在观察窗口无样本时的补样策略；
  3. 冻结逐场 enrollment/baseline manifest 及 SHA-256；
  4. 取得针对精确 manifest、赛事集合和观察窗口的独立用户授权。
