# 未来七天重点赛事官方数据设计

## 设计结论

现有 `RaceEventDataCandidate` 和历史赛事 detail candidate 链路提供了“候选池不直接覆盖公开
字段”的基础，但赛前 canonical 数据已经存在于 race-live revision 模型。新链路不得另建第二套
canonical runner 表：它复用 candidate 的离线 artifact/sanitization，apply 时写入现有
source identity → observation → revision → participant canonical 链，再投影到 legacy
`RaceEvent`/`RaceEventRunner`。TRA 暂定数据仍为 supplemental。

## 数据流

```text
冻结窗口 + 生产清单快照
  -> 地区 source contract
  -> 受控官方 fetch（仅获授权的 route）
  -> 不可覆盖 source cache + receipt
  -> parser（raw -> normalized -> zh display）
  -> RaceResultSourceIdentity / participant source identity resolver
  -> immutable candidate artifact + blocker report
  -> dry-run / field review / coverage audit
  -> approved SHA gate
  -> atomic idempotent apply
  -> independent verifier + rollback manifest
```

## 组件边界

建议新增：

- `server/stable/services/upcoming_racecard_inventory.py`
  - 计算 aware `[start, end)`；
  - 枚举 `is_key_race` 超集；
  - 输出稳定 inventory snapshot，不联网、不写库。
- `server/stable/services/official_racecard_contracts.py`
  - 校验 provider/region/route/field/phase/version；
  - 未审核 route、过期 terms 或不允许自动化时在 transport 前拒绝。
- `runtime/tools/prepare_upcoming_official_racecards.py`
  - 只从受控缓存或明确允许的网络 route 生成 artifact；
  - 不导入 Django 写业务表。
- `server/stable/management/commands/review_upcoming_racecard_artifact.py`
  - dry-run、diff、覆盖与 blocker 审计。
- `server/stable/management/commands/apply_upcoming_racecard_artifact.py`
  - 必须传独立 approval receipt 和 `--expected-approval-sha256`；
  - projection control row lock + `transaction.atomic()` + compare-and-swap。
- `server/stable/management/commands/verify_upcoming_racecard_apply.py`
  - 独立读取 artifact 与数据库，验证写后值、旧值保护、覆盖和计数。

文件名是方案级建议，实现阶段可在真实 RED 后小幅调整，但不得改变合同边界。

## 唯一 canonical 层与 projection

本 change 不新增 phase、canonical participant 模型或 writer owner：

| 语义 | 现有持久化位置 |
|---|---|
| 官方赛事身份/许可 | `RaceResultSourceIdentity`，`result_authority=official`、approved terms/automation |
| 一次官方赛前观察 | `RaceResultObservation`，`result_phase=racecard` |
| 当前/历史出马表 | `RaceEventRevision(kind=racecard, phase=racecard)` 与 revision items |
| canonical 出马 | `RaceEventParticipant` |
| source-scoped runner ID | `RaceEventParticipantSourceIdentity` |
| 当前投影所有权 | `RaceEventProjectionControl` |
| event/participant 字段权威 | `RaceEventFieldAuthority` 与 append-only `RaceEventFieldChange` |
| 兼容旧页面/后台 | `RaceEvent.race_datetime/local_start_time` 与 `RaceEventRunner` projection |

官方 observation 的 `field_provenance` 保存
`provider_contract_version`、`time_semantics=scheduled_post_time`、原始时区/值及 source
receipt；`RaceEventRevision.source_authority=official`。不新增任何其他 phase。

`RaceEventRunner.external_runner_id` 只投影当前 revision 的 primary official source ID；
`source_refs` 必须同时带 `source_key/external_race_id/external_runner_id/revision_id`。它不是
canonical identity。多来源相同 runner ID 由各自 `RaceResultSourceIdentity` 命名空间隔离；
本 change **禁止跨 source 自动合并 participant**，名称、马号或相同 ID 字符串均不能成为
合并依据。若同一赛事已有另一 source 的 current participant/revision，新 source 整场形成
`cross_source_identity_review_required` blocker、零写；未来只有另一个 change 建立并人工批准
明确的 canonical horse identity 映射后，才可设计合并。官方来源切换同样不改 current revision。

## writer ownership 与并发

- 每场必须存在 `RaceEventProjectionControl`；不存在且已有任何 revision/participant/legacy
  runner 时 blocker。全空事件可在同一事务建立 `UNMANAGED` control。
- apply 锁定 event、projection control、lifecycle control（若存在）、current revision、
  participant identities、legacy runners 和 field authorities。
- 默认只接受 `write_owner=UNMANAGED`。`LIVE`、`HISTORICAL`、`MANUAL_PAUSED` 均拒绝；
  如未来需要 owner handoff，必须另有精确 handoff artifact/review，不在本 change 猜测接管。
- 在事务中把 owner CAS 到现有 `MANUAL_PAUSED`，绑定 approval SHA 并递增 generation；
  完成 revision/projection/verifier receipt 后恢复 `UNMANAGED`，再次递增 generation。
  所有其他 writer 也必须锁同一 control；没有锁/owner 检查的旧 writer 由回归测试定位并在
  本 change 实现前补齐，否则 apply 功能保持关闭。
- lifecycle control 不存在可继续；存在时只允许 `mode=off`，并把当前
  `schedule_generation` 纳入写前 CAS。任何 lifecycle transition、race_datetime 变化或
  generation 漂移都使整批失败。
- event/runner module manual lock、participant field authority manual lock 任一命中即阻断
  该场；批次默认整批回滚。

## 与现有链路的复用

- 复用 `race_event_source_cache` 的不可覆盖缓存和来源 URL receipt。
- 复用 `import_race_event_detail_candidates` 的 JSONL UTF-8、SHA-256、结构化行证据清洗和
  transaction 模式。
- 复用 JRA/HKJC/NAR parser 的行级 `source_refs`、官方原名、马号、骑师/练马师和状态映射；
  这些当前主要面向赛果/历史详情，赛前 parser 必须另写测试，不能假设 DOM 相同。
- 复用 `RaceEventRunner` 仅作 current revision 的 legacy projection，不得沿用只靠名称/
  日期的旧 matching。
- TRA `prepare_race_live_racecards` 只可提供发现/补充 diff；racecard observation 仍使用
  `phase=racecard`，但 `source_authority=supplemental`，不得进入 official approved manifest。

## artifact 合同

目录不可预先存在，完成后原子 rename：

```text
artifact/
  inventory.json
  source_contracts.json
  sources/<provider>/<opaque-id>.body
  sources/<provider>/<opaque-id>.receipt.json
  candidates.jsonl
  blockers.jsonl
  coverage.json
  manifest.json
review/
  approval_receipt.json
```

`manifest.json` 至少包含：

- `schema_version`、`generated_at`、`window_start/end`、项目时区；
- 生产 inventory snapshot SHA、source contract version/digest；
- 每个 source receipt 的 URL、fetched_at、HTTP 元数据、body SHA；
- 每场官方 event ID、官方 runner ID 完整度、time field semantics；
- raw/normalized/zh-display 字段级 diff；
- expected/confirmed/applicable/blocked 计数；
- payload 文件 SHA-256 和 `content_manifest_sha256`。

`manifest.json` 不哈希自身，也不包含 approval receipt。content manifest 算法固定为：

1. 递归枚举 artifact root 内 manifest 之外的普通文件；
2. 路径必须是 NFC 规范化 UTF-8 相对 POSIX 路径，按字节序排序；
3. 拒绝绝对路径、`..`、NUL、重复规范路径、symlink、非普通文件和 root 外 realpath；
4. 每项为 `{"path":...,"sha256":...,"size":...}`，按 key 排序、UTF-8、无 BOM、
   `ensure_ascii=false`、分隔符 `,`/`:` 编码成 JSON array；
5. 对该字节串计算 `content_manifest_sha256`；再对最终 `manifest.json` 原始字节计算
   `artifact_manifest_sha256`。

新增 additive model `UpcomingRacecardArtifactApproval`，作为批准真实性的唯一服务端信任根：

- `id`；
- `artifact_manifest_sha256`、`content_manifest_sha256`、`inventory_sha256`；
- `source_contract_digests`、`approved_scope`（JSON，创建前 canonicalize）；
- `verdict`（approved/rejected）；
- `approved_by`（`AUTH_USER_MODEL`，`PROTECT`）；
- `approved_at`；
- `canonical_approval_sha256`（上述字段规范 JSON 的 SHA-256，unique）。

数据库约束要求三个 digest 和 canonical digest 为 64 位小写十六进制；同一
`artifact_manifest_sha256 + approved_scope` 只能有一个 approved 记录。PostgreSQL migration
安装 trigger，拒绝 UPDATE/DELETE；Django model/admin 同样禁止修改/删除。

批准记录只能由 Django Admin 的专用字段级 review 页面创建。actor 必须取认证
`request.user`，要求 active staff、专用 `approve_upcoming_racecard_artifact` permission；
请求体不接受 `approved_by`，CLI/importer 不提供创建批准记录的入口。Admin 在同一事务重算
artifact/manifest/coverage，展示字段 diff 后写入 approval，审计日志记录 object ID 和 actor。

`approval_receipt.json` 位于 artifact root 外，只能由 export 命令从上述已存在的 immutable
approval row 导出，包含 approval ID、全部绑定字段与数据库 canonical digest。apply：

1. 校验 receipt 文件 SHA 与用户授权批次中的 `--expected-approval-sha256`；
2. 按 approval ID `select_for_update` 反查数据库；
3. 重算 DB row canonical digest，逐字段比较 receipt；
4. 要求 verdict=approved、actor 仍为 active staff 且 permission 未撤销；
5. 重算 artifact/content/inventory/contracts。

手工构造 receipt、填写任意有效 staff ID、缺 DB approval row 或任一字段漂移都必须零写。
仅传 artifact 自身 SHA 必须拒绝。

密钥、cookie、授权 header、整页超大 raw payload不得进入数据库；原始 body 只在受控 artifact
目录保留。异常文本经过 URL query、凭据和个人信息去敏。

## 时间与 DST

- 使用 `zoneinfo.ZoneInfo`，场地时区来自经审核的 event manifest。
- 英国 `Europe/London`、法国 `Europe/Paris`，美国逐场使用
  `America/Los_Angeles`、`America/New_York` 等；禁止 region 级固定 offset。
- 解析必须拒绝不存在或歧义的 local time，除非官方来源明确给出 offset/fold。
- 同时保存：
  `source_time_raw`、`source_timezone_raw`、`scheduled_post_time_utc`、
  `venue_local_start_time`、`display_time_zh_cn`。

## apply 规则

- 批次锁键由 `window + inventory_sha + approval_receipt_sha` 确定。
- 加锁后重新读取目标行并对比 candidate 中的写前 fingerprint。
- 按 event ID 排序 `select_for_update` 锁定上述 canonical/projection/authority/lifecycle 行。
- 任一赛事的官方 event ID、时间或 runner 身份冲突时抛错，整批回滚。
- source identity 唯一键为 `(source_key, external_race_id)`；runner identity 唯一键为
  `(source_identity, external_runner_id)`，由现有约束表达。马号只用于同场交叉验证。
- current revision 已来自其他 source 时，本 change 不合并、不切换，只报告 blocker。
- 修订采用 upsert + revision evidence：退赛/取消更新状态，不删除审计记录。
- 新值为空时 noop；新值与既有较高权威非空值冲突时 fail closed。
- 创建 `RaceResultObservation(result_phase=racecard)`、official racecard revision 与 items，
  更新 `current_racecard_revision/last_known_good_racecard_revision`，再从 current revision
  投影 legacy runners。
- `race_datetime/local_start_time` 与 participant 字段的每次实际变化同时更新
  `RaceEventFieldAuthority` 并追加 `RaceEventFieldChange`；manual lock 或更高权威冲突拒绝。
- 重放相同 official content hash 不新增 revision/change，只验证 projection 一致。

## 独立 verifier

verifier 不调用 apply service，逐项重算：

- artifact SHA 和批准 manifest；
- 窗口与地区时区换算；
- event/runner 外部身份唯一性；
- projection owner/generation、lifecycle generation 和 manual locks；
- 写前/写后数、每地区和每赛事覆盖；
- 已批准 diff 与数据库当前值逐字一致；
- 未在 artifact 的赛事/runner 零变化；
- 重放同一 SHA 为 noop；
- rollback manifest 能以 CAS 精确恢复本批写前值。

verifier 以 canonical revision 为真值，legacy runner 只能与 current revision 对账，不能反向
覆盖 canonical participant。

## 并行变更

`recover-race-results-through-20260727` 正在另一隔离 worktree 处理历史赛果与赛事身份，
会触及 `RaceEvent`、`RaceEventRunner` 和状态文档。本 change 实现前必须：

1. 重新 fetch 最新 `origin/main` 并确认该 change 的合并状态；
2. 对模型、迁移、candidate/apply service 和文档做 overlap diff；
3. 若两者都新增迁移，重新排列依赖并取得真实迁移 RED；
4. 不复用其 artifact、生产窗口或授权。
