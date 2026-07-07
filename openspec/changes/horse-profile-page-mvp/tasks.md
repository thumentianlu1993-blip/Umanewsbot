## 0. Pre-declared hypotheses

- [x] 0.1 (operations) PASS：公开 `/horses/`、`/horses/<id>/`、首页关注模块和新闻详情 tag 请求只访问本地数据库，测试中不得触发外部网络；BLOCKER：任一公开请求路径访问 netkeiba、HKJC、Sporting Life、Racing Post、Geny、France Galop、HRN 或 Equibase。
- [x] 0.2 (operations) PASS：外部补全 dry-run 对 `HorseProfile`、`HorseRaceRecord`、`HorseProfileDataCandidate` 和公开状态写入数均为 0；BLOCKER：dry-run 修改主表或公开可见性。
- [x] 0.3 (operations) PASS：补全 commit 必须读取已审核 artifact 且只写 artifact 覆盖范围；BLOCKER：允许无 artifact、无确认参数或重新抓取后直接写库。
- [x] 0.4 (operations) PASS：完整二代成功率统计只把父、母、父父、父母、母父、母母六项文本齐全计为成功；BLOCKER：任一缺项被计为 `complete_pedigree_2gen`。
- [x] 0.5 (operations) PASS：公开索引、关注流和后台列表均分页并使用 `select_related` / `prefetch_related` / 索引约束控制查询；BLOCKER：无分页全表渲染或明显 N+1。

## 1. 数据模型与迁移

- [x] 1.1 (application) 新增马匹页相关枚举，覆盖审核状态、资料完整度、候选模块、候选状态、新闻关联状态、比赛关系类型、关注范围和补全结果原因。
- [x] 1.2 (application) 新增 `HorseProfile` 模型，绑定主 `TermEntry(term_type=horse)`，保存展示名、基础资料、二代血统文本/term/profile 关联、审核状态、公开审计、字段级人工锁定和来源引用；提供 `is_public` / `public_path` 并保证主 term 一对一唯一。
- [x] 1.3 (application) 新增 `HorseProfileDataCandidate` 模型，支持 `profile/pedigree/race_record/aliases` 模块、before/after diff、来源、置信度、状态、应用/忽略/冲突审计和错误信息。
- [x] 1.4 (application) 新增 `HorseRaceRecord` 模型，保存马-比赛事实、可选 `RaceEvent` / `RaceEventResult` 关联、比赛快照字段、名次/状态、等级排序、主胜鞍标记、排序和来源引用。
- [x] 1.5 (application) 新增 `ArticleHorseLink`、`HorseRaceLink` 和 `HorseFollow` 模型，支持候选/自动/人工/移除状态、匿名 `token_hash`、后代订阅和必要唯一约束；不得在数据库、日志或 artifact 中保存明文 `follower_token`。
- [x] 1.6 (application) 生成并检查 Django migration，确保迁移后不会自动公开任何马匹资料、不会在 migration 中批量生成 P0 草稿，并补齐公开列表、关注流、关联扫描和后台筛选所需索引。

## 2. 核心领域服务

- [x] 2.1 (integration) 新增 `stable.services.horse_profiles` 或等价服务，提供 P0 术语批量生成 `HorseProfile`、展示字段初始化、资料完整度计算和审核状态转换。
- [x] 2.2 (integration) 实现二代血统字段读写、完整二代判断和 `get_descendant_horses(horse_profile, depth=2)`，确保纯文本血统不参与后代查询。
- [x] 2.3 (integration) 实现 `HorseRaceRecord` 等级 ranking 与主胜鞍计算，支持最高等级多场胜利、无重赏降级、新马/未胜利和无胜利场景。
- [x] 2.4 (integration) 实现 `ArticleHorseLink` 自动扫描服务，按标题高可信、正文弱信号、短英文/歧义英文、人工移除保护生成 `auto/candidate` 关联。
- [x] 2.5 (integration) 实现关注服务，支持签名匿名 token 创建、token hash 查询、关注/取消关注、后代订阅更新、关注列表和关注流文章查询；cookie 使用 `HttpOnly`、`SameSite=Lax`、随 HTTPS 配置启用 `Secure`，关注 POST 保持 CSRF 保护。
- [x] 2.6 (integration) 实现候选资料 diff 和应用服务，按模块应用 `HorseProfileDataCandidate`，跳过字段级人工锁定并记录处理结果；复用 `stable.services.race_events` 的候选 diff、应用、移除保护和 `OperationLog` 模式。

## 3. 外部资料补全

- [x] 3.1 (integration) 设计外部补全 adapter 接口，统一输出基础资料、二代血统、别名、参赛履历候选、source evidence、请求摘要和失败原因。
- [x] 3.2 (integration) 实现或接入日本 netkeiba/JBIS 补全调研路径，并评估 `new-village/KeibaScraper` 的许可、维护状态、字段覆盖、限速风险和是否作为依赖引入。
- [x] 3.3 (integration) 实现香港 HKJC official 补全路径，复用现有 HKJC parser 能力并补齐二代血统候选输出。
- [x] 3.4 (integration) 实现英国 Sporting Life / Racing Post 候选补全路径，支持低频样本、字段覆盖报告和失败分类。
- [x] 3.5 (integration) 实现法国 Geny / France Galop 候选补全路径，保留 429/限流处理、低频请求和失败分类。
- [x] 3.6 (integration) 实现美国 HRN / Equibase 候选补全路径，保守输出可用字段和不可用原因。
- [x] 3.7 (application) 新增全地区 P0 补全管理命令，支持 dry-run、commit、地区过滤、limit、请求间隔、缓存目录、artifact 输出和已审核 artifact 写入；commit 必须要求 `--artifact` 与显式确认参数，拒绝无 artifact 或重新抓取后直接写库。
- [x] 3.8 (integration) 输出补全报告，包含全局/按地区完整二代成功率、未补全占比、逐马失败原因、样例列表、source URL 和候选 diff。

## 4. 后台审核工作台

- [x] 4.1 (application) 新增马匹审核列表路由、视图、表单和模板，支持按地区、审核状态、完整二代、主胜鞍、相关新闻、关注和公开状态筛选。
- [x] 4.2 (application) 新增马匹审核详情页，支持基础资料、展示名、别名、二代血统、字段锁定、审核状态、发布/下线备注和预览。
- [x] 4.3 (application) 新增候选资料 diff 面板，支持按模块应用、忽略、标记冲突，并显示人工锁定跳过字段。
- [x] 4.4 (application) 新增参赛履历和主胜鞍维护 UI，支持手动添加/编辑 `HorseRaceRecord`、关联 `RaceEvent`、调整主胜鞍和排序。
- [x] 4.5 (application) 新增新闻关联管理 UI，展示 `ArticleHorseLink` 的候选、自动、人工和移除状态，支持确认、手动添加、移除和重置。
- [x] 4.6 (application) 新增相关赛事和关注统计 UI，展示 `HorseRaceLink`、关注数量、后代订阅数量和匿名关注摘要。
- [x] 4.7 (application) 将马匹审核入口接入 `stable/console/base.html` 导航，并确保所有后台 POST 使用现有登录态、权限和 CSRF 模式。

## 5. 公开页面与关注体验

- [x] 5.1 (application) 新增公开 `/horses/` 索引路由、视图和模板，只展示 `published` 马匹，支持搜索、地区筛选、默认排序和分页，并避免别名搜索造成未发布马匹泄露。
- [x] 5.2 (application) 新增公开 `/horses/<id>/` 详情路由、视图和模板，展示基础资料、二代血统、主胜鞍、相关新闻、相关赛事和关注按钮；使用 `select_related` / `prefetch_related` 避免 N+1。
- [x] 5.3 (application) 在公开站点导航新增“马匹”一级入口，并调整公开样式以适配桌面和移动端马匹页面。
- [x] 5.4 (application) 在新闻详情页 tag 区展示已发布相关马匹 tag，候选/移除关联和未公开马匹不得展示。
- [x] 5.5 (application) 在首页新增“我的关注”模块或标签页，按匿名 token 展示关注马及子孙代相关新闻，并标明命中关系。
- [x] 5.6 (application) 新增关注/取消关注/管理关注列表的前台交互，支持调整是否包含后代并保持匿名 cookie。

## 6. 自动任务与历史回填

- [x] 6.1 (application) 将文章发布或重校验后的马匹关联扫描接入任务编排，避免在公开请求路径中扫描全文或请求外部站点。
- [x] 6.2 (application) 新增历史已发布文章马匹关联扫描管理命令，支持 dry-run、commit、limit、文章范围和人工移除保护。
- [x] 6.3 (application) 新增后台“重新扫描马匹关联”入口，用于单篇文章或单匹马补扫。
- [x] 6.4 (operations) 更新 `.env.example` 与设置项，记录外部补全开关、请求间隔、批次上限、缓存目录和默认禁用真实网络写入的策略。
- [x] 6.5 (application) 为异步扫描、批量生成和补全任务写入 `TaskExecutionLog` 或等价运行日志，失败时在后台或 artifact 中可见。

## 7. 测试与验收

- [x] 7.1 (application) 添加模型和服务测试，覆盖 P0 生成幂等、审核状态公开控制、未公开 404、展示字段 fallback、完整二代判断和后代查询去重。
- [x] 7.2 (application) 添加主胜鞍测试，覆盖多 G1、G1/G2/G3 混合、无重赏降级、新马/未胜利和无胜利场景。
- [x] 7.3 (application) 添加 `ArticleHorseLink` 测试，覆盖标题自动、正文候选、歧义候选、人工移除不恢复、新闻详情 tag 展示和隐藏规则。
- [x] 7.4 (application) 添加关注流测试，覆盖签名匿名 token、数据库只保存 token hash、关注/取消关注、后代订阅、只消费 `auto/manual` 关联、首页关注模块过滤和 CSRF/安全 cookie 属性。
- [x] 7.5 (integration) 添加外部补全 adapter 与报告测试，覆盖 dry-run 不写库、完整二代成功定义、部分补全缺失字段、歧义/不可用/限流原因、人工锁定跳过和 commit artifact 写入。
- [x] 7.6 (application) 添加后台视图测试，覆盖审核列表筛选、详情编辑、候选 diff 应用、字段锁定、发布/下线审计、关联管理和未登录/非 staff 访问保护。
- [x] 7.7 (application) 添加公开页面性能/查询测试或等价断言，覆盖 `/horses/`、`/horses/<id>/`、首页关注模块和新闻详情 tag 不发生明显 N+1。
- [x] 7.8 (application) 运行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 7.9 (application) 运行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput` 或拆分后的等价 focused/full 测试组合。
- [x] 7.10 (operations) 运行 `openspec validate horse-profile-page-mvp --strict`、`openspec validate --all` 和 `git diff --check`。

## 8. 文档与交付记录

- [x] 8.1 (operations) 更新 `docs/current_state.md`，记录马匹页 MVP 当前实现状态、未公开默认策略、补全 dry-run/commit 门禁和剩余风险。
- [x] 8.2 (operations) 更新 `docs/decisions.md`，记录 ID URL、匿名关注、`HorseRaceRecord` 取代单独主胜鞍表、完整二代成功定义和全地区补全策略。
- [x] 8.3 (operations) 更新 `docs/deploy_runbook.md`，记录迁移、P0 草稿生成、全地区补全 dry-run、用户确认后 commit、回滚和验收步骤；生产步骤必须包含 `HEAD`、迁移状态、`.env` 相关开关、容器状态、外部导入锁、数据库备份、`/healthz/`、首页、`/horses/`、样例 `/horses/<id>/` 和 `/admin/horse-profiles/` smoke。
- [x] 8.4 (operations) 如公开产品入口或链路发生变化，更新 `docs/project_overview.md` 和 `docs/project_status.md`。
