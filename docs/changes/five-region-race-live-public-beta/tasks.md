# 五地区准实时赛果公开 Beta 任务

## 1. 方案与来源

- [x] (integration) 建立最新 `origin/main` 独立 worktree，确认无历史任务脏改动。
- [x] (operations) 只读核对生产 revision、容器、healthz、scheduler、tracking、
  allowlist、policy 和未来五地区目标总量。
- [x] (integration) 联网核对 TRA 官方文档、coverage、条款、Free endpoint/限速。
- [x] (integration) 使用现有 Free 账户做四次最小只读探测，记录地区/racecard/results
  实际计数，不保存原始 payload。
- [x] (integration) 完成 spec/design/test_cases/tasks/rollout 方案审核并关闭 P0/P1。

## 2. RED

- [x] (integration) 新增 TRA registry v2/URL builder RED。
- [x] (integration) 新增五地区 racecard/timezone/identity/artifact RED。
- [x] (integration) 新增共同 eligibility matrix/exception artifact RED；香港与日本均覆盖
  G/Jpn/JG 1-3，未知/Listed/Open 保持 fail-closed。
- [x] (integration) 新增赛前 racecard refresh/off-time/source-gap RED。
- [x] (application) 新增 enabled-region selector/worker preflight RED。
- [x] (integration) 新增地区快照/cache/pagination/host budget RED。
- [x] (application) 新增通用 publication transition 和跨 event 隔离 RED。
- [x] (integration) 新增通用 official route/receipt/邮件 RED。
- [x] (application) 新增独立 official authorization/read gate/migration RED。
- [x] (integration) 新增 SLA monitor/alert incident/delivery lease RED。
- [x] (application) 新增前台 provisional/official/corrected/conflict/event-off RED。
- [x] (integration) 新增 PostgreSQL claim/CAS/transition 竞争 RED。
- [x] (integration) 实际运行并记录目标能力缺失导致的 RED 证据。

## 3. 实现

- [x] (integration) 升级 TRA registry schema、五地区路由和镜像/Compose SHA。
- [x] (integration) 泛化 racecard prepare、timezone、名称/场地匹配和 initializer v2。
- [x] (integration) 实现共同 eligibility core 和 exception artifact 复核；Jpn/JG 仅使用
  总账既有标准化等级，不按地区或名称推导；exception 通过 `0600` 独立文件输入并把完整
  严格 schema/digest 绑定进 manifest 供 initializer 重验。
- [x] (integration) 实现 pre-off racecard refresh、immutable revision 和 off-time CAS。
- [x] (application) 增加 `RACE_LIVE_ENABLED_REGIONS` 默认空和 selector/preflight 门禁。
- [x] (integration) 实现地区 results 快照、150 秒 cache、严格分页和 batch 复用。
- [x] (integration) 保持 TRA supplemental、observation/revision/admission 幂等链。
- [x] (application) 泛化 single-event promotion/disable/restore CAS transition。
- [x] (integration) 新增五地区 manual official route registry，泛化 receipt/apply/email。
- [x] (application) 新增 official authorization/alert incident/publication audit migration。
- [x] (application) 在同一 migration 增加专用 provisional rollback pointer 和严格回填。
- [x] (application) 实现 official/corrected 独立 admission/read gate。
- [x] (application) 实现单事务 emergency provisional pointer/legacy/tracking restore。
- [x] (application) 实现可在精确维护 off 下验证计划 policy 的 rollback-target validator。
- [x] (operations) 实现冻结 release image 的 validator/policy-restore one-shot 命令契约，
  强制 image ID、manifest SHA、filtered env SHA、只读 validator 和 secret-free mount。
- [x] (operations) 实现 filtered rollback env 生成器与 pre-Django wrapper：严格 DB
  allowlist、禁止来源/SMTP/通知/Celery 凭据、固定安全 backend/flags、`0600` 和 SHA。
- [x] (integration) 实现 Beat SLA monitor、持久去重和事务外 SMTP delivery/retry。
- [x] (application) 修正前台 corrected/source 文案和多 event read gate 回归。
- [x] (operations) 更新 `.env.example`、三份 Compose、Dockerfile、部署脚本和资源限制。
- [x] (operations) 在完整 review 前更新 current_state/project_status/decisions/
  deploy_runbook 预期行为和精确命令。

## 4. GREEN/REFACTOR

- [x] (integration) 逐个 RED 切片转 GREEN，保留无网络 fixture。
- [x] (integration) 运行准实时相关 SQLite 组合。
- [x] (integration) 运行 PostgreSQL 专项竞争测试。
- [x] (application) 运行前台详情/日历/缓存回归。
- [x] (operations) 运行 Django check、compileall、migration drift、Compose config 和镜像
  registry SHA 检查。
- [ ] (operations) 验证 migration 前后 event 924 provisional 页面不变，并验证旧 image
  回滚前 `scheduler/monitor/global/event off` 下的 provisional pointer restore、分层
  policy restore 和最终 read gate 演练。
- [ ] (operations) 模拟 app services 已切 old image，仍用 reviewed release image ID
  完成只读 validator、global/region/source restore、再次 validator、event-final restore。
- [ ] (operations) 在上述模拟中断言 one-shot 容器无 TRA/SMTP/通知/真实 Celery 凭据，
  validator DB 只读，restore 除 manifest 允许 policy 外零写入。
- [x] (integration) 检查凭据、原始响应和第三方版权字段未进入 git diff/artifact。

## 5. 独立代码审核与冻结

- [x] (integration) 由未参与实现的 reviewer subagent 实际执行
  `codex review -c 'sandbox_mode="read-only"' --uncommitted`；首次结论为
  `CHANGES_REQUIRED`。
- [x] (integration) 修复首次 review findings。
  - [x] (application) 以 40 场 official/corrected RED 修复 bulk read gate N+1。
  - [x] (integration) 以原始页首/中/末截断 RED 修复地区过滤前分页完整性校验。
  - [x] (integration) 保留 pagination 结构化 checkpoint 并贯通 monitor incident。
  - [x] (integration) 统一十页 results deadline 与 Celery 软硬时间预算。
- [ ] (integration) 复审复用同一 reviewer session，只核对 findings、修复及直接路径。
- [ ] (operations) 记录 scope、approved parent、fingerprint 和 content manifest SHA。
- [ ] (operations) 最新 review 成功后停止，取得当前冻结版本的用户发布授权。

## 6. 部署

- [ ] (operations) 发布前备份数据库并独立校验 checksum/restore list。
- [ ] (operations) stage/commit/push exact reviewed content，构建 AMD64 image，核对 OCI
  revision/tree/registry SHA。
- [ ] (operations) 冻结 reviewed release/old rollback 两份 image digest 和 rollback
  manifest SHA，稳定窗口结束前不删除。
- [ ] (operations) 部署代码，初始保持 scheduler false、enabled regions 空。
- [ ] (operations) migrate/check/collectstatic，核对 web/worker/beat/live worker、队列、
  healthz、日志和资源。
- [ ] (operations) 验证 event 924 页面和 kill switch 无回归。

## 7. 五地区 shadow/public Beta

- [ ] (integration) 对当前有 racecard 的显式 event 生成 prepare artifact。
- [ ] (operations) 每个 artifact 单独 dry-run/apply/verify/replay，默认 shadow。
- [ ] (operations) 按地区逐个加入 `RACE_LIVE_ENABLED_REGIONS`，先 scheduler false 手动
  claim/dispatch smoke。
- [ ] (operations) 取得首次 shadow result、完整性、identity、cache/pagination和延迟证据。
- [ ] (operations) 执行 official manual route preflight 和 SMTP 告警 smoke。
- [ ] (operations) 对通过门槛的 event 生成 promotion/disable/restore bundle。
- [ ] (operations) scheduler/monitor false 且 queue/claim 排空后，生成 coarse official
  scope + event authorization bundle。
- [ ] (operations) 精确 event promotion 后验证详情、日历、状态、T+15m 告警和 kill switch。
- [ ] (operations) 只有已证明地区才开启 scheduler；未证明地区保持 off。
- [ ] (operations) 香港/日本 JG 若真实 coverage proof 不足，只能在运行开关或获准
  deferred artifact 层暂缓，不得从代码资格矩阵或正式范围分母删除。

## 8. 收尾

- [ ] (operations) 报告各地区 `code_ready/racecard_seen/shadow_result_seen/public_eligible`
  的真实状态。
- [ ] (operations) 执行 event 级和 global kill switch 演练。
- [ ] (operations) 完成 evidence-only closure 文档和同一代码 reviewer evidence review。
- [ ] (operations) 提交 evidence patch，不为记录 evidence commit SHA 制造递归 patch。
- [ ] (integration) 建立上线后回归清单和 P50/P95 样本积累，不把未证明地区称为上线。
