# 历史赛事赛历完整性修复设计

## 1. 设计总览

本 change 由四条实现链和一条受控数据治理链组成：

```text
年份双语义模型 ─┬─> 香港存量审核/修复 ─> canonical URL + legacy redirect
                 └─> 历史物化与导入写入门禁

公开筛选合同 ───> 历史重点 G1/G2 ─┬─> 稳定 keyset 分页
                                      └─> 全筛选参数守恒

参赛马身份合同 ─> 马号占位符归一化 ─> profile/source identity/name fallback
```

代码修复先在零生产数据环境完成；全库年份 census 与香港存量 prepare/apply 是部署后的独立
数据阶段，不能被代码发布自动触发。

## 2. 数据模型

### 2.1 `RaceEvent.edition_year`

新增 nullable `PositiveSmallIntegerField`：

- 第一阶段 migration 添加字段并把现有值回填为 `year`；
- 历史和当前创建路径随后双写 `year` 与 `edition_year`；
- `RaceEvent.year` 改为公开自然年，`edition_year` 改为届次身份；
- target/event 校验从 `target.year == event.year` 改为
  `target.year == event.edition_year`；
- 系列年度唯一约束从 `(race_series, year)` 迁移到
  `(race_series, edition_year)`；
- `(year, slug)` 继续是 canonical 公开路径唯一约束。

迁移不能只在文档中分阶段，因为生产 release task 会对当前镜像执行全部 pending migrations。
必须形成三个独立、分别 review/授权/构建的 release：

1. **Release A**：镜像只包含 nullable `edition_year`、旧值回填、双读/双写、public-path
   registry、target supersession 和 repair receipt schema；最终约束 migration 在该 commit
   中尚不存在。
2. **Release B**：全库 census 通过后，单独提交并发布移除旧 `(race_series, year)`、切换
   `(race_series, edition_year)`，并把 target `(race_series, year)` 唯一约束改为只覆盖
   `resolution_status != SUPERSEDED` 的兼容 migration；此时 `edition_year` 仍 nullable，数据
   apply 仍未自动执行。
3. **Release C**：数据 apply/verifier 完成且全库 blocker 为 0 后，单独提交并发布
   `edition_year NOT NULL` 与
   `local_date IS NULL OR year = EXTRACT(YEAR FROM local_date)`。

每个 release 都冻结唯一 migration leaf，部署前后保存 `showmigrations`、pending plan、commit
和 image。Release C 未完成前不得声称年份治理闭环。

### 2.2 `RaceEventPublicPath`

采用统一 public-path registry，而不是 canonical/alias 分表：

- `year`
- `slug`
- `event`（`PROTECT`）
- `path_kind`（`canonical|legacy`）
- `reason`
- `manifest_sha256`
- `created_by/created_at`

单表唯一约束 `(year, slug)`，并用条件唯一约束保证每个 event 只有一个 canonical path。
Release A migration 为全部现有 `RaceEvent` 回填 canonical registry 行。详情 view 只从 registry
解析路径：canonical 返回详情，legacy 在 event 已发布时 301 到其 canonical registry。
legacy 不进入日历、sitemap、搜索或系列历届列表。

所有 event 创建、year/slug 修改和 legacy 写入必须走同一
`reserve_race_event_public_path()` 服务、事务和 registry 唯一约束；migration/import 的 bulk
路径也必须显式调用 registry 同步器。`RaceEvent.year/slug` 是兼容投影，写后 verifier 要求与
canonical registry 一致。不得继续用分表 canonical-first 查询造成路径静默遮蔽。

### 2.3 目标年份

`HistoricalRaceEventTarget.year` 本 change 不改字段名，但在代码、文档和 artifact schema 中统一
标注为 `edition_year`。所有 target/event pair、selection、detail source 和 importer 的身份
比较逐步改为：

```text
target.year == event.edition_year
event.year == event.local_date.year  # local_date 已知时
```

香港普通马季错误 target 不能只靠新增 event 字段掩盖；审核 action 必须纠正 target 的届次年。

Release A 同时为 `HistoricalRaceEventTarget` 增加 `SUPERSEDED` resolution status、nullable
`superseded_by` self FK、`superseded_at` 和 `supersession_manifest_sha256`。superseded target
必须 `event=NULL`，不得被 selection/materialize/detail/import 重新领取。Release B 把 target
的 series/year unique 改成只约束未 supersede 行，使审计行保留时仍能创建正确 active 届次。

### 2.4 `HistoricalRaceCalendarRepairReceipt`

Release A 新增 exactly-once 权威模型：

- `manifest_sha256`（unique）
- `approval_sha256`
- `action_scope_sha256`
- `actor`（`PROTECT`）
- `status`（`APPLIED|VERIFIED|VERIFICATION_FAILED|ROLLED_BACK`）
- `rollback_sha256`
- `applied_at/verified_at/rolled_back_at`
- `verifier_result_sha256`

receipt 与业务写入在同一 `transaction.atomic()` 中以 `APPLIED` 创建；manifest unique 是重复
apply 的数据库门禁。verifier 只更新状态/验证摘要，rollback 不删除 receipt，而把成功状态改为
`ROLLED_BACK` 并保留原 apply 身份。`OperationLog` 只保存人类审计摘要，不能替代 receipt。

## 3. 写入合同

新增集中式 helper（建议位于 `server/stable/services/race_event_years.py`）：

- `derive_public_year(local_date, planned_year)`
- `validate_event_years(public_year, edition_year, local_date, cross_year_evidence)`
- `historical_event_identity(target, local_date)`

历史 materializer、通用赛事导入、日期发现 apply、详情导入和当前赛事初始化不得各自复制年份
判断。`RaceEvent.save()` 只做最后一道防误用检查，不替代 service 和数据库约束；bulk/update
路径必须通过各自受审服务。

日期发现的 `actual_year/cross_year_reason` 保留，但语义改为证明
`edition_year != public_year`，不能再允许 `RaceEvent.year` 与 `local_date.year` 不同。
旧原因 `hong_kong_racing_season_spans_calendar_years` 明确无效，不能证明不同届次年；包含该
原因的旧香港 artifact 必须重新 prepare，不能继续 apply。

## 4. 全库 census 与香港存量修复

### 4.1 prepare

新增管理命令建议命名：

```text
repair_historical_race_calendar_integrity --prepare --all-regions --output <new-dir>
```

prepare 必须：

- 拒绝已存在输出目录；
- 使用 repeatable-read 只读事务或绑定数据库 snapshot 标识；
- 枚举全地区 mismatch，不使用地区或年份起点截断；所有地区每行都进入 action，合法跨届次使用
  `repair_public_year_keep_edition` 修复 public year/slug/path 并保留 edition；
- 同时读取相邻 target、同系列全部年度 event、依赖计数和关键行哈希；
- 为每个系列输出完整年度图，并把每行分类为：
  - `ordinary_season_year_shift`
  - `legitimate_cross_year_edition`
  - `canonicalize_duplicate`
  - `conflict`
  - `needs_manual_review`
- 输出 machine JSON、review CSV、summary、manifest 和可读报告；
- 保持零写入。

不能仅凭日期差一年来自动分类。普通马季分类至少绑定 HKJC 赛历/结果来源、赛事名、日期和系列；
延期分类必须有非废弃原因与权威直接证据。非香港 mismatch 未分类会阻断 Release C。

连续错年可能形成多对一而非轮转。prepare 必须为 duplicate 给出 canonical 选择依据（来源、
完整度、公开/链接状态、现有 canonical 关系）、survivor event、duplicate event、全部 FK
动作与旧路径目标；无法无损确定时标记 `block`。

duplicate 固定终态：

- survivor target/event 成为唯一 active series/edition；
- duplicate target 设 `SUPERSEDED`、清空 event 并指向 survivor target；
- duplicate event 的所有可变依赖重挂 survivor 后，设 `race_series=NULL`，`year` 改为自然年，
  slug 改为 `superseded-<event-id>-<digest>`，visibility 永久 draft，provenance 绑定 survivor；
- 旧公开 registry path 改为 survivor 的 legacy path，duplicate tombstone canonical path 不公开；
- 不可重挂的 immutable receipt/projection/依赖必须在 prepare 中明确允许只读保留引用，否则 block。

### 4.2 apply

apply 只接受 prepare 生成且人工批准的不可变 manifest：

```text
repair_historical_race_calendar_integrity
  --apply
  --artifact <manifest>
  --expected-manifest-sha256 <sha256>
  --approval <approval.json>
  --expected-approval-sha256 <sha256>
  --actor <username>
  --confirm-reviewed-artifact
```

apply 顺序：

1. 核对命令 actor、manifest/approval SHA、批准人/时间和精确 action IDs；
2. 进入受控 maintenance/freeze，停止会写该 scope 的 beat/worker/race-live worker，并阻止历史
   import/reconciliation/P0 命令重新 admission；
3. 以 no-replace 方式预留 rollback artifact，绑定其 SHA；
4. 进入 `transaction.atomic()`，取得 advisory lock，并按
   series -> target -> event -> registry -> 可变依赖固定顺序取行锁；
5. 重算 scope、依赖计数和 precondition SHA；
6. 在 registry 中创建 legacy path；
7. 对 `rotate_year` 使用临时保留年份；对 `repair_public_year_keep_edition` 保持 target/edition、
   只修改 public year/slug/path；对 `canonicalize_duplicate` 按固定终态处理 target/event/FK；
8. 写入最终 target `year`、survivor event `edition_year/year/slug` 与 canonical registry；
9. 重算 source refs 中明确使用公开路径的派生字段；
10. 写业务变更与 `HistoricalRaceCalendarRepairReceipt(status=APPLIED)`；
    `OperationLog` 仅写审计摘要；
11. 同事务运行核心守恒检查，失败整体回滚；
12. transaction commit 后以 receipt 为权威运行 verifier、更新 receipt 状态，再派生文件 summary。

临时年份只用于单事务内解除现有唯一约束冲突，不公开、不提交中间状态；manifest 必须绑定其范围，
且正式年份写完后数据库中不得残留保留年份。

### 4.3 写后 verifier

独立只读 verifier 核对：

- 全地区全部已知日期 event 的 `year == local_date.year`；
- 普通马季 target `year == event.edition_year == event.year`；
- 合法延期 target `year == event.edition_year` 且 evidence 完整；
- rotate/keep-edition action 的 event PK 守恒；duplicate action 的 survivor、superseded target、
  detached/draft tombstone event 和全部 FK 重挂精确符合 approval；
- runner/result、文章链接、P0 来源、live projection 和 canonical link 计数/哈希守恒；
- 所有旧路径 301 到唯一新路径；
- 新路径 200，sitemap 只含 canonical；
- 无重复系列届次、无 registry 路径冲突、无临时年份残留。

## 5. 历史“重点”语义

`_public_race_calendar_base_queryset` 必须获得已解析的年份和 `today`，再决定 key scope：

```text
tab != key:
    不增加重点条件
tab == key and valid selected year < today.year:
    normalized_grade in G1-family ∪ G2-family
otherwise:
    priority in P0/P1 OR is_featured
```

历史判断使用上海日期，与当前公开日历一致。无效年份不能意外进入历史分支。

此规则只改变赛事日历“重点”tab；首页今日赛事、即将开赛和本周焦点保持现有运营/周焦点规则。

## 6. 稳定分页

### 6.1 游标

新增版本化、签名游标，payload 至少包含：

- `v`
- `mode` 与 `direction`
- `date_is_null`、`date_value`
- `time_is_null`、`time_value`
- `event_id`
- 页面的 first/last boundary
- 默认窗口的 `anchor_date`
- 当前规范化筛选的 SHA-256 指纹

使用 Django signing 和独立 salt。游标只表达位置，不包含可执行查询片段。签名失败、版本不支持、
字段非法或筛选指纹不匹配时同时丢弃 cursor 与 direction，返回当前筛选第一页。默认窗口游标还
必须匹配 anchor date，跨日旧 cursor 不得改变新请求定位。

### 6.2 排序和边界

SQLite/PostgreSQL 统一使用显式 annotation/null bit，canonical tuple 为：

```text
(date_is_null, date_value, time_is_null, time_value, id)
```

每一项均显式升序，NULLS LAST 不依赖数据库默认值。future/next 使用严格 `>` 复合边界，
past/previous 使用严格 `<` 复合边界并在返回前恢复升序。
查询多取 1 行判断是否存在下一页，模板只在确有页面时显示链接。

显式年份、搜索以及两者组合均使用该游标；默认当前日期窗口继续保留现有窗口行为，但复用同一
游标编码和筛选守恒 helper，避免两套 URL 合成逻辑。

### 6.3 查询性能

- 复用 `(visibility_status, local_date)`、`(visibility_status, year)` 索引；
- 如 PostgreSQL explain 显示历史 region/year/key 查询退化，再新增覆盖
  `(visibility_status, year, country_region, normalized_grade, local_date, local_start_time, id)`
  的受审索引；不得仅凭推测增加大索引；
- 名称搜索的 related joins 必须先得到唯一 event ID scope，再做 keyset，避免 `.distinct()` 与
  游标边界组合产生重复；
- 目标是每页固定 41 行上限，不把全年记录加载进 Python。

## 7. 无马号身份

年度研究采集器在任何 identity、dedupe、checkpoint 或 CSV 输出之前调用统一归一化：

```text
"" / "-" / "–" / "—" -> ""
其他值 -> trim 后原值
```

同场身份优先级：

1. 非空真实马号；
2. 已校验为当前 UmaFans host/path 的 profile URL 或来源 external ID；
3. 规范化完整马名。

同一优先级 key 对应不同马匹时 fail closed。缺马号但 profile 不同的多匹马必须保留；仅马名
相同且无更强身份时记录 ambiguity gap，不按行号拆成两个“唯一身份”。

占位符归一化保留在 collector 内的无 Django 依赖纯函数，不放入 Django service。checkpoint
identity 和最终 artifact 使用规范化后的身份。现有 manifest 已绑定源码 SHA/版本，因此本 change
锁定正式验证只能使用**全新 output root 和 fresh run**；不提供旧 checkpoint 迁移，不修改任何
旧不可变 artifact。

## 8. 并发、事务与安全

- Release A/B/C、全库 prepare、人工 approval、data apply、verify 是独立门禁。
- advisory lock 只是第二道保护；data apply 必须先进入受控 maintenance/freeze，停止并禁止
  historical inventory/detail/series reconciliation、race-live projection 和 P0 participant
  同 scope 写入 admission。
- `HistoricalRaceCalendarRepairReceipt` 是 apply 是否提交的权威；进程在 commit 后、文件
  summary 前退出时，
  重跑只读取 receipt 并继续 verifier，不猜测未知状态。
- 所有 artifact 路径必须位于受审 runtime 根，拒绝 symlink、覆盖和路径穿越。
- manifest 绑定代码版本、schema、数据库 snapshot、scope、每个 action 和输入 SHA。
- 输出不包含 secret、cookie、完整第三方正文或未脱敏异常。
- prepare/apply 不调用网络；来源证据必须来自已批准 cache/数据库 provenance。

## 9. 回滚

### 9.1 代码与 schema

- 第一阶段 `edition_year` 为 nullable，旧代码回滚仍可忽略新字段。
- Release B/C 前必须证明目标旧版本是否兼容；不兼容时不能只回滚代码。
- public-path registry 是公开路由权威，代码回滚前不得删除。

### 9.2 香港数据

apply ledger 必须保存逐行 before/after、registry ID、superseded target 和 tombstone event。
Release B 后、Release C 前，回滚只接受精确 apply manifest 和当前状态
SHA：

- 恢复 target/event 的旧 year/edition_year/slug；
- 只删除本 manifest 创建且仍未漂移的 legacy path；
- rotate/keep-edition 保持 FK；duplicate 按 approval/ledger 反向重挂，恢复 target active/event
  关联、duplicate event series/slug/visibility 和原 registry。

状态漂移时停止，评估恢复部署前已校验数据库备份；不得部分猜测回滚。

Release C 后旧 before 值会违反自然年约束，因此不允许直接执行上述 ledger rollback。必须先经
独立 review/授权发布反向约束 migration，再执行数据 rollback；若无法证明当前代码和反向迁移
兼容，则只允许恢复已验证整库备份。两条路径都必须在真实 PostgreSQL 演练。

## 10. 可观测性

- prepare summary：总 mismatch、普通马季、合法跨年、冲突、待人工、依赖计数。
- apply summary：planned/applied/already_applied/stale/blocked，任一 blocked/stale 进程非零。
- verifier：自然年一致率、target/edition 一致率、redirect 成功率和逐依赖守恒。
- 前台测试/监控：历史年份第一页、末页、重点 G1/G2 和旧香港 URL。
- collector summary：missing_number_rows、profile_fallback、name_fallback、ambiguity_gap、
  real_number_conflict，不能把缺号记为采集异常。

## 11. 主要受影响文件

- `server/stable/models.py`、新 migrations
- `server/stable/services/historical_race_batches.py`
- `server/stable/services/historical_race_date_discovery.py`
- `server/stable/services/historical_race_inventory.py`
- `server/stable/services/historical_race_importer.py`
- `server/stable/services/historical_race_detail_*`
- 新 `server/stable/services/race_event_years.py`
- `server/stable/views.py`、赛事日历模板
- 新受控管理命令和数据 verifier
- `runtime/research/collect_graded_race_participants.py` 及其离线测试
- 历史 inventory/date/detail、公开赛历、route redirect、研究 collector 相关测试

具体触及范围必须在测试 RED 前通过 `rg` 清单再次冻结；不得以本列表为由顺带重构其他赛事链。
