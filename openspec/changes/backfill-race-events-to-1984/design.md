## Context

生产当前有 `995` 个 `RaceEvent`，全部属于 2026 年：日本 186、中国香港 20、英国 203、法国 174、美国 412。现有详情编排器已经具备 plan、应到快照审批、adapter 请求预算、coverage、dry-run、apply-check、候选哈希、备份和原子写入门禁，但它把“已存在的年度 `RaceEvent`”作为应到分母，无法先发现 1984–2025 的完整年度赛事。

本变更的历史范围是五地区 1984 年以来全部 graded/pattern 系列，以及这些系列从 `max(1984, 创办年)` 起的完整届次。范围不仅包括 2026 年现役系列，也包括历史上曾进入分级体系、后来停办或降级退出的系列。赛事身份、历史等级、改名、迁场、取消和未举办必须来自逐年来源证据，不能复制 2026 行。

该目标会产生约四万级年度目标、更多出马和赛果行，并涉及旧页面、PDF、档案目录、来源限流、永久缺档和同名赛事。设计必须允许完整目标先分批写入，同时保持总账不丢失未解决目标。

## Goals / Non-Goals

**Goals:**

- 建立稳定赛事系列目录、年度应到总账和年度 `RaceEvent` 三层身份。
- 从 1984 年起逐年发现五地区 graded/pattern 目录和历史独有系列。
- 用 artifact + 数据库账本共同证明应到分母、审批身份、批次范围和完成状态。
- 支持 `not_due / not_held / source_unavailable / permanently_unavailable / identity_review_required` 等真实结论。
- 对 held/due 赛事分批生成基础赛事、出马表、赛果和系列历史冠军覆盖，并复用现有写入门禁。
- 支持第一批约 45 场跨地区、跨年代验收和后续年代带推进。
- 让达标历史赛事通过现有年度详情页、赛事日历搜索和年份筛选公开访问。

**Non-Goals:**

- 不抓普通赛、让赛、未胜利赛等非 graded/pattern 全赛程。
- 不新增公开赛事系列页。
- 不因历史参赛记录批量创建 `HorseProfile`。
- 不自动音译并写入正式术语库。
- 不把 `ExternalRace*` 作为产品层历史总账。
- 不在无来源证据时推断创办年、缺届、等级、冠军或参赛名单。

## Decisions

### 1. 新增稳定赛事系列实体，不再把字符串 series_key 当完整身份

新增 `RaceSeries`，保存稳定 key、地区、规范名称、中文名、创办/终止年份、状态、审核状态、来源证据和人工锁。新增：

- `RaceSeriesName`：历史名称、语言、有效年份、冠名/别名类型和证据。
- `RaceSeriesRelation`：前身、后继、合并、拆分、替代关系和人工批准。
- `RaceEvent.race_series` nullable FK：逐步绑定年度赛事。

兼容期保留 `RaceEvent.series_key`，但新历史流程以 `race_series_id` 为身份；保存时同步稳定 key。`RaceEvent` 对非空 `race_series` 增加 `(race_series, year)` 条件唯一约束，防止同一系列同一年产生两个产品对象。系列关系服务拒绝 self relation、重复 relation 和会形成直接或间接循环的前身/后继关系。现有 2026 行先生成 mapping candidate，不自动合并带日期 key 或同年重复 key。

新历史年度 slug 从已批准稳定系列 key 生成并带地区前缀，`(year, slug)` 必须唯一；创建后 slug 视为公开 URL 身份，不因后续冠名、中文译名或马场修正自动改变。现有年度 slug 保持不动，通过 FK 与稳定系列关联。

替代方案是继续扩展字符串 `series_key`。该方案无法表达改名有效期、前身后继、审核状态和同名冲突，因此拒绝。

### 2. 新增年度应到总账，RaceEvent 只代表真实年度赛事

新增 `HistoricalRaceEventTarget`，唯一键为 `(race_series, year)`。为避免把客观举办事实和处理过程混成一个状态，拆为：

- `expectation_status`：`held / cancelled / not_due / not_held`。
- `resolution_status`：`pending / ready / source_unavailable / identity_review_required / permanently_unavailable / imported`。
- 当年名称、等级、马场、距离、日期、举办状态候选和逐字段来源。
- `module_statuses`：基础、出马、赛果、冠军覆盖状态。
- 关联 `RaceEvent`、来源证据、最后核查时间、永久不可得批准元数据和批次身份。

状态转换由一个共享服务校验，模型 `clean()` 和写入命令复用；例如 `not_held` 不得关联 `RaceEvent`，`not_due` 不得标记 imported，`permanently_unavailable` 必须具备批准证据。`not_held` 目标不创建 `RaceEvent`。已排期后取消则创建 `RaceEvent(status=cancelled)`。`not_due` 由比赛日期和地区宽限期计算，不进入历史缺失分母。

替代方案是为每个 series/year 预建草稿 `RaceEvent`。该方案会制造未举办和未创办年份的假比赛，并让前台、统计和去重复杂化，因此拒绝。

### 3. 逐年赛历发现是总账唯一来源，2026 目录只作为种子

发现分两步执行：

1. 每个地区的逐年 graded/pattern catalog adapter 发现当年进入分级目录的系列，包括历史独有系列。
2. 对已进入范围的系列执行 lineage/timeline adapter，从权威沿革、结果索引或年鉴扩展到创办年起的前分级和后降级连续届次，并显式识别 not-held/取消年份。

标准输出包括 `catalog_candidate.jsonl` 和 `series_timeline_candidate.jsonl`：

- 来源年份和地区。
- 当年赛事原名、等级、马场、日期和来源标识。
- 建议 series mapping、置信度、匹配理由和冲突。
- source URL、缓存文件身份和解析器版本。

总账构建先汇总所有年度目录确定“曾进入范围的系列”，再用已批准 timeline 扩展完整连续届次。2026 目录只用于产生初始系列候选；历史独有系列必须从旧年度目录发现；前分级或后降级届次不得因为不在分级目录中被遗漏。名称模糊匹配只能进入 `identity_review_required`。

### 4. artifact 是审批/apply 的唯一凭证，数据库用于查询和状态

每次 inventory run 输出：

- `series_candidates.jsonl`
- `series_conflicts.csv`
- `annual_targets.jsonl`
- `annual_targets_review.csv`
- `gap_ledger.csv`
- `summary.json`
- source cache 清单和所有文件 SHA-256

批准文件绑定整套 artifact manifest。审核通过后，commit 只读取同一 manifest 中的字节，不重新触网。后台读取数据库投影，提供地区、年代、系列、状态、冲突和完成率筛选；后台不能直接绕过已批准 artifact 执行批量 apply。

### 5. 字段级来源权威和可回滚更新

来源顺序为：

1. 当年主办方/监管机构官方结果。
2. 官方历史档案或年鉴。
3. 高可信专业数据库。
4. 参考来源。

低级来源只补空。同级或更高级来源冲突时，target 转为 `identity_review_required` 或字段冲突 blocker。每个应用字段保存来源、快照和批次；后续改进必须生成 before/after diff。`manual_lock_flags` 继续保护人工字段。

### 6. 三模块深度一致，但历史冠军不做 O(n²) 复制

held/due 年度目标必须有：

- runners：独立 racecard，或从包含所有参赛者的可信完整赛果派生。
- results：可信完整赛果，含未完赛/取消参赛状态时一并保存。
- history coverage：该年度冠军由正式赛果第一名提供；缺完整赛果但有可信冠军证据时由 `RaceEventHistoryWinner` 补位。

前台历届冠军按同一 `RaceSeries` 的年度正式赛果和补位冠军动态汇总、按年份去重。不得把完整冠军表复制到每个年度 `RaceEvent`。

派生 runner 在 `source_refs` 标记 `derived_from_results`，只复制来源字段。

### 7. 总账切批，而不是让 plan 自行发明范围

扩展编排器，从已批准 `HistoricalRaceEventTarget` 快照选择 `ready/due` 目标生成 batch plan。plan 只能缩小到已批准 scope，不能添加总账外目标。

第一批选择规则：

- 每地区 3 个系列。
- 每地区约 9 个真实 held/cancelled 年度目标，地区样本整体覆盖 1980 年代、2000 年前后和近年。
- 长寿现役系列优先取三个年代锚点；历史停办系列无法覆盖近年时取其可举办范围内代表年份，并由同地区其他系列补足近年锚点。
- 覆盖长寿、改名/迁场、历史独有或停办系列。
- 目标约 45 个年度赛事。

后续按 `2016–2025 → 2006–2015 → 1996–2005 → 1984–1995` 推进。标准全量批次每地区最多 50 个 held/cancelled 年度目标；变更批次上限必须写入 plan 和审批。地区同步以同一年代带已 accounted/imported 的 due 目标数计算，任何地区不得比最慢地区领先超过 100 个标准目标，避免通过拆小或放大批次绕过护栏。

### 8. 允许完整 scope 先写，缺口不消失

coverage 对每个 target 输出模块结论。完整 target 可形成独立 apply scope；缺口目标保留在总账，不进入 approved candidate，也不阻止其他完整 scope。

`permanently_unavailable` 必须有官方/监管档案和独立可信来源两类证据、查询范围、时间和人工批准。最终报告：

- `accounted_rate`
- `data_complete_rate`
- 各 expectation/resolution 状态和模块缺口数量
- 按地区/年代/系列拆分

目标闭环要求 `accounted_rate=100%`，但不得把永久缺档计入数据完整。

### 9. 历史发布门槛与公开入口

历史 inventory apply 首先创建或更新 draft `RaceEvent`。finished/held 赛事的明确公开门槛为：稳定系列和年度身份已批准、名称/地区/年份/举办状态/来源齐全、无 blocker、完整正式 results 存在、runners 已由独立 racecard 或完整赛果派生；缺赔率、闸位等非来源字段不阻止。`permanently_unavailable` 资料不足目标保持 draft。同一批准批次只有包含显式 publication scope 时才能执行 publication transition；不依赖“抓到数据就自动公开”的旧禁令。取消赛事有已批准排期和取消证据时可不要求 runners/results 并公开。

赛事日历增加 `year` 和 `q`：

- `year` 精确筛选年度。
- `q` 匹配年度中英文名、年度别名和稳定系列历史名称。
- 保留全部/重点和地区筛选。

不新增系列页。详情页历史冠军动态汇总。未命中马名/骑师术语时保留原文并输出术语缺口，不自动创建 HorseProfile。

published 且质量达标的年度页进入分片 sitemap；draft、冲突、空壳和 `not_held` 不进入。

### 10. 性能与原子性

- 总账按 `(region, year, expectation_status, resolution_status)`、`(race_series, year)` 建索引。
- artifact 流式读写，避免一次加载四万目标及全部赛果。
- 后台汇总使用数据库聚合与分页。
- 每个批准 apply scope 独立事务；scope 内任一模块失败整批回滚。
- 大批 runner/result 使用已有 bulk_create 路径并在写后重新计数。
- sitemap 按固定 URL 数量分片，不一次渲染全部页面。

容量预估按约 40,000–50,000 年度赛事、约 50 万 runners 和约 50 万 results 做上线前测算。数据库只保存结构化事实、行级有限 provenance 和 source cache 身份，不保存整页 HTML/PDF 字节或重复整页 payload；原件留在受控 source cache。第一批 dry-run 必须输出预计新增行数、索引体积和数据库增长，磁盘预检不通过时不得扩大批次。

`RaceEventResult` 新增 nullable `official_finish_position`，现有 `finish_position` 继续作为稳定存储顺序并保持 event 内唯一；导入时把同着官方名次写入新字段。`RaceEventHistoryWinner` 唯一约束改为 `(event, winner_year, horse_name)`，允许可信补位证据表达并列冠军。动态冠军查询使用 `official_finish_position=1`（为空时回退 `finish_position=1`），从而支持并列冠军。

生产增加保守总开关 `HISTORICAL_RACE_BACKFILL_ENABLED=false` 和 `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。只读 plan、离线 cache 解析和 dry-run 在功能开关关闭时仍可执行；commit/publication 需要功能开关，网络 prepare 还必须同时满足网络总开关、plan `allow_network=true` 和应到审批。plan 必须声明共享请求预算、`max_source_cache_bytes` 和 `min_free_disk_bytes`，每次请求/写缓存前检查持久化账本与剩余磁盘，超限后 fail closed。已批准 source cache 由 manifest 固定，不得在对应批次可回滚期内清理。

inventory commit、series mapping、永久不可得批准、publication transition、网络 run 开始/失败/恢复和写后核验必须写 `OperationLog` 或 `TaskExecutionLog`，日志保存 artifact SHA、目标范围、操作者、状态和摘要，不保存整页原件或敏感环境变量。

## Risks / Trade-offs

- [历史年度目录无法在线获取] → 支持官方 PDF/纸本目录扫描的离线 source cache，缺失进入证据账本，不复制当前目录。
- [旧页面结构跨年代变化] → adapter manifest 声明解析器版本和支持年代；第一批跨年代样本先验收。
- [同名赛事误合并] → 稳定系列映射必须显式批准，模糊匹配只做候选。
- [四万年度目标导致后台或命令内存增长] → 流式 artifact、分页、批量查询和按年代/地区切批。
- [允许部分完整 scope 先写导致整体状态复杂] → 总账是唯一分母，apply 后重新生成全局 summary，缺口不会从分母消失。
- [自动发布历史赛事产生空壳 SEO 页面] → 发布门槛、分片 sitemap 过滤和 draft 默认状态。
- [冠军动态汇总查询变慢] → 对 series/year 建索引，详情页只查询有限年份并允许缓存。
- [来源许可或版权限制] → 数据库只保存结构化事实和必要 provenance；原始文档保存在受控 source cache，不公开转载整页内容。

## Migration Plan

1. 新增系列、系列名称/关系、年度目标模型、`RaceEvent.race_series` nullable FK、`RaceEventResult.official_finish_position`，并调整历史冠军唯一约束；数据迁移把现有 `source_refs.official_finish_position` 合法整数回填到新字段，其余回退 `finish_position`，先部署兼容空表、nullable 字段和索引。
2. 对现有 2026 `RaceEvent` 生成只读 series mapping artifact，人工处理日期型 key 和美国重复 key。
3. 应用已批准 mapping，绑定现有年度赛事；保留原 `series_key` 兼容。
4. 部署 inventory 命令、后台只读汇总、总账 artifact 和测试；网络默认关闭。
5. 为五地区逐一加入年度目录 adapter，先离线 cache/dry-run。
6. 生成 1984–当前总账并人工批准系列冲突、not-held 和历史独有系列。
7. 执行约 45 场第一批跨年代详情验收；完整 scope 备份、apply、写后核验。
8. 开启年代带批次，逐批更新完成率和缺口账本。
9. 数据达到公开门槛后启用日历年份/搜索、动态冠军和 sitemap。

回滚时先停止新 run；代码回滚后保留新增表和 nullable FK不影响旧页面。单批数据异常使用 apply artifact 保存的 before 值回滚；大范围异常使用批次前数据库备份。不得通过删除总账掩盖已发现缺口。

## Open Questions

- 各地区历史赛历权威来源和在线可得起点需要在 adapter spike 中逐年记录；这是来源证据调查，不再改变已锁定的产品范围。
- 地区结果确认宽限期初始值将在真实来源探测后配置，默认保守且不影响 1984–2025 历史目标。
