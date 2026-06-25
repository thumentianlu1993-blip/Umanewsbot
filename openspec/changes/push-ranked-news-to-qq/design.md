## Context

自动 QQ 推送已经有 `QQPushDelivery` 状态机，支持多群、去重、有限重试、URL 检查、OneBot 业务失败识别和按群限速。生产测试期曾设置 `QQ_PUSH_SCOPE=all_public`，适合验收链路，但不适合作为长期群推策略。用户当前定义的本期重点新闻是 netkeiba 访问量榜和注目数榜命中的新闻；后续还可能出现“榜单 + 比赛日高频”和“按分数推”等策略，因此需要把“是否重点推”和“重点如何判定”拆成两个配置概念。

## Goals / Non-Goals

**Goals:**

- 让 `QQ_PUSH_SCOPE=high_value_only` 通过可配置策略判断重点新闻，本期只实现 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。
- 继续保证文章公开、无 blocker、URL 可访问后才发送。
- 继续复用 `QQPushDelivery` 的幂等、重试和限速。

**Non-Goals:**

- 不新增 OneBot 协议能力或 QQ 群配置模型。
- 不做历史补推。
- 不改变消息模板结构，除 URL 来源由 `article.public_path` 自然承接后续 ID URL。
- 不改变自动发布门禁的评分规则。

## Decisions

1. QQ 推送范围与重点判定策略分层。
   - `QQ_PUSH_SCOPE` 继续表示“推送范围”：`high_value_only` 表示只推重点，`all_public` 表示临时全推公开文章。
   - 新增 `QQ_PUSH_IMPORTANCE_STRATEGY` 表示“重点如何判定”。本期支持值为 `ranked`，含义是 netkeiba 访问量榜 / 注目数榜；未来再扩展 `ranked_with_race_day_burst`、`score_threshold` 等策略。
   - 未配置或非法策略值保守回退到 `ranked` 并记录日志，避免误配置导致刷屏。

2. 本期 `ranked` 策略以榜单来源为核心。
   - 选择原因：这是用户明确的社群分发口径，比单纯分数阈值更可解释。
   - 替代方案：继续用 `score_total`。缺点是可能推送非榜单普通新闻，也可能错过榜单新闻。

3. 推送资格检查读取 `NewsArticle.source_site/source_mode`，已公开文章的补充触发读取来源提升信号。
   - 选择原因：依赖 `elevate-ranked-netkeiba-sources` 后，文章主来源就是当前运营判断所需的事实；对于已经公开的文章，还需要本轮 `source_elevated` 或等价信号来判断是否刚刚变成重点新闻。
   - 替代方案：扫描最近 `NewsSnapshot`。缺点是查询更复杂，也会让后台主来源和推送口径不一致。

4. blocker 判断复用现有结构化门禁。
   - 选择原因：自动发布已经把阻断问题写入 `NewsArticle.gate_issues`，模型属性 `NewsArticle.gate_blockers` 会筛选 `severity=blocker` 的 issue。QQ 推送只消费这个结论，不重新实现正文为空、乱码、重复内容等门禁规则。
   - 替代方案：在 QQ 服务里重复判断各类 blocker。缺点是两套规则容易漂移。

5. 保留 `all_public` 配置。
   - 选择原因：测试链路或临时灰度仍可能需要全量公开推送，但生产默认建议切回 `high_value_only`。

## Risks / Trade-offs

- [Risk] 如果来源提升未部署，榜单文章仍可能因为主来源是 latest 而不推。Mitigation: 将 `elevate-ranked-netkeiba-sources` 作为前置子 change。
- [Risk] 已经公开的文章后续才被榜单提升，可能需要在提升后触发推送。Mitigation: 实现时读取来源提升子 change 暴露的稳定信号，检查发布状态，允许榜单提升后的已公开文章进入自动交付，并依靠唯一交付记录避免重复发送。
- [Risk] blocker 判断与 QQ 服务耦合过深。Mitigation: 只读取 `article.gate_blockers` 或 `gate_issues.severity=blocker` 这类已有结构化门禁结果，不在 QQ 服务里重新实现自动发布门禁。

## Migration Plan

1. 本地实现资格判断与任务触发测试。
2. 部署后将生产 `.env` 从 `QQ_PUSH_SCOPE=all_public` 改为 `QQ_PUSH_SCOPE=high_value_only`，并设置 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，重启 `worker/beat/web`。
3. 观察测试群下一批榜单文章，不做历史补推。
4. 若发送异常，设置 `QQ_PUSH_ENABLED=false` 暂停。
5. 本 change 完成并准备归档前，必须先确保 `add-qqbot-auto-push` 已同步或归档为正式 `qqbot-auto-push` 规格。

## Open Questions

无。
