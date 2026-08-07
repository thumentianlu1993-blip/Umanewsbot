# 赛事日历月份与等级徽标测试用例

## 测试原则

- 授权后由测试 subagent 新建聚焦测试并取得真实 RED；失败必须来自月份/跨年/徽标尺寸契约尚未实现。
- 自动化测试使用 SQLite 与本地 fixture，不访问真实网络或生产数据库。
- CSS 几何最终以真实浏览器计算尺寸为准；自动化静态契约测试负责阻止 `flex: auto`、尺寸下限缺失等
  已知 mutation 回归。

## 自动化测试

### A. 日期显示与状态

| ID | 场景 | 断言 | 当前预期 RED |
| --- | --- | --- | --- |
| A1 | 同月 7 月 24/28 日 | 对两个具体 group 分别断言日期轴连续文本、时间线 `.m/.day` 和完整 `aria-label` 为 `7月24日`、`7月28日` | 当前只输出 `24/28` |
| A2 | 7 月 28 日到 8 月 1 日 | 对两个具体 group 分别断言 `7月28日`、`8月1日`，不使用整页模糊命中 | 当前只输出 `28/01` |
| A3 | 2026-12-31 到 2027-01-01 | 两个具体 group 的 `.date-year` 与 `aria-label` 分别含 `2026年12月31日`、`2027年1月1日` | 当前只输出 `31/01` |
| A4 | 单一年份结果 | 月日明确但不重复无必要年份 | 当前缺月份 |
| A5 | 星期 | 固定日期输出正确中文星期 | 防止格式调整丢失星期 |
| A6 | 今天 | today class、`今天`、`aria-current="date"` 和时间线强调契约存在 | 新增可访问断言 RED |
| A7 | 有赛事与焦点 | `.race-dot` 数量与 dated groups 一致，focus strip 仍只展示本周重点 G1 | 防止状态丢失 |
| A8 | 日期待定 | 不输出虚构年月日，继续显示“日期待定” | 回归 |
| A9 | URL 与筛选 | tab/region/grade/when/year/q/cursor、锚点和详情 URL 保持 | 回归 |
| A10 | 查询数量 | 现有初始窗口查询上限不增加 | 回归 |
| A11 | 非硬编码 | 使用 2031/2032 fixture 仍输出 fixture 年月 | 捕获写死 2026/当前月 |

日期测试固定 `TIME_ZONE=Asia/Shanghai`，并对 `stable.views.timezone.localdate()` 使用确定日期，
避免测试运行日造成 today 漂移；`RaceEvent.local_date` 直接使用 fixture date。

### B. 徽标、标题与共用组件

| ID | 场景 | 断言 | 当前预期 RED |
| --- | --- | --- | --- |
| B1 | 共用尺寸契约 | `.grade-badge` 同时固定 width/min/max/flex-basis/height 为 42px | 当前缺显式宽度上下限 |
| B2 | 移动日历覆盖 | 599px 规则不再把 `.cal-card .grade-badge` 设为 `flex: 0 0 auto` | 当前准确失败 |
| B3 | G1/G2/G3 | 三种标签渲染正确 class，浏览器 390px 均为 42×42 | 当前约 18–21px 宽 |
| B4 | JPN1 | 四字符正式等级在 390px 为 42×42，文字居中且不溢出 | 当前约 36px 宽 |
| B5 | 未知四字符 | 使用四个全角字符 fixture；g-other 为 42×42、最多两行完整居中，`scrollWidth/clientWidth` 与 `scrollHeight/clientHeight` 均不溢出 | 当前依内容变宽且无全角回退 |
| B6 | 空等级 | 中性 42×42 占位并显示破折号 | 当前宽度为 0 |
| B7 | 长中文/英文标题 | 标题区换行，徽标仍为 42×42 | 当前徽标受 auto 内容宽影响 |
| B8 | 连续卡片 | 多卡徽标左边与尺寸一致 | 视觉回归 |
| B9 | 首页/赛事详情/新闻赛事预告 | 共用徽标仍为 42×42、颜色 class 不变 | 共用组件回归 |
| B10 | 桌面 | 1440px 日历卡为现有横向布局，徽标 42×42 | 桌面回归 |

CSS 自动化测试应提取具体 selector block 后断言属性，不能用整文件模糊字符串命中；否则其他 selector
中的 `42px` 可能造成假 GREEN。

## RED 取得方式


1. 新建 `server/stable/test_race_calendar_responsive_ui.py`；
2. 只写 A/B 对应自动化测试，不改 view/template/CSS；
3. 运行：

   ```bash
   DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
     .venv/bin/python server/manage.py test \
     stable.test_race_calendar_responsive_ui --noinput
   ```

4. 保存完整测试摘要和关键失败：
   - 日期 HTML 缺 `月`/跨年年份；
   - today 缺 `aria-current`；
   - CSS block 缺固定 width/min/max；
   - 移动 selector 仍为 `flex: 0 0 auto`；
   - 空等级缺视觉占位。

若失败来自 import、fixture、migration、locale 或环境，先修正测试基础设施并重跑；不得把环境错误记为 RED。

## GREEN 与回归

实现 subagent 完成后运行：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  .venv/bin/python server/manage.py test \
  stable.test_race_calendar_responsive_ui \
  stable.tests.RaceEventPageMVPTests --noinput
```

随后由主代理在所有 subagent 结束后运行：

- 赛事日历相关 view/template 回归；
- 公开首页、新闻详情赛事预告和赛事详情回归；
- 并行公共导航 change 的联合回归测试；
- `python server/manage.py check`；
- `python server/manage.py makemigrations --check --dry-run`；
- 必要的完整 `stable` 回归；
- 模板渲染验证；
- `git diff --check`。

## 真实视觉验收矩阵

使用仓库外临时 SQLite 数据库和真实 Django 页面；临时截图不加入 Git。

| 视口 | 日期数据 | 等级/标题 | 必查项 |
| --- | --- | --- | --- |
| 1440px | 同月 7/24、7/28 | G1/G2/G3 | 月份、星期、today、横向卡布局、42×42 |
| 1440px | 跨月 7/28、8/1 | JPN1、长标题 | 月份切换、标题不挤徽标、无 overflow |
| 1440px | 跨年 12/31、1/1 | 未知/空等级 | 每项年份、回退占位、对齐 |
| 390px | 同月与跨月 | G1/G2/G3/JPN1 连续卡 | 全部 42×42、点击区、内部日期轴滚动 |
| 390px | 多个长中文/英文标题 | 未知/空等级 | 标题换行、状态行对齐、页面无横向 overflow |
| 390px | today + 点击非 today 日期 | 混合等级 | today 与 target 反馈可辨、race-dot 保留 |
| 375px 或 320px | 最长标题与跨年 | JPN1/未知/空 | 必要时补验最窄屏，不出现页面级 overflow |

浏览器记录至少包含：

- `window.innerWidth`、`documentElement.clientWidth/scrollWidth`；
- 每个 `.grade-badge` 的 label、width、height、computed flex/min-width；
- 四个全角字符 `.g-other` 的 client/scroll width、client/scroll height 和完整可见文本；
- 日期轴可见文本与链接；
- today/target/race-dot/focus 状态；
- console error；
- 关键页面截图或等价可审计结果。

## 实际证据（2026-07-24）

- 实现方已保存目标能力 RED，并在实现后取得聚焦套件 `21/21` GREEN。
- 独立复验再次取得 `21/21` GREEN；Django check、`makemigrations --check --dry-run` 和
  `git diff --check` 均通过。
- 首轮独立 review 发现固定日期测试依赖真实 `timezone.localdate()`，会随日期推移失效。
  该 finding 属测试确定性修复，不改变运行时行为，因此不伪造新的产品 RED；测试现统一把
  `stable.views.timezone.localdate()` 固定为 `2026-07-24`，并用同一常量建立 today/窗口 fixture。
- 真实浏览器验收覆盖 1440px、390px、320px：
  - 根页面 `scrollWidth == clientWidth`；
  - 日期轴仅在需要时内部横向滚动；
  - 日历、首页和赛事详情的 G1/JPN1/未知等级均为 `42×42`；
  - 未知四字符徽标 `scrollWidth == clientWidth` 且 `scrollHeight == clientHeight`；
  - 跨年轴显示 `2026年12月31日 / 2027年1月1日`；
  - `:target` outline 为 2px，offset 4px，定位 top 与 sticky header scroll margin 一致；
  - 控制台无应用错误；仅观察到既有 `/favicon.ico` 404，不属于本 change。
