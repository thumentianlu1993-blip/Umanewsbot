# 赛事新闻质量治理：Claude 实现交接

## 0. 交接目的

本文是新 agent 的单一接手入口。即使没有原对话上下文，也应能据此理解：

- 线上发生了什么；
- 用户已经确认了哪些产品规则；
- 两组方案当前处于什么状态；
- 允许做什么、禁止做什么；
- 应按什么顺序完成 RED、实现、验证与独立审核。

本文不是第三个 change。实际需求由以下两组已审 durable artifacts 共同定义：

1. `docs/changes/govern-race-news-exposure/`
2. `docs/changes/unify-public-racing-terms/`

若本文与上述 `spec.md/design.md/test_cases.md/tasks.md/rollout.md` 冲突，以两组 change 的当前文件
和 `docs/current_state.md` 为准；不要按聊天记忆猜测。

## 1. 仓库、工作树与基线

- 仓库：`/Users/mentianlu/Code/umanews`
- 规划工作树：
  `/Users/mentianlu/Code/umanews/.worktrees/plan-race-news-quality-20260726`
- 规划分支：`codex/plan-race-news-quality-20260726`
- 建立时 HEAD / `origin/main`：
  `0aeb0ed7660746bdcdcbad0343aad771b1324918`
- 当前规划文档尚未 commit；它们只存在于上述规划工作树的未提交 diff 中。
- 主检出区 `/Users/mentianlu/Code/umanews` 有大量其他任务的修改，禁止在那里覆盖、清理或复用
  未确认文件。

接手后先执行只读核对：

```sh
cd /Users/mentianlu/Code/umanews/.worktrees/plan-race-news-quality-20260726
git status --short
git rev-parse HEAD
git fetch origin
git rev-parse origin/main
```

若 `origin/main` 已推进，不得直接假设方案中的代码路径仍准确。先在新的干净实现工作树基于最新
`origin/main` 做 overlap preflight，再把本交接和两组 change 文档作为当前实现 diff 带入。不要在
规划工作树写应用代码，也不要删除规划工作树。

## 2. 必读顺序

新 agent 开始前必须完整阅读：

1. `AGENTS.md`
2. `docs/codex_workflow.md`
3. `docs/session_bootstrap.md`
4. `docs/project_overview.md`
5. `docs/current_state.md`
6. `docs/decisions.md`
7. `docs/deploy_runbook.md`
8. 本文
9. `docs/changes/govern-race-news-exposure/{spec,design,test_cases,tasks,rollout}.md`
10. `docs/changes/unify-public-racing-terms/{spec,design,test_cases,tasks,rollout}.md`

本项目已停用 旧规格流程。禁止调用任何 `旧规格流程-*` skill 或 旧规格流程 CLI，也不要在
`旧规格流程/changes/` 下建立新 change。

## 3. 当前工作流状态与授权

固定流程：

```text
探索
  -> spec/design
  -> 方案审核
  -> 测试先行
  -> subagent 实现
  -> 独立 reviewer 会话 /review
```

当前状态：

- 探索：完成。
- 两组 `spec/design/test_cases/tasks/rollout`：完成。
- fallback 工程方案审核：首轮 `REVISE`，修订后限定复审 `VERDICT: APPROVED`。
- RED、应用代码、配置、migration、历史数据处理：尚未开始。
- commit、push、PR、部署、生产写入：未授权。


- 编写和运行自动化测试，取得真实 RED；
- 启动符合仓库规则的测试/实现 subagent；
- 修改应用代码、模型、migration、配置和本地文档；
- 运行本地 SQLite / PostgreSQL / Docker 验证。

上述授权不允许：

- commit、push、创建或合并 PR；
- 部署、迁移生产数据库、重启生产服务；
- 写入正式术语、回填历史文章、创建/修改生产 exposure；
- 发送 QQ 或改动任何生产数据。

与历史数据 apply 也应分开报告和授权。

## 4. 线上问题与诊断证据

### 4.1 同一赛事新闻占据首页

2026-07-26 对生产公开首页和后台记录做过只读诊断：

- 首页最新区域约 11 个可见位置中，9 篇普通稿件属于同一英皇锦标事件，头条也属于该事件。
- 代表文章 ID：
  `10081, 10082, 10083, 10084, 10086, 10088, 10090, 10091, 10098, 10105`。
- 这些文章均为自动发布并在对应发布窗口入选，没有被记录为 `duplicate` 或 `dedupe_loser`。
- 当前正文 Jaccard 复算最高约 `0.3438`，低于现有近似去重阈值；因此“调低一个相似度阈值”
  不能正确区分硬重复和同赛事不同角度。
- `10082` 与 `10084` 的日文来源标题完全相同，但历史发布窗口没有硬标题规则，二者在同一窗口
  同时入选。当前代码重算能够发现精确标题相同，历史为何漏判仍需用冻结快照回归测试证明。

现有相关实现：

- `NewsArticle.duplicate_of/duplicate_score/duplicate_reason`
- `ArticleRaceLink`
- `stable.services.publishing_windows.select_publish_candidates`
- `stable.services.qq_windows.select_qq_window_deliveries`
- `stable.services.qq_auto_push`
- `stable.services.editorial_headlines`
- `stable.views.public_news_feed`

根因：当前 `content_fingerprint()` 只解决单窗口内容重复；首页头条、普通列表、热门榜和 QQ 没有
共享的 `RaceEvent` 级曝光预算。

### 4.2 多语言术语不一致

生产只读诊断发现：

- `Kalpana -> 幻梦逸想` 对应现有 `TermEntry#6013`，源语言为英语。
- 该记录地区元数据为法国，但现有身份线索指向英国；不得直接静默改字段，必须进入正式 mapping
  审核包。
- 没有日文 `カルパナ` alias，因此日文稿把它视为未知词并保留。
- 英文文章中 `Kalpana` 有时被 occurrence classifier 判为 uncertain 而保留，有时在强马匹语境
  下翻译为“幻梦逸想”。
- `Calandagan` 等其他马名存在同类问题。
- 英文赛事全称已有映射到“英皇锦标”，但缺少常用短称 `King George` 和相应日文短称/全称，
  AI 改写因此产生“乔治六世锦标”“英王乔治锦标”等变体。

现有相关实现：

- `TermEntry`
- `TermAlias`
- `TermCandidate`
- `TermCandidateEvidence`
- `stable.services.terms`
- `stable.services.validation`
- `stable.services.automation`
- `stable.services.term_gate_reprocessing`
- `stable.test_english_term_context_gates`
- `stable.test_term_gate_reprocessing`

根因：多语言 surface 没有完整汇聚到同一正式实体；公开字段缺少共享 canonical consistency
门禁；已有 published audit 没有针对正式术语一致性的字段级 CAS repair。

## 5. 已锁定产品规则

### 5.1 新闻曝光

1. 同一赛事允许保留不同角度的稿件。
2. 首页同一赛事最多 2 篇，头条计入这 2 篇。
3. 第一篇可信综合赛果立即进入首页和 QQ。
4. 第二席等待约 15 分钟，从明确不同角度稿件中择优。
5. 后续更优稿只替换首页第二席；第一席不被自动无声替换。
6. 已发 QQ 不撤回、不因首页替换而重发。
7. 同一目标群对同一 `RaceEvent` 最多发送 2 篇。
8. 超额文章仍保持公开详情 URL，并出现在赛事详情页；不进入首页分页、热门榜或 QQ。
9. 赛事身份以 `RaceEvent.id` 为权威；身份不唯一时 fail closed，不按名字跨年度猜测。

### 5.2 术语

1. 本赛事正式公开简称为“英皇锦标”。
2. `Kalpana` 与 `カルパナ` 应归到同一正式马匹术语“幻梦逸想”。
3. 已有可靠中文名时，标题、摘要、正文、push summary 和标签统一使用 canonical 中文名。
4. 源文永久保留。
5. 身份、语言、地区或 occurrence 语境不可靠时保留原文，不猜译。
6. 不能因为某个英语 surface 在别处是马名，就把全文所有同形 occurrence 当作马名。
7. 已发布文章要受控修复，但不得覆盖人工字段、改变 slug/公开时间/workflow 或重发 QQ。

## 6. 已审技术方案摘要

### 6.1 `RaceNewsExposure`

新增赛事曝光模型，核心字段：

- `event`、`article`
- `channel=homepage/qq`
- `scope_key=site/target:<id>`
- `slot=1/2`
- `status=waiting/active/replaced/sent/suppressed`
- `angle`、`policy_version`、`reason`、`evidence`
- `delivery`、lease 与替换审计字段

关键约束：

- 同一 event/channel/scope/article 唯一；
- 首页 `waiting/active` 同席位唯一；
- QQ `waiting/active/sent` 同席位唯一，已发两席永久占用；
- `slot` 只允许 1/2，channel/scope 组合必须合法。

赛事身份解析必须使用现有真实枚举：

- 优先唯一 `ArticleRaceLink.status=manual`；
- 其次唯一无冲突且达到可靠阈值的 `status=auto`；
- `candidate/removed` 不能作为身份；
- `link_type=post_race` 只是关系类型，不等于主身份。

QQ 的 quota、exposure 和 delivery 在同一数据库事务中创建/绑定，事务内不访问 OneBot。发送结果
不明或已有 message ID 时保留席位并人工核对，不能自动重试制造第三次实际发送。

### 6.2 硬重复与角度

硬重复和曝光密度是两套规则：

- 同来源 ID、同赛事规范化来源标题完全相同、内容指纹相同等写入 `duplicate_of`；
- 同赛事但角度不同不写 `duplicate_of`，只竞争两席。

角度固定枚举：

```text
comprehensive_result
winner
connections
runner
analysis
market
other
```

结构化证据优先，模型只能给枚举候选；冲突/低置信使用 `other`。`other` 不能自动证明第二篇与第一篇
角度不同。

### 6.3 正式术语与证据

继续使用：

- `TermEntry`：正式实体及唯一 `target_zh`
- `TermAlias`：英语/日语等源语言别名
- `TermEntry.aliases_zh`：旧中文搜索/兼容别名

不要给 `TermAlias.source_language` 伪造中文值。

新增 `TermMappingEvidence`，保存正式术语/alias 的来源、digest、identity SHA、审核状态和审核人。
现有 `TermCandidateEvidence` 只证明文章 occurrence，不能替代正式身份/译名来源证据。

### 6.4 occurrence resolver 与 published repair

共享 resolver 优先级：

1. 已确认赛事中的 runner/result/participant；
2. 已确认文章马匹链接；
3. 唯一 active alias + 强赛马语境；
4. 否则保留原文。

输出 term/alias、字段位置、`confirmed/uncertain/conflict`、证据和版本。只替换 confirmed occurrence。

历史修复复用 `term_gate_reprocessing`，新增 `canonical_term_consistency` issue 和字段级 patch：

- dry-run -> manifest -> 人工审核 -> approval -> CAS apply -> verifier/rollback；
- 允许字段以 change design 为准；
- `manually_edited_fields` 中的字段整字段跳过；
- 源文、QQ、通知、slug、公开时间和 workflow 守恒；
- 任一 before hash 或 mapping version 漂移时首批整批停止。

## 7. 实现前 overlap preflight

已知可能重叠的并行线：

- `normalize-race-and-career-fields`
- `fix-external-english-horse-context-gate`
- `automate-race-event-lifecycle`
- `translate-collected-race-horse-names`
- 主检出区 `news_reflect`

在最新 `origin/main` 重新检查：

- `server/stable/models.py`
- 最新 migration 图
- `server/stable/services/terms.py`
- `server/stable/services/validation.py`
- `server/stable/services/automation.py`
- `server/stable/services/term_gate_reprocessing.py`
- `server/stable/services/publishing_windows.py`
- `server/stable/services/qq_windows.py`
- `server/stable/services/qq_auto_push.py`
- `server/stable/services/editorial_headlines.py`
- `server/stable/views.py`
- `server/stable/tasks.py`

如果并行线已改变模型、术语解析、published audit、赛事关联或窗口语义，先更新 design/test cases，
回到原方案 reviewer 上下文复审直接受影响路径，再继续 RED；不要复制成第二套服务。

## 8. 推荐实现顺序

两项 change 使用一个协调实现分支，避免 migration 与共享 resolver 冲突。写密集任务默认串行。

### 阶段 A：冻结基线与测试文件边界

1. 基于最新 `origin/main` 建立干净实现工作树。
2. 把本交接和两组 change 文档带入实现 diff。
3. 完成 overlap preflight 和 migration leaf 检查。
4. 明确测试 subagent 与实现 subagent 的文件所有权；禁止 subagent commit/push/deploy/生产写入。

### 阶段 B：术语 RED

先委派测试 subagent 编写：

- 多语言 alias 汇聚/冲突；
- `TermMappingEvidence` 约束和未批准 evidence fail closed；
- occurrence 级英文语境；
- 标题/摘要/正文/push summary/标签 canonical；
- published dry-run/CAS/人工字段/守恒/rollback；
- 10/20/100 篇性能边界。

实际运行并保存真实 RED。失败必须是目标能力尚未存在，不得来自 fixture、语法或环境。

### 阶段 C：术语 GREEN

串行委派 integration/application subagent：

1. `TermMappingEvidence` 模型与 migration；
2. 正式 mapping 审核包；
3. occurrence resolver；
4. 新文章一致性门禁；
5. published audit dry-run/apply/rollback；
6. 后台审计；
7. 聚焦 GREEN 和受影响回归。

这一步只能实现本地能力，不得写生产 `TermEntry/TermAlias` 或修复生产文章。

### 阶段 D：曝光 RED

委派测试 subagent 编写：

- 现有枚举下的唯一赛事身份与 unresolved；
- 精确标题硬重复；
- 角度与两席状态机；
- 首页/分页/热门榜/头条共同计数；
- QQ 两席、失败/重试/结果不明；
- 并发唯一约束、lease 与事务回滚；
- 历史 exposure dry-run/manifest/守恒；
- 查询数和 PostgreSQL 性能边界。

保存真实 RED。

### 阶段 E：曝光 GREEN

串行委派 application/integration subagent：

1. 主赛事身份与硬重复分类；
2. `RaceNewsExposure` 模型/migration/状态机；
3. 首页、热门榜和头条接入；
4. 即时 QQ 与窗口 QQ 接入；
5. 后台审计、metrics、shadow 开关；
6. 历史 exposure 只读盘点/dry-run；
7. 聚焦 GREEN 和受影响回归。

### 阶段 F：整体验证

至少执行：

- Django check；
- `makemigrations --check --dry-run`；
- migration plan 与 PostgreSQL migration 测试；
- 两组新增测试；
- publishing/QQ/headline/term/reprocessing 受影响回归；
- 查询数、100 篇/2 万 alias 和 QQ 100 篇×5 目标形状；
- `git diff --check`；
- shadow 模式的冻结英皇锦标样本；
- 本地 1440px / 390px 首页、分页、热门榜、赛事详情和文章详情；
- console、URL、overflow 和无真实 QQ 发送验证。

不要把本地验证表述为生产证据。

## 9. RED 与关键 mutation

测试必须能捕获以下错误实现：

- 只调低 Jaccard 阈值，导致不同角度稿件被误标 duplicate；
- 头条不计入首页两席；
- 手工头条在 15 分钟内绕过第二席；
- QQ 只按 article 去重，没有 event/target 两席；
- worker 崩溃后释放了结果不明的席位并再次发送；
- 用赛事中文字符串代替 `RaceEvent.id` 聚类；
- 使用不存在的 `ArticleRaceLink.confirmed/PRIMARY` 枚举；
- 把旧中文译名写进不支持中文的 `TermAlias.source_language`；
- 没有 approved mapping evidence 也激活 alias；
- 对英文 surface 做全文字符串替换；
- 覆盖 `manually_edited_fields`；
- published repair 触发 QQ、通知或重新发布；
- per article × 全量术语，或 article × target N+1。

## 10. 性能与容量门禁

曝光：

- 首页 50 篇候选，赛事 link/exposure 额外查询不超过 3 次；
- QQ 100 篇候选、5 个目标群，禁止 article × target 查询；
- 本地 PostgreSQL QQ 选择阶段不超过 5 秒；
- production-shaped shadow 的首页 p95 相对关闭策略时退化不超过 20%。

术语：

- 本地 PostgreSQL 100 篇、2 万 active alias dry-run 不超过 10 秒，ORM 查询数保持常数；
- 生产只读阶段未来从 20 篇开始；超过 512 MiB RSS 或 30 秒必须停止扩大。

这些是门禁，不是当前已经取得的结果。

## 11. 灰度与历史数据边界

计划开关：

```text
RACE_NEWS_EXPOSURE_ENABLED=false
RACE_NEWS_EXPOSURE_SHADOW=true
RACE_NEWS_SECOND_SLOT_DELAY_MINUTES=15
RACE_NEWS_HOMEPAGE_MAX=2
RACE_NEWS_QQ_TARGET_MAX=2
```

实现时补充术语一致性 shadow/enforce 开关，并在 `.env.example`、settings 和部署文档中保持一致。

未来发布顺序：

1. schema + 代码，所有新行为关闭；
2. 术语 consistency shadow；
3. 新闻 exposure shadow；
4. 审核 shadow；
5. 首页 enforce；
6. 测试群 QQ enforce；
7. published term repair dry-run；
8. exposure 历史 dry-run；
9. 两类生产 apply 分别重新授权。

关闭 enforce 是首选行为回滚。正常回滚保留审计表；不要在紧急回滚中删表。

## 12. 独立 code review 与发布停点

实现与主代理整合验证完成后：

1. 派出未参与本轮实现的 reviewer；
2. 实际运行 Codex 原生只读 review；
3. 使用 `docs/codex_workflow.md` 指定的 fingerprint helper；
4. 所有 actionable findings 修复并回到同一 reviewer 会话限定复审；
5. 得到成功 review 后停止。

必须向用户汇报：

- 根因和最终改动；
- RED/GREEN 命令与结果；
- migration、性能、并发和浏览器证据；
- 历史 dry-run 尚未/已经生成，但未 apply；
- reviewer 结论和冻结 fingerprint；
- 发布、术语写入、历史文章修复、exposure 回填仍需哪些授权。


## 13. 文档回写

实现完成、首次 code review 前，更新并纳入完整审核范围：

- 两组 change 的 `test_cases.md/tasks.md/rollout.md`
- `docs/current_state.md`
- `docs/decisions.md`（只有新增行为决策时）
- `docs/project_status.md`
- `docs/project_overview.md`（只有产品链路实际变化时）
- `docs/deploy_runbook.md`（配置、migration、灰度、验证和回滚命令）

部署后的事实证据严格按 `docs/codex_workflow.md` 的 evidence-only closure 处理，不要提前写成已发生。

## 14. 当前交接结论

```text
plan review approved
implementation authorized for Claude
implementation not started
no RED yet
no code or migration yet
no commit / push / PR
no deployment
no production term or article write
```

新 agent 的下一动作不是再次讨论产品口径，也不是操作生产；而是：

1. 读取本文及两组已审 artifacts；
2. fetch 最新 `origin/main`；
3. 建立干净实现工作树并完成 overlap preflight；
4. 按阶段 B 委派测试 subagent，取得第一组真实 RED。
