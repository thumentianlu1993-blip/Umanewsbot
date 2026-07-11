## Context

赛事页 MVP 已经提供 `RaceEvent`、`RaceEventRunner`、`RaceEventResult`、`RaceEventHistoryWinner`、`RaceEventDataCandidate` 和后台候选应用链路。2026 五地区重点赛事基础表已导入，`runtime/tools/` 中也已经存在多地区出走表、赛果和历届冠军候选生成脚本。当前问题不是没有 parser，而是缺少一个正式、可审计、可恢复的编排层。

现有 `import_race_event_detail_candidates` 已经是合适的最终写入入口：它能读取 JSONL，支持 dry-run，并可将候选保存后按模块 apply。风险在于 `race_events.py` 的 apply 逻辑会按模块整体替换正式行；如果候选覆盖不完整、series mapping 错误或来源误配，历史回填会污染公开赛事页。

本变更第一版只服务 `RaceEvent*` 产品层。`ExternalRace*` 外部缓存层继续属于真实外部数据库导入体系，不在本变更写入。

## Goals / Non-Goals

**Goals:**

- 提供一个正式 Django 管理命令，编排现有 `runtime/tools` 候选生成脚本。
- 支持日本、香港、英国、法国、美国五个目标地区的赛事信息批次计划、候选生成、覆盖审计、dry-run 和 apply 门禁。
- 第一版同时覆盖 `runners`、`results`、`history_winners`，并要求同一目标范围内三模块历史深度一致。
- 以少数核心赛事系列作为五地区第一验收批次，每个地区都必须跑通三模块主流程。
- 建立 `series_key` / mapping 审核机制，禁止名称模糊匹配直接写入正式赛事详情数据。
- 明确来源权威等级，支持官方源优先，同时允许受控使用高可访问第三方源。
- 产出可恢复、可审计的 run artifact，包含 plan、source cache、候选 JSONL、review CSV、summary、coverage audit、dry-run 结果、diff/review 和 apply checklist。

**Non-Goals:**

- 不写入 `ExternalRace*`、`ExternalHorse*` 等外部数据库缓存表。
- 不重写所有地区 parser；现有 `runtime/tools` 脚本先作为 adapter 被编排。
- 不新增公开页面、不改变赛事可见性规则、不改变新闻抓取、翻译、自动发布或 QQ 推送。
- 不把 long-running crawl 加入 Celery Beat，也不建设无人值守常驻调度。
- 第一阶段不包含 Listed，不追所有普通比赛。

## Decisions

### 1. 用 Django 管理命令做统一编排，复用现有脚本

新增 `orchestrate_race_event_crawl` 管理命令，读取 plan 文件并执行指定阶段：`plan`、`prepare`、`audit`、`dry-run`、`apply-check`。命令负责创建 run 目录、调用 adapter、归集 artifact、更新 state，并输出下一步命令。

备选方案是把所有 parser 立即重写进 `server/stable/services/`。这会在第一版引入过大重写风险，也会丢掉已经在生产复核中跑通的脚本行为。第一版先收口编排和门禁；稳定后再逐步迁移 parser。

### 2. 以 plan 文件作为运行事实入口

每次运行必须从 plan 文件开始。plan 至少包含：

- `run_id` 或可派生的运行名
- `target_layer=race_event`
- 地区、来源、来源权威等级
- 目标赛事系列清单或 series mapping artifact
- 年份范围或历史起点策略
- 模块清单，第一版必须包含 `runners`、`results`、`history_winners`
- 批次大小、限速、是否允许网络
- 输入 `events_csv` / 已有 source cache / 输出目录

不允许直接给脚本散传参数后跳过 plan，因为那样无法恢复和审计。

### 3. Adapter 是“命令级封装”，不是 parser 重写

第一版 adapter 以受控 subprocess 方式调用现有脚本，并校验产物文件是否存在、summary 是否可解析、JSONL 模块是否符合预期。adapter 必须记录实际命令、退出码、stdout/stderr 摘要和产物路径。

这样可以保持 parser 现状，同时把失败、缺产物、网络未授权、输出不一致等问题收束到编排层。

Adapter manifest 不得假设所有脚本都有统一参数。manifest 必须逐个声明脚本路径、工作目录、参数映射、必需输入、依赖产物、必需输出、产物模块归属、是否支持年份范围和输出归一化规则。对于仍使用固定年份文件名或特殊输入名的脚本，adapter 负责把产物复制或索引成 run 目录内的标准命名，不要求 parser 在第一版全部改写。

### 4. 目标 RaceEvent 行必须先预检，缺失时生成补建清单

现有 `import_race_event_detail_candidates` 在 dry-run 阶段也会按 `year + slug` 查询 `RaceEvent`。因此深历史回填不能只生成详情候选；它还必须先确认目标年份的 `RaceEvent` 行存在。

编排工具在 coverage audit 前执行目标赛事行预检：对 plan 中每个地区、赛事系列、年份和模块目标，检查对应 `RaceEvent` 是否存在且 `series_key`/slug/mapping 可审计。缺失时，工具输出 draft `RaceEvent` seed review artifact 和阻塞原因，不自动公开，也不直接跳过 dry-run。只有目标行已存在或经人工导入/确认后，该年份才可进入详情候选 dry-run 和 apply-check。

### 5. Coverage audit 是 apply 前的核心门禁

coverage audit 读取目标赛事范围、series mapping、候选 JSONL、review CSV、summary 和现有数据库状态，输出机器可读 JSON 与人工 review CSV。审计至少区分：

- `complete`
- `missing_runners`
- `missing_results`
- `missing_history_winners`
- `series_needs_review`
- `ambiguous_series`
- `duplicate_candidate`
- `source_conflict`
- `existing_data_diff`
- `manual_lock_conflict`

只有没有 blocker 的批次才能进入 dry-run；只有 dry-run 通过且 apply checklist 完成的批次才能成为 apply 候选。

### 6. Series mapping 显式化

历史回填不依赖名称模糊匹配直接写正式数据。抓取器可以生成候选 mapping，但编排工具必须将未确认 mapping 标记为 review。`ambiguous_series` 和 `needs_series_review` 不得进入正式 apply。

### 7. Apply 仍通过现有 importer，但增加 apply-check 阶段

正式写入仍使用 `import_race_event_detail_candidates --jsonl ... --apply`。编排工具新增 apply-check 阶段，生成或验证以下证据：

- coverage audit 无 blocker
- Django dry-run 通过
- 首批人工确认满足策略
- 外部导入锁为空
- 生产健康检查通过
- 数据库备份路径和 `gzip -t` 结果已记录
- diff/review 已确认

编排工具不做无人值守自动 apply；它输出显式 apply 命令和 checklist。

### 8. 手动分批运行，不做常驻调度

长周期历史抓取通过一次性容器或手动分批命令执行。state 文件记录每个 batch 的阶段、开始/结束时间、产物路径和错误摘要。失败后允许从同一 batch 的下一个未完成阶段 resume。

### 9. 用候选文件哈希绑定 coverage、dry-run 和 apply-check

coverage audit 必须记录候选 JSONL 的绝对路径、大小和 SHA-256。dry-run 产出结构化 JSON artifact，并记录同一候选文件的 SHA-256、通过状态、完成时间和 importer 输出。apply-check 只接受 `status=passed` 且候选哈希与 coverage、当前 apply 文件完全一致的 dry-run artifact；命令行不得用另一份候选文件覆盖已经审计的对象。

### 10. 来源权威等级由 adapter manifest 注入并在门禁中校验

adapter manifest 是 adapter 来源名称、地区、模块和 `source_authority` 的权威声明。adapter 成功后，编排层必须为其候选 JSONL 补齐这些 provenance 字段；候选已有字段与 manifest 冲突时直接失败。coverage audit 将缺失或非法来源等级视为 blocker，并按模块汇总来源组合。若同一赛事的不同模块使用不同来源或权威等级，apply-check 必须要求与实际组合完全匹配的人工确认。

### 11. Resume 同时校验输入和必需输出，全阶段写入 state

adapter 只有在输入指纹未变化、所有必需输出仍存在且输出哈希与上次成功记录一致时才可跳过。输出缺失或变化时必须重新执行，并记录对应 resume action。`dry-run` 和 `apply-check` 与 plan、prepare、audit 使用同一 `RunState`，成功和失败都必须写入阶段、产物、错误及 completed stages；resume 根据最后阶段和已保存输入恢复后续步骤。

### 12. 应到清单独立生成并作为不可静默缩减的覆盖率分母

run 创建时，在任何真实网络请求前根据 plan 的地区、系列、年份、slug 和正式 `RaceEvent` 生成 `expected_targets.json`。该快照绑定 plan SHA-256，恢复时不得随实际抓取结果重建或缩减。运营通过 `review/expected_targets_review.csv` 审核赛事中英文名、年份、地区、slug 与预检状态；快照为空、重复、目标行缺失或 plan 哈希变化时均 fail closed。

### 13. Prepare 统一汇总 adapter 候选

每个 adapter 仍保留独立原始与归一化 artifact；prepare 完成后额外按 adapter 结果顺序合并为 `candidates/combined_candidates.jsonl`，并把路径、大小与 SHA-256 写入 state。audit 和 dry-run 默认使用这份汇总文件，避免人工漏拼某个地区或模块。

### 14. 所有网络 adapter 共享运行级请求预算

plan 中的 `rate_limit.max_requests` 和 `request_interval_seconds` 被下发为同一 run 的持久化请求预算。每次外部请求前先原子更新 `request_budget.json`，失败请求也计数；多个 adapter 与 resume 共享累计值。预算 artifact 损坏时停止请求，避免通过重置状态绕过限流。`batch_size` 同时限制单个地区 plan 的目标赛事年份数量。

### 15. Apply 范围必须由候选实际内容推导

coverage audit 按候选记录和模块来源生成实际 `region + source + modules` 组合；apply-check 不信任人工单独填写的 `apply_scope`。准备写入的每个实际组合都必须被 apply scope 覆盖，并拥有对应人工确认；任一地区、来源或模块未确认时阻止整份候选 apply。第一验收总 plan 可以覆盖五地区，但正式 apply 应优先使用按单一地区/来源组合拆分的候选 artifact。

### 16. Apply-check 生成批准副本，Importer 在写库时复核哈希

apply-check 全绿后，将已验证候选复制到 run 目录 `approved/` 下的按 SHA-256 命名文件，并生成只引用该绝对路径的命令。`import_race_event_detail_candidates` 新增 `--expected-sha256`；执行 apply 时必须先读取候选原始字节、校验哈希，再从同一批字节解析和写库。批准后文件被修改时 fail closed，不创建候选、不改正式数据。

### 17. Adapter 配置必须严格且不可静默跳过

plan 中 adapter 只能是 registry 已存在的字符串 key，或包含非空 command、modules、outputs 及完整 provenance 的自定义 manifest。任何其他字典、空 command 或缺少必需输出的配置均在 plan 校验阶段失败。prepare 遇到无法构造 manifest 的配置必须报错，不允许 `continue` 后把阶段标为成功。

### 18. Coverage 行状态分别表达 blocker 与 warning

coverage 每个目标分别维护 blocker codes 和 warning codes。只有 blocker 会排除 `complete_count` 并将行状态设为 `blocked`；三模块完整且只有 warning 时状态为 `complete_with_warnings`，仍计入完整覆盖。`existing_data_diff` 保持 warning，`candidate_less_complete` 保持 blocker。

### 19. 应到审批、抓取输入和 Apply 证据形成闭环

`expected_targets.json` 创建后同步生成固定路径 `review/expected_targets_approval.json`。真实网络 prepare 只接受与当前应到清单 SHA-256 一致、`status=approved` 且带批准人/批准时间的记录。编排层从这份应到清单查询正式 `RaceEvent`，按地区生成 run 内独立 `input/events_<region>.csv` 并交给 adapter，避免复用工作区旧 CSV。

coverage 只接受显式 `mapping_status=approved`，模块存在但 `items=[]` 仍视为缺失有效内容，候选缺少 `source_url` 时禁止通过。apply-check 重新计算当前应到清单身份并与 coverage 对账，实际读取完整 gzip 备份验证可解压；范围确认同样必须包含 approved 状态、批准人和批准时间。任何一层证据缺失、失配或拼写错误都 fail closed。

### 20. 批量写入原子性与批准输入不可漂移

`expected_targets.json` 必须保存生成 adapter CSV 所需的完整赛事输入，包括名称、别名、日期、赛场、系列和 `source_refs`。prepare 只从该批准快照生成 CSV，同时重新计算当前 `RaceEvent` 的输入；任一字段变化时停止并要求重新生成快照和审批，不得静默使用数据库新值。

正式 importer 在候选保存和 apply 外层使用一个数据库事务。即使后续赛事或模块在类型转换、约束校验或正式写入时失败，先前已处理内容也必须全部回滚。混合来源策略 SHA 只从完整 approved 确认中收集；pending 或缺少批准元数据的记录不能提供策略批准。

按本轮用户决定，`--expected-sha256` 继续保持可选以保留现有单场人工修复入口；请求预算暂不增加跨进程锁。两项均不改变当前显式 apply 和手动分批运行口径。

## Risks / Trade-offs

- [Risk] 现有 `runtime/tools` 脚本参数和输出格式不完全一致 -> Mitigation: adapter 层为每个 source 定义 manifest，统一校验必需产物，缺失时失败。
- [Risk] 历史深度要求三模块一致，会让某些地区长期处于 incomplete -> Mitigation: coverage audit 明确 gap，不伪装完成；允许保存部分候选但禁止 incomplete 批次自动 apply。
- [Risk] 第三方来源覆盖好但权威性低 -> Mitigation: plan、候选和审计均记录 source authority；官方源和第三方源不得混同。
- [Risk] Apply 会按模块整体替换已有正式行 -> Mitigation: apply-check 必须比较现有数据和候选完整性，已有数据默认 diff/review，不允许无条件覆盖。
- [Risk] 长周期抓取与生产部署互相影响 -> Mitigation: 使用一次性容器/手动批次，state 可恢复；runbook 要求避开部署窗口并检查锁。
- [Risk] 五地区首批验收范围过大 -> Mitigation: 每地区只选少数核心赛事系列，先证明 adapter、mapping、coverage 和 dry-run 都能工作。

## Migration Plan

1. 新增编排服务和管理命令，不改变现有模型和公开页面。
2. 为第一批五地区小样本创建本地 plan fixture 和测试。
3. 本地验证 `plan -> prepare -> audit -> dry-run`，不执行生产 apply。
4. 更新 runbook，记录生产手动分批、备份、锁检查和 apply-check 步骤。
5. 验收通过后，按用户确认选择第一批真实地区系列运行。

回滚方式：该变更第一版主要新增命令、服务和文档；如果未执行 apply，删除 run artifact 即可。若已通过现有 importer apply，则按数据库备份或候选 apply 前 diff/review artifact 恢复对应 `RaceEvent*` 模块数据。

## Open Questions

- 五地区第一验收小批的具体赛事系列清单。
- 各地区默认来源矩阵和 source authority 枚举细节。
- 日本“分级制度建立时”的具体历史起点年份和 JRA/NAR 分层起点。
- 香港、英国、法国、美国的长期历史起点需在第一验收批次后分别锁定。
