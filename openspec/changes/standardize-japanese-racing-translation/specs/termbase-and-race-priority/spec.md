## ADDED Requirements

### Requirement: 日英机构名称必须归入同一中文术语概念
系统 SHALL 使用 `TermAlias` 把同一日本机构或场所的日文名和英文名绑定到同一 `TermEntry`，不得为不同语言重复创建概念。

#### Scenario: 社台日英名称
- **WHEN** 术语迁移处理日文 `社台` 和英文 `Shadai`
- **THEN** 两个来源名 SHALL 解析到同一中文目标“社台”

#### Scenario: 北方马公园日英名称
- **WHEN** 术语迁移处理日文 `ノーザンホースパーク` 和英文 `Northern Horse Park`
- **THEN** 两个来源名 SHALL 解析到同一中文目标“北方马公园”

### Requirement: 精选拍卖会与普通片假名词必须提供稳定译法
系统 SHALL 以固定译法术语保存 `セレクトセール` 及本 change 明确列出的日文普通赛马词，并带非马名标记。

#### Scenario: 精选拍卖会术语
- **WHEN** 日文文章出现 `セレクトセール`
- **THEN** 翻译术语 SHALL 使用“精选拍卖会”
- **AND** 较短的 `セール` SHALL NOT 覆盖该最长命中

#### Scenario: 普通词不是马名
- **WHEN** 本 change 新增的普通片假名词同时与既有或未来马名同形
- **THEN** 普通句子中的命中 SHALL 作为 `fixed_phrase` 使用
- **AND** 只有文章级解析确认强马名语境时才可接受马名实体

### Requirement: 术语数据迁移必须幂等且冲突即失败
系统 MUST 可重复执行术语种子逻辑而不创建重复概念或别名，并保护既有人工数据。

#### Scenario: 首次写入空术语库
- **WHEN** 数据库尚无本 change 的术语和别名
- **THEN** 迁移 SHALL 创建唯一术语概念及对应日英别名

#### Scenario: 相同目标已经存在
- **WHEN** 迁移发现相同术语概念、中文目标和别名已存在
- **THEN** 迁移 SHALL 保持幂等且不创建重复记录

#### Scenario: 既有人工概念冲突
- **WHEN** 相同来源名或别名已指向不同中文目标或另一术语概念
- **THEN** 迁移 MUST 明确失败
- **AND** 迁移 MUST NOT 静默覆盖或合并人工数据
