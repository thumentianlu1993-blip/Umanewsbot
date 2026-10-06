# B038：同一领取内已验证翻译结果检查点与恢复方案

任务 B038-M02-NEXT-BOUNDED-SLICE-PLAN-001。状态：**仅方案，待原 R 审核；未实施、未运行测试或数据库**。推荐下一片为“同一 claim 内已验证 TranslationResult 持久化，并由原消息重投恢复终态”。它缩小 provider 返回后、article/run 终态事务前的结果丢失窗口，复用 B037 fence，不引入通用执行框架。

## 基线、授权与交付边界

ROOT 已反馈原 R `2e1868bf6bb90abac00530908d909cc22914dd60` 关闭 B037-R01、APPROVED_LOCAL_SLICE，并将固定 B037 `a8b182bd51ad9d2358f8c0164e2f53f06c2f63bc` 交 C033 集成。本轮只读源码核对绑定该固定提交，不把该协调反馈当主线/生产证据。B038 新树 `/Users/mentianlu/.codex/worktrees/b038-m02-next-slice/umanews`，分支 `codex/b038-m02-next-slice` 从 a8b182bd 创建；B037 候选及 C033 不改。

当前目标是选最小下一片并给出可审核的执行流、RED 和风险；只增加本方案与仓库外 runtime 静态证据。已核 AGENTS.md、session_bootstrap、完整 M02 任务卡及 B036/B037 输入，current_state/decisions/future_work_roadmap 的精确 M02/claim-fence/B037 查询无直接命中，不能由旧项目状态推定当前交付。门禁只引用根 AGENTS.md；本轮只读方案不需新增 G1，G2/G3 动作不在当前范围。没有 DB/PG、Docker、broker、外网、模型、付费、通知、生产操作；独立审核由 ROOT 交原 R。本文件中的接口、JSON、断言均是拟定方案。

## 真实调用链与可复用设施

| 执行顺序 | 固定基线的函数/数据 | 已有能力与直接缺口 |
|---|---|---|
| 1 到期领取/派发 | translation_recovery.py：dispatch_due_translation_retries → claim_translation_retry | 条件领取，确切 run_id/claimed_at，raw_response.recovery_claim_v1 存源摘要和固定 deadline；selector 消息带完整身份。派发失败释放确切 run |
| 2 消费 | tasks.py：_translate_managed_claim_task → consume_translation_claim | 禁外层事务；article→确切 run 锁后读取时钟，只一位 claimed→executing；执行中的重投统一跳过，不能恢复已返回但未提交的结果 |
| 3 翻译 | translation.py：translate_article(managed_run=run) → provider.translate | provider 在事务外，受管模式不写终态；先实体解析，再构造请求、校验与占位符恢复，最后返回 TranslationResult(title_zh/body_zh/push_summary_zh/metadata)。循环中可能多次请求，metadata.raw 是模型原输出，并非最终恢复文本 |
| 4 回写 | tasks.py → finalize_translation_claim | 当前 result 只在内存；两锁后校验 executing、归属、源摘要、固定 deadline；新读取 article 按人工字段保护规则 apply，article 与确切 run 原子终态。结果返回到事务提交前崩溃会失去完整结果 |
| 5 派发 | tasks.py 成功后的 on_commit → queueing.dispatch_task | 队列异常可同步 task.run；on_commit robust 不保证可靠投递。不能当 outbox 或远端副作用幂等协议 |
| 6 回收 | recover_one_stale_translation | claimed/executing 可回收为 interrupted，随后可能新 claim；同一消息不会再次消费。没有跨 claim 调用预算或费用账 |

TranslationRun.raw_response 是现有 JSONField，主键和 article 外键可作检查点载体。apply_translation_result 会读 machine_horse_tags 并保护人工字段，故不能只存三段正文后重建空 metadata，也不能复用 metadata.raw 替代已经校验/恢复的结果。

现有 QuotaLedger.kind 仅 web_publish/qq_push，scope 为地区/群/站点时间窗，limit/used 为 PositiveSmallInteger；它是发布配额，不是 token、金额、预留/结算账。现翻译 client 构造未显式传 max_retries，单请求 timeout/max_tokens 与进程内 max_attempts 不等于跨轮预算。_usage_to_dict(None) 返回 {}，且 last_metadata 覆盖前次尝试：最终一次 usage 不证明整轮费用已知。以上判断来自仓库源码，不查 SDK 外部文档或声称实测其重试次数。

M01 Responses adapter 自有关闭态、单请求和 usage 边界，与现行翻译入口不同；本片不把 M01 接入 tasks，不修改其配置或扩大真实调用。

## 三个剩余面的取舍

| 候选 | 复用条件与新增复杂度 | 推荐顺序 |
|---|---|---|
| 累计 token/请求/墙钟/金额预算与 unknown usage | 必须定义逻辑任务跨 claim 及内容/策略版本身份、每次 SDK 实际请求预留、未知用量占账、金额币种/单价版本、每日共享账户锁和普通路径范围；发布配额账不能直接代用。F06 的账号/单价仍是外部输入 | 不作为本次最小片；不猜金额，不先做一个看似总预算但只覆盖末次请求的 JSON 计数器 |
| 已验证结果检查点 | 复用确切 run、源 SHA、不可续期 deadline、锁序、现有 apply 和终态事务；两处短事务之间新增可复用的完整结果 | **本次推荐**。限定同一 claim；零新增恢复 provider 调用；无需新模型/索引/迁移 |
| 可靠下游派发 | 需事务内持久 outbox、重发所有权/扫描、broker 接收不确定性、下游业务键幂等及副作用边界；只补回调重试不足 | 后续独立片；不顺带开启自动发布/外发 |

## 拟定检查点合同与版本

在 raw_response 中增加独立键 `recovery_result_v1`，保持原 `recovery_claim_v1.phase=executing`，不新增 phase，以便旧代码仍拒绝执行中的重投且 stale 仍能回收。检查点包含：

- schema_version=1、application_contract_version=`translation-result-apply-v1`；这是结果/恢复合同版本，不冒充完整术语库、实体解析或 prompt 版本。
- article_id/run_id/claimed_at/input_sha256/deadline_at，与现有 claim 全部一致；不是文章级缓存键，也不能借新 claim 复用。
- title_zh/body_zh/push_summary_zh 和完整可 JSON 序列化 metadata（包含已解析术语、实体、标签、provider/model 等），保留恢复后的最终文本。禁止 metadata 覆盖 recovery_claim_v1/recovery_result_v1 等内部保留键。
- `suppress_automation` 原执行策略快照，首次有效写入后不可变。恢复不能用重投参数把原 suppress=True 改成允许派发，也不能用改参静默改变原策略。
- checkpoint_at 和 canonical payload_sha256（UTF-8、严格 JSON、排序键、固定分隔符）；摘要用于一致性，不声称防恶意数据库篡改。读取重新校验类型、绑定和摘要。
- usage_report 保留 provider 原 usage；usage_reconciliation=`unreconciled`，没有金额字段默认为零。即使末次 usage 合法也不宣称前次尝试/SDK 重试用量完整。缺失/无效用量标 unknown，不根据文本长度补估或归零。

严格 JSON 仅接受内置 dict/list/str/bool/int/有限 float/null，键必须字符串；拒绝循环、过深、NaN/Infinity、repr 兜底及不可序列化对象。标题/正文为非空字符串，summary 为字符串，metadata 必须 dict；对 apply 会消费的 terms、machine_horse_tags、provider/model 等验证相应形状，不把 JSON 合法当业务结果合法。编码/shape 检查及重建在锁外；锁内复核归属与摘要即可。建议检查点 canonical 字节上限 2 MiB、嵌套深度 32，作为待 R 评审的防膨胀技术参数，尚无代表数据容量证据；超限仅明确 checkpoint_invalid/oversize，保留 executing，不进入 provider 异常计次或补发路径。若实际合法数据与界限冲突，回 ROOT 调整方案，不以截断存储通过。

同一 run 是已经消费的执行身份，本片恢复的是这个执行结果；不会重新解析术语、重建 prompt、重新运行 provider 或改写旧 metadata。合同版本不支持时拒绝恢复，不换新版本调用。源字段改变即 input_changed。术语库或设置变化不自动使同一 claim 的既有输出变成跨版本缓存；在原 deadline 内按原结果快照完成这一执行。若产品要求术语更新必须撤销进行中的所有结果，需要新的版本失效决策，回 ROOT，不自行造全库版本账。

## 拟定执行流：只增加一个结果持久化边界

1. **原消息入口分支**：新增受管“领取或读取检查点” helper，在短 atomic 中 article→指定 run 锁后核对身份/源/实际时钟。claimed 且无检查点：沿原消费改 executing，返回 execute；executing 且有合法绑定检查点：返回 resume；executing 无检查点：保持原 already_consumed，provider=0。终态、失主、未知合同、非法 JSON 或检查点位置不合法：明确 skipped，绝不回落 execute。恢复返回快照后锁释放。
2. **首次执行**：execute 才调用现有 translate_article(managed_run)，事务外；provider 异常沿原有效异常 finalize，不创建成功结果检查点。provider 正常返回后，锁外生成完整 canonical 检查点。
3. **检查点保存**：新增短 atomic，锁 article→run，phase 必须 executing；再次锁后检查当前归属/源摘要/固定 deadline。首个合法检查点只写 run.raw_response，保留 claim 与其他 metadata，不写 article 终态、不派发、不通知。已存在同摘要检查点可以幂等读取；存在不同摘要不得覆盖。保存失败/绑定失效明确退出，不能被宽泛 provider except 捕获并记翻译失败，也不能重新调用 provider。
4. **原执行与重投共用回写**：execute 写检查点后，与 resume 均走“从检查点完成” helper；锁外严格解码为 TranslationResult，短 atomic 内按原锁序复核当前 executing、检查点摘要/版本/绑定、实际时钟和源。article.apply 使用当前人工保护字段，article/run 原子完成，checkpoint 保留作审计；run metadata 合并不得覆盖内部保留键。这一 helper 不接受任意调用者内存 result 绕过检查点。
5. **竞争**：原执行保存后和多个 resume 都可能持相同快照入场；终态事务锁后只一位 executing→completed，其他 skipped。没有临时 resuming lease、没有把 claim 再改回 claimed，因此不需要另一套执行权框架。异常回写对已存在成功检查点不得覆盖为 failed；原 provider 已完成，只允许检查点完成或现有归属/期限拒绝。
6. **派发**：只有真正提交 article/run 终态的胜者按持久 suppress 快照和当前既有 AUTOMATION_ENABLED 条件执行原成功回调。重投后的 completed 不补派发。本片仍有“提交后、回调前崩溃”缺口，不声称 reliable dispatch。
7. **回收**：phase 不变，无须新增 stale selector。过截止仍沿既有 stale 回收确切 executing run；保留 checkpoint 审计但不再应用，不延长 deadline。回收/下一 claim 不借它调用 provider 或复用正文。不得新增无身份/latest-run 扫描。

恢复触发仅现有准确 envelope 的重投或被授权的同消息重放；settings 默认 acks_late=True 是源码配置，并非所有 worker 退出均自动重投的保证。本片不改 ack/reject/broker、不新增定时扫描或恢复队列，故交付名称是“具备同消息恢复能力”，不是“保证所有崩溃最终恢复”。需要 deadline 后恢复/自动扫描时另派 ROOT 方案。

## 崩溃、预算与未知费用边界

| 时点 | 拟定恢复行为 | 费用/可靠性含义 |
|---|---|---|
| 发送前或 provider 内退出，未存检查点 | executing 重投仍 skipped；只有已有 stale 流可产生新 claim | 不能判断请求是否已扣费，本片不新增调用；已有跨轮重试的未知费用风险未闭合 |
| provider 已返回，检查点尚未提交 | 与上一行相同，明确无 durable result | 不承诺消灭远端返回与首次数据库保存之间的窗口 |
| 检查点提交后、终态前退出 | 同 envelope 在原截止前读取完整结果，provider/client/entity-resolution 次数均为0，原子回写 | 恢复不新增请求/token/金额；不退还/补结旧预留，不把未知 usage 记0 |
| 终态事务中 article 或 run 保存失败 | 两者回滚，已独立提交的检查点仍在；同消息可再做本地终态尝试 | 本地恢复次数不是付费次数；仍不续期，零 provider |
| 锁等待跨截止/源更改/新 claim/旧合同 | 不应用结果，不通知、不派发、不换版本重调 | fail closed；原 B037-R01 时钟规则继续适用 |
| 同一检查点多个恢复者 | 至多一个终态写入和成功回调登记 | 不承诺 broker 或远端发布 exactly-once |
| 终态提交后退出 | 重投跳过，不补派发 | outbox 缺口保留 |

**预算语义必须分开**：run_id/claimed_at 是 claim 身份；input_sha256 是源内容绑定。未来跨轮预算应绑定逻辑任务+内容版本+预算策略/模型定价版本，所有相关 claim 共用累计预留/消耗，重投/新 claim/配置变更不得自动重置；换内容或策略是否新预算、账户每日金额如何汇总必须由 ROOT/F06 锁定，当前没有实现此身份账。

未来真实调用准入在没有完整额度/单价/币种/实际 usage 或请求结果未知时应 fail closed，未知费用保留预留或阻断后续有偿调用，不能“timeout=未收费”。本片直接相关的 fail-closed 是**所有恢复/非法检查点分支零 provider**；它允许用已验证输出做不收费的本地提交，不要求以未知成本销毁可用结果，也不改变原自动新 claim 重试策略。因此整条跨轮付费链尚不满足完整预算闭环，不能据本片启用或扩大付费调用。若 ROOT 要求同时阻断已有 stale→新 claim 的未知费用调用，需扩大到请求预留账与调用准入，不能作为小修混入本片。

本片 wall-clock 仍是原 claim 固定 deadline，对所有恢复尝试共用；不重置 started_at、deadline 或请求/token计数，不说明远端请求被强制取消。没有新增真实单价、金额估算或吞吐结论；mock 计数只验调用边界。

## Ownership、依赖及 DDL 风险

| 拟实施 ownership | 最小责任 | 禁止扩张 |
|---|---|---|
| (integration) B：translation_recovery.py | 严格 checkpoint 编解码/绑定；受管入口 execute/resume；保存和从检查点终态 helper；旧异常不得覆盖检查点；保留 article→run 锁后deadline | 不改普通路径/预算模型/stale调度范围 |
| (integration) B：tasks.py 的 _translate_managed_claim_task 及必要相邻导入 | provider except 与本地 checkpoint异常分开；execute/resume共用终态与胜者回调，保持旧返回shape | 不重构共享 tasks，不改M01/发布/QQ |
| (integration) B：新增受管检查点测试及本片文档 | 真实RED、回滚与两连接竞争断言 | 不独自改共享catalog/full规则 |
| ROOT/C：固定实施基线、共享文件排队、catalog/impact/full及测试窗口 | 须含 B037 与 R01 修复；C033 后的确切集成 SHA 由ROOT给出并重核此方案依赖 | B038当前a8b182bd不是C033未来集成SHA；没有实施授权/窗口 |

translation.py、models.py、settings.py、migrations 本片建议零改动，复用 TranslationResult 和现有 JSON。不新增索引或大量扫描，无 schema/data migration，JSON checkpoint写入是未来功能的持久数据影响。数据库 DDL 风险为无新增 DDL；但JSON膨胀/WAL/备份及无数据库schema约束是实际风险，需上限验证与helper合同测试。保留原raw_response消费者兼容；metadata合并保留内部键。

M02 卡工程估算5小时、DDL截止2026-10-07 18:00 Asia/Shanghai是规划工期，不是已完成事实。下一片即使通过仍有预算/outbox/自动恢复缺口，存在完整M02按期交付风险。范围应由ROOT继续拆解排期，不能把本片通过改为M02 DONE。若独立审核认为预算账应先行、无新增schema无法安全表达合同，或期限/恢复触发要求必须扩大，先回ROOT重新锁范围。

## RED 与验证设计（均未执行）

所有 provider/client、dispatch、通知为替身，数据库只能使用ROOT精确分配的官方隔离PG runner；不连接生产/Redis/broker/真实服务。先在固定未改业务代码上取得行为RED，新增helper不存在/签名不符不算RED。

| 断言 | 基线业务RED的构造 | 预期GREEN |
|---|---|---|
| durable成功结果 | 真实受管task调用mock provider，拦截最终finalize模拟进程退出，再读run；当前只有executing且无完整最终结果 | checkpoint独立提交，包含最终中文及完整metadata；不是metadata.raw |
| 重投恢复零调用 | fixture在现有executing run预置拟定合法checkpoint，走现有envelope任务；当前只跳过，不写终态 | 未重新创建provider、实体解析或请求；article/run成功，输出/人工保护正确 |
| 回滚后恢复 | 先成功提交checkpoint，再让run终态save抛错 | article/run终态原子回滚，checkpoint仍存在；下次相同envelope本地成功，provider总次数不增加 |
| 同claim竞争 | 两连接两个相同checkpoint恢复者在helper入口同步 | 一成功、一skip；只一次apply/胜者回调，线程/连接关闭；PG锁证据而非顺序调用 |
| 未知usage | 有完整有效结果但usage空、无效、仅末次report | 本地恢复成功且provider0；保留unknown/unreconciled，费用不归零，不声称整轮known |
| 完整metadata/人工字段 | 结果含machine_horse_tags、术语、模型，与源raw不同；checkpoint后编辑人工中文字段 | 最终translated字段来自checkpoint，人工保护按当前字段，不重算实体/术语 |
| flags重投漂移 | 原checkpoint suppress=True，重投传False；反向同样检查 | 持久原执行策略胜出；suppress=True时派发0；当前AUTOMATION关闭仍0 |
| identity/version/JSON坏值 | 错run/文章/源摘要/时间、hash错、未知版本、保留键、循环/过深/超限或缺少正文等 | 明确skip且provider0、article/run不改；不借最新run、不截断、不fallback调用 |
| 截止与锁等待 | checkpoint保存与恢复终态两边均测截止前、等于、之后；article/run各持锁让等待跨deadline | 锁后真实时钟拒绝；deadline不续期、零回写/派发/通知 |
| 原执行与恢复竞态 | checkpoint提交后原worker暂停，重投完成，再恢复原worker | 仅恢复者提交；原workerskip，不覆盖终态、不重复回调 |
| checkpoint保存失败/冲突 | run.save异常、已存不同hash、源变更或stale抢先 | 无article终态、失败计数/通知不额外改变、不走provider异常重试；已有checkpoint不覆盖 |
| 无checkpoint和终态重投 | executing但无checkpoint、completed/failed/interrupted或旧preclaimed缺身份 | 原fail-closed不变，provider0；已终态不补派发 |

第一/第二条先取得真正业务RED后再实施；其余以明确 mutation 验证而非强求旧代码在所有防护测试失败。隔离TransactionTestCase验证实际独立提交、回滚以及回调无事务；不能在外层TestCase事务内手动执行回调冒提交证据。崩溃注入使用测试专用BaseException/明确阶段拦截，不访问真实进程/付费服务，也不宣称模拟等于broker进程丢失恢复。

回归保留B037 25项、recovery22、普通/force翻译与字段保护、相邻受管通知与M01无变更证据；准确IDs/受影响范围/并发连接资源由实施时ROOT批准，当前不复跑47。正式catalog/impact/full由ROOT/C闭合，诊断测试不能替代。失败后不自行复用窗口或减分母。

## 兼容、回滚与停止点

- 老消息缺身份仍fail closed；老executing无检查点仍不重调。普通首次翻译、force/manual、M01和可靠结构更新入口不新增checkpoint依赖。
- 新JSON键和原phase兼容旧B037：旧worker看到executing仍skip，stale仍回收。回滚代码可能失去本片恢复能力，但不得把executing重置claimed或主动重调provider；检查点原文保留。混合新旧worker不保证及时恢复，未来精确发布包须界定worker版本/队列和观察方式。
- 无新feature flag、自动发布/邮件开关或外发范围；成功沿原受管回调条件。旧metadata消费者与受管raw JSON必须回归。
- 实施后只回写实际变化的B文档；集成/主线状态由ROOT更新current_state，真正形成共享产品/架构决策时再写decisions，未发布不更新生产为完成。

请ROOT将固定方案交原R审核：重点核同claim结果检查点是否为最小下一片、严格合同/保留键、unknown usage的本地恢复边界、原deadline内恢复的实际价值及无保证重投/outbox的验收命名。本轮停在方案；通过方案后仍需ROOT派固定集成SHA、文件ownership与RED资源，不能直接从本树实施或竞争C033共享面。
