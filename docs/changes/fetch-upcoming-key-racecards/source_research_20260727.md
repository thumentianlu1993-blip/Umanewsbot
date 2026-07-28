# 2026-07-27 官方赛前来源研究

## 研究方法与限制

本轮使用仓库既有来源政策、生产 `source_refs`、官方公开页面和浏览器人工观察。研究访问不写
业务库；页面内容没有保存为候选，也没有据此 apply。页面观察窗口为
`2026-07-27T01:50:01+08:00..2026-07-27T02:15:49+08:00`；没有独立 receipt 的页面观察
只能标为 research signal。

仓库权威 policy locator：
`runtime/policies/race_live/official_routes_manual_v1.json`，文件 SHA-256
`fbd4dbabf4092dc7f9439bd02b4608663a1c14973ed9197ed54ae37e38220423`，
`generated_at=2026-07-19T00:00:00Z`、`valid_until=2027-07-19T00:00:00Z`。
继承研究 locator：
`docs/changes/automate-race-event-lifecycle/regional_source_research_20260725.md`，
SHA-256 `3157c7e7c7eaaa786238140be7464d15b2786167fb34e8c1908e81a3cbb996c5`。

## 来源矩阵

| 地区 | 官方来源 | 稳定标识/字段 | 公布与修订 | 条款与访问 | 结论 |
|---|---|---|---|---|---|
| 英国 | BHA 2026 Fixture List、BHA Pattern Book、Goodwood 官方 timetable | 赛程可证实日期、场地、赛事；当前动态页未得到完整 racecard/稳定 runner ID | Goodwood 明示时间为 provisional、可变 | policy route=`bha_manual_verification`、terms digest=`1edbbd...018`、contract=`da1162...a39`，仅 results/manual | entries 许可=`unknown`，transport blocked |
| 美国 | TOBA graded stakes schedule；Equibase official entries | Equibase 页面含 track/date/race number、post time、马号、马名、骑师、练马师、状态；需进一步证明稳定 event/runner ID | entries 分批发布并持续更新 scratched/MTO 等状态 | policy route=`us_official_manual_verification`、terms digest=`f2ca8e...57a8`、contract=`e7ae0f...00d6`，仅 `/static/chart/`；继承研究明确禁止未授权自动抓取/再发布 | entries automation=`blocked` |
| 法国 | France Galop groupes/listed PDF 与 Racing 入口 | PDF 可证实日期/赛事；公开赛前入口当前跳转登录，未取得 runner ID/完整 racecard | 未取得可审计公开发布时间证据 | policy route=`france_galop_manual_verification`、terms digest=`00ccf3...3df`、contract=`ca6219...2834`，仅 results/manual | entries 许可=`unknown`，transport blocked |
| 补充 | The Racing API | 可提供 provider race/runner ID 和 racecard 字段 | 免费层仅 today/tomorrow；T-7 依赖商业档位，覆盖/延迟待 proof | 非官方；provider contract 与联网需独立授权 | 只能做 discovery/provisional signal |

## 官方 URL

- 英国：
  - BHA fixtures：
    <https://www.britishhorseracing.com/racing/fixtures/upcoming/>
  - BHA 2026 Fixture List：
    <https://media.britishhorseracing.com/bha/Fixture_List/2026_Fixture_List.xlsx>
  - BHA 2026 Pattern Book：
    <https://media.britishhorseracing.com/bha/Publications/Pattern_Listed_Books/British_Flat_Pattern_Listed_2026.pdf>
  - Goodwood timetable：
    <https://www.goodwood.com/horseracing/qatar-goodwood-festival/timetable/>
- 美国：
  - TOBA 2026 graded stakes：
    <https://toba.org/graded-stakes/2026-races/>
  - Equibase entries：
    <https://www.equibase.com/static/entry/index.html>
- 法国：
  - France Galop racing：
    <https://www.france-galop.com/en/racing/>
  - 2026 groupes/listed PDF：
    <https://www.france-galop.com/sites/default/files/2026-02/groupes_listed_plat_2026_v7.pdf>

URL 只用于证据定位，不代表允许自动化。

## 条款/许可证据分类

| 来源 | evidence locator | observed/valid | 当前分类 | 说明 |
|---|---|---|---|---|
| BHA | policy JSON 内 `bha_manual_verification` | observed 2026-07-19；valid 至 2027-07-19 | `manual`（results）；entries=`unknown` | 没有 entries 自动化许可，不等同于官方明确禁止 |
| France Galop | policy JSON 内 `france_galop_manual_verification` | observed 2026-07-19；valid 至 2027-07-19 | `manual`（results）；entries=`unknown` | 没有 entries 自动化许可，不等同于官方明确禁止 |
| Equibase | policy JSON 内 `us_official_manual_verification`；继承研究文档 3 节 | observed 2026-07-19 / research 2026-07-25 | results=`manual`；entries automation=`blocked` | 原始 terms URL/正文 receipt 未进入本 change；在补齐前按更严格 blocked、transport=0 |
| TRA | 继承研究文档 3/4/7 节及已审核 provider registry | research 2026-07-25 | `supplemental` | 不具 official authority，联网/订阅另授权 |

本 change 没有把本轮浏览器页面另存为条款 receipt，因此不能更新上述 policy digest 或延长
有效期。任何证据不完整、过期或 scope 不含 entries 都保持 `transport=0/applicable=0`。

## 美国人工观察样本

以下只证明页面在证据时点显示了什么，不是可 apply artifact：

- Event 426，DMR race 9：官方页显示 Eddie Read，计划 `6:10 PM PT`，9 行中
  Astronomer 为 scratched；换算 UTC `2026-07-27T01:10:00Z`、上海
  `2026-07-27 09:10`，落入冻结窗口。
- Event 427，SAR race 8：Honorable Miss，计划 `5:12 PM ET`，7 行；UTC
  `2026-07-26T21:12:00Z`、上海 `2026-07-27 05:12`，落入冻结窗口。
- Event 428：Glens Falls，计划 `5:14 PM ET`，页面含 12 行及 MTO 状态。
- Event 429：Amsterdam，计划 `5:44 PM ET`，页面含 8 行。
- Event 434/435/436：Colonial Downs race 10/11/9 分别显示计划
  `5:05/5:52/4:22 PM ET`，页面可见 entries。
- Event 430/431/433：证据时点对应 DMR/SAR 页面返回未发布/404，不能猜时刻或出马。

## 字段与 phase 合同

| 字段 | 官方赛前语义 | 允许 phase |
|---|---|---|
| `race_datetime` | `scheduled_post_time` 换算后的 aware instant | `racecard`；provenance `time_semantics=scheduled_post_time` |
| `local_start_time` | 场地本地 wall-clock | `racecard`；provenance `time_semantics=venue_local_wall_clock` |
| 实际发走 | 赛后/实时确认的 actual off | 不属于本 change；使用现有 `official/corrected` 等受审赛果 phase |
| runner 基础字段 | 当前官方 declaration/entry | `racecard`；provenance `item_semantics=declaration` |
| 退赛/取消/MTO | 官方当前状态与修订时间 | `racecard`；provenance `item_semantics=revision_status_update` |
| TRA racecard | 第三方暂定候选 | `racecard` + `source_authority=supplemental`，不得冒充 official |

表中 `scheduled_post_time/declaration/revision_status_update` 均为 provenance 语义标签，不是
`RaceResultPhase` 枚举。

## blocker

1. 英国、法国没有当前已审核且机器可用的 official entries route。
2. 美国 official entries 可访问但自动抓取/再发布许可不成立。
3. 现有 route registry 的 official 合同只覆盖赛果，不覆盖赛前字段。
4. 部分美国赛事尚未发布；英国/法国具体公布时点缺连续证据。
5. 当前未证明所有来源都提供稳定 runner/horse ID。
6. 没有 T-7 官方全地区机器来源，无法把本窗口 19 场变为可信可 apply 全量。

## 解除 blocker 所需证据

- BHA/France Galop/Equibase 或其明确授权数据商的书面机器访问与再发布许可；
- 赛前 route 的稳定 event/runner ID、字段 schema、限流和变更通知合同；
- 至少连续 4 周的公布/修订时间、覆盖和结构稳定性 evidence；
- 新 provider contract version、terms digest、permission digest 与 field/phase 映射 review；
- 有界网络 proof 和不可变 artifact，再取得精确批次 apply 授权。
