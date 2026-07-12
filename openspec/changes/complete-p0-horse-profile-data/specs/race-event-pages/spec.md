## ADDED Requirements

### Requirement: 重点赛事参赛马必须可作为 P0 来源
系统 SHALL 允许结构化赛事、出赛表和赛果数据为新版 P0 马范围提供来源证据。重点赛事参赛证据 MUST 可追溯到赛事、等级、地区、参赛或赛果记录和 source URL。

#### Scenario: 从出赛表产生 P0 来源候选
- **WHEN** 五大地区重点赛事的出赛表被导入或补抓
- **THEN** 每匹出赛马 SHALL 可生成 `major_race_participant` P0 来源候选
- **AND** 候选 SHALL 包含赛事、等级、地区、出赛证据和 source URL

#### Scenario: 从赛果产生 P0 来源候选
- **WHEN** 五大地区重点赛事的赛果被导入或补抓
- **THEN** 每匹赛果马 SHALL 可生成 `major_race_participant` P0 来源候选
- **AND** 候选 SHALL 包含名次或参赛状态、赛事、等级、地区和 source URL

#### Scenario: P0 来源不依赖马名搜索
- **WHEN** 外部马资料搜索命中某匹马
- **AND** 系统没有可追溯的重点赛事参赛或赛果证据
- **THEN** 系统 SHALL NOT 仅凭该搜索命中创建 `major_race_participant` P0 来源

### Requirement: 重点赛事等级集合必须与 P0 马定义一致
系统 SHALL 使用同一重点赛事等级集合驱动 P0 参赛马同步。该集合 MUST 包含 `G1/G2/G3/JG1/JG2/JG3/JPN1/JPN2/JPN3`，并排除 Listed、Open、`LOCAL_GRADE` 和其它等级。

#### Scenario: 指定等级产生 P0 参赛来源
- **WHEN** `RaceEvent.normalized_grade` 属于指定重点赛事等级集合
- **THEN** 该赛事的出赛和赛果马 SHALL 可进入 P0 来源同步

#### Scenario: 非指定等级不产生 P0 参赛来源
- **WHEN** `RaceEvent.normalized_grade` 为 Listed、Open、`LOCAL_GRADE` 或其它等级
- **THEN** 该赛事 SHALL NOT 仅因赛事页存在而产生 P0 参赛来源

### Requirement: 历史与未来重点赛事都必须支持同步
系统 SHALL 支持历史和未来全部已知重点赛事参赛马进入 P0 范围。未来赛事数据进入系统后，P0 来源同步 MUST 能增量处理新增参赛马。

#### Scenario: 历史赛事回填
- **WHEN** 操作者导入或补抓历史重点赛事出赛/赛果
- **THEN** 系统 SHALL 能为历史参赛马生成 P0 来源候选

#### Scenario: 未来赛事增量
- **WHEN** 未来重点赛事出赛表或赛果新增
- **THEN** 系统 SHALL 能增量生成或更新 P0 来源
- **AND** 新增 P0 马 SHALL 可进入资料补全队列
