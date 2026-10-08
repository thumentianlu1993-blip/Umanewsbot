# B089：累计已报告token停止线真实RED源码准备

任务 `B089-REPORTED-TOKEN-STOP-RED-PREP-001`；2026-10-09 Asia/Shanghai。状态 **RED_SOURCE_PREPARED_NOT_COLLECTED_NOT_EXECUTED**。ROOT已锁B088修订b318988257d8a4fc9903b68bcf31a69683df28df及原R cde4324579004056e0b1e41d63a2e52ba3675ff4 APPROVED_PLAN_ONLY（receipt SHA31fdfc5afe67a488a202e6ce78161c1dc775b001406cea5d5aefc939510d731c）。ROOT依据原M02 token/请求/退出/重投合同及持续本地开发授权确认既有G1覆盖offline增量；本卡仅解锁RED准备，不解锁功能实现、实际执行、合并/生产/付费/抓取。

## 固定基线与改动

独立分支 `codex/b089-reported-token-stop-red-prep`，worktree `/Users/mentianlu/.codex/worktrees/b089-reported-token-stop-red-prep/umanews`。精确起点main/merge `582846d4b525378e8b44d03674be1d47b71e7a65`，parents90f73d8093df00827a7ec78cc41dc3d3b91730c0 +1b3d0fab49c112fc6e3c86eab7cdf6e11cde79b2，tree e1aca24ea9b27d62c78c2faeff973e2c0b1f00e6。本地原缺该merge对象，ROOT从同origin补齐对象后本卡仅本地核对/建树，没有fetch或导造merge。

只新增 `server/stable/test_translation_reported_token_stop.py` 与本说明。共享产品services/models/tasks、原fixture、原35和所有旧docs/封存未改；正常fixture可使用现有JSON policy列，无DDL、无新接口骨架或功能实现。原B088文档不复制到main树覆盖，批准提交/报告/receipt从本轮runtime追溯。

## 两条真实入口、控制与预期业务FAIL

正常源码类 `stable.test_translation_reported_token_stop.ReportedTokenStopTests`，固定两条拟ID：

1. `test_registered_quality_retry_stops_when_reported_total_reaches_limit`
2. `test_ordinary_quality_retry_stop_and_failed_closure_repeat`

第一条真实后台重试→OperationLog/due→selector/claim→安全登记固定两步→真实source_excerpt→真实provider/usage→checkpoint/Article；第二条同样真实后台/selector/claim→普通offline受管task/provider。第二条名称沿已审六方法表；**本卡仅写其同claim第二create RED及控制，不提前实现未来早停收口/重复诊断GREEN子场景**，不宣称跨claim。

每方法先运行独立来源/操作的limit4正常控制，再运行limit3目标。request_limit2、原期限10分钟、质量max_attempts2。第1轮内容body为空触发现有真实质量修复，usage prompt2/completion1/total3；第2轮为真实可用完整译文。所有响应来自原 `_ClosedOfflineSDKClient` 有限纯数据script，OpenAI构造保留原BaseException deny。只替换外部admin dispatch/broker，不mock admission/reserve/usage/read/解析/checkpoint/final成功。

第1轮沿原closed SDK `wait_for_receipt` choices gate暂停：主连接观察真实usage_reported提交、独立worker网络阶段无业务事务/锁，调用原 `core.record_usage` 和原synthetic receipt完成真实合成对账，再释放choices。这是测试态对账，不是真实费用证据；不由SDK脚本偷偷改账或返回permit。复用原RemainingReadonlyE2EFixture的有界worker/连接finally；每次仅1worker+主连接，未另造资源监督器/执行协议。

limit4控制必须到真实第二create，两个create看见已提交slot1/2，译文、Article TRANSLATED、Run SUCCESS及checkpoint真实保存；控制不通是前置ERROR，不能当RED。累计可到6>4仍完整留usage，符合首轮/在途可能超阈值且不截断的有限停止线合同。

limit3目标在未实现停止线的固定源码预期仍发生第二create并成功终态；**第一条目标断言就是create_count=1**，实际2即业务FAIL。后续GREEN断言再核slot1/真实停止原因、usage原值/收据、原policy摘要/期限、未伪造译文、TaskExecutionLog及有限OperationLog诊断；登记读step真实completed且仅读1。未运行，不冒称这些条件现已失败或通过。

已审version2 policy为exact `{mode:"offline_test",version:2,reported_token_stop_v1:{total_tokens_limit:N}}`，摘要为完整canonical UTF8 JSON SHA256（ensure_ascii=False/sort_keys/紧凑分隔符/allow_nan=False）。现有core只检查mode，正常创建该policy无需新功能；identity.policy_sha绑定实际摘要。不得后写普通ORM修改不可变根或强填claim/usage终态。

## 静态校验、runner读取方式与短窗估计

仅对源码 `ast.parse` 语法与声明ID读取，未import应用/SDK、未collect/执行。类只继承无test_*方法的两原fixture/mixin，不继承原10方法测试类，避免新增类意外带入旧方法形成隐性分母。runtime保存AST提取的两个拟ID，不称已collection。

ROOT沿既有官方runner把**新固定候选完整source tree**作为只读输入，原controls/镜像/入口保持；使用runtime `red-labels.txt` 中两个完整Django方法label选测，模块从候选 `server/stable/test_translation_reported_token_stop.py` 正常读取。文件依赖已有真实fixtures/services/model/migrations，不能只拷新test而漏掉已审1b3d/main依赖。新版本控制/stop实现尚无；本卡不改catalog/impact/full分母，ROOT未来可固定必要manifest。

短窗估计：正常两个方法共4独立场景，4次worker、最多8合成create，gate wait8s/join12s复用原有上限；测试体预计30–90s，含PG/schema启动及正常报告估计≤180s，均为未校准估计。ROOT仍按原600总窗/570止测/30清理和原资源上限排窗口，不为估计另起协议/容器/FD分配。只有ROOT实际运行后，两个真实业务FAIL、控制正常、fixture ERROR=0及实际报告/清理可称RED；若前置ERROR先如实定位，不能先写功能补成假RED。

## 后续与验收边界

(application) B：固定本RED源码候选/来源/manifest交ROOT；不改共享产品文件。
(integration) ROOT/R：原runner实际RED并独立实际结果审；ROOT据真实FAIL才另卡解锁实现。
(application) 后续B：在已锁B088合同内实现，完善原6 GREEN子场景；fresh登记model_started仍unknown，普通真实失败收口清due、失败+1与原消息重复诊断不补due。旧v1摘要/入口兼容保持。
(integration) ROOT/C/R：固定6 GREEN、原35及必要budget影响回归不减，代码/实际结果审；本局部不关闭完整M02/M03。

本卡collect/PG/Docker/FD/SDK/网络/费用=0；SDK脚本只是待执行源码，没有运行。原10/07与10/08整体逾期保留，不借RED准备称节点完成，不消耗10/23候选/观察窗。可靠input/output硬预留、每日金额/可信unknown对账、跨进程/Celery恢复、outbox、M03工具面仍为后续义务；本卡不建立新监督平台或修改这些边界。
