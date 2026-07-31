# 历史赛事赛历完整性方案审核

## 审核范围

- `spec.md`
- `design.md`
- `test_cases.md`
- `tasks.md`
- `rollout.md`
- 直接相关模型、历史赛事服务、公开赛历 view、年度 collector、旧在途 OpenSpec 和 runbook

reviewer 全程只读，未修改文件。

## 审核结果

- Round 1：`REVISE`，3 P0 / 7 P1 / 3 P2。
- Round 2：`REVISE`，10 项关闭，剩余 1 P0 / 2 P1。
- Round 3：剩余 findings 全部关闭，未出现新的直接 P0/P1。
- 最终 verdict：`APPROVED`。
- 开放 P0/P1：0。
- artifact consistency：通过。

## 审核锁定的关键修订

1. 最终自然年约束以全地区 census/action 为前置；合法跨届次也修公开 year/path，只保留 edition。
2. 连续错年多对一使用 survivor + superseded target + detached permanent-draft tombstone event，
   不再假设所有 event PK 都可保持 active。
3. schema 分为 Release A/B/C 三个独立 commit/image/migration leaf，后续 leaf 不得提前存在。
4. canonical/legacy 使用单表 public-path registry，建立统一路径唯一命名空间。
5. apply 绑定 manifest/approval/action/actor，并以 Release A 的
   `HistoricalRaceCalendarRepairReceipt` 作为 exactly-once 提交权威。
6. data apply 前必须 maintenance/freeze；业务写与 `APPLIED` receipt 同事务，crash 后以 receipt
   判定状态。
7. Release C 后不能直接恢复违反自然年 check 的旧值，必须先反向约束 migration 或恢复整库备份。
8. 游标使用跨 SQLite/PostgreSQL 一致的 null-bit tuple、签名筛选指纹和默认窗口 anchor。
9. collector 正式验证只允许 fresh output root，不迁移或修改旧不可变 checkpoint。
10. 旧香港赛季跨年 reason、旧公开年份与历史重点合同已被精确取代。

## 下一门禁

方案审核通过不授权实现。主线程必须先向用户汇报最终范围、RED、数据边界、风险和回滚；只有用户
针对本方案明确回复“确认实现”“开始实现”“继续实现”或同义语句，才可编写测试并取得真实 RED。
