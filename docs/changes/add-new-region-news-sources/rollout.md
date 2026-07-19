# 新地区新闻抓取 rollout

## 当前边界

- 当前验收 worktree：
  `/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-release-candidate`
- 当前分支：`codex/add-new-region-news-sources-release-candidate`
- 集成时点基线与 HEAD：`a122ff6dde16ab4b53f34e446b0f959751ad7a77`
- main 对齐：第三次集成时 `origin/main=HEAD`，`origin/main..HEAD=0`。
- 集成形态：基线 HEAD 上保留全部目标变更，尚未为当前候选 commit、push 或创建 PR。
- 回退副本：`add-new-region-news-sources-integrated`、
  `add-new-region-news-sources-main-integrated` 与
  `add-new-region-news-sources-final-integrated` 三个旧 worktree；不在其中继续验收或发布。
- 当前阶段：首次独立代码审核 `REVISE (2 P1 + 5 P2)` 的七项 finding 已 RED/GREEN 修复。
  同一 reviewer 修复复审实质 `APPROVED`，但 main 漂移令完整性门禁 `BLOCKED`；当前已经
  重新集成最新 main，下一门禁是 release-candidate 精确版本复审。后续统一使用仓库原生流程，
  不再使用 OpenSpec。
- 当前禁止：commit、push、PR、部署、生产迁移/写入、启用来源、自动外部发布或 QQ 推送。
  旧 review 和旧授权均不覆盖当前集成版本。

## 2026-07-20 第三轮 live evidence 收口

- 使用已迁移的仓库外 `/tmp` SQLite；透明 bounded HTTP；每源 listing `1`、detail 最多
  `2`；不连接或写入生产。首次空库 `no such table` 是环境问题，迁移后重跑才作为正式 probe。
- 24-source registry 为 `16 accepted / 8 blocked`，全部 internal-only/public-false。
  accepted：RTÉ、IrishRacing、Dubai Racing Club、JCSA、SPA、Racing Victoria、Just Horse
  Racing、The Straight、Racing NSW、Tasracing、TDN、BloodHorse、Horse Racing Nation、
  Sky Sports Racing、Sporting Life、BHA。blocked：HRI、Woodbine、Canadian
  Thoroughbred、Assiniboia Downs、ERA、The National、Arab News、Paulick Report。
- 第三批 12 源为 `8 accepted / 4 blocked`；四个 blocked 是 Canadian Thoroughbred、
  Assiniboia Downs、The National、Arab News。IrishRacing、SPA、Racing NSW、Tasracing
  均按 live 结构 TDD 修复并复探 accepted；Racing NSW 排除 tips/preview，generic
  `Latest News` 不覆盖 RSS 标题。
- HRI/Woodbine/ERA listing 虽 HTTP `200`，仍因详情 `missing_published_at` 端到端 fail
  closed。TDN 正文成功后 technical accepted，但本次时间 evidence unverified，不进六小时
  候选。JCSA、Racing Victoria live accepted。
- 约 `2026-07-19T17:41Z` 的严格最近六小时只得到 Ireland `2`：
  RTÉ `Power Blue back to winning ways at the Curragh`
  （`15:09:15Z`，verified）和 IrishRacing
  `Tokyo Tower shows resolution to land Curragh finale`
  （`16:51:00Z`，verified）。Canada/UAE/Saudi/Australia 均为 `0`。TDN 因 unverified、
  JHR 因 `10:09:13Z` 超窗、其余来源因更早日期/时刻均不计。本轮样本全为精确时间，没有
  使用 date-only `0/1` 日规则提高数量。
- 综合源离线 attribution 回归确认 Curragh/Irish Oaks -> Ireland、Woodbine/Canadian ->
  Canada，无关键词保留原 US/UK region。Sporting Life technical accepted，但因 unverified
  time 延后进入候选。
- 同一迁移临时库使用真实 RTÉ 正文 `6616` 字符和 dummy provider：
  `translate_article_task` 返回 `translated=true`，article 为 `translated`，
  `TranslationRun=success`，标题明确带 `[未配置真实翻译模型]`。本机 SiliconFlow/OpenAI
  key 均 absent，故只验收任务/持久化编排；真实中文远程模型仍未完成。
- 最新 release-candidate 离线组合为 `214/214 OK`、follow-up `10/10`；migration 无漂移、Django checks
  通过。来源实现代理另报告 `202 + 1 skip`、translation recovery `22/22`。
- rollout 后续硬门：同一 reviewer 审核最终精确版本 -> PostgreSQL 专项 -> 生产 TLS/私有
  media -> 用户新授权 -> commit/push/PR/deploy。所有第三批来源保持
  `enabled=false / production_approved=false`。

## 2026-07-20 首次代码审核修复与第二轮 main 集成（历史检查点）

- 首次独立代码审核提出 `2 P1 + 5 P2`。七个 finding test 取得
  `7 failures / 0 errors` 的真实 RED；修复后定向 `7/7`。
- 来源级 `usage_scope=internal_only` / `public_publish_allowed=false` 现在独立于全局登录墙，
  公开 queryset、详情和 QQ 共用文章级 blocker。`DEBUG=false` 内部模式要求 session/CSRF
  secure cookies，并且只能采用 direct HTTPS redirect，或显式 trusted TLS termination 加
  合法 `SECURE_PROXY_SSL_HEADER`；其他组合启动 fail closed。
- translation retry selector 在外部 AI 关闭时 claim 前跳过，preclaim 状态被释放，batch skip
  不计 translated。通知只保留安全 counts/IDs，翻译失败耗尽消息改为
  `article_id`-only；TDN freshness metrics 和 probe canonical normalize/拒绝原因闭环。
- 同一 reviewer session 对修复范围实质确认 `APPROVED`，但审核期间 main 漂移，因此完整性
  结果是 `BLOCKED`。二次集成到 `58f00961…` 不能继承该批准，最终精确版本仍待同 session
  复审。
- migration 最终唯一 leaf 为无操作 `0050_merge_20260720_0017.py`：它合并 main 的
  `0048_raceeventrunner_external_runner_identity.py` 与功能
  `0049_alter_newsarticle_source_site_and_more.py`；此前双 `0047` 与功能 `0048_merge` 保留。
- 最新验证：findings `7/7`、重点功能 `175/175`、translation failure recovery `22/22`、
  latest-main release-gate `69 OK`（SQLite 跳过 PostgreSQL 专项 `15`）、race-live
  `37/37 + 63/63`；migration check/plan/test DB migrate、Django checks、diff/cached diff 和
  相关 `py_compile` 通过。
- 当前仍未完成最终精确版本复审、12 源受控 live probe/最近 6 小时汇总/真实翻译实跑、
  PostgreSQL 专项、生产 TLS/私有 media、commit/push/PR/deploy。

## 2026-07-19 首次 main 无提交集成检查点（历史）

- 第三批 12 个来源已按设计清单实现，均为
  `enabled=false / production_approved=false`；Google News 未实现。既有 HRI、Woodbine、
  ERA 保持 technical blocked，JCSA/Racing Victoria 保持 unknown；当前集成 worktree
  尚未重新探测，不改写为 accepted。
- 内部访问、受保护媒体、QQ/PushLog/内容通知外发和 translation/rewrite 外部 AI 门禁已实现；
  默认 `SITE_INTERNAL_ONLY_ENABLED=true`、
  `NEWS_EXTERNAL_AI_PROCESSING_ENABLED=false`。HTTPS 或获准 TLS 与 local protected media/
  私有 OSS 短签名是生产前置，不安全配置 fail closed。
- 日期精度按来源当地日期判定：可信发表日与抓取日差 `0/1` 天进入候选，`>1` 天归历史，
  无可信时间或 evidence/precision/时区无效归 `unresolved`，均在 upsert 前停止。
- 双 `0047` migration 已用
  `0048_merge_20260719_2242.py` 汇合，之后为
  `0049_alter_newsarticle_source_site_and_more.py`；`makemigrations --check` 无漂移，
  `migrate --plan` 可解析。
- 真实 RED 为 `62 tests / 74 expected failures / 0 errors`。最终门禁目标 `47/47`，
  重点功能独立复核 `175/175`，race-live 集成回归 `37/37 + 63/63`；
  `manage.py check`、`git diff --check`、cached diff check 通过。旧测试维护只在测试中
  显式关闭内部总门并补 `production_approved` fixture，没有放宽生产默认。
- 未完成：12 源最终受控 live probe、真实翻译实跑、PostgreSQL 专用/生产运行态验证、当前
  集成版本独立代码 review、用户新授权、commit/push/PR/deploy。所有新来源仍不可生产调度。

## 2026-07-19 内部使用策略切换

- 用户明确决定：网站只供内部使用，不向外部访客发布新闻原文和译文；除透明请求技术上
  无法取得的站点外，其他来源均按内部候选处理。
- 本轮必须先实现并验证全站认证门禁、匿名 API `401`、robots `Disallow: /`、sitemap 隐藏
  、受保护媒体及 QQ/PushLog/邮件外发零副作用，再允许任何新增来源进入内部常态抓取。
- 既有 permission registry 不删除历史证据，但从“法律/条款阻断”改为“技术准入 + 内部
  scope + 公开禁止 + terms risk”四轴。`production_approved` 仍只作为运维开关且默认 false。
- 第三批计划新增 12 个直接来源；Google News RSS 仅保留为后续研究方法，本批不实现
  collector，也不保存聚合 metadata 或正文。
- 外部 AI translation/rewrite 处理由共享默认关闭开关控制；采集成功、真实翻译成功与真实
  改写成功分开报告。
- 该策略切换时的源 worktree HEAD `42a06f47` 与当时的 `origin/main@85948707` 各自领先一个提交；主线新增
  race-live `0047`，本 change 也有 `0047`。发布前必须在独立集成检查点解决 migration 和
  触及代码冲突，不能把当前分支直接部署。
- 本轮从 spec/design 变更重新进入方案审核；先前成功代码 review 和历史用户授权均因需求、
  fingerprint 与主线发生变化而失效。
- 生产启用内部模式的前置条件是 HTTPS 或获准的私网/VPN TLS 入口，以及 local protected
  media 或 private OSS 签名链路验收；当前 HTTP-only Nginx 不满足部署门禁。本轮可以完成
  代码与离线验证，但不得把未完成 TLS 的生产环境标为可上线。

## 2026-07-19 第二批增量边界

- 用户确认：原文只有发表日期时，以来源当地“发表日期”和“抓取日期”的绝对日差判定；
  `<=1` 天进入候选池，`>1` 天作为历史新闻。
- 爱尔兰、加拿大优先复用既有英国/美国/全球 adapter，不复制 canonical 来源；地区依赖文章
  强证据，许可依赖 canonical 来源。
- UAE/Saudi/Australia 新调研入口若官方条款 blocked 或透明请求 403/406，则只记录 no-go，
  不绕过、不新增生产 adapter、不抓正文。
- 本增量允许仓库外隔离 SQLite、blocked 零请求、unknown 每源列表 1 次/详情最多 2 次；
  生产来源、自动发布和 QQ 继续全关。
- 方案 Round 1 为 `VERDICT: REVISE`：canonical permission preflight、content-scoped
  mode-off 候选、硬请求预算、旧 TDN 隔离证据处置、固定 freshness 摘要和 Canadian
  可复跑边界共 6 项。修订后 live 范围收窄为 JCSA/Racing Victoria；Canadian 只用已取得
  最小证据，blocked 来源零请求。
- 方案 Round 2 仍为 `VERDICT: REVISE`：需要进一步避免 registry 误停现有生产来源、把
  content-scoped target 变成 upsert 前单次不可变 preview、把预算下沉到每个 HTTP redirect
  hop、统一 blocked crawl 的零请求 CrawlJob 审计合同。Round 3 修订将 production enforcement
  收窄到显式 managed canonical 集合并增加默认关闭 flag；TDN 是唯一潜在既有生产差异，启用
  前必须单独核对运行态、取得精确停抓授权。本轮保持 flag 关闭，不改变生产选择集。
- 方案 Round 3 仍为 `VERDICT: REVISE`，唯一剩余问题是 flag 关闭时 public/direct task 可能
  绕过 blocked 门禁。Round 4 将 public/direct task 与自动 scheduled task 拆成不同入口：
  probe、隔离 runner、public/direct 始终 managed preflight；只有无外部 origin/bypass 参数的
  scheduled task 受默认关闭 flag 控制。这样既保留现有自动生产选择集，又保证本轮所有显式
  抓取 blocked 来源为零请求。

## 2026-07-19 最近 6 小时隔离抓取与翻译 smoke

- 固定 UTC 窗口：`2026-07-19T00:43:47Z..06:43:47Z`；独立 SQLite：
  `/private/tmp/umanews-new-region-six-hour-20260719T0644Z.sqlite3`，已迁移至 `0047`。
- permission `blocked` 的 HRI/Woodbine/ERA 未联网。permission `unknown` 的 JCSA 和
  Racing Victoria 分别按列表 `1`、详情最多 `2` 的透明 UA 预算执行：
  - JCSA：technical `accepted`、artifact
    `09c67e68847ba1a502078196d5db2ade21fb2921b579a5c8644acfd540e14afd`，最新样本
    `2026-03-22T14:00:00Z`；
  - Racing Victoria：technical `accepted`、artifact
    `65515fbd10c31fb529cffd1871e2f7a0fe01451c71ebc3da0f03cb7b0128b6d8`，最新样本
    `2026-07-15T20:55:00Z`。
- TDN 全球补漏 artifact
  `268ac6eed6bd8c628722f5debfc23bc91a5b81402b7071d70151c563f1414fb3` 有两篇窗口内美国稿，
  不属于新五区。五个目标地区本窗口均为 `0`。
- 本机翻译 provider 密钥为空。用第一篇窗口内 TDN 稿运行真实任务状态链路后，
  `TranslationRun=success / translation_status=translated / workflow_status=pending_edit`，
  但 provider/model 均为 `dummy`，标题明确标记 `[未配置真实翻译模型]`，正文仍英文。
  该结果只证明机械链路，不是实际中文翻译。
- 隔离库最终 `NewsArticle=1 / TranslationRun=1 / published=0 / QQ delivery=0 /
  NotificationLog=0`。新五来源仍全部 `enabled=false/production_approved=false`，未连接
  生产、未部署、未发布、未推送。

## 2026-07-19 本地实现检查点

- Checkpoint B 已完成：原专用测试 `22` 个逻辑用例中 `21` fail / `1` pass，失败均来自目标
  能力缺失。
- Checkpoint C 的 SQLite/聚焦范围已完成：初始专用范围曾为 `30/30` GREEN；补救后当前
  专用 `51/51`、归属/法国时间组合 `151` 个通过加 `1` 个既有 live probe 跳过；既有
  来源/QQ/抓取/首页回归 `69/69`。
- `manage.py check`、migration drift 和 `git diff --check` 通过；同步最新主线后本 change
  migration 顺延为 `0047`。
- 五来源定义仍全部 `enabled=false/production_approved=false`；候选归属开关及 source
  allowlist 默认空/关闭，全局 attribution mode 未改变。
- Checkpoint D 已执行首轮但未通过：五源技术状态均为 `deferred`；HRI/Woodbine/ERA
  permission 为 `blocked`，JCSA/Racing Victoria 为 `unknown`，当前不能宣称任何来源
  `effective_production_status=eligible`。
- 临时 PostgreSQL migration smoke、390px 浏览器视觉 QA 和 Compose config 仍待后续
  检查点。本地实现没有触发生产、翻译、发布或 QQ。
- 本 change 的新有界 HTTP 路径只接受 `200`，其他状态 fail closed；结构化安全异常和
  adapter 元数据已让 probe/crawl 保留精确 `403/429` 与最终 URL，并覆盖 `360` 分钟
  blocked backoff。旧 helper/default headers 与旧 adapter 路径未改变。

## 2026-07-19 首次代码 review 修复

- 原生只读 reviewer 会话：`019f76e0-c8a5-7330-9da1-f51f279a0dd0`。
- 首次结论：`VERDICT: REVISE`，共六项 actionable findings。
- 六项均先取得专用测试真实 RED：`36` 个测试中 `11` 个 failure/subTest failure；修复后
  `36/36` GREEN。
- 直接归属/时间回归更新为 `136` 个通过、`1` 个既有 live probe 跳过；来源/QQ/抓取/首页
  回归仍为 `69/69`。
- 修复后五来源仍默认关闭、未生产批准；新五来源已从默认 probe 外联矩阵移除，只能显式
  `--source` opt-in。
- 当前状态：六项 finding 已关闭并完成限定复审；这仍不是发布授权。

## 2026-07-19 限定复审批准

- 首次 `REVISE` 的 `F1-F6` 均为 `CLOSED`。最终限定复审 native session 为
  `019f76f0-ef8b-71d1-a0ad-246d26352f0e`；header：workdir
  `/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources`、model
  `gpt-5.6-sol`、approval `never`、sandbox `read-only`。
- 复审命令 exit `0`，结论 `VERDICT: APPROVED`。前后 helper 均 exit `0` 且原始输出逐字
  一致：
  - `FINGERPRINT_SHA256=7858ebb1e71c4f19860493c58dca9362c39c10fd99d770ebe3c310d0f23bcf3e`
  - `content_manifest_sha256=24608da5ef542932c3e4a6535e549cc5ce0b253862f1a5b9e55378e2a4e97064`
  - `tracked_diff_sha256=11e460c7ebccba7ade08daabe4ac9231de27d93f36fcd19a27c07a01de057c57`
  - `untracked_manifest_sha256=b2d6b831aa80d241a3bae90fa1a07dc84c4e815bb93fcaae2e1cc0e5cec3a66d`
- Reviewer 提出三项非阻断、范围外后续建议：评估旧 adapter `empty_listing` 影响、补非 ISO
  visible date 解析、检查地区关键词 substring boundary。这三项不是本次 finding，也未标为
  已验证。
- 批准绑定本次状态文档回写前的候选。本次 `current_state`、项目文档和 change artifact
  回写已改变 fingerprint，docs patch 本身尚未复审；需复用同一 reviewer 做 docs-only
  只读核对。当前继续无 commit、push、PR、deploy 或生产验证。

## 2026-07-19 Docs-only 一致性复审

- Native session：`019f76fb-5494-7a63-b9e5-b4d5a6985bff`；sandbox `read-only`，
  复审命令 exit `0`，fingerprint 前后一致。
- 结论为 `VERDICT: REVISE`：共享 choices 的结构化字段影响、临时 PostgreSQL 状态、
  非 200 精确分类缺口和测试文档阶段需要修正，因此受审 current docs 基线未获批准。
- 本轮只修复这些文档 findings，没有改代码、测试、配置或迁移；修复后由同一 reviewer
  在 native session `019f7705-375e-7ee3-aaa4-8125215be390` 限定复审为
  `VERDICT: APPROVED`。
- 批准 fingerprint 为
  `e28e8a433934de9d67c03d01f3277b59ec576db48e8771a30b29f748cec8a38c`。
  后续真实 probe 与本轮补救文档再次改变内容，旧批准不覆盖当前候选。

## 2026-07-19 首轮真实来源 proof

- 使用显式 `--source`、`--limit 2`，每源列表 1 请求、详情最多 2 请求；为只读重复计数创建
  仓库外迁移后临时 SQLite，未写 `NewsArticle`、未翻译、未发布、未推 QQ。
- 五站列表入口均 HTTP 200，但现有 adapter 技术状态全部 `deferred`：
  - HRI：6 条，2 个详情均 `missing_published_at`。
  - Woodbine：只错误匹配 `/news/` 根入口，详情 `missing_published_at`。
  - ERA：1 条真实文章，详情 `missing_published_at`。
  - JCSA：旧媒体工具入口空列表。
  - Racing Victoria：静态新闻页空列表。
- 浏览器只读补充证明确认：JCSA 的公开 HTML 片段为 `/api/news/en/0/12`；Racing Victoria
  动态列表可见，但前端 GraphQL 依赖公开客户端配置，因此补救改用官方 sitemap，不保存或调用
  该前端凭据。
- 对一个已知 Racing Victoria 详情 URL 的单次透明 UA GET 进一步证明：静态 `#__next` 为空，
  route `Title/ArticleDate` 与主正文 `RichText` 位于 `script#__NEXT_DATA__` 的
  `headless-main`，footer 另有 copyright RichText，fixture 必须证明二者不会混淆。
- robots 当前未禁止普通新闻路径，但不等于内容再利用许可。官方条款核验结果为
  HRI/Woodbine/ERA `blocked`，JCSA/Racing Victoria `unknown`。五来源继续
  `effective_production_status=production_blocked`。
- 本轮把真实 selector、非 ISO/JSON-LD/`__NEXT_DATA__` 时间正文、透明 User-Agent、
  逐请求 XML allowlist 和精确 `403/429` crawl/backoff 诊断纳入补救范围。补救必须重新走
  plan review、RED、GREEN；只对 permission `unknown` 的 JCSA/Racing Victoria 做同预算
  技术复测，三个 blocked 来源不再联网；之后回到同一代码 reviewer，旧批准不再覆盖。

## 2026-07-19 补救方案限定复审

- 复用同一方案 reviewer 完成 Full mode 两轮限定复审。Round 1 提出五项：
  blocked 来源仍计划联网、403/429 未覆盖 crawl/backoff、RV 正文证据不足、XML/UA 未逐请求
  隔离、来源齐备混用 accepted/eligible。
- Round 2 逐项确认 `CLOSED`，未发现修复引入的直接 P0/P1 回归，结论
  `VERDICT: APPROVED`。
- 一项非阻断 P2 仅要求把任务文字中的泛化 `headers` 收窄为
  `accepted_content_types/user_agent`；已随本记录同步，不扩大设计范围。
- 下一门禁为补救测试先行：测试 subagent 只能修改测试与本专项测试证据，必须先取得真实 RED，
  运行代码在 RED 之前不得修改。

## 2026-07-19 补救实现、复测与最终 GREEN

- 第一轮补救 RED：专用 `51` 项中 `37` 个 failure、`0 ERROR`；原有 `36/36` 继续通过。
  修复真实入口/时间/正文、透明 UA、逐请求 XML、结构化 HTTP、probe/crawl 诊断后，新严格
  子集 `15/15` 通过。
- 过时通用 fixture 不再要求错误入口合法；JCSA 与 Racing Victoria 的第二轮真实证据对齐
  取得 `5` 个目标 failure，再以来源专属日期 selector 和严格
  `/news/YYYY/MM/DD/slug` 修复。内置来源 URL/许可 notes 的最后一轮取得 `12` 个目标
  failure，再更新五条定义；全程没有运行时测试特例或联网测试。
- 独立最终验证：专用 `51/51`；归属/法国时间组合 `151` 个通过、`1` 个既有 live-network
  skip；既有来源/QQ/抓取/首页 `69/69`；Django check、migration drift、
  `git diff --check` 通过。
- JCSA 受控复测 artifact
  `0244333e5c84ea9da8d55e604cae6ea9a1c3c1fde79186da3615e0177ed753ca`：
  HTTP `200`、list `12`，当时抽样详情 missing time，technical `deferred`。剩余一次详情预算
  保存的当前 HTML 在修复后可离线解析标题、`724` 字正文和
  `2026-03-22T14:00:00Z`；未重复联网生成 accepted artifact。
- Racing Victoria 受控复测 artifact
  `d35b541c698a94aba8e5b4979d8f0d3a64eba81c306b50c28bce5ce1fa304c9f`：
  sitemap HTTP `200`、当时错误日期 regex 导致 list `0`、technical `deferred`。保存证据已
  支持严格斜杠日期修复，但列表预算用完，未重复联网。
- HRI/Woodbine/ERA permission `blocked`，没有补救联网；JCSA/Racing Victoria permission
  `unknown`。五来源继续 `enabled=false/production_approved=false` 且 effective
  `production_blocked`。
- 旧 review 指纹不覆盖当前补救候选。下一门禁是复用同一 native code reviewer 审查最新
  完整 fingerprint；通过后仍不 commit、push、PR 或 deploy。
- 最新主线集成基线为 `566a9b1012aac7fe52ad7aec793ab0ff4b9eae18`；主线占用 `0046`
  后，本 change migration 顺延为 `0047`。event 924 重叠回归 `200` 个通过、`2` 个
  PostgreSQL-only skip。
- 完整 `stable` 的本 change 直接 NameError 与旧 Ireland 合同已关闭；剩余
  `12 ERROR / 2 FAILURE` 在干净主线精确复现，记录于 `test_cases.md` 第 17 节，不扩大本
  专项去修历史 runner/current-year 基线。
- 正式候选迁至
  `/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-integrated`。旧同名
  worktree 因仓库级 stash 并行竞争保留错误恢复现场，只用于隔离，不得 review、测试或发布。

## 2026-07-19 最新代码审查 P2 修复

- 原生只读 review session `019f78e0-c31f-7c41-8885-7010617e379d` 首轮结论为
  `VERDICT: REVISE`：现有 `other` 赛事/马匹无法通过 ModelForm 保存无关修改，以及 Ireland
  来源缩写 `hri` 会裸子串命中 `thrilling`。
- 三项回归先在旧实现上稳定得到 `3 failures / 0 errors`。修复只新增表单专用的旧五区加
  `other` choices，并复用既有边界匹配器；赛事、马匹、historical、P0 和 race-live 的
  执行能力集合均未扩大。
- 修复后精确三项 `3/3`、新地区专用 `54/54`、新地区/归属/法国时间
  `154 passed / 1 existing skip`、相邻路径 `70/70`、event 924 重叠
  `200 passed / 2 PostgreSQL-only skip`；Django check、migration drift 与
  `git diff --check` 通过。
- 当前仍等待同一 reviewer 限定复审最新完整 fingerprint。所有来源继续
  `enabled=false/production_approved=false`，没有联网、commit、push、PR、deploy 或生产
  状态变化。

## 2026-07-19 Django Admin choices 审查修复

- 同一 native session 对 fingerprint
  `def49ae28389b8913ee5c86ee425094a0c136023921e7c6d2668fce766af5d9e`
  的限定复审再次为 `VERDICT: REVISE`：`RaceEventAdmin` 绕过运营表单而暴露五个
  news-only 地区，且 `test_cases.md` 顶部测试计数未更新。
- Admin 真实 `get_form()` 测试先得到 `1` 项内 `2` 个 failure；最小修复只让
  `formfield_for_choice_field()` 复用 `RACE_EVENT_FORM_REGIONS`，保留 `other`、排除新五区，
  不修改模型 choices 或任何执行能力集合。
- 修复后 Admin 精确回归 `1/1`、新地区专用 `55/55`、新地区/归属/法国时间
  `155 passed / 1 existing skip`、相邻路径 `70/70`；Django check、migration drift 和
  `git diff --check` 通过。
- 同一 reviewer/native session 第三次限定复审前后 fingerprint
  `83675edc20358bf813a73a1db4ccf49e7f3f34bc67cd0b3ac4d05f4a57fb1353`
  一致，结论 `VERDICT: APPROVED`，无 P0/P1/P2 actionable finding。当前仍未 commit、
  push、PR、deploy 或启用来源，等待用户针对最终冻结版本另行授权。

最新 `origin/main` 的状态文档显示生产服务和 HTTP healthz 当前正常，并在 event 924 的单赛事
TRA shadow 证据后保持 scheduler false；本专项不触碰该准实时范围。早期 OOM/不可用记录属于
历史状态，不作为本 worktree 的当前生产结论。

## 与并行任务的关系

本专项会触及多地区新闻核心路径：

- `server/stable/models.py`
- `server/stable/adapters/international.py`
- `server/stable/services/sources.py`
- `server/stable/services/news_attribution.py`
- `server/stable/services/multiregion.py`
- `server/stable/views.py`
- 相关 migration、tests、templates 和 `.env.example`

这些路径可能与在途 `fix-france-news-freshness-and-multiregion-attribution`、新闻质量/归属审核和
历史赛事地区消费者重叠。实施不得复制主工作区未提交修改；代码 review 前必须 fetch 最新
`origin/main`，明确处理冲突并重跑直接路径。另一个 worktree 的旧发布授权、review 或 flag
结论不适用于本专项。

新地区只扩展新闻能力。历史赛事 runner、race-live worker/event 924、P0 马匹资料和现有
五地区 Gold/Shadow 不移交所有权，不共享运行目录、请求预算或生产授权。

## 安全检查点

### Checkpoint A：方案审核

- 五份 durable artifact 完整。
- 明确五个持久地区键、无 `middle_east`。
- 明确技术准入、内部 scope、公开禁止、terms risk、时间、归属和非新闻范围隔离。
- 明确全局 mode off 下只保存 source-scoped `review_candidate`，文章保持来源主地区并阻止
  匿名读取和全部外部分发。
- `plan-eng-review` 为 `APPROVED` 前不得进入测试实现。

### Checkpoint B：RED

- 新测试实际失败，原因是缺新地区/adapter/归属/UI。
- 历史/准实时范围污染测试能够捕获隐式枚举扩张。
- 不用 import error、坏 fixture 或环境错误冒充 RED。

### Checkpoint C：代码 GREEN

- 新来源仍默认关闭。
- SQLite、目标和直接回归通过；临时 PostgreSQL migration smoke 未执行，仍待验证。
- 无真实网络进入自动测试。
- 未执行生产同步、抓取、翻译、发布或 QQ。

### Checkpoint D：只读来源 proof

- 每源列表最多 1 请求、详情最多 2 请求。
- technical accepted/blocked、internal-only scope、public publish false 和 terms risk
  分别记录；只有 technical accepted 才可进入后续内部启用候选。
- 零业务表写入、零凭据、零大段正文入库。
- 五地区各至少两个独立入口、其中至少一个 technical accepted，才可宣称“内部来源齐备”。

### Checkpoint E：代码 review

- 未参与实现的 reviewer 使用原生 read-only review。
- fingerprint 前后相同，所有 actionable findings 清零。
- 成功后仍停在未提交/未发布，等待当前任务新授权。

## 未来内部生产灰度（不属于当前授权）

### 阶段 0：部署但全关

- 新 migration 已应用。
- 十七个直接来源均存在但 `enabled=false/production_approved=false`。
- crawl allowed regions 不含新五区；QQ 和其他外部分发保持内部模式硬阻断。
- 旧五区抓取、赛事和 race-live 状态不变。
- HTTPS/私网 TLS、认证媒体链路和内部访问 runtime preflight 必须先通过；HTTP-only 环境停止。

### 阶段 1：逐源 crawl-only

- 每次只批准一个来源和一个地区。
- `production_approved=true` 前复核 technical probe digest、host、parser version 和 terms risk。
- 全局 attribution mode 与关联地区查询继续关闭；如需抓取，另行只为精确来源
  开启 source-scoped candidate allowlist，候选不自动改主地区。
- 观察至少多个有效窗口的 HTTP、解析、新增、重复、时间和翻译质量。

### 阶段 2：地区人工审核

- 每地区抽检近期文章的正文边界、日期、翻译和归属。
- 爱尔兰/英国、加拿大/美国、UAE/沙特跨地区样本必须覆盖。
- `needs_review`、`other` 回退和术语 blocker 形成可读审计。
- 人工确认并锁定地区前，所有新来源文章不进入内部已发布状态；外部分发始终阻断。

### 阶段 3：认证后内部筛选

- 只向已认证用户开放地区 tab/更多地区筛选。
- 验收匿名零内容、登录回跳、桌面、390px 移动、空状态、缓存和查询数。

### 阶段 4：内部已发布状态

- 内部人工审核后可使用既有 `PUBLISHED` 状态，但 URL 始终要求登录。
- QQ、PushLog、公开 URL 和内容邮件外发继续为
  `internal_only_distribution_blocked`；本 change 没有恢复阶段。
- 阿联酋、沙特分别配置，不存在中东总开关替代单国来源或审核。

## 回滚

优先使用配置回滚：

1. `production_approved=false`
2. `enabled=false`
3. 从 crawl/publish/QQ allowed regions/sources 移除
4. 保留 `NewsArticle`、snapshot 和 CrawlJob 审计

choice migration 不做破坏性反迁移。若已存在新地区文章，禁止直接回滚到无法在后台正确处理新
choice 的旧镜像；应先部署前向兼容代码并关闭行为。来源解析错误时只停问题来源，不影响其他
地区。

## 恢复 handoff

若本任务暂停，恢复者必须先核对：

- 当前 worktree/分支/HEAD 与 `origin/main`；
- 本目录五份 artifact 和方案 reviewer 的同一会话；
- `test_cases.md` 的真实 RED/GREEN 证据；
- 五个来源各自条款和 probe 状态；
- 新来源是否仍全部关闭；
- 是否存在 active subagent/reviewer；
- 生产是否有另一个新闻/赛事维护窗口。

任何缺项都停在上一个安全 checkpoint，不推断授权、不扩大范围。

## 2026-07-19 第二批实现与隔离 proof

### 方案与 RED/GREEN

- 独立 plan reviewer 四轮限定审查先后关闭 canonical permission preflight、未验证时间放行、
  unknown 翻译政策、freshness 审计、pre-upsert target scope 和 legacy 来源兼容问题，最终
  `VERDICT: APPROVED`。
- 第二批测试首轮为 `Ran 18 tests / failures=41 / errors=0`，真实暴露 freshness service、
  attribution preview、permission resolver、preflight、poll、窗口 summary 等缺失；补齐
  redirect-hop 与 scheduled policy 合同后，最终专用模块 `31/31`。
- 第一批新地区、第二批、归属、法国时间和通用来源轮询组合 `202 passed / 1 existing skip`；
  Django check、`makemigrations --check --dry-run` 与 `git diff --check` 通过。本增量没有
  migration。

### 实际 technical probe

隔离库为 `/private/tmp/umanews-new-region-second-batch-20260719.sqlite3`，权限 `0600`，
只执行迁移、只读 probe 和合成翻译 smoke。

| 地区 | 来源/证据 | 请求 | 结果 | 最近样本 | 候选结论 |
| --- | --- | --- | --- | --- | --- |
| 爱尔兰 | HRI/TDN blocked；复用强信号 fixture | blocked `0` | 未联网 | 无 permission-approved 新样本 | `0` |
| 加拿大 | Woodbine/TDN blocked；Canadian Thoroughbred 既有 date-only 证据 | blocked `0`；本轮 CT `0` | `2026-07-17` date-only | Toronto 当地日差 `2` | historical，`0` |
| 阿联酋 | ERA/DRC/Gulf News/The National blocked | `0` | 未联网 | 无 eligible 样本 | `0` |
| 沙特 | JCSA unknown technical probe | listing `1` + detail `2` | HTTP 200、list `12`、detail/time `2/2`、artifact `75ecff06…eb5e24` | `2026-03-22T14:00:00Z` | 超六小时，`0` |
| 澳大利亚 | Racing Victoria unknown technical probe | listing `1` + detail `2` | HTTP 200、list `20`、detail/time `2/2`、artifact `58d1818b…ad3566` | `2026-07-15T20:55:00Z` | 超六小时，`0` |

JCSA/Racing Victoria 的 technical 状态已由真实新 artifact 支持为 accepted，但 permission
仍 unknown、effective 仍 production blocked。probe 后业务表写入为 0；没有把 technical
accepted 解释为可生产。

### 翻译与隔离边界

- 没有 permission approved 的真实外部候选，因此真实外部全文翻译数为 `0`；本次显式强制
  dummy provider，没有调用外部翻译服务。
- 自有合成稿完成
  `synthetic NewsArticle -> translate_article_task -> TranslationRun -> pending_edit`；
  隔离库最终只有 synthetic `NewsArticle=1 / NewsSnapshot=0 / TranslationRun=1`，external
  probe article `0`、blocked TranslationRun `0`、CrawlJob `0`、ProductionWindow `0`、
  published `0`、QQ delivery `0`、NotificationLog `0`。
- 许可结论前的旧 TDN SQLite 已整库移至
  `/private/tmp/umanews-private-quarantine-20260719/pre-permission-tdn-smoke.sqlite3`，
  目录 `0700`、文件 `0600`，不读取或重新处理正文，不计入本轮验收。

当前仍未 commit、push、PR、deploy 或启用来源。下一门禁是最新完整 fingerprint 的独立只读
代码 review；即使 review 通过，也必须等待用户对冻结内容重新授权发布。

### 原生 code review Round 1 findings

复用既有 native session `019f78e0-c31f-7c41-8885-7010617e379d`，以
`codex exec resume -c 'sandbox_mode="read-only"' -c 'approval_policy="never"' ...` 完成只读
review，命令 exit `0`。审查期间 untracked 测试继续发生外部变化，fingerprint 从
`e8b6533f…f0bca1` 变化到 `321d6b84…df71ff`，退出后又变化到
`a2c1f1ec…1298c`，因此 fingerprint gate 明确 `BLOCKED`，本轮不能作为批准基线。
review 结论 `REVISE`，findings 为：

1. production-window 仍派发 public task，scheduled task 缺精确 `window_id`；
2. ingestion 可从 metadata 重建伪造 preview，且检查晚于图片/数据库副作用；
3. `all_details_failed` 的 CrawlJob `fail_count` 错用 `seen_count`；
4. request budget 耗尽路径可能改写上一条已完成 ledger 状态；
5. `AttributionPreview` evidence 只浅层不可变。

冻结代理后补测，稳定基线 `34/34` 增至 `41 tests / 12 failures / 0 errors`；其中第 4 项在
当时快照已 GREEN，由新增 succeeded/failed/redirected terminal 场景防回归。其余最小修复：

- production-window 派发 `crawl_scheduled_news_source_task(source_id, window_id)`；task 签名
  不暴露 origin/bypass，成功/失败窗口 payload 均保存 `source_summary`；显式 `window_id`
  在任何 source sync、crawl core、来源健康记录、窗口写回和 task log 之前验证 source、
  kind=`CRAWL`、status=`RUNNING`，无效绑定统一 `invalid_scheduled_crawl_window` 且不修改
  任一窗口或来源；
- content-scoped upsert 只接受显式真实 `AttributionPreview`，在图片、文件、Article 和
  Snapshot 前 fail closed，完全移除 metadata 重建，并以 exact type identity 拒绝可伪造
  `__class__` 的 `Mock(spec=AttributionPreview)`；
- `all_details_failed` 使用 `len(detail_errors)`；
- request budget 耗尽且没有新增 ledger attempt 时，不改写上一条
  `succeeded/failed/redirected` terminal 状态；
- preview evidence 递归冻结，输出 payload 时递归 thaw 为 JSON-safe 结构。

启动前窗口绑定的 runtime 修复先于补充测试落地，故没有可诚实取得的 RED；本轮只新增一个
4-subTest post-fix GREEN regression，并明确记录为 procedural gap。

### 原生 code review Round 2 限定复审

同一 session 在冻结 fingerprint `6638ef25…e508db1` 上确认 F1/F3/F4/F5 `CLOSED`，未发现
直接 P0/P1 回归，但 F2 仍 `OPEN`：ingestion 只检查 preview 非空，非空 fake object 仍可能
通过。native review 前后指纹一致；reviewer 退出后的外层复核发现 round2 测试文件又被补充
F1 启动前验证，故外层 fingerprint 漂移，门禁继续 `BLOCKED`，没有把旧候选当作批准版本。

F1 post-fix GREEN regression 阶段 round2 为 `42/42`、指定组合共运行 `213` 项且
`OK (skipped=1)`；该测试因 runtime 先落地没有真实 RED，属于已记录的流程顺序偏差。随后
新增可伪造 `__class__` 的 fake preview 得到
`43 tests / 4 subTest failures / 0 errors`：未抛门禁、图片调用、Article 与 Snapshot 写入各
一项失败。最小修复在所有副作用前用 exact type identity 要求对象实际类型为
`AttributionPreview`；合法测试均改用真实对象。根任务最终复核专用 `43/43`、完整指定组合
共运行 `214` 项且 `OK (skipped=1)`、bounded HTTP + request budget `11/11`；Django check、
migration drift、`git diff --check` 通过。没有联网、读取隔离库、commit、push 或部署。
仍待同一 session 对 F1-F5 修复、F2 类型加固、补充回归和最新稳定 fingerprint 限定复审，
不得把本段写成 review 已通过。

### 原生 code review Round 3 限定复审与唯一 P1/F2

- native same-session `019f79aa-be0a-71c0-8399-bff0c36ff038` 对 fingerprint
  `13f7e095…6422`（HEAD `42a06f47`、content `60743f…78d0`）执行只读限定复审；命令 exit
  `0`，review 前后 fingerprint 一致。
- 结论为 `VERDICT: REVISE`。F1/F3/F4/F5 已 `CLOSED`；唯一 P1/F2 是 content-scoped
  ingestion 只接受 exact Preview、会误拒真实 `AttributionResult`，而 direct
  `apply_article_attribution` 仍可让能伪造 `isinstance` 的 fake Preview/Result 触发候选
  helper、`article.save` 和 attribution 字段变更。
- review 前历史验证为专用 `43/43`、完整指定组合共运行 `214` 项且 `OK (skipped=1)`、
  bounded `11/11`。这些结果保留为该阶段历史，不覆盖 reviewer 新发现。

### Round 3 唯一 F2 补救与最终验证

只补测试与证据后得到真实 RED：

```text
Ran 45 tests in 0.224s
FAILED (failures=9)
errors=0
```

最小 runtime 修复在 ingestion 与 direct apply 两入口统一采用 exact type
`{AttributionPreview, AttributionResult}`，并把 direct 检查放在任何 helper、保存和内存/
数据库字段变更之前；fake/spec、子类、`None` 和其他对象统一
`attribution_preview_required`，不允许从 metadata 恢复。根任务独立验证：

```text
专用：45/45
完整指定组合：Ran 216 tests in 2.247s
OK (skipped=1)
bounded HTTP + request budget：11/11
Django check: 0 issues
makemigrations --check --dry-run: No changes detected
git diff --check: pass
```

验证为离线 SQLite/fixture/mock，没有联网、读取隔离库、commit、push、PR、deploy 或启用来源。
上述验证作为最终 F2-only 限定复审的既有测试证据。

### F2-only 最终原生限定复审 closure

- same native session：`019f79aa-be0a-71c0-8399-bff0c36ff038`；
- 命令模式：`codex exec resume -c 'sandbox_mode="read-only"' ...`，内层 read-only，
  exit `0`；
- 复审范围仅为 ingestion/direct apply 两入口 exact type
  `{AttributionPreview, AttributionResult}`；
- actionable findings：无；F2 `CLOSED`；结合此前 F1/F3/F4/F5 `CLOSED`，最终
  `VERDICT: APPROVED`；
- native 遵令未重跑测试，引用主代理独立验证的专用 `45/45`、组合
  `Ran 216 tests / OK (skipped=1)`、bounded `11/11`。

审前审后 helper raw 完全一致：

```text
fingerprint=30e7592accad91458fc2f9609f107232221e3bbd5295345e2b0b5bf060b6ca1c
HEAD=42a06f47c7529f2b9ca23b01ad951d8ab10e304d
content=a1dc620e46956375e3b188d6897bf408c7540d84c65f6f72c23ef6e5b284a636
tracked=5bd6b4393d8a6ee833e5118abd9c8603ff58888c9e497124009aea124e8a893d
untracked=af9c1ea5e1432c5a7b904c5f0009ba969b6753433a003b4aa6618cf106dff04d
```

没有新增 release report 或部署证据，也没有 commit、push、PR、deploy 或启用来源。本段证据
回写会改变 docs-only fingerprint，下一步仅为最终 docs-only fingerprint 一致性复审及用户对
最终冻结内容的新授权；历史授权不可复用。
