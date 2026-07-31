# Lifecycle shadow 纳管准备发布与观察方案

## 1. 阶段门禁

### R0：代码关闭态部署

- lifecycle 继续 `false/off`；
- 不创建 control；
- 不修改 Beat 周期、队列、race-live 或业务数据；
- 验证 migration plan 为零、服务健康、现有 scanner disabled。

### R1：生产 prepare + dry-run

- 先做只读库存，按未来实际日期选择 2–4 场，不硬编码当前很快过期的赛事 ID；
- 至少两个地区；
- 全部满足地区时区合同，排除 `Asia/Shanghai` 错误样本；
- 首批允许全部无 `race_datetime`，但报告必须明确只验证当地次日规则；
- prepare 写仓库外 `0600` artifact，数据库零写；
- dry-run 输出每场 predicted decision/next refresh、manifest SHA 和零写证明；
- 停止并请求用户对精确 artifact 授权。

### R2：false/off 下 control apply

- 发布前备份、HEAD/image/env filtered hash、队列/锁/磁盘预检；
- 只 apply 获准 manifest；
- 命令硬门禁确认当前进程严格 `false/off`；生产只读 preflight 同时证明 Beat/普通 worker
  也是 `false/off`，lifecycle active/reserved 和有效 claim 均为 0；
- v1 manifest 不可 apply，只接受 strict v2；
- verify control 精确集合、全部 shadow、generation=1、manifest SHA/next refresh 一致；
- 赛事状态、赛果、新闻、QQ 和 transition 均零变化；
- 保持 false/off，提交证据并再次停止。

### R3：小范围 shadow

取得新的精确授权后：

- 显式 `RACE_EVENT_LIFECYCLE_ENABLED=true`；
- 显式 `RACE_EVENT_LIFECYCLE_MODE=shadow`；
- 只重建读取这些环境值的必要 Beat/普通 worker；
- 不启动或改变 race-live worker/scheduler；
- 观察至少 48 小时并跨一个选定赛事的当地次日午夜；
- 每 5 分钟 scanner 只处理 2–4 个 control；
- proposal 与人工计算逐条比对。

### R4：关闭或继续

观察成功也不自动进入 enforce。先关闭 false/off 或保持 shadow，由用户决定下一 change：

- 补齐可信 `race_datetime` 后验证 running/T+30；
- 修复错误时区赛事；
- 或准备小范围 enforce。

## 2. 首批选择标准

执行时重新从当前生产选择：

- `local_date` 位于未来 1–21 天；
- P0/P1 或 featured、published、scheduled；
- series 已 approved（作为人工质量门禁，虽非生命周期模型硬要求）；
- 地区/时区合同正确；
- 无 manual lock、无 existing lifecycle control；
- 优先法国、英国、日本和美国中两个地区；
- 美国逐场仅批准当前真实 zone；
- 不为了赶观察窗口使用已过期日期或错误时区赛事。

截至本方案盘点，近期可作为“候选而非批准范围”的例子包括法国 event `740`、美国
event `430/431`、日本 event `91`、英国 event `944`。实际 IDs 必须在 R1 当日重新核对，
本段不构成生产纳管授权。

## 3. 成功门禁

- manifest/dry-run/apply/verify SHA 一致；
- 目标 control 集合精确，无额外 control；
- 0 个 schema/timezone/DB drift error；
- 0 个公开状态、赛果、新闻、QQ 变化；
- 0 个重复 proposal；
- 0 个 cancelled/postponed 错推；
- scanner/task 无持续 error、claim 泄漏或热循环；
- 普通 Celery queue age、active/reserved 和数据库锁正常；
- 内外 healthz、日历页和赛事详情页正常；
- race-live scheduler/worker 保持原授权状态。

## 4. 失败与回滚

任一异常：

1. 立即设置 lifecycle false/off；
2. 重建必要 Beat/普通 worker；
3. 验证 scanner disabled、active/reserved/queue 无 lifecycle 残留；
4. 保留 control/proposal/manifest/日志供审计；
5. 不删除 proposal，不批量改 `RaceEvent.status`；
6. shadow 没有公开状态写入，因此不执行赛事数据反向修复；
7. 若发现非 lifecycle 业务变化，停止并按独立事故流程处理。

## 5. 与其他生产任务的边界

R1 只读可与普通内容处理并行。R2/R3 涉及数据库写入或服务配置变化，必须与新闻历史批次、
历史赛事批次、race-live admission、部署和 migration 维护窗口互斥。不得顺带处理
race-live 积压、开启 provider、重建无关服务或发布新闻。
