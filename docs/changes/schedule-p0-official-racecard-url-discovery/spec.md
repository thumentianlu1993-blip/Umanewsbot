# P0 官方出马页面 URL 定时发现规格

## 1. 目标

每天 `06:30`、`18:30`（`Asia/Shanghai`）枚举未来七天全部 P0 赛事，发现能与赛事稳定身份
对齐的官方出马页面或官方日期索引 URL，并把当前窗口的最新状态写入服务器持久化文档。
精确页面已存在与日期索引入口可达必须分栏呈现，禁止混为同一可信级别。
任务只保存 URL 及最小审计元数据，不保存网页正文、出马名单或其他页面内容。

本 change 是 `fetch-upcoming-key-racecards` 的窄化后继：前者仍负责结构化赛前数据候选与数据库
apply；本 change 不写赛事业务表，也不把 URL 发现等同于出马数据可信或可 apply。

## 2. 时间与范围

- 调度时区：`Asia/Shanghai`。
- 调度表达式：`crontab(minute=30, hour="6,18")`。
- 每次运行冻结绝对窗口 `[started_at, started_at + 7 days)`，同时记录 UTC 和中文展示值。
- 精确 P0 定义：`RaceEvent.priority == RaceEventPriority.P0`。
- 排除 `status=cancelled`；`scheduled/running/postponed/finished` 是否落窗由时间证据决定。
- 有 `race_datetime` 时按 aware datetime 判断半开窗口。
- 缺 `race_datetime` 但有 `local_date + timezone_name` 时，以赛事地区该本地日与窗口相交作为
  保守超集，写明 `inclusion_basis=local_date_superset`；不得猜开始时刻。
- 缺上述两类时间证据时无法证明属于未来七天，不计入 future-seven-day denominator；另建
  有界 orphan 审计集合：`year` 落在窗口涉及的公历年份、`status in
  {scheduled, postponed}`、`priority=P0`、非 cancelled。该集合显示
  `暂无（time_identity_missing）`，独立计数，不与可判窗赛事的 expected/coverage 混算。
- 不以 `visibility_status`、`is_featured` 或 RaceSeries 审核状态缩小 P0 清单；这些值只作为审计列。
- 文档只保留当前窗口赛事及本轮有界 orphan；离开范围的旧赛事在下一次成功发布时移除。

## 3. 地区与 provider

适配器注册表必须覆盖：

| 地区 | 官方 provider | 首期行为 |
|---|---|---|
| 日本中央 | JRA | 注册适配器；仅在受审 route 可用时发现 |
| 日本地方 | NAR | 注册适配器；复用 `TodayRaceInfo/DebaTable` 身份约定 |
| 香港 | HKJC | 注册适配器；复用日期、马场、场次参数身份约定 |
| 英国 | BHA 或赛事官方机构 | 仅使用受审官方入口，禁止 Sporting Life 等第三方冒充官方 |
| 法国 | France Galop | 仅使用 France Galop 赛事/场次稳定身份 |
| 美国 | Equibase 或赛场官方机构 | 仅使用允许自动访问的受审官方入口；不得绕过 robots/条款 |

没有 P0 赛事不等于适配器未覆盖。每次运行都输出 `registered / enabled / blocked` 的 provider
覆盖矩阵。

## 4. outcome、持久化状态与更新

adapter outcome：

- `found`：官方正向证据确认精确出马页 URL。
- `listing_reachable`：官方共享日期索引由稳定日期确定性生成，且应用入口 `HEAD` 2xx；不声称
  单场出马表已经发布。
- `not_published`：官方入口明确列出该赛事并明确表示出马页尚未发布。
- `candidate_unverified`：能按已知模板构造 URL，但没有官方正向存在证据。
- `identity_missing`：缺稳定外部 ID、官方场次号或必要时间身份。
- `adapter_disabled`：已有适配器但 route 尚未获准启用。
- `policy_blocked`：条款、robots、host/path 或 contract 阻止请求。
- `identity_conflict`：provider/track namespace 得到多个候选或跨 provider 身份冲突。
- `duplicate_match`：同一 provider 内正向证据命中多个官方页面。
- `path_unverified`：普通 404、模板失效或无法区分未发布/无效路径。
- `source_error`：超时、限流、5xx 或结构漂移。

`found` 与 `listing_reachable` 都可保存 URL，但 Markdown 必须分别显示“已确认出马索引”和
“官方日期索引（需人工确认）”。其余 outcome 中文均显示“暂无”及原因。持久化事件状态：

- `confirmed`：本轮 `found`；
- `listing_reachable`：本轮只确认共享日期索引入口；
- `not_available`：本轮为明确无确认 URL 的非错误 outcome；
- `previous_url_unverified`：上轮有确认 URL，本轮为
  `source_error/path_unverified/identity_conflict/duplicate_match`，保留旧 URL；
- `error_without_previous`：本轮错误且无可保留 URL。

完整转移：

| 旧状态 | 本轮 outcome | 新状态 | URL |
|---|---|---|---|
| 任意 | found | confirmed | 新确认 URL |
| 任意 | listing_reachable | listing_reachable | 新官方日期索引 URL |
| confirmed/previous_url_unverified | source_error/path_unverified/identity_conflict/duplicate_match | previous_url_unverified | 保留旧 URL |
| 无确认 URL | source_error/path_unverified/identity_conflict/duplicate_match | error_without_previous | 空 |
| 无确认 URL | not_published/candidate_unverified/identity_missing/adapter_disabled/policy_blocked | not_available | 空 |
| confirmed/previous_url_unverified | 上述明确无页面 outcome | previous_url_unverified | 保留旧 URL并记 state conflict |

同一赛事多次发现时：

- 新的已确认 URL 替换旧 URL；
- 相同 URL 仅更新时间，重放幂等；
- 后续 404/消失不自动清空已确认 URL；
- 较早启动、较晚完成的旧运行不得覆盖更新运行。

## 5. 身份与可信边界

- 主键使用内部 `RaceEvent.id`，并保存 `year/slug/series_key` 作人读校验。
- URL 必须绑定 `provider`、`country_region`、provider 稳定赛事 ID、官方场地+日期组合，或
  明确标为 `verification_scope=date_listing` 的官方日期索引、
  `provider_contract_version`、`verification_method`、`verification_scope`、`source_url`、
  `checked_at`。
- 禁止按赛事名模糊命中。日期可以作为官方共享日期索引的完整路径身份，但必须同时绑定内部
  `RaceEvent.id`、地区和 `verification_scope=date_listing`，不得称为单场确认。
- adapter 由 `source_refs` provider namespace、官方 race/track identity 与 route contract
  唯一选择。日本只允许唯一命中 JRA 或 NAR；美国只允许唯一命中 Equibase 或精确赛场 provider。
  零匹配为 `identity_missing`；多 adapter 候选或跨 provider 冲突为 `identity_conflict`，禁止按
  注册顺序选取。
- `verification_method=head_exact_path` 只看状态码，不下载正文：2xx 为 `found`、404 为
  `not_published`、429/5xx/超时为 `source_error`。`head_application_entry` 的 2xx 只能产生
  `listing_reachable`。认证跳转或真假路径不可区分为 `path_unverified`。
- 同一 provider 需要正文 marker 时正向证据零命中为 `candidate_unverified/path_unverified`，重复命中为
  `duplicate_match`；这些 outcome 均显示“暂无”或按转移表保留上轮确认 URL。
- 自动 transport 必须通过 HTTPS、allowlisted host/path、redirect、超时、响应大小、请求预算、
  robots/terms 和 contract 有效期检查。
- 确定性 URL 构造不属于正文抓取。联网验证仅允许 route contract 声明的 `HEAD` 或既有受审
  marker 模式；本 change 不解析或保存 Equibase/BHA/France Galop 出马正文。
- BHA/Equibase 本轮 route 只允许 `HEAD` 且响应 body 读取字节数必须为零；BHA 同批应用入口
  去重为一次请求，Equibase 同 host 请求间隔至少 5 秒。route contract 必须绑定 robots
  evidence SHA、有效期、method、host/path、请求上限和最小间隔。
- robots evidence 必须与请求的 scheme/host/port 精确一致。目标 origin 返回 404 时，contract
  绑定该 404 状态、时间和 body SHA，并记录“未发布规则”；不得继承其他子域/父域的规则。

## 6. 持久化产物

宿主机 root：

`/opt/umanewsbot/runtime/upcoming_racecard_urls/`

容器 root：

`/app/runtime/upcoming_racecard_urls/`

每次成功发布生成不可变 generation bundle：

- `generations/<generation_id>/latest.md`：供人工录入使用的中文文档；
- `generations/<generation_id>/latest.json`：同一 canonical state 的机器 sidecar；
- `generations/<generation_id>/manifest.json`：两个文件 SHA、generation ID 与 schema；
- `current`：唯一原子切换的受控相对 symlink，只能指向 `generations/<generation_id>`。

人工固定读取：

`/opt/umanewsbot/runtime/upcoming_racecard_urls/current/latest.md`

完整 generation 在临时目录写入并 `fsync` 后原子 rename；最后一次 `os.replace(current)` 切换
整批。读取者只可能看到上一完整代或下一完整代。只保留当前与上一完整代作文件级回滚，不累计
无界历史；每一代每场仅有一个 URL。

产物包含：

- schema/version、启动/完成时间、窗口、调度时区；
- future expected 与 orphan 独立计数、地区/provider 覆盖、found/暂无/保留旧 URL/blocker；
- 每场稳定身份、地区、本地日期、provider、当前 URL 或“暂无”、原因、最后确认/检查时间；
- canonical payload、Markdown、JSON 与 manifest SHA-256。

不保存页面正文、HTML cache、马名、骑师、练马师、cookie、token 或响应 header。数据库
`TaskExecutionLog` 与应用日志只允许固定 error code、provider、计数和耗时；原始异常在内存分类
后丢弃，禁止把 `str(exc)`、URL/query、Location、header 或 body 写入日志。

## 7. 非目标与授权边界

- 不抓取或保存出马表内容，不写 `RaceEvent`、runner、participant、result 等业务表。
- 不公开文档，不新增前台/API 下载入口。
- 不启用 race-live scheduler、monitor 或结果发布。
- 实现完成不等于生产部署、网络 route 启用或 Celery beat 生效；这些动作在最新 code review 后
- 不绕过官方站点的 robots、条款、认证、验证码或限流。

## 8. 验收

- 离线测试证明可判窗 P0 全量、有界 orphan、窗口/DST、状态转移、幂等、旧 URL 保护、
  stale 防覆盖、generation 原子切换和无网络门禁。
- `current` 一次切换完整 generation；Markdown/JSON/manifest SHA 可复算。
- 容器重建后宿主机文件仍在；功能关闭时无网络、无文件写入。
- JRA、NAR、HKJC 无当前赛事也有契约测试；英国、法国、美国有正向/负向 fixture。
