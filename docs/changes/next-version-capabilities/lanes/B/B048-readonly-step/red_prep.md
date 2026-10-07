# B048-READONLY-STEP-RED-PREP-001

状态：schema + 私有闭合 RED interface + 测试静态准备。未 import/collect/执行业务测试，未启动 PG/Docker，未获得实际 RED/GREEN，未 push/merge/release。ROOT 独占 PG 队列；本文及 runtime resource-request 只提出窗口申请。

## 来源和范围

固定基线 `90f73d8093df00827a7ec78cc41dc3d3b91730c0` / tree `3e02fd2150bcc5c77b7d4e734bc8012089ff35e9`。B047 批准方案 `02a47d0c7470c8aeb5c4bc75b1df550dae0cfeaf`，原 R review `c6da99b690170f9d0f86a35afe91740653f8a14e` 为 APPROVED_PLAN_ONLY、零 findings；不将方案批准写成实现批准。

ROOT 已批准本卡 schema/interface RED 前置并保留 migration 0081（依赖 0080）。只 append models 的专用 manager 和两张独立账表，新增 migration/service/test 与本卡文档；translation、recovery、retry-budget core、tasks、settings、catalog、旧测试及 8 个执行控制不修改。服务仅由显式 offline fixture 进入，无生产/task/provider 接线。

## 已准备的合同

只读预算一对一 PROTECT 原 TranslationRetryBudget，独立 tool_read_limit / tool_reads_reserved；没有 Article/Run 外键级联，删除文章不删除读账。独立 step 的 logical key 固定 source_excerpt:1，唯一 `(read_budget, logical_step_name)`，step UUID / reservation token 唯一，completed 必须有时间、非空 JSON 和 64 位 SHA。专用普通 ORM writer 禁止修改与删除；有限私有状态写入只可走明确的 base QuerySet 边界，不声称 DB 超级用户无法篡改。

只接受 `source_excerpt_v1` 的 exact dict `{body_chars: 256}` 或 512。真实 executing envelope 经原 Article/Run fence 重新验证，不重复 prepare、不伪造 TranslationResult checkpoint。parent/read root/Article/Run 授权检查使用短事务；实际有限摘录 SELECT 在事务之外。实际 SELECT 同一行返回源身份、语言、标题和正文材料，再按现有 source digest 算法校验，不能把另一次查询的 hash 标给旧摘录。摘录标题上限 256、正文 256/512、结果 JSON ≤8KiB；用于同源 digest 的材料最多 65536 字符，超长源明确拒绝。

scope 绑定 parent nonce、PID/thread、版本和不可逆 grant epoch。复用现有完整 preflight（mode→outer atomic→identity/clock）；finite fault reader 仍执行实际 ORM，无 arbitrary callable、URL/SQL 参数或模型工厂。撤权后的结果返回须再经 fence。结构化读不受模型不可用或现存 request pending 槽阻塞，且不增加 SDK request/attempt。

## 明确的 RED 缺口

当前 execute_step 直接进行真实有限读取，尚未预留独立 tool slot、插入/提交 step、保存 completed 结果、检查已存幂等身份或重放缓存。因此预算耗尽时仍读、观察点 reserved=0/inflight=0、并发重投重复读，以及缺少持久 step 是预期业务失败。前置 mode/scope/fence/grant 不是这些 RED 缺口。

`exit_after_reservation` / `exit_after_commit` 是固定故障边界名称；当前 RED 没有对应真实提交。测试应先因“无计数/无 step” FAIL，不能把这一版称为已证明 reserve 后崩溃或 result-save 后恢复。真实 crash/unknown/缓存证据须待 GREEN 实现并在 ROOT 窗口完成。

## 测试封存和验证边界

`server/stable/test_managed_readonly_steps.py` SHA256：`6a7616377a42171cdb975ab12ce3cd0cc17d58a6b2d058eb33fb3f32c4246500`。RED→GREEN 必须保留此文件字节；若发现 fixture/import/migration 技术错误，应独立说明与重新封存，不记作目标业务 RED。

16 个 service 方法名与批准 test_design 完全对应，另加 3 个独立 schema 方法：唯一/计数/completed 约束、普通 writer 禁止修改、0081 真逆/正迁移保留原文章和原 request root。加 4 个旧精确方法，共 23 个 ID，完整 manifest 位于外部 runtime。

静态预测：14 个新 service 业务 FAIL，2 个 scope/结构化读 PASS，3 个 schema PASS，4 个旧回归 PASS，即 14 FAIL / 9 PASS。**此为预测，不是运行结果。** 多个方法在“无 step”处先失败，其后的版本漂移、源身份、缓存撤权、digest 污染和生命周期断言尚不可到达；即使实际首轮 RED 符合预测，也不证明这些深层断言通过。16 个方法实现本阶段具体输入与故障，不声称已穷举方案提到的所有 schema/非 finite/环境变量组合。

新增 `test_existing_request_checkpoint_and_unbound_paths_unchanged` 检查 readonly blocked 时 Article/Run/request 账不变；checkpoint、普通/force/legacy 原路径由四个原方法覆盖：

- stable.test_translation_retry_budget.TranslationBudgetBoundaryTests.test_repeat_claim_index_and_pending_new_claim_never_refund
- stable.test_translation_result_checkpoint.TranslationResultCheckpointRedTests.test_same_envelope_resumes_committed_result_without_provider
- stable.test_translation_claim_fence.TranslationClaimFenceBoundaryTests.test_wrong_run_and_invalid_identity_do_not_consume_current_claim
- stable.test_managed_translation_budget_consumer.ManagedTranslationBudgetConsumerBoundaryTests.test_unbound_ordinary_force_and_legacy_checkpoint_are_compatible

真实并发最多主连接+2 worker=3 PG，复用已存在的实际 blocking graph helper；独立读前观察点记录提交计数/inflight、worker xact_start/tuple locks，释放后实际 SELECT 完成再断言计数。所有 worker finally 关闭连接。测试继承关闭 automation/email、收件人为空、OpenAI constructor 拒绝的原 fixture；schema 类单独关闭 automation/email。PG 缺失、表缺失、collect/import ERROR、SDK 防线触发不算业务 RED。

## 静态证据与窗口申请

外部目录：`/Users/mentianlu/.codex/runtime/b048-readonly-step-red-prep-001/`。static-check.py 只使用 AST、文件字节和 Git，不 import Django 或业务模块。已确认 models 原 bytes 前缀/AST 不变、两模型与 migration 字段/Meta AST 完全一致、16 方法对应、19+4 精确 ID、原业务与控制 bytes 不变；0081 实际迁移是否成功仍未验证。

窗口建议 `B048-EXACT23-READONLY-STEP-RED-WINDOW-001` / batch `b048-readonly-step-red-23`，固定 candidate SHA/tree 后才可执行；ROOT 可另分核心子集，不能将未跑 ID 写成已跑。单容器、network none、只读 source/controls/rootfs、非 root、2CPU/4GiB/256pids/3GiB tmpfs、max3 PG/max2 worker、600秒总窗口（570秒停止测试、30秒清理）；固定原 image ID 和 8 个 controls，原 runner 不改，无 host fallback、无另行 collect、无新 settings 文件。当前 Docker/image 可用性未检查；具体资源与锁由 ROOT 后续分配。

收到精确窗口后才运行；实际核心 RED 接受后再做唯一 guard/commit/replay GREEN，仍保持测试 SHA，最后按 ROOT 安排原 R 复审。暂停 checkpoint 原文件保持原样，本卡沿原任务续做，没有重建方案或新开任务。

## R01 技术 fixture 修订（冻结例外）

原 R 静态预检确认 cab38b20 的嵌入指令用例先创建 520 字符标题，超过原 NewsArticle.title_ja max_length=500，可能先 DataError，不能计作业务 RED。ROOT 指定 B048-R01-FIXTURE-FIX-001 最小修订：仅将 `"Source title " * 40` 改为 `* 30`，标题 390 字符仍大于输出上限 256 且小于等于原字段上限 500；业务断言、model 限制和其他测试字节均不改，不吞 ERROR、不放宽 schema。

原 cab38b20 与 `/Users/mentianlu/.codex/runtime/b048-readonly-step-red-prep-001/` 保持不变，原 23 ID 申请不可执行。修订后的 manifest/plan/resource/seals 独立写入 `/Users/mentianlu/.codex/runtime/b048-r01-fixture-fix-001/`，等待 ROOT 安排原 R 窄复审及后续窗口。上文 14 FAIL/9 PASS 是未运行的静态预测，原候选已发现前置错误，更不能作为实际 RED/GREEN 证据；新候选同样未 import/collect/执行测试，未启动 PG/Docker、未 GREEN。
