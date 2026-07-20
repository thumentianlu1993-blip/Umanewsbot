## 0. Pre-declared hypotheses

- [x] 0.1 (operations) 在实现前确认滚动批次默认阈值：每地区每批 100 匹、单批五地区合计不超过 500 匹；无 `--regions`/`--profile-ids` 且无显式上限时抓取命令 fail closed；显式调大上限需操作者确认并记录原因。（用户 2026-07-21 确认）
- [x] 0.2 (operations) 在实现前确认滚动批次批准机制：每批 manifest 必须人工批准（reviewer、approved_at、逐模块批准覆盖），apply 绑定“显式传入 SHA + 文件字节 SHA”；每批复审产物为指定本地目录下的单独文件（默认 Excel 工作簿，地区分 sheet + 逐匹摘要 + 异常抽样页）；首批硬编码可信白名单仅保留给首批 artifact 幂等复验。（用户 2026-07-21 确认）
- [x] 0.3 (operations) 在更新 proposal 后重新执行 plan-eng-review，并将 review 结果写入 `.openspec.yaml`。（2026-07-21 完成：2 P0 + 6 P1 + 5 P2 全部修复，phase=reviewed）
- [x] 0.4 (operations) 在实现前确认 commit 阈值：只允许审核通过的模块写入；重复 commit planned write 必须为 0；人工锁定字段计入 `manual_lock_skipped`；未审核行写库或公开页触网为 BLOCKER。（沿用既有阈值，用户 2026-07-21 确认方案）

## 1. 批次选择与批次 manifest

- [x] 1.1 (integration) 实现滚动批次选择服务：复用 `build_p0_completion_queue`，支持 `--regions`、`--profile-ids`、`--limit-per-region` 任意组合，默认每地区 100、单批合计 500；默认排除 `complete_profile_full` 与进行中批次的 profile（in-flight 清单固定在 `HorseProfileCompletionRun.parameters` schema），显式覆盖时记录原因。实现队列项 → adapter 候选形状的转换层：从 `HorseP0Source` 构造 `candidate_key`、`identity_keys`（namespace 前缀）、`source_namespace`、`source_url` 与预期血统三字段；`REQUIRE_SOURCE_URL=true` 下无 URL 来源的行为显式定义并留痕。
- [x] 1.2 (integration) 定义批次 manifest schema：批次 SHA-256、逐匹 profile id、四字段身份快照、P0 来源摘要、队列排序原因、地区分布、adapter 配置指纹、状态（pending/approved）、reviewer、approved_at。
- [x] 1.3 (application) 新增批次管理命令入口：select（只读预览，不写任何资料字段）、approve（写入批准字段、重算 SHA、追加 approvals ledger）、prepare（强制校验批准绑定后才允许触网）。

## 2. 抓取 checkpoint 与 resume

- [ ] 2.1 (integration) 新增 `server/stable/services/p0_horse_completion_batch.py`：`BatchRunState` dataclass（batch_id、run_dir、stage、candidate_states、artifacts、resume_history、errors），每候选完成和每阶段结束立即原子写 `state.json`。
- [ ] 2.2 (integration) 实现逐候选输入指纹（身份 + adapter 配置 + 来源 URL + 预期血统字段规范化哈希）与必需输出 SHA-256 校验；resume 决策矩阵覆盖 `skipped_unchanged / retry_failed / rerun_input_changed / executed` 及输出缺失/漂移原因码。
- [ ] 2.3 (integration) resume 入口：读取 state.json，追加 `resume_history`（时间、原因、决策摘要），任一候选重跑后作废下游 review/apply 阶段状态。
- [ ] 2.4 (integration) 中断现场处理：staging 目录保留并可在 resume 复用；批次放弃需显式命令并留痕，不静默清理证据。

## 3. 请求预算、限速与重试

- [x] 3.1 (integration) 抽象 `runtime/tools/race_event_request_budget.py` 的预算/限速为显式配置（artifact 路径、max requests、interval），保留环境变量默认值兼容赛事专项；host 级限速 artifact 从全局单文件扩展为按来源主机派生路径；两个专项共用同一实现。
- [x] 3.2 (integration) P0 source client 每次网络请求前过预算账本：按地区独立账本 `budget/<region>.json`（flock 跨进程安全），host 级限速 artifact 跨 run 共享；账本损坏、锁失败或超限 fail closed。
- [x] 3.3 (integration) 实现瞬时失败有限重试：引入结构化来源异常（携带 status_code 与 transient 标记，替代错误消息字符串匹配）；timeout/连接错误/429/5xx 指数退避（默认 3 次含首次、基数 30s、尊重 Retry-After 下限）；重试尝试不消耗 per-candidate 地区常量（该常量只计首次访问的不同 URL），但计入地区持久账本与 run 级上限；403/登录墙/解析失败/缓存身份错配不重试，直接 blocked payload。
- [x] 3.4 (application) settings 接线：新增 `HORSE_PROFILE_COMPLETION_MAX_REQUESTS`、`HORSE_PROFILE_COMPLETION_RETRY_MAX_ATTEMPTS`、`HORSE_PROFILE_COMPLETION_RETRY_BACKOFF_BASE_SECONDS`、`HORSE_PROFILE_COMPLETION_BUDGET_DIR`、`HORSE_PROFILE_COMPLETION_BATCH_STATE_DIR`、`HORSE_PROFILE_COMPLETION_REVIEW_OUTPUT_DIR`、`HORSE_PROFILE_COMPLETION_REGION_BATCH_LIMIT`（默认 100）与 `HORSE_PROFILE_COMPLETION_TOTAL_BATCH_LIMIT`（默认 500）；source client 的 per-region 候选数上限改为消费 `HORSE_PROFILE_COMPLETION_REGION_BATCH_LIMIT`（替换 adapters 硬编码 10，旧 `HORSE_PROFILE_COMPLETION_BATCH_LIMIT` 不再作为该上限来源）；`.env.example` 同步保守默认。

## 4. 任意批次抓取、复审文件与滚动提交链

- [ ] 4.1 (integration) 扩展 `run_reviewed_p0_horse_completion_batch` 或新增等效入口：接受批次 manifest 而非 50 行 CSV；候选 payload 流式写 staging JSONL（逐匹 fsync），末尾校验后原子发布；artifact 内容保持 JSONL、CSV、summary、失败/冲突清单、source evidence manifest；批次内按地区交错调度候选，使 host 级限速下整体吞吐最大化；移除 adapters 中硬编码 `batch_limit=10`。
- [ ] 4.2 (integration) 实现确定性转换器：批次 crawl artifact → 每地区 research v3 JSON（`p0-horse-research.v3`）。转换是纯函数，同输入字节必得同输出字节并输出 SHA；不做推断补值，无法确定的字段保持缺失并进入复审文件异常页。
- [ ] 4.3 (integration) 生成每批单独复审文件：新增 `openpyxl` 依赖（requirements + Docker 镜像），默认输出 `HORSE_PROFILE_COMPLETION_REVIEW_OUTPUT_DIR/<batch_id>.xlsx`，按地区分 sheet、逐匹摘要行（身份、硬字段完整度、血统、履历计数、异常标记、来源 URL）、异常/低置信抽样页（unknown 结果、生涯缺口、身份冲突、来源失败、字段冲突）和批次汇总页；复审文件从每地区 research v3 派生；JSONL artifact 仍是唯一 commit 凭证。
- [ ] 4.4 (integration) 实现批准回写：操作者批准命令按地区生成/更新 mapping decisions（逐马 bind/create、同名候选显式拒绝、四模块 module_reviews、数据库快照）、US authority manifest（仅批内含美国马时）和 release manifest；未通过复审的马整匹排除并记录到 blocker/替补池；每次批准追加 append-only `approvals_ledger.jsonl` 并镜像进 run parameters。
- [ ] 4.5 (integration) 泛化可信 release manifest 校验：滚动批次要求显式 `--approved-manifest-sha256` + 文件字节复核 + schema/reviewer/approved_at 校验 + 台账条目核对；`HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256` 全局 pin 保留为可选额外强制；首批硬编码白名单仅限首批复验路径。
- [ ] 4.6 (integration) 按地区生成独立 commit artifact（各自 expected_actions/summary/SHA/manifest 绑定/run），直接复用既有 `prepare_reviewed_p0_completion_artifact` → dry-run → commit 链与全部 fail-closed 断言；约束重 commit 必须同一 artifact 字节，内容修复必须另起新批次；执行顺序为逐地区“prepare → dry-run → commit”串行，每地区 prepare 前重取数据库快照，全局同一时间只允许一个批次处于 prepared-uncommitted 状态（互斥锁防并发批次）。

## 5. 幂等验收与审计留痕

- [ ] 5.1 (integration) 每个地区子批 commit 成功后自动以同一 artifact 重跑该地区范围 dry-run simulation，断言 planned creates/updates/audits 全为 0；复验摘要写入 `HorseProfileCompletionRun.summary.idempotent_verification` 与 `state.json`；复验失败只报警不自动修补。
- [ ] 5.2 (application) `HorseProfileCompletionRun.parameters` 记录批次 checkpoint 指针（run_dir、state SHA）与批次 manifest SHA，run 列表可按批次反查。

## 6. 验证与文档

- [ ] 6.1 (integration) 目标测试：选批排除/覆盖规则与默认 100/500 阈值、队列项→候选形状转换（含无 source URL 行为）、manifest 批准绑定、checkpoint 决策矩阵全分支、预算账本超限/损坏/并发、结构化异常分类、重试记账（不计 per-candidate 常量、计地区账本）、永久失败不重试、地区交错调度、确定性转换器同字节复现、复审文件生成与抽样页内容、批准回写与排除马替补池、台账核对、滚动批准 fail closed、每地区独立 commit artifact 与既有断言兼容、重 commit 同 SHA 约束、幂等复验、无界执行拒绝；回归保护：首批 50 行 CSV 入口与首批白名单幂等复验路径保持可用。
- [ ] 6.2 (operations) 本地验证：`DB_ENGINE=sqlite python manage.py check`、目标 Django 测试、完整 `stable` 回归、`makemigrations --check --dry-run`（本 change 无迁移，确认无漂移）、`openspec validate productize-p0-horse-batch-completion --strict`、`openspec validate --all`、`git diff --check`。
- [ ] 6.3 (integration) 离线 fixture 端到端：选批 → 批准 → prepare 模拟中断 → resume → artifact → dry-run → commit（sqlite）→ 幂等复验，全程零真实网络。
- [ ] 6.4 (operations) 独立 code review 并修复全部 actionable finding；更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`（滚动批次操作手册）；将 `complete-p0-horse-profile-data` tasks.md 的 `4.2` 标记为由本 change 完成。
- [ ] 6.5 (operations) 生产部署按 runbook 执行（备份、容器健康、check/healthz smoke、含 openpyxl 的镜像构建验证）；本 change 部署不触网、不写马匹资料；首个生产滚动批次以单地区小批验证 checkpoint/resume/预算/复审文件/批准回写/地区独立 commit 证据后，再按默认 100/500 阈值滚动；串行提交窗口约束写入 deploy_runbook。
