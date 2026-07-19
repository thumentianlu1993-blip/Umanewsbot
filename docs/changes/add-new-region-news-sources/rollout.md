# 新地区新闻抓取 rollout

## 当前边界

- worktree：`/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-integrated`
- 分支：`codex/add-new-region-news-sources-integrated`
- 基线：`origin/main@566a9b1012aac7fe52ad7aec793ab0ff4b9eae18`
- 当前动作：补救 RED/GREEN 与受控 proof 已完成；正在准备最新完整指纹代码复审
- 当前禁止：commit、push、PR、部署、迁移生产、生产写入、启用来源、自动发布、QQ 推送

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
- 明确来源条款、时间、归属和非新闻范围隔离。
- 明确全局 mode off 下只保存 source-scoped `review_candidate`，文章保持来源主地区并阻止发布/QQ。
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
- 条款/robots 与技术解析分别给结论；只有 technical accepted + permission approved 才
  effective eligible。
- 零业务表写入、零凭据、零大段正文入库。
- 五地区各至少一个 `effective_production_status=eligible` 才能宣称“来源齐备”；
  technical accepted 只表示解析能力，不能替代 permission approved。

### Checkpoint E：代码 review

- 未参与实现的 reviewer 使用原生 read-only review。
- fingerprint 前后相同，所有 actionable findings 清零。
- 成功后仍停在未提交/未发布，等待当前任务新授权。

## 未来生产灰度（不属于当前授权）

### 阶段 0：部署但全关

- 新 migration 已应用。
- 五个来源均存在但 `enabled=false/production_approved=false`。
- crawl/publish/QQ allowed regions 不含新五区。
- 旧五区抓取、赛事和 race-live 状态不变。

### 阶段 1：逐源 crawl-only

- 每次只批准一个来源和一个地区。
- `production_approved=true` 前复核条款与 probe digest。
- 全局 attribution mode、publish/QQ/关联地区查询继续关闭；如需抓取，另行只为精确来源
  开启 source-scoped candidate allowlist，候选不自动改主地区。
- 观察至少多个有效窗口的 HTTP、解析、新增、重复、时间和翻译质量。

### 阶段 2：地区人工审核

- 每地区抽检近期文章的正文边界、日期、翻译和归属。
- 爱尔兰/英国、加拿大/美国、UAE/沙特跨地区样本必须覆盖。
- `needs_review`、`other` 回退和术语 blocker 形成可读审计。
- 人工确认并锁定地区前，所有新来源文章保持发布/QQ 硬阻断。

### 阶段 3：公共筛选

- 先开放地区 tab/更多地区筛选，不自动发布新稿。
- 验收桌面、390px 移动、空状态、缓存和查询数。

### 阶段 4：发布/QQ

- 自动发布与 QQ 分别取得独立授权和 allowlist。
- 阿联酋、沙特分别配置，不存在中东总开关替代单国许可。
- 旧群空地区仍只接收日本。

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
