# REVIEW：JRA 全马场扩展计划审阅记录

## 第 1 轮（2026-09-26，独立只读 Agent）：REVISE

发现与处置：

| # | 级别 | 发现 | 处置 |
|---|---|---|---|
| P0-1 | P0 | policy 扩版必导致 route/policy digest 漂移；既有 103–107 登记的 `claim_binding` 会因 `binding_route_missing` 停止刷新，`attach` 被 `enrollment_policy_drift` 拒绝（adapters.py:525-526、admission.py:459-463、enrollment.py:1486-1487） | 已在 3.1 增加受控轮换对策：policy 切换后经既有受审链路 `adopt_stalled_event_policy`/`rotate_enrollment`（9/7 用于 755/756/757）轮换五条既有登记，轮换完成才宣布激活完成 |
| P1-1 | P1 | "按 9/22 同款激活流程"不可字面复用：activate-jra.py 硬编码旧 commit/policy SHA/providers 断言（不含 jra）/release_0079 绑定 | 3.4 改为按同款模式新写脚本，列出全部硬编码替换点与独立审阅要求；服务器侧状态列为实施前只读核对项 |
| P2-1 | P2 | T/F 归一结构兼容；建议补"以 T/F 结尾但本体不同不合并"拒绝用例；F=フィリーズ 外部事实未核验 | 已纳入 3.2 测试要求与实施前复核项 |
| P2-2 | P2 | 告警无外发已可代码证实；但 incident dedupe_key 含 policy_id，切换后旧 key 不自动关、新 key 重开；激活时点回看窗口可能同时开双 incident | 3.5 新增旧 key incident 显式收口步骤与实测要求 |
| P2-3 | P2 | 任务清单缺时间约束：107 闭环先后、108/109 seed 窗口（约 9/30） | 任务 5 增加硬时间约束 |
| P2-4 | P2 | 完成标准 T+30 口径与代码不符（result_overdue 是 T+30 分钟、time_unknown_overdue 是 T+1 日） | 第 6 节已改为精确口径 |
| P2-5 | P2 | proof 锚点"页面仍可访问"为未验证断言 | 3.3 已改为候选锚点 + 实施时真实抓取为准 + 逐马场降级 |

审阅者已确认无误的点：`_JRA_VENUE_CODES` 01–10 完整；venue 匹配为日文页头精确 `in` 匹配（英文别名为无害冗余）；赛前 seed 覆盖全部 10 马场；v1 policy 引用一致；CNAME↔页头强身份不受扩版影响。

审阅者未覆盖声明（实施前必须补齐核对）：服务器运行态（`.env`、锁、`release_0079` 模块）；`race_data_sync_control.py` 未通读；v1 `proof_digest` 生成方式未定位（已列为任务 2）。

## 第 2 轮（2026-09-26，同一独立审阅者）：REVISE

P1-1、P2-1~P2-5 逐条确认已闭合。P0-1 **未闭合**：复审证实 v2 引用的"9/7 同款轮换"链路对 v2 登记不可用——`adopt_stalled_event_policy` 拒绝 authority_version=2（`race_data_sync_repair.py:108-111`）；stalled 扫描扫不到健康的 103–107（`repair.py:49-89`）；`rotate_enrollment` 走 legacy provider 注册表且从不更新 `RaceDataSyncSourceBinding`（`control.py:840-930`）；`disenroll` 后 re-attach 被 `enrollment_not_active` 拒绝（`enrollment.py:1484-1485`）。结论：当前代码库不存在任何可让 v2 登记换绑新 route digest 的已审阅路径。

新发现：N1（P1）背景段 106/107 闭环陈述与 release README 旧证据冲突，需补新证据引用；N2（P2）9/30 前链路偏紧，需降级预案；N3（P2）目标与完成标准随 P0-1 对策失效而悬空。

**v3 修订处置**：

- 3.1 整段重写为"新增受审的 v2 换绑路径"（`rebind_multisource_enrollment` 语义、SHA 绑定 manifest、逐场单事务、identity 不变、fail closed），作为独立 PR 与激活前置；删除对 755/756/757 旧轮换的错误引用。
- N1：背景段补充 106/107 于 9/26 晚间闭环的新证据出处（current_state 2026-09-26 顶部条目，随 PR #217 入库），既有登记明确为 5 条。
- N2：任务清单增加降级预案（9/30 未就绪则 108/109 放弃作验收样本，顺延至 110/111/112，期间不切换）。
- N3：第 2 节目标与第 6 节完成标准改由新换绑路径支撑，措辞同步。

## 第 3 轮（2026-09-26，同一独立审阅者）：REVISE

P0-1 对策形态确认正确（新增换绑路径是唯一正确做法；模型层无约束阻碍）；N2/N3 闭合。新发现：

- N4（P1）：换绑字段闭集不完整——遗漏 `enrollment.route_digest`（claim 计划校验）、`binding_manifest_sha256` 与内嵌 `policy_digest`、source set manifest 再生成（应复用 `_multisource_manifest`）、checkpoint `registry_digest`（claim 选取循环强一致条件）、`binding.valid_until`/`source.valid_until`（10-21 提前断流）。
- N5（P2）：3.4 的 commit 绑定漏掉换绑 PR。
- N6（P2）：3.5 不应预设 106/107 incident 仍 open，应先只读核对实际状态。
- N1 复核：所引用的 106/107 闭环证据在仓库中尚不存在（PR #217 仍 Draft）；计划不能引用未入库证据。

**v4 修订处置**：

- 3.1 对策段按 N4 枚举完整 digest 闭集（binding 5 字段 → enrollment 2 字段 → 复用 `_multisource_manifest` 再生成 source set 与 lifecycle 证据 → checkpoint `registry_digest` → `valid_until` 同步），并要求每一点有对应回归测试与明确拒绝码清单。
- N5：3.4 改为绑定任务 1 与任务 2 均合并部署后的 commit。
- N6：3.5 改为"先只读核对实际 open incident 再受控 resolve"。
- N1：背景段降级为不预设登记数量——106/107 在 9/26 18:01 交接样本中未登记，换绑 manifest 目标由任务 5 预检时的实际 enrolled 集合生成。

## 第 4 轮

待同一审阅者复审 v4 修订稿。
