# 最近赛事赛果定时审核发布报告

## 发布版本

- 主功能：PR `#39`，merge commit
  `dd35038f5ef5b6c61491b7365366cad589bbf748`
- 补跑 JSON 修复：PR `#40`，merge commit
  `ca22c9fa6389984cf38f6cbb9f8c6179e7249798`
- 生产镜像：
  `sha256:0cb2e1787fadfb742d3733db3a53e0d08035c22d98d71779dd874bb4a06def65`

## 恢复点

- 数据库：
  `/opt/umanewsbot/backups/db/pre-scheduled-race-result-review-20260728T004929+0800.dump`
- 大小：`262544260` bytes
- SHA-256：
  `6edc1c6b7057f1be2ab622d570816890958edf7e67557b38b8dc95ff2c9b2205`
- `.env`：
  `/opt/umanewsbot/.env.backup.pre-scheduled-race-result-review-20260728T004929+0800`
- 镜像：
  `umanewsbot:rollback-pre-scheduled-race-result-review-20260728T004929_0800`

数据库备份已通过 `pg_restore -l`，数据库和环境备份权限均为 `0600`。

## 发布与故障处置

1. 关闭态部署 PR `#39`，应用 migration `0062`；disabled smoke、route registry、
   持久卷、healthz、Celery ping 和四张治理表零基线均通过。
2. 首次启用后，自动 catch-up 在写入 coalesced run 的 JSON 摘要时触发
   `datetime` 不可序列化。失败点早于来源联网和邮件。
3. 立即停止 Beat、关闭总开关与网络开关；`RaceEventResult=92223`、finished event
   `9419`、scheduled event `443`，四张治理表仍为 0。
4. PR `#40` 将 JSON 内 slot 转为 ISO 8601，并增加 `schedule_slot=None` 的真实持久化
   回归。修复版再次关闭态部署和 smoke 后才重新启用。

## 首次受控运行

- run ID：`26`
- 数据库终态：`notified`
- selector SHA-256：
  `29ffd2b4ceeb5d6cd7358cc72a863dbd81e91c7edf79e908732cb44dd6fa8ec3`
- bundle SHA-256：
  `07e7f22374bbc09a85df441f87da1cd0228f5431a8f9378a8f1e578bbecf4d47`
- 邮件：唯一收件人投递成功
- 重复运行：`already_claimed`
- delivery 总数：`1`
- 业务写入：`0`

首次 selector 找到 13 场，候选为 0、blocker 为 13，原因全部是 `route_missing`。邮件内容
是阻断审核包，不是完整赛果包；不得进入 apply。

## 调度

- Celery Beat：北京时间每日 `06:30/18:30`
- 任务：`stable.tasks.scheduled_race_result_review_task`
- Codex 备用 automation：`umanews`
- 备用入口：`deploy/run-scheduled-race-result-review.sh`
- 双入口共享唯一 schedule slot；重复 smoke 已证明不会重复投递。

## 未关闭的产品缺口

当前赛事记录没有可供定时任务直接使用的稳定 provider identity，现有 route registry 因此不能
选择唯一 route。下一阶段必须实现并审核通用来源身份发现/写入链路，至少覆盖当前 13 场及未来
72 小时目标；重新运行后以完整数字名次、runner 守恒、`candidate > 0` 和 `blocker=0`
作为“仅剩人工审阅授权点”的验收条件。
