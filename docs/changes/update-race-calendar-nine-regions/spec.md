# 九地区赛事日历更新与 2025+ 全集补足

## 背景

用户任务（2026-09-26）：赛事日历的未来赛事几乎没有更新。要求调研各地区比赛源（多数据源防缺失）、
以 IFHA ICS 蓝皮书为全集基准补足准确比赛全集；将日本（区分 JRA/NAR）、中国香港、英国、爱尔兰、
法国、美国、澳洲、德国、中东的比赛来源保存下来；补足 2025 年起所有比赛信息；已结束的历史比赛
按当前要求补充赛果。范围限定国际重赏（G1/G2/G3）+ 地方一级赛（如 Jpn1）。

## 生产基线（2026-09-26 只读实测）

- 2025：日本 139 / 香港 19 / 英国 305 / 法国 191 / 美国 411；爱尔兰/澳洲/德国/中东 = 0。
- 2026：日本 260 / 香港 51 / 英国 296 / 法国 248 / 美国 605；2027 仅香港 22。
- 27 场已过赛日仍 `scheduled`（法 8 / 日 3 / 英 5 / 美 11）；15 场 `finished` 零赛果。
- 香港马季错位实锤：生产**完全没有** local_date 落在 2024/2025 年 9-12 月的香港赛事——
  2025/26 马季前半段（12 场 ICS 分级赛：香港杯/一哩/短途/瓶、骑师俱乐部系列、国庆杯等）整体缺失。

## 范围口径

- 地区：japan（JRA/NAR 分源）、hong_kong、united_kingdom、ireland、france、united_states、
  australia、germany、middle_east（阿联酋+沙特；卡塔尔/巴林仅 ICS 收录场次）。
- 等级：ICS Part I 收录的 G1/G2/G3（含障碍）+ 日本 NAR Jpn1（ICS 不收，单独从 keiba.go.jp 补）。
- 年份：2025（完整年，补全部赛果）、2026（当前年）、2027（已公布赛历地区）。
- 跨年赛季（香港 9-7 月、澳洲 8-7 月、中东 11-4 月）按 `local_date` 公历年归属，ICS 年度按赛季映射。

## 全集基准与来源

详见根文档 [race_calendar_source_registry.md](../../race_calendar_source_registry.md)。
ICS 蓝皮书为集合与级别的唯一基准；官方赛历定日期/马场；赛果官方优先 + 第三方交叉。

## 阶段 0 已交付（本 change 当前状态）

1. 新增爱尔兰 ICS catalog 支持：`hri_pattern_catalog`（`Pt I—IRELAND/IRE` 平地 + Irish Jumps 页头），
   从 UNSUPPORTED 清单移除爱尔兰；解析器版本升至 `2026.09.1`。
2. 修复澳洲 25 场/年被静默丢弃的解析缺陷：ICS 澳洲章节年龄栏使用 `open`（含 `open f/m`），
   `AGE_PATTERN` 不支持导致整行不成段——含 The TAB Everest、C. F. Orr S.、All-Star Mile 等 G1。
3. 修复 `_suspicious_catalog_names` 守卫对合法含数字赛名的误判
   （Irish 1,000/2,000 Guineas、Doomben 10,000 等），保留对奖金串入名称的拦截。
4. 新增对账工具 `runtime/tools/reconcile_race_calendar_vs_ics.py`（ICS 应办全集 vs 生产导出，
   赛季窗口映射、别名匹配、同日重复检测、缺赛果/滞留状态标记）+ 7 项测试。
5. 产物（本地 `runtime/race_calendar_nine_regions/`）：
   - ICS 2025/2026 source cache（PDF + 索引，SHA-256 锁定）与九地区 derived CSV、manifest；
   - 来源冲突审批（5 项上游印刷/计数不一致，逐项分析与区域官方对账来源）；
   - 生产导出（2,547 场 2025+ 赛事 + 3,280 别名）与 gap_ledger.json / gap_review.csv。

## 对账结论（2026-09-27）

ICS 2025+2026 应办全集 3,393 行（含障碍）：澳洲 337×2、法国 191×2、德国 42×2、香港 31×2、
爱尔兰 187/184、日本 141×2（另有 NAR Jpn1 需从官方单补）、中东 45/44、英国 307/306、美国 420/416。

- **2025 真实缺口（完整年）**：香港 12（马季前半段整段缺失）、英国 15（多为让赛家族冠名版本，
  含 Dick Poole S. G3 待确认）、美国 10（含 Matron S.——ICS PDF 文本层损坏行，TOBA 补齐；
  4 场障碍 G1/G2 待确认）、日本 2（中山大障害/中山グランドジャンプ 两场 J-G1 待确认匹配）。
- **新四地区**：爱尔兰/澳洲/德国/中东 2025+2026 全部缺失（约 1,218 场）。
- **2026 身份挂账**：法国 67、英国 183、日本 65、美国 48 场 ICS 行未匹配——大量是命名差异
  （冠名/语言/Prix 前缀），须走系列身份映射（map_existing_race_event_series / 身份审核），
  禁止据此盲目新建赛事（会造成重复）。
- **生产侧问题**：同日疑似重复 145 组（290 行，美国双轨导入为主）；43 场 Jpn2/Jpn3 等地方
  存量保留；24 场 stuck_scheduled + 6 场 finished 零赛果（与对账前的只读口径 27/15 存在
  匹配覆盖差异，以 ledger 为准）。
- **urgent**：TRA registry `valid_until=2026-09-27`（已到期），`verified_at` 31 天门禁
  2026-09-28 到期——race_data_sync 链路正在/即将 fail-closed，需立即续验。

## 后续阶段（见 tasks.md）

1. 阶段 1：存量五地区 2025/2026 补缺（先身份映射、后导入）+ 赛果按当前要求补齐。
2. 阶段 2：新四地区详情 adapter + inventory/series + 2025 起赛事与赛果（draft 导入）。
3. 阶段 3：周期赛历刷新机制（修复"无自动新增入口"根因）+ 日本登记修复 + TRA 续验与新地区路线。
4. 阶段 4：新地区公开展示（地区 tab/颜色，用户确认后发布）+ 文档回写。

## 验收

- 阶段 0：`stable.test_tjcis_ics_catalog`（77 项）、`stable.test_historical_race_catalog_adapters`、
  `stable.test_race_calendar_ics_reconciliation`（8 项）通过；ICS 解析全部地区通过官方计数自校验
  或登记在册的审批冲突；对账 ledger 与 review CSV 生成。
- 后续阶段的生产写入均走既有门禁（descriptor/approval、dry-run、备份、apply、verifier、公网验收）。

## 阶段 1-C 核验结论（2026-09-27）

`verify_calendar_gap_rows.py`（6 项测试）对 ICS 2025 缺口行逐场核验（生产导出+别名）：
- 香港 12 场：真实缺失（已产出候选，P1-A）。
- 日本 2 场 J-G1：真实缺失（已产出候选，P1-B）。
- 英国 15 场：13 场为 ICS 冠名变体的身份挂接问题（生产已有同日赛事），**Dick Poole S. G3 为真实缺场**——
  原赛日 2025-09-04 Salisbury 会议因暴雨取消，BHA 官宣改期至 2025-09-12（已产出 Sporting Life 候选，
  冠军 Anthelia 正确）；Classic H. Stp.（Warwick 2025-01-11 冰冻取消、未补办）→ not_held。
- 美国 10 场：Remsen G2（2025-12-06 Aqueduct，Paladin）与 Matron G3（2025-10-02 Aqueduct，Final Accord）
  已产出 HRN 候选；4 场障碍（Colonial Cup G1 2025-11-23 Camden-FIL DOR、Commonwealth Cup G1 2025-05-03
  Great Meadow-Cool Jet、Temple Gwathmey G2 2025-04-19 Middleburg-Snap Decision、Noel Laing G3 2025-11 Montpelier
  -Cool Jet）已用 NSA 官方结果 PDF 解析验证（parse_nsa_pdf 新增 race_marker 分场，4 项测试）。
  Brooklyn G2、Cougar II G3、Robert J. Frankel G3、Tokyo City Cup G3 四场 2025 未举办
  （Wikipedia/TOBA/HRN 多重证据），应标 not_held 而非补场。
- Matron S. 是 ICS 2025 印刷行被 PDF 文本层损坏（"yo f"）而漏入目录的赛事，由 TOBA 官方表补入；
  该目标不在生产总账，apply 时需新建 target。

证据目录：runtime/race_calendar_nine_regions/{hk_gap_2025,jra_gap_2025,nar_gap_2025,uk_gap_2025,us_gap_2025,us_jumps_2025}/。
