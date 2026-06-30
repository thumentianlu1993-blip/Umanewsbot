## ADDED Requirements

### Requirement: 系统必须提供多地区新闻生产审计
系统 SHALL 提供生产只读审计能力，用于在开启或扩大多地区常态生产前确认各地区来源、文章、翻译、发布、QQ 交付和术语运营状态。审计 MUST 不触发抓取、翻译、发布、推送或外部数据库导入写入。

#### Scenario: 审计输出地区来源状态
- **WHEN** 运维人员执行多地区新闻生产审计
- **THEN** 系统 SHALL 输出每个地区的启用来源数量、最近抓取时间、最近抓取状态、成功无新增来源和失败来源

#### Scenario: 审计输出地区文章状态
- **WHEN** 运维人员执行多地区新闻生产审计
- **THEN** 系统 SHALL 输出每个地区按工作流状态、翻译状态、自动化状态和公开状态聚合的文章数量

#### Scenario: 审计不修改生产数据
- **WHEN** 多地区新闻生产审计执行完成
- **THEN** 系统 SHALL NOT 创建新的 `CrawlJob`、`NewsArticle`、`QQPushDelivery`、`ExternalDataImportRun` 或其他业务写入记录

#### Scenario: 审计输出可保存为 runtime JSON
- **WHEN** 运维人员执行多地区新闻生产审计并显式提供输出路径
- **THEN** 系统 MAY 将审计结果保存到 `runtime/` 下 JSON 文件
- **AND** 该保存动作 SHALL NOT 修改数据库业务表

### Requirement: 多地区常态生产必须按阶段灰度
系统 SHALL 支持按地区和来源分阶段启用常态生产。第一阶段 MUST 允许只启用测试群和少量已验证来源；正式群、法国、美国或更多来源的扩大范围 MUST 通过显式配置或运维动作完成。

#### Scenario: 测试群先接收多地区新闻
- **WHEN** 香港或英国新闻进入常态生产第一阶段
- **THEN** 系统 SHALL 允许测试 QQ 群通过显式 `allowed_regions` 接收对应地区新闻
- **AND** 未显式允许该地区的正式群 SHALL NOT 接收该地区新闻

#### Scenario: 访问受限来源保持停用
- **WHEN** 某国际来源在生产探测中返回 `403`、反机器人页、空样本或结构不可稳定解析
- **THEN** 系统 SHALL 保持该来源停用或排除在常态生产 allowlist 之外

#### Scenario: 扩大地区前执行审计
- **WHEN** 工作人员准备把一个新地区从手动测试升级为常态生产
- **THEN** 系统 SHALL 要求先执行或记录该地区的只读审计结果，并确认来源、翻译、发布和 QQ 配置没有阻断问题

### Requirement: 后台必须展示地区生产闭环指标
系统 SHALL 在运营后台展示地区级生产闭环指标，使工作人员能够判断每个地区是否持续完成抓取、翻译、审核或自动发布、公开展示和 QQ 推送。

#### Scenario: 展示地区今日生产概览
- **WHEN** 工作人员打开运营后台地区生产概览
- **THEN** 系统 SHALL 展示每个地区今日新增文章、待翻译、翻译失败、待人工审核、已自动发布、已人工发布和公开文章数量

#### Scenario: 地区生产概览使用有限窗口
- **WHEN** 系统计算地区生产概览
- **THEN** 今日指标 SHALL 以服务器当前日期窗口统计
- **AND** 近期指标 SHALL 使用明确的有限时间窗口
- **AND** 不得默认扫描全部历史明细生成页面

#### Scenario: 展示地区 QQ 交付概览
- **WHEN** 工作人员查看地区生产概览
- **THEN** 系统 SHALL 展示每个地区近期 QQ 交付的成功、等待、跳过和失败数量

#### Scenario: 区分未启用和启用无新增
- **WHEN** 某地区没有启用来源
- **THEN** 后台 SHALL 将该地区展示为未启用或未灰度
- **AND** 不得把该状态误报为抓取失败

### Requirement: 外部赛马数据库不得进入新闻常态调度
系统 SHALL 保持新闻抓取调度与外部赛马数据库导入分离。HKJC、英国、法国、美国的 `External*` importer MAY 为术语、外部马名识别和后续数据底座服务，但 MUST NOT 被新闻常态调度自动触发。

#### Scenario: 新闻轮询不触发外部 importer
- **WHEN** 通用新闻来源轮询任务运行
- **THEN** 系统 SHALL 只处理新闻来源
- **AND** 不得调用 `import_external_horse_data_task`、HKJC importer、英国 importer、法国 importer 或美国 importer

#### Scenario: 外部数据不自动生成公开新闻
- **WHEN** 外部赛马数据库 importer 写入或 dry-run 解析比赛、出马、赛果和马匹数据
- **THEN** 系统 SHALL NOT 因这些数据自动创建公开新闻、公开比赛页、QQ 推送或前台赛果页面

### Requirement: 多地区生产运行手册必须可执行
系统 SHALL 在仓库文档中维护多地区常态生产运行手册，覆盖启用前审计、灰度开启、验收、异常处理、停用和回滚。

#### Scenario: 运行手册包含启用步骤
- **WHEN** 工作人员准备启用某地区常态生产
- **THEN** 运行手册 SHALL 提供只读审计、来源启用、调度开关、QQ 测试群配置、观察窗口和验收命令

#### Scenario: 运行手册包含停用步骤
- **WHEN** 某地区新闻源异常、翻译质量异常或 QQ 推送异常
- **THEN** 运行手册 SHALL 提供关闭通用轮询、停用具体来源、收窄群允许地区和关闭 QQ 自动推送的步骤
