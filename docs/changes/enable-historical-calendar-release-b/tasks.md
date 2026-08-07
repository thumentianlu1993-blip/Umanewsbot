# 历史赛历 Release B 任务

## 0. 设计与门禁

- [x] 0.1 (operations) 固化 Release A 生产基线、v1 census SHA、81 条分类与 14 个 series 的只读
  证据；明确本 change 不执行生产 apply
- [x] 0.2 (application) 完成独立方案审核并关闭所有 actionable findings
- [x] 0.3 (operations) 方案审核通过后向用户汇报范围、RED、数据边界和回滚，等待明确实现授权

## 1. 测试先行：migration 与 planner

- [x] 1.1 (application) 新增 `0071` 约束切换的 SQLite/迁移状态测试并取得旧行为 RED
- [x] 1.2 (application) 新增真实 PostgreSQL 正反 migration、唯一约束、锁和时长测试并取得 RED
- [ ] 1.3 (integration) 新增系列级 chain、duplicate boundary、同年多届、英国跨年 fixture 并取得
  v1 classifier 无法表达的 RED
- [x] 1.4 (integration) 新增 reviewed overlay、path owner、target reassignment、FK relation policy 与
  漂移拒绝 RED
- [x] 1.5 (application) 新增 apply/verifier/rollback 整批原子、exactly-once 和失败零写入 RED
- [ ] 1.6 (application) 新增 apply/maintenance exit 锁顺序真实 PostgreSQL 并发 RED
- [x] 1.7 (operations) 新增 forward/reverse schema preflight、停服前挂接及 B-only 状态禁止反向
  migration 的 SQLite/真实 PostgreSQL RED
- [x] 1.8 (integration) 新增脱敏固定 SHA 的 81 mismatch/14 series census fixture 守恒 RED，以及
  target supersession 拓扑和三类互斥 ledger RED
- [x] 1.9 (application) 为 reviewer session `019fc318-431e-7771-aa79-bf01a9fdb992` 的三个 P1
  取得直接 RED：未知 applied migration 被静默忽略、supersession datetime/string 比较失败、
  series/edition 链式交换触发即时唯一冲突；并覆盖 deploy/rollback preflight 失败边界

## 2. GREEN：Release B schema

- [x] 2.1 (application) 修改模型约束为 series/edition 与 active target series/year
- [x] 2.2 (application) 创建唯一 `0071_historical_calendar_release_b`，仅切换四个约束并保持
  `edition_year` nullable
- [ ] 2.3 (application) 验证 writer/materializer/importer 对新约束的兼容与 superseded target
  显式排除，禁止隐式 reclaim
- [x] 2.4 (operations) 实现只读 `check_historical_calendar_release_b_schema` forward/reverse 命令及
  candidate one-shot wrapper，输出 count/rows SHA 与 commit/image/schema/DB identity；在候选镜像
  构建后、应用停服和 `run_application_release.sh` 前挂接 forward preflight

## 3. GREEN：v2 系列级 artifact

- [x] 3.1 (integration) 把 mismatch 按 series 聚合并生成完整 event/target/path/dependency 图与
  series precondition SHA
- [ ] 3.2 (integration) 实现 duplicate equivalence 候选、ordinary chain、cross-year edition 与
  same-natural-year slug 的 fail-closed planner
- [x] 3.3 (integration) 实现 review template/overlay 校验与 v2 manifest/action scope；v1 不可升级复用
- [x] 3.4 (integration) 实现 relation policy allowlist，首版仅自动支持 retain_on_tombstone，其他策略
  无逐行 ledger 时 block
- [x] 3.5 (integration) 将 managed target/path、managed canonical link 与 immutable reverse
  dependencies 划为互斥 ledger；canonical link 两向拓扑受锁、漂移与 rollback 覆盖
- [x] 3.6 (integration) 实现 target supersession 同 series/edition、active survivor、单层无环强校验

## 4. GREEN：系列级 apply/verifier/rollback

- [x] 4.1 (application) 实现固定锁顺序和系列级 path owner 轮转、duplicate tombstone、canonical
  product link、event/target reassignment
- [x] 4.2 (application) 保持 manifest/approval/actor/write-flag/live-gate/receipt/no-replace rollback
  合同，并使所有 series 在单一事务内原子提交
- [x] 4.3 (integration) 扩展 verifier 覆盖自然年、series/edition、active target、registry owner、
  tombstone/link、retain SHA 与临时 key 零残留
- [x] 4.4 (integration) 扩展 exact rollback；post-state 漂移时 fail closed
- [ ] 4.5 (application) 统一 apply 与 maintenance exit 锁顺序，关闭 Release A 遗留理论 P2
- [x] 4.6 (application) 未知 `stable.*` applied migration fail closed；supersession 时间戳统一为
  UTC 微秒表示；apply 使用 manifest-bound 临时 event/path identity 并先解除 series/edition 键，
  保持最终状态、ledger、verifier 与 rollback 合同

## 5. REFACTOR 与验证

- [ ] 5.1 (integration) 消除 v1/v2 artifact、digest、controlled read 和 dependency enumeration 重复，
  保持 v1 只读兼容但禁止 apply
- [x] 5.2 (application) 运行 Release B 聚焦 SQLite 与真实 PostgreSQL 两轮验证，记录 RED/GREEN、
  migration 时长、锁与查询/性能门槛
- [ ] 5.3 (application) 运行受影响回归、Django check、migration drift/graph/owner、完整 stable 并与
  主线失败集合比较
- [x] 5.4 (operations) 验证两份 Compose config、停服前 preflight、部署/反向 migration/备份/恢复
  命令和 runbook；将“81 mismatch 清零”改为“v1 census 冻结且 schema preflight 通过”
- [x] 5.5 (operations) 更新 current_state、project_status、decisions、deploy_runbook 与本 change
  rollout；保持生产与本地证据分层

## 6. 审核与发布门禁

- [ ] 6.1 (application) 由未参与实现的独立 reviewer 在只读模式审核完整 diff，并冻结 fingerprint
- [ ] 6.2 (operations) 最新 review 成功后另行等待 commit/push/PR/Release B 发布授权
- [ ] 6.3 (operations) Release B 关闭态部署，保存备份、旧 image、commit/image/migration leaf；不
  执行 v2 census 或数据 apply
- [ ] 6.4 (operations) evidence-only 收尾并复用同一代码 reviewer 会话审核事实文档

## 7. 后续阶段（不属于本 change 的自动动作）

- [ ] 7.1 (integration) 另行取得生产只读授权，生成 v2 census/review template
- [ ] 7.2 (application) 完成人工 survivor/chain/path/FK overlay 审核并冻结新 SHA
- [ ] 7.3 (operations) 另行取得生产写入授权，maintenance + 备份 + apply + verifier + 公网抽检
- [ ] 7.4 (operations) verifier 清零后另建 Release C change
