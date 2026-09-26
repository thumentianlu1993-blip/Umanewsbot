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

## 第 2 轮

待同一审阅者复审 v2 修订稿。
