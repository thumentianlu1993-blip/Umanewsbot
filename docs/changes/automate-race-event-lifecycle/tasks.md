# 赛事日历自动更新与赛事生命周期任务

> 当前仅完成规划。未取得实现授权前，以下测试/实现任务全部保持未开始。

## 阶段 A：生命周期自动推进

### 测试

- [ ] (application) 为有时间、无时间、延期、取消、幂等、回滚和 cache 失效编写测试并取得真实 RED。
- [ ] (application) 为 London/Paris/纽约/洛杉矶 DST 与无效时区编写纯决策 RED。
- [ ] (integration) 在临时 PostgreSQL 为双 worker、expired claim、generation 漂移编写竞争 RED。
- [ ] (operations) 为 mode 默认 off、Beat selector 有界和 dry-run 零写编写配置/任务 RED。
- [ ] (application) 为显式纳管、重复 manifest、资格失效和不在 manifest 的新赛事编写 RED。
- [ ] (application) 为 shadow proposal -> 首次 enforce applied -> enforce replay 编写 RED。
- [ ] (operations) 为 baseline/rollback manifest SHA、漂移拒绝和反向 dry-run 编写 RED。

### 实现

- [ ] (application) 新增 lifecycle control、transition、field authority/change 模型与迁移。
- [ ] (application) 实现纯生命周期决策和原子 apply，复用 `RaceEvent.status`。
- [ ] (application) 实现后台只读状态、最近错误/变更和 cache on-commit 失效。
- [ ] (integration) 实现 bounded scanner、claim TTL、generation 与任务幂等。
- [ ] (integration) 实现 manifest 驱动、分页 500 的 lifecycle control 纳管/资格 reconciler。
- [ ] (operations) 增加默认 off 配置、Beat 5 分钟入口和 shadow/enforce 开关；dry-run 只走
  一次性零写管理命令。
- [ ] (operations) 实现逐场 baseline/rollback manifest、SHA/漂移校验和反向 candidate。

### 验证

- [ ] (application) 运行生命周期聚焦测试、赛事页面/字段归一化回归。
- [ ] (integration) 运行 PostgreSQL 并发、Celery eager/worker、race-live 回归和查询数测试。
- [ ] (operations) 运行 Django check、迁移往返、migration drift、Compose config、diff check。

### review

- [ ] (operations) 冻结 uncommitted fingerprint，由未参与实现的 reviewer 执行原生只读 `/review`。
- [ ] (application) 修复 actionable findings，并复用同一 reviewer 会话限定复审。
- [ ] (operations) review 通过后记录 approved parent/content hash 并停止等待发布授权。

### 发布

- [ ] (operations) 最新 review 后取得当前阶段发布授权，才允许 commit/push/PR。
- [ ] (operations) 备份、核对生产 HEAD/image/队列/锁/磁盘，先部署 mode=off。
- [ ] (operations) 冻结逐场 baseline manifest，再依次一次性 dry-run、shadow、小范围
  enforce；每步独立验收/回滚。
- [ ] (operations) 完成 evidence-only 状态文档收尾并复用代码 reviewer 审核。

## 阶段 B：赛前结构化资料

### 测试

- [ ] (integration) 按地区为已批准 provider 的出马/时间/骑师/闸位/退赛/延期建立离线 fixture RED。
- [ ] (application) 为字段 authority、人工锁、冲突、相同值重放和 omission 非退赛建立 RED。
- [ ] (application) 为同场多 participant 的 stable subject identity 与独立字段更新建立 RED。
- [ ] (integration) 为 provider budget、429/circuit、地区隔离和赛日请求合并建立 RED。
- [ ] (integration) 为商业来源按 provider/region/field/result phase/`provider_contract_version` 授权、
  合同到期和 schema 漂移 fail-closed 建立 RED。
- [ ] (integration) 为 JRA/NAR identity 分流、爱尔兰拒绝纳管、NAR 合同缺失关闭建立 RED。
- [ ] (integration) 为 JRA snapshot 签名/hash/marker、build/schema/contract/fencing 漂移、乱序、
  缺前驱、重放和事务水位原子性建立 RED。
- [ ] (integration) 为 TRA 法国逐场缺口、North America omission 非退赛和 provider 独立
  kill-switch 建立 RED。

### 实现

- [ ] (integration) 每个地区先完成字段级 source proof/registry 审批，不通过的 provider 保持关闭。
- [ ] (integration) 复用 racecard revision、HostBudget 与 candidate 接入赛前 refresh。
- [ ] (application) 实现 field authority 比较、审计、人工冲突处理。
- [ ] (operations) 配置 P0/P1 窗口和每来源预算，不把数值散落在任务中。
- [ ] (operations) 为通过采购和 proof 的商业来源建立不含凭据的 registry/合同版本清单；
  订阅、proof、registry 批准和生产启用保持独立。
- [ ] (integration) 实现 JRA Windows collector 的不可变签名 snapshot importer；collector
  不得连接生产业务数据库，MCP 不进入自动写链路。
- [ ] (operations) 固化 collector/build/schema/contract/fencing registry、SFTP-only 拉取、
  payload 30 天保留、manifest/receipt 长期保留和 RPO/RTO 告警。

### 验证

- [ ] (integration) 逐地区离线/受控 proof、失败恢复、N+1 与请求预算验收。
- [ ] (application) 后台字段变更、退赛/延期/取消显示和移动端回归。
- [ ] (operations) 确认阶段 A 与现有 race-live 不重复写同一 projection。

### review

- [ ] (operations) 独立只读代码 review、同会话复审、fingerprint 冻结。

### 发布

- [ ] (operations) 每地区/来源独立授权、独立开关、独立小范围 enforce。

## 阶段 C：赛事影响新闻

### 测试

- [ ] (application) 为 impact schema、唯一赛事身份、只出现赛事名不放行和低置信不写入建立 RED。
- [ ] (application) 为软门禁绕过和全部硬门禁保留建立 RED。
- [ ] (application) 为 spec 9.4 每个 hard reason code（显式包含 `possible_duplicate_content`）与未知 blocker 默认 hard 建立回归。
- [ ] (integration) 为发布事务/on_commit candidate apply、重放和失败解耦建立 RED。
- [ ] (integration) 为 QQ 唯一性和默认 racecard_update 不自动 QQ 建立回归。

### 实现

- [ ] (application) 新增 assessment 模型/分类器、后台解释和人工审核。
- [ ] (application) 拆分 hard readiness 与 normal soft policy，增加特殊小配额。
- [ ] (integration) 发布成功后才派发候选应用，复用 field authority。
- [ ] (operations) 增加 classifier shadow/特殊发布 enforce/字段自动应用三个独立开关。

### 验证

- [ ] (application) 运行 translation/validation/dedupe/publishing/attribution 回归。
- [ ] (integration) 运行重复发布、事务失败、QQ delivery 回归。
- [ ] (operations) 用人工标注 gold set 验收 precision，未达门槛不得 enforce。

### review

- [ ] (operations) 独立只读代码 review、同会话复审、fingerprint 冻结。

### 发布

- [ ] (operations) 先 shadow 分类，再只启用发布绕过，最后另授权字段自动应用。

## 阶段 D：赛中与赛后赛果

### 测试

- [ ] (integration) 为 T+3、T+30、无时间次日、provisional/official/corrected 建立 RED。
- [ ] (integration) 为 T+0 只推进/零 transport、T+3 首次联网和既有 tracking 兼容建立 RED。
- [ ] (integration) 为 selector 与 lifecycle 不重复 dispatch、supplemental 不升 official 建立回归。
- [ ] (operations) 为 scheduler/region/source/event 四层默认关闭与 kill-switch 建立回归。
- [ ] (integration) 为 JRA 三名/五名/全马最终/更正 marker、未知 marker fail-closed 和 NAR
  独立 marker 合同建立 RED。
- [ ] (integration) 为美国官方复核长期缺失保持 provisional/official-overdue 建立 RED。

### 实现

- [ ] (integration) 复用现有 selector/race_live_worker/revision 接入已批准赛事。
- [ ] (application) 将 finished/result pending/official confirmed 的展示语义明确分离。
- [ ] (operations) 仅为通过 proof 的地区/赛事配置 allowlist 和观察窗口。
- [ ] (integration) 将 JRA-VAN raw marker 通过版本化 registry 映射到
  provisional/official/corrected；collector 版本仅记 provenance。

### 验证

- [ ] (integration) event 924 与新增至少两个地区、有/无时间赛事的 shadow 回归。
- [ ] (application) 日历/详情 provisional/official 标签一致。
- [ ] (operations) worker/beat/race_live_worker、healthz、队列、锁、错误率验收。

### review

- [ ] (operations) 独立只读代码 review、同会话复审、fingerprint 冻结。

### 发布

- [ ] (operations) 只在最新 review 后取得精确授权，按 event allowlist 小范围启用。
