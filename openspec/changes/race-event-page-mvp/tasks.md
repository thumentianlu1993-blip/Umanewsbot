## 0. Pre-declared hypotheses

- PASS：五个目标地区 japan / hong_kong / united_kingdom / france / united_states 各至少 1 场 P0/P1 年度赛事完成 CSV/人工创建、候选抓取、后台应用、日历展示、详情页展示和新闻关联验收。
- PASS：赛事日历首屏只加载当前日期附近窗口，后续通过前后方向懒加载补充历史/未来赛事，不一次性加载全部前台可见赛事。
- PASS：赛事详情页赛前、赛中、赛后三种状态均能在无完整赛果数据库的前提下展示可用资料；赛中不得展示未确认最终赛果。
- BLOCKER：任一地区样本无法完成后台确认到前台可见闭环，或人工移除的新闻关联被自动任务重新公开。
- BLOCKER：赔率出现在赛事日历，或候选抓取自动覆盖了非白名单人工确认字段。

## 1. 数据模型与迁移

- [x] 1.1 (application) 在 `server/stable/models.py` 新增年度赛事产品层模型：`RaceEvent`、`RaceEventAlias`、`RaceEventRunner`、`RaceEventResult`、`RaceEventHistoryWinner`、`RaceEventDataCandidate`、`ArticleRaceLink`。
- [x] 1.2 (application) 为赛事模型新增 Django migration，并配置必要索引与唯一约束：年度 slug、年份/日期、地区、priority、状态、可见性、文章关联去重。
- [x] 1.3 (application) 在 Django Admin 注册新增模型，提供表级兜底管理入口。
- [x] 1.4 (application) 明确 `RaceEvent` 与现有 `MajorRaceEvent` 的边界：`RaceEvent` 负责前台赛事页/日历，`MajorRaceEvent` 保持生产窗口升频用途；如需复用资料，只通过可选引用或导入转换实现。
- [x] 1.5 (application) 为赛事等级与 surface 增加模型校验：保留原文等级 `grade_text`，保存规范化等级 `normalized_grade`，并将 surface 限定为 `turf`、`dirt`、`jumps`。

## 2. 赛事领域服务

- [x] 2.1 (integration) 新增赛事候选归并服务，支持按基础资料、历史冠军、出马表/闸位、赛果、相关新闻关联保存候选和差异。
- [x] 2.2 (integration) 新增动态字段刷新服务，仅允许赔率、热门度、出走状态和退赛状态自动更新，并记录更新时间和错误。
- [x] 2.3 (integration) 新增文章赛事关联服务，复用 `TermEntry`、`TermAlias`、`NewsArticle.content_category`、`tags_json`、`decision_reason`、日期窗口和 AI/实体信号区分自动展示与候选关联。
- [x] 2.4 (integration) 实现人工移除关联保护，确保自动关联任务不得重新公开已人工移除的文章赛事关联。
- [x] 2.5 (integration) 为候选抓取、候选应用、动态字段刷新和人工纠偏补充可追溯日志，用户操作写 `OperationLog`，批处理/命令写 `TaskExecutionLog` 或候选错误状态。

## 3. 导入与候选抓取

- [x] 3.1 (application) 新增 CSV 种子导入管理命令，导入 P0/P1 年度赛事基础资料、别名、priority、surface、距离、参赛条件和可见性。
- [x] 3.2 (integration) 新增指定网站候选抓取配置与适配器入口，配置放在代码或配置文件中，不建设后台规则 UI。
- [x] 3.3 (integration) 新增候选抓取管理命令，将抓取结果写入 `RaceEventDataCandidate`，不得自动覆盖公开结构化字段。
- [x] 3.4 (integration) 新增只读赛中字段调研命令，记录少量指定网站可用字段、样例、失败原因，不写入公开赛事状态或赛果。
- [x] 3.5 (operations) 提供赛事 CSV 字段模板与样例，覆盖名称、日期、马场、等级、surface、priority、地区、别名和可见性字段。

## 4. 后台赛事工作台

- [x] 4.1 (application) 新增业务后台赛事列表页，支持按年份、地区、priority、状态、可见性、资料完整度筛选。
- [x] 4.2 (application) 新增业务后台赛事详情维护页，支持基础资料、历史冠军、出马表/闸位、赛果、动态字段和可见性编辑。
- [x] 4.3 (application) 新增候选资料对照预览与按模块应用交互，应用时记录来源、抓取时间、应用人和应用时间。
- [x] 4.4 (application) 新增关联新闻管理页或详情区块，支持查看已关联、候选、已人工移除新闻，并支持手动添加/移除关联。

## 5. 公开赛事日历

- [x] 5.1 (application) 新增赛事日历路由、视图和查询服务，默认返回当前日期附近窗口，并使用分页、索引、`select_related`/`prefetch_related` 或等价查询避免无界扫描和 N+1。
- [x] 5.2 (application) 实现“全部 / 重点”二级 tab、地区单选筛选和前后方向懒加载。
- [x] 5.3 (application) 实现移动端日期分组赛事卡，赛前展示名称、马场、时间、等级、surface，赛后展示前 5 名和马身差。
- [x] 5.4 (application) 实现 PC 端高密度赛事表，展示日期、时间、状态、赛事、地区/马场、等级、surface 和赛前/赛后摘要。
- [x] 5.5 (application) 将赛事日历接入公开站导航或首页入口，并确保候选、草稿、隐藏赛事不展示。

## 6. 公开赛事详情页

- [x] 6.1 (application) 新增年度赛事详情路由和视图，URL 使用年份与 slug，并预取出马表、赛果、历史冠军和关联新闻，避免详情页 N+1。
- [x] 6.2 (application) 实现赛前、赛中、赛后 Header：赛前展示赛事身份，赛中展示进行中标识，赛后在赛果确认后展示结果摘要。
- [x] 6.3 (application) 实现详情页概览模块，展示基础资料、出马表/闸位、赔率、热门度、出走状态和历史冠军中已有字段。
- [x] 6.4 (application) 实现赛果模块，赛果存在后展示完整赛果，缺失时隐藏空内容。
- [x] 6.5 (application) 实现新闻模块，按赛前新闻、赛后新闻和相关新闻分组展示。
- [x] 6.6 (application) 在文章详情页展示已确认关联赛事入口。
- [x] 6.7 (application) 确保赛事日历不展示赔率，赔率只作为详情页出马表动态字段展示。

## 7. 文档与运维记录

- [x] 7.1 (operations) 更新 `docs/current_state.md`，记录赛事页 MVP 的当前能力、入口、数据边界和未实现项。
- [x] 7.2 (operations) 更新 `docs/project_status.md`，补充赛事日历和年度赛事页阶段状态。
- [x] 7.3 (operations) 更新 `docs/decisions.md`，记录年度赛事粒度、候选确认、动态字段白名单、赔率展示范围和马匹库延期决策。
- [x] 7.4 (operations) 更新 `docs/project_overview.md`，把赛事日历和年度赛事页补充为新闻流之外的公开内容组织入口。
- [x] 7.5 (operations) 更新导入/候选抓取操作说明或 `docs/deploy_runbook.md`，覆盖 CSV 种子导入、指定网站候选抓取、只读赛中调研和回滚/停用边界。

## 8. 验证

- [x] 8.1 (application) 增加模型与服务测试，覆盖最小公开条件、可见性、状态切换、动态字段更新、人工锁定和关联移除保护。
- [x] 8.2 (integration) 增加 CSV 导入、候选抓取、候选应用和只读赛中调研测试。
- [x] 8.3 (application) 增加公开赛事日历和赛事详情页视图测试，覆盖全部/重点、地区筛选、懒加载、赛前/赛中/赛后展示和赔率隐藏规则。
- [x] 8.4 (application) 增加后台赛事工作台测试，覆盖筛选、编辑、候选应用、关联新闻添加/移除和可见性控制。
- [x] 8.5 (application) 增加查询效率或分页边界测试，覆盖赛事日历首屏、双向加载和详情页关联数据预取。
- [x] 8.6 (application) 在本地执行 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite python manage.py makemigrations --check --dry-run` 和 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`。
- [x] 8.7 (operations) 执行 `openspec validate race-event-page-mvp --strict`、`openspec validate --all` 和 `git diff --check`。
- [x] 8.8 (application) 使用代表性 P0/P1 样本验收五个地区各至少 1 场年度赛事：CSV/人工创建、指定网站候选抓取、后台模块应用、赛事日历可见、详情页可读、新闻自动/手动关联可用。
