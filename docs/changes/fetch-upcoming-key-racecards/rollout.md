# 未来七天重点赛事官方数据 rollout

## 当前门禁

当前为 `plan review pending / implementation not authorized / apply count 0`。本文件描述后续
获授权后的顺序，不是可立即执行的操作单。

## 阶段 1：本地实现

1. 重新确认最新、干净 `origin/main` 和并行赛果恢复 change 的 overlap。
2. 取得测试真实 RED，subagent 完成实现，主代理整合验证。
3. 全程使用 fixture/fake transport；不使用生产 secret，不联网。
4. 独立 reviewer 执行原生只读 review；关闭 finding 后冻结 fingerprint。

## 阶段 2：受控来源 proof

需要新的精确联网授权，且只允许来源合同中 `automation_allowed=true` 的 route：

- 限定 provider、region、route、时间窗、最大请求数和唯一 output 目录；
- 无 redirect、无自动重试、限速、响应大小和内容类型 fail closed；
- 不写数据库、不 dispatch Celery；
- 保存成功或失败 receipt 和 SHA，不能覆盖重跑；
- 未取得许可的 Equibase/BHA/France Galop 赛前页面继续为 0 请求。

## 阶段 3：候选审核

1. 冻结 inventory 和来源合同；
2. prepare 不可变 artifact；
3. dry-run 输出每场 raw/normalized/中文值和字段 diff；
4. 审核 expected/confirmed/applicable/blocked 覆盖；
5. active staff 通过认证 Admin review 动作创建不可更新/删除的数据库 approval row；再从
   该 row 导出 artifact 外的 receipt，绑定 manifest、content、inventory、source contracts、
   范围、真实 request actor/时间和 verdict；
6. 独立 verifier 在零写模式复算。

若仍无合规官方机器来源，阶段 3 的正确结果是全部 blocker、0 条可 apply，而不是补用第三方或
手工抄录凑齐。

## 阶段 4：本地/测试数据库验证

取得精确数据库目标授权后：

- 先备份目标测试库；
- apply 锁定 `expected_approval_sha256`，核验 receipt 后再锁 projection control，单事务执行；
- 记录写前/写后 event、runner、地区与状态计数；
- 相同 SHA 重放验证 noop；
- 注入冲突验证完整回滚；
- 执行独立 verifier 和 CAS rollback 演练。

## 阶段 5：生产门禁

本 change 不含生产授权。若未来要求生产 apply，必须先提交：

- 精确 artifact 路径与 SHA；
- 每场来源、时间、runner 字段 diff；
- 影响 `RaceEvent`/`RaceEventRunner` 的精确行数；
- blocker 和不覆盖项；
- 数据库备份路径、SHA、restore 检查；
- rollback manifest、命令和预计停写窗口；
- 最新 code review fingerprint 与 dry-run/verifier 结果。

只有用户明确批准该批次后才能 apply；授权后内容或 SHA 变化必须重新 review 和授权。

## 回滚

- apply 事务内失败：自动全批回滚。
- apply 后字段错误：使用已审核 rollback manifest 做写后 CAS；数据库已被其他任务修改则停止。
- 仅代码回滚：回到批准父版本，不删除 additive 审计证据。
- 只有确认数据库级损坏且字段级 CAS 无法恢复时才使用整库备份。

## 每日任务可行性

当前结论：**NO-GO**（跨地区无人值守官方赛前数据任务）。

原因：

- 美国官方 entries 页面可人工访问，但已记录条款禁止未授权机器人抓取/再发布，当前 contract
  仅允许赛果人工核验；
- 英国官方赛前动态页在本次证据时点没有可用结构化 racecard，旧 contract 只覆盖赛果；
- 法国官方赛前入口要求登录，旧 contract 只覆盖赛果；
- TRA 的 T-7 能力依赖商业档位且不是官方权威，不能单独满足本任务。

取得合规来源后建议：

- T-7 每日一次 inventory；
- T-3 起每日 2 次刷新，T-1 到 post time 每 2–4 小时一次；
- 每次生成新不可变 revision，按稳定 ID upsert，退赛/时间修订保留证据；
- 429/5xx 指数退避并服从 Retry-After，身份/合同/结构错误不重试；
- 监控覆盖率、最早/最晚发布时间、source age、blocker、冲突和 verifier；
- 关键缺失、官方源不可用或结构漂移告警并转人工复核；
- 官方源不可用时可保存第三方补充信号，但不得降级为官方写入。

上述频率只是待验证假设；至少需连续 4 周、多地区、多类赛事的合规来源证据后再作 go/no-go
复评。创建或启用每日任务需要独立方案、review 和用户授权。
