# 英文单词型马名 occurrence 语境门禁规格

## 目标

修复英文新闻中“单词或普通短语同时也是马名”造成的马名保护告警污染。判定单位必须是每一次文本 occurrence，而不是词条或整篇文章。真实马名仍须在翻译、改写和发布校验中得到保护；只有字面索引证据的命中保留审计信息，但不得触发高价值 warning 邮件。

任务 slug：`fix-external-english-horse-context-gate`。

## 已确认现状

- 基线：`origin/main@d64c69264df8bf16389e99514fb4ab553ca3f37b`，独立分支 `codex/fix-external-english-horse-context-gate`。
- 生产只读核对时间：2026-07-23。服务器 Git `HEAD=15645b054ff1c4057b1463d3382892cbe4c68106`，`ENGLISH_TERM_CONTEXT_MODE=shadow`。
- article `9595` 的 13 条污染告警 code 均为 `pending_horse_original_missing`，候选来源是待译正式 `TermEntry`，不是 `ExternalHorseAlias`。这些词条均标记 `p0_major_race_participant_auto_created`；生产中对应英文 `ExternalHorseAlias` 查询为 0。
- 生产状态已从启动提示中的 `pending_edit / publish_ready` 漂移为 `published / auto_published`，但 `gate_issues` 仍保存 13 条 warning，且高价值 warning 邮件已发送。
- `Logician` 是 active、已翻译的英国 `TermEntry`，原文 occurrence 位于 `St Leger winner-turned-stallion Logician`，属于强马名语境。

## 范围

1. 为英文正式 horse `TermEntry`（包括 pending translation）和英文 `ExternalHorseAlias` 使用同一个 occurrence 级三类判定器。
2. 翻译保护、发布校验、候选发现、单篇实时处理和批量重判消费同一判定结果。
3. 使 warning / info payload 保留可解释字段，并保证只有确认马名缺失才产生马名保护 warning 或 blocker。
4. 提供历史文章只读 dry-run、经审核的状态更新和生产发布之间的独立门禁。
5. 保持现有日文、繁中和正式中文术语行为不变。

## 非目标

- 不修改新闻 HTML 抓取、正文提取器、正文清洗、来源 adapter 或公开页面。
- 不修改 `AGENTS.md`、`docs/codex_workflow.md`、全局状态文档或另一 change 的 artifacts。
- 不删除合法 `ExternalHorseAlias`，不批量修改/停用正式 `TermEntry` 或 `TermAlias`。
- 不以不断扩充英文停用词或文章级黑名单作为主要方案。
- 不在本 change 中修复 article 9595 的地区归属；`tdn:latest` 当前归为美国而原文属于 Europe 是独立问题。

## 三类判定

### `confirmed_horse`

有 occurrence 附近或可信结构化数据的充分马匹证据。该 occurrence 必须作为 horse entity。保护方式按数据状态区分：

- 已有可信中文译名的正式 horse `TermEntry`：继续通过 accepted term 映射保护，`needs_preserve=False`，不得强制保留英文原文；
- 待译正式 horse 或 alias-only：`needs_preserve=True`，若发布稿未保留原名，沿用马名缺失 warning/blocker。

强证据包括：

- `won`、`finished`、`runs`、`ran`、`ridden by`、`trained by`、`is trained` 等赛马关系；
- `stall`、`draw`、`runner`、`colt`、`filly`、`mare`、`gelding`、`stallion`、`broodmare` 等实体信号；
- 紧邻的 `(GB)`、`(IRE)`、`(FR)`、`(USA)`、`(JPN)` 等国别后缀；
- 血统、骑师、练马师、赛果、出马表结构；
- 生效中的 `RaceEventRunner` / `RaceEventResult` 关联、可信来源结构化实体或标签；
- `winner-turned-stallion Logician` 这类明确实体描述。

### `uncertain`

仅有正式待译 horse 词条或外部马名索引的字面命中，局部语境既不能证明马匹，也不能证明普通用法。该 occurrence 不自动保护，不产生高价值 warning/blocker；必须以 info/audit 形式保留 matched text/context、reason、confidence、term/external horse identity 和 span。

### `common_word`

局部句法、搭配或非马实体语境明确为普通词、地名、业务描述、动词、形容词或名词。该 occurrence 不作为 horse entity，不进入马名保护，不产生马名缺失 warning。

必须覆盖的普通用法包括：

- 地区及业务范围：`include Africa, the Middle East and Asia Pacific`；
- 普通量词/名词：`a fair amount`、`a particular emphasis on`；
- 普通目的/政策搭配：`campaign to abolish`、`beer duty escalator`；
- 普通动词：`meet and engage with`、`has established`、`role which expanded`、`work together`、`to set ... up`；
- 普通形容词/复合词：`really good work`、`work already underway`、`top-class horses`。

## occurrence 规则

- 同一 surface form 在同一文章中可分别得到不同 classification。
- 强马名证据优先于普通词句法证据，但证据窗口不得跨 occurrence 污染。
- 大写、Title Case、词条类型或外部索引存在本身都不是充分马名证据。
- 多词 Title Case 标题本身也不是充分证据，例如 alias-only `Brilliant Result Announced` 必须保持 `uncertain`；只有同一 surface 的实际赛马关系才能升级为 confirmed。
- 正式 `TermEntry` 优先提供 canonical/译名语义；同一 span 的 `ExternalHorseAlias` 只补充 external horse identity，不重复产生实体或告警。
- 只有 `confirmed_horse` 进入翻译占位符、机器马名标签和马名保留校验。

## 可解释 payload

每个被审计的英文 horse occurrence 至少包含：

- `matched_text`
- `matched_context`
- `matched_span` 与 field/position
- `classification`
- `reason`
- `confidence`
- `term_id`（若来自正式术语）
- `external_horse_ids` / primary external horse ID（若来自外部索引）
- `entity_evidence`

`uncertain` 进入 info/audit，不进入 `warning_signature()` 的 warning 集合。

## 验收标准

1. article 9595 等价正文中的 Africa、Amount、Campaign、DUTY、East、Emphasis、Engage、Established、Expanded、Really Good、Set、Top、Work 均不产生马名保护 warning/blocker。
2. `Logician` 仍判为 `confirmed_horse`，沿用正式中文译名映射且不被改为强制保留英文原文。
3. `Brilliant won/finished/...` 五类强语境均判为 `confirmed_horse`。
4. 同文同形词分别作为马名和普通词时独立分类。
5. `uncertain` 可在 audit payload 和批量摘要中检索，但不触发高价值 warning 通知。
6. 单篇实时与批量重判产生相同 occurrence classifications 和 gate issues。
7. 查询数不随 alias/文章数线性增加为逐 alias 或逐文章 N+1；批量只允许有界预加载。
8. 日文片假名、繁中、正式中文替换和非 horse 术语回归保持不变。
