## ADDED Requirements

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
