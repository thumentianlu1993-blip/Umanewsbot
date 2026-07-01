## MODIFIED Requirements

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

## ADDED Requirements

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
