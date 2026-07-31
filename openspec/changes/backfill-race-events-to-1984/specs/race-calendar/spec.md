## MODIFIED Requirements

### Requirement: 赛事日历筛选与懒加载
系统 SHALL 在赛事日历提供“全部 / 重点”二级 tab、地区单选筛选、年份筛选、赛事名称搜索、当前日期定位和前后方向懒加载。年份和搜索筛选 MUST 与 tab、地区组合使用，并在分页或切换方向时保留。

#### Scenario: 切换重点赛事
- **WHEN** 用户选择“重点”tab
- **THEN** 显式选择早于当前上海自然年的年份时，系统 SHALL 只展示 G1/G2 等级族的前台可见赛事
- **AND** 当前年、未来年或未选择年份时，系统 SHALL 只展示 P0/P1 或人工标记为重点的前台可见赛事
- **AND** 本场景由
  `docs/changes/repair-historical-race-calendar-integrity/spec.md`
  的历史重点合同取代旧的全时期 P0/P1 口径

#### Scenario: 按地区筛选
- **WHEN** 用户选择日本、中国香港、英国、法国或美国
- **THEN** 系统 SHALL 只展示该地区前台可见赛事
- **AND** 全部/重点状态、年份和搜索词 SHALL 保留

#### Scenario: 按年份筛选
- **WHEN** 用户选择 1984–当前年度中的某一年
- **THEN** 系统 SHALL 展示该年度符合其他筛选条件的前台可见赛事
- **AND** 用户 MUST NOT 需要按短时间窗口连续翻页到该年份

#### Scenario: 按赛事名称搜索
- **WHEN** 用户输入赛事原名、中文名、年度别名或稳定系列历史名称
- **THEN** 系统 SHALL 返回匹配的前台可见年度赛事
- **AND** 结果链接 SHALL 进入现有年度赛事详情页而不是新系列页

#### Scenario: 继续加载前后赛事
- **WHEN** 用户向未来或过去方向继续浏览赛事日历
- **THEN** 系统 SHALL 使用日期游标加载下一段赛事
- **AND** 已选择的 tab、地区、年份和搜索词 SHALL 保留

#### Scenario: 无筛选默认定位当前
- **WHEN** 用户未选择年份和搜索词进入赛事日历
- **THEN** 系统 SHALL 默认定位当前日期附近的赛事窗口
