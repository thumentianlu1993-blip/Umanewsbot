# `automate-race-event-lifecycle` Claude 实现交接

## 0. 交接状态与强制门禁

本文是本任务的独立实现入口。Claude 可以仅凭本文和仓库当前文件完成实现与自测，不需要重新
询问产品范围或重新设计状态机；但本文**不是实现授权或发布授权**。

当前状态：

- 独立 worktree：`/Users/mentianlu/Code/umanews/.worktrees/automate-race-event-lifecycle`
- 分支：`codex/automate-race-event-lifecycle`
- 基线：已验证的 `origin/main`，交接时 OID 为
  `9b58bfd437f58dede0de5d11d64537e2e68e214e`
- 已完成：只读探索、规格、设计、测试矩阵、发布方案、商业来源研究、独立方案审核。
- 方案 reviewer：`lifecycle_plan_reviewer`；同一会话最终结论 `APPROVED`，无未关闭 finding。
- 未完成：任何自动化测试、应用代码、迁移、配置、实现代码 review、commit、push、PR、部署
  或生产写入。

Claude 开始时必须先检查用户在**当前已审方案之后**是否明确回复了“确认实现”“开始实现”
“继续实现”或同义授权。没有该授权时，只能阅读和解释本文，禁止：

- 编写或修改测试；
- 修改应用代码、迁移、配置或 Celery Beat；
- 启动测试/实现 subagent；
- commit、push、PR、部署、迁移、服务重启或生产写入。

取得实现授权后，直接从本文第 8 节阶段 A 开始，不需要再次做开放式方案调查。若必须采购套餐、
取得凭据或批准新的 provider proof，应 fail closed 并继续完成不依赖它们的阶段 A。

代码 review 通过后仍必须停下。只有用户针对**最新成功 review 的精确内容**另行明确授权发布，
才允许 commit、push、PR、部署或生产写入。

## 1. 必读顺序与权威文件

进入任何动作前依次完整阅读：

1. 仓库根目录 `AGENTS.md`
2. `docs/codex_workflow.md`
3. `docs/session_bootstrap.md`
4. `docs/project_overview.md`
5. `docs/current_state.md`
6. `docs/decisions.md`
7. `docs/deploy_runbook.md`
8. 本目录的 `spec.md`
9. 本目录的 `design.md`
10. 本目录的 `test_cases.md`
11. 本目录的 `tasks.md`
12. 本目录的 `rollout.md`

来源决策还需阅读：

- `commercial_api_research.md`
- `tra_free_p0_coverage_20260725.md`
- `regional_source_research_20260725.md`

冲突优先级：

1. 用户在当前任务中的最新明确指令；
2. `AGENTS.md` 与 `docs/codex_workflow.md`；
3. `spec.md`；
4. `design.md`；
5. `test_cases.md` 对测试行为与验收的要求；
6. `tasks.md` 对执行范围和顺序的要求；
7. `rollout.md` 对灰度、发布和回滚的要求；
8. 本文。

禁止使用任何 OpenSpec skill、OpenSpec CLI 或新建 OpenSpec change。历史 `openspec/` 仅可读。

## 2. 当前真实数据流与根因

### 2.1 赛事与公开状态

核心模型在 `server/stable/models.py`：

- `RaceEvent`：公开赛事日期、`race_datetime`、`timezone_name`、`status`、等级、重点与可见性。
- `RaceEventStatus`：当前公开状态为
  `scheduled/running/finished/postponed/cancelled`。
- `RaceEventParticipant`：结构化参赛者。
- `RaceEventRevision`、`RaceEventRevisionItem`、`RaceEventRevisionEvidence`、
  `RaceEventRevisionPublication`：racecard/result 的版本、证据与发布链。
- `RaceEventLiveTracking`：现有 live polling 状态。
- `RaceEventDataCandidate`：候选更新。

重点赛事的准确业务判定为：

```text
RaceEvent.is_key_race
等价于 priority ∈ {P0, P1} 或 is_featured = true
```

自动生命周期还必须同时满足：

- 赛事公开可见；
- 非 cancelled；
- 位于经 SHA 固定、显式 apply 的 enrollment manifest；
- 已有有效 lifecycle control。

迁移不得把所有历史重点赛事自动启用；新重点赛事也不得因属性匹配而自动纳管。

### 2.2 现有赛果链

真实调用路径：

```text
Celery Beat 每分钟
  -> stable.tasks.select_due_race_live_events_task
  -> stable.services.race_events.claim_due_race_event_live_tracking
     (select_for_update(skip_locked))
  -> stable.tasks.poll_race_live_event_task(queue="race_live")
  -> provider / revision / publication
```

关键入口：

- `server/stable/tasks.py`
- `server/stable/services/race_events.py`
- `server/stable/test_realtime_race_results.py`
- `server/stable/test_realtime_race_results_postgres.py`
- `server/stable/test_race_live_multiregion_selector.py`
- `server/stable/test_race_live_racecard_sync.py`

`race_live_worker` 只负责 `race_live` queue 的 provider polling。新 lifecycle scanner **不得**
调用或重复 dispatch `poll_race_live_event_task`。赛果调度所有者仍是现有 selector。

### 2.3 赛事长期停留“赛前”的根因

当前没有覆盖全部重点赛事、按赛事 IANA 时区执行的生命周期扫描器。`RaceEvent.status` 通常在
成功发布赛果 revision 时才变为 `finished`。因此以下任一情况都会使旧赛事继续
`scheduled`：

- provider 失败或尚未批准；
- 没有完整赛果；
- 没有 live tracking；
- 缺少精确出走时间；
- live scheduler/region/event 开关关闭；
- 赛事没有被现有 live selector 纳管。

状态推进错误地依赖了赛果成功。阶段 A 的首要修复是把“比赛时间已过”和“赛果权威阶段”拆开。

### 2.4 新闻链

主要入口：

- `server/stable/services/automation.py`
  - `score_article_for_automation`
  - `is_ready_for_auto_publish`
  - `publish_article_automatically`
- `server/stable/services/race_events.py`
  - `associate_articles_for_event`
- `server/stable/tasks.py`
- `server/stable/views.py`

现有关联主要针对已公开新闻，赛事名命中不足以安全回写赛事。阶段 C 才增加结构化影响评估；
阶段 A 不得改变新闻门禁。

### 2.5 页面与缓存

日历、详情和相关公开 surface 读取 `RaceEvent.status` 及 live projection。缓存失效入口：

- `server/stable/services/race_event_public_cache.py`
- `server/stable/signals.py`

生命周期服务若使用 queryset update/bulk update，不能依赖 model signal；必须在成功事务的
`transaction.on_commit(invalidate_public_race_cache)` 显式失效。首页“近期赛事”不在本任务范围。

## 3. 已锁定的生命周期设计

### 3.1 两条正交状态轴

公开赛事生命周期复用 `RaceEvent.status`：

```text
scheduled -> running -> finished
     |           |
     +-> postponed
     +-> cancelled
```

赛果权威继续复用 revision/live 概念：

```text
awaiting -> provisional -> official -> corrected
```

约束：

- `finished` 只表示比赛时间生命周期已结束，不表示正式赛果已确认。
- `result_confirmed_at` 只能由 `official` 或 `corrected` 设置。
- `provisional` 永远不能显示或写成 official。
- `cancelled` 是终态，不能由时间规则改为 finished。
- `postponed` 必须使旧 `schedule_generation` 失效；只有高权威新时间可受控返回 scheduled。
- 来源失败不阻止时间状态推进，也不得因此伪造赛果。

### 3.2 时间规则

有 `race_datetime`：

- `now < race_datetime`：保持 `scheduled`。
- `now >= race_datetime`：幂等推进 `scheduled -> running`。
- T+0：现有 live tracking 只可推进至 awaiting，并把下次尝试设为 T+3；零网络请求。
- T+3 起：只有现有、已批准的 race-live selector 可调用 provider。
- T+30：幂等推进 `RaceEvent.status -> finished`，无论来源是否成功。

无 `race_datetime`：

- 使用赛事**当地日期**；
- 当地次日 `00:00` 才推进 `finished` 并成为赛果补采候选；
- 不得直接启动未批准 provider。

固定时区：

| 地区 | 时区规则 |
|---|---|
| 日本 | 仅 `Asia/Tokyo` |
| 香港 | 仅 `Asia/Hong_Kong` |
| 英国 | 仅 `Europe/London` |
| 法国 | 仅 `Europe/Paris` |
| 美国 | manifest 人工核定的具体 `America/*` |

不得依赖服务器本地时区。无效、缺失或与 manifest 不一致的时区 fail closed、记录错误、零推进。
DST 必须使用 Python `zoneinfo.ZoneInfo`，覆盖 London、Paris、New York、Los Angeles。

爱尔兰明确不在本 change 范围：当前模型、P0 清单和页面路由未完整支持；不得映射成英国或
`other`。以后单独 change。

### 3.3 新模型

在 `server/stable/models.py` 新增，名称可按 Django 约定微调但语义不得减少：

1. `RaceEventLifecycleControl`（event 一对一）
   - `mode`: `off/shadow/enforce`
   - `next_refresh_at`
   - `schedule_generation`
   - 最近尝试、结果、来源、错误
   - `refresh_profile`
   - 连续失败数
   - claim token/generation/expiry
   - pause 状态与原因
   - enrollment manifest SHA
2. `RaceEventLifecycleTransition`（append-only）
   - proposal 与 applied 必须使用不同 dedupe key
   - from/to status、规则、触发任务、generation、observed_at、evidence
   - 重放不得制造重复有效记录
3. `RaceEventFieldAuthority`
   - event、participant stable key、field 的当前权威/值/人工锁
4. `RaceEventFieldChange`（append-only）
   - field、old/new、source、URL/external ID、confidence、authority、task、article ID
5. `RaceNewsImpactAssessment`（阶段 C）
   - article + content hash + classifier/contract version
   - 影响类型、匹配赛事、提取变化、证据、置信度、审核状态

阶段 A 按已审核 `tasks.md` 在同一 schema 变更中实现前四项：lifecycle control/transition 和
field authority/change；field authority/change 在阶段 A 仅建立持久化、权威约束和审计基础，
不得在没有阶段 B RED 的情况下接入外部来源或自动写字段。`RaceNewsImpactAssessment` 留到
阶段 C。

迁移基线是 `server/stable/migrations/0057_merge_20260725_0448.py`；先检查最新 main 是否漂移，
迁移编号不得凭本文硬编码。

### 3.4 原子性、幂等与 claim

建议新增：

- `server/stable/services/race_event_lifecycle.py`：纯决策、原子 apply、manifest reconcile。
- `server/stable/management/commands/reconcile_race_event_lifecycle_controls.py`：
  一次性 strict dry-run 与显式 manifest apply。
- `server/stable/test_race_event_lifecycle.py`
- `server/stable/test_race_event_lifecycle_postgres.py`

scanner：

- Beat 每 5 分钟；
- 每批最多 100 个 due control；
- `select_for_update(skip_locked)`；
- claim TTL 4 分钟；
- selector 和单场任务设有限时，设计值 120/150 秒；
- 不高频扫描 RaceEvent 全表；
- lifecycle 单场任务只做数据库时间决策，不联网；
- 默认 mode `off`；
- 持久 scanner 不提供 dry-run mode，dry-run 只通过一次性零写管理命令。

事务必须把 status、transition、control 状态放在同一原子块。事务晚期失败全部回滚；缓存仅
`on_commit` 失效。旧 generation 的任务必须拒绝执行。

shadow：

- 写一条 dedupe 后的 proposal；
- 不改变公开 status；
- 重复 shadow 不产生同义重复 proposal。

enforce：

- 第一次原子写 applied transition + status + control；
- shadow proposal 与 applied 各自可审计；
- 重放为 noop。

## 4. 来源与字段权威合同

权威等级固定为：

```text
官方结构化来源 500
> 已验证专业 API 400
> 官方新闻/公告 300
> 可信媒体新闻 200
> 日期/时间规则推断 100
```

低权威不能静默覆盖高权威；同权威异值进入冲突；人工 lock 阻止所有自动覆盖；provider omission
不得解释为退赛。

商业 provider 的批准范围必须精确到：

```text
(provider, region, field_name, result_phase, provider_contract_version)
```

付费不等于官方权威。合同、schema 或版本漂移一律 fail closed。

地区路由：

| 地区 | 设计结论 |
|---|---|
| 英国 | The Racing API Pro 候选；BHA/官方证据复核 |
| 香港 | The Racing API Pro 候选；HKJC 官方证据复核 |
| 法国 | The Racing API Pro 候选，但必须逐场 proof |
| 美国 | The Racing API North America add-on 候选；无合规同类 GitHub 库 |
| 日本 JRA | JRA-VAN，经 `miyamamoto/jrvltsql` Windows collector |
| 日本 NAR/JPN1 | 独立 provider/身份/marker；不得用 JRA 合同代替 |
| 爱尔兰 | 本 change 不接入 |

The Racing API 永远先作为 supplemental/provisional；未经字段级官方性 proof 不得生成
`official_result`。公开套餐研究时 Pro 为 £99.99/月、最远未来 racecard 约 T-7；它不能满足
T-21 的全部发现窗口。当前 2026 剩余 P0 审计基数为 113 场：美国 50、法国 24、英国 19、
日本 19、香港 1；TRA 路由候选覆盖 94/113，但这不是逐场实际覆盖证明。

美国禁止 Equibase scraping、隐身、验证码绕过；仅可人工复核或取得授权 Data Sales API。

### 4.1 日本 collector 边界

生产自动链使用 `jrvltsql`，不是 `jvlink-mcp-server`。MCP 只可用于诊断。

Windows collector：

- JRA-VAN/COM/32-bit；
- 不持有生产数据库凭据，不直连生产业务库；
- 输出 immutable Ed25519-signed snapshot；
- Umanews 通过 SFTP-only、read-only 账户主动拉取；
- 临时文件 + fsync，签名 manifest，atomic rename，最后写 `COMPLETE`。

envelope 至少包含：

```text
schema_version, snapshot_id, provider, provider_contract_version,
collector_id, collector_git_sha/build_sha, fencing_token, upstream_spec,
high_watermark, source_observed_at, fetched_at, record_counts,
payload_sha256, previous_snapshot_sha256
```

import 前校验活动 collector/token/key/build/schema/contract、签名、hash、marker 和连续前驱。
任一失败整批零写。业务候选与消费 watermark 同事务提交；重放 noop；乱序/缺前驱失败。赛日
RPO 5 分钟、RTO 30 分钟；非赛日 RPO 24 小时。payload 保存 30 天，manifest/receipt/audit
长期保留。

`jrvltsql` 只是访问层，权威来自 JRA-VAN。版本化 marker registry 将
`record_type + raw_status + sequence/correction` 映射到 result phase；三名、五名、partial
和未知 marker 都只能 provisional。只有 proof 明确的最终 marker 才 official，之后明确更正
才 corrected。NAR 使用完全独立 marker 合同。

以上全部属于阶段 B/D；阶段 A 不依赖 collector。

## 5. 赛前刷新配置

推荐值已在方案审核中通过，但用户仍需在阶段 B 实现前确认预算：

| 阶段 | P0 | P1 |
|---|---|---|
| 进入窗口 | T-21，每日 | T-14，每日 |
| 中期 | T-7 至 T-49h，每 6h | T-72h 至 T-25h，每 6h |
| 临近 | T-48h 至 T-7h，每 2h | T-24h 至 T-7h，每 2h |
| 开赛前 | T-6h 至出走，每 30min | 同左 |
| 首次赛果 | T+3min | 同左 |
| 时间完成 | T+30min | 同左 |

单场逻辑刷新上限约 P0 67 次、P1 40 次；adapter 应按“地区 + 赛日 + provider”合并请求。
默认网络上限建议总计 100 次/日、单 provider 40 次/日，并复用 HostBudget。预算不足时降频，
不能挤占新闻 worker。

## 6. 新闻特殊放行合同（阶段 C）

分类必须发生在翻译成功后、普通评分前，输出：

```text
affects_race_details
matched_race_id
event_type
extracted_changes
evidence
confidence
```

只有同时满足以下条件才绕过软门禁：

- `confidence >= 90`；
- 唯一匹配到具体赛事届次；
- 新闻包含会真实改变详情的结构化变化；
- assessment 的 article content hash 仍有效。

仅出现赛事名不得放行。跨届、多候选、低置信度进入人工审核且零赛事写入。

只允许绕过普通热度、价值评分、地区产量和普通编辑阈值。以下仍为硬门禁：

- 翻译失败；
- 重复新闻，包括 `possible_duplicate_content`；
- 来源合规/production approval；
- 标题、正文、source URL、发布时间完整性；
- rewrite/validation 失败；
- 核心术语或实体冲突；
- 未知 blocker 默认 hard。

发布与字段回写解耦：

1. 新闻发布事务成功；
2. `on_commit` 派发字段 candidate apply；
3. apply 失败可重试，不回滚已发布新闻；
4. 发布失败则字段零变化。

QQ `(article, target)` 唯一性必须保留；racecard update 默认不自动发 QQ。

## 7. 测试先行执行规则

取得实现授权后，第一位 subagent 必须只拥有测试文件，先写阶段 A 测试并实际取得 RED。主线程
在任一 subagent active 时遵守 `docs/codex_workflow.md` 静默规则，只能等待或派发无冲突任务。

有效 RED：

- 因 lifecycle 模型、纯决策、claim 或 apply 尚不存在而失败；
- 断言明确指向目标行为；
- 命令、时间、exit code、失败测试和缺失能力写入 `test_cases.md` 的证据区。

无效 RED：

- fixture、迁移依赖、语法或 import 拼写错误；
- mock 目标错误；
- 数据库未启动；
- 用 SQLite 冒充 PostgreSQL 并发语义。

阶段 A 首批必须覆盖 `test_cases.md` 的 A01-A33，并至少取得以下核心 RED：

1. 有精确时间的 T-1、T+0、T+30。
2. 无时间赛事当地次日 00:00。
3. London/Paris/New York/Los Angeles DST。
4. 延期 generation 使旧任务失效。
5. cancelled 不变。
6. 重放不重复 transition。
7. PostgreSQL 双 worker 只一次有效更新。
8. provider 失败但状态推进、零伪造赛果。
9. provisional 与 official 分离。
10. strict dry-run 零写、shadow proposal、首次 enforce、enforce replay。
11. 显式 manifest 纳管、资格失效关闭、未纳管赛事不扫描。
12. cache on-commit 失效和页面一致。
13. lifecycle scanner 不 dispatch live polling。
14. 100 due controls 查询数不超过 8，batch 内存有界。

推荐测试文件：

- `server/stable/test_race_event_lifecycle.py`
- `server/stable/test_race_event_lifecycle_postgres.py`

阶段 B/C/D 必须分别先写对应 `test_cases.md` B/C/D RED，不能用阶段 A 授权推定用户已授权
采购、provider enable 或新闻门禁 enforce。

## 8. 推荐实施顺序与 subagent 文件所有权

强烈建议按 A/B/C/D 四个独立可发布、可回滚 change unit 完成。先只实现阶段 A。

### 8.1 阶段 A

按以下串行顺序委派；每个 subagent 必须被告知“不是独占仓库，不回退他人改动，禁止
commit/push/PR/deploy/生产写入”。

1. 测试 subagent
   - 所有权：新 lifecycle 测试文件，以及 `test_cases.md` 仅追加 RED 证据。
   - 产出：真实 RED。
2. application subagent
   - 所有权：`models.py`、新迁移、`services/race_event_lifecycle.py`、必要的 admin。
   - 产出：纯决策、原子 apply、audit、cache invalidation、GREEN。
3. integration subagent
   - 所有权：`tasks.py`、manifest reconciler/management command、PostgreSQL claim。
   - 产出：bounded selector、claim TTL、generation、幂等和查询边界。
4. operations subagent
   - 所有权：Celery/setting/Compose 示例配置和 change 文档。
   - 产出：默认 off、Beat 每 5 分钟、明确 queue、无凭据配置、回滚说明。

文件有交叉时必须串行；不要让两个 subagent 同时编辑 `tasks.py`、`models.py` 或迁移。

阶段 A 不得：

- 增加或启用新 provider；
- 改新闻门禁；
- dispatch race-live polling；
- 批量修正历史赛事；
- 自动纳管全表；
- 改首页“近期赛事”。

### 8.2 阶段 B

在阶段 A 独立 review/授权/发布后再做。先完成 provider contract proof 和字段级 fixtures，再实现
authority/change、racecard refresh 和日本 snapshot importer。TRA core、TRA North America、
JRA、NAR 必须有独立开关和 kill switch。

### 8.3 阶段 C

先 classifier shadow，再独立启用 soft-gate bypass，最后另行授权 field auto-apply。三者不得
一个开关同时启用。

### 8.4 阶段 D

只扩展现有 selector/race_live_worker/revision，不建第二套结果 scheduler。先 shadow 单场，
再 allowlist。阶段 A 上线不能改变 event 924 或现有 race-live 行为。

## 9. 自测矩阵

Claude 在启动任何测试 subagent 前必须先重新核对主线，不安装或升级依赖，且不输出 `.env`：

```sh
git fetch origin
git status --short
git rev-parse HEAD
git rev-parse origin/main
git merge-base HEAD origin/main
git worktree list --porcelain
git diff --name-status HEAD..origin/main
git diff --unified=0 HEAD..origin/main -- \
  server/stable/models.py server/stable/tasks.py server/stable/services/race_events.py \
  server/stable/admin.py server/stable/signals.py server/stable/migrations \
  docs/codex_workflow.md docs/changes/automate-race-event-lifecycle
```

交接 OID 只是记录，不是可长期复用的移动基线。若 `origin/main` 已前进：

1. 只读检查 merge-base、迁移叶节点、模型/任务/配置入口和上述 hunk overlap；
2. 不在当前 worktree 静默 merge/rebase，也不覆盖主工作区；
3. 无相关重叠时，从最新已验证 `origin/main` 重新建立或更新独立干净 worktree；
4. 有相关重叠、迁移冲突或已审假设变化时，先修订 spec/design/test/tasks/rollout，并回到同一
   `lifecycle_plan_reviewer` 会话复审；
5. 方案重新通过且用户对当前版本重新确认实现后，才启动测试 subagent。

工作区与主线预检完成后，再自动发现当前可用 Python/Docker 环境：

```sh
docker image inspect umanews-historical-race-check:local
```

若现有项目镜像可用，建议从聚焦到回归执行：

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e CELERY_TASK_ALWAYS_EAGER=true \
  -e CELERY_TASK_EAGER_PROPAGATES=true \
  umanews-historical-race-check:local \
  python server/manage.py test stable.test_race_event_lifecycle -v 2

docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e CELERY_TASK_ALWAYS_EAGER=true \
  -e CELERY_TASK_EAGER_PROPAGATES=true \
  umanews-historical-race-check:local \
  python server/manage.py test \
  stable.test_realtime_race_results \
  stable.test_race_live_multiregion_selector \
  stable.test_race_live_racecard_sync -v 1

docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e CELERY_TASK_ALWAYS_EAGER=true \
  umanews-historical-race-check:local \
  python server/manage.py check

docker run --rm -v "$PWD:/workspace" -w /workspace \
  -e CELERY_TASK_ALWAYS_EAGER=true \
  umanews-historical-race-check:local \
  python server/manage.py makemigrations --check --dry-run

git diff --check
```

PostgreSQL 并发测试必须在仓库既有临时 PostgreSQL harness 或隔离 Compose 数据库执行，禁止连接
生产库；具体测试 label：

```text
stable.test_race_event_lifecycle_postgres
```

还必须运行：

- 生命周期聚焦测试；
- 赛事日历、详情、字段归一化、移动端相关回归；
- race-live selector、racecard sync、publication、rollback/kill-switch 回归；
- 阶段 C 时运行 translation、validation、dedupe、publishing window、QQ 回归；
- 100 due controls 查询数测试；
- 迁移 forward/backward（仅隔离测试库）；
- Compose config 静态检查；
- `git diff --check`。

不得以“全量测试太慢”为由省略受影响回归；可分批运行并记录每条命令与计数。

## 10. 独立代码 review

全部实现和主线程复验通过后，启动一位**未参与测试或实现**的独立 reviewer，并实际执行 Codex
原生只读 review。首次建立 reviewer 会话；有 finding 时修复并复用同一会话复审。

uncommitted review 的唯一允许命令：

```sh
python3 .codex/scripts/review_fingerprint.py
codex review -c 'sandbox_mode="read-only"' --uncommitted
python3 .codex/scripts/review_fingerprint.py
```

要求：

- 两次 helper 完整原始 stdout 和 `FINGERPRINT_SHA256` 逐字节一致；
- 内层启动头真实显示 `sandbox: read-only`；
- review 覆盖全部 tracked/untracked 改动；
- 所有 P0-P3 和其他 actionable finding 清零；
- 记录 reviewed scope、approved parent、`content_manifest_sha256`、完整 fingerprint；
- review 通过后冻结内容并停止，等待用户发布授权。

普通 diff、测试或人工阅读不能替代原生 review。

## 11. 灰度、回滚与生产边界

独立开关至少包括：

- lifecycle global mode、region、event allowlist；
- pre-race refresh；
- TRA core；
- TRA North America；
- JRA snapshot；
- NAR；
- news classifier；
- news soft bypass；
- field auto-apply；
- 现有 live scheduler/monitor/region/event。

阶段 A 推荐：

```text
部署 mode=off
-> 一次性 strict dry-run（零写、零 dispatch）
-> shadow 至少 48 小时且覆盖实际赛日
-> 少量人工核对赛事 enforce
-> 扩大 allowlist
```

小范围必须覆盖至少两个地区、有时间和无时间赛事，并包含 postponed/cancelled 负例。

严禁同一部署同时：

- 启用全部赛事自动写入；
- 启用新闻软门禁绕过；
- 启用新赛果来源；
- 批量修正全部历史赛事。

发布前必须重新核对最新 review fingerprint，取得当前版本发布授权，备份数据库，核对生产
HEAD、镜像、Celery 队列、锁、磁盘和当前新闻正文生产批次。若新闻正文历史批次仍在做生产写入，
本任务不得并发执行生产数据库写入、Beat 变更、服务重建或部署。

生产验收：

- 选定赛事的有时间/无时间推进正确；
- 日历与详情一致；
- provisional/official 不混淆；
- 没有重复发布或 QQ；
- worker、beat、race_live_worker、healthz、队列、锁和错误日志正常；
- 任一异常可通过独立开关停止，不反向伪造或覆盖高权威数据。

回滚以关闭开关、停止 selector、恢复上一镜像/提交为先。状态和字段数据通过逐场 baseline
manifest、SHA/generation 漂移校验产生反向 candidate；禁止无审计地批量覆盖。

## 12. 完成定义

每个阶段分别满足以下条件才算完成：

1. 对应 RED 真实且记录完整；
2. 实现与受影响回归 GREEN；
3. PostgreSQL 并发、Django check、migration drift、diff check 通过；
4. 独立原生只读 review 无 actionable finding；
5. fingerprint 冻结；
6. 停止等待当前版本发布授权；
7. 发布后只按 `docs/codex_workflow.md` evidence-only allowlist 回写真实运行证据。

任何 provider 尚无 proof、合同未冻结、marker 未登记、时区不确定或身份关联冲突，都应保持
关闭/候选/待人工审核；不能用猜测换取流程“完成”。
