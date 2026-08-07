# Lifecycle shadow 观察加固发布报告

## 结论

- 代码发布完成：本地提交 `bfd20169496a67a9c48a9e049452e617bbfcdffc` 已推送，PR #72 已合并为
  `main@c4ad7277498846695065c71239dc59334e04370e`。
- 生产部署未完成：在 Beat 已停止、生命周期配置已收敛为 `false/off` 后，Release B schema preflight
  仍在唯一 release task、Django migration、collectstatic 和候选镜像接管常驻服务之前 fail closed。
  候选生命周期代码没有进入生产运行态。
- 生产已安全恢复到旧镜像 `sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`，
  web/worker/Beat 明确为 `RACE_EVENT_LIFECYCLE_ENABLED=false`、
  `RACE_EVENT_LIFECYCLE_MODE=off`；race-live 未启动。

## 冻结版本与恢复点

- reviewed parent：`11abe4bf2d2badbfe1daa2f5fdd8f8e97f5f0093`
- 发布授权 fingerprint：`b59610908e070a6a8b3ec8c0d52d01766d9051155b046cdb00393c734b11f556`
- content manifest：`0433a7f2d5a2a04edd05baa0c032470d33a606e0f093c6ebaf9b99b104ae6feb`
- merge commit：`c4ad7277498846695065c71239dc59334e04370e`
- 候选镜像：`sha256:eb701e55c08e7d93febfd41c2ae9a8c1b06191d11048790c7a3a448c43a28b53`
- 隔离 release：`/opt/umanews-release-c4ad7277-CxzJ88Sx/umanewsbot`
- 数据库恢复点：
  `/opt/umanewsbot/backups/db/pre-lifecycle-shadow-hardening-c4ad7277-20260807T203206Z.dump`
  - bytes：`409315522`
  - TOC entries：`1297`
  - mode：`0600`
  - SHA-256：`477bd03d86630c8ac67b47da0529ca68f85b522d0a77aa24fedeb3435db0c32d`
- 旧镜像恢复 tag：
  `umanewsbot:rollback-pre-lifecycle-shadow-hardening-c4ad7277-20260807T203206Z`

## 阻断证据

标准 low-cost 发布完成候选镜像构建后，首次 Release B 预检因未显式提供
`EXPECTED_PRODUCTION_DB_IDENTITY_SHA256` 停止；未执行 release task。随后在共享部署锁内，以冻结的
数据库 identity `a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c`
重新执行候选只读预检，得到：

- `ok=false`
- `identity_ok=false`
- `migration_graph_known=true`
- `migration_leaf="stable.0067_historical_calendar_release_a,stable.0070_horse_identity_evidence_commit_receipt"`
- `unknown_applied_migrations=[]`
- `event_conflict_count=0`
- `target_conflict_count=0`
- `rows_sha256=d63cd2a2898e22e18d9f012e40989f159388aae3d2002640a693ab4007ce0435`

生产 `MigrationRecorder` 的相关已应用节点再次核对为
`0067_historical_calendar_release_a` 与 `0070_horse_identity_evidence_commit_receipt`；`0068`、`0069`
未应用，候选 main 还包含 `0071`。这是既有生产迁移历史与当前 main 图不兼容的问题，不允许在本次
lifecycle 发布中通过 fake、直接改 recorder 或跳过预检处理。

## 恢复与关闭态验收

预检失败后在共享部署锁内恢复旧镜像，依次重建 web，等待 healthy，再恢复 worker、Beat、nginx；
race-live 保持停止。验收结果：

- web/worker/Beat 均运行旧镜像并统一为 `false/off`；
- deployment lock 不存在，one-off container 不存在；
- Django check 通过，旧镜像 `migrate --plan` 无计划操作；
- lifecycle 为 `controls=16 / proposals=16 / applied=0 / active claims=0`；
- disabled scanner 为 `enabled=False / claimed=0 / dispatched=0`；
- 内部 healthz、公网 HTTP healthz 和首页均为 200；
- web/worker/Beat 近期 `Traceback/ERROR=0`，nginx `502=0`；
- worker ping 正常，active queues 仅包含 `celery`；
- 最终队列为 `celery=10 / default=2 / race_live=7543`。其中 `default` 的 2 条均为部署前已存在的
  `advance_race_event_lifecycle_task`，数量未增加且当前 worker 不消费该队列；`race_live` 积压未处理。
  `celery` 的 10 条为新闻发现、文章自动化与翻译重试任务，不含 lifecycle task。

本轮没有运行唯一 release task、没有执行 migration/collectstatic、没有修改赛事或 lifecycle 业务表，
也没有启用 lifecycle、enforce 或 race-live。

## 执行偏差

- 首个自定义远端只读编排通过 `ssh ... bash -s` 传入，内部 `docker compose exec` 消费了后续 stdin，
  因而只完成部署锁、停止 Beat、写入 `false/off` 和 historical preflight 后提前结束。后续远端读取均
  显式使用 `</dev/null`；未因此发生 migration 或业务写入。
- 一次本地拼接的 trap 引号错误留下 stale lock。删除前已精确核对锁内 PID 不存在、无 release/migration
  进程、无 one-off container，之后只删除 `/tmp/umanews-deployment.lock` 的精确文件和目录。
- 两次队列只读统计分别因 Compose 文件名和 Python 转义错误失败；均未连接队列执行读取或消费，随后用
  正确 low-cost Compose 文件完成只读核对。
- 当前公网验收以项目既有 HTTP 入口为准；HTTPS 连接拒绝属于既有未配置状态，不作为本 change 的成功证据。

## 后续门禁

下一步不是恢复 shadow，而是单独设计、测试、独立 review 并获得授权后修复生产 migration history，
使 `0067/0068/0069/0070/0071` 与当前 main 的受支持迁移合同一致。该修复完成且重新冻结生产数据库
identity 后，必须重新取得 lifecycle 候选版本的关闭态部署授权；关闭态部署成功后，恢复现有 16 场
`true/shadow` 仍是独立授权步骤。
