# 出马资料、准确出走时间、赛果同步与生命周期集成设计

## 1. 当前真实状态

| 能力 | 已有实现 | 本任务缺口 |
|---|---|---|
| 赛事状态 | `RaceEvent.status` | provider 时间变化未统一 reschedule |
| 生命周期 | control/transition、scanner、generation/claim/CAS | shadow promotion/re-arm 缺合同 |
| live 调度 | `RaceEventLiveTracking`、`race_live` queue | adapter 单一且当前关闭 |
| observation | `RaceResultObservation` 支持 racecard | provider-neutral schema/provenance 不足 |
| revision/projection | `RaceEventRevision`、projection control | 多来源 phase/conflict 合同不足 |
| racecard apply | TRA 专用 CAS/runner merge | 直接改 T，绕过 lifecycle 与完整字段审计 |
| 字段审计 | `RaceEventFieldAuthority/Change` | observation/hash/contract/decision 字段不足 |
| 马匹身份 | `HorseProfile` 与既有候选/人工锁基础 | runner 没有受审档案关联合同 |

2026-08-02 生产只读快照：运行镜像 `sha256:24fc89cf…67b9f`；web/worker/beat lifecycle 均
`false/off`；race-live scheduler/monitor/worker 关闭；16 个 control 全为 shadow、generation=1、
transition=0；event 940/941 只有过期 claim；event 924 有一条历史 provisional 链；Redis `race_live`
积压读数 7543。本任务不清理或消费积压。发布前必须重新取证，不能把该快照当实时授权。

规划期间 `origin/main` 前进到 `d5ae1d7e`：PR #65 已把 lifecycle advance task 从无人消费的
`default` 改投普通 worker 的 `celery`，并增加旧 generation 隔离测试；生产部署状态尚未在本轮
证明。R3 遗留的 2 条 `default` lifecycle 消息不清理、不重放，后续必须以新 generation/CAS 隔离。
本设计的 provider poll 仍只进入专用 `race_live` queue，不改变这项 queue routing 决定。

## 2. 核心架构

只保留两条正交轴：

```text
发生轴：RaceEvent.status
scheduled -> running -> finished
cancelled / postponed 优先

证据轴：RaceEventLiveTracking + RaceEventRevision.phase
racecard -> awaiting_result -> provisional_result -> official_result -> corrected_result
```

`finished` 不等于 official。official 可经现有 lifecycle control/transition 提前确认 finished；
provisional 不可以。两条轴幂等汇合，不新建状态机。

`RaceResultObservation` 继续统一承载 racecard/result raw 与 normalized observation；模型名称是历史
命名，不另建 `RaceDataObservation`。lifecycle scanner 保持无网络；provider poll 复用现有 selector、
tracking claim 和 `race_live` queue；不新增 Beat 调度器或赛果链。

## 3. 数据流与职责

```text
versioned provider registry
  -> RaceResultSourceIdentity
  -> bounded transport / immutable raw
  -> RaceResultObservation
  -> strict parser/normalization
  -> provider-neutral reconciliation
       -> field decisions + racecard revision
       -> result revision
       -> horse profile candidates
  -> atomic projection
       -> RaceEvent / Runner / Result
       -> lifecycle/live reschedule when needed
  -> transaction.on_commit cache invalidation
  -> public read policy
```

transport 不写业务字段；parser 不读写数据库；decision service 不联网。不同来源按自身频率采集，
但拥有相同的合同化写入资格；频率差异不是权威等级。

## 4. 数据模型建议

### 4.1 Observation 与字段审计

复用 `RaceResultObservation`，补充/明确 `source_class`、provider contract/registry digest、
transport run/Celery task、source updated time、raw artifact/size/retention。normalized payload 必须为
版本化 strict schema。

复用 `RaceEventFieldAuthority/Change`，给 change 增加 nullable observation FK、source class、source
updated time、parser version、raw/normalized SHA、registry/contract、Celery task ID，以及
`applied/replayed/needs_review/rejected` decision。新增字段先 nullable，schema migration 与历史数据
填充/约束收紧分开；旧代码在关闭态必须可读。

完整 raw 在线保留 90 天；冲突、人工确认和正式修正 raw 设置 legal/audit hold。hash、normalized、
revision 与 field ledger 长期保留。清理任务只能清大字段，不能删除审计关系。

### 4.2 Runner 与 HorseProfile

`RaceEventRunner` 是赛事内的一行，继续允许只保存来源马名/骑师/马号/闸位/status；没有档案链接
不阻止公开或赛果。为 runner 增加 nullable、可审计的 profile 关联或复用等价 link model；不得用
马名相似度直接写最终关联。

候选服务复用既有 HorseProfile source/alias/candidate/manual-lock 能力，输出候选、匹配特征与原因。
Admin 可确认候选、选择其他档案、创建新档案、撤销/改绑；人工确认产生 lock，自动同步只能提示
冲突。真正合并两个长期 HorseProfile 是独立身份治理，不属于本功能。骑师/练马师只保留文本和
external ID，不建主档。

### 4.3 Control 与 promotion 审计

不新增 control。继续复用 lifecycle schedule/claim generation、live claim generation/lock version、
projection owner generation。promotion 审计优先扩展 transition record kind 或 metadata，记录 mode、
manifest、before/after generation 和批准 identity，不建 promotion 表。

### 4.4 多 provider checkpoint（不是第二个 control）

新增 `RaceEventLiveProviderCheckpoint` 作为 tracking 子状态，唯一键 `(tracking, source_key)`，保存
`next_poll_at/last_attempt_at/last_success_at/consecutive_failures/circuit_reason/stale_at/phase/
last_observation_hash/contract_digest`。它没有 enable/mode/claim/token，不由独立 scheduler 扫描；
`RaceEventLiveTracking` 仍是每场唯一 claim/control，父 `next_poll_at` 等于所有可用 provider
checkpoint 的最小 due。

selector 每次只 claim 一场，冻结 `attempt_token + claim_generation + due-provider-plan hash`。worker
在事务外按稳定 source key 顺序对 due providers 做有界请求；单 provider timeout 后继续下一个。
每个响应先以 source identity + phase + content hash 幂等写 observation，再由 CAS finalize 分别更新
provider checkpoints 与父 min due。worker 崩溃后重投会 replay observation 并补齐 checkpoint；host
budget/circuit 只推迟对应 provider，不推迟整场。

## 5. Provider registry 与可信写入合同

route 以以下键授权：

```text
provider + region + data_kind + field/result_phase
+ contract version + host/path/identity + parser version
+ source class + automation_allowed + proof digest
+ request budget + retention policy
```

所有已确认 roster 来源均可自动写入；`source_class` 只反映真实 provenance，不作为全局优先级。
同值合并；同一来源新版本可修正旧版本；跨来源异值保持 canonical 并进入 review。公共网页采集可
直接建设 adapter，不把条款/robots 检查设为产品门禁；实现仍不得绕过登录、验证码或访问控制，
且必须遵守配置的限流、超时、内容大小、host allowlist 和 kill switch。

现有 `RaceResultSourceIdentity.result_authority` 与 `race_srcid_tra_supplemental` 是 legacy 合同。B 的
additive-first migration 增加 `result_contract_version/result_contract_digest/official_eligible/
finality_marker_kind`，删除按 provider 名称写死的 TRA constraint，并增加 fail-closed 约束：
`official_eligible=true` 必须同时满足 identity approved、automation allowed、非空 contract version/
digest 和受支持 marker kind。历史 identity 原值保留，新 eligibility 默认 false；TRA 历史 row 仍为
supplemental，不会因 migration 自动升级。

新 decision service 不比较 provider 等级，而按地区/result contract eligibility、payload completeness
和 finality marker evidence 判定。contract 可声明 `complete_payload_defaults_official`；此时完整性
证明与 contract digest 共同生成 marker evidence。来源显式 provisional 优先；contract 缺失/过期、
payload 不完整或 marker 不满足均零 official。`result_authority` 保留为旧代码只读兼容证据；回滚
旧代码前关闭新 result apply。

`RaceEventFieldAuthority/Change.authority_level` 同样保留为 legacy evidence，新 row 写中性值 0，
新 reconciliation 禁止读取它作覆盖比较。Admin 改为只读并标注 legacy；旧 row 不重写。contract
digest/decision 是唯一新语义；回滚旧代码时关闭新 field auto-apply。

## 6. 来源覆盖矩阵

| 地区 | provider | source class | racecard/计划 T | 修正 T/骑师/闸位/退赛 | provisional | official | 延迟/限流/成本 | 当前 proof / 生产自动化 | fallback |
|---|---|---|---|---|---|---|---|---|---|
| 香港 | HKJC | official operator | 是 | 是，需 parser proof | 明示时可 | 完整结果可单源 official | 官方页；无自动 SLA | registry 当前 manual，待 2–4 场 proof；获准后可自动写 | TRA Pro |
| 香港 | The Racing API Pro | licensed API | 是 | off time/jockey/draw/scratch，逐字段 proof | 明示时可 | 完整结果默认 official | 今日约 3m、明日约 15m、公开默认 5 req/s；Pro 已购买 | 已有 free/schema 基础，Pro 生产调用另授权 | HKJC |
| 日本 JRA | JRA 官网 | official operator | 正式 card；前日带马号/枠号 | 时间/取消/变更 | 明示时可 | 完整结果可 official | 页面约发布后 15–20m；公开网页 | 当前 manual route；待自动 parser proof | 时间 lifecycle；后续 JRA-VAN |
| 日本 NAR | NAR web/data | official operator | racelist/horse list | start/jockey/draw/withdrawal | 明示时可 | 完整结果可 official | 官方文件/网页；实时 SLA 待量测 | 当前 manual；独立于 JRA 做 2–4 场 proof | 时间 lifecycle |
| 英国 | TRA Pro | licensed API | 是，Core 覆盖 | change/scratch 字段待样本固化 | 明示时可 | 完整结果默认 official | 同上；Pro 已购买 | schema 基础存在；待生产 proof | Sporting Life |
| 英国 | Sporting Life | trusted publisher | 可采集 | 可采集，按页面字段 | 明示时可 | 完整结果默认 official | 网页采集、独立频率预算 | parser 已有部分能力；扩为 live 前做 2–4 场 proof | TRA Pro |
| 法国 | France Galop | official operator | 是 | 时间/runner/变更 | 明示时可 | official 可后续 correction | 官方页，无自动 SLA | 当前 manual；待 parser proof | TRA Pro / ZEturf |
| 法国 | TRA Pro / ZEturf | licensed API / trusted publisher | 可采集 | 按字段 proof | 明示时可 | 完整结果默认 official | 独立预算；TRA Pro 已购买 | TRA paid proof 与现有 ZEturf parser 待 live proof | France Galop |
| 美国 | Equibase | official database | entries/card | scratches/track/date | 明示时可 | 完整结果默认 official | official 后数分钟 payoff、约 30m chart；网页预算 | 当前仅 URL discovery；待内容 parser proof | TRA Pro / HRN |
| 美国 | TRA North America / HRN | licensed API / trusted publisher | 可采集 | changes/scratch/postponed，时区需 proof | 明示时可 | 完整结果默认 official | NA add-on/配额需运行前核对；HRN 网页预算 | 未做当前付费/页面 proof | Equibase |
| 爱尔兰（后续 cohort） | HRI / TRA Pro / Sporting Life | official/licensed/trusted | 可采集 | 按字段 proof | 明示时可 | 完整结果默认 official | 独立预算 | 设计支持；线上有赛事后再灰度 | 相互 fallback |

JRA-VAN/jrvltsql 只保留后续 Windows collector 方案，不能假定 Linux 可运行。赔率仅在 payload 附带
时 best-effort 保存，不单独提高轮询频率，也不纳入验收 SLA。

## 7. Racecard normalization 与 reconciliation

统一 schema 包含 event identity、aware T 与 IANA zone、local time、取消/延期、participants、逐字段
present/unknown/partial、source pointer/hash/update time。缺少 runner 不能推断退赛；退赛必须有明确
状态。赛事身份缺失或歧义时只存 observation，不自动创建 `RaceEvent`。

同一 polling reconciliation run 先保存所有成功 observation，再计算 canonical。相同值合并；同源
版本按 source updated time演进；跨来源异值保持 current value并写 needs_review。初值为空可应用首个
完整候选。manual lock 永远不被自动覆盖。

## 8. 原子 schedule transaction

固定锁序：

```text
RaceEvent
-> RaceEventProjectionControl
-> RaceEventLiveTracking
-> RaceEventLifecycleControl
-> RaceEventFieldAuthority（稳定排序）
-> current revision/observation
```

事务内校验 observation/source identity/registry/field contract/manual lock/event CAS；计算 schedule
group；append changes；applied 时更新 event；semantic schedule 变化时同时 bump lifecycle schedule 与
claim generation、live claim generation 与 lock version，清 token/attempt，重算 next due，并写绑定
observation/change 的 control-change 审计。commit 后才失效 cache。网络请求不得在锁或事务内执行。

任一获该字段权限的可信来源可单独取消/延期。延期无新 T 时停止旧 T；有新 T 时同事务受控回
scheduled。已经 T+30 finished 后收到未来 T 不自动回退：无 official 转高优先级审核，有 official
保持 finished；管理员 correction 才能回退并生成新 generation。

## 9. Polling 策略

racecard：T-72h 每日；T-24h 每 3h；T-6h 每 30m；T-90m 每 10m；T-20m 至 T+5m 每 3m。

result：T+3/T+5/T+10/T+20/T+30m；之后每 30m 至 T+6h，再每 3h 至 T+24h；仍无结果转
`result_sync_stale` 与每日补偿。完整 official 后低频修正检查至 T+24h。各 provider 独立频率、
budget/circuit；同等写入资格不意味着相同请求频率。

一次父 claim 的 execution plan 最多包含 registry 限定数量的 due providers。provider A 的 429/
timeout 只更新 A checkpoint，provider B 仍可在同 attempt 成功。fallback 成功不删除其他 checkpoint；
official 后各来源按自己的 correction due 继续至 T+24h。finalize 后父 `next_poll_at` 取所有未停用
provider due 的最小值；全部到 24h stale 后转每日 compensation。重复投递以 plan hash、observation
hash 和 checkpoint CAS 幂等。

完整可信结果默认 official；明确 provisional/unofficial 才 provisional；部分结果只 observation。
跨来源 official 冲突保持 canonical 并审核。official 可触发 lifecycle 决策提前 finished；provider
失败不阻断 T/T+30，也不产生空 revision。

## 10. Promotion、公开与通知

promotion 只支持 re-arm/recompute：manifest 冻结 event/control、expected mode=shadow、result
mode=enforce、generation/claim/schedule hash/proposal IDs/commit/expiry。false/off 且无有效任务时
逐场锁 control，CAS 后原子写 mode=enforce、bump generation、清 claim，保留旧 proposal 审计但不
执行，再按当前事实重算。apply 后全局仍 false/off，因此不执行；另获授权打开全局后 effective
mode 才为 enforce。mode/generation 漂移零写，相同 manifest 重放 noop。

B 先移除 `_publish_race_result_revision()` 中 provisional/official 对 `RaceEvent.status` 的直接写入；
B 只写 revision/result rows/confirmed evidence，且 C 上线前新 result public admission 保持关闭。
C 再把 official evidence 交给现有 lifecycle decision/control/transition；provisional 永不推进 status。
这样任一可部署 PR 都不会绕过 lifecycle，也没有 B/C 循环依赖。

字段/结果 commit 后调用既有 cache invalidation。公开页只读 admitted canonical revision；明确
provisional 显示醒目标记，部分/冲突 observation 不公开为完整结果。本阶段无新闻、无 QQ。仅预留
`(event, revision, target, notification_type)` 幂等通知接口，未来单独开关与授权。

## 11. 性能、迁移与文件范围

- selector 通过 due index 有界 claim；provider 请求可按 region/race day 合并，event observation 独立；
- 单 event apply，批次/并发上限配置化；锁内无网络；真实 PostgreSQL 验证锁序和 CAS；
- nullable additive schema 先部署，data migration/constraint 收紧分开；旧代码关闭态兼容；
- 90 天 raw cleanup 有界分页、skip locked、可重入，并观测删除量/失败量。

四个 PR：

1. A：models/audit migration、legacy authority 读写切换、registry/normalizer、provider-neutral
   racecard decision、关闭态 flags；
2. A2：runner-profile link/candidate、Admin confirm/rebind/audit/manual lock；
3. B：source identity contract/constraint migration、provider checkpoints、result adapters、poll policy、
   phase/revision，以及移除 result projection 的直接 status write；
4. C：schedule transaction、generation invalidation、shadow->enforce re-arm、official-to-lifecycle、cache。

A2 与 B 可在 A 后独立；C 在 A/B 接口稳定后。每个 PR 独立 RED、review、关闭态部署、灰度与回滚。

## 12. 灰度选择

香港、JRA、NAR、英国、法国、美国各选 2–4 场，先 observation，再在同 cohort 内分别授权字段、
结果公开和 lifecycle enforce。通过后该 cohort 可直接扩大到全部符合条件赛事，不要求其他 cohort
先通过。符合条件指确定性 event identity、有效 IANA zone、有效 T 和登记 route；通过地区的新
符合条件 event 自动使用现有 lifecycle control/enforce。Ireland 在线上出现赛事后同样灰度。
