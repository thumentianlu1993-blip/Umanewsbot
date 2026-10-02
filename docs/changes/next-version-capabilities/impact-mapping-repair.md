# 三线首批交付的影响映射修正

2026-10-03，Asia/Shanghai。固定修改前基线 `84b439a2`，当前精确提交由协调阶段消息绑定。责任仅 `tools/test_impact/rules.json` 与本说明，不修改执行器、选择算法、profile、catalog、skip、阈值或业务代码。

## 问题和修改

真实 PR 基线 `907f8de699b31a6fcc80acc78e9ba070aadc4f28` 到 C 候选存在十个未映射路径和两个 view 函数。不能缩到测试父提交或手选标签绕过。

1. 将 C 提案列明的九份静态规划/观察证据逐项加入 docs 精确列表：dispatch_state、inheritance、task_index，F04-prototype.html、F05-public-evidence.json，以及2026-10-02能力基线目录的四份观察/需求JSON。仓库 server/scripts/tools/.github 中未发现运行消费者；原型未发现 fetch、XMLHttpRequest、form action、远端URL、WebSocket、iframe、submit。此分类只适用这些固定用途的路径，不扩展 JSON/HTML 通配。
2. U01-offline-cases.json 是行为 fixture，映射到 race_information_display_pages、race_information_display、race_field_normalization 三个既有领域，保留 core/依赖展开。
3. `_public_race_calendar_base_queryset` 与 `_public_weekly_focus_events` 映射到 C 提案的八个既有模块领域，覆盖等级/来源、历史/公开/canonical/分页、日期、响应式、public_time、新地区与首页新闻消费者。

C 提案见其固定文档 `a8d07e6c` 的 `lanes/C/U01-impact-mapping-proposal.md`。A/B独有新模块的catalog/profile变更仍由各自已审补丁交接，当前补丁不会登记本树不存在的新模块。

## 验证

- 修改前直接对当前selector输入十路径与两个函数，实际抛出 `unmapped`，与C真实计划阻塞相同。
- 修改后九静态路径为 docs-only；fixture 为 targeted 且包括三领域+core；两函数包含八既有领域。
- 三个未登记邻接文件（新fixture、manifest、prototype）仍fail closed；没有增加通配豁免。
- 将rules.json变更加入同一输入仍为 full（293 labels）；现行规则/目录演进的旧新覆盖要求保持。
- `python3 -m unittest scripts.tests.test_test_impact scripts.tests.test_impact_evolution`：30/30 PASS；`git diff --check` PASS。这些是映射技术检查，不是业务Linux完整交付收据。

## 交接限制

补丁先交原R独立审核，再由协调者给各线明确控制SHA。不得修改A在途0e05029c固定树；不得把其base7c的开发验证收据自动挪作真实PR基线证明。后续集成候选按现行政策从真实main基线重新生成计划并取得必要收据，只有不可变范围、测试和审核对应时才记录通过。根AGENTS.md继续作为人工门禁唯一来源。
