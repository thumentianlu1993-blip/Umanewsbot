## ADDED Requirements

### Requirement: 超时抓取任务必须受控收敛 <!-- id: req-stale-crawl-reconcile -->
系统 SHALL 提供 dry-run 与显式 apply 入口收敛超过配置阈值的 `CrawlJob(status=started)`。apply MUST 绑定审核 manifest，并且只有没有活跃 Celery 或有效生产窗口证据的记录才能转为 failed。

#### Scenario: dry-run 生成遗留任务清单
- **WHEN** 运维人员扫描超过 60 分钟的 started 抓取任务
- **THEN** 系统 SHALL 输出任务 ID、来源、开始时间、关联文章数、活动执行证据、建议动作和 manifest SHA
- **AND** dry-run SHALL NOT 修改 `CrawlJob` 或来源状态

#### Scenario: apply 遇到状态漂移
- **WHEN** manifest 中某任务在 apply 前已经完成或状态不再是 started
- **THEN** 系统 SHALL 跳过该任务并报告状态漂移
- **AND** 系统 SHALL NOT 覆盖其新终态

### Requirement: 抓取任务终态必须防止迟到覆盖 <!-- id: req-crawl-terminal-cas -->
系统 MUST 仅允许 `CrawlJob` 从 started 原子转换到 success 或 failed。已由超时收敛或其他执行写入终态的记录，不得被旧任务内存对象再次覆盖。

#### Scenario: 超时任务晚到成功结果
- **WHEN** 某 CrawlJob 已被受控收敛为 failed，原 Celery 任务随后返回成功
- **THEN** 迟到完成逻辑 SHALL NOT 把该记录改回 success
- **AND** 系统 SHALL 在任务日志记录 `terminal_state_already_claimed` 或等价原因

### Requirement: 来源健康必须展示滚动失败与任务遗留 <!-- id: req-source-rolling-failures -->
系统 SHALL 分别展示当前运行、最近完成、最近 2 小时与 24 小时失败、超时 started 数和最后成功时间，不得只展示单一最新缓存状态。

#### Scenario: 成功结果跟在失败之后
- **WHEN** 某来源最近一次完成为成功，但过去 2 小时曾多次失败
- **THEN** 来源健康 SHALL 同时显示最后成功与滚动失败数
- **AND** 运营人员 SHALL 能查看稳定错误类别和首个错误摘要
