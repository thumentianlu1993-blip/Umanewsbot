## ADDED Requirements

### Requirement: HKJC 日语马名概念合并必须可审计且保守
系统 SHALL 提供 HKJC horse 术语的日语 alias 概念合并流程，将安全匹配的日语主术语并入对应 HKJC 英文概念，并对不安全项输出人工复核记录。

#### Scenario: dry-run 输出同目标合并候选
- **WHEN** active HKJC 英文 horse 术语与 active 日语 horse 主术语拥有相同规范化 `target_zh` 和相同 `term_type`
- **THEN** 系统 MUST 在 dry-run artifact 中输出该日语 source text 可并入目标英文概念的候选记录
- **THEN** 系统 MUST 不写入数据库

#### Scenario: apply 合并安全候选
- **WHEN** 操作者对 dry-run 中的安全候选显式执行 apply
- **THEN** 系统 MUST 将日语 source text 写入目标 HKJC 英文概念的 alias 集合
- **THEN** 系统 MUST 将冗余日语主术语停用或标记为已合并，并记录合并目标 term id
- **THEN** 系统 MUST 保持重复执行幂等，不创建重复 alias

#### Scenario: 冲突项不自动合并
- **WHEN** 日语 owner 的 `target_zh`、`term_type`、active 状态或概念归属与目标 HKJC 英文概念不一致
- **THEN** 系统 MUST 将该记录写入 skipped/review artifact，并包含可读跳过原因
- **THEN** 系统 MUST 不移动 alias、不停用术语、不修改目标概念

#### Scenario: apply 前重新校验当前状态
- **WHEN** dry-run 之后、apply 之前相关 term 或 alias 已发生变化
- **THEN** 系统 MUST 在 apply 时重新校验合并条件
- **THEN** 不再满足安全条件的记录 MUST 被跳过并写入 apply result

#### Scenario: active alias 被其它概念占用时跳过
- **WHEN** 待合并的日语 source text 已作为其它 active 概念的主原文或 active alias 存在
- **THEN** 系统 MUST 将该记录写入 skipped/review artifact，并包含占用方 term id
- **THEN** 系统 MUST 不在目标 HKJC 英文概念上创建重复 alias

### Requirement: 已发布文章术语回填必须精确且不重翻译
系统 SHALL 提供已发布文章的术语再应用流程，按过滤条件对中文字段执行字段级 source text 替换，并避免触发整篇重翻译或发布副作用。

#### Scenario: dry-run 输出字段级 diff
- **WHEN** 已发布文章的中文字段仍包含目标术语的 source text
- **THEN** 系统 MUST 在 dry-run artifact 中输出文章 ID、字段名、命中术语、完整 before/after 字段值、before/after 摘要和预期替换次数
- **THEN** 系统 MUST 不写入数据库

#### Scenario: apply 只替换明确命中的术语文本
- **WHEN** 操作者对已审核的 dry-run 结果显式执行 apply
- **THEN** 系统 MUST 仅在命中 source text 的文章字段中执行术语替换
- **THEN** 系统 MUST 使用正式术语的 `target_zh` 作为替换结果
- **THEN** 系统 MUST 保持不命中的字段不变

#### Scenario: 手工编辑字段受到保护
- **WHEN** 文章发布字段被记录在 `manually_edited_fields` 中
- **THEN** 系统 MUST 默认跳过该发布字段
- **THEN** 系统 MUST 在 artifact 中记录该字段因手工编辑而 skipped

#### Scenario: 回填不产生发布副作用
- **WHEN** 文章术语回填 apply 成功
- **THEN** 系统 MUST 不重新抓取、不重新翻译、不调用 AI 改写
- **THEN** 系统 MUST 不改变文章发布状态、审核状态、workflow 状态或 QQ 推送状态

#### Scenario: 回填支持受控批次
- **WHEN** 操作者指定 term、文章 ID、发布时间范围、来源语言或 limit 过滤条件
- **THEN** 系统 MUST 只扫描和修改过滤条件覆盖的文章
- **THEN** 系统 MUST 输出 summary artifact，记录扫描数、命中文章数、更新字段数和跳过数

#### Scenario: apply 拒绝无审核范围写入
- **WHEN** 操作者执行文章术语回填 apply 但未提供已审核 dry-run artifact 或显式过滤范围
- **THEN** 系统 MUST 拒绝写入并返回可读错误
- **THEN** 系统 MUST 不修改任何文章字段
