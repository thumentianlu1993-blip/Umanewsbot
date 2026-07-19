# 五地区准实时赛果公开 Beta 设计

## 1. 基线与复用结论

| 能力 | 现有实现 | 本轮处理 |
|---|---|---|
| 赛事总账 | `RaceEvent/RaceSeries/MajorRaceEvent` 已含五地区、等级和日期 | 复用；补 off time/外部 ID |
| 出马表/结果投影 | `RaceEventRunner/RaceEventResult` | 继续作为 current projection |
| 写入仲裁 | `RaceEventProjectionControl` + owner generation | 复用 |
| live 状态 | `RaceEventLiveTracking` 六态、claim/checkpoint CAS | 复用 |
| 不可变证据 | source/participant identity、observation、revision/item | 复用 |
| 发布门禁 | 四层 policy、event allowlist、read gate | 复用并增加 selector 配置上限 |
| TRA runner | Free results 单 event runner | 增加地区路由、快照复用和分页 |
| racecard | schema v2 但仅 `GB/Europe-London` | 泛化到五地区 |
| official | BHA/event 924 manual receipt | 泛化为五地区 route registry |
| official 公开 | 现有 resolver 错误要求 manual source 具备自动许可且 digest 与 TRA policy 相同 | 新增独立 official authorization/read gate |
| 调度 | Beat 每分钟 selector + 独立 `race_live` worker | 保留，增加地区/准入过滤 |
| 前台 | provisional/official/corrected 标签和读侧隐藏 | 直接复用，修正文案通用性 |
| 告警 | event 924 unavailable 邮件闭环 | 泛化 region/event dedupe |

生产只读基线为：

- production checkout/image revision：`91cf50ad677a1b8c9b253528c9db98481fd1031a`；
- `RACE_LIVE_SCHEDULER_ENABLED=false`；
- 独立 live worker runner 为 `the_racing_api_free`；
- tracking/allowlist 只有 event `924`，tracking 已停；
- event `924` provisional public，official incident 已 resolved；
- web/db/redis healthy，HTTP healthz `200`。

## 2. 目标池现状

`2026-07-19` 生产正式总账未来合资格赛事：

| 地区 | 数量 | 最近事件 |
|---|---:|---|
| 英国 G1-G3 | 71 | 7 月 25 日 event 925-928 |
| 法国 G1-G3 | 96 | 7 月 19 日 event 733-735；7 月 22 日 event 736 |
| 美国 G1-G3 | 160 | 7 月 19 日 event 420；7 月 24 日 event 421 |
| 日本含 Jpn/JG | 90 | 7 月 19 日 event 80/81；7 月 20 日 event 185 |
| 中国香港（含总账已标准化 Jpn/JG） | 1 | 12 月 13 日 event 2 |

这些 event 多数只有 `local_date`，没有 `race_datetime/local_start_time`。因此不能直接开启
scheduler，必须先 racecard prepare/initializer。

## 3. 来源路由与能力分层

### 3.1 暂定赛果主链

TRA 是五地区唯一自动 provisional adapter，但只在精确 event proof 成功后启用。官方
inventory 截至核对日显示 Core 有 GB/FR/US/HK/JP 历史结果；它只作为目标发现线索。

实时能力分四层记录：

1. `region_listed`：地区 code 存在；
2. `racecard_seen`：合资格赛事在 today/tomorrow racecard 唯一命中；
3. `shadow_result_seen`：同 external ID 出现在 results，participant 全集和字段通过；
4. `public_eligible`：延迟/页面/告警/official route 均通过。

只有第 4 层生成 event public transition manifest。coverage proof digest 绑定 event、
region、source、racecard/result SHA、观察时间区间和验收结论。

### 3.2 官方复核主链

新增 tracked registry：

`runtime/policies/race_live/official_routes_manual_v1.json`

顶层为严格 schema，按 route key 保存：

- `bha_manual_verification`
- `france_galop_manual_verification`
- `hkjc_manual_verification`
- `jra_manual_verification`
- `nar_manual_verification`
- `us_official_manual_verification`

每个 entry 包含地区、source key、固定 HTTPS host/path 约束、manual-browser-only、
automation=false、marker types、terms evidence、validity、operator role、SLA 和 contract
digest。美国 event 还要在 allowlist 中绑定精确官方 host（Equibase 或赛马场/监管方），
不能用一个任意 URL 通配。

Racing Post、Sporting Life、PMU、Geny、netkeiba、HRN 只可放在人工核对 notes，不生成
official marker，除非后续单独完成许可和稳定 feed 审核。

## 4. TRA registry v2

现有 registry schema v1 把 GB 路径写死。升级为 schema v2：

```json
{
  "source_key": "the_racing_api",
  "host": "api.theracingapi.com",
  "allowed_region_codes": {
    "united_kingdom": "gb",
    "france": "fr",
    "hong_kong": "hk",
    "japan": "jpn",
    "united_states": "usa"
  },
  "route_contracts": {
    "racecards_free": {
      "path": "/v1/racecards/free",
      "day": ["today", "tomorrow"],
      "limit": [500],
      "skip": [0]
    },
    "results_today_free": {
      "path": "/v1/results/today/free",
      "limit": [50],
      "skip": [0, 50, 100, 150, 200, 250, 300, 350, 400, 450]
    }
  }
}
```

URL builder 固定参数名、顺序和值；未知 region、day、limit、skip、重复 query、fragment、
非 HTTPS、host/port 漂移全部拒绝。proof 的前三次请求预算不变；v2 自动化 routes 不扩大
proof 默认请求数。

## 4.1 共同目标资格 core

新增纯函数模块 `race_live_target_eligibility.py`，prepare 和 initializer loader/verify
都调用，不允许各自复制条件。输入为 event 的 event ID、year、region、
`normalized_grade` 和可选 exception artifact；输出：

```text
eligible / reason / matrix_version / exception_digest
```

矩阵固定为：

- UK/FR/US：`year>=2025` 且 `G1/G2/G3`；
- HK/JP：`G1/G2/G3/JPN1/JPN2/JPN3/JG1/JG2/JG3`；Jpn/JG 只接受
  `RaceEvent.normalized_grade` 已有标准化值，不从地区或赛事名称推导。

exception artifact 使用严格 schema，至少含 approved commit、event IDs、原因、批准证据
SHA、generated/valid-until 和 scope digest。normal eligibility 的
`exception_digest=""`；例外时 prepare 通过可选
`--eligibility-exception-file` 读取 `0600`、非 symlink 的独立 artifact，并把完整严格
schema 副本和 digest 绑定进对应 event manifest。initializer 从 manifest 重读该完整副本，
复核 approved commit、SHA/expiry/exact event scope。只在命令参数中传 event ID 不能绕过
矩阵；artifact 的 event IDs 必须与本 run 实际需要例外的 events 精确相等。

## 5. 五地区 racecard prepare

### 5.1 命令

在现有命令增加必填：

```text
--region united_kingdom|france|hong_kong|japan|united_states
--official-route <route-key>
```

同一 run 的全部 event 必须属于该 region。today/tomorrow 各请求一次，不能按 event
重复请求。

### 5.2 时间

- source `off_time` 必须是 aware datetime。
- `event.timezone_name` 必须是有效 IANA timezone。
- source instant 转换到 event timezone 后，local date 必须与 `RaceEvent.local_date` 相同。
- 英国默认要求 `Europe/London`、法国 `Europe/Paris`、香港 `Asia/Hong_Kong`、日本
  `Asia/Tokyo`。
- 美国不设单一默认；必须使用赛事已审核的 `America/*` timezone。
- initializer v2 不再写死 London，只验证 manifest 的 expected timezone 与 event 一致。

### 5.3 名称/场地匹配

- 先按 TRA region + local date + normalized course 缩小；
- 再按 event original name、active alias、series name、major race alias 精确集合匹配；
- 中文展示名不参与英文 TRA 匹配；日文原名可参与日文来源值匹配；
- `G1/G2/G3` 的 Group token 补全规则只对经过地区测试的英文 Group 名称启用；
- Jpn/JG 不映射成普通 G 等级；
- `len(matches)==1` 才生成 manifest。

### 5.4 事务

保持 schema v2 的 complete artifact、CAS、fresh/replay/verify 语义。一个 manifest 可以包含
同地区多个 event；任一 event blocker 整批不生成 applyable manifest。

### 5.5 赛前增量 refresh

`poll_race_live_event_task` 在 `scheduled/racecard_ready` 且 `now<off_time` 时不再只做
`pre_off_wait`，而是调用 `refresh_race_live_racecard()`：

1. 从同地区 150 秒 racecard cache 读取或按 host budget 获取 today 快照；
2. 只按已经绑定的 external race ID 查找，不重新做模糊赛事发现；
3. 形成 racecard phase observation 和 canonical hash；
4. 相同 hash replay，只推进 checkpoint；
5. 新 hash 在短事务锁 event/control/tracking/current racecard 后复核 owner generation、
   claim token、人工锁、external ID 和 previous revision；
6. 分配新 racecard revision，更新 current pointer 和 legacy runner objective fields；
7. off time 变化按同当地日期和最大 12 小时边界 CAS 更新
   `race_datetime/local_start_time/next_poll_at`；
8. 网络期间不持事务，迟到 observation 可留审计但不能成为 current。

participant 规则：

- 新 external runner ID 可在 off 前加入并建立 identity；
- 同 external runner 的 number/draw/jockey/weight 变化形成新 item；
- 后续 racecard 缺少旧 runner 不推断 withdrawn，旧 runner 保留 declared，并在 observation
  写 `missing_runner_source_gap`；
- 当前 Free racecard runner schema 没有已证明的 explicit withdrawn marker，因此本期
  不声称赛前自动退赛；final results 的明确 `NR` 才投影 non-runner；
- result completeness 以 current racecard 全集为分母；缺失 runner 既无 `NR` 时保持
  shadow 并告警。

refresh 沿用 T-24h/60m、T-2h/15m、T-30m/5m 窗口，同地区 cache 避免多 event 重拉。
source race status 表示 postponed/cancelled 时只生成 blocker/incident，不自动改粗状态。

## 6. 调度与结果快照

### 6.1 selector

`select_due_race_live_events_task()` 从设置读取非空
`RACE_LIVE_ENABLED_REGIONS`，传给 claim 服务。claim SQL 先做：

- `event.country_region IN enabled_regions`
- tracking enabled/due
- live owner
- source key TRA、approved、terms approved、automation true、not expired
- allowlist enabled、max mode 非 off

取得 bounded candidates 后，在网络前调用只读 `resolve_race_live_publication_policy()`。
shadow 和 public 均可轮询，off/invalid 不可。task 若发现漂移，使用 CAS checkpoint 释放
claim 并写原因。

### 6.2 快照缓存

live worker 并发固定 1，因此使用共享 Redis cache 即可避免 stampede：

```text
race-live:tra-results:v2:<registry-digest>:<region-code>:<provider-date>
```

value 只含 parser 归一化后的：

- payload SHA；
- fetched_at；
- total/pages；
- external race ID -> objective result row。

TTL `150s`。缓存 miss 才请求；每页经过 HostBudget reservation/outcome。Redis get/set
异常记 metric；若已有合格网络响应，cache set 失败不丢弃本次结果。

### 6.3 分页

1. 请求 `skip=0`；
2. 验证 `0 <= total <= 500`；
3. 按 `ceil(total/50)` 请求剩余固定 skip；
4. 在任何地区过滤前验证原始页条数精确等于
   `min(50, total - skip)`；
5. 每页 `total/limit/skip` 一致、race ID 唯一、响应/集合上限合格；
6. overflow、incomplete、metadata drift 和 deadline exceeded 保留结构化 pagination
   checkpoint；monitor 据此生成 incident，普通 payload 错误不误分类；
7. 任一页失败整组快照失败，不缓存、不覆盖 last-known-good、不用部分页发布。

results fetch 使用从 task 起始时间计算的 `165s` deadline。每页 transport timeout 为
`min(15s, remaining)`；十页均耗时 15 秒时仍可完成，超出 deadline 立即 fail-closed。

同一地区 batch 中的所有 claims 消费同一快照。暂保留单 event task API 兼容手动 runner，
但内部都走 `get_or_fetch_region_results_snapshot()`。

### 6.4 轮询

沿用现有算法：

- T-24h 至 T-2h：60 分钟；
- T-2h 至 T-30m：15 分钟；
- T-30m 至 off：5 分钟；
- off 后到 provisional：3 分钟；
- provisional 到 T+2h：10 分钟；
- T+24h/T+72h/T+7d：修订探针。

Beat 每分钟只选 due，实际 provider 请求受 cache 和 host budget 合并。

## 7. 通用 publication transition

现有 transition 的 CAS 和 bundle/manifest 机制保留，移除以下 event 924 专用假设：

- `event_id == 924`
- 地区必须 UK
- tracking/allowlist 全库 universe 必须 `[event_id]`
- route 必须 BHA

替换为：

- event 必须是正整数且有完整 live baseline；
- route 从 event allowlist 读取并在多地区 registry 精确命中；
- manifest 保存目标 event 的 policy/source/tracking/revision/participant digest；
- 另保存 `unrelated_scope_digest`，apply 前后证明非目标 event/policy 未变化；
- 每次 transition 只锁/改目标 event 的 event policy/allowlist/tracking/projection；
- global/region/source policy 只可在单独受审的 scope transition 中改变，event promotion
  默认不提升宽 scope。

首次部署时 global cap 可提升到 `official_public` 作为最大权限，TRA source cap 固定
`provisional_public`，各新 region/event 初始 shadow。这样 TRA 永远不能因宽 scope 获得
official 权限。event promotion 只提升 provisional；official 另走下一节的授权。

## 8. 独立 official/corrected publication gate

### 8.1 模型

新增 `RaceLiveOfficialPublicationAuthorization`：

- `event` OneToOne；
- `source_key`、`route`、`route_version`；
- `route_registry_digest`、`contract_digest`、`terms_evidence_digest`；
- `coverage_proof_digest`；
- `max_phase=official|corrected`；
- `enabled`、`version>=1`、`valid_until`；
- 唯一 event，source/route 非空、digests 格式和 phase check constraints。

它不含 `automation_allowed`，也不替代 `RaceResultSourceIdentity`。manual official source
继续 `terms_status=manual/automation_allowed=false`。authorization 只允许一个已经由
receipt 形成并有 marker evidence 的 observation 公开，不允许发网络请求。

### 8.2 Resolver

`resolve_race_live_official_publication_authorization()` 在 admission/read 两侧共用：

1. current event/source/observation/marker evidence/contract 全部存在且 source official；
2. source approved、manual、automation false、identity/registry digest 与 route registry
   一致；
3. global/region/event coarse policy 存在、未过期、mode 达到 official_public；这些 scope
   的 TRA registry/coverage 字段仍与 event 的 TRA source/allowlist 相等，用来防止宽
   policy 漂移，但不要求等于 official route digest；
4. TRA event allowlist enabled，official route/version/contract/terms/validity 和 coverage
   proof 与 authorization 相等；
5. authorization enabled、未过期、source/route/phase/version/digests 全等；
6. marker contract approved/有效，evidence raw/contract/parser/source timestamp 合格；
7. corrected 还要求 authorization.max_phase=corrected，默认 official。

official admission 在同一锁事务重读这些行后，原子写 revision/current projection/
publication audit/incident。`RaceEventRevisionPublication` 增加：

- `authorization_kind=provisional_policy|official_route`；
- `official_authorization_version`（provisional 为 0）；
- 既有 `registry_digest`：provisional 保存 TRA registry，official 保存 route registry；
- `coverage_proof_digest` 始终保存 event proof；
- `policy_versions` 保存 coarse policy 版本，official 另含 authorization version。

read gate 按 revision phase 分支：provisional 使用现有 TRA resolver；official/corrected
使用本 resolver。任一 gate 漂移只让当前 official revision不可见；旧 provisional
observation/revision/publication 审计不删除。运维 restore manifest 可把 current pointer
回到专用 `last_provisional_result_revision` 后重新投影。

### 8.3 专用 provisional 回滚指针

`RaceEventProjectionControl` 新增 nullable FK
`last_provisional_result_revision`：

- provisional 第一次成功公开或新的 provisional 修订成功公开时，在同一 publication
  事务把它更新为该 revision；
- official/corrected publication 只更新 generic current/last-known-good，不改此字段；
- migration 对既有 control 只选择同 event、kind=result、phase=provisional、
  `published_at` 和 publication audit 一致的最新 revision 回填；没有则保持 null；
- application 和 PostgreSQL 专项测试必须阻止跨 event、非 result、非 provisional 或未
  published revision 被当作回滚目标。

新增 operator-only `restore_last_provisional_result()`：

1. 要求 scheduler/monitor false、queue/active claim 空；
2. 单事务锁 event/control/tracking、当前 revision、provisional pointer/items/observation；
3. 要求 global/event 当前为本 rollback manifest 预期的临时 off，页面保持隐藏；
4. 调用专用 `validate_race_live_provisional_rollback_target()`，复核 pointer
   event/kind/phase/publication audit、TRA source approved/terms/automation/expiry、
   event allowlist/coverage/route digest，以及 manifest 中计划恢复的
   global/region/source/event mode/version/registry/coverage/expiry；validator 以计划状态
   计算 provisional effective mode，不把当前临时 off 当成来源/证据失败；
5. 从该 immutable revision items 原子重建 legacy `RaceEventResult`；
6. current pointer 指回 provisional，tracking 显式设为 `provisional_result`，清空
   official/corrected 页面时间但保留 incident/revision 审计；
7. 写 `race_live_emergency_provisional_restore` OperationLog。

这是显式 emergency rollback 旁路，不是正常状态机倒退。若 pointer 无效或当前 TRA gate
的 source/allowlist/digest/expiry 与计划 policy 任一不可用，事务零写入，global/event
保持 off，页面继续隐藏并产生告警。

恢复旧 image 后仍不立刻对外：

1. 发布时冻结本次 release image，并在 rollback artifact 记录
   `docker image inspect` 返回的完整 image ID `sha256:<64hex>`、可选 repo digest、
   reviewed commit、manifest SHA；回滚窗口结束前不得删除，本机 one-shot 只允许用该
   完整 image ID 寻址；
2. 发布前由受审 `build_race_live_rollback_env` 工具从生产 `.env` 严格解析并只复制
   `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_HOST`、
   `POSTGRES_PORT`、`POSTGRES_CONNECT_TIMEOUT`、`POSTGRES_SSLMODE`；工具拒绝重复/
   空值/变量展开，追加 `DEBUG=false`、非生产用途固定 `SECRET_KEY`、
   `POSTGRES_CONN_MAX_AGE=0`、专用 `POSTGRES_APPLICATION_NAME`、`memory://` Celery、
   dummy email backend 和全部 race-live 执行开关 off，写 `0600`
   `rollback.filtered.env`。文件 SHA-256 写入并绑定 rollback manifest；禁止变量只校验
   key、不回显 value；
3. old web/worker/beat/live worker 已运行旧 image 后，启动冻结 release image 的 one-shot
   wrapper。wrapper 在导入 Django 前校验 filtered env SHA、`0600`、必需 key、安全固定值
   以及禁止变量不存在；禁止前缀/变量至少包括 `THE_RACING_API_*`、
   `RACE_LIVE_TRA_SECRET_ENV_FILE`、`EMAIL_HOST*`、`RACE_LIVE_ALERT_NOTIFY_EMAILS`、
   `AUTOMATION_WARNING_NOTIFY_EMAILS`、`TRANSLATION_FAILURE_NOTIFY_EMAILS`，并要求
   `CELERY_BROKER_URL` 精确等于 `memory://`、`CELERY_RESULT_BACKEND` 精确等于
   `cache+memory://`。随后才加载同一 PostgreSQL 和
   只读 manifest；validator 使用 PostgreSQL read-only transaction，stdout 只输出
   event ID、digest、gate reason，退出码非 0 停止；
4. validator 通过后，仍用同一冻结 release image 的显式
   `restore_race_live_provisional_policies` one-shot 命令按 SHA 绑定 manifest 恢复
   global/region/source policy，event policy 继续 off；
5. 再用冻结 release image 执行只读 validator，确认如果 event policy 恢复为 provisional，
   所有非维护门禁均会通过；
6. 用冻结 release image 最后恢复 event policy；
7. 旧 web 的首次无缓存请求验证其真实 `resolve_race_live_public_read()` 可见。

这样 pointer/legacy restore 全程发生在页面隐藏状态，且不会形成“为了验证先公开”的窗口。
冻结 release one-shot 是受审回滚控制面，不启动 Celery、不访问外部来源、不装载来源/
通知凭据；filtered env 是含数据库密码的短期敏感 artifact，须 root `0600`、不入 git/
stdout、稳定窗口后删除；mutable
`umanewsbot:prod` tag 不可作为此执行面。

### 8.4 Scope 提升

official 公开前必须在 scheduler false 的维护窗口用受审 scope manifest 把 global、目标
region 和目标 event coarse cap 提升到 `official_public`，同时创建/启用 event official
authorization。TRA source policy保持 provisional。只提升 coarse cap 不会公开 official，
因为 authorization 和 marker evidence 仍是硬门。

## 9. 通用 manual official receipt

receipt 增加 `route`，loader 用 event allowlist 的 route/version 选择 registry，禁止调用方
任意指定 source authority。移除 event 924 和 BHA 文案硬编码。

apply 锁定：

- event/projection/tracking；
- provisional revision/items；
- incident；
- event policy/allowlist；
- marker contract/evidence。

`available` participant ID 全集必须与 provisional 相同。`match` 晋级 official；
`conflict` 先把目标 event policy 收紧到 shadow，再应用 official revision并把 incident
escalated；恢复公开需单独 restore manifest。`unavailable` 不生成 official source/
observation，只更新 incident probe 和持久 email intent。

邮件主题和正文使用 event ID、中文名、地区、route、incident ID；dedupe key 为：

```text
race_live_official_unavailable:<region>:<event_id>:<incident_id>:<route_version>
```

## 10. SLA monitor 和邮件 delivery

新增 `RaceLiveAlertIncident`：

- `alert_type`：`provisional_overdue/official_overdue/source_failures/
  pagination_overflow/host_circuit/queue_age`；
- `scope_type=event|region|host|queue`、`scope_key`、`reference_version`；
- `dedupe_key` unique；
- `status=open|resolved`、deadline/opened/resolved/last_seen/next_attempt；
- `delivery_attempts`、`delivery_token`、`delivery_lease_expires_at`、
  `alert_sent_at`、`last_error_code`；
- bounded objective `details` JSON。

Beat 每分钟运行 `monitor_race_live_sla_task`，受独立
`RACE_LIVE_MONITOR_ENABLED=false` 和 enabled regions 限制：

- tracking 在最新 off time +15m 仍无 provisional；
- official incident deadline 到期仍 open；
- tracking consecutive failures >=3；
- checkpoint 标记 pagination overflow；
- HostBudget circuit open；
- due row `next_poll_at < now-3m` 且无 active claim，作为 queue age。

monitor 每类查询有 batch 上限 100，只 stage incident/NotificationLog，不发送 SMTP。
`deliver_race_live_alert_task` 短事务 claim token/5 分钟 lease，事务外 `send_mail`，再短事务
CAS 写 SENT 或 FAILED。FAILED 的 `next_attempt` 为 1/5/15 分钟，最多三次；lease 过期可被
重领，SENT 永不重发。resolved incident 不再投递。结构化 metric 先落
TaskExecutionLog/OperationLog 和 checkpoint，后续可接 Prometheus，不阻塞本期。

## 11. 前台

现有详情页直接复用。需要补充：

- corrected label 统一为“赛果已更正”；
- provisional source label 可显示“The Racing API（补充来源）”；
- 官方 route 未完成时显示“尚待官方来源复核”，不展示内部 URL/terms；
- stale/conflict 文案按 event 生效；
- 日历、详情、结果摘要均调用 read gate，不从 legacy results 绕过。

不展示赔率、专有评级、评论、tips、图片或 API 原始 payload。

## 12. 资源和故障隔离

- `race_live_worker`：concurrency 1、prefetch 1、CPU/内存限制保持现值；
- 普通 worker 不注册 `race_live` queue；
- Beat 网络请求 `0`；
- 历史 native runner/runtime/lease/checkpoint 完全不读写；
- selector batch 默认 `20`，地区快照最多 `10` 页，results fetch deadline 固定
  `165s`；
- task 与独立 worker 的 soft/hard time limit 默认统一为 `180s/210s`，确保先由业务
  deadline 写入 fail-closed checkpoint，再由 Celery 软硬门禁兜底；claim lease 默认
  `240s`，覆盖 hard limit 后仍保留安全 CAS 余量；
- cache key 不进入页面 cache namespace。

## 13. 数据库和 migration

新增 `stable.0047` additive migration：

1. `RaceLiveOfficialPublicationAuthorization`；
2. `RaceLiveAlertIncident` 及 due/lease 索引；
3. `RaceEventRevisionPublication.authorization_kind` 和
   `official_authorization_version`；
4. `RaceEventProjectionControl.last_provisional_result_revision`。

data migration 只把既有 publication 标为
`provisional_policy/official_authorization_version=0`，并按上述严格条件回填最近合法
published provisional pointer；不创建 event 授权、不改变 current pointer、policy 或页面
可见性。新 authorization/alert 默认为空。

部署顺序：备份 -> 代码/镜像（flags off）-> migrate -> check -> web/worker/beat/live
worker -> 验证 event 924。旧 image 回滚前必须 scheduler/monitor off，把 official/corrected
event 精确 disable 并用专用 provisional pointer 原子恢复 current/legacy/tracking；
additive columns/tables留存，禁止 reverse migration 删除审计。

发布 artifact 另保存：

- reviewed release image ID/digest；
- old rollback image ID/digest；
- source commit/tree；
- rollback manifest path/SHA；
- validator/restore command version。

两份 image 都保留到至少 24 小时稳定窗口结束；删除必须是后续运维动作。

## 14. 成本与升级门槛

- 当前 Free：继续使用，不新增成本。
- Basic 参考旧预算约 `£27.99/月`，购买前必须在登录 dashboard 重新核价。
- North America add-on 不在本期购买。
- 建议升级 Basic 的全部门槛：
  1. 至少两个地区、每地区至少三场合资格赛事完成 Free shadow；
  2. identity precision 100%，完整结果 >=99%，错误状态 0；
  3. provisional P95 <=10m；
  4. 唯一剩余 blocker 是 Basic 独有字段/端点或 Free 明确权限限制；
  5. 书面列出升级后能解除的精确 blocker 和月成本。

## 15. 主要风险

| 风险 | 处理 |
|---|---|
| 地区在 coverage 页但今日无 racecard | 逐 event proof；保持 off |
| 美国 Free Core 只覆盖部分大赛 | `racecard_seen` 才初始化；不购买 add-on |
| 日本日文/英文名称不一致 | 只用已审核 alias；歧义人工处理 |
| 美国跨时区 | event IANA timezone，不用地区默认 |
| 当日结果超过 50 | 严格分页；超过 500 fail closed |
| 多赛事重复请求 | 地区快照 + 150s cache + worker concurrency 1 |
| official 页面不稳定 | manual route，不称自动 API；unavailable incident |
| manual official 与 TRA policy digest 冲突 | 独立 official authorization/read gate |
| racecard runner 缺少退赛字段 | 不推断；source gap，final NR 或保持 shadow |
| SLA 无人触发 | Beat monitor + 持久 alert incident + 事务外 SMTP |
| 通用 transition 误改其他 event | 单 event lock/CAS + unrelated digest |
| scheduler 误扫全量 | enabled regions 默认空 + tracking/allowlist 双门 |
| 48h 无香港自然赛事 | code ready/source unproven，禁止虚假上线 |
