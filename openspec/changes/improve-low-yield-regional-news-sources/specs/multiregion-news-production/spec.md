## ADDED Requirements

### Requirement: 地区生产审计必须提供逐来源全漏斗 <!-- id: req-source-full-funnel -->
系统 SHALL 在有限时间窗口内按来源输出 listing、详情、时效跳过、非赛马跳过、重复、入库、翻译、门禁、候选和公开数量，并保持各阶段口径可解释。

#### Scenario: 来源任务成功但没有新增
- **WHEN** 某来源最近 7 天抓取任务均成功但 created 为 0
- **THEN** 审计 SHALL 输出 listing_seen、stale_skipped、duplicate_seen、detail_failed 等前置计数
- **AND** 不得仅显示“成功无新增”而无法定位损失层

#### Scenario: 来源入库充足但公开不足
- **WHEN** 某来源达到入库供给目标但公开数量未达到观察目标
- **THEN** 审计 SHALL 展示翻译失败、门禁阻断、候选过期和发布窗口损失
- **AND** 系统 SHALL 把问题归入对应下游阶段而非继续盲目扩源

### Requirement: 低产地区扩源必须经过统一准入 <!-- id: req-regional-source-admission -->
系统 MUST 在新增来源生产批准前完成只读准入探测，覆盖访问、正文、发布时间、相关性、语言、canonical 身份、重复和来源许可。未被标记为 accepted 的来源 MUST NOT 生产批准。

#### Scenario: 候选来源满足准入
- **WHEN** 候选来源在有限 probe 中稳定返回至少 3 篇近 7 天赛马正文，且所有准入字段可验证
- **THEN** 系统 MAY 将其标记为 accepted
- **AND** 同步到 `NewsSource` 时仍 SHALL 默认关闭且未生产批准

#### Scenario: HTTP 200 但详情为空
- **WHEN** 候选列表返回 200，但详情为反机器人页、空正文或无法获得真实发布时间
- **THEN** 来源 SHALL 标记为 deferred 或 blocked
- **AND** 系统 MUST NOT 将其加入生产抓取 allowlist

#### Scenario: 没有 accepted 来源
- **WHEN** 某地区全部候选均未通过准入
- **THEN** 验收 SHALL 明确记录 no-go 与原因
- **AND** 系统 SHALL NOT 为满足数量目标强行启用来源

### Requirement: 新来源必须有界并行生产上线 <!-- id: req-bounded-parallel-production-rollout -->
系统 SHALL 只把通过准入与 fixture 回归的 accepted 来源加入生产。系统 MAY 每地区并行直接启用多个来源，初始上限 SHALL 为 2；新来源 MUST 继续经过现有翻译、门禁、去重、配额和发布策略，并且每个来源 MUST 可独立停用。

#### Scenario: 两个 accepted 来源直接生产启用
- **WHEN** 某地区两个来源均通过准入、fixture 回归和部署前检查
- **THEN** 运维人员 MAY 同时设置两个来源为 enabled 且 production approved，并直接进入现有生产窗口
- **AND** 系统 SHALL 分来源记录 listing→公开漏斗、抓取耗时、错误和容器/队列观察证据

#### Scenario: 生产观察发现质量或容量问题
- **WHEN** 新来源出现日期错误、非赛马内容、正文缺失、异常重复、队列持续增长、容器重启或健康检查异常
- **THEN** 运维流程 SHALL 立即停用问题来源并停止继续扩大并发
- **AND** 其他健康来源 SHALL 可保持运行，已公开错误内容 SHALL 进入单独审计和撤回流程

### Requirement: 地区产出目标必须区分供给与公开 <!-- id: req-regional-yield-slo -->
系统 SHALL 分别定义地区 7 天入库供给目标和公开观察目标。目标仅用于告警与复盘，不得作为绕过质量门禁或强制发布的配额。

#### Scenario: 供给目标未达
- **WHEN** 某地区 7 天入库数量低于配置目标
- **THEN** 系统 SHALL 触发来源覆盖或适配器复盘
- **AND** 不得通过降低翻译或发布硬门禁补足数量

#### Scenario: 供给达标但公开未达
- **WHEN** 某地区入库达到目标但公开未达到观察目标
- **THEN** 系统 SHALL 把差额按翻译、门禁、候选消费和人工审核分类
- **AND** 来源扩展 SHALL NOT 被自动视为唯一解决方案
