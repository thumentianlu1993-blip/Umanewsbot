## ADDED Requirements

### Requirement: 单词型正式马名必须保留并按命中上下文解释
系统 SHALL 允许 `Brilliant`、`Something`、`Tuesday` 等普通英文词形成为合法正式马名或马名 alias。系统 MUST 保留这些正式概念，不得为了减少误挡而自动删除、停用或永久标记为普通词；发布门禁 MUST 使用文章中每次实际命中的上下文判断语义。

#### Scenario: 合法单词型马名不被清理
- **WHEN** 正式术语或结构化马匹数据证明某匹马的合法名称与普通英文词相同
- **THEN** 系统 MUST 保留该马名概念及安全 alias
- **AND** 普通词治理 MUST NOT 自动停用或删除该概念

#### Scenario: 术语类型只提供先验
- **WHEN** 文章命中 `term_type=horse` 的单词型正式术语
- **THEN** 术语类型 SHALL 作为上下文分类输入之一
- **AND** 系统 MUST NOT 仅凭 `term_type=horse` 判定当前命中一定是马名

#### Scenario: 结构化实体证据支持马名判断
- **WHEN** 命中文本可与马匹维表、参赛记录、赛果、国别后缀、骑师或练马师关系可靠对应
- **THEN** 系统 SHALL 将该证据提供给命中级分类器
- **AND** 审计结果 SHALL 记录证据类型和稳定实体标识

#### Scenario: alias 只影响实际命中的写法
- **WHEN** 同一正式术语包含多个英文 alias
- **AND** 当前文章只命中其中一个 alias
- **THEN** 系统 SHALL 按实际命中的 alias 和上下文分类
- **AND** 其他 alias 的普通词或专名结论 MUST NOT 自动覆盖本次命中

#### Scenario: 术语变化使后续索引失效
- **WHEN** 正式术语或 alias 被新增、更新、启停或合并
- **THEN** 后续校验批次 MUST 重建或命中新版本的术语匹配索引
- **AND** 系统 MUST NOT 长期使用无法识别该变化的陈旧索引
- **AND** 术语快照标识 MUST 由有效术语与 alias 的规范化关键字段生成，不得仅依赖单个最大更新时间
