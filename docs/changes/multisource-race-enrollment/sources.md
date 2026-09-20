# 来源调查与准入矩阵（2026-09-20）

本轮核对仓库入口及公开来源页面／来源自身说明，未对生产新增爬虫、调用新付费端点或证明自动化授权。表中“实施目标”是适配器任务，不是当前可用性断言。既有日历缺source ID时按design A0从原导入来源／已受审候选重新核验生成seed receipt；不要求先有受审series，也不把裸URL当身份证明。每来源必须提交固定页面 fixture、身份、开放窗口、完整性、确认标记、请求成本与访问许可证据，才可在相应地区启用。

| 地区合同桶 | 当前代码可复用 | 非 TRA 首批实施目标 | 补充候选／限制 |
| --- | --- | --- | --- |
| japan_jra | `race_pre_race.py`、JRA detail/legacy parser，104真实页已有证据 | JRA 官方赛程→当场卡→真实结果链接；完整身份/赛时/名单/结果，现有候选先重新核验 | Racing Post/ATR 按实际日本赛事覆盖验证；不假设全日本可读 |
| japan_nar | `race_pre_race_sources._nar`、`prepare_nar_race_detail_candidates.py` | NAR 官方列表、DebaTable/TodayRaceInfo/结果链，BabaCode+当地日期+RaceNo；与 JRA operator 严格分离 | RP/ATR 只有证实该场覆盖才用；来源没有赔率不补猜 |
| hong_kong | HKJC results-all/local-results parser；persisted official path 不是实时抓取 | HKJC 官方中英页面同一 race ID，RaceDate+Racecourse+RaceNo；报名/排位/赛果能力分别证明 | RP/ATR 国际场覆盖按场验证；不能将中文和英文页面当两个独立来源 |
| united_kingdom | Sporting Life 参考结果及绑定卡刷新；RP受限候选解析 | Sporting Life 独立发现/登记与全链（不再只在 TRA not_found 后调用） | BHA官方日历/结果、Racing Post、ATR；RP曾406，页面存在不代表生产可抓 |
| ireland（event country_region 目前可为 other） | TRA ireland；Sporting Life 卡解析可借鉴，但 roster 当前只准 UK | Sporting Life 或 ATR 的 Ireland 独立地区合同，不能借 UK proof 开放 Ireland | HRI 官方、RP；必须由 venue/operator registry 明确判为 Ireland，不能把所有 other 自动纳入 |
| france | ZEturf 参考结果、已绑定赛前刷新，France Galop已有离线工具/持久证据路径 | ZEturf 独立发现/登记、race_time/racecard/result 分能力准入 | France Galop 官方赛程与结果、RP/ATR；排除 trot/attelé/monté，不因法国网站而收全部赛种 |
| united_states | HRN 参考结果及 SL美国卡已有现场实例，NYRA绑定卡解析 | Horse Racing Nation 独立身份+结果登记；有合法完整结果时允许 result-only bootstrap；SL可补赛时/名单 | Equibase官方chart、NYRA官方站、RP/ATR。NYRA曾403、RP曾406，不能作为已可用备份 |

以上七桶统一机制。新增国家桶本轮不自动开启；适配器不允许覆盖外地域。首批验收每桶至少一个非 TRA 来源能独立登记；TRA作为另一个独立来源的去重到达顺序在fixture中必须覆盖。第二个非 TRA 仅在实际覆盖/访问/proof通过后启用，不为凑“多源”把同站双语或同一数据镜像重复计数。

## 公开资料依据

- [JRA 当场完整结果](https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde0106202604061120260920/92)：上一阶段实际取得完整详情及哈希，不能仅使用搜索索引的年度列表判断是否已出赛果。
- [NAR 数据入口](https://www.keiba.go.jp/KeibaWeb/DataRoom/DataRoomTop)：比赛信息与数据查询入口。[NAR 数据下载说明](https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf)可辅助核对字段，不等于授权批量下载。
- [HKJC 赛果入口](https://racing.hkjc.com/en-us/local/information/resultsall)、[HKJC 主页](https://www.hkjc.com/en-us/index)：存在排位、赛果和赛历入口；具体赛事与中英 ID 同一性仍需 fixture。
- [Sporting Life 赛事入口](https://www.sportinglife.com/racing/)、[结果入口](https://www.sportinglife.com/racing/fast-results/all)：用于后续列表/详情发现；快速结果不等于完整正式结果。
- [Racing Post 卡片/结果说明](https://help.racingpost.com/hc/en-us/articles/208203965-Cards-and-Results-grid)、[快速与完整结果说明](https://help.racingpost.com/hc/en-us/articles/212575729-Results-fast-and-full)：网站区分快速/完整赛果，适配器不能把获胜/入位摘要当完整名单。
- [ATR 官方打印资料说明](https://www.attheraces.com/printouts)：明确英国/爱尔兰卡片覆盖，其他地区本轮未验证。[ATR主页](https://www.attheraces.com/)可作发现入口，非隐藏 API 合同。
- [BHA官方赛果](https://www.britishhorseracing.com/racing/results/)：公开页依赖动态模板，本轮未取得单场结构化结果；保持 proof_required。
- [HRI官方入口](https://www.hri.ie/corporate)：有最新结果入口，本轮未验证单场正文与身份，保持 proof_required。
- [France Galop日历](https://www.france-galop.com/en/node/38)、[ZEturf主页](https://www.zeturf.fr/fr)：可见赛程及来源标注的正式到达信息；实际 gallop 完整结果要独立证明，不能将首页名次摘要视为完整结果。
- [Equibase Entries](https://www.equibase.com/premium/pubentriesfullindex.cfm)、[Full Charts说明](https://www.equibase.com/products/whatisfullcharts.cfm)：chart提供北美比赛结果资料；自动提取、字段及访问条件需后续合法proof，不绕过访问墙。
- HRN 本轮依据仓库现有 reference parser/route；未拿到新的官方说明页，实时覆盖留 unknown，不补造成功。

## 每个 route 的实施交付合同

记录 provider、contract_region、operator、source_class、identity namespace/ID解析、可信venue aliases、host/path/redirect、可用能力、source window/timezone、分页完成信号、完整 roster判据、官方/临时/更正判据、fixture URL+抓取时刻+SHA、parser版本、自动化准入/有效期、请求/字节预算。Racing API、官方、可信综合来源均可命中登记；来源类别只影响既有字段仲裁及结果authority，不提供跳过身份/权限/完整性检查的捷径。

不新增更高套餐的默认请求；TRA free 空响应不推断 Pro 同样为空。新端点若需要权限或成本变化，在 rollout 包明确，而不是藏在自动重试中。
