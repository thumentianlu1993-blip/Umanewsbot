# 出马资料、准确出走时间、赛果同步与生命周期集成规格

## 1. 状态与工作流门禁

- 任务 slug：`build-race-data-sync-pipeline`。
- 基线：`origin/main@54a793089a5a265d608492a6846adb7d040eae00`（实现期间 main 前进后已
  fast-forward；包含 lifecycle advance task queue 修复及其关闭态部署记录）。
- 当前阶段：探索、spec/design、用户 grilling 与独立方案审核。
- 当前授权不包含测试/应用代码、migration、Celery 配置、联网 proof、生产写入、开关修改、
  commit、push、PR、部署、迁移或服务重启。
- 方案审核通过后必须停在用户“确认实现”门禁；实现必须先取得真实 RED，再交给实现 subagent。

本 change 是既有赛事生命周期 Phase A 的后续能力，不创建 OpenSpec change，不调用 OpenSpec
skills/CLI，不替代既有赛事、赛果或调度链路。

## 2. 当前事实与根因

现有系统已经有两条正交链路：

1. `RaceEvent.status` 与 `RaceEventLifecycleControl/Transition` 表达赛事是否按时间规则发生；
2. `RaceEventLiveTracking`、`RaceResultObservation`、`RaceEventRevision` 与
   `RaceEventProjectionControl` 表达 racecard、临时/正式/更正赛果及其公开投影。

Phase A 已实现 `scheduled -> running -> finished`、取消/延期终止、generation/claim/CAS、shadow
proposal 和 enforce applied。`finished` 只表示时间规则认为赛事已结束，不表示存在赛果。

当前主要缺口：

- `apply_race_live_racecard_refresh()` 写死 The Racing API，并可直接更新出走时间，却没有统一执行
  字段冲突决策、完整审计和 lifecycle reschedule；
- 字段审计尚不能完整保存 source class、source updated time、parser/raw/normalized hash、
  observation/task identity；
- racecard observation 已复用 `RaceResultObservation(phase=racecard)`，但 provider-neutral registry、
  parser normalization 和字段 apply 尚未形成统一合同；
- 生产已有 16 个 `mode=shadow` control。全局 enforce 不会提升逐场 shadow；shadow 终态 proposal
  可把 `next_refresh_at` 设为 `None`，仅改全局环境变量不会应用或重算旧 proposal；
- race-live selector/worker 当前关闭，且有历史 `race_live` 队列积压；不得把积压当作可恢复任务。
- 最新 main 已修正 lifecycle advance task 的 queue route，但该代码不证明生产已部署。R3 期间写入
  `default` 的 2 条旧 lifecycle 消息按既有 runbook 保留；本任务不清理、重放或消费。

## 3. 目标

1. 在有界窗口同步 racecard、runner、准确/修正出走时间、骑师、闸位、退赛、取消、延期和其他
   结构化赛事字段。
2. 所有已登记可信来源先形成不可变 observation，再经 parser/normalization、来源合同和字段冲突
   决策，最后写字段或形成赛果 revision。
3. 时间、时区、取消或延期变化与 lifecycle/race-live reschedule 同事务完成；旧任务必须因
   generation/claim CAS 失效。
4. T+3 分钟开始尝试赛果；可信来源给出的完整赛果可独立形成 official。只有来源明确标为
   provisional/unofficial 时才形成临时赛果；不完整 payload 只保存 observation。
5. 来源失败不阻止 Phase A 按时间推进 `finished`；official 可确认赛事发生，但 `finished` 不能
   反推 official，provisional 也不能提前推进 finished。
6. shadow 到 enforce 只采用显式 generation re-arm/recompute；同一事务必须把逐场 control mode 从
   shadow 原子改为 enforce，不应用历史 proposal。全局仍保持 false/off，另获授权才运行。
7. racecard runner 可在没有长期马匹档案时正常公开；系统给出 `HorseProfile` 候选，由管理员确认。
8. 本阶段不发新闻或 QQ；为未来 QQ 预留按 revision 幂等的通知接口。

## 4. 非目标

- 不新建第二套赛事状态机、control 表、Beat 调度器、result revision 或 public projection。
- lifecycle scanner 不调用 provider；provider 失败不阻断时间状态推进。
- 不自动创建缺失的 `RaceEvent`；未匹配赛事只保存 observation。
- 不批量回填 T-72 小时以前的历史赛事，不处理或默认消费历史 `race_live` 积压。
- 当前阶段不调用收费 API、读取生产 API 凭据或执行批量网络 proof。
- 不建立骑师或练马师主档、候选匹配和合并流程。
- 不把 JRA-VAN/jrvltsql 假定为 Linux 云端可直接运行，也不把 JRA 覆盖泛化到 NAR。
- Ireland 保留设计支持，但因线上当前可能无赛事，不作为首轮灰度前置条件。
- 不一次部署同时启用全部 provider、字段写入、赛果公开和 lifecycle enforce。

## 5. 可信来源、字段合同与冲突

首版登记的 HKJC、JRA、NAR、France Galop、Equibase、HRI、The Racing API Pro、Sporting Life、
ZEturf、Horse Racing Nation 均可在对应 parser/identity/schema proof 后自动写入。系统保留真实
`source_class`（赛事主办方、付费 API、可信发布方）用于 provenance，但不设置全局高低顺序。
写入资格按 `provider contract version + region + field/phase` 授予。

- 所有来源都自动保存 observation 与字段决策；
- 相同 semantic value 自动合并；同一来源的新 `source_updated_at` 可修正其旧版本；
- 不同来源冲突时保持当前 canonical 值并记录 `needs_review`，不得由抓取先后静默覆盖；
- 后续达成一致或管理员确认后才改变 canonical；manual lock 永远优先；
- 初始 canonical 为空时可应用首个完整可信候选，后来冲突仍保持该值并告警；
- source class 必须真实记录，不因可信而把第三方伪标为赛事主办方。

每个候选产生 `applied/replayed/needs_review/rejected` 之一。审核或拒绝也追加审计，但不改变
canonical 值。赔率是 best-effort 附带字段：有则保存，无则不失败，不做高频赔率采集。

现有数值 `authority_level` 保留为 legacy evidence，不再参与新 decision service 的比较。新记录统一
写中性值；Admin 明示“历史证据、非决策字段”并只读。旧 row 不破坏性重写；回滚到旧代码时所有
新 auto-apply 必须关闭，避免旧比较逻辑重新获得写权限。

## 6. 字段审计与保留合同

每次候选决策至少保留：event/subject/field、旧值/新值、provider/source class、URL/external ID、
confidence、observed/source-updated time、parser/version、raw/normalized SHA、Celery task/业务 run、
registry/contract version、关联 observation/revision、decision、自动 apply 与否、拒绝/审核原因和
schedule generation。

normalized observation、revision、字段审计和 SHA 长期保留；完整 raw payload 在线保留 90 天，
之后可归档/清理大字段。冲突、人工确认或正式赛果修正涉及的 raw 不自动清理。API key、签名和
敏感 header 永不进入 raw payload 或日志。

## 7. 时间修正与 reschedule

变更 `race_datetime/local_start_time/timezone_name/status(cancelled/postponed)` 的事务必须：

1. 按固定锁序锁 event、projection、live tracking、lifecycle control、field authority；
2. 校验赛事身份、字段合同、manual lock、终态冲突、IANA 时区和调用者 snapshot/CAS；
3. 写 append-only field decision，仅 applied 时更新 canonical；
4. lifecycle schedule/claim generation 增加，清 claim 并重算 `next_refresh_at`；
5. live claim generation/lock version 增加，清 attempt 并按新 T 重算 poll window；
6. 任一获该地区/字段写权限的可信来源可独立取消或延期；延期无新 T 时旧 T 不再可执行；
7. transaction commit 后才失效公开缓存，任一步失败整批回滚。

已由 T+30 进入 finished 后又收到未来 T 时不得自动回退：无 official 时进入高优先级审核，有
official 时保持 finished 并记录冲突。管理员可通过审计化 correction 回退并生成新 generation。

## 8. 采集节奏与赛果阶段

racecard 默认基线：T-72h 每日、T-24h 每 3 小时、T-6h 每 30 分钟、T-90m 每 10 分钟、
T-20m 至 T+5m 每 3 分钟。provider 可因发布时间、限流和成本覆盖频率，但不得超过批准预算。

result 默认基线：T+3m、T+5m、T+10m、T+20m、T+30m；之后每 30 分钟至 T+6h，再每 3 小时至
T+24h。仍无结果标记 `result_sync_stale` 并转每日补偿。取得完整 official 后仍低频检查修正至
T+24h。失败不生成空 revision。

`RaceEventLiveTracking` 保持每场唯一 claim/control；每个 provider 使用无 mode/claim 的子 checkpoint
保存独立 due/failure/circuit。父 `next_poll_at` 取最小 provider due。一次父 claim 可有界处理多个
due provider；某来源超时或 429 不阻止其他来源，崩溃重投通过 observation/checkpoint CAS 幂等。

- 完整可信赛果默认 official，不要求第二来源；“可信”必须由未过期的地区/result contract 表达，
  contract 可声明 `complete_payload_defaults_official` 并生成可审计 finality marker evidence；
- 明确 provisional/unofficial 才形成 provisional，并可在公开页醒目标注；
- 部分名次只保存 observation，不形成公开 canonical result；
- official 可经现有 control/transition 链提前推进 finished；provisional 不可以；
- official 冲突保持现有 canonical 并审核；明确修正经 `RaceEventRevision` 演进。

现有按 TRA 名称强制 supplemental 的数据库约束必须迁移为 contract eligibility 约束。历史 TRA
identity 不自动升级；只有 approved/automation-allowed、未过期 contract、完整 payload 和可审计
finality evidence 同时成立才可 official。`complete_payload_defaults_official` 是一种版本化 contract
marker，不是仅凭时间或 provider 名称推断。

## 9. Shadow/enforce promotion

只采用 `generation re-arm/recompute`：全局保持 false/off 时，promotion 逐场锁定并 CAS 验证
`mode=shadow`、generation、claim 与 manifest，原子写 `mode=enforce`、递增 schedule/claim
generation、清除旧 claim，使历史 proposal 失去执行资格但保留审计，再以当前 event、最新
observation 与当前时间重算 `next_refresh_at`。manifest 固定 expected/result mode。仅修改全局 mode
不属于有效 promotion；re-arm 完成前不会执行，另获授权打开全局后 effective mode 才为 enforce。

## 10. 独立发布切片

### A. `sync-racecards-and-race-schedules`

provider-neutral observation、normalization、字段审计、runner merge 与 schedule candidate。C 就绪
前 schedule-impacting apply 关闭。

### A2. `match-race-runners-to-horse-profiles`

为 event-scoped runner 生成 `HorseProfile` 候选；Admin 支持确认、选择其他档案、创建新档案、
撤销/改绑和审计。未确认不阻塞 racecard/result；确认后设置 manual lock。真正合并两个长期档案
不属于本 PR。

### B. `ingest-race-results-by-authority`

扩展既有 race-live adapter、既定 polling、provisional/official/corrected 与 revision；公开
provisional/official 由独立开关控制。B 必须先删除新 projection 对 `RaceEvent.status` 的直接写入，
只产出 revision、result rows、confirmed evidence；在 C 接入前 result public admission 保持关闭。

### C. `integrate-race-data-with-lifecycle`

实现 schedule transaction、generation/claim invalidation、re-arm/recompute、official-to-lifecycle
有限联动和缓存一致性。只有 C 可把 official evidence 经既有 control/transition 推进 finished。

四个切片必须是独立 PR。A2 与 B 可在 A 后独立推进，C 在 A/B 接口稳定后集成。

## 11. 地区灰度与验收

首轮六个独立 cohort：香港、日本 JRA、日本 NAR、英国、法国、美国。每个 cohort 选 2–4 场完成
observation、字段、赛果与 lifecycle 验收后，可独立扩大到全部符合条件赛事。Ireland 出现线上
赛事后另做 2–4 场灰度。

符合条件指：已有确定性 `RaceEvent` 身份、有效 IANA 时区、有效 T 和已登记 route。地区验收后，
新符合条件赛事可自动创建/更新现有 lifecycle control 并进入 enforce；缺任一条件只存 observation。

验收必须证明：重放无重复；时间变化使旧任务失效；来源失败不阻止 T/T+30；finished 与赛果阶段
正交；冲突/manual lock 不被覆盖；公开 provisional 标签正确；新闻/QQ 为零；美国逐场使用真实
`America/*` zone；provider、字段 apply、公开赛果与 enforce 可独立关闭和回滚。
