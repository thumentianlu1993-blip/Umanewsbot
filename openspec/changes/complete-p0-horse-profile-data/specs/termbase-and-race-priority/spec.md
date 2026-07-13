## ADDED Requirements

### Requirement: 马名术语必须支持暂无中文译名状态
系统 SHALL 允许 active horse `TermEntry` 暂无中文译名。暂无中文译名的马名术语 MUST 可用于实体识别、P0 马资料补全、新闻马名保护和文章/马匹关联，但 MUST NOT 被当作可中文替换术语。

#### Scenario: 创建暂无中文译名马名术语
- **WHEN** 系统从重点赛事参赛马或人工录入创建 horse `TermEntry`
- **AND** 尚无合适中文译名
- **THEN** 系统 SHALL 允许 `target_zh` 为空或等价无译名状态
- **AND** 该术语 SHALL 能保持 active 以参与实体识别

#### Scenario: 无译名术语不参与中文替换
- **WHEN** 术语应用、翻译后处理或改写后处理遇到暂无中文译名的 horse term
- **THEN** 系统 SHALL NOT 将原文替换为空值或占位中文
- **AND** 系统 SHALL 将其加入原文保留名单

#### Scenario: 有译名后升级为普通正式术语
- **WHEN** 管理员为暂无中文译名的 horse term 补充正式中文译名
- **THEN** 系统 SHALL 将该术语视为可中文替换术语
- **AND** 继续保留原有别名、地区、P0 来源和审计信息

#### Scenario: 同一马匹支持多语种名称识别
- **WHEN** 同一 horse term 具有外文主名、中文译名或其它语言 `TermAlias`
- **THEN** 实体识别和马匹身份匹配 SHALL 将这些名称解析为同一术语概念

#### Scenario: 同一原名对应多个马匹术语
- **WHEN** 同一语言原名命中多个 active horse term
- **THEN** 系统 MUST 保留原文并标记马名歧义
- **AND** 系统 MUST NOT 任意选择其中一个中文译名做替换

### Requirement: 翻译必须保留暂无中文译名的已知马名原文
系统 SHALL 在翻译提示、占位符保护和译后校验中识别暂无中文译名的已知 horse term。命中这类术语时，最终译文 MUST 至少保留一次原文。

#### Scenario: 正文命中无译名马名
- **WHEN** 原文正文命中暂无中文译名的 horse term
- **THEN** 翻译结果 SHALL 至少一次包含该马名原文
- **AND** 校验失败时 SHALL 触发重试或 blocker

#### Scenario: 标题命中无译名马名
- **WHEN** 原文标题命中暂无中文译名的 horse term
- **THEN** 翻译结果 SHALL 在标题或正文首段保留该马名原文

#### Scenario: 有译名术语继续使用中文译法
- **WHEN** 原文命中已有中文译名的 horse term
- **THEN** 翻译结果 SHALL 继续优先使用正式中文译名或可接受中文别名
- **AND** 不得因本需求降级为仅保留原文

### Requirement: 术语门禁必须区分中文译名保留和原文保留
系统 SHALL 在发布校验中区分有中文译名术语和暂无中文译名术语。有中文译名术语继续校验中文译名或别名稳定保留；暂无中文译名 horse term 校验原文保留。

#### Scenario: 无译名 horse term 未保留原文
- **WHEN** 原文命中暂无中文译名的 horse term
- **AND** 发布稿未保留该马名原文
- **THEN** 系统 SHALL 记录原文未保留问题
- **AND** 核心位置命中 SHOULD 阻断自动发布或转人工审核

#### Scenario: 无译名 horse term 不产生中文译名缺失 blocker
- **WHEN** 原文命中暂无中文译名的 horse term
- **THEN** 系统 SHALL NOT 因缺少 `target_zh` 生成中文译名缺失 blocker
- **AND** 校验重点 SHALL 转为原文保留
