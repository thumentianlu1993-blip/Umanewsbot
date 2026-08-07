# 赛事日历月份与等级徽标发布与并行方案

## 当前状态

当前已完成方案审核、测试先行、应用实现、21 项聚焦 GREEN、Django/迁移检查和
1440px/390px/320px 真实浏览器验收。独立原生代码 review 首轮结论为 `REVISE`：
固定日期测试未冻结视图时钟、worktree 本地 `.venv` 绝对路径 symlink 会污染发布范围、
durable status 未同步。三项均已做窄修复，等待同一 reviewer 会话限定复审。


## 基线与 worktree

- worktree：
  `/Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews`
- 分支：`codex/polish-race-calendar-responsive-ui`
- 基线：`origin/main@97dd2350a193c74d5063bf7432a283e4d47f6d0a`
- 独立验证时 `origin/main@97a38cf5e2a692b7336c8518a4cdd6dfcc511d2a`，本分支落后 12 个提交；
  相关上游提交未修改本 change 的 `views.py`、日历模板或 `public.css` hunk。
- 基线已包含 `fix-news-body-extraction-boundaries` PR #13。
- 原主检出目录有大量既有未提交改动且位于另一个无 `codex/` 前缀分支，本任务不触碰该目录。

## 并行 change 边界

### 后台新闻链路

- `fix-news-body-extraction-boundaries` 已进入本任务基线，不再作为未合并实现来源。
- `fix-external-english-horse-context-gate` 的服务/测试与本任务无业务耦合。
- 本任务禁止修改新闻 adapter、正文提取、术语/马名识别、历史新闻或生产数据。

### `simplify-public-navigation-and-attribution`

首次探索时该 worktree 与本任务同基线 `97dd2350`，只有文档和测试改动。独立方案审核期间它已经
进入实现；限定复审前重新核对的 HEAD 仍为 `97dd2350`，但工作树当前包含：

- `server/stable/views.py`
- `server/stable/static/stable/public.css`
- `server/stable/models.py`
- `feed.html`、`_headline.html`、`_article_card.html`、`_hot_list.html`
- `detail.html`、`base.html`、`horse_index.html`
- `server/stable/tests.py`
- `server/stable/test_public_navigation_and_attribution.py`
- `server/stable/migrations/0054_add_horse_profile_stats_fields.py`
- `server/stable/migrations/0055_allow_null_horse_profile_primary_term.py`
- `docs/changes/simplify-public-navigation-and-attribution/`

其中 model/migration 超出该 change 已批准的原公开导航方案，进一步说明当前工作树尚未形成可直接
rebase 的稳定版本。本任务不判断或吸收这些额外改动，只把它们视为实现前必须重新核对的漂移。

明确交集与边界：

| 文件 | 本任务边界 | 前序 change 边界 | 结论 |
| --- | --- | --- | --- |
| `server/stable/views.py` | `public_race_calendar()` 跨年布尔值 | 新闻/马匹 list、旧 region 归一化、首页赛事 helper | 同文件不同函数/hunk |
| `server/stable/static/stable/public.css` | `.grade-badge`、P2 日期轴/日历卡、599px cal-card | 新闻来源、Tab 删除后的间距、马匹专用死规则 | 同文件不同 selector；需联合回归 |
| `race_calendar.html` | 月日/年份/状态 | 明确非前序 change 范围 | 不重叠 |
| `base.html`/新闻/马匹模板 | 不修改 | 前序 change 修改 | 不重叠 |
| `server/stable/tests.py` | 不修改，新建聚焦测试文件 | 已修改 | 避免写冲突 |

进入实现前、启动测试 subagent 之前必须完成 tasks 1.1，记录当时的精确 HEAD、修改文件全集和以下
共享 hunk 状态，并满足以下任一条件：

1. 前序 change 修改范围已稳定并冻结；或
2. 本 worktree 已基于其最新审核版本 rebase/merge 并重做方案前提检查；或
3. 双方 owner 明确保持上表 selector/function/hunk 边界，确认不重叠，并把锁定结果写入本文件。

若前序 change 改动 `.grade-badge`、`.cal-card`、`.date-axis`、`.agenda-*`、
`public_race_calendar()` 或 `race_calendar.html`，视为边界变化，停止实现并更新方案/测试；不能只靠
Git 自动合并判断安全。若前序 change 仍混有未归属的 model/migration 或无法给出稳定 owner 边界，
本任务保持阻塞，不启动测试 subagent。

### 2026-07-24 task 1.1 预检结果


**并行 change worktree 快照**：

- 路径：`/Users/mentianlu/Code/umanews/.worktrees/simplify-public-navigation-and-attribution`
- HEAD：`97dd2350a193c74d5063bf7432a283e4d47f6d0a`
- 修改文件：
  - `server/stable/static/stable/public.css`（删除 `.hero-kicker .dot`、`.region-mark`、`.region-label`、`.feed-card-source`、`.source-box`、`.horse-region-tabs` 等旧规则）
  - `server/stable/views.py`（新增 `PUBLIC_REGION_COLORS`、`_redirect_legacy_region()`；移除 `_public_published_articles`/`_public_today_races`/`_public_next_key_race` 的 `region` 参数）
  - `server/stable/templates/stable/public/_article_card.html`
  - `server/stable/templates/stable/public/_headline.html`
  - `server/stable/templates/stable/public/_hot_list.html`
  - `server/stable/templates/stable/public/base.html`
  - `server/stable/templates/stable/public/detail.html`
  - `server/stable/templates/stable/public/feed.html`
  - `server/stable/templates/stable/public/horse_index.html`
  - `server/stable/tests.py`
  - 未跟踪：`server/stable/test_public_navigation_and_attribution.py`、`docs/changes/simplify-public-navigation-and-attribution/`
  - **无 migration 文件**（`0054`/`0055` 不存在于当前工作树）

**共享 hunk 冲突检查**：

| 目标 selector/函数 | 并行 change diff 中命中 | 结论 |
| --- | --- | --- |
| `.grade-badge` | 无 | ✅ 安全 |
| `.cal-card` | 无 | ✅ 安全 |
| `.date-axis` | 无 | ✅ 安全 |
| `.agenda-*` | 无 | ✅ 安全 |
| `public_race_calendar()` | 无 | ✅ 安全 |
| `race_calendar.html` | 无 | ✅ 安全 |

**门禁判定**：条件 1 满足 — 前序 change 修改范围已稳定，与本任务共享文件中的 target hunk 完全不重叠。条件 3 也满足 — 双方 owner 已通过 `design.md`/`rollout.md` 锁定 selector/function/hunk 边界，实际 diff 确认不重叠。

**结论**：✅ 门禁通过，允许启动测试 subagent。

## 发布前门禁

2. 测试 subagent 取得真实 RED；实现 subagent 串行完成 GREEN。
3. 主代理完成聚焦、相邻、联合和必要完整回归，Django check、无迁移、模板与 diff 检查。
4. 完成 1440px/390px 和必要窄屏真实视觉验收。
5. 未参与实现的 reviewer 按 fingerprint 规则完成原生只读 code review，actionable finding 清零。
7. staging 前重算相同 scope fingerprint；stage 后核对 approved parent、内容 hash 与工作树状态。

## 生产发布与验收


1. 核对生产 HEAD、镜像、容器状态和并行公共页面 change 是否已合并。
2. 建立并验证常规数据库与 `.env` 恢复点；虽然本 change 不写业务数据，仍遵守门户发布 runbook。
3. 使用低成本 Compose 发布并核对 `web / worker / beat / race_live_worker` 镜像一致。
4. 运行 Django check、migration plan/无新增迁移、collectstatic、内外 `/healthz/`。
5. smoke `/races/`、跨月窗口、跨年 cursor、一个赛事详情和首页近期赛事。
6. 真实 1440px/390px 复核月份、年份、徽标、长标题、today/target、overflow 和 console。
7. 不执行数据库迁移、服务外生产写入、赛事补采或历史数据重处理。

## 回滚

- 无 schema/data 变更，首选回滚到部署前应用 commit/镜像并重建全部应用服务。
- 回滚后验证 Django check、healthz、首页、赛事日历、赛事详情和新闻详情赛事预告。
- 不恢复数据库，除非另有与本 change 无关的数据损坏证据。
- 不在线编辑容器 CSS/template 作为长期修复。

## 文档与证据

- 实现前后只维护本 change 目录和受审代码/测试范围，避免抢写共享状态文档。
- 实际发布后按 evidence-only allowlist 向 `docs/current_state.md`、`docs/project_status.md`、
  `docs/deploy_runbook.md`、必要的 `docs/decisions.md` 和本任务 `release_report.md` 追加事实。
- evidence-only patch 不夹带代码、测试、配置、迁移、spec、tasks、skills 或 agents 变更，并复用
  同一 code reviewer 会话审核。
