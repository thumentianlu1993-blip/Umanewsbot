# contextual-news-entity-resolution Specification

## Purpose
TBD - created by archiving change contextualize-news-entity-resolution. Update Purpose after archive.
## Requirements
### Requirement: 新闻实体必须形成统一文章级解析结果
系统 SHALL 对文章标题和正文生成统一、确定性、带原文跨度的实体解析结果，并区分人物、马名、普通词和需要整体保留的未知完整马名。翻译、标签、发布校验和自动马匹关联 MUST 使用该结果，不得各自以不一致的裸字符串命中重新判定实体类型。

#### Scenario: 同一命中被多个消费点使用
- **WHEN** 文章级解析器把某个跨度判定为人物或普通词
- **THEN** 翻译术语表、马名标签、发布马名校验和自动马匹关联 SHALL NOT 再把该跨度当成马名
- **AND** 解析摘要 SHALL 记录实体类型、原文跨度和判定证据

#### Scenario: 解析结果重复执行
- **WHEN** 系统以相同文章文本、术语库和外部别名索引重复执行解析
- **THEN** 系统 SHALL 返回相同的实体顺序、跨度、类型和冲突标记

### Requirement: 完整实体跨度必须优先于内部短术语
系统 SHALL 在重叠候选中优先接受证据充分的完整人物名或完整马名。一个完整跨度被接受后，其内部较短的马名、父马名、冠名或普通术语 MUST NOT 独立触发翻译替换、未知马名保护、标签或自动关联。

#### Scenario: 完整日文马名包含父马名
- **WHEN** 原文在马名语境中出现 `ノリヤンモーニン`，且只有内部 `モーニン` 存在正式译名
- **THEN** 系统 SHALL 将 `ノリヤンモーニン` 作为一个完整未知马名
- **AND** 系统 MUST NOT 输出 `ノリヤン爵士蓝调`

#### Scenario: 完整日文马名包含冠名或短术语
- **WHEN** 原文出现 `マドモアゼルアスク`、`プティフォリー`、`ルアーヴル` 或包含 `ユーロ` 的完整专名
- **THEN** 系统 SHALL 优先保护完整跨度
- **AND** 系统 MUST NOT 在该跨度内部执行局部中文替换

### Requirement: 英文人物语境和篇内姓氏回指必须压制马名误识别
系统 SHALL 使用正式人物术语及任职、职业、发言等明确人物语境识别英文完整人名。确认完整人物后，系统 SHALL 在同篇文章中把后续无歧义的姓氏简称回指到该人物；人物跨度及其回指 MUST NOT 被识别为马名。

#### Scenario: 正式人物后续使用姓氏
- **WHEN** 同篇文章先出现正式人物术语 `Donnacha O'Brien → 岳品贤`
- **AND** 后文以 `O'Brien` 唯一回指该人物
- **THEN** 翻译术语 SHALL 将后续 `O'Brien` 解析为岳品贤
- **AND** 系统 SHALL NOT 把 `O'Brien` 作为独立马名

#### Scenario: 任职语境中的完整人名
- **WHEN** 原文包含 `Grace Hamilton has joined Four Star Sales as Bloodstock and Sales Coordinator`
- **THEN** 系统 SHALL 把 `Grace Hamilton` 判定为人物
- **AND** 系统 SHALL NOT 因内部 `Hamilton` 命中马名术语而生成马标签或马匹关联

#### Scenario: 同姓对应多个人物
- **WHEN** 同篇文章存在两个可由同一姓氏简称指代的人物
- **THEN** 系统 SHALL 将单独姓氏保持为歧义而不自动回指
- **AND** 系统 SHALL NOT 据此生成确定性人物译名替换

### Requirement: 普通词同形马名必须依赖强马名上下文
系统 SHALL 对英文普通词、短语和高歧义马名术语执行上下文判定。只有出马表、赛果、血统、性龄、赔率、明确参赛或胜负等强马名证据存在时才能把同形文本判定为马名；普通叙述语境 MUST 判为普通词。

#### Scenario: 普通叙述中的同形词
- **WHEN** 原文包含 `the years roll on`、`more than enough time` 或文章 8330 中的普通叙述词组
- **THEN** 系统 SHALL NOT 为其中同形马名生成翻译术语、标签或自动关联

#### Scenario: 8086 普通词与真实马名并存
- **WHEN** 文章 8086 同时包含普通语境中的 `够分量`、`好年月`、`常联系`、`加快步`、`有效数字`、`连捷`、`乐观正面`、`先兆`、`猎鹰五月` 和真实马名 `多爵`
- **THEN** 系统 SHALL 只保留有强马名证据的 `多爵` horse 实体
- **AND** 其他列举文本 SHALL NOT 生成机器马标签或自动关联

#### Scenario: 8330 全部旧马名标签来自普通词
- **WHEN** 文章 8330 的旧识别马名在逐个上下文判断后均属于普通词
- **THEN** 当前机器 horse entity 和机器马标签 SHALL 为空
- **AND** 系统 SHALL 清理有 provenance 或显式目标 legacy 的旧机器马标签

#### Scenario: 强马名语境中的同形词
- **WHEN** 同形词出现在出马表、赛果、赔率、父母血统或明确参赛/胜负语境
- **THEN** 系统 MAY 将其判为马名
- **AND** 解析结果 SHALL 记录允许升级的强上下文证据

### Requirement: 实体解析必须支持显式历史文章重处理
系统 SHALL 提供按显式文章 ID 执行的实体、标签和自动关联重处理能力，默认 dry-run。提交模式 SHALL 保护人工字段、人工或已移除关联、公开文章身份、原发布时间和 QQ 幂等状态。

#### Scenario: dry-run 指定问题文章
- **WHEN** 运维人员对问题文章运行实体重处理但未提供 commit 参数
- **THEN** 系统 SHALL 输出实体类型、跨度、术语、标签、自动关联及前后差异
- **AND** 系统 SHALL NOT 修改数据库

#### Scenario: 提交已发布文章重处理
- **WHEN** 运维人员显式提交问题文章的机器实体结果并同步重译
- **THEN** 系统 SHALL 保持公开文章 ID、公开状态和原发布时间
- **AND** 系统 SHALL NOT 创建新的 QQ delivery
- **AND** `tags_json` 人工锁定及 `ArticleHorseLink` 的人工或移除决定 SHALL 保持不变

#### Scenario: 多篇重处理中单篇失败
- **WHEN** 显式重处理多篇文章且其中一篇在标签或关联写回时失败
- **THEN** 系统 SHALL 回滚失败文章的全部实体写入
- **AND** 其他文章的成功或失败结果 SHALL 独立记录并可审计

#### Scenario: 清除过时自动马匹关联
- **WHEN** 显式文章重处理确认旧 `AUTO` 或 `CANDIDATE` 马匹关联不再对应任何接受的 horse 实体
- **THEN** dry-run SHALL 报告该待删除关联
- **AND** commit SHALL 删除该过时自动关联
- **AND** 同文章的 `MANUAL` 或 `REMOVED` 关联 SHALL 保持不变

### Requirement: 批量实体解析和关联必须有界
系统 SHALL 按文章原文候选预加载相关术语、别名和马匹 Profile，不得对每篇文章扫描全部英文外部别名或执行全马匹与全文章笛卡尔匹配。

#### Scenario: 二十篇文章批量解析
- **WHEN** 系统批量解析 20 篇英文或日文文章
- **THEN** 术语与外部别名查询数量 SHALL 保持在预先声明的固定上限内
- **AND** 查询数量 SHALL NOT 随文章数线性增长

#### Scenario: 单篇自动关联
- **WHEN** 系统为一篇文章重算自动马匹关联
- **THEN** 系统 SHALL 先按接受实体的 term ID、外部 horse ID 或规范化名称筛选候选 Profile
- **AND** 系统 MUST NOT 遍历全部已发布马匹后逐一做全文字符串匹配

