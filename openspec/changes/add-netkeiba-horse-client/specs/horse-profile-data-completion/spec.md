## ADDED Requirements

### Requirement: 日本候选有 netkeiba key 时必须经 netkeiba ID 直取抓取

系统 SHALL 为携带 `netkeiba:{id}` identity key 的日本候选直接抓取 netkeiba 马匹页与战绩页，MUST NOT 依赖名称检索消歧；payload 的 netkeiba ID 与候选 key 完全一致才构成 provider-bound 身份；页面马名与候选名规范化不一致时系统 SHALL fail closed 并记录身份冲突。无 netkeiba key 的候选 SHALL 保持既有 JBIS 检索路径。页面结构无法识别时系统 SHALL 记录不可解析并 fail closed，MUST NOT 猜测字段值。

#### Scenario: ID 直取无检索歧义

- **WHEN** 某日本候选携带 `netkeiba:{id}` key 且 JBIS 名称检索存在同名马
- **THEN** 系统 SHALL 经 netkeiba ID 直取页面完成 prepare，身份锁按 provider-bound 通过
- **AND** 页面提取的父母、出生日期 SHALL 满足四字段口径

#### Scenario: 马名不符 fail closed

- **WHEN** netkeiba 页面马名与候选名规范化比对不一致
- **THEN** 系统 MUST NOT 写入该候选的任何字段，并记录身份冲突

#### Scenario: 生涯总数与逐场数对账

- **WHEN** 战绩页生涯总数与逐场记录数不一致
- **THEN** 系统 SHALL 记录生涯缺口，MUST NOT 标记生涯完整

#### Scenario: 结构变化 fail closed

- **WHEN** 页面结构无法被解析器识别（缺表、改版）
- **THEN** 系统 SHALL 记录不可解析并阻断该候选，MUST NOT 猜测字段值
