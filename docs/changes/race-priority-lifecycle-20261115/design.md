# 实施设计

## 范围与基线

分支 `codex/race-priority-lifecycle-20261115`，独立 worktree，基于 `633f80ce`。2026-11-15 本轮只读复核生产应用为 `f19c7f2d`；旧调查记录 `e6c47a98` 不再作为发布基线。无模型迁移，不引入新抓取来源。交付按根 AGENTS.md。

## 调度与资源

- `race_control` 承接 due selector、状态扫描/推进、结果 SLO；一分钟一轮。与新闻及广域发现分开。
- 未确认结果 claim 分派至 `race_realtime`；失败后通过检查点重新领取有效 claim，投递 `race_realtime_retry`。同一实时 worker 使用 Redis 消息优先级（重试 0、普通 3）优先消费重试，单并发、单预取，不重放过期 token。
- 新增 control/realtime 两个独立容器，各 384 MiB 限额，CPU 上限分别 0.25/0.5，CPU shares 2048；保留原后台 `race_sync_v2_worker`。完整继承赛事 worker 的环境和数据挂载，生产覆盖配置须同样扩展到两个新服务。
- selector 优先选择最近一天未确认赛果，避免旧检查点占满批次；失败一分钟重试，显式拒绝保持一小时退避，来源 Retry-After 取较晚时点。
- 0078/0079 正常在线升级在冻结 manifest 时将两个新增 worker 作为目标启动服务，并在 Beat 前启动；手工停服 release 保持停服意图。
- 历史缺赛果盘点保留独立的时间到期判断，不再依赖“可以自动完赛”；不会据此写入赛事状态。
- 删除周日 netkeiba 两条 rush 计划，保留小时与排行榜计划。旧消息参数仍兼容，避免发布时已在队列的消息反序列化失败。

## 请求预算

`artifact_daily_requests_exceeded` 是本系统 ledger 的每日限制，不是 TRA 的拒绝响应。只有锁内核验通过的未确认结果 claim 可以建立临场网络上下文，且只对该来源/地区、该 claim 有效期生效。此上下文免除每日请求/预留字节上限，仍如实记账；后台任务仍受日额度限制。单响应大小、根目录容量、可用磁盘、host 频率与第三方退避不变。上下文在 finally 中恢复，不能由任务输入的任意 bool 开启。

## 冠军与正式结果

时间引擎只能把 scheduled 推进 running；删除 T+30 和 date-only 跨日完赛。来源、同场身份、claim、生命周期权限、人工锁校验通过后，明确第一名（含并列第一）即可记录 `data_sync_winner_observed` 并推进 finished。取消/延期不得被结果写入覆盖。部分结果不填 `result_confirmed_at`，不投影完整正式表，保持补采。公开页依据已应用冠军转态证据显示已完赛，历史无冠军的 time-only finished 仍提示待确认。

JRA/NAR/HKJC/Geny/TRA 部分结果保留可验证的冠军；不放宽来源和同场身份规则。损坏身份、未识别名次不作为冠军证据。后续完整官方结果继续走原 roster、权限、publication 与证据完整性合同。

## 结果重复与补全

`revision.content_sha256` 保留对完整 observation 的绑定，兼容已有公开读验证。只有判断赛果是否变化时排除抓取时间、原文 SHA、来源 URL 等传输元数据。同来源补齐原为空的 finish_time 可更新；更改已有时间、名次、马匹身份等仍需原有更正依据。相同的待审冲突仅追加/复用证据，不逐次制造新冲突版本；不批量改写旧 pending 记录。

## 方案审核收敛

按仓库 plan-eng-review 指引检查了五份输入与上述代码路径。初始方案需补正三点：部分资料在 writer 前被拒绝；内容 SHA 同时承担公开证据校验，不能直接改成语义 SHA；新增队列必须纳入服务恢复与完整生产覆盖配置。当前设计逐项覆盖；实现与验证状态以 tasks/rollout 为准。无独立代理参与方案或实现，最终代码使用只读独立 reviewer。
