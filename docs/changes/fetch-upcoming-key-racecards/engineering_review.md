# 未来七天重点赛事官方数据方案工程审核

## 审核会话

- reviewer task：`/root/upcoming_racecards_plan_review`
- 审核类型：实现前只读 `plan-eng-review`
- 最终结论：`VERDICT: APPROVED`
- 审核未联网、未修改代码、未写数据库、未部署。

## 首轮 findings

首次结论为 `REVISE`：

1. high：新链路没有对齐现有 revision、participant、field authority 和 projection owner。
2. high：`RaceEventRunner` 不能表达 source-scoped runner identity。
3. high：只传 artifact SHA 不能证明已人工批准。
4. medium：19 场清单使用了不真实的谓词且缺可重放 snapshot。
5. medium：逐来源条款/许可缺 locator、digest、有效期和分类。

## 第一轮修订

- 明确复用
  `RaceResultSourceIdentity → RaceResultObservation → RaceEventRevision →
  RaceEventParticipant` canonical 链，legacy runner 只作 current revision projection。
- 使用现有 `RaceResultPhase.RACECARD`、projection control CAS、field authority/change、
  manual lock 和 lifecycle generation。
- runner identity 改为
  `(source_identity, external_runner_id)`。
- 定义 canonical manifest 与 artifact 外 approval receipt。
- 新增生产只读 snapshot，SHA-256
  `cc87c32cb56f75af43f7d67a8beb281385f99c781549e38ac9e462143e14a319`。
- 补齐 policy/research locator、digest、有效期和 `manual/unknown/blocked`。

限定复审保留 3 个 high：

1. source research/decisions 残留虚构 phase。
2. 跨来源 participant 合并依赖不存在的 horse external ID 映射。
3. receipt 内填写有效 staff ID 仍可伪造批准者。

## 第二轮修订

- 全范围统一 `phase=racecard`，具体时间/declaration/revision 语义进入 provenance；
  TRA racecard 为 `source_authority=supplemental`。
- 本 change 禁止跨 source participant 自动合并；来源切换整场 blocker、零写。
- 新增 `UpcomingRacecardArtifactApproval` 方案：
  - 认证 Admin `request.user` + 专用 permission 创建；
  - PostgreSQL trigger 与应用层同时拒绝 UPDATE/DELETE；
  - receipt 只能从 immutable DB row 导出；
  - apply 锁定并反查 approval row，拒绝手工伪造 actor/receipt。

## 最终复审

同一 reviewer 会话只核对上轮 findings、修订和直接触及路径，确认全部关闭，最终：

```text
VERDICT: APPROVED
```

残余外部风险：

- migration trigger、Admin permission、锁和伪造 receipt 测试尚未实现；
- 官方机器赛前来源仍不可用，当前 applicable/apply 均为 0；
- 审核不构成实现、联网、生产写入、部署或调度授权。
