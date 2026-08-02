# 商业赛事数据 API 调研

## 1. 调研状态

- 调研日期：2026-07-25
- 范围：日本、香港、英国、法国、美国的赛前 racecard、计划/修正时间、骑师、闸位、
  退赛/取消/延期、临时赛果、正式赛果。
- 本文只基于供应商公开资料形成采购候选，不代表来源 proof、合同批准或生产授权。
- 价格、覆盖和条款会变化；签约前必须取得书面报价、许可和样本响应，并冻结到
  `provider_contract_version`。

## 2. 候选矩阵

| 候选 | 公开覆盖/字段 | 公开价格 | 权威与限制 | 建议 |
|---|---|---:|---|---|
| The Racing API | Core 完整覆盖英国、爱尔兰、香港；全球 Group 级与部分 handicap；北美 add-on；racecard 含 `off_dt`、draw、jockey、runner，今日资料/赔率/结果约每 3 分钟更新 | Basic £27.99/月；Standard £59.99/月；Pro £99.99/月；北美 +£49.99/月 | 条款明确声明不是任何地区官方数据商、更新频率不保证；未来 racecard 最多约 7 天；不得未经许可转售原始数据 | 首选低成本、一个月的英国＋香港＋全球重点赛 supplemental proof；美国按需加购。不能直接产生 official |
| JRA-VAN Data Lab / JV-Link | JRA 官方数据；30 年 JRA 数据及比赛日实时赔率、马体重、赔付等；`jrvltsql` 可导入 SQLite/PostgreSQL | ¥2,090/月，首月试用 | Windows PC/JV-Link 形态，不是现成 Linux REST API；用户已核实本站可在限速条件下使用 | 日本 JRA 官方候选；用 `jrvltsql` 确定性采集，不用 MCP 自然语言层承担生产写入；NAR/JPN1 另行补源 |
| Equibase / TrackMaster downloadable charts | 美国机器可读 XML/CSV 赛果；Downloadable Charts 公开页未披露文件时效。另一项 PDF Full Charts 页面只称比赛结束后数分钟可用，不能外推为 XML/CSV SLA 或 official marker | $1.50/race card，或 $199.95/月 | 公开产品是下载文件而非通用实时 API；机器文件真实延迟、正式性、赛前 entries 和公开再发布权均需按场 proof/书面确认 | 美国赛果 proof 可先按场购买，避免直接订阅；proof 通过前不能产生 official，也不能单独满足阶段 B |
| Podium（原 PA Betting Services）Pulse | API/live feed，公开页支持赛前资料、live updates、official results，但没有给出 Umanews 五地区逐项覆盖 | 询价 | 面向 sportsbook/媒体，地区、字段、中文媒体展示许可和最低合同额未公开 | 先索取五地区字段表；若有非博彩媒体小流量方案，再作为企业候选 |
| SIS | 提供 racecard、race-day control、settlement；宣传覆盖多个地区和赛种，其 59,000+ 数量不能解释为纯赛马或 Umanews 五地区完整覆盖 | 询价 | 面向 betting operator；存在 territorial restriction，部分地区还需 rights-holder licence | 地区表值得询价，但必须确认逐项赛马覆盖、中国大陆/香港访问与非博彩媒体许可 |
| BetMakers | 提供实时 racefield/result management 和 API；335,000+ 是 Thoroughbred、Greyhound、Harness 等多赛种总量 | 询价 | 主要面向 wagering；未公开 Umanews 五地区逐字段覆盖和媒体许可 | 只有逐项覆盖和小流量报价合理才进入 proof |
| Racing and Sports | 全球 wholesale data、enhanced content、SaaS，覆盖赛事机构、媒体和 wagering 客户 | 询价 | 公开页没有逐地区字段、时效、SLA 和价格 | 作为媒体取向的备选询价对象 |
| Spotlight/Racing Post Superfeed | API 提供 form、silks、ratings、逐马评论，公开称每年 60,000+ racing events | 询价 | 更偏内容和 insights，不等同于官方 race control/result feed | 可补充展示内容，不作为本生命周期的首要状态权威 |

## 3. 公开资料

- The Racing API：
  - https://www.theracingapi.com/
  - https://www.theracingapi.com/data-coverage
  - https://api.theracingapi.com/documentation
  - https://www.theracingapi.com/terms-of-service
- JRA-VAN：
  - https://jra-van.jp/dlb/
  - https://developer.jra-van.jp/
- Equibase：
  - https://www.equibase.com/products/whatisfullcharts.cfm
  - https://www.equibase.com/products/whataredownloadablecharts.cfm
- Podium：https://podiumsports.com/sportsbooks/pulse/
- SIS：
  - https://www.sis.tv/rights_holders/
  - https://www.sis.tv/wp-content/uploads/2026/01/SIS-Racing-Sales-Presenter-ENG.pdf
- BetMakers：
  - https://betmakers.com/solutions/fixed-odds
  - https://betmakers.com/solutions/data
- Racing and Sports：https://www.racingandsports.com.au/about-us
- Spotlight：https://www.spotlightsportsgroup.com/b2b-content-services/superfeed/

## 4. 采购前强制问卷

任何商业来源必须逐项取得书面答案：

1. 五地区逐项覆盖：entries、计划/修正时间、jockey、barrier/draw、scratch/withdrawal、
   postponed/cancelled、provisional/official/corrected result。
2. 每个字段的首次可用时间、典型/最差延迟、修正事件语义和稳定外部 ID。
3. 是否为 rights holder/official distributor；若不是，原始来源和权利链是什么。
4. 是否允许 Umanews 在中文新闻网站缓存、转换、翻译、公开展示衍生字段；是否要求署名、链接、
   删除或合同终止后清除。
5. 中国大陆/香港的地域限制、并发/IP 限制、月请求量、超额费用、最低合同期和税费。
6. SLA、维护通知、schema/version/deprecation、支持响应时间、事故与补数机制。
7. 是否允许保存原始响应作为内部审计 evidence；保存期限及个人/敏感数据限制。
8. 测试环境、至少 20 场跨地区样本和一个实际赛日 trial；不得只凭销售演示签生产合同。

## 5. 推荐采购顺序

1. **The Racing API Pro 单月 proof**：£99.99；先覆盖英国、香港和全球重点赛事。若需要美国，
   再加 North America £49.99/月。订阅前先书面确认 Umanews 的中文公开展示属于允许的
   application/website 使用，而不是禁止的原始数据 resale。
2. **JRA-VAN 一个月 proof**：¥2,090；用户已核实限速使用边界，下一步验证 Windows collector、
   `jrvltsql` 字段映射、实时恢复和 staging 隔离。JPN1/NAR 不在其覆盖内。
3. **Equibase 美国按场 proof**：先用 $1.50/race card 的少量赛事验证 official chart
   身份、延迟和字段，再决定是否采用 $199.95/月。
4. 用同一 RFQ 向 SIS、Podium、BetMakers、Racing and Sports 询小流量非博彩媒体报价。
   报价未返回前不能把“企业级”写成“价格合理”或排入生产计划。

建议的初始自助订阅成本上限是 **£150/月加实际税费**，仅用于一个月 proof；企业合同预算
由用户在收到书面报价后另行确认。任何付费 proof 与生产采购、生产启用仍是三个独立授权。

## 6. 对现有阶段设计的影响

- 阶段 A 不依赖任何付费来源，保持不变。
- 阶段 B 可把通过合同与样本 proof 的商业来源加入 provider registry；T-21/T-14 的窗口不能
  依赖只提供未来 7 天 racecard 的来源。
- 阶段 D 可用商业聚合源提供 provisional/supplemental，但只有合同明确的 official feed 或
  现有官方核验链可升级为 official。
- 同一供应商在不同地区、字段和结果阶段可具有不同 authority，不能只按 provider 名称赋权。
- 供应商费用、请求量、覆盖缺口、延迟和错误率必须进入运营指标，便于续费与 fallback 决策。
