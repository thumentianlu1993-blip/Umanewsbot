# D082 剩余公开体验：有界核定后停等

结论：NO_NEW_READY_SLICE_STOP_WAIT_DEPENDENCIES。本次不选择新实现片，不建议再为填线路拆文案或重复静态核定。不是剩余U04/U05已经完成，也不是证明仓库没有其它缺陷。

固定clean HEAD `cf351eebbc873a0264f8b42dbbb92805ddd38491` / TREE `aeaab001753bab3ddfab1319cbcf773ea91c8d6c`。已读原U04 tasks.md:1270–1278、U05:1440–1448、TC-U01/02 test_cases.md:52–53及D077选择/阻塞记录；原RD D081 report f5e7e1dca4a26bdc210134b615462c0bfbc178a0bb9468496c0a49d362c8af41 / index2a61279eb60ff4457d5c7811e1e24bb2133d5727f9ce74c2e71ef3aab29a3353已核。D081仅列表日文fallback片闭环，formal gate FAIL/整U04/U05未完成保持。

| 剩余原义务 | 本次源码依据与具体依赖 | 为什么此刻没有独立测试oracle |
|---|---|---|
| 读取失败区别于暂无资料、失败可重试 | U04:1275–1277；views.py公开详情4216/4326及其render context4271/4463，_render_race_information4869–4871没有独立业务读取失败/重试契约 | 真实读取异常、公开门禁隐藏、空结果不是同一状态；需C先给错误分类、可见性与安全重试目标。不能mock空列表/模板context制造业务RED或抢改C服务 |
| 新鲜度、暂定/确定 | race_detail.html48–50已有真实赛果发布时间/stale，81已有preview checked_at/stale；views.py3999起关联公开read/revision、4044–4050预览选取 | 未找到额外且已就绪的新误导；真实新鲜度边界需来源/公开revision语义和相应许可，不能凭空再添更新时间承诺。已验date/K2不重做 |
| 正式域名/别名、旧链接、浏览器实际点击、长表与关键控件 | U05:1445–1447明确要求真实点击和无横向遮挡 | 需固定候选域/运行环境及浏览器资格；模板形状或静态href不能代验。D070 STOP不恢复，不试探域/browser资源 |
| p95与查询量、明确N+1/阻断布局 | U05:1445–1447要求固定数据量旧新测量 | 缺获准真实可比数据/执行资源及已定位根因，源码不能产生真实p95/布局失败；不自行启动PG/profile或借B域 |

已闭片不重复：nav/follow/body/dateK2、五basic空态、horse_index日文fallback。无赛果现有views.py3211–3212已给“赛果待确认”，列表无匹配/无资料已有各自分支，不再造空模块。

另明确保留一个未选观察：horse_detail.html14仍只original→English，日文单字段时原名段可能空；D081并未覆盖该详情段。它是刚闭列表fallback的同族展示扩展，当前原验收未给“所有页面必须统一日文副标题”这一独立义务，本轮不把它自动升级为下一片，不声称它已修复或其UI已观察。

下一工作只能在上述具体依赖变化后由ROOT定卡；不自动另开审计/实现/重跑。D070 STOP、CSS/p95/K3资格、D035/外部CID cleanup UNKNOWN及formal expired-skip缺口原样保持。只写本短runtime及摘要，工作区读前读后clean；没有源码/tests改动、commit/push、产品import/render/tests、DB/CI/网络/下载/浏览器/生产访问。
