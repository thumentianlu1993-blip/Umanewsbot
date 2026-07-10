# 现有赛事信息抓取与导入链路盘点

> 本文件是 proposal 后的上下文盘点，不是最终设计。`2026-07-10` 已完成第一轮 grill，锁定 proposal 级边界；后续 `design.md` / specs / tasks 仍需在用户确认继续后再生成。

## 正式管理命令

- `import_race_events`
  - 路径：`server/stable/management/commands/import_race_events.py`
  - 职责：从 CSV 导入或更新年度赛事基础表 `RaceEvent` 与别名。
  - 状态：正式链路，支持 `--dry-run`，适合继续作为基础赛事种子导入入口。

- `fetch_race_event_candidates`
  - 路径：`server/stable/management/commands/fetch_race_event_candidates.py`
  - 职责：按单场赛事读取候选 JSON payload 或 URL，并写入 `RaceEventDataCandidate`。
  - 状态：正式但偏单场/通用 JSON 入口；`jra`、`hkjc`、`racing_post` 等 source config 当前主要是占位或 payload 入口，不是完整批量爬虫。

- `import_race_event_detail_candidates`
  - 路径：`server/stable/management/commands/import_race_event_detail_candidates.py`
  - 职责：从 JSONL 批量导入 `runners`、`results`、`history_winners` 候选，并可 `--apply` 到正式表。
  - 状态：正式链路；当前最适合作为编排工具的最终 dry-run/apply 写入入口。

- `research_live_race_fields`
  - 路径：`server/stable/management/commands/research_live_race_fields.py`
  - 职责：只读调研赛中/动态字段。
  - 状态：与历史回填不是同一主线，编排工具第一版不应依赖该命令。

## 正式服务层

- `server/stable/services/race_events.py`
  - `save_data_candidate()` 保存候选。
  - `apply_data_candidate()` 根据模块应用候选。
  - `runners`、`results`、`history_winners` 当前应用逻辑是按模块整体替换，若模块未被人工锁定，会删除现有模块行后 bulk create。
  - 编排工具必须在 apply 前证明候选完整、来源正确、无重复污染；否则历史回填可能覆盖已有好数据。

## 当前运行期候选生成脚本

### 出走表 / 赛果候选

- `runtime/tools/prepare_jra_race_detail_candidates.py`
  - JRA 官方结果页生成 `runners` / `results`。
- `runtime/tools/prepare_nar_race_detail_candidates.py`
  - NAR / keiba.go.jp 官方页面生成 `runners` / `results`。
- `runtime/tools/prepare_hkjc_race_detail_candidates.py`
  - HKJC zh-HK 结果页生成 `runners` / `results`。
- `runtime/tools/prepare_uk_sportinglife_race_detail_candidates.py`
  - Sporting Life 日期结果页与 race detail 生成英国 `runners` / `results`。
- `runtime/tools/prepare_uk_sportinglife_gap_candidates.py`
  - Sporting Life 明确 gap mapping 生成英国缺口 `runners` / `results`。
- `runtime/tools/prepare_france_zeturf_race_detail_candidates.py`
  - ZEturf 日期/场次页匹配法国赛事并生成 `runners` / `results`。
- `runtime/tools/prepare_france_zeturf_gap_candidates.py`
  - ZEturf 明确 gap mapping 生成法国缺口 `runners` / `results`。
- `runtime/tools/prepare_us_hrn_race_detail_candidates.py`
  - HRN track-day 页面生成美国 `runners` / `results`。
- `runtime/tools/prepare_us_equibase_result_candidates.py`
  - Equibase PDF/chart 缺口结果候选，当前属于较新的未归档脚本，后续设计时需单独评估稳定性。

### 历届冠军候选

- `runtime/tools/prepare_jra_history_winner_candidates.py`
  - JRA 官方重赏列表生成历史冠军候选。
- `runtime/tools/prepare_nar_history_winner_candidates.py`
  - NAR / keiba.go.jp 历史页面生成 dirt graded 历史冠军候选。
- `runtime/tools/prepare_hkjc_history_winner_candidates.py`
  - HKJC key-races API / 结果页生成香港历届冠军候选。
- `runtime/tools/prepare_uk_sportinglife_history_winner_candidates.py`
  - Sporting Life previous-winners 链路生成英国历届冠军候选。
- `runtime/tools/prepare_france_wikipedia_history_winner_candidates.py`
  - Wikipedia winners table 加当前年确认冠军生成法国历届冠军候选。
- `runtime/tools/prepare_us_toba_history_winner_candidates.py`
  - TOBA 年度 graded stakes 页面生成美国历届冠军候选。

这些脚本普遍支持 `--events-csv` / `--output-dir` / `--allow-network` / `--limit` / `--sleep-seconds` / `--fail-fast` 等参数，输出 JSONL、review CSV、summary 和 source cache。第一版编排工具应优先调用或封装它们，而不是重写 parser。

## 已存在运行产物

- 基础赛事导入产物：`runtime/race_event_imports/2026/`
  - 包含 JRA、NAR、HKJC、TOBA、BHA、France Galop 2026 基础赛事 CSV、官方来源文件、summary。
- 赛事详情产物：`runtime/race_event_detail_imports/2026/`
  - 包含 JRA/NAR/HKJC/US/UK/France 出走表与赛果候选，以及 2026-07-10 英法覆盖审计。
- 历史冠军产物：`runtime/race_event_history_imports/2026/`
  - 包含 JRA、NAR、HKJC、UK、France、US 的 `history_winners` 候选与 review 文件。
- 全量导出产物：`runtime/race_event_exports/race_event_full_export_20260706/`
  - 可用于后续编排工具做覆盖基线或生产导出对照。
- 外部数据库 proof：`runtime/global_racing_import/proof-20260627/`
  - 与 `External*` 外部缓存相关，不应与第一版 `RaceEvent*` 产品层回填混淆。

## 编排工具需要补齐的缺口

- 统一 plan 文件：明确地区、来源、年份范围、模块、输入 CSV、输出目录、批次大小、是否允许网络、限速配置。
- 统一运行状态：支持批次状态、resume、跳过已完成批次、记录失败原因。
- 统一候选审计：检查 JSONL 可解析、event slug 存在、source URL 非空、slug 无重复、source URL 无一对多污染、候选模块非空、history 年份无重复。
- 统一覆盖审计：对比目标 `RaceEvent` 范围与候选覆盖，区分未来赛事、取消赛事、来源无历史、需人工确认、真实缺口。
- 统一 dry-run 门禁：本地/生产 `import_race_event_detail_candidates --dry-run` 结果必须纳入运行产物。
- 统一 apply 门禁：正式 apply 前必须有人工确认、数据库备份、生产健康检查、外部导入锁检查和运行产物快照。
- 统一运行目录：建议 `runtime/race_event_crawl_runs/<region>-<source>-<module>-<range>-<timestamp>/`。

## 第一轮 grill 已锁定结论

1. 第一版只服务 `RaceEvent*` 产品层，不写入 `ExternalRace*` / `ExternalRaceEntry` / `ExternalRaceResult` / `ExternalHorse*` 外部数据库缓存层。
2. 第一版必须同时覆盖 `runners`、`results`、`history_winners`，不是只做历届冠军。
3. 三个模块的历史深度必须相同；如果某地区/系列追到某个历史起点，则同一目标范围内三类模块都要按同一深度推进。
4. 允许部分候选存在，但不能把不完整批次伪装成完成。缺 `runners`、缺 `results`、缺 `history_winners` 都必须进入 coverage / gap artifact。
5. 目标赛事集合是重点赛事集合，不追所有普通比赛。
6. 第一阶段不包含 `Listed / Listed Race`。
7. 日本范围包含 JRA 中央平地分级赛事、JRA 障碍分级赛事 `JG1/JG2/JG3`、NAR/地方交流重赏、ダートグレード和 `Jpn1/Jpn2/Jpn3`，并需要分开统计。
8. 历史赛事系列必须显式 `series_key` / mapping；模糊名称匹配只能生成待审候选，不得自动写入正式赛事详情数据。
9. 已有正式数据默认进入 diff/review，不允许无条件覆盖；覆盖必须按模块、来源权威性、完整性和人工确认判断。
10. 第一版实现形态为“统一 Django 管理命令编排现有 `runtime/tools` 脚本”，不重写所有 parser。
11. 长周期历史抓取默认手动分批 / 一次性容器运行，不做 Celery Beat 或常驻后台自动调度。
12. 正式 apply 采用“每个地区 + 来源 + 模块组合首批人工确认；后续同组合批次在全绿门禁下可继续执行显式 apply 命令”的门禁，不做无人值守自动 apply。
13. 补充到已公开 `RaceEvent` 的结构化数据可随页面展示；新建或新匹配赛事不自动公开，编排工具不改变可见性。
14. 第一批验收必须覆盖日本、香港、英国、法国、美国五个目标地区，每个地区选择少数核心赛事系列，而不是只用 JRA 小批验收。
15. 官方源优先；允许受控使用高可访问第三方源，但必须显式记录来源权威等级。
16. 日本历史方向为追溯至分级制度建立时；香港、英国、法国、美国的历史起点待第一验收批次后按来源可访问性、赛事制度边界和 series mapping 结果分别锁定。

## 后续设计阶段仍需展开

- 每个地区第一验收小批具体选择哪些赛事系列。
- 每个地区 `official / authoritative_third_party / community_or_reference` 来源权威等级的枚举与默认来源矩阵。
- `series mapping` artifact 的字段、review CSV 格式和 apply 前检查。
- coverage audit 的 blocker / warning / info 分级，以及允许继续 dry-run、禁止 apply 的具体条件。
- 长周期批次 state 文件格式，以及失败后从哪个阶段 resume。
