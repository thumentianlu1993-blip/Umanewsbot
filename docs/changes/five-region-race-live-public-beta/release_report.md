# 五地区准实时赛果公开 Beta 代码层发布报告

## 发布身份

- 发布时间：2026-07-19
- 冻结 fingerprint：
  `17a1b34321ee25f13f783c1fe24278bbacdab288f3a30281a981e4986158e0fa`
- Git commit：`85948707c7b2bf3c62a66b09b2ddb202adf2d1ee`
- Git tree：`d13071a446c2c8c4dc479aa78f341a21b0921c8e`
- source archive SHA-256：
  `54ab84a56468a306e27a891901c91274003106f9f4e9b4c68da5d9cf11400dab`
- 生产 AMD64 image ID：
  `sha256:4c40ae1946dd9ac85a368917fe3de64269e6cf848737e24253f0d0996403eda6`
- TRA registry SHA-256：
  `7aca49ff1df7573ebfe6a9e403eefca5c9e64d8ee18d8d3be383d67803db550a`

## 备份与回滚锚点

- 数据库备份：
  `/opt/umanewsbot/backups/db/pre-five-region-race-live-85948707-20260719T111505Z.dump`
- 大小：`204,512,228` bytes
- SHA-256：
  `98833a3d9dd5ebd74eb5c7d46ac44caa9b3d5d9ab6e310ec02137fe612e79c89`
- 校验：非空且 `pg_restore -l` 退出 0
- 环境备份：
  `/opt/umanewsbot/.env.backup.pre-five-region-race-live-85948707-20260719T111505Z`
  ，权限 `0600`
- filtered rollback env SHA-256：
  `cda13ce08c6a6d03ffcb4812cf1e1bc1d56fa7eae2244d7cf72330869811062e`
- 旧 image ID：
  `sha256:700ea78698fb67de602fb7e5447b997610e24e64de29df4591e4bb9e476087ef`
- 旧镜像标签：
  `umanewsbot:rollback-pre-five-region-race-live-85948707-20260719T111505Z`

## 切换和验证

- 历史 runner 预检为 `migration_safe`；切换前 Celery
  `active=0 / reserved=0`。
- migration `stable.0047_race_live_public_beta_controls` 成功应用。
- Django check、migration drift、collectstatic、web health、两个 worker ping、
  Beat、内部和公网 `/healthz/` 均通过。
- `web / worker / race_live_worker / beat` 均运行冻结 image ID 和 revision。
- event 924 保持 revision `#2`、phase `provisional`、原 content SHA、7 条结果和
  “暂定赛果”页面。migration 补齐
  `last_provisional_result_revision_id=2` 和
  `authorization_kind=provisional_policy`。
- 五地区赛事筛选页均为 HTTP 200；近期四个 app 日志未发现
  traceback、critical、integrityerror 或 fatal。

## 开关与地区真实状态

- `RACE_LIVE_SCHEDULER_ENABLED=false`
- `RACE_LIVE_MONITOR_ENABLED=false`
- `RACE_LIVE_ENABLED_REGIONS=[]`
- selector：`enabled=false / claimed=0 / dispatched=0`
- active claim：0
- `celery` queue：0
- `race_live` queue：0

Free 有界 proof 用 3 个请求得到地区表 55 条、今日 racecard 43 场、今日 result 2 场，
三次 HTTP 均为 200；只保存去标识元数据，summary SHA-256 为
`1369c0c27af746891bbfdf932010601e3e6def82eba749452cf1522e4de9db79`。

地区 Gate E 当前事实：

- 法国：event 733–735 返回 HTTP 200，但 coupled entries 的重复参赛编号触发
  `racecard_schema_invalid`，保持 off。
- 日本：event 80/81/185 为 `racecard_not_found`，保持 off。
- 美国：event 420 为 `racecard_not_found`，保持 off。
- 英国：event 924 既有 provisional public 不变；下一批 7 月 25 日赛事尚未进入
  today/tomorrow prepare 窗口。
- 中国香港：下一场正式目标在 12 月，本轮没有 racecard proof。

因此本次发布结论是：
`code deployed / five-region source proof incomplete / no new region enabled`。
不得把本报告表述为五地区来源或自动调度已经公开上线。

## 证据锚点与回滚就绪度补充

来源 proof 的持久目录为：

`/opt/umanewsbot/runtime/race_live_racecards/source-proof-free-20260719T112200Z`

| 文件 | SHA-256 | 权限与所有者 | 证明内容 |
| --- | --- | --- | --- |
| `manifest.json` | `26af97b56781803de44e418b8693ca13e1fff61f653f44a4acffb27b78ae3bfe` | root-owned `0600` regular file | 固定 proof runner、registry、端点和预算 |
| `requests.jsonl` | `98e513464736082176bfa91b7579e45326d7228653ad6ac8090e92890d69127a` | root-owned `0600` regular file | 三次 HTTP 200 和 `55/43/2` 集合计数 |
| `summary.json` | `1369c0c27af746891bbfdf932010601e3e6def82eba749452cf1522e4de9db79` | root-owned `0600` regular file | proof 完成状态和请求总数 |

rollback artifact 目录
`/opt/umanewsbot/runtime/race_live_rollback/five-region-race-live-85948707-20260719T111505Z`
当前只有 root-owned `0600` `rollback.filtered.env` 及其 SHA 文件，**没有**
`manifest.json`。因此：

- 数据库备份、旧 image tag 和 `.env` 备份可用于代码/环境恢复；
- reviewed-release one-shot 的 result/policy business rollback 尚未可执行；
- 缺少 manifest 时继续保持 scheduler/monitor false、enabled regions 为空，禁止任何
  新 event promotion。

## Rollback 门禁事实更正

冻结 Gate D 要求 release artifact 在代码发布时已保存 manifest 路径和 SHA；本次实际
没有生成 `manifest.json`，因此：

- 原发布门禁未满足；
- frozen-image business rollback 未就绪；
- 本次 release evidence closure 仍不完整；
- 任何补救必须另走独立受审、用户授权和只读验证；
- 补救完成前 scheduler/monitor 和全部新地区继续关闭。

本次冻结 review 身份为：

- review scope：受审的五地区完整 uncommitted scope；
- approved parent：
  `566a9b1012aac7fe52ad7aec793ab0ff4b9eae18`；
- approved content manifest SHA-256：
  `d5b53eabd90b5fddd769d38f7a98cca18ad8dc16564ba497e2da3b4a023e62c9`。
