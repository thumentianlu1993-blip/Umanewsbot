# 首页人工头条与 AI 编辑推荐设计

## 1. 现状数据流

当前公开首页数据流：

```text
NewsArticle
  -> _public_published_articles()
  -> _select_headline_article()
  -> public_news_feed(headline_article)
  -> feed.html
  -> _headline.html
```

`_public_published_articles()` 预取封面、图片、地区、赛事和马匹链接，只接收
`workflow_status=published` 且 `published_to_web_at` 非空的文章，并按网页发布时间倒序。
`_select_headline_article()` 对最新 48 篇候选使用赛事优先级、自动分数、封面和时间排序。

后台日常入口是自建 `/admin/`，不是 Django Admin。`article_editor` 已在右栏展示自动化决策、
`score_total`、AI 翻译和 AI 改写；人工发布/撤稿、候选自动化、图片和术语操作都使用 staff-only POST
入口并写 `OperationLog`。现有首页没有 headline cache，也没有新闻保存后的首页 cache invalidation。

## 2. 方案比较

### 2.1 方案 A：在 `NewsArticle` 增加布尔/状态字段

可能字段：

```text
is_homepage_headline
headline_selected_by
headline_selected_at
headline_recommendation_status/reason
```

优点：

- 首页查询直观；
- 少一个 join；
- Django Admin 容易展示。

缺点：

- “全站唯一头条”是跨文章不变量。普通布尔字段不能阻止两个请求同时把不同文章设为 `True`；
- 即使增加 PostgreSQL 条件唯一约束，也需要先取消旧文章再设置新文章，事务锁顺序和并发冲突分散在多行；
- 当前状态、历史操作和 AI 推荐容易被堆在同一文章上，文章切换后会留下难解释的残余字段；
- 删除文章会同时删除其选择事实，审计只能依赖旁路日志；
- 把字段暴露到 Django Admin 会绕过资格、版本和审计校验；
- AI 推荐与正式人工头条很容易被错误地视为同一状态。

结论：不采用。

### 2.2 方案 B：独立单例选择 + 独立推荐记录

采用两个模型：

1. `HomepageHeadlineSelection`：每个 `slot` 一行的当前人工控制状态；
2. `HomepageHeadlineRecommendation`：有生命周期的推荐快照记录。

优点：

- `slot` 唯一约束从结构上把首页头条控制收敛为一行，选择值本身只有一个 FK；
- 所有写请求锁同一选择行，易于序列化并发；
- `version` 可拒绝陈旧浏览器提交；
- 推荐是独立记录，不会因为生成推荐而修改选择；
- 推荐理由和信号以快照保存，历史状态可追溯；
- 文章删除可用 `SET_NULL` 保留控制/推荐记录，审计仍存在；
- 未来若真的增加其他 slot，可以复用 `slot`，但本版本只允许固定首页主头条。

代价：

- 新增两个表和一个服务层；
- 首页增加一次很小的单例读取；
- 需要处理首次创建单例行的并发。

结论：采用方案 B。

## 3. 数据模型

### 3.1 `HomepageHeadlineSelection`

建议字段：

```text
slot: CharField(max_length=32, unique=True, default="homepage_primary")
article: ForeignKey(NewsArticle, null=True, blank=True, on_delete=SET_NULL)
selected_by: ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
selected_at: DateTimeField(null=True, blank=True)
version: PositiveBigIntegerField(default=0)
created_at / updated_at
```

语义：

- 固定 `slot=homepage_primary`；
- `article is null` 表示没有人工头条；
- `version` 每次设置、替换、取消或失效清除增加 1；
- 模型只存当前控制状态，历史动作写 `OperationLog`。

数据库约束：

- `CheckConstraint(slot="homepage_primary")` 拒绝当前版本未定义的其他 slot；
- PostgreSQL/SQLite 的 `UNIQUE(slot)` 保证同一个 slot 最多一行；
- 一行只有一个 `article_id`，因此结构上不可能出现两个生效人工头条；
- 不增加 NewsArticle 布尔字段或条件唯一约束。

### 3.2 `HomepageHeadlineRecommendation`

建议字段：

```text
slot: CharField(max_length=32, default="homepage_primary")
article: ForeignKey(NewsArticle, null=True, blank=True, on_delete=SET_NULL)
status: active | accepted | superseded | invalidated
reason: TextField
evidence: JSONField
engine_version: CharField(max_length=64)
generated_by: ForeignKey(User, null=True, on_delete=SET_NULL)
accepted_by: ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
accepted_at: DateTimeField(null=True, blank=True)
created_at / updated_at
```

约束与索引：

- `CheckConstraint(slot="homepage_primary")`，当前版本不能借其他 slot 绕过单头条/单推荐边界；
- PostgreSQL 条件唯一约束：
  `UniqueConstraint(fields=("slot",), condition=Q(status="active"), ...)`；
- `(slot, status, -created_at)` 索引支持读取当前推荐和历史；
- 事务中先把旧 active 改为 superseded，再插入新 active，不能依赖插入失败做正常流程；
- 条件唯一约束不能设置 deferred，应用层锁与数据库约束共同防守。

推荐证据至少包括：

- 有序候选文章 ID；
- 候选上限与筛选时间；
- 每个参与排序信号的保存值；
- 选中文章的排序 key；
- 当前人工选择文章 ID（只作上下文，不产生覆盖）；
- `engine_version=homepage-headline-recommendation.v1`。

### 3.3 默认权限

使用 Django 为 `HomepageHeadlineSelection` 自动生成的
`change_homepageheadlineselection` 权限作为统一写权限。推荐生成、接受、人工设置和取消均复用该权限，
避免创建难以理解的多权限组合。模型不注册为可写 Django Admin。

## 4. 服务边界

新增 `server/stable/services/editorial_headlines.py`，视图、信号和公开首页只调用该服务。

建议接口：

```python
is_headline_eligible(article, *, now=None) -> EligibilityResult
headline_candidate_queryset(*, now=None)
get_headline_state(*, now=None) -> HeadlineState
select_automatic_headline(public_queryset, *, now=None) -> NewsArticle | None
resolve_homepage_headline(public_queryset, *, now=None) -> NewsArticle | None
set_manual_headline(article_id, *, user, expected_version) -> SelectionResult
cancel_manual_headline(*, user, expected_version) -> SelectionResult
generate_headline_recommendation(*, user, now=None) -> RecommendationResult
accept_headline_recommendation(
    recommendation_id, *, user, expected_selection_version
) -> SelectionResult
invalidate_headline_state_for_article(article_id, *, reason) -> None
```

`resolve_homepage_headline()` 负责人工优先和安全 fallback：

- 有效时返回人工文章；
- 缺失或无效时调用 `select_automatic_headline()`；
- `select_automatic_headline()` 保留原有 72 小时/7 天/全部窗口、最多 48 篇合格候选和排序元组，
  但用同一 `is_headline_eligible()` 排除未来网页时间或空有效内容；
- 无效选择或失效协调尚未完成时不能让首页 500；只在能确认人工选择无效时回退；
- 不在公开 GET 内写数据库或创建审计。

`set/cancel/generate/accept/invalidate` 是唯一写入入口。视图不得自己 bulk update 模型。

## 5. 唯一性与并发

### 5.1 单例首次创建

所有写操作先取得固定 selection 行：

1. 在内层 savepoint 中 `get_or_create(slot=homepage_primary)`；
2. 首次并发创建时，唯一约束只允许一个成功；
3. 败方捕获 `IntegrityError` 后退出内层 savepoint，再读取已创建行；
4. `select_for_update()` 锁定 selection 行。

不能在已经标记回滚的同一事务块中捕获后继续查询。

### 5.2 人工设置/取消

在 `transaction.atomic()` 中：

1. 锁 selection；
2. 比较 `expected_version`；
3. 锁目标 `NewsArticle` 并重新验证资格；
4. 更新 selection、操作者、时间、`version + 1`；
5. 写同事务 `OperationLog`。

并发请求即使选择两篇不同文章，也必须串行到同一 selection 行。后到请求若来自同一旧页面，因为版本不符
返回 409/表单冲突，不执行“最后写入者静默获胜”。

### 5.3 推荐生成/接受

生成推荐也锁 selection 行，把它当成该 slot 的统一互斥点，然后锁当前 active 推荐。接受推荐按固定顺序：

```text
selection -> recommendation -> article
```

人工设置、取消、推荐生成、推荐接受和失效协调全部遵守同一锁顺序，避免死锁。

数据库条件唯一约束仍是最后防线。真实 PostgreSQL 测试必须用两个连接验证：

- 同时选择不同文章；
- 同时生成推荐；
- 选择与失效协调交错；
- 最终最多一行 selection、一个 active 推荐，且 OperationLog 与最终版本一致。

## 6. 推荐算法

候选范围沿用公开首页的有限读取原则，并锁定如下：

1. `headline_candidate_queryset()` 先用数据库过滤
   `workflow_status=published`、`published_to_web_at` 非空且 `<= now`，并用标题/正文各层“至少一个非空”
   条件排除明显无效行；这个 queryset 是资格的数据库超集，不替代 Python 最终判断；
2. queryset 必须 `select_related("cover_media_asset")`，并把按 `sort_order,id` 排列的 `NewsImage`
   预取到专用 `to_attr`；封面判断只读取这些已加载字段，不调用逐篇 related-manager 查询；
3. 每个时间窗口按网页发布时间倒序分批扫描，每批 48 行、最多扫描 192 行；逐篇调用
   `is_headline_eligible()` 精确复现 `effective_title/effective_summary/effective_body` 的人工字段优先级
   和摘要回退，收集前 48 篇合格候选后停止；
4. 若前 48 个原始行中有不合格文章，继续在 192 行扫描上限内补足；第 49 篇**合格**文章不参与排序；
5. 使用现有 `_headline_sort_key` 等价的共享排序信号选出最大 key；
6. 推荐根据保存信号生成简洁理由，例如“近 72 小时 P0 赛事稿，自动化分数 92，且有封面”，并把完整
   信号快照保存到 evidence。

192 行是显式性能上限。若一个窗口扫描满 192 行仍没有合格候选，则进入下一级时间窗口；全部窗口均无
合格候选时允许没有 headline hero，普通信息流仍正常显示，不返回 500。该极端状态写入后台可见诊断，
但公开 GET 不写日志。

为避免视图和服务复制排序，实施时把当前 `_race_priority_score` / `_headline_sort_key` 移到
`editorial_headlines.py` 或保留一处公共实现，再由现有算法回退与推荐共同调用。不得改变排序元组和三级
fallback 行为；移动代码必须由现有头条测试保护。

推荐不是一次新的模型调用。`generated_by` 表示点击生成的运营人员，`engine_version` 表示自动化推荐引擎。

## 7. 失效与审计协调

扩展 `server/stable/signals.py` 和已知批量写入口：

- `post_save(NewsArticle)`：`transaction.on_commit()` 后调用
  `invalidate_headline_state_for_article(article_id, reason="article_became_ineligible")`；
- `pre_delete(NewsArticle)`：在删除事务内按统一锁顺序清除 selection、把 active recommendation
  标为 invalidated，并记录 `article_deleted`；
- `NewsArticleAdmin.mark_pending_review()` 当前使用 `queryset.update()`，不会触发 signal；本变更把它改为
  逐文章受控 `save(update_fields=...)` 或等价共享状态转换，使当前头条失效协调、version 和审计不被绕过；
  其他只更新非资格字段的 bulk update 不扩大处理范围；
- 服务只在控制/推荐确实指向该文章且文章已不合格时写入，因此普通新闻保存只产生小额索引查询，不写日志。

失效协调必须幂等：

- selection 已空或指向其他文章：零写；
- recommendation 已非 active：零写；
- 重复 signal：不重复审计；
- `on_commit` callback 用模块级 logger 捕获异常，记录结构化 `article_id/reason/exception` 和 traceback，
  不重新抛出，避免把已成功保存的文章呈现为整体失败；公开 resolver 仍会重新验证并安全回退；
  后续同一文章保存或头条管理写操作会再次协调。数据库不可写时无法伪造 `OperationLog`，结构化 error log
  是该异常路径的明确运营信号。

失效后 `version + 1`，旧页面不能把原选择作为当前状态继续操作。

## 8. 缓存

探索确认：

- 首页没有 `cache_page`、cache middleware 或 headline cache key；
- `CACHES` 当前只由 `race_event_public_cache.py` 的赛事站点地图/年份统计使用；
- 新闻发布、撤稿和保存不调用 cache deletion。

因此本变更不为头条新增缓存，也不触碰赛事 cache。头条状态变化后的“缓存失效”验收定义为：

- 同一进程连续两次首页请求在设置/替换/取消/失效后立即读取新数据库状态；
- 不出现进程内 memoization、session 或模板 fragment 的陈旧头条；
- 若实施过程中提出新增 headline cache，必须回到方案审核，补 key、TTL、事务提交后删除和 Redis 故障回退，
  不能在实现时临时加入。

## 9. 页面与路由

新增路由建议：

```text
GET  /admin/headline/                         管理页
POST /admin/headline/select/                  人工设置/替换
POST /admin/headline/cancel/                  取消
POST /admin/headline/recommend/               刷新推荐
POST /admin/headline/recommend/<id>/accept/   接受推荐
```

管理页最近合格文章最多 48 篇，支持现有文章标题查询的最小筛选，不做新的频道/分页体系。

`article_editor.html` 右栏增加只读推荐卡和“刷新推荐”按钮。和现有 quick-term 一样，实际 POST form 放在
外层文章表单之外，通过 `form` 属性关联，避免嵌套表单导致误保存或误发布。

公开 `_headline.html` 和 `public.css` 预计无需行为改动：`headline_article` 对象契约不变。只有实际浏览器
验收证明出现布局问题时才允许做最小样式修复，并需回到同一方案/代码 reviewer 范围。

## 10. 预计文件

应用与迁移：

- `server/stable/models.py`
- `server/stable/migrations/0054_homepage_headline_control.py`
- `server/stable/services/editorial_headlines.py`（新增）
- `server/stable/admin.py`
- `server/stable/forms.py`
- `server/stable/views.py`
- `server/stable/urls.py`
- `server/stable/signals.py`
- `server/stable/templates/stable/console/headline_control.html`（新增）
- `server/stable/templates/stable/console/article_editor.html`
- `server/stable/templates/stable/console/base.html`


- `server/stable/test_editorial_headlines.py`（新增）
- 必要时增加 PostgreSQL 专项测试文件，或在同文件按 vendor 跳过。
- 复用 `server/stable/tests.py::PublicHomeInfoFeedTests` 与
  `server/stable/test_public_navigation_and_attribution.py`。

文档：

- 本目录五份产物；
- `docs/current_state.md`
- `docs/decisions.md`
- `docs/project_status.md`
- 发布/运行态实际发生后才向 `docs/deploy_runbook.md` 和本变更 `release_report.md` 追加证据。

`_headline.html`、`feed.html`、`public.css` 当前预计不修改。若实现基线变化，必须在 rebase 后重新做文件/hunk
重叠检查。

## 11. 迁移、上线与回滚

迁移只新增两张表、索引、FK 和约束，不回填 `NewsArticle`，部署后 selection 为空，首页继续走现有算法。

PostgreSQL 影响：

- 两表的 `CHECK(slot='homepage_primary')`；
- `UNIQUE(slot)`；
- `UNIQUE(slot) WHERE status='active'` 条件索引；
- FK 使用 `SET NULL`，删除文章不删除审计模型；
- 新表为空创建，预计锁时短，不扫描 `NewsArticle`。

上线顺序：

1. 备份数据库并验证恢复点；
2. 在任何 RED/实现前，先确认未提交内容仅为本任务规格/状态文档，记录完整 diff 与逐文件内容
   fingerprint；用带名称且包含 untracked 文件的 stash 暂存并记录精确 OID，确认 worktree 干净后
   fetch、rebase 到届时最新 `origin/main`，再 apply 该精确 stash；
3. 恢复后逐文件核对内容 fingerprint，检查 hunk 重叠；只有无冲突且内容一致才删除临时 stash。若
   rebase/stash 恢复改变内容或方案，则保留 stash、停止实现，先复用方案 reviewer 复审并重新取得
   实现确认；
4. 部署已审核代码并执行 `0054`；
5. 验证 migration、Django check、公开首页和后台权限；
6. selection 为空时确认算法头条与部署前一致；
7. 仅在人工操作后创建第一条选择/推荐，不做自动数据写入。

回滚：

- 首选回滚应用代码并保留新增表，旧代码会忽略新表并继续算法头条；这样保留审计和人工选择证据。
- 不在故障窗口直接反向迁移。经单独批准后才可 reverse `0054`，其影响是删除全部头条选择/推荐记录，
  但不修改或删除 `NewsArticle`。
- 若新头条逻辑异常但应用仍可用，可取消 selection 立即恢复算法回退；这比回滚数据库更小。

## 12. 风险与处理

- **陈旧后台页面覆盖新选择**：selection version + 行锁拒绝。
- **两个 worker 首次创建单例**：唯一 slot + savepoint 内 create/retry。
- **推荐覆盖人工选择**：推荐模型独立，生成路径没有 selection 写入。
- **文章撤稿后仍显示**：写路径失效协调 + 公开读取时资格复验双层防线。
- **公开 GET 产生副作用**：resolver 明确只读；审计由保存/删除协调完成。
- **推荐理由与实际信号漂移**：推荐保存 evidence snapshot，不在展示时重新拼接历史理由。
- **首页性能下降**：单例 `select_related(article)` 查询；现有公开候选和预取范围不扩大。
- **前序来源隐藏回归**：不改 headline partial，回归测试显式断言公开 HTML。
- **范围膨胀为推荐平台**：固定一个 slot、一个 active 推荐、最多 48 个候选，不做定时/多地区/个性化。
