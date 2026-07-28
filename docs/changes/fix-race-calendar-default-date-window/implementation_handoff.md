# `fix-race-calendar-default-date-window` 完整实施交接

> 交接对象：Claude 或其他新的实现 agent  
> 交接日期：2026-07-28  
> 当前状态：探索、规格、设计和独立方案审核已完成；尚未取得实现授权  
> 本文目标：让接手者不依赖聊天记录即可安全继续

## 1. 先读结论

这是 Umanews/UmaFans 公开赛事日历的默认日期窗口修复。当前 `/races/` 默认页按“北京时间
今天前后 30 个连续自然日”查询，再按日期升序截取前 40 场赛事，最后从这 40 场反推日期栏。
因此 2026-07-27 的查询下界正好是 2026-06-27；赛事密集时前 40 场可能在 2026-07-19
耗尽，页面就会看起来停留在旧窗口。

已审核通过的目标方案是：

- 以 `Asia/Shanghai` 今日为基准；
- 今日有符合当前公开筛选的赛事时锚定今日；
- 今日无赛事时锚定未来最近比赛日；
- 没有未来赛事时回退最近历史比赛日；
- 展示锚点前 5 个、锚点、锚点后 5 个实际比赛日；
- 某侧不足时从另一侧补足，总数最多 11；
- 保留现有最多 40 张赛事卡上限，并保证日期栏中的每个日期至少有一张同资格赛事卡；
- 默认模式在移动端把锚点水平滚动到日期轴可见区域；
- 不改赛事数据、模型、迁移、Celery、赛事生命周期或整体视觉设计。

## 2. 当前授权边界

本交接文档的创建不构成实现授权。

当前已经授权并完成：

- 只读探索；
- 规格和设计；
- 独立方案审核；
- 实施交接文档。

当前仍禁止：

- 编写或修改自动化测试；
- 修改应用代码、模板、CSS、JavaScript、配置或迁移；
- 启动实现 subagent；
- commit、push、创建 PR、merge；
- 部署、服务重启、联网或生产数据写入。

接手者必须先让用户针对当前已审方案明确回复“确认实现”“开始实现”“继续实现”或同义语句。
取得该授权后，才进入测试先行和实现。

即使实现后的独立代码 review 已通过，仍不得直接 commit/push/PR/部署。必须冻结最新成功
review fingerprint，再取得用户针对该 fingerprint 的明确发布授权。

## 3. 仓库、worktree 与基线

主仓库：

`/Users/mentianlu/Code/umanews`

本任务独立 worktree：

`/Users/mentianlu/Code/umanews/.worktrees/fix-race-calendar-default-date-window`

分支：

`codex/fix-race-calendar-default-date-window`

创建时基线：

`origin/main@7385f59ab87bcce5193f3313ecca6809b165ad89`

创建时 `HEAD`、`merge-base` 与 `origin/main` 一致。当前 worktree 只有本任务文档改动，尚未
commit。接手时必须重新执行：

```sh
git fetch --prune origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git merge-base HEAD origin/main
git worktree list --porcelain
```

不得因为本文记录了上述 SHA 就假定它仍是最新 main。若 `origin/main` 已推进，先只读检查
新提交是否触及本任务预计文件和公开资格语义；任何 rebase/merge 仍受当前授权边界约束。

不要在主仓库的脏 worktree 开发。该主 worktree 基于旧提交，存在大量未提交门户、模板、
CSS、赛事和历史数据改动。

## 4. 必须阅读的仓库文档

接手后、进行任何实现动作前，依次阅读最新 worktree 中：

1. `AGENTS.md`
2. `docs/codex_workflow.md`
3. `docs/session_bootstrap.md`
4. `docs/project_overview.md`
5. `docs/current_state.md`
6. `docs/decisions.md`
7. `docs/deploy_runbook.md`
8. `docs/project_status.md`
9. 本目录的 `spec.md`
10. 本目录的 `design.md`
11. 本目录的 `test_cases.md`
12. 本目录的 `tasks.md`
13. 本目录的 `rollout.md`
14. 本文

本任务禁止使用 OpenSpec skills 或 OpenSpec CLI，包括：

- `openspec-explore`
- `openspec-propose`
- `openspec-apply-change`
- `openspec-archive-change`
- `openspec-sync-specs`

## 5. 项目背景

Umanews/UmaFans 是面向中文用户的赛马新闻和赛事资料平台，主技术栈为 Django、PostgreSQL、
Celery、Redis、Docker Compose 与 Nginx。公开赛事产品层使用 `RaceEvent`，赛事日历入口为
`/races/`，详情页为 `/races/<year>/<slug>/`。

本任务只处理公开赛事日历首次进入时的日期选择。不要把它扩展为：

- 赛事生命周期或状态机改造；
- 赛事自动更新；
- race-live/racecard/result 同步；
- 赛事资料或时间归一化；
- 首页近期赛事；
- 赛事详情页年份控件；
- 生产赛事数据修复。

## 6. 当前代码定位

公开 URL：

- `server/app/urls.py`
- `path("races/", stable_views.public_race_calendar, name="public-race-calendar")`

核心 view：

- `server/stable/views.py`
- `_race_calendar_queryset`
- `_group_race_events_by_date`
- `_public_weekly_focus_events`
- `public_race_calendar`

当前关键常量：

- `RACE_CALENDAR_PAGE_SIZE = 40`
- `RACE_CALENDAR_WINDOW_DAYS = 30`

模板与样式：

- `server/stable/templates/stable/public/race_calendar.html`
- `server/stable/static/stable/public.css`

相关服务与缓存：

- `server/stable/services/race_event_public_cache.py`
- `server/stable/signals.py`
- `server/app/settings.py`
- `deploy/nginx/nginx.conf`

相关测试：

- `server/stable/test_race_calendar_responsive_ui.py`
- `server/stable/tests_legacy.py`
- `server/stable/tests/test_page_regression.py`
- `server/stable/test_realtime_race_results.py`
- `server/stable/tests/test_race_result_recovery_application_pages.py`
- `server/stable/test_public_navigation_and_attribution.py`

## 7. 已确认的准确根因

当前 `_race_calendar_queryset` 的默认分支满足 `not (year or query)` 且没有 cursor 时：

```python
start = today - timedelta(days=RACE_CALENDAR_WINDOW_DAYS)
end = today + timedelta(days=RACE_CALENDAR_WINDOW_DAYS)
queryset = queryset.filter(
    Q(local_date__gte=start, local_date__lte=end)
    | Q(local_date__isnull=True)
).order_by("local_date", "local_start_time", "id")
```

随后统一执行：

```python
queryset.prefetch_related("results")[:RACE_CALENDAR_PAGE_SIZE]
```

日期栏来自已经截断的 `events`：

```python
groups = _group_race_events_by_date(events)
date_axis = [group for group in groups if group["date"]]
```

所以旧窗口是以下三件事共同造成：

1. 使用连续自然日 `today ± 30`，而不是实际比赛日；
2. 在赛事对象层先截取 40 场；
3. 日期栏从截断后的赛事对象反推。

已排除：

- 日期硬编码；
- 默认排序为最早全年数据；
- UTC 导致 6 月至 7 月的大跨度偏差；
- Django/Nginx 动态页面缓存；
- JavaScript 固定日期；
- 模板自行生成连续日期。

## 8. 当前公开资格和筛选语义

日期窗口与赛事列表必须复用同一基础 queryset：

- `visibility_status=published`；
- 排除 `canonical_product_links__is_active=True` 的重复底层赛事；
- `tab=key` 时仅 P0/P1 或 `is_featured=True`；
- 应用当前 `region`；
- 应用当前 `grade`；
- 应用当前 `when`；
- 默认比赛日要求 `local_date` 非空。

当前公开资格不以 `data_quality_status` 为额外门禁。本任务不得自行新增该条件。

默认锚点参与的筛选：

- `tab`
- `region`
- `grade`
- `when`

继续绕过默认锚点的显式跨期模式：

- 合法 `direction=past|future` 与 `cursor=YYYY-MM-DD`；
- `year=YYYY`；
- 非空 `q` 搜索。

现有产品没有 `date=` URL 参数。日期栏当前是页内
`#race-date-YYYY-MM-DD` 锚点。不要在本任务中擅自新增 `date=` 协议。

搜索 `q` 是跨年度赛事名称检索；若强行套用今天附近 11 日，会隐藏合法历史结果。因此保持
当前跨期语义。`year` 同理。

## 9. 锁定的默认锚点算法

view 只计算一次：

```python
shanghai_today = timezone.localdate(
    timezone=ZoneInfo("Asia/Shanghai")
)
```

该值必须同时传入：

- 默认日期窗口服务；
- `_group_race_events_by_date`；
- 赛事公开状态标签计算；
- `is_today`；
- 模板的 `today` class 和 aria 标记。

不得在上述路径中再次隐式调用 `timezone.localdate()`，避免 UTC/上海跨日时锚点与高亮不一致。

在当前已筛选公开 queryset 中：

1. `local_date == shanghai_today` 存在时，以今天为锚点；
2. 否则取 `local_date > shanghai_today` 的最早日期；
3. 若未来为空，取 `local_date < shanghai_today` 的最近日期；
4. 若没有任何带日期赛事，返回无锚点和空状态。

## 10. 5+1+5 平衡窗口

建议新增：

`server/stable/services/race_calendar.py`

服务分为：

1. 纯函数 `select_balanced_race_dates(...)`
2. queryset 服务 `public_default_race_date_window(...)`

纯函数输入：

- 锚点前日期，倒序；
- 锚点；
- 锚点后日期，升序；
- `side_size=5`
- `limit=11`

规则：

- 先取前 5、锚点、后 5；
- 一侧不足时从另一侧按离锚点由近及远补；
- 最终升序；
- 唯一；
- 最多 11；
- 必须包含锚点；
- 总数据不足时不造自然日。

数据库层使用两条有界日期聚合查询：

- `local_date <= shanghai_today`，倒序，最多 11 日；
- `local_date > shanghai_today`，升序，最多 11 日。

不要加载全部赛事对象，也不要为 11 个日期逐日查询。

## 11. 保留 40 卡上限

方案 reviewer 明确阻止“11 日内无上限加载全部赛事”。必须继续保留
`RACE_CALENDAR_PAGE_SIZE=40`。

高密度窗口需要：

1. 从每个所选日期取得一个同资格代表赛事 ID，最多 11 个；
2. 默认赛事查询优先保留这些代表赛事；
3. 剩余容量按现有 `local_date/local_start_time/id` 顺序填充至 40；
4. 取得对象后在 Python 中恢复现有时间升序；
5. 日期栏中的每个日期必须存在对应 agenda group 和至少一张赛事卡。

代表赛事必须来自未带 read-gate 展示 annotation 的公开资格 queryset；最终赛事对象查询再
添加现有 `public_current_result_revision_id` 和 `public_projection_write_owner` annotation，
避免聚合分组被展示 annotation 污染。

推荐以两条日期聚合 SQL 同时返回 `local_date` 和稳定代表赛事 ID，再在最终单次赛事查询中
使用代表 ID 优先级。不得为了保证日期覆盖增加 11 次查询。

实现时必须验证 SQLite 测试与 PostgreSQL 生产查询语义一致。代表赛事 ID 的选择、排序和
去重不能依赖仅 PostgreSQL 支持而 SQLite 测试无法表达的隐式行为。

## 12. 锚点标记和移动端位置

默认模式向分组传入选定锚点日期，生成 `is_anchor`。

日期链接：

- 锚点增加 `data-calendar-anchor` 和 `anchor` class；
- 今天继续使用 `today`；
- 今天使用 `aria-current="date"`；
- 未来/历史回退锚点使用 `aria-current="true"`；
- 只能有一个 anchor。

默认模式下，模板内允许一个最小脚本：

- DOM ready 后读取 `.date-axis` 和 `[data-calendar-anchor]`；
- 只设置日期轴自身的 `scrollLeft`；
- 把锚点水平居中；
- 不使用 `scrollIntoView`；
- 不改变页面纵向位置；
- 不使用动画；
- 不修改 URL/hash；
- 显式 cursor/year/q 模式不运行自动定位。

CSS 只能给 `anchor` 增加与现有日期轴一致的轻量强调。不要改卡片布局或 42×42px 等级徽标。

## 13. 缓存结论

`/races/` 没有 `cache_page`、Django cache middleware 或 Nginx proxy cache。

现有 Redis/LocMem 缓存只涉及：

- 赛事日历年份列表；
- sitemap 数量。

本任务不新增默认日期窗口缓存。每个默认请求重新读取上海日期和 distinct 比赛日，因此上海
跨日后不需要 cache key 失效。

年份缓存仍按现有 signal 在 `RaceEvent` 变更时失效，与默认锚点无关。

## 14. 预计修改文件

实现阶段预计：

- 新增 `server/stable/services/race_calendar.py`
- 新增 `server/stable/test_race_calendar_default_date_window.py`
- 窄改 `server/stable/views.py`
- 窄改 `server/stable/templates/stable/public/race_calendar.html`
- 窄改 `server/stable/static/stable/public.css`
- 必要时仅补充既有日历测试断言
- 更新本 change 文档和规定状态文档

不预计修改：

- models；
- migrations；
- settings；
- Celery/tasks；
- lifecycle/race-live/racecard/result 代码；
- 首页；
- 赛事详情年份控件；
- 生产数据。

若实现需要迁移、新字段、配置或更广文件范围，立即停止并回到方案审核/用户确认，不得自行
扩大范围。

## 15. TDD：必须先取得真实 RED

只有用户明确授权实现后，先启动测试 subagent。测试 subagent 不得实现功能，不得
commit/push/PR/部署。

首个可靠 RED：

1. 冻结 `shanghai_today=2026-07-27`；
2. 创建今日、前 5 个和后 5 个实际比赛日；
3. 让部分日期距离今天超过 30 个自然日；
4. 每个日期至少有一场符合 `tab=all` 的 published 赛事；
5. 断言默认日期栏精确等于 11 个实际比赛日。

当前代码会因 `today ± 30` 漏掉远端合法比赛日，因此失败。

第二个 RED：

1. 今天无赛事；
2. 最近未来比赛日超过 30 天；
3. 断言默认页仍以该未来日期为锚点。

当前代码会返回空窗口，因此失败。

RED 必须由缺少目标能力造成。fixture、语法、迁移、依赖或数据库环境错误不能作为 RED。

## 16. 自动化测试矩阵

至少覆盖：

1. 今日存在赛事；
2. 今日无赛事，取未来最近；
3. 无未来，回退最近历史；
4. 完全无公开赛事返回 200；
5. 锚点前不足 5 日；
6. 锚点后不足 5 日；
7. 总日期少于 11；
8. 非连续日期不补自然日；
9. 跨月；
10. 跨年；
11. UTC/上海跨日，锚点、状态、today class、aria 一致；
12. 显式 cursor 历史 URL 保留；
13. region/grade/tab/when 参与窗口；
14. 空筛选结果；
15. hidden/draft/active canonical duplicate 不制造比赛日；
16. 上海跨日后不复用旧窗口；
17. 11 日合计超过 40 场时仍最多 40 卡且每日至少一张；
18. q/year 保持跨期语义；
19. 非法或不完整 cursor 安全回默认；
20. anchor 唯一、未来 anchor 与 today 语义区分；
21. 显式模式不自动滚动日期轴。

## 17. 查询性能预算

现有合同：

- 轻量默认日历：不超过 8 SQL；
- 40 卡 live read gate：不超过 12 SQL；
- 40 卡 official/corrected read gate：不超过 20 SQL；
- canonical 年份模式：不超过 12 SQL。

目标预算：

- 轻量默认：不超过 10 SQL；
- 40 卡 live：不超过 14 SQL；
- 40 卡 official/corrected：不超过 22 SQL；
- canonical 年份模式仍不超过 12 SQL。

默认路径只允许比现有增加两条有界日期聚合查询。实现阶段记录修改前/后的真实 SQL 数和关键
SQL 形状。超过预算时应优化或回到方案审核，不能直接放宽预算。

## 18. 主线程验证

所有测试和实现 subagent 结束后，主线程至少运行：

- 新默认窗口聚焦测试；
- `test_race_calendar_responsive_ui`；
- 日历 view/template 回归；
- filter/search/year/cursor 回归；
- timezone/cache/query-count 回归；
- live/official read-gate 查询预算测试；
- Django check；
- `makemigrations --check --dry-run`；
- `git diff --check`。

不要声称整仓测试通过，除非实际执行并保存结果。环境或既有失败必须与本任务 GREEN 分开报告。

## 19. 浏览器验收

使用真实页面和真实浏览器至少检查：

- 1440px；
- 390px；
- 必要时 320px。

必须记录：

- 默认日期栏最多 11 个实际比赛日；
- 锚点处于日期轴可视区域；
- 自动定位只发生水平滚动；
- 页面纵向位置不跳动；
- 月份可识别；
- 跨年时年份清晰；
- 页面无横向 overflow；
- G1/G2/G3 徽标仍为 42×42px；
- 控制台无新增错误；
- 显式 cursor/year/q 不自动重定位。

浏览器验收不替代自动化测试。

## 20. 并行 worktree 与集成顺序

探索时已核对：

- `automate-race-event-lifecycle` 和 phase B 没有修改日历 view、query service、template、
  CSS 或日历测试；
- lifecycle 阶段 A worktree 有未合并的状态文档追加；
- `impl-race-news-quality-20260726` 修改 `views.py`，但 hunk 位于 public news feed，不在
  日历函数；
- 主仓库脏 worktree 有旧版门户级 `views.py/race_calendar.html/public.css/tests` 大改。

接手时必须重新检查，因为并行状态可能已经变化。

集成顺序：

1. 本任务继续基于最新 main 做窄改；
2. 不复制或覆盖脏主 worktree 的整文件；
3. 若旧门户改动仍继续，应在本任务之后 rebase 并人工适配；
4. 共享状态文档只能基于最新 main 追加，不能用旧分支整文件覆盖。

若发现并行任务开始修改 `_race_calendar_queryset`、新日历服务、日历模板、public.css 同一
hunk 或目标测试文件，先停止并向用户报告精确重叠和建议集成顺序。

## 21. 方案审核记录

独立方案 reviewer 未参与规格编写。

首轮结论：`VERDICT: REVISE`

首轮 3 项 P1：

1. `Asia/Shanghai` 未贯穿 `_group_race_events_by_date` 和 today markup；
2. 11 日内全部赛事无上限，冲突现有 40 卡合同；
3. 移动端第 6 个锚点初始不可见。

修订：

1. 单一 `shanghai_today` 贯穿窗口、状态、分组和 aria；
2. 保留 40 卡，以每日期代表赛事优先；
3. 增加 `is_anchor` 与只改 `scrollLeft` 的最小水平居中。

同一 reviewer 会话限定复审：3 项 P1 全部关闭，`VERDICT: APPROVED`。

之后状态标题出现一次 P3 文案不一致，已在同一 reviewer 会话改正并复审关闭。

最终方案 reviewer 结论：`VERDICT: APPROVED`，无剩余 finding。

残余实现风险：

- ORM 代表赛事排序的 SQLite/PostgreSQL 一致性；
- 390px/320px 的 `scrollLeft` 真实浏览器行为。

这两项已进入测试和浏览器门禁。

方案审核通过不等于代码 review，也不等于实现或发布授权。

## 22. 实现 subagent 边界

获得实现授权后，顺序必须是：

1. 测试 subagent 只写测试并取得真实 RED；
2. 测试 subagent 结束；
3. 实现 subagent 完成最小 GREEN；
4. 所有 subagent 结束；
5. 主线程检查、整合和验证。

subagent 不得：

- commit；
- push；
- PR；
- 部署；
- 连接或写生产；
- 扩大到非目标模块；
- 回退其他人的改动。

交付必须包含改动文件、执行的测试、真实结果和剩余风险。

## 23. 独立代码 review

实现与主线程验证完成后，必须由未参与实现的独立 reviewer 进行 Codex 原生只读 review。
首次建立 reviewer 会话；后续 finding 修复必须复用同一会话。

发布前未提交范围使用：

```sh
python3 .codex/scripts/review_fingerprint.py
codex review -c 'sandbox_mode="read-only"' --uncommitted
python3 .codex/scripts/review_fingerprint.py
```

必须保存前后完整 fingerprint 输出并逐字节一致，内层启动头必须确认
`sandbox: read-only`。CLI exit 0 只表示命令完成，不代表通过。

成功 review 必须同时满足：

- 覆盖完整目标范围；
- 前后 fingerprint 不变；
- 内层实际只读；
- 所有 actionable findings 清零。

有 finding 时修复后回到同一 reviewer，会话复审只限定上轮 finding、修复及直接触及路径。

## 24. 发布边界

最新成功代码 review 后仍需用户针对当前 fingerprint 明确说“上线”“发布吧”或同义语句。

发布授权前禁止：

- commit；
- push；
- PR/merge；
- 部署；
- migration；
- 服务重启；
- 生产写入。

授权后 staging 前重算同 scope fingerprint。内容漂移则 review 和授权失效。

本任务预计无 migration、无配置、无业务数据写入。正常回滚只恢复上一应用 revision/镜像，
不恢复数据库。

## 25. 接手后的第一条安全动作

接手者应先向用户报告：

1. 已读取本文和五份方案；
2. 当前没有实现授权；
3. 当前 worktree/HEAD/origin-main/重叠检查结果；
4. 将在用户确认后先让测试 subagent 取得真实 RED；
5. 不会自动 commit、push、PR 或部署。

然后停止，等待明确实现授权。不要仅凭“已交给 Claude 实现”这句话假定当前 agent 已获得仓库
实现授权；如果用户在 Claude 会话中明确说“开始实现”或同义语句，才进入下一阶段。

## 26. 完成定义

实现阶段完成但尚未发布的必要条件：

- 全部目标行为已测试；
- 真实 RED 与 GREEN 均有证据；
- 默认日期栏满足实际比赛日 5+1+5；
- 40 卡上限和每日期覆盖同时满足；
- 上海日期贯穿；
- 显式 cursor/year/q 保持；
- query budget 通过；
- 1440px/390px 浏览器通过；
- Django/migration/diff 检查通过；
- 独立代码 reviewer 最终 APPROVED；
- fingerprint 已冻结；
- 没有 commit/push/PR/部署；
- 已停止等待发布授权。

## 27. 权威文件顺序

若本文与其他文件冲突，按以下顺序处理：

1. 用户在接手会话中的最新明确指令；
2. 最新 `AGENTS.md` 与 `docs/codex_workflow.md`；
3. `docs/current_state.md`；
4. 本 change 的 `spec.md`、`design.md`、`test_cases.md`；
5. `tasks.md`、`rollout.md`；
6. 本文。

不要用聊天历史、Chronicle 观察、旧 worktree、旧 reviewer 输出或本文记录的旧 SHA 取代当前
Git、文档和运行态核对。
