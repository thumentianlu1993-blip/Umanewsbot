# B036：M02 自动重试轮次归属与迟到回写最小方案

任务：B036-M02-BOUNDED-RECOVERY-FIRST-SLICE-PLAN-001。状态：原 R 初审 REVISE，唯一 P2 B036-R01 已修订方案，待同 R 局部复审；未实施、未跑 RED/GREEN、未合并或发布。

推荐先闭合一个已有业务路径：**自动翻译重试领取 → 同一轮消息消费 → 翻译 → 受归属保护的成功/失败回写**。复用 TranslationRun，不引入通用 agent 编排、运输协议、工具框架。该切片解决同一领取重复执行和失去归属的迟到回写；完整 M02 的跨轮费用预算、结果复用和可靠下游派发仍须另行交付。

## 核对基线与范围

2026-10-06 只读核对：远端 main 是 `6e6aded22764ebee3d6a97f2834f47d4b4baa7bb`；检查树为 `/Users/mentianlu/.codex/worktrees/b035-n01-cleaning/umanews`，应用代码基于该 main，HEAD `4bdeb6101f604dbdf06f48a8ce8ac97b38b7b55c` 仅叠加已交接 B035。开始时工作树干净。本轮只增加本 B 报告与独立 runtime 源码摘要；不修改共享代码、ROOT 台账或旧包。后续实现应由 ROOT 指定新的固定集成基线及独立分支/worktree，不能直接沿本 B035 树实现共享变更。

授权及门禁统一引用根 AGENTS.md。当前只读方案不触发新的 G1/G2/G3；ROOT 指令限定先审方案再派实施。没有生产/真实数据库、Redis、Celery broker、模型、抓取、付费、外部发送或新增 Docker 资源。B034 精确包保持冻结且生产动作未批准；后台与 QQ 暂缓范围不变。

## 已有成果足够做什么

| 已有部分 | 当前证据与可复用能力 | 尚不能证明的能力 |
|---|---|---|
| M01 Responses adapter | `responses_analysis.py:281` 的 analyze；输入绑定和严格输出校验；关闭态零 client；`max_retries=0`、一次 create、timeout ≤90s、max_output_tokens ≤16384；usage 未提供时为 null；只输出候选 | tasks/models 无 M01 调度接入；无持久化步骤、跨重投累计预算或发布授权。不能用它替换现行翻译再称已接入 |
| 翻译 recovery | `translation_recovery.py:185/244/292`：到期选择、FAILED→TRANSLATING 条件领取；派发失败按开始时间释放；stale 回收在短事务内复核状态和时间；暂时错误退避/Retry-After/耗尽退出 | Celery 消息没有 run 身份；领取次数不等于失败次数；stale 的 is_retry=False 不累计 retry_count。故不能证明所有崩溃路径有累计调用硬上限 |
| 翻译 provider | `translation.py:798` 的单进程校验轮数，单调用 timeout/max_tokens，现有 run 审计 | SDK 构造未显式关闭自动重试；单进程轮数不是持久化请求预算；没有整轮 deadline、可恢复的完整 TranslationResult |
| 旧 M02 静态成果 | `43de074c` 的 B016 partial Index 映射；clock-budget-static.json 明示 static_inventory_and_budget_not_native_trace、actual_native_calls=0、candidate_tests=0，可复用“固定输入/hash、预算与证据状态分开”原则 | 这是静态运输字节/调用槽计量，不是 Django/Celery 模型调用预算、恢复运行态或生产验收；不搬它的框架进业务代码 |
| 当前测试 | `test_translation_failure_recovery_change.py:205` 起已有二次条件领取、非 preclaimed 重复跳过、stale 回收、已完成不被 stale 覆盖 | “concurrent”命名的领取测试实际顺序两次调用；未证明真实并发、preclaimed 重投、迟到成功/异常或 run 与 article 原子终态 |

M01 保持原服务、开关和结构候选边界。本片只改翻译恢复路径；不会把模型不可用变成赛事/马匹可靠结构数据更新的全局阻断。隔离测试应另断言可靠结构更新入口未新增此依赖。

## 当前真实执行流与缺口

1. selector 读取 due 行 → claim 在短事务内更新 article.started_at，并建一个 STARTED TranslationRun；返回值只有 claimed/article_id/reason。
2. selector 发 `translate_article_task.delay(article_id, preclaimed_retry=True)`；消息未绑定 run_id/claim 时间。
3. task 只验证文章仍 TRANSLATING 且存在任意 STARTED run。随后走 else 分支重新写 started_at，改变原领取时间；两个同消息 worker 都可能通过。
4. `translate_article()` 选择该文章最新 STARTED run，自行把它改为 SUCCESS/FAILED，再返回结果或抛异常。它没有接收领取身份。
5. task 对启动时取得的 article 无条件 apply/save；异常分支也先 save provider/model，再记录失败。此时 stale recovery、后续领取或编辑可能已经改变数据库。
6. 成功后另行 dispatch automation。Article save 与消息派发之间也有崩溃窗口，但本片不扩大到可靠 outbox 或发布实现。
7. `record_translation_failure:181–182` 在终止条件满足时同步调用 `notify_terminal_translation_failure`，后者约第438行 `send_mail`。直接在受管原子事务内复用此调用链，会持 article/run 锁外发；若后续 run 保存失败，数据库可回滚而邮件不可撤回。

反例：W1 领取 A 并调用 provider；回收 A 后 W2 领取 B；W1 迟到成功会覆盖 B 的状态及正文，迟到异常会把 B 改失败；旧消息又可能借用 B 的 STARTED run 执行。仅增加 task 最后一处检查无法保护翻译服务内部 run 写入和异常路径。

## 推荐第一切片：单个自动重试领取的消费与终态保护

以下是拟定接口及业务流，**不是现有实现**。先覆盖 selector 自动重试和 task 内到期失败领取两条汇入同一 claim 的入口；普通首次翻译、force/manual 语义保留原路径，不借此重构。

### 输入、持久化与输出

- claim 返回 `article_id/run_id/claimed_at`；JSON Celery envelope 携带 run_id 和精确 UTC 时间。article.started_at 不再由 preclaimed worker 重置。只认该 run 与文章，不查“任意最新 run”。
- 用现有 `TranslationRun.raw_response` 下独立 `recovery_claim_v1` 保存阶段 `claimed/executing/completed/failed/interrupted`、固定 claimed_at、固定 deadline_at、源输入摘要；结果 metadata 保持独立键，禁止覆盖 claim 部分。run_id 是轮次身份；不是长期内容缓存键。
- 源摘要绑定实际消费的 source_site/source_language/title_ja/body_ja_normalized 或 raw 正文及字段选择版本，不以 updated_at 代替内容版本。仅保护文章源内容；术语/实体解析版本暂未被完整绑定，不能宣称跨术语版本结果复用。
- deadline 在领取时固定为 claimed_at + 当前 stale 时间上限；重投不能延长。此 deadline 控制准入和回写，不能称远端请求被强制取消或精确计费截止。
- 输出保持 task 既有成功形状；新增 skipped reason 如 claim_missing/claim_changed/claim_already_consumed/claim_expired/input_changed。失去归属是终止旧消息，不再触发该文章失败/自动派发。

### 执行顺序与事务边界

1. **领取**：在现有领取事务中建确切 run，保存不可延长 deadline 与输入摘要。返回完整 envelope，事务提交后发消息。派发失败只释放这个 run/claim，不能批量终止其他 STARTED run。
2. **消费**：短事务内锁 article 后锁该 run，统一锁顺序；核对 TRANSLATING、原 started_at、run.article、STARTED、phase=claimed、deadline 尚未到及源摘要。只一位消费者把 phase 改 executing。第二位读到 executing 即跳过；不得因为重新收到消息而再次付费调用。
3. **外部工作**：事务结束后调用现有翻译逻辑。拟给 `translate_article` 增加明确的受管 run 参数/模式；此模式使用指定 run，禁止自行选择最新 run或写终态。现有普通路径保持兼容。provider 调用期间不得持有数据库事务/行锁。
4. **成功回写**：短事务重新锁 article、run 并核对同一归属、phase=executing、deadline 和源摘要；在当前新读取的 article 上按现有字段保护规则 apply，避免启动快照全字段覆盖。article 翻译终态与该 run 终态/metadata 同事务提交。提交后才允许现有 automation 派发，失效消息零派发。
5. **异常回写**：必须先执行同样的归属核对，才能沿既有分类、退避和失败次数逻辑回写；旧 worker 不得先保存 provider/model 或修改其他轮的 run。受管模式只复用失败状态计算/保存，显式禁止 helper 同步通知；有效异常写 article 和指定 run 的 FAILED 同事务。仅在此 claim 首次有效终态转换且满足既有 terminal 通知条件时注册提交后回调，不为失主/重复消息注册。
6. **回收/释放**：复用已有 stale 条件复核，按绑定领取终止确切 run。若过了本片 deadline，则 executing→interrupted；到期选择仍走现有错误退避，不由旧消息自行重新调用。受管 stale 回收和派发失败释放也遵守同一状态/通知拆分：只在有效归属且既有 terminal 条件成立时登记回调，非 terminal 不新增通知；不得绕道原同步通知 helper。
7. **终态通知**：`transaction.on_commit` 或等价提交后机制在最外层事务成功提交、article/run 行锁释放之后，使用绑定 article_id/run_id 的本次终态快照调用既有通知 helper；不借用另一轮当前状态。通知日志写入和 send_mail 都在该持锁事务外。article/run 任一保存失败则全部回滚、回调丢弃；失去归属零通知。通知调用失败只记录通知失败，不能进入翻译异常回写再改变已提交状态或重试 provider。普通非受管路径、现有通知条件/开关/收件人不变。

deadline 的领取值及 claim 消费记录是本片持久化的一个步骤；不是所有模型步骤/工具的总预算。原 provider 的进程内请求次数、SDK 重试、跨新 claim 的调用费用仍未硬界定。本片不会新增 ledger、扣账、模型启用或自动发布能力。

### 失败、重投和迟到边界

| 时点/状态 | 预期行为 | 仍待后续的边界 |
|---|---|---|
| claimed，尚未消费时重投 | 同一 run 的首位消费者执行；其余跳过 | 新增消费记录必须与领取同库持久化 |
| executing 时同消息重投 | 不再调用，不重复 article/run 终态写入或派发 | worker 已发送远端请求而响应未知，不能推断未扣费 |
| 执行进程退出 | 原消息不能重新消费；由现有 stale 回收，按已有策略产生新的领取 | 新领取可能再次调用；没有跨轮预留预算，本片不证明累计费用有界 |
| 旧轮成功/异常在回收、新领取或源内容变化后返回 | 拒绝旧 article/run 终态回写，零 automation 派发、零终态通知；只写任务层 skipped 审计 | 本片不存旧响应原文作跨轮恢复缓存 |
| provider 返回但终态事务未提交即崩溃 | 仍为 executing；重投不盲目再调用 | 结果可能丢失；下一片需要响应持久化/未知用量策略 |
| 终态提交后同消息重投 | 返回已消费，provider=0、article/run 二次写入=0、派发=0 | 不补 article 已提交但 dispatch 未发生的窗口；须后续可靠下游派发方案 |
| 缺 envelope 的旧 preclaimed 消息 | fail closed，不猜最新 run；现有 stale 可回收 | 将来发布包要明确旧队列兼容/排空或观察策略，当前不操作队列 |
| 模型不可用 | 有效归属沿现有可重试/终止分类；结构数据路径独立 | M01/结构数据集成验收不是本片完成证据 |
| 有效 terminal 失败提交 | article/run 原子提交且释放锁后，既有通知 helper 调用一次；同消息重投不再次登记 | 提交与回调之间进程崩溃可能漏通知；无 outbox，不证明可靠投递或远端 exactly-once |
| 受管失败/回收/释放保存失败 | article/run 原子回滚，提交后回调丢弃，通知 helper/send_mail 调用 0 | 不通过直接发送或立即重试补偿回滚 |

这里的“无重复”仅指同一 claim 的主动消费和回写/派发；不承诺跨新领取的模型 exactly-once、远端扣费 exactly-once，或整个自动发布流水线 exactly-once。旧路径仍有独立风险，不能因本片完成降低完整 M02 分母。

## 文件归属与 ROOT 需要安排的共享面

| 拟触达文件/函数 | 必须改动 | 当前处理 |
|---|---|---|
| services/translation_recovery.py：claim/dispatch/release/stale/record_translation_failure | 完整 claim 身份、消费/终态核对 helper、固定 deadline、确切 run 释放；仅受管路径拆分失败状态与提交后通知，保留普通路径行为 | 需 ROOT 派共享面责任，未改 |
| stable/tasks.py：translate_article_task | envelope 参数、消费入口、成功/异常受保护回写；不先写失效快照 | **共享 tasks 必须 ROOT 明确安排，未改** |
| services/translation.py：translate_article | 指定受管 run，避免自身终态写入绕过 fence | 需 ROOT 固定兼容责任与相邻回归，未改 |
| models.py/settings.py/migrations | 本片优先复用 raw_response 与 started_at、现有 stale 配置，不增加字段/配置/迁移 | 若 R 认为 JSON 约束不能保证并发语义，先报 ROOT 调整，不自行新增模型/迁移 |
| recovery 测试 + 新针对性隔离测试/catalog | 扩展 envelope 契约、竞态与迟到断言；新模块登记由 ROOT/C 处理 | 不改共享 catalog，不启动新 Docker/DB |

不得把所有调用者改成通用 managed runtime。需先检索现有 raw_response 消费者，确保保留 translation metadata 读取兼容。本片实现前应再核固定基线的该三文件 SHA 与 C 的共享改动，冲突交 ROOT。

## RED 设计与验证计划（尚未执行）

先在当前基线上取得业务失败，不以新增字段缺失或签名 TypeError 代替核心 RED。以下 mock 是现有入口替身和可控交错，不访问真实服务。

| RED 场景 | 当前会失败的业务断言 | GREEN 后验收 |
|---|---|---|
| preclaimed 同领取第二位入场 | 第一位 mock provider 暂停时，第二位同消息也调用 provider | 同 run 调用计数为 1；重复返回明确 skipped |
| W1 成功迟到 | mock provider 内安排 stale 回收并建立 W2 领取，随后 W1 返回 | W2 started_at/run/状态/正文原样保留；automation mock 调用 0 |
| W1 异常迟到 | 同上但抛 timeout | W2 retry_count/next_retry/状态不变；旧 run 不写成功/失败，任务审计失效 |
| 源内容改变 | mock provider 返回前更新源正文 | 新源不被旧结果覆盖，零派发，原 claim 可明确终止 |
| run 身份替换 | 旧消息入场时只有另一个 STARTED run | provider 0；不得偷用新 run |
| 领取时间保持 | 自动 claim 后消费入口 | started_at 与 claim 一致，重投不能延长 deadline |
| 截止前后 | 注入本地时钟，入场到期/返回到期各一例 | 到期分别 provider=0/拒绝终态；精确时间边界确定 |
| 原子终态失败 | mock 保存 article 或 run 抛错 | 两者同时回滚；重投不重复消费，不声称已完成 |
| 终态后的重投 | 同 envelope 连续执行两次 | 结果回写/失败次数/automation 各至多一次 |
| B036-R01：有效 terminal 通知一次 | 受管失败事务直接复用现 helper 时，通知 mock 在 in_atomic_block=True 下被调用 | 成功提交后 article/run 均为对应终态；回调执行时 in_atomic_block=False；既有通知 helper 一次，同消息重投仍一次；send_mail 替身不联网 |
| B036-R01：保存失败回滚零通知 | terminal article 已保存/同步通知后，mock 指定 run.save 抛错 | article/run 状态全部回滚；on_commit 回调不执行，通知 helper/send_mail 各 0。受管 stale/释放同样遵守此断言 |
| B036-R01：失效异常零通知 | W1 异常迟到，W2 已领取；旧异常若进入 terminal helper 会发错误通知 | W2 状态/次数/run 不变；不登记回调，通知 helper/send_mail 各 0；受管回收/释放归属失败同样为 0 |

隔离 Django TestCase 可先跑顺序交错与回滚；mock provider/client、dispatch、通知，CELERY eager 或直接 task.run，网络 deny、DB 连接只指向明确测试库。此轮没有连接测试库或运行测试。

B036-R01 三项窄断言拟采用隔离 TransactionTestCase、受管入口的实际 atomic 与通知 helper/send_mail 替身；成功例让 on_commit 在退出最外层 atomic 时自然执行，并在替身内检查无事务及 article/run 已提交；回滚例断言回调被丢弃。不在仍持锁的 TestCase 包装事务内手动执行捕获回调来冒称提交后验证。不启用邮件、不使用真实收件人，不新增测试资源。这三项仅补测试方案，尚未执行。

mock/SQLite 不证明 select_for_update 真并发。最终并发验收需 ROOT 明确现有隔离 PostgreSQL runner：两独立连接/线程同步在消费处，验证一位获得执行权及统一锁顺序；当前无新 Docker 授权，资源未就绪时标缺证，不把顺序案例当并发通过。

相邻回归：现有 recovery 模块、翻译 provider/术语字段保护、force published 保留人工字段、普通首次翻译路径；M01 mock 测试保持开关关闭/输入绑定/单次请求契约。按共享 tasks 的 impact plan 保留正式门槛，不能用小片 mock 代替 required full。测试登记与 CI 由 ROOT/C 协调。

## 交接与停止点

请 ROOT 将本固定方案交原 R 快审，重点确认：现有 JSON 上持久化消费是否足够、三文件受管模式是否为最小改动、失效异常的任务返回语义，以及旧消息和 deadline 的兼容边界。确认共享文件责任、固定基线和隔离测试资源后，再派实现；本轮停止在方案。

完整 M02 仍缺：跨请求/跨轮持久预算预留与未知用量账、严格整体 deadline/SDK 重试费用边界、响应存储及同输入版本恢复复用、可靠下游派发/公开副作用去重、真实隔离并发和失败矩阵。这些不能从 B016 静态预算或本片 fence 推导完成，也不自动扩大本片实施范围。

## B036-R01 方案返修记录

派单 B036-R01-POSTCOMMIT-NOTIFICATION-PLAN-REPAIR-001；依据原 R 的 [唯一 P2 审核报告](/Users/mentianlu/.codex/worktrees/3ab1/umanews/docs/changes/next-version-capabilities/lanes/R/R-B036-M02-claim-fence-plan-review.md)。本次只修受管有效失败及其回收/释放复用路径：先原子完成 article+确切 run，提交后无锁调用既有通知；失主/回滚零通知，并补上述三窄 mock 断言。普通路径不改，不引入 outbox 或新外发权限；真实发送仍未授权。未修改共享代码/测试，未运行 RED/GREEN；修订文档检查及固定小提交由独立 runtime receipt 绑定，交 ROOT 返回同 R 限定复审。
