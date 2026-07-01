## ADDED Requirements

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
