# 未来七天重点赛事官方数据任务

## 探索与方案

- [x] (application) 从干净且与 `origin/main` 一致的基线创建隔离分支。
- [x] (application) 按现有重点赛事规则完成生产只读窗口超集盘点。
- [x] (integration) 研究实际地区官方来源、route contract、条款、稳定 ID 与发布时间。
- [x] (integration) 识别既有 JRA/HKJC/NAR、historical candidate 和 race-live 复用边界。
- [x] (application) 完成独立方案审核并关闭 P0/P1 finding。
- [x] (operations) 向用户报告最终方案并停在“确认实现”门禁。

## 测试（取得实现授权后）

- [ ] (application) 为窗口、半开边界、地区时区与 DST 编写真实 RED。
- [ ] (integration) 为 source contract、官方 event/runner ID 和 fail-closed 编写真实 RED。
- [ ] (integration) 为完整/空/局部/冲突 racecard 与退赛修订编写真实 RED。
- [ ] (application) 为 canonical revision、legacy projection、所有 writer owner、manual lock、
  lifecycle 并发、旧值保护、幂等、事务回滚和独立 verifier 编写真实 RED。
- [ ] (operations) 为 canonical manifest、immutable DB approval、receipt、伪造 actor/
  替换/路径逃逸编写真实 RED。
- [ ] (operations) 为无网络 fixture 和 transport 零调用编写真实 RED。

## 实现（取得实现授权后）

- [ ] (application) 实现确定性窗口 inventory 与覆盖快照。
- [ ] (integration) 实现版本化官方来源合同和 transport 前许可门禁。
- [ ] (integration) 实现受控缓存、parser 和不可变候选 artifact。
- [ ] (application) 实现 dry-run、字段 diff、覆盖审核与批准 manifest。
- [ ] (application) 新增 immutable approval model/migration 与认证 Admin review 动作；
  receipt 只能从 approval row 导出。
- [ ] (application) 实现 SHA 锁定、事务化幂等 apply、旧值保护和 rollback manifest。
- [ ] (application) 复用现有 observation/revision/participant/source identity canonical 链，
  通过 projection control CAS 投影 legacy runner，并记录 field authority/change。
- [ ] (application) 实现与 apply 解耦的独立 verifier。
- [ ] (operations) 在状态/决策/运维文档写明实际命令、边界与恢复步骤。

## 验证与审核

- [ ] (integration) 跑聚焦测试和既有 parser/candidate/racecard/realtime/lifecycle 回归。
- [ ] (operations) 跑 Django check、migration drift、OpenSpec 兼容检查和 diff check。
- [ ] (application) 派出未参与实现的 reviewer subagent，并实际执行 Codex 原生 review。
- [ ] (application) 关闭 findings，冻结 scope、fingerprint、approved parent 和 content hash。

## 数据批次门禁

- [ ] (operations) 生成精确官方来源 candidate、coverage、blockers 和 artifact SHA。
- [ ] (application) 完成字段级人工 review 与独立 verifier dry-run。
- [ ] (operations) 本地/测试数据库 apply 需单独确认目标数据库与批次。
- [ ] (operations) 生产 apply 前生成影响行数、备份、rollback、写前 fingerprint，并等待用户
  对该精确 artifact SHA 的明确授权。

## 每日化

- [ ] (integration) 取得各地区允许自动化的官方/授权 entries 数据合同。
- [ ] (operations) 用多日证据统计最早/最晚公布、修订频率、覆盖率和限流。
- [ ] (operations) 另行设计重试、监控、告警、人工复核和官方源降级策略。
- [ ] (operations) 只有另获授权后才创建或启用每日任务；本 change 不改 Celery beat。
