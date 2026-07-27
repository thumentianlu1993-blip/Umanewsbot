## ADDED Requirements

### Requirement: 赛果恢复后的日历筛选必须反映正式终态
赛事日历 SHALL 让恢复后 `finished` 的 canonical event 出现在“已完赛”筛选，并继续只在存在确认冠军时展示冠军名称。

#### Scenario: 旧赛程由恢复流程推进
- **WHEN** 已过期 canonical event 从 `scheduled` 原子推进为 `finished` 且具有确认赛果
- **THEN** 全部与重点 tab 的状态、日期轴和“已完赛”筛选必须一致

#### Scenario: 赛事明确延期或取消
- **WHEN** inventory 中既有且未漂移的终态为 `postponed` 或 `cancelled`
- **THEN** 赛事不得出现在“已完赛”筛选，也不得显示冠军

### Requirement: 日历不得重复展示同一批准赛事身份
赛事日历 MUST 对 active `RaceEventProductCanonicalLink` 仅展示 canonical product event，并保持 canonical 详情链接稳定。

#### Scenario: 两个公开 RaceEvent 属于同一批准 identity group
- **WHEN** 两条底层记录都仍为 published
- **THEN** 日历和日期轴只能出现 canonical event 一次
