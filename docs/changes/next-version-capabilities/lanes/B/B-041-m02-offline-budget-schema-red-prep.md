# B041：离线翻译预算 schema 与 RED 技术准备

任务 `B041-OFFLINE-BUDGET-SCHEMA-RED-PREP-001`。固定起点 C036 `558df2a3bf83d590ccbdb010d3f73dc70d528041`，独立分支 `codex/b041-offline-budget-core`。只读方案输入 B040 `9d2fefbd965629e4fd3ad4d337e0fd5e70b226ad`；ROOT转达同R `8284247bab46ecfcb98951a4e7b7e9908ccb8113` APPROVED_PLAN_ONLY，不代表本候选通过 review 或 CI/main/生产。

本次授权为新增两账 schema、专用 manager、正常可导入零写 stub、独立合成 fixture/测试及B文档。**状态机未实施；测试=0；迁移未执行；无 Django/PG/容器启动。** 原自动重试仍使用既有 B039 路径，跨 claim 消耗预算缺口仍存在。门禁仅引用根 AGENTS.md；本次无合并、发布、生产或外部消息动作（仅按既有授权向ROOT交接）。

## Schema 与边界

新增 `TranslationRetryBudget`、`TranslationRequestAttempt`，以及各自 QuerySet manager。既有 models 顶层节点 AST 全部保持；只追加四类。新账不注册 admin，无 Article/Run 外键；原对象 PK 是普通可空 BigInteger 快照。唯一关系为 attempt→budget（PROTECT），不进入原文章/run collector。文章删除仍由既有 CASCADE、头条失效 signal 等负责；无新 signal/TTL/清理入口。

预算保存 operation_uuid 与 budget_uuid 双唯一身份、完整独立来源 pair/digest、源摘要、provider/model/policy 快照/hash、逻辑起止期限、请求上限/已用槽、阻断/退役状态。请求保存预算引用与原操作/预算/claim UUID、原 claimed_at、原文章/run PK、来源快照、全局 seq、provider_attempt_index、reserved_at、usage/validation/reconciliation/receipt。初建要求显式 UUID；不从新 claim/PK/settings 生成续期或充值行为。

普通 Model.save 已有行拒绝，初建强制 INSERT 防同 PK 覆盖；Model.delete、QuerySet.delete/update/bulk_update、bulk_create(update_conflicts=True) 拒绝。base/default manager 同为受限 objects。计数与状态的专用锁内更新尚未存在；后续 GREEN 需专用 helper，不开放普通 ORM 写口。这些是业务 ORM 限制，**不是管理员 SQL 不可篡改保证**；跨表快照一致性/退役历史解析由未来 helper 核，不冒称 DB CHECK 已实现这些语义。

## Migration / DDL / 回滚面

固定基线 migration 图经 AST 核对只有 leaf `0079_multisource_race_enrollment`（依赖 `0078_externalhorse_profile_snapshot`）。新增准确编号 `0080_translation_retry_budget`，唯一依赖 `0079`。仅两个 CreateModel，无 RunPython/RunSQL、回填或旧表 ALTER。

| 对象 | 数据库约束 |
|---|---|
| budget | operation_uuid/budget_uuid 各 UNIQUE；`uq_tr_budget_active_source` 对(scope_kind, source_site_snapshot, source_article_id_snapshot)且 retired_at IS NULL 部分唯一；closed/blocked/exhausted 均继续占位 |
| budget | `ck_tr_budget_limit_positive` limit>0；`ck_tr_budget_reserved_bounds` 0≤reserved≤limit；`ck_tr_budget_deadline` deadline>opened；PositiveInteger 另有数据库非负约束 |
| attempt | `uq_tr_attempt_budget_seq`；`uq_tr_attempt_claim_index` (budget, claim_execution_uuid, provider_attempt_index)；seq/index>0；内部 budget FK |

以上是文件定义，尚未执行 sqlmigrate/迁移或核数据库实际 DDL。官方PG技术检查须验证创建成功、真实约束、实际无原对象FK及普通删除兼容；失败为 setup/schema finding，不能算业务 RED。首次根创建不得只锁不存在行；后续实现须依赖 active source DB UNIQUE 并受控处理冲突，不回退成两个根。

隔离测试空库逆迁移可按 Django CreateModel 逆操作先删 attempt 再删 budget；**会删除新账数据**。此逆操作没有运行，不能用于含审计/unknown账的生产环境。未来部署需单独准确发布包，保留账/停受管调用、备份恢复与观测；本候选不提供生产迁移或回滚授权。

## Stub 与行为 RED

`stable.services.translation_retry_budget` 只导入标准库，提供不可变 BudgetIdentity/BudgetDecision 和 resolve_budget/reserve_request/record_usage 三个零写函数。offline_test 返回 core_not_implemented；其他 mode 返回 supported_mode_missing。无 provider/callable、网络执行器、SDK、队列、公共 CLI/API/Beat/生产 hook，无调用者接入 tasks/recovery/translation/settings。

fixture 用正常 ORM INSERT 建立完整身份/期限/合成 policy，测试不调用 stub 建 fixture、不借 update 绕过 manager。合成已用槽/unknown 初建是离线反例输入，非 legacy 回填策略或真实费用证据。schema 与业务两组分离；缺 import/fixture/连接/迁移错误必须先修技术准备。

全部 canonical 前缀 `stable.test_translation_retry_budget.`：

| 分组 | 精确类/方法 | 预期（未运行） |
|---|---|---|
| schema | TranslationBudgetSchemaTests.test_active_source_unique_including_closed | PASS：closed 新根同 pair SQL UNIQUE 拒绝 |
| schema | TranslationBudgetSchemaTests.test_counter_bounds_database | PASS：0 limit / over-limit SQL 拒绝 |
| schema | TranslationBudgetSchemaTests.test_attempt_unique_sequence_and_claim_index_database | PASS：seq/claim-index SQL 冲突 |
| schema | TranslationBudgetSchemaTests.test_audit_orm_guards_separate_from_database | PASS：ORM 修改/删/冲突更新与同PK覆盖拒绝 |
| schema | TranslationBudgetSchemaTests.test_article_delete_preserves_independent_audit | PASS：原 article/run 删除，账保留快照，实库 FK 仅账内 |
| schema | TranslationBudgetSchemaTests.test_production_mode_refuses_without_writes | PASS：生产模式拒绝且零写 |
| RED首个 | TranslationBudgetCoreRedTests.test_reservation_persists_counter_and_attempt | counter仍0，而应1并持久attempt |
| RED首个 | TranslationBudgetCoreRedTests.test_unknown_consumption_blocks_new_claim_with_specific_reason | 应usage_unknown，stub尚无解析 |
| RED首个 | TranslationBudgetCoreRedTests.test_same_source_delete_recreate_resolves_retained_root | 应命中含已用槽/unknown的旧根，不重置期限/账，不新授权 |
| RED边界 | TranslationBudgetCoreRedTests.test_old_operation_cannot_authorize_reused_pk_new_source | 应identity_changed，旧PK不能作权威 |
| RED并发 | TranslationBudgetCoreRedTests.test_two_consumers_last_slot_single_reservation | 两个独立PG backend同时进入；应1胜者，stub为0 |
| RED并发 | TranslationBudgetCoreRedTests.test_concurrent_first_create_resolves_one_authoritative_root | 正常合成无历史baseline；应同一根且冲突无泄漏，stub未建根 |

并发 harness 两个独立 PG backend、Barrier、join/连接关闭，并先断言零线程/连接错误；最多主连接+两worker=3。当前 Barrier 证明并发进入，未实施 helper 不会产生预算锁等待；不称已观察行锁串行。后续 GREEN 还需补真实锁后 deadline/未知状态竞态、迟到报告、历史/退役/源版本/策略与 UUID 更换等全合同。本12不覆盖全部B040验收，不能缩 formal/catalog/full 分母。

## 静态证据与官方窗口请求

runtime `/Users/mentianlu/.codex/runtime/b041-schema-red-prep-001/static-receipt.json` 与 `test-ids.txt` 保存固定输入、12源码指纹及完整 IDs。静态 AST/语法（compile，不执行模块）、迁移图与旧models节点比较通过；git diff --check 通过。8个 trusted runner/control 加 tasks/recovery/translation/settings 共12文件与固定基线逐字节一致；所有旧migration保持。正常运行时 import/fixture/schema 仍待窗口验证，静态检查不能代替。

请求 ROOT 精确绑定本候选 SHA 的官方隔离 PG16 窗口：12 IDs（6技术+6目标行为），主+2worker最多3连接，既有固定 image `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`，原可信 runner、network none/nonroot/只读源码、600秒总边界，专用 runtime/FD锁与最终退出清理；不构建/拉镜像，不连release/宿主/生产DB。获确切窗口前不运行。若ROOT只派第一组，优先6技术+前三个业务RED，保留其余3明确待验，不改分母。

## 后续责任

- (integration) 测试：按ROOT窗口先确认正常 schema/fixture，再记录业务 RED 与 zero errors；技术失败先返修，不实施状态 GREEN。
- (integration) 实现：待ROOT另派，完成离线身份/首次冲突/预算锁与usage状态合同，仍无生产 caller。
- (application) 验证：原 admin 单/批删及头条失效完整兼容、迁移逆操作及全B040边界另需窗口；当前未声称通过。
- (operations) 交付：ROOT安排同R独立只读 review 和后续集成，B不改C036候选、不合并/迁移/发布。

完整M02的真实金额/token上界/账户日账、可信unknown对账、真实SDK/enforce接入和outbox仍未完成。
