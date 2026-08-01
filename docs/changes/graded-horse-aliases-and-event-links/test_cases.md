# Test Cases: 重赏导入马术语别名与赛事关联

## 别名命令

### TC-A1: 为国别后缀术语添加基础名别名

**Given**: 一个 `TermEntry`，`source_ja="A Bit Of Spirit (IRE)"`，且关联 `HorseProfile.source_refs` 含 `theracingapi_horse_id`。

**When**: 运行 `add_graded_horse_term_aliases`。

**Then**:
- `TermEntry.aliases_ja` 包含 `"A Bit Of Spirit"`
- 存在 `TermAlias` 记录，`text="A Bit Of Spirit"`，`source_language="en"`，`is_active=True`

### TC-A2: 跳过无国别后缀术语

**Given**: 一个 `TermEntry`，`source_ja="Normal Name"`，且关联 `HorseProfile.source_refs` 含 `theracingapi_horse_id`。

**When**: 运行 `add_graded_horse_term_aliases`。

**Then**: 不存在该 `TermEntry` 的 `TermAlias`。

### TC-A3: 幂等执行

**Given**: 一个 `TermEntry`，`source_ja="Duplicate Base (GB)"`，`aliases_ja=["Duplicate Base"]`，且关联 `HorseProfile.source_refs` 含 `theracingapi_horse_id`。

**When**: 运行 `add_graded_horse_term_aliases`。

**Then**: `aliases_ja` 中 `"Duplicate Base"` 仅出现一次；命令输出包含跳过提示。

## 赛事匹配服务

### TC-M1: 完整条件匹配

**Given**:
- `RaceEvent`，`local_date=2024-06-01`，`racecourse="Ascot"`，`original_name="King George Stakes (Group 1)"`
- `RaceEventRunner`，`horse_name="Horse One"`
- `HorseProfile`，`english_name="Horse One"`
- `HorseRaceRecord`，`race_date=2024-06-01`，`racecourse="Ascot"`，`race_name="King George Stakes"`

**When**: 调用 `RaceEventMatcher.find_best_match(record, profile)`。

**Then**: 返回匹配，对应事件为上述 `RaceEvent`，`horse_name_match=True`。

### TC-M2: 不同马场不匹配

**Given**:
- `RaceEvent`，`local_date=2024-06-01`，`racecourse="Ascot"`
- `HorseRaceRecord`，`race_date=2024-06-01`，`racecourse="Curragh"`

**When**: 调用 `RaceEventMatcher.find_best_match`。

**Then**: 返回 `None`。

### TC-M3: 无马名确认时要求较高名称相似度

**Given**:
- `RaceEvent`，`local_date=2024-06-01`，`racecourse="Ascot"`，`original_name="Totally Different Race"`
- `HorseProfile`，`english_name="Missing Horse"`
- `HorseRaceRecord`，`race_date=2024-06-01`，`racecourse="Ascot"`，`race_name="King George Stakes"`

**When**: 调用 `RaceEventMatcher.find_best_match`。

**Then**: 返回 `None`。

## 关联命令

### TC-L1: Dry-run 不写入

**Given**: 存在一条可匹配的 `HorseRaceRecord`，`event=None`。

**When**: 运行 `link_graded_horse_race_records --dry-run`。

**Then**:
- 命令输出 `matched=1`
- 该记录 `event` 仍为 `None`

### TC-L2: Apply 模式写入

**Given**: 存在一条可匹配的 `HorseRaceRecord`，`event=None`。

**When**: 运行 `link_graded_horse_race_records`（不带 `--dry-run`）。

**Then**: 该记录 `event` 指向匹配的 `RaceEvent`。

## 导入命令回归

### TC-I1: 导入时新记录自动尝试关联赛事

**Given**: 导入命令运行时存在可匹配的 `RaceEvent`。

**When**: 运行 `import_graded_horses_to_profiles` 创建新 `HorseRaceRecord`。

**Then**: 部分新创建的 `HorseRaceRecord.event` 被填充，输出 `records_linked` 计数。

**注**：该用例目前未纳入自动化测试。原因是 `import_graded_horses_to_profiles` 通过 raw SQL 直接查询生产 PostgreSQL 的 `theracingapi` schema，标准内存测试 DB 无法提供该 schema。后续如需覆盖，应通过 mock `_load_horse_profile_batch` / `_load_results_for_horses` 或建立 fixture 数据库实现。本次改动未影响该命令既有行为，仅新增可选的 `event` 填充路径。
