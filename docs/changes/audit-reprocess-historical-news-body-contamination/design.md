# 历史新闻正文污染盘点与重处理设计

## 1. 核心判断

根因已经在上游修复，但历史内容存在分层错位：

`original_content_html -> body_ja_* -> translated_* -> body_zh -> rewrite_* -> effective_body`

自然重复抓取只可能刷新左侧来源层，不会自动使右侧旧中文层失效。现有
`translate_article_task(force=True)` 会覆盖人工字段，且任务执行过程中会直接写库；因此不能把它当成
历史批处理引擎。AI 输出又具有非确定性，不能在批准动作后才临时调用模型。

本设计把“生成内容”和“写入内容”彻底分开：人审批准的是精确候选文本及其哈希，commit 阶段不联网。

## 2. 四阶段数据流

### A. inventory：生产只读总账

扩展既有 `repair_article_content_boundaries` 的扫描能力或增加同模块的专用只读命令，读取冻结 cohort
中的每篇文章和保存的 `original_content_html`，不发网络请求、不写数据库。

输出目录：

`/app/runtime/news_body_history/<run_id>/inventory/`

生产执行时必须显式把宿主
`/opt/umanewsbot/runtime/news_body_history` 挂载到容器同路径；现有 Compose 默认没有该挂载。

输出至少包含：

- `cohort.json`：selector、冻结上界、有序 ID、集合 SHA、revision、生成时间；
- `inventory.jsonl`：逐篇状态、全部输入/层级哈希、解析选择器、长度和验证结果；
- `summary.json`：穷尽分类计数和 blockers；
- `manifest.json`：上述文件的 size/SHA-256。

每行记录只表达事实，不自动决定 `no_action`。旧 `TranslationRun` 只有 `prompt_excerpt`，没有完整
source-input hash，因此旧机器中文稿默认为 `chinese_input_unverifiable`，必须进入对照人审。

每行记录：

- 文章身份、`updated_at`、来源 URL、原始 HTML SHA；
- 当前/重新解析后的 `title_ja/body_ja_raw/body_ja_normalized` SHA、selector/status；
- `translated_*`、`title/body/summary/push_zh`、`rewrite_*` SHA；
- `effective_*` 所属层与 SHA；
- `manually_edited_fields`；
- workflow/translation/automation/review/publication 状态；
- latest `TranslationRun` provider/model/status/time；
- QQ delivery 的 ID/status/message_id/sent_at 摘要；
- 已知框架词命中、结构差异等辅助信号，但这些信号不单独决定 action。

### B. prepare：候选输出生成

输入是人工选择的 inventory 行，而不是动态数据库查询。prepare 先在数据库只读事务中重新核对文章快照并
转换成脱离 ORM 的 DTO；状态漂移则拒绝。生产使用专用只读角色，或至少对该连接执行 PostgreSQL
`SET TRANSACTION READ ONLY` 并用写探针证明拒绝写入。

顺序：

1. 若来源层仍旧，先生成已清理的来源候选；不直接写库。
2. 使用该干净来源候选调用纯 provider/DTO 接口，得到机器翻译候选。
3. 仅对确需机器改写的文章调用纯 rewrite provider/validator。
4. 运行正文完整性、结构、术语和门禁验证。
5. 输出 exact candidate。明确禁止 `translate_article()`、`translate_article_task`、
   `apply_translation_result()`、`rewrite_article_task`、`apply_rewrite_result()` 及任何会创建
   `TranslationRun/AutomationLog/TaskExecutionLog` 的路径。

候选 artifact 包含全部拟写字段、provider/model、prompt/rule version、验证结果、before/after SHA 和生成错误。
网络失败只产生 `prepare_failed` 行，不改变数据库。

### C. review：人工决策

审核包由不可变 inventory 与 candidate artifact 生成：

- immutable evidence/template：绑定不可编辑证据列、row identity、candidate SHA 和模板文件 SHA；
- `review.xlsx`：每篇一行，前置 `decision/reviewer/reason`，展示公开状态、QQ 不可逆提示、首尾摘要、
  before/after 差异与验证结果；
- `review.jsonl`：机器可读等价记录；
- `review_template_manifest.json`：绑定 cohort、inventory、candidate、证据列 identity 和生成代码 revision。

允许决定：

- `approve_no_action`
- `approve_fields`（必须同时填写下节 allowlist 内的 `approved_fields`）
- `keep_manual`
- `reject`

人工填写后，导入器不要求 submitted workbook 等于模板文件 SHA；它验证不可编辑证据列、row identity
和 candidate SHA 仍与 template manifest 相同，记录 submitted workbook 的独立 SHA，严格归一化三个人工列，
生成 canonical `approved_decisions.json` 和 `approved_manifest.json`。拒绝公式、隐藏行、重复 ID、未知列值、
缺 reviewer/reason 或证据列变动。批准 manifest 绑定精确输出文本 SHA，不允许只批准“重新调用 AI”这一动作。

### D. apply / verify / rollback：离线精确写入

建议使用新服务和管理命令，避免改变在线 Celery 任务语义：

- `apply_news_body_history_batch --manifest ... --manifest-sha256 ... --dry-run`
- 同命令显式 `--commit` 才写入；
- `verify_news_body_history_batch --receipt ...`
- `rollback_news_body_history_batch --rollback-manifest ... --manifest-sha256 ... --commit`

commit：

1. 校验 schema、file SHA、code revision、批准 decision 与精确输出；
2. 从 approved manifest/candidate 已绑定的完整 before 值构造 rollback artifact；此时尚未启动 DB
   写事务，也不持有行锁；
3. 把 rollback artifact 写临时文件、`fsync` 文件、
   `os.replace`、`fsync` 父目录，计算并固定 SHA；
4. 只有上述文件持久化成功后，才开启唯一的 `transaction.atomic()`，按 ID 升序
   `select_for_update()` 锁定整个批次；
5. 事务内重新从 DB 计算全集与逐篇 before fingerprint，并与 approved manifest 和预写 rollback
   artifact 双重匹配；任一漂移抛错，业务字段和 OperationLog 零写入；
6. 仅写批准字段；
7. 每篇写 `OperationLog`，detail 包含 batch ID、approved manifest SHA、rollback artifact SHA、
   before/after SHA、逐字段 decision；
8. commit 后生成 receipt；若 receipt 写入时崩溃，可从数据库、OperationLog 和预写 rollback artifact
   重建，不得再次 apply。

事务前若需读取数据库，仅允许使用短暂只读快照构造或核对 artifact；它不得被称为写事务，也不得把
`select_for_update` 行锁跨越文件 I/O。预写文件失败发生在唯一 `transaction.atomic()` 之前。

commit 不调用网络，不派发 Celery，不调用 publish/QQ，不新建 `TranslationRun/AutomationLog` 来伪装在线执行。
候选生成 provenance 保存在不可变 artifact。除来源修复的 canonical parse metadata 外，首版不增加其他
`translation_metadata` 内容；OperationLog 只保存 artifact SHA/相对路径。

## 3. 字段所有权

### 永久不自动写

- `id/source_site/source_article_id/source_url/public_slug`
- `workflow_status/review_mode/automation_status`
- `published_to_web_at/published_by/published_by_mode/auto_publish_at`
- `manually_edited_fields` 及其中列出的字段
- QQ delivery 与 PushLog
- tags、马匹/赛事链接、图片、归属字段

### 可按逐字段批准决定写

- `repair_source_body`：仅 `body_ja_raw/body_ja_normalized` 及 canonical
  `translation_metadata.content_boundary_repair`
- `replace_translated_body`：仅 `translated_body_zh`
- `replace_body_zh`：仅当 `body_zh` 非人工字段时写 `body_zh`
- `replace_translated_summary`：仅 `translated_summary_zh`
- `replace_summary_zh`：仅当非人工字段时写 `summary_zh`
- `replace_push_summary_zh`：仅当非人工字段时写 `push_summary_zh`
- `replace_base_translation_body`：仅现有机器 rewrite 文章的 `base_translation_zh`
- `replace_rewrite_body`：仅现有机器 rewrite 文章的 `rewrite_body_zh`

首版永不改任何 title 字段，也不改 `translation_status/status/error/retry/provider/model/translated_at`。
`failed/pending` 默认 blocked/manual review。每个批准 decision 必须列出 `approved_fields`；字段不在上述
allowlist、文章不满足前置状态、或批准字段之间依赖不完整时整批拒绝。

逐字段前置矩阵：

| approved field | 允许的文章状态 | 必须同时批准 | 禁止条件 |
| --- | --- | --- | --- |
| `body_ja_raw/body_ja_normalized/content_boundary_repair` | source_changed 且 parse ok | 三者作为一个来源原子组 | 缺 HTML、parse failure |
| `translated_body_zh` | translated 且 candidate validation 通过 | 无 | failed/pending、人工字段不相关但仍需人审 |
| `body_zh` | translated 且当前 effective/body 层需替换 | `translated_body_zh` | `body_zh` 人工锁定 |
| `translated_summary_zh` | translated 且摘要被逐字段判定受影响 | 无 | failed/pending |
| `summary_zh` | translated 且摘要被逐字段判定受影响 | `translated_summary_zh` | `summary_zh` 人工锁定 |
| `push_summary_zh` | translated 且推送摘要被逐字段判定受影响 | `translated_summary_zh` | `push_summary_zh` 人工锁定 |
| `base_translation_zh` | 当前存在机器 rewrite 且正文需重建 | `translated_body_zh` | 无现有机器 rewrite |
| `rewrite_body_zh` | 当前存在机器 rewrite 且 rewrite validation 通过 | `base_translation_zh` | 人工正文或无现有机器 rewrite |

`approve_no_action/keep_manual/reject` 的 `approved_fields` 必须为空。任何 `translation_status=failed/pending`
均不能使用 `approve_fields`；本变更只记录、保持其全部状态/错误/重试字段不变。

若 implementation 探索证明某个时间/状态字段必须改变才能维持模型不变量，必须回到规格审核，不得实现时临时扩权。

## 4. 分批策略

- inventory 可按 `500` 的只读页执行，cohort 当前仅 282 篇，最终 artifact 仍是一个穷尽集合。
- prepare 默认每批最多 `10` 篇，控制 AI 成本与人工审核量。
- 首次 pilot 建议：
  - `9623`；
  - `9519`；
  - inventory 中选出的一个正常 `no_action` 反例；
  - 一个未公开候选（仅当确需重处理且验证通过）。
- apply 每批最多 `10` 篇；pilot 完整验收后才允许下一批。
- 已公开且 QQ 已发送的文章必须在工作簿醒目标记：网站可纠正，但旧 QQ 消息不会改变。

## 5. 一致性与性能

- 查询使用稳定 ID 顺序、`select_related/prefetch_related` 获取 latest run 和 QQ 摘要，避免 N+1。
- 大文本在 JSONL 中保存必要正文或单独 content object；总账行保存 SHA 和相对引用。
- artifact 使用临时文件 + file `fsync` + `os.replace` + directory `fsync` 原子发布，目录 `0700`、
  文件 `0600`。
- 正式 commit 前要求可验证 PostgreSQL custom-format 备份；回滚 manifest 保存本批全部被修改字段的 before
  值和 fingerprint。
- 不新增数据库 migration；若实现阶段证明必须持久化批次锁或 run model，应重新方案审核。

## 6. 独立门禁

1. 代码实现与部署授权；
2. 正式生产 inventory 授权（只读、无业务写）；
3. 候选生成的网络/API 成本授权；
4. 人工定稿批准；
5. 绑定精确批准 manifest SHA 的生产 apply 授权；
6. 每批写后验收后下一批授权。

## 7. 数据库只读硬边界

- inventory 与 prepare 的 ORM 读取必须在 PostgreSQL read-only transaction 中进行；生产优先使用只有
  `SELECT` 权限的专用角色。
- AI/provider 调用发生在只读快照已复制为 DTO 且事务关闭后；provider 接口不得持有 ORM instance。
- 测试必须主动尝试写 `NewsArticle/TranslationRun/AutomationLog/OperationLog/QQPushDelivery/
  TaskExecutionLog` 并证明数据库拒绝或写拦截器失败测试；仅“代码没有调用 save”不算零写证据。
