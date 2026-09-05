# 补齐赛事状态自动更新完整链路：工程审核记录

## 1. 审核结论

```text
Review mode: Full (profile: feature)
结论：APPROVED FOR USER REVIEW
含义：方案可以交给用户审核；尚未授权实现、合并或部署。
```

本仓库当前使用原生 `docs/changes/` 工作流，不使用 OpenSpec phase、journal 或 sidecar。审核按照
`plan-eng-review` 的范围、架构、代码质量、测试、性能、上线与一致性门禁执行，但不生成已被仓库规则禁用的 OpenSpec 文件。

## 2. 审核基线

- 代码基线：`origin/main@241bf60f0406401115accd59c6f477883692e816`
- 方案工作树：独立 clean worktree `codex/plan-complete-race-status-automation`
- 生产基线：本轮只读验收的 PR #137 / revision `1312c8de…a03` / migration leaf 0077
- 本轮未执行：生产写入、provider 手工触发、服务重启、队列操作、部署和 migration

## 3. 第一轮审核发现与修正

### F-001（Critical）：不能让 Celery 自动改固定 lifecycle registry 的环境变量

问题：最初可考虑“每发现一场赛事就生成新的 registry 并自动替换”。但当前 runtime 把 registry root、成员 SHA、成员数和 activation ID 绑定在环境变量中。后台任务自动改它们会要求重启服务，也会让应用任务取得发布权限。

修正：不自动轮换旧 registry。新 data-sync 赛事以现有 standing policy + enrollment 作为动态 lifecycle admission；旧 registry 保留给既有固定名单。两种授权共用同一个 lifecycle writer，双命中时拒绝。

状态：已解决。

### F-002（Critical）：备用来源不能参与 enrollment 主路由竞争

问题：当前法国、英国和美国各有主 API 与备用结果源。它们被放在同一 routes 列表后，没有身份的新赛事无法选择唯一 route，造成 127 场批量歧义。

修正：standing policy v2 明确 `primary` 和 `result_fallback`。每个地区恰好一个 primary；fallback 只在结果 not-found 后参与赛果仲裁。

状态：已解决。

### F-003（High）：不能承诺当前来源做不到的远期数据

问题：现有 The Racing API 自动入口只允许 today/tomorrow racecard。继续承诺 D-30 或 D-60 自动取得赛时和出马表，会把产品目标写成不可验证的口号。

修正：产品承诺从“来源开放窗口”开始计算；30 天盘点保留，但窗口外明确标为 `awaiting_source_window`。若以后要提前数周获取赛时，必须作为新 provider/route 项目单独审核。

状态：已解决。

### F-004（High）：不能直接把旧 official revision 推到公开页

问题：755/756/757 已有 official revision，但这些 revision 产生时 lifecycle/public admission 不完整。直接复用会绕过当前来源、claim 和政策复核。

修正：先轮换 enrollment 和补齐 lifecycle admission，再等下一次自然 provider 响应；只有新响应仍通过全部门禁才投影。

状态：已解决。

### F-005（High）：写入授权和页面读取授权不能各写一套

问题：当前 lifecycle、result projection 和 public read 都依赖 lifecycle registry，但检查位置不同。仅修改 writer 会产生“库里写了，页面不显示”；仅修改页面会产生“页面比写入更宽松”。

修正：新增唯一共享 validator，并强制三个入口共用；测试要求任一 drift 时三处结论一致。

状态：已解决。

### F-006（High）：当前磁盘余量不足以安全发布

问题：约 8.18 GiB 仅比 8 GiB 硬门槛高约 189 MiB，无法同时容纳新备份、新镜像和临时文件。

修正：rollout 使用动态磁盘预算：备份 + 镜像增量 + 临时文件 + 1 GiB 缓冲 + 发布后 8 GiB 保底。未满足前不提交生产发布包。

状态：方案已解决；真正实施时仍是外部硬门禁。

### F-007（Medium）：真实赛果更正可能长期不发生

问题：如果把“生产出现一条真实更正”设为发布完成前置，完成时间不可控；如果生产造数，则违反赛果真实性。

修正：更正变化分支在隔离 PostgreSQL 用确定性 fixture 证明；生产只要求自然无变化周期幂等，首个真实更正作为持续验收。

状态：已解决。

### F-008（Medium）：identity discovery 统计存在静默缺口

问题：当前候选可以进入初始列表，随后因为不是 today/tomorrow 而不进入请求 bucket，最终结果没有解释这些赛事。

修正：新增 outcome 守恒公式和 `awaiting_source_window`，审计必须列出每个分类的 event ID。

状态：已解决。

### F-009（High）：未来 30 天清单找不到已经过去的 755/756/757

问题：三场法国赛事已超过 cutoff，单靠未来 census 不会轮换它们的 enrollment，方案会写着“恢复”但实际上永远选不中。

修正：增加最近 7 天未闭环恢复清单，只选择已 data-sync 纳管、tracking 开启，并存在未公开 official revision、开放 incident 或 correction watch 的赛事；仍要求下一次自然 provider 响应。

状态：已解决。

### F-010（High）：同一状态列表不能同时服务新纳管和赛后继续跟踪

问题：新纳管只应接受 scheduled/postponed，但已经纳管的赛事进入 running/finished 后还要继续获取赛果和更正。继续共用一个 `event_statuses` 会让赛事刚推进状态就失去授权。

修正：policy v2 分成 `new_enrollment_statuses` 和 `continuation_statuses`；后者明确包含 running/finished。

状态：已解决。

## 4. 架构审核

### 4.1 通过项

- 保留 Django 单体、PostgreSQL、Celery、Redis、Compose 和 Nginx 主干；
- 不增加第二套赛事状态机、结果表、provider registry 或业务总开关；
- 复用现有 observation/revision/enrollment/control/incident；
- provider transport、业务判断、Celery orchestration 和 public read 的层次保持清楚；
- manual lock、source contract、claim/CAS 和 kill switch 继续 fail closed；
- legacy `race_live` 完全不在新链路中。

### 4.2 需要实施时重点复审的代码边界

- `validate_data_sync_lifecycle_admission()` 必须是唯一逻辑，不得在三个调用方复制；
- lifecycle reconciliation 必须沿用现有锁顺序；
- standing policy v2 的 primary/fallback 不能与来源优先级混成一个字段；
- policy v1 到 v2 必须使用新 SHA 和 successor enrollment，不能静默接受旧文件；
- 已结束 event 956 的 legacy evidence 不得因新 validator 被改写。

架构问题：两轮共 7 项，其中 Critical 2、High 5；均已在方案中解决。

## 5. 代码质量审核

- 新 helper 放在现有 race-data service 层，tasks 只负责编排；
- 不新建与 `resolve_source_route_admission()` 重复的来源校验；
- reason code 为稳定机器字段，中文解释由审计/后台展示层处理；
- 所有网络调用继续使用现有 transport、timeout、host/path allowlist 和容量预留；
- 不在日志中输出 secret、header、raw payload；
- future census 必须保持数据库窗口查询和批量预取，不能退化为逐赛事 N+1；
- 没有新增 Python 或系统依赖；
- 预计没有 migration，避免扩大发布风险。

代码质量问题：1 项（重复授权判断风险），已通过共享 validator 解决。

## 6. 测试审核

覆盖范围已经包含：

- policy schema、角色和 digest；
- discovery 窗口与统计守恒；
- identity 唯一性；
- enrollment/lifecycle authority；
- schedule/lifecycle/result/public/correction；
- PostgreSQL 并发和事务回滚；
- Celery 重试、claim expiry 和 kill switch；
- root/www 页面一致性与内部字段防泄露；
- 755/756/757 同形态恢复；
- event 956 历史证据不变；
- `race_live` 不变和资源门禁。

测试缺口：两轮共 5 项——双 authority、discovery 守恒、无真实 correction 时的验收方式、最近 7 天恢复清单、new/continuation 状态分离；均已补入测试方案。

## 7. 性能审核

- 30 天窗口当前只有百级赛事，查询规模合理；
- provider 请求继续每轮最多 3 个，并复用 shared snapshot；
- enrollment/lifecycle reconciliation 每批最多 20；
- selector/lifecycle 每批最多 100；
- 不提高 worker concurrency 和 Web 常驻进程；
- 不增加公开页实时第三方请求。

性能风险：扩大 enrollment 后 provider task 数会上升。现有按地区/日期共享 snapshot 和 capacity ledger 可以控制增长，但生产阶段必须观察 request_count、queue lag、artifact bytes 和磁盘下降速度。

性能问题：1 项，已通过批次和现有容量账本约束；上线时继续验证。

## 8. 失败模式审核

| 失败情况 | 测试 | 处理/回退 | 运营是否可见 |
| --- | --- | --- | --- |
| 一个地区零个或两个 primary | 有 | 整地区零 enrollment | audit 明确 reason |
| 来源窗口未到 | 有 | 不请求、不写入 | 显示正常等待 |
| 来源窗口内找不到赛事 | 有 | 零 enrollment | event ID + reason |
| 身份多解或跨 event | 有 | 整场零写 | P0/P1 incident |
| 人工锁或人工暂停 | 有 | 自动化零写 | audit 显示 |
| policy/route/contract 过期 | 有 | 网络或投影前阻断 | audit + incident |
| claim 在网络期间过期 | 有 | observation 可保留，canonical 零写 | task reason |
| lifecycle 双 authority | 有 | 状态、赛果、公开全部拒绝 | P0 incident |
| 只写了 result、页面不显示 | 有 | 共享 validator 使测试失败 | public verifier |
| partial result/无 terminal marker | 有 | observation only | provisional overdue |
| correction 内容不同但无 marker | 有 | 不改 current | conflict incident |
| worker OOM/restart | 有 | 10 false + 停专用 worker | host gate |
| 磁盘不足 | 有 | 请求/发布前停止 | capacity audit |
| 发布中断 | 有 | 原 token 恢复关闭态 | deployment lock/receipt |
| `race_live` 数量变化 | 有 | 立即停止发布 | queue verifier |

没有发现“无测试、无处理、且对运营静默”的 Critical failure mode。

## 9. 本期明确不做

- 新增商业 API 或官方爬虫：会扩大网络、许可和成本范围；
- 提前 30 天赛时承诺：当前来源合同不支持；
- 清理人工锁：人工锁本来就是自动化停止信号；
- 批改全部历史 scheduled 赛事：容易把取消/延期/重复赛事误改；
- 直接公开旧 official revision：会绕过当前 admission；
- 在生产制造 correction：会污染真实赛果；
- 迁移/消费旧 `race_live`：属于另一条遗留链；
- France 2023 马匹 staging/canonical：属于另一个会话和产品范围；
- 新闻或 QQ 自动发送：与赛事状态链无关。

## 10. 第二轮收敛审核

第二轮重新核对了 `spec.md`、`design.md`、`test_cases.md`、`tasks.md` 和 `rollout.md`：

- primary/fallback 定义一致；
- 来源窗口和 30 天盘点分母一致；
- 最近 7 天恢复清单能精确覆盖停滞赛事且不扩大到全部历史；
- 新纳管状态和 continuation 状态分离；
- legacy registry 与 data-sync admission 边界一致；
- 755/756/757 均只通过新自然响应恢复；
- correction 的测试与生产验收口径一致；
- 预计无 migration，发现 migration 即重新审核；
- tasks 按测试 -> 实现 -> 验证 -> 发布排列；
- rollout 的开关、备份、磁盘、队列和回滚均与设计一致。

第二轮发现并修正了 F-009、F-010 两项高风险遗漏；修正后再次做逐项一致性复核，未再发现新问题，方案在第二轮收敛。

## 11. 完成摘要

```text
Plan Engineering Review Summary
================================
Review rounds: 2 (converged at round 2)

Step 0: Scope Challenge — scope reduced to current approved providers and source windows
Architecture Review: 7 issues found, all resolved in plan
Code Quality Review: 1 issue found, resolved in plan
Test Review: 5 gaps identified, all added
Performance Review: 1 risk found, bounded by batching and capacity ledger
Consistency check: All artifacts consistent

What already exists: enrollment, lifecycle control, observation/revision,
provider roster, selector, dedicated worker, public verifier, audit and kill switches
NOT in scope: new providers, historical bulk repair, race_live, horse staging, news/QQ
Failure modes: 0 unhandled critical gaps

Next: Waiting for user product review. Implementation has not started.
```
