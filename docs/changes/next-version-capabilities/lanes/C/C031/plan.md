# C031：U04 马匹搜索空态首片方案

2026-10-06，C031-U04-PUBLIC-STATE-FIRST-SLICE-PLAN-001。固定基线 `2c72521c55b6cdc24f7650d172b48079cbff969a`；本轮仅方案，应用/测试/共享文件未修改，未执行 RED 或实现。PR240 候选和现有 C027 演示不动。门禁仅引用根 AGENTS.md，后续交同原 R 快速方案审，ROOT 再授权实施。

## 当前可证明的问题

`public_horse_index`（views.py:4287）经 `_public_horse_queryset`（2723）只选 published，按去空白的 `q` 筛选并分页，将 `filters.q` 与 `horse_profiles` 交给 `horse_index.html`。模板第 37–38 行对所有空集显示“目前还没有已发布马匹资料。”，没有区分搜索条件。

C027 现存合成演示实际 GET `/horses/` 和 `/horses/?q=C031-SYNTHETIC-NO-MATCH` 均 200、均为此文案。演示本身没有马匹档案，所以该运行观察不证明“存在已发布档案仍错误”；这一分支可由固定模板与 view 代码确定，并须在实施阶段用独立合成已发布档案取得真实 RED。相关 view/template 的 Git blob 与本方案基线相同，未用旧截图推断当前代码。

## 一个用户行为闭环

搜索词非空且结果为空时，改为“没有找到符合搜索条件的已发布马匹资料。”，显示“清除搜索”链接。点击返回 `{% url 'public-horse-index' %}`，清除 q/page/return_nav；重新显示当前公开列表，保留原来的匿名关注 cookie，不改变可见范围。不显示搜索词原文，不新增数据查询、自动重试或采集。

未搜索（包含仅空白 q）且列表为空仍显示原文案；有匹配档案时正常显示卡片，不出现空态或清除入口。它只表达“本站当前公开集合的搜索结果”，不声称目标不存在、全球无资料、系统故障或覆盖完整。

预期实现仅 `server/stable/templates/stable/public/horse_index.html` 的 empty 分支：按现有 `filters.q` 选择固定文案，在搜索空态放置真实站内链接。复用 `_empty_state.html` 和既有按钮/链接样式，不改 view/query/pagination/共享空态组件，不引入状态框架。测试复用现有 `stable.tests_legacy.HorseProfilePageMvpTests` 的合成 profile helper；不在本轮写测试或修改 catalog。

## 实施阶段的 RED 与保护断言

用独立测试数据库、真实 Django Client 与模板，禁外网；不向 C027 演示数据库插入资料。计划三项真实 RED，随后原例 GREEN，再检查两个保护分支：

| 条件 | 输出断言 | 原实现预期 |
| --- | --- | --- |
| 至少一份 published 档案；q 不匹配 | 新“符合搜索条件”文案出现，旧“目前还没有”文案不出现 | RED：仍显示旧文案 |
| 上述搜索空态 | 真实“清除搜索”链接指向 `/horses/`；点击后不带 q/page/return_nav，原 published 卡片出现 | RED：无链接 |
| 无 published，只有同名非公开档案；非空 q | 仍使用搜索空态，隐藏档案名称/状态，不声称失败或尚无全站资料 | RED：仍显示旧文案；隐藏性为保护断言 |
| 空库且无 q / q 仅空白 | 原未发布资料文案保留，无清除入口 | 原实现应通过，防回归 |
| published 档案且 q 命中 | 卡片与现有详情/返回筛选保持，无空态 | 原实现应通过，防回归 |

若首个 RED 失败于环境/导入而不是上述页面断言，应先修隔离环境，不当作行为 RED。实施后用新的独立合成演示验证空态→清除→公开卡片，C027 原进程、端口、数据库继续保留。只执行新增和实际受影响测试，正式资源与选测登记按 ROOT 协调；不为短文案重跑旧全套。

## U04 其余边界

- **仅当地赛日**：已有 public_time / race_field 路径保留日期且时刻未知；C027 德国 date-only 详情实际显示“北京时间待定”，无 00:00。这是已有能力证据，不算本片新实现；此处不改时区/日期规则。
- **尚无资料**：赛事详情未收录出马表、马匹详情暂无履历与列表搜索空集不同，保留既有范围。本片不将缺资料改为读取失败。
- **读取失败**：当前无统一、可靠的公开 error 状态供本片模板区分，数据库异常不应捕获成空集；统一失败页/重试语义另行限定入口，不用空态伪造故障状态或故障已恢复。
- **更新时间与新鲜度**：赛事已有 runner_preview.checked_at、stale 及行级 dynamic_updated_at，模板只在相应数据存在时展示。它们不证明整个赛事/马匹已刷新；不拿 model.updated_at、当前时间或历史资料时间冒充整站更新时间。H07/R03 未交付的新鲜度、资料阶段与完整主链口径延期。
- **关注聚合**：L05 未交付的聚合/订阅语义延期，不改关注行为；QQ 停用后文案条款和后台改造本轮暂缓，保持现有 QQ 行为。没有新 schema/settings/migration、真实来源读取、生产数据动作或通知。

只读证据：`/Users/mentianlu/.codex/runtime/c031-u04-public-state-plan-001/` 的两份 horse HTML、race-date-only.html、observations.json、source-equivalence.json；全为现存本地合成演示 GET，写入数 0，不代表生产验收。当前只提交本 C 方案；U04 整卡仍部分延期，不宣称完成。
