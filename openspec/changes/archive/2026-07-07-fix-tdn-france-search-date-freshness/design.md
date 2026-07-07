## Context

生产 `NewsSource#21`（`tdn_france_broad`）已因历史旧文事故临时暂停。该来源使用 TDN WordPress search API 按关键词发现法国相关英文新闻，search API 返回的是相关性结果，不保证时间倒序，并且 search item 只包含 `id/title/url` 等轻量字段，没有 `date/date_gmt`。现有 TDN adapter 在缺少日期字段时会兜底为 `timezone.now()`，使 2020/2022/2023/2024 旧文被写成当前时间并进入翻译、自动化、发布和 QQ 流程。

本次修复要先恢复代码安全边界，再清理已公开旧文，最后重新启用来源并验收真实运行态。

## Goals / Non-Goals

**Goals:**

- `tdn_france_broad` 只使用 TDN post API 的真实 `date_gmt/date` 作为发布时间。
- 搜索条目如果无法取得真实 post 日期，必须跳过并记录原因。
- 搜索结果中的历史旧文必须按新鲜度窗口过滤，不能进入文章入库链路。
- 保持 TDN canonical 去重逻辑和法国来源信号，不破坏既有 `tdn` / `tdn_france` 去重。
- 为事故场景补充可重复测试。
- 上线后清理已误发布旧文，并重新启用 `NewsSource#21`。

**Non-Goals:**

- 不新增数据库字段或迁移。
- 不重做 TDN 全部来源架构。
- 不扩大法国法语新闻来源范围。
- 不自动删除所有历史待审核文章；清理范围以本次事故确认的受影响文章为准。

## Decisions

1. **搜索条目二次拉取 post API**

   - 决策：`tdn_france_broad` 对每个 search item 使用 `id` 或 `_links.self` 拉取 `/wp-json/wp/v2/posts/<id>`，从 post JSON 读取 `date_gmt` 或 `date`。
   - 理由：search API 不提供发布时间，详情 HTML 当前也不能稳定补齐真实日期；post API 是同站公开结构化数据，字段更可靠。
   - 替代方案：改用 `wp/v2/posts?search=...&orderby=date`。该方案可以作为优化，但仍需处理关键词相关性和分页，且 post API 按 id 拉取能最小化改动。

2. **无可信日期跳过，不兜底当前时间**

   - 决策：TDN search 发现链路中，缺少可信 post 日期的条目直接跳过，写入 skipped/detail error 统计。
   - 理由：新闻系统的发布时间影响新鲜度、发布窗口和 QQ 推送，错误兜底比少抓一篇风险更高。
   - 替代方案：继续入库但标记人工审核。该方案仍会污染候选池和运营统计，不适合生产常态来源。

3. **按新鲜度窗口过滤历史旧文**

   - 决策：对 `tdn_france_broad` 只接受真实发布时间在允许回看窗口内的文章；窗口值复用或新增轻量常量/配置，默认覆盖正常 15 分钟轮询的网络延迟和上游发布时间偏差，但不接受多年旧文。
   - 理由：TDN 搜索结果会长期返回高相关旧文，仅修正日期还不足以避免旧文被反复候选。
   - 替代方案：只依赖发布窗口 3 小时回看过滤。该过滤发生在入库后，仍会浪费翻译/门禁资源并污染后台。

4. **生产清理采用受控状态回退**

   - 决策：对确认误发布的旧文撤出公开状态，保留原文、译文、日志和可追溯字段；记录清理时间和原因。
   - 理由：这是错误发布，不应继续展示在公开前台；但直接删除会损失排查证据。
   - 替代方案：物理删除文章和推送记录。该方案破坏审计，不采用。

## Risks / Trade-offs

- [Risk] TDN post API 对部分 search id 返回失败或限流。→ Mitigation：单条失败跳过并继续处理后续条目，来源整体只有在所有条目不可用时才失败或无新增。
- [Risk] 新鲜度窗口过窄导致上游延迟发布的真实新闻被跳过。→ Mitigation：窗口设置为小时级宽松值，并只用于宽关键词搜索来源；后续可按运行态调参。
- [Risk] 清理已发布文章后 QQ 群里可能仍有历史消息链接。→ Mitigation：公开页面撤回后链接不再作为正常新闻展示，清理记录写入文档；不尝试撤回 QQ 历史消息。
- [Risk] 重新启用后短期抓不到法国 TDN 新文。→ Mitigation：以“不会再抓旧文”为首要验收，使用只读探测和真实抓取统计确认过滤原因。

## Migration Plan

1. 本地实现 adapter 修复和测试，无数据库迁移。
2. 本地运行针对性测试、`manage.py check`、OpenSpec 严格校验和 `git diff --check`。
3. 部署生产前备份数据库，记录当前 commit 和容器状态。
4. 部署代码并重建容器，确认 `/healthz/`、`manage.py check` 和 worker/beat 正常。
5. 清理已确认误发布旧文，将其撤出公开前台并记录原因。
6. 重新启用 `NewsSource#21`，执行只读探测和一次真实抓取或等待最近窗口验证。
7. 更新 `docs/current_state.md`、`docs/deploy_runbook.md`、`docs/project_status.md`，归档 OpenSpec change。
