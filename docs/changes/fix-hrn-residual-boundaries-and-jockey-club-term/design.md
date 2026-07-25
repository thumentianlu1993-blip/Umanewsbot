# 设计

## 当前链路

`HRN HTML -> HorseRacingNationAdapter(.article-body) -> clean_international_article_body -> body_ja_raw/body_ja_normalized -> entity resolution/translation prompt -> translated fields -> review/apply -> public/QQ`

此前边界修复阻止了页面外导航进入正文，但 `.article-body` 自身还包含赛马卡片的 Bootstrap modal。通用文本抽取会递归读取 modal header 和关闭按钮，因此输出 `Race Video ×`。

生产术语库同时存在 `The Jockey Club -> 英国赛马会` 的英国机构词条。英文翻译会把已解析术语放入 glossary，并在模型输出后再次执行映射；HRN 美国文章因此被错误地套用英国机构译名。

## 方案 A：来源级结构清洗

在 `server/stable/services/article_content.py` 增加 HRN 专属结构噪声选择器：

- `[role='dialog']`

清洗器在调用 `extract_article_text` 前删除命中节点，并记录 `hrn_structured_noise`。选择结构语义而不是显示文本，可覆盖当前 `#last-race-modal.modal[role=dialog]`，同时不会删除普通段落中的同词。

不将 `.modal` 文本或 `Race Video` 加入通用正则；若未来存在没有 dialog 语义的新控件，应以真实 DOM 证据另行扩展。

## 方案 B：HRN 来源级机构保护

在 provider 共用的确定性术语占位符阶段增加极窄映射：

`(source_site=horse_racing_nation, source_language=en, source_text=The Jockey Club) -> 美国赛马会`

新增 provider 共用的 `SourceTermPlaceholderPlan`（名称可等价），并复用现有
`__UMA_TERM_n__` 校验、重试和恢复链：

1. 用大小写不敏感的边界表达式
   `(?<![A-Za-z0-9])The\s+Jockey\s+Club(?![A-Za-z0-9])`
   扫描 HRN 标题和正文，记录每个字段的出现次数；不使用 `str.replace` 做识别；
2. 先收集来源级机构映射，再收集现有人物 TERM 映射；相同源词由来源级映射覆盖；
3. 两类映射按“源词长度降序、规范源词、目标词”统一稳定排序和编号，保证
   `__UMA_TERM_n__` 无碰撞；
4. 从普通 glossary 中排除被来源计划覆盖的 `The Jockey Club => 英国赛马会`，并在
   生成文本的普通后处理映射中跳过同一源词，避免模型前后出现冲突；
5. prompt 把 TERM 描述改为“确定性术语占位符”，明确可包含人物和来源机构；
6. OpenAI-compatible provider 必须按标题/正文的原始出现次数返回占位符；删除、跨字段移动、
   篡改或伪造继续 fail closed。摘要可以复制来源中已有的占位符，但不得发明编号；
7. 输出阶段把 TERM 占位符恢复为对应中文；来源计划 metadata 单独记录
   `source_site/source_text/target_zh/field_counts`；
8. Dummy provider 在执行普通 contextual mapping 前应用同一计划，并跳过冲突普通 term，
   再确定性恢复；它不经过模型，故不需要模型响应校验，但输出不得产生英国误译。

不修改生产中现有英国词条，也不新增全局数据迁移。这样英国来源仍保持原义，HRN 的美国机构则由来源上下文消歧。

## 数据与状态

- 无模型字段、schema 或 migration 变更。
- 新采集从代码发布后生效。
- 既有文章只有在重新 prepare、人工批准并 apply 后才变化。
- QQ 历史消息不可逆，本轮不重发。

## 预计文件

- `server/stable/services/article_content.py`
- `server/stable/services/translation.py`
- `server/stable/test_news_content_boundaries.py`
- 必要的翻译专项测试文件（优先复用现有测试文件）
- `server/stable/fixtures/news_content_boundaries/` 下等价真实结构 fixture
- `docs/changes/fix-hrn-residual-boundaries-and-jockey-club-term/`
- 发布前状态文档：`docs/current_state.md`、`docs/project_status.md`

## 兼容与回滚

- 结构清洗只在 HRN 分支执行；通用来源不变。
- 来源级机构保护只在 HRN 英文文章执行；其他来源术语行为不变。
- 代码回滚恢复发布前镜像即可停止新行为；本轮无迁移。
- 已 apply 的历史文章使用每批 rollback artifact 和 receipt 做 CAS 回滚，不依赖代码回滚。
- 若机构映射存在语义争议，先停止剩余历史批准；不得把已审 candidate 替换成不同内容。

## 可观测性

- 解析 metadata 中记录 `hrn_structured_noise` 删除数量。
- 翻译 metadata 记录来源级确定性术语占位符。
- 历史运行继续保存 candidate SHA、approved manifest SHA、receipt、rollback SHA、逐篇失败/拒绝原因。
