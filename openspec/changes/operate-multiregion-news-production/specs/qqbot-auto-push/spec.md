## ADDED Requirements

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
