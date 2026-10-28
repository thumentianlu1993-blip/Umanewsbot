# P02 分区交付与恢复方案

本文件是待实施的发布设计，不是已获准发布包。人工确认仅遵循[根 AGENTS.md](../../../AGENTS.md)；未执行生产迁移、启用或外部发送；2026-10-28 已追加只读生产预检，见[验收准备](acceptance-readiness.md)。

## 当前交接点

固定起点 e4df6bda；独立 worktree 为 `/Users/mentianlu/.codex/worktrees/p02-race-lifecycle-design-20261027/umanews`，分支 `codex/p02-race-lifecycle-design-20261027`。原 business-handoff 及旧线程工作区不修改，不恢复旧调度。进入实现时先核最新 Git、脏状态和并行改动；接最新主线的差异只在独立分支处理，不 checkout 共享 main。

核心与地区隔离测试、有限公开来源取样及独立实现评审已完成；当前候选 CI、发布升级、真实赛日和七天观察仍未完成。只读生产预检发现的基线、迁移与覆盖缺口见[验收准备](acceptance-readiness.md)。后续运行脚本固定候选 SHA/镜像，runtime 产物写专用目录，不随可变工作树漂移。

## 分阶段执行

| 阶段 | 动作与出口 |
|---|---|
| L0 隔离开发 | 自动测试离线，fixture/raw 来源可追溯；必要 RED/GREEN、PostgreSQL 并发和只读独立实现 review 通过，才形成可交付候选。 |
| L1 来源与地区准备 | 按现有权限/用途证据建立 AE/SA 等目标清单和来源五类能力矩阵，证明全追踪窗口的版本发现覆盖与最坏 60/120 秒间隔，计入 7 天及未确认存量预算。真实调用需按根规则纳入具体范围/预算；无及时发现路径的地区不能按 SLA 交付，备源缺口如实报告，不能强制双源才能确认。 |
| L2 预发布影子 | additive migration、回放、backfill dry-run、容量/断源/崩溃/回滚演练；旧公开写入者保持唯一，新决策只记录差异。影子不构成公开启用。 |
| L3 地区小样本真实验证 | 将明确 cohort、有限网络范围和唯一 writer 切换列入候选包；至少一完整真实赛日走完名单/变化/完整结果/公开探针，满足首批条件后小范围交付。真实端到端验证本身若需公开或生产写入，同样属于精确发布包，不能当作“测试”绕过。 |
| L4 7 天观察 | 分地区公布 N/E/U/D/L、来源时间区间、公开时延、漏场与恢复；未遇到的异常保留回放证据。无赛日/样本不足延长收集，不宣称长期达标；其余达标地区独立交付。 |
| L5 后续区域 | 复制合同和验证方式，各地区独立审核来源、范围、预算，不能把一个地区通过外推至九地区。滚动 28 天持续报告。 |

## 候选发布包必须填实的内容

实施完成时形成可审阅的一份具体记录，按根 G2/G3 办理，不在此另定义确认门禁：
- PR/commit/镜像 digest，目标环境、地区/赛事 ID、cohort 清单和 manifest SHA、有效期；合并与部署结果分别记录。
- schema migration 清单、新增 nullable 字段和表；历史 backfill 是否执行、确切 ID/批量/行数、dry-run 差异及备份恢复点。
- 配置/功能开关旧值新值、来源 host/endpoint/data kinds、现有账号权限、每分钟/每日请求与费用上限；不含任何秘密。
- web/worker/beat 是否重建或重启、队列与在途任务处理、publication owner 切换、缓存/CDN 策略、内部探针与告警目的地；外部发送如不在包内不执行。
- 技术验证命令与成功条件、自动停止条件、恢复命令/镜像/数据范围、负责人和 release lock 资源域。
- 该次真实赛日与 7 天观察起止时间、报告路径、未覆盖项；批准版本必须与实际执行一致。

## 发布与回滚技术顺序

1. 唯一 release coordinator 取得有存活信息的 production release lock，核实无冲突生产任务；备份相关数据并验证能读取。integration lock 只保护短时整合，不能替代 release lock。
2. 应用 additive schema（含不可变 EpochPublication 和每模块成熟度）。部署兼容 reader、当前 epoch/权限验证、fencing、具备 expired-running 回收的 outbox consumer，开关默认 off；先保证旧写入者也不能绕过本期已隐藏资料的读规则。验证相同内容确认、A→B→A 当前凭据、撤销授权与迟到 ack。
3. 影子与 backfill 检查通过后，暂停 cohort 新 claim，等待现有 lease 结束或由 token/generation 作废，事务内切换单 writer，记录 policy/manifest；再恢复新队列。禁止旧/new writer 同时改公开 projection。
4. 启用一个地区有限 cohort 的新 reader/公开写入；立即探针验证 identity、epoch、名单/结果一致与时效。所有正式验证绑定候选 SHA/manifest。
5. 开启按地区观察；每次扩大范围绑定新清单和根规则，不能把首次 cohort 自动扩大至全部国家或赛期。

停止条件：任意身份串场、伪造确定、已撤销内容重新可见、并发混写、越额访问立即停止该 cohort；公开错误率达到 1% 或卡顿率达到 3%（D>0）停止扩量并修复，保留缺来源原因和原分母。样本不足、探针不完整时不得标达标。source 故障维持合格备源与有界恢复，无法确认则显示已约定提示，不猜测结果。

回退优先：关闭新 claim/写入开关，令在途 claim 失效，停止相关新计划，保留支持新可见性规则的 reader 以及只读已验证快照。可回退到上线前部署并验证过的兼容 reader 镜像；不能直接回到会复活已隐藏/已撤销数据的旧二进制。保持 schema 为 additive，不立刻 drop 新表；对公开指针回退也必须复验目标版本未撤销、无冲突、未过期，否则保持“资料更新中/核实中”。清除相关缓存，公开探针证明后才记录回退完成。

数据回滚单独处理：先停 writer，依据 backup 和精确受影响清单恢复；不可盲目整库覆盖其他线程的数据。outbox 未完成项保留且按新 policy/generation fence，不因回退重放旧错误公开事件。恢复新版本需同一失败原因已复验关闭；人工确认是否仍有效仅按根文件判断。

## 中断恢复交接

每次交接保存：worktree/branch/commit、未提交文件清单、task ID/实际测试、review findings、schema/backfill cursor、cohort SHA/策略、writer owner、claim/队列存活信息、已执行步骤和公开探针证据、回退点、下一动作。执行结果未知时先读权威 DB/任务/公开状态，不重复 apply；恢复不能凭聊天“应该成功”。

历史 R09 审计只从交接的既有目标清单出发，实际更新单列 manifest；未知旧资料仍按 spec 的兼容规则处理。无关 worktree、旧调度、新闻/QQ 和其他项目不受本发布包影响。

## 2026-10-27 实现接口补充（本轮未执行发布）

运行参数：`RACE_LIFECYCLE_V2_WRITE_ENABLED=false`、`RACE_LIFECYCLE_DELIVERY_ENABLED=false`、`RACE_LIFECYCLE_V2_EVENT_IDS` 空列表，公开 `RACE_LIFECYCLE_PUBLIC_ORIGIN` 与 `RACE_LIFECYCLE_CAPACITY_FILE/SHA256` 默认空。既有 multisource、provider/region/field、host budget 开关仍须同时成立；新开关不取代它们。

- `report_race_lifecycle_capacity --manifest <文件> --sha256 <原始文件SHA>`：离线能力/全库存容量报告，零网络零写库。运行容量文件额外含 `valid_from/valid_until`，覆盖所有 cohort canonical ID。
- `backfill_race_lifecycle --event-id <ID> [--after-id <游标>]`：默认只读，每页最多100，输出 manifest 及 canonical 内容 SHA。回填使用 `--apply-manifest <纯manifest文件> --sha256 <canonical内容SHA>`；不能传整个带包装的报告，也不能拿原始字节 SHA 替代内容 SHA。
- `manage_race_lifecycle_report --input <文件> --sha256 <原始文件SHA>`：输入 `{document, anchors}` 导入严格 R01；输入 `{scope, window, as_of}` 从账本组装并保存。`--register-scope` 输入 `{scope,window,obligations}` 保存冻结分母及明确期限；义务绑定其 target 的 current_input_version。`--receipt <key>` 回读。
- 延迟输入 `{event_id,epoch,module,candidate_sha256,as_of}` 经同一报告命令输出版本绑定的 R01 latency input/result。来源或探针时钟没有可信证据时返回 UNKNOWN，不能把入库时刻当来源首发。真实时钟证据和独立覆盖审计尚未配置。
- outbox 周期任务 `stable.tasks.deliver_race_lifecycle_outbox_task` 在配置启用时每30秒进入 `race_sync_v2`；运行失败保留持久投递并重试。探针需要HTTPS真实公开 origin；测试替身不计生产验收。

P02 新增迁移为0083、0084、0085、0086；现生产停在0079，当前候选的实际升级还包含0080–0082，完整清单须随依赖方案冻结，见[验收准备](acceptance-readiness.md)。0086仅新增最近获准佐证的可空引用，历史行为空时回落到发布观测；部署时与新 writer 同步，保留该列可向前兼容。0085扩展 observation 去重键，旧 writer 空 acquisition_key 的行为不变。**产生新领取观测后，不逆迁移0085回旧唯一约束**：同内容多次观测是合法新证据，反向DDL可能唯一冲突，也不能为回滚删除证据。出现问题优先关闭新写入/网络发现，保留新 reader、证据表与迁移，按逐事件当前授权保持 fail closed；未经核验直接切回不认识 epoch 的旧代码可能重新公开争议内容。schema回退需要独立恢复设计，不能当机械代码回退。

地区可行性与未完成项见[来源盘点](source-inventory.md)；本记录没有发出任何发布或外部请求授权。人工确认只按根 AGENTS.md。
