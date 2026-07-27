## ADDED Requirements

### Requirement: 恢复范围必须由双层不可变清单定义
系统 MUST 为指定日期窗口生成逐 `RaceEvent` 记录清单和真实赛事分组清单，并以 manifest SHA-256 绑定生成时点、查询参数、事件身份和数据库基线。

#### Scenario: 同一真实赛事存在两条公开记录
- **WHEN** 两条记录可能表示同一地区、年度和日期的赛事但属于不同 `RaceSeries`
- **THEN** 系统必须保留两条 event row，并仅生成待审 identity group，不得自动合并、删除或复制赛果

#### Scenario: 清单生成后数据库漂移
- **WHEN** event 身份、结果计数、公开状态或系列关系在 prepare/apply 前变化
- **THEN** 系统必须拒绝继续使用旧 manifest，并要求重新生成与审批

### Requirement: 每个到期目标必须进入明确 accounted 状态
系统 SHALL 令每个冻结目标唯一地进入 `confirmed_result`、`cancelled`、`postponed` 或 `blocked_with_evidence`，并保持总数守恒；只有 `blocked_with_evidence=0` 且所有赛果应到目标均为 `confirmed_result` 时，恢复 run 才能标记 `completed`。

#### Scenario: 已举办赛事缺少官方完整赛果
- **WHEN** 候选只有第三方结果或官方页面无法确认完整 finish order
- **THEN** 目标必须保持 `blocked_with_evidence`，不得伪造 confirmed 终态，且 run 必须保持 partial/blocked

#### Scenario: 来源只列出 Also Ran 而没有完整名次
- **WHEN** 来源仅给出前若干名，并把其余完赛马统一标为 `Also Ran`、`N/A` 或其他无顺序状态
- **THEN** adapter 不得按页面顺序补造后续名次，candidate 必须标记 `result_order_complete=false`，coverage 以 `incomplete_result_order` 阻断该场

#### Scenario: 任一恢复来源无法证明完整排名
- **WHEN** candidate 缺少 target `event_id`、完整参赛名单、任一非退赛马的结果、连续唯一的内部名次，或仅包含 discovery-only winner
- **THEN** candidate 不得进入可写入状态；系统必须保留精确缺项，并以 coverage blocker 阻断该场

#### Scenario: 清单中已有取消或延期终态
- **WHEN** inventory 生成时赛事已是 `cancelled/postponed` 且身份在后续步骤未漂移
- **THEN** 目标保持既有终态且不得创建赛果行

#### Scenario: 人工核验新发现取消或延期
- **WHEN** 当前官方 route contract 没有对应 outcome marker
- **THEN** 目标必须进入 `blocked_with_evidence`，不得借 `official_result` marker 改写赛事状态

### Requirement: 候选与官方确认必须分层
系统 MUST 将 adapter/TRA/第三方候选与人工官方 evidence 分开存证，只有符合地区 route contract 的官方 evidence 才能授权 `is_confirmed=true` 和 `result_confirmed_at`。

#### Scenario: 两个第三方来源一致
- **WHEN** 两个第三方来源给出相同冠军或完整顺序但没有官方 marker
- **THEN** 系统只能保存候选一致结论，不得提升为官方确认

#### Scenario: 官方 evidence 合法
- **WHEN** evidence 的 host、path、marker、region、observed_at、reviewer 和 contract digest 均通过验证
- **THEN** 系统可将其绑定到精确赛事与结果事实以进入待 apply 状态

#### Scenario: manual-only 官方路由被自动请求
- **WHEN** recovery purpose 尝试自动访问 Equibase、BHA、France Galop 或其他 `manual_browser_only` 路由
- **THEN** source permission gate 必须在请求前拒绝，且网络请求计数保持为零

#### Scenario: route contract 过期或摘要漂移
- **WHEN** receipt、dry-run 或 apply 时 registry/contract/terms digest 或 `valid_until` 不再匹配
- **THEN** 整场必须 fail closed，旧 receipt 不得获得 grandfathering

### Requirement: 重复实体投影必须经过独立身份审批
系统 MUST 对跨 `RaceSeries` 的重复候选生成逐组审核记录，并要求批准 canonical product event、来源 event、事实 identity 和 manifest SHA；批准关系必须持久化为可回滚的 `RaceEventProductCanonicalLink`。

#### Scenario: 名称相似但系列身份未批准
- **WHEN** 赛事名称、日期和地区相似但 identity review 仍为 pending
- **THEN** 系统不得跨 event 投影结果

#### Scenario: 已批准投影
- **WHEN** identity review 精确批准同一真实赛事及 canonical product event
- **THEN** 系统可以把经本次官方 evidence 复核的结果投影到 canonical event，同时保留非 canonical 底层记录

#### Scenario: 并发审批形成链或环
- **WHEN** 两个事务同时尝试建立共享赛事端点的 active canonical link
- **THEN** PostgreSQL advisory lock 与 row lock 必须串行化审批，后提交者重新校验并拒绝链、环或跨地区/年度关系

#### Scenario: 回滚后改选 canonical
- **WHEN** 旧 link 已 inactive 且新审批选择另一 canonical event
- **THEN** 系统必须创建新的 active link、保留旧 inactive 审批行，并由条件唯一约束保证同一 duplicate 至多一条 active link

### Requirement: 生产 apply 必须经过 projection arbitration
系统 MUST 在每场事务内锁定并校验 `RaceEventProjectionControl` 的 owner/generation/current revision；正式赛果必须先形成 official observation/revision/evidence，再由 live publication transition 或 recovery historical projection service 更新 `RaceEventResult`、赛事终态、确认时间、OperationLog 和 rollback ledger。

#### Scenario: live owner 赛事恢复
- **WHEN** 目标 event 的 projection owner 为 `live` 且既有 allowlist/incident/tracking/authorization 完整
- **THEN** 系统必须复用 manual official evidence 与 official publication transition，禁止抢占 owner 或直接写结果表

#### Scenario: live owner 缺少既有发布前置
- **WHEN** 任一 live allowlist、incident、provisional revision、tracking 或 official authorization 缺失
- **THEN** 整场必须 blocker，recovery service 不得为其补造 live 控制面

#### Scenario: unmanaged 赛事恢复
- **WHEN** owner 为 `unmanaged` 且 before identity 通过
- **THEN** 系统必须以 CAS 晋级为 `historical`、递增 generation 并创建 official revision 后投影

#### Scenario: owner 被人工暂停
- **WHEN** owner 为 `manual_paused` 或 generation/current revision 漂移
- **THEN** 系统必须整场 fail closed 且零业务写入

#### Scenario: non-live participant 身份不唯一
- **WHEN** official row 缺 source runner ID 且官方原名/马号与既有 participant 发生重名、冲突或模糊匹配
- **THEN** 整场必须 blocker，不得以中文译名或相似度创建 revision item

#### Scenario: 同着与非完赛结果
- **WHEN** non-live recovery receipt 含重复 official position 或 SCR/DNF/DSQ 等无名次状态
- **THEN** revision item 必须保留官方名次/状态，并以唯一稳定 internal order 投影到 legacy result

### Requirement: 生产 apply 必须可审计、原子且可回滚
系统 MUST 保存完整写前 projection、owner/current revision、赛事状态、确认时间和 canonical link 身份；任何后段失败必须回滚该场全部业务写入，回滚不得删除 revision/evidence 审计。

#### Scenario: apply 前结果发生变化
- **WHEN** 现有 `RaceEventResult` identity 与批准 artifact 不一致
- **THEN** 系统必须在写入前 fail closed

#### Scenario: apply 后重复执行
- **WHEN** 使用同一 manifest、approval 和 evidence 重放已成功场次
- **THEN** 系统必须返回幂等成功且业务表、审计表和 `updated_at` 均无额外变化

#### Scenario: 精确替换 provisional projection
- **WHEN** 已批准 official revision 与既有 provisional projection 的结果行集合不同
- **THEN** 系统只能执行 manifest 明列的 create/update/delete，并保留旧 revision 与 rollback 能力

#### Scenario: write-ahead ledger 与提交结果不一致
- **WHEN** 进程在 ledger 发布与数据库提交之间中断
- **THEN** verifier 必须把孤立文件标为 `prepared_not_applied`，禁止自动 rollback 或误报已应用

#### Scenario: runner phase 权限混合
- **WHEN** 同一步同时声明网络与数据库写入或 recovery command 未进入历史 runner allowlist
- **THEN** runner 必须在启动前拒绝，不得执行子进程

### Requirement: verifier 必须证明数据与公开效果闭环
系统 SHALL 验证冻结目标守恒、结果数量与 SHA、状态、确认时间、canonical 展示、非目标计数和新闻/QQ 非影响，并输出 machine-readable summary。

#### Scenario: 仍有过期赛前目标
- **WHEN** 冻结范围内存在既非 blocker、取消、延期也非 confirmed 的到期目标
- **THEN** verifier 必须失败，且不得报告窗口恢复完成

#### Scenario: accounted 仍含 blocker
- **WHEN** 所有目标数量守恒但至少一个目标为 `blocked_with_evidence`
- **THEN** verifier 可以报告 accounted 完整，但 run 不得标记 completed

#### Scenario: 非目标数据变化
- **WHEN** 窗口外赛事、新闻、QQ delivery 或公开范围发生未批准变化
- **THEN** verifier 必须失败并指明变化层
