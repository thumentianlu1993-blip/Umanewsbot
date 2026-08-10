# lifecycle enforce canary 灰度与回滚

## 本实现轮边界

- 只在独立 worktree `codex/lifecycle-enforce-canary` 修改与测试。
- 不 commit/push/PR/merge，不连接生产，不改 control、赛事、env、容器或 Beat。

## 候选发布包（需后续 G2）

- 部署受审代码，预期无 migration；所有 lifecycle 保持发布前 mode。
- 验证 production revision/image、迁移计划为空、web/worker/Beat/队列/锁/healthz。
- 不自动 prepare/apply canary，不启用 enforce。

## 精确生产启用包（需后续 G3）

1. 核对 production revision、统一 image、release lock、active/reserved、event 186/187 快照。
2. 在生产严格 `false/off` 下只读 prepare，冻结 raw SHA、apply_expires_at 与覆盖 event 187 T+30+24h
   的 runtime_valid_until；独立核对 artifact。
3. 备份数据库和两份 env，保存 SHA、恢复镜像与当前状态快照。
4. 通过 shared-lock promotion wrapper，使用精确 manifest SHA 在 false/off 下 dry-run/apply/verify，
   仅提升 186/187 control；PostgreSQL advisory lock 防并发 cohort。
5. 使用同 SHA、精确 `186,187` 和同 revision 分阶段切 `true/enforce`；manifest 原始字节经有界
   stdin 传入 current/recreated web，SHA/IDs 写入两份 env 与三服务 settings，control 在 worker
   coherence 后、Beat 前从 inactive 原子激活；不启动 race-live。
6. activation active verifier 通过后启动 Beat，观察第一个正常 scanner tick；不另发手工 scanner，
   验证其他 control 仅 proposal、applied 只可能属于 186/187。
7. 在 186 T、T+30、187 T、T+30 观察 DB audit、公开详情/日历缓存、worker/Beat/日志。

## 停止条件

- manifest/DB/runtime/revision 任一漂移；
- 范围外 applied；重复 applied；公开状态与审计不一致；
- worker/Beat/coherence/healthz 异常；
- event 被取消/延期、时间来源发生变更但 generation 未同步。

触发后立即以不依赖 manifest 的 `false/off` 路径止写；保留 control/transition/日志证据，不自动反向
修改已合法推进的赛事状态。race-live 始终保持关闭。

## 2026-08-10 实际发布状态

- PR #100 已合并为 `a7e3783ff7d188481cecd421cd2595f43e9a706b`，无 migration；关闭态部署、生产
  artifact dry-run 和绑定 raw SHA `eacffda6…d303fc` 的 G3 均已完成。
- event 186/187 已为 `enforce/active`，全局为 `true/enforce`；其他 enforce control 为 0，race-live
  仍关闭。两场未到 T，公开状态仍为 `scheduled`、applied transition 为 0。
- 用户的精确 G3 明确包含手工 scanner smoke，故实际执行取代了候选步骤 6 的“不另发手工 scanner”
  假设；同步与 Celery 队列 smoke 都是 `claimed=0 / dispatched=0`，Beat 也已自动运行一次。
- 恢复点、activation ID、服务/HTTP/日志验收及观察时间见 `release_report.md`。
