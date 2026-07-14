## Context

历史赛事已有 approved inventory、标准 batch selection、日期发现、详情来源审批、详情候选导入和独立 historical runner。batch005 的五地区抓取证明底层适配器与写入命令可用，但跨地区编排仍由多份 `tmp/build_batch005_*.py` 完成：脚本写死生产路径、年份和 target ID，无法由 runner 白名单稳定复用，也没有统一表达“完整候选或显式 gap”的分母。

batch006 已批准 1061 场，地区/年份跨度为法国 2023-2024、香港 2016-2017、日本 2022-2024、英国 2024-2025、美国 2024-2025。单个 runner crawl 的请求预算硬上限为 250，因此同一正式批次必须拆成多个不可变 shard，并在暂停、恢复或部分来源失败后仍可证明不重不漏。

## Goals / Non-Goals

**Goals:**

- 用 tracked、镜像内、显式白名单工具替代 batch005 通用临时脚本。
- 从 approved selection 和 stage descriptor 生成 runner 可直接校验的固定 plan；每个 shard 绑定目标、请求预算、image/revision、tool SHA 和输入输出身份。
- 对日期 provider rows、详情 candidates 和 gap fragments 进行确定性合并，任何重复、冲突、越界或 SHA 漂移 fail closed。
- 允许少量歧义进入结构化 gap 后继续其他目标；每阶段必须满足 `complete + gap = approved scope`。
- 提供可重复的数据库阶段验收命令，逐 target 核对日期、来源、模块完整性、draft 可见性和 applied provenance。

**Non-Goals:**

- 不新增新的赛事模型、迁移、公开页面或自动公开行为。
- 不在本 change 中为每个来源重写抓取解析器；继续复用 JRA、HKJC、Sporting Life、ZEturf、Equibase 等现有工具。
- 不把人工争议自动裁决为 `not_held/cancelled`，也不把 gap 伪装成完整候选。
- 不允许任意 shell、artifact 自带代码或未跟踪脚本进入生产 runner。

## Decisions

### 1. 使用 stage descriptor 生成 plan，而不是手工维护 runner-plan.json

新增纯结构化 plan builder。输入 descriptor 绑定 selection、approval、manifest、image 和一个 stage 的 shards；每个 shard 显式列出 target ID、地区、请求预算及 typed recipes。builder 不接受任意 argv，而是按受支持工具的 recipe 生成命令，并解析该工具实际读取的 events CSV、selection subset、provider JSONL 或 candidate JSONL，证明输入 target 集合与 shard scope 精确相等。随后校验 approval 覆盖、SHA、地区一致性、每 shard 不超过 250 个目标和 250 次请求，再调用现有 `validate_runner_plan()` 验证最终 plan。

builder 为每个 shard 生成 canonical `scope.json` 与输入身份清单；recipe 必须把 scope 对应的结构化输入作为 declared input，输出路径必须位于 shard 独占目录，跨 shard 输出冲突直接拒绝。未知工具或未实现 target-binding policy 的已白名单工具也不得用于正式 plan。

每个 shard 拥有独立的宿主 artifact 目录，并在运行时单独挂载为 `/app/historical-runtime`，因此请求账本、source-cache manifest、runner state、lock 文件和输出都按 shard 隔离。selection/approval/manifest 与 recipe 输入以普通文件复制到 shard 目录并重新核对原 SHA，禁止 symlink；父 stage 目录只保存 shard identities 和全量覆盖 summary。不得把多个 shard 指向同一 artifact 根，否则共享账本会把整批错误压成 250 次请求。

batch006 初始 recipe policy 至少覆盖：`discover_historical_race_band_sources.py`、`cache_historical_race_date_sources.py`、JRA/HKJC/Sporting Life/ZEturf/Equibase 详情 preparer、`prepare_cached_historical_race_details.py`、`package_historical_race_detail_candidates.py` 与本 change merger。每种 policy 明确读取哪个输入字段得到 target identity；未列出的工具后续必须先补测试和 policy。

替代方案是允许操作者直接写 plan，但它无法证明所有 approved target 在同一 stage 恰好出现一次，也容易遗漏 image/tool identity，因此不采用。

### 2. 将碎片合并器设计为两个模式，共享同一分母契约

新增 `merge_historical_race_batch_fragments.py`：

- `date` 模式读取重复 `provider JSONL` 与 issues/gap 文件，按 `(series_key, edition_year)` 绑定 selection target，输出确定排序的 provider rows、gap ledger 和 summary。
- `detail` 模式读取重复 detail candidate JSONL 与 gap 文件，按 `target_id` 绑定 selection，核对 target/inventory SHA、来源、runners/results 两模块和完整性，输出正式候选、gap ledger 和 summary。

两个模式都要求 scope 中每个 target 恰好归入 `complete` 或 `gap`，且两集合不得相交。gap 必须来自显式 fragment，并包含 target/selection SHA、原因代码、来源或失败证据身份和记录时间；merger 不得把完全缺失的 target 自动包装为 gap。不同来源对同一 target 给出不一致有效值时转为 conflict gap，不按输入顺序静默覆盖。相同规范化记录可去重但必须在 summary 留下来源计数。

替代方案是为五地区各建一套 merger；这会重复分母、SHA 和冲突逻辑，并延续 batch005 的维护问题，因此不采用。

### 3. 人工覆盖是独立 evidence fragment，不进入代码常量

人工补证使用 JSONL，必须包含 target ID、预期 target SHA、字段/模块、旧值、新值、来源 URL、来源级别、理由、审核者和时间。覆盖只在预期旧值仍匹配时生效；同一字段多份覆盖冲突则进入 gap。工具代码不得出现生产 target ID 常量。

### 4. gap 不阻断 crawl，但阻断对应 target 的 apply

stage summary 明确输出 `scope_count / complete_count / gap_count / conflict_count / accounted_count`，并要求 `accounted_count == scope_count`。后续 shard 可以继续执行；apply artifact 只包含 complete targets，gap 保持 pending 并累计到用户最终统一审核表。任何目标既不在 complete 也不在 gap 时整个 stage 失败。

### 5. 计划资源限制在 runner 取锁前与 phase env 对齐

正式 plan 顶层包含 `resource_limits`，至少绑定 `request_budget`、`max_source_cache_bytes`、`min_free_disk_bytes` 和 `request_interval_seconds`。`validate_runner_plan()` 校验边界，runner 在创建/恢复 run 和取得双锁前把这些值与 settings 派生的实际 phase env 比较；不相等即拒绝。legacy smoke plan 可继续使用 schema 1.0，但正式 plan builder 只生成带资源身份的新 schema，且生产 batch descriptor 不得降级为 legacy。

### 6. 数据库验收使用正式管理命令，不扩大 control role

新增只读管理命令 `verify_historical_race_batch_stage`，复用 batch005 验收逻辑，支持 `date/detail-source/final`。它在写后短时 one-off 中使用现有业务角色读取数据库，并在 PostgreSQL `transaction.atomic()` 内执行 `SET TRANSACTION READ ONLY`；SQLite 测试通过只读查询捕获与禁止 ORM 写方法验证相同意图。不授予 `historical_runner_control` 业务表权限，也不把 verifier 塞进 apply 白名单。长期 crawl 仍由独立 runner，短时 apply/verify 继续遵循单一生产窗口、备份与无网络门禁。

### 7. 新 merger 进入显式白名单，plan builder 和 verifier 不进入 crawl 白名单

merger 需要在 runner crawl artifact 内组合来源输出，因此加入 `_APPROVED_HISTORICAL_PYTHON_TOOLS` 并绑定镜像 SHA。plan builder 在启动前运行，verifier 在写后运行，不需要成为 runner Python tool。plan builder 和 merger 都要求最终输出目录不存在，在同级临时目录内完成全部 canonical JSON/JSONL、文件 fsync、目录 fsync 和 manifest 校验，再以一次目录 rename 发布；失败只删除本次临时目录并保留输入，禁止覆盖既有 artifact。

### 8. 以 batch 最大规模锁定性能和查询上限

纯 artifact builder/merger 在 1250 targets、10 shards、每 target 20 runners/results 的 fixture 上必须在 30 秒内完成且峰值额外 RSS 不超过 256 MiB，不得把所有 source body 常驻内存。数据库 verifier 对 1250 targets 的查询数不超过 20，使用 annotations/prefetch 或聚合查询，禁止逐 target 查询。

## Risks / Trade-offs

- [来源工具仍可能产出地区特有缺口] -> 统一记入 gap ledger，继续其他 shard；后续补源只重跑 gap scope，不重抓已完成目标。
- [1061 场一次合并占用内存或输出过大] -> descriptor 和 merger 支持 shard scope，默认逐地区/年份分片；最终全批 summary 只合并小型身份与计数。
- [人工覆盖误用于已变化 target] -> 同时绑定 target SHA 和 expected old value，任一漂移即拒绝。
- [生成 plan 与真实挂载路径不同] -> 生产 plan 只允许 `/app/historical-runtime` artifact root 和 `/app/runtime/tools` tool root，并在镜像内运行 builder/validator。
- [descriptor scope 与工具实际输入不一致导致重复抓取] -> 只支持 typed recipe，并为每种工具实现 target-binding policy；没有 policy 的工具不能进入正式 plan。
- [plan 声明预算与容器 env 不一致] -> runner 在创建/恢复 run 和取锁前比较 `resource_limits` 与实际 settings，任何差异 fail closed。
- [多个 shard 错误共享同一请求账本] -> 每个 shard 使用独立宿主 artifact 根和挂载，父 stage 只保存不可变身份与覆盖汇总。
- [多文件输出中途失败留下半套 artifact] -> 同级临时目录完整构建和 fsync 后一次目录 rename，目标目录必须预先不存在。
- [gap 过多导致表面 accounted 率很高] -> 报告同时保留 `accounted_rate` 与 `data_complete_rate`，不得合并成单一完成率。

## Migration Plan

1. 先完成 specs、完整测试用例和 Full 工程审查。
2. 测试优先实现 plan builder、fragment merger、stage verifier 和 runner 白名单更新；反复 review 至无问题。
3. 从最新 main 构建可复现 AMD64 镜像，镜像内运行专项与完整 stable；生产保持历史公开和常驻开关关闭。
4. 按既有安全窗口备份并只替换 web/worker/beat，重新执行 runner 拒绝/暂停恢复 smoke。
5. 用 batch006 approved selection 生成 stage descriptor 和 shards，先 dry-run/只读验证，再开始 crawl。
6. 回滚代码时切回旧 image；新 artifact 为追加证据，不删除。若尚未 apply，无数据库业务回滚；若已 apply，使用对应写前备份恢复。

## Open Questions

- 无产品口径待定。零星来源歧义按用户决定统一进入 gap，待 1998-2026 正式总账数据收集完成后集中审核。
