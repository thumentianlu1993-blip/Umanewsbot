# production-window-observability Specification

## Purpose
TBD - created by archiving change increase-multiregion-news-volume. Update Purpose after archive.
## Requirements
### Requirement: 窗口运行结果持久化
系统 SHALL 为抓取、发布选择和 QQ 推送保存结构化窗口运行结果。

#### Scenario: 发布窗口保存结果
- **WHEN** 某地区发布窗口执行完成
- **THEN** 系统 SHALL 记录窗口开始时间、结束时间、模式、候选数、硬门禁过滤数、去重过滤数、发布数、0 发布原因、上限触发和执行状态

#### Scenario: QQ 窗口保存结果
- **WHEN** 某地区某 QQ 群推送窗口执行完成
- **THEN** 系统 SHALL 记录候选推送数、成功数、跳过数、失败数、0 推送原因、OneBot 状态和上限触发

### Requirement: 窗口幂等和补跑
系统 SHALL 使用窗口唯一键和原子领取机制避免重复执行，并支持最近 3 小时内缺失或失败窗口自动补跑。

#### Scenario: 重复调度同一窗口
- **WHEN** 两个 worker 同时尝试执行同一地区同一开始时间的发布窗口
- **THEN** 系统 SHALL 只允许一个 worker 成功领取并执行该窗口

#### Scenario: 自动补跑失败窗口
- **WHEN** 调度任务发现最近 3 小时内存在失败或缺失窗口
- **THEN** 系统 SHALL 自动补跑该窗口并记录补跑来源

### Requirement: 窗口决策原因持久化
系统 SHALL 保存候选文章和 QQ 目标群在窗口中的入选、跳过、失败或阻断原因。

#### Scenario: 文章因去重未入选
- **WHEN** 某候选文章因同事件已有更高分赢家而未发布
- **THEN** 系统 SHALL 保存该文章的窗口决策为 `dedup_loser` 并关联赢家或解释原因

#### Scenario: QQ 因无高价值文章推送 0 条
- **WHEN** 某 QQ 窗口存在已发布文章但没有高价值文章
- **THEN** 系统 SHALL 保存 0 推送原因为 `not_high_value`

### Requirement: 地区生产中心
系统 SHALL 提供统一的后台地区生产中心，作为查看多地区窗口状态、失败原因、重要赛事模式和快速操作的主入口。

#### Scenario: 查看地区最近窗口
- **WHEN** 运营打开地区生产中心
- **THEN** 系统 SHALL 按地区展示最近抓取窗口、发布窗口、QQ 窗口、异常来源、0 结果原因和当前模式

#### Scenario: 从生产中心进入重跑
- **WHEN** 运营在地区生产中心选择某个失败发布窗口重跑
- **THEN** 系统 SHALL 重新执行发布选择，但不重新抓取外部来源

### Requirement: 窗口预览
系统 SHALL 支持后台预览当前窗口的候选、过滤、去重、评分、上限和预计结果。

#### Scenario: 预览发布窗口
- **WHEN** 运营预览某地区当前发布窗口
- **THEN** 系统 SHALL 展示候选文章、硬门禁原因、去重输赢、分数和预计发布列表，且不修改文章发布状态

#### Scenario: 预览 QQ 窗口
- **WHEN** 运营预览某地区 QQ 推送窗口
- **THEN** 系统 SHALL 展示可推文章、目标群、跳过原因和预计推送数，且不创建真实发送任务

### Requirement: 生产摘要与异常通知
系统 SHALL 提供后台和管理命令生产摘要，并通过内部运营 QQ 群和邮件发送每日摘要、异常通知和恢复通知。

#### Scenario: 每日摘要
- **WHEN** 每日摘要任务执行
- **THEN** 系统 SHALL 汇总各地区抓取窗口、发布数、保底发布数、QQ 推送数、0 结果原因、降频来源和全站上限触发

#### Scenario: 异常通知冷却
- **WHEN** 同一地区同一异常在 30 分钟内重复出现
- **THEN** 系统 SHALL 避免重复刷屏通知，并保留后台异常记录
