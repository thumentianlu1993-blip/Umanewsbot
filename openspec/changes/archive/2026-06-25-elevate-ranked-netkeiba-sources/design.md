## Context

当前抓取入库以 `source_site + source_article_id` 唯一识别文章。文章首次从 `netkeiba:latest` 入库后，后续即使在 `netkeiba:access` 或 `netkeiba:attention` 中出现，也只会新增 `NewsSnapshot`，不会更新文章主来源。自动发布门禁和 QQ 推送高价值判断主要读取 `NewsArticle.source_site/source_mode`，因此榜单命中证据无法稳定驱动后续流程。

## Goals / Non-Goals

**Goals:**

- 让同一文章从新着顺再次被访问量榜或注目数榜命中时，主来源提升为榜单来源。
- 保留 `NewsSnapshot` 作为每次榜单命中的历史证据。
- 保持访问量榜与注目数榜之间不互相覆盖。

**Non-Goals:**

- 不新增数据表或字段。
- 不回填历史文章来源。
- 不改变抓取频率、适配器解析或来源健康 UI。
- 不直接触发 QQ 推送，QQ 资格由后续子 change 处理。

## Decisions

1. 在 `upsert_article_from_draft()` 中处理来源提升。
   - 选择原因：这里已经持有 draft、文章、source_config 和 crawl_job，是重复文章更新的唯一收口。
   - 替代方案：在抓取 task 外层处理。会让 netkeiba 和后续来源扩展重复实现更新规则。

2. 只允许 `latest -> access/attention`。
   - 选择原因：用户明确要求榜单覆盖新着顺，但榜单之间不互相覆盖；这样可避免同一文章随榜单抓取顺序来回变动。
   - 替代方案：用 `NewsSnapshot` 派生高价值，不改主来源。缺点是当前后台、自动化和高价值来源逻辑仍会显示 latest，排查时不直观。

3. 不创建迁移。
   - 选择原因：现有 `source_mode/source_config/source_note/crawl_job` 足以表达当前主来源，`NewsSnapshot` 足以表达历史命中。

4. 来源提升必须返回或暴露可检测信号。
   - 选择原因：已公开文章可能在发布后才被榜单命中；后续 QQ 推送需要知道“本轮 upsert 发生了来源提升”，否则无法可靠触发交付。
   - 可接受实现：让入库结果返回 `source_elevated`，或提供等价的结构化结果对象；不接受只在数据库里静默改字段后让后续逻辑反查猜测。

## Risks / Trade-offs

- [Risk] 提升后会失去主记录上“首次来自新着顺”的直观信息。Mitigation: `is_first_crawled/first_seen_at` 和历史 `NewsSnapshot` 仍保留首次与榜单命中证据。
- [Risk] 文章已发布后来源才提升，自动化状态可能已经完成。Mitigation: 本 change 除了保证来源状态正确，还暴露本轮来源提升信号；后续 QQ 子 change 负责按发布状态和交付记录决定是否发送。
- [Risk] access 与 attention 哪个先提升取决于抓取顺序。Mitigation: 明确二者不互相覆盖，避免后续抖动。

## Migration Plan

1. 本地实现来源提升规则和测试。
2. 部署后等待自然榜单抓取，抽检 `NewsArticle` 与 `NewsSnapshot`。
3. 回滚时还原代码即可；已提升的少量文章可保留，因为这是产品期望状态。

## Open Questions

无。
