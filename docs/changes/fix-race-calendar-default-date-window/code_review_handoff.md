# `fix-race-calendar-default-date-window` 代码审查交接（自包含）

> 交接对象：Codex 代码 reviewer（新一轮独立审查）
> 编写日期：2026-07-28
> 编写者：Claude（本任务的实现协调方）
> 本文目标：不依赖任何聊天记录/其他会话上下文，即可对当前未提交改动开展完整代码审查
> 阅读时间：约 15 分钟；审查时请同时核对本文声明与仓库实际内容是否一致

## 0. 审查任务与边界

你是未参与本轮实现的独立 reviewer。请对 worktree 当前**全部未提交改动**执行只读审查。

你必须遵守：

- 全程只读：不得修改、创建、删除任何文件；不得 commit、push、建 PR、部署、联网、写生产。
- 审查命令（在本 worktree 根目录执行，codex CLI 不在 PATH 上，用完整路径）：

  ```sh
  python3 .codex/scripts/review_fingerprint.py          # 审前指纹，保存完整原始 stdout
  /Applications/ChatGPT.app/Contents/Resources/codex review -c 'sandbox_mode="read-only"' --uncommitted
  python3 .codex/scripts/review_fingerprint.py          # 审后指纹，与审前逐字节一致
  ```

- 内层启动头必须实际报告 `sandbox: read-only`；CLI exit 0 只表示命令完成，不等于通过。
- 审查通过（APPROVED）需同时满足：原生 review 覆盖完整未提交范围；审前/审后
  fingerprint 逐字节一致；内层实际只读；所有 P0-P3 及 actionable findings 清零。
- 若有 findings：按严重度列出（文件、定位、说明），结论 REVISE 或 BLOCKED。
- 项目工作流细节见 `AGENTS.md` 与 `docs/codex_workflow.md` 第 7 节（与本文冲突时以它们为准）。

## 1. 仓库、worktree 与基线

- 主仓库：`/Users/mentianlu/Code/umanews`
- 本任务 worktree（审查目录）：`/Users/mentianlu/Code/umanews/.worktrees/fix-race-calendar-default-date-window`
- 分支：`codex/fix-race-calendar-default-date-window`
- 基线：`HEAD == origin/main == 7385f59ab87bcce5193f3313ecca6809b165ad89`（审查前请重新
  `git rev-parse HEAD origin/main` 核对，不要凭本文记录假定）
- 工作树状态：8 个 tracked 修改 + 11 个 untracked 叶子（2 个代码文件 + 本目录 7 个
  Markdown 文档与 2 张浏览器验收截图）。除本目录文件与下列第 4 节清单外，不应出现其他改动。

## 2. 产品背景与根因

Umanews/UmaFans 是面向中文用户的赛马新闻与赛事资料平台（Django/PostgreSQL/Celery/Redis/
Docker Compose/Nginx）。公开赛事日历入口 `GET /races/`，由
`server/stable/views.py` 的 `public_race_calendar` → `_race_calendar_queryset` 处理。

修复前行为（根因，三件事共同造成"日期栏停留在旧窗口"）：

1. 默认模式（无 `year`/`q`/合法 `cursor`）按 `timezone.localdate() ± 30` 个**连续自然日**过滤；
2. 按日期升序在赛事对象层截取前 40 场（`RACE_CALENDAR_PAGE_SIZE`）；
3. 日期栏从这 40 场反推。

例：2026-07-27 的查询下界恰为 2026-06-27；赛事密集时前 40 场在 2026-07-19 耗尽，日期栏
就停在 6/27–7/19。已排除硬编码日期、UTC 偏移、页面缓存、JS 固定日期等原因。

## 3. 目标行为合同（审查核对称）

### 3.1 默认模式判定

仅当**没有**以下显式浏览意图时进入新默认窗口逻辑：

- 合法 `direction=past|future` 且 `cursor` 可被 `datetime.fromisoformat` 解析（独占边界分页，行为逐字保留）；
- `year=YYYY`（年度模式，保留）；
- 非空 `q`（跨年度名称搜索，保留）。

非法或不完整 cursor（无法解析、或 direction 非 past/future）必须安全回退默认模式，不得再
落入旧代码"无边界截取全库前 40 场"分支。

### 3.2 上海今日与锚点

- view 以 `timezone.localdate(timezone=ZoneInfo("Asia/Shanghai"))` **只计算一次**
  `shanghai_today`，显式传入日期窗口服务、`_group_race_events_by_date`、
  `_public_race_status_label`、`_public_weekly_focus_events` 与模板上下文；日历请求路径上
  不再有裸 `timezone.localdate()`。
- 锚点（在当前 tab/region/grade/when 筛选后的公开集合内）：今天有赛事→今天；否则未来最早
  比赛日；否则最近历史比赛日；都没有→无锚点空状态。

### 3.3 5+1+5 平衡窗口

- 锚点前最多 5 个实际比赛日 + 锚点 + 锚点后最多 5 个；一侧不足从另一侧按离锚点由近及远
  补足；升序、唯一、≤11、必含锚点；不补造无赛事自然日；总量不足 11 只显示实际数量。
- 数据层恰好两条有界聚合查询：`local_date <= today` 倒序最多 11 个 distinct 日期、
  `local_date > today` 升序最多 11 个，均以 `Min("id")` 聚合该日代表赛事 ID
  （SQLite/PostgreSQL 语义一致，不依赖仅 PG 特性）。

### 3.4 公开资格一致性

日期窗口与赛事列表复用同一基础 queryset（`_public_race_calendar_base_queryset`）：
`visibility_status=published`、排除 `canonical_product_links__is_active=True`、tab=key 时仅
P0/P1 或 is_featured、应用 region/grade/when。不以 `data_quality_status` 为门禁（现状语义，
不得新增）。read-gate 展示 annotation（`public_current_result_revision_id`、
`public_projection_write_owner`）只加在最终赛事对象查询上，不得污染日期聚合。
默认模式只承认 `local_date` 非空的实际比赛日；日期待定赛事仅在显式 year/q 模式展示。

### 3.5 40 卡上限与每日期覆盖

- 保留 `RACE_CALENDAR_PAGE_SIZE = 40`。
- 默认赛事查询一条 SQL：`Case(When(pk__in=representative_ids, then=0), default=1)` 优先 +
  现有 `local_date/local_start_time/id` 排序，截 `[:40]`，`prefetch_related("results")` 保留。
- 取回后在 Python 恢复时间升序，排序键
  `(local_date, local_start_time is None, local_start_time or time.min, pk)`——
  `local_start_time` 为 None 的排在当天定时赛事**之后**，对齐生产 PostgreSQL
  `ORDER BY ... ASC` 的 NULLS LAST 语义（这是第一轮 review 的 P2 修复点，请重点核对）。
- 结果：日期栏每个日期必须有对应 agenda group 且至少一张同资格赛事卡。

### 3.6 模板与标记

- 日期轴链接：锚点带 `data-calendar-anchor` 属性与 `anchor` class；今天锚点同时有
  `today` class + `aria-current="date"`；未来/历史回退锚点用 `aria-current="true"` 且无
  today class；全页恰好一个 `data-calendar-anchor`。
- 仅默认模式（`default_anchor_date` 非空）输出最小脚本：DOM ready 后只设置 `.date-axis`
  的 `scrollLeft` 使锚点水平居中；不用 `scrollIntoView`、无动画、不改 URL/hash、不影响
  页面纵向滚动。显式 cursor/year/q 模式不输出该脚本。
- CSS 只为 `.date-axis a.anchor:not(.today)` 增加轻量强调（粗体 + `--gold` 下划线），
  不改卡片布局与 `.grade-badge` 42×42。

### 3.7 缓存

不新增缓存。`/races/` 无页面缓存；既有年份列表缓存与 sitemap 计数缓存与默认锚点无关。
每个默认请求重新读取上海日期与 distinct 比赛日，跨日不需要失效。

## 4. 改动文件清单（精确全集）

代码与测试：

| 文件 | 性质 | 说明 |
|---|---|---|
| `server/stable/services/race_calendar.py` | 新增 | `select_balanced_race_dates` 纯函数；`DefaultRaceDateWindow` dataclass；`public_default_race_date_window`（两条有界聚合） |
| `server/stable/views.py` | 窄改 | 拆分 `_public_race_calendar_base_queryset`；`_race_calendar_queryset(request, *, today)` 三模式分派 + 代表赛事优先 40 卡；`_group_race_events_by_date(events, *, today, anchor_date=None)` 增加 `is_anchor`；`_public_weekly_focus_events` 增加可选 `today`；`public_race_calendar` 计算 `shanghai_today` 并传 `default_anchor_date`；删除不再引用的 `RACE_CALENDAR_WINDOW_DAYS` |
| `server/stable/templates/stable/public/race_calendar.html` | 窄改 | 日期轴链接 anchor/today/aria 标记；仅默认模式的 scrollLeft 居中脚本 |
| `server/stable/static/stable/public.css` | 窄改（+2 行） | `.date-axis a.anchor:not(.today)` 粗体与金色下划线 |
| `server/stable/test_race_calendar_default_date_window.py` | 新增 | 41 个用例（33 view 级 + 8 纯函数） |
| `server/stable/tests_legacy.py` | 窄改 | `test_calendar_query_count_stays_bounded_for_initial_window` 预算 8→10（获批预算，注释注明依据） |
| `server/stable/test_realtime_race_results.py` | 窄改 | live gate 预算 12→14、official gate 20→22；4 个日历用例创建后补 `local_date = timezone.localdate()`（新默认模式不展示无日期赛事；未改共享 fixture） |
| `server/stable/test_race_calendar_responsive_ui.py` | 窄改 | A8 日期待定改显式 `q="A8"` 请求；A6 断言放宽为 `class="today anchor"`（与新锚点标记合同一致） |

文档（本目录方案文档 + 状态文档）：`docs/changes/fix-race-calendar-default-date-window/`
全部（含 `acceptance_1440.png`/`acceptance_390.png` 两张验收截图）、
`docs/current_state.md`、`docs/project_status.md` 本任务条目。

不应出现：models/migrations/settings/Celery/tasks/首页/赛事详情页/部署配置的改动。

## 5. 已执行的验证证据（请复核必要时重跑）

测试环境：`cd server && /Users/mentianlu/Code/umanews/.venv/bin/python manage.py test <module>`
（SQLite）。

- TDD：先取得真实 RED（冻结 `today=2026-07-27`：11 个实际比赛日含 ±30 天外日期、日期栏
  应精确等于这 11 日——旧代码失败；今天无赛事且最近未来比赛日 >30 天应锚定未来——旧代码
  返回空窗口）。实现后新增聚焦测试 **41/41 GREEN**。
- 回归：`stable.test_race_calendar_default_date_window + stable.test_race_calendar_responsive_ui`
  62/62；`stable.test_realtime_race_results` 中 4 个日历 read-gate 用例 4/4；
  `stable.tests.test_page_regression + stable.test_public_navigation_and_attribution +
  stable.tests.test_race_result_recovery_application_pages` 44/44；
  `manage.py check`、`makemigrations --check --dry-run`、`git diff --check` 通过。
- 既有失败（改动前即存在，已用 stash 基线对照证实，与本任务无关）：
  `stable.test_realtime_race_results.RaceLiveTheRacingApiFreeRunnerTests` 9 个；
  `stable.tests_legacy.RaceEventPageMVPTests` 3 个（`import_race_events` 的 current-year CSV
  CommandError）。
- 查询预算实测（基线 → 改后，恰为 +2 条有界日期聚合）：轻量默认 3→5（预算 ≤10）；
  40 卡 live read gate 12→14（≤14）；40 卡 official/corrected 12→14（≤22）；
  canonical 年份模式不进入默认窗口（预算 ≤12 不变）。
- 真实浏览器验收（本地临时 SQLite + runserver + Chrome DevTools）：
  1440px 11 个比赛日全可见；390px 与 320px 锚点居中于日期轴可视区（中心偏移 -12px）、
  仅水平滚动（scrollLeft>0）、页面纵向 scrollY=0、无横向 overflow、G1/G2/G3 徽标 42×42；
  显式 cursor/q 模式无 `data-calendar-anchor`、无定位脚本、scrollLeft=0；
  控制台唯一错误为开发环境 favicon 404（与本改动无关）。

## 6. 既有审核记录

- 方案审核（实现前）：独立方案 reviewer 首轮 REVISE（3 项 P1：上海日期未贯穿 today 标记；
  11 日全量赛事缺 40 卡边界；移动端锚点初始不可见），修订后同会话复审 APPROVED。
- 代码审核第 1 轮（上一 Claude reviewer 会话，agentId `a2c900bbc44ffa26f`）：REVISE，
  2 项 P2：
  1. Python 重排把 `local_start_time IS NULL` 排到定时赛事前（SQLite NULLS FIRST），
     与生产 PostgreSQL NULLS LAST 不一致 → 已修复为 `is None` 排后；
  2. `docs/current_state.md` 本任务条目停留在"未写测试或应用代码" → 已重写为真实状态。
- 代码审核第 2 轮（同一 reviewer 会话限定复审）：**APPROVED**，无新增 findings，审前/审后
  fingerprint 逐字节一致。冻结基线：approved parent `7385f59ab87bcce5193f3313ecca6809b165ad89`，
  content_manifest_sha256 `6dd3948cc4c1b275fe6fc6b63a47707fb468067fc7285c6b2ce1a076b26bb065`。
  **注意：本文档是第 2 轮 APPROVED 之后新增的，因此该指纹对当前工作树已自然失效；
  你本轮审查需建立新的指纹基线。**
- 代码审核第 3 轮（应用户要求追加的全新 Codex 独立审查，session
  `019fa932-ca46-7b23-a2d6-c9fc9381cca7`，即按本文档执行的那一轮）：代码实现未发现
  问题，范围/指纹/只读均满足，但首轮 REVISE——1 项 P2：`docs/current_state.md` 与
  矛盾，错误提前推进工作流状态。已修复：两个标题改为"处于代码复审门禁"，正文同步
  记录本轮 REVISE 与修复事实，待同一 Codex 会话限定复审关闭。

## 7. 建议的审查重点（不限制你的独立判断）

1. `views.py` 默认/显式模式分派：合法 cursor、非法 cursor、year/q 优先级与旧行为逐字对比；
   `direction=past` 的反转是否仍只作用于显式模式。
2. `race_calendar.py` 纯函数补足逻辑的边界（两侧都不足、总量 <11、anchor 恰为边界日期、
   limit 裁剪仍含 anchor）。
3. 代表赛事优先策略：40 卡截取是否保证每个窗口日期至少一卡；`Min("id")` 代表资格是否与
   列表资格一致；SQLite/PG 语义一致性。
4. NULL 时刻排序（第 6 节 P2 修复点）与生产 PG 语义对齐。
5. `shanghai_today` 是否真正单次计算并贯穿；日历请求路径是否还有裸 `timezone.localdate()`。
6. 模板脚本：是否仅默认模式输出、只改 scrollLeft、不碰纵向滚动/URL；aria 与 class 组合
   （today+anchor、单独 anchor、单独 today）。
7. 测试窄改是否与获批预算和行为变更一一对应，有无借机放宽无关断言。
8. 改动是否越出第 4 节清单（模型/迁移/配置/任务/其他页面）。

## 8. 返回要求

- 审前/审后 FINGERPRINT_SHA256、content_manifest_sha256、summary.head 与一致性结论；
- codex review 命令、真实退出码、内层启动头 sandbox 行；
- findings 清单（severity/文件/定位/说明）或"无 actionable findings"声明；
- 最终 VERDICT（APPROVED / REVISE / BLOCKED）与残余风险。
