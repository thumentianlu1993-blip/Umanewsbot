# 赛事日历自动更新与赛事生命周期任务

> review 首轮及第二轮限定复审均为 `REVISE`；两轮各 4 项 P2 均已按新增真实 RED 修复，
> 第三轮确认上一轮 4 项 P2 全部关闭，但新增 1 项 P1 与 3 项 P2；均已按新增真实 RED 修复，
> 第四轮关闭其中 3 项、另 1 项部分关闭，并留下 2 项 P2；均已按真实 RED 修复，
> 第五轮确认前 2 项 P2 关闭，但新增 4 项 P2；均已按真实 RED 修复，
> 第六轮确认前 4 项 P2 关闭，但新增 5 项 P2；均已按真实 RED 修复，
> 第七轮确认前 5 项 P2 关闭，但新增 3 项 P2；均已按真实 RED 修复，
> 第八轮发现唯一 P2 并以 3 项真实 RED 修复，
> 第九轮新增 1 项 P1 与 3 项 P2；均已按真实 RED 修复，
> 第十轮唯一 P2 也已以 2 项真实 RED 修复，
> 第十一轮 2 项 P2 已以 3 项真实 RED 修复，
> 第十二轮 2 项 P2 也已按反例 RED 修复，
> 第十三轮 3 项 P2 已以 3 项真实 RED 修复，
> 第十四轮 2 项 P2 也已按真实 RED 修复，
> 第十五轮 2 项 P2 已以重签 artifact 真实 RED 修复，
> 第十六轮唯一 P2 已以 6 项真实 RED 修复；第十七轮同一 reviewer 已 `APPROVED`。
> 用户随后授权 fetch/commit/push/Draft PR，但 `origin/main` 前进 14 个提交，候选已迁移到
> 联网、部署、生产迁移和生产写入仍未授权。

> 状态更正：阶段 A 已完成实现、review、关闭态部署和一次生产零写 dry-run，但 shadow/enforce
> 仍未授权。以下阶段 A 清单保留为历史设计基线；本轮待实现范围是阶段 B0.1。

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

### 发布

- [ ] (operations) 备份、核对生产 HEAD/image/队列/锁/磁盘，先部署 mode=off。
- [ ] (operations) 冻结逐场 baseline manifest，再依次一次性 dry-run、shadow、小范围
  enforce；每步独立验收/回滚。
- [ ] (operations) 完成 evidence-only 状态文档收尾并复用代码 reviewer 审核。

## 阶段 B：赛前结构化资料

### 阶段 B0.1：赛后内部参考源

#### 测试

- [x] (integration) 为 Sporting Life、ZEturf、HRN 统一 reference schema 编写 fixture 测试并取得真实 RED。
- [x] (application) 为内部 run/payload/receipt、semantic/provenance hash、跨 run 重放、变化版本、
  重新匹配、歧义和 partial 编写 RED。
- [x] (application) 为 public/admin 隔离、无 promotion、公开查询零读取编写 RED。
- [x] (integration) 为 manifest canonical SHA/DB drift/provider key/host-path、collect/record 分离、
  事务并发和 run-local 预算编写 RED。
- [x] (integration) 为 legacy official 字段降权、schema/response 大小和 artifact COMPLETE 编写 RED。
- [x] (integration) 为 collection 不触发 data candidate、race-live、lifecycle、新闻和 QQ 编写 RED。

#### 实现

- [x] (application) 新增内部 reference run/payload/receipt 模型、additive migration 和只读 admin。
- [x] (integration) 抽取三个赛后 parser 的 parse-only API，并让历史 CLI 与 reference wrapper
  复用同一实现，输出精确 v1 reference schema。
- [x] (integration) 实现只读 manifest build、manifest-bound collect、离线 record、report 命令；
  禁止 auto-discover。
- [x] (integration) 为 safe HTTP 增加 content type、4MiB 双重上限和最多 2 次逐跳重验。
- [x] (application) 保证服务层不调用 candidate apply、race-live projection、news/QQ。

#### 验证

- [x] (integration) 运行三 parser 历史回归、reference 聚焦测试和 PostgreSQL advisory lock/事务测试。
- [x] (application) 运行公开日历/详情/API/sitemap/cache/query-count 与 admin 权限回归。
- [ ] (operations) 运行 lifecycle/race-live/news/QQ 回归，确认未新增 Celery route/Beat/worker，
  再运行 Django check、migration drift、Compose 和 diff check。
  - 已完成除 Compose 外的本地验证；两组组合回归各有 1 项纯 `origin/main` 可复现的既有失败。
  - Compose 因隔离 worktree 缺 `.env` 未成功执行，故本项保持未完成。

#### review

- [ ] (operations) 冻结 uncommitted fingerprint，由未参与实现的 reviewer 执行原生只读 review。
  - 首轮 session `019fa021-3552-7f23-a17f-2cae48ccc4bb` 对 fingerprint
    `f2463878ffa4011aa91cf5b3cd7c5fe817b66157691e9eaf6e309640623695cd`
    返回 `REVISE`（P0 0、P1 0、P2 4）。
  - 同一 reviewer 第二轮 inner session `019fa02f-1976-7d10-b177-a18a0216591e` 对
    fingerprint `561cdbf66dd3a26c702366bd113d2aed197dc98446eec34856d2c2c1350e9200`
    仍返回 `REVISE`（4 项直接 P2）。
  - 第三轮 inner session `019fa044-4483-72e1-b836-53e6900df34c` 对 fingerprint
    `22675d91cb097737bb678bd547874cce1ae1d7c481f416710911740a24981f06`
    关闭上一轮 4 项 P2，但新发现 1 项 P1、3 项 P2，结论仍为 `REVISE`。
  - 第四轮 inner session `019fa051-bcf9-7e71-bd04-f11090fe8112` 对 fingerprint
    `a3f862fd93041831250fe855e383ee911843f6eb940433604c5a08b1f835b63b`
    关闭其中 3 项、Sporting Life description 部分关闭，剩余 2 项 P2，仍为 `REVISE`；
  - 第五轮 inner session `019fa062-e917-76e2-aacd-e807fb0f1f9b` 对 fingerprint
    `50b50866f19853534daad66c9a2cd18650d4d74cafbfebec106b09c8b36c274d`
    关闭第四轮 2 项 P2，但新增 4 项 P2，仍为 `REVISE`。
  - 第六轮 inner session `019fa071-ca82-7b80-9af1-d4725efb6c` 对 fingerprint
    `41307729d9896c7fbd721b2e8864177990a7d190d3c25011b53a0bf284db0d87`
    关闭第五轮 4 项 P2，但新增 5 项 P2，仍为 `REVISE`。
  - 第七轮 inner session `019fa07f-90e2-7f60-b08d-125e01d55ba3` 对 fingerprint
    `6dd68951fe0ff90847c74f3873fb0539eec8226441473c294e7c444591ebba1a`
    关闭第六轮 5 项 P2，但新增 3 项 P2，仍为 `REVISE`。
  - 第八轮 review session `019fa08e-e782-7d31-9cbc-921bb3b4efbd`、fingerprint 前缀
    `d98034f…` 发现唯一 P2。
  - 第九轮 session `019fa09e-88c5-7180-a678-39874ff6e045` 对 fingerprint
    `84e8f4fafc4db634911c9aa18f6f473bdba12078e2957072a660434505c5ce6f`
    返回 `REVISE`（P1 1、P2 3）。
  - 第十轮 session `019fa0ad-c024-7a21-8ebb-31b19df760ab` 对 fingerprint
    `abbc00318318447abb86627ffe29a076012f8eceee4aa1b8d3f6c0c157dc4b20`
    返回 `REVISE`（唯一 P2）。
  - 第十一轮 session `019fa0b9-b2c8-77d0-9473-7caff58d87eb` 对 fingerprint
    `ef778594f1d471a239432c6bd65054dcb2491fb918c46a660ea321436a827b0d`
    返回 `REVISE`（P2 2）。
  - 第十二轮 session `019fa0c7-7f55-7960-9f5d-5b81ba13437c` 对 fingerprint
    `6b0246db6647786e351492822d86f70a8dd15dbb272a19a6a34a324f15ca7b3b`
    返回 `REVISE`（P2 2）。
  - 第十三轮 session `019fa0db-0a80-72c0-a6ad-bb1142432a83` 对 fingerprint
    `384ef97820f9e6d9c0c8f6df7190f1fb546746570aff018379b742a41e3b0c00`
    返回 `REVISE`（P2 3）。
  - 第十四轮 session `019fa0ea-65a3-7383-b208-c0f571e7b98a` 对 fingerprint
    `18ac8b531f2d123b132fbe45104999feeea814315087ac6e4cdc0d043a4baeae`
    返回 `REVISE`（P2 2）。
  - 第十五轮 session `019fa0fa-b908-7d43-9f7e-807bf132a9a3` 对 fingerprint
    `59ffcb96972cef74dcff8df87e5a9d1b0f3923ecf59f5f5b594e58e48594424f`
    返回 `REVISE`（P2 2）。
  - 第十六轮 session `019fa106-3b52-7a02-b756-31f718ffe4d0` 对 fingerprint
    `571664940ea3e77b60368fe4ddf72292404060fedfb27f281d6b7f7d1f815cc7`
    返回 `REVISE`（唯一 P2）。
  - 第十七轮 session `019fa113-9c02-7c63-b48d-466c40d323cf` 对 fingerprint
    `5095a06e326a9cef470f4ef5d2111c87e8daa77a45fbc9507a27b024369edea7`
    返回 `APPROVED`，P0/P1/P2/P3 均为 0。latest-main 集成改变了父提交和冲突文件，
    故本项保持未完成，等待集成版本复审。
- [ ] (application) 修复 actionable findings，并复用同一 reviewer 会话限定复审。
  - 首轮 collect 误绑定、ZEturf `R/C` 证明缺失、`source_only` `KeyError`、report 多日指标
    缺失已先补真实 RED 并由原实现 subagent 修复。
  - 第二轮 record racecourse 重验、report frozen event/date 过滤及默认开发 Compose parser
    可见性问题也已先补真实 RED 并修复。
  - 第三轮 safe HTTP MIME 全局回归、ZEturf `NP`、HRN 国家后缀、Sporting Life 下划线状态均已
    先补真实 RED；MIME 改为 opt-in，collect 显式 HTML/XHTML，三个 parser 统一规范化并保留
    raw 证据。
  - 第四轮 `ride_description` 下划线和 manifest parser identity 未绑定实际模块均已先补
    真实 RED；description 统一，parser 身份在 service/build/collect/record 全链 fail closed。
  - 第五轮 transport-only circuit、parse failure raw、HRN heading block 与唯一 15 秒 timeout
    均先补真实 RED；network/parse 分段、raw/response/parse_error ledger、严格 race block 和
    timeout 已修复。
  - 第六轮失败请求计数、HRN alias、ZEturf `FR + NP`、重复指标与 event-filtered run count
    均先补真实 RED；ledger phase/request_issued、显式双向 alias、迭代后缀和筛选后 distinct
    统计已修复。
  - 第七轮 ledger 完整性、unknown completeness 与 matched receipt `SET_NULL` 约束均先补
    真实 RED；精确 manifest 覆盖、unknown incomplete、matched snapshot + 新 matched event
    绑定已修复。
  - 第八轮 safe HTTP runtime 遮蔽问题先取得 3 项真实 RED；唯一实现已迁至
    `server/stable`，runtime 仅兼容 wrapper，collect 直接 import stable。
  - 第九轮 runtime CLI `sys.path`、event/raw 逐场绑定、`error_summary` 和无 receipt 失败 run
    报告均先补真实 RED 并修复。
  - 第十轮 observations 与 `outcome=parsed` ledger event 一一对应、`parse_error` 零
    observation 的合同先补 2 项真实 RED 后最小修复；既有正向 fixture 已改为合法
    `parsed + observation`，replay 继续验证。
  - 第十一轮共享 safe HTTP legacy 默认兼容与跨日 run 单日报告归属先取得 3 项真实 RED；
    legacy 默认不自定义 body cap/redirect 上限，collect 显式保留 `4MiB / 2 跳`，report
    按 event/date 归属并单列 `unattributed_errors`。
  - 第十二轮来源赛事名 exact normalized membership 与单日无 receipt 错误回退先取得反例
    RED；公开 normalization helper、manifest `normalized_accepted_race_names` + snapshot
    SHA、record exact membership 和 single-day fallback 已实现，过时 fixture 已同步。
  - 第十三轮 collect 异名降级、多日错误 `local_date` 与 event-filtered 无 receipt run
    分别取得真实 RED；collect exact frozen name 分类、逐 event 日期冻结与 record 核验、
    detail 驱动的 run 纳入及其他错误隔离均已实现，6 个旧 fixture 已补必需字段。
  - 第十四轮 artifact 采集窗口和失败 run 重复分组取得真实 RED；record 按最早 ledger
    `fetched_at` 与 artifact `completed_at` 原子保存签名窗口，拒绝逆序/naive/显著未来并
    容忍 5 分钟 clock skew；report 统一 receipt/error-detail run membership。
  - 第十五轮以重签 artifact 取得时间上界和逐 event provenance 反例 RED；record 要求
    `max(ledger fetched_at) <= artifact.completed_at`，且 observation 的 URL、时间及
    raw/ref/hash 与 manifest、parse ledger、response 逐 event 精确一致。
  - 第十六轮为 Payload/Receipt `QuerySet.update/bulk_update/delete` 绕过 append-only
    增加 6 项真实 RED 和 5 项实例/`SET_NULL` 正例；专用 QuerySet/Manager 已拒绝 Payload
    所有批量变更，Receipt 仅允许 Collector 精确清空 event FK，且无需迁移。
  - 第十七轮已无 actionable finding；之后 latest-main 集成保留上游 recovery-mode 和
    结果完整度检查，并继续委托唯一 stable parser。集成回归已通过，等待同一 reviewer 复审。

#### 发布

- [ ] (operations) 最新 review 后取得 commit/push/PR 授权；不得视为联网或部署授权。
- [ ] (operations) 独立授权后先部署 schema/code；B0.1 无调度入口，不触网、不 record。
- [ ] (operations) 再分别授权 one-shot 网络 collect、小范围离线 record 和 7 个逐日 one-shot 观察。
- [ ] (operations) 永不进入公开发布；如未来需要采纳，另立 change。

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
