## ADDED Requirements

### Requirement: 自动归属必须使用分层内容证据 <!-- id: req-attribution-evidence -->
系统 MUST 区分中心赛事发生地、核心对象所属地、上下文地区和来源 fallback。明确中心赛事发生地 SHALL 优先决定主地区；核心对象所属地 MAY 成为相关地区；普通地名、来源 URL、来源备注和背景履历 MUST NOT 单独决定主地区。

#### Scenario: 法国马参加英国赛事
- **WHEN** 文章中心是英国举办的赛事且核心法国马参赛
- **THEN** 系统 SHALL 将英国设为主地区
- **AND** SHALL 将法国保存为相关地区及对象证据

#### Scenario: 法国机构新闻无具体赛事
- **WHEN** 文章主题是 France Galop、法国育马场或法国拍卖且没有更强赛事中心
- **THEN** 系统 SHALL 将法国设为主地区

#### Scenario: 背景地名不改变主地区
- **WHEN** 法国只出现在血统、历史履历或普通背景段落
- **THEN** 系统 MUST NOT 仅凭该命中把法国加入主地区或相关地区

### Requirement: 归属结果必须包含置信度、正反证据和冲突状态 <!-- id: req-attribution-confidence -->
系统 SHALL 输出规则版本、主地区、相关地区、置信度、正反证据和 `applied|fallback|needs_review` 状态。证据不足或冲突时 MUST 保留当前主地区并转人工复核。

#### Scenario: 高置信度赛事归属自动应用
- **WHEN** 唯一赛事实体和赛场实体一致指向同一地区
- **THEN** 系统 SHALL 输出 high confidence
- **AND** MAY 自动应用主地区和可信相关地区

#### Scenario: 多个赛事中心冲突
- **WHEN** 文章同时出现多个互斥赛事中心且无法识别文章中心
- **THEN** 系统 SHALL 输出 `needs_review`
- **AND** MUST NOT 自动改变现有主地区

### Requirement: 自动归属必须防止无依据过度扩散 <!-- id: req-attribution-spread -->
系统 MUST NOT 因弱命中自动把文章扩散到多个地区。当自动候选相关地区超过 3 个、主地区离开来源地区但没有强证据，或多个弱上下文互相冲突时，系统 SHALL 转人工复核。

#### Scenario: 单篇出现四个弱地区
- **WHEN** 正文背景中出现四个地区但没有唯一中心赛事或主题对象
- **THEN** 系统 SHALL 标记 `needs_review`
- **AND** MUST NOT 自动写入四个相关地区

#### Scenario: 强证据支持真实三地区
- **WHEN** 文章中心赛事和两个核心对象分别有可解释的三个地区强证据
- **THEN** 系统 MAY 保存三个地区
- **AND** SHALL 在审计中逐项展示证据

### Requirement: 多地区归属必须通过版本化真实样本质量门槛 <!-- id: req-attribution-quality -->
系统 SHALL 维护至少 250 篇五地区 gold set，五地区各不少于 40 篇且跨地区样本不少于 50 篇。生产启用前总体主地区准确率 MUST 不低于 95%，单地区 MUST 不低于 90%，相关地区 precision MUST 不低于 95%，recall MUST 不低于 90%，无依据主地区变更 MUST 不高于 2%，过度扩散率 MUST 不高于 1%，人工锁定覆盖 MUST 为 0。

#### Scenario: 指标全部达标
- **WHEN** 当前规则版本在完整 gold set 上达到全部门槛
- **THEN** 系统 MAY 进入生产 shadow 验收
- **AND** SHALL 保存逐样本结果和汇总指标

#### Scenario: 任一地区准确率不足
- **WHEN** 总体指标达标但某单地区主地区准确率低于 90%
- **THEN** 系统 MUST 判定不具备生产启用资格
- **AND** 归属模式 SHALL 保持 `off`，相关地区查询开关 SHALL 保持关闭

#### Scenario: 样本漂移导致分母不足
- **WHEN** 输入快照缺失或 SHA 漂移导致任一地区有效已裁决样本少于 40 篇
- **THEN** 系统 MUST 判定 no-go
- **AND** SHALL 报告缺失、漂移和未裁决样本

### Requirement: 生产 dry-run 必须覆盖所有主地区变化和待复核项 <!-- id: req-attribution-dry-run -->
系统 SHALL 对近期真实文章输出 before/after、证据、置信度和状态。启用前 MUST 人工抽检全部主地区变化、全部 `needs_review` 和按地区分层随机样本。

#### Scenario: 生产 dry-run 不写数据
- **WHEN** 运维对最近 72 小时文章运行归属 dry-run
- **THEN** 系统 SHALL 输出完整差异和指标
- **AND** SHALL NOT 修改文章或相关地区记录

#### Scenario: 人工锁定不可覆盖
- **WHEN** dry-run 或 commit 遇到 `attribution_locked=true` 的文章
- **THEN** 系统 MUST 保留人工主地区和相关地区
- **AND** SHALL 在报告中标记 locked skip

### Requirement: 多地区归属必须使用单一运行模式 <!-- id: req-attribution-mode -->
系统 SHALL 使用 `off|shadow|enforce` 单一模式控制自动归属。`off` MUST 跳过推断，`shadow` SHALL 只保存审计结果而不修改主地区和关联地区，`enforce` MAY 写入归属。相关地区查询 MUST 仅在 enforce 且独立查询开关开启时生效。

#### Scenario: shadow 不改变地区
- **WHEN** 生产运行模式为 shadow
- **THEN** 系统 SHALL 保存推断结果、规则版本和置信度
- **AND** MUST NOT 修改 `racing_region` 或 `NewsArticleRelatedRegion`

#### Scenario: shadow 不覆盖权威审计
- **WHEN** 文章已有 enforce 或人工应用的归属审计后切入 shadow
- **THEN** 系统 SHALL 将新推断写入独立 shadow 命名空间
- **AND** MUST NOT 覆盖 applied/人工审计内容

#### Scenario: 旧布尔配置兼容
- **WHEN** 新 mode 变量未配置而旧归属布尔开关存在
- **THEN** 系统 SHALL 将旧 true 映射为 enforce、旧 false 映射为 off
- **AND** 新 mode 变量存在时 SHALL 优先使用新值

### Requirement: 归属质量运行和 commit 必须持久化锁定 <!-- id: req-attribution-run-ledger -->
系统 SHALL 持久化每次 dry-run 的 selectors、规则/术语/gold 版本、候选指纹、指标、outcomes 和 manifest，并使用可续租数据库 lease 防止同类运行并发。commit MUST 引用成功 dry-run ID 与 manifest，并逐文章校验漂移和人工锁定。

#### Scenario: runtime 文件不是唯一凭证
- **WHEN** dry-run 同时输出 runtime JSON
- **THEN** 数据库运行账本 SHALL 作为 commit 的权威状态
- **AND** runtime JSON SHALL 仅作为可读导出

#### Scenario: 重复 commit 幂等
- **WHEN** 已成功提交的 run 使用相同 manifest 再次 commit
- **THEN** 系统 SHALL 返回已提交结果
- **AND** MUST NOT 重复修改文章、发布或推送

#### Scenario: commit 中途失败后续跑
- **WHEN** commit 在部分文章完成后因异常中断
- **THEN** 系统 SHALL 保存 cursor、已完成 ID 和逐篇 outcome
- **AND** 使用同一 run ID 与 manifest 恢复时 MUST 跳过已完成文章并继续剩余候选

### Requirement: 批量归属必须满足性能门槛 <!-- id: req-attribution-performance -->
系统 SHALL 在批量评估中一次预加载并复用术语、alias 和赛事证据快照，避免逐文章全量 ORM 查询。250 篇 PostgreSQL 基准 MUST 不超过 30 条 SQL、30 秒和 256 MiB RSS 增量。

#### Scenario: 批量基准超标
- **WHEN** 当前规则版本处理 250 篇基准超过任一性能门槛
- **THEN** 系统 MUST 判定生产 no-go
- **AND** SHALL 输出 SQL、耗时、内存和预加载计数
