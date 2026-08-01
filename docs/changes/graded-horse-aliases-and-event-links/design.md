# Design: 重赏导入马术语别名与赛事关联

## 别名补全设计

### 识别目标术语

- 过滤条件：
  - `term_type = TermType.HORSE`
  - `is_active = True`
  - `source_ja` 匹配正则 `\s+\([A-Z]{2,3}\)$`
  - 关联的 `HorseProfile.source_refs` 包含 `theracingapi_horse_id`

### 提取基础名

- 使用正则 `\s+\([A-Z]{2,3}\)$` 去掉尾部国别后缀。
- 例如 `A Bit Of Spirit (IRE)` → `A Bit Of Spirit`。

### 写入别名

- 若基础名不在 `aliases_ja` 中，追加进去。
- 调用 `sync_term_source_aliases(term, SourceLanguage.ENGLISH)` 同步到 `TermAlias`。
- 幂等：重复执行不会重复添加。

### 命令

- `server/stable/management/commands/add_graded_horse_term_aliases.py`
- 参数：`--dry-run`, `--batch-size`

## 赛事关联设计

### 为什么不用外部 ID

生产 DB 中 `RaceResultSourceIdentity` 的 `the_racing_api` 仅 1 条，直接外部 ID 关联覆盖率极低。

### 启发式匹配策略

1. **索引**：预加载所有 `local_date__isnull=False` 的 `RaceEvent`，按 `(local_date, normalized_racecourse)` 索引。
2. **候选筛选**：对每条 `HorseRaceRecord`，用 `race_date` + `racecourse` 找候选赛事。
3. **赛事名评分**：
   - 标准化：小写、去空格、移除 `(group 1)` / `(grade 3)` / `(handicap ...)` / `(gbb race)` 等后缀。
   - 完全相等 → 1.0
   - 互相包含 → 0.85
   - 否则 SequenceMatcher ratio
4. **马名确认**：用 `HorseProfile.english_name/original_name/japanese_name` 去掉国别后缀后，与 `RaceEventRunner.horse_name` 比较。
5. **综合评分**：
   - 马名确认：`score = 0.6 + 0.4 * race_name_score`
   - 未确认：`score = race_name_score * 0.8`
6. **阈值**：默认 0.6，取最高且超过阈值者写入 `HorseRaceRecord.event`。

### 命令

- `server/stable/management/commands/link_graded_horse_race_records.py`
- 参数：`--dry-run`, `--threshold`, `--batch-size`, `--limit`

### 服务函数

- `server/stable/services/horse_race_record_event_matching.py`
  - `RaceEventMatcher`: 索引与评分
  - `match_horse_race_records`: 批量更新封装

## 导入命令增强

修改 `server/stable/management/commands/import_graded_horses_to_profiles.py`：

- 启动时预加载 `RaceEventMatcher`。
- 在 `HorseRaceRecord` bulk_create 前，对每个新记录调用 `find_best_match` 设置 `event`。
- 统计并输出 `records_linked`。

## 测试设计

- 别名命令：
  - 为国别后缀术语添加别名
  - 跳过无后缀术语
  - 幂等性
- 匹配服务：
  - 日期+马场+赛事名+马名确认可匹配
  - 不同马场不匹配
  - 无马名确认时要求较高名称相似度
- 关联命令：
  - dry-run 不写入
  - apply 模式正确写入

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 错链赛事 | 阈值默认较高，宁可少链；马场必须匹配；马名确认加权 |
| 内存占用 | `RaceEventMatcher` 一次加载约 1 万赛事 + 10 万出马，可控 |
| 重复运行 | 已关联记录跳过；别名命令幂等 |
| 性能 | 日期+马场索引 O(1) 候选查找 |
