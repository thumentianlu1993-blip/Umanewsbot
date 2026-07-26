# 2026-07-08 至 2026-07-26 缺失赛果来源调研

## 1. 结论

生产只读盘点中的 `49` 个零赛果 `RaceEvent` 包含 `9` 个已经在另一历史实体上有确认赛果的
重复赛事；按真实赛事去重后，待采集为 `40` 场：

| 地区 | 待采集 | 候选采集层 | 官方确认层 |
|---|---:|---|---|
| 日本 | 6 | 不需要第三方候选 | JRA 官方 replay 4 场；NAR `RaceMarkTable` 2 场 |
| 英国 | 11 | Sporting Life 日期结果页 | BHA Results，仅人工浏览 |
| 法国 | 4 | ZEturf 逐场结果页 | France Galop，仅人工浏览；当前匿名访问跳转登录 |
| 美国 | 19 | TOBA→Equibase 12 场；Sporting Life 7 场 | Equibase chart，仅人工浏览 |

`RaceEvent#924` Hackwood Stakes 不计入上述 40 场。它已有 `7` 条未确认赛果，应继续走现有
race-live owner/投影链，只补 BHA official receipt，不得由历史补数命令直接覆盖。

## 2. 分母守恒与重复实体

本 change 的冻结基线不是“约 40 场”，而是以下精确分解：

`59 event rows = 40 missing + 9 duplicate-zero + 9 duplicate-confirmed + 1 provisional`

`50 race groups = 40 missing + 9 duplicate groups + event 924`

9 组重复候选为：

| 零结果产品 Event | 已有确认结果 Event | 赛事 |
|---:|---:|---|
| 405 | 15640 | Victory Ride |
| 408 | 15587 | Prairie Meadows Cornhusker |
| 409 | 15487 | Caress |
| 410 | 15484 | Bowling Green |
| 79 | 15441 | 七夕赏 |
| 729 | 16193 | Prix Jean Prat |
| 730 | 16176 | Prix de Malleret |
| 731 | 16199 | Grand Prix de Paris |
| 732 | 16198 | Prix Maurice de Nieuil |

上述 18 条 event row 只形成 9 个 identity review group，不进入 40 场 candidate 分母；
任何一组都不能只凭本表自动投影，仍须重新核对官方结果并批准 canonical event。

40 场缺失 event ID 精确全集：

- 日本：`80, 81, 82, 83, 184, 185`
- 英国：`917, 918, 919, 920, 921, 922, 923, 925, 926, 927, 928`
- 法国：`733, 734, 735, 736`
- 美国：`406, 407, 411, 412, 413, 414, 415, 416, 417, 418, 419, 420, 421, 422, 423, 424, 425, 426, 427`

实现必须断言四组互斥、总数为 `40`，且 event `924` 与上述 18 条重复 event row 均不在集合中。

## 3. 现有台账为什么不能直接补

- 英国 `source_refs.primary` 只是 BHA 年度 Pattern/Listed 赛程 PDF，不含赛果。
- 法国 `source_refs.primary` 只是 France Galop 年度分级赛赛程 PDF，不含赛果。
- 美国 19 场在生产台账中的 `chart_url` 全为空；原始 TOBA 内容抓取时间为赛前。
- HRN 旧 `/entries-results/YYYY-MM-DD` 入口在本次复核中重定向至首页，不能继续视为可靠
  的美国历史赛果入口。
- 官方确认路由在仓库 policy 中均为 `manual_browser_only`；
  第三方候选不能单独生成 `is_confirmed=true`。

## 4. 日本 6 场

| Event | 日期 | 赛事 | 官方赛果来源 |
|---:|---|---|---|
| 184 | 07-08 | スパーキングレディーカップ | NAR `RaceMarkTable?k_raceDate=2026/07/08&k_babaCode=21&k_raceNo=11` |
| 80 | 07-19 | 小倉記念 | JRA `/datafile/seiseki/replay/2026/063.html` |
| 81 | 07-19 | 函館2歳S | JRA `/datafile/seiseki/replay/2026/064.html` |
| 185 | 07-20 | マーキュリーカップ | NAR `RaceMarkTable?k_raceDate=2026/07/20&k_babaCode=10&k_raceNo=12` |
| 82 | 07-26 | 関屋記念 | JRA `/datafile/seiseki/replay/2026/065.html` |
| 83 | 07-26 | 東海S | JRA `/datafile/seiseki/replay/2026/066.html` |

实测：JRA 年度页已列出四场冠军和上述 replay 链接；两个 NAR `RaceMarkTable` 均可从对应
`DebaTable` 解析到，HTTP 200。现有 JRA/NAR detail adapter 已支持这些页面结构。

## 5. 英国 11 场

候选页按日期批量采集：

| Event | 日期 | 赛事 |
|---:|---|---|
| 917 | 07-09 | Princess of Wales's Stakes |
| 918 | 07-09 | Bahrain Trophy Stakes |
| 919 | 07-10 | Falmouth Stakes |
| 920 | 07-10 | Duchess of Cambridge Stakes |
| 921 | 07-10 | Summer Stakes |
| 922 | 07-11 | Summer Mile Stakes |
| 923 | 07-11 | Superlative Stakes |
| 925 | 07-25 | King George VI and Queen Elizabeth Stakes |
| 926 | 07-25 | Valiant Stakes |
| 927 | 07-25 | Princess Margaret Stakes |
| 928 | 07-25 | York Stakes |

实测 Sporting Life 的四个日期页 HTTP 200，页面逐场命中上述 11 场。仓库已有
`prepare_uk_sportinglife_race_detail_candidates.py`，可解析 runners/results，但输出仍是
候选。最终确认使用 BHA `https://www.britishhorseracing.com/racing/results/` 的浏览器页面；
该站结果由前端 token/API 加载，直接按日期拼 path 会 404，因此不能把日期 path 当固定 API。

## 6. 法国 4 场

| Event | 日期 | 赛事 | 已验证候选页 |
|---:|---|---|---|
| 733 | 07-19 | Prix Robert Papin | ZEturf `R1C1` Chantilly |
| 734 | 07-19 | Prix Chloé | ZEturf `R1C5` Chantilly |
| 735 | 07-19 | Prix Messidor | ZEturf `R1C7` Chantilly |
| 736 | 07-22 | Grand Prix de Vichy | ZEturf `R5C6` Vichy |

四个页面标题均实测返回对应赛事的 `Résultats & Rapports`；现有
`prepare_france_zeturf_race_detail_candidates.py` 支持该结构。最终确认仍应使用
France Galop；本次匿名访问 `/en/racing/` 会跳转 Microsoft CIAM 登录，所以执行时必须由
人工浏览器会话完成，不能把 France Galop 作为当前无人值守抓取入口。

## 7. 美国 19 场

### 7.1 已有精确 Equibase chart discovery 的 12 场

TOBA 当前页面已经为以下赛事给出 `eqbPDFChartPlus.cfm` 的精确 `TID/DT/RACE`，并填入冠军：

| Event | TID / 日期 / Race | 赛事 |
|---:|---|---|
| 406 | IND / 07-11 / 11 | Indiana Oaks |
| 407 | IND / 07-11 / 12 | Indiana Derby |
| 411 | MTH / 07-18 / 7 | Matchmaker |
| 412 | MTH / 07-18 / 6 | Molly Pitcher |
| 413 | MTH / 07-18 / 4 | Monmouth Cup |
| 414 | MTH / 07-18 / 11 | United Nations |
| 415 | MTH / 07-18 / 12 | Haskell |
| 416 | DMR / 07-18 / 8 | San Diego |
| 417 | DMR / 07-18 / 9 | San Clemente |
| 418 | SAR / 07-18 / 5 | Diana |
| 419 | SAR / 07-18 / 8 | Coronation Cup |
| 420 | SAR / 07-19 / 9 | Quick Call |

这些 TOBA 链接仅用于发现具体 Equibase chart；TOBA 是 candidate/discovery 证据，不是本
change 的官方结果 authority。最终全马名次、骑师、时间和退赛状态以对应 Equibase chart
人工核验，不以 TOBA 的冠军列代替完整赛果，也不自动下载 chart。

### 7.2 TOBA 尚未更新的 7 场

| Event | 日期 / 赛场 | 赛事 | 当前候选 |
|---:|---|---|---|
| 421 | 07-24 / SAR | Shuvee | Sporting Life 日期结果页 |
| 422 | 07-25 / MTH | Monmouth Oaks | Sporting Life 日期结果页 |
| 423 | 07-25 / DMR | Bing Crosby | Sporting Life 日期结果页 |
| 424 | 07-25 / SAR | Alfred G. Vanderbilt | Sporting Life 日期结果页 |
| 425 | 07-25 / SAR | Coaching Club American Oaks | Sporting Life 日期结果页 |
| 426 | 07-26 / DMR | Eddie Read | Sporting Life 日期结果页 |
| 427 | 07-26 / SAR | Honorable Miss | Sporting Life 日期结果页 |

TOBA 当前仍没有这 7 场的 chart link、出赛数或冠军，不能等待台账旧字段自动补齐。
Sporting Life 三个日期页已实测逐场命中，可先生成候选；然后按日期和赛场在 Equibase
downloadable chart 中定位 race number 并人工确认。Equibase 对非浏览器请求返回拦截 HTML，
现有 policy 也明确禁止自动抓取或绕过反爬。

## 8. 执行边界

本调研只确认来源与可行性，不产生 candidate artifact，不写数据库，也不构成联网批量采集、
历史 apply、发布或 official promotion 授权。后续采集应先冻结上述 40 场 source map，
再生成只读候选和逐场 completeness/identity report；40 场全部无 blocker 后，另行申请生产写入。

candidate 网络访问还必须独立满足既有 source permission/runner allowlist；官方 registry 中的
`manual_browser_only` 只允许人工浏览核验，不授权自动抓取。特别是 Equibase chart 本批只生成
结构化人工 receipt，不保存受限 raw 页面或凭据；既有离线 PDF parser 的存在不等于网络许可。
