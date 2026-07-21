# 赛事展示名与术语库去让赛标记设计（原文括号规则）

## 规则（用户 2026-07-21 锁定）

1. **判定以原文括号为准**：原文名（`RaceEvent.original_name` / `RaceSeries.canonical_name_original` / `TermEntry.source_ja`）中 `handicap/H/让赛/讓賽` 被中英文括号圈住 → 补充说明，清理中文展示名中的标记；未被括号圈住 → 赛事名组成部分，保留。
2. **京成杯唯一例外**：展示名为 `京成杯秋季让赛` 的对象（日本 RaceSeries `285`、术语 `1972`/`15215`）一律改为用户逐字锁定的 `京成杯秋季赛`，与已上线的系列 `6125`、Event `96` 和 16 场历史赛事一致。
3. **删除机制只删不补**：仅删除四种中文标记 `让赛 / 讓賽 / 让步赛 / 讓步賽` 及直接包裹该标记的中英文括号；括号前只有一个分隔空格时一并删除该空格。不补写任何新词，不折叠其他空格，不删除无关标点。
4. 不再设"条件描述型豁免"独立逻辑：`2yo Handicap → 两岁马让赛`、`ALBATROSS HANDICAP → 信天翁让赛` 等原文无括号标记的对象一律自然落入 `kept` 桶保留。

## 现状与分母（2026-07-21 生产只读盘点，按新规则重算）

| 桶 | 数量 | 说明 |
|---|---:|---|
| RaceEvent 清理 | 9 | 香港 2026 赛历，原文 `Premier Cup (H)` 等括号形式 |
| RaceSeries 清理 | 10 | 香港 9（原文带 `(HANDICAP)`）+ 日本 `285`（京成杯例外） |
| 术语清理 | 151 | 括号规则 149（香港 135、英国 14）+ 京成杯例外 2 |
| 术语保留 | ~1550 | 原文无括号标记（条件型与专名型均保留） |
| 全库 race 术语原文形式 | bracketed 149 / unbracketed 1523 / none 1898 | 判定输入，dry-run 时重算 |

精确分母以生产 dry-run 输出为准；上表为设计基线，漂移时报告必须明示。

## 清理准入与校验

1. `should_clean(original, display_name)`：原文含括号标记（`(H)`、`(Handicap)`、`(HANDICAP)`、`（讓賽）` 等，大小写不敏感）或展示名命中京成杯锁定例外。
2. auto_clean 准入：清理后非空、含至少一个中文字符、不含任何让赛标记残留、且同一 `racing_region` 内不与其他清理结果重名。
3. 任一准入失败转入 `review` 桶：保持原值、不写入、逐条列入审核清单。
4. manual lock（`manual_lock_flags.chinese_name`）命中的赛历对象进入 `locked` 桶，整批阻断 commit。
5. `original_name`、术语 alias、来源、公开状态、manual lock、RaceSeries 关系一律不修改；不做任何系列合并。

## 数据流

```text
生产只读导出目标对象当前值
  -> 分桶 dry-run（auto_clean / kept / review / locked）
  -> dry-run 报告 + 审核清单（CSV/JSON，含 before/after 逐行）
  -> 用户审核清单
  -> 生产备份（custom-format，独立校验）
  -> 显式 --commit：单事务写入 + 逐对象 before CAS + OperationLog
  -> 写后独立校验：目标值、标记零残留、kept/review 未动
  -> 前台抽检：赛事日历香港区、赛事详情、首页
```

## 写入面

- `RaceEvent.chinese_name`：9 个对象（当前盘点值）。
- `RaceSeries.chinese_name`：10 个对象。
- `TermEntry.target_zh`：151 个对象。

只更新上述三个字段（及 `updated_at`）。

## 安全与幂等

- 默认 dry-run，不连接生产写入；`--commit` 需要显式审核后 artifact SHA、备份 SHA 与授权信息。
- 写入前保存全部目标对象 before 值；事务内逐对象比较 before（赛历对象含 manual_lock_flags 快照），漂移即整批回滚。
- 幂等：同批 OperationLog 已存在时拒绝重复 commit。
- OperationLog 恰一条：`action_type=race_name_handicap_markers_removed`，detail 记录备份 SHA、桶计数与 artifact SHA。
- 回滚：以 before 值为依据的对象级恢复；同时保留数据库备份作为灾难恢复点。

## 与既有任务的关系

- 本规则取代此前"让赛不展示一律删除"的口径（2026-07-20 决策），以 2026-07-21 修订为准；京成杯例外与 2026-07-20 逐字锁定一致。
- 不做 1300 系列术语同步、不做术语候选池变更、不回填已发布文章。

## 测试

- 删除机制单元测试：四种标记、中英文括号、括号前分隔空格、锁定值例外、`H. Allen` 类不误删。
- 判定测试：括号/非括号原文、京成杯例外、无标记原文（Quality 类）落入 kept。
- 分桶测试：清理结果无中文转 review、同地区重名转 review、manual lock 入 locked。
- 写入测试（SQLite + PostgreSQL 16）：before CAS 漂移回滚、manual lock 整批阻断、幂等重复执行、OperationLog 唯一性、kept/review 写后未动。
- dry-run 计数锚点：分桶计数与锁定基线不一致时报告明示差异。
