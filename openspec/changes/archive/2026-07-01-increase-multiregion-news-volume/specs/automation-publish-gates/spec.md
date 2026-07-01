## ADDED Requirements

### Requirement: 窗口自动发布硬门禁
系统 SHALL 使用统一硬门禁判断文章是否可进入窗口自动发布。

#### Scenario: 硬门禁阻断
- **WHEN** 某文章翻译失败、无中文正文、正文过短、明显乱码、非赛马内容、URL 不可访问或重复组已有赢家
- **THEN** 系统 SHALL 阻断该文章自动发布并保存结构化 blocker

#### Scenario: 预览和执行一致
- **WHEN** 运营预览发布窗口后真实执行该窗口
- **THEN** 系统 SHALL 使用同一硬门禁服务生成一致的 blocker 结果

### Requirement: 保底发布分数边界
系统 SHALL 允许地区软下限保底发布低于高价值阈值但不低于 45 分的文章。

#### Scenario: 低于高价值但满足保底
- **WHEN** 某地区窗口没有高价值文章但存在 45 分及以上且通过硬门禁的候选
- **THEN** 系统 SHALL 允许将该文章作为 `region_minimum_fill` 自动发布

#### Scenario: 低于 45 分
- **WHEN** 某候选文章分数低于 45
- **THEN** 系统 SHALL 不自动发布该文章

### Requirement: 自动发布去重赢家
系统 SHALL 在自动发布前执行地区内强去重和跨地区弱去重，并保存赢家与落选原因。

#### Scenario: 地区内重复报道
- **WHEN** 同一地区多篇候选文章报道同一事件
- **THEN** 系统 SHALL 只自动发布最高优先级文章，并将其他文章记录为 `dedup_loser`

#### Scenario: 跨地区高度重复
- **WHEN** 不同地区候选文章内容高度重复且全站额度紧张
- **THEN** 系统 SHALL 优先发布最高分或最相关地区文章，并保存跨地区去重解释

### Requirement: 自动发布配额账本
系统 SHALL 使用持久化配额账本控制地区窗口、地区小时和全站小时自动发布数量。

#### Scenario: 并发发布窗口竞争
- **WHEN** 两个 worker 并发尝试占用同一地区小时发布额度
- **THEN** 系统 SHALL 通过事务和配额账本防止超过配置上限

#### Scenario: 配额不足
- **WHEN** 某候选文章通过硬门禁但地区或全站配额不足
- **THEN** 系统 SHALL 不发布该文章并保存 `quota_limited` 原因
