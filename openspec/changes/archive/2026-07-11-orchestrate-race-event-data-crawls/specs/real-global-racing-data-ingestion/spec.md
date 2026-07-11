## ADDED Requirements

### Requirement: RaceEvent 历史回填必须与 External 数据库导入分离
系统 MUST 将 `RaceEvent*` 产品层历史回填与 `ExternalRace*` 外部数据库导入保持分离。赛事信息编排工具不得把产品层回填误写入外部缓存表，也不得把外部 proof 当作产品层 apply 证据。

#### Scenario: RaceEvent 编排不写 External
- **WHEN** 运维人员执行赛事信息编排工具的 plan、prepare、audit 或 dry-run 阶段
- **THEN** 系统 MUST 不修改 `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse` 或 `ExternalHorseAlias`

#### Scenario: External proof 不等于 RaceEvent apply 证据
- **WHEN** 某地区已有 `External*` proof-only 或 dry-run artifact
- **THEN** 系统 MUST 不将该 artifact 直接视为 `RaceEventRunner`、`RaceEventResult` 或 `RaceEventHistoryWinner` 的 apply 证据
- **AND** 系统 MUST 要求转换为 `RaceEventDataCandidate` 可审计候选后才能进入产品层流程

### Requirement: RaceEvent 历史回填复用真实抓取安全门禁
系统 SHALL 复用真实外部数据库抓取中已经建立的保守限速、显式网络授权、单次批量上限、运行证据和生产锁检查原则。

#### Scenario: 显式网络授权
- **WHEN** RaceEvent 历史回填需要请求外部来源页面
- **THEN** 系统 MUST 要求显式网络授权
- **AND** 系统 MUST 在运行 artifact 中记录请求入口、限速和请求摘要

#### Scenario: 批次超限
- **WHEN** RaceEvent 历史回填批次的赛事数、来源请求数或目标年份范围超过 plan 配置上限
- **THEN** 系统 MUST 拒绝执行或要求拆分批次
- **AND** 系统 MUST 不静默截断后伪装为完整覆盖

#### Scenario: 生产锁检查
- **WHEN** RaceEvent 历史回填准备进入正式 apply
- **THEN** apply-check MUST 确认外部数据导入运行数为 0 且相关导入锁为空
- **AND** 缺少该证据时 MUST 阻止 apply

### Requirement: RaceEvent 历史回填不得改变新闻分发
系统 MUST 保证 RaceEvent 历史回填不创建新闻文章、不触发翻译、不触发自动发布或 QQ 推送。

#### Scenario: 结构化赛事数据写入
- **WHEN** RaceEvent 历史回填通过审核并写入结构化赛事资料
- **THEN** 系统 MUST 不创建 `NewsArticle`
- **AND** 系统 MUST 不创建 `QQPushDelivery`

#### Scenario: 回填不触发新闻流水线
- **WHEN** RaceEvent 历史回填完成
- **THEN** 系统 MUST 不派发新闻抓取、翻译、AI 改写、自动发布或 QQ 推送任务
