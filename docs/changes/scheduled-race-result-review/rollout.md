# 最近赛事赛果定时收集与邮件审阅发布与回滚

## 1. 当前状态

- 基线：`origin/main@0bf3fd97`。
- worktree：`.worktrees/schedule-race-result-review`。
- 分支：`codex/schedule-race-result-review`。
- 当前阶段：方案编写完成，等待独立方案审核。
- 尚未实现、提交、推送、创建 PR、部署、联网或创建 automation。

本 change 的“唯一需授权点”指部署后的每个审核包只需一次赛果内容批准。首次实现与发布仍按

## 2. 发布前门禁

必须具备：

- 方案 reviewer `APPROVED`；
- 真实 RED/GREEN 和受影响回归；
- 独立代码 review 所有 actionable finding 清零；
- 冻结 fingerprint、approved parent、content manifest hash；
- 生产运行态、队列、外部 import lock、磁盘、SMTP 和 SSH 可用性只读盘点。

## 3. 默认关闭部署

1. 创建数据库 custom-format 备份并通过 `pg_restore -l`，备份 `.env`，记录回滚镜像。
2. 创建 `/opt/umanewsbot/runtime/race_result_review`，最小权限，拒绝 symlink。
3. 部署受审镜像和 Compose mount，应用治理模型 migration。
4. 保持：
   - `RACE_RESULT_REVIEW_ENABLED=false`
   - `RACE_RESULT_REVIEW_ALLOW_NETWORK=false`
   - `RACE_RESULT_REVIEW_NOTIFY_EMAILS=`。
5. 执行 Django check、migration drift、healthz、容器和挂载验证。
6. 运行 flag-off smoke，必须为 network 0、email 0、business write 0。

## 4. 单次启用验收

在同一已授权发布窗口：

1. `.env` 设置总开关、网络开关和唯一收件人 `754652181@qq.com`；
2. 重建需要读取环境的服务，确认其他 race-live/历史开关未被改变；
3. 手工调用固定 wrapper 一次；
4. 记录窗口、target/reviewable/blocked/request、bundle SHA、delivery 和邮件终态；
5. 验证 `RaceEventResult`、`RaceEvent.status`、receipt 均无变化；
6. 用户确认邮件可读、附件 SHA 可复算，但此测试邮件不自动触发 apply。

## 5. 启用生产调度并创建 Codex automation

- 项目使用 Umanews 本地项目 ID，由 Codex App `list_projects` 实时取得，不写死到仓库。
- 生产 Beat 是主调度面；先验证 schedule、普通 worker route、soft/hard limit 和同 slot claim。
- Codex automation 类型为独立 cron，执行环境为 local，时区为 `Asia/Shanghai`。
- 每天 06:30、18:30 运行固定 deploy wrapper，与 Beat 争用同一个唯一 schedule slot。
- automation prompt 明确已预授权：生产只读目标盘点、受限 provider 网络、artifact/审计写入和
  向唯一收件人发审核邮件；禁止生产业务表 apply。
- 通知策略只报告 automation 失败；正常审核通知由应用邮件承担。
- 创建后立即 view 核对名称、项目、两个北京时间、状态 active 和 prompt 边界。

本地 execution host 离线或 SSH 不可用时，生产 Beat 仍应执行；Beat/Codex 都曾中断时，下次任一
触发把 14 天内遗漏 slot 合并到最新到期 slot，旧 slot 留审计终态但不逐轮联网。验收覆盖并发
claim、单侧故障、28 个遗漏 slot 仅一次联网 prepare 和 pending 跨 72 小时窗口。

## 6. 审核后生产写入

收到用户明确的 `<bundle_sha256> + approved event IDs` 后：

1. 只读 verify bundle；
2. apply 命令默认 dry-run；
3. 创建写前数据库备份并校验；
4. 以 exact SHA/scope/reviewed-row digest 执行 `--apply --confirm-apply`；
5. 独立进程 `--verify`；
6. 核对 results、confirmed timestamp、finished status、receipt、幂等重放和网页；
7. 写回 evidence-only 生产事实。

这一步是每个 bundle 唯一的人为授权点。网络、重新 prepare、dry-run、备份和 verify 不再逐项
索取授权。

## 7. 监控

- 每日两个时点是否有 success/noop/already_notified 或明确 failure；
- target/reviewable/blocked/request 数与 inventory 守恒；
- bundle/manifest/file SHA；
- review delivery QUEUED/FAILED/SENDING 是否在下一次恢复；
- 同 bundle 是否出现多封 SENT；
- provider route contract/有效期、磁盘余量、artifact 权限；
- status repair 数和超过 72 小时仍缺赛果的事件。

## 8. 回滚

1. 暂停/删除 Codex automation，记录最后一次实际运行。
2. 设置 `RACE_RESULT_REVIEW_ENABLED=false`；若只需停联网则关闭 network flag。
3. 确认后续手工调用为 disabled 且三零。
4. 恢复旧镜像和 Compose；治理表为追加审计数据，默认保留。只有回滚到不兼容版本且已验证无
   必须保留记录时，才按 migration reverse 计划处理。
5. 保留 immutable bundle、review run/delivery/approval、TaskExecutionLog 和 OperationLog。
6. 如果错误已经通过审核后 apply，停止 automation，按对应 receipt 和写前备份进入独立数据回滚；
   cron 不自动删除或覆盖正式赛果。
