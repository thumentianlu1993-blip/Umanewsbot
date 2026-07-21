## ADDED Requirements

### Requirement: 后台必须支持新版 P0 补全专项筛选
系统 SHALL 在马匹后台审核工作台提供新版 P0 补全专项相关筛选和排序。筛选 MUST 帮助运营按 P0 来源、补全批次、完整资料状态、候选状态、资料缺口、履历覆盖、无中文译名和人工锁定状态定位马匹。

#### Scenario: 按 P0 来源筛选
- **WHEN** 运营人员进入后台马匹审核列表
- **THEN** 系统 SHALL 支持按 `term_active_with_zh`、`major_race_participant` 或其它 P0 来源筛选
- **AND** 筛选结果 SHALL 不改变马匹公开状态

#### Scenario: 按完整资料状态筛选
- **WHEN** 运营人员查看 P0 补全专项列表
- **THEN** 系统 SHALL 支持按完整资料、完整二代、仅基础资料、空壳、有待审核候选和有冲突候选筛选

#### Scenario: 显示批次和来源证据
- **WHEN** 马匹存在来自 P0 补全批次的候选、应用记录或 P0 来源
- **THEN** 后台 SHALL 展示来源名称、补全批次、候选状态、P0 来源、source URL 和最近更新时间

### Requirement: 中文名缺失不得阻塞后台补全和人工发布
系统 SHALL 允许暂无中文译名的 P0 马进入资料补全、ready 和人工发布流程。前台与后台展示 MUST 使用外文原名作为回退主名，并清晰提示中文名待补。

#### Scenario: 无中文译名马进入 ready
- **WHEN** P0 马缺少中文译名但完整资料硬字段齐备且审核通过
- **THEN** 后台 SHALL 允许将其标记为 `ready`
- **AND** 资料质量提示 SHALL 显示“中文名待补”

#### Scenario: 无中文译名马人工发布
- **WHEN** 管理员人工发布缺少中文译名但完整资料已审核的 P0 马
- **THEN** 前台 SHALL 使用外文原名展示标题
- **AND** 页面 SHALL 不因中文译名缺失返回 404 或隐藏资料

### Requirement: 发布前必须展示完整资料质量提示
系统 SHALL 在后台发布或标记 ready 前展示完整资料质量提示。提示 MUST 包含 P0 来源、中文名状态、基础事实缺口、二代血统、完整赛事履历、主胜鞍、候选冲突、人工锁定跳过和同步时间。

#### Scenario: 完整资料可进入 ready
- **WHEN** 马匹具备完整资料硬字段且必需模块均已审核通过
- **THEN** 后台 SHALL 将其标记为完整资料或等价提示
- **AND** 运营人员 MAY 将其推进到 `ready` 或人工 `published`

#### Scenario: 空壳资料发布前提示风险
- **WHEN** 运营人员尝试发布空壳或资料明显不足的马匹
- **THEN** 后台 SHALL 展示缺失字段、候选状态和 P0 来源
- **AND** 系统 SHALL 继续允许管理员强制发布并记录审计信息

#### Scenario: 候选冲突发布前可见
- **WHEN** 马匹存在未处理冲突候选或歧义来源
- **THEN** 后台 SHALL 在发布前提示冲突数量和来源
- **AND** 不得把冲突候选自动视为已确认资料

### Requirement: 应用候选必须保留 before/after 和处理结果
系统 SHALL 在后台应用、忽略或标记冲突 P0 补全候选时保留 before/after diff、处理人、处理时间和结果摘要。

#### Scenario: 应用候选记录差异
- **WHEN** 运营人员应用 `HorseProfileDataCandidate`
- **THEN** 系统 SHALL 保存应用前后字段差异、被写入字段、被人工锁定跳过字段和来源证据

#### Scenario: 忽略候选记录原因
- **WHEN** 运营人员忽略候选
- **THEN** 系统 SHALL 记录处理人、处理时间和忽略原因或结果摘要

#### Scenario: 标记冲突不写主表
- **WHEN** 运营人员将候选标记为冲突
- **THEN** 系统 SHALL 保留候选和 raw payload
- **AND** 不得把该候选写入 `HorseProfile` 或 `HorseRaceRecord`

### Requirement: 首批公开验收必须由人工发布触发
系统 SHALL 保持资料补全和资料公开分离。首批每地区完整资料样本 MAY 进入 `ready`，但公开发布 MUST 由管理员人工执行。

#### Scenario: 每地区人工发布样本
- **WHEN** 首批五地区各 10 匹完整资料马完成审核
- **THEN** 运营人员 SHOULD 每地区人工发布 1-2 匹做公开验收
- **AND** 未人工发布的完整资料马 SHALL 不自动进入前台公开列表

#### Scenario: 自动发布能力仅预留
- **WHEN** 系统保存完整资料状态和发布质量信号
- **THEN** 这些信号 MAY 作为未来自动发布门禁输入
- **AND** 本阶段 SHALL NOT 启用未发布马的自动首次公开

### Requirement: 公开马匹详情必须支持浏览完整生涯履历
系统 SHALL 在公开马匹详情页以分页或等价交互展示全部 `HorseRaceRecord`，不得使用固定切片把最近 20 条冒充完整履历。页面 MUST 只读本地数据库，并区分已关联公开赛事与未关联普通比赛。

#### Scenario: 履历超过单页数量
- **WHEN** 已发布马匹有超过 20 条履历
- **THEN** 页面 SHALL 提供后续分页并能访问全部记录
- **AND** 默认按日期倒序，用户 MAY 切换为正序

#### Scenario: 未关联普通比赛展示
- **WHEN** 履历没有关联 `RaceEvent`
- **THEN** 页面 SHALL 展示日期、比赛名、场地、距离和结果状态
- **AND** 不得生成无效赛事详情链接

#### Scenario: 已关联公开赛事展示
- **WHEN** 履历关联的 `RaceEvent` 已公开
- **THEN** 比赛名 SHALL 可链接到赛事详情页
