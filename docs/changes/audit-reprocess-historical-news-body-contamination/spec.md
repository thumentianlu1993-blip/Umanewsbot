# 历史新闻正文污染盘点与重处理规格

## 1. 背景

`fix-news-body-extraction-boundaries` 已把 Horse Racing Nation（HRN）正文选择器收紧到
`.article-body`，新解析不再把导航、侧栏、登录入口和工具菜单当正文。生产自然重复抓取也已把
文章 `9623` 的日文原文层更新为干净正文，但其历史中文翻译、可编辑中文正文及公开
`effective_body` 仍保留旧污染。

本变更承接前一变更的历史 Gate B/C，只处理：

1. 部署前 HRN 历史文章的只读、穷尽盘点；
2. 可审计的人工决策包；
3. 对人工批准且状态未漂移文章的精确重处理；
4. 写后核验与可恢复回滚。

本规格不是新的正文解析器修复，也不以已知中文词黑名单决定正文边界。

## 2. 权威范围

- 来源：`source_site=horse_racing_nation`。
- 冻结上界：`NewsArticle.id <= 9788`，即正文边界修复部署前已存在的 HRN 文章。
- 当前生产只读基线（2026-07-24）：
  - 共 `282` 篇，ID `5711..9788`；
  - `original_content_html` 缺失 `0`；
  - `published=68`，QQ delivery `52`（`sent=47 / failed=5`）；
  - `translation_status=translated` 为 `248`；
  - 人工编辑字段非空 `0`，`rewrite_body_zh` 非空 `0`。
- 正式盘点必须重新生成有序 ID 集合、总数、最小/最大 ID 与集合 SHA-256；若与上述探索基线
  不一致，只记录漂移并停止生成可执行批准清单，不用动态查询扩张范围。
- 即使自然重复抓取已经把某篇日文原文层更新干净，该文章仍属于盘点范围；是否需要中文层重处理
  不能只由“当前日文正文是否变化”决定。

## 3. 目标

- 对范围内每篇文章产生一条且仅一条审计记录，解释原始 HTML、当前解析结果、日文原文层、中文
  翻译层、编辑层、改写层、公开层、工作流和 QQ 交付状态。
- inventory 只输出可观察事实，不在缺少 provenance 时自动替人作处置决定：
  - 来源：`source_clean / source_changed / source_blocked`；
  - 中文：`chinese_input_verified / chinese_input_unverifiable / chinese_absent`；
  - effective layer、人工字段、rewrite、公开和 QQ 状态。
- 旧 `TranslationRun` 没有保存完整来源输入哈希；因此 `chinese_input_unverifiable` 的旧机器中文稿不得
  自动归为 `no_action`，必须进入 source-vs-Chinese side-by-side 人审。
- 人工审核后才可给出 action：
  - `no_action`：仅当可信 source-input hash 可验证，或人工查看对照后明确签署；
  - `repair_source_only`：仅日文来源层需要使用既有 schema v2 修复；
  - `retranslate_machine_fields`：来源边界可信，机器拥有的中文字段需要重译；
  - `retranslate_and_rewrite`：重译后还需重建机器改写层；
  - `manual_review`：存在人工字段、复杂历史状态或无法自动证明安全；
  - `blocked_missing_html`；
  - `blocked_parse_failure`；
  - `blocked_state_drift`。
- 生成供人工审核的机器可读 JSON/JSONL 和可读工作簿；决定与原始审计、候选输出、文章状态均以
  哈希绑定。
- 只有人工批准的精确文章和精确候选输出可写入。任何集合、文章状态、输入或输出漂移均 fail
  closed，目标批次零写入。
- 保持真正属于文章的段落、小标题、引用、列表、表格及正文首尾完整。
- 保持发布状态、公开时间、slug、QQ delivery、人工字段和其他非批准字段不变。

## 4. 非目标

- 不重新设计 HRN 或其他来源的正文提取器。
- 不使用文章 ID 特判、中文词黑名单、翻译提示词规避或模板/CSS 隐藏作为修复。
- 不自动判定人工编辑内容可覆盖；人工锁定字段默认只报告、不写入。
- 不撤回、编辑或重发既有 QQ 消息；已发送消息是外部不可逆历史。
- 不自动重新发布、置顶、改发布时间、创建 QQ delivery 或触发自动运营。
- 不在本变更中修复 HRN 以外来源；其他来源发现的污染只进入后续只读问题清单。
- 不以一次大事务覆盖全部 282 篇；正式写入必须使用小批次精确 manifest。

## 5. 失败边界

- 原始 HTML 缺失、可信正文容器缺失、解析为空或解析异常：阻断该文章，不生成自动重处理输出。
- cohort 集合与冻结证据不一致：盘点可以输出诊断，但不得产生可执行 manifest。
- AI/翻译/改写调用失败：候选准备失败，数据库零写入；不得保留半成品公开状态。
- 候选输出未通过结构、术语和正文完整性验证：进入人工复核，不得批准写入。
- 批次内任一文章在批准后发生 `updated_at`、原始 HTML、源正文、中文字段、人工字段、
  workflow/public/QQ 状态漂移：整个批次零写入。
- manifest/file SHA、schema version、revision 或 candidate hash 不匹配：整个批次零写入。
- 写后 verifier 任一不变量失败：立即停止后续批次，保留证据并进入精确回滚。
- `translation_status=failed/pending` 的历史文章默认进入 `manual_review`，本变更不自动恢复翻译状态、
  清理错误字段或重试计数。

## 6. 验收标准

1. 正式盘点对冻结 cohort 穷尽记账，计数相加等于集合总数，没有重复或遗漏 ID。
2. `9623` 和 `9519` 在审核包中能解释“来源层已干净但历史中文层仍污染”，不能因来源层
   `unchanged` 被漏掉。
3. 已知中文词仅作为辅助证据列；候选和写入由 DOM 来源边界、层级归属、状态和哈希决定。
4. 审核包包含至少一个人工签署或可信输入哈希证明的 `no_action` 正常文章反例，并证明正文首尾、
   段落、小标题、引用和列表不被裁剪。
5. 候选准备阶段不写数据库；正式 commit 不调用网络、翻译或改写服务，只应用人工批准的精确输出。
6. 人工字段永不被自动覆盖；如果正式盘点发现人工字段，默认转 `manual_review`。
7. 批次 commit 对全集加锁并在同一事务中校验；任一漂移时业务字段和 `OperationLog` 均零写入。
8. 写入不改变文章 ID、来源身份、slug、workflow、published timestamp、发布者、QQ delivery、
   tags/马匹链接及未列入批准动作的字段。
9. `9623` 的网页正文不再含来源框架污染，正文首尾和合法结构完整；`9519` 同样通过，正常反例保持不变。
10. 每批具有 before snapshot、批准 manifest、apply receipt、写后 verifier 和精确 rollback artifact。
11. rollback artifact 在 DB 写事务前以完整 before 值原子落盘并 `fsync`；事务中的 OperationLog 绑定其
    SHA，DB 成功而 receipt 缺失时可从 DB 与预写 artifact 重建。
