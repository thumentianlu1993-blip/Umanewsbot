# 马匹资料页规格

## Purpose
为公开站点和业务后台提供马匹资料页、审核发布、血统展示、参赛履历、新闻关联、匿名关注和后代新闻订阅能力。马匹资料以稳定 `HorseProfile.id` 作为公开 URL 标识，默认先进入后台草稿，只有管理员审核发布后才进入前台。
## Requirements
### Requirement: P0 马必须生成后台草稿资料
系统 SHALL 从正式术语库中 active 且具备中文译名的 `TermEntry(term_type=horse)` 幂等生成 `HorseProfile`。每个 `HorseProfile` MUST 绑定一个主 horse `TermEntry`，并默认处于后台草稿状态，不得自动前台公开。

#### Scenario: 批量生成 P0 马草稿
- **WHEN** 管理员执行 P0 马资料生成命令
- **THEN** 系统 SHALL 为尚无资料页的 active horse `TermEntry` 创建 `HorseProfile`
- **AND** 新建资料 SHALL 处于 `draft` 状态
- **AND** 重复执行 SHALL 不创建重复 `HorseProfile`

#### Scenario: 展示字段优先使用产品层资料
- **WHEN** `HorseProfile` 已保存人工维护的展示中文名、原文名、英文名或日文名
- **THEN** 前台和后台 SHALL 优先展示 `HorseProfile` 字段
- **AND** 仅在 `HorseProfile` 对应字段为空时回退到主 `TermEntry` 或 alias

### Requirement: 马匹资料审核控制公开可见性
系统 SHALL 使用 `draft / ready / published / hidden` 状态管理马匹资料公开流程。只有 `published` 马匹能在公开索引、详情页、新闻 tag 和关注流中出现；未公开马匹公开访问 MUST 返回未找到。

#### Scenario: 未公开马匹详情返回 404
- **WHEN** 用户访问 `draft`、`ready` 或 `hidden` 马匹的 `/horses/<id>/`
- **THEN** 系统 SHALL 返回未找到或等价非公开响应
- **AND** 页面不得暴露该草稿是否存在

#### Scenario: 管理员强制公开空壳资料
- **WHEN** 管理员将资料缺失的 `HorseProfile` 标记为 `published`
- **THEN** 系统 SHALL 允许该马匹前台访问
- **AND** 后台 SHALL 保留资料缺失提示和发布审计记录

#### Scenario: 发布和下线记录审计信息
- **WHEN** 管理员发布或下线马匹资料
- **THEN** 系统 SHALL 记录操作者、操作时间、目标状态和备注

### Requirement: 公开马匹索引和详情页
系统 SHALL 提供公开一级入口 `/horses/` 和详情页 `/horses/<id>/`。公开索引只展示 `published` 马匹，并支持搜索、地区筛选和可解释排序。

#### Scenario: 马匹索引只展示已发布马匹
- **WHEN** 公开索引同时存在已发布和未发布马匹
- **THEN** `/horses/` SHALL 只展示 `published` 马匹
- **AND** 不得展示草稿、待审核或隐藏马匹名称

#### Scenario: 马匹详情使用唯一 ID URL
- **WHEN** 用户访问已发布马匹的 `/horses/<id>/`
- **THEN** 系统 SHALL 展示该马匹资料页
- **AND** URL SHALL 不依赖中文名、英文名或 slug

#### Scenario: 索引支持搜索和地区筛选
- **WHEN** 用户在 `/horses/` 按中文名、原文名、英文名、日文名或别名搜索并选择地区
- **THEN** 系统 SHALL 返回匹配的已发布马匹
- **AND** 筛选和搜索 SHALL 不包含未发布马匹

### Requirement: 马匹详情展示基础资料和二代血统
系统 SHALL 在马匹详情页展示已有基础资料和二代血统。二代血统 MUST 包含父、母、父父、父母、母父、母母；缺失字段不得显示空标签。

#### Scenario: 展示二代血统文本
- **WHEN** 已发布马匹存在父、母、父父、父母、母父、母母文本
- **THEN** 详情页 SHALL 按父系和母系展示六项血统

#### Scenario: 血统关联对象可跳转
- **WHEN** 某个血统字段关联到已发布 `HorseProfile`
- **THEN** 详情页 SHALL 将该血统项渲染为可点击马匹链接
- **AND** 未发布或仅文本血统项 SHALL 显示为普通文本

#### Scenario: 完整二代成功以文本齐全为准
- **WHEN** 父、母、父父、父母、母父、母母六项血统文本均存在
- **THEN** 系统 SHALL 将该马匹血统补全状态统计为完整二代成功
- **AND** 不要求六项都绑定 `TermEntry` 或 `HorseProfile`

### Requirement: 后代查询基于直接父母关联
系统 SHALL 基于 `sire_horse_profile` 和 `dam_horse_profile` 计算后代关系。第一版后代查询 MUST 支持下溯 2 代，并且不得把纯文本血统纳入后代匹配。

#### Scenario: 查询直接子代
- **WHEN** 某马 A 被其它马的 `sire_horse_profile` 或 `dam_horse_profile` 引用
- **THEN** `get_descendant_horses(A, depth=1)` SHALL 返回这些直接子代

#### Scenario: 查询子代和孙代
- **WHEN** 管理员或关注流请求 `get_descendant_horses(A, depth=2)`
- **THEN** 系统 SHALL 返回 A 的直接子代和孙代
- **AND** 同一匹马 SHALL 不重复返回

#### Scenario: 纯文本父母不参与后代订阅
- **WHEN** 某马只在文本字段中记录父母名称但未绑定父母 `HorseProfile`
- **THEN** 系统 SHALL 仅用于页面展示
- **AND** 不得将该文本关系用于关注后代匹配

### Requirement: 马-比赛事实表支持主胜鞍计算
系统 SHALL 使用 `HorseRaceRecord` 记录马匹参加过的比赛事实。主胜鞍 SHALL 基于已录入或已确认的胜利记录按等级排序自动计算，并允许后台人工覆盖。

#### Scenario: 录入参赛履历记录
- **WHEN** 管理员或导入任务为马匹录入比赛记录
- **THEN** 系统 SHALL 保存马匹、比赛文本、年份、等级、马场、距离、场地、名次、来源和可选 `RaceEvent` / `RaceEventResult` 关联

#### Scenario: 最高等级多场胜利都为主胜鞍
- **WHEN** 某马存在多条同一最高等级的胜利 `HorseRaceRecord`
- **THEN** 系统 SHALL 将这些同等级胜利全部标记或计算为主胜鞍

#### Scenario: 无重赏胜利时降级选择
- **WHEN** 某马没有 G1/Jpn1/Grade 1/Group 1、G2、G3 或 Listed 胜利但存在普通胜利、新马赛或未胜利赛胜利
- **THEN** 系统 SHALL 按等级排序选择可用最高等级胜利作为主胜鞍

#### Scenario: MVP 前台不展示完整参赛履历
- **WHEN** 马匹存在多条非主胜鞍 `HorseRaceRecord`
- **THEN** 前台详情 MVP SHALL 不展示完整参赛履历表
- **AND** 后台 SHALL 可查看和维护这些记录

### Requirement: 新闻与马匹关联必须可解释和可纠偏
系统 SHALL 使用 `ArticleHorseLink` 建立新闻与马匹的关系，并区分 `candidate / auto / manual / removed`。前台和关注流 MUST 只消费 `auto` 和 `manual` 关联。

#### Scenario: 标题高可信命中自动公开
- **WHEN** 已发布文章标题命中已发布马匹主术语或 active alias，且匹配非短歧义词
- **THEN** 系统 SHALL 创建 `auto` 状态的 `ArticleHorseLink`
- **AND** 该关联可在前台新闻详情和关注流中使用

#### Scenario: 弱信号进入候选
- **WHEN** 文章仅通过正文单点命中、短英文、歧义英文或低置信实体识别匹配马匹
- **THEN** 系统 SHALL 创建 `candidate` 关联
- **AND** 前台和关注流不得展示该候选关系

#### Scenario: 人工移除不自动恢复
- **WHEN** 管理员手动移除某文章与某马匹的关联
- **THEN** 系统 SHALL 将关系标记为 `removed`
- **AND** 后续自动扫描不得重新公开同一文章-马匹关系，除非管理员重置

### Requirement: 马匹后台审核工作台
系统 SHALL 在业务后台提供马匹审核列表、详情编辑、资料完整度、候选资料 diff、字段级人工锁定、关联新闻/赛事/履历维护和关注统计。

#### Scenario: 审核列表筛选资料状态
- **WHEN** 运营人员进入后台马匹审核列表
- **THEN** 系统 SHALL 支持按地区、审核状态、是否有完整二代血统、是否有主胜鞍、是否有关联新闻、是否被关注和是否公开筛选

#### Scenario: 应用候选资料时保护人工锁定字段
- **WHEN** 运营人员应用外部补全候选
- **THEN** 系统 SHALL 展示 before/after diff、来源、置信度和缺失项
- **AND** 对字段级人工锁定项 SHALL 跳过覆盖并在 diff 中说明

#### Scenario: 候选资料可处理
- **WHEN** 运营人员审核 `HorseProfileDataCandidate`
- **THEN** 系统 SHALL 支持应用、忽略或标记冲突
- **AND** 记录处理人、处理时间和结果摘要

### Requirement: 匿名关注与关注管理
系统 SHALL 允许普通用户通过匿名 `follower_token` 关注马匹、取消关注、管理关注列表，并可选择是否包含下溯 2 代后代相关新闻。

#### Scenario: 首次关注生成匿名 token
- **WHEN** 普通用户首次点击关注马匹
- **THEN** 系统 SHALL 生成签名匿名 `follower_token` 并写入 cookie
- **AND** 创建该 token 对应的 `HorseFollow`
- **AND** 数据库 SHALL 只保存不可反推的 `token_hash`，不得保存明文 token

#### Scenario: 修改后代订阅设置
- **WHEN** 用户已关注某马并调整“同时关注后代相关新闻”
- **THEN** 系统 SHALL 更新 `include_descendants`
- **AND** 第一版 `descendant_depth` SHALL 固定为 2

#### Scenario: 管理关注列表
- **WHEN** 用户打开“管理关注”入口
- **THEN** 系统 SHALL 列出当前浏览器 token 关注的马匹
- **AND** 支持取消关注或调整是否包含后代

#### Scenario: 关注 cookie 不暴露给前端脚本
- **WHEN** 系统设置或更新匿名关注 cookie
- **THEN** cookie SHALL 使用 `HttpOnly` 和 `SameSite=Lax`
- **AND** 在 HTTPS 安全 cookie 配置开启时 SHALL 使用 `Secure`
- **AND** 页面 HTML、日志和 artifact SHALL 不输出明文 token

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

