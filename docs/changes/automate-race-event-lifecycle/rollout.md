# 赛事日历自动更新与赛事生命周期发布方案

## 1. 并行边界

当前新闻正文历史批次可以与本任务的探索、设计、本地测试和本地实现并行，但下列生产动作
必须互斥并进入同一个维护窗口协调：

- 生产数据库写入/迁移；
- Celery Beat 调度变更；
- web/worker/beat/race_live_worker 重建或重启；
- lifecycle/news/live 开关切换；
- 赛事或新闻批量写入；
- 部署。

发布前必须只读确认正文批次没有 active DB apply、锁、待提交原子事务或需保持的 worker。
本任务不能中断正在执行的原子写入；先等其到安全检查点。

## 2. 独立开关

建议：

- `RACE_EVENT_LIFECYCLE_MODE=off|shadow|enforce`
- `RACE_EVENT_LIFECYCLE_ENABLED_REGIONS=`
- `RACE_EVENT_LIFECYCLE_EVENT_ALLOWLIST=`
- `RACE_EVENT_PRERACE_REFRESH_ENABLED=false`
- `RACE_PROVIDER_TRA_CORE_MODE=off|shadow|enforce`
- `RACE_PROVIDER_TRA_NORTH_AMERICA_MODE=off|shadow|enforce`
- `RACE_PROVIDER_JRA_SNAPSHOT_MODE=off|shadow|enforce`
- `RACE_PROVIDER_NAR_CSV_MODE=off|shadow|enforce`
- `RACE_NEWS_IMPACT_CLASSIFIER_MODE=off|shadow|enforce`
- `RACE_NEWS_SOFT_GATE_BYPASS_ENABLED=false`
- `RACE_NEWS_FIELD_AUTO_APPLY_ENABLED=false`
- 既有 `RACE_LIVE_SCHEDULER_ENABLED=false`
- 既有 `RACE_LIVE_MONITOR_ENABLED=false`
- 既有 `RACE_LIVE_ENABLED_REGIONS=`

不得用一个总开关同时启用生命周期、新闻绕过和赛果来源。
阶段 B0.1 不增加内部参考配置开关或 Celery 调度；只接受 manifest-bound one-shot 命令。内部
参考链也不设计 publication/apply 开关，不存在通过配置把内部观察公开的合法路径。

## 3. 阶段 A 发布

### 3.1 部署但关闭

1. 核对 review fingerprint、approved parent/content hash。
3. 等新闻正文批次进入安全检查点。
4. 备份数据库并验证可恢复；记录旧 HEAD/image/env filtered hash。
5. 核对生产 HEAD、四应用 image、Celery active/reserved/scheduled、race_live queue、
   历史 runner/正文批次锁、数据库锁、磁盘。
6. 部署迁移，所有新 mode 保持 off；不创建 enabled control。
7. 验证 Django check、migration plan、四应用镜像、healthz、日历/详情。

### 3.2 dry-run

- 使用一次性只读管理命令，不启动/复用 Beat claim；数据库零写、Celery 零 dispatch；
- 只计算未来 14 天和过去 7 天的重点赛事；
- 每批最多 100，不写 DB；
- 输出 proposed/noop/error 数、地区/时区/有无时间分布；
- 抽检至少日本、香港、英国、法国、美国和美国两个时区；
- 不调用任何 provider。

### 3.2.1 纳管与逐场回滚基线

进入 shadow 前生成 lifecycle enrollment/baseline manifest，至少包含：

- schema/version、生成代码 commit、event IDs；
- 每场 priority/is_featured/visibility/status、region/timezone/local date/time/race_datetime；
- source/projection owner、live tracking/revision 摘要；
- control mode/generation/next refresh；
- 内容 canonical SHA-256 和整份 manifest SHA-256。

默认 dry-run；显式 apply 必须给出精确 SHA。重复 apply 为 replay。进入 enforce 前再冻结一份
逐场 rollback baseline；反向 candidate 必须核对 event generation、当前 status、字段 authority、
live revision 和后续人工变更。任一漂移即拒绝该场，不批量覆盖。发布前在隔离 PostgreSQL 至少
演练一次 baseline -> enforce sample -> reverse dry-run/apply -> verifier。

### 3.3 shadow

- 只写 lifecycle transition candidate/audit，不改 `RaceEvent.status`；
- 观察至少 48 小时并跨一个实际赛日；
- 对每条 proposed transition 与人工时间计算比对；
- 0 个时区隐式 fallback、0 个 cancelled/postponed 错推、0 个重复审计。

### 3.4 小范围 enforce

allowlist 至少包含：

- 两个地区；
- 一场有 `race_datetime`；
- 一场仅有 `local_date`；
- 一场 postponed/cancelled 负例；
- 不包含 event 924 的 publication policy 改动。

观察至少一个完整赛后边界，再扩大。阶段 A 不打开 race-live scheduler。

## 4. 阶段 B/C/D

- B：每个 provider 单独 proof、registry、预算和授权；先 candidate-only，再 field enforce。
- B0.1：Sporting Life、ZEturf、HRN 先进入独立 internal reference run/payload/receipt，永不进入
  candidate apply、public projection、新闻或 QQ。
- C：classifier shadow -> soft-gate bypass -> field auto apply 三步分开；先用人工 gold set，
  建议 precision >= 98%、错误赛事写入为 0。
- D：先 shadow observation，再单 event provisional；official 仅官方 authority/marker。
- 商业来源：付款不等于生产批准。固定顺序为书面许可/报价 -> 单月或按场 proof -> schema/身份/
  延迟报告 -> registry 独立审核 -> 小范围 shadow -> 用户授权 enforce。合同到期或
  `provider_contract_version` 漂移必须自动 fail closed。

地区/provider 增量门禁：

- 爱尔兰不属于本 change，selector 必须拒绝，不得映射为英国或 `other`。
- TRA Core 的英国、香港、法国和 TRA North America 分开开关、预算、circuit 和回滚；
  法国逐场缺失、NA `changes` 语义未知均 fail closed。
- JRA provider 只接受 registry 活动 collector/build/schema/contract/fencing token 签发的连续
  Ed25519 snapshot。shadow 前演练不完整 marker、坏签名、乱序、重放、split brain、事务失败和
  high-watermark 恢复。
- JRA collector 通过 SFTP-only 只读出口交付，防火墙只允许生产出口 IP；它无生产 DB 凭据。
  payload 保留 30 天，manifest/receipt 长期保留；赛日 RPO 5 分钟/RTO 30 分钟门禁不满足时
  自动告警并保持 pending。
- JRA 与 NAR 使用独立 identity/marker 合同和 kill-switch。NAR 许可/合同未冻结时 mode 必须 off。
- JRA 结果先观察三名、五名、全马最终和更正四阶段；未知 marker 不得 official。
- 美国没有官方复核时，TRA 结果只能保持 provisional/official-overdue。

JRA rollback 演练顺序：关闭 provider mode -> 撤销活动 fencing token/验签公钥 -> 停止 snapshot
拉取 -> 验证旧 snapshot 重放零写。已应用高权威事实不批量反写；逐字段 reverse candidate 需
人工批准并核对后续来源/人工锁漂移。

一次部署不得同时启用：

1. 全部赛事生命周期 enforce；
2. 新闻软门禁绕过；
3. 新赛果来源；
4. 全历史状态修正。

### 4.1 阶段 B0.1 赛后内部参考源

1. **离线 GREEN**：只运行冻结 fixture/parser/reference schema/隔离测试。
2. **关闭部署**：新增 schema/code/命令，但不增加 Beat/task/queue/worker；零网络、零业务写入。
3. **one-shot 网络 dry-run**：每来源使用精确 event manifest 和请求上限，只写受限 raw cache/
   artifact，不写数据库；需要单独联网授权。
4. **小范围 internal record**：每来源最多少量已人工核对赛事，只写 reference 三表；需要独立
   业务写入授权。
5. **连续观察**：至少 7 天，覆盖英国、法国、美国各一个真实赛日；每天每来源使用新 manifest
   显式执行 one-shot collect/record，不启用 lifecycle、race-live、新闻或 QQ 新行为。
6. **观察报告**：覆盖率、首次可用时间、字段完整率、partial、match conflict、403/429/timeout、
   request/cache 数；公开对象变化必须为 0。

扩大内部观察也必须按来源分别授权。Sporting Life、ZEturf、HRN 的连续观察成功不构成公开数据
源 proof，不会提高 field/result authority。

## 5. 观察门禁

每阶段至少观察：

- due/claimed/applied/replayed/conflicted/error；
- p50/p95 task latency；
- 每 provider request/429/403/timeout/circuit；
- 状态错误率、字段冲突率；
- provisional 到达时间、official overdue；
- internal reference matched/ambiguous/partial、来源延迟与 route/schema drift；
- 新闻 impact precision、特殊发布数、hard blocker 分布；
- 重复公开/重复 QQ 必须为 0；
- Celery queue age、active/reserved、数据库锁；
- 日历/详情缓存与 HTTP/浏览器一致性。

扩大范围需要人工抽检与错误率门禁，不能仅凭 task success。

## 6. 回滚

### 6.1 行为回滚

按影响最小顺序：

1. 关闭对应 enforce/bypass/provider 开关；
2. 清空 enabled regions/event allowlist；
3. 保持 audit/revision，不删除证据；
4. 停止新 selector claim，等待 active claim TTL/安全完成；
5. 必要时回滚应用镜像。

内部参考链没有常驻 collection 或 queue。回滚时停止后续 one-shot 命令并保留
run/payload/receipt 审计；它不应需要回滚任何公开赛事、赛果、新闻或 QQ。raw cache 清理按
保留策略另行执行，不作为紧急回滚的一部分。

`RaceEvent.status` 回滚不能简单批量改回 scheduled。只允许使用 enforce 前冻结 manifest，
逐场核对当前 generation、后续人工/高权威变化、结果 revision 后生成反向 candidate；有漂移
则人工处理。official/corrected 绝不由通用回滚降级。

### 6.2 数据/迁移回滚

- 新表为 additive；关闭开关后可保留审计表。
- reverse migration 只能在确认没有生产审计需保留、完成备份并获独立授权后执行。
- 新闻 special assessment 可以保留；撤回新闻与回滚赛事字段是两个独立动作。

## 7. 生产验收

1. 有时间赛事到点 running、T+30 finished；无时间赛事当地次日 finished。
2. cancelled/postponed 不误推，改时只采用新 generation。
3. 来源失败不阻断状态，且没有虚假 result。
4. provisional/official/corrected 与 finished 区分。
5. 日历/详情状态一致；1440/390/320 无回归。
6. 特殊新闻只绕过软门禁，翻译/重复/完整性仍阻断。
7. 低权威字段冲突进入审核，不覆盖官方。
8. 没有重复发布、QQ、transition、field change。
9. web/worker/beat/race_live_worker 健康，内外 healthz 正常。
10. queue、error log、数据库锁、磁盘正常。

## 8. 当前发布状态

阶段 A：`DEPLOYED DISABLED / DRY-RUN COMPLETED / SHADOW NOT AUTHORIZED`

阶段 B0.1：`PLAN REVIEW APPROVED / WAITING IMPLEMENTATION AUTHORIZATION / NOT IMPLEMENTED /
NOT REVIEWED FOR CODE / NOT DEPLOYED`

本轮方案通过后也只进入阶段 B0.1“等待实现确认”，不是发布、联网或生产写入授权。
