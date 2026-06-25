## MODIFIED Requirements

### Requirement: 支持推送范围策略
系统 SHALL 通过配置控制自动 QQ 推送范围。`QQ_PUSH_SCOPE=high_value_only` 时系统只推送重点新闻，并 MUST 通过重点推送策略配置决定“重点新闻”的判定方式；本期唯一支持的重点推送策略为 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，该策略 MUST 将 `source_site=netkeiba` 且 `source_mode` 为 `access` 或 `attention` 的公开文章视为榜单重点新闻。`QQ_PUSH_SCOPE=all_public` 时系统推送所有公开 URL 可访问且不存在 blocker 的已发布新闻。`QQ_PUSH_SCOPE` 未配置或配置非法时，系统 MUST 默认使用 `high_value_only`；`QQ_PUSH_IMPORTANCE_STRATEGY` 未配置或配置非法时，系统 MUST 默认使用 `ranked` 并记录日志。

#### Scenario: 默认只推榜单重点新闻
- **WHEN** `QQ_PUSH_SCOPE` 未配置
- **AND** `QQ_PUSH_IMPORTANCE_STRATEGY` 未配置
- **AND** 一篇已发布文章不是 netkeiba 访问量榜或注目数榜来源
- **THEN** 系统不向 QQ 群发送该文章，并记录或返回跳过原因

#### Scenario: 访问量榜新闻被推送
- **WHEN** `QQ_PUSH_SCOPE=high_value_only`
- **AND** `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`
- **AND** 已发布文章的 `source_site=netkeiba`、`source_mode=access`
- **THEN** 系统在公开 URL 可访问且不存在 blocker 后向启用的 QQ 群推送该文章

#### Scenario: 注目数榜新闻被推送
- **WHEN** `QQ_PUSH_SCOPE=high_value_only`
- **AND** `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`
- **AND** 已发布文章的 `source_site=netkeiba`、`source_mode=attention`
- **THEN** 系统在公开 URL 可访问且不存在 blocker 后向启用的 QQ 群推送该文章

#### Scenario: 新着顺文章不自动推送
- **WHEN** `QQ_PUSH_SCOPE=high_value_only`
- **AND** `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`
- **AND** 公开文章的 `source_site=netkeiba` 且 `source_mode=latest`
- **THEN** 系统 SHALL NOT 自动创建新的 QQ 交付记录

#### Scenario: 所有公开新闻被推送
- **WHEN** `QQ_PUSH_SCOPE=all_public`
- **AND** 文章已发布、公开 URL 可访问且不存在 blocker
- **THEN** 系统不再因文章分数或重点推送策略跳过该文章

#### Scenario: 非法范围配置保守处理
- **WHEN** `QQ_PUSH_SCOPE` 被配置为不支持的值
- **THEN** 系统按 `high_value_only` 处理自动 QQ 推送范围

#### Scenario: 非法重点策略保守处理
- **WHEN** `QQ_PUSH_IMPORTANCE_STRATEGY` 被配置为不支持的值
- **THEN** 系统按 `ranked` 处理重点新闻判定，并记录日志

## ADDED Requirements

### Requirement: QQ 自动推送必须复用发布门禁 blocker 口径
系统 SHALL 仅在文章不存在阻断级发布门禁问题时执行 QQ 自动交付。阻断级问题 MUST 复用现有 `NewsArticle.gate_blockers` 或等价的 `gate_issues` 中 `severity=blocker` 结构化结果；QQ 推送服务 MUST NOT 重新实现一套独立的 blocker 判定规则。

#### Scenario: 未公开文章不推送
- **WHEN** 文章尚未满足 `workflow_status=published` 或 `published_to_web_at` 非空
- **THEN** 系统 SHALL NOT 自动创建新的 QQ 交付记录

#### Scenario: 有 blocker 的文章不推送
- **WHEN** 文章的 `gate_blockers` 非空
- **THEN** 系统 SHALL NOT 自动创建新的 QQ 交付记录

#### Scenario: 公开 URL 不可访问时记录失败
- **WHEN** 文章符合推送范围和重点策略但公开 URL 检查失败
- **THEN** 系统 SHALL 将对应交付记录记录为 URL 不可用相关失败或重试状态

### Requirement: 榜单提升后的已公开文章必须可以进入交付
系统 SHALL 在文章已公开后又被榜单来源提升时，使用来源提升子 change 暴露的稳定信号进入 QQ 自动推送编排，并依靠交付唯一约束避免重复发送。

#### Scenario: 已公开 latest 文章被提升为访问量榜
- **WHEN** 一篇已公开文章原本为 `netkeiba:latest` 且未自动推送
- **AND** 后续抓取将其提升为 `netkeiba:access`
- **AND** 入库结果暴露本轮发生来源提升
- **THEN** 系统 SHALL 允许该文章进入 QQ 自动推送编排

#### Scenario: 已发送文章再次被榜单命中
- **WHEN** 一篇文章对某 QQ 群已有 `sent` 状态的 `QQPushDelivery`
- **AND** 后续再次被访问量榜或注目数榜命中
- **THEN** 系统 SHALL NOT 对同一文章和同一 QQ 群重复自动发送
