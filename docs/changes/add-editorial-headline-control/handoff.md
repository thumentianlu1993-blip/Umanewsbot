# `add-editorial-headline-control` 完整交接文档

> 交接对象：后续负责测试、实现、验证和代码审核协调的 Claude agent  
> 文档日期：2026-07-24（Asia/Shanghai）  
> 当前阶段：探索、规格、设计和独立方案审核均已完成；尚未开始测试或实现  
> 方案审核结论：`VERDICT: APPROVED`

## 1. 一页式状态

本 change 要实现两项互相隔离的能力：

1. 后台运营人员可以明确选择唯一一篇当前首页人工头条；
2. AI 编辑页可以基于已有自动化/AI 编辑信号推荐一篇候选及理由，但推荐不会直接修改首页，只有人工明确
   接受后才切换人工头条。

当前仓库仍只有原有算法头条。没有新增模型、迁移、服务、视图、模板、样式或测试；本 change 当前只有
规格和状态文档。

已经完成：

- 从已验证的最新 `origin/main` 建立独立 worktree；
- 确认前序 `simplify-public-navigation-and-attribution` 已合入；
- 只读探索首页头条算法、公开 queryset、后台、AI 编辑区、审计、权限、缓存和批量状态入口；
- 编写 `spec.md`、`design.md`、`test_cases.md`、`tasks.md`、`rollout.md`；
- 独立方案 reviewer 在同一会话完成三轮审核，首轮 6 项 finding 全部关闭，最终批准。

尚未完成：

- 实现前最新主干 rebase 门禁；
- RED 测试；
- 任何应用实现或迁移；
- GREEN 验证和浏览器验收；
- 独立代码 review；
- commit、push、PR、部署、生产迁移或生产数据写入。

## 2. 工作区和 Git 基线

必须在以下 worktree 工作，不要回到原始 checkout：

```text
/Users/mentianlu/Code/umanews/.worktrees/add-editorial-headline-control
```

当前分支：

```text
codex/add-editorial-headline-control
```

2026-07-24 最后一次 `git fetch origin --prune` 后：

```text
HEAD        = 10f341e6b76b634d840ec8c87b818de3c722f450
origin/main = 10f341e6b76b634d840ec8c87b818de3c722f450
ahead/behind = 0/0
```

该提交是：

```text
Merge pull request #19 from
thumentianlu1993-blip/codex/audit-reprocess-historical-news-body-contamination
```

当前未提交内容应严格限于：

```text
M  docs/current_state.md
M  docs/decisions.md
M  docs/project_status.md
?? docs/changes/add-editorial-headline-control/
```

如果 Claude 接手时看到任何额外文件或 hunk，不要覆盖、reset 或假设它属于本任务；先辨认所有权并向用户报告。

## 3. 授权边界

原始用户指令规定：

- 方案审核通过后必须停止；
- 用户明确回复“G1 范围确认”“开始实现”或同义授权前，不得写测试、实现、迁移或启动实现 subagent；

用户本轮说明将项目交给 Claude 实现，但本轮直接动作是“编写交接文档”，并没有让当前 Codex 开始测试。
“G1 范围确认”“开始实现”或等价指令。若没有，先用一句话请求确认，不得自行越过。

本任务的测试和实现必须委派给 subagent，并按文件边界串行处理。subagent 不得 commit、push、PR、
部署、执行生产迁移或写生产。独立代码 reviewer 必须未参与实现。

## 4. 强制工作规则

### 4.1 开始前必读

先完整阅读：

- `AGENTS.md`
- `docs/codex_workflow.md`
- `docs/project_overview.md`
- `docs/current_state.md`
- `docs/decisions.md`
- `docs/deploy_runbook.md`
- `docs/session_bootstrap.md`

涉及后续发布或运维时再读：

- `docs/deploy_production.md`
- `docs/alicloud_hongkong_step_by_step.md`
- `docs/rollback_guide.md`
- `docs/backup_recovery.md`

本 change 的规范文件必须全部阅读：

- `docs/changes/add-editorial-headline-control/spec.md`
- `docs/changes/add-editorial-headline-control/design.md`
- `docs/changes/add-editorial-headline-control/test_cases.md`
- `docs/changes/add-editorial-headline-control/tasks.md`
- `docs/changes/add-editorial-headline-control/rollout.md`
- 本文件

### 4.2 明确禁止

- 禁止使用任何 旧规格流程 skill 或 旧规格流程 CLI；
- 不修改 `AGENTS.md`；
- 不修改新闻采集、正文提取、马名识别、赛事日历；
- 不顺手重构首页推荐、热门或普通 feed 系统；
- 不新增第二套外部 LLM/API 调用；
- 不把 Django Admin 展示字段变成未经业务校验的生产选择入口；
- 不在公开 GET 请求中写数据库或审计；
- 不在尚未授权时 commit、push、PR 或部署。

## 5. 需求背景与验收目标

现有首页头条完全由系统自动选择，运营人员没有明确控制入口。目标是在保持原有自动 fallback 的同时增加
人工控制和 AI 建议。

最终产品必须满足：

1. 有权限后台用户可选择一篇合格文章作为当前人工头条；
2. 同时最多一个人工头条，新选择原子替换旧选择；
3. AI 编辑页展示一篇推荐文章、中文推荐理由及证据摘要；
4. AI 推荐和正式人工选择是两个独立持久状态；
5. 生成或刷新推荐不得改变首页；
6. 只有人工明确接受推荐才切换人工头条；
7. 有效人工头条优先于算法；
8. 人工头条失效后安全回到原算法；
9. 非公开、未来网页发布时间或有效内容不完整的文章不能成为人工、推荐或算法头条；
10. 设置、替换、取消、接受、失效和推荐生命周期可审计；
11. 并发操作不能留下两个有效头条或两个 active 推荐；
12. 首页继续隐藏来源、地区、原文语言和原文链接；
13. 1440px 和 390px 页面正常，无横向溢出。

当前版本不做：

- 多头条轮播；
- 按地区分别设置；
- 个性化；
- 定时开始/结束；
- AI 自动发布或自动替换；
- 新的推荐平台或提示词体系。

## 6. 已确认的当前实现

### 6.1 公开 queryset

入口：

```text
server/stable/views.py::_public_published_articles()
```

当前条件：

```text
workflow_status = PUBLISHED
published_to_web_at IS NOT NULL
ORDER BY published_to_web_at DESC, id DESC
```

该 queryset 会预取公开展示所需的图片和关联对象，但当前没有
`published_to_web_at <= now` 门禁，也没有有效标题/摘要/正文完整性门禁。

### 6.2 当前自动头条

入口：

```text
server/stable/views.py::_select_headline_article()
```

当前按以下窗口依次尝试：

1. 近 72 小时；
2. 近 7 天；
3. 全部公开文章。

每个窗口先取按网页发布时间倒序的前 48 个原始对象，再用现有排序 key 取最大值：

```text
race priority
score_total
has cover
web/source publish timestamp
article id
```

必须保留三级窗口和排序元组。批准方案只统一资格并把“48 个原始行”收敛为“前 48 个合格候选”，不是
重新设计排序算法。

### 6.3 公开模板

大致数据流：

```text
NewsArticle
  -> _public_published_articles()
  -> _select_headline_article()
  -> public_news_feed(headline_article)
  -> feed.html
  -> _headline.html
```

普通 feed 会排除最终 `headline_article`，避免重复。

当前 `_headline.html` 已只展示标题、有效摘要、网页发布时间、详情链接和图片，不显示来源或地区。

### 6.4 后台与 AI 编辑区

项目主要运营入口是自建 `/admin/` console，不是 Django Admin 模型表单。

```text
server/stable/views.py::article_editor
server/stable/templates/stable/console/article_editor.html
```

编辑页已有自动化分数、决策、AI 翻译/改写信息，可在该区域新增推荐卡，但推荐操作 form 不能嵌套在
文章编辑 form 内。应沿用现有 quick-term 等操作的外置 form + `form` 属性模式。

### 6.5 权限和审计

后台已有 staff gate 和 `OperationLog` / `log_operation()`。新能力复用它们，不新建另一套审计系统。

已批准权限为：

```text
is_staff = True
stable.change_homepageheadlineselection
```

superuser 沿用 Django 默认权限规则。

### 6.6 缓存

首页、详情和 headline 当前没有：

- `cache_page`；
- cache middleware；
- template fragment cache；
- headline cache key。

现有 Django cache 只用于赛事站点地图/日历相关统计。因此本任务不新增 headline cache，也不触碰赛事
cache。“缓存正确失效”的本版本验收是连续请求立即读到数据库新状态，不出现进程内陈旧值。

### 6.7 已知批量绕过

```text
server/stable/admin.py::NewsArticleAdmin.mark_pending_review()
```

当前使用 `queryset.update(workflow_status=PENDING_REVIEW)`，不会触发 `post_save`。本任务必须把该入口改为
逐文章受控保存或等价共享状态转换，使当前头条的失效协调、version 和审计不被绕过。

不要扩大到所有无关 bulk update。

## 7. 已批准的数据模型

### 7.1 为什么不在 `NewsArticle` 增加布尔字段

已比较过 `is_homepage_headline` / `is_featured` 一类方案，未采用，原因是：

- 唯一头条是跨文章不变量；
- 两个请求可同时把不同文章设为 `True`；
- 替换需要协调多行，锁和审计容易分散；
- 推荐与正式选择容易混在文章字段上；
- Django Admin 容易绕过业务校验；
- 文章删除会丢失选择事实。

### 7.2 `HomepageHeadlineSelection`

建议字段：

```text
slot: CharField(max_length=32, unique=True, default="homepage_primary")
article: ForeignKey(NewsArticle, null=True, blank=True, on_delete=SET_NULL)
selected_by: ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
selected_at: DateTimeField(null=True, blank=True)
version: PositiveBigIntegerField(default=0)
created_at
updated_at
```

必须有：

```text
CheckConstraint(slot = "homepage_primary")
UNIQUE(slot)
```

语义：

- 固定 slot；
- `article_id IS NULL` 表示没有人工头条；
- 设置、替换、取消、接受推荐和失效清除均递增 version；
- 历史动作进 `OperationLog`，selection 只保存当前控制状态。

### 7.3 `HomepageHeadlineRecommendation`

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
created_at
updated_at
```

必须有：

```text
CheckConstraint(slot = "homepage_primary")
UniqueConstraint(fields=("slot",), condition=Q(status="active"))
index(slot, status, -created_at)
```

推荐记录是快照和历史，不是首页控制状态。

### 7.4 迁移

预计新增：

```text
server/stable/migrations/0054_homepage_headline_control.py
```

迁移只新增两张空表、索引、FK 和约束，不扫描或回填 `NewsArticle`。

上线后 selection 为空，旧算法继续工作。应用回滚时优先保留新表；反向迁移会删除选择/推荐历史，必须
单独批准并先备份。

## 8. 统一资格

人工选择、AI 推荐和算法 fallback 必须调用同一个资格函数，并同时满足：

```text
workflow_status == published
published_to_web_at is not null
published_to_web_at <= now
effective_title.strip() is not empty
effective_summary.strip() is not empty
effective_body.strip() is not empty
article can use current numeric public detail route
```

补充：

- 不要求图片；图片只参与排序；
- `published_at` 是来源时间，不用作网页未来门禁；
- 不单独依赖历史 `withdrawn_at`，以当前 workflow 状态为准；
- 必须精确复现 `effective_*` 的人工字段优先级与摘要 fallback；
- 普通公开 feed 的历史查询语义本任务不修改；
- 无效人工选择不得被原算法马上重新选回。

## 9. 服务层和并发

新增：

```text
server/stable/services/editorial_headlines.py
```

建议接口：

```python
is_headline_eligible(article, *, now=None)
headline_candidate_queryset(*, now=None)
get_headline_state(*, now=None)
select_automatic_headline(public_queryset, *, now=None)
resolve_homepage_headline(public_queryset, *, now=None)
set_manual_headline(article_id, *, user, expected_version)
cancel_manual_headline(*, user, expected_version)
generate_headline_recommendation(*, user, now=None)
accept_headline_recommendation(
    recommendation_id, *, user, expected_selection_version
)
invalidate_headline_state_for_article(article_id, *, reason)
```

视图、信号和首页不得复制写逻辑。

### 9.1 首次创建 selection

必须处理两个 worker 同时首次创建：

1. 外层 `transaction.atomic()`；
2. 内层 savepoint 中 `get_or_create(slot=homepage_primary)`；
3. 唯一约束冲突方捕获 `IntegrityError`；
4. 退出已回滚的内层 savepoint后重新读取；
5. `select_for_update()` 锁定唯一 selection 行。

不要在已标记回滚的事务块中捕获后继续查询。

### 9.2 写锁顺序

统一锁顺序：

```text
selection -> recommendation -> article
```

人工设置/取消、推荐生成/接受和失效协调都必须遵守。

人工写入请求携带 `expected_version`：

- 一致：更新并 `version + 1`；
- 不一致：返回 409 或明确表单冲突；
- 陈旧页面不能静默覆盖新选择。

真实 PostgreSQL 双连接测试必须覆盖并发设置、并发推荐及选择/失效交错。SQLite 下不能伪装成行锁测试，
应明确 skip。

## 10. 候选读取和推荐算法

### 10.1 数据库超集

先在数据库过滤：

```text
workflow_status=published
published_to_web_at IS NOT NULL
published_to_web_at <= now
标题各层至少一个非空
正文各层至少一个非空
```

这是资格超集，不替代 Python 的 `effective_*` 精确判断。

### 10.2 预取和边界

必须：

- `select_related("cover_media_asset")`；
- 将按 `sort_order,id` 排列的 `NewsImage` 预取到专用 `to_attr`；
- 排序时只读取已加载字段，不能逐篇 related-manager 查询。

每个 72h/7d/all 窗口：

1. 按网页发布时间倒序每批读取 48 行；
2. 最多扫描 192 个数据库超集行；
3. Python 精确校验资格；
4. 收集前 48 个合格候选；
5. 第 49 个合格候选不参与排序；
6. 使用原排序 key 选最大值。

若一个窗口 192 行内没有合格候选，进入下一级窗口；全部没有时允许不渲染 headline hero，但普通 feed
继续正常展示，不能出现 500、空链接或空白占位框。

### 10.3 AI 推荐

本版本不发起新的模型请求。复用已有持久化信号：

```text
decision_reason.signals.race_priority
score_total
has cover
published_to_web_at
现有稳定 tie-break
```

证据至少保存：

- 有序候选 ID；
- 候选时间和上限；
- 参与排序的信号值；
- 选中文章排序 key；
- 生成时人工选择文章 ID；
- `engine_version=homepage-headline-recommendation.v1`。

理由应是基于保存信号的简洁中文说明，不得声称新调用了模型或输出未保存的隐式推理。

刷新推荐：

- 必须是 POST；
- 普通 GET 不写；
- 锁 selection 和当前 active 推荐；
- 旧 active 变 `superseded`；
- 新建唯一 active；
- 无合格候选时不创建空推荐；
- 不修改 selection。

接受推荐：

- 明确人工 POST；
- 校验权限、selection version、推荐仍 active、文章仍合格；
- 同一事务更新 selection、推荐状态和审计；
- 有效人工头条存在时，按钮文案必须明确“替换当前头条”。

## 11. 失效、删除和审计

### 11.1 保存后的失效协调

扩展：

```text
server/stable/signals.py
```

`post_save(NewsArticle)` 在 `transaction.on_commit()` 后调用失效协调。

回调必须：

- 幂等；
- 只在 selection/active recommendation 实际指向该文章且文章已不合格时写；
- 失效 selection 时 `version + 1`；
- 捕获异常；
- 用模块 logger `.exception()` 记录结构化 `article_id`、reason、exception 和 traceback；
- 不重新抛出，以免已成功文章保存被用户误认为整体失败；
- 公开 resolver 仍重新校验并安全 fallback；
- 后续保存或头条管理写入可再次协调。

数据库不可写时不能伪造 `OperationLog`，结构化 error log 是该异常路径的运营信号。

### 11.2 删除

`pre_delete(NewsArticle)` 在删除事务内按统一锁顺序：

- 清除指向该文章的 selection；
- active recommendation 变 `invalidated`；
- 写 `article_deleted` 原因的审计；
- FK 使用 `SET_NULL` 保留控制和推荐记录。

### 11.3 审计 action

沿用 `OperationLog`，至少包含：

```text
headline_set
headline_replaced
headline_cancelled
headline_invalidated
headline_recommendation_generated
headline_recommendation_superseded
headline_recommendation_accepted
headline_recommendation_invalidated
```

detail 保存旧/新文章 ID、selection version、推荐 ID、engine version、原因和操作者；不要保存正文全文、
模型 prompt、密钥或敏感配置。

## 12. 页面和路由

建议新增：

```text
GET  /admin/headline/
POST /admin/headline/select/
POST /admin/headline/cancel/
POST /admin/headline/recommend/
POST /admin/headline/recommend/<id>/accept/
```

新增模板：

```text
server/stable/templates/stable/console/headline_control.html
```

管理页显示：

- 当前有效人工头条，或“当前使用算法回退”；
- 当前 AI 推荐、推荐理由、证据摘要和状态；
- 最近最多 48 篇合格文章；
- 设置/替换、取消、刷新推荐、接受推荐；
- 最近相关 `OperationLog`。

`article_editor.html` 增加只读推荐卡、刷新和“前往确认”入口。所有 POST 仍由服务端重新校验，不信任
隐藏字段、展示字段或陈旧页面。

选择模型不得注册成可自由编辑的 Django Admin 表单。

## 13. 预计文件边界

应用：

```text
server/stable/models.py
server/stable/migrations/0054_homepage_headline_control.py
server/stable/services/editorial_headlines.py
server/stable/admin.py
server/stable/forms.py
server/stable/views.py
server/stable/urls.py
server/stable/signals.py
server/stable/templates/stable/console/headline_control.html
server/stable/templates/stable/console/article_editor.html
server/stable/templates/stable/console/base.html
```

测试：

```text
server/stable/test_editorial_headlines.py
server/stable/tests.py::PublicHomeInfoFeedTests
server/stable/test_public_navigation_and_attribution.py
```

预计不需要修改：

```text
server/stable/templates/stable/public/_headline.html
server/stable/templates/stable/public/feed.html
server/stable/static/stable/public.css
```

只有真实浏览器验收证明布局有问题时，才允许最小样式修复，并要纳入同一代码 review 范围。

严禁触碰：

```text
新闻采集
正文提取
马名识别
赛事日历
AGENTS.md
```

## 14. 前序 change 和冲突分析

`simplify-public-navigation-and-attribution` 已通过 PR #16 合入 `main@438ab6a1`，当前基线是其后代。

该前序 change 修改过：

- `server/stable/views.py`；
- `_headline.html`、`_article_card.html`、`_hot_list.html`、`feed.html`、`detail.html`；
- `public.css`；
- `server/stable/tests.py`；
- `server/stable/test_public_navigation_and_attribution.py`。

本任务预计直接重叠集中于 `views.py` 的最终 headline 解析；另有审核新增的 `admin.py`
`mark_pending_review` 修复。公开 partial 和 CSS 原则上不改。

实现前必须重新检查上述文件的最新 hunk，尤其不能恢复来源、地区、原文语言或原文链接。

## 15. Claude 的准确启动顺序

### 15.1 确认授权

如果 Claude 会话中尚无用户明确“G1 范围确认/开始实现”或等价指令，先停下请求确认。不要把本交接文档本身

### 15.2 安全同步最新主干

由于规格文件未提交，普通 rebase 会被拒绝。不得临时 commit，也不得丢弃文档。

先：

1. 确认所有未提交内容仅为本任务规格/状态文档；
2. 记录 `git status --short`；
3. 保存完整 diff；
4. 对下列文件逐一记录 SHA-256：
   - `docs/current_state.md`
   - `docs/decisions.md`
   - `docs/project_status.md`
   - 本 change 目录内全部文件；
5. 执行带描述的 `git stash push -u`；
6. 记录精确 stash commit OID；
7. 确认 worktree clean；
8. `git fetch origin --prune`；
9. `git rebase origin/main`；
10. apply 精确 stash OID，不依赖可能变化的 `stash@{0}`；
11. 重新计算逐文件 SHA-256并与恢复前比较；
12. 检查 hunk 重叠和 `git diff --check`；
13. 只有无冲突且内容一致才删除临时 stash。

若 rebase 或 stash 恢复有冲突、文件内容/fingerprint 改变或方案需要调整：

- 保留 stash；
- 不开始测试；
- 修订方案；
- 复用方案 reviewer 重新审核；
- 审核通过后重新取得实现确认。

### 15.3 测试先行

取得有效授权并完成基线门禁后，所有测试委派给测试 subagent，按下列顺序：

1. 模型、迁移、固定 slot、唯一 selection、active 推荐约束；
2. 资格、设置/替换/取消、版本冲突、权限、审计；
3. 保存/删除失效、Admin bulk action、on_commit callback 异常、读取 fail-safe；
4. AI 推荐生成/替换/接受/失效，以及“推荐不改变首页”；
5. 48 合格/192 扫描边界、49th exclusion、图片 query count；
6. 管理页、编辑页非嵌套 form、公开来源隐藏；
7. 真实 PostgreSQL 双连接并发。

必须实际运行并取得真实 RED。RED 原因必须是目标能力尚未实现，不能来自语法错误、错误 fixture、错误依赖
或测试环境损坏。

### 15.4 串行实现

只有真实 RED 后，按文件边界串行委派：

1. 模型 + `0054`；
2. `editorial_headlines.py` 服务；
3. signals 与删除协调；
4. `admin.py` bulk 绕过修复；
5. forms、routes、console view/template；
6. article editor 推荐卡；
7. 首页 resolver 接入；
8. 文档证据更新。

每个 subagent 必须知道：

- 它不独占工作区；
- 不覆盖其他 agent 改动；
- 只修改被分配文件；
- 不 commit/push/PR/deploy；
- 不执行生产迁移或生产写入。

## 16. RED 测试最低矩阵

至少覆盖：

1. 合格文章可设为头条；
2. 新选择原子替换旧选择；
3. 同时只有一个 selection；
4. 未发布、撤稿、未来网页时间或内容不完整不可选择；
5. 生效文章失效后首页安全 fallback；
6. 无人工头条沿用原三级算法和排序；
7. AI 推荐不改变首页；
8. 人工接受后才切换；
9. 推荐生成不能静默覆盖人工选择；
10. 无权限用户不能写；
11. 设置、替换、取消、接受、失效和推荐生命周期有审计；
12. 并发设置不会留下两个头条；
13. active 推荐条件唯一；
14. 连续首页请求立即反映设置/取消/失效；
15. 公开页面继续隐藏来源和地区；
16. 1440px/390px 头条正常；
17. 非 `homepage_primary` slot 被数据库拒绝；
18. 前 48 原始行有无效文章时可在 192 内补足 48 个合格候选；
19. 第 49 个合格候选不参与；
20. 封面/图片读取无 N+1；
21. `mark_pending_review` 可使当前头条失效；
22. on_commit 协调异常被记录、不重抛，公开读取仍安全；
23. PostgreSQL 两连接并发设置/推荐/失效交错后状态和审计一致。

更详细步骤见 `test_cases.md`。

## 17. 实现后验证

至少运行：

- 聚焦头条测试；
- 后台权限与审计测试；
- AI 推荐生命周期测试；
- 首页 view/template 回归；
- `PublicHomeInfoFeedTests`；
- `test_public_navigation_and_attribution.py`；
- 缓存实时性连续请求测试；
- 真实 PostgreSQL 并发测试；
- `python manage.py check`；
- `python manage.py makemigrations --check --dry-run`；
- 必要的完整 `stable` 回归；
- `git diff --check`。

浏览器真实验收：

- 公开首页 1440px；
- 公开首页 390px；
- 后台头条管理页桌面/移动；
- article editor 推荐卡；
- 可见 DOM 中无来源/地区/语言/原文链接；
- 无横向溢出；
- 导航和按钮可用；
- console 无新增错误。

本地测试通过不是生产证明，不得在此阶段宣称已部署。

## 18. 独立代码审核与 fingerprint

实现和全部验证完成后：

1. 冻结完整未提交范围；
2. 运行仓库 `review_fingerprint.py`；
3. 使用未参与实现的 reviewer；
4. reviewer 必须实际执行 Codex 原生只读 review：

```text
codex review -c 'sandbox_mode="read-only"' --uncommitted
```

5. 记录命令、会话、fingerprint、stdout 结论；
6. 有 actionable finding 时由实现 subagent 修复；
7. 复用同一代码 reviewer 会话，只复审 finding、修复和直接触及路径；
8. 重新验证；
9. review 前后 fingerprint 必须一致；

测试通过不能替代原生 review；review 命令 exit 0 也不等于 `VERDICT: APPROVED`。

## 19. 发布边界


- commit；
- push；
- 创建 PR；
- merge；
- 部署；
- 执行 `0054`；
- 重启服务；
- 写生产数据。

取得授权后仍要：

1. fetch 并确认主干未推进；
2. 若推进，重新集成、验证、review，并重新取得授权；
3. staging 前重算同 scope fingerprint；
4. 确认 staged/unstaged/untracked 状态；
5. 部署前核对生产 HEAD、容器、队列、磁盘、备份和环境 key 存在性；
6. 部署后 selection 保持为空，不自动创建推荐或头条；
7. 首个人工头条仍由运营在后台显式选择；
8. 按证据 allowlist 更新 release report 和运行态文档。

## 20. 方案审核历史

独立方案 reviewer 使用同一会话完成三轮审核。

首轮 `VERDICT: REVISE` 的 6 项 finding：

1. 无效人工文章可能被较宽松的原算法立即选回；
2. Django Admin `mark_pending_review` bulk update 绕过 signal；
3. rebase 被错误放到发布阶段，且未处理未提交规格文档；
4. `UNIQUE(slot)` 仍允许写入其他 slot；
5. `effective_*` 的 Python 资格、N+1 和候选边界不清；
6. `on_commit` callback 异常的可观测性和传播策略不清。

关闭方式：

1. 人工、AI、算法共用统一资格；
2. `admin.py` 纳入范围并添加专项测试；
3. RED 前增加精确 stash/rebase/restore/fingerprint 门禁；
4. 两张表增加固定 slot CheckConstraint；
5. 明确数据库超集、Python 精确资格、48/192 边界、预取和 query count；
6. callback 结构化 exception log 且不重抛，增加故障注入测试。

第三轮最终结论：

```text
VERDICT: APPROVED
Review rounds: 3
F1-F6: all closed
Remaining P0/P1/P2 findings: 0
```


## 21. 容易踩坑的地方

- 不要只给人工选择加严格资格，却让 fallback 继续使用旧宽松候选；
- 不要把 recommendation 的 `active` 当成正式头条；
- 不要在生成推荐时“顺便”填 selection；
- 不要用两个文章布尔字段实现替换；
- 不要只靠应用代码保证唯一，必须有 PostgreSQL 约束；
- 不要把 `select_for_update()` 测试伪装在 SQLite；
- 不要在公开 GET 中清理 selection 或写 audit；
- 不要在 on_commit 异常时把已成功文章保存重新抛成失败；
- 不要遗漏 `mark_pending_review` 的 bulk update；
- 不要调用图片 related-manager 造成每篇查询；
- 不要恢复公开来源/地区字段；
- 不要因后台列表方便而暴露可直接编辑的模型字段；
- 不要在未提交规格存在时直接 rebase；
- 不要把“准备交接”解释为 commit 或发布权限。

## 22. 成功定义

只有同时满足以下条件，代码阶段才算完成：

- 后台可明确选择唯一人工头条；
- AI 只推荐，不自动覆盖；
- 明确接受后才切换；
- 非公开或不完整文章不能进入任何头条路径；
- 失效后安全回到原算法；
- 并发和陈旧页面均 fail closed；
- 审计完整；
- 公开来源隐藏不回归；
- 桌面/移动页面正常；
- 自动化和 PostgreSQL 并发测试通过；
- Django/migration/diff 检查通过；
- 独立原生代码 review `APPROVED`；
- fingerprint 未漂移；
- 尚未发布时明确停下等待授权。

## 23. 权威文档优先级

如本交接与其他材料有差异，按以下顺序处理：

1. 用户最新明确指令；
2. `AGENTS.md`；
3. `docs/current_state.md`；
4. 本 change 的 `spec.md` 和 `design.md`；
5. `test_cases.md`、`tasks.md`、`rollout.md`；
6. 本交接文档。

发现冲突不要自行扩大解释；记录具体文件和行，向用户确认或回到方案 reviewer。

