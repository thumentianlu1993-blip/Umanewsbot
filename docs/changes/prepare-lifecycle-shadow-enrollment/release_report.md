# Lifecycle shadow 纳管准备代码发布报告

## 发布结果

- 代码提交：`ca37d51e5720c674bc234ab01f6b2a23d62f53fc`
- Pull Request：[#56](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/56)
- 合并提交：`3ba5defc526259b2785f4d84736551ab826804b3`
- 合并时间：`2026-07-31T20:29:35Z`（上海时间 `2026-08-01 04:29:35`）
- 目标分支：`main`
- GitHub 合并结果：`MERGED`

## 审核与内容身份

- 最新成功只读 reviewer session：`019fb637-a018-7f43-a119-4f54f55cba00`
- 最终结论：`APPROVED`，P0/P1/P2/P3 均为 0，原生 CLI exit 0。
- 审核 parent：`1cdd066b80861520f60515d3912c0f0a8283b0eb`
- 审核 fingerprint：
  `11928d9946ea81ad2c1a34b802964a454ae3fb25f0cd69c74573b761a2dfcd1c`
- 审核 content manifest：
  `6a501ebc0f3b05614a37718abd3294bd0d89b1e19b79c599a6bb2ad820397975`
- index 与 commit transition 均成功，提交 tree 与审核 content manifest 精确一致。

## 验证证据

- lifecycle enrollment + 既有 lifecycle SQLite：`91/91 OK`
- 最新 main 赛事年份/当前赛事描述符：`20/20 OK`
- 隔离 PostgreSQL enrollment + 既有 lifecycle：`6/6 OK`
- Django check、migration drift、cached diff check：通过。
- 相邻套件：`187 passed / 3 errors`；相同 3 个 `public_year/local_date` fixture error
  已在独立干净 `origin/main@1cdd066b` 精确复现，属于合并前 main 既有问题。
- PR #56 创建时 GitHub `mergeStateStatus=CLEAN`，未配置 status checks。

## 代码合并阶段未执行范围（后续状态由下节关闭态部署取代）

- 未部署或重建服务。
- 未执行生产 migration、control apply 或其他生产数据库写入。
- 未启用 lifecycle；生产 `false/off` 状态未由本次代码发布改变。
- 未执行联网 provider proof，也未处理 race-live 队列或积压。

以上小节记录代码提交与合并当时的边界；后续生产运行态以紧随其后的关闭态部署小节为准。
本报告不改变规格、任务、应用、测试、配置、迁移或生产治理规则。

## 关闭态生产部署（2026-08-01）

- 用户随后授权开始部署；本次只部署代码并保持 lifecycle 关闭，不包含 control apply、
  provider proof、联网 prepare 或 lifecycle 启用。
- 部署目标为 `main@6a185eaa35c9ea89211a33fa5a6cde81d76dbee3`，Git tree 为
  `8fd0214762037f92a9672c2c92f1f2f9d7478cf0`，clean source archive SHA-256 为
  `c73d91ea29822e94f59d6f9e19dac731df06cddea59f1cb0f09d02f1ad1f360d`。
- 使用隔离 release 目录 `/opt/umanews-release-6a185eaa-069tQL/umanewsbot`，没有修改生产
  主 checkout 的既有脏工作区。最终 web/worker/beat 统一运行 image
  `sha256:8ae8ce4e7ee4a08a1e3208cff06cbf2e89cd83aebe52587dbe117b621326d31b`。
- 写前 custom-format 数据库备份为
  `/opt/umanewsbot/backups/db/pre-lifecycle-shadow-enrollment-6a185eaa-20260731T211429Z.dump`，
  `371214432` bytes、mode `0600`、`pg_restore -l` 为 `1295` 项，SHA-256 为
  `98d9629615f68d747f54866e75f4b892453e9ccd18be9144e724176f8599dd05`。
- `.env` 备份为
  `/opt/umanewsbot/.env.backup.pre-lifecycle-shadow-enrollment-6a185eaa-20260731T211429Z`，
  SHA-256 为 `c0588d4498afd817e3d0d385ecad36516b31c13bdf9721bc21a9935f3a19a130`；
  回滚 tag 为 `umanewsbot:rollback-pre-lifecycle-shadow-enrollment-6a185eaa-20260731T211429Z`，
  指向旧 image `sha256:cd57a7a8a2bba6c7efc7bd99b95b350b57af72db4f98f673a61a97399d047624`。
- 部署前目标 migration plan 为 `No planned migration operations`。发布走共享部署锁与单一
  release-task owner；Beat 停止后等待一条既有 `discover_term_candidates_task` 自然完成，
  再停 worker/web、执行 release task、等待 web healthy 并恢复 worker/beat/nginx。
  `race_live_worker` 部署前为 `Created` 且未运行，部署后继续未运行；部署锁和 race-live
  intent 文件均已清理。
- 上述既有术语发现任务属于正常内容处理，任务自身必然更新 `TaskExecutionLog`，并可能按其
  既有逻辑写入术语候选/证据；本次没有把它误记为零生产写入，也没有中断、重跑或扩展其范围。
  本次零写结论仅覆盖 lifecycle control、transition、claim 及赛事/赛果/新闻/QQ 路径。
- web/worker/beat 三容器均为 `RACE_EVENT_LIFECYCLE_ENABLED=false`、
  `RACE_EVENT_LIFECYCLE_MODE=off`、`HISTORICAL_RACE_BACKFILL_ENABLED=false`。
  scanner 关闭态 smoke 返回 `enabled=False / claimed=0 / dispatched=0`；数据库保持
  `controls=0 / transitions=0 / active_claims=0`。
- 容器内两个新增核心文件 SHA-256 与目标源码精确一致；Django check、migration drift、
  两条管理命令 help 和最终 migration plan 通过。worker ping 正常，HTTP `/healthz/` 与
  `/races/` 均为 `200`，发布后 15 分钟 web/worker/beat/nginx 的
  `Traceback / ERROR / 502 / migration failure` 计数均为 `0`。
- HTTPS 仍不可用；项目当前只完成 HTTP 接入，HTTPS/证书启用仍是后续独立工作，未在本次
  lifecycle 部署中扩大范围处理。

下一门禁是生产只读 prepare/dry-run；control apply 与 `true/shadow` 启用仍须分别授权。
