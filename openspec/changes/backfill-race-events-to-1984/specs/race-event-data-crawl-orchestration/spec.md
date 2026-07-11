## MODIFIED Requirements

### Requirement: 第一版必须覆盖三类赛事详情模块
系统 SHALL 在历史回填范围内同时支持 `runners`、`results` 和 `history_winners` 三类产品能力，并对同一目标范围采用相同历史深度。held/due 年度必须取得独立出马表或从可信完整赛果派生 runners，必须取得可信完整 results；该年度冠军 SHALL 由正式赛果第一名提供，只有缺完整赛果但有可信冠军证据时才使用 `RaceEventHistoryWinner` 补位。系统 MUST NOT 为每个年度赛事复制整张历届冠军表。

#### Scenario: plan 缺少任一目标能力
- **WHEN** plan 声明历史回填但没有 runners、results 或系列冠军覆盖能力
- **THEN** 系统 MUST 拒绝将该 plan 标记为完整历史回填计划
- **AND** 系统 MUST 在错误或审计结果中列出缺失能力

#### Scenario: 三类能力历史范围不一致
- **WHEN** 同一地区、来源和赛事系列的 runners、results、冠军覆盖声明不同历史起点或年份范围
- **THEN** 系统 MUST 将该批次标记为 invalid 或 incomplete
- **AND** 系统 MUST 不允许该批次进入 apply 候选

#### Scenario: 完整赛果派生出马表
- **WHEN** 历史来源提供包含全部参赛者的可信完整赛果但没有独立 racecard
- **THEN** 系统 MAY 从赛果派生 runners
- **AND** 派生记录 MUST 标记 `derived_from_results` 且缺失字段保持为空

#### Scenario: 年度冠军由正式赛果提供
- **WHEN** 某年度赛事已有正式完整赛果
- **THEN** 该年度冠军覆盖 SHALL 由赛果第一名满足
- **AND** 系统 MUST NOT 要求再复制一份相同的历史冠军候选

## ADDED Requirements

### Requirement: 历史批次必须从已批准总账切分
系统 MUST 从已批准年度应到总账选择目标并生成 batch plan。plan MAY 缩小到批准 scope，但 MUST NOT 添加总账外目标、删除未解决目标的总账记录或自行改变目标 expectation/resolution 状态。

#### Scenario: plan 包含总账外目标
- **WHEN** 批次 plan 声明的 series/year 不在批准总账
- **THEN** 编排器 MUST fail closed
- **AND** 系统 MUST NOT 发起网络请求

#### Scenario: 批次只选择完整可执行目标
- **WHEN** 总账同时包含 ready、source unavailable 和 identity review 目标
- **THEN** plan MAY 只选择 ready 目标执行
- **AND** 未选择缺口 MUST 继续保留在总账

### Requirement: 第一批历史验收必须跨五地区和三个年代
系统 MUST 为第一批选择每地区 3 个代表系列和约 9 个真实 held/cancelled 年度目标，地区样本整体覆盖 1980 年代、2000 年前后和近年，目标约 45 个年度赛事。长寿现役系列 SHOULD 跨三个年代取样；历史停办系列无法覆盖近年时 MUST 在其真实举办范围取代表年份，并由同地区其他系列补足近年锚点。样本 MUST 包含长寿、改名/迁场以及历史独有或停办系列。

#### Scenario: 某地区只包含近年样本
- **WHEN** 第一批计划中某地区没有 1980 年代或中间年代样本
- **THEN** 第一批校验 MUST 失败
- **AND** 系统 SHALL 列出缺失的地区和年代

#### Scenario: 五地区样本完整
- **WHEN** 五地区均满足 3 系列和 3 年代锚点
- **THEN** 第一批计划 MAY 进入应到审批

### Requirement: 全量批次必须按年代带保持地区同步
系统 SHALL 按 `2016–2025`、`2006–2015`、`1996–2005`、`1984–1995` 从新到旧推进，每个年代带 MUST 覆盖五地区。标准批次每地区最多 50 个 held/cancelled 年度目标；地区进度 MUST 按同年代带 accounted/imported 的 due 目标数计算，任何地区不得比最慢地区领先超过 100 个标准目标。

#### Scenario: 单地区试图连续领先
- **WHEN** 某地区将比最慢地区领先超过 100 个同年代带标准目标
- **THEN** 批次生成器 MUST 阻止新计划
- **AND** 系统 SHALL 提示需要推进落后地区

#### Scenario: plan 修改标准批次上限
- **WHEN** 操作者需要调整每地区 50 个目标的默认上限
- **THEN** 新上限 MUST 写入 plan 和应到审批
- **AND** 地区进度护栏 MUST 继续按标准目标数计算而不是按 run 数量计算

### Requirement: 历史年度 URL 身份必须稳定
系统 MUST 从已批准稳定系列 key 生成带地区前缀的历史年度 slug，并保持 `(year, slug)` 和 `(race_series, year)` 唯一。年度赛事创建后，名称、翻译、冠名或马场修正 MUST NOT 自动改变 slug；现有年度 URL MUST 保持不变。

#### Scenario: 历史冠名后续修正
- **WHEN** 已创建年度赛事的赛事名称或中文译名被修正
- **THEN** 其 slug 和公开 URL MUST 保持不变

#### Scenario: 同年 slug 冲突
- **WHEN** 建议 slug 与同年其他赛事冲突
- **THEN** 基础年度 apply MUST 在写入前阻断
- **AND** 冲突 MUST 进入身份审核

### Requirement: Coverage 必须允许完整 scope 独立应用
系统 SHALL 按年度目标拆分完整 scope 和缺口 scope。完整 scope MAY 继续 dry-run、apply-check 和正式写入；`source_unavailable / identity_review_required` 等缺口 MUST 留在总账且不得进入批准候选。

#### Scenario: 同批存在完整和缺失目标
- **WHEN** 45 个目标中 40 个三类能力完整、5 个来源暂不可用
- **THEN** coverage SHALL 为 40 个完整目标生成可审核 apply scope
- **AND** 5 个缺口 SHALL 留在 gap ledger 且不计为完成

#### Scenario: 缺口被空候选占位
- **WHEN** adapter 为不可用目标输出空 items 试图满足模块键
- **THEN** coverage MUST 拒绝该目标
- **AND** 系统 MUST NOT 将其计入完整 scope

### Requirement: 历史写入必须保留字段级变更和人工锁
系统 SHALL 对已存在年度赛事生成字段级 before/after/source diff。更高权威或更完整来源只有在新批准批次中才能更新未人工锁定字段；人工锁定字段 MUST 保留。apply artifact MUST 保存回滚所需旧值。

#### Scenario: 更高权威来源补齐空字段
- **WHEN** 新官方来源补齐现有空字段且字段未人工锁定
- **THEN** 新批准批次 MAY 更新该字段
- **AND** 系统 SHALL 保存旧值、来源和变更原因

#### Scenario: 新来源试图覆盖人工字段
- **WHEN** 候选与人工锁定字段不同
- **THEN** apply MUST 保留人工值
- **AND** diff SHALL 显示冲突和跳过原因

### Requirement: 写后核验必须回写总账而不删除缺口
系统 MUST 在每个 apply scope 后核对年度赛事、runner、result、冠军覆盖、可见性和来源计数，并将成功目标更新为 imported。失败或未选目标 MUST 保留原状态和证据。

#### Scenario: 部分 scope 写入成功
- **WHEN** 某批准 scope 原子写入并通过写后计数
- **THEN** 对应目标 SHALL 更新为 imported
- **AND** 同批其他缺口状态 MUST 保持不变

#### Scenario: 写后计数不符
- **WHEN** 实际 runner/result 数量与批准 artifact 不一致
- **THEN** 总账 MUST NOT 标记 imported
- **AND** 系统 MUST 生成写后 blocker 和回滚指引

### Requirement: 历史批次关键状态必须写操作日志
系统 MUST 为 inventory commit、series mapping、永久不可得批准、publication transition、网络 run 开始/失败/恢复和写后核验记录操作或任务日志。日志 MUST 绑定 artifact SHA、目标范围、操作者、状态和摘要，且不得记录整页原件或敏感环境变量。

#### Scenario: 历史批次正式写入
- **WHEN** 批准 scope 完成或失败
- **THEN** 系统 MUST 记录批次身份、目标计数、结果和失败摘要

#### Scenario: 永久不可得获得批准
- **WHEN** 运营人员批准 permanently unavailable
- **THEN** 操作日志 MUST 记录批准人、年度目标和证据 manifest 身份
