# 生命周期任务队列路由修复发布报告

## 代码发布

- 功能提交：`03314a2c4ec701751312cc13afd3fe8b5d4559b5`。
- PR：[#65](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/65)。
- main merge commit：`d5ae1d7e227d486569c47344f7ea8f4d2e13d109`，tree
  `c2fea717831b6f11ad0827bc690014275bcf3fff`。
- 独立原生只读 review 结论为 `APPROVED`；冻结 fingerprint 为
  `6a9a1ba6e092e57df6a6c2c6efaae0c2c3a8f58dc8421542ac83f5682c314dad`。

## 关闭态部署

- 使用精确 merge commit 的隔离 checkout
  `/opt/umanews-release-d5ae1d7e-8biMT2TI/umanewsbot`，生产主 checkout 的长期 dirty
  文件未清理、覆盖或 checkout。
- 发布前 lifecycle 为 `false/off`，16 个 control、0 transition/proposal/applied、0 active
  claim；普通 worker 实际只消费 `celery`，队列为 `celery=0 / default=2 / race_live=7543`，
  race-live worker 未运行。
- 数据库恢复点：
  `/opt/umanewsbot/backups/db/pre-lifecycle-queue-routing-20260801T192601Z.dump`，
  `374107496` bytes、TOC `1288`、mode `0600`、SHA-256
  `a05e166259e646ffbc464bb900052b8d8f4f2a9d9b599c5396ae0315f2d8125d`。
- `.env` 恢复点：
  `/opt/umanewsbot/.env.backup.pre-lifecycle-queue-routing-20260801T192601Z`；旧镜像冻结为
  `umanewsbot:rollback-pre-lifecycle-queue-routing-20260801T192601Z`，指向
  `sha256:24fc89cfd801f624c4c2e42bfb5654def6cf50785bda6f8a4d89bb9028c67b9f`。
- 共享部署锁与 historical migration-safe preflight 通过；构建成功后 Beat 停止，Celery
  自然 drain 为 `active=0 / reserved=0 / active_confirm=0 / workers=1`，随后停止 worker/web。
- 唯一 one-shot release task 报告无待应用 migration，完成 collectstatic；web healthy 后才
  恢复 worker/beat/nginx。race-live 前后均未启动。
- 最终 web/worker/beat 镜像统一为
  `sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`。

## 关闭态验收

- web/worker/beat 三容器均为 lifecycle `false/off`；运行时 task route 为
  `advance_race_event_lifecycle_task -> celery`，worker `active_queues` 只有 `celery`，ping 为
  1 node online。
- 16 个 control 关联赛事仍全部为 `scheduled`；active claim、transition、proposal、applied
  均为 0。关闭态 scanner 返回 `enabled=False / claimed=0 / dispatched=0`。
- 两分钟观察后队列仍为 `celery=0 / default=2 / race_live=7543`；未消费、清理或重放两条
  旧 `default` 消息，也未处理 race-live 积压。
- migration plan 为 0；内部 healthz、公网 healthz、赛事页均为 HTTP 200；近五分钟
  web/worker/beat 的 `Traceback/ERROR` 计数均为 0，Nginx 502 为 0。
- 发布锁和 race-live intent 文件均不存在。证据目录：
  `/opt/umanewsbot/runtime/operations/lifecycle-queue-routing-deploy-20260801T192601Z`；
  `deploy.log` SHA-256 为
  `0fbadd0f5c0e80bdd48a5fee8de45323e0bb99792a866deeba87a41ba08109fc`，
  `acceptance.txt` SHA-256 为
  `7885f44e400473fe6e809cf4e733dfb2fc96bcc00745a724a17e320d9d70f8e4`。

## 并行偏差

- 部署验收发现一个早于本次 release task 启动、使用旧镜像的独立 one-off 容器，命令为
  `bootstrap_p0_horse_identity_evidence --prepare --allow-network`。它属于 P0 马身份只读
  prepare，不属于生命周期任务；本次未停止、删除或重跑它。
- 本次没有启用 lifecycle shadow。重新执行 R3 前仍需独立授权，并须先核对实际
  `active_queues` 无 `default` consumer，再以手工 scanner 使目标 control generation 增长。
