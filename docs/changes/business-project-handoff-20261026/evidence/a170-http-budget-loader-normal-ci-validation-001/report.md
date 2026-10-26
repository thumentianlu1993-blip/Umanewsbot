# A170 test loader 修复新SHA首次正常CI结果

结论：**HTTP-budget原3方法本attempt全部fresh PASS，A164唯一import ERROR依本次完整执行闭环；新22及旧相关回归全PASS。正式CI仍因本run实际expired-skip verifier失败，不是full GREEN或交付。** 待同原R_A实际结果审。

## 固定对象与一次自然运行

PR266普通nonforce push恰一次（原pre-push hooks保留），未rerun旧SHA。HEAD `12d54be46de8b8bf20490e3a738f141e187b402d` / TREE `4a057f7ba1c0b7147e880d41f5f9ebef4060eac0` / base `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`，唯一自然run [40090667403](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/40090667403) / attempt1，pull_request，completed/failure。官方TEST `889eab8d8c2e6f57c3c48f8940e85112aa2b2831` 双父依次base、HEAD，tree与固定HEAD相同。

原RA169 report/index已核为 `8965b584ed50ecdbeebdc9bc8a393712737c8b041a8fa38521a1781ecec984a1` / `095491c8f10e7ae7877b8ded219de68af5248dc46b68971e7cc8d8a28fde64ff`，成员核验并留副本。原结论保留原方法11PASS/外层1supported3unsupported，不是暖态全通过。

相对A164 head38070421唯一源码差异是HTTP-budget测试loader单点上下文；原3方法体、descriptor ledger oracle、业务runner/provider、direct loader、compat模块、22测试/catalog/rules/skip预算无改。HTTP源SHA `a977473cc51bc269d9700bf3bca8fae7981138c154d7bd49d4d7ea2fe5268cc2`，service SHA `74413ae84aff62378a0df5c8a9e836716500963b05dd33c307ef95f2434b304c`，22源SHA `5b42e41597e0e1f6aeb30a585702f9b6243aabbd5fac14cbc661358de33353aa`。执行前后HEAD/clean及5份冻结源hash核验。

当前plan digest `b3edfa84636aa5221deb0a9c2713f9a5485f5ae378177bd2ea1fd7db897c1125`，20 control blobs和两份canonical JSON hash匹配，mode full、332 labels/266 domains/321 aliases。pre-push该head run数0，终态同head唯一run/attempt1；无dispatch、rerun、merge/deploy。

## HTTP3闭环与真实完整分母

| 原方法 | 本次实际状态 | 原raw RUN |
| --- | --- | --- |
| `test_host_budget_is_per_descriptor_while_shared_state_still_limits_and_audits` | PASS | batch-009:104 |
| `test_redirect_reserves_the_shared_budget_before_controlled_transport` | PASS | batch-009:105 |
| `test_runner_host_budget_uses_only_the_descriptor_ledger` | PASS | batch-009:106 |

batch-009实际171方法complete/exit0，raw178–180 `Ran171 ... OK(skipped=4)`，三方法planned3/executed3/PASS3，无SKIP/ERROR。原A164出错 `test_runner_host_budget_uses_only_the_descriptor_ledger` 本次已实际越过加载并完成原ledger允许/拒绝断言；不是只用本地harness支持或借前run PASS。A164 run40085694607/1 原ModuleNotFoundError记录不覆盖，闭环对照见http3-import-error-closure-proof.json。

**6948唯一方法 = 6938 PASS + 10 SKIP + 0 FAIL/ERROR**；49批全部complete/exit0。Django6147/44批、Python752/4批、release-postgres49/1批。A164的6948身份全部保留，无增删；所有raw RUN逐位/逐字匹配executed，无literal渲染例外、无raw gap。

新22（回归）planned/executed/PASS22，0 NOT_READY/FAIL/ERROR/SKIP；旧prepare16/private11/basic20/whole25及legacy career10均fresh PASS。方法ID/batch/raw行和实际条目完整保留all-method-statuses.json及official-evidence-inspection.json，不沿用历史PASS。

旧10执行skip的ID/理由及allowed_skips与A164逐项相同；collection另9skip相同，不能叠入执行分母。未改时间、分母、策略、skip或预算绕门禁。

## 新22的四个PG场景本次回归原证据

| 场景 | holder PID | observer PID | worker PID | 正图/方法/连接收取检查 |
| --- | --- | --- | --- | --- |
| concurrent | 193 | 194 | 196,198 | True |
| actor_expiry | 160 | 161 | 163 | True |
| profile_expiry | 181 | 182 | 184 | True |
| revoked | 165 | 166 | 168 | True |

均实际DB test_bounded_ci/user bounded_ci、各连接PID互异，独立autocommit observer的activeLock+pg_blocking_pids到holder正阻塞图。并发一创建一回放且同IDs；actor/profile跨TTL和撤权均实际拒绝并零净写，controlled clock只在正样本后推进、撤权COMMIT后释放。四条原JSON完整行及逐项proof保留，方法实际完整PASS。

COMPLETE只说明这些显式future/连接已收取；不冒独立OS/容器整体cleanup。source_permission仍not_evaluated、public_consumer_authorized=false，合成PG机制回归不授权真实来源/公开消费。

## 本run正式verifier实际失败

tests job120862489090 / test-plan-gate job120868204589 均failure。static-contracts、generate-plan、execute-isolated-plan实际SUCCESS；**verify-execution实际FAILURE**，与A164执行失败后跳过verifier的stage不同。

本次官方原日志 `official-run-logs/tests/7_verify-execution.txt:12–22`，2026-10-24T12:06:58Z traceback：verify_test_plan.py:17 → tools/test_impact/core.py:176 → `raise ValueError('unexpected/expired skip')` → exit1。该trace未打印任何具体skip ID，first skip ID=NOT_PRINTED，不猜测哪一个是首先触发者。正式summary.json未生成。这里引用本run新trace，不借A160/旧SHA结果。

collect-catalog-without-running=SKIPPED，upload-test-image=SKIPPED，upload-evidence成功；gate require-complete-plan实际失败。独立collect/external CID仍NOT_ESTABLISHED，native本run完整计划/6948执行记录不等于独立collector或外部CID证据。plan image_id只作元数据，整体cleanup UNKNOWN。

## 官方获取、保留失败与停止点

官方artifact12559671811 `impact-40090667403-1` evidence566247B，SHA `9441e02f521786ab4e4f11ab7b68cc8c0bd2c8d3d7e34f3afacea09bdd236747`，官方size/digest匹配，102成员与提取原件逐字相同。attempt1 logs33401B，SHA `22fc781ac14bc5cbd55ba22a1b1880ee94049d5d7c3b6cba1c85b1cfc28df78c`，17成员匹配。两archive各必要单次获取，无image/依赖/额外artifact下载。

采集ledger39个单次成功请求，含33个有界jobs观察快照；最后jobs对象直接复用终态快照，没有重复最终jobs请求。必要TEST对象另一次单次API读取。observer退出0；短时push OS flock随进程退出释放。不新增本地harness循环/工具测试、真实DB/Redis/第三方/生产操作、安装/镜像或网络抓取；仅一次授权自然CI及官方取证/标准库raw分析。

A167/A169原sealed indexes已核未变。A169真实TOOLS残留、暖态旧loader NOT_REACHED、两邻域整体恢复后件失败继续保留；本次HTTP3 CI闭环不改写这些局部结果或证明A160历史cache。没有扩修direct loader/兼容模块或撤断言。

preimplementation业务RED仍NOT_RUN；native方法执行结果支持本测试loader修复闭环，但full_GREEN=false、来源权威未建、H03/A137-B226/交付未提升。无merge/deploy授权。最终固定包ROOT→同原RA审查，本卡停止，不机械rerun或修expired skip。
