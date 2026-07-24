# `polish-race-calendar-responsive-ui` — Code Review 交接文档

> 当前状态（2026-07-24）：第二份 handoff。首份 handoff 对应的 review session
> `019f9233-c39b-73e0-9b08-83f831cffd23` 首轮结论 `REVISE`（3×P2），三项 finding
> 已完成窄修复并 rebase 到最新 `origin/main`。**请以本文件所述的最新代码状态为准，从零开始
> 独立审查。**

## 1. 给 Reviewer 的一句话

这是赛事日历的两个小型前台修复 change（日期显示月份 + 移动端徽标固定尺寸）。实现、测试、视觉验收、首轮 review 和 finding 修复均已完成。现在需要你基于当前精确代码状态执行完整只读审查，不依赖之前的 review 上下文。

## 2. 仓库与分支

- 仓库：`/Users/mentianlu/Code/umanews`
- 本任务独立 worktree：
  `/Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews`
- 分支：`codex/polish-race-calendar-responsive-ui`
- 当前 HEAD：`438ab6a14f9665fd77318d8c12f8bc5a3ca63690` (= `origin/main`，已 rebase)
- 首次基线：`97dd2350a193c74d5063bf7432a283e4d47f6d0a`（`fix-news-body-extraction-boundaries` PR #13）
- 当前 `origin/main` 领先基线 19 个提交（含 `simplify-public-navigation-and-attribution` PR #16 等），
  本分支已 rebase 到最新 `origin/main`，零冲突。

必须在上述独立 worktree 中工作。

接手的只读命令：

```bash
cd /Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

## 3. Change 概述

两个小型前台修复：

### 问题 A：赛事日历日期月份不可读

当前日期导航只显示日号（`24 / 27 / 28 / 01`）。用户无法判断月份，跨月/跨年尤其容易误解。

**修复**：
- 日期轴每项显示 `n月j日`
- 跨年时每项额外显示 `Y年`
- 保留星期、today、race-dot、focus-strip
- 新增 `aria-current="date"`、`aria-label` 和 `agenda-day:target` 定位反馈

### 问题 B：移动端等级徽标被压窄

移动端（≤599px）`.cal-card .grade-badge { flex: 0 0 auto }` 覆盖全局规则，徽标退化为文字宽度（实测 G1 18px、JPN1 36px、空等级 0px）。

**修复**：
- `.grade-badge` 显式声明 width/min-width/max-width/height 均为 42px
- 移动端覆盖改为 `flex: 0 0 42px`
- 新增 `.g-other`（未知等级回退）、`.grade-badge:empty::before`（空等级占位）
- `.cal-card-name` 增加 `overflow-wrap: anywhere`

## 4. 修改文件清单

仅以下 4 个文件有变更：

### 4a. `server/stable/views.py`（+2 行）

```diff
 groups = _group_race_events_by_date(events)
+date_axis_spans_years = len({group["date"].year for group in groups if group["date"]}) > 1
```

```diff
 "date_axis": [group for group in groups if group["date"]],
+"date_axis_spans_years": date_axis_spans_years,
```

- `date_axis_spans_years` 只读计算：对当前结果中的非空日期取年份集合，如果 > 1 个自然年则为 True
- 不改变查询语义、cursor、分页或 URL
- `public_race_calendar_years()` 导入和调用保持原样

### 4b. `server/stable/templates/stable/public/race_calendar.html`（+5/-3 行）

**日期轴**（行 53-54）：
```django
<a class="{% if group.is_today %}today{% endif %}" {% if group.is_today %}aria-current="date"{% endif %} href="#{{ group.anchor_id }}">
  <b>{% if date_axis_spans_years %}<span class="date-year">{{ group.date|date:"Y年" }}</span>{% endif %}{{ group.date|date:"n月j日" }}</b>
```

**议程日期**（行 92-97）：
```django
<header class="agenda-date {% if group.is_today %}today{% endif %}" {% if group.date %}aria-label="{{ group.date|date:'Y年n月j日' }}"{% endif %}>
  {% if group.date %}
    {% if date_axis_spans_years %}<div class="date-year">{{ group.date|date:"Y年" }}</div>{% endif %}
    <div class="m">{{ group.date|date:"n月" }}</div>
    <div class="d">{{ group.date|date:"j日" }}</div>
    <div class="w">{{ group.date|date:"D" }}{% if group.is_today %} · 今天{% endif %}</div>
```

"日期待定"回退保持不变。

### 4c. `server/stable/static/stable/public.css`（+26/-2 行）

**徽标尺寸固定**（全局 `.grade-badge`）：
```css
.grade-badge {
  flex: 0 0 42px;
  width: 42px;
  min-width: 42px;
  max-width: 42px;
  height: 42px;
  line-height: 1;
  white-space: nowrap;
  text-align: center;
  /* 原有属性保留: display, align-items, justify-content, font, color, background */
}
```

**空等级占位**：
```css
.grade-badge:empty::before {
  content: "—";
}
```

**未知等级回退**（新增）：
```css
.grade-badge.g-other {
  font-size: 12px;
  line-height: 1.2;
  white-space: normal;
  overflow-wrap: anywhere;
  padding: 2px;
}
```

**日期排版**（新增/修改）：
```css
.date-axis a b { /* 已有 */ white-space: nowrap; }
.date-year { font-size: 11px; color: var(--ink-3); }
.agenda-date .m { font-size: 14px; color: var(--ink-3); font-weight: 700; }
```

**目标定位反馈**（新增）：
```css
.agenda-day:target { outline: 2px solid var(--gold); outline-offset: 4px; border-radius: var(--radius); }
```

**标题换行**（修改）：
```css
.cal-card-name { /* 已有... */ overflow-wrap: anywhere; }
```

**移动端覆盖修复**（修改，行 1708）：
```css
/* 原: .cal-card .grade-badge { flex: 0 0 auto; } */
.cal-card .grade-badge { flex: 0 0 42px; }
```

### 4d. `server/stable/test_race_calendar_responsive_ui.py`（新建，untracked，444 行）

21 个测试，覆盖：
- A1-A4：同月、跨月、跨年、单一年份日期显示
- A5：中文星期正确
- A6：today class、`aria-current="date"`
- A7：race-dot 数量、focus strip 只显示 G1
- A8："日期待定"回退
- A9：URL、anchor、筛选参数
- A10：初始窗口查询上限 ≤ 40
- A11：非硬编码（2031/2032 fixture 不输出 `2026年`）
- B1：共用 `.grade-badge` 尺寸契约（width/min/max/height 42px）
- B2：移动端不再有 `flex: 0 0 auto`
- B3-B4：G1/G2/G3/JPN1 渲染
- B5：`.g-other` CSS 规则存在
- B6：`.grade-badge:empty::before` 规则存在
- B7：`.cal-card-name` 有 `overflow-wrap: anywhere`
- B8：多卡徽标一致性
- B9：全局 `.grade-badge` 尺寸
- B10：桌面布局无 flex-wrap

运行命令：
```bash
cd /Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  .venv/bin/python server/manage.py test \
  stable.test_race_calendar_responsive_ui --noinput
```

当前 21/21 全部通过。

## 5. 明确的非修改范围

禁止将以下视为 scope 或 review 范围：
- 模型（models）、迁移（migrations）
- `base.html`、新闻模板、马匹模板、赛事详情模板
- `server/stable/tests.py`
- 新闻正文提取、英文马名识别、新闻来源展示、新闻地区 Tab
- 马匹国家 Tab
- URL 结构、筛选参数语义、cursor、分页逻辑
- Celery、Redis、配置、部署文件

## 6. Review 历史

### 第一轮（实现方自审 + reviewer A）：APPROVED

- **P2-1**：`.agenda-day:target` layout shift → 改用 outline
- **P3-1**：冗余 `flex-basis: 42px` → 移除
- **P3-2/P3-3**：低风险，接受
- 限定复审：RE-APPROVED

### 第二轮（独立原生 review session `019f9233`）：REVISE

三项 finding 及修复：

- **P2**：日期测试 A1-A3 使用整页 `assertIn`，`aria-label` 可能让测试假绿
  - **修复**：新增 `_date_axis_link_text()` 和 `_agenda_day_text()` helper，按具体 DOM 元素（date-axis `<b>` 文本、agenda `.m`/`.d`/`.date-year`）断言可见文本，不复用 `aria-label`

- **P2**：worktree 内 `.venv` 符号链接指向本机绝对路径，`.gitignore` 的 `.venv/` 目录规则不覆盖 symlink
  - **修复**：`.gitignore` 增加 `.venv`（无尾斜杠），同时覆盖目录和 symlink

- **P2**：分支落后 `origin/main` 19 个提交，fingerprint 与交接记录不符
  - **修复**：已 rebase 到最新 `origin/main`（`438ab6a1`），零冲突；更新所有 durable 文档状态

- **P3**：`spec.md`/`tasks.md` 仍标记"等待实现"
  - **修复**：已更新状态为实际完成态

## 7. 当前 Fingerprint

```text
FINGERPRINT_SHA256 25e10860441554f6d48345be1185c69bdc0c411d521bdae258243f4c641e7164
HEAD             438ab6a14f9665fd77318d8c12f8bc5a3ca63690  (= origin/main)
tracked changes  4 files (.gitignore, public.css, race_calendar.html, views.py)
untracked        8 leaves (test file + docs/changes/ 目录)
conflicts        0
```

> 审前/审后 fingerprint 必须用 `python3 .codex/scripts/review_fingerprint.py` 重新计算；
> 上值仅作为审前预期参考，不是冻结值。

## 8. Review 执行清单

### 8a. 环境确认

```bash
cd /Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews
git rev-parse HEAD                    # 必须 = 438ab6a14f9665fd77318d8c12f8bc5a3ca63690
git rev-parse origin/main              # 必须 = 438ab6a14f9665fd77318d8c12f8bc5a3ca63690
git status --short --branch            # 仅 4 个文件有变更
```

### 8b. 运行 fingerprint（审前）

```bash
cd /Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews
python3 .codex/scripts/review_fingerprint.py 2>&1 | grep "FINGERPRINT_SHA256"
```

### 8c. 执行 Codex 原生只读 review

```bash
cd /Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews
codex review -c 'sandbox_mode="read-only"' --uncommitted 2>&1
```

若 `codex review` 不可用，手动执行 8d–8g 全部检查点。

### 8d. 运行 fingerprint（审后，必须与审前一致）

```bash
python3 .codex/scripts/review_fingerprint.py 2>&1 | grep "FINGERPRINT_SHA256"
```

### 8e. 代码审查检查点

#### views.py
- [ ] `date_axis_spans_years` 计算正确（仅遍历已加载 groups，不增加查询）
- [ ] 无查询语义改变
- [ ] `public_race_calendar_years` 导入未被移除

#### race_calendar.html
- [ ] 日期轴 `<b>` 使用 `date:"n月j日"`
- [ ] 跨年时 `.date-year` 和 `date:"Y年"` 正确
- [ ] today `<a>` 含 `aria-current="date"`
- [ ] `.agenda-date` 含完整 `aria-label`
- [ ] `.m`（月份）、`.d`（日号+日）正确
- [ ] "日期待定"回退不变

#### public.css
- [ ] `.grade-badge` width/min-width/max-width/height 均为 42px
- [ ] 移动端 `.cal-card .grade-badge` 为 `flex: 0 0 42px`
- [ ] `.g-other` 含 `white-space: normal; overflow-wrap: anywhere`
- [ ] `.grade-badge:empty::before` 含 `content: "—"`
- [ ] `.cal-card-name` 含 `overflow-wrap: anywhere`
- [ ] `.agenda-day:target` 使用 outline（非 margin/padding）
- [ ] 无 `flex-basis: 42px` 冗余声明

#### test_race_calendar_responsive_ui.py
- [ ] 21 个测试全部通过
- [ ] B1 测试接受 `flex: 0 0 42px` 或显式 `flex-basis: 42px`

#### 安全性
- [ ] 无 XSS 风险（Django 模板自动转义）
- [ ] 无信息泄露

#### 性能
- [ ] `date_axis_spans_years` O(n) 遍历已加载 groups
- [ ] CSS 变更 < 30 行，无昂贵选择器/动画

### 8f. 测试验证

```bash
cd /Users/mentianlu/.codex/worktrees/polish-race-calendar-responsive-ui/umanews
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  .venv/bin/python server/manage.py test \
  stable.test_race_calendar_responsive_ui --noinput
```

### 8g. Django 检查

```bash
DB_ENGINE=sqlite .venv/bin/python server/manage.py check
DB_ENGINE=sqlite .venv/bin/python server/manage.py makemigrations --check --dry-run
git diff --check
```

## 9. 输出要求

完成后返回：

1. 执行的 review 命令/模式及结果
2. 审前/审后 fingerprint SHA256 及是否一致
3. 按严重度排列的 findings（P0/P1/P2/P3），每条含文件、行号和描述
4. 整体结论：APPROVED / REVISE / BLOCKED
5. 残余风险（如有）
