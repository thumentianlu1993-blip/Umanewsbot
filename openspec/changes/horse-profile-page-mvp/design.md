## Context

当前站点已经形成新闻流、公开文章详情页、赛事日历和年度赛事详情页。正式术语库 `TermEntry` 已支持 `horse` 类型和多语言 alias；外部数据层已有 `ExternalHorse`、`ExternalHorseAlias`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorseHistory` 等导入缓存；赛事产品层已有 `RaceEvent`、`RaceEventRunner`、`RaceEventResult`、`ArticleRaceLink` 和候选资料应用模式。

马匹资料页需要建立新的产品层对象，而不是直接公开 `TermEntry` 或 `ExternalHorse`。`TermEntry` 是翻译和术语概念层，`ExternalHorse` 是来源缓存层；公开站点需要可审核、可补全、可下线、可关联新闻和赛事的 `HorseProfile`。本轮同时引入普通用户匿名关注能力，并把关注结果接入首页“我的关注”模块。

## Goals / Non-Goals

**Goals:**

- 为正式术语库中的 P0 马批量生成后台草稿马匹资料，并通过审核状态控制公开。
- 提供公开马匹索引、马匹详情页和新闻详情页马匹 tag 入口。
- 支持二代血统展示、完整二代补全统计和字段级人工锁定。
- 用 `HorseRaceRecord` 建立马-比赛事实表，为未来完整参赛履历预留；MVP 前台只展示主胜鞍和相关赛事。
- 用 `ArticleHorseLink` 建立可解释、可纠偏的新闻-马匹关联。
- 用匿名 `follower_token + cookie` 支持普通用户关注、取消关注、管理关注和首页关注新闻聚合，后端仅保存 token hash。
- 为所有地区 P0 马提供外部资料补全 dry-run、候选 diff、未补全原因报告和受控 commit 路径。

**Non-Goals:**

- 不引入注册登录、手机号、邮箱或第三方账号体系。
- 不在本轮实现复杂推送通知；仅记录关注关系和关注流查询基础。
- 不在前台展示完整参赛履历表。
- 不做三代/五代血统图、血统图谱可视化、近交计算或种牡马/繁殖牝马统计。
- 不要求上线时所有 P0 马都有完整二代血统。
- 不允许外部补全实现完成后自动写生产资料；必须先 dry-run 报告，经用户确认后 commit。

## Decisions

### 1. 使用 `HorseProfile` 作为产品层主对象

`HorseProfile` 必须绑定一个主 `TermEntry(term_type=horse)`。批量生成时从 active horse 术语创建一对一草稿，默认 `draft` 且不前台公开。公开 URL 使用 `/horses/<id>/`，不使用 slug，避免中文名、英文名、译名或 alias 变化导致链接漂移。

替代方案是直接公开 `TermEntry` 或用 slug URL。直接公开术语会把翻译概念层和产品展示层绑死；slug URL 更利于 SEO，但本项目当前更需要稳定和可维护，因此选择 ID URL。

实现时应复用当前 `RaceEvent` 产品层模式：模型枚举放在 `server/stable/models.py`，公开可见性提供 `is_public` / `public_path` 等稳定属性；后台审核、候选资料、关联新闻和操作日志沿用 `RaceEventDataCandidate`、`ArticleRaceLink`、`stable.services.race_events` 与 `OperationLog` 的结构，而不是新建一套并行后台框架。

### 2. 审核状态与公开可见性分离

马匹资料状态使用 `draft / ready / published / hidden`。只有 `published` 可在 `/horses/`、`/horses/<id>/`、新闻详情 tag 和关注流中公开出现；未公开详情返回 `404`。系统提供资料完整度和缺失项提示，但不做硬性发布阻断，即使空壳也允许管理员强制发布。

这个决策保留运营自由度，同时避免未审核草稿和补全候选被搜索引擎或普通用户看到。

### 3. 二代血统采用混合字段模型

`HorseProfile` 直接保存父、母、父父、父母、母父、母母六组展示字段。每组支持文本、可选 `TermEntry`、可选 `HorseProfile` 关联。后代订阅只依赖直接父母 `sire_horse_profile` / `dam_horse_profile` 递归 2 层；纯文本血统只展示，不参与子代/孙代匹配。

替代方案是第一版就建血统边表。边表更适合复杂血统图，但会抬高 MVP 复杂度；本轮以页面展示和二代关注范围为主，因此保留简单字段，未来可迁移到图谱表。

### 4. 用 `HorseRaceRecord` 承载马-比赛事实

不单独创建只记录胜利的 `HorseMajorWin`。`HorseRaceRecord` 记录马参加过的一场比赛，支持可选关联 `RaceEvent`、可选关联 `RaceEventResult`，并保留比赛名、年份、等级、马场、距离、场地、名次、来源和原始 payload 快照。主胜鞍从 `HorseRaceRecord` 中的胜利记录按等级 ranking 计算并可人工覆盖 `is_major_win` 和排序。

这样第一版能满足主胜鞍展示，又不会在未来做完整参赛履历时推翻模型。

### 5. 关联表区分事实和松散关系

`ArticleHorseLink` 记录新闻-马匹关联，状态沿用赛事关联模式：`candidate / auto / manual / removed`。前台和关注流只消费 `auto/manual`；低置信正文命中、短英文、歧义英文进入候选；标题高可信命中可自动公开；人工移除后自动任务不得恢复。

`HorseRaceLink` 记录马匹与赛事页的松散展示关系，例如主胜鞍赛事、相关新闻涉及赛事、人工相关赛事。参赛事实仍以 `HorseRaceRecord` 为准。

### 6. 匿名关注优先于完整用户体系

普通用户第一次关注时，系统生成匿名 `follower_token` 并写入 cookie。`HorseFollow` 绑定 `token_hash`，可选绑定 `AUTH_USER_MODEL` 以便未来升级。用户可关注/取消关注、调整是否包含后代；后代范围固定下溯 2 代。换浏览器或清 cookie 后关注丢失，这是 MVP 可接受边界。

这个方案能让普通用户立即使用“我的关注”模块，同时避免为一个 MVP 强行建设账号体系。

`follower_token` 必须按匿名身份凭据处理：cookie 使用签名随机 token，设置 `HttpOnly`、`SameSite=Lax`，并随站点 HTTPS 配置使用 `Secure`；数据库保存不可反推的 `token_hash`，不保存明文 token，不在日志、artifact 或前台 HTML 中输出 token。关注相关 POST 继续使用 Django CSRF 保护，服务端从 cookie 解析 token，不依赖前端脚本读取 token。

### 7. 补全流程先候选和报告，后人工确认写入

全地区 P0 马都必须有补全尝试路径，但成功标准只把六项二代血统文本齐全视为 `complete_pedigree_2gen`。其它状态包括 `partial_pedigree`、`profile_only`、`unmatched`、`ambiguous`、`source_unavailable`、`rate_limited`、`manual_lock_skipped`。

外部补全必须支持 dry-run、limit、请求间隔、缓存、source evidence 和 diff artifact。唯一高可信命中可写草稿字段；歧义和冲突进入 `HorseProfileDataCandidate`。人工锁定字段不得自动覆盖。

commit 阶段不得直接重新抓取并写库，必须读取同一批次已审核 dry-run artifact，并要求显式确认参数，例如 `--commit --artifact <path> --confirm-reviewed-artifact`。commit 只能写入 artifact 覆盖的 `HorseProfile`、`HorseProfileDataCandidate` 和 `HorseRaceRecord` 字段；如果 artifact 缺少 batch id、生成时间、source 摘要、before/after diff 或审核确认标记，命令必须拒绝写入。

### 8. 分地区 adapter 与 source 优先级

日本优先调研 netkeiba / JBIS，并将 `new-village/KeibaScraper` 作为参考实现或可选依赖候选；正式引入依赖前必须评估许可、维护状态、字段覆盖、限速和与现有代码风格的耦合风险。香港优先 HKJC official；英国使用 Sporting Life / Racing Post 候选；法国使用 Geny / France Galop 候选；美国使用 HRN / Equibase 候选。

所有地区执行时按地区分批，不并发真实外部请求，不在新闻处理同步链路中访问外部站点。

## Risks / Trade-offs

- [Risk] 全地区 P0 补全请求量大，可能触发来源限流或封禁 → [Mitigation] 每个 adapter 必须支持 dry-run、limit、请求间隔、缓存、单来源互斥和失败原因统计；生产 commit 必须由用户确认。
- [Risk] 文本马名与 `HorseProfile` 匹配错误会污染主胜鞍、关注流和血统 → [Mitigation] 高置信唯一命中才自动绑定外键；歧义进入候选；前台只消费已发布 profile 和 `auto/manual` 关联。
- [Risk] 完整二代血统成功率可能低于预期 → [Mitigation] 报告完整二代成功率、部分补全率、未补全占比和具体原因；页面允许缺字段展示。
- [Risk] 匿名关注跨设备不可用 → [Mitigation] 明确为 MVP 边界；模型保留可选 user 字段，为后续账号绑定预留。
- [Risk] 后台审核功能范围较大 → [Mitigation] 复用赛事候选资料和关联新闻的既有模式，优先实现列表、详情、候选 diff、字段锁定、发布/下线和核心关联管理。

## Migration Plan

1. 新增模型、枚举、索引和迁移，保证迁移后不会自动公开任何马匹。
2. 新增批量生成命令，只创建 `draft` 马匹资料，重复执行幂等；批量生成不放进 schema migration，避免迁移时自动写业务草稿。
3. 新增后台审核工作台和公开页面路由，未 `published` 详情返回 `404`。
4. 新增外部补全 dry-run 命令与报告 artifact；先本地验证，再由用户确认后执行 commit。
5. 新增文章关联扫描和关注流查询，避免在请求路径内发起外部网络请求。
6. 部署前执行 Django check、focused tests、完整 stable tests、OpenSpec validate、git diff check；如进入生产 commit 补全数据，需先备份并按地区分批执行。

回滚策略：代码异常可回滚到部署前 git ref 并重建服务；新增数据均默认草稿或候选，公开影响可通过将 `HorseProfile.review_status` 改回 `hidden/draft` 或关闭公开导航入口缓解；外部补全写入必须有 dry-run diff 和 commit artifact，可按 before 值恢复字段。生产部署或数据 commit 前必须记录生产 `HEAD`、迁移状态、`.env` 相关开关、容器状态、外部导入锁、数据库备份和 `/healthz/`。

## Open Questions

- 日本 netkeiba adapter 是否最终引入 `KeibaScraper` 依赖，还是仅参考其解析策略，需要实现阶段完成许可、维护和小样本字段覆盖评估。
- 各地区完整二代血统的真实成功率需要 dry-run 报告确认；本 change 不承诺上线时达到固定覆盖率。
