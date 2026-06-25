# qqbot-auto-push Specification

## Purpose
为已发布公开新闻提供可灰度、可重试、可审计的 QQ 群自动推送能力。系统通过数据库维护目标群，使用 OneBot v11 HTTP API 发送消息，并以文章和群为粒度记录交付状态，确保推送失败不影响文章发布；生产默认可按重点策略推送 netkeiba 访问量榜 / 注目数榜新闻，也支持临时切换为全公开推送。
## Requirements
### Requirement: 公开文章自动触发 QQ 群推送
系统 SHALL 在文章进入公开已发布状态后自动启动 QQ 群推送编排。自动编排 MUST 只在文章 `workflow_status=PUBLISHED`、存在 `published_to_web_at`，且公开详情页 URL 可访问后发送消息。推送失败或 OneBot 不可用 MUST NOT 阻断文章发布和公开页面访问。

#### Scenario: 人工发布后进入自动推送编排
- **WHEN** 工作人员将文章发布到公开网站，且文章详情页 URL 返回可访问结果
- **THEN** 系统为该文章创建或复用自动 QQ 推送交付记录，并向启用的目标群发送消息

#### Scenario: 自动发布后进入自动推送编排
- **WHEN** 自动化发布任务将高价值文章发布到公开网站，且文章详情页 URL 返回可访问结果
- **THEN** 系统为该文章创建或复用自动 QQ 推送交付记录，并向启用的目标群发送消息

#### Scenario: 公开 URL 暂不可访问
- **WHEN** 文章已经是已发布状态，但公开详情页 URL 检查未返回可访问结果
- **THEN** 系统暂不发送 QQ 消息，并按有限重试规则重新检查

#### Scenario: 推送服务失败不影响发布
- **WHEN** OneBot 网关不可用或发送群消息失败
- **THEN** 文章仍保持公开已发布状态，系统记录交付失败或等待重试

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

### Requirement: 群配置由数据库管理
系统 SHALL 使用数据库中的 QQ 群目标配置决定自动推送目标。自动推送只以 `is_active=True` 作为目标群过滤条件，MUST NOT 使用 `is_default` 过滤自动推送目标；`is_default` 只保留给现有手动推送默认目标语义。只有启用状态的群目标会收到自动推送；工作人员 MUST 能通过 Django Admin 新增、修改、停用和查看群配置。

#### Scenario: 多个启用群收到同一篇新闻
- **WHEN** 数据库中存在多个启用的 QQ 群目标，且文章满足自动推送条件
- **THEN** 系统为每个启用群分别创建交付记录并发送消息

#### Scenario: 停用群不收到自动推送
- **WHEN** 某个 QQ 群目标被标记为停用
- **THEN** 系统不会为该群创建新的自动推送交付记录或发送消息

#### Scenario: 后台维护群配置
- **WHEN** 工作人员打开 Django Admin 的群配置页面
- **THEN** 系统允许维护群名称、群号、默认标记和启用状态

### Requirement: 自动推送交付记录幂等去重
系统 SHALL 以“文章 x QQ 群”为粒度维护自动推送交付记录。系统 MUST 保证同一篇文章不会因重复触发、任务重试或 worker 重启而重复发送到同一个群。交付记录 MUST 保存状态、尝试次数、最大尝试次数、最近错误、OneBot 响应、最后尝试时间和成功发送时间。

#### Scenario: 重复触发复用交付记录
- **WHEN** 同一篇文章的自动推送编排被触发多次
- **THEN** 系统复用同一文章和同一群的交付记录，而不是创建重复交付记录

#### Scenario: 已成功交付不重复发送
- **WHEN** 某篇文章对某个群的交付记录已经成功
- **THEN** 后续自动编排不会再次向该群发送同一篇文章

#### Scenario: 多群交付相互独立
- **WHEN** 同一篇文章发送到多个 QQ 群，其中一个群发送失败
- **THEN** 系统只重试失败群的交付记录，不影响已成功群的状态

### Requirement: 自动推送有限重试
系统 SHALL 对公开 URL 检查失败、OneBot 请求失败和网络超时执行有限次重试。重试次数 MUST 可配置，默认最多 3 次；达到最大次数后，交付记录 MUST 标记为失败并保留最后错误。

#### Scenario: 发送失败后继续重试
- **WHEN** OneBot 发送群消息失败且交付记录未达到最大尝试次数
- **THEN** 系统增加尝试次数、保存错误原因，并安排下一次重试

#### Scenario: URL 检查失败错误类型可区分
- **WHEN** 公开详情页 URL 检查失败
- **THEN** 系统保存最近错误类型为 `url_unavailable`，并保留 URL 检查失败原因

#### Scenario: OneBot 发送失败错误类型可区分
- **WHEN** OneBot 请求失败、超时或返回错误
- **THEN** 系统保存最近错误类型为 `send_failed`，并保留发送失败原因

#### Scenario: 达到最大尝试次数后失败
- **WHEN** 自动推送交付记录已经达到最大尝试次数仍未成功
- **THEN** 系统将该交付记录标记为失败，并停止自动重试

#### Scenario: 后续重试成功
- **WHEN** 前一次发送失败的交付记录在后续重试中发送成功
- **THEN** 系统将该交付记录标记为成功，保存发送时间和 OneBot 响应

### Requirement: 自动推送按目标群限速
系统 SHALL 支持配置同一目标群自动推送发送尝试之间的最小间隔，默认 `QQ_PUSH_MIN_INTERVAL_SECONDS=60`。当未达到最小间隔时，系统 MUST 延后交付任务，且 MUST NOT 增加该交付记录的尝试次数。

#### Scenario: 批量发布时延后后续发送
- **WHEN** 同一目标群刚发生一次自动推送发送尝试，且另一条交付记录在最小间隔内开始执行
- **THEN** 系统延后该交付记录的发送任务，不调用 OneBot，也不增加尝试次数

### Requirement: 自动推送消息使用中文最终稿和站内链接
系统 SHALL 使用面向前台展示的中文最终内容生成 QQ 群消息。消息 MUST 包含 `【UmaFans】` 前缀标题、摘要和 `阅读全文` 站内公开链接。摘要为空时，系统 MUST 从有效正文截断生成摘要，并用 `……` 表示截断。

#### Scenario: 使用已有摘要
- **WHEN** 已发布文章存在有效中文摘要
- **THEN** QQ 群消息使用该摘要，并包含文章公开详情页链接

#### Scenario: 摘要为空时截断正文
- **WHEN** 已发布文章没有有效中文摘要，但存在有效正文
- **THEN** QQ 群消息从正文截断生成摘要，并在截断内容后追加 `……`

#### Scenario: 使用站内公开链接
- **WHEN** 系统生成自动 QQ 推送消息
- **THEN** 消息中的 `阅读全文` 链接指向 `SITE_URL` 与文章 `public_path` 组成的公开详情页 URL

### Requirement: 自动推送可灰度关闭
系统 SHALL 通过 `QQ_PUSH_ENABLED` 控制自动 QQ 推送总开关。关闭时系统 MUST 不发送 OneBot 消息；关闭自动推送 MUST NOT 影响手动推送入口、文章发布、公开页面或自动化内容运营。

#### Scenario: 自动推送关闭
- **WHEN** `QQ_PUSH_ENABLED=false`
- **THEN** 文章发布后系统不执行自动 QQ 群发送

#### Scenario: 自动推送开启
- **WHEN** `QQ_PUSH_ENABLED=true`，且文章满足范围策略、URL 检查和群配置要求
- **THEN** 系统执行自动 QQ 群推送流程

#### Scenario: 手动推送不受自动开关影响
- **WHEN** `QQ_PUSH_ENABLED=false` 且工作人员通过现有后台手动推送入口发送文章
- **THEN** 系统仍按手动推送流程处理该请求

### Requirement: 自动推送状态后台可见
系统 SHALL 在 Django Admin 中提供自动 QQ 推送交付记录的查看能力。工作人员 MUST 能按状态、目标群、文章和时间筛选交付记录，并查看最近错误、尝试次数、成功时间和 OneBot 响应。

#### Scenario: 查看成功交付记录
- **WHEN** 工作人员打开自动推送交付记录后台列表
- **THEN** 系统展示文章、目标群、状态、尝试次数和发送成功时间

#### Scenario: 排查失败交付记录
- **WHEN** 某条自动推送交付记录失败
- **THEN** 工作人员能在后台看到失败状态、最近错误和最后尝试时间

### Requirement: OneBot 同机部署保持安全边界
系统 SHALL 通过 OneBot v11 HTTP API 发送群消息，并在生产配置中避免将 OneBot API 公网裸露。系统 MUST 支持 access token 配置，应用日志 MUST NOT 输出 token。

#### Scenario: 使用 OneBot HTTP API 发送群消息
- **WHEN** 自动推送任务向 QQ 群发送消息
- **THEN** 系统调用配置的 OneBot HTTP `/send_group_msg` 接口，并传入目标群号和文本消息

#### Scenario: OneBot API 不公网裸露
- **WHEN** 生产使用 Docker Compose 同机部署 OneBot 网关
- **THEN** Compose 示例和运维文档要求通过 Docker 内网或 `127.0.0.1` 访问 OneBot API，而不是开放公网端口

#### Scenario: Token 不进入日志
- **WHEN** OneBot 请求失败并记录错误
- **THEN** 系统记录状态码、错误摘要或响应内容，但不记录 `ONEBOT_ACCESS_TOKEN`

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
