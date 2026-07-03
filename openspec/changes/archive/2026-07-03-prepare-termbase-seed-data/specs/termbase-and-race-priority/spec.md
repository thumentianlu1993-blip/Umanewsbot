## ADDED Requirements

### Requirement: 术语种子候选必须兼容正式术语导入
系统 SHALL 允许经过人工审核的术语种子候选继续使用现有正式术语导入流程。种子候选主表 MUST 使用 `term_type,source_language,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade` 字段，并且 `target_zh` 与 `aliases_zh` 中的中文内容 MUST 为简体中文。

#### Scenario: 种子候选通过正式术语 dry-run
- **WHEN** 工作人员将人工审核后的 `seed_candidates.csv` 交给 `import_terms --dry-run`
- **THEN** 系统 SHALL 使用现有术语导入校验执行预检
- **AND** 不要求额外转换字段或专用导入命令

#### Scenario: 繁体译名不得作为目标中文入库
- **WHEN** 种子候选来源提供繁体中文译名
- **THEN** 审核后的正式导入文件 SHALL 使用简体中文作为 `target_zh`
- **AND** 原始繁体写法 MAY 保留在 `source_ja`、`aliases_ja`、`aliases_zh` 或 `notes` 中，具体取决于该行的 `source_language` 和人工审核结果

#### Scenario: 多语言候选按现有原文语言校验
- **WHEN** 种子候选包含英文、繁体中文或日文原文
- **THEN** 系统 SHALL 按现有 `source_language` 校验和导入规则处理
- **AND** 同一术语概念的多语言原文 MAY 通过多行候选或后续别名合并表达
