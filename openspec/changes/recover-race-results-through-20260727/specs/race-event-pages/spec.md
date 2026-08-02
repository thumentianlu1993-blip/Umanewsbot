## ADDED Requirements

### Requirement: 已到期赛事的公开状态必须来自明确恢复终态
公开赛事详情 SHALL 仅依据已批准的赛事状态和确认赛果展示“已完赛”与冠军，不得依据日期自行猜测，也不得让已进入恢复 confirmed 终态的 canonical event 继续显示“赛前”。

#### Scenario: 官方赛果已应用
- **WHEN** canonical event 已写入完整确认赛果、`finished` 状态和 `result_confirmed_at`
- **THEN** 详情页必须展示已完赛与确认赛果

#### Scenario: 恢复目标仍有 blocker
- **WHEN** 赛事已过期但官方证据或身份仍阻断
- **THEN** 页面不得展示虚构冠军，恢复审计必须保留 blocker

### Requirement: 重复真实赛事必须只有一个产品展示实体
系统 SHALL 根据 active `RaceEventProductCanonicalLink` 选择 canonical product event，并避免在公开赛事入口同时展示同一真实赛事的非 canonical 记录；直接访问旧详情 URL 不得 404，并应提供 canonical 赛事链接。

#### Scenario: canonical 选择被回滚
- **WHEN** identity projection 按 rollback ledger 回滚
- **THEN** 前台展示选择必须恢复到写前状态，底层赛事与赛果记录不得被删除
