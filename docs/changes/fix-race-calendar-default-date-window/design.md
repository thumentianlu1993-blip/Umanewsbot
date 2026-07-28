# 赛事日历默认比赛日窗口设计

## 当前数据流

`/races/`
→ `public_race_calendar`
→ `_race_calendar_queryset`
→ `RaceEvent` 公开/重复项/筛选条件
→ 默认 `today ± 30 natural days`
→ 赛事对象前 40 场
→ `_group_race_events_by_date`
→ `date_axis`
→ `race_calendar.html`。

模板没有复杂日期运算，也没有专属 JavaScript。`public.css` 只负责日期轴、月份、卡片和徽标
布局。Nginx 仅缓存静态与媒体文件；Django 只缓存赛事年份列表和 sitemap 数量，未缓存
`/races/` 页面或默认窗口。

## 目标数据流

`/races/`
→ 解析并规范化 filters
→ 构造唯一的公开基础 queryset
→ 判断默认模式/显式模式
→ 默认模式对基础 queryset 做 distinct `local_date` 查询
→ 纯函数平衡前侧、锚点、后侧
→ 以 `local_date__in=<最多11日>` 批量查询赛事
→ 现有分组、状态、术语展示与模板。

日期窗口选择集中在新服务 `stable.services.race_calendar`。模板不承担选择算法。

## 服务接口

计划提供两个可独立测试的层次：

1. `select_balanced_race_dates(before_desc, anchor, after_asc, *, side_size=5, limit=11)`
   - 输入已排序且唯一的日期序列；
   - 输出升序唯一日期；
   - 纯函数，不访问时钟或数据库。
2. `public_default_race_date_window(queryset, *, today)`
   - queryset 已含全部当前公开资格和筛选；
   - 排除 `local_date=None`；
   - 以少量 distinct date 查询取得锚点两侧候选；
   - 调用纯函数返回最多 11 日。

`shanghai_today` 由 view 使用
`timezone.localdate(timezone=ZoneInfo("Asia/Shanghai"))` 只计算一次并显式传入日期服务、
`_group_race_events_by_date` 和赛事状态标签。锚点、`is_today`、`public_status_label` 与模板
aria 标记不得再次隐式调用 `timezone.localdate()`；测试冻结同一输入。

## 日期查询算法

使用两条有界 distinct date 查询：

- `local_date <= today`，按日期倒序，最多读取 11 个日期；
- `local_date > today`，按日期升序，最多读取 11 个日期。

若第一组首项等于 today，则它是锚点；否则未来组首项是锚点；未来组为空时使用历史组首项。
两侧各取 5 后，按缺口从另一侧补足到 11。每侧最多读取 11 个日期足以完成任一方向补足，
不加载全部赛事对象。

## Queryset 一致性

现有 `_race_calendar_queryset` 拆成：

- 参数解析；
- `_public_race_calendar_base_queryset(filters)`；
- 默认/显式查询策略。

基础 queryset 统一承载：

- published；
- active canonical duplicate 排除；
- key/all；
- region；
- grade；
- when。

默认日期查询和默认赛事查询复用同一基础 queryset。`q`/`year` 属于显式跨期模式，继续在
同一基础 queryset 上增加自身条件，但不调用默认日期窗口。

## 40 卡有界策略

保留 `RACE_CALENDAR_PAGE_SIZE=40`。两条日期候选查询除 `local_date` 外，同时以聚合得到该日
一个稳定的代表赛事 ID。默认赛事查询按以下优先级在一条 SQL 中截取：

1. 最多 11 个代表赛事 ID，保证每个所选日期至少有一张卡；
2. 其余同窗口赛事按现有 `local_date/local_start_time/id` 顺序填充至 40。

查询结果在 Python 中恢复为现有时间升序后再分组。代表赛事必须来自同一个已筛选公开
queryset，不能由隐藏或不匹配赛事占位。该策略保持响应体和 ORM 对象最多 40 场，同时避免
密集的早期日期吞掉日期轴后半段；不得按 11 个日期逐日查询。

## URL 行为

- `/races/` 及仅含 `tab/region/grade/when` 的 URL：计算新默认窗口；
- `direction=past|future&cursor=YYYY-MM-DD`：保留现有独占边界分页；
- `year=YYYY`：保留年度模式；
- `q=...`：保留跨年度名称搜索；
- 日期轴仍使用页面锚点，不改模板 URL 协议；
- 非法 cursor 不再进入“无边界却截取全库前 40 场”的异常分支，回到默认模式。

## 锚点标记与移动端初始位置

默认模式把选定锚点日期传给分组，生成 `is_anchor`。模板为对应日期链接增加
`data-calendar-anchor` 和轻量 `anchor` 状态；今天仍单独保留 `today` 与
`aria-current="date"`。未来/历史回退锚点用 `aria-current="true"` 表示当前默认焦点。

仅在默认模式，模板内最小脚本在 DOM ready 后直接设置 `.date-axis.scrollLeft`，把锚点水平
居中；不调用可能改变页面纵向位置的 `scrollIntoView`，不使用动画，也不改变 URL/hash。
显式 cursor/year/q 模式不自动滚动。CSS 只为 `anchor` 复用现有日期轴强调语汇，不调整卡片、
徽标或整体布局。

## 空数据与无日期数据

默认窗口只承认有 `local_date` 的实际比赛日。数据库无公开赛事、筛选为空或仅有日期待定赛事
时，默认模式返回空 groups，由现有模板展示“暂无符合条件的赛事”。显式 year/q 模式仍可
按现有语义展示日期待定记录。

## 缓存

不为默认窗口新增 cache key。每个默认请求重新读取北京时间今天和数据库中的 distinct
比赛日，故跨日无需主动失效。既有 `public_race_calendar_years()` 300 秒缓存与默认锚点
无关；Nginx 不缓存动态页面。

## 性能预算

现有已跟踪预算分别为：轻量默认不超过 8 条 SQL、40 卡 live read gate 不超过 12 条、
40 卡 official/corrected read gate 不超过 20 条。新算法只增加 2 条有界日期聚合 SQL，
代表赛事优先级并入既有单次赛事查询，不按自然日循环、不逐日查询赛事：

- 同等轻量默认 fixture 目标不超过 10 条 SQL；
- 40 卡 live read gate 不超过 14 条；
- 40 卡 official/corrected read gate 不超过 22 条；
- canonical 年份模式不进入默认窗口，继续保持现有不超过 12 条；
- 日期候选每侧最多 11 行，赛事 ORM 对象和响应卡片最多 40 场；
- 赛事对象一次性按所选日期批量读取，results 继续单次 prefetch；
- 实现阶段记录修改前/后的真实 SQL 数和关键 SQL 形状。

若实现阶段实测超过上述精确预算，必须优化或回到方案复审，不能以放宽预算替代 N+1 修复。

## 预计文件

- 新增 `server/stable/services/race_calendar.py`；
- 窄改 `server/stable/views.py`；
- 窄改 `server/stable/templates/stable/public/race_calendar.html`；
- 窄改 `server/stable/static/stable/public.css`；
- 新增 `server/stable/test_race_calendar_default_date_window.py`；
- 仅在回归证明必要时补充既有日历测试断言；
- 更新本 change 文档与规定状态文档。

不预计修改 settings、模型或迁移；JavaScript 仅为模板内默认锚点水平居中。

## 回滚

代码回滚只需恢复 view 的旧查询策略并删除新服务；无 schema、配置或数据回滚。若浏览器验收
发现日期轴或卡片布局回归，停止发布并回退代码，不操作赛事业务数据。
