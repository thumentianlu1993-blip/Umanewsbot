## Context

香港两个来源在 61 小时内各运行约 180 次且状态成功，但没有新入库；这可能是上游确实无稿、列表只含旧稿、详情/日期解析漏抓、canonical 去重或来源覆盖不足。法国、英国和美国同时存在“入库后翻译/门禁损失”，因此扩源前必须把供给问题与下游问题分开。本变更排在索引、候选消费、英文门禁和翻译恢复之后，避免把下游阻塞误判为来源不足。

现有 `NewsSource`、国际 adapters、只读 probe、`CrawlJob`、`ProductionWindow` 和多地区审计可复用。需要补的是结构化逐来源漏斗与统一准入证据，而不是另建抓取系统。

## Goals / Non-Goals

**Goals:**

- 解释每个低产来源在哪一层损失：listing、详情、时效、重复、入库或下游。
- 修复已验证的适配器漏抓，并为确有覆盖缺口的地区接入合格候选来源。
- 新来源按“只读探测与 fixture 回归 → 关闭态同步 → 每地区最多 2 个并行直接生产启用 → 在线观察与逐源熔断”推进。
- 建立可观测的地区供给目标和 no-go 结论。

**Non-Goals:**

- 不为追求数量降低翻译、术语、重复、来源许可或公开硬门禁。
- 不接入法语正文；法国仍只接受英文来源。
- 不启用未通过自动化准入和 fixture 回归的来源，不启用新赛马地区。
- 不把赛事数据库 importer 当新闻来源。

## Decisions

### Decision 1: 先建立逐来源全漏斗再决定扩源 <!-- adr: adr-001-source-funnel-first -->

**Choice：** 每次抓取记录 listing_seen、detail_attempted/succeeded/failed、stale_skipped、non_racing_skipped、duplicate_seen、created、translation_started/succeeded/failed、gate_blocked、publish_ready 和 public。抓取阶段结构化字段优先写入 `CrawlJob.result_payload`（最小 JSONField 迁移），发布后指标由有限窗口聚合，不把不同阶段全部冗余写入 job。

**Alternatives considered：**

- 继续从 `success_count/fail_count/error_message` 推断 — 当前 `fail_count` 还被用于重复计数，无法稳定区分损失层。
- 新建时序统计服务 — 超出单机阶段，现有数据库有限窗口足够。

### Decision 2: 现有适配器修复优先于新增来源 <!-- adr: adr-002-repair-before-expand -->

**Choice：** 对香港、法国现有来源保存只读 listing/详情样本，逐项核对发布日期、链接提取、分页、赛马过滤、canonical ID 和重复判定。若 upstream 近 7 天存在合格文章而 adapter 未产出，先修 parser；只有来源真实供给仍低于目标才进入候选来源准入。

**Alternatives considered：**

- 立即增加多个来源 — 会扩大维护、去重和许可风险，也掩盖现有 adapter 缺陷。
- 单凭页面人工浏览判断 — 无法形成可复跑的解析与时效证据。

### Decision 3: 候选来源使用统一准入矩阵 <!-- adr: adr-003-source-admission -->

**Choice：** probe 必须证明 HTTP/访问策略可接受、近 7 天至少 3 篇赛马正文样本、真实发布时间、正文完整、语言受支持、canonical ID 稳定、重复率可解释、来源许可/归属可记录。结果为 accepted/deferred/blocked；没有 accepted 候选时明确 no-go，不为了完成变更启用不合格来源。

**Alternatives considered：**

- 以 HTTP 200 作为准入 — 可能是反机器人页、空壳或无正文。
- 以 RSS/列表有条目作为准入 — 不证明详情、日期和正文可用。

### Decision 4: 每地区有界并行直接生产启用 <!-- adr: adr-004-bounded-parallel-rollout -->

**Choice：** 同步定义时保持 `enabled=false/production_approved=false`；只读 probe、最小脱敏 fixture 和自动化准入通过后，执行阶段允许每地区初始最多 2 个 accepted 来源同时设置 `enabled=true/production_approved=true`，直接进入现有生产窗口，不设置 shadow。所有文章继续经过现有翻译、门禁、去重、配额和发布策略；每个来源独立记录漏斗、耗时和错误，触发日期/正文/非赛马严重错误、容器重启、队列持续增长或健康检查异常时只停用问题来源并停止继续扩大。并发上限只能依据生产 CPU、内存、队列和窗口耗时证据上调。

**Alternatives considered：**

- 72 小时 shadow 后逐源启用 — 风险更低，但用户在 `2026-07-22` 明确选择提高测试速度并直接观察生产表现，不采用。
- 一次启用所有 accepted 来源 — 出现容量或质量问题时难以止损；保留每地区初始上限 2 和逐源熔断。

### Decision 5: 以供给 SLO 和公开 SLO 分层验收 <!-- adr: adr-005-regional-slo -->

**Choice：** 初始建议 7 天供给目标为香港入库 ≥7、法国 ≥21、英国 ≥56、美国 ≥140；公开观察目标为香港 ≥3、法国 ≥7、英国 ≥14、美国 ≥35。供给未达先查来源；供给达标但公开未达转交翻译/门禁/发布变更，不在本变更降标准。日本保持当前基线，仅作为对照。

**Alternatives considered：**

- 只看任务成功率 — 香港现状已证明成功不等于产出。
- 只设公开目标 — 会混淆来源与下游问题。
- 把目标作为自动发布硬配额 — 可能诱导低质量补量，不采用。

## Risks / Trade-offs

- [只读 probe 也触发上游风控] → 单来源有限样本、超时、请求预算和现有 SSRF/TLS 边界；地区内并行不等于对同一站点并发轰炸。
- [新增来源带来重复稿] → canonical URL/source ID、跨源指纹、现有重复门禁和生产首窗口漏斗监控。
- [页面结构短期通过后漂移] → fixture + parser 回归、结构化 detail failure 和单来源快速停用。
- [直接生产上线影响内容质量或产品性能] → 每地区初始最多 2 个、沿用全部发布门禁与配额、观测容器/队列/窗口耗时；任一异常逐源熔断并停止扩大。历史上法国 TDN 日期解析曾导致 5 篇旧文误发布，因此“无影响”必须由上线数据验证，不能作为预设事实。
- [留存 fixture 泄露账号信息或保存过量受版权保护内容] → 仅保存最小、脱敏、可复现片段和必要响应字段，不保存 Cookie、token、账号信息或整站内容。
- [SLO 高于上游自然供给] → SLO 是告警/复盘目标，不是发布硬门槛；允许证据充分的 no-go 和用户调整目标。
- [CrawlJob JSON 增长] → 只保存计数、稳定原因码和首个有界样本，不保存原始正文/HTML。

## Migration Plan

1. 在前四个问题修复并稳定后，新增有界 `CrawlJob.result_payload` 和逐来源漏斗审计，先不改来源。
2. 保存香港/法国现有来源的只读样本并执行 parser/date/canonical 对照；有漏抓先修复并跑 fixture 回归。
3. 若供给仍不足，按矩阵为香港、法国各准备候选来源；英国、美国只在各自 SLO 未达时推进。
4. accepted 来源以关闭态同步；执行阶段按每地区初始最多 2 个直接设置 `enabled=true/production_approved=true`，进入现有生产窗口并沿用全部质量门禁与配额。
5. 观察首 4 个窗口和 24 小时 CPU、内存、队列、抓取耗时、日期、重复、翻译、门禁与公开漏斗；问题来源立即单独停用，生产证据不支持时不得提高并发上限。
6. 异常时停用具体来源/取消 production approval；模型字段和历史漏斗可保留。

## Open Questions

- `2026-07-22` 已确认建议的 7 天供给/公开观察目标。
- `2026-07-22` 已确认取消 shadow，允许每地区并行直接生产测试多个来源；实现初始上限取 2，后续只按生产容量证据上调。
- 没有通过准入的候选来源时继续输出 no-go，不接入 blocked/deferred 来源。
