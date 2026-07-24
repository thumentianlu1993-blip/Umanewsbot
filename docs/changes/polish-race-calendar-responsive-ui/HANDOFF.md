# `polish-race-calendar-responsive-ui` 完整交接文档

> 历史说明：本文件记录实现前交接状态，已被 `REVIEW_HANDOFF.md` 及当前
> `spec.md`、`tasks.md`、`rollout.md` 的实现后状态取代，不再作为当前执行门禁。

## 1. 给接手 Agent 的一句话说明

这是一个已经完成只读探索、持久规格、设计和独立方案审核，但**尚未获得实现授权**的前台小型修复：

1. 让赛事日历中的每个日期直接显示月份，并消除跨年歧义；
2. 修复移动端赛事等级徽标被 flex 布局压窄的问题。

接手后不要重新走 OpenSpec，也不要立即写测试或代码。首先向用户确认：当前交接是否同时构成
“确认实现 / 开始实现 / 继续实现”的明确授权。若用户没有明确授权，只能继续只读核验和维护方案文档。

## 2. 仓库、分支与工作目录

- 仓库：`/Users/mentianlu/Code/umanews`
- 本任务独立 worktree：
  `/Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews`
- 分支：`codex/polish-race-calendar-responsive-ui`
- 当前 HEAD：`97dd2350a193c74d5063bf7432a283e4d47f6d0a`
- 当前 `origin/main`：`97dd2350a193c74d5063bf7432a283e4d47f6d0a`
- 基线提交：
  `Merge pull request #13 from thumentianlu1993-blip/codex/fix-news-body-extraction-boundaries`
- 当前 Git 状态：只有
  `docs/changes/polish-race-calendar-responsive-ui/` 为未跟踪目录；应用代码和测试尚未修改。

必须在上述独立 worktree 中工作。不要在
`/Users/mentianlu/Code/umanews` 主检出目录实现；该目录存在其他分支和大量并行改动。

接手后的第一组只读命令：

```bash
cd /Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git worktree list --porcelain
```

不要自行删除、覆盖或清理任何其他 worktree 的改动。

## 3. 强制工作流与权限边界

用户锁定的顺序是：

```text
探索
→ spec/design
→ 方案审核
→ 用户确认实现
→ 测试先行
→ 子代理实现
→ 独立 reviewer 会话 /review
→ 用户授权后发布
```

当前已完成前三步，正停在“用户确认实现”门前。

### 未取得实现授权前禁止

- 编写或修改自动化测试；
- 修改 view、模板、CSS、配置或迁移；
- 启动测试或实现 subagent；
- commit、push、创建 PR、merge、部署；
- 服务重启、数据库迁移或生产数据写入。

### 取得实现授权后仍须遵守

- 先执行第 11 节的并行变更预检；
- 所有测试与实现必须委派给 subagent；
- 先由测试 subagent 取得真实 RED，再由实现 subagent 实现；
- 写密集任务串行，subagent 不得 commit、push、建 PR、部署或写生产；
- 完成主代理验证和真实视觉验收；
- 使用未参与实现的 reviewer 实际执行原生只读 `/review`；
- code review 通过后再次停下，等待用户针对精确版本的发布授权。

### 明确禁止

- 使用任何 OpenSpec skill 或 OpenSpec CLI；
- 修改 `AGENTS.md`；
- 顺手重构整个 `public.css` 或赛事日历；
- 修改新闻正文提取、英文马名识别、新闻来源展示、新闻地区 Tab 或马匹国家 Tab；
- 修改模型、数据库字段、迁移、赛事数据或赛事状态逻辑。

## 4. 接手前必须阅读

先完整阅读仓库工作约束：

1. `AGENTS.md`
2. `docs/codex_workflow.md`
3. `docs/session_bootstrap.md`
4. `docs/project_overview.md`
5. `docs/current_state.md`
6. `docs/decisions.md`
7. `docs/deploy_runbook.md`

若后续取得发布授权，再补读：

- `docs/deploy_production.md`
- `docs/alicloud_hongkong_step_by_step.md`
- `docs/rollback_guide.md`
- `docs/backup_recovery.md`

本 change 的持久文件全部位于当前目录：

- `spec.md`：锁定需求、非目标和验收标准；
- `design.md`：探索证据、根因、DOM/CSS 契约和预计文件；
- `test_cases.md`：RED、GREEN、回归和视觉矩阵；
- `tasks.md`：唯一执行清单；
- `rollout.md`：并行冲突、发布和回滚门禁；
- `HANDOFF.md`：本交接入口。

如本文件与上述规格文件冲突，以 `spec.md`、`design.md` 和用户最新明确指令为准。

## 5. 用户问题与需求边界

### 问题 A：赛事日历月份不可读

当前日期导航主要显示 `24 / 27 / 28 / 01 / 04`。用户无法直接判断月份，跨月、跨年尤其容易误解。

要求：

- 每个日期无需依赖前后文即可识别月份；
- `2026-07-28` 与 `2026-08-01` 应清楚区分；
- 跨年时 `2026-12-31` 与 `2027-01-01` 都必须显示各自年份；
- 保留星期、today、有赛事圆点、重点赛事和日期定位状态；
- 桌面与移动端清晰，日期轴仍保持紧凑和可点击；
- 不允许写死当前月份或年份；
- 不改变 URL、筛选、cursor、分页或赛事数据语义。

### 问题 B：移动端等级徽标被压窄

移动端赛事日历中的 G1/G2/G3 等徽标退化为文字内容宽度，长标题会进一步暴露问题。

要求：

- G1、G2、G3、JPN1 等标准等级稳定为同一方框；
- 徽标不得因标题变长而 flex shrink；
- 文字水平、垂直居中；
- 长标题由标题区域换行；
- 未知或空等级有稳定回退；
- 共用该徽标的首页、日历、赛事详情和新闻赛事预告不退化；
- 不做无边界 CSS 重构。

### 非目标

- 术语归一化；
- 赛事状态自动更新；
- 出马表、赛果抓取或数据补采；
- 首页文案重命名；
- 新闻正文、英文马名、来源或地区 Tab；
- 马匹国家 Tab；
- 数据库字段、迁移；
- 整体赛事日历视觉重设计。

## 6. 已确认的代码入口与准确根因

### 日期链路

```text
GET /races/
  -> _race_calendar_queryset()
       -> timezone.localdate()
       -> RaceEvent.local_date 过滤、排序、cursor
  -> _group_race_events_by_date()
       -> 按 local_date 分组
       -> anchor_id = race-date-<ISO date>
       -> is_today
  -> public_race_calendar()
       -> groups / date_axis / previous_url / next_url
  -> race_calendar.html
```

准确根因：

- 日期轴与议程日期都使用 Django 模板 `date:"d"`，只输出日号；
- ISO 日期存在于锚点中，但没有进入可见文本；
- `RaceEvent.local_date` 是已经落定的 `DateField`，本任务不从 `race_datetime` 重新换算；
- `timezone.localdate()` 只继续用于今天判定，不应被用来硬编码当前月份。

当前状态：

- today 使用 `.today`；
- 有赛事日期使用 `.race-dot`；
- 本周重点由独立 `.focus-strip` 表达；
- 日期轴链接指向 `#race-date-YYYY-MM-DD`；
- 当前没有额外 JavaScript 选中状态。

### 徽标链路

`.grade-badge` 被以下公开页面共用：

- `feed.html`：首页近期赛事；
- `race_calendar.html`：赛事日历卡片；
- `race_detail.html`：赛事详情 hero；
- `detail.html`：新闻详情赛事预告。

准确 CSS 根因：

```css
/* 全局原有契约 */
.grade-badge {
  flex: 0 0 42px;
  height: 42px;
}

/* max-width: 599px 中的日历覆盖 */
.cal-card .grade-badge {
  flex: 0 0 auto;
}
```

全局规则缺少显式 `width/min-width/max-width`。移动规则将 basis 改回 `auto` 后，日历徽标按文字固有
宽度布局。真实 390px 临时页面曾测得：

| 标签 | 首页/详情 | 日历卡片 |
| --- | ---: | ---: |
| G1 | 42px | 18.44px |
| G2 | 42px | 20.69px |
| G3 | 42px | 20.67px |
| JPN1 | 42px | 36.09px |
| 空 | 42px | 0px |

因此问题不是 grid 列宽、数据库等级值或父容器 overflow，而是移动端 flex 覆盖与尺寸下限缺失。

## 7. 已审核通过的最终设计

### 日期显示

- 不采用月份分组标题；
- 日期轴的每一项直接显示动态 `n月j日`；
- 议程左栏显示小号月份 `.m` 加较大日号 `.day`；
- `public_race_calendar()` 根据本次 `groups` 的年份集合计算
  `date_axis_spans_years`；
- 当结果包含多个自然年时，每个有日期项都显示自身 `.date-year`；
- 单一年份结果不重复年份，减少拥挤；
- 无日期赛事继续显示“日期待定”；
- 每个议程日期提供完整日期 `aria-label`；
- today 链接增加 `aria-current="date"`；
- 使用 `agenda-day:target` 提供点击锚点后的轻量定位反馈；
- 不新增 JavaScript，不改变查询参数、anchor ID 或 cursor。

预期示例：

```text
同月：7月24日 / 7月28日
跨月：7月28日 / 8月1日
跨年：2026年 12月31日 / 2027年 1月1日
```

### 等级徽标

共享 `.grade-badge` 明确固定：

```css
flex: 0 0 42px;
width: 42px;
min-width: 42px;
max-width: 42px;
height: 42px;
line-height: 1;
white-space: nowrap;
text-align: center;
```

- 删除或覆盖移动端 `.cal-card .grade-badge { flex: 0 0 auto; }`；
- G1/G2/G3/JPN/JG 系列保持现有颜色映射；
- `.g-other` 使用中性背景、12px 字号、紧凑行高、最多两行居中，
  `white-space: normal; overflow-wrap: anywhere`；
- 四个全角字符必须完整可见，不能用裁切伪装通过；
- `.grade-badge:empty::before` 显示 `—`；
- `.cal-card-main` 保持 `min-width: 0`；
- `.cal-card-name` 增加 `overflow-wrap: anywhere`；
- 所有断点统一使用 42px，不创建第二套移动尺寸。

## 8. 预计代码与测试文件

实现范围应严格限制在：

- `server/stable/views.py`
  - 只修改 `public_race_calendar()`，增加结果是否跨年的只读 context；
- `server/stable/templates/stable/public/race_calendar.html`
  - 月日、条件年份、ARIA 和 target 所需标记；
- `server/stable/static/stable/public.css`
  - 日期排版、target、共享徽标、未知/空值和标题换行；
- `server/stable/test_race_calendar_responsive_ui.py`
  - 新建聚焦测试文件，避免抢写并行 change 修改中的 `server/stable/tests.py`；
- 本 change 文档
  - 补充实际 RED/GREEN、视觉和 review 证据。

不预计修改：

- models；
- migrations；
- `base.html`；
- 新闻、马匹、首页或赛事详情模板；
- Celery、Redis、配置或部署文件。

## 9. 测试先行与真实 RED

只有在用户明确授权实现且并行预检通过后，才启动测试 subagent。

测试 subagent 的责任：

1. 只新增 `server/stable/test_race_calendar_responsive_ui.py`；
2. 不修改 view、模板或 CSS；
3. 覆盖 `test_cases.md` 的 A1–A11 与 B1–B10；
4. 运行：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  .venv/bin/python server/manage.py test \
  stable.test_race_calendar_responsive_ui --noinput
```

可接受的目标 RED：

- HTML 中缺少月份；
- 跨年项缺少各自年份；
- today 缺少 `aria-current`；
- `.grade-badge` 缺少固定 width/min/max；
- 移动端仍存在 `flex: 0 0 auto`；
- 空等级缺少稳定占位。

不可接受的 RED：

- import 或语法错误；
- fixture 创建失败；
- migration 问题；
- locale 或环境配置错误；
- 测试自身选择器错误。

CSS 静态测试必须解析具体 selector block，不能用全文件模糊搜索 `42px` 造成假 GREEN。

## 10. 实现后的验证矩阵

### 自动化与静态验证

至少运行：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  .venv/bin/python server/manage.py test \
  stable.test_race_calendar_responsive_ui \
  stable.tests.RaceEventPageMVPTests --noinput

DB_ENGINE=sqlite .venv/bin/python server/manage.py check
DB_ENGINE=sqlite .venv/bin/python server/manage.py makemigrations --check --dry-run
git diff --check
```

还要运行：

- 赛事日历 view/template 回归；
- 首页近期赛事、赛事详情、新闻赛事预告回归；
- 并行公共导航 change 的联合回归；
- 必要的完整 `stable` 回归；
- 模板真实渲染验证。

### 真实视觉验收

使用仓库外临时 SQLite 数据和真实 Django 页面。临时数据库、截图或浏览器产物不得加入发布范围。

| 视口 | 必查内容 |
| --- | --- |
| 1440px | 同月、跨月、跨年；桌面横向卡布局；G1/G2/G3/JPN1/未知/空等级 |
| 390px | 连续徽标均为 42×42；长中英文标题；today/target/race-dot；无页面横向溢出 |
| 375/320px | 仅在 390px 暴露窄屏风险时补验最长标题、跨年和未知等级 |

保存的可审计数据至少包括：

- `window.innerWidth`；
- `documentElement.clientWidth` 与 `scrollWidth`；
- 每个 badge 的 label、width、height、computed flex/min-width；
- 四全角字符 `.g-other` 的 client/scroll width 与 height；
- 日期轴可见文本与 href；
- today、target、race-dot、focus 状态；
- console error；
- 必要截图。

四全角字符必须满足：

```text
scrollWidth <= clientWidth
scrollHeight <= clientHeight
```

历史探索中的 390px 结果是真实本地 Django 渲染。桌面浏览后端当时只能稳定返回 1280 CSS pixels，
因此不能把旧结果声称为 1440px 验收；实现后必须重新取得真实 1440px 证据。

## 11. 与并行公共页面 change 的强制预检

主要并行 change：

`/Users/mentianlu/Code/umanews/.worktrees/simplify-public-navigation-and-attribution`

本交接编写时的快照：

- HEAD：`97dd2350a193c74d5063bf7432a283e4d47f6d0a`
- 分支：`codex/simplify-public-navigation-and-attribution`
- 仍有未提交实现；
- 修改或新增包括：
  - `server/stable/views.py`
  - `server/stable/static/stable/public.css`
  - `server/stable/models.py`
  - 多个公共模板
  - `server/stable/tests.py`
  - `server/stable/test_public_navigation_and_attribution.py`
  - migrations `0054`、`0055`
  - 其 change 文档

本任务与其明确共享：

| 文件 | 本任务 hunk | 并行 change 当前意图 | 风险 |
| --- | --- | --- | --- |
| `views.py` | `public_race_calendar()` | 新闻/马匹 list 与首页 helper | 同文件，不同函数；必须重查 |
| `public.css` | `.grade-badge`、`.date-axis`、`.agenda-*`、`.cal-card` | 新闻来源/Tab/马匹相关规则 | 同文件，不同 selector；必须联合回归 |
| `race_calendar.html` | 本任务修改 | 不在其已知范围 | 当前不重叠 |
| `tests.py` | 本任务不修改 | 对方已修改 | 通过新测试文件避冲突 |

对方工作树混有超出其初始公开导航范围的 model/migration，说明它目前不能视为稳定可 rebase 版本。

启动测试 subagent 前必须重新记录：

```bash
git -C /Users/mentianlu/Code/umanews/.worktrees/simplify-public-navigation-and-attribution \
  status --short
git -C /Users/mentianlu/Code/umanews/.worktrees/simplify-public-navigation-and-attribution \
  rev-parse HEAD
git -C /Users/mentianlu/Code/umanews/.worktrees/simplify-public-navigation-and-attribution \
  diff --name-only
```

只有下列条件之一成立才可继续：

1. 前序 change 的修改范围已稳定并冻结；
2. 本 worktree 基于它的最新审核版本完成 rebase/merge，并重新核验设计前提；
3. 双方 owner 明确锁定共享文件中的非重叠 function/selector hunk。

若对方修改了以下任何目标，立即暂停并更新方案，必要时重新做方案审核：

- `.grade-badge`
- `.cal-card`
- `.date-axis`
- `.agenda-*`
- `public_race_calendar()`
- `race_calendar.html`

用户的“确认实现”不会自动绕过这个技术门禁。

## 12. 方案审核记录

方案由未参与编写的独立 reviewer 审核。

首轮结论：`REVISE`

- 1 项 high：四个全角字符在 42px 框中的完整回退未锁死；
- 1 项 medium：agenda DOM 契约与测试断言不一致；
- 1 项 medium：并行 change 状态可能漂移，缺少可执行的实现前门禁。

修订后复用同一 reviewer 会话进行限定复审。第一次限定复审仍为 `REVISE`，唯一原因是并行文件清单
漏记新增 migration `0055`。补齐后第二次限定复审以及最终状态复核均为：

```text
VERDICT: APPROVED
```

残余风险只有活跃并行 change，因此 `tasks.md` 的 1.1 是不可跳过的硬门禁。

## 13. 独立代码审核要求

实现、主代理回归和视觉验收完成后：

1. 启动一个未参与测试或实现的 reviewer；
2. reviewer 必须实际执行 Codex 原生只读 `/review`；
3. 审核输入锁定为当前 worktree、基线、修改文件和 fingerprint；
4. 有 actionable finding 时交回实现 subagent 修复；
5. 每项修复必须有对应 RED/GREEN 或明确验证证据；
6. 复用同一个 reviewer 会话，只复审 finding、修复和直接触及路径；
7. 最新 review 成功后停止，向用户提交 fingerprint、测试、视觉结果和残余风险。

不要把“主代理自查”或普通文字点评当成独立 `/review`。

## 14. 发布门禁

代码审核通过并不构成发布授权。必须再次取得用户对当前受审版本的明确授权，才可：

- commit；
- push；
- 创建 PR；
- merge；
- 部署；
- 重启服务；
- 写入生产。

本 change 无 schema/data 变化，正常不应执行数据库迁移。发布时仍需核对：

- 精确 Git HEAD 与镜像；
- `web / worker / beat / race_live_worker` 镜像一致；
- Django check 与 migration plan；
- collectstatic；
- 内外 `/healthz/`；
- `/races/`、跨月、跨年 cursor、首页和赛事详情 smoke；
- 1440px/390px 生产页面；
- console 与横向 overflow。

## 15. 文档回写

实现阶段只在本 change 目录记录实际 RED/GREEN、视觉和 review 证据，避免提前抢写共享状态文档。

真正完成发布后，再按实际证据更新：

- `docs/current_state.md`
- `docs/project_status.md`
- `docs/deploy_runbook.md`
- 有新决策时的 `docs/decisions.md`
- 本 change 的 `release_report.md`

不要在没有生产证据时把“代码预期”写成“当前生产状态”。

## 16. 接手 Agent 的下一步清单

### 若用户尚未明确授权实现

1. 阅读第 4 节全部文件；
2. 核对当前 worktree 与并行 change 快照；
3. 向用户说明方案已 `APPROVED`、当前仍停在实现门；
4. 等待“确认实现 / 开始实现 / 继续实现”或明确同义授权。

### 若用户明确授权实现

1. 执行第 11 节并行预检并把结果写回 `rollout.md`；
2. 只有门禁通过后，启动测试 subagent；
3. 取得目标行为真实 RED；
4. 串行启动实现 subagent；
5. 主代理完成全部 GREEN、回归和视觉验收；
6. 启动未参与实现的独立 code reviewer；
7. findings 清零后向用户汇报并停止；
8. 等待新的发布授权。

### 当前绝对不要做

- 不要因交接发生而默认用户已经授权实现；
- 不要重做或替换已批准设计；
- 不要运行 OpenSpec；
- 不要先改 CSS 再补测试；
- 不要吸收并行 worktree 中未归属的 model/migration；
- 不要 commit、push、建 PR 或部署。
