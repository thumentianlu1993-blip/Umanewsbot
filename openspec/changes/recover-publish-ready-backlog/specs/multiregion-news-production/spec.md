## MODIFIED Requirements

### Requirement: 候选池补量 <!-- id: req-candidate-backlog-fill -->
系统 SHALL 在地区窗口新新闻不足时，同时从最近 3 小时实时候选和仍处于自动消费期限内的 `publish_ready` 积压候选补量。实时候选时间口径 SHALL 支持文章首次入库时间和 `ranked_revived_at` 榜单唤醒时间；积压候选 SHALL 以显式 `publish_ready_at` 为资格时钟，并保持查询、排序和每轮扫描有界。

#### Scenario: 本窗口新新闻不足
- **WHEN** 某地区本窗口只有 0 篇新候选但存在处于自动消费期限内的可发布积压候选
- **THEN** 系统 SHALL 允许使用积压候选补足软目标
- **AND** 候选仍 SHALL 经过统一硬门禁、去重、评分和配额

#### Scenario: 晚于入库时间进入发布就绪
- **WHEN** 某文章首次入库已超过 3 小时，但在最近 24 小时内完成完整校验并进入 `publish_ready`
- **THEN** 系统 SHALL 按 `publish_ready_at` 将其纳入积压候选通道
- **AND** 不得仅因 `first_seen_at` 过旧而永久漏掉

#### Scenario: 候选超过自动消费期限
- **WHEN** 某候选 `publish_ready_at` 已超过配置的自动消费期限
- **THEN** 系统 SHALL 不再自动发布该文章
- **AND** 系统 SHALL 将其展示为过期待复核并记录候选年龄

#### Scenario: 榜单唤醒候选进入实时窗口
- **WHEN** 某未发布文章首次入库时间已经超过实时回看窗口
- **AND** 该文章在最近 3 小时内被榜单二次命中唤醒
- **THEN** 系统 SHALL 允许发布窗口按榜单唤醒时间将该文章纳入实时候选

#### Scenario: 双通道候选重复
- **WHEN** 同一文章同时满足实时与积压通道条件
- **THEN** 系统 SHALL 只评估并发布该文章一次
- **AND** 窗口决策 SHALL 记录该文章命中的通道

## ADDED Requirements

### Requirement: 发布资格必须具有稳定时间戳 <!-- id: req-publish-ready-time -->
系统 MUST 在文章通过完整自动发布校验并进入 `publish_ready` 时保存 `publish_ready_at`。普通文章更新、抓取回看或审计写入 MUST NOT 刷新该时间。

#### Scenario: 新文章通过完整校验
- **WHEN** 文章从非 ready 状态完成评分与门禁并进入 `publish_ready`
- **THEN** 系统 SHALL 原子保存 `publish_ready_at`
- **AND** 发布窗口 SHALL 能按该时间查询候选

#### Scenario: 普通字段保存
- **WHEN** 工作人员或抓取任务更新与发布资格无关的字段
- **THEN** 系统 MUST NOT 因该保存刷新 `publish_ready_at`

#### Scenario: 已就绪文章重复校验
- **WHEN** 一篇已处于 publish_ready 的文章因重复任务再次通过相同校验
- **THEN** 系统 MUST NOT 默认刷新 `publish_ready_at`
- **AND** 只有榜单唤醒、人工批准或审核 manifest 恢复的显式意图可以刷新

### Requirement: 过期发布候选必须可见且不可突发公开 <!-- id: req-stale-ready-review -->
系统 SHALL 区分自动消费期限、人工复核期限和过期处置期限。超过自动期限的候选 MUST 不再自动公开，但 SHALL 在后台与生产审计中可见。

#### Scenario: 候选进入人工复核年龄
- **WHEN** 候选年龄超过 24 小时且不超过 72 小时
- **THEN** 系统 SHALL 将其列入过期待复核指标并触发有冷却的积压信号
- **AND** 发布窗口 SHALL NOT 自动公开该文章

#### Scenario: 候选超过过期处置年龄
- **WHEN** 候选年龄超过 72 小时
- **THEN** 系统 SHALL 要求显式重新校验或人工处置后才能重新进入自动消费期限
- **AND** 系统 SHALL NOT 自动把其时间刷新到当前时刻

### Requirement: 历史发布积压恢复必须绑定审核清单 <!-- id: req-backlog-recovery-manifest -->
系统 SHALL 为历史 `publish_ready` 积压提供 dry-run manifest。任何恢复 apply MUST 引用 manifest SHA、逐篇检查状态和内容漂移，并且不得在命令内直接公开或创建 QQ delivery。

#### Scenario: dry-run 生成历史候选清单
- **WHEN** 运维人员扫描超过自动期限的 publish_ready 文章
- **THEN** 系统 SHALL 输出文章 ID、地区、来源、候选年龄、门禁、内容指纹和建议处置
- **AND** dry-run SHALL 对文章零写入

#### Scenario: 审核后恢复仍具时效文章
- **WHEN** 已审核 manifest 批准某文章重新校验且文章未漂移
- **THEN** 系统 SHALL 运行完整门禁并仅在通过时刷新 `publish_ready_at`
- **AND** 文章 SHALL 等待正常发布窗口、去重和配额

### Requirement: 积压候选查询必须有界 <!-- id: req-backlog-query-bounded -->
系统 MUST 为实时和积压候选设置独立扫描上限并使用索引友好条件；不得在每个发布窗口加载全部历史 `publish_ready` 文章。

#### Scenario: 某地区积压超过扫描上限
- **WHEN** 某地区符合条件的积压候选超过单窗口扫描上限
- **THEN** 系统 SHALL 只加载有界候选集
- **AND** 系统 SHALL 记录剩余积压数量或截断标记供后续窗口继续处理
