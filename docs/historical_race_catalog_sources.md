# 五地区历史赛事目录来源矩阵

## 使用边界

- 本文记录 `backfill-race-events-to-1984` 的逐年目录和系列 timeline 来源调查，不代表已经抓取或批准任何历史总账。
- 目录权威顺序：当年主办方/监管机构官方资料、官方历史档案或年鉴、高可信专业数据库、参考来源。
- 线上缺少某年官方目录时，必须进入 `source_unavailable` 或使用经审核的官方年鉴离线 cache；不得把当前目录机械复制到旧年份。
- 每个 adapter 输出必须保存 source URL、cache SHA-256、parser version、来源年份和支持年代。解析空表、损坏 PDF、403 或结构不符必须失败，不能输出“空成功”。

## 日本 JRA / NAR

### JRA

- 官方入口：`https://www.jra.go.jp/datafile/seiseki/index.html`。
- JRA 页面明确说明年度“重赏赛事列表”覆盖 2002 年以后；G1 单赛历史页可查看 2001 年以前成绩，例如 1984 有马纪念：`https://www.jra.go.jp/datafile/seiseki/g1/arima/result/arima1984.html`。
- JRA DB 还能返回部分 1980 年代正式赛果，但年度完整 graded 目录不能只靠 G1 历史页证明。
- 国立国会图书馆书目可确认 JRA 正式《中央競馬年鑑 昭和59年》存在：`https://ndlsearch.ndl.go.jp/search?cs=bib&from=0&q-subject=%22%E7%AB%B6%E9%A6%AC--%E5%B9%B4%E9%91%91%22&size=20`。该书目证明权威年鉴路径存在，不等于当前仓库已经取得可解析扫描。
- 结论：2002 年以后可使用官方年度重赏列表；1984–2001 必须组合 JRA 官方 DB、当年赛程/成绩表和官方年鉴 cache。只找到 G1 结果时不得宣称该年全部 G2/G3 已完整发现。

### NAR

- 官方数据下载说明：`https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf`，标准 race-list CSV 包含竞走种类、重赏名称等字段。
- 官方重赏日程 PDF 可作为近年逐月目录，例如 `https://www.keiba.go.jp/pdf/RaceScheduleList/heavyprize201801.pdf`。
- 当前在线下载和日程资料不能单独证明 1984 起全部地方分级/重赏目录。
- 结论：近年使用官方 CSV/PDF；旧年代按 NAR/各地方主办方官方年鉴分层建 cache，Jpn/地方等级必须保存当年语义，不把当前 `Jpn` 等级倒灌到制度建立前。

## 中国香港 HKJC

- HKJC 官方正式赛果支持至少 1984 年，1984 香港打吡示例：`https://racing.hkjc.com/en-us/local/information/localresults?RaceNo=5&Racecourse=ST&racedate=1984%2F01%2F22`。
- 同日全部赛果入口：`https://racing.hkjc.com/en-us/local/information/resultsall?racedate=1984%2F01%2F22`。
- 正式赛果包含赛名、日期、场地、途程、名次、马号、马名、骑师、练马师、闸位、负磅、时间和赔率，可作为详情与 timeline 证据。
- 结论：详情可直接跨到 1984；年度 graded 目录仍要按香港赛季和当年分级制度重建，不能仅以名称含 `Derby` 判断分级。跨年赛季必须映射到实际比赛公历年。

## 英国 BHA

- BHA 官方保留 Flat Pattern/Listed 年册，已确认 2013：`https://www.britishhorseracing.com/wp-content/uploads/2017/03/FlatPattern2013-1.pdf`、2014：`https://www.britishhorseracing.com/wp-content/uploads/2017/03/Flat-pattern-2014-LowRes.pdf`。
- BHA 官方年册索引：`https://www.britishhorseracing.com/about/publications/pattern-and-listed-race-books/`，当前可见部分 2018 以后年册；索引未覆盖 1984 起全部年份。
- 现行官方年册位于 BHA media 的 `Pattern_Listed_Books`，例如 2024 Flat 和 2024/25 Jump。
- 年册区分 Flat Group 与 Jump Grade/Pattern，两个体系必须分别解析，不能把 Jump Premier Handicap 当 Flat Pattern。
- 结论：已找到部分官方旧年册和现行年册；1984 起缺失年份须继续收集 BHA/BHB/Jockey Club 官方年册 cache。年度变更新闻只能补充升降级/迁场沿革，不能替代当年完整目录。

## 法国 France Galop

- France Galop 官方发布现行平地 Group/Listed 总表，例如 2026：`https://www.france-galop.com/sites/default/files/2026-02/groupes_listed_plat_2026_v7.pdf`。
- 官方赛程 PDF 和结果公报可提供当日等级、马场、距离与正式结果，例如结果公报入口可见 `24plat09.pdf`。
- 官方历史专题可作为单系列沿革补证，例如 Arc、Grand Prix de Saint-Cloud 等，但专题文章不是年度完整目录。
- 结论：近年目录和结果使用 France Galop PDF；1984 起旧年度完整 Group 目录需要 France Galop 官方年鉴/公报离线 cache。OCR 断词、重音和冠名变化必须进入显式修正规则或人工审核。

## 美国 TOBA / AGSC

- TOBA American Graded Stakes Committee 官方入口：`https://toba.org/graded-stakes/`。
- TOBA 说明 AGSC 始于 1973，1974 发布第一份北美分级赛表，并作为北美赛事 grading authority；因此 1984 已处于正式分级制度内。
- 当前官方页说明年度审核、Grade I/II/III/Listed 与最近五届正式 chart 的评估机制，但当前网页不能直接替代 1984 年年度完整清单。
- 结论：逐年 grade 目录优先使用 TOBA/AGSC 当年正式列表或 workbook cache；正式详情使用各赛场/Equibase chart。历史同名异场赛事和 Bayakoa/Frankel 等重复 key 必须逐项审核，不能只按名称合并。

## 当前来源缺口

- JRA 1984–2001 全部 G2/G3 年度目录尚缺统一在线入口。
- NAR 1984 起地方重赏/分级目录尚缺连续官方在线年表。
- BHA 1984 起 Flat/Jump 官方 Pattern 年册尚未收齐。
- France Galop 1984 起年度 Group/Listed 官方年鉴尚未收齐。
- TOBA/AGSC 1984 起年度 Graded Stakes 正式列表尚未收齐。
- 以上缺口均为 adapter/source-cache 任务，不改变“统一追溯至 1984”的产品范围；未补齐前对应年度保持待发现或 `source_unavailable`，不得生成完整总账批准。

## 离线 adapter 契约

- 五地区目录统一由 `parse_historical_race_catalog` 读取离线 source manifest；该命令不触网、不写数据库，只校验 cache 身份并生成 `catalog_candidate.jsonl`、`series_timeline_candidate.jsonl`、`summary.json` 和带 SHA-256 的 `manifest.json`。
- source manifest 必须声明 `schema_version=1.0`、adapter key、parser version、provider、authority、支持年份范围，以及每个 cache 文件的相对路径、原始 source URL 和 SHA-256。cache 路径不得逃出 manifest 所在目录。
- CSV 必填列为 `record_type / year / series_key / original_name / grade_text / racecourse / local_date / distance_text / surface / expectation_status / season_label / source_scope / discipline`。香港必须保存官方赛季标签；英国必须区分 `flat / jumps`；日本 JRA/NAR、美国 graded stakes 等来源范围保存在 `source_scope`。
- `catalog` 只接受该地区允许的 graded/group 等级；`timeline` 可额外接受 `Listed / Open / Ungraded`，仅用于已在任一年度进入范围的系列补足升格前、降级后、取消或未举办届次。只有 timeline、从未进入 catalog 的系列必须失败。
- 运行示例：`python server/manage.py parse_historical_race_catalog --source-manifest <manifest.json> [--source-manifest <manifest.json> ...] --output-dir <candidate-dir>`，随后使用 `python server/manage.py build_historical_race_inventory --catalog-jsonl <candidate-dir>/catalog_candidate.jsonl --timeline-jsonl <candidate-dir>/series_timeline_candidate.jsonl --output-dir <inventory-dir>`。
- `server/stable/fixtures/historical_race_catalog/` 只用于验证五地区、三年代和旧格式解析契约，是小型测试摘录，不是权威完整年度目录，也不得直接作为生产 inventory 批准依据。生产逐年 source cache 收集仍属于任务 `8.3`。

## TJCIS / IFHA International Cataloguing Standards 年鉴

- 官方历年入口为 `https://www.tjcis.com/default.asp?content=PASSYR`，当前版入口为 `https://www.tjcis.com/default.asp?content=ICS`。官方页面提供 1998–2025 历年整本 PDF 和 2026 当前整本 PDF，每本只代表其标注年度，可作为五地区逐年 graded/group 目录共同骨架。
- 年鉴覆盖法国、英国、日本、美国和香港；香港在不同年代分布于 Part I/Part II，英法日美障碍赛还可能位于 Part IV。解析必须按分册和国家页头切换，不能把相邻国家赛事串入目标地区。
- `runtime/tools/prepare_tjcis_ics_catalog.py` 低频下载官方索引和 PDF。所有请求经过共享 request budget，原始文件经过 source cache/磁盘预算并记录 URL、大小和 SHA-256；派生 CSV 每行继续保存原始 PDF 路径、SHA-256 和 URL。
- 解析器只输出 G1/G2/G3，Listed/LR 不进入 catalog；平地章节若自报 `Total Graded/Group races`，解析数必须完全一致。`awt` 映射为 synthetic，同年同地区同名赛事按赛场形成不同待审 key，禁止静默覆盖。
- 正式命令：`python runtime/tools/prepare_tjcis_ics_catalog.py --years 1998-2026 --output-dir <source-dir> --allow-network`。中断后可加 `--resume`，但只复用 source-cache manifest、大小和 SHA-256 全部一致的缓存；全缓存离线复跑不要求开启网络开关。
- 年鉴解决 1998–2026 的目录骨架，不替代主办方正式赛果，也不补齐 1984–1997。完整总账批准前仍须按地区补齐 1984–1997 官方年鉴/目录，并审核改名、迁场、前分级和停办 timeline。
