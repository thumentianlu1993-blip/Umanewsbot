# 新地区新闻抓取任务

## 最新收口状态

- [x] 第三轮受控 live probe 已在迁移后的仓库外 `/tmp` SQLite 完成；24-source registry 为
  `16 accepted / 8 blocked`，第三批 12 源为 `8 accepted / 4 blocked`。
- [x] 同一临时库已用真实 RTÉ 正文和 dummy provider 完成
  `translate_article_task -> TranslationRun -> article state` 编排验证。
- [ ] 真实中文远程 translation provider 尚未验证；SiliconFlow/OpenAI key 均 absent。
- [x] 当前候选已重新集成 `origin/main=HEAD=a122ff6d…`，`origin/main..HEAD=0`。
- [ ] 仍须完成最终同 reviewer 复审、PostgreSQL 专项、生产 TLS/私有 media、用户新授权及
  commit/push/PR/deploy。
- 所有第三批来源继续 `enabled=false / production_approved=false`。

## 0. Pre-declared hypotheses

- [x] H0.1 (operations) 每个来源的真实 probe 请求预算固定为列表 `1` 次、详情最多 `2` 次；
  超预算为 blocker，不通过增加请求解释失败。
- [x] H0.2 (operations) “五地区来源齐备”的 PASS 门槛是每地区至少一个来源同时满足
  `technical_status=accepted`、`automation_permission_status=approved`、
  `effective_production_status=eligible`；任一地区不满足则项目级结论为部分完成。
- [x] H0.3 (operations) 新 adapter 单响应最大 `2 MiB`、重定向最多 `3` 次、timeout
  `connect=5s/read=15s`；任一边界被突破即 blocked，不放宽后重试。
- [ ] H0.4 (integration) 归属候选相关地区最多 `3` 个；超过即 `needs_review`。
- [ ] H0.5 (application) 全局 attribution mode 保持 `off` 时，PASS 是“来源地区主值不变、
  review_candidate 正确持久化、发布/QQ 被阻断”，不是候选自动写入主地区。
- [x] H0.6 (operations) permission `blocked` 的 HRI/Woodbine/ERA 在取得新书面许可前不再联网；
  permission `unknown` 的 JCSA/Racing Victoria 仅允许显式、透明 UA、列表 1 次/详情最多 2 次、
  零业务写入的补救技术复测。
- [x] H0.7 (integration) date-only 当地日差 `0/1` 必须进入候选、`2` 必须作为历史跳过；
  精确时间文章行为不得改变，无效 evidence 时区必须 fail closed。
- [x] H0.8 (operations) 第二批 blocked 来源联网请求必须为 `0`；unknown 来源每源最多
  `1` 次列表和 `2` 次详情，隔离库最终必须 `published=0/QQ=0`。
- [x] H0.9 (integration) 复用来源中 `Irish Oaks` 必须归爱尔兰，Woodbine/Ontario 强信号
  必须归加拿大；canonical 来源许可不得被地区 wrapper 放宽。

## 1. 测试先行

- [x] 1.1 (application) 新增地区 choice、显式新闻/赛事/马匹/live 能力集合的测试，并取得
  “新五区缺失”和“choice 扩展会污染非新闻范围”的真实 RED。
- [x] 1.2 (integration) 为 HRI、Woodbine、ERA、JCSA、Racing Victoria 新增最小列表/详情
  fixture 与 adapter 契约测试，覆盖可信时间、内容边界、URL 稳定性和缺失时间 RED。
- [x] 1.3 (integration) 新增爱尔兰/英国、加拿大/美国、UAE/沙特、澳大利亚归属测试，
  取得当前回退到英国/美国/other 的真实 RED。
- [ ] 1.4 (application) 新增来源同步、默认关闭、单源停用、窗口选择、人工审核和 QQ 独立订阅测试。
- [ ] 1.5 (application) 新增公共“更多地区/中东视觉分组”筛选和移动布局静态/响应测试。
- [x] 1.6 (application) 新增新闻与马匹 resolver/tab 隔离测试、HTTP 200 空列表失败测试、
  有界 HTML 请求测试和 probe 技术/许可/effective 三轴状态测试。
- [ ] 1.7 (integration) 新增全局 mode off 的 adapter→upsert→review_candidate→发布/QQ
  阻断→人工锁定端到端测试。
- [x] 1.8 (integration) 新增发布时间 evidence 持久化、missing summary 计数和 verified
  时间防降级覆盖测试。
- [x] 1.9 (operations) 将 RED 命令、失败测试和核心断言写入 `test_cases.md`；确认失败来自目标行为未实现。

## 2. 地区模型与隔离实现

- [x] 2.1 (application) 扩展 `RacingRegion` 五个值，新增 migration，保持旧数据不变。
- [x] 2.2 (application) 建立显式 `NEWS_ATTRIBUTION_REGIONS`、`NEWS_PRODUCTION_REGIONS`、
  `RACE_DATA_REGIONS`、`HORSE_PROFILE_REGIONS`、`RACE_LIVE_SUPPORTED_REGIONS` 或等价能力集合。
- [x] 2.3 (application) 审计并替换依赖 `RacingRegion.values/choices` 的隐式全量循环，
  确保历史批次、准实时 initializer、赛事日历和马匹任务范围不扩大。
- [x] 2.4 (application) 更新后台 choice、公共地区筛选和中文标签；阿联酋/沙特只做 UI 分组，
  不新增 `middle_east` 数据值。
- [x] 2.5 (application) 拆分新闻与马匹的地区 tabs/resolver，赛事日历继续使用显式赛事地区集合。

## 3. 来源与 adapter 实现

- [x] 3.1 (application) 新增五个 `SourceSite` 和内置 `NewsSource` 定义，全部默认
  `enabled=false/production_approved=false`。
- [x] 3.2 (integration) 实现 HRI adapter，解析 Dublin 当地时间、标题、正文、作者和 URL。
- [x] 3.3 (integration) 实现 Woodbine adapter，解析 Toronto 当地时间并隔离加拿大来源。
- [x] 3.4 (integration) 实现 Emirates Racing Authority adapter，解析 Dubai 当地时间。
- [x] 3.5 (integration) 实现 JCSA adapter，解析 Riyadh 当地时间。
- [x] 3.6 (integration) 实现 Racing Victoria adapter，解析 Melbourne 当地时间。
- [x] 3.7 (integration) 收紧新 adapter 的时间契约：缺可信时间不得用 crawl time 入库，
  单篇失败继续、全轮失败可见。
- [x] 3.8 (integration) 为新 adapter 实现 HTTPS/host/redirect/content-type/2 MiB/timeout/
  登录页/验证码有界请求 helper，不改写旧 adapter。
- [x] 3.9 (integration) 扩展只读 probe 输出 technical/permission/effective 三轴状态、
  版本、artifact SHA、成功响应 HTTP、最终 URL、解析质量、时间证据和零业务写入断言。
- [x] 3.10 (integration) 区分 `empty_listing`、`all_details_failed` 和成功全重复，并让
  前两者进入明确来源健康/backoff。
- [x] 3.11 (integration) 在非 200 fail-closed 基础上使用结构化安全异常保留精确 HTTP
  `403/429` 与最终 URL；adapter、probe、crawl、ProductionWindow 和 blocked backoff
  均有测试覆盖，同时兼容旧 `exc.response.status_code`。

## 4. 归属、窗口和分发实现

- [x] 4.1 (integration) 扩展正式地区/事件关键词与稳定排序，停止新文章的临时
  `ireland -> UK + tag` 和新五区 `out_of_scope -> other` 行为。
- [x] 4.2 (integration) 实现跨地区主/关联规则，覆盖本地来源报道外国赛事和全球来源报道新地区。
- [x] 4.3 (integration) 前进归属规则版本，保持旧 Gold/Shadow 资格不自动继承。
- [x] 4.4 (integration) 增加默认关闭、source allowlist 限定的 mode-off
  `review_candidate` 路径，只保存候选并设置地区人工审核硬门，不修改主/关联地区。
- [ ] 4.5 (application) 提供人工确认主/关联地区并锁定后的发布门禁闭环；提供旧
  `other`/`ireland` 文章只读候选导出，不提供本 change 的历史 commit。
- [ ] 4.6 (application) 将新五区接入来源健康、地区生产审计、窗口配置和 QQ 显式订阅，
  保持默认关闭与旧群兼容。

## 5. GREEN、真实探测与文档

- [ ] 5.1 (application) 运行模型、migration、UI、窗口、QQ 聚焦测试至 GREEN。
- [x] 5.2 (integration) 运行五 adapter、抓取失败、内容边界、归属和去重测试至 GREEN。
- [x] 5.3 (operations) 运行受影响的历史批次、准实时、赛事日历、马匹和旧五区归属回归：
  event 924 重叠 `200+2 skip`、直接范围 GREEN；完整 stable 剩余 `14` 项失败在干净主线
  精确复现并记录，不归因于本 change。
- [x] 5.4 (operations) 对五个候选入口执行有界真实只读 probe，保存逐源
  accepted/deferred/blocked 和条款结论；任一地区无 `eligible` 来源时明确部分完成/no-go，
  不把 technical accepted 冒充可灰度资格。
- [ ] 5.5 (operations) 运行 SQLite check、目标测试、临时 PostgreSQL migration smoke、
  Compose config、迁移漂移和 `git diff --check`。
- [x] 5.6 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、
  `docs/decisions.md`；只有涉及实际部署准备时才更新 `docs/deploy_runbook.md`。
- [x] 5.7 (operations) 更新本目录 `test_cases.md`、`rollout.md` 的真实 RED/GREEN/probe
  证据和剩余风险。

## 6. 审核与发布边界

- [x] 6.1 (operations) 首次实现完成后由未参与实现的 reviewer subagent 实际运行原生
  read-only review，记录完整 fingerprint、命令、范围和 findings。
- [x] 6.2 (application) 如有 actionable finding，先为具体漏洞补真实 RED，再由实现
  subagent 修复并交回同一 reviewer 做限定复审。
- [x] 6.3 (operations) review 成功后停在未提交、未推送、未部署状态；只有用户针对最新冻结
  内容明确授权后，才可 stage/commit/push/PR 或部署。

## 7. 首次代码 review findings

- [x] 7.1 (application) 为人工 publish 绕过地区审核门禁补 RED，并统一人工/自动/QQ
  `region_review_required` fail-closed 判定。
- [x] 7.2 (integration) 为 UAE/Saudi 日文强信号补 RED 并加入正式地区/事件词表。
- [x] 7.3 (operations) 为 probe `--limit > 2` 补 RED 并使用 `CommandError` 拒绝。
- [x] 7.4 (integration) 为默认 probe 外联矩阵补 RED；新五来源仅保留显式 opt-in。
- [x] 7.5 (integration) 为 bounded HTTP `206/300/304` 补 RED并只接受精确 `200`。
- [x] 7.6 (operations) 为人类可读 probe 成功/错误输出补 RED并输出完整 contract。
- [x] 7.7 (operations) `F1-F6` 全部 CLOSED 后交回同一 reviewer 做限定复审；最终 native
  session `019f76f0-ef8b-71d1-a0ad-246d26352f0e` 为 `VERDICT: APPROVED`。批准绑定文档
  回写前 fingerprint；本次 docs patch 本身不在该批准范围。

## 8. 限定复审后的范围外建议

- [ ] 8.1 (integration) 另行评估旧 adapter 的 `empty_listing` 语义影响；本 change 不扩大
  该行为变更。
- [x] 8.2 (integration) 在真实来源 proof 后为 HRI/JCSA 来源限定的英文长日期、序数日期与
  date-only precision 补解析策略和真实最小 fixture；未扩散为旧 adapter 的全局宽松解析。
- [x] 8.3 (integration) 最新代码 review 以 `hri` 命中 `thrilling` 的反例证明地区关键词
  substring boundary 缺口；已补真实 RED，并让来源地区上下文复用既有边界匹配器。

## 9. Docs-only 一致性复审 findings

- [x] 9.1 (operations) 记录 native session
  `019f76fb-5494-7a63-b9e5-b4d5a6985bff` 的 docs-only review：sandbox
  `read-only`、命令 exit `0`、fingerprint 前后一致，因 findings 结论为
  `VERDICT: REVISE`；current docs 基线未获批准。
- [x] 9.2 (operations) 修正共享 `RacingRegion` choices、临时 PostgreSQL 状态及非 200
  精确分类能力的过宽表述，并更新测试文档现状。
- [x] 9.3 (operations) 将修复后的纯文档 patch 交回 reviewer 限定复审；native session
  `019f7705-375e-7ee3-aaa4-8125215be390` 为 `APPROVED`。后续真实 probe 与补救文档再次
  改变 fingerprint，旧批准不覆盖新内容。

## 10. 首轮真实 probe 补救

- [x] 10.1 (operations) 在迁移后的临时 SQLite 中对五来源分别执行显式、低预算、零业务写入
  probe；记录五个 artifact SHA、HTTP、列表/详情结果与 deferred 原因。
- [x] 10.2 (operations) 核验五站 robots 与官方条款：HRI/Woodbine/ERA 记为 `blocked`，
  JCSA/Racing Victoria 记为 `unknown`；任何来源都不提升 `production_approved`。
- [x] 10.3 (integration) 用浏览器只读检查 JCSA/Racing Victoria 动态列表；确定 JCSA
  `/api/news/en/0/12` HTML 片段和 Racing Victoria sitemap 路径，不在代码中保存前端
  GraphQL 凭据。
- [x] 10.4 (operations) 复用同一方案 reviewer 完成两轮 `plan-eng-review` 限定复审；首轮
  5 项 findings 全部关闭，Round 2 未发现直接 P0/P1 回归，`VERDICT: APPROVED`。
- [x] 10.5 (integration) 仅在测试文件加入五站真实结构最小 fixture、permission、透明
  User-Agent、逐请求 XML allowlist 与精确 `403/429` adapter/probe/crawl/backoff 诊断测试，
  并取得真实 RED。
- [x] 10.6 (integration) 修复五 adapter 的真实列表/详情/日期/canonical URL；有界 helper
  只新增受限 `accepted_content_types/user_agent` 与精确状态异常，不改变旧 adapter 默认行为。
- [x] 10.7 (application) 更新五个内置来源的真实 homepage/feed URL 与许可说明，保持
  `enabled=false/production_approved=false`。
- [x] 10.8 (operations) 专用与直接回归 GREEN 后，只对 JCSA/Racing Victoria 在相同请求预算
  下做一次补救技术复测；HRI/Woodbine/ERA 不联网且不得凭 fixture 把 technical 提升为
  accepted。两源复测仍 deferred，随后只用保存证据离线修复且不重复请求；所有 permission
  blocked/unknown 来源继续 `production_blocked`，项目不得宣称五地区来源齐备。
- [x] 10.9 (operations) 复用同一代码 reviewer 审核补救后的完整 fingerprint；首轮
  `VERDICT: REVISE` 提出旧 `other` 表单兼容与 Ireland `hri` 裸子串两项 P2，均先取得
  真实 RED 再最小修复并完成直接回归。
- [x] 10.10 (operations) 将两项修复和文档回写交回同一 reviewer 限定复审；fingerprint
  `def49ae…d9e` 前后一致，结论 `VERDICT: REVISE`，新增 Django `RaceEventAdmin`
  结构化 choices 与测试摘要旧计数两项 P2。
- [x] 10.11 (application) 为真实 `RaceEventAdmin.get_form()` 补 RED，并仅在 admin
  choice hook 复用 `RACE_EVENT_FORM_REGIONS`；更新 durable 当前测试计数，不扩大模型或
  执行能力集合。
- [x] 10.12 (operations) 将最新 Admin/文档修复交回同一 reviewer 限定复审；前后
  fingerprint `83675edc…b1353` 一致，`VERDICT: APPROVED`，无 P0/P1/P2 actionable
  finding。仍不 commit、push、PR、deploy 或启用任何来源，等待用户针对最终冻结内容另行
  授权。

## 11. 第二批来源调研、date-only freshness 与隔离实抓

- [x] 11.1 (operations) 持久化第二批来源矩阵，逐源记录入口、HTTP/页面结构、时间精度、
  robots、官方条款、technical/permission/effective 状态与 no-go 原因。
- [x] 11.2 (integration) 只修改测试和测试证据，为 date-only 日差 `0/1/2`、跨 UTC 日期、
  夏令时、无效时区、missing/unknown precision、verified false、naive datetime、固定
  crawled_at、crawl/probe 摘要和精确时间不回归取得真实 RED。
- [x] 11.3 (integration) 只修改测试和测试证据，为 `Irish Oaks`、`Woodbine Oaks` 及
  content-scoped mode-off 正负例、重复文章和 canonical permission 不可被 wrapper 绕过取得
  真实 RED。
- [x] 11.4 (integration) 为 blocked 显式 probe/wrapper/direct crawl、enabled 但未批准来源、
  unknown 业务写入、全 historical/全 unresolved、freshness 审计 metadata 与窗口 summary
  补 RED；允许先建审计 CrawlJob，但 fetch spy 必须证明 preflight 后零请求并统一
  `permission_blocked_preflight`。同一 canonical 来源还需覆盖 target 缺时间/无效时区/历史稿
  在 upsert spy 前停止、普通 UK/US 缺时间稿维持旧行为、target candidate 前后传递对象 identity
  相同且只计算一次的 preview result。
- [x] 11.5 (integration) 最小扩展 Ireland/Canada 强地区信号，不新增重复 adapter、不改变
  全局 attribution mode 或既有 Gold/Shadow 资格；新增默认关闭/空 allowlist 的
  content-scoped candidate 路径，只门禁强证据新地区稿。
- [x] 11.6 (integration) 新增 canonical permission registry/resolver，在 probe、crawl 和
  隔离 runner 的任何请求前执行；TDN 三入口/wrapper/HRI/Woodbine/ERA blocked 零请求，
  adapter 自报状态不得覆盖 canonical 结论。public/direct task 无论 flag 值都强制 managed
  preflight；自动 poll 改为无可伪造 origin/bypass 参数的独立 scheduled task，只有该入口受
  默认关闭 flag 控制且只覆盖五个首批 canonical 加 TDN。flag 关闭时既有 enabled +
  production-approved 自动选择集合逐项相等，未登记 legacy 不新增 permission 条件并输出
  `legacy_permission_unregistered`，不得进入新五地区候选。flag 开启前 TDN scheduled 停抓
  需独立运行态核对与新授权。
- [x] 11.7 (integration) 为 `TrustedLocalTimeNewsAdapter` 接入 per-source
  `SourceRequestBudget`，把 callback 下沉到 `_bounded_html()` redirect loop 的每个
  `session.get()` 前；unknown research 按实际 HTTP hop 严格 listing `1`、detail `2`，覆盖
  redirect、失败 redirect、多源隔离、部分失败、耗尽后零额外 GET 和不支持 budget 的 adapter。
- [x] 11.8 (integration) 实现独立 date-only candidate freshness service，并在国际 crawl
  upsert 前和只读 probe 输出中复用；新增共享纯函数 pre-upsert preview，正式 attribution
  通过显式参数复用同一不可变 result，命中专项却缺 preview 时 fail closed；历史不入库，
  未验证/缺失/naive 时间对 Ireland/Canada target fail closed；普通 UK/US 兼容，候选证据
  写入 article/snapshot，窗口保存 source summary。
- [x] 11.9 (operations) 将许可结论前的旧 TDN SQLite 移入仓库外私有 quarantine，不读取或
  重新处理正文；新隔离库验证 blocked 文章/正文/HTML/TranslationRun/请求均为 `0`。
- [x] 11.10 (operations) 使用已取得的 Canadian Thoroughbred 最小结构证据制作无第三方正文
  synthetic fixture；本轮不再联网、不新增生产或 research adapter。
- [x] 11.11 (operations) 运行专用 GREEN、受影响 crawl/attribution/probe/source polling
  回归、Django check、migration drift、`git diff --check`；不要求为本增量新增 migration。
  F1 修复复核后另补 1 个启动前显式窗口绑定 GREEN regression（4 个 subTest）；因 runtime
  已先落地无法取得真实 RED，已在 `test_cases.md` 记录 procedural gap，不伪造历史 RED。
  该阶段专用 `42/42`、指定组合共运行 `213` 项且 `OK (skipped=1)`；后续 F2 fake preview
  类型限定先取得专用 `43 tests / 4 failures / 0 errors` 的真实 RED，exact type identity
  修复后最终专用 `43/43`、完整指定组合共运行 `214` 项且 `OK (skipped=1)`、bounded HTTP +
  request budget `11/11`。
- [x] 11.12 (operations) 使用新仓库外 SQLite 只对 JCSA/Racing Victoria 执行 unknown 小预算
  真实 technical probe；汇总五地区复用证据、候选/历史/缺时间/许可或技术阻断，但 unknown
  不创建业务文章或运行全文翻译。
- [x] 11.13 (operations) 真实外部全文翻译只允许 permission approved 的 freshness 候选；
  无候选时如实停止，并用自有合成文本/最小 fixture 验证 translation task/DB 机械链路，
  分开记录 real provider、dummy、fixture，不冒充真实新闻翻译。
- [x] 11.14 (operations) 更新 `current_state/project_status/decisions` 和本 change 证据；
  不更新 deploy runbook，除非实际发生部署或运维行为。
- [x] 11.15 (operations) 复用本需求连续审核边界完成最新 uncommitted 原生只读代码 review；
  same native session `019f79aa-be0a-71c0-8399-bff0c36ff038` 以
  `codex exec resume -c 'sandbox_mode="read-only"' ...` 仅复审 F2 两入口 exact-type 修复，
  内层 read-only、exit `0`，审前审后 helper raw 一致。fingerprint
  `30e7592accad91458fc2f9609f107232221e3bbd5295345e2b0b5bf060b6ca1c`，HEAD
  `42a06f47c7529f2b9ca23b01ad951d8ab10e304d`，content
  `a1dc620e46956375e3b188d6897bf408c7540d84c65f6f72c23ef6e5b284a636`，tracked
  `5bd6b4393d8a6ee833e5118abd9c8603ff58888c9e497124009aea124e8a893d`，untracked
  `af9c1ea5e1432c5a7b904c5f0009ba969b6753433a003b4aa6618cf106dff04d`。无 actionable
  finding，F2 `CLOSED`；结合 F1/F3/F4/F5 `CLOSED`，最终 `VERDICT: APPROVED`。native 未
  重跑测试；本次 docs-only 回写后仍待最终 fingerprint 一致性复审和用户新授权。
- [x] 11.16 (integration) reviewer 后续指出合法 exact `AttributionResult` 正例和 direct
  fake Preview/Result 边界仍需锁定；取得 `45 tests / 9 failures / 0 errors` 的真实 RED，
  两入口 exact type `{AttributionPreview, AttributionResult}` 修复后专用 `45/45`，根任务
  独立完整组合 `Ran 216 tests / OK (skipped=1)`、bounded `11/11`，Django check、
  migration `No changes detected`、`git diff --check` 通过。仍不 commit、push、PR、deploy
  或启用来源，等待用户针对最终冻结内容的新授权；历史授权不可复用。

## 12. 内部使用与第三批多来源增量

- [x] 12.1 (integration) 按用户新口径更新 `spec/design/test_cases/tasks/rollout`，明确旧
  permission 结论只保留为历史 `terms_risk`，不调用 OpenSpec。
- [x] 12.2 (integration) 独立方案 reviewer 已覆盖内部访问、分发硬门、技术准入、12 来源、
  migration 集成、翻译处理和测试矩阵，最终 `VERDICT: APPROVED`。
- [x] 12.3 (application) 测试先行：新增内部 HTML/API/healthz/robots/sitemap 与 QQ 零副作用
  测试，并与 integration 测试共同保存
  `62 tests / 74 expected failures / 0 errors` 的真实 RED。
- [x] 12.4 (integration) 测试先行：新增 registry 三轴、RSS 基类、12 来源 fixture/crawl、
  date-only/主题过滤、外部翻译开关和 migration 集成测试；RED 不含环境或 fixture error。
- [x] 12.5 (application) 实现内部访问 middleware、robots view、受保护 local media、OSS
  private-mode fail-closed 预检、QQ/PushLog/通知外发硬门和默认配置；同步更新 Nginx 配置，
  不部署、不修改生产。
- [x] 12.6 (integration) 将 canonical registry 改为
  `technical_access/usage_scope/public_publish_allowed/terms_risk`，保留 legacy dispatcher
  兼容且所有新来源默认关闭。
- [x] 12.7 (integration) 实现 `TrustedRssNewsAdapter` 和 12 个来源 adapter/SourceSite/
  NewsSource 定义；不读取媒体 enclosure，不抓图片/视频。
- [x] 12.8 (integration) 实现来源主题过滤、date-only 复用、crawl 集成和
  translation/rewrite 共享 `NEWS_EXTERNAL_AI_PROCESSING_ENABLED` 门禁。
- [x] 12.9 (integration) 在首次 main 无提交集成 worktree 解决双 `0047` migration 分叉，形成
  `0048_merge_20260719_2242.py -> 0049_alter_newsarticle_source_site_and_more.py`，
  保留 race-live 与本 change 双方能力。
- [x] 12.10 (operations) 完成本地 SQLite/fixture 验证：内部访问/媒体/外发/AI 门禁
  `47/47`、重点功能独立复核 `175/175`、race-live 集成回归 `37/37 + 63/63`；
  `manage.py check`、migration drift、`migrate --plan`、`git diff --check` 和 cached diff
  check 通过。旧测试只显式关闭测试环境内部总门并补 `production_approved` fixture，
  未放宽生产策略。
- [x] 12.11 (operations) 完成首次 `current_state/project_overview/project_status` 和本目录
  durable artifacts 收口；明确后续不再使用 OpenSpec。
- [x] 12.12 (operations) 用透明 UA 和小预算对 12 个第三批来源执行当前集成版本的最终受控
  live probe；记录 HTTP/final URL、解析/时间/新鲜度、blocked 原因和 artifact SHA，
  不绕过 403/429/challenge。最终第三批为 `8 accepted / 4 blocked`；IrishRacing、SPA、
  Racing NSW、Tasracing 依据 live 结构完成 TDD 修复与复探。
- [ ] 12.13 (integration) 仅对通过受控 live probe 且符合内部候选边界的最小样本执行真实
  translation 运行，分开报告远程 provider、local/dummy 和未决结果。真实 RTÉ 正文的
  dummy 编排已完成，但真实中文远程 provider 未验证，因此本项保持未完成。
- [ ] 12.14 (operations) 在临时 PostgreSQL 验证 migration 正向/反向/再次正向、必要并发
  与生产形状；不得用 SQLite `migrate --plan` 代替。
- [x] 12.15 (operations) 未参与实现的首次代码 reviewer 已执行完整只读审核，结论
  `REVISE`，共 `2 P1 + 5 P2`。
- [x] 12.16 (application) 为七项 finding 新增聚焦测试并取得
  `7 failures / 0 errors` 的真实 RED；失败均来自目标合同缺失。
- [x] 12.17 (application) 修复来源级公开/QQ blocker、`DEBUG=false` secure cookies 与
  direct HTTPS/可信 TLS 反代启动预检、通知 counts/IDs 且无 URL 的合同。
- [x] 12.18 (integration) 修复 translation retry/preclaim/batch skip、TDN freshness
  metrics 和 probe canonical normalize；聚焦 `7/7`，旧 URL 通知测试改为
  `article_id`-only。
- [x] 12.19 (operations) 同一 reviewer session 对七项修复范围实质确认 actionable findings
  清零并给出 `APPROVED`；因审查期间 main 漂移，完整性结论保持 `BLOCKED`，未将其写成成功
  review 或请求发布授权。
- [x] 12.20 (integration) 二次集成
  `origin/main=HEAD=58f00961f2cd9750d1285f7d6229494903e975a5`，保持
  `origin/main..HEAD=0`；新增无操作 `0050_merge_20260720_0017.py` 合并 main
  `0048_raceeventrunner_external_runner_identity.py` 与功能 `0049`，并确认唯一 leaf。
- [x] 12.21 (operations) 运行修复与二次集成回归：findings `7/7`、重点功能 `175/175`、
  translation failure recovery `22/22`、latest-main release-gate `69 OK`（SQLite 跳过
  PostgreSQL 专项 `15`）、race-live `37/37 + 63/63`；migration check/plan/test DB migrate、
  Django checks、diff/cached diff 和相关 `py_compile` 通过。
- [x] 12.22 (operations) 第二轮更新本目录 durable artifacts 与
  `current_state/decisions/project_overview/project_status`，记录来源级硬门、可信 TLS 和安全
  通知行为决策；保留最新 main 原有 race-live 决策。
- [ ] 12.23 (operations) 复用同一 reviewer session 对 final-integrated 的完整
  `58f00961…` 精确版本执行只读复审；成功前审核门禁保持 `BLOCKED`。
- [ ] 12.24 (operations) 最终成功 review 后请求用户对当前冻结内容的新发布授权；旧 review、
  旧授权和两个回退 worktree 的内容均不覆盖本版本。
- [ ] 12.25 (operations) 只有取得新授权并通过发布前冻结校验后，才可 commit、push、创建
  PR、部署、应用迁移或逐源启用；当前所有新来源仍不可生产调度，TLS/私有 media 前置未满足。
- [ ] 12.26 (operations) 发布后按 `docs/codex_workflow.md` 的 evidence-only closure 回写
  真实生产状态；未发布时不得建立上线成功记录。
- [x] 12.27 (operations) 扩展受控 probe 至 24-source technical registry，并记录精确
  `16 accepted / 8 blocked`；HRI/Woodbine/ERA 虽 listing HTTP `200`，仍因
  `missing_published_at` 端到端 fail closed。TDN 正文成功 accepted，但 unverified time
  不进入候选。
- [x] 12.28 (integration) 验证综合源 attribution：Curragh/Irish Oaks -> Ireland，
  Woodbine/Canadian -> Canada，无强关键词保持原 US/UK region；Sporting Life technical
  accepted 但当前候选因 unverified time deferred。
- [x] 12.29 (operations) 以约 `2026-07-19T17:41Z` 为 probe 时点生成严格最近六小时汇总：
  Ireland `2`，Canada/UAE/Saudi/Australia 均 `0`；本轮样本均为精确时间，未用 date-only
  规则抬高数量。
- [x] 12.30 (integration) 在同一迁移临时库用真实 RTÉ 正文 `6616` 字符和 dummy provider
  完成 translation task/persistence 编排；标题带 `[未配置真实翻译模型]`。
- [x] 12.31 (operations) 运行最新 release-candidate 离线组合 `214/214 OK`、follow-up `10/10`，确认
  migration 无漂移、Django checks 通过；另保留来源实现代理的 `202 + 1 skip` 与
  translation recovery `22/22` 独立计数。
- [x] 12.32 (integration) 将当前候选重新集成到最新 `origin/main@a122ff6d…`；
  `origin/main=HEAD`、`origin/main..HEAD=0`。冲突仅限
  `docs/current_state.md` 与 `docs/project_status.md`，已同时保留主线发布证据和本专项
  live evidence；migration DAG、直接回归与最终 fingerprint 已重新验证。
