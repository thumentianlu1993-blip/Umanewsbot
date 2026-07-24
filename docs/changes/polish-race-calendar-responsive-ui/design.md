# 赛事日历月份与等级徽标响应式修复设计

## 当前结构与探索证据

### 日期数据流

```text
GET /races/
  -> _race_calendar_queryset()
       -> today = timezone.localdate()
       -> RaceEvent.local_date 过滤、排序和 cursor
  -> _group_race_events_by_date()
       -> 按 event.local_date 分组
       -> anchor_id = race-date-<ISO local_date>
       -> is_today = local_date == timezone.localdate()
  -> public_race_calendar()
       -> groups / date_axis / previous_url / next_url
  -> race_calendar.html
       -> date_axis: date:"d"
       -> agenda_date: date:"d"
```

`RaceEvent.local_date` 是已经按赛事所在地落定的 `DateField`；本 change 不从 `race_datetime` 重算日期。
时区只继续用于 `timezone.localdate()` 的“今天”判定。当前模板的 `date:"D"` 在中文 locale 下输出
中文星期。

真实临时 SQLite 页面在 390px 验证：

- 同月/跨月日期轴输出 `24 / 28 / 01 / 04 / 05 / 06`；
- 跨年结果输出 `31 / 01`，虽然锚点含完整 ISO 日期，视觉文字没有月或年；
- `document.documentElement.scrollWidth == clientWidth == 390`，现有横向滚动只发生在日期轴内部。

### 日期状态

- 今天：group 与日期轴链接使用 `.today`，日期轴有绿色下划线，时间线日期与左边线有强调。
- 有赛事：每个 `date_axis` group 都渲染 `.race-dot`。
- 本周重点：`focus_events` 在独立 `.focus-strip` 中展示；日期轴没有独立重点 class。
- 定位：日期链接指向 `#race-date-YYYY-MM-DD`；当前没有额外 JavaScript 选中状态。

### 徽标共用与准确根因

`.grade-badge` 被以下公开页面共用：

- `feed.html` 的首页近期赛事；
- `race_calendar.html` 的赛事卡片；
- `race_detail.html` 的赛事 hero；
- `detail.html` 的新闻赛事预告。

全局规则是 `flex: 0 0 42px; height: 42px`。移动断点 `max-width: 599px` 额外设置：

```css
.cal-card .grade-badge { flex: 0 0 auto; }
```

因为全局规则没有显式 `width/min-width/max-width`，该覆盖把日历徽标宽度交回内容固有宽度。390px
真实计算结果为：

| 标签 | 首页/详情 | 日历卡片 |
| --- | ---: | ---: |
| G1 | 42px | 18.44px |
| G2 | 42px | 20.69px |
| G3 | 42px | 20.67px |
| JPN1 | 42px | 36.09px |
| 空 | 42px | 0px |

日历卡片标题已有 `min-width: 0`，但没有异常长文本的明确换行规则。问题不是数据库等级值、grid
列宽或父容器 overflow，而是移动端 flex 覆盖和缺少显式尺寸下限。

## 设计决策

### D1：每项显示月日，跨年时每项再显示年份

不采用月份分组标题。原因：

- 用户要求无需回看或推断；
- 日期轴本来允许横向滚动；
- 月份分组标题在只显示少数日期、过滤结果或 cursor 分页中容易与可见项脱节。

日期轴主文字使用动态 `n月j日`。时间线左栏把月份和带“日”字的日号拆为小月份 + 大日号，适配 900px 以下现有
`64px` 日期列：

```text
日期轴：7月24日
        星期五 · 今天

时间线：7月 24日
        星期五 · 今天
```

`public_race_calendar()` 对本次 `groups` 中非空日期的年份取集合：

```python
date_axis_spans_years = len({group["date"].year for group in groups if group["date"]}) > 1
```

当集合大于一个年份时，日期轴和时间线的每个有日期项都显示自己的 `Y年`。同一结果只含一个年份时
不重复年份，减少拥挤。该判断不依赖当前系统月份/年份。

模板契约锁定为：

- `.date-axis a` 的主文字节点直接输出连续 `n月j日`；
- 每个 `.agenda-date` 提供完整日期 `aria-label`；
- `.agenda-date .m` 输出 `n月`，`.agenda-date .day` 输出 `j日`；
- 跨年结果中的 `.date-year` 输出该项自己的 `Y年`，并同时进入完整日期 `aria-label`；
- 自动化测试按对应日期 group/selector 逐项读取，不以整页字符串命中代替时间线断言。

### D2：保持原日期与 URL 语义

- 不改变 `_race_calendar_queryset()`、`local_date`、cursor、排序或查询数量。
- 不修改 `anchor_id`，仍使用 ISO 日期保证唯一和深链稳定。
- `today`、`.race-dot`、`.focus-strip` 原 class 与含义保留。
- 给 today 链接补充 `aria-current="date"`，并以 `agenda-day:target` 复用现有强调色给点击后的目标组
  提供定位反馈；不新增 JavaScript，也不把 hash 写入服务端筛选状态。

### D3：共用徽标固定为 42px 方框

共用 `.grade-badge` 明确声明：

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

现有 flex 居中继续负责水平/垂直居中。移动端 `.cal-card .grade-badge` 删除 `auto` 覆盖或显式恢复
`flex: 0 0 42px`，不得出现第二套尺寸。

### D4：四字符与空等级回退

- JPN1/JPN2/JPN3/JG1/JG2/JG3 继续使用现有 g1/g2/g3 颜色映射，15px 字号可容纳在 42px。
- `.g-other` 使用中性背景、12px 字号、紧凑行高、受控内边距，并覆盖为
  `white-space: normal; overflow-wrap: anywhere`。这样最多四个全角字符可以在固定方框内按最多
  两行居中排版，拉丁四字符也可在必要时换行；不得使用 `overflow: hidden` 裁切文字。
- `.grade-badge:empty::before` 输出 `—`；只改变展示，不改模型或数据。
- 不增加 G1 专用补丁，不改变 `grade_badge_label` 截断契约。

真实浏览器验收除外框 `42px × 42px` 外，还必须对 `.g-other` 的四个全角字符样本断言：

```text
scrollWidth <= clientWidth
scrollHeight <= clientHeight
```

并目视确认文字完整、水平/垂直居中且未裁切。

### D5：标题消费剩余空间

`.cal-card-main` 保留 `min-width: 0`，移动端继续在徽标右侧占用剩余行宽；`.cal-card-name` 增加
`overflow-wrap: anywhere`，让异常长连续文本也在标题区换行。状态区继续独占下一行并按固定徽标
宽度对齐。徽标不参与标题压缩。

## 响应式边界

- 大于 900px：时间线日期列保持 `92px`；月日清楚，徽标和状态维持现有横向卡片布局。
- 600px–900px：时间线日期列保持现有 `64px`，月份用小字号与大日号同行。
- 小于等于 599px：卡片继续换行；徽标固定 `42px`，标题占剩余宽度，状态区下一行。
- 日期轴所有断点继续内部横向滚动，不允许页面根节点横向溢出。

## 预计修改文件

- `server/stable/views.py`
  - 只在 `public_race_calendar()` 计算并传递跨年布尔值。
- `server/stable/templates/stable/public/race_calendar.html`
  - 日期轴和时间线的月日/条件年份标记、today 可访问状态。
- `server/stable/static/stable/public.css`
  - 共用徽标尺寸、未知/空等级、日期月日排版、目标组反馈和长标题换行。
- `server/stable/test_race_calendar_responsive_ui.py`
  - 新建聚焦测试，避免与并行 change 已修改的 `server/stable/tests.py` 发生写冲突。
- `docs/changes/polish-race-calendar-responsive-ui/`
  - 本 change 的五份持久文档；实现后补 RED/GREEN/视觉/review 证据。

不预计修改模型、迁移、基础模板、新闻模板、首页模板或赛事详情模板。

## 性能、数据与回滚

- 只对最多 40 个已加载 group 的 Python date year 取集合，不增加数据库查询。
- 无模型、迁移、缓存、Celery、配置、生产数据或历史数据处理。
- 回滚只需回退 view/template/CSS/test patch；赛事数据不需要恢复。
- 若部署后日期或徽标出现严重回归，回滚到部署前应用 commit/镜像并重建应用服务；不得在线手改容器。
