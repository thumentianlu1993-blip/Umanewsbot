## ADDED Requirements

### Requirement: batch006 起标准批次单地区最多选择 250 场
系统 MUST 保留 batch005 的单地区最多 50 场历史口径，并从 batch006 起允许标准批次在同一年代带内每地区最多选择 250 场。实际批准上限 MUST 作为单一参数同时约束选择、artifact 写入和后续验证。

#### Scenario: batch006 使用默认上限
- **WHEN** 运维人员未显式缩小 batch006 或后续标准批次的地区上限
- **THEN** 系统 MUST 使用每地区 250 场作为默认及最大标准上限
- **AND** selection summary 与 manifest MUST 记录 `approved_region_limit=250`

#### Scenario: 显式执行较小批次
- **WHEN** 运维人员为 batch006 或后续批次显式指定 1 到 249 的地区上限
- **THEN** 系统 SHALL 按该上限选择并验证目标
- **AND** artifact MUST 记录实际批准值，不得仍声称使用 250

#### Scenario: 超过标准上限
- **WHEN** 命令或 artifact 尝试让任一地区超过 250 场
- **THEN** 系统 MUST 在写出可审批 artifact 前失败
- **AND** 系统 MUST 不通过截断候选来伪装成功

#### Scenario: 选择与 artifact 上限不一致
- **WHEN** 选择阶段、artifact 写入阶段或验证阶段使用了不同的地区上限
- **THEN** 系统 MUST fail closed
- **AND** 系统 MUST 指出批准上限或地区计数不一致

### Requirement: 扩大批次不得削弱地区进度和排除门禁
系统 MUST 在 250 场标准上限下继续执行 100 场地区领先护栏、已耗尽地区退出比较、不可变排除 snapshot 和 pending 分母记账规则。

#### Scenario: 仍有多个未完成地区
- **WHEN** 本批选择后仍有两个或以上地区存在未排除可抓目标
- **THEN** 系统 MUST 比较这些地区的 prospective accounted 数
- **AND** 最大差值超过 100 时 MUST 拒绝该批次

#### Scenario: 地区已经抓空
- **WHEN** 某地区在本批选择后没有未排除可抓目标
- **THEN** 系统 MUST 将该地区移出领先比较
- **AND** 系统 MUST 保留其待审排除项和 pending 总账分母

#### Scenario: 旧批次 gap 被排除
- **WHEN** 运维人员传入既有不可变 selection snapshot
- **THEN** 系统 MUST 在应用地区上限前排除其中仍 pending 的 target
- **AND** 系统 MUST 不让这些 target 重复占用 250 场配额或被标记为已完成
