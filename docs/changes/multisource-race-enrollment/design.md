# 设计 v2（独立首轮返修）

## 1. 已有结构与入口

| 现有代码 | 复用与需要修改的地方 |
| --- | --- |
| `models.py:RaceResultSourceIdentity` | 已支持一赛事多来源；保留四元组全局唯一和 event+route 唯一，不以名称替代 external ID |
| `RaceDataSyncEnrollment / RaceEventProjectionControl / RaceEventLiveTracking` | 保留 event 一对一登记、单 owner 和 event claim；Enrollment 当前单 source FK 作为 v1／首次来源 provenance |
| `RaceEventLiveProviderCheckpoint` | 保留按 tracking+source_key+data_kind 唯一的进度；同 provider 同场只选一个有效 namespace，其他身份仅作证据，不产生 checkpoint 歧义 |
| `race_data_sync_enrollment.py` | 扩展 policy/census/manifest，解除所有 eligible route 必须 full_data_kinds 的 v1 约束；新旧 schema 分支 |
| `tasks.py:discover_future_race_data_sync_task / sync_race_event_provider_task` | 从硬编码 TRA discovery/dispatch 改为批准来源注册表；先生成覆盖分母，按源发现、统一匹配、登记、分能力同步 |
| `race_data_sync_control.py / admission.py` | 更新 claim plan/CAS、绑定集合和统一准入；保留旧 owner 冲突、manual lock、有效期等检查 |
| `race_data_sync_pipeline.py / results.py / providers.py` | 复用 snapshot、请求/字节额度、observation/revision、结果投影；新 adapter 不直写业务表 |
| `race_pre_race.py / refresh.py / sources.py` | 复用 JRA、NAR、SL、ZEturf 等现有解析；分离请求时间窗与赛后只读显示 |
| `race_reference_sources.py` | 复用候选 schema、来源 URL 和强身份核验、事务审计；不把 source_name 占位入口当完整 adapter |
| `RaceSeriesName / RaceEventAlias / RaceEventProductCanonicalLink` | 复用受审且有 provenance/有效届次的别名；既有人工 canonical 映射先解析，禁止自动创建映射 |
| `RaceLiveAlertIncident / TaskExecutionLog / RaceEventDataCandidate` | 覆盖 incident、执行统计及身份冲突候选，避免新增审计表 |

主线没有历史候选 worktree 的 `race_data_identity.py`；可借鉴算法并逐段复核，不能直接合并旧分支或其 0079 迁移。所有新 parser 必须检查上表模块及 runtime/tools 现有实现，提取纯解析函数并使离线工具复用，不能两份复制演化。

## 2. 观测与来源协议

拟增 `services/race_data_source_adapters.py`：纯协议和注册分派，parser 按来源放既有 adapters/services；不引入另一个调度系统。

`SourceObservation v1` 必填 provider、contract_region、identity_namespace、external_race_id、canonical_url、fetched_at（aware UTC）、source_updated_at（可空）、raw_sha256、parser_version、route/contract/proof digest、source_class、operator、venue_key 及 venue evidence、local_date、IANA timezone、raw_names[{text,language}]。`meeting_id/session/race_number`、series/edition evidence、off_time、surface/type/distance、roster、result phase 按能力可空。每字段保留 raw value、单位、source URL 与证据，不从数值大小猜单位、不从 country=japan 猜 JRA/NAR。

Adapter 明确 `discover_identity / fetch_schedule / fetch_racecard / fetch_result` 可用能力、来源开放窗口、固定允许 host/path、重定向白名单、超时、最大字节和请求预算。身份能力可以独立于三种资料能力；data_kind 仍仅 race_time/racecard/result，不伪造空赛果或增加 identity 网络任务种类。返回 matched/not_found/not_published/window_unsupported/transport_failed/access_denied/parse_failed 等枚举，不能全部归零行成功。HTTP 403/406、CAPTCHA 为该来源访问缺口，不绕过；其他来源可正常继续。

所有网络在事务外，通过已有 `_get_or_fetch_shared_snapshot`、容量预算和 host budget。每个来源每地区发现分桶共享一次列表，URL scope 沿用超长 URL 哈希；禁止每场重复下载全天列表。发现身份的持久运行状态沿用 `source_refs.pre_race_checks` 的锁内 helper，但迁移为独立 `source_discovery_v2` 命名空间，不再调用 `in_window()`；输入/终态摘要写 TaskExecutionLog。

## 3. 跨来源与跨语种身份判定

拟增纯服务 `services/race_source_identity.py`，输出 exact / review_required / conflict / unmatched 及候选集合、算法版本、原始来源哈希、命中和拒绝证据。候选最多同 operator、canonical venue、当地日期附近 ±1 天 100 条；±1 仅用于召回处理时区，最终自动绑定必须满足明确的同一举办地日期，除非有受信延期跨日证据。

### 3.1 自动绑定优先证据

- A0（旧日历冷启动）：event无source ID、无实例key、RaceSeries未受审时，读取已有导入来源 `source_refs.primary`、受审参考候选或 `jra_pre_race_binding`。旧URL/baseline只是线索，必须在该来源已准入且预算许可的前提下重新取得原始页面：①核对原导入/候选的raw SHA、baseline(event/date/venue/name/operator)和当前event一致；②从可信日历页面唯一一行（同当地日期、canonical venue、原语种赛事名/有provenance别名及已知等级/距离无矛盾）沿真实官方race链接追踪到赛卡/结果，或重新验证已存当场binding URL及其页面；③验证URL解析的race ID、页面日期/venue/race_no与本场唯一一致，所有强key无其他event占用。形成 `identity_seed_receipt`（event snapshot SHA、旧来源/候选ID、完整链接链、fresh raw SHA/抓取时间、核验字段、matcher/route digest），再原子创建source四元组与B key。不能只凭数据库里有人填过URL、传入event_id或名称相似就seed；没有完整旧证据/链接链则保留review_required。104的primary年度表和已有JRA候选/binding可走此路径，T01须用series未受审的冷启动fixture证明。UK/其他地区可从原官方日历或已受审参考候选建立同等seed；缺证据的具体赛事进入固定待审清单，不假装自动覆盖。
- A：已有 source-scoped 四元组 ID，或来源提供的可验证官方外链指向已绑定 race ID；重新核验地区／举办地／届次上下文，ID 重用或日期矛盾不得按既有 ID 盲信。
- B：官方/可信来源提供 `operator + canonical_venue + local_meeting_date + meeting_session + race_number`，与 event 已保存的可信发生实例锚点唯一一致。meeting_session 缺省只在来源证明当天没有多场同号会次时用显式 `single`；否则不构造 B。赛事名称可完全不同语种。若 event 原来没有 B 锚点，必须先由 A/C 或受审候选证明唯一 event 后才添加 B，不能用输入声称 event_id 自证。
- C：受审 RaceSeries 的 active、届次有效、provenance 明确的名称/crosswalk，匹配唯一 `race_series + edition_year`，同时核对 operator、canonical venue、举办地日期；赛次、场地/赛种、显式距离或届次有矛盾均拒绝自动绑定。

A0/A/B/C产生的所有强证据目标必须一致；不得“取第一个能匹配的”掩盖另一锚点冲突。受审发生实例有明确改期/改场证据时保留旧 alias 和新 key，记录 correction provenance；不能仅凭相近比赛时间跨日合并。来源 ID 解析、venue 别名表按版本冻结并有语言/运营方/有效期；Nakayama/中山只是同 venue 的例子，现有词库文本本身不视作已受审 crosswalk。

### 3.2 名称处理

保留原文；用于召回的副本做 HTML entity 解码、NFKC、casefold、空白和受控标点统一。简繁、变音符、冠名/等级/届次清理以及音译作为独立召回 key，不覆盖原文、不任意删除词。RaceEventAlias 缺 provenance 或 RaceSeries 未受审时只召回。模糊匹配只在相同 operator/venue/date 候选内排序，最多展示 5 条；分数不进入自动绑定判据，不调用 LLM 翻译作为唯一证明。

示例：オールカマー / Sankei Sho All Comers / 产经赏All Comers 可由相同中山日期+11R 的已核验锚点合并；`All Comer` 拼写差异仅降低名称证据，不影响已证实的 B。两个同日同场分组赛、同名不同年度、JRA/NAR 同名赛场不得仅因名字近似合并。

### 3.3 跨来源并发唯一性

新增 `RaceEventIdentityKey`：event FK(PROTECT)、key_type、namespace、key_sha256、key_payload、evidence JSON、matcher_version、created_at；DB UNIQUE(namespace,key_sha256)。key 为 B 的完整实例元组或明确官方 crosswalk；C 利用已有 series+edition 唯一约束，不生成以可变赛时/名称为主键的 key。payload 与 hash 双重校验，SHA 命中而 payload 不同拒绝。

写入事务：按排序后的 namespace/key 取得 PostgreSQL transaction advisory locks（节约冲突，不作为唯一保障）→遵守全局行锁图 lifecycle_control→event→projection→tracking/enrollment/checkpoints→source_identity→identity keys/bindings→observation/revision；涉及多event时每个层级按event ID升序，不能先event再回头锁lifecycle。lifecycle缺行先按既有模式读取并锁event，锁后若发现控制行被竞争者创建，回滚整个事务重试，从lifecycle重新取锁；缺行创建由event序列化且受一对一唯一约束保护。v2涉及的attach/claim/apply/rotation入口都遵守此锁序，不沿用event-first的末端apply辅助函数而在持锁后追加lifecycle锁；对所有强 key 和 source 四元组重新查询。任何一个已属于不同 event，整组零业务写入并在事务外记录 conflict。缺失 key 用 DB UNIQUE + 内层 savepoint INSERT；IntegrityError 后回滚 savepoint、重读并判断同 event 幂等或异 event 冲突。全部 key/source/binding/enrollment 一次提交，on_commit 才发任务。SQLite 可验证唯一性和重试逻辑，真实并发验收用 PostgreSQL。

现有 ProductCanonicalLink 只读取审核后的有效单层映射；链/环或两个 active canonical 目标均冲突。历史重复 event 不自动重写 canonical 链。找不到 event 只存候选，不创建新 event，避免跨源新建双份。

## 4. 登记、binding 与权限

新增 `RaceDataSyncSourceBinding`：enrollment FK(PROTECT)、source_identity FK(PROTECT)、state(active/quarantined/retired)、capabilities JSON、route/contract/proof digest、registry_schema_version、identity_evidence_sha256、binding_manifest JSON+SHA、valid_until、created_at/updated_at；UNIQUE(enrollment,source_identity)。服务事务校验 source.event_id=enrollment.event_id；不接受客户端自行指定任意 source FK。无资料能力但身份明确的来源可登记，空计划不派发 provider task。

Enrollment 新增默认兼容字段：`authority_version=1`、`source_set_generation=0`、`source_set_digest=''`、`source_set_manifest={}`；v2 manifest 包含有序 active bindings、各 data_kind 当前选中 binding、policy digest、event identity keys digest、owner/enrollment generation、有效期、matcher version和父 manifest SHA。完整 manifest hash 为权威，不能只接受一段任意 JSON。旧 source FK/route_digest/entry/manifest SHA 保留首次 v1 provenance，v2 准入不能误用它当唯一当前权限。

首次唯一来源命中：原子建 source identity、identity keys、一个 enrollment/control/tracking/lifecycle evidence。`write_owner=data_sync` 只授予一次；后续 attach 保持 event ID、owner_generation、现有 revision 号和已确认结果，不重新 enroll。绑定变化更新 source_set_generation/digest 和控制证据，清除在途 token、推进 claim_generation；旧 worker 仅能保存不可变 observation，不能投影。相同 binding/hash 重试不增代、不发重复任务。

每 data_kind 选源：当前选中来源仍合法则保持；空能力槽按 policy 固定 tiebreak 选择首个能力完整、身份合法来源。后到来源只登记证据与可用能力；源空响应不会删除最后有效数据。当前源 not_found/not_published，或同kind连续2次 transport_failed/timeout，或明确403/406/access_denied使该来源circuit_open时，允许另一合法binding取得5分钟 alternate_fetch 授权（沿用claim TTL时取更短者）。来源失败计数/冷却存现有checkpoint；403/406立即隔离该端点并至少冷却1小时，遵守更长Retry-After，不换身份/代理绕过。alternate授权的kind/binding/原因/expiry写入v2 manifest并推进generation，worker只执行被授权来源；成功且完整后把该kind选源粘滞为B并保存前后source_set receipt；失败仅保留observation，仍按可用性/预算选源，不写空数据。A恢复时不自动抢回，A同内容仅补证据不新建publication。部分/不明finality的结果不得标成功；来源合同失效只隔离该binding并重验其他binding，赛事身份冲突、人工锁、全局停用或撤销不能靠fallback绕过。所有更正仍需现有 correction/finality 规则；不因来源权重改变重写已确认结果。

统一 `validate_data_sync_lifecycle_admission` 扩展 capability 和 operation(write/lifecycle/public_read) 参数并由 lifecycle、schedule/racecard/result writers、public reader 共用；v2 验证 policy、manifest、owner、bindings、被选中能力与锁/有效期，任一必需证据漂移 fail closed。生命周期需要登记+可信赛时证据或完整来源终态；不会要求唯一来源同时具备三种能力，也不会因某个无关 binding 过期让所有其余有效来源失效。来源过期/隔离通过同一事务重算集合，未完成重算前拒绝新写入并保留最后已发布有效版本。public_read模式验证发布当时的不可变授权证据、publication和当前显式撤销/身份invalidated标记，不依赖当前网络写开关，也不因历史来源现在过期或无关route变更而隐藏历史结果；已撤销或错误身份内容必须隐藏。write/lifecycle模式使用当前policy/proof/有效期，不借历史发布证据获得新写权限。

## 5. Claim、结果与跨源参赛名单

沿用每个 event 同时一个 active claim；每 claim 仅处理一个 binding 的 due data_kinds，维持 `len(planned_source_keys)==1`，其他来源下轮公平轮转，避免多 writer。v2 claim 新增 authority_version、binding_id/source_identity_id、source_set_generation/digest、binding_manifest_sha、route/contract/proof digest 和精确 checkpoint 集合；plan SHA 覆盖全部字段。网络返回后锁内重验每项及有效期。selector、celery 参数、checkpoint 更新、pipeline、result apply、fallback 和公开 admission 同步改造；不允许仍用 enrollment.source_identity 隐式代替 claim source。

仅有官方结果的首次来源也能登记。若正式 runners 为空：只有完整 roster 和明确终态的结果观察可在同一受 claim 保护事务内创建 event 内 participants/runner source IDs/runner 投影及 result revision，再公开；该 bootstrap 独立标记来源为 result，不伪造赛前 card 或历史赔率。部分结果只保存 observation，不创建半份正式名单。

已有名单的跨语言对齐：先用 source-scoped runner ID/crosswalk；同一已核验赛事中的唯一马号可作为 runner slot，对齐需完整 roster、无重复号、无换号/替补冲突及一致的退赛证据。该 slot 只绑定本场 participant，不合并全球 HorseProfile。若姓名变化不属于已核验别名且存在马匹属性/替补证据矛盾，记 roster_identity_conflict，不能凭马号忽略冲突；缺少足够身份证据时保留原名单并待审。结果名次、未完赛、退赛、同着按既有守恒合同；不能以“有 13 行”代替所有状态完整。

## 6. 窗口、覆盖与公开显示

覆盖分母为启用地区、published、排除有效 canonical duplicate 的 event；包括人工锁、无来源、未开放等对象并分层报告，不从 enrollment 表倒推分母。当地日期缺失者进入独立 missing_date 分组；不猜今天。

- future：未来 30 天（举办地日期）。各来源有自身开放窗口，窗口外零 provider 请求但保留目标。
- pre：沿用 D−4～D−2 3h、D−1 1h、D0 10min 的资料刷新。
- late admission：过去 7 天、scheduled/running 或 finished 但未确认结果，也包括无 enrollment 的 event；不调用 pre `in_window()`。有完整结果可直接建立 finished+confirmed 的合法链。postponed 保留但不按旧赛时推进；cancelled 不做普通结果轮询，保留身份/取消证据和观测。
- 七天后：保留 overdue incident 与候选证据，转为一次性修复清单；不自动无限爬历史。
- 无分钟赛时但已知当地日期的result能力：按来源明确开放窗口轮询，D0每30分钟、D+1～D+7每6小时；来源只有日期列表则按列表观测，不伪造race_datetime。需在调度层显式覆盖现有 `calculate_next_poll_at(result, race_datetime=None)` 返回None的分支，取消/已确认则按其终态规则收敛。
- 所有资料 kind 按已有 `calculate_next_poll_at` 的赛后频率和 correction 窗口执行，date-only 不编造分钟时间。

扩展既有 incident 类型，scope=canonical event；dedupe_key 包含 issue_type、event_id、policy版本（不含时间），update last_seen，不每分钟外发。T−1 天已进入某来源开放窗口仍未登记→enrollment_missing；有可信赛时 T+30 未确认→result_overdue（不要求 enrollment）；缺赛时且举办地 D+1→time_unknown_overdue。manual_pause/owner conflict 分组可见但抑制普通催抓；解绑/停用不算解决。只有对应真实状态条件消失才 resolve；重复扫描幂等。源障碍按 provider+region+reason 聚合，失败不使整个 census 分母缩小。

`public_jra_preview` 和通用候选读改为“请求窗口”与“合法只读保留”两条判断：最后经验证名单在赛后可读，显示最后更新时间；退赛标记保留，赔率按 TTL 和来源观察时间隐藏；正式 revision接管后只显示一份。人工锁、撤销来源、错误身份或 invalidated candidate 不可因缓存继续露出。

## 7. 新旧兼容、迁移和预算

现 route_digest 包含整个 roster.registry_digest；直接增加 JRA route 会让旧 TRA 授权全部漂移。因此引入 v2 route-local digest：provider/region/namespace/capabilities/host-path/parser-contract/proof/terms/有效期；新 registry 总摘要单独审计，不因无关来源新增改变旧路线。

v1 policy/roster 定义和摘要算法冻结为版本化 legacy resolver；不能修改其 entry 集合后仍声称 digest 未变。v2 使用独立 schema 的 standing policy，resolver 按 Enrollment.authority_version 选择 policy和注册表，而非全局一个 policy SHA。旧 identity.registry_digest 保持原值；新 binding 的 digests 存 binding。v1 的有效期、开关、人工锁和 proof 校验不得豁免。先用全部现存 enrollment 的只读快照做旧准入/公开路径等价验收，再启用新来源。

新增表/字段的下一迁移号在实施时读取 leaf（当前 0078）后确定；仅加表、索引及默认兼容字段，不迁移比赛名、不批量生成推测 keys、不迁移未受审别名。v1→v2 是固定 event 集合的独立管理命令，提供 prepare/dry-run/apply/verify，逐 event 原子重验并写前后 manifest/父SHA；不在 Django schema migration 联网或转换全部生产登记。

三个默认关闭的配置：`RACE_DATA_MULTISOURCE_DISCOVERY_ENABLED`、`RACE_DATA_MULTISOURCE_APPLY_ENABLED`、`RACE_DATA_COVERAGE_ALERTS_ENABLED`；apply 只允许新 schema/固定地域 allowlist。另加 `RACE_DATA_MULTISOURCE_POLICY_FILE` / `RACE_DATA_MULTISOURCE_POLICY_SHA256`（默认空，双配置缺一即拒绝v2）；沿用现有全局/地区/provider/data_kind开关与每日 512 请求、1GiB 桶上限、host rate limit，不自行扩大。单轮最多 20 个 event，每 event 至多 2 个 source attempt，结果优先；地区/来源轮转，未处理对象显式 budget_deferred。上限不能替代上线容量计算；请求可能覆盖不同桶，启用总量必须纳入发布包。暂不新增队列。

## 8. 失败可见性

| 失败 | 行为 | 验证 |
| --- | --- | --- |
| 一源空响应/403/超时 | 保存原因，其他源继续，有界退避 | T01/T11/T29 |
| 跨源重名/跨语种歧义 | 候选+identity_conflict，不写身份或结果 | T04–T09 |
| 并发抢 key / binding | unique/savepoint/整组回滚，同 event 幂等 | T10/T17 |
| 网络后合同/claim 过期 | observation保留，投影零写 | T18/T19 |
| 半结果/同着/退赛缺行 | 不确认、不发布半名单，告警 | T15/T16 |
| 新 registry 使老授权漂移 | legacy等价测试失败即不启用 | T21/T22 |
| 公共卡片赛后消失 | 独立只读保留，取消过期赔率 | T24/T25 |
| 七天窗口到期仍无来源 | 持久 incident/修复清单，零自动历史扩量 | T26 |
