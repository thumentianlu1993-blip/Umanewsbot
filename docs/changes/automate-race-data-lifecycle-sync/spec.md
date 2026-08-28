# 赛事时间、出马表与赛果自动同步规格

## 1. 文档状态

- 变更 slug：`automate-race-data-lifecycle-sync`。
- 工作流：仓库原生 `docs/changes/` 方案，不使用 OpenSpec，也不生成 OpenSpec 产物。
- 基线：`origin/main@2833558a6a2d67b7dc9816b53ea8ad5d580eb56c`。
- 当前阶段：实现、migration、Compose/Beat/worker、聚焦与 PostgreSQL 测试、零写 dry-run、扩展基线归因
  和生产只读 preflight 均已完成，代码位于 PR #108；生产尚未合并、迁移、部署或启用。
- 用户已明确覆盖早期“多 PR、7 天 shadow、逐地区/逐赛事人工批准”门禁：dry-run 通过后，只需一次最终
  生产确认，即可在同一隔离 release 中按开关顺序直接上线；任一步验收失败自动停止，不回退已留存审计。

## 2. 基线与最新只读事实

`2026-08-19 23:24 +08:00` 的方案基线快照（不再作为当前运行态）：

- web、普通 worker、Beat、db、Redis、Nginx 正常运行，运行 revision 与方案基线同为 `2833558a`；
- `race_live_worker=created`，没有运行；
- 未来 30 天共有 `99` 场 published/scheduled 赛事，其中仅 `8` 场有 `race_datetime`；
- 重点赛事 `61` 场，其中仅 `8` 场有 `race_datetime`；
- 未来 30 天 `99` 场均没有 `RaceEventRunner`；
- `RACE_RESULT_REVIEW_ENABLED=true` 且允许受限网络，但每天 `06:30/18:30` 的任务只准备审核包，
  不会自动 apply；
- race-data、race-live、lifecycle 自动写入开关均关闭；
- 主干已存在 race-data Slice A：`RaceDataProviderRoster`、严格 racecard normalizer、
  `RaceResultObservation`、`RaceEventFieldChange` reconciliation、raw cleanup 与唯一
  `RACE_DATA_SYNC_*` 字段写入 admission；schedule apply 目前明确返回 `slice_c_required`；
- 普通 `celery` 队列为 `0`，遗留 `race_live` 队列为 `7543`；该积压不属于本方案的可恢复任务。

`2026-08-28` 最新只读 preflight：web/worker/Beat 统一运行 `2833558a` / `sha256:4bc392…`，双 healthz
为 200，migration leaf 为 `0073`，external started/active lock 为 0（另有 2 条未持有的 lock 占位行），
`celery=0`、`race_sync_v2=0`、`race_live=7543`；磁盘可用 `12,211,531,776` bytes。生产 checkout 有
1,710 项历史 dirty，发布必须使用隔离 release。runtime 仅有 4 个旧键：`RACE_DATA_SYNC_ENABLED=false`
及 provider/region/field 三个空集合；本 change 的 scheduler/network/apply/capacity 等新增键尚不存在。
现有 lifecycle 为 `true/enforce`，race-live network/scheduler 仍关闭。

因此本功能不能简化为“增加两个 cron”。第一道门槛是建立可审计的赛事身份、准确时间和来源路由，
之后才允许动态调度出马表与赛果。

## 3. 产品目标

1. 对所有已发布且身份确定的未来赛事，持续补齐并修正 `race_datetime`、当地日期、当地时间和时区。
2. 在出马表发布后持续同步参赛马、马号、档位、骑师、练马师、负磅与退赛状态，并及时反映变化。
3. 从计划开跑时间后开始高频检查赛果；只要已登记来源给出终态且完整的赛果，自动更新网站。
4. 在计划开跑后 30 分钟仍不能得到可写赛果时生成明确告警并继续补偿，不猜测、不制造赛果。
5. 所有自动变化可解释、可重放、可审计、可关闭，并能由精确 revision 或 reverse manifest 回退。

最终覆盖 standing policy 内所有已发布且身份唯一的未来赛事。生产启用按能力开关顺序推进以便止损，
但不要求逐赛事人工确认，也不以固定 7 天 shadow 或地区 canary 作为初次上线前置条件。

## 4. 非目标

- 不自动创建缺失或身份不唯一的 `RaceEvent`。
- 不以赛事名、日期、马号或模糊字符串单独完成跨来源身份匹配。
- 不自动把赛事内 runner 合并到长期 `HorseProfile`；未匹配 profile 不阻塞出马表或赛果。
- 不采集高频赔率，不建设投注、预测、新闻或 QQ 自动发送能力。
- 不把生命周期时间状态与赛果权威混为一体；`finished` 不等于已有赛果。
- 不清空、重放、消费或迁移现有 `race_live` 7543 条积压。
- 不修改当前人工审核赛果任务的既有语义；新的自动链独立完成无人审核 apply，人工任务只保留为异常兜底，
  不能成为正常赛事的逐场确认门槛。

## 5. 核心状态语义

系统保留两条正交状态轴。持久化状态只使用现有枚举：

```text
赛事发生状态：scheduled -> running -> finished
              cancelled / postponed

RaceEventLiveTracking.state：scheduled -> racecard_ready -> awaiting_result
                           -> provisional_result -> official_result -> corrected_result
```

- `RaceEvent.status=finished` 只表示赛事发生状态，不证明赛果已经确认。
- `confirmed_result` 要求终态、完整、身份唯一和来源合同有效。
- 明确标记为 provisional/unofficial 的上游内容只能进入 provisional revision，不得成为确认赛果。
- confirmed result 可通过唯一 lifecycle 协调服务推进 `finished`；result projection 不直接绕过该服务写状态。
- `time_pending` 是纳管排除原因，不是 tracking state；`prerace_tracking`、`correction_watch`、`closed`
  都是由 canonical state、provider checkpoint 与 `next_poll_at` 计算的 selector/UI phase，不写入数据库。

## 6. 赛事身份要求

任何自动采集或写入前必须唯一确定稳定来源身份：

```text
provider
+ region
+ identity_namespace
+ external_race_id
```

该稳定键唯一映射一个 `event_id`。provider contract version/digest 属于本次 admission proof，允许升级，
不得成为稳定身份键或因升级制造第二条 identity。

辅助核对字段至少包括比赛日期、当地时区、马场、场次号或官方 edition。辅助字段冲突时保持阻断，
不能以名称近似度覆盖稳定外部身份。

一个来源身份只能绑定一个 `RaceEvent`，一个 `RaceEvent` 在相同
`provider + region + identity_namespace` 下只能有一个 current identity。
身份缺失、重复、过期或冲突时允许保存脱敏 observation，但业务字段、runner 和赛果均不得写入。

## 7. 来源优先级与前台语义

自动仲裁固定为 `licensed_api > official_operator > trusted_publisher`，当前分别对应 Racing API、已经由
官网/官方数据链导入的事实、已登记可信第三方。三类都属于可自动采用的正式来源，不需要逐赛事人工确认。
内部必须保留 provider、URL、抓取时间、source class、contract/proof digest 和 observation/revision；前台
统一显示“赛果”，不显示来源类别，也不显示 provisional/official/corrected 等内部阶段标签。

- 相同 semantic value 自动合并；同来源以更晚 `source_updated_at` 更新。
- 不同来源值冲突时，高优先级覆盖低优先级；同优先级按 observation 时间和稳定 provider key 决胜，保证
  重放确定性。manual lock 仍优先，身份不唯一、结果不完整或合同失效继续 fail closed。
- `human_reviewed_reference` 只属于旧人工兜底，不进入无人审核自动来源链。
- `reported_finish_position` 是公开名次真相并支持并列；legacy `official_finish_position` 可为兼容旧投影镜像
  同值，但不得被解释为前台来源声明或改变上述来源优先级。

每个 provider route 必须版本化登记 region、data kind、字段、host/path、identity namespace、
parser version、终态 marker、自动化许可、有效期、请求预算、限速和 proof digest。合同过期或不完整时
自动降为只观察。

## 8. 时间同步要求

### 8.1 数据合同

- canonical `race_datetime` 必须是 aware datetime；
- 同时保存来源给出的 IANA `timezone_name`、`local_date` 和 `local_start_time`；
- UTC 与当地时间必须可互相严格换算；不得把所有地区强制写为 `Asia/Shanghai`；
- 美国赛事必须使用逐场真实 `America/*` 时区并覆盖 DST；
- 来源只给日期、未给时间时，时间保持缺失，不能用往年或默认时间猜测。

### 8.2 更新规则

时间、时区、取消或延期变化必须通过一个原子协调事务：

1. 校验 event/source identity、parser/contract、manual lock 和调用者 baseline；
2. 追加 observation 和字段 decision；
3. 只在 decision=`applied` 时更新 canonical 字段；
4. 递增 lifecycle 和 race-sync generation，清理旧 claim/token；
5. 按新时间重算全部 `next_poll_at`；
6. transaction commit 后失效公开缓存。

旧任务携带旧 generation 时必须零写退出。赛事已 `finished` 后又收到未来时间不得自动回退，必须进入
高优先级审核或受审 correction。

## 9. 出马表同步要求

- runner 的稳定身份优先使用 provider horse ID；没有稳定 ID 时使用 event-scoped stable key 并保持待审核。
- 马号、档位、骑师、练马师、负磅与 runner status 是可变化字段，不得参与唯一身份本身。
- 新 observation 必须生成不可变 racecard revision；相同内容 hash 重放为 noop。
- 明确 withdrawal/scratched/non-runner 才更新状态；某次 payload 缺少 runner 不等于退赛或删除。
- 不硬删除既有 runner；更名、换骑师、改档和退赛均保留 before/after 与来源。
- manual lock 永远优先；自动来源只能创建冲突提示。
- 未关联 `HorseProfile` 的 runner 仍可公开显示和进入赛果链。

## 10. 赛果同步要求

可自动写入的结果必须同时满足：

1. event/source identity 唯一；
2. route、自动化许可、parser 和合同均有效；
3. 来源状态命中该 provider 明确登记的终态 marker；
4. 完整覆盖实际参赛 runner，或对未完赛、退赛、取消、并列等给出完整状态；
5. 名次序列可确定性投影，无重复身份、未知缺口或部分 `Also Ran`；
6. raw/normalized 内容 SHA、抓取时间、来源更新时间和 external race ID 已冻结；
7. 当前结果 baseline、manual lock 和 projection generation 未漂移；
8. 来源仲裁已经按固定等级、观测时间和 provider key 得到确定结果，且没有 manual lock 或身份冲突。

自动 writer 的持久 owner 必须是新增的 `data_sync`，不得复用 legacy `live`。只有 exact enrollment manifest
可把 `unmanaged` CAS 为 `data_sync`；`live/historical/manual_paused` 一律冲突，disenroll 只有在无 active
claim 且 baseline 匹配时才能 `data_sync -> unmanaged`。历史 `live` 不自动迁移。

死热/并列继续使用唯一 `finish_position` 作为内部稳定排序键；另增 authority-neutral、可重复的
`reported_finish_position` 保存来源报告名次。页面展示 `reported_finish_position`，仅历史无证据行才回退
旧字段；legacy `official_finish_position` 即使为兼容投影镜像同值，也不用于判断来源类别。所以可信第三方
`1,1,3` 必须显示为
`1,1,3`，而不是内部排序 `1,2,3`。

完整 confirmed/corrected candidate 在 R3 只创建 immutable、未公开 shadow revision，不移动 current、
不写 legacy results、不改 status。R4 在 lifecycle enforce + exact membership/trust root 下只 promote 该指定
revision，并在一个事务中写结果行、平台确认时间、来源标签、OperationLog 与 lifecycle transition；不能再次
创建相同 revision。更正创建下一 shadow revision并绑定 supersedes，不覆盖或删除旧 revision。

## 11. 动态调度

Beat 只运行一个轻量 selector，不为每场赛事创建固定 cron。selector 每分钟检查 due tracking，
使用 `next_poll_at`、generation、lease 和批次上限派发到专用 `race_sync_v2` 队列。

selector 不负责猜测纳管。独立 enrollment census 必须对当前 99 场及之后新发布赛事分类为
`eligible / route_missing / identity_conflict / time_pending / projection_owner_conflict /
duplicate / cancelled / postponed`。只有命中版本化 standing enrollment policy、稳定身份唯一、来源 route
有效、无 manual lock/owner conflict 的赛事，才可由 manifest-bound apply 幂等创建缺失的 source identity、
projection control、tracking 和 provider checkpoint。每个 enrollment manifest 绑定 event snapshot、
identity/route digest、预期 owner/generation 和精确 before state，可反向 disenroll；模糊匹配或策略外新赛事
只形成 proposal。data-sync 纳管不隐式加入 lifecycle enforce cohort，公开赛果仍需独立 lifecycle trust root。

默认频率：

| 数据 | 时间窗口 | 频率 |
|---|---|---|
| 开跑时间 | D-60 至 D-15 | 每日 |
| 开跑时间 | D-14 至 D-3 | 每 6 小时 |
| 开跑时间 | T-72h 至 T-12h | 每小时 |
| 开跑时间 | T-12h 至 T+5m | 每 15 分钟 |
| 出马表 | D-7 至 T-48h | 每 6 小时 |
| 出马表 | T-48h 至 T-6h | 每小时 |
| 出马表 | T-6h 至 T+5m | 每 10 分钟 |
| 赛果 | T+3/5/10/15/20/25/30m | 固定检查点 |
| 赛果补偿 | T+30m 至 T+2h | 每 15 分钟 |
| 赛果补偿 | T+2h 至 T+6h | 每 30 分钟 |
| 更正检查 | T+6h 至 T+24h | 每 3 小时 |

没有 `race_datetime` 时，只允许按 `local_date` 调度时间/出马表发现，不得启动赛果倒计时。

同一 provider、地区和日期应使用共享 snapshot/cache，一次网络请求服务多场赛事；不能按 event 数量
线性重复抓同一列表。provider 可以在合同范围内降低频率或请求预算，但不能绕过 T+30 告警。

## 12. 30 分钟 SLO

因为真实冲线时间通常直到上游发布时才可机器观察，SLO 分开计算，告警不能充当赛果成功：

1. `upstream_terminal_available_by_t30`：由冻结的独立官网/API/可信第三方 reference snapshot 判断，
   上游是否在 T+30 前已有完整终态；
2. `terminal_detection_rate`：在上述可用赛事中，系统是否在 T+30 前抓到并识别该终态；
3. `confirmed_publication_rate`：在已识别终态中，是否通过完整性、授权和原子投影后确认并公开；
4. `blocked_alert_coverage`：只统计上游确实未终态、不可用或身份/授权阻断的赛事，要求唯一 reason-code
   告警；该指标只证明运营覆盖，不计入赛果成功率；
5. 上游终态首次被系统观察后，P95 5 分钟、P99 10 分钟内完成公开更新。

生产上线观察期中，独立 reference 证明 T+30 前已完整终态的赛事，confirmed/publication rate 目标至少
95%，稳定运行后至少 99%，错误赛果始终为 0。该指标是上线后的持续验收和自动止损信号，不是强制等待
7 天或逐地区人工批准的前置门禁。上游未发布终态时继续补偿，reference snapshot 必须能独立证明告警
原因，不能由本系统自己的 alert 反向证明成功。

## 13. 队列、并发与资源隔离

- 新任务只进入 `race_sync_v2`；遗留 `race_live` 队列保持原状并单独治理。
- selector 可由普通 worker 消费，但所有 provider 网络和投影任务必须由专用 worker 消费。
- 专用 worker 设置独立 concurrency、prefetch、soft/hard limit、内存限制和网络 admission。
- 每个 event 只有一个父 claim；每个 provider 使用独立 checkpoint 保存 due/failure/circuit。
- 一个 provider 的 timeout/429/403 不阻止其他 due provider。
- host budget、指数退避、jitter、最大 payload、无重定向默认值和 circuit breaker 必须可配置。
- worker 崩溃重投必须通过 observation hash 和 generation CAS 幂等恢复，不重复 revision 或公开写入。

## 14. 可观测性与告警

至少记录：

- 未来赛事时间覆盖率、出马表覆盖率和 route_missing；
- provider 请求数、延迟、429/403/5xx、schema drift、circuit 和预算；
- observation matched/unmatched/replayed/partial/conflict；
- 字段 applied/replayed/needs_review/rejected；
- upstream T+30 terminal availability、terminal detection、confirmed publication、blocked alert coverage、
  terminal-detected-to-public 延迟、补偿和 correction；
- queue lag、active/reserved、stale claim、generation rejection；
- manual lock override 尝试、跨 event identity 冲突和重复 revision；
- 页面/DB verifier、缓存一致性、新闻与 QQ side effect 必须为 0。

告警内容只包含 event ID、source key、reason code、计数、时间和 SHA，不包含 credential、header 或原始正文。

## 15. 验收标准

生产启用前必须有代码/迁移/Compose、聚焦与 PostgreSQL 测试、zero-write dry-run、来源/容量配置、备份与
回滚证据；以下覆盖率与延迟指标从启用后首个自然赛事窗口开始持续计算，未达标时自动停在当前阶段或
关闭对应 provider/region/apply，不需要逐赛事人工确认：

- 支持地区的 future published events 100% 有唯一 source route，或明确 `route_missing`；
- 首发 cohort 在 T-24h 的 `race_datetime` 覆盖率至少 95%；
- T-6h 内出马表更新新鲜度 P95 不超过 15 分钟；
- 首发 cohort 终态赛果检测后公开延迟 P95 不超过 5 分钟、P99 不超过 10 分钟；
- 独立 reference 证明 T+30 前终态完整的赛事，confirmed/publication rate 初始目标 >=95%、稳定目标
  >=99%；真正 blocked 赛事 alert coverage >=99%，两者分别报告；
- 错绑赛事、跨 event 写入、manual lock 覆盖、重复 current revision、无证据公开均为 0；
- 关闭任一 provider/cohort/field/public flag 后，新写入在一个 selector 周期内停止；
- 所有写入都有 observation、revision/field decision、来源合同摘要和可验证回滚路径。
