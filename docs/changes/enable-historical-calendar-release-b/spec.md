# 历史赛历 Release B 规格

## 1. 背景

Release A 已在生产部署 `stable.0067_historical_calendar_release_a`，并完成全库只读 census。
生产共有 `9867` 个赛事，发现 `81` 条 `year != local_date.year`：中国香港 `80`、英国 `1`。
Release A 将这些行全部保守分类为 `canonicalize_duplicate + block`，可执行 action 为 `0`。

后续只读核验表明，81 条并非 81 个互相独立的重复赛事：

- 12 个香港系列存在同一 `race_series + local_date` 的真实重复边界；两侧 runner/result 等
  计数相同，但仍须审核字段级身份与依赖摘要。
- 重复边界之后连接着连续年份错位链。链内 event 各自代表不同比赛，不得逐条删除或合并。
- 至少一个香港系列在同一自然年有两届不同比赛，必须保留不同 `edition_year`，且 public slug
  需要显式消歧。
- 英国 1 条为跨自然年的届次候选，不能套用香港普通马季轮转规则。

Release B 的职责是切换 series/edition 约束，并让 prepare/apply/verifier 支持经人工审核的
“系列级修复计划”；Release B 部署本身不执行生产数据修复。

## 2. 目标

- 将 event 唯一身份从 `(race_series, year)` 切换为
  `(race_series, edition_year)`，`edition_year IS NULL` 时继续保持 Release A 兼容态。
- 将 target 唯一身份改为只约束非 `SUPERSEDED` 的 `(race_series, year)`。
- 把 v1 的逐 event census 升级为 v2 系列级计划，显式表达重复边界、链式重挂、跨年届次和路径
  轮转，而不是自动猜 survivor。
- 对每个系列冻结 event、target、public path、canonical product link 和全部反向 FK 的写前/写后
  ledger，未知关系或漂移一律阻断。
- 保持 Release B 部署关闭态：不签 approval、不进入 maintenance、不 apply、不启用历史联网或
  Celery/Beat 调度。

## 3. Release B schema 合同

### 3.1 `RaceEvent`

- 移除 `uq_race_event_series_year`。
- 新增条件唯一约束 `uq_race_event_series_edition`：仅当
  `race_series IS NOT NULL AND edition_year IS NOT NULL` 时约束
  `(race_series, edition_year)`。
- 保留 `(year, slug)` 和 `RaceEventPublicPath(year, slug)` 的公开路径唯一约束。
- `edition_year` 在 Release B 继续 nullable；non-null 与自然年 check 属于 Release C。

### 3.2 `HistoricalRaceEventTarget`

- 移除无条件 `uq_historical_target_series_year`。
- 新增条件唯一约束 `uq_hist_target_active_series_year`：仅约束
  `resolution_status != SUPERSEDED` 的 `(race_series, year)`。
- superseded target 继续必须满足 Release A 的 event 为空、指向 survivor、时间与 manifest 完整
  合同，并在 Release B 强化为：`superseded_by` 必须是同 series、同 edition/year identity 的
  非 `SUPERSEDED` target，拓扑深度只能为一层且不得自指、成链或成环；普通链式重挂不得为了
  绕过冲突而滥用 `SUPERSEDED`。

## 4. 系列级 v2 action 合同

每个受影响系列只能形成一个原子 `series_action`，至少包含：

- `series_id`、完整 event/target/path/FK 快照及各自 SHA；
- 每个 event 的 `before` 与 `expected_after`：public year、edition year、slug、visibility、series；
- 每个 target 的 before/after event、year、resolution status；
- 每个 public path 的 before/after owner、kind、year、slug；
- 每个真实重复边界的 `duplicate_event_id`、`survivor_event_id`、字段级身份摘要、依赖处理策略与
  人工审核结论；
- 对同一自然年多届赛事的显式 `public_slug`，不得由 apply 临时猜测；
- 所有反向关系的逐 relation policy：`retain_on_tombstone`、`repoint`、`dedupe_exact` 或 `block`。

ledger 必须把对象划分为互斥三组：受管理的 target/public path、受管理的 canonical product
link、不可变 reverse dependencies。canonical link 不得同时计入 retain dependency SHA。

允许的系列操作为：

- `rotate_ordinary_season_chain`：香港普通马季错位链；
- `preserve_cross_year_edition`：公开自然年变化但保留届次年；
- `collapse_exact_duplicate_boundary`：仅处理经审核的同一实际比赛重复边界；
- `block`：任何 survivor、target、path 或依赖策略未决。

一个系列可以在同一 action 中组合 duplicate boundary 与 chain rotation，但不得拆成多个可部分
提交的 event action。

## 5. 重复边界终态

- survivor 保留实际比赛数据和正确的系列/届次身份。
- duplicate event 解除 `race_series`，改为永久 draft，并取得不可碰撞的 tombstone slug。
- 为 duplicate 建立 active `RaceEventProductCanonicalLink` 指向 survivor；禁止链和环。
- duplicate 的反向依赖默认保留在 tombstone 上，避免隐式删除或发生唯一约束碰撞。只有 artifact
  明确给出逐行 mapping 和哈希时才允许 repoint/dedupe。
- duplicate 原 public path 不自动指向 survivor；系列级 path ledger 必须明确其最终 owner。
  路径可以在同一事务内轮转给代表该自然年真实赛事的 event。
- target 只按系列链的真实届次重挂。若某 target 代表仍未导入的届次，则恢复为无 event 的受审
  resolution 状态；不得伪造已导入赛事。

## 6. 用户与公开行为

- Release B 关闭态部署不得改变当前公开页面、URL、日历数量或可见性。
- 后续独立 apply 后，公开年份按 `local_date.year`；同一自然年多届赛事均可访问且 slug 唯一。
- 原错误 URL 的最终 owner 必须来自审核 path ledger；不存在审核映射时 action block。
- tombstone event 不进入日历、搜索、sitemap、首页或系列历届列表。

## 7. 验收标准

1. migration 仅包含两组旧约束移除和两组新约束新增，无 Release C non-null/check。
2. SQLite 与 PostgreSQL 均验证 event 可在同一 public year 下以不同 edition year 共存，且相同
   series/edition 被拒绝。
3. superseded target 可保留审计行，两个 active target 的相同 series/year 被拒绝。
4. v2 prepare 对生产形态 fixture 输出系列级 action；真实重复、链式轮转、同年多届和英国跨年
   各有独立 fixture。
5. 未审核 survivor、非等价 duplicate、未知 FK、路径 owner 冲突、target 链断裂均输出 block。
6. prepare 继续为 PostgreSQL repeatable-read read-only，数据库零写入。
7. apply 只接受 v2 manifest/approval/action scope/actor/live maintenance gate，任一漂移整系列回滚。
8. Release B 部署后生产 `81` mismatch、`0` receipt、`0` active gate 与两个关闭 flags 保持不变；
   新 v2 census 需另行只读授权。
9. Django check、migration drift、聚焦 SQLite/真实 PostgreSQL 测试、受影响回归和 diff check 通过。
10. 候选 Release B image 构建后，由绑定候选 commit/image、当前 `0070` migration leaf 和目标数据库的
    受控 one-shot 容器，在停服务和 DDL 前运行 schema preflight；其机器可读证据证明新约束
    兼容，未知或冲突状态均 fail closed，且不得调用 release orchestration。反向迁移另以旧约束
    兼容性查询为准，不以 receipt 数量代替。

## 8. 非目标

- 不在 Release B migration 中修复 81 条生产数据。
- 不创建 Release C 的 non-null 或自然年数据库 check。
- 不补抓跨栏赛马号，不猜测缺失马号。
- 不重抓历史赛事、修改赛果/马名、自动发布 draft 或启用历史网络。
- 不批量删除 duplicate 的 runner/result/candidate/P0/identity-conflict 依赖。
- 不把现有 v1 census 或 approval template 直接升级为可执行 approval。

## 9. 失败边界

- migration 前出现重复 `(race_series, edition_year)`：部署前检查阻断。
- 系列 action 无法唯一解释每个 event、target 和 path 的终态：block。
- duplicate 只凭年份/名称相似、没有相同实际比赛证据：block。
- FK ledger 缺少当前模型中的任一反向关系，或行级摘要漂移：block。
- 路径轮转会覆盖 scope 外 registry key：block。
- apply 中任一系列失败：同一事务整体回滚，不允许部分系列成功。
