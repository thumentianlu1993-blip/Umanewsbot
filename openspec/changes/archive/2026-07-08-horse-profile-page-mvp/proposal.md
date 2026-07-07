## Why

当前公开站点已经具备新闻流、赛事日历和年度赛事详情页，但缺少以“马匹”为核心的长期资料页。建设马匹资料页可以把新闻、赛事、术语库和外部马匹资料串联起来，让网站从“新闻流 + 赛事页”升级为“新闻流 + 赛事页 + 马匹资料页”的综合中文赛马资讯站。

本轮先围绕正式术语库中的 P0 马实现可审核、可补全、可关注的 MVP：默认生成后台草稿，后台审核后才公开；同时为所有地区 P0 马尝试外部二代血统补全，并用关注模块把用户关心的马及其子孙代相关新闻聚合出来。

## What Changes

- 新增产品层 `HorseProfile`，从正式术语库 `TermEntry(term_type=horse)` 批量生成 P0 马草稿，默认不前台公开。
- 新增马匹审核工作台，支持 `draft / ready / published / hidden` 状态、资料完整度提示、字段级人工锁定、候选资料 diff、一键应用/忽略/冲突处理和发布/下线审计。
- 新增公开马匹索引 `/horses/` 和马匹详情 `/horses/<id>/`，只展示 `published` 马匹；未公开马匹前台返回 `404`。
- 新增二代血统展示，覆盖父、母、父父、父母、母父、母母；完整二代成功以六项文本存在为准，`TermEntry` 或 `HorseProfile` 关联为增强项。
- 新增 `HorseRaceRecord` 作为马-比赛事实表，为未来完整参赛履历预留；MVP 前台只展示主胜鞍和相关赛事，不展示完整履历列表。
- 新增 `ArticleHorseLink`，按 `candidate / auto / manual / removed` 管理新闻-马匹关联；前台和关注流只消费 `auto/manual`，人工移除后不得自动恢复。
- 新闻详情页下方 tag 区展示已发布相关马匹 tag，点击进入对应马匹页。
- 新增匿名 `follower_token + cookie` 的普通用户关注能力，后端仅保存 token hash，支持关注马匹本身、可选包含下溯 2 代后代、取消关注和管理关注列表。
- 首页新增“我的关注”模块或标签页，按当前匿名用户关注范围展示已发布相关新闻，并标明命中的关注马或后代关系。
- 新增全地区 P0 马外部资料补全流程，覆盖日本、香港、英国、法国、美国等地区；必须先 dry-run 输出补全占比、未补全原因和候选 diff，经人工确认后才能分地区/批次 commit。
- 日本补全把 netkeiba 作为关键可信候选源，并将 `new-village/KeibaScraper` 作为参考实现或可选依赖候选；正式引入依赖前需评估许可、维护、字段覆盖和限速风险。
- 不引入注册登录用户体系、不实现复杂推送通知、不展示完整战绩前台、不做三代/五代血统图、不要求所有 P0 马在上线时补齐完整二代血统。

## Capabilities

### New Capabilities
- `horse-profile-pages`: 马匹产品页、后台审核、二代血统、马-比赛事实、新闻/赛事关联、匿名关注和公开索引。
- `horse-profile-data-completion`: 面向所有地区 P0 马的外部资料补全、候选资料审核、dry-run/commit 门禁、完整二代统计和未补全原因报告。

### Modified Capabilities
- `public-home-info-feed`: 首页新增“我的关注”模块或标签页，文章详情页新增已发布相关马匹 tag 入口。

## Impact

- 数据模型与迁移：新增 `HorseProfile`、`HorseProfileDataCandidate`、`HorseRaceRecord`、`ArticleHorseLink`、`HorseRaceLink`、`HorseFollow` 及必要枚举、索引、约束和审计字段。
- 服务层：新增马匹资料生成、血统补全、候选 diff、主胜鞍计算、后代查询、新闻-马匹关联扫描、关注流查询和外部 source adapter。
- 外部集成：复用现有 `ExternalHorse` / `ExternalHorseAlias` / 外部 importer 经验，并新增或扩展 netkeiba、HKJC、Sporting Life / Racing Post、Geny / France Galop、HRN / Equibase 的低频补全路径。
- 前台：新增 `/horses/`、`/horses/<id>/`、首页关注模块、新闻详情页马匹 tag 和公开站点样式。
- 后台：新增马匹审核列表、详情编辑、候选资料应用、关联新闻/赛事/履历管理、关注统计和补全报告查看。
- 管理命令与任务：新增 P0 批量生成、全地区补全 dry-run/commit、历史文章马匹关联扫描和补全报告 artifact 输出。
- 文档与运维：补充当前状态、决策、运行手册、数据源补全边界、dry-run/commit 门禁和后续生产执行步骤。
