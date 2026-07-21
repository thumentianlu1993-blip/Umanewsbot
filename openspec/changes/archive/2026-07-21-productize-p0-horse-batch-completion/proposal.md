## Why

`complete-p0-horse-profile-data` 已完成能力底座和首批验收：五地区各 10 匹严格完整资料已写入生产（`complete_profile_full 50/50`、`1439` 条履历、`published=0`），全量 P0 范围也已入队（`46318` 匹 profile、`56745` 条来源）。但 `46266` 匹仍为 `empty/not_started`，而现有网络补全批次只能在首批的受控形态下运行：

- 批次输入硬编码为“恰好 50 行、五地区各 rank 1-10”的审核 CSV，不支持任意地区、任意 profile 集合或动态批次大小；队列选择能力（`build_p0_completion_queue`）只读存在，未接入补全执行。
- 抓取侧没有任何显式 checkpoint/resume：批次循环全内存、末尾原子发布，中断后只能靠 per-candidate 缓存文件提供隐式“软续跑”，无进度清单、无失败候选枚举、无 resume 审计。
- 请求预算是 per-candidate、per-run 的内存计数，跨 run 失效；限速是进程内 sleep，跨 run 失效；429/超时/5xx 直接失败无重试；`HORSE_PROFILE_COMPLETION_BATCH_LIMIT` 已定义但没有任何代码消费。
- 生产 `2 vCPU / 4 GiB / no swap` 主机已有无地区全量单事务 OOM 事故教训：任何全量化、无界化执行都必须被结构性地禁止，而不是靠操作者自觉。

没有可恢复、可限流、可审计的小批次流水线，4.6 万匹详细资料补全无法长期推进。本 change 把五地区补全 adapter 产品化为长期可运行的滚动批次能力，即完成 `complete-p0-horse-profile-data` 的 tasks `4.2` 长期版本。

## What Changes

- 批次选择接入 P0 补全队列：支持 `--regions`、`--profile-ids`、`--limit-per-region` 任意组合选批，默认每地区 100 匹、单批五地区合计不超过 500 匹；输出带逐匹身份快照、队列排序原因和地区分布的批次 manifest。批次 manifest 必须经人工批准（approved + SHA-256 绑定）后才允许触网抓取；不再把“50 行审核 CSV”作为唯一合法批次输入。
- 每批复审产物为单独文件：每 500 匹待审核批次输出一个独立复审文件（默认 Excel 工作簿，按地区分 sheet，附异常/低置信抽样页和逐匹摘要行），写入可配置的本地复审目录；机器可读 JSONL artifact 继续作为 commit 凭证，复审文件服务于人工抽样、重点字段核对和 AI 辅助复审。
- 抓取侧显式 checkpoint/resume：每个批次 run 目录维护原子写入的 `state.json`，逐候选记录输入指纹、输出 SHA-256、状态和失败原因；resume 按决策矩阵 `skipped_unchanged / retry_failed / rerun_input_changed / executed` 精确续跑，并写入 `resume_history` 审计；既有 per-candidate 缓存继续作为零网络软续跑层。
- 请求预算与限速产品化：复用赛事请求预算的 flock 持久账本模式，每地区独立预算 artifact，host 级限速证据跨 run 共享；新增 `HORSE_PROFILE_COMPLETION_MAX_REQUESTS`（run 级上限）、重试和预算目录配置；接线 `HORSE_PROFILE_COMPLETION_BATCH_LIMIT`；预算证据损坏或超限一律 fail closed。
- 瞬时失败有限重试：timeout、429、5xx 按可配上限指数退避重试，每次尝试计入请求预算；403、登录墙、解析失败等永久失败不重试，直接写 blocked payload，不中断同批其他候选。
- 滚动批次提交链产品化：新增确定性转换器（批次 crawl artifact → 每地区 research v3，同字节复现、不推断补值）和批准回写（按地区生成 mapping decisions、四模块 module_reviews、US authority manifest、release manifest），未通过复审的马整匹排除进 blocker/替补池；既有 prepare/dry-run/commit 链与其全部 fail-closed 断言零改动复用。
- 滚动批次人工审核门禁：沿用“抓取 artifact → 人工审核 → 批准 manifest → 显式 SHA 绑定 → apply-check → commit”链路；批准机制从首批一次性硬编码可信 SHA 白名单泛化为逐批显式批准 SHA + 文件字节复核 + append-only 批准台账核对，仍然 fail closed；AI 生成内容不得标记为人工已审核。
- commit 按地区独立 artifact 执行：一个批次（≤500 匹）拆为每地区一份独立 commit artifact（≤100 匹），逐地区“prepare → dry-run → commit”串行提交；任一地区的坏行只回滚该地区，不阻塞同批其他地区；重 commit 必须使用同一 artifact 字节，内容修复必须另起新批次；重复 commit planned write 为 0；全局同一时间只允许一个批次处于 prepared-uncommitted 状态。
- 批次幂等验收自动化：每个地区 commit 后自动重跑该地区 dry-run 断言 planned write 为 `0`，并把复验摘要写入 `HorseProfileCompletionRun`；完全重跑已提交批次只能走 already-applied 对账分支。
- 内存与故障边界：候选 payload 流式写入 staging JSONL，不在内存累积整批；单批失败只影响该批；结构性禁止无地区、无上限的全量抓取执行。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `horse-profile-data-completion`: 从“首批 50 匹冻结批次一次性执行”扩展为“面向整个 P0 队列长期运行的可恢复滚动小批次流水线”：任意批次选择、显式 checkpoint/resume、持久化按地区请求预算、瞬时失败重试、滚动批次人工批准绑定和批次幂等自动验收。

## Impact

- 代码：新增 `server/stable/services/p0_horse_completion_batch.py`（批次 run 状态机、选批、manifest、确定性转换器、批准回写、复审文件生成）；扩展 `server/stable/services/p0_horse_completion_adapters.py`（任意批次输入、checkpoint 钩子、移除硬编码 batch_limit）、`server/stable/services/p0_horse_completion_source_clients.py`（预算账本、host 限速、结构化异常、重试）；抽象或参数化 `runtime/tools/race_event_request_budget.py` 的预算/限速能力供两个专项共用；扩展管理命令；`server/app/settings.py` 新增配置；`requirements.txt` 新增 `openpyxl`；新增专项测试。
- 数据：无新模型、无迁移；批次 checkpoint 指针和复验摘要记录在 `HorseProfileCompletionRun.parameters/summary`。
- 运维：新增批次 run 目录 `runtime/horse_profile_completion/batches/<batch_id>/`（state、artifact、预算账本）和可配置复审输出目录（默认 `runtime/horse_profile_completion/review/`，每批一个复审文件）；生产默认保持 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`，每批触网仍需该批 manifest 人工批准；默认每批 ≤500 匹且 payload 流式落盘，保证 4 GiB 主机内存安全。
- 文档：更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`（批次操作手册）；本 change 归档时将 `complete-p0-horse-profile-data` tasks.md 的 `4.2` 标记完成，`6.7` 公开验收继续独立跟踪。
- 明确不做：身份冲突治理（另起 change）、`6.7` 公开验收（本 change 部署后立即执行，但属运营动作）、未发布马自动首次公开、美国来源策略变化、Equibase 防护绕过。
