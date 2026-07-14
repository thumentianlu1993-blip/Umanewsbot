# termbase-and-race-priority Specification Delta

## ADDED Requirements

### Requirement: 翻译术语与确定性替换必须使用上下文实体结果
系统 SHALL 只把文章级实体解析接受的术语加入翻译 prompt、`TranslationRun.terms_used`、翻译元数据和确定性译后替换。人物或普通词跨度中的同形马名术语，以及被完整实体压制的内部短术语 MUST NOT 参与替换。

#### Scenario: 同一人物的姓氏回指进入翻译术语
- **WHEN** 文章级解析把后续 `O'Brien` 回指到正式人物术语 `Donnacha O'Brien → 岳品贤`
- **THEN** 翻译 prompt SHALL 包含该篇内回指映射
- **AND** 最终正文 SHALL 对同一人物使用一致译名

#### Scenario: 普通词马名不进入翻译术语
- **WHEN** 文章级解析把 `more than enough` 或 `years` 判定为普通词
- **THEN** 翻译 prompt、确定性替换和翻译元数据的 horse terms SHALL NOT 包含该命中

#### Scenario: TranslationRun 与最终翻译元数据一致
- **WHEN** 系统为文章创建或完成一次 `TranslationRun`
- **THEN** `terms_used` SHALL 与该次翻译 metadata 的接受术语使用同一文章级解析结果
- **AND** 外层任务 SHALL NOT 再用旧裸字符串解析生成不同术语列表

### Requirement: 未知完整马名保护必须先于内部术语映射
系统 SHALL 在构建翻译 prompt 和执行任何确定性术语映射前保护已确认的完整未知马名跨度，并在译后恢复完整原文。保护范围 MUST 覆盖该跨度内部所有短术语。

#### Scenario: 完整马名保护阻止局部替换
- **WHEN** `マドモアゼルアスク` 被解析为未知完整马名且内部 `アスク` 存在中文映射
- **THEN** 系统 SHALL 先把完整马名替换为单一保护占位符
- **AND** 系统 SHALL 在恢复占位符前完成上下文接受术语的确定性映射
- **AND** 译文 SHALL 最后恢复为 `マドモアゼルアスク`，不得出现 `マドモアゼル请问`

### Requirement: 机器马名标签必须复用文章级实体结果
系统 SHALL 只从文章级解析接受的 horse 实体生成机器马名标签，并在既有翻译元数据中记录本轮机器标签 provenance。重算机器标签时 SHALL 移除有 provenance 的旧机器马标签并加入当前结果，同时保留来源默认/非马标签；旧文章无 provenance 时只有显式目标文章修复可按 active 马名译词列出并清理 legacy 候选。人工锁定标签 MUST NOT 被覆盖，内容强制重译不得改变该规则。

#### Scenario: 正文翻译正确但旧标签误标
- **WHEN** 正文中的 `more than enough time` 已按普通句翻译，但旧 `tags_json` 包含同形马名中文标签
- **THEN** 显式机器标签重算 SHALL 删除该错误马标签
- **AND** 系统 SHALL NOT 因裸字符串术语命中再次添加该标签

#### Scenario: 人工标签被锁定
- **WHEN** `tags_json` 已列入 `manually_edited_fields`
- **THEN** 自动翻译或实体重处理 SHALL NOT 修改该字段
- **AND** 内容字段使用强制重译参数时也 SHALL NOT 覆盖人工标签
