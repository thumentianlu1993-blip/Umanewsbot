# B041：离线翻译预算核心与验证记录

当前进入 `B041-GREEN-OFFLINE-CORE-PREP-001`：离线 helper 已写，尚未运行 GREEN；下文首阶段内容保留为固定703e1620的技术准备历史，最新状态见末节。

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


## B041-FIRST-12-SCHEMA-RED-PG-WINDOW-001 已实测

ROOT 精确批准703e162074b28a8cacc971973604be724e20178a的单次12项官方窗口。receipt `/Users/mentianlu/.codex/runtime/b041-first-12-schema-red-pg-window-001/red-receipt.json` SHA256 `278e19bf4b263a01c6c1a12812d4dddb199026f91a2a18de09eb2e110847f0a7`，ROOT已核原始8seals/IDs/tracebacks并认可RED。

实际6schema PASS、6业务 FAIL、0ERROR、0skip，lifecycle complete/exit1；PG16.15/Django5.2.1，业务3.990s/worker40.266s/全窗50.640s。Django隔离testDB已前进迁移并实际验证独立新表/约束、无原对象FK和原Article/Run删除保留账。失败依次是counter0!=1、未知未给usage_unknown、删建未解析旧root、PK复用未给identity_changed、并发0胜者/应1、首次并发0根/应1。并发当时证明两个独立backend/Barrier，无预算锁实现；采样仅最大1client，不作真实峰值或行锁证据。

owner64564/runner64590均ps不存在、容器0、FD锁实重取释放；固定源码/12指纹未变且工作树clean。此窗口没有逆迁移、额外sqlmigrate/showmigrations、admin/头条回归或生产动作。原候选与runtime封存，不重写该RED证据。

## B041-GREEN-OFFLINE-CORE-PREP-001 当前实现（未运行 GREEN）

ROOT认可RED后授权离线状态实现和必要B测试/文档，禁止自行启动DB；本轮仍无数据库/容器运行。测试设计先记入 `B041-m02/test_cases.md`，沿已审B040合同；新增边界未单独跑RED，遵从本轮禁止DB窗口指令，不伪报它们已有运行证据。

- resolve_budget：mode/输入/外层事务门槛（来源接受普通str或项目SourceSite枚举的持久值，其他自定义字符串不接受）；按旧operation UUID优先，完整精确来源pair（含digest）校验，不按PK/内容猜身份；同源陌生UUID返回保留根+operation_resolution_required，不授权；仅retired历史也不另建。首次只允许精确合成无历史消费baseline，逻辑UUID在账端分配；active-source唯一冲突采用内层savepoint，仅该约束名可处理，随后加锁读取已存在根。再次initial_contract不改上限/期限/policy。没有自动retire/clearunknown/renewal入口。
- reserve_request：普通外层atomic拒绝；预算根→请求固定次序（不取原Article/Run锁）；幂等claim/index不新授权，reserved/unknown先阻断，合法usage但未对账仍阻断；源/模型/provider/policy漂移不充值；锁后用max(输入now,actual clock)复核固定deadline。计数递增和新attempt同事务，allowed返回前提交，失败整体回滚，不退槽。
- record_usage：锁预算→确切请求，原操作/预算/来源/摘要快照一致；只接受builtin有限JSON（64KiB/16层），prompt/completion/total为非bool非负整数且sum一致。缺/非法报告留unknown，合法报告没收据仍cost_unreconciled。首份报告冻结，重复幂等、冲突不覆盖；同份已知报告可补一次严格绑定budget UUID/attempt/usage SHA的synthetic_offline_usage_v1收据。无效首份报告需要后续独立审计修复合同，本片不自动替换。迟到报告只改旧请求，不受原文章删除影响、不续预算期限或退槽，也不回写正文。
- 内部写入只允许预算requests_reserved和请求状态/usage/收据字段，要求短atomic；普通ORM保护不变。原model/migration0080字节与703e1620保持，无新状态字段/索引/原对象关系。缺省production模式直接supported_mode_missing，生产路径零caller。offline_reconciled明确是测试状态，不是真实费用对账/下一真实付费调用授权。

政策hash是明确注入、被冻结的离线版本标识；合成policy/receipt不是价格或实际历史无消耗证据。本片不把token报告总数冒称输入硬预留/账户账，也不提供真实SDK执行器。无SDK/provider/队列/callable/公开CLI/API/Beat、没有把旧selector重试改成预算enforce。

### 原12保持与新增风险用例

原12 IDs及所有assert AST保持；原unknown、同源删建、last-slot三个方法仅在构造新来源pair时补其canonical identity_sha256（原fixture沿用了旧pair摘要），没有降低断言。基础fixture另冻结timezone.now为self.now，支持actual-clock锁后检查与受控跨deadline，不用过期的固定日期导致无关环境失败。原703e1620 RED报告保持不变；这些输入修正有明确diff理由。

新增27方法，总39，无继承测试重复分母：边界22、实际PG锁3、admin/头条1、迁移1。风险覆盖幂等/unknown不退槽、合法用量缺费用证据、synthetic收据及幂等/冲突、JSON/整数非法、身份/历史/版本漂移、外层事务、两处存储回滚、迟到report/错配、ORM identity修改/更新创建、实际两次missing-root读取后的unique冲突（保存实际约束名）、last-slot两worker锁等待/单胜者、等锁跨截止0slot、迟到审计锁序。测试只验证离线状态，未执行前不称GREEN/行锁观察成功。

删除组使用合成superuser直接调用原admin delete_model/delete_queryset，带预算reserved/unknown屏障和原run，核头条selection清空/version+1、推荐失效、原run CASCADE、新账/快照/期限/计数保留；不是线上账号/UI权限实测。迁移组只允许test_前缀隔离PG且两新表为空，执行0080→0079→0080，finally恢复，核旧Article保留；明确drop表会丢账数据，绝非生产回滚测试或授权。

### 固定候选与资源请求边界

GREEN候选/完整39 IDs/新旧AST对比/117拟运行IDs封存在新runtime，准备阶段只AST/compile（不导入）和diff检查。精确相关回归为原B03930+B03725+recovery22=77，外加原headlines `stable.test_editorial_headlines.InvalidationTests.test_delete_article_invalidates` 1项，合计39+77+1=117；既有63含M01证据保持，M01本片未改不机械重跑，未缩正式catalog/full分母。

请求ROOT另派精确GREEN SHA的official django PG16窗口：单批117<=200，既有固定image/可信8controls，1container、2CPU/4GiB/256pids/3GiBtmpfs，none/RO/nonroot/capdropALL/NNP，主+2worker最多3连接；600总窗/570止测/30清理、FD锁/存活信息/最终容器进程锁清理。迁移往返仅新独立测试库空账表，不生产migrate。ROOT验证器占用本地资源期间本B不启动DB。下一终点是117实测证据与同R独立只读review；不能以静态检查或代码完成称完整M02/enforce/费用上限完成。

## B041-FIRST-117-GREEN-PG-WINDOW-001 与 fixture 技术返修

ROOT给固定25add5cca32abfab4ecbf91e8b7f3010fdf7dfa9的单次117窗口已运行。receipt `/Users/mentianlu/.codex/runtime/b041-first-117-green-pg-window-001/green-receipt.json` SHA256 `279b08c47e2230939356b3aa297d9b9a4151c72a56743a73bb202fb38ea0175a`，实际117 unique canonical IDs全执行，116PASS/1canonical FAIL（bulk=True子例）/0ERROR/0skip，complete/exit1。业务36.129s/worker72.067s/全窗82.779s。**不是117 GREEN。** 原12及无关78回归全部PASS，B041其余38PASS；PG真锁、unique初建冲突、空账往返都有实际marker。

last-slot预算锁118→115、119→118且单胜者；等锁跨deadline122→120拒绝0slot；迟到usage锁125→123保留计数/期限；数据库唯一冲突`uq_tr_budget_active_source`实际捕获；空testDB0080→0079→0080恢复、原Article保留。admin单删及批删的原对象删除/头条/推荐失效前置断言均过，但bulk最终审计PK断言失败：root/article快照60，传入identity沿用59，attempt按该输入保留59。owner76297/runner76321消失、容器0、FD锁释放且源码clean未改；ROOT已核释放。

ROOT派 `B041-ADMIN-FIXTURE-PK-REPAIR-PREP-001`，只修测试共享`fresh_root`中`replace(identity)`同步`article_pk_snapshot=self.budget.article_pk_snapshot`。业务helper、models/0080、原生产文件及controls不改；39测试方法及其全部断言保持原AST，未降低PK断言或挑单subcase。fixture构造新root后输入现与root审计快照一致；没有新增产品/身份行为。

静态直接调用映射只有5方法，重验请求保留整个方法及所有子例：

- `stable.test_translation_retry_budget.TranslationBudgetBoundaryTests.test_invalid_missing_bool_negative_and_total_usage_stays_unknown`
- `stable.test_translation_retry_budget.TranslationBudgetBoundaryTests.test_retired_history_and_old_uuid_never_allocate_new_operation`
- `stable.test_translation_retry_budget.TranslationBudgetBoundaryTests.test_usage_wrong_budget_or_snapshot_cannot_modify_attempt`
- `stable.test_translation_retry_budget.TranslationBudgetLockTests.test_last_slot_two_actual_locked_consumers_have_one_winner`
- `stable.test_translation_retry_budget.TranslationBudgetDeleteCompatibilityTests.test_admin_single_and_bulk_delete_keep_audit_and_headline_invalidation`

上述5包括原4PASS方法和完整admin单/批删方法，其他112已PASS不受该fixture调用影响；原116PASS证据保留，无关78不重跑。所有39IDs/所有117完整分母保持，不把局部5重验命名为重跑117，也不缩formal/catalog/full。新固定SHA/单keyword代码diff/15其余源码指纹/5ID映射收据单独封存。此返修仅静态准备，尚未运行DB；ROOT占用PR242验证器资源，需另派新SHA窗口，再交同R独立review。
