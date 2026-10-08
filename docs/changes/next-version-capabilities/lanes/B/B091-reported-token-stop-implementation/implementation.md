# B091：已报告 token 后续准入停止线实现

任务 `B091-REPORTED-TOKEN-STOP-IMPLEMENT-001`；2026-10-09 Asia/Shanghai。状态 **LOCAL_IMPLEMENTATION_PREPARED_PENDING_ORIGINAL_R_CODE_REVIEW / GREEN_NOT_EXECUTED**。

ROOT 已明确授权既有 M02 本地 G1 范围，固定实施合同 b318988257d8a4fc9903b68bcf31a69683df28df（原 R cde43245 批准）。旧方案文档的 G1_PENDING 历史状态由此次 ROOT 明确决策取代。起点源码 b02216c7305a6d1f17f9ed9baa9053dd49ed8888；本树为 codex/b089-reported-token-stop-red-prep，保留原 b089 独立工作树。

真实 RED 由 ROOT 确认已完成：B090 两目标各为实际第二 create 的 2!=1 FAIL、0ERROR，两个 limit4 正常控制完成真实翻译。原 R actual 审核 e4aa64b0f8f166147464d340aef7724e7fc29283，receipt `/Users/mentianlu/.codex/runtime/r-b090-actual-red-audit-001/review-receipt.json` SHA f118816245f2ccede9a6654c012d3f9005eddaf3df31a2f88de097fa323e105f。旧 wrapper 因枚举 repr 解析 exit2 原样保留；R 确认无需重跑 RED，ROOT 独立资源 FREE。本卡没有运行新 RED/GREEN，也没有修 execution wrapper。

## 业务链与具体改动

新离线操作精确 policy 为 `{mode:"offline_test", version:2, reported_token_stop_v1:{total_tokens_limit:N}}`；N 必须原生正整数且不超过 2^63-1。创建及每次准入验证完整 canonical UTF8 JSON 摘要；旧 `{mode:"offline_test",version:1}` 的旧摘要规则保留，夹带停止字段或未知版本/后缀拒绝。消息、模型 metadata、settings 均无覆盖阈值入口。

两入口继续调用原预算根锁内 `_admission`：先保留身份、retired、unknown/未对账、账序列/根身份、源/策略版本、root state、原期限围栏，再验证 v2 policy、全部逐请求合法 usage 及 synthetic 收据和有界总和。达到 N 返回 reported_token_stop_reached，不新增 slot/CAS/create，不改变原 usage，不退槽、不续期。低于 N 仍受原 request_limit；首轮及在途响应可以超过 N，停止线只阻止后续准入，不能作为硬 token 或真实费用上限。

普通 provider 质量失败按原逻辑先计失败恰1，再保存 failed Run 和已有 CLAIM_KEY.budget_blocked_reason、清 due。仅本次实际达到新停止线时返回已保存原因；原其它失败返回合同保持。首次停止诊断 OperationLog 与收口同事务。原消息重投在普通 prepare 前仅检查原预算→Article→确切 Run 及 attempts，要求实际 failed+持久停止字段、无 due/新 run/checkpoint、有效原 scope/来源/版本/claim UUID/期限及完整对账，总量达到阈值才返回相同诊断；缺证据回原拒绝，诊断不改账、claim、due 或失败次数。日志错误会传播，不伪报已存成功。

登记 owner 首次停止仅追加有限 OperationLog，核当前原 owner/binding/index；不把新原因写入 v1 progress/codec。fresh 同 job 的 model_started 仍返回 model_start_unknown，现有 blocked_unknown/blocked_fence 和身份/权限/期限围栏保持。免费 checkpoint apply 原路径不经过新增请求准入，不额外 charge/read/create。

日志只含 reason、operation/root/run/claim 标识、reported_total/limit，无正文或凭据。TaskExecutionLog 仍由原 task 真实返回路径保存。改动限定 core、三处窄消费者适配、新测试模块及本说明；没有 migration/模型/后台/SDK权限/fixed steps 修改。

## 六方法与待真实验证范围

`stable.test_translation_reported_token_stop.ReportedTokenStopTests` 保持前两条实际 RED 方法目标断言，完善为六方法：

| 方法 | 覆盖 |
| --- | --- |
| test_registered_quality_retry_stops_when_reported_total_reaches_limit | limit4 控制及 limit3 目标；fresh unknown、真实 reserved/usage/timeout/quality blocked 状态，权限/期限/身份负例，控制字段与账不变 |
| test_ordinary_quality_retry_stop_and_failed_closure_repeat | limit4/limit3 两轮入口、真实 max1 failed 收口及计数/due/双日志、selector0、原消息只读重投；无终态/字段、损坏/unknown/未对账/冲突/版本/期限拒绝；低于阈值普通质量失败控制 |
| test_policy_validation_and_existing_contract_compatibility | 精确 v2/N/digest 拒绝、消息身份改变、持久策略损坏、production 拒绝；v1 固定旧摘要、真实 ordinary/force/unbound/legacy checkpoint；原控制 metadata 拒绝 |
| test_unknown_unreconciled_and_invalid_ledger_never_become_zero | reserved/unknown/invalid/未对账、report/receipt/根身份/序列损坏、单条与累计溢出；迟到收据/重复报告不重复 charge、已有 blocked 原因 |
| test_concurrent_admission_and_deadline_keep_original_fences | 原 root 锁真实 PG 阻塞图，两 worker 达阈值不预留、低阈值未结 reservation 排他、等待跨期限拒绝；真实 owner 在 wire gate 已对账达到 N 时 fresh 仍 unknown，不夺 owner；无网络事务锁 |
| test_committed_checkpoint_resumes_without_token_recharge | 真实 checkpoint 后 final 事务异常，真实 usage 对账达到停止线后免费 apply/重复收据；撤权/期限拒绝，无额外 read/slot/create |

这些为源码 AST 拟定 exact6，未 collect 或执行。fixture 只替换 closed SDK/broker/故障注入边界，真实 ORM、admission/reserve/usage writer/claim/checkpoint/Article 保存保留；损坏负例使用现有负 fixture 注入，不手造成功终态或补 due/claim。最多2 worker+主 PG 连接，gate 有界释放、线程 finally 关连接，外部 SDK 构造 deny 保持。

## 交付、验证和范围

固定提交及必要证据保存在 `/Users/mentianlu/.codex/runtime/b091-reported-token-stop-implementation-001`。AST 语法/compile、diff check、原35所在六源文件字节、原 SDK/模型/fixture/steps 字节、codec/owner/reserve/final 等关键 AST 保持验证。仅对新纯 policy/total helper 做隔离 AST 校准；没有 import Django/应用、native collect、测试、Docker/PG/FD 或网络 SDK 动作。

候选 manifest 包含 exact6、原35原 ID 与字节，以及全部本次直接引用消费者的预算/claim/checkpoint/重试/metadata 与翻译兼容模块；是待 ROOT/C 锁定执行批次的输入，不是实际收集分母，不替代 formal/full 义务。ROOT 转原 R 代码审后另给固定执行包与 fresh 窗口。未来 GREEN 采集应在下一包精确修旧 literal_eval 枚举缺陷，并用现存原日志离线校准；不得改业务断言以迎合 formatter。

未合并/部署/迁移/启用/生产验收，M02/M03 整体仍未完成；原35、必要预算影响及完整质量义务保留，原逾期与10/23候选观察窗口不变。
