# Spec: 重赏导入马术语别名与赛事关联

## 背景

已完成 6,054 匹多地区重赏赛马的导入，并在前端 `/horses/` 可浏览、可按地区筛选。当前还有两个体验缺口：

1. **术语别名缺失**：3,518 匹马的 `TermEntry.source_ja` 因同名冲突采用了 `基础名 (国别)` 形式（如 `A Bit Of Spirit (IRE)`）。文章正文通常只写 `A Bit Of Spirit`，导致自动链接命中率下降。
2. **参赛履历未关联赛事**：51,698 条 `HorseRaceRecord.event` 为空，详情页只能显示文字履历，无法跳转到对应 `RaceEvent` 详情页。

## 目标

- 为所有带国别后缀的重赏导入马 `TermEntry` 添加基础英文名别名，使文章自动链接能命中。
- 通过启发式匹配将 `HorseRaceRecord` 关联到已有 `RaceEvent`。
- 保证后续重新导入时新创建的 `HorseRaceRecord` 也能自动尝试关联赛事。

## 范围

### 在范围内

- 批量为 3,518 个冲突马术语添加基础名别名。
- 批量启发式关联 51,698 条 `HorseRaceRecord`。
- 修改导入命令，使其在创建记录时同步尝试关联。
- 两个 management command 及对应服务函数。
- 自动化测试覆盖核心匹配逻辑。

### 不在范围内

- 修改文章自动链接算法本身。
- 补充 `RaceResultSourceIdentity` 外部 ID 数据。
- 前端模板改动（模板已支持 `event` 渲染）。
- 为其他数据源（非 `theracingapi`）的履历做关联。

## 验收标准

1. 别名命令运行后，`TermEntry.aliases_ja` 包含基础名且对应 `TermAlias` 存在。
2. 关联命令 dry-run 能输出匹配统计。
3. 关联命令实际运行后，`HorseRaceRecord.event` 非空数量显著增长。
4. 新测试全部通过。
5. 生产运行两个命令后复查计数符合预期。

## 关键数据

- 3,518 个冲突术语待补别名。
- 51,698 条 `theracingapi` `HorseRaceRecord` 待关联。
- 9,828 条 `RaceEvent` 有 `local_date`。
- 100,320 条 `RaceEventRunner` 覆盖 9,387 场赛事。
- `RaceResultSourceIdentity` 中 `the_racing_api` 仅 1 条，无法直接外部 ID 关联。
