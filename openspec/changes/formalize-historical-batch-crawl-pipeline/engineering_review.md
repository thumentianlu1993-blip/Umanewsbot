# 工程评审

Review mode: Full（profile: feature）

结论：**APPROVED**。proposal、design、两份 delta spec 与 tasks 已形成完整、可测试、可回滚的实现边界；没有剩余架构、数据一致性、性能或生产安全阻断项。

## 范围与复用

- 继续使用现有 approved inventory/selection、historical runner、请求预算、source cache、地区详情 preparer、日期/来源 apply 和最终 candidate importer。
- 最小新增面为 plan builder、通用 fragment merger、阶段 verifier，以及 historical runner 对正式 plan 资源身份的校验；不新增模型、迁移、第三方依赖、Celery task 或公开页面。
- `tmp/build_batch005_*.py` 只作为行为参考和历史证据，不进入镜像白名单，不复制到新 artifact。

## Round 1

1. **shard 声明没有约束工具实际读取的目标集合**：仅在 descriptor 列 target ID，仍可能让 events CSV 或 selection input 多抓/漏抓。已改为 typed recipe + per-tool target-binding policy，禁止任意 argv 和无 policy 工具。
2. **plan 请求预算未与 runner phase env 绑定**：声明值可能与实际 settings 不同。已新增正式 plan `resource_limits`，runner 在创建/恢复 run 和取双锁前逐项比较。
3. **gap 可能掩盖完全遗漏**：若 merger 自动把无输入目标转 gap，accounted 看似完整但无证据。已要求 gap 必须有 selection/target SHA、原因、来源或失败身份和时间；完全缺失直接失败。
4. **verifier 只靠代码约定只读**：业务角色仍有写权限。已要求 PostgreSQL `transaction.atomic()` 内首先执行 `SET TRANSACTION READ ONLY`，并加入意外写入失败测试。

## Round 2

1. **多个 shard 共用 artifact 根会共用 250 次请求账本**：已改为每 shard 独立宿主目录、挂载根、账本、cache manifest、state 和 lock；父 stage 只保存身份与全量覆盖汇总。
2. **逐文件 rename 仍会发布半套 artifact**：已改为同级临时目录完整构建、文件/目录 fsync、校验后一次目录 rename，目标目录预先必须不存在。
3. **缺少规模性能合同**：已锁定 1250 targets、10 shards、每场 20 runners/results；纯 artifact 编排不超过 30 秒/256 MiB，数据库 verifier 不超过 20 条查询。

## 验收门禁

- 实现前先完成 `test_cases.md` 并写入失败回归。
- 完成后运行聚焦测试、完整 stable、Django check、迁移漂移、OpenSpec strict/all、diff/shell 检查和性能合同。
- 代码必须反复 review、修复、重新 review，直到一次 review 无 actionable finding。
- 生产部署保持历史公开、常驻网络和常驻写入关闭；每次 apply 前独立备份，写后逐 target verifier error=0 才进入下一阶段。
