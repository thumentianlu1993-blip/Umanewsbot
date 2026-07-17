# 准实时赛事赛果测试用例

## 测试先行门禁

本 change 会改变模型、数据、调度、队列、权限、网络、缓存和公开页面行为，不适用 RED 豁免。方案审核通过后，必须先由测试阶段补充自动化测试并实际取得因目标能力尚未实现产生的 RED；不得通过写错误 fixture、断网或破坏既有行为伪造 RED。

RED 证据至少记录：测试文件/测试名、命令、目标行为、失败断言、失败原因、时间和工作树 fingerprint。实现 subagent 只接收已审核的测试与 RED 清单。

## Application RED 清单

### 状态机

- scheduled 只可到 racecard_ready，racecard_ready 可到 awaiting_result；非法跳转或倒退被拒绝并无写入。
- 单一非官方完整结果只能生成 provisional，不能把 `result_confirmed_at` 写成官方确认。
- 官方结果可从 awaiting/provisional 推进 official；官方后续不同 revision 推进 corrected。
- 空响应、字段减少、未知 phase、过期 observation 不得清空当前结果或推进状态。
- 延期/取消会停止普通轮询并保留 tracking reason；恢复必须显式重新计划。

### 身份与选择

- 2025+ 英法美 G1-G3、香港 G1-G3、日本 G1-G3/JpnⅠ-Ⅲ/J-G1-3 且位于正式总账/allowlist 的赛事被选择；2024-、范围外等级、未批准白名单不被选择。
- 没有有效 deferred artifact 时，日本 J-G1-3 全部进入原始目标池和 selector；“能力待验证”、普通 allowlist 缺失或未批准草稿不能排除。
- J-G proof 覆盖首个可观测日起 90 天内全部合资格赛事，最低 3 场并覆盖窗口内实际举办的每个等级；不足时延长但最多 180 天，仍不足精确记录 `availability_gap`，不算通过。
- 第 30 天无获准来源只记录 checkpoint，不能提前结束 proof；满 90 天仍无获准自动化来源、180 天样本不足，或至少观察 90 天且满足最低样本后 identity 100%/结果完整度 99%/分类零错误/字段状态/延迟任一门槛失败，分别产生可审计 deferred 候选原因。
- deferred artifact 缺用户批准、SHA 不符、过期、event/grade 越界或缺 review_due_at 时 fail closed 为“继续 active”，不能排除；有效 artifact 只排除精确清单，过期后恢复选择。
- 所有验收输出 original/active/deferred 数及逐赛事/等级缺口；deferred 非零时断言报告不能宣称“日本完整范围完成”，G1-3/JpnⅠ-Ⅲ 可继续推进。
- 同名但日期/场地/距离/场次号冲突进入 identity review，网络 task 不运行。
- source external ID 不能绑定两场赛事；绑定漂移 fail closed。
- due selector batch cap、`skip_locked`、重复 Beat tick 不产生重复并发业务写入。
- 历史任务未提交完整安全交接 manifest 时，任何真实网络 proof/contract/shadow、live worker 启动、tracking 初始化或业务写入都在动作前 fail closed。
- 交接 manifest 漏掉重叠 event ID、2025+ 所有权、lease/checkpoint、共享 host 或资源窗口时不能接管；仅 manifest 精确列出的赛事可转为 live owner。

### participant 与 racecard revision

- source runner ID、已审核 HorseProfile/Term、规范名+国家/出生年按固定顺序匹配；马号、档位和骑师不能单独作为稳定身份。
- 同名马、空马号、马号/档位变化、骑师更换和 external runner ID 漂移均不会猜错 participant；歧义进入 review。
- late scratching、withdrawn、reinstated 和 non-runner 各自生成不可变 racecard revision，旧出马表可追溯。
- `declared/running/scratched/withdrawn/reinstated/non_runner/unknown` 与 result 的 `finished/dead_heat/disqualified/did_not_finish/pulled_up/unseated_rider/fell/refused/non_runner/unknown` 全部可往返；未知 raw 状态被保留。

### observation/revision 幂等

- 相同 observation 重放 10 次只有一条去重 observation、一个 canonical revision 和一次投影变更。
- 不同来源相同 canonical 内容只补 supporting evidence，不制造页面 revision 抖动。
- provisional 与 official 内容相同仍产生状态 revision，但赛果投影内容哈希保持稳定。
- official 与 provisional 不同产生 superseding revision，旧 revision/observation 可追溯。
- transaction 中任一 result item 失败时 observation 可保留为失败证据，但 canonical/current projection 全部回滚。
- `(event, kind, revision_no)`、内容幂等、item participant/internal order 唯一约束生效；同着 official position 允许重复。
- supersedes/current/last-known-good 跨 event、跨 kind、指向自身或未来 revision 被 deferred constraint trigger 拒绝。
- 两 worker 并发分配 revision number 不重复；serialization/deadlock 只做有界重试。
- last-known-good rollback 原子切换 pointer 并恢复完整投影，revision/observation 审计链不删除。

### 赛果边界

- 同着允许多个相同 official finish position，同时内部投影顺序稳定。
- DQ、DNF、PU、UR、NR/scratched 等不被丢弃或伪造成普通名次。
- 官方不提供马号时允许空值，但 identity 使用 approved fallback；非空马号仍不可重复。
- 人工锁 runner/result 字段不被低等级来源覆盖；官方冲突进入 review 或显式人工批准。
- 退赛更新不删除历史 observation，当前出马表准确显示退出状态。

### 来源优先级和冲突

- A 级官方来源可确认/纠正 B/C 来源；C 来源不能覆盖 A 级 official。
- The Racing API 完整结果在 `provisional_public` 下无需等待官方 observation 即可立即物化公开投影；测试必须断言页面仍标“暂定赛果”、`result_confirmed_at` 为空且未出现“官方/已确认”。
- 同一 TRA 暂定结果随后被官方相同结果复核时，只生成 official 状态 revision；官方不同结果到达时原子 supersede 暂定 revision、保留双方 observation，并立即显示官方结果。
- TRA 缺马、身份歧义、空结果、未知关键状态或人工锁冲突时不能因“商业 API 可信”绕过字段/身份门禁，也不能清空 last-known-good。
- 两个 B/C 来源一致提高 provisional confidence，但仍不能标 official。
- 两个来源部分一致、关键名次冲突时冻结上一公开 revision 并创建 conflict。
- parser version 变化导致 normalized 内容变化时必须形成可审计 diff，不静默替换。

### 投影写入所有权

- historical importer、`apply_data_candidate()`、后台人工和 live redelivery 同时写同一赛事时，只有当前 owner generation 的一个 apply 成功。
- live-owned 赛事拒绝历史 importer/candidate/admin 直接覆盖；人工改动只能形成 observation/revision。
- 非 live-owned 赛事保持既有历史导入结果；精确 ownership transfer manifest 幂等切换 owner，旧 generation 的在途响应不能 apply。
- 后续历史修复必须先暂停 live、转交 owner，修复后再显式交回；任何一步失败保持 last-known-good projection。
- latest main 的 chunk importer 在同一事务内完成 candidate、revision、物化投影和 receipt COMPLETED；任一 revision/owner/receipt 写入失败整批回滚。
- receipt completion payload/verifier 同时绑定 owner generation、racecard/result revision ID、content hash、candidate provenance 和当前物化计数；篡改 pointer、revision 或 generation 时 replay verification 失败。
- STARTED/ABANDONED receipt、尚未执行的批准 chunk、2026 current_year_due 或 new formal event 未完成 handoff 时，live owner transfer fail closed；精确终态 handoff 后才可接管。

### Publication admission

- adapter/runner 不再接受 `project_current`；只有 `admit_race_live_publication()` 可创建 published revision、物化准实时公开投影或 promotion audit。
- global/region/source/event 任一 off、条款过期、registry/coverage digest drift、地区 proof 不覆盖、非 event allowlist、official route 缺失/过期均在 publication transaction 内拒绝；shadow observation/revision 可保留但公开投影不变。
- admission 检查后并发修改 policy/allowlist/registry/coverage version 时 CAS 失败；旧检查不能公开。重放经新版本重新 admission，幂等 audit 只有一次。
- `the_racing_api` source identity 在 Django 模型、PostgreSQL constraint 和 apply service 三层都不能保存/使用 official authority；字符串伪造、管理员初始化和错误 manifest 均 fail closed，authority decision/audit 绑定 registry digest。
- expected participant 集合从获准 racecard revision/manifest 读取；覆盖空结果、缺一马、额外马、pending/conflict identity、scratched/withdrawn/non-runner、已知 DNF/DQ、并发新增人工锁。删除 `identity_valid/payload_complete/manual_lock_conflict` 任一调用方自报授权后测试仍能捕获错误。

### 页面与缓存

- provisional/official/corrected badge、来源类别和更新时间文案准确。
- `provisional_public` 页面发布时间不得依赖官方复核任务完成；官方复核超时只产生赛事级告警，不撤下已明确标注且仍通过完整性门禁的暂定赛果。
- 暂定页面不出现“官方/已确认”；改判后只显示最新名次并显示更正提示。
- shadow mode 永不改变公开页面和当前投影。
- 发布 mode 仅接受 `off/shadow/provisional_public/official_public`，effective mode 取 global/region/source/event/terms 所有适用 cap 的最小值；缺失 global、未知/冲突/过期配置按 off 处理。
- `global=off + event=official_public`、`region=off + event=official_public`、`source=off + event=official_public` 均断言 effective off，且不发网络任务、不写公开投影；下层配置永远不能提升上层 cap。
- region/source/event 缺失时只继承当前上限；event allowlist 可进一步拒绝，但不能把 shadow 提升到 provisional 或 official。
- 未 published 的 RaceEvent 继续 404/不进入日历；live tracking 不绕过 visibility。
- revision apply 后事件 cache 失效；Redis 故障不阻止正确 DB 页面，也不错误晋级。
- 页面不输出 raw payload、评论、评级、tips、图片/视频或 secret。
- 公开读取门默认 off；已经有 `published_at` 的 revision 在 global/region/source/event 任一 off 后，详情、结果列表和相关 cache 均立即隐藏。重新开启只恢复当前获准 revision，cache key/version 和事务后失效可重复。

## Integration RED 清单

### Adapter contract

每个地区 adapter 使用保存的 fixtures 覆盖：

- racecard、late scratching、provisional、official、corrected。
- 完整/缺字段、结构变化、错误 content type、超大响应、timeout、429/Retry-After、403、404、5xx。
- 时区/DST、午夜跨日、延期、取消、同名多场、同着、DQ/DNF。
- response SHA、normalized SHA、parser version 和 source timestamps 可重复。

真实网络不作为普通单元测试依赖；网络 contract test 只有历史安全交接完成、显式 flag/secret、批准 manifest 和有效 `proof_network_allowed` 证据同时存在才运行，并受 request budget/host limit 约束。fixture 必须记录取得时间、来源、SHA、保存许可和脱敏方式；没有保存许可时只保存手工构造的最小事实 fixture。

### The Racing API

- Free endpoints 的 Basic Auth 不出现在日志、artifact、异常和测试 snapshot。
- regions/course/race ID mapping 稳定；today/tomorrow/date 边界按 API UTC 与赛事 timezone 正确处理。
- Free 1 req/s 客户端上限被强制，429 读取 Retry-After 并有界退避。
- 当天 results 批量响应只请求一次并分发给多赛事，不按 event 重复请求。
- 不把 API 返回的 comments/ratings/tips 写入 normalized payload 或页面。
- Core 美国/日本缺失目标时记录 coverage gap，不伪造空赛果或自动升级计划。

### 官方/网页来源

- 所有自动真实联网模式都执行条款门禁：生产/正式 shadow 要求 `terms_status=approved + automation_allowed=true`；一次性 proof 要求显式 `proof_network_allowed=true`、有效期、证据 SHA、registry digest 和批准预算。
- unknown/expired/digest drift/manual/blocked 在 proof、shadow 和 production 均于首个请求前 fail closed；offline fixture 测试不伪装成联网验证。
- Sporting Life、Racing Post、HRN 等当前 blocked/manual 来源在生产模式 fail closed。
- redirect 到未批准 host、登录页、captcha、robots/403 被识别为 non-retryable 或人工 review，不绕过。
- NAR CSV ZIP/CSV 解压有 zip-slip、大小、编码、schema 和 SHA 校验；2 分钟文档频率不写成保证。
- HKJC/JRA/France Galop/BHA/Equibase 的 official marker 使用 fixture 明确验证，不能仅以页面有结果表推断正式。
- official/corrected marker 必须匹配持久 contract digest、marker type、parser version 和不可变 evidence SHA；裸布尔、TRA marker、未知/过期 contract 均不能确认 official。
- 首次官方结果与 TRA 暂定不同仍进入 official；只有 existing official 后的官方变化进入 corrected。correction source/event gate 默认 off 时保留 evidence/conflict 但不自动公开 corrected。

### 官方异步复核 incident

- provisional 发布时幂等创建 event + provisional revision + route version incident；deadline 为最新有效 off time +2h。
- 延期更新 off time 后 deadline 重算并留 audit；fake clock 到 T+2h 只开一次告警，重复轮询不重复开单。
- 官方一致关闭 incident，官方不同升级并应用 official revision；持续 provisional 保持 incident open，并在 T+24h/T+72h/T+7d 继续修订探针。
- route 在灰度前不可执行时 event 不得进入 allowlist；发布后 route 过期/失败不撤下已标 provisional，但触发同一 incident。

### Celery/资源隔离

- Beat selector 只入 `race_live` queue；新闻 worker route 不消费 live task，live worker 不消费新闻/QQ/翻译 task。
- live worker concurrency/time limits/resource config 生效；慢 host 不占满 web/新闻 worker。
- 历史 runner lease、文件锁、checkpoint、runtime artifact 和数据库控制表在 live task 前后完全不变。
- Redis 暂停、worker crash、task redelivery、部署重启后从 DB checkpoint 恢复且不重复 revision。
- host 限速跨两个 worker/进程仍共享；竞态最多一个实际请求/一个 canonical apply。
- claim 在短事务中领取后提交，网络阶段断言没有 active DB transaction、row lock 或 advisory lock；claim 超时可由新 generation 恢复。
- 网络返回后的 CAS 同时校验 attempt token、claim generation、owner generation 和旧 current pointer；旧响应只保存 observation，不生成 current revision。

### 数据库与迁移

- migration 从当前 latest main 正向应用，`makemigrations --check --dry-run` 无漂移。
- migration 后所有既有 RaceEvent 默认为 live off，既有 runners/results/public pages 不变。
- migration 后既有 HistoricalRaceDetailImportReceipt 内容与终态不变；新增 revision 身份只对迁移后的新 apply 记录，旧 receipt 不伪造历史 revision，并由兼容 verifier 明确 legacy 状态。
- 初始化 tracking 只有 dry-run manifest + 精确 SHA + commit 才写，幂等复跑 0 变化。
- PostgreSQL 下验证 select-for-update/skip-locked、unique constraints、事务回滚和并发 revision number。
- PostgreSQL 下验证 deferred triggers、current/last-known-good 同 event/kind 约束和 ownership generation CAS；SQLite 只验证可表达的纯逻辑，不代替这些结果。
- 当前 SQLite stable tests、目标 PostgreSQL tests 和生产形态 dry-run 必须分层报告，不能混写为一个“通过”。
- 当前迁移基线明确为 `0033-0041`；后续 publication/authority/marker/incident migrations 从 latest main 向前应用。验证 `0041` choices、后续迁移正向/往返和 PostgreSQL constraints；一旦存在 live audit 数据，回滚只向前修复或恢复备份，不反向删除审计表。

## 性能、延迟与故障验收

- 10/50/200 个 due target 压测 selector 查询数、时间和索引；Beat tick 不做网络。
- 单 host 多赛事证明 batch/cache 去重，实际请求数符合公式而非赛事数线性增长。
- 注入 30 秒慢源、连续 429、5xx、DNS/timeout，验证 worker time limit、circuit breaker、队列深度和恢复。
- web 赛事日历/详情 p95 与基线比较；shadow worker 运行时新闻抓取/翻译/QQ 队列无可归因延迟增长。
- 有可信 source timestamp 时验证精确三段延迟；人工观察标记为 `manual_external_observation`，不得混作机器时间。
- 无可信时间时记录 `[previous_successful_poll_at, first_seen_at]` 区间删失，并以保守上界做采购/灰度判定；不得把 first_seen 当精确 source available。
- 429/5xx/timeout 覆盖的失败区间单列 `polling_failure_delay`，不混入来源主 SLO；`first_seen_at -> public_applied_at` 仍单独验收。
- 每地区至少 10 个真实窗口，至少 3 个正式重点赛事；没有实际改判样本时 corrected 只可完成 fixture/历史 replay 验证，自动 correction public gate 保持关闭。

## 安全与合规测试

- secret redaction、allowlisted HTTPS host、redirect、DNS rebinding/私网 IP、response size、content type、压缩炸弹。
- 条款/许可过期或 source registry digest 变化时生产 adapter 自动阻断并告警。
- proof/shadow 也验证相同的到期和 digest drift fail-closed 语义，禁止用模式名称绕过许可。
- raw cache retention 到期删除内容但保留 SHA/元数据；legal hold 可显式延长。
- 公开模板 snapshot 证明只包含客观字段，不复制第三方评论、评级和版权段落。
- 管理员 manual correction 需要权限、理由、官方证据 URL、双确认（正式灰度后）和 OperationLog。

## 回归范围

- 现有赛事模型/页面/候选导入/历史 importer tests。
- `stable.test_race_event_crawl_orchestration`、历史 batches/pipeline/runner 相关测试。
- Celery routing、news crawling、translation、QQ 和 health checks。
- 全量 `stable` 回归；长任务必须等待显式终态，不以超时窗口推断通过。

## RED 完成条件

- 所有新增/变更行为在实现前有对应自动化测试。
- 关键 RED 至少覆盖状态晋级、participant/racecard revision、幂等/约束/回滚、官方纠正、共享投影所有权、两阶段 claim/CAS、页面标识、全联网模式 source terms gate、mode precedence、区间延迟、queue 隔离和历史 runner 不受影响。
- 失败明确来自缺失目标能力；现有 unrelated failure 必须单独记录，不能充当 RED。
- RED artifacts 经方案 reviewer 通过后的 `test_cases.md` 对齐，再交实现 subagent。

## RED 执行证据

### 2026-07-16 第一批：发布 mode 单调合并

- 测试：`stable.test_realtime_race_results.RaceLiveModeResolutionTests`，4 tests。
- 命令：本地 `umanewsbot:main-8dd935e3-amd64-20260716` 镜像，挂载当前源码，`--network none`、SQLite、Celery eager；执行 `python server/manage.py test stable.test_realtime_race_results.RaceLiveModeResolutionTests --noinput`。
- 结果：退出码 `1`，`4 tests / 6 failures`；Django system check 为 0 issues。
- 目标失败：`stable.services.race_events.resolve_race_live_mode` 尚未实现，断言“准实时发布 mode resolver 尚未实现”失败；不是导入错误、fixture 错误、网络或环境失败。
- mutation：删除任一层 cap、允许 event 提升 global/region/source、把 unknown 当继承、忽略 event allowlist，都会被后续行为断言捕获；删除 resolver 会回到本次 RED。
- 首次代码 review finding RED：追加 `terms_mode=None` 必须返回 `off`；用于捕获“许可状态缺失被当作继承”的提权回归。
- finding RED 结果：退出码 `1`，`5 tests / 1 failure`；实际 `official_public != off`，其余 4 项保持 GREEN。
- ProjectionControl 完整 review finding RED：追加 event allowlist 必须为显式布尔 `True`；省略、`None`、字符串和数值均 fail closed。定向测试退出码 `1`，省略参数时实际 `official_public != off`；测试还会捕获仅改默认值但继续使用 truthiness 的不完整修复。
- finding GREEN：`event_allowed` 默认改为 `False` 且只接受 `is True`；定向 `1/1`、mode class `6/6`、完整准实时模块 `16/16`。合并完整历史 chunk/receipt 和 3 项相邻赛事回归后共 `42/42`；再快进历史 importer 主线并加入完整历史 import primitive 回归后 `49/49`，check 与 migration drift 继续通过。

### 六态状态机纯函数（2026-07-16）

- 测试：`stable.test_realtime_race_results.RaceLiveStateTransitionTests`，覆盖设计表中 7 条合法边（含 `awaiting_result -> official_result` 和 `corrected_result -> corrected_result`），以及跳级、倒退、未知状态和未批准自循环。
- 命令：本地 `umanewsbot:main-8dd935e3-amd64-20260716` 镜像，挂载当前源码，`--network none`、SQLite、Celery eager；执行 `python server/manage.py test stable.test_realtime_race_results.RaceLiveStateTransitionTests --noinput`。
- RED 结果：退出码 `1`，Django system check `0 issues`；2 个测试方法的 14 个 subtest 失败，失败断言均为“准实时赛事状态转移纯函数尚未实现”。
- 归因：目标函数 `is_race_live_state_transition_allowed` 尚不存在；没有网络、fixture 或既有行为失败，属于目标能力缺失产生的真实 RED。
- GREEN 结果：实现显式 7 边白名单后，完整准实时模块 7 项测试与 3 项相邻赛事回归共 `10/10` 通过，Django system check `0 issues`；命令仍使用 `--network none`、SQLite 和 Celery eager。
- 当前边界：本切片只验证纯状态拓扑，尚未接入 revision、来源权限、持久化写入或 ProjectionControl；这些行为继续按各自 RED 切片推进。
- finding GREEN：`terms_mode` 现在必须显式为合法 cap；目标 `5/5` 通过。主会话随后合并运行目标 5 项和相邻 candidate/dynamic-field 回归 3 项，共 `8/8` 通过；仍使用 `--network none`、SQLite 和 Celery eager。

### Canonical 内容哈希（2026-07-16）

- 测试：`stable.test_realtime_race_results.RaceLiveCanonicalHashTests`，固定 mapping key 顺序无关、赛果数组顺序/事实变化敏感、输出为 64 位小写 SHA-256，并拒绝非 object、非字符串 key、NaN 和非 JSON 值。
- 命令：本地 `umanewsbot:main-8dd935e3-amd64-20260716` 镜像，挂载当前源码，`--network none`、SQLite、Celery eager；执行 `python server/manage.py test stable.test_realtime_race_results.RaceLiveCanonicalHashTests --noinput`。
- RED 结果：退出码 `1`，Django system check `0 issues`；3 个测试方法的 6 个失败样例均断言“准实时赛果 canonical hash 纯函数尚未实现”。
- 归因：目标函数 `build_race_live_canonical_sha256` 尚不存在；没有网络、fixture 或既有行为失败，属于目标能力缺失产生的真实 RED。
- GREEN 结果：严格 JSON 验证与确定性 SHA-256 实现后，完整准实时模块 10 项测试与 3 项相邻赛事回归共 `13/13` 通过，Django system check `0 issues`；仍使用 `--network none`、SQLite 和 Celery eager。
- 当前边界：hash 尚未接入 revision/CAS 持久化；Python 数字 JSON 表示之外的跨语言 canonicalization 不在本切片范围。
- 第三轮代码 review finding RED：追加业务等价数字 `1 == 1.0`、`0.0 == -0.0` 必须同 hash，以及 provisional/official phase 元数据不得进入内容 hash。目标测试退出码 `1`，5 个测试中 1 failure（等价数字 hash 不同）和 1 error（函数尚不接受独立 `result_phase` 元数据）；其余 3 项保持 GREEN。
- finding 修复直接回归：数值归一化后上述 5 项 GREEN；主会话进一步按已批准设计扩展 phase 为 `racecard/provisional/official/corrected/unknown`，取得 `racecard/unknown` 被错误拒绝的 2 个 subtest RED，补齐枚举后 GREEN，非法 phase 继续拒绝且所有合法 phase 均不改变内容 hash。
- finding 修复后合并结果：完整准实时模块 12 项与 3 项相邻赛事回归共 `15/15` 通过，Django system check `0 issues`，仍为 `--network none`、SQLite、Celery eager。

### ProjectionControl 基础所有权行（2026-07-16）

- 测试：`stable.test_realtime_race_results.RaceEventProjectionControlModelTests`，覆盖既有赛事不隐式创建 control、显式 control 默认 `unmanaged`/generation 0/revision counters 1、一场一行，以及非法 owner 的数据库约束。
- 命令：本地 `umanewsbot:main-8dd935e3-amd64-20260716` 镜像，挂载当前源码，`--network none`、SQLite、Celery eager；执行 `python server/manage.py test stable.test_realtime_race_results.RaceEventProjectionControlModelTests --noinput`。
- RED 结果：退出码 `1`，Django system check `0 issues`；3 项测试均在既有 `RaceEvent` 成功创建后，仅因 `RaceEventProjectionControl` 模型不存在而失败。
- mutation：自动创建 control、默认 owner 非 unmanaged、counter 从 0 开始、移除 event 唯一性或 owner check constraint，分别会被本组断言捕获。
- 当前边界：本切片只增加显式基础仲裁行；revision pointers、owner transfer/CAS、receipt/importer 接入和 tracking 初始化均不在本次 GREEN 范围。
- GREEN 结果：新增基础模型与前向 `0033` migration 后目标 `3/3`；主会话合并运行完整准实时模块、3 项相邻赛事回归和历史 chunk/receipt/import primitive 测试，最终 latest-main 上 `49/49` 通过。Django system check `0 issues`，`makemigrations --check --dry-run` 为 `No changes detected`。
- 验证分层：上述结果来自 `--network none` 的 SQLite 测试数据库；尚未宣称 PostgreSQL owner transfer/CAS、deferred trigger 或生产 migration 已验证。
- 最终纯文档 review 后续 RED：新增两个 revision counter 必须在数据库层 `>=1`；定向测试退出码 `1`，`next_racecard_revision_no=0` 和 `next_result_revision_no=0` 两个 subtest 均未触发预期 `IntegrityError`，证明 `PositiveBigIntegerField` 自身不足以阻止 revision 0。
- counter GREEN：模型与未发布 `0033` 分别增加 racecard/result `>=1` check constraint；定向 `1/1`、ProjectionControl class `4/4`、完整准实时模块 `17/17`。latest-main 组合历史/相邻回归共 `50/50`，Django check 与 migration drift 继续通过。

### LiveTracking 基础 checkpoint 行（2026-07-16）

- 测试：`stable.test_realtime_race_results.RaceEventLiveTrackingModelTests`，覆盖既有赛事不隐式启用 tracking、显式行默认 `scheduled + tracking_enabled=false`、claim/checkpoint fail-closed 默认、一场一行及非法状态数据库约束。
- RED：断网 SQLite 定向测试退出码 `1`，Django system check `0 issues`；3 项均在 `RaceEvent` 正常创建后仅因 `RaceEventLiveTracking` 模型不存在而失败。
- mutation：自动创建 tracking、默认 enabled、默认 state 非 scheduled、claim generation/token 非空、移除 event 唯一性或 state check constraint 均会被捕获。
- 当前边界：本切片只建立调度/checkpoint 数据骨架，不启用 Beat、selector、claim 服务、网络任务或 tracking 初始化。

### ProjectionControl owner transfer（2026-07-16）

- 测试：`stable.test_realtime_race_results.RaceEventProjectionOwnerTransferTests`，覆盖 expected owner/generation、64位 manifest、原子 owner/generation 更新、相同 manifest 重放幂等、过期/不同 manifest 冲突，以及缺 control/非法输入不隐式建行。
- RED：断网 SQLite 定向测试退出码 `1`，Django system check `0 issues`；4 项均仅因 `transfer_race_event_projection_owner` 尚未实现而失败。
- mutation：去掉行锁、忽略 expected generation、重放再次递增、允许不同 manifest 覆盖、缺行自动创建或弱化 SHA 校验均会被捕获；SQLite 不证明真实并发锁，PostgreSQL 并发测试另行补足。

### Source/participant identity 数据骨架（2026-07-16）

- 测试：`stable.test_realtime_race_results.RaceLiveIdentityModelTests`，覆盖 source identity 的条款/自动化 fail-closed 默认、两组赛事来源唯一约束、审核状态约束、participant stable key，以及非空 external runner ID 在 source race 内唯一。
- RED：断网 SQLite 定向测试退出码 `1`，Django system check `0 issues`；4 项分别仅因 `RaceResultSourceIdentity`、`RaceEventParticipant` 等目标模型不存在而失败。
- mutation：默认许可 approved/automation true、移除 source/event/stable key 唯一性、把空 runner ID 也全局唯一或允许非空 runner ID 重复均会被捕获。

### Observation/revision append-only 骨架（2026-07-16）

- 测试：`stable.test_realtime_race_results.RaceLiveRevisionModelTests`，覆盖 observation 的 source/hash/phase 去重、revision number 与 phase/content 去重、kind/phase/revision_no fail-closed、item participant/internal order 唯一、同着 official position 可重复，以及 supporting evidence link 唯一。
- RED：断网 SQLite 定向测试退出码 `1`，Django system check `0 issues`；5 项仅因 `RaceResultObservation`、`RaceEventRevision`、item/evidence 模型尚未实现而失败。
- mutation：把 phase 从 observation/revision 幂等键移除、允许 revision 0、去掉 item 两个唯一约束、错误限制同着名次或允许重复 evidence link 均会被捕获。
- 当前边界：本切片不增加 current/last-known-good pointers、跨 event/kind deferred trigger、allocator 或物化投影 apply。

### Revision pointer 与编号分配（2026-07-16）

- 测试：`stable.test_realtime_race_results.RaceEventRevisionAllocatorTests`，覆盖 ProjectionControl 四个 nullable pointer、racecard/result 独立 counter、owner generation 门禁、同 phase/content 重放幂等，以及 primary observation 同赛事/phase 校验。
- RED：断网 SQLite 定向测试退出码 `1`，Django system check `0 issues`；pointer 缺失且 `allocate_race_event_revision` 尚未实现，5 项共 7 个失败断言。
- mutation：共用 counter、重放再次递增、忽略 owner generation、允许跨赛事/错 phase observation、隐式推进 current pointer 均会被本组或后续 apply 测试捕获；真实并发分配留 PostgreSQL 测试。

### Source network permission fail-closed resolver（2026-07-16）

- 测试：`stable.test_realtime_race_results.RaceSourceNetworkPermissionTests`，覆盖 offline fixture、proof 的独立许可/manifest/预算/handoff、shadow/production automation 许可，以及所有网络模式的条款、有效期、证据 SHA、registry digest 和时间输入。
- RED：修正测试类边界后，断网 `SimpleTestCase` 定向执行退出码 `1`，Django system check `0 issues`；5 项共 29 个 subtest 仅因 `resolve_race_source_network_permission` 尚未实现而失败。
- mutation：把 offline 误挡、把 proof flag 当 automation、遗漏 handoff、允许 bool 预算、忽略过期/digest drift/manual/blocked 或 naive datetime 均会被捕获。

### 调度、host 限速与两阶段 checkpoint（2026-07-16）

- `RaceLiveHostBudgetModelTests` RED 为 `3/3` 仅缺模型；新增 `0038` 后 GREEN，覆盖 host 唯一/非空、最小间隔 `>=1`、共享 next-allowed、失败计数、circuit 和 lock version 默认。
- `RaceLivePollingScheduleTests` RED 为 5 个方法、11 个断言仅缺函数；GREEN 固定 T-24h/T-2h/T-30m/开跑后/暂定后窗口和 T+24h/T+72h/T+7d 锚定探针，naive/未知/纠正终态停止。
- `RaceEventLiveClaimTests` RED 为 4 个方法、6 个断言仅缺服务；GREEN 覆盖 owner generation、到期、短 TTL、未过期阻止、过期回收、token/generation/lock version 和不隐式建行。
- `RaceLiveHostReservationTests` RED 为 `4/4` 仅缺服务；GREEN 覆盖 DB 行锁预约、毫秒最小间隔、circuit 优先、rate limit、缺预算及非法输入 fail closed。
- `RaceEventLiveCheckpointTests` RED 为 4 个方法、10 个断言仅缺服务；GREEN 覆盖 owner/claim 双 CAS、成功/失败 checkpoint、claim 释放、旧响应零 mutation、strict digest/JSON/aware datetime。
- 首次统一 review P1 RED：claim expiry 恰好等于 completion `now` 时旧响应实际返回 `applied=True`；补边界测试后 `<= now` 返回 `claim_expired` 且零 mutation。限定复审进一步要求缺失 expiry 的独立覆盖；新增测试先取得实际 `claim_expired != claim_missing_expiry` 的 RED，再拆分为缺失 lease 返回 `claim_missing_expiry`。两条路径均保持 checkpoint/claim 零 mutation，修复后准实时 `65/65`、latest-main 组合 `105/105`。
- SQLite 不能替代 PostgreSQL 行锁/并发验证，且本批尚未接 Beat、真实 worker、HTTP 或生产。

### Batch due-selector（2026-07-16）

- 测试：`RaceEventLiveDueSelectorTests`，覆盖只领取 due + enabled + live-owned 行、按 `next_poll_at/event_id` 稳定顺序、batch cap、活跃 claim 不重复派发、过期 claim 回收，以及非法时间/批次/TTL 零 mutation。
- RED：SQLite/Celery eager 定向执行退出码 `1`，3 个测试方法共 8 个失败断言，均只因 `claim_due_race_event_live_tracking` 尚未实现；Django system check 0 issues。
- mutation：去掉 live owner 过滤、batch cap、active-claim 排除、过期回收、稳定排序、claim generation/token/TTL 更新或非法输入门禁均会被捕获；SQLite 不证明 `skip_locked` 并发语义，留 PostgreSQL 集成层验证。

### Host outcome 与 circuit（2026-07-16）

- 测试：`RaceLiveHostOutcomeTests`，覆盖连续失败计数、精确 threshold 打开 circuit、成功恢复、error code、lock version，以及缺预算/非法 host、时间、状态、threshold、circuit seconds 零 mutation。
- RED：SQLite/Celery eager 定向执行退出码 `1`，3 个测试方法共 10 个失败断言，仅因 `record_race_live_host_outcome` 尚未实现；Django system check 0 issues。
- mutation：不加锁、off-by-one threshold、成功不清 circuit、失败丢 error code、非法 success truthiness、缺预算自建或拒绝路径改写 lock version 均会被捕获；真实并发序列留 PostgreSQL 验证。

### Celery selector 与队列隔离（2026-07-16）

- 测试：`RaceLiveCeleryIsolationTests`，覆盖 scheduler 默认关闭、每分钟 Beat selector、poll task 固定 `race_live` queue、关闭时不 claim/dispatch、开启时传递 owner/claim generation 与 token，并在 commit 后派发。
- RED：SQLite/Celery eager 定向执行退出码 `1`，3 项均因 `RACE_LIVE_SCHEDULER_ENABLED`、selector/task import 或 route 尚不存在而失败；Django system check 0 issues。测试中的 crontab minute 断言已先校正为 Celery 展开的 `0..59`，环境行为不充当 RED。
- mutation：默认开启、漏独立 route、Beat 非每分钟、关闭仍领取、直接同步执行 poll、丢失任一 CAS 字段或在 transaction commit 前派发均会被捕获；独立 worker 容器和真实 broker 隔离另走 compose/PostgreSQL 集成层。

### The Racing API Free 离线 fixture contract（2026-07-16）

- 依据当前官方公开文档，仅固定 Free `/v1/racecards/free` 与 `/v1/results/today/free` 的最小客观字段；不请求 API、不保存凭据或真实响应。TRA 非官方，因此 results fixture 只归一化为 `provisional`。
- 测试：`TheRacingApiOfflineFixtureContractTests`，覆盖 metadata/schema version、合成或获许可 acquisition、redistribution、aware created time、canonical payload SHA、endpoint 白名单、race/runner identity、客观字段 allowlist、名次数值和空 results 防覆盖。
- RED：SimpleTestCase 定向执行退出码 `1`，4 个方法共 13 个失败断言，全部因 `stable.services.race_live_fixtures` 尚不存在；Django system check 0 issues，无网络或 fixture 环境错误。
- mutation：允许 Basic/未知 endpoint、digest drift、未授权保存、naive 时间、缺 race/runner ID、空 results、把 TRA 提升 official、复制 form/评级字段或把数字名次丢成 unknown 均会被捕获。

### Append-only observation recorder（2026-07-16）

- 测试：`RaceResultObservationRecorderTests`，覆盖从 normalized payload 计算 canonical SHA、创建 observation、同 source/hash/phase 精确重放幂等且不覆盖首份证据、同 payload 不同 phase 独立，以及来源/时间/parser/raw SHA/phase/payload/provenance/warnings/permission 非法时零写入。
- RED：SQLite/Celery eager 定向执行退出码 `1`，4 个测试方法共 13 个失败断言，仅因 `record_race_result_observation` 尚未实现；Django system check 0 issues。

### 并发控制复审 finding RED（异常 claim lease / host reservation CAS）

- `RaceEventLiveClaimTests.test_nonempty_token_without_expiry_is_corrupt_and_not_reclaimed`：非空 attempt token 但缺失 expiry 必须视为损坏租约并 fail closed，单事件 claim 不得回收或改写。
- `RaceEventLiveDueSelectorTests.test_selector_excludes_nonempty_token_without_expiry`：批量 due selector 必须排除同类损坏租约，避免第二个 worker 重复领取。
- `RaceLiveHostReservationTests`：成功预约必须返回本次 `reservation_version`。
- `RaceLiveHostOutcomeTests.test_stale_success_cannot_clear_newer_failures_or_open_circuit`：outcome 必须以预约版本做 CAS；旧请求迟到的 success 不得清除较新的失败计数或 circuit。
- RED：上述 4 项定向执行退出码 `1`，Django system check 0 issues；结果为 `2 failures / 2 errors`。现状分别错误回收损坏租约、selector 错误选中损坏租约、预约 decision 缺少 `reservation_version`、outcome 不接受 `expected_reservation_version`，均直接对应 reviewer 的两个 actionable findings。
- GREEN：单事件 claim 现在对非空 token + NULL expiry 返回 `claim_missing_expiry`，batch selector 仅纳入空 token 或具有显式到期 expiry 的 lease；host reservation 返回自增后的版本，outcome 在锁行后以该版本 CAS，迟到结果返回 `stale_reservation` 且零 mutation。新增定向 `4/4`、相关并发类 `17/17`、完整准实时 `85/85` 通过；准实时与 historical detail chunk/import receipt/import primitives 组合 `122/122` 通过，Django check、migration drift 和 diff check 均通过。SQLite 结果不替代后续 PostgreSQL `select_for_update/skip_locked` 集成门禁。

### 独立 `race_live` worker 部署契约（2026-07-16）

- 测试：`RaceLiveWorkerDeploymentContractTests`，覆盖普通 worker 显式只消费 `celery`、live worker 固定只消费 `race_live`，并固定并发 1、prefetch 1、soft/hard time limit；三份 Compose 均定义独立 live worker 且 scheduler 默认关闭；`.env.example` 暴露安全默认值。
- RED：断网容器定向执行退出码 `1`，3 个测试方法得到 `4 failures / 1 error`：普通 worker 未显式限定 queue、live worker 脚本与三份 Compose service 均不存在、poll task annotation 与环境默认不存在。Django system check 0 issues，失败均来自目标隔离能力缺失。
- GREEN：普通 worker 显式只消费 `celery`，独立脚本固定只消费 `race_live`，默认并发 1、prefetch 1、soft/hard time limit 45/60 秒；开发、标准生产、低成本生产三份 Compose 均定义独立 worker 且 scheduler 默认 `false`，`.env.example` 同步安全默认。定向 `3/3`、既有 Celery 隔离 `3/3`、准实时 `88/88`、与 historical detail chunk/import receipt/import primitives 组合 `125/125` 通过；三份 Compose 精确配置解析、脚本语法/executable、Django check 和 diff check 通过。尚未启动 worker 连接真实 Redis/PostgreSQL。

### 赛果 source authority / conflict policy（2026-07-16）

- 测试：`RaceResultConflictPolicyTests`，覆盖 supplemental 只能形成 provisional、official 可确认/替换 provisional、official 变化必须显式 corrected、同 phase/hash 重放幂等、supplemental 分歧与人工锁冻结当前结果，以及 identity/完整性/marker/digest/转移非法时 fail closed。
- RED：断网 `SimpleTestCase` 定向执行退出码 `1`，5 个测试方法共 10 个失败样例，全部仅因 `decide_race_result_revision_action` 尚不存在；Django system check 0 issues。
- GREEN：纯策略实现 supplemental/official、marker、显式 corrected、replay、冲突冻结和严格输入一致性；目标 `5/5`、准实时 `93/93`、与 historical detail chunk/import receipt/import primitives 组合 `130/130` 通过。

### Observation -> result revision/current pointer CAS（2026-07-16）

- 测试：`RaceResultRevisionApplyTests`，覆盖 shadow 只写 immutable revision/items/evidence/current pointer 而不改现有公开投影；official public 原子 supersede、LKG、materialized results、确认时间和状态晋级；重放幂等；owner/claim/expiry CAS；supplemental 冲突冻结；未知 runner identity 零 revision。
- RED：断网 SQLite 定向执行退出码 `1`，目标 5 项均仅因 `apply_race_result_observation_revision` 尚不存在而失败；同批既有 checkpoint 6 项保持 GREEN，Django system check 0 issues。
- GREEN：shadow revision/pointer 与 public materialized projection 分离，revision/items/evidence/LKG/counter/tracking 在 owner+claim CAS 短事务中原子提交；目标 `5/5`、含 checkpoint `11/11`、准实时 `98/98`、与 historical detail chunk/import receipt/import primitives 组合 `135/135` 通过。

### PostgreSQL 并发门禁（2026-07-16）

- 测试：`RaceLivePostgresConcurrencyTests`，覆盖 selector 对另一调度器锁行使用 `skip_locked`、同 host 两请求串行预约、同 claim 两 worker 只能创建一个 revision。
- 首次 PostgreSQL 16 RED：3 项中 selector 与 host budget 2 项 GREEN；revision contention 因 control 查询同时 `select_related` nullable current revision，触发 PostgreSQL `FOR UPDATE cannot be applied to the nullable side of an outer join`，退出码 `1`。该问题只出现在真实 PostgreSQL 锁语义，修复必须限定 `FOR UPDATE OF` 为 control 自身。
- 第二次 PostgreSQL 16 RED：限定 `FOR UPDATE OF self` 后外连接异常关闭，但同 claim 双 worker 仍为 `apply + reject(current_result_inconsistent)`，而不是 `apply + replay`。根因是等待行锁的语句在锁前建立 JOIN 快照，control FK 可见新值但 nullable related object 仍被旧快照缓存为 `None`；必须在取得 control 锁后用新查询读取 current revision，不能复用锁语句的 `select_related` 快照。
- 两层锁修复后 PostgreSQL 并发模块 `3/3` GREEN：locked due row 被 `skip_locked` 跳过、host 两请求只有一个 reservation、同 claim 双 worker 为 `apply + replay` 且只生成一个 revision。
- Deferred link guard RED：新增跨 event pointer、result pointer 指向 racecard、pointer 指向 `revision_no >= next counter`，以及 supersedes 跨 event/kind/向前引用测试；首次 PostgreSQL 16 执行在前三个 pointer subtest 均未抛出 `DatabaseError`，退出码 `1`，证明当前 `0037` 只有 FK、没有设计要求的 event/kind/向前引用约束。
- Deferred link guard GREEN：`0039` 在 PostgreSQL 安装两个 `DEFERRABLE INITIALLY DEFERRED` constraint triggers 和 revision identity immutable guard；pointer event/kind/counter、supersedes event/kind/严格向后均由 SQLSTATE `23514` 阻断。PostgreSQL 专项 `4/4`，迁移 apply -> reverse 至 `0038` -> re-apply 通过；SQLite 准实时 `98/98`、migration drift/check/diff 通过。

### 公开赛事页赛果状态标识（2026-07-16）

- 测试：`RaceLivePublicStatusTests`，覆盖 provisional 明示“暂定/待官方复核/补充来源/更新时间”，official/corrected/conflict/stale 使用不同文案，以及 shadow revision 因 `published_at=NULL` 不得泄漏任何 live badge。
- RED：断网 SQLite 定向执行退出码 `1`，3 个测试方法为 `2 failures / 1 error`；页面无任何 live 状态文案且 context 缺 `live_result_status`，Django system check 0 issues。
- GREEN：公开赛事页只在 current result revision 已有 `published_at` 时展示状态；provisional、official、corrected、conflict 和 stale 文案可区分，shadow revision 不泄漏。目标与 6 项既有赛事详情回归共 `9/9`，完整准实时模块 `101/101`，与 historical detail chunk/import receipt/import primitives 组合 `138/138` 通过，Django system check 0 issues。
- mutation：去掉 `published_at` 门禁、把 provisional 错标为官方、隐藏 conflict/stale、或遗漏 context 均会被本组捕获。页面只展示客观状态、来源类别与更新时间，不复制第三方评级、评论或其他专有内容。

### 增量审核 P1 RED：持久来源权威与 shadow 晋级（2026-07-16）

- reviewer finding 1：`RaceResultRevisionApplyTests.test_caller_cannot_spoof_official_authority_for_supplemental_source` 要求 apply 从持久化、已审核的 source identity 派生 authority，调用方把 supplemental 冒充 official 必须零写入拒绝；identity 模型同时要求默认 supplemental，且 pending identity 不得保存为 official。
- reviewer finding 2：`RaceResultRevisionApplyTests.test_same_revision_can_be_audited_and_promoted_from_shadow_to_public` 要求同 observation/hash 的 shadow revision 在模式切换后可一次性、可审计地晋级公开，复用同一 revision、不增加编号，并原子物化当前赛果与发布时间。
- RED：断网 SQLite 定向执行 11 项，退出码 `1`，得到 `2 failures / 3 errors`。两个 identity error 来自 `result_authority` 字段/约束尚不存在；official 正向测试因同字段不存在报错；spoof 当前错误地 `applied=True`；shadow replay 当前错误地 `applied=False`。其余 6 项保持 GREEN，Django system check 0 issues，证明失败均直接对应两项审核 finding。
- GREEN：source identity 新增默认 supplemental 的持久 authority 与 official 必须 approved 的数据库约束；apply 在事务中锁定来源并校验 caller/持久 authority 一致。direct public 与 shadow promotion 均写唯一 publication audit，后者复用同一 revision、不递增 counter，并共享当前投影物化路径。SQLite 定向 `11/11`、准实时 `103/103`、相邻历史组合 `140/140`。
- PostgreSQL 直接回归 RED/GREEN：首次在 PostgreSQL 16 执行 identity/apply/并发共 15 项时，shadow promotion 因 deferred trigger 使用初始 INSERT 的旧 `NEW.published_at=NULL` 行像而 `1 error`；`0040` 改为约束执行时按 revision ID 重读当前值后 `15/15` GREEN。`0040 apply -> reverse 0039 -> apply 0040` 往返成功，Django check、migration drift 与 diff check 通过。

### 离线 fixture 端到端 poll runner（2026-07-16）

- 测试：`RaceLiveOfflineFixtureRunnerTests`，覆盖 runner 默认 disabled 且零 mutation、受控 TRA fixture 完成 parse -> observation -> shadow revision -> checkpoint、fixture 缺失与 path traversal identity 均 fail closed 并以失败 checkpoint 释放 claim。
- RED：断网 SQLite 定向执行退出码 `1`，3 个测试方法得到 `3 failures / 1 error`。默认安全 setting 尚不存在；offline mode 仍统一返回 `runner_not_configured`，因此没有 observation/revision/checkpoint，缺失与不安全路径也未分类。Django system check 0 issues；失败全部来自离线 runner 能力缺失，没有网络或外部 fixture 依赖。
- 初次 GREEN 后补充调度/证据 RED：目标 3 项得到 3 failures。成功 observation 的 `raw_sha256` 实际等于 payload digest、不是读取文件字节 SHA；成功与 fixture 缺失的 checkpoint 均把 `next_poll_at` 清为 NULL，导致 selector 永久不再领取。第二个 unsafe subtest 因前一断言中止未重置 claim 而连带返回 `checkpoint_claim_mismatch`，不作为独立产品 finding；修复前两项后应恢复原 unsafe 断言。
- 离线公开隔离 RED：补充第 4 项后，`RACE_LIVE_PROJECT_CURRENT=True` 实际返回 `processed=True` 并物化合成 fixture，违反离线证据不得公开的边界；其余 3 项 GREEN。offline runner 必须拒绝该配置、失败 checkpoint 并保持 revision/当前投影为 0。
- GREEN：runner 默认 disabled；offline mode 仅从绝对受控 root 读取 2 MiB 内 TRA fixture，严格 basename/resolve 边界，使用实际文件 bytes SHA 记录 observation，随后执行 shadow revision 与双 CAS checkpoint。成功按 off time/state 计算下一探针，失败 5 分钟重试；offline public 配置在读取 fixture 前拒绝。目标 `4/4`、准实时 `107/107`、与 historical detail chunk/import receipt/import primitives 组合 `144/144`，Django check、migration drift、py_compile 与 diff check 通过。
- 2026-07-17 合约替代：用户把 TRA 调整为可公开暂定赛果的主链后，`project_current` 不再是 runner 配置，offline runner 永远只写 shadow；即使运行时残留同名环境变量也会被忽略，不会发布。公开晋级改由持久 policy/allowlist、racecard 全集、身份审核和人工锁共同约束的唯一 `admit_race_live_publication()` 完成。新增旁路 RED 证明旧配置/底层 supplemental apply 仍可影响公开，修复后目标 `3/3`、完整准实时 `125/125`，历史 RED/GREEN 仅保留为当时证据，不再代表当前运行契约。
- reviewer P2 RED：新增 off time 已超过 T+7d 最终探针的成功路径；目标 5 项中仅该项 failure，checkpoint 实际仍写 `now+10min`，证明 runner 覆盖了窗口算法以 `None` 表达的正常停止语义并会永久轮询。
- reviewer P2 GREEN：删除固定 10 分钟 fallback，成功 checkpoint 原样保存既有窗口算法结果，包括 T+7d 后的 `None`；合成 fixture 默认改为已开跑 5 分钟，不为不真实的“未来开跑但已有赛果”增加生产兼容分支。目标 `5/5`、准实时 `108/108`、相邻历史组合 `145/145`。

### 隔离 Redis/Celery broker smoke（2026-07-17）

- 使用临时 PostgreSQL 16、Redis 7、独立 Docker network 和当前源码挂载启动真实 `race_live` worker；未使用 eager、HTTP、生产 DB/Redis 或历史 runtime。
- selector 在真实数据库领取 1 场并经 Redis 投递；worker 完成 `1 observation / 1 revision / checkpoint succeeded`，claim token 清空、failure 0、`race_live` queue 归零，shadow 下 `RaceEventResult=0`。
- 另向普通 `celery` queue 投递 1 个任务，live worker 运行期间该 queue 保持 1、`race_live` 保持 0，证明 live worker 未消费新闻/普通队列。烟测后 worker/PostgreSQL/Redis/network、临时数据库、普通队列消息和合成 fixture 已全部删除。

### 后台只读观测面与赛事级 kill switch（2026-07-17）

- 测试：`RaceLiveKillSwitchTests` 覆盖 lock-version CAS、停用 tracking、清空 next poll/claim、claim generation 失效在途响应、单次审计和 stale/repeat 零 mutation；`RaceLiveAdminSurfaceTests` 覆盖 10 个控制/来源/observation/revision/publication 模型只读注册、conflict filter，以及 LiveTracking 只通过 kill-switch action 操作。
- RED：断网 SQLite 定向 4 项退出码 `1`，kill-switch 2 项仅因 service 不存在失败；10 个模型和 LiveTracking 均未注册后台，得到 11 个注册 failure 与 1 个后续 KeyError。Django system check 0 issues，失败精确来自目标后台/停用能力缺失。
- GREEN：kill switch 以 tracking 行锁 + lock-version CAS 停用，清空 next poll/claim、claim generation +1、lock version +1，并在同事务写一次 OperationLog；stale/repeat 零 mutation。10 个控制/来源/observation/revision/publication 模型只读，LiveTracking 全字段只读且唯一 action 走 CAS service。补充真实 Django admin changelist POST 验证 superuser action 为 302、tracking 停用且 audit 绑定操作者。目标 `5/5`、准实时 `113/113`、相邻历史组合 `150/150`，check/drift/py_compile/diff 通过。

### latest-main 完整 stable 与基线归因（2026-07-17）

- 当前专项与 latest-main 新增四组历史测试的组合回归 `249/249`（1 skip）通过；准实时目标仍为 `113/113`。
- 完整 `stable` 实际发现 `1837` 项，运行 `1397.954s`，终态为 `2 failures / 13 errors / 23 skipped`。15 个失败全部位于既有历史/赛事路径：4 个 current-year CSV 测试受日期门禁影响，9 个 helper 测试依赖未跟踪的 `/app/tmp/run_*.py`，1 个 runner v2 package fixture 缺 `parse_gap_json`，1 个子进程缺历史 discovery module import path。
- 为排除本专项回归，使用干净临时 worktree `origin/main@c40a8c2b`、相同镜像/SQLite/`--network none` 精确复跑这 15 项；结果同样为 `2 failures / 13 errors`，错误与 traceback 一致，证明它们是当前主线基线问题。临时 worktree 已删除。本专项不修改上述 command/helper/runner 文件，也未为通过门禁伪造 `tmp` 运行产物。
- 当前 worktree 的 Django check 和 `makemigrations --check --dry-run` 通过；三份 Compose 使用临时、无 secret 的 synthetic `.env` 解析通过，临时文件已删除；两个 worker 脚本 `bash -n`、`git diff --check` 通过。

### 最终 full review findings：非完赛语义与 worker 资源限制（2026-07-17）

- 完整只读 review 会话 `019f6bd8-2336-79b2-9990-c60640c09469` 返回 2 项 P1、1 项 P2：TRA 非数字 position 被压成 unknown；无官方名次的非完赛投影会 fallback 内部顺序形成伪造公开名次；两份生产 Compose 的 live worker 缺显式 CPU/内存限制。
- RED：新增 3 个目标测试实际得到 `4 failures`。PU/F/UR/NR/DSQ/REF 全部错误为 unknown；pulled_up 物化后的 `RaceEventResult.running_status` 为空；标准与低成本生产 live worker 均缺 `cpus`。失败精确对应三项 finding，Django system check 0 issues。
- GREEN：TRA 已把上述 6 个状态映射为 `pulled_up/fell/unseated_rider/non_runner/disqualified/refused`，未知代码仍为 unknown，`position_raw` 原样保留。revision item status 物化到结果投影；无 official position 且属于已知 non-finisher 时，页面显示统一中文状态，不再回退内部唯一顺序。`RaceRunnerStatus` 扩展并新增 `0041` choices migration。两份生产 live worker 均有可环境覆盖的 `cpus=0.25`、`mem_limit=384M` 安全默认。
- 目标 `3/3`、准实时 `116/116`、latest-main 组合 `252/252`（1 skip）通过；Django check、migration drift、SQLite 从零应用至 `0041`、两份生产 Compose config 和 `git diff --check` 通过。临时 synthetic `.env` 已删除。

### The Racing API Free 受控来源 proof runner（2026-07-17）

- 首次人工只读探针已使用仓库外 `0600` secret 发出 3 个串行请求：regions、racecards free today、results today free 均 HTTP 200；只输出状态码、耗时、bytes、条数和字段名，不保存原始响应、马名或凭据，不写业务数据库。
- 自动化 RED 必须覆盖：secret 缺失/权限过宽、registry SHA 漂移、`terms_status`/官方文档与条款证据/用户自动化授权依据缺失或漂移、许可 false/过期、非 HTTPS/非 allowlisted host/path、请求预算超限、输出目录复用，均在首个网络调用前 fail closed。
- 成功路径固定最多 3 请求、相邻请求启动间隔至少 1.05 秒、15 秒 timeout、2 MiB 响应上限、禁止重定向；报告只保存响应 SHA、状态、延迟、大小、集合数量和字段集合，不保存 raw body、实体值或 credential。
- 429/非 200/非 JSON/超限/transport exception 不自动重试；停止后续请求并生成 `completed=false` 的脱敏审计，异常文本中的 username/password 必须被替换，不能进入 traceback、manifest、ledger 或 summary。
- 输出目录必须原子新建且包含 manifest、request ledger、summary；manifest 绑定 source key、registry SHA、固定 endpoints、request budget、runner version 和时间。服务层不得访问 ORM，普通自动化测试使用 fake transport，不访问真实网络。
- RED/GREEN：初始 5 项均因 runner/command 缺失得到真实 RED；随后针对 manifest 完整性、错误 schema、原子 artifact 得到 `1 error + 2 failures`，针对 registry 条款证据得到 1 项 contract RED。代码 review P2 再以 `proof_network_allowed=true + automation_allowed=false` 取得 `PermissionError` RED，确认一次性 proof 被错误绑定长期自动化许可；修复后 registry 仍要求 automation key 为显式 bool，但 proof 只依赖自身许可。最终 proof `8/8`、proof + 准实时 `124/124`、再合并 latest-main 相邻历史回归为 `260/260`（1 skip），均在隔离镜像、`--network none` 下通过，Django system check 0 issues。
- 真实 run01 在本地代理 DNS 返回非公网地址时于首个请求前安全阻断并产出脱敏失败审计；run02 使用一次性容器固定经独立 DNS 审计的公网地址后完成 3/3 请求，regions `55`、racecards `10`、results `0`。没有保存 raw body/实体值或写业务 DB；完整 SHA 与边界见 `source_proof_report.md`。
- 当前仍为首个观察窗口，0 个已完赛结果样本；不得据此宣称覆盖、延迟、暂定/正式或 Basic 升级门槛通过。
- 限定复审后的两个质量建议也已取得真实 RED：proof 传入独立完成时钟时为 `unexpected keyword argument 'clock'`，未知 result status 被错误改写为 `did_not_finish`。修复后 `finished_at` 在请求结束后取得且必须 timezone-aware、不早于开始时间；未知状态保持 unknown/raw，已知非完赛状态不变。review finding 再补 naive、倒退、非 datetime、clock exception、正式/临时目录零残留和 transport/sleep/clock 调用顺序测试。proof + 准实时为 `126/126`，latest-main 相邻历史组合 `262/262`（1 skip）。

### The Racing API Free provisional 自动化 runner（2026-07-17）

- 实时 payload parser RED/GREEN 覆盖：无 fixture redistribution metadata 的合法 results、空集合为正常未命中、非空 malformed schema fail closed；只保留客观身份/名次/状态字段。
- 网络 runner RED/GREEN 覆盖：automation registry 与 source permission 必须在 secret/host/transport 前通过；固定单次 results endpoint、15 秒、2 MiB、禁止 redirect；HTTP、content type、size、JSON/schema、重复 external race ID、无匹配、网络后 stale claim 均不得产生公开写入。
- 唯一匹配成功路径必须依次产生 observation、shadow revision、publication admission、materialized provisional results、publication audit、official verification incident 和成功 checkpoint；raw body 不落盘，host reservation/outcome 使用版本 CAS。
- task/config RED/GREEN 覆盖默认 disabled/空配置、仅显式 `the_racing_api_free` 使用固定安全 transport；镜像包含受审 registry，只有独立 live worker 获得只读 secret 目录挂载。
- 当前官方文档确认 Free racecards 默认 limit 500、results 默认 50；把旧 `10/10` 测试改为 `500/50` 后，proof 先得到 `9 errors / 1 failure`、runner 请求数为 0 的 registry allowlist RED；同步生产常量、runner URL 和 registry 后，proof `10/10`、runner `5/5`、完整专项 `149/149`。

### 生产 shadow 初始化器与 shadow checkpoint（2026-07-18）

- 初始化器 RED：新增 `stable.test_race_live_initialization`，首次 6 项执行得到命令缺失的 `3 errors` 与 shadow admission 被当作失败的 `1 failure`；命令实现后再用独立 RED 捕获未来 `generated_at`、人工 runners/results 锁和 racecard authority 写成 source key 三个缺口。
- GREEN：`initialize_race_live_events` 成功路径只接受 regular file、严格 schema v1、lowercase manifest SHA/40 位 approved commit、aware 时间、固定 TRA source/host 和无重复 event/participant/source identity；默认 dry-run 零写，apply 必须同时传 `--confirm-apply`，verify 只读。赛事 baseline 精确绑定 ID/year/slug/name/region/course/grade/race time/updated_at，未来 manifest、过期许可、人工锁、既有赛果或非精确初始化行全部 fail closed。
- apply 对完整 manifest 使用单事务和 event row lock，只创建四层 `shadow` policy、enabled 且 cap 为 provisional 的精确 allowlist、1050ms host budget、live generation 1 control、无 active claim tracking、TRA supplemental source、approved participants、未发布 racecard revision/items/pointers，以及逐 event 唯一 `OperationLog`。任一 event 冲突整批回滚；同 manifest 重放只验证并返回 replay，零新增。
- shadow runner 只把 admission 的精确 `shadow_only` 作为成功 shadow checkpoint：保留未发布 revision，清 claim、失败计数归零并继续窗口轮询；不生成 `RaceEventResult`、publication audit 或 official incident。其他 admission rejection 仍失败。
- SQLite 初始化器与 TRA runner 聚焦回归为 `13/13`。临时 PostgreSQL 16 新增双进程同时 apply 同一 manifest 的真实并发测试，与既有 selector/host/revision/deferred guard 合计 `5/5`：结果固定为一次写入、一次 replay，control/revision/OperationLog 各一份；临时数据库、容器和 network 已清理。

### 最终原生 review P1：赛事日历公开读取门 N+1（2026-07-18）

- 首次成功原生完整 review 确认旧时钟、incident replay、生产初始化和 raw official marker findings 已关闭，但指出 `_group_race_events_by_date()` 对最多 40 场赛事逐场调用单赛事公开读取门，导致查询数随 live revision 数线性增长。
- RED：`RaceLivePublicStatusTests.test_calendar_live_read_gate_query_count_is_bounded_for_full_page` 创建 40 场合法、已公开的 provisional live event，并用 `CaptureQueriesContext` 对完整日历请求设置 `<=12` 硬门禁；首次执行实际为 `525` 次查询，目标测试退出码 `1`，页面内容本身仍正确。
- GREEN：新增批量 public-read resolver，一次加载赛事、control/current revision/primary observation/source、publication、适用 global/region/source/event policy 和 event/source allowlist，再逐赛事复用原 fail-closed 判定；详情页继续走单赛事 resolver。公开状态组 `6/6`、准实时/来源 proof/初始化 SQLite `160/160`、临时 PostgreSQL concurrency/constraint/initializer `5/5` 通过，40 场页面查询数满足 `<=12`。
- 候选镜像分层验收：镜像内 `manage.py check` 和实际随镜像交付的初始化器+TRA runner `13/13` 通过，registry SHA 精确为 `1d801e95b2770c741503a75dbcba93aca407a6cd681f3471813f1e7d5586fa32`，不存在 `.env` 或 TRA secret。整套 `160` 项中的 `RaceLiveWorkerDeploymentContractTests` 必须读取仓库根三份 Compose 与源 registry，直接在运行镜像内执行会按预期得到缺文件的 `5 errors / 1 failure`；该组已在完整源码挂载环境随 `160/160` 通过，三份 Compose config 另行通过，禁止为消除环境误用而把非运行时部署源复制入镜像。

### 最新 main 单父整合验证（2026-07-18）

- 原冻结提交 `e21dc6ea` 以 `main@ccb56f7d` 为单一 parent 重放；main 增量仅为赛事身份 PostgreSQL 锁修复、对应测试和四份生产事实文档。冲突仅发生在 `docs/current_state.md` 与 `docs/project_status.md` 的同日顶部章节，解法为完整保留双方事实并把原授权状态改为“整合树待复审/新授权”；准实时业务代码无冲突。
- SQLite 组合 `stable.test_race_live_source_proof + stable.test_realtime_race_results + stable.test_race_live_initialization + stable.test_race_series_identity_review` 为 `180/180`，其中赛事身份 PostgreSQL 专用用例按设计 skip 1。
- 临时 PostgreSQL 16 精确执行准实时并发/初始化 5 项和赛事身份 nullable-series base-row lock 1 项，结果 `6/6`。直接把整个 SQLite-oriented `RaceSeriesIdentityReviewTests(TestCase)` 放入 PostgreSQL 会因测试事务已开始后再设置 repeatable-read 得到环境性 errors；该错误执行未作为通过证据，随后在全新数据库只运行明确标注的 PostgreSQL 专用目标。
- 整合镜像 `sha256:87f8603320f856bbc4167f29b76c811fe6e2a06b62bfb72dd73b944840b73bcf` 绑定 approved-parent 候选 `ccb56f7d526daf70357f193f716b23eacb26edbe`；镜像内 check、初始化器+TRA runner `13/13`、registry SHA 和无 secret 检查通过。
