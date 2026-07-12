## Context

法国生产源 `#13/#14/#21` 当前均以 15 分钟有效间隔运行，但运行态证明链路存在四类独立问题：TDN France 使用按相关度排序的 `/wp/v2/search`，每轮过滤固定历史结果却漏掉新稿；France Galop 列表以抓取时间代替官方发布时间，重复抓取会覆盖 `published_at`；两篇最新稿因供应商 `429/503` 停在 `translation_failed` 且没有周期重试；全球 TDN 新稿仍因旧归属写入配置关闭而沿用美国来源地区。此前 `support-multiregion-news-attribution-and-english-gates` 已提供主地区、相关地区、人工锁定和重算命令，但生产 dry-run 出现跨地区误判和三四地区过度扩散，因此旧归属写入与查询配置保持关闭。

本 change 需要同时调整来源适配、时间证据、翻译任务、归属推断、窗口查询、运营观测和生产灰度。用户已确认法国只接受英文来源，但赛事、育马、拍卖、马场和机构新闻均可进入新闻池；同一新闻可同时属于法国和其他实际涉及地区。

## Goals / Non-Goals

**Goals:**

- 可靠发现 TDN 最近 3 天法国相关英文稿，不再让相关度历史结果占满候选页。
- 保存 France Galop 官方发布时间及证据，阻止 fallback 时间污染已有文章。
- 自动恢复短暂限流或供应商繁忙造成的翻译失败，并让最终失败可感知、可快速重试。
- 让自动归属基于文章中心事件和可信实体，而不是来源、普通地名或任意弱命中。
- 用可重复的五地区基准集和指标决定是否允许开启多地区生产开关。
- 以单文章、单次公开、单次 QQ 交付为前提，让相关地区页面和群看到同一篇跨地区新闻。
- 提供近期数据修复、灰度启用、验收和一键回滚路径。

**Non-Goals:**

- 不接入法语翻译链路或法语新闻源。
- 不重建通用机器学习 NER/分类平台，不新增外部向量数据库或第三方归属服务。
- 不复制 `NewsArticle` 以表达多个地区，不改变公开文章 URL。
- 不放宽 TDN 3 天新鲜度门禁，不通过扩大抓取频率绕过来源限制。
- 不在本 change 中自动发布结构化赛果数据库记录，也不改变现有地区发布上限和 QQ 总量限制。

## Decisions

### Decision 1: TDN 使用 posts 搜索并在服务端限定时间 <!-- adr: adr-001-tdn-date-search -->

**Choice：** TDN France 两个 adapter 改用 `/wp-json/wp/v2/posts`，为每个审核过的查询传递 `search`、`orderby=date`、`order=desc`、`after=<UTC cutoff>`、`per_page` 和有限 `_fields`。posts 响应直接包含 `date_gmt`，不再逐篇补请求；多查询结果按 canonical URL/source ID 去重，并按真实发布时间倒序截断。3 天门禁仍在 adapter 端二次校验。

**Why：** 同时解决相关度历史结果占满候选页和 N+1 日期请求，并保留本地 fail-closed 新鲜度保护。

**Alternatives considered：**

- 继续 `/search` 并翻页 — 请求更多，仍不能保证最新优先。
- 抓取 TDN 全量最新流后本地全文过滤 — 15 分钟轮询下带宽和解析成本更高，且易受每页上限影响。

### Decision 2: 为关键运行状态新增结构化字段 <!-- adr: adr-002-structured-state -->

**Choice：** `NewsArticle` 新增 nullable `published_at_verified`、`published_at_evidence` JSON；新增 `translation_error_category`、带索引的 `translation_next_retry_at`、`translation_retry_exhausted_at`；新增带索引的 `attribution_status`、`attribution_confidence` 和 `attribution_rule_version`。历史行的 `published_at_verified=NULL` 表示 legacy unknown，不触发全站阻断；新 adapter 明确写 `true/false`，只有 `false` 阻断自动发布。迁移只加 nullable/default-safe 字段，不在 schema migration 中联网或回填。

France Galop 使用 `ZoneInfo("Europe/Paris")` 解析页面当地时间并保存原文；TDN 使用 UTC `date_gmt`。`upsert_article_from_draft()` 仅允许 verified 时间覆盖，fallback 可创建新行但重复抓取只更新 `last_seen_at`。时间修复通过独立受控命令完成。

**Why：** 这些字段需要后台筛选、Beat 到期查询、索引和 PostgreSQL/SQLite 一致行为，不适合仅放在通用 JSON；证据细节仍保留 JSON，避免字段爆炸。

**Alternatives considered：**

- 全部放入 `translation_metadata/attribution_summary` — JSON 查询与索引在 PostgreSQL/SQLite 行为不同，也混淆领域边界。
- 把 legacy 行默认设为未验证 — 会意外阻断全部历史来源和重处理文章。

### Decision 3: 翻译重试使用条件更新 claim 和 stale recovery <!-- adr: adr-003-translation-retry -->

**Choice：** 把翻译异常规范为 `transient_rate_limited`、`transient_provider_unavailable`、`transient_timeout`、`permanent_payload`、`permanent_auth` 和 `unknown`。前三类默认最多 3 次，退避 60/300/900 秒并加入抖动，`Retry-After` 优先。新增 `TRANSLATION_AUTO_RETRY_ENABLED=false` 安全开关、每分钟 Beat selector 和每轮上限。

selector 只派发到期 ID；worker 使用带预期状态/到期时间的单条条件 `UPDATE` 把文章原子 claim 为 `TRANSLATING`，更新行数为 0 即幂等跳过。派发失败不会提前 claim。`translation_started_at` 超过配置阈值的 translating 行可被恢复为 transient stale failure；永久、unknown 和耗尽记录不自动循环。现有 `TranslationRun` 与 `TaskExecutionLog` 继续保存每次执行。

**Why：** 条件更新同时适用于 PostgreSQL 与 SQLite 测试，不依赖 `skip_locked`；stale recovery 避免 worker 崩溃后文章永久卡在 translating。

**Alternatives considered：**

- selector 先加行锁并标记 translating 再派发 — broker 派发失败会留下假执行状态。
- 直接使用 Celery `autoretry_for` — 难以支持后台筛选、人工重试、全局批次限流和跨重启持久状态。

### Decision 4: 归属采用单一 off/shadow/enforce 模式 <!-- adr: adr-004-attribution-mode -->

**Choice：** 新增 `MULTIREGION_ATTRIBUTION_MODE=off|shadow|enforce`，默认 `off`。环境变量未配置时兼容读取旧 `MULTIREGION_ATTRIBUTION_ENABLED`：旧值 true 映射 enforce，false 映射 off；新变量存在时优先。`off` 不推断，`shadow` 计算并写审计字段但不改主地区或关联表，`enforce` 才写归属。`attribution_summary` 新写入使用 `applied` 与 `shadow` 命名空间；shadow 只能更新 `shadow`，不得覆盖既有 `applied`，旧的扁平 summary 读取时视为 applied legacy。`MULTIREGION_RELATED_REGION_QUERIES_ENABLED` 仅在 mode=enforce 时生效。

**Why：** 当前布尔开关无法表达真实 shadow；单一模式防止 web/worker/beat 组合出相互矛盾的行为，旧变量映射保证生产升级安全。

**Alternatives considered：**

- 增加第二个 shadow 布尔开关 — 会产生多个非法组合且难以审计。
- shadow 完全不写任何内容 — 无法持续观察自然流入文章结果，只能依赖一次性命令。

### Decision 5: 归属采用“文章中心事件 + 分层证据”，不按命中数量投票 <!-- adr: adr-005-evidence-hierarchy -->

归属证据分为：

1. `event_location`：明确赛事、赛场及其举办地区；仅当文章以该赛事为中心时可决定主地区。
2. `subject_origin`：核心马匹、骑师、练马师、马主、育马场、拍卖机构和赛马机构的所属地区。
3. `context_region`：标题/导语中的明确国家或地区上下文，只能佐证，不能单独压过赛事证据。
4. `source_fallback`：来源默认地区，仅在没有可信内容证据或证据冲突时使用。

标题和导语证据权重大于正文背景提及；来源 URL、来源备注、普通词术语和仅出现在历史履历/血统背景中的地名不参与主地区判定。地区选择不是“命中最多者胜出”：海外赛事报道以赛事地区为主，核心对象原属地为相关地区；法国机构、法国育马或 Arqana 拍卖为文章主题且没有更强赛事中心时，法国可作为主地区。

**Alternatives considered：**

- 按地区命中数量投票 — 长正文背景提及会压过标题中的中心赛事。
- 始终按新闻源地区 — 无法让全球 TDN 中的法国稿进入法国池。

### Decision 6: 冲突和过度扩散先转复核，不自动猜测 <!-- adr: adr-006-fail-closed -->

推断输出包含主地区、相关地区、每项正反证据、规则版本、置信度 `high|medium|low` 和状态 `applied|fallback|needs_review`。以下情况进入 `needs_review`，保留当前主地区且不扩大相关地区：多个互斥赛事中心、只有弱上下文、候选相关地区超过 3 个、主地区将离开来源地区但缺少强赛事/主题证据、或新旧规则结果发生低置信度变化。

人工锁定继续拥有最高优先级。多地区只写一篇文章；相关地区用于可见性和审计，发布/小时/日配额只消耗主地区。相比硬性最多两个地区，`needs_review` 可保留真实三地区新闻，同时阻止弱命中扩散。

**Alternatives considered：**

- 自动截断到前两个地区 — 会静默丢掉真实三地区新闻且无法解释。
- 对所有弱命中都保存相关地区 — 会重现生产 dry-run 的三四地区扩散。

### Decision 7: gold set 标签与运行账本必须可复现 <!-- adr: adr-007-quality-ledger -->

**Choice：** 仓库保存版本化 gold labels，记录 article ID、source URL、输入快照 SHA-256、期望主/相关地区、审核人角色和理由；不复制完整版权正文。CI 使用覆盖相同规则分支的小型脱敏文本 fixture，生产质量门禁在数据库快照与 SHA 匹配时运行真实 gold set。至少两次独立标注不一致的样本先 adjudicate，未决样本不计入门槛分母。

新增持久化 `MultiregionAttributionRun`，保存 mode、selectors、规则/术语/gold 版本、候选指纹、metrics、outcomes、manifest SHA、cursor、已完成 ID、状态和错误；新增结构相同但外键指向该 run 的 `MultiregionAttributionLock`，提供 30 分钟可续租 lease。不能复用 `TermGateReprocessLock`，因为其 `locked_by_run` 外键只接受术语门禁 run。commit 只能引用成功 dry-run ID 和 manifest，逐行校验文章/人工锁定/规则/术语/gold 漂移，并在单篇事务中写归属。中途失败保存 cursor 和逐篇 outcome，使用同一 run/manifest resume；已完成 ID 不重写。相同 manifest 的重复 commit 幂等。运行 artifact 是账本导出，不是唯一真相。

**Why：** 真实样本不能只靠易漂移的文章 ID，也不能把完整第三方正文提交进仓库；持久 run/manifest 可支撑高风险 commit 审计和断点恢复。

**Alternatives considered：**

- 只保存 runtime JSON — 可被覆盖且无法可靠绑定 commit。
- 在仓库保存 250 篇完整正文 — 体积、版权和持续更新成本不合适。

### Decision 8: 用版本化 gold set 与阈值决定生产资格 <!-- adr: adr-008-quality-thresholds -->

仓库保存脱敏/可复现的标注 fixture，至少 250 篇：五地区各不少于 40 篇，跨地区样本不少于 50 篇，并包含赛事、海外远征、育马、拍卖、机构、普通地名和来源 fallback 反例。每条记录保存期望主地区、相关地区、允许 fallback 与判定说明。

启用门槛：总体主地区准确率不低于 95%，单地区不低于 90%；相关地区 precision 不低于 95%、recall 不低于 90%；无依据改变主地区比例不高于 2%；自动产生超过两个相关地区的过度扩散率不高于 1%；人工锁定覆盖为 0。生产近期 dry-run 还必须人工抽检全部 `needs_review` 和所有主地区变化。

这些阈值优先保证错误地区少于漏掉少量相关地区，因为错误地区会影响网页频道、发布配额和 QQ 群。阈值与报告格式配置化，但降低生产门槛必须形成新决策记录。

只有 adjudicated 且输入 SHA 匹配的样本进入分母；报告必须同时输出有效分母、缺失/漂移样本和 Wilson 置信区间，缺失或漂移导致任一地区有效样本少于 40 时直接 no-go。

**Alternatives considered：**

- 只看总体准确率 — 会掩盖单一地区系统性错配。
- 只做人工抽查不设阈值 — 无法重复判断规则版本是否退化。

### Decision 9: 批量归属必须复用预加载上下文 <!-- adr: adr-009-batch-performance -->

**Choice：** 从现有 `_term_regions()` 的逐文章 ORM 查询改为可复用 `AttributionBatchContext`，一次预加载活跃地区术语、aliases 和赛事证据，并按语言/首 token 建索引；gold set、72 小时 dry-run 和 commit 复用同一快照。250 篇 PostgreSQL 基准目标为不超过 30 条 SQL、30 秒、256 MiB RSS 增量；超标即 no-go。自然单篇流程可构造单元素 context，不引入常驻跨进程缓存。

**Why：** 当前实现会为每篇文章扫描/查询全量地区术语，250 篇评估会产生 N+1 和高 CPU；请求内批量 context 与既有 term-gate 重处理模式一致且不会有缓存失效风险。

**Alternatives considered：**

- 全局进程缓存术语 — 多 worker 更新失效难以保证。
- 保持逐文章查询 — 无法满足生产 dry-run 与 gold set 的可预测性能。

### Decision 10: 分阶段启用写入、展示和 QQ <!-- adr: adr-010-staged-rollout -->

单一 attribution mode 控制计算/写入，独立 related-region query 开关控制展示与路由。上线顺序：代码部署且 mode=off、查询关闭；shadow 计算不写地区；gold set 与生产 dry-run 通过；enforce 只处理新文章但相关查询关闭；观察至少 24 小时；为网页和测试 QQ 群开启相关地区查询；近期 72 小时 manifest 回填；最后扩大正式群。每一步保存窗口指标和样本，失败可退回前一步。

常驻 mode 切到 `enforce` 前，最新成功 run 必须与当前规则/术语/gold 版本一致且不超过 24 小时；运行手册和后台显示该资格，但应用不在请求路径每次查询 run 表，避免可用性耦合。生产变更仍由显式 `.env` 操作完成。

**Alternatives considered：**

- 一次性开启写入、网页和 QQ — 错配会同时影响配额与外发，回滚面过大。
- 请求路径强制查询最新合格 run — 数据库或时钟异常会让正常页面不可用。

## Risks / Trade-offs

- [宽关键词把只在背景中提到法国的全球稿纳入法国池] → 使用中心事件/主题证据、标题导语权重和 `needs_review`，并以相关地区 precision 作为硬门槛。
- [France Galop 页面日期格式变化] → 多格式解析、保存原始证据；解析失败时允许入库但标记时间不可信，禁止自动发布并告警。
- [翻译供应商持续繁忙导致重试风暴] → 全局每轮上限、指数退避、抖动、`Retry-After`、同文章幂等和耗尽终态。
- [多地区开启后同文重复发布或重复 QQ] → 继续以 article/delivery 唯一身份去重，相关地区只增加可见性，不创建副本或额外配额消费。
- [gold set 与真实分布漂移] → 固定回归集外，每次上线追加近期生产变化样本；规则版本升级必须重跑全套指标。
- [历史错误时间修复改变排序] → 只在 manifest 锁定小批中修复，输出 before/after，已发布文章不自动重新发布或补推。
- [规则保守导致部分跨地区稿仍只在来源地区] → 先保证 precision；通过运营待复核入口和后续实体库完善逐步提高 recall。

## Failure Modes

| 新路径 | 现实失败 | 处理与回滚 | 可见信号 | 测试 |
| --- | --- | --- | --- | --- |
| TDN 日期查询 | 单个查询 `429/5xx` 或返回非列表 | 保留其他查询结果；全部失败才标来源失败 | CrawlJob/来源摘要列出 query error | adapter 部分/全部失败测试 |
| France Galop 时间 | 页面格式或夏令时变化导致解析失败 | 写 unverified、阻断自动发布，不覆盖旧时间 | `published_at_unverified` 与文章入口 | 多格式/DST/缺失测试 |
| 翻译自动重试 | provider 持续繁忙或 worker 在 claim 后退出 | 有限退避、耗尽终态、stale translating 恢复 | 后台、TaskExecutionLog、去重通知 | 退避/耗尽/stale/并发测试 |
| shadow 归属 | 推断服务异常或批量超时 | 不改地区；run 标 failed，可关闭 mode | run 错误、窗口 no-go | mode/失败持久化测试 |
| attribution commit | 文章、术语、gold 或人工锁定发生漂移 | 逐篇拒绝并保持旧归属；可续租 lease 防同类并发 | run outcome 列出 drift/locked | manifest/lease/幂等测试 |
| 相关地区展示 | join 造成重复分页或 QQ 双命中 | queryset distinct/稳定排序与 delivery 唯一身份 | 窗口重复计数、QQ delivery | 页面/API/QQ 去重测试 |
| 质量基准 | gold 输入缺失、SHA 漂移或标签未裁决 | 从分母剔除并在地区样本不足时 no-go | 指标报告列出 invalid samples | 分母/漂移/adjudication 测试 |

## Migration Plan

1. 新增 nullable/default-safe 文章字段、`MultiregionAttributionRun/Lock` 和索引；迁移不联网、不回填，先在生产规模快照验证锁时长。
2. 部署 adapter、时间证据、翻译恢复、归属规则和审计命令，保持 attribution mode=off、相关查询关闭、翻译自动重试关闭；执行数据库和 `.env` 备份。
3. 部署前先通过本地日期 fixture、脱敏规则 fixture 和 gold label 结构检查；部署后运行 TDN/France Galop 只读 probe、真实 gold set 和最近 72 小时生产 dry-run，未达阈值则停止。
4. 对 `7871/7699` 等瞬时失败稿执行受控翻译重试；对 France Galop 错误时间生成 manifest，抽检后 commit，不触发直接发布。
5. 开启 attribution shadow；通过后仅对新文章启用归属写入，相关地区页面/QQ 查询仍关闭，观察至少 24 小时。
6. 先向网页和测试群开启相关地区查询，验证单文章、配额、窗口原因和 QQ 去重；再回填最近 72 小时。
7. 验收法国日常候选、翻译、发布数量及五地区错配指标，达标后扩大正式群并更新状态、决策和 runbook。
8. 回滚时先关闭相关地区查询，再关闭归属写入；停用有问题的法国来源或翻译重试调度。保留审计数据，必要时按回填 manifest 恢复旧主地区/相关地区；无需回滚文章表或删除公开记录。

## Open Questions

- 无阻断性产品问题。实现阶段需用真实 gold set 分布确认 250 篇样本是否足够覆盖五地区长尾；若不足，只能增加样本，不能降低既定准确率门槛。
