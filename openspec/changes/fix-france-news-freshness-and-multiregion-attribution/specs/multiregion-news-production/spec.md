## ADDED Requirements

### Requirement: 多地区生产必须分阶段开启归属写入与相关地区查询 <!-- id: req-attribution-rollout -->
系统 SHALL 将自动归属写入和相关地区查询分开灰度。代码部署后归属模式 MUST 默认为 `off`，相关地区查询开关 MUST 默认关闭；通过 gold set 和生产 dry-run 后，先将归属模式切到 `enforce` 处理新文章，观察至少 24 小时后才可为网页和测试 QQ 群开启相关地区查询。

#### Scenario: 代码部署不自动启用
- **WHEN** 新版本首次部署生产
- **THEN** 自动归属写入和相关地区查询 SHALL 保持关闭
- **AND** 旧单地区生产 SHALL 继续运行

#### Scenario: 测试群先验证相关地区
- **WHEN** 归属写入观察通过并准备开启相关地区查询
- **THEN** 系统 SHALL 先对网页和显式测试群启用
- **AND** 正式群 MUST 保持原地区行为直到验收通过

### Requirement: 多地区文章必须保持单次发布和单次 QQ 交付 <!-- id: req-single-publish-delivery -->
系统 MUST 只保存和公开一条文章记录。相关地区可见性 MUST NOT 创建文章副本、重复公开、重复 QQ 交付或消耗相关地区发布配额。

#### Scenario: 已由主地区发布的文章进入相关地区页
- **WHEN** 主地区文章已经公开且相关地区查询命中另一地区
- **THEN** 该文章 SHALL 在相关地区页可见
- **AND** MUST NOT 再次执行公开发布

#### Scenario: 多个群地区命中同一交付目标
- **WHEN** 同一 QQ 群因主地区和相关地区同时匹配文章
- **THEN** 系统 MUST 只创建一次该文章到该群的交付

### Requirement: 近期回填必须使用 manifest 且不重放副作用 <!-- id: req-recent-manifest-backfill -->
系统 SHALL 支持最近 72 小时文章归属、可信时间和翻译失败的分项 dry-run/commit。每项 commit MUST 绑定已审核 manifest、检查数据漂移并保持幂等；已发布文章 MUST NOT 因归属或时间回填重新发布或补推。

#### Scenario: 回填候选已发布
- **WHEN** 归属回填命中一篇已发布文章
- **THEN** 系统 MAY 更新允许的归属字段
- **AND** MUST NOT 修改原公开时间或创建 QQ 补推

#### Scenario: manifest 漂移
- **WHEN** 文章内容、状态、人工锁定或术语版本与 dry-run manifest 不一致
- **THEN** commit MUST 跳过或拒绝该文章
- **AND** SHALL 输出漂移原因

### Requirement: 法国生产效果必须分层验收 <!-- id: req-france-layered-volume -->
系统 SHALL 分别统计来源候选、去重后新文章、翻译成功、门禁通过、窗口入选、网页公开和 QQ 交付。上线后 SHALL 复核法国日常约 3–6 篇、重要赛事日前后约 6–10 篇的估算，但数量目标 MUST NOT 覆盖新鲜度、翻译、归属和发布硬门禁。

#### Scenario: 数量不足可定位原因
- **WHEN** 法国某日公开量低于估算
- **THEN** 系统 SHALL 展示损失发生在来源、去重、翻译、归属、门禁或窗口的具体层级

#### Scenario: 为达数量不得放宽硬门禁
- **WHEN** 法国候选不足
- **THEN** 系统 MUST NOT 自动提高新鲜度上限、绕过翻译失败或发布硬门禁
