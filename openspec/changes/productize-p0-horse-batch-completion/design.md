## Context

P0 马专项当前状态（以 `docs/p0_horse_information_completion_handoff.md` 和生产核验为准）：

- 首批五地区 50 匹严格完整资料已提交生产，链路为：人工审核 CSV（恰好 50 行、五地区各 rank 1-10）→ `run_reviewed_p0_horse_completion_batch` 抓取并生成 artifact → 人工审核工作簿 → 独立批准 manifest（硬编码可信 SHA 白名单）→ `apply_reviewed_p0_horse_completion` prepare/dry-run/commit。
- 全量 P0 范围已入队：`46318` 匹 profile、`56745` 条来源，其中 `46266` 匹 `empty/not_started`。
- 代码核实结论：`load_reviewed_p0_horse_candidates` 硬性校验恰好 50 行；批次循环全内存且无进度落盘；请求预算为 per-candidate per-run 内存计数（地区常量 日3/港1/英1/法2/美3）；client 无重试；`HORSE_PROFILE_COMPLETION_BATCH_LIMIT` 无消费方；`build_p0_completion_queue` 已支持 regions/profile_ids/limit_per_region 但只读未接入。
- 可复用资产：赛事编排 `RunState`（state.json + 输入指纹 + resume 决策矩阵 + sha256 输出校验 + resume_history）；`runtime/tools/race_event_request_budget.py`（flock 持久预算账本 + host 级限速 artifact）；已审核 artifact 的 dry-run/commit 分离、expected-actions 断言、整批事务、already-applied 幂等对账均已产品化。
- 吞吐约束：人工审核不是瓶颈——操作者通过抽样、重点字段核对和 AI 辅助复审可达到每日 1-2 万匹；瓶颈在来源礼貌限速。首批实测每匹约 29 条履历、约 41 行字段证据、1-3 次来源请求；限速为 8s/请求/host，五地区主要来源是五个不同 host，批次内地区交错处理可在不降低单站礼貌度的前提下获得约 5 倍整体吞吐。
- 生产约束：`2 vCPU / 4 GiB / no swap`，已有无地区全量单事务 OOM 事故；交接文档明确禁止再次直接运行无地区全量 P0 单事务。

本 change 只解决“批处理产品化”（`complete-p0-horse-profile-data` tasks `4.2` 的长期版本）。身份冲突治理、`6.7` 公开验收、地区滚动补齐的执行节奏不在本 change 内。

## Goals / Non-Goals

**Goals:**

- 任意批次选择：从 P0 补全队列按地区、profile id、每地区上限（默认 100）选批，单批五地区合计不超过 500，生成可人工批准的批次 manifest，替代固定 50 行 CSV 作为网络批次唯一输入。
- 可恢复抓取：批次 run 具备显式 checkpoint，进程中断、单候选失败或预算耗尽后可 `--resume` 精确续跑，已成功候选零重复网络请求。
- 持久化预算与限速：每地区独立请求预算账本跨 run、跨进程生效；host 级限速证据跨 run 共享；预算证据损坏或超限 fail closed。
- 有限重试：瞬时失败（timeout/429/5xx）按可配上限退避重试并计入预算；永久失败写 blocked payload 不中断批次。
- 滚动批次人工门禁：逐批人工批准 manifest + 显式 SHA 绑定 + 字节复核后才能 apply-check/commit；不放宽模块级人工审核。
- 幂等验收自动化：commit 后自动复验 planned write 为 0 并留痕。
- 内存安全：单批有界、payload 流式落盘，4 GiB 主机可长期运行。

**Non-Goals:**

- 不做身份冲突治理（`HorseIdentityConflict` 分组、去重、管理员队列）：另起 change。
- 不做 `6.7` 公开验收本身：这是运营动作，本 change 部署后立即单独执行。
- 不改变“完整资料”硬字段口径、四模块人工审核要求或身份四字段锁规则。
- 不启用未发布马自动首次公开，不改变已发布马增量更新策略。
- 不改变美国逐场来源策略；不绕过 Equibase 访问限制；不把 HRN 提升为官方逐场来源。
- 不做 Celery Beat 定时批次或无人值守 commit；批次执行仍为人工触发的管理命令。
- 不做逐匹部分提交（partial commit）：commit 以地区子批（≤100 匹）为最小事务单元。

## Decisions

### 1. 批次输入从固定 50 行 CSV 改为“队列选批 + 批次 manifest + 人工批准”

新增批次选择服务，从 `build_p0_completion_queue` 按 `--regions`、`--profile-ids`、`--limit-per-region` 选批，默认每地区 100 匹、单批五地区合计不超过 500 匹，输出批次 manifest：逐匹 profile id、四字段身份快照、P0 来源摘要、队列排序原因、地区分布、adapter 配置指纹和批次 SHA-256。manifest 初始为 `pending`；操作者审核批次构成后写入批准信息（reviewer、approved_at、批准说明）并计算 approved SHA，网络 prepare 强制校验“显式传入 SHA + 文件字节 SHA + schema + 批准字段”一致，否则 fail closed。500 匹一批对应约 1000 次来源请求，按 8s/host 限速和地区交错约 30-60 分钟可完成抓取；全量 46266 匹约 93 批，按每日数批的抓取节奏 1-2 周可完成，审核侧按操作者每日 1-2 万匹的复审能力不构成瓶颈。

备选方案是保留 50 行 CSV 形式只放宽行数。它无法承载身份快照漂移检测和队列排序原因审计，也不能利用既有队列优先级。备选方案二是维持首批 50 匹批量，全量需要 900+ 批，项目周期不可接受。

### 2. checkpoint 采用文件态 BatchRunState，不新增数据库字段

新增 `server/stable/services/p0_horse_completion_batch.py`，实现借鉴赛事编排 `RunState` 的 `BatchRunState` dataclass：`batch_id / run_dir / stage / candidate_states{} / artifacts{} / resume_history[] / errors[]`，每个候选完成、每个阶段结束立即原子写 `<run_dir>/state.json`（tmp + replace）。checkpoint 指针（run_dir、state SHA）写入 `HorseProfileCompletionRun.parameters`，复用现有 run 记录而不加迁移。

备选方案是沿用 `HistoricalBatchRun` 的 DB checkpoint 模式。批次补全是短周期 artifact 流程，状态与 artifact 同目录更利于整体打包审核；DB checkpoint 更适合长跑容器任务，这里引入迁移收益不足。

### 3. resume 复用“输入指纹 + 输出校验”决策矩阵

逐候选记录输入指纹（候选身份 + 适配器配置 + 来源 URL + 预期血统字段的规范化哈希）和必需输出的 SHA-256。resume 时：指纹一致 + 上次成功 + 输出校验通过 → `skipped_unchanged`；上次失败或中断 → `retry_failed`；指纹变化 → `rerun_input_changed`；输出缺失/漂移 → 重跑该候选并记录原因码。任何候选重跑后，下游 review/apply 阶段状态作废必须重跑。每次 resume 追加 `resume_history`（时间、原因、决策摘要）。

### 4. 请求预算复用 flock 持久账本，参数化共享模块

把 `runtime/tools/race_event_request_budget.py` 的预算/限速能力抽象为显式配置（artifact 路径、max requests、interval），保留环境变量默认以兼容赛事专项；P0 source client 在每次网络请求前调用同一 `before_network_request`。预算账本按地区独立：`runtime/horse_profile_completion/budget/<region>.json`；host 级限速 artifact 按来源主机共享（如 `host-interval/www.jbis.or.jp.json`），跨 run 生效。账本 JSON 损坏、锁失败或计数超限时 fail closed。run 级上限 `HORSE_PROFILE_COMPLETION_MAX_REQUESTS` 默认由批次导出（逐候选地区预算之和），操作者可收紧不能放宽到无界；既有 per-candidate 地区常量预算保留为第二层。

备选方案是维持 per-run 内存预算。它无法防止 resume 后重复消耗配额，也无法让两个顺序执行的批次共享 host 限速证据。

### 5. 只对瞬时失败做有限重试，且每次尝试计入预算

`_get` 层对 timeout、连接错误、HTTP 429 和 5xx 做指数退避重试：`HORSE_PROFILE_COMPLETION_RETRY_MAX_ATTEMPTS`（默认 3，含首次）、`HORSE_PROFILE_COMPLETION_RETRY_BACKOFF_BASE_SECONDS`（默认 30）；每次尝试都先过预算账本。HTTP 403、登录墙、重定向超限、解析失败、缓存身份错配立即失败。最终失败转为该候选 blocked payload 并继续同批其他候选，与现有行为一致。

### 6. 滚动批次提交输入产品化：确定性转换器 + 批准回写，既有提交链零改动

代码核验证实 commit 凭证不是抓取 JSONL，而是 `prepare_reviewed_p0_completion_artifact` 从三类独立人工产物合成的：research v3（`p0-horse-research.v3`）、US authority manifest（美国马强制）、approved profile mapping decisions（逐马 `bind_existing/create_new` + `rejected_profile_ids` + 四模块 `module_reviews` + 数据库快照绑定）。首批这三类产物由一次性脚本手工产出。滚动批次必须把这层产品化：

1. **确定性转换器**：批次 crawl artifact → 每地区 research v3 JSON。转换是纯函数：同输入字节必得同输出字节，输出 SHA 可复核；不做任何推断补值，转换器无法确定的字段保持缺失并进入复审文件异常页。
2. **批准回写**：操作者审完复审文件后执行批准命令，按地区生成/更新：mapping decisions（逐马 bind/create 决策、同名候选显式拒绝、四模块 module_reviews 批准、数据库快照）、US authority manifest（仅批内含美国马时）、release manifest。未通过复审的马整匹排除（四个模块一起排除），进入 blocker/替补池记录，不允许部分模块带批通过。
3. **既有链复用**：上述产物按地区切片后，直接喂给现有 `prepare_reviewed_p0_completion_artifact` → dry-run → commit，`_validate_module_reviews`、authority chain、mapping snapshot 校验语义全部原样保留，不新增第二条 commit 路径。

### 7. 提交单元为每地区独立 commit artifact，既有断言体系不改

地区子批不以“整批 artifact + region 参数”实现，而是**每地区一份独立 commit artifact**：各自 expected_actions、summary、SHA-256、release manifest 绑定和 `HorseProfileCompletionRun`。这样 `_assert_expected_actions`、“partially applied batch” fail-closed、`p0_reviewed_batches` 幂等锚点（按地区 artifact SHA 记录）、`run_was_committed` 幂等复验归类、锁内 snapshot rescan 五处整批假设全部保持原语义；地区 B 的首次 commit 是独立 artifact，不会被误判为幂等复验。约束：重 commit 必须使用同一 artifact 字节；内容修复（换马、改字段）必须另起新批次新 artifact，禁止原地改字节。附带收益：500 匹整批 artifact 约 60MB 的 apply 侧解析峰值降回每地区约 12MB，4 GiB 主机安全。

备选方案是单 artifact + region 参数化 `_simulate`/`_assert_expected_actions`/completion run：至少改动五处既有 fail-closed 断言，回归风险远高于上游切片。

### 8. 批间串行提交窗口与快照保鲜

mapping decision 的数据库快照在 prepare 和 commit（锁内 rescan）双重校验，任一批次 commit 创建新 profile 后，其他已 prepare 未 commit 批次的快照即漂移 fail closed。因此规定：**全局同一时间只允许一个批次处于 prepared-uncommitted 状态**；批次内按“地区 A prepare → dry-run → commit → 地区 B prepare → …”串行执行，每地区 prepare 前重新取数据库快照并重算绑定；命令层以既有外部导入互斥锁防止并发批次。该约束写入 deploy_runbook。

### 9. 每批复审产物为单独文件（openpyxl），面向抽样与 AI 辅助复审

每 500 匹待审核批次在可配置复审目录（`HORSE_PROFILE_COMPLETION_REVIEW_OUTPUT_DIR`，默认 `runtime/horse_profile_completion/review/<batch_id>.xlsx`）输出一个独立复审文件：按地区分 sheet，每 sheet 逐匹一行摘要（身份、硬字段完整度、血统状态、履历计数、异常标记、低置信字段、来源 URL），另附异常/低置信抽样页（unknown 结果、生涯缺口、身份冲突、来源失败、字段冲突集中列出）和批次汇总页。复审文件由每地区 research v3 派生，在批准回写前生成。技术选型：新增 `openpyxl` 进 `requirements.txt`（纯 Python、无本地依赖，适合 4 GiB 主机与现有 Docker 构建）；首批的 Node workbook builder 依赖 Codex 工作区专供包且消费 research JSON，不复用。机器可读 JSONL artifact 仍是唯一 commit 凭证；复审文件是人工抽样、重点字段核对和 AI 辅助复审的阅读界面。备选方案是复用首批 50 匹工作簿格式原样放大到 500 匹：约 2 万行字段证据全部平铺，抽样效率低，且生产镜像无 Node 运行时。

### 10. 重试记账：不消耗 per-candidate 常量，只计地区账本与 run 级上限

既有 `REVIEWED_CANDIDATE_REQUEST_BUDGETS`（港/英=1、法=2、日/美=3）是“每候选不同页面数”的上限，若重试也计入则港/英任何瞬时失败都无法重试。规定：per-candidate 常量只计**首次访问的不同 URL**；同一 URL 的重试尝试不消耗该常量，但计入地区持久账本和 run 级上限，并受 `HORSE_PROFILE_COMPLETION_RETRY_MAX_ATTEMPTS` 硬约束。client 的 `batch_limit`（不同候选数上限）从硬编码 10 改为消费 settings 的地区批次上限（默认 100）。错误分类引入结构化异常（携带 status_code 与 transient 标记），不再靠解析错误消息字符串判断可重试性。

### 11. 滚动批准通道：append-only 批准台账 + settings 全局 pin 保留为可选

首批的仓库硬编码 SHA 白名单是第二通道保障，滚动模式下无法延续（每批改代码不现实）。补偿控制：批准命令把每次批准追加写入批次目录的 append-only `approvals_ledger.jsonl`（reviewer、approved_at、逐地区 manifest SHA、批次 SHA、排除马清单），并镜像进 `HorseProfileCompletionRun.parameters`；commit 校验 release manifest SHA 必须在台账中存在对应条目，首批硬编码白名单仅保留给首批 artifact 幂等复验。settings 级 `HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256` 全局 pin 保留为可选：非空时作为额外强制（适用于需要冻结单批的特殊窗口），默认为空，滚动模式不依赖它，避免每批改 `.env` 重启容器。

### 12. commit 后自动幂等复验并留痕

每个地区子批 commit 成功后自动以同一 artifact 重跑该地区范围的 dry-run simulation，断言 planned creates/updates/audits 全为 0（全部命中 already-applied），复验摘要（时间、计数、SHA）写入 `HorseProfileCompletionRun.summary.idempotent_verification` 和 `state.json`；复验失败只报警不自动修补，交由人工排查。

### 13. 内存安全靠结构约束而不是操作者自觉

候选 payload 逐匹流式写入 staging JSONL（写完 fsync），批次循环不累积整批 payload；artifact 发布仍是 staging → 校验 → 原子 replace；commit 输入按地区切片（≤100 匹、约 12MB），apply 侧单次解析峰值有界。管理命令在没有 `--regions` 或 `--profile-ids` 且没有显式 `--limit-per-region` 时拒绝执行抓取（fail closed），从命令层禁止无界全量执行；默认上限每地区 100、单批 500，显式调大时要求操作者确认并记录原因。

### 14. 队列排序原因进入批次 manifest

批次 manifest 逐匹保留队列排序原因（近期新闻、术语优先级、重点赛事证据、外部匹配信号、人工标记），人工批准批次构成时可解释“为什么是这批马”，也让后续批次去重和替补有据可查。

### 15. 已记录取舍

- rerun 会清除 `commit:{region}` artifact 键（下游失效的一部分），因此“已 commit 地区 + 再次重跑 prepare”的场景下同 SHA 重 commit 保护不复存在；此时既有 commit 链自身的 already-applied 幂等对账仍然兜底， planned write 为 0。
- manifest 的 `batch_sha256` 为内容规范化 SHA（排除 `batch_id`/`batch_sha256` 字段），不是文件字节 SHA；操作者从 select/approve 命令输出取得该值，不需要自行 `shasum`。
- 预算账本按 run（批次）维度隔离，host 限速证据跨 run 共享；`HORSE_PROFILE_COMPLETION_MAX_REQUESTS>0` 时作为 per-run 覆盖而非历史累计上限。

## Risks / Trade-offs

- [预算账本与 per-candidate 常量双口径混淆] -> 账本记录每次请求的来源 URL 与候选键，summary 同时输出两种口径；账本只控 run/region 级，候选级仍走既有常量。
- [checkpoint 文件与真实缓存漂移] -> resume 时逐候选校验必需输出 SHA-256；缓存自身有 schema 校验；漂移一律重跑该候选。
- [重试放大来源压力] -> 重试次数小（默认 3）、退避基数大（默认 30s）、每次计入预算并受 host 限速约束；429 响应的 Retry-After 作为退避下限。
- [滚动批准 manifest 被当成形式] -> manifest 必须含 reviewer、approved_at、逐模块批准覆盖；缺字段或覆盖不全 fail closed；批准动作强制写 append-only 台账并在 commit 时核对；AI 生成/未审核内容标 approved 属于流程违规，代码侧无法替人背书，依赖操作纪律和审计留痕。
- [500 批复审文件过大难以使用] -> 按地区分 sheet + 逐匹摘要行 + 异常/低置信抽样页，全量字段证据仍留在 JSONL artifact 可回查；复审文件只服务抽样与重点核对，不要求逐行通读。
- [批间数据库快照漂移] -> 全局串行 prepare→commit 窗口 + 每地区 prepare 前重取快照重算绑定 + 互斥锁防并发批次；fail closed 时错误信息指明需重新 prepare。
- [修复失败地区时改动 artifact 字节] -> 设计禁止：重 commit 必须同一 artifact SHA，内容修复一律另起新批次；命令层校验 artifact SHA 与 run 记录一致性。
- [选批误含已在批的马] -> 批次选择默认排除 `complete_profile_full` 和已有进行中批次（run 状态非终态，in-flight profile 清单固定在 run parameters schema）的 profile，可显式覆盖并记录原因。

## Migration Plan

1. 实现批次选择、BatchRunState、预算账本接入和重试，全部默认关闭网络。
2. 目标测试 + 完整 `stable` 回归 + `manage.py check` + 迁移漂移检查（本 change 无迁移，确认无漂移即可）+ OpenSpec 严格/全量校验 + `git diff --check`。
3. 离线 fixture 端到端：选批 → 批准 → prepare（模拟中断）→ resume → artifact → dry-run → commit（sqlite）→ 幂等复验。
4. 部署走既有 runbook：`.env` 与数据库备份、容器健康、check/healthz smoke。本 change 部署本身不触网、不写任何马匹资料。
5. 生产首批滚动批次：先以单地区 ≤10 匹小批验证（建议日本 JBIS 链路），确认 checkpoint/resume/预算/复验证据后再按“日→港→英→法→美”节奏滚动。
6. 回滚：代码回退到上一镜像；新 run 目录和预算账本为新增文件，无数据库写入可回滚；进行中的批次放弃 run 目录即可。

## Resolved Questions

- 范围：仅 4.2 批处理产品化；身份冲突治理与 6.7 公开验收分别独立推进（用户 2026-07-21 确认）。
- 审核门禁：抓取侧自动化连续执行（选批、prepare、resume、artifact），每批 commit 前仍需人工批准 manifest + SHA；批准后 apply-check/commit/幂等复验连续执行不逐批再问（用户 2026-07-21 确认）。
- 批次阈值与复审形态：默认每地区 100 匹、单批 ≤500 匹；每批输出一个单独复审文件到指定本地目录，操作者以抽样 + 重点字段 + AI 辅助复审，复审能力约每日 1-2 万匹，不构成瓶颈（用户 2026-07-21 确认）。
- 6.7 时机：本 change 上线后立即从已完成 50 匹中每地区人工发布 1-2 匹做公开验收（用户 2026-07-21 确认）。
- 工作分支：独立 worktree，基于 `codex/p0-horse-production-release`（用户 2026-07-21 确认）。
