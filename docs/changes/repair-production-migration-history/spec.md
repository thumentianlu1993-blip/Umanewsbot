# 生产 migration history 一致性修复规格

## 1. 背景

Release B 的首次生产发布在任何新 migration 执行前被 Django
`InconsistentMigrationHistory` 阻断。生产 `django_migrations` 已记录：

- `stable.0067_historical_calendar_release_a`
- `stable.0070_horse_identity_evidence_commit_receipt`

但没有当前主线中 `0070` 的父节点 `0068/0069`。只读审计进一步确认：`0070` 对应 receipt
表、sequence、主键、两个唯一约束、外键和 pattern index 已存在且已有 7 条有效 receipt；`0068`
的 11 个字段与 `0069` 的 check constraint、trigger、function 全部不存在。

Git 时间线表明 receipt migration 最初名为 `0068_horse_identity_evidence_commit_receipt`，直接依赖
`0067`；生产 recorder 在重命名提交前约两小时已写入 `0070`。随后提交把该 migration 重命名为
`0070` 并把依赖改成 `0069`，造成当前 graph 与既有生产事实不一致。

## 2. 目标

1. 把 migration graph 表达为两个从 `0067` 分叉、在 `0071` 汇合的合法分支：
   `0067 -> 0068 -> 0069 -> 0071` 与 `0067 -> 0070 -> 0071`。
2. 不删除、不补写、不 fake 任何生产 migration recorder 行。
3. 生产从当前状态只需真实应用 `0068`、`0069`、`0071`，不得再次执行 `0070` 的 `CreateModel`。
4. 新安装数据库仍能创建完整 receipt、field audit、ledger guard 与 Release B 约束。
5. 候选镜像 preflight 必须证明 recorder 与 `0068/0069/0070/0071` 实际 schema 精确一致；缺表、
   缺列、错误约束、部分 DDL 或未知 migration 均 fail closed。
6. preflight 必须比较受审 `production_audit.json` 中的 receipt 与 operation-log expected baseline，
   并在服务停止后、migration 前消费同一不可变 handoff artifact 做第二次核验。
7. `0071` 部署成功后才恢复 Release B 的 v2 census、人工审核、生产回填和 2025 full-network 门禁。

## 3. 范围

- 调整 `0070_horse_identity_evidence_commit_receipt` 的 dependency，使其恢复为 `0067` 的独立分支。
- 调整 `0071_historical_calendar_release_b`，使其同时依赖 `0069` 和 `0070`。
- 扩展 Release B schema preflight 与 wrapper，识别受控的双 leaf/中间恢复状态，并验证精确 schema。
- 增加受审生产 audit baseline、mode `0600` no-clobber preflight artifact 和关闭态二次核验入口。
- 增加 SQLite graph 测试、真实 PostgreSQL legacy/fresh/mismatch/partial-state 测试和部署合同测试。
- 更新本 change 五份文档及项目状态/运行手册。

## 4. 非目标

- 不修改 `django_migrations` 数据。
- 不使用 `--fake`、`--fake-initial` 或手写 INSERT/DELETE 修复 recorder。
- 不改变 receipt 业务数据、P0 马匹数据、赛果同步数据或 81 条历史赛历 mismatch。
- 不在修复 migration 中运行 v2 census、maintenance、apply、verifier 或 full-network workflow。
- 不启用任何 `RACE_DATA_SYNC_*`、historical write/network、race-live 或自动发布开关。
- 不处理 HTTPS、新闻翻译或其他生产队列问题。

## 5. 验收标准

1. production-like recorder `{0067,0070}` 对候选 graph 通过 Django consistent-history 检查。
2. 该状态的 forward plan 精确为 `0068 -> 0069 -> 0071`，不包含 `0070`。
3. 真实 PostgreSQL legacy fixture 中既有 receipt 行、主键、SHA 和 operation-log 外键在迁移前后
   完全不变。
4. 迁移后 `0068` 的 11 个字段和 observation FK 完整，`0069` 的 decision check、append-only
   trigger/function 完整，`0071` 的两组新唯一约束完整，pending plan 为零且唯一 leaf 为 `0071`。
5. fresh PostgreSQL/SQLite 从零迁移到 `0071` 成功，receipt 表只创建一次。
6. recorder 与 schema 不匹配、未知 applied node、非法 leaf 组合或部分 DDL 时 preflight 返回机器可读
   `ok=false`，且部署脚本在停服务/迁移前停止。
7. 中断在 `0068` 或 `0069` 后的受控恢复状态只有在对应 schema 完整时才允许重试。
8. 任一 receipt 字段、被引用 operation-log 字段或 FK 集合相对受审 baseline 漂移时，在第一次
   preflight 或关闭态二次核验中停止；migration 调用次数为零。
9. 固定旧镜像在 `0068-only` 与 `0069-complete` 两种 partial schema 上通过关闭 flags 的容器启动和
   只读 smoke；该状态只允许同一候选 forward resume，不得执行其他 deploy/migrate。
10. Django check、migration drift、聚焦回归、两份 Compose config、shell syntax 与 diff check通过。

## 6. 失败边界

- receipt contract 任何一项未知或不匹配：停止，不猜测 adoption。
- 7 条 receipt 或其 operation log 发生漂移：停止，不继续迁移。
- 第一次 preflight artifact 缺失、可覆盖、权限/owner 不可信、commit/image/DB/lock token 不匹配，
  或关闭态二次核验不一致：停止且零 migration。
- 生产出现计划外 applied migration 或 migration plan 不等于允许序列：停止。
- `0068/0069` 出现 recorder/schema 部分状态：停止并保留旧应用，不自动反向 DDL。
- `0071` 约束 preflight 冲突：停止，不修改 81 条业务数据来迁就部署。
