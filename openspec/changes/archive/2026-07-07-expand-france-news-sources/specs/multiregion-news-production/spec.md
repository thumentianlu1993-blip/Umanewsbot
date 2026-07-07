## ADDED Requirements

### Requirement: 法国常态生产必须支持来源扩展
系统 SHALL 支持为法国地区增加新的常态新闻来源，并将这些来源纳入现有多地区生产窗口、来源灰度和审计体系。新增法国来源 MUST 通过显式启用和生产批准后才进入 15 分钟生产抓取。

#### Scenario: 新法国来源未批准前不进入生产窗口
- **WHEN** 新增法国新闻来源已同步到 `NewsSource`
- **AND** 该来源 `production_approved=false`
- **THEN** 多地区生产抓取窗口 SHALL NOT 抓取该来源

#### Scenario: 没有 accepted 新来源时不得宣称生产 ready
- **WHEN** 法国候选来源探测全部被标记为 deferred 或 blocked
- **THEN** 系统 SHALL NOT 新增生产批准的法国来源
- **AND** 验收记录 SHALL 明确标记本次扩源 no-go 及原因

#### Scenario: 批准后的法国来源进入窗口
- **WHEN** 法国新闻来源 `enabled=true` 且 `production_approved=true`
- **AND** 该来源未暂停、未 backoff 且到达有效抓取间隔
- **THEN** 多地区生产抓取窗口 SHALL 按法国地区处理该来源
- **AND** 入库文章 SHALL 标记为法国地区

#### Scenario: 法国来源可单独回滚
- **WHEN** 某个新增法国来源出现访问受限、解析失败或质量问题
- **THEN** 运维人员 SHALL 能通过停用该来源或取消生产批准阻止后续生产抓取
- **AND** 该操作 SHALL NOT 影响法国其他来源或其他地区来源

### Requirement: 法国来源扩展必须区分入库不足和发布阻断
系统 SHALL 在法国地区生产审计中区分来源无新稿、列表重复、解析失败、入库成功但发布门禁阻断等不同原因。

#### Scenario: 来源成功但无新稿
- **WHEN** 法国来源抓取成功且所有列表项均已入库
- **THEN** 审计输出 SHALL 将该来源标记为成功无新增或重复旧稿
- **AND** 不得把该情况展示为抓取失败

#### Scenario: 来源入库后被门禁阻断
- **WHEN** 法国来源成功入库文章
- **AND** 文章因发布门禁未公开
- **THEN** 审计输出 SHALL 展示入库数量、候选数量和门禁原因
- **AND** 不得把该情况归因于来源无新稿

#### Scenario: 法国最近窗口验收
- **WHEN** 运维人员验收法国扩源上线效果
- **THEN** 系统 SHALL 能输出最近若干窗口内每个法国来源的抓取状态、新增数、重复数、入库状态和公开数

#### Scenario: 来源语言不受支持时不得生产批准
- **WHEN** 新法国来源的 `source_language` 尚未被翻译和改写链路支持
- **THEN** 该来源 SHALL 保持未生产批准或 deferred
- **AND** 审计输出 SHALL 标记语言链路不支持
