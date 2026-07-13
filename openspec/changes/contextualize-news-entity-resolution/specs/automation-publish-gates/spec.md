# automation-publish-gates Specification Delta

## ADDED Requirements

### Requirement: 发布门禁必须校验正文与机器实体类型一致
系统 SHALL 使用文章级实体解析结果检查翻译术语、机器马名标签和自动马匹关联。批量校验上下文 SHALL 预计算并携带同一实体结果及接受术语 ID，不得在校验阶段重新运行旧识别。人物或普通词不得以马名形式进入任一机器输出；同一已接受马名在正文、标签和关联中的类型 SHALL 一致。

#### Scenario: 普通词批量误标
- **WHEN** 一篇文章的全部马名标签都来自被解析为普通词的跨度
- **THEN** 系统 SHALL 将这些标签视为机器实体不一致
- **AND** 自动发布 SHALL 在完成机器标签重算前阻止或转人工处理

#### Scenario: 人物被标记成马
- **WHEN** `Grace Hamilton` 被解析为人物但机器标签或自动关联包含内部 `Hamilton` 马名
- **THEN** 系统 SHALL 记录实体类型不一致问题
- **AND** 该马名标签或自动关联 SHALL NOT 进入最终机器输出

### Requirement: 实体修复后必须支持受控重新校验
系统 SHALL 允许对显式文章 ID 在实体、翻译和机器标签修复后重新运行完整发布校验。重新校验 MUST 保留其他真实 blocker，不得因清除误识别而自动绕过人工终态或直接重复发布。

#### Scenario: 误识别清除后仍有其他 blocker
- **WHEN** 文章的普通词马名误识别已清除但仍存在其他 blocker
- **THEN** 系统 SHALL 保留其他 blocker 和人工处理状态

#### Scenario: 已发布文章只更新内容
- **WHEN** 已发布问题文章完成实体修复、重译和重新校验
- **THEN** 系统 SHALL 保持既有公开状态和发布时间
- **AND** 系统 SHALL NOT 重新占用发布配额或创建 QQ delivery
