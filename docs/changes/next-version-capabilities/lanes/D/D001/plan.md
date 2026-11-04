# D001：赛事日历空态重置筛选短方案

日期：2026-10-17（Asia/Shanghai）。任务 `D001-PUBLIC-EXPERIENCE-INDEPENDENT-SLICE-PLAN-001`，仅只读定位及方案，待 ROOT 路由专属 R_D。工作树 `/Users/mentianlu/.codex/worktrees/2076/umanews`，分支 `codex/d-public-experience-20261017`，固定 base `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`；初始无脏改动，HEAD 与本地 origin/main 一致，未 fetch 或核验远端实时 head。

本次修订任务 `D002-CALENDAR-EMPTY-RESET-DEFAULT-RULE-WORDING-PLAN-REPAIR-001`，仅修订 RD-D001-01。原稿保存在受审提交 `cabdc28cbc5bc7124bdad3f5f4a0ae54a36a4e30`，Git blob `b5f120cc9ac1e08d1e524538f0d8723fd800760c`，SHA-256 `53c6b8efc94c7da30288d2ae60732b3f56ca8b06041e8282b5799695261505ff`；原 R_D 报告提交 `e4802eeb408c14a4ed059456a8561bfa2c0e6002`，路径 `docs/changes/next-version-capabilities/lanes/R_D/D001/plan-review-001.md`。本修订不是 finding 已关闭的声明，待 ROOT 转同原 R_D 复审。

## 目标与当前证据

U04/TC-U02 的一个独立切片：让读者从赛事日历空结果一次回到不带用户筛选的公开列表。源码已能确定缺口，尚未启动服务、浏览器或行为测试；不声称生产复现。

- `server/stable/templates/stable/public/race_calendar.html:135` 的空分支只有“暂无符合条件的赛事。”，无就地恢复入口。
- `server/stable/views.py:3780` 的 `filter_url` 保留现有 tab/region/grade/when/year/q；顶部 `clear_search_url` 只清 year/q。因此从地区、等级、已完赛或重点交集的空列表点击顶部“清除”仍可能为空，而且没有 year/q 时顶部根本没有“清除”。现有逐项导航可以手动恢复，不把它描述为页面完全不可用。
- `server/stable/views.py:3356` 的 `_race_calendar_queryset` 已接收并规范这些筛选；`tab=all` 明确解除重点限制，其他字段缺省为空。默认日期窗口、公开资格、canonical 排除、北京时间及稳定排序均已有合同。
- `server/app/urls.py:16` 已有命名路由 `public-race-calendar`（`/races/`），可以模板直接生成固定站内地址，无需改 view/DTO。

已排除重复实现：当前 horse_index 已有 C032 搜索空态及清除链接（最近路径提交 `db076d3bd24aa943dafc08753526b391604aae6e`）；U01 公开等级共用读投影已在当前树（`3ac1e3a750e68bafe7950fa726481a02ecccfad6`）；U02 的签名返回与七天首页已有 `fe53b27d4f35b37a9bd85b3f933344be79f8fefa`，本片不重写。新闻 detail 已渲染 horse_links/race_links 的“本文提及”入口，只能证明已有展示，不证明 L03 整卡完成；不碰其关系算法或状态。本地旧 dispatch 副本仍是 10/03；只读查询 ROOT 当前动态派单可见 C183 纯核心任务，未写 ROOT 或 C 树。

## Before → After 与范围

示例：现有公开日本普通赛事；请求 `/races/?tab=key&region=de&grade=g1&when=finished` 返回空。Before：只有统一空文案，无顶部“清除”；读者必须逐个改变范围。After：空分支显示“当前列表暂无可展示的已发布赛事。”和真实链接“重置筛选，返回默认赛事列表”，链接固定为 `{% url 'public-race-calendar' %}?tab=all`。点击只读 GET，移除 region/grade/when/year/q/cursor/direction/return_nav 及未知查询参数，全部范围导航激活，合成公开日本普通赛事可以展示。

入口旁说明为“重置后按赛事日历的默认规则显示。”。现有默认规则包括正常日期窗口，以及公开基础集合没有有效公开日期时的跨期列表回退；后者可以展示日期待定的公开赛事（固定 views.py:3397–3399、3417–3467）。保持原分页及公开资格，不承诺全部历史同屏或来源覆盖完整，不通过排除无日期赛事、修改查询或默认窗口迁就文案。

入口条件：`groups` 为空，且规范 filters 含任一 region/grade/when/year/q/cursor/direction，或 tab 为 key。`tab=all` 且其余规范筛选为空时，保持原空文案，无无效重置链接。有结果时不显示本片空态或重置链接。只使用服务端既有规范 filters，不直接回显用户输入，不保留 return_nav，也不拼接任意 URL。

拟改文件仅：

1. `server/stable/templates/stable/public/race_calendar.html` 的 `{% empty %}` 分支（现 135–136 行）。保留上方所有筛选/卡片/O03 marker/分页结构；复用现有 empty-state 样式，不新增 CSS、脚本、共享组件。
2. 新增独立 `server/stable/test_calendar_empty_filter_recovery.py`，仅负责本片真实 Django Client 渲染与 GET 恢复。测试 helper 自有，不改他线测试或共享 fixture。
3. 未来测试包同时准备 `tools/test_impact/catalog.json` 与 `tools/test_impact/rules.json` 的精确映射草稿交 ROOT：新文件路径 → 模块 `stable.test_calendar_empty_filter_recovery`；catalog 的 domains/tests/profiles 登记 django profile，rules 路径与相同行为域一致。由 ROOT 组织核对选择输出，不能声称未创建的模块已登记/选中或已运行。不改 runner/workflow/skip；本轮不写实际映射。

本轮只新增本 D 方案文件。上述模板不属于派单列出的三个需先划独占块的详情模板；如 ROOT 存在其他占用，先按这一个精确 empty 块协调，不能覆盖他线改动。`views.py`、三个详情模板、models/migrations、tasks/settings、生产配置和总任务台账均无改动。

## 测试矩阵与执行次序

后续获短方案通过后，固定受控时间，使用独立合成已发布普通赛事取得真实断言 RED，不用真实服务或权限 gate 错误充 RED。具体隔离 runner/数据库资源由 ROOT 分配；当前 Docker 四 profile 保持停止，不为本方案恢复。

| 场景 | 预期断言 | 基线预计 |
| --- | --- | --- |
| published 日本普通赛事；重点/德国/G1/已完赛交集为空 | 新空文案和唯一重置入口出现，href 精确 `/races/?tab=all`；不是失败/采集中/全球无资料声明 | RED：缺文案/链接 |
| 从上述 DOM 提取真实 href 后 Client GET | 该公开赛事出现，all 激活；filters 其余为空，无 cursor/direction/return_nav；旧筛选不再生效 | RED：缺链接，恢复断言仅 GREEN 后实测 |
| 分别只有 q、year、region、grade、when 或默认 key 导致空集 | 每个独立限制均有相同恢复入口；原顶部清除合同保留 | RED：缺入口 |
| 有效签名 return_nav 还原空筛选 | 使用现有 `_public_nav_token` 生产，查询仅含单个 return_nav，不混普通筛选；先断言实际还原规范 filters，再提取 href GET 恢复默认列表，无旧 token | RED：缺入口；错误/过期/混参 token 不满足此前件 |
| 有效末页游标空页 | 用 `encode_race_calendar_cursor` 为集合末项生成、绑定同 filters，direction=future；先断言 decode 成功及规范 filters，再验空页入口和 href GET 恢复默认列表 | RED：缺入口；非法 cursor 回退不冒充成功游标覆盖 |
| 唯一可展示赛事已发布但无有效公开日期；先用不匹配 q 得空集 | 实际 Client 空态提取固定 href 后 GET；断言该无日期赛事出现、日期待定表达保留、无伪造日期/00:00，按既有跨期回退且公开资格不变；说明不承诺默认日期窗口 | RED：缺入口；恢复及回退断言仅 GREEN 后实测 |
| `tab=all` 空库 / 只有 hidden 或 active canonical duplicate | 原空文案，无重置入口、不泄漏隐藏名称或状态 | 原实现应通过 |
| 受限筛选确有匹配赛事 | 正常卡片，空态及本片入口均不出现；详情签名返回仍可用 | 原实现应通过 |
| q 含 HTML/扩展汉字、非法筛选或非法 cursor | 文案固定，无原文注入；依据现有规范 filters 决定入口，无任意跳转；无业务状态伪造 | 保护断言 |
| unknown 查询参数触发现行 canonical 301 | 分别断言初始 301 与 Location，再跟随跳转断言最终规范 filters/空态；不将 301 响应缺入口计作行为 RED | 保护断言 |
| 新旧规范展示开关两态，date-only 赛事、合法结果读门禁 | 返回集合/等级/时间/公开资格保持当前合同，不新增北京时间 00:00 或冠军 | 保护断言 |

按测试 → 模板实现 → 同例 GREEN → 最近相关导航/日期窗口/公开展示回归 → R_D 代码复审排列。预计关键 RED 是页面缺入口，不能先修改产品再倒填 RED。以上是计划，尚无任何执行通过数字。新模块映射的正式 CI 范围交 ROOT/R_D 按现行规则判定，不修改到期 skip 或降低准入。

未来 U05 手机验证可使用离线合成浏览器页面，在 320/375/768px 检查文字自然换行、链接可见可点、键盘可聚焦，浏览器实际点击相同恢复 URL；服务启动需要另获 ROOT 资源安排。本片不改变 CSS，不宣称手机整站旅程或性能提升。没有实测 p95/查询数，不提供提升数字。

## 依赖绑定、门禁与停止条件

全部输入都来自固定 base，主要 Git blobs：race_calendar.html `1fe0827a0cf34729e8c33bba1bc8a93bb90e5b89`；views.py `173b75b0101d188542cc0adb37431effb21a5dcb`；日期窗口回归模块 `3c02244522e5e973be221a7213163c90663970da`。模板最新路径提交为 `185f7b3375210a0da6f34426918b87c1fb2038a6`，需保护其 O03 marker。方案后基线若漂移先报告 ROOT，不静默换 base。

G1 已由本次新增 D 公开体验范围授权覆盖；本阶段只读及方案不需要重复询问。G2/G3 按根 AGENTS.md，本片不合并、部署、生产读写、真实抓取、付费或外发。QQ 下线仍暂缓，关注/订阅/发送行为及文案保持。无配置、迁移、服务重启或数据修复；未来代码回退仅撤回本片模板/测试。

U04 的 H07/L05/R03 全局新鲜度、资料阶段、失败状态输入未闭环；U05 的 L06/E06/U04 整卡依赖保留。当前没有可靠统一 error DTO，因此不选“读取失败重试”，不捕获异常为空、不用空集推断资料缺失或采集状态。本片完成也只记空筛选恢复子片，不验收 U04/U05 整卡。

如需新增业务状态、字段、查询、改变公开资格/默认窗口、修改共享 view 或模板其他块，停止扩展并给 ROOT 精确依赖。若行为测试因环境或过期 gate 失败，保留基础设施证据并报告，不修复旧停域或延长 skip。所有 finding 交原 R_D 上下文闭环，不启动子代理。
