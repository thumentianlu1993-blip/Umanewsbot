## Context

当前 `_candidate_queryset()` 只查询 `first_seen_at >= now-3h OR ranked_revived_at >= now-3h`。`mark_publish_ready()` 没有记录进入 `publish_ready` 的时间，因此翻译、门禁或重处理晚于入库 3 小时完成的文章可能从未被任何发布窗口看见；已被配额或竞争推迟的文章也会在 3 小时后无声消失。直接把回看扩大到数天会让每个 15 分钟窗口反复扫描旧稿，并可能突然公开大量过时新闻。

本变更需要把“实时发现时间”和“具备发布资格时间”拆开，同时保持现有硬门禁、地区主配额、去重、每窗口 5 篇和全站小时上限。

## Goals / Non-Goals

**Goals:**

- 确保新进入 `publish_ready` 的文章至少在一个明确自动消费期限内持续可见。
- 对超出自动期限的候选给出人工复核/过期处置，不静默永久堆积。
- 用索引友好、有界的查询支持 SQLite 测试和 PostgreSQL 生产。
- 对当前 21 篇旧候选生成逐篇审核清单，不自动突发发布。

**Non-Goals:**

- 不提高每地区每窗口、地区小时或全站小时配额。
- 不放宽分数、来源 allowlist、硬门禁、重复检测或 QQ 资格。
- 不把所有历史 `publish_ready` 自动回填为当前时间。
- 不在恢复命令内直接公开文章。

## Decisions

### Decision 1: 新增显式 `publish_ready_at` 作为资格时钟 <!-- adr: adr-001-ready-timestamp -->

**Choice：** 为 `NewsArticle` 增加 nullable、indexed `publish_ready_at`。所有从非 ready 状态进入 `AutomationStatus.PUBLISH_READY` 的路径必须原子设置该时间；已处于 ready 的文章重复评分、重复校验或普通保存不得刷新。只有榜单唤醒、人工批准或绑定审核 manifest 的恢复动作可以显式请求刷新。离开 ready 后保留最后一次时间供审计。迁移不为旧候选猜测时间，避免把三周前文章伪装成新稿。

**Alternatives considered：**

- 使用 `updated_at` — 任意编辑、抓取回看或日志更新都会改变，不能代表资格时钟。
- 使用 `first_seen_at` / `ranked_revived_at` — 正是当前漏稿根因，不能表达晚完成门禁。
- 从 `AutomationLog` 每窗口反查 — 查询复杂且易形成 N+1，不采用。

### Decision 2: 实时候选与积压候选使用双通道有界查询 <!-- adr: adr-002-dual-candidate-lane -->

**Choice：** 实时通道保留 3 小时 `first_seen_at/ranked_revived_at` 语义；积压通道只查询 `automation_status=publish_ready`、`publish_ready_at` 在自动期限内、主地区匹配且未公开的文章。每通道有独立扫描上限，合并去重后使用现有门禁、内容指纹、分数与配额选择；同分时优先更早进入 ready 的候选，避免长期饥饿。

**Alternatives considered：**

- 把 lookback 从 3 小时改为 72 小时 — 会扩大所有候选扫描并混淆新鲜度与状态。
- 新增独立消息队列作为发布候选队列 — 增加新状态源和恢复复杂度，现有数据库账本足够。

### Decision 3: 默认采用 24 小时自动、24–72 小时人工、72 小时后过期 <!-- adr: adr-003-age-policy -->

**Choice：** `publish_ready_at <=24h` 可由窗口自动消费；24–72h 不再自动发布，进入后台“过期待复核”视图并触发一次积压告警；>72h 标记为“过期处置候选”，只有显式重新校验/唤醒才能重新进入 ready。发布窗口本身不自动改文章工作流，避免在选择路径产生隐式状态副作用。

**Alternatives considered：**

- 72 小时内全部自动发布 — 赛马新闻时效强，可能公开明显过时内容。
- 3 小时后立即丢弃 — 会延续任务抖动和配额竞争造成的漏稿。
- 永不过期 — 会持续扫描和累积，且恢复时可能突发发布。

### Decision 4: 当前旧候选通过 SHA manifest 逐篇处置 <!-- adr: adr-004-legacy-manifest -->

**Choice：** 管理命令按固定 ID/状态/内容指纹/门禁快照输出 21 篇 manifest，分类为“仍具时效可重新校验”“保留人工发布”“驳回/归档”。apply 仅接受已审核 manifest，逐篇锁行、拒绝漂移，并调用完整校验；通过者设置新的 `publish_ready_at`，但仍等待正常发布窗口。

**Alternatives considered：**

- 一次性把 21 篇 `ranked_revived_at=now` — 会绕过内容时效审核并制造集中发布。
- 全部归档 — 可能丢失仍具长期价值或赛事资料价值的文章。

## Risks / Trade-offs

- [ready 时间被多次刷新导致旧稿常驻] → 默认只在非 ready→ready 转换时设置；榜单唤醒、人工批准或 manifest 恢复必须使用显式 `refresh_ready_at` 意图，普通重复校验不得触碰。
- [双通道重复候选] → 按 article ID 去重并在决策 payload 记录进入通道集合。
- [积压查询影响每 15 分钟窗口] → 组合索引、通道 limit、只取必要字段并设置查询数/耗时门槛。
- [过期阈值不符合运营节奏] → 阈值配置化，但生产变更需记录旧值、新值与影响计数。
- [恢复旧稿发生内容漂移] → manifest 绑定内容、状态、门禁和更新时间指纹，漂移逐篇跳过。

## Migration Plan

1. 增加 `publish_ready_at` 与组合索引；迁移保持历史值为 NULL。
2. 先补旧行为回归：入库超过 3 小时、刚进入 ready 的文章在旧代码中不可见。
3. 实现双通道、年龄策略、后台/审计指标和 manifest 命令；默认关闭积压通道，通过配置灰度。
4. 部署迁移后只读预览最近 24 小时会新增进入窗口的候选，确认查询计划与数量。
5. 开启一个地区，观察 4 个窗口后扩到五地区；确认每窗口/小时配额不变。
6. 当前 21 篇另生成审核 manifest，用户确认后才 apply；异常时关闭积压通道，字段和审计记录可保留。

## Open Questions

- 是否确认默认时效分层为 `0–24h 自动 / 24–72h 人工 / >72h 不自动`？推荐确认。
- 当前 21 篇均已远超 72 小时，是否按“逐篇审核，默认不自动公开”处理？推荐确认。
