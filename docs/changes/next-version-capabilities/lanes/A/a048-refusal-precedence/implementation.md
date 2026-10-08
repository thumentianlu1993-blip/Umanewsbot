# A048：既定拒绝顺序与无副作用断言修订

基础候选 `66d39b9983dd625e6734a01dcef87e7defde1506`。ROOT 的 A047 单次实际窗口运行原 19 个唯一 ID，两批、lifecycle complete，18 PASS / 1 FAILED_METHOD / 3 failure subcases / 0 ERROR / 0 SKIP，NOT GREEN。A047 审计序列化的九个 ERROR 已消除，但这不等于完整验收。唯一失败方法为 `test_nonstarter_ignore_and_dry_run_do_not_consume`，其三个失败子例为 WV+started、UNKNOWN、race_date=2025。原 report `/Users/mentianlu/.codex/runtime/a047-root-green-window-prep-001/output/report.json`，SHA `91649d3c35f5a4e4c59e086d7b2b61f7e26a071eae48ddb9e9ca935993812794`；parent2/child1/report1 不改。

原 ROOT 清理核验 `/Users/mentianlu/.codex/runtime/a047-root-execution-audit-001/cleanup-verification.json` 保留 exact 容器 absent、running 空、PIDs83490/83500/83514 gone、FD 重获、2061 sealed 不变、PG stop0/status3。原 R `55bacef1daf35ed800a55a01f264beb8f54bbec6` 对实际结果核定的 receipt SHA 为 `80d84f74f46e575e97069fb124ae2597374a1f8ca67f3886f7253f90c105274b`。旧 source、测试、allocation/start、report、owner、清理证据完整保留；本次不重跑旧窗。

## 既定合同与不可达的较后拒绝

依据 A044 `docs/changes/next-version-capabilities/lanes/A/a044-career-review-consumer/plan.md` 的输入及执行顺序：复用原 prepare、真实 HKJC cache adapter、H02 planner、Hong Kong normalizer，不放宽原约束，然后才进入单行投影及消费事务。A045 `docs/changes/next-version-capabilities/lanes/A/a045-career-consumer-red-prep/preparation.md` 明确保留完整 source validator。A044 `test_cases.md` 的 nonstarter 方法要求 WV、显式 started+WV、unknown finish/非 exact 拒绝、starts 不增加，ignore/dry-run 零消费；没有规定这些输入统一返回 `record_not_started_exact`。单行消费不把 profile 全生涯提升为完整，不能据此绕过已经存在的 cache 输入校验。

实际顺序是 `prepare_reviewed_career_record` 调用 `_prepare`，后者运行 canonical normalizer；`validate_p0_horse_completion_payload` 对 coverage 中不完整组写入 failure_reason；`_prepare` 发现非空 failure_reason，立即以 `cache_validation` 拒绝。单行 started/exact 的 `record_not_started_exact` 检查在此之后，`consume_reviewed_career_record` 的 `_apply`/事务/锁/writer 亦在完整 prepare 返回之后。此顺序已在原 shared guard 中存在，不是本次新产品口径。

| 原输入，全部保留 | 既定 normalization/coverage 合同 | 正确期望的最先拒绝 |
| --- | --- | --- |
| finish=WV，source_start_count=0 | 原始 finish 推得 did_not_start，实际 starts=0 与来源数相符；其余原 cache evidence 可通过。随后单行不满足 actual started。 | record_not_started_exact |
| finish=WV + 显式 start_status=started，source_start_count=0 | 原 normalizer 保留合法显式 started，汇总 actual starts=1，与来源数0不符；source_start_count_mismatch/source_start_count_exceeded:1 令 career_history partial，coverage 不完整。 | cache_validation |
| finish=UNKNOWN，source_start_count=1 | start_status=unconfirmed，actual starts=0，来源数1；source_start_count_mismatch/source_start_count_missing:1、unconfirmed_start_status 令 coverage 不完整。 | cache_validation |
| race_date=2025，source_start_count=1 | 原日期规范化为 year precision；core evidence 检查要求 exact，race_record_core_evidence_missing 令 coverage 不完整。 | cache_validation |

三个真实栈均已证明在 shared `_prepare` 的 failure_reason 分支拒绝，较后单行错误不可达。以上具体 blocker 名依据原 normalizer 代码追踪，原 report 没有输出内部 failure_reason/blocker 的运行值；不将静态追踪当成额外运行观测。没有改 shared guard、normalizer 或产品错误码，没有添加允许任意错误码通过的断言。

## 实际副作用覆盖边界及最小修订

原 `blocked` helper 先检查拒绝错误码，最后才执行 `state()==before`。三个子例在错误码断言失败，因此末尾全 DB 状态断言未执行。已观察 fail-closed 拒绝，尚不能声称其零写已经由数据库 readback 验证。流程显示它们在消费事务之前失败，这是代码路径证据，不替代实际 state 验证。

本次仅改自有测试中的上述方法及本说明：四种 changes、source_start_count 计算、全部 input/SHA 重建及 19 方法 ID/两批不变；为四组输入分别指定既定最先拒绝，plain WV 保留原后置错误。错误码仍由原 `blocked` helper 明确断言，不吞异常、不降低为“任意拒绝”。在四个子例局部捕获完整 before state，并在 `finally` 独立执行完整 state 相等检查，即使错误码断言再次失败，也要检查 DB 副作用。原 helper、其他方法、ignore/dry-run 真 writer/审计及回滚断言字节不变；不以减少输入、分母或取消 state 断言制造 GREEN。

## 本次验证与后续

仅做源码/原 report/设计证据读取、AST 和差异静态核验、输入集合与断言结构检查。未导入业务模块、未运行 Docker/PG/native/collect 或候选测试；新增 finally 在实际数据库中的运行及三组输入零副作用仍待 ROOT 新窗口验证。未新增测试 ID、代理、授权或窗口，未改原执行包及结果；所有 production service、command、shared prepare/cache/normalizer/writer/模型保持原字节。

固定新候选、差异与独立 runtime 证据先交 ROOT→原 R 技术审查。审查通过后 ROOT 再准备绑定新 SHA 的包并分配窗口，原19/四输入/三失败原件不减，核实际拒绝与 state、完整报告及清理证明。18 PASS 仅指该次方法结果，不替代完整验收；当前仍 NOT GREEN。
