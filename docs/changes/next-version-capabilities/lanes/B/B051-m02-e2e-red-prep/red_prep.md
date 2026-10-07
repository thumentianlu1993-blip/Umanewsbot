# B051：固定两步M02端到端的真实RED准备

状态：`SOURCE_PREPARED_STATIC_ONLY_PENDING_ORIGINAL_R`。未业务import/collect/PG/Docker/native/CI、未调用provider或网络。
本候选有两个可供ROOT审后选入真实RED窗口的方法；“可选入”只表示源码及静态前置已准备，**不是运行时fixture已通过**。
E03有源码与完整目标，但真实registered完成态前置未实现，当前不得选入RED或计作第三业务FAIL。
ROOT经原R确认 `B051-E03-ORDER-RESOLVED-001`：先E01/E02正常fixture后两业务RED，再最小依赖实现，
用真实registered整链检E03；若随不可分割实现即满足，诚实记无独立RED，仍须GREEN。
原三个设计目标及十方法/35局部GREEN分母保留，不删除实现造失败、不降低断言。

## 1. 固定来源、隔离与实际修改

ROOT指定base `90f73d8093df00827a7ec78cc41dc3d3b91730c0`，B049依赖
`3dd653139759b48c41d8d43fdab927e0e3b20ddb` / tree `bb280a7833be160405e3be10e3c4ca4a38bb5a17`。
新独立branch `codex/b051-m02-e2e-red-prep`，不改主线或A050的catalog/worker文件。
纳入B049六路径**逐字节相同**：B048 red_prep、B049 implementation、models追加版本、0081、
managed_readonly_steps及固定23来源test。没有本切片新表/迁移，不修改/重编号0081或冻结旧测试。

执行合同仍为B050 `fd7b0772ceacbda855ee5a953a33bde4ae5178bf` / tree
`facdf31c7b95a32f8e6ce0854864565f16c1f047` 的plan/evidence_map/test_design三文档；
原R `e65d7247` verdict `APPROVED_PLAN_ONLY`，receipt SHA
`7f7eea38c8e6d057f849e3861745a8b05365f191a3a7fead60df988ba18f6a8e`，68输入。
B050原件/旧runtime及全部B049执行原件保留。审批唯一来源仍为根AGENTS，已有本地范围授权覆盖本卡。

本候选仅增加 `managed_readonly_translation.py`、`test_managed_readonly_translation.py`、本中文准备文档，
并窄改tasks.py/translation_recovery.py/translation.py。新service没有read→model→checkpoint→final消费者。
不得把纯前置源码称作M02实现、局部GREEN或生产启用。

## 2. 安全前置与仍缺的业务接口

- 登记codec：plan/progress/final v1精确字段/原生类型/canonical SHA、总16KiB/8层/1024节点限制、
  未知namespace/version拒绝；字段/状态与真实read/request ledger交叉核验。plan不可变，当前无mutable
  progress/CAS writer或final writer。registered的真实read提交后仍可保留registered进度，恢复consumer须后续从真实ledger推进。
- 安全登记：只允许真实claimed、新合成10分钟/tool1/request2账、匹配parent/read scope及closed SDK/reader；
  parent→read root→Article→Run→step→request ledger锁后核源、版本、epoch与actual clock，原子写控制键。
  不消费claim、不预留SDK/read、不建立model permit。已有相同plan只返回严格匹配值，不重置身份。
- task持久guard：旧prepare/provider之前识别namespace及消息job UUID；scope缺失/错scope/缺closed依赖/
  未知版本/损坏/歧义消息均拒绝。确认never-registered才能旧路由；原message run/stamp不换。
  合法registered入口当前正常返回 `registered_consumer_not_implemented`，read/SDK/claim改写均0，
  这是E01/E02要暴露的实际业务缺口，不是假成功或内部调用mock。
- 普通writer/admission保护：prepare/consume/request reservation/save/final/失败close/stale/dispatch release
  在原锁后查job标志，拒绝registered，防classifier→prepare竞态；provider构造与每次旧managed请求再次拒绝。
  B049所用 `_locked_translation_claim` 低层校验和history原AST不变，合法E02 reader仍能运行。
- metadata：所有现有raw_response metadata merge/assignment、checkpoint decode拒绝CLAIM/RESULT、
  新namespace任意后缀及程序provenance，不静默drop；普通任务的合法business字段继续原语义。
  private registered save/final及typed provenance可信解码接口尚未实现，public codec不能放宽为接受provider注入。

R02授权仍是**下一GREEN实施义务**：owner CAS+read grant+SDK slot同txn提交为每轮授权点，锁外SDK；
授权前撤权SDK0，授权后可能一次在途且结果不得披露/apply，每轮重新检查。当前普通请求不具此授权，
因此registered全部拒绝，未借用旧reservation冒充新permit。checkpoint/final同read root围栏txn也未实现。

`prepare_registered_read_phase`是E02必要真实前置：同一原scope/锁后校验，严格registered且无step/attempt/
checkpoint时只写claimed→executing/suppress_automation。随后fixture调用未改B049真实reader，制造合法
read-completed断点，不由fixture手填step/SHA/checkpoint或伪造授权。

## 3. 两个真实RED候选与E03边界

正常前置必须先成立：Django import/0080+0081 schema、官方PG16、无外层atomic、真实staff用户、
admin接受及OperationLog/due保存、真实selector取得唯一消息、安全登记codec与closed依赖。
前置异常使用fixture ERROR，不能计作目标RED；所有业务断言都基于真实ORM/task返回与ledger。
只mock外部OpenAI构造deny、broker/通知边界；不mockprovider.translate、授权、save/final、read/ledger成功。
原文长度大于256，后续成功断言要求完整正文与真实excerpt/UUID/SHA同时进入SDK消息。

| 方法/状态 | 实际构造与预期观察 |
|---|---|
| E01 `test_user_retry_reaches_read_step_and_final_article` / 首轮RED源码 | 真实NewsArticleAdmin.retry_failed_translations→OperationLog/due→selector/claim→安全登记→真实task.run。先校准缺scope/SDK入口拒绝且raw不变。合法scope下当前task正常返回组合未实施，实际摘录0；read=1断言应FAIL。保留最终Article/Run、请求/usage、全文/excerpt/provenance断言 |
| E02 `test_resume_after_read_commit_before_model_start` / 首轮RED源码 | 安全登记→真实private read prepare→原B049 exit_after_commit；真实completed step/SHA/read_at、counter1、SDK/attempt0、executing且无checkpoint都先核成立。fresh scope/依赖+同原message调用task，当前返回未实施；translated断言应FAIL。保留免费同step恢复/不重读/期限不续断言 |
| E03 `test_completed_job_redelivery_returns_same_final_receipt` / 前置阻塞，不选首轮 | 必须真实registered整链先产生Article/Run/final，随后fresh同消息断言相同receipt、0新增读/SDK/应用、时间/账不变。当前合法入口未实施，源码前置明确ERROR以防误排；没有手填终态或内部成功mock。GREEN依赖后再正常构造，不追求独立RED |

never-registered completed的旧skip/无新receipt是合法兼容行为，只由既有兼容回归校准；
本候选不拿它替代E03。两个task `.run` + capture只是离线consumer入口模拟，未证明真实broker ack/kill/redelivery。

## 4. 十方法与35完整后续映射

类namespace `stable.test_managed_readonly_translation.ManagedReadonlyTranslationEndToEndTests`。
本文件当前只有E01/E02/E03三个真实方法，无空stub/skip占其余七个；runtime将首轮实际source IDs与设计IDs分列。

| ID/设计方法 | 源码/后续fixture与受审子场景 |
|---|---|
| E01 `test_user_retry_reaches_read_step_and_final_article` | 已有首轮源码；补错scope/root/claim、unknown schema/namespace及registered-before-prepare；真实整链与来源引用 |
| E02 `test_resume_after_read_commit_before_model_start` | 已有首轮源码；fresh同原身份、缺依赖拒绝、真实读cache→新model owner，绝不续期限 |
| E03 `test_completed_job_redelivery_returns_same_final_receipt` | 已有源码，真实完成态前置阻塞；GREEN后检查当前scope/grant/source/version、未知codec/metadata防覆盖、同receipt免费重投 |
| E04 `test_two_quality_rounds_share_one_read_and_cumulative_request_budget` | 待创建；真实provider质量失败→usage journal→独立合成对账→第二轮新grant/slot，read1/request2/第三轮0 |
| E05 `test_tool_exhaustion_or_unknown_prevents_model_start` | 待创建；耗尽/inflight/timeout保留槽，0model，unknown不接管/退款/重读 |
| E06 `test_model_unavailable_retains_structured_evidence_and_explicit_gap` | 待创建；合法绑定依赖、真实读后closed SDK有限timeout，材料/partial/gap保留，不伪造译文；缺SDK入口0读 |
| E07 `test_model_started_or_usage_unknown_is_not_reissued` | 待创建；CAS+slot提交后SDK0退出亦不可接管，timeout/usage unknown/response未存拒绝重发 |
| E08 `test_version_source_grant_and_deadline_fence_each_resume_and_apply` | 待创建；真实独立连接授权前/后create前、save前、checkpoint后final前撤权/期限；epoch/source/类型/版本，锁后clock |
| E09 `test_two_redeliveries_have_one_model_owner_and_one_final_apply` | 待创建；两worker实际PG blockers，CAS+slot单owner、final单赢家、败者不关winner、网络无业务锁 |
| E10 `test_storage_failures_keep_commit_boundaries_and_free_checkpoint_resume` | 待创建；CAS/slot同rollback、checkpoint/progress/final原子失败，原账不退款；免费final、strict codec/metadata覆盖拒绝和普通helper绕过拒绝 |

完整局部GREEN仍是十方法 + 原B049精确23 + 两旧SDK方法 = 35 unique；原formal/full分母不减。
两个旧SDK ID是ManagedTranslationBudgetConsumerRedTests中的each_create_observes_committed_reservation与
quality_retry_cannot_create_again_with_unknown_usage。原23/两SDK及其它旧测试均字节保持。
当前新source3中仅2可安排RED，另外7方法未创建，故35是设计manifest，不能称已collect的测试清单。

## 5. ROOT运行前检设计与责任交接

runtime保存fixed commit/tree/source.tar及全部源码文件SHA/bytes/模式、依赖六路径、旧原件fingerprint、
两RED精确manifest、E03blocked说明、35设计manifest、官方plan template/resource request、八原controls SHA。
本轮无Docker endpoint探测/镜像检查、import/schema执行或collect；已知镜像ID只作ROOT待实时确认的固定输入。
没有新allocation/start/owner token、host启动脚本或旧run复用。

ROOT/R顺序：固定候选→同原R审源码/正常fixture/顺序→ROOT绑定一次窗口及完整host包→官方preimport gate→
实际import/schema/fixture→仅E01/E02→报告→cleanup与实际结果审。import/schema/fixture ERROR要先修同卡，
不得把无模块/缺表/guard异常当业务RED。E03不在first RED labels；正式计划为diagnostic targeted并绑定SHA/tree。
官方batch.log双marker必须来自同实际日志，marker/runner0/静态trace不等于业务完成。

环境沿原官方PG16 immutable image/八controls：network none、nonroot10001:10001、readonly root/source/control、
cap_drop ALL/no-new-privileges、1 container/2CPU/4GiB/256pids/3GiB tmpfs、max3 PG connections/2workers。
600总窗/570止测/30清理，ROOT父FD flock及owner/PID/heartbeat；finally container/process/FD reacquire核验。
源预检须核exact archive/full manifest/六依赖SHA、未偷改旧测试或controls；fixture无真实密钥、DB/Redis/外部服务。

(application) B交源码/静态证据及具体RED失败点，后续真实RED后才实现组合；
(integration) ROOT/R固定审/窗口/结果、ROOT/C负责既有formal/full；
(operations) ROOT建立新包/占窗/清理，B保留本次及所有旧原件并按实际结果写回。
回退仍遵B050：停新登记、保留registered guard/兼容候选与原账，不转legacy、不接管unknown、不重发/新claim/删账。
没有push/merge/部署/生产或新UI/通用agent，完整M02的真实计划、累计token/每日费用、生产enforce、
broker恢复/outbox/真实公开/模型质量等仍未完成。


## 6. B051-R01唯一P1返修

原R固定 `a7692e80f8c0d5dbd1fc2699ebf31b09ed476a00`，source前检receipt SHA
`55b21e0722ff9df5ecc0363edf10d03e2336353f92c420aa867280694b39711a`，4211输入，
结论 `REVISE_SOURCE_PRECHECK_NO_WINDOW`。其纯提取反例确认：无offline scope的公共translate_article
调用selector时漏传article/managed_run，导致guard目标None，实际合成边界观察到constructed/wire。

本返修仅改translation.py的公共API调用、原E01前置helper及本说明。所有scope分支现在都显式向
同一selector传实际article/managed_run，登记拒绝发生于provider构造之前；never-registered仍选旧provider。
新直接API负校准在无scope时分别传真实registered run及仅article，要求明确拒绝、constructor/SDK/read0、
plan和真实账不变；不新增test方法，不mock内部成功。负校准异常记fixture ERROR，不能算E01目标RED。

新runtime另存源码/完整diff/原件fingerprint以及纯stdlib AST提取负校准：只执行提取的实际API/selector/marker
函数并替换imports为明确供应的合成边界，不导入Django或业务、不构造真实provider。
注册run/仅article反例要求合成constructor/wire均0；never-registered显式run兼容校准仍构造/调用合成边界一次。
这仅验证实参/guard控制流，不能证明真实ORM、fixture、并发或任何业务测试已通过。
旧candidate `cec37ce2`及旧15artifact包/source.tar/seals原件保留，不重跑会写旧receipt的原verify/package脚本。
R报告中的4211输入除本返修三工作树文件外全部保持原fingerprint；旧三文件Git blob/source.tar仍保留。
R02的锁后admission/private authorizer/save/final义务与现有拒绝保护不变，未提前实现组合GREEN。
首轮exact2、E03 blocked/另七方法待创建、10/35设计、八原controls不混A050均不变。
本卡没有PG/Docker/collect/host启动/真实provider/CI/network，finding是否关闭仍交同原R窄复审。
