## ADDED Requirements

### Requirement: 地区生产审计必须解释翻译失败 <!-- id: req-region-translation-funnel -->
系统 SHALL 在地区生产审计和后台概览中按错误码、年龄、尝试次数和可恢复性聚合翻译失败，并区分正在退避重试、最终失败和人工处理。

#### Scenario: 地区存在瞬态失败
- **WHEN** 某地区最近 24 小时存在 rate limit、5xx、timeout 或 connection 错误
- **THEN** 审计 SHALL 输出各错误码数量、重试中数量、最终失败数量和最老年龄
- **AND** 不得只显示一个笼统的 translation_failed 总数

#### Scenario: 翻译失败异常激增
- **WHEN** 某地区最近 2 小时翻译最终失败达到配置阈值
- **THEN** 系统 SHALL 产生有冷却的运营异常信号
- **AND** 信号 SHALL 包含主要错误码和受影响地区
