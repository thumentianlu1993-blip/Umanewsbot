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
系统 SHALL 通过 QQ 自动推送总开关和目标群配置共同控制自动 QQ 推送范围。`QQ_PUSH_ENABLED` 仍作为全局总开关，只决定自动推送是否运行；具体某篇文章要不要推送给某个 QQ 群，MUST 以该 `PushTarget` 的允许地区、推送范围和重点策略为准。全局 `QQ_PUSH_SCOPE` 与 `QQ_PUSH_IMPORTANCE_STRATEGY` MAY 作为迁移默认值或兼容回退值，但当目标群存在群级配置时，系统 MUST 使用群级配置判定该群的推送资格。文章地区缺失时，系统 MUST NOT 自动推送，并应记录 `region_missing` 或等价跳过原因。

#### Scenario: 总开关关闭时不推送
- **WHEN** `QQ_PUSH_ENABLED=false`
- **THEN** 系统 SHALL NOT 为任何目标群执行自动 QQ 群发送

#### Scenario: 群级配置决定推送内容
- **WHEN** `QQ_PUSH_ENABLED=true`
- **AND** 目标群配置允许中国香港地区并设置 `push_scope=all_public`
- **AND** 一篇中国香港地区文章已发布、公开 URL 可访问且不存在 blocker
- **THEN** 系统 SHALL 允许该文章进入该群的自动推送交付

#### Scenario: 群级重点策略决定重点新闻
- **WHEN** `QQ_PUSH_ENABLED=true`
- **AND** 目标群配置 `push_scope=high_value_only`、`importance_strategy=ranked`
- **THEN** 系统 SHALL 使用该群的重点策略判断文章是否为该群可推送的重点新闻

#### Scenario: 群级配置覆盖全局配置
- **WHEN** 全局 `QQ_PUSH_SCOPE=all_public`
- **AND** 某目标群配置 `push_scope=high_value_only`
- **THEN** 系统 SHALL 按该目标群的 `high_value_only` 范围判定该群推送资格

#### Scenario: 缺少文章地区时不自动推送
- **WHEN** 一篇公开文章缺少地区字段或地区值非法
- **THEN** 系统 SHALL NOT 向任何 QQ 群自动发送该文章，并记录 `region_missing` 或等价跳过原因

#### Scenario: 群级配置缺失时使用兼容默认
- **WHEN** 某目标群尚未显式配置推送范围或重点策略
- **THEN** 系统 SHALL 使用迁移生成的兼容默认值或全局配置回退值，并在后台展示最终生效配置

#### Scenario: 空允许地区保持旧日本推送行为
- **WHEN** 既有目标群迁移后仍缺少显式允许地区，或运行时遇到空 `allowed_regions`
- **THEN** 系统 SHALL 将该目标群的允许地区按兼容默认解释为仅日本地区
- **AND** 系统 SHALL NOT 因空地区配置向该群发送中国香港、英国、法国或美国新闻

### Requirement: 群配置由数据库管理
系统 SHALL 使用数据库中的 QQ 群目标配置决定自动推送目标。自动推送只以 `is_active=True` 作为目标群基础过滤条件，MUST NOT 使用 `is_default` 过滤自动推送目标；`is_default` 只保留给现有手动推送默认目标语义。每个启用群目标 MUST 能配置允许地区、推送范围和重点策略；系统 MUST 允许不同 QQ 群接收不同地区或不同范围的新闻。工作人员 MUST 能通过 Django Admin 新增、修改、停用和查看群配置。

#### Scenario: 多个启用群收到同一篇新闻
- **WHEN** 数据库中存在多个启用的 QQ 群目标，且文章满足这些群各自的自动推送条件
- **THEN** 系统为每个符合条件的启用群分别创建交付记录并发送消息

#### Scenario: 停用群不收到自动推送
- **WHEN** 某个 QQ 群目标被标记为停用
- **THEN** 系统不会为该群创建新的自动推送交付记录或发送消息

#### Scenario: 后台维护群配置
- **WHEN** 工作人员打开 Django Admin 的群配置页面
- **THEN** 系统允许维护群名称、群号、默认标记、启用状态、允许地区、推送范围和重点策略

#### Scenario: 不同群可以订阅不同地区
- **WHEN** 群 A 配置为允许日本和中国香港，群 B 配置为只允许英国和美国
- **AND** 一篇已发布文章属于中国香港地区
- **THEN** 系统 SHALL 只为群 A 创建或处理自动推送交付记录，不为群 B 创建新的交付记录

#### Scenario: 现有群迁移保持旧行为
- **WHEN** 系统从旧的全局 QQ 推送配置迁移到群级配置
- **THEN** 既有 `PushTarget` SHALL 获得与迁移前等价的推送范围和重点策略默认值
- **AND** 既有 `PushTarget.allowed_regions` SHALL 回填为日本地区或按空值兼容为日本地区，避免部署后突然接收全球新闻

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

### Requirement: 多地区常态推送必须继续按群级地区灰度
系统 SHALL 在多地区新闻常态生产后继续以 `PushTarget.allowed_regions` 决定每个 QQ 群可接收的地区。旧群、空地区配置或非法地区配置 MUST 继续按日本兼容处理，除非工作人员显式允许更多地区。

#### Scenario: 旧群不接收新地区
- **WHEN** 某 QQ 群 `allowed_regions` 为空或非法
- **AND** 一篇中国香港、英国、法国或美国文章公开发布
- **THEN** 系统 SHALL NOT 向该群自动发送该文章

#### Scenario: 测试群接收显式允许地区
- **WHEN** 测试 QQ 群显式允许中国香港和英国
- **AND** 对应地区文章满足推送范围和公开 URL 检查
- **THEN** 系统 SHALL 允许该测试群接收对应地区文章

#### Scenario: 正式群扩大地区必须显式配置
- **WHEN** 工作人员希望正式 QQ 群接收英国、法国、美国或中国香港新闻
- **THEN** 系统 SHALL 要求该群目标显式包含对应 `allowed_regions`

### Requirement: QQ 自动推送消息必须标识新闻地区
系统 SHALL 在多地区新闻自动推送消息中展示可读地区信息，使群用户能区分日本、中国香港、英国、法国和美国新闻。

#### Scenario: 国际新闻消息包含地区
- **WHEN** 系统生成中国香港、英国、法国或美国新闻的 QQ 自动推送消息
- **THEN** 消息 SHALL 包含该文章的可读地区标签

#### Scenario: 日本新闻保持清晰来源
- **WHEN** 系统生成日本新闻的 QQ 自动推送消息
- **THEN** 消息 SHALL 继续包含 `【UmaFans】` 前缀和站内链接
- **AND** MAY 包含日本地区标签但不得破坏既有消息结构

### Requirement: 多地区推送验收必须覆盖跳过原因
系统 SHALL 在灰度启用某地区 QQ 推送前后验证交付创建、发送、跳过和失败原因。地区不允许、非重点新闻、OneBot 离线、公开 URL 不可访问和 blocker 均必须保持可区分。

#### Scenario: 地区不允许跳过原因
- **WHEN** 一篇英国文章公开发布
- **AND** 某目标群未允许英国地区
- **THEN** 系统 SHALL 不为该群发送消息
- **AND** 跳过原因 SHALL 为 `region_not_allowed` 或等价稳定原因

#### Scenario: OneBot 离线不消耗尝试次数
- **WHEN** OneBot 状态检查显示离线或不可确认
- **AND** 多地区文章存在待发送交付
- **THEN** 系统 SHALL 不调用发送接口
- **AND** 不得增加交付尝试次数

#### Scenario: 关闭 QQ 总开关暂停所有地区自动推送
- **WHEN** `QQ_PUSH_ENABLED=false`
- **THEN** 日本、中国香港、英国、法国和美国文章均不得执行自动 QQ 发送
- **AND** 公开发布流程 SHALL 不受影响

### Requirement: 自动推送必须按群级地区和范围判定
系统 SHALL 在为文章创建或处理 QQ 自动推送交付前，同时检查文章公开状态、blocker、公开 URL、文章地区、目标群启用状态、目标群允许地区、目标群推送范围和目标群重点策略。新地区新闻默认可进入自动推送评估，但只有文章地区明确且目标群配置允许该地区时才会发送。

#### Scenario: 群允许地区时发送
- **WHEN** 一篇美国地区文章已公开且无 blocker
- **AND** 某启用 QQ 群允许美国地区并配置为推送所有公开新闻
- **THEN** 系统 SHALL 为该群创建自动推送交付记录并按现有 URL 检查和 OneBot 流程发送

#### Scenario: 群不允许地区时跳过
- **WHEN** 一篇英国地区文章已公开且无 blocker
- **AND** 某启用 QQ 群未允许英国地区
- **THEN** 系统 SHALL 不向该群发送该文章，并记录或返回地区不匹配的跳过原因

#### Scenario: 群级范围覆盖全局范围
- **WHEN** 全局 `QQ_PUSH_SCOPE` 与某目标群的群级推送范围不同
- **THEN** 系统 SHALL 以该目标群的群级推送范围作为该群的自动推送判定依据

#### Scenario: 群级配置缺失时使用兼容默认值
- **WHEN** 某目标群尚未显式配置允许地区、推送范围或重点策略
- **THEN** 系统 SHALL 对允许地区使用旧日本新闻兼容默认，对推送范围和重点策略使用迁移生成的兼容默认值或全局配置回退值，并在后台展示最终生效配置

### Requirement: 群级配置不得破坏交付幂等和限速
系统 SHALL 在引入群级地区和范围配置后继续以“文章 x QQ 群”为唯一交付粒度。群级配置变化 MUST NOT 导致同一文章对同一群重复自动发送；同一目标群的最小发送间隔仍按该群交付记录计算。

#### Scenario: 配置变化后不重复发送
- **WHEN** 某文章对某 QQ 群已有 `sent` 状态交付记录
- **AND** 工作人员后来调整该群允许地区或推送范围
- **THEN** 系统 SHALL NOT 因配置变化再次向同一群自动发送同一篇文章

#### Scenario: 群级限速继续生效
- **WHEN** 同一目标群在短时间内有多篇不同地区文章待发送
- **THEN** 系统 SHALL 继续按目标群最近发送尝试时间延后后续交付，且不得在延后时增加尝试次数

### Requirement: OneBot 离线时自动交付必须暂停发送
系统 SHALL 在自动 QQ 交付真正调用 OneBot `/send_group_msg` 前检查 OneBot 当前是否在线可发送。若 OneBot HTTP 不可达、状态响应异常、业务状态失败，或 `/get_status` 显示 `online=false`，系统 MUST NOT 调用 `/send_group_msg`，MUST NOT 增加本次交付的 `attempt_count`，并 MUST 在交付记录中写入可排查的离线或状态检查失败摘要。Bot 恢复在线后，同一交付记录 MUST 仍可由后续任务继续发送，且不需要人工重建交付记录。

#### Scenario: OneBot 显示离线时不消耗重试
- **WHEN** 自动交付任务准备发送一条尚未达到最大尝试次数的 QQ 交付记录
- **AND** OneBot `/get_status` 返回 `status=ok` 且 `data.online=false`
- **THEN** 系统 SHALL NOT 调用 `/send_group_msg`
- **AND** 系统 SHALL NOT 增加该交付记录的 `attempt_count`
- **AND** 系统 SHALL 记录 OneBot 离线相关错误摘要

#### Scenario: OneBot 状态检查失败时不消耗重试
- **WHEN** 自动交付任务准备发送一条尚未达到最大尝试次数的 QQ 交付记录
- **AND** OneBot 状态检查超时、HTTP 失败、返回非 JSON 或返回业务失败
- **THEN** 系统 SHALL NOT 调用 `/send_group_msg`
- **AND** 系统 SHALL NOT 增加该交付记录的 `attempt_count`
- **AND** 系统 SHALL 记录状态检查失败摘要

#### Scenario: OneBot 恢复在线后继续发送
- **WHEN** 自动交付记录此前因 OneBot 离线被保留为可恢复状态
- **AND** 后续 OneBot `/get_status` 返回 `status=ok` 且 `data.online=true`
- **THEN** 系统 SHALL 正常领取发送尝试并调用 `/send_group_msg`

### Requirement: 窗口化 QQ 自动推送
系统 SHALL 基于已发布文章执行地区 QQ 推送窗口，日常为 15 分钟，重要赛事为 5 分钟。

#### Scenario: 日常 QQ 窗口
- **WHEN** 某地区处于日常模式
- **THEN** 系统 SHALL 在每个 15 分钟窗口中最多自动推送 3 篇高价值文章

#### Scenario: 重要赛事 QQ 窗口
- **WHEN** 某地区处于重要赛事模式
- **THEN** 系统 SHALL 在每个 5 分钟窗口中最多自动推送 3 篇高价值文章

### Requirement: QQ 只推高价值文章
系统 SHALL 只自动推送高价值文章，保底发布文章默认不自动 QQ。

#### Scenario: 保底文章不自动推
- **WHEN** 某文章因 `region_minimum_fill` 被网页公开但不满足高价值条件
- **THEN** 系统 SHALL 不自动创建 QQ 推送发送任务

#### Scenario: 人工推送仍可用
- **WHEN** 运营在后台人工推送保底文章
- **THEN** 系统 SHALL 仍按群地区、总量上限、URL 和 OneBot 状态校验处理

### Requirement: QQ 多层配额
系统 SHALL 控制每地区每窗口、每群每小时和全站每小时 QQ 自动推送上限。

#### Scenario: 群小时上限触发
- **WHEN** 某 QQ 群在当前小时已达到配置上限
- **THEN** 系统 SHALL 跳过该群后续自动推送并保存 `group_hourly_cap_reached`

#### Scenario: 全站 QQ 上限触发
- **WHEN** 全站当前小时自动 QQ 推送达到配置上限
- **THEN** 系统 SHALL 跳过后续自动推送并保存 `site_hourly_cap_reached`

### Requirement: QQ 0 推送原因
系统 SHALL 为每个 QQ 推送窗口保存 0 推送原因。

#### Scenario: 无发布文章
- **WHEN** 某地区 QQ 窗口内没有可推的已发布文章
- **THEN** 系统 SHALL 保存 0 推送原因为 `no_published_articles`

#### Scenario: 群未订阅地区
- **WHEN** 某群未订阅该地区
- **THEN** 系统 SHALL 保存该目标群跳过原因为 `region_not_allowed`

#### Scenario: OneBot 离线
- **WHEN** OneBot 状态为离线或状态检查失败
- **THEN** 系统 SHALL 保存 `onebot_offline` 或状态检查失败原因，且不消耗发送尝试次数

### Requirement: 运营通知通道
系统 SHALL 使用独立运营通知通道发送生产摘要、异常通知和恢复通知，不占用用户新闻 QQ 推送配额。

#### Scenario: 异常即时通知
- **WHEN** 某地区连续 4 个窗口发布 0 篇且原因不是确实无新闻
- **THEN** 系统 SHALL 向内部运营 QQ 群或邮件发送告警通知，并附带后台快速入口

#### Scenario: 恢复通知
- **WHEN** 某地区从连续失败状态恢复并成功发布或推送
- **THEN** 系统 SHALL 发送简短恢复通知

### Requirement: QQ 自动推送必须按主地区和相关地区匹配群订阅
系统 SHALL 在判断某篇文章是否可推送给某个 QQ 群时，同时检查文章主地区和相关地区。只要目标群允许任一命中地区，且文章满足推送范围、重点策略、公开 URL 和 blocker 规则，系统 SHALL 允许该群接收该文章。

#### Scenario: 群订阅相关地区可收到文章
- **WHEN** 一篇文章主地区为英国、相关地区包含法国
- **AND** 某 QQ 群允许法国但不允许英国
- **AND** 该文章满足该群推送范围和重点策略
- **THEN** 系统 SHALL 允许该群接收该文章

#### Scenario: 未订阅任何命中地区不推送
- **WHEN** 一篇文章主地区为英国、相关地区包含法国
- **AND** 某 QQ 群只允许中国香港
- **THEN** 系统 SHALL NOT 向该群自动发送该文章
- **AND** 跳过原因 SHALL 表示地区不匹配

### Requirement: 多地区文章对同一群仍必须幂等去重
系统 SHALL 继续以“文章 x QQ 群”为自动推送交付唯一粒度。多地区文章即使同时命中同一群的多个允许地区，也 MUST 只创建或发送一次交付。

#### Scenario: 同一群订阅多个命中地区
- **WHEN** 一篇文章主地区为英国、相关地区包含法国
- **AND** 某 QQ 群同时允许英国和法国
- **THEN** 系统 SHALL 只为该文章和该群创建一条 `QQPushDelivery`
- **AND** 系统 SHALL NOT 向同一群发送两次同一篇文章

### Requirement: QQ 消息必须展示多地区标签
系统 SHALL 在多地区文章 QQ 消息中展示主地区，并在存在相关地区时展示可读相关地区标签，使群用户理解文章涉及的地区。

#### Scenario: 多地区消息展示地区
- **WHEN** 系统生成主地区为英国、相关地区为法国的 QQ 消息
- **THEN** 消息 SHALL 包含英国地区标签
- **AND** 消息 SHOULD 包含法国相关地区标签或等价说明

### Requirement: QQ 高价值资格必须按内容类别分层
系统 SHALL 对新增内容类别使用可配置 QQ 资格策略。赛果简报和重大赛事赛前展望 MAY 进入 QQ 高价值推送；普通 tips、投注营销、普通官方通知、普通育马或拍卖内容默认不得进入 QQ 高价值推送，除非来源或类别配置显式允许。

#### Scenario: 赛果简报可进 QQ
- **WHEN** 一篇 `result_brief` 文章已公开且无 blocker
- **AND** 目标群允许该文章主地区或相关地区
- **AND** 文章满足分数或来源重点策略
- **THEN** 系统 SHALL 允许其进入 QQ 自动推送资格

#### Scenario: 普通 tips 默认不进 QQ
- **WHEN** 一篇 `tips` 文章主要是普通投注预测或赔率营销
- **THEN** 系统 SHALL 默认判定该文章不具备 QQ 高价值推送资格
- **AND** 系统 SHALL 保存 `content_category_not_qq_eligible` 或等价跳过原因
