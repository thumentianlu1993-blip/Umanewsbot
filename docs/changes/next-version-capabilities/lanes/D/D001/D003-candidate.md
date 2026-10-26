# D003：测试与精确映射候选交接

2026-10-17（Asia/Shanghai）。固定直接 parent `b58b35cb874bbf8db563dd59ab9d6cf4692b636e`，parent tree `c9a353529d090345a9456a450dc5dc643e7b5b6b`；最终候选 commit/tree、测试整文件SHA和静态收据由交接消息精确绑定。分支 `codex/d-public-experience-20261017`，工作树2076。原方案/受审hash和R_D报告链不改，D002方案层finding关闭不等于实现通过。

本卡仅新增 `server/stable/test_calendar_empty_filter_recovery.py`、本目录测试矩阵/交接文档，及修改 `tools/test_impact/catalog.json` / `rules.json`。生产 race_calendar.html、views.py、其余模板和服务源码均与直接 parent 原字节相同；未来唯一模板exclusive范围仍仅empty 135–136行，本卡未触碰。没有生产实现，因此没有 GREEN 或产品完成声明。

## 映射与静态校验

- catalog domains：`module:stable.test_calendar_empty_filter_recovery` → `[stable.test_calendar_empty_filter_recovery]`；tests：精确新文件路径→同label/domain；profiles：同模块→`django`。没有修改其他模块、allowed_skips或profile归属。
- rules paths：新测试、公开日历模板、`race_calendar.py`、`race_public_time.py` 精确路径追加此域；模板和两个服务仍保留原high_risk/full优先级，不能靠path规则降风险。
- views现有symbol映射仅追加此域：`public_race_calendar`、`_public_race_calendar_base_queryset`、`_public_apply_list_nav`、`_public_nav_token`、`_public_read_nav`。原有symbol域保留；未登记的 `_race_calendar_queryset` / `_race_calendar_canonical_redirect_url` 保持原fail-closed，不新增降级映射。初始化full列表不变。
- 静态校验只解析测试AST及JSON，比较生产/控制文件bytes、old/new映射保留关系、声明ID不重复和新增类直继承TestCase；不是业务import/collect/测试通过。原工具静态选测计划另存D专用runtime并在消息绑定；不启动runner。

已完成静态本地计划：原 `scripts/plan_affected_tests.py --base b58b35cb874bbf8db563dd59ab9d6cf4692b636e --local` 输出 full / 267 domains / 329 labels，包含新模块；这是工作区静态选择，非正式收集数量。最终固定Git计划在提交后生成并由消息绑定。测试整文件 SHA-256：`5e5d27fabad15436a093b4d805672183384e5a857909e1f11c253788fa0a308a`。原catalog移除唯一新增domain/test/profile后与parent相等；rules去掉精确追加域后与parent相等，所有allowed_skips/high_risk/初始化full义务均未改。`git diff parent -- server/stable/templates server/stable/views.py server/stable/services` 为空。静态收据：`/Users/mentianlu/.codex/runtime/d003-calendar-empty-reset-candidate-001/final-static-source-receipt.json`，早期同目录static-source-receipt仅为中间测试文件hash，最终以final收据和固定Git为准。

## 正常 CI 诊断 RED 包（未执行）

计划命令：`python3 scripts/plan_affected_tests.py --base b58b35cb874bbf8db563dd59ab9d6cf4692b636e --head <本候选40位SHA> --test <本候选40位SHA> --output <D-runtime>/fixed-plan.json`。这是纯静态Git选测，不导入业务。真实PR的test必须使用该次精确merge SHA，不把branch head静态计划冒充PR计划。

正常运行入口保持原工具：由 ROOT 安排有授权的 CI 后，`.github/workflows/affected_tests.yml` 的 static-contracts → generate-plan → execute-isolated-plan → verify-execution；执行步骤使用 `scripts/run_test_plan.py`，收集/执行使用原 `scripts/test_plan_worker.py`，结果核验用 `scripts/verify_test_plan.py` / `tools/test_impact/core.py:verify_results`。不使用缩减catalog、替换worker或自造passed收据。

正常CI能否抵达业务断言：**源码静态上没有expiry前置阻止，但实际抵达未知**。现有 planner 在 catalog/rules变化时用 old/new catalog full union，保留全部历史覆盖；新域包含本模块。worker collect实际加载测试并按profile/类分片，未在collect检查review_by；run阶段真实DiscoverRunner执行Client用例。`run_test_plan.py` 把各批通过ThreadPool执行并汇总exit状态，业务失败可保存在对应batch JSON/log。若任一批失败，runner非零，workflow的 `verify-execution` 仅在execute成功时执行，因此本候选预期业务RED时该步可能根本不会运行，必须读真实batch断言定位。Docker/构建/静态合同/收集/fixture失败仍可能使目标方法未执行，不能提前说一定到达。

2026-10-17 时原catalog的10项 allowed_skips复核日仍为2026-10-16，已到期且本候选逐字保留。如果全量仍产生这些skip，即使其余测试全部通过，`verify_results` 中 `date.fromisoformat(review_by) < date.today()` 会拒绝 `unexpected/expired skip`，完整交付不能验收；这与新用例缺页面入口的AssertionError是两类事实。业务RED可以在实际批次断言中单独识别，不代表本full已通过；未来页面GREEN也不能解除这10项正式交付阻塞。不延日期、不加skip、不恢复旧域或环境。此处时点按用户Asia/Shanghai日期，工具实际比较使用执行环境date.today，未来收据需核对运行日期。

ROOT后续若批准正常CI，应保留：固定base/head/test/tree与controls/image、原plan/execution-plan、collection与各batch日志/JSON、19项实际ID/执行数、生命周期/退出状态、目标AssertionError原文、独立保存的expiry/其他失败。只有实际到达预期“缺新文案/唯一链接”断言才是业务RED；固定href点击恢复保护大多在RED首次失败之后，须等同例GREEN实跑才能认定。不得以预计失败数当实际结果。CI实时policy/配额/真实环境可用性本轮未查询，未推送或触发。

所有业务import/collect/Client、CI、浏览器、服务/Docker恢复、实网、QQ/邮件外发和生产操作均 **NOT_RUN**。不使用credits/reset/换模型，weekly复核单独回报ROOT。G1范围沿已审方案，G2/G3仅引用根AGENTS。本包等待 ROOT→同原R_D源码与包审，不自行派审或自领实现。
