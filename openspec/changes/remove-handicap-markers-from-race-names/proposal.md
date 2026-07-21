# 赛事展示名与术语库去让赛标记（原文括号规则）

## Why

用户已锁定赛事中文展示名的让赛处理规则（2026-07-21 修订）：**以原文名的括号形式为准**——原文中 `handicap/让赛` 被括号圈住时，视为赛事的补充说明，中文展示名删除该标记；未被括号圈住时，视为赛事名组成部分，保留。唯一例外是"京成杯"：按用户此前逐字锁定，凡 `京成杯秋季让赛` 一律改为 `京成杯秋季赛`（与已上线的系列 6125、Event 96 及 16 场历史赛事保持一致）。

2026-07-21 五区历史赛事中文名导入发布后，生产仍有两类与该规则冲突的展示面：

1. **赛事日历对象**：`9` 个 2026 香港赛历 `RaceEvent`（原文如 `Premier Cup (H)`，括号为补充说明）与 `10` 个 `RaceSeries`（香港 `175-193` 段原文带 `(HANDICAP)`、日本 `285` 为京成杯例外）的 `chinese_name` 含让赛字样，目前正在公开赛事日历前台展示。
2. **术语库**：active `race` 术语中 `149` 条的原文带括号 handicap 标记、`target_zh` 相应带让赛字样（香港 135、英国 14），新闻翻译/改写管线会持续把让赛字样写进新文章中文稿；另有 `2` 条京成杯例外术语（`1972`/`15215`，`京成杯秋季让赛`）与锁定值冲突。

用户 2026-07-21 已明确范围决策：本 change 覆盖赛事日历对象 + 术语库清理；规则按原文括号判定；京成杯为例外按锁定值处理；**不新增术语**（1300 系列术语同步不在本 change）；**不回填历史文章**。原文无括号标记的对象（如 `2yo Handicap → 两岁马让赛`、`ALBATROSS HANDICAP → 信天翁让赛`、`CANMAKE TOKYO → CANMAKE TOKYO让赛`）一律保留，不再设"条件描述型豁免"的独立逻辑。

## What Changes

- 清理 `9` 个 `RaceEvent.chinese_name` 与 `10` 个 `RaceSeries.chinese_name`：原文括号标记者删除标记（`精英杯 (让赛)` → `精英杯`）；日本 RaceSeries `285` 按例外规则 `京成杯秋季让赛` → `京成杯秋季赛`。
- 清理 `149` 条原文带括号 handicap 标记的 active race 术语 `target_zh`（如 `THE BAUHINIA SPRINT TROPHY (HANDICAP) → 洋紫荆短途锦标(让赛)` 改为 `洋紫荆短途锦标`）；`2` 条京成杯例外术语按锁定值改为 `京成杯秋季赛`。
- 判定函数：`should_clean(original, display_name)` = 原文含括号 handicap/让赛 标记，或展示名命中京成杯锁定例外；其余对象全部保留并列入 `kept` 桶。
- 删除机制只删不补：仅删除四种中文标记及直接包裹该标记的中英文括号，括号前只有一个分隔空格时一并删除该空格；不补写"锦标""大赛"等任何新词。
- 清理结果校验：非空、含中文字符、无标记残留、同 `racing_region` 清理结果不重名；失败转入 `review` 桶，保持原值、只报告。
- 提供 dry-run → 审核 artifact → 显式 `--commit` 的受控写入工具：默认只读，写前数据库备份 + SHA 校验，单事务写入 + 逐对象 before CAS + manual lock 整批阻断，OperationLog 审计，写后独立校验与前台抽检。

## Capabilities

### New Capabilities

- `race-name-handicap-marker-removal`：赛事展示名与 race 术语的去让赛清理（原文括号规则）。输入为生产当前值；输出为 `auto_clean / kept / review / locked` 分桶 dry-run 报告、审核清单与一次受控写入；京成杯按锁定例外处理；review/kept 桶 fail closed 不写入。

### Modified Capabilities

（无；不修改任何现有规格行为、模型、迁移、新闻/发布/QQ 链路或公开开关。）

## Impact

- 受影响数据（仅授权后一次写入）：`9` 个 `RaceEvent.chinese_name`、`10` 个 `RaceSeries.chinese_name`、`151` 条 active race 术语 `target_zh`（精确分母以生产 dry-run 为准；当前只读盘点为 `149` 条括号规则 + `2` 条京成杯例外）。
- 保留面：约 `1550` 条原文无括号标记的 race 术语与任何 `original_name`、alias、来源、公开状态、manual lock、RaceSeries 关系。
- 不受影响：历史文章正文（不回填）、1300 系列术语同步（后续独立任务）。
- 后续文章翻译/改写将使用清理后的术语，不再为这些括号标记赛事产生带让赛的中文稿。
