## ADDED Requirements

### Requirement: 日本候选有 netkeiba key 时必须经 netkeiba ID 直取抓取

系统 SHALL 为携带 `netkeiba:{id}` identity key 的日本候选直接抓取 netkeiba 马匹页、战绩页与血统页，MUST NOT 依赖名称检索消歧；payload 的 netkeiba ID 与候选 key 完全一致才构成 provider-bound 身份；页面马名与候选名规范化不一致时系统 SHALL fail closed 并记录身份冲突。无 netkeiba key 的候选 SHALL 保持既有 JBIS 检索路径。页面结构无法识别时系统 SHALL 记录不可解析并 fail closed，MUST NOT 猜测字段值。

#### Scenario: ID 直取无检索歧义

- **WHEN** 某日本候选携带 `netkeiba:{id}` key 且 JBIS 名称检索存在同名马
- **THEN** 系统 SHALL 经 netkeiba ID 直取页面完成 prepare，身份锁按 provider-bound 通过
- **AND** 页面提取的父母、出生日期 SHALL 满足四字段口径

#### Scenario: 马名不符 fail closed

- **WHEN** netkeiba 页面马名与候选名规范化比对不一致
- **THEN** 系统 MUST NOT 写入该候选的任何字段，并记录身份冲突

#### Scenario: 生涯总数与逐场数对账

- **WHEN** 马匹页的通算成績总数与战绩页逐场记录数不一致
- **THEN** 系统 SHALL 记录生涯缺口，MUST NOT 标记生涯完整

#### Scenario: 结构变化 fail closed

- **WHEN** 页面结构无法被解析器识别（缺表、改版）
- **THEN** 系统 SHALL 记录不可解析并阻断该候选，MUST NOT 猜测字段值

#### Scenario: 已注销马标题按精确状态词解析

- **WHEN** netkeiba 标题使用 `抹消　牡　黒鹿毛` 等已知已注销状态形态
- **THEN** 系统 SHALL 独立解析状态、性别和毛色并继续处理候选
- **AND** 未知状态、性别或毛色仍 SHALL fail closed，MUST NOT 通过宽松正则猜测字段

#### Scenario: 候选部分期望身份字段保持完整锁并给出字段级诊断

- **WHEN** 候选仅携带父名、母名或出生年中的部分期望字段
- **THEN** 系统 SHALL 保持完整四字段期望锁、阻断候选并记录候选缺少的具体期望字段
- **AND** 系统 MUST NOT 以空值、默认值或同名推断补齐身份

#### Scenario: 解析器规则变化不得复用旧 checkpoint

- **WHEN** netkeiba 解析语义版本发生变化且旧批次已有 succeeded staging
- **THEN** 系统 SHALL 使批次输入指纹发生变化或拒绝旧 approval binding
- **AND** 运维人员 SHALL 通过 abandon 后重新 select/approve 建立新批次，不得手改 `state.json`

#### Scenario: 旧版 netkeiba canonical cache 不得绕过新解析器

- **WHEN** netkeiba canonical cache 缺少当前 parser version 或版本不匹配
- **THEN** 系统 SHALL 将其视为 cache miss，并在网络门禁与预算允许时重新抓取三页
- **AND** 刷新成功后 SHALL 并发安全地原子替换 stale cache，当前调用与竞争调用均只使用同一份当前版本 canonical payload
- **AND** 该规则 MUST NOT 改变 JBIS 或其他地区的既有 cache 兼容语义
