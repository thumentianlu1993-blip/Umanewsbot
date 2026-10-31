# P02 开发设计

## 代码复用与差距

本设计以 e4df6bda 为准；以下是源码存在性判断，不是本轮测试或生产证明。

| 责任 | 现有入口 | 本期补齐 |
|---|---|---|
| 身份/能力/请求额度 | race_source_identity.py、race_data_sync_enrollment.py、race_data_sync_providers.py、race_data_sync_control.py | 逐地区逐能力凭据、来源样本、缺口与请求预算 |
| 决策/资料显示 | race_data_sync_policy.py、race_information_display.py、race_pre_race.py | 真实 loader、成熟度与可见性投影、影子对照 |
| 来源裁决 | race_source_arbitration.py、race_result_arbitration_shadow.py | producer 的资格/版本/完整性证明；名单不能误用仅结果裁决器 |
| 调度/异常 | race_event_lifecycle.py、race_data_sync_results.py、名单对账相关模块 | 实际 hook、期限更新、claim fence、赛后追踪 |
| 结果版本与公开 | race_events.py、RaceEventRevision/Item/Evidence/Publication | 原子发布、统一读快照、可靠失效补偿 |
| 计量 | race_timeliness_contracts.py、race_public_coverage.py | 持久化 receipt、目标集合、外部公开探针 |

服务路径均在 `server/stable/services/`；模型在 `server/stable/models.py`。保留现有 revision 唯一约束、单写入者、来源网络准入与 publication admission。不得将纯裁决的 qualified 布尔值当成真实授权或来源证据。

## 数据流与模块职责

```mermaid
flowchart LR
  A[目标清单与能力登记] --> B[容量准入与有界调度]
  B --> C[事务外抓取并保存来源观测]
  C --> D[身份 完整性 成熟度 新鲜度]
  D --> E[纯决策与影子比较]
  E --> F[事务内复验 claim 与 generation]
  F --> G[原子 revision 与公开快照]
  G --> H[提交后失效和幂等补偿]
  H --> I[公开探针与质量时效报告]
```

补充两个薄服务：`race_lifecycle_projection.py` 负责把已验证输入映射到现有决策并构造统一公开快照；`race_lifecycle_metrics.py` 负责持久证据到 R01 合同的映射。网络 adapter 不调用模板；视图不自行裁决来源。现有 loader/批量公开 resolver 是全部页面的共同入口。

归一化观测包含：event/source race ID、data kind、schedule generation、payload digest、parser version、origin group、fetched_at、source published_at 或观测区间、maturity、full roster/status、supersedes/correction evidence、能力凭据引用。原文去凭据后按许可保存于 artifact 存储，DB 留 hash/URI；不保存 token 或任意可执行 URL。

结果冲突先比较同一 generation、同一资料种类和具备资格的观测；明确更正须有来源修订号/明确更正标记及目标关联，或可证明的同源版本序列且语义上为更正。抓取时间更晚不算更正。无裁决依据时输出 conflict 并自动补查，不强制等待第二个来源才首次确认。

## 正交状态与公开行为

赛事进程沿用 scheduled/postponed/cancelled/finished 等既有状态；资料成熟度独立，公开可见性为 visible/updating/verifying。开赛时间只驱动期限，不直接驱动 finished。来源明确开赛但未完赛才可显示进行中。

每种资料分别计算：已裁决冲突优先 verifying；临时且达到截止则 updating；其余展示相应成熟度。确定名单与已确认结果不会因日期过期被降级。遇到明确撤销资料有效性的证据时进入 verifying，而不是静默恢复旧错误值。页面同时显示“比赛延期/取消”等比赛状态，不能用资料提示覆盖赛事状态。

“隐藏赛果表”同时隐藏该版本的冠军卡、摘要名次、结构化数据/JSON/API 中相关结果，不能只隐藏 HTML 表格；名单冲突同理。日历、详情、冠军卡使用同一公开快照中的 generation、publication epoch、revision IDs。其他独立无冲突模块正常显示。

日期未知/仅当地日期时保留精度；不能触发伪造开赛倒计时。改期事务递增 schedule_generation，旧 claim、deadline、缓存版本均失效；记录更改前后时间和来源证据。取消停止普通名单/结果轮询，但保留每日低频状态纠正入口与人工/新观测触发，取消不是删除赛事。

## 持久化及迁移

复用 RaceResultObservation、RaceEventRevision/Item/Evidence/Publication、LifecycleControl 和 transport ledger。不修改旧 phase 的语义来冒充官方来源。新增以下最小数据面（模型名为实施目标）：

1. `RaceLifecyclePublicState`：event OneToOne(PROTECT)、epoch bigint、schedule_generation、racecard_revision/result_revision nullable FK(PROTECT)、每模块 maturity/visibility/reason/evidence_refs/deadline_at、policy_digest、updated_at。名单 maturity 为 predicted/confirmed/unknown，结果为 provisional/confirmed/corrected/unknown；每模块 deadline_at nullable，confirmed/corrected 不沿用临时截止。既有 RACECARD phase 不承担名单成熟度。内容、成熟度、证据、截止或可见性任一变化均递增 epoch；同一名单内容由预想转确定可复用 revision，但必须产生新 epoch。对已存在 revision A→B→A 更正使用新的 epoch，复用 A 的不可变内容，不能违反 (event,kind,phase,hash) 唯一约束。
2. `RaceLifecycleReceipt`：不可变 idempotency_key unique、target_key、nullable event FK(PROTECT)、kind、generation、revision/epoch、occurred_at nullable、recorded_at、deadline_at nullable、evidence_refs/payload JSON、rule_version。覆盖 scope、observation、deadline、publish、probe、audit、repair；未匹配目标也能落账，按 target_key+recorded_at 与 kind+deadline_at 建索引。null 时间代表未知。
3. `RaceLifecycleDelivery`：公开变更事务内 outbox，unique(event,epoch,consumer)，状态 pending/running/done、next_attempt_at、attempts、lease token/expiry、payload hash；索引 status+next_attempt_at 和 status+lease_expires_at。消费者仅缓存失效、探针调度、内部版本通知；不发送外部 QQ/邮件。
4. LifecycleControl 增加可空 first_result_confirmed_at、correction_until、next_correction_at；策略与来源能力沿用现有 registry/manifest，版本化快照，不另建权限体系。
5. `RaceLifecycleEpochPublication`：不可变每次发布凭据，unique(event,epoch)，并以 unique(event,idempotency_key) 防重复提交；event FK(PROTECT)、previous_epoch、schedule_generation、writer_owner/generation、两类 revision FK(PROTECT)、逐模块 maturity/visibility/deadline/evidence refs、当次 observation refs、content/policy/registry/allowlist digest、authorization kind/version、admitted_at、published_at、reason、完整 snapshot digest。它记录现有权限体系在本次 epoch 的校验结果，不授予新权限。PublicState 只是最新凭据的投影，更新与凭据插入同事务；reader 校验 state 与不可变凭据完全一致。

旧 RaceEventRevisionPublication 保持 OneToOne 和历史内容不变，不拿旧 A 的 publication 证明再次发布 A。新 cohort 通过明确的 epoch 发布服务，调用从现有 admission 中复用的当前权限谓词，逐项复验 owner、membership、generation、策略有效期、来源能力、证据与资料 phase；不得直接把旧 publication 中的 allowlist/registry digest 复制为当次证明。复用内容时使用本次 observation/evidence，而不是旧 revision.primary_observation 代表新事实。previous_epoch 表示 A→B→A 的发布顺序，旧 revision.supersedes 不回写。

现有 `resolve_race_live_public_reads` 对新 cohort 增加 epoch 分支，批量加载当次凭据和内容 revision、当前有效策略及权限：引用一致、权限仍有效、资料未撤销、当前时间符合 deadline 才可见。失败返回已有资料提示，不降回 legacy reader；未纳入 cohort 的赛事继续旧分支。关闭新 writer 不关闭该兼容 reader；权限撤销必须同步递增 cohort policy version/失效键，reader 不只依赖发布时通过。T11/T14 验证切换及回滚，不把历史授权表结构强行改为一对多。

migration 分两步：先 additive schema（小新表、nullable 字段，无默认全表重写）；再独立可恢复 backfill command。历史回填每批 100，记录最后 ID、输入 hash 和计数，幂等重跑；不在 migration 中请求网络。新表 FK 仅指向已存在对象，应用校验 event/kind/generation 一致，DB Check 保证 epoch>0、合法 visibility/maturity、visible 必须有该模块 revision、confirmed/corrected 的临时 deadline 为空。跨行一致性由锁与测试保障。unknown 无证据不能变 confirmed，重启后的 loader 只从持久 epoch 还原成熟度，不凭时间或来源名称推断。

未纳入本期清单的历史赛事保留旧读路径；已纳入的赛事须先审计现有公开结果，构造兼容快照或显式缺证状态，不能因为缺新字段把全站旧赛果隐藏。backfill 不凭空制造“已确认”，不追认旧授权；不确定项保留来源缺口供 R09 处理。

## 并发、原子性与失败路径

沿用现有全局锁图：registry barrier/membership → lifecycle control → 现有 claim 校验/事件及相关观测 → public state。实现须逐一对照现有 apply/claim 的实际锁顺序，不新建反向锁链；同一事务禁止网络 I/O。

流程：
1. 现有 claim 取得 owner token、generation 和 lease；在事务外按来源 host budget 抓取，解析并记录不可变观测。超时/429/空响应记录 transport 失败，不能提升成熟度。
2. 短事务内按既有顺序锁定、重新验证 membership、权限、token、lease 未过期、generation、owner、policy digest。输入在抓取期间过期即丢弃写入并重排。
3. 原子写 revision/items/evidence、按上述当前 admission 插入 EpochPublication、更新兼容 projection 和 PublicState、deadline/receipt、Delivery。任一失败整体回滚。idempotency_key 绑定 event+generation+目标种类+观测版本/证据 hash+策略版本+动作；不能只用内容 hash，否则相同内容的成熟度变化会被吞掉。claim token 只用于 fence，不因重试换 token 就制造新业务事件。
4. on_commit 唤醒 delivery；每 30 秒扫描 due pending 和 lease_expires_at 已到的 running，每批最多 100。原子 CAS（旧状态/旧 token/过期时间）夺回并签发新 token，lease 120 秒；耗时任务每 30 秒按 token 续约，失去 lease 即停。ack/fail 必须匹配当前 token、epoch、状态且 lease 未过期，迟到 consumer 不能确认新租约。操作后 ack 前崩溃会重放，因此失效、探针、内部消费均按 event+epoch+consumer 幂等，乱序旧 epoch 不能覆盖新快照。失败回 pending 并退避最长 15 分钟，后台持续补偿并记录超时；数据库故障期间保留 running，恢复后由过期扫描收回，不能永久卡住。
5. 公开 reader 单次批量加载 state 与所指 revision，禁止一半读旧行一半读新行。模板只消费已构造 DTO，不再临时查询当前可变结果。

Cache Key 包含 epoch/generation/policy digest。模块缓存有效期不超过其 deadline_at；组合页面取全部可见临时模块的最早 deadline。请求时始终用真实时间判定临时资料过期，后台任务宕机也不能继续展示。缓存服务故障回读 DB；禁止 stale-on-error 复活已隐藏内容。公开 HTML/CDN 涉及赛事内容的缓存上限 30 秒且不跨该 deadline，强制失效失败仍受上限约束；来源更新的 5/10 分钟预算包含此 30 秒。现有 race_event_public_cache.py 只覆盖站点计数/年份，不当作完整页面失效已实现。

## 调度和预算

复用 Celery、现有 enrollment 与共享 host ledger；每批最多 100 个 due control，使用索引和 claim，跳过已锁行，所有 network timeout ≤20 秒、单响应 ≤2 MiB，重试必须重新计费/计额。每个 provider 的批量赛事请求只计一次 HTTP 请求，不把 batch 内每场重复扣款。

初始可调参数（不是目前实测能力）采用两条不同任务：
- **及时版本发现**：在目标清单资料可能发布的有效覆盖窗口内，重点发现间隔最长 60 秒、常规最长 120 秒，包括确定名单出现、未确认/已超时赛事的新结果，以及首次确认后完整 7×24 小时的更正。日期赛和延期赛不因缺精确时间退出发现范围。使用能逐场反映所有相关版本变化的已验证批量索引/版本号/hash/增量端点；有可靠推送时仍保留缺口检测。只有前三名快讯、只列新比赛不反映更正的索引不合格。发现变化立即进入完整抓取、校验与公开流程。
- **完整资料复查**：确认后首日每 15 分钟，第 2–7 天每日一次；未确认超期赛事前 24 小时每 10 分钟，此后每日一次，用于发现完整性或索引遗漏，并保留低频恢复。它不能替代上面的及时发现。
- 来源没有合格轻量发现接口时，必须用满足 60/120 秒间隔的完整请求证明预算可行，或换用有能力的合格来源；无可行路径的地区登记能力缺口，不按 5/10 分钟 SLA 交付。不能为兑现低频方案而默认扩大真实请求量或付费预算。
- 已确认后满 7 天停止主动发现/完整轮询；以后新线索仍启动校验更新，记录来源实际时间与首次发现时间，发现较晚就报告延迟，不把此阶段追溯宣称持续主动监测。未确认赛事不因经过 7 天停止发现/恢复，除非取消证据改变了资料义务；目标退出必须留原因和已有失败。
- 429 遵守 Retry-After；无额度停止请求、标容量缺口，不能突破上限或延长业务 deadline 假装达标。无条件无限重试禁止。

重点预算示例 60s 发现+60s 排队+40s 主/备抓取+30s 解析/提交+30s 公开缓存+30s 探针=250s，余量 50s；常规发现上限 120s，预留余量更多。容量公式按 host 汇总“发现批次/发现间隔 + 变化后完整抓取 + 完整复查 + 失败重试”，包含全部仍在追踪的 7 天赛事和超期未确认存量，至少留 30% 故障/备用余量。备用额度不能仅按当天开赛数估计。无额度/发现接口失效时切合格备源，否则停止请求并登记 discovery gap、计时效失败，不延长 deadline 或排除分母。T08/T09 在一次发现刚结束后发布新版本，跨首日/第 2–7 天/长期未确认阶段验证最坏延迟；真实接口覆盖与速率证据不足不能按合成压测宣称达标。

## 计量与下游

公开探针通过真实公开 URL 读取 epoch、revision、visibility，并关联来源时间证据；DB published_at 不能当用户已看见。结果、更正、隐藏、恢复均留 receipt。单场跨窗口未完成义务在后续窗口继续列为 outstanding，已关闭窗口的 E/L 不回写归零。

复用 R01 strict DTO：在适配层补 scope、版本、coverage evidence，不能改合同来吞掉缺记录。关键资料审计与业务生产分离，使用保留样本/第二证据或人工核查，不用同一个 parser 的输出当自身真值。接口对下游提供 event_id、generation、epoch、previous_epoch、result_revision、status、当次 evidence digest；发布顺序按 epoch，不依赖内容 revision.supersedes 的历史指针。P03/P04/P05 自行幂等消费，本期只验证合同。

## 实施前外部未知

各来源用途与权限、TRA 套餐、真实速率/批量能力、既有生产拓扑、未来真实赛日、CDN 路径与 TTL 仍待核验。它们是进入相应交付阶段的技术检查项，不阻止隔离环境实现；无法证实时该地区保持未交付。所有人工确认只引用根 AGENTS.md。
