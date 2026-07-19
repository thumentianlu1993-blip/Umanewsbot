# 新地区新闻抓取任务

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
