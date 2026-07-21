# race-name-handicap-marker-removal Delta

## ADDED Requirements

### Requirement: 原文括号判定规则

清理判定 SHALL 以原文名的括号形式为准：原文（`RaceEvent.original_name` / `RaceSeries.canonical_name_original` / `TermEntry.source_ja`）中 `handicap/H/让赛/讓賽` 被中英文括号圈住时，中文展示名 SHALL 删除让赛标记；未被括号圈住时，对象 MUST 保留原值并列入 `kept` 桶。唯一例外：展示名为 `京成杯秋季让赛` 的对象 MUST 改为用户逐字锁定的 `京成杯秋季赛`。

#### Scenario: 括号标记者清理

- **WHEN** 处理原文 `THE BAUHINIA SPRINT TROPHY (HANDICAP)`、展示名 `洋紫荆短途锦标(让赛)` 的术语，或原文 `Premier Cup (H)`、展示名 `精英杯 (让赛)` 的赛历对象
- **THEN** 清理结果 MUST 分别为 `洋紫荆短途锦标` 与 `精英杯`

#### Scenario: 非括号标记者保留

- **WHEN** 处理原文 `2yo Handicap → 两岁马让赛`、`ALBATROSS HANDICAP → 信天翁让赛`、`CANMAKE TOKYO → CANMAKE TOKYO让赛`
- **THEN** 三者 MUST 列入 `kept` 桶且写入集合 MUST NOT 包含它们

#### Scenario: 京成杯例外

- **WHEN** 处理展示名为 `京成杯秋季让赛` 的系列或术语（无论原文括号形式）
- **THEN** 清理结果 MUST 精确为 `京成杯秋季赛`，不得为 `京成杯秋季` 或保留 `京成杯秋季让赛`

#### Scenario: 姓名首字母保护

- **WHEN** 处理含 `H. Allen` 的文本
- **THEN** 清理 MUST NOT 删除该 `H` 或任何字母

### Requirement: 删除机制只删不补

清理工具 SHALL 只删除 `让赛 / 讓賽 / 让步赛 / 讓步賽` 四种标记及直接包裹该标记的中英文括号；括号前只有一个分隔空格时 SHALL 一并删除该空格。工具 MUST NOT 补写任何新词、折叠其他空格或删除无关标点。

#### Scenario: 不补词

- **WHEN** 清理 `雅士谷锦标 (让赛)`
- **THEN** 结果 MUST 为 `雅士谷锦标`，不得改写为 `雅士谷大赛` 或任何其他词

#### Scenario: 原工作簿不折叠空格

- **WHEN** 清理含双空格的名称
- **THEN** 双空格 MUST 保持不变

### Requirement: 分桶与 fail-closed 审核

dry-run SHALL 把目标对象分为 `auto_clean`、`kept`、`review`、`locked` 四桶；清理结果为空、无中文字符、含标记残留或同 `racing_region` 清理结果重名的对象 MUST 进入 `review` 桶并保持原值；manual lock 命中的赛历对象 MUST 进入 `locked` 桶并阻断 commit。只有 `auto_clean` 桶可进入写入集合。

#### Scenario: 无中文字符转 review

- **WHEN** 某括号标记术语清理后不含任何中文字符
- **THEN** 该对象 MUST 进入 `review` 桶且不写入

#### Scenario: 同地区重名转 review

- **WHEN** 两个同地区术语清理后得到相同名称
- **THEN** 涉及术语 MUST 进入 `review` 桶且不写入

#### Scenario: manual lock 阻断

- **WHEN** 任一清理目标存在 `manual_lock_flags.chinese_name`
- **THEN** commit MUST 整批拒绝且不写任何对象

### Requirement: 受控写入与审计

写入工具 SHALL 默认 dry-run，只有显式 `--commit` 并提供审核后 artifact 身份、当前数据库备份身份与授权信息才可写入；写入 MUST 在单事务内逐对象比较 before 值（赛历对象含 manual_lock_flags 快照），任一漂移即整批回滚，成功时恰写一条 OperationLog。`original_name`、alias、来源、公开状态、manual lock 与系列关系 MUST NOT 被修改。

#### Scenario: before 漂移回滚

- **WHEN** 事务内任一目标对象当前值与 dry-run before 不一致
- **THEN** 整批 MUST 回滚且不写 OperationLog

#### Scenario: 幂等重复执行

- **WHEN** 对已成功批次重复执行 commit
- **THEN** 工具 MUST 拒绝，不得重复写 OperationLog

#### Scenario: 写后校验

- **WHEN** commit 完成后运行独立校验
- **THEN** 全部写入对象的值 MUST 等于 dry-run after，写入对象 MUST 不含四种标记，`kept` 与 `review` 桶对象 MUST 与 before 完全一致
