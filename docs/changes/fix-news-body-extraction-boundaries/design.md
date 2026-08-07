# 新闻正文提取边界修复设计

## 当前数据流

```text
HRN listing
  -> HorseRacingNationAdapter.fetch_detail()
  -> SimpleInternationalNewsAdapter.parse_detail_html()
  -> body_selector 选择 main（错误边界）
  -> clean_international_article_body(main)
  -> CanonicalNewsDraft
  -> upsert_article_from_draft()
       body_ja_raw / body_ja_normalized / original_content_html
  -> translate_article_task()
  -> 自动化改写与发布门禁
  -> NewsArticle.effective_body
  -> public/detail.html
```

展示模板只渲染 `effective_body`，没有主动拼接来源导航。污染在抓取详情解析阶段已经进入原文正文，
之后的翻译、改写和展示只是传播既有错误。

## 只读证据

- `origin/main@d64c69264df8bf16389e99514fb4ab553ca3f37b` 的 HRN 适配器声明
  `body_selector = "article, main"`。
- 2026-07-23 在线 HRN 页面中真实正文容器为 `.article-body`；页面没有语义 `<article>`，顶部和底部框架均在
  `<main>` 内。
- 公开文章 `9623` 的开头包含 ticker、登录入口和标题元数据，结尾包含 Related Pages/Top Stories。
- 同源公开文章 `9519` 也以“即时/热门/登录/免费注册”等同型页面框架开头。
- 现有 `article_content.py` 已能在选定可信节点后处理通用结构化噪声；现有
  `repair_article_content_boundaries` 已能读取数据库内 `original_content_html` 离线重解析，默认 dry-run。

## 根因

根因不是翻译模型、模板拼接或个别中文词，而是来源适配器的 DOM 边界过宽：HRN 在 7 月 14 日全页
`body` 兜底被移除时仍保留 `main` 兜底；该站的详情正文实际有稳定 `.article-body`，但适配器未声明它。
通用清理器会删除 `nav/footer/aside/form/script` 等结构节点，却无法证明 `<main>` 内普通 `div`、标题、ticker
和侧栏文字不是正文，因此这些文本被合法地保留下来。

## 设计决策

### D1：修复来源边界，不扩大通用黑名单

将 `HorseRacingNationAdapter.body_selector` 收紧为来源级可信 `.article-body`。不保留 `article`、`main` 或
`body` 回退；上游结构漂移时宁可生成 `selector_not_found`，也不重新发布页面框架。

此改动复用 `SimpleInternationalNewsAdapter._select_body_node()` 和
`clean_international_article_body()`，不增加新的解析框架或依赖。

`parse_detail_html()` 目前只返回失败状态，调用方仍会 upsert。实现必须在
`_crawl_international_source()` 的 draft/upsert 边界验证 `body_parse_status == "ok"` 且规范正文非空；
否则将该 URL 作为 detail error 记入现有抓取摘要并继续下一篇。检查发生在 upsert 前，因此新文章不会创建，
既有文章也不会被空正文、新 HTML 或失败 metadata 更新，术语发现和翻译均不会派发。

### D2：fixture 保留真实结构，断言内容边界而非词表实现

从 `9623` 对应实时页面裁剪最小 HRN fixture：保留 `<main>` 内 ticker/login、标题/作者、`.article-body`、
右侧相关推荐等相对结构；正文部分保留首段、末段、小标题、引用、列表和表格样本。测试断言：

- 命中 `.article-body`；
- 框架文本不出现；
- 所有合法正文结构文本存在且顺序正确；
- 选择器缺失时 fail-closed。

另加一个正常 HRN fixture/等价内联页面，确保没有噪声的普通文章首尾完整。测试可以使用已知框架文本做结果
断言，但应用实现不得依赖这些词。

### D3：历史识别复用离线重解析，扩展为只读来源扫描

最小改动优先扩展现有 `repair_article_content_boundaries`：

- 保持 `--article-id` 默认 dry-run 与 `--commit` 语义兼容；
- 新增只读识别模式，要求显式 `--source-site horse_racing_nation`、`--after-id` 和 `--limit`，按 ID 稳定分页；
- 识别模式禁止 `--commit`，不触网，只解析已保存 `original_content_html`；
- JSON 输出选择条件、每类计数、逐篇 HTML/旧正文/新正文/有效公开正文哈希、长度、状态、选择器、人工字段、
  workflow/translation/automation 状态和 QQ delivery 数；不输出完整 HTML 或正文；
- 将 `before_body_sha != after_body_sha`、选择器失败、缺少 HTML 分别列为候选原因。
- 识别输出的 scope 是部署前已存在的全部 HRN 文章，而不只是 `changed` 行；记录冻结的最大文章 ID，后续分页
  必须带同一 `max_id`，避免新文章混入或重复抓取先清理 source body 后漏掉旧中文/改写层。

运维人员保存每批 JSON 并计算文件 SHA-256；批次范围、文件 SHA 和人工决定形成未来重处理审计输入。
若实现阶段发现现有命令职责因此变得混乱，可将只读扫描拆为相邻管理命令，但不得复制解析或哈希逻辑。

批准 manifest 使用固定 schema v2，顶层仅含 `schema_version=2/source_site/articles`，每行固定为：

- `article_id`、`decision=repair_source_body`、`updated_at`；
- `original_content_html_sha256`、`before_body_sha256`；
- `after_title_sha256`、`after_body_sha256`、`after_body_normalized_sha256`；
- `after_parse_metadata_sha256`。

最后一项绑定 commit 实际写入 `translation_metadata` 的
`body_parse_status/body_selector/body_cleaning`，其摘要必须由 UTF-8 canonical JSON
（`ensure_ascii=False, sort_keys=True, separators=(",", ":")`）计算。commit 同时要求 manifest 文件
SHA-256；命令先验证文件 SHA/schema/来源/集合，在单一 `transaction.atomic()` 中一次性锁定全部目标行并重解析，
再逐项比较批准输入和 `title_ja/body_ja_raw/body_ja_normalized/parse metadata` 输出哈希。只有全部匹配才进入
写回循环；legacy v1、缺字段或任一漂移均抛错并使整批零写入、零 OperationLog。扫描 JSON 本身不是批准
manifest，必须由人工决定产生独立批准 artifact，避免“被识别”自动等于“批准写入”。
显式 ID dry-run 必须输出上述 v2 所需哈希，作为人工批准 artifact 的唯一生成输入；不得仅显示 raw 正文哈希却
在 commit 时顺带写入未受审的标题、normalized 正文或解析元数据。

### D4：历史重处理不是代码部署副作用

部署只影响新详情解析。历史文章保持原样，直到另一次明确授权。未来顺序固定为：

1. 在部署/重抓前冻结部署前 HRN `max_id`，停止或排空相关写入窗口，核对生产 HEAD/镜像/来源开关与队列。
2. 备份数据库并验证备份可读。
3. 分批运行只读识别，保存 JSON 与 SHA；人工审查首尾、人工字段和当前有效正文来源。
4. 从审核决定生成独立 schema v2 批准 manifest，记录精确文章集合、逐篇输入哈希及全部持久化 parser 输出哈希，
   并保存 manifest file SHA。
5. 使用批准 manifest + file SHA 运行 repair dry-run；commit 在事务锁行后复核全部哈希，任一漂移整批零写入。
6. 仅对批准文章执行原文正文 commit；随后按文章状态决定中文层处理：
   - 无人工正文、无机器改写：同步强制翻译并验收；
   - 存在机器 `rewrite_body_zh`：在不自动派发的受控步骤中重跑或替换改写，确保旧改写不再优先于新译文；
   - 存在人工正文/摘要：默认不自动覆盖，进入人工审核决定。
7. 逐篇核对 `effective_body`、公开状态、发布时间、文章 ID 和 QQ delivery 数不变；失败篇独立停止。

识别、原文修复、翻译、改写和公开验收必须分层记录，不能用“命令成功”替代最终公开正文验证。

### D5：不改展示层和数据模型

`public/detail.html` 不修改；否则只会隐藏已污染的有效正文，翻译、改写、搜索、QQ 和其他消费者仍受影响。
现有字段足以保存 HTML、正文和解析元数据，不需要迁移。

### D6：工作流文档与机器契约保持一致

仓库的 `.codex/scripts/check_workflow_contract.py` 当前硬编码旧七阶段字符串；工作流文档改为八阶段后，静态契约
`26/26`，避免改写既有迁移历史计数。测试先取得由旧 checker 导致的 RED，再同步 checker marker。checker 的
GREEN 必须同时覆盖 `AGENTS.md`、`docs/codex_workflow.md` 和 `docs/session_bootstrap.md` 三处八阶段文本。此项只
校验仓库治理文本，不改变应用运行态；当前方案阶段不修改脚本或测试。

## 预计实现文件


- `server/stable/adapters/international.py`：收紧 HRN 正文选择器。
- `server/stable/tasks.py`：在国际详情 upsert 前阻断失败/空正文，并复用现有 detail error/CrawlJob 摘要。
- `server/stable/test_news_content_boundaries.py`：新增 HRN 边界、fail-closed、正常反例和历史识别测试。
- `server/stable/fixtures/news_content_boundaries/hrn_9623.html`：真实结构最小 fixture。
- `server/stable/fixtures/news_content_boundaries/hrn_normal_article.html`：正常反例 fixture；若复用同一真实结构的
  独立正文片段更清晰，可只保留一个 fixture 并在测试中构造无噪声变体。
- `server/stable/management/commands/repair_article_content_boundaries.py`：只读来源扫描/审计输出，以及批准
  manifest/file SHA、事务锁行和逐篇哈希绑定；若职责审查要求拆分，改为新增相邻识别命令并复用公共解析函数。
- `.codex/scripts/test_workflow_contract.py`：扩展既有基线测试加入八阶段门禁 mutation，保持 `26/26` inventory，
  并取得 RED。
- `.codex/scripts/check_workflow_contract.py`：同步八阶段 canonical marker，使契约检查恢复通过。
- `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md`：实现/审核阶段事实更新。
- `docs/deploy_runbook.md` 与本目录 `rollout.md`：仅在后续取得发布/历史重处理授权并发生相应事实时更新。

无预计修改：模型、迁移、settings、`.env.example`、Celery 路由、公开模板和 CSS。

## 并发、事务与性能

- 新采集路径只把选择范围从 `<main>` 缩小到 `.article-body`，不增加网络请求或数据库查询。
- 历史识别按 `id > after_id`、固定 `limit` 顺序扫描，避免无界加载；每篇只解析数据库已保存 HTML。
- 识别只读，不持有长事务，不调用 `select_for_update`。
- 未来 commit 继续复用显式范围，但先在单一事务锁定全部批准行并完成全集校验；任一集合/输入哈希漂移整批回滚，
  不扩大到未批准文章。

## 可观测性

- 新采集沿用 `body_parse_status`、`body_selector`、`body_cleaning` 和 CrawlJob/来源错误摘要。
- 历史识别输出结构化计数与逐篇哈希，不把完整 HTML复制进 metadata。
- 生产验收需要分别证明新采集原文、翻译/改写输入、`effective_body` 和真实公开页面无框架污染。

## 安全与隐私

- fixture 只保留证明 DOM 边界所需的最小公开内容，不保留账号、CSRF token、广告脚本或无关整页源代码。
- 识别报告不输出完整 HTML/正文，不记录密钥、cookie 或请求头。
- 历史扫描不触网，避免实时页面变化替代原采集证据。

## 回滚

- 代码回滚：回到部署前经验证镜像/commit，暂停 HRN 抓取或自动发布，重建 web/worker/beat 后验证 healthz、
  队列和来源状态。
- 无数据库迁移，无 schema 回滚。
- 历史数据回滚：历史写入必须在单独授权和已验证备份后执行；若误裁剪，按批次 before hash/备份恢复原文及中文层，
  再逐篇核对公开状态和 QQ 幂等。
- 回滚旧代码会重新暴露宽泛 `main` 风险，因此在修复版恢复前 HRN 来源保持暂停或人工门禁。

## 方案审核记录

- 首轮结论：`REVISE`。
- 首轮 finding 1：解析失败虽然产生状态，但旧调用方仍会 upsert/派发翻译。已将“在
  `_crawl_international_source()` 调用 upsert 前验证状态与正文、失败进入现有 detail error”纳入 D1、规格、测试与任务。
- 首轮 finding 2：历史 commit 只靠文章 ID 无法证明写入仍对应人工批准输入。已加入批准 manifest/file SHA、
  全集事务锁行、集合与逐篇输入/输出哈希复核，任一漂移整批零写入。
- 首轮 finding 3：重复抓取既有文章不会常规刷新翻译/改写，不能作为公开修复验收。已把 Gate A 限定为此前
  从未入库的新文章，并把部署前全部 HRN 文章保留在历史 scope。
- 限定复审结论：首轮三项 finding 全部关闭，未发现直接 P0/P1 回归，`VERDICT: APPROVED`。
- 非阻塞执行注意：真实 HRN DOM 仍可能漂移；实现保持 fail-closed，且必须在部署/重抓前保存历史
  `max_id`，不得等到 Gate B 才冻结。
- 审核后静态校验补充：现有 workflow checker 硬编码旧七阶段 marker；已将 checker/test 同步加入待实现范围，
  当前未修改脚本或测试。补充 reviewer 首轮指出 T16 未进入 GREEN、inventory 策略未锁定；修订为 T1–T16
  全部进入 GREEN、两个契约命令必须退出 0，并扩展现有测试方法以保持 `26/26`。
- 补充限定复审结论：两项 P1 全部关闭，未发现直接 P0/P1 回归，`VERDICT: APPROVED`。
- 用户已于 2026-07-23 明确“开始实现”；测试 subagent 取得目标 RED 后，三个不重叠实现 subagent 分别完成
  新采集边界、历史 repair/scan 与 workflow checker。主代理整体验证已通过。
- 当前状态：实现完成，等待未参与实现的独立 code reviewer 执行原生只读 review。

## 代码审核记录

- 首轮 reviewer 会话：`019f8c87-a86e-7903-84f7-f6a9b494f67e`。
- 原生命令：`codex review -c 'sandbox_mode="read-only"' --uncommitted`；内层 `sandbox: read-only`，退出码 0。
- 审前/审后 fingerprint 完整 stdout 逐字节一致；本轮身份
  `FINGERPRINT_SHA256=282759c8d5b5644198d89803f0254b8612798f8d2f03f3b63c156998aab59f32`，但因存在 findings
  不构成 approved baseline。
- 首轮结论：`REVISE`，四项 P2：`empty_after_cleaning` 分类被折叠、扫描缺 workflow/translation/automation/QQ
  风险字段、runbook 仍使用旧直接 `--commit`、混合成功时 CrawlJob `fail_count` 未计详情失败。
- 修复：测试 subagent 先取得 4 项目标 RED；实现 subagent 分别补独立分类、批量 QQ 计数与状态字段、dry-run
  manifest 输入、详情失败计数；operations subagent 将 runbook 改为 dry-run → 唯一来源/精确 ID 校验 →
  manifest → file SHA → commit 的 fail-closed 流程。
- 修复后本地验证：正文边界 `43/43`、抓取相邻回归 `13/13`、workflow `26/26`、Django/static 检查通过。
- 当前状态：等待复用同一 reviewer 会话限定复审上述四项 finding 与直接触及路径。
- 第一次限定复审仍为 `REVISE`：两项已关闭；runbook 的人工审查证据尚未由 explicit dry-run 输出，且把
  `CrawlJob.fail_count` 从既有 duplicate counter 改成详情失败数会破坏消费者语义。
- 第二轮修复同样先取得目标 RED：`fail_count` 恢复 `seen_count`，详情失败通过持久消息
  `detail_failures=N` 与 source summary 记录；explicit dry-run 增加同一 ID 绑定的首尾 160 字符摘要、长度/哈希、
  workflow/translation/automation、effective layer/hash、manual/rewrite、发布时间与批量 QQ count。runbook 只依赖
  这份 artifact，并从其中 fail-closed 推导唯一来源；混合来源必须分批。
- reviewer 非阻塞建议中的 scan `before_length/after_length/length_delta` 也已补齐。
- 第二轮修复后正文 `43/43`、抓取 `13/13`、workflow `26/26`、Django/static 再次全绿；等待同一 reviewer
  会话继续限定复审。
