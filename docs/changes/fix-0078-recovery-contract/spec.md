# 0078 发布与恢复合同修复方案

## 1. 状态与范围

- 日期：2026-09-07；方案 r2 已获准，当前为实施记录。
- 基线：main@a88bcbf669bd609e30f97c8a07f009881d2da705。
- 用户已明确要求开始实现，完成后由独立子 agent 测试，并要求避免过度设计/实现。
- 当前指令覆盖本修复的实现、验证与必要技术修正。交付与生产动作统一引用根 AGENTS.md 的 G2/G3。
- 已取得完整仓库，在独立 codex/fix-0078-recovery-contract 分支/worktree 工作。方案审核时使用的固定源码证据和 r2 指纹保留为历史记录；本阶段不执行生产操作。

## 2. 要解决的问题

生产交接记录已应用 0078_externalhorse_profile_snapshot，但当前发布与恢复控制面仍以 0077 为最终状态。这不仅影响一个回滚测试：正常发布的 migration graph、handoff、恢复完成和恢复服务也可能拒绝 0078。

关键证据（路径行号相对于上述基线）：

| 证据 | 含义 |
| --- | --- |
| server/stable/migrations/0078_externalhorse_profile_snapshot.py:15 | 增加 profile_snapshot JSONField；反向执行明确抛 IrreversibleError |
| deploy/verify_rollback_target_migration.py:18、117、206 | 文件白名单、迁移上限、最终叶子仍为 0077 |
| deploy/reviewed_release_b_rollback_migrations.json | generic_code_rollback_allowed=false，reviewed_targets=[]；禁止普通代码回滚是既定策略 |
| server/stable/services/historical_calendar_release_b_schema.py:32、114、485 | TARGET、可接受状态及后续迁移检查仍停在 0077 |
| server/stable/services/historical_calendar_release_b_handoff.py:47 | FINAL_LEAF_SET 为 0077，并被 intent/completion 命令复用 |
| deploy/resume_stopped_release.sh:146 | 服务恢复只接受 exact 0077 |
| server/stable/test_single_migration_owner.py:670–700 | fake Git 清单随仓库 glob 到 0078，却只提供 0076/0077 blob，并写入 0077 的模拟批准 |
| docs/test_baseline_failures_20260907.md | 记录 36 项相关失败；本轮未重跑，不能把该数字当当前实测 |

此前“提高回滚上限即可恢复回滚”的描述不准确。实际目标是恢复一条可证明安全、认识 0078 的发布/继续完成/备份恢复路径，普通代码回滚仍保持关闭。

## 3. 目标与非目标

目标：

1. 当前 exact 0078 数据库可通过只读完整性检查，正常同版本发布没有额外 DDL；失败后可在同一受绑定发布内继续完成和恢复服务。
2. 0077 → 0078 的升级与失败停在 0077 的重试均有备份绑定、关闭态复验和明确终态。
3. 0078 数据列和 recorder 一致才算完成；缺列、错类型、NULL/default 漂移、未知迁移和候选后续迁移必须拒绝。
4. 普通代码回滚与反向迁移继续拒绝；备份恢复通过隔离 PostgreSQL 16 演练，验证数据与镜像匹配。
5. 重建有真实代际边界的测试夹具，相关测试不靠降低断言、跳过或 expectedFailure 变绿。

非目标：

- 不修改已发布 0077/0078 的内容、依赖、迁移名或 hash，不新增 0079，不修改业务模型。
- 不新增可回滚生产 OID、不把 generic_code_rollback_allowed 改为 true。
- 不全面修复 235 项测试，不重构所有历史发布工具，不实现通用迁移框架。
- 不修改赛事自动化、新闻、QQ、canonical/External 数据，不操作旧 race_live 队列。
- 不在本轮 SSH、执行迁移、恢复备份、调整生产开关或发送外部消息。

## 4. 两个合同世代

本候选的主发布路径只处理“稳定 0077 → 0078”和“稳定 0078 → 0078”。更早来源状态或旧 release 的在途恢复，继续由其固定旧控制镜像与原始 artifact 完成至 0077，再以新候选建立新的升级包。

不能把旧 0077 artifact 换名、换 target 或补字段后用于 0078。旧流程并未因方案获准获得新的生产执行授权。若实时发现生产仍在旧在途状态，当前候选发布停止，先按对应旧协议恢复；不能直接改 marker 或跳过 verifier。

这是明确的兼容边界：本次不将所有旧起点自动扩展为直接迁到 0078，也不删除其历史实现和测试。设计必须让新、旧 artifact 的目标世代显式可辨，不能仅依赖全局 FINAL_LEAF_SET 改值。

## 5. 完成标准

| 编号 | 必须证明 |
| --- | --- |
| AC-01 | exact 0078 + 正确 catalog + 空 migration plan 正常通过；当前模型读取 profile_snapshot 正常 |
| AC-02 | 0077 升级到 0078 有唯一迁移 owner，升级失败原子停在 0077，重试沿用同一 candidate/备份/原始意图 |
| AC-03 | snapshot 列与 recorder 任意不一致均为结构化拒绝；不先触发依赖缺列的 ORM 查询 |
| AC-04 | 0079、同号异名、嵌套迁移、低序号插入、0078 blob/依赖漂移均被拒绝 |
| AC-05 | 仓库真实默认策略下 rollback.sh/rollback_lowcost.sh 拒绝，且 checkout/build/retag/stop/migrate/restore 均未执行 |
| AC-06 | 新旧 handoff、manifest、marker、completion receipt 不混用；首次 stop 前有持久发布意图，覆盖停止前后、marker 前后和恢复服务前后的全部重试断点 |
| AC-07 | 隔离备份恢复验证 recorder、catalog、profile_snapshot 内容、关键业务表与目标镜像兼容性；不能以 pg_restore --list 冒充恢复成功 |
| AC-08 | 相关 Linux/PG16 测试全部通过，无新增 migration；其他基线失败按名称和原因单独报告 |
| AC-09 | 发布后服务、开关、队列和业务抽样按发布包核验；方案和代码审核通过不等于生产验收通过 |

来源：
- [固定基线](https://github.com/thumentianlu1993-blip/Umanewsbot/tree/a88bcbf669bd609e30f97c8a07f009881d2da705)
- [最新交接](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/a88bcbf669bd609e30f97c8a07f009881d2da705/docs/current_state.md)
