# 英文单词型马名 occurrence 语境门禁设计

## 根因与数据流

article 9595 的真实告警链路为：

`P0 重点赛事参赛马同步 -> pending English horse TermEntry -> validate_rewrite() 原文命中 -> is_pending_horse_translation -> pending_horse_original_missing warning -> apply_validation_outcome() 保存 gate_issues/signature -> process_article_automation_task() -> send_high_value_warning_notification()`。

问题不在正文提取。13 个词的正文 occurrence 与 TDN 原文一致；发布校验在 `server/stable/services/validation.py` 的 pending horse 分支先生成 warning 并 `continue`，没有使用已经计算出的 `entity_resolution` occurrence 分类。

外部别名还有相邻缺口：

- `resolve_article_entities()` 的英文路径已有强语境/普通词二分雏形，实时翻译和发布校验使用它；
- 旧 `_recognize_non_japanese_external_aliases()` / `recognize_horse_names()` 对非日文 alias 字面命中直接 `needs_preserve=True`；`term_discovery` 仍调用该入口；
- `build_validation_batch_context()` 还计算一份旧 lexical recognized-horse 结果，虽然 `validate_rewrite()` 当前实际消费的是 `entity_resolutions_by_article`；
- v2 `EnglishTermSemanticDecision` 只在 `TermEntry` 循环内运行，不能表示 alias-only uncertain，也没有统一 translation/audit payload。

因此当前不是单一判定源，pending 正式词、外部 alias、实时与批量之间存在分叉。

## 设计决策

### 1. 建立唯一 occurrence classifier

在 `server/stable/services/terms.py` 的实体解析层建立可复用的英文 horse occurrence 判定函数和结构化结果。输入为：

- field、全文、start/end、matched text；
- 可选 `TermEntry`；
- 0..N 个 `ExternalHorseAlias`；
- 可选可信 structured entity evidence。

输出固定为 `confirmed_horse | uncertain | common_word`，并携带 reason、confidence、context、span 和 evidence。`ArticleEntity` 序列化补充这些字段，不新增数据库字段或迁移。现有 `_english_title_proper_horse_context()` 的“多词 Title Case 自动确认”规则必须移除或降为 uncertain；标题大小写只提供 surface 信息，不是实体证据。

### 2. 通用证据优先级

1. 生效结构化实体精确命中、国别后缀、赛果/出马表/血统/骑练关系等强证据 -> `confirmed_horse`。
2. occurrence 局部句法明确是普通动词、形容词、普通名词、地理/业务枚举或连字符复合词 -> `common_word`。
3. 其他仅词条/alias 命中 -> `uncertain`。

规则按句法形态和赛马实体关系组织，不以 13 个词建立专用 stoplist。强证据只在当前 span 的有界窗口内判断。

### 3. 实体映射

- `confirmed_horse` -> `entity_type=horse`。待译正式词或 alias-only 为 `needs_preserve=True`；已有可信中文译名继续进入 accepted term 映射且 `needs_preserve=False`。
- `common_word` -> `entity_type=common_word`，`needs_preserve=False`。
- `uncertain` -> `entity_type=ambiguous`（或等价审计实体），`needs_preserve=False`，保留来源 identity 和 classification payload。
- 同 span 同时命中正式词和 external alias 时合并为一个 occurrence：正式词提供 canonical/译名，alias 补充 external horse IDs。

### 4. 发布校验只消费 occurrence 结果

`validate_rewrite()` 不再仅因 `entry.is_pending_horse_translation` 且全文字面命中就生成 `pending_horse_original_missing`。

- 只对该 entry 的 `confirmed_horse` occurrences 检查原名/译名保留，并按 core/background 生成现有 warning/blocker。
- `uncertain` 写入新的 info/audit issue 或 details，不能进入 warning signature。
- `common_word` 只写分类明细；默认不生成 warning。
- `term_region_excluded` 仍保持现有地区门禁顺序，本 change 不改变地区归属。

notification 层继续按 severity 过滤；无需为 13 个词增加通知黑名单。

### 5. article-aware resolver 与 structured evidence API

在 `terms.py` 锁定两层 API：

- 纯文本底层 resolver：接收已预加载 index 与 `structured_entities`，不自行逐条查询；
- article-aware 单篇/批量 wrapper：`resolve_article_entities_for_article(article)` 与 `resolve_article_entities_for_articles(articles)`（最终命名可等价），统一批量加载 term/alias index 和生效 structured evidence。

structured evidence loader 固定只接受生效的 `ArticleRaceLink`（`AUTO`/`MANUAL` 且 `removed_at IS NULL`），以两次有界查询批量加载 `RaceEventRunner` 与 `RaceEventResult`，输出 article -> normalized horse name -> evidence IDs。candidate link、removed link 和无关联均不提供强证据。

调用点锁定如下：

- `translation.py` 的 article 翻译入口使用 article-aware wrapper，并把同一 resolution 传入 provider；
- `automation.py` 的评分/P0 horse hits 使用 article-aware wrapper；
- `rewriting.py` 的 article 改写入口复用传入的同一 resolution；
- `validation.py` 单篇无 batch context 时使用 article-aware wrapper；
- `term_discovery.py` 使用 article-aware wrapper；
- `term_gate_reprocessing.py` 批量构建一次 article-aware resolutions，并同时供 validation 使用。

这样 structured evidence 不再只存在于 batch validation 的第二套 classifier。translation、automation、实时 validation、discovery 和 batch 对同一数据库快照得到同一 classification；调用方不得再次自行加载/重判。

### 6. 实时、翻译、发现与批量共用

- 实时翻译、自动化评分、发布校验使用 article-aware 单篇 wrapper。
- 批量重判使用 article-aware 批量 wrapper，再把同一 resolution 传给 `validate_rewrite()`。
- `term_discovery` 改为消费 resolution 中的 `confirmed_horse`，不再通过字面 alias 入口制造候选。
- `recognize_horse_names()` 的非日文兼容入口委托统一 resolver，或只保留为相同结果的薄适配层。
- `build_validation_batch_context()` 删除/替换未消费的第二套 lexical recognition；`recognized_horses_by_article` 如为兼容保留，应从已经构建的 resolutions 派生，不再额外扫一次 alias。

### 7. 已发布历史稿的独立 audit-only apply

不允许把 article 9595 交给现有“恢复候选” commit。为历史 published 稿设计独立、默认关闭的 exact-ID audit-only 路径：

- 输入必须是显式 article IDs、已审核 dry-run run/manifest SHA 和确认参数；不接受按时间窗隐式全量写；
- 写前锁 article 并重算 input/settings/term-alias snapshot/expected outcome，任何 drift fail closed；
- 只允许更新 `NewsArticle.gate_issues`、`decision_reason.gate_issues`、`decision_reason.gate_issue_counts`、`automation_warning_email_signature` 和必要的 `updated_at`；
- 禁止调用 `apply_validation_outcome()`，禁止改 `workflow_status`、`automation_status`、`review_mode`、`risk_level`、`publish_ready_at`、`ranked_revived_at`、`published_to_web_at`、译文、公开数据或 QQ delivery；
- 不发送通知，不修改既有 `NotificationLog`；审计身份记录在锁定 reprocess run/manifest 中；
- 独立 verifier 对上述 allowlist 和所有禁止字段/账本做 before/after 比较。

未发布 core blocker 候选继续使用现有恢复流程；published audit-only 与候选恢复不得共享 apply 分支。

## 预计修改文件

- `server/stable/services/terms.py`
- `server/stable/services/validation.py`
- `server/stable/services/translation.py`
- `server/stable/services/automation.py`
- `server/stable/services/rewriting.py`
- `server/stable/services/term_discovery.py`
- `server/stable/services/term_gate_reprocessing.py`
- `server/stable/management/commands/reprocess_term_gate_blocked_articles.py`
- `server/stable/test_external_english_horse_context_gate.py`（新增专用测试）
- 受影响既有测试文件仅做必要断言更新，不改正文提取测试。

预计不修改：models/migrations、settings、notifications、HTML/adapters/extractors/templates/public pages、`AGENTS.md`。

## 查询与性能

现有 entity batch index 会先从文章生成候选 key，再批量查询 `TermAlias`、`TermEntry`、`ExternalHorseAlias`。设计保持每种索引每批有界查询，不允许在 occurrence、alias 或 article 循环内访问数据库。structured evidence 固定为每批 runner/result 各一次查询。

当前 `build_validation_batch_context()` 的旧英文 alias recognition 会整表预加载英文 aliases；其结果未被校验消费。实现应复用 entity batch 结果，消除重复扫描，而不是增加查询。硬门禁为：10/20 篇 article-aware resolver 查询数相同且均 `<=8`；100 篇完整 reprocess dry-run 总 SQL `<=35`；runner/result evidence 各固定 1 次；无逐 article/alias 查询。若查询计划显示 `Lower(normalized_name)` 无法利用现有索引，本 change 不贸然新增迁移；先保持候选集合有界并记录后续索引优化，除非实现证据证明现有规模不可接受。

## 失败模式

| 失败模式 | 防护 |
| --- | --- |
| 强证据正则过窄导致真实单词型马名漏保护 | 五类强语境、国别后缀、stall/draw、stallion、Logician 回归；默认无普通证据时为 uncertain 而非 common_word |
| 同词另一 occurrence 被邻近马名证据污染 | 每 span 独立窗口和同文双角色测试 |
| uncertain 仍进入 warning email | issue severity/info 与 warning signature、notification 回归测试 |
| alias-only 审计丢失外部 ID | payload 完整性断言 |
| 批量和实时证据不同 | 同 fixture 双路径结构化比较；单篇 evidence loader 与 batch loader 共用 |
| 引入 N+1 或英文 alias 全表重复扫描 | CaptureQueriesContext 和 batch query budget |
| 已译 confirmed horse 被错误强制保留英文 | Logician 断言 `confirmed_horse`、accepted mapping 生效且 `needs_preserve=False` |
| 多词 Title Case 被自动升级 | 标题 alias-only uncertain RED 与强赛马关系 confirmed 对照 |
| published 稿误走候选恢复 | audit-only allowlist 与全状态/QQ/NotificationLog 不变测试 |
| 误改日文/繁中/中文链路 | 现有语言回归测试 |

## 与正文提取 change 的边界

本 change 只读取 `title_ja` 与 `body_ja_normalized or body_ja_raw` 的既有可见文本，不修改其生成方式。另一 worktree `codex/fix-news-body-extraction-boundaries` 当前只修改工作流/规格文档；未来即使其实现正文边界，本 change 也只把提取后的文本当输入。任何 extractor、cleaner、source adapter、HTML selector 或导航过滤规则均不在本分支修改。
