# 历史新闻正文污染盘点与重处理测试

## 1. RED 取得原则

行为；fixture、依赖、语法或数据库环境错误不计。预计首个有效 RED 是新服务/管理命令缺失或现有扫描不能
识别“来源已干净、中文仍陈旧”的层级差异。

## 2. Inventory

- I01：冻结 HRN `id <= max_id`，输出稳定升序全集、min/max/count/ID-set SHA。
- I02：分页下没有重复/遗漏；分类计数之和严格等于 cohort。
- I03：`9623` 等价 fixture 的当前来源层已干净，但旧 `translated_body_zh/body_zh` 缺可信
  source-input hash，输出 `chinese_input_unverifiable` 并强制进入 side-by-side 人审。
- I04：`9519` 等价 fixture 同样被识别，不使用文章 ID 特判。
- I05：正常文章 fixture 的段落、小标题、引用、列表和正文首尾全部保留；缺可信输入 hash 时也不能
  自动 `no_action`，只有可信 hash 或人工签署后才成为 no-action 反例。
- I06：缺原始 HTML、选择器缺失、空正文、解析异常分别 fail closed。
- I07：已知中文词仅产生辅助 signal；合法正文包含“当前/热门”等普通语义时不能仅因此入选。
- I08：latest TranslationRun、effective layer、人工字段、rewrite、workflow/publication 与 QQ
  delivery 状态完整记账。
- I09：inventory 使用 PostgreSQL read-only transaction/role；主动写探针被 DB 拒绝，且无模型 save、
  OperationLog、任务派发、网络请求。
- I10：相同快照两次生成 canonical manifest SHA 相同（生成时间排除在 identity 外）。
- I11：cohort 与冻结基线漂移时输出诊断且阻断 executable manifest。
- I12：查询数受控，282 篇等价规模不出现按文章线性增加的 run/QQ N+1。

## 3. Candidate prepare

- P01：使用 clean source candidate 生成翻译，不从旧污染中文层生成。
- P02：翻译/改写 provider 失败时数据库零写入，artifact 记录失败。
- P03：prepare 不调用 `apply_translation_result/save/publish/QQ`。
- P03a：prepare 禁止调用 `translate_article/translate_article_task/rewrite_article_task` 等写路径；
  NewsArticle、TranslationRun、AutomationLog、OperationLog、QQPushDelivery、TaskExecutionLog 快照全零增量。
- P03b：provider 只接收 detached DTO；AI 调用发生在 read-only ORM 事务关闭后。
- P04：人工字段文章默认 `manual_review`，候选不得覆盖人工字段。
- P05：无 rewrite 的文章只生成 translation candidate；有机器 rewrite 的文章按“翻译后改写”生成。
- P06：候选保存 exact output、provider/model/rule、before/after SHA 与验证结果。
- P07：正文结构完整性不足、空输出、边界污染仍存在或 validator blocker 时不可批准。
- P08：相同输入可以产生不同 AI 文本，但每个 candidate 都有唯一哈希；批准后不重新调用 AI。

## 4. Review package

- R01：JSONL 与 XLSX 行数、ID、candidate SHA 一致。
- R02：允许决定枚举、reviewer/reason 必填；未知决定 fail closed。
- R03：重复 ID、隐藏行、公式、未知列、缺行或增行拒绝。
- R04：submitted workbook 记录独立 SHA；不可编辑证据列、row identity 或 candidate SHA 与 template
  manifest 不匹配时拒绝，合法填写人工列不会因模板文件 SHA 改变而被拒绝。
- R05：已发送 QQ 的公开文章显示不可逆提示。
- R06：只有可批准分类能生成 apply manifest；blocked/manual/reject 不进入。
- R07：批准 manifest 绑定 exact output，而不是只绑定 action。

## 5. Apply 与原子性

- A01：默认 dry-run；缺 `--commit` 时业务表和 OperationLog 零写入。
- A02：manifest schema/revision/file SHA/candidate SHA 错误时零写入。
- A03：锁行后任一文章 `updated_at` 或任一 before 字段漂移，整批业务字段和 OperationLog 零写入。
- A04：cohort/action ID 集合增减、重复、乱序语义漂移时拒绝。
- A05：人工字段不覆盖；对应文章不能绕过 `keep_manual/manual_review`。
- A06：逐字段 allowlist 生效；首版 title、translation status/error/retry/provider/model/time 永不写，
  failed/pending 默认 blocked，未批准字段逐项不变。
- A07：不调用网络、Celery、publish、QQ，不创建/修改 QQ delivery。
- A08：workflow、automation、review mode、public slug、published timestamp、publisher、tags 和链接不变。
- A09：同一 manifest replay 幂等拒绝或报告 already-applied，不重复 OperationLog。
- A10：10 篇批次在单事务完成；并发两个相同批次至多一个成功。
- A11：receipt 与 rollback manifest 的 before/after fingerprint 和数据库一致。
- A12：rollback artifact 写文件、file fsync、rename、directory fsync 任一步失败时尚未进入唯一
  `transaction.atomic()`，DB 业务字段和 OperationLog 零写。
- A13：DB commit 成功后 receipt 写入前模拟崩溃；重启后可由 OperationLog、DB 和预写完整 rollback
  artifact 重建 receipt，不重复 apply。

## 6. Verify 与 rollback

- V01：写后 `9623/9519` 公开 effective body 无框架污染，正文首尾与合法结构完整。
- V02：正常反例字节级或规范化等价不变。
- V03：批次全部不变量验证；任一失败返回非零且阻断后续批次。
- V04：rollback 也要求 exact manifest SHA 与当前 after fingerprint；漂移整批零写。
- V05：rollback 恢复本批字段并保持发布/QQ 不变量，不触发外部副作用。
- V06：rollback replay 幂等拒绝或报告 already-rolled-back。

## 7. 回归与静态检查

- 既有 `test_news_content_boundaries.py` 全量；
- 翻译、改写、自动发布与 QQ 相关受影响测试；
- 正常国际来源正文提取反例；
- Django `check`；
- migration drift（预期无 migration）；
- compile/static check 与 `git diff --check`；
- 真实 PostgreSQL 的事务漂移、并发锁和 rollback 测试。
