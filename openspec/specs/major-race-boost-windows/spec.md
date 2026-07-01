# major-race-boost-windows Specification

## Purpose
TBD - created by archiving change increase-multiregion-news-volume. Update Purpose after archive.
## Requirements
### Requirement: 重要赛事维表维护
系统 SHALL 提供后台可维护的重要赛事表，用于按地区、年份和赛事等级定义重要赛事升频窗口。

#### Scenario: 新增重要赛事
- **WHEN** 运营创建一条包含地区、赛事名、年份、赛事等级、比赛日期和启用状态的重要赛事
- **THEN** 系统 SHALL 保存该赛事并用于对应地区的升频判断

#### Scenario: 同年同地区赛事唯一
- **WHEN** 已存在相同赛事名、年份、地区和赛事等级的重要赛事
- **THEN** 系统 SHALL 更新原记录的日期、时间、启用状态或备注，而不是新增重复记录

### Requirement: 重要赛事 CSV 导入
系统 SHALL 支持通过 CSV 批量导入重要赛事，并按赛事名、年份、地区和赛事等级执行 upsert。

#### Scenario: CSV 更新开跑时间
- **WHEN** CSV 中某条赛事与已有赛事的业务唯一键相同但开跑时间不同
- **THEN** 系统 SHALL 更新已有赛事的开跑时间

#### Scenario: CSV 导入新年份赛事
- **WHEN** CSV 中包含同名赛事但年份不同
- **THEN** 系统 SHALL 创建新的年份记录

### Requirement: 重要赛事时间和时区
系统 SHALL 按赛事所属地区的当地日期和当地开跑时间录入赛事，并在内部使用 UTC 判断升频窗口。

#### Scenario: 有开跑时间的赛事窗口
- **WHEN** 某地区当前时间落在已启用赛事开跑前 3 小时到开跑后 1 小时之间
- **THEN** 系统 SHALL 将该地区判定为重要赛事模式

#### Scenario: 无开跑时间的日期级赛事
- **WHEN** 已启用赛事只有地区当地比赛日期而没有开跑时间
- **THEN** 系统 SHALL 使用该地区本地日期级默认窗口进行保守升频，并在后台标记缺少开跑时间

### Requirement: 重叠赛事窗口合并
系统 SHALL 合并同一地区的重叠重要赛事窗口，不因多场赛事重叠而叠加频率或每窗口上限。

#### Scenario: 同地区两场赛事重叠
- **WHEN** 同一地区两条启用赛事的升频窗口互相重叠
- **THEN** 系统 SHALL 对该地区只启用一个 5 分钟窗口节奏，并在后台显示命中的赛事列表

#### Scenario: 不同地区赛事互不影响
- **WHEN** 日本处于重要赛事模式且香港不处于重要赛事模式
- **THEN** 系统 SHALL 只提升日本地区窗口频率，不改变香港地区日常窗口频率
