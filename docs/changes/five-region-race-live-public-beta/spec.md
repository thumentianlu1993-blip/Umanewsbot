# 五地区准实时赛果公开 Beta 规格

## 文档状态

- 变更：`five-region-race-live-public-beta`
- 基线：`origin/main@566a9b1012aac7fe52ad7aec793ab0ff4b9eae18`
- 独立 worktree：
  `/Users/mentianlu/Code/umanews/.worktrees/five-region-race-live-public-beta`
- 阶段：方案待审核
- 核对日期：`2026-07-19`
- 生产基线：event `924` 是唯一已公开准实时赛事；全局 scheduler 关闭，其他地区尚未
  建立 tracking/allowlist。

## 目标

在不接管历史回填、不复制第三方专有评级或评论的前提下，把现有 event `924` 单赛事链路
扩展为英国、法国、中国香港、日本、美国共用的准实时赛果能力：

1. 重点赛事赛前通过 The Racing API（TRA）Free racecard 绑定外部赛事和参赛马身份；
2. 预计开跑后以 TRA 完整结果生成并可公开“暂定赛果”；
3. 官方来源异步复核后晋级“正式赛果”，后续变化形成“赛果已更正”；
4. 页面始终显示真实状态、来源类别和更新时间；
5. 每个地区、来源和赛事独立启停，未证明覆盖的范围保持 fail-closed。

本变更采用公开 Beta 口径。48 小时交付目标是五地区通用代码、配置、前台、调度、告警和
发布工具达到可部署状态，并对届时有真实来源证据的精确赛事开放。它不把“地区出现在 API
地区列表或历史覆盖页”误写成“该地区实时覆盖已验收”，也不承诺在 48 小时内人为制造没有
自然赛程的香港或其他地区实赛样本。

## 正式赛事范围

- 英国、法国、美国：`2025+ G1/G2/G3`。
- 中国香港、日本：`G1/G2/G3`、`JpnI/JpnII/JpnIII`、
  `JG1/JG2/JG3`。Jpn/JG 只接受赛事总账已有的标准化等级，不从香港赛事名称或地区
  自造、推断或改写等级。
- 中国香港和日本的 `JG1/JG2/JG3` 在 48 小时交付中可以保持
  `code_ready/source_unproven`，但不能据此生成正式 deferred 结论。只有从历史 handoff
  后首个可观测日连续 proof 90 天、样本不足时延长至最多 180 天，并取得带 SHA、精确
  赛事/等级、原始/active/deferred 分母、失败门槛、批准人/时间和
  `review_due_at<=批准后180天` 的用户批准 artifact 后，selector 才可在 artifact
  有效范围内暂缓；过期、范围外或未批准 artifact 不得影响目标池。
- 非上述范围只能通过用户审核的精确 event allowlist 纳入。

## 当前事实边界

`2026-07-19` 已通过官方文档和现有 Free 账户做最小只读探测：

- TRA Free 端点为 `/v1/racecards/free` 和 `/v1/results/today/free`，默认限速
  `1 request/second`。
- 地区表含 `gb/fr/hk/jpn/usa`，但地区表只证明可查询代码，不证明当日数据存在。
- 今日 racecard 实测 `43` 场：`GB 20 / FR 15 / IRE 8`。
- 明日 racecard 实测 `33` 场：`GB 26 / IRE 7`。
- 当时今日 results 为 `0`；不能从该空样本推导结果延迟或地区覆盖。
- 官方 coverage 页的 Core 库存含五地区历史结果，但美国完整 North America 数据是
  独立 add-on；历史库存不等于 Free 今日端点实时覆盖。
- 官方 FAQ 称今日 racecard/results 大约每 3 分钟更新，条款明确更新频率不保证；验收
  以真实 observation 的 P50/P95 为准。

因此本变更不得先购买 Basic、历史包或 North America add-on。升级只在 Free 已证明赛事
覆盖和延迟合格、但字段或端点权限成为唯一阻塞时另行建议并取得用户授权。

## Requirements

### Requirement 1：五地区目标必须经过同一资格选择器

- 目标必须绑定既有 `RaceEvent`、地区、年度、等级、日期、场地和可审核名称/别名。
- selector 只处理显式目标池中未来 24 小时到赛后修订窗口内的赛事，不扫描全天全库。
- 地区、等级、赛事日期、人工锁、历史/live ownership 任一不满足时不得初始化。
- 日文、法文、英文赛事名只允许 NFKC/大小写/标点归一化和已审核 alias，不使用模糊
  substring、编辑距离或自动翻译匹配。
- 美国使用赛事自身 `timezone_name`，不得把全美国强制为同一时区。
- 每个 event 必须保存 TRA external race ID 和全部 participant external runner ID；
  零命中、多命中、重复 external ID 或参赛马全集冲突均进入 blocker。
- prepare 与 initializer 必须调用同一个确定性 eligibility core。该 core 精确检查：
  英法美 `year>=2025 + G1/G2/G3`；香港和日本均为
  `G1/G2/G3/JPN1/JPN2/JPN3/JG1/JG2/JG3`。Jpn/JG 资格只读取事件总账已有
  `normalized_grade`，不得按地区、名称或来源文本推导。
- 范围外 event 必须绑定独立、只读、带 SHA 和有效期的用户批准 exception artifact；
  artifact digest、资格原因和矩阵版本写入 manifest 并在 dry-run/apply/verify/replay
  全部复核。prepare 只从 `0600`、非 symlink 的显式 exception 文件读取，并把完整严格
  schema 副本及 digest 绑定进对应 event manifest，initializer 必须重新验证
  approved commit、event scope、有效期和 scope digest。仅传入 event ID 或在名称中出现
  “Group” 不构成例外授权。

### Requirement 2：赛前 racecard 准备必须支持五地区且保持可审计

- racecard prepare 只访问受审 TRA host 和 registry 允许的固定路由模板。
- 每次 run 只能包含一个地区和一个官方复核 route；event ID 必须显式传入。
- 支持 `today/tomorrow`，按地区代码过滤；同一 run 最多两次 racecard 请求。
- 只归一化客观字段：赛事身份、off time、场地、等级、马号、闸位、马名、骑师、负磅、
  退赛/出走状态和来源 ID。赔率、评级、tips、评论、图片不进入公开投影。
- manifest、requests、report 继续使用 exclusive-create、SHA 绑定、`0600/0700` 和
  symlink 防护；凭据只从 worker secret 文件读取。
- initializer 继续默认 dry-run、显式 apply/verify；同 manifest replay 零新增，不同
  manifest 或任一 CAS 漂移整批失败。
- racecard 不是只在初始化时读取一次。`scheduled/racecard_ready` event 在既有有界
  赛前窗口继续刷新，同地区同日快照复用；变化形成新的不可变 racecard observation/
  revision，再以 owner generation 和 event/tracking CAS 更新 current racecard 投影。
- 当前 Free schema 已证明有 `race_status`，但 racecard runner 样本没有获准的显式
  withdrawn/non-runner 字段。实现不得因 runner 从后续列表缺失而推断退赛；缺失只能
  记录 `source_gap` 并保留上一版 declared。最终 results 中明确 `NR` 才可投影
  non-runner。若结果也缺少该 runner，则 participant completeness 失败并保持 shadow。
- off time 在同 external race ID、同当地日期、来源时间 aware 且无人工锁时可 CAS 更新；
  跨日、过大漂移、迟到旧快照或已进入 provisional 后的赛前时间改写必须阻断并人工处理。

### Requirement 3：调度不得把 event 924 专用开关直接扩成全量扫描

- Beat 仍只执行轻量 due selector；网络请求只在独立 `race_live` worker。
- 新增显式 `RACE_LIVE_ENABLED_REGIONS` 配置上限，默认空集合；空集合即使 scheduler
  为 true 也不得 claim。
- claim 前必须同时满足：地区配置获准、tracking enabled/due、live ownership、TRA
  source 已审核且条款有效、event allowlist enabled、四层 policy 非 off。
- task 开始网络前再次复核准入；配置或数据库漂移时释放/失败 checkpoint，禁止请求。
- live worker 保持并发 1、prefetch 1、独立队列、soft/hard limit，不与新闻 worker 或
  历史 runner 共用队列。

### Requirement 4：同一 TRA 地区快照必须合并复用并处理分页

- 同地区同 endpoint 的今日 results 在 provider 更新周期内只请求一次，多个 due event
  复用同一有界快照；不得每场重复拉全天数据。
- cache key 必须绑定 source、地区、当地日期、registry digest、endpoint contract
  version；TTL 小于或等于 150 秒。
- 缓存只保存受限、规范化的客观结果快照，不保存凭据、评论、评级或未用字段。
- results 使用 `limit=50`，只允许 `skip=0,50,...,450`；`total>500`、页间 total 漂移、
  重复赛事 ID、响应过大或分页不完整均 fail-closed 并告警。
- 429/403/5xx、schema drift、cache 故障和 host circuit 均不得覆盖 last-known-good
  revision；按 checkpoint/退避继续。

### Requirement 5：状态机和公开语义保持统一

固定状态机：

`scheduled -> racecard_ready -> awaiting_result -> provisional_result -> official_result -> corrected_result`

- TRA 永远是 `supplemental`，完整且身份一致的 TRA 结果只能形成 provisional。
- `provisional_public` event 不等待官方复核即可同步投影前台。
- 页面显示“暂定赛果 / 尚待官方来源复核 / 补充来源 / 更新时间”。
- 官方首次结果无论是否与 provisional 相同，都形成 official revision；内容不同时原子
  替换当前投影并保留双方证据。
- 已有 official 后的官方变化才形成 corrected revision；页面显示“赛果已更正”。
- 冲突、字段不完整或来源过期时保留 last-known-good，不以空表覆盖。

### Requirement 6：官方二次复核必须按地区路由，查漏网页不得伪装稳定 API

进入 provisional public 前，每个 event 必须绑定当前有效的地区官方复核 route：

| 地区 | 官方复核主路由 | 本期模式 | 补充来源边界 |
|---|---|---|---|
| 英国 | BHA Results | 人工浏览器 evidence receipt | Racing Post / Sporting Life 只查漏 |
| 法国 | France Galop 官方赛果/公报 | 人工浏览器 evidence receipt | PMU / Geny / Racing Post 只查漏 |
| 中国香港 | HKJC Local Results | 人工浏览器 evidence receipt | TRA 只交叉验证 |
| 日本 | JRA 或 NAR 官方赛果 | 人工浏览器 evidence receipt | netkeiba 等只查漏 |
| 美国 | 监管/赛马场官方结果或 Equibase | 人工浏览器 evidence receipt | HRN 只查漏 |

- 本期不把偶尔可访问的网页实现为稳定实时 API adapter。
- route registry 必须保存官方 URL host/path 约束、source key、地区、marker allowlist、
  manual-only、条款证据 digest、有效期和责任角色。
- 通用 manual receipt 必须按 event 的 allowlist route 选择 registry，不能由调用方把
  其他地区 source 提升为 official。
- `unavailable` 保持 provisional、打开 incident 并发送去重邮件；`match` 晋级 official；
  `conflict` 先收紧该 event public read，再保存官方 revision，禁止影响其他 event。
- event `924` 的既有 BHA receipt/审计兼容，不改写历史证据。
- manual official source 的 `terms_status=manual/automation_allowed=false` 是正确权限，
  不得为了复用 TRA resolver 把它改成自动网络获准。official/corrected 使用独立的
  `RaceLiveOfficialPublicationAuthorization` gate；它只授权已存在的人工官方
  observation/marker 公开，不授权任何网络访问。

### Requirement 7：发布策略必须逐地区、逐赛事 fail-closed

- 四层模式仍为 `global / region / source / event`，effective mode 取最小权限。
- global 只提供全站最大权限，不代表所有地区自动开放。
- 每个地区必须独立有 policy；每个赛事必须有精确 allowlist、coverage proof digest、
  official route/version/contract/terms digest 和有效期。
- 新初始化 event 默认 `shadow`。只有真实 racecard 匹配、首次 shadow result 完整、页面
  零泄漏、告警可达后，才可用通用 CAS transition 晋级该 event。
- transition/disable/restore 必须从 event `924` 专用逻辑泛化，但每次仍只操作一个
  event；不再要求 tracking/allowlist 全库只含一个 ID。
- read gate 每次按当前 policy 重算；任一 scope off 应立即隐藏该 event 的 live revision。
- provisional 继续使用 TRA source policy/allowlist/digest。official/corrected 不复用
  TRA source digest，而是同时要求：
  1. global/region/event coarse policy 达到 `official_public`；
  2. TRA event allowlist 中的官方 route/coverage proof 仍有效；
  3. 独立 official authorization 的 source/route/contract/terms/version/phase 有效；
  4. official marker evidence 与 authorization 精确一致。
- `RaceEventRevisionPublication` 必须记录本次使用
  `provisional_policy` 或 `official_authorization`、相应 authorization version、
  registry digest 和 coverage proof。任一当前 gate 漂移，读侧立即隐藏 official/
  corrected，但保留 provisional 和全部审计证据。

### Requirement 8：告警、监控和运行证据必须能区分地区

- 指标至少按地区/source 统计：due、claim、请求、cache hit、页数、200/429/403/5xx、
  schema drift、identity blocker、provisional 首见、official 延迟、stale、冲突、队列深度。
- 告警：T+15m 无 provisional、T+2h 无 official、连续三次来源失败、分页溢出、host
  circuit、identity 冲突、队列最长等待超过 3 分钟、worker 资源超限。
- 邮件沿用已验收的 QQ 邮箱 SMTP；告警必须使用 incident/event/region 组成去重 key，
  不再写死 event 924 文案。
- P50 是一半样本不超过的延迟；P95 是 95% 样本不超过的延迟。无可信 source timestamp
  时记录 `[last_empty_poll, first_seen]` 区间并使用上界，不伪造精确来源发布时间。
- 新增默认关闭的 Beat 轻量 SLA monitor，每分钟只做有界数据库查询，不访问来源。它为
  T+15 无 provisional、T+2h 无 official、连续三次失败、分页溢出、host circuit 和
  due/queue age>3m 创建持久 `RaceLiveAlertIncident`。
- alert incident 以 `alert_type + scope_type + scope_key + reference_version` 唯一去重，
  使用短事务 claim/lease；SMTP 在事务外发送，随后用 token/CAS 写 SENT/FAILED。FAILED
  按 `1m/5m/15m` 最多三次重试；并发 monitor 不得重复发送。

### Requirement 9：数据库、锁、缓存、重试和回滚

- 优先复用 `RaceEventLiveTracking`、source/participant identity、observation、revision、
  publication policy/allowlist、marker contract/evidence、incident 和 OperationLog。
- 本期明确新增 additive migration：
  1. `RaceLiveOfficialPublicationAuthorization`，为单 event 官方 source/route/phase
     提供独立公开授权；
  2. `RaceLiveAlertIncident`，提供 SLA 告警真相、去重和 delivery lease；
  3. `RaceEventRevisionPublication` 增加 authorization kind/version，区分 provisional
     policy 与 official route 审计；
  4. `RaceEventProjectionControl.last_provisional_result_revision` 专门保存最近一次已公开且
     可回退的 provisional revision；official/corrected 写入不得覆盖它。
- migration 不隐式创建任何地区/event 授权，不改变 event `924` 当前 provisional
  可见性；新行默认关闭。旧 publication 数据迁移为 `provisional_policy/version=0`，并
  仅对存在合法 published provisional 的 control 确定性回填 provisional pointer。
- 旧代码回滚前必须先 scheduler/monitor off、隐藏 official/corrected event，并把 current
  pointer、legacy result projection 和 tracking 状态在同一锁事务恢复到
  `last_provisional_result_revision`，写显式 emergency rollback OperationLog；additive
  schema 保留，不执行反向迁移抹除审计。指针缺失、跨 event、非 result/provisional、
  未 published 或 publication audit 不一致时保持隐藏并 fail-closed。恢复发生时
  global/event 维护开关继续 off；专用 rollback-target validator 验证受审 manifest 中计划
  恢复的 provisional policy，而不是错误要求当前 read gate 已经开放。
- 本次 reviewed release image 必须以 `docker image inspect` 返回的完整不可变 image ID
  `sha256:<64hex>` 保留到回滚窗口结束；如推送 registry，release artifact 另记
  repo digest，但 one-shot 执行引用一律使用本机已核验的完整 image ID。旧 app
  services 已切回旧 image 后，validator 和分层 policy restore 仍由该冻结 release image
  以 one-shot 管理命令执行；禁止用 mutable tag、宿主临时代码或手工 SQL 替代。
- one-shot 禁止加载完整生产 `.env`。发布前必须由受审脚本从生产 `.env` 严格提取
  `POSTGRES_DB/USER/PASSWORD/HOST/PORT/CONNECT_TIMEOUT/SSLMODE`，再写入固定安全启动值，
  生成权限 `0600` 的 `rollback.filtered.env` 和 SHA-256。生成器与容器入口必须双重拒绝
  `THE_RACING_API_*`、`RACE_LIVE_TRA_SECRET_ENV_FILE`、SMTP/收件人变量、真实
  `CELERY_BROKER_URL/RESULT_BACKEND` 及其他来源/通知凭据；one-shot 只使用 `memory://`
  broker、dummy email backend、disabled runner/scheduler/monitor。filtered env 的 SHA
  必须绑定 rollback manifest；缺项、重复项、禁止变量、SHA 漂移或权限不符均 fail-closed。
- 网络期间不持数据库事务；claim/checkpoint/admission/transition 使用短事务和现有
  generation/token/CAS。
- Redis 只做可丢弃快照缓存，不是审计真相；缓存清空最多导致下一次受限重抓。
- 单 event kill switch 优先；结构性故障才 global off。回滚不删除 observation/revision。

### Requirement 10：48 小时发布边界

- 必须在部署前完成本变更关键 RED/GREEN、Django check、迁移漂移检查、准实时组合测试、
  独立代码 review 和最新冻结版本授权。
- 可在上线后补跑非阻塞的全仓长回归和积累 P50/P95 样本，但不能把身份、权限、幂等、
  分页、读侧隐藏、邮件告警或回滚测试推迟到上线后。
- 部署先保持 scheduler false/地区集合空；再按真实 proof 开启地区 shadow。
- 英国现有 event `924` 保持现状。法国、日本、美国只有命中真实 racecard + shadow
  result 后才能选择精确 event public；香港在下一场自然合资格赛事前保持代码就绪但关闭。
- 若 48 小时内某地区没有合资格赛事或 TRA Free 不返回对应 racecard，交付状态必须写为
  `code_ready/source_unproven`，不能写成“该地区实时上线”。

## 验收指标

- 非目标赛事被 claim：`0`。
- 未启用地区网络请求：`0`。
- 同一地区 150 秒内 results 网络快照：最多 `1` 组分页请求。
- identity 错配、把 provisional 标为 official、跨 event policy 误改：`0`。
- observation/revision 重放 10 次，业务 revision/publication/OperationLog 仅一次变化。
- 有可信来源时间时，TRA 可用到本站 provisional：P50 `<=5m`，P95 `<=10m`。
- T+15m 无 provisional 告警投递成功；T+2h official incident 仍 open 且只告警一次。
- event disable 后首次无缓存读取不可见；其他已获准 event 不受影响。
- manual-only official source 网络权限仍为 false，但匹配 receipt 后 official 页面可见；
  后续 corrected 可见。authorization/marker/route 任一漂移时 official 隐藏，provisional
  revision 和 observation 仍保留。

## 明确不在本期

- 比赛中逐秒位置、沿途排名、直播、赔率或投注建议。
- 自动购买 Basic、历史包或 North America add-on。
- 官方网页自动 scraping；本期官方核验是可审计人工 receipt。
- 2024 年及以前历史回填或历史总账重新归属。
- 在来源证据缺失时用手工猜测 external race/runner ID。
