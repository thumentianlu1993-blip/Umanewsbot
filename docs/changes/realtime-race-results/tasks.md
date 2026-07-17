# 准实时赛事赛果任务清单

## 0. 当前门禁

- [x] (operations) 初始 PLAN 基于 `9b617702`；离线 TDD 期间持续安全快进，当前 `HEAD == origin/main == 283bacf2cdc5ff97423b50ff46cfda2a87120a2b`；每次均核对主线直接影响并重跑专项回归。
- [x] (application) 只读审计现有赛事模型、runner/result importer、抓取编排、Celery/Beat、缓存和前台页面。
- [x] (integration) 联网核对 The Racing API 当前价格、计划、覆盖、频率、限速和条款；核对地区官方/第三方来源的当前可见能力与使用边界。
- [x] (operations) 固化本目录五份 PLAN artifacts。
- [x] (integration) 首次方案审核已在持久 reviewer 会话完成，结论 `REVISE`；九项 findings 已修订。
- [x] (integration) 复用同一 reviewer 会话完成两轮限定复审，九项 findings 全部关闭，最终结论 `APPROVED`。
- [x] (operations) 用户确认方案和六项产品决定；日本/香港等级范围按本轮修正，J-G1-3 允许在 proof 不达标时显式延期。
- [x] (integration) 原 reviewer 会话被运行环境回收且 `list_agents` 不可恢复；替代 reviewer 在完整交接后完成范围修正限定复审，两项 findings 已关闭，最终 `APPROVED`。
- [x] (integration) latest main 新增 receipt/chunk/current-year due 写入路径后，已更新真实代码复用与 handoff 方案；同一替代 reviewer 限定复审 `APPROVED`。
- [x] (application) 发布 mode resolver 已按真实 RED -> GREEN 实现；5 项目标测试和 3 项相邻回归通过，同一代码 reviewer 限定复审 `APPROVED`。

## 1. 离线开发准备（方案通过且历史任务交接前可做）

- [x] (integration) source terms、proof manifest/request budget 与 registry digest 的 fail-closed resolver 已按真实 RED -> GREEN 完成；纯函数不发送请求，实际 runner 接入仍待后续切片。
- [x] (application) 已实现完全离线 fixture contract harness：严格 metadata/许可/canonical SHA/Free endpoint/客观字段白名单，全程不发请求。
- [x] (integration) 已按当前官方公开 schema 用合成数据完成 The Racing API Free racecard/results contract tests；TRA results 固定 provisional，尚未保存或请求真实响应。
- [x] (application) 两阶段协议的离线 claim 与 checkpoint CAS 原语已按真实 RED -> GREEN 完成；owner/claim generation 与 token 不匹配均 fail closed，尚未接网络 runner 或 revision 投影 apply。

## 2. 历史任务安全交接与真实来源 proof

- [x] (operations) latest main 已记录第一期历史详情总账 `8032 = 6534 complete + 1491 evidence gap + 7 not_due`、global verifier `errors=0`、无 historical runner 且网络/功能开关关闭；来源 proof 的“历史先完成”条件已满足。shadow 前仍须单独生成精确 event ownership/lease/checkpoint/source registry/共享资源 SHA handoff。
- [x] (integration) handoff/ownership gate 已 fail closed：无显式 source permission 时不允许真实请求，无 tracking/owner/claim 时不能推进 revision/checkpoint；shadow 前仍需用真实 allowlist manifest 复核生产历史表/锁零变化。
- [x] (operations) 已为 The Racing API Free 固化精确 terms/proof registry：approved、用户确认自动化许可、官方文档/条款证据、有效期、registry digest 和最多 3 请求预算；其他 source 仍须逐项审核。
- [x] (integration) 已用受控 runner 完成 The Racing API Free 首个真实 contract proof：3/3 HTTP 200、regions 55、racecards 10、results 0；凭据仅从仓库外 `0600` secret 注入，raw/实体值不落盘，业务 DB 零写入。
- [x] (operations) 用户已提供 Free secret 的本地注入方式；当前不购买 Basic/历史/北美包。
- [ ] (integration) 对四个以上真实赛日执行低频 Free proof，生成覆盖、字段、延迟和失败报告；不写业务 DB。
- [ ] (integration) 对 JRA/NAR/HKJC/BHA/France Galop/PMU/Geny/Equibase/赛马场逐项完成技术和条款矩阵。
- [ ] (operations) 对 Sporting Life/Racing Post/HRN 等限制来源标记 manual/blocked；若需自动化，先取得书面许可/正式 feed。
- [ ] (operations) 用户审核 source proof report，决定首个 shadow 地区和是否满足 Basic 建议门槛。

## 3. 数据层和状态机

- [x] (application) 六态状态转移纯函数按真实 RED -> GREEN 实现；7 条合法边、非法跳级/倒退/未知状态测试和相邻回归通过，同一代码 reviewer 完整只读复审 `APPROVED`。
- [x] (application) Canonical 内容哈希纯函数按真实 RED -> GREEN 实现；严格 JSON、key-order 确定性、事实/数组顺序敏感、等价数字归一化、phase 排除和非法 payload fail-closed 测试通过，上轮唯一 P2 已由同一 reviewer 限定复审关闭，结论 `APPROVED`。
- [x] (application) ProjectionControl 基础所有权行按真实 RED -> GREEN 新增：显式一对一、fail-closed owner、generation/counters 和 `0033` migration；event allowlist P2 已关闭，两个 revision counter `>=1` 后续建议也已按真实 RED 修复；latest-main SQLite 目标/相邻/历史回归 `50/50`，等待限定复审。
- [x] (application) 状态机、participant/source identity、observation/revision/evidence、owner transfer、revision pointer/allocator 与 host budget 已逐切片取得真实 RED 并 GREEN。
- [x] (application) 已新增 live tracking、ProjectionControl、participant/source identity、observation/revision/evidence link/host budget 模型与 `0033`-`0038` 前向迁移；PostgreSQL-only deferred constraints 仍待集成层。
- [x] (application) append-only observation recorder 已实现：内部计算 canonical SHA，同 source/hash/phase 重放不覆盖首次 evidence，迟到响应只留 observation、不推进 revision/pointer。
- [x] (application) 实现纯函数状态转移、source authority、canonical hash 和 conflict policy；supplemental/official/corrected/replay/manual-lock 规则均有 fail-closed 测试。
- [x] (application) official authority 已绑定持久化且 approved 的 source identity，调用方不得提权；shadow revision 可通过唯一 publication audit 单向晋级公开，SQLite 与 PostgreSQL 直接路径均 GREEN。
- [ ] (application) 实现共享 arbitration service，并让 chunk importer、historical candidate apply、通用 candidate apply、后台 inline/人工和 live apply 全部接入；非 live-owned 赛事保持既有结果语义。
- [ ] (application) 扩展新 receipt completion/verifier 绑定 owner generation、revision IDs/content hashes；保留旧 receipt legacy 兼容且不伪造历史 revision。
- [x] (integration) PostgreSQL owner generation/CAS、并发 revision、deferred constraints 与重放已 GREEN；last-known-good 回滚、同着/DQ/DNF/空马号/人工锁的完整投影组合仍待补齐。
- [x] (operations) 已实现 `initialize_race_live_events`：严格 schema v1、manifest SHA/approved commit、赛事更新时间与人工锁门禁，默认 dry-run，显式 `--apply --confirm-apply`，独立 `--verify`，全 manifest 单事务、精确 replay 与逐赛事唯一审计；migration 仍不隐式回填。生产 manifest/event IDs 尚未生成或应用。
- [x] (application) 新增持久化 publication policy/event allowlist/coverage proof 版本和唯一 admission service；offline/TRA runner 不再接收 `project_current`，supplemental 低层旁路被阻断。
- [x] (application) admission 以获准 racecard revision 的参赛全集、真实 participant review 状态和 runner/result 人工锁计算完整性；已知退赛/非完赛状态保持客观语义。
- [x] (application) 在模型、数据库 constraint 和 apply 三层固定 `the_racing_api => supplemental`，publication audit 绑定 registry/coverage digest。
- [ ] (application) 新增地区级 official marker contract/evidence 与 corrected source/event gate；首次官方差异为 official，已有 official 后变化才为 corrected。
- [ ] (application) 官方复核 incident 已在 provisional admission 时按 route/version、off-time+2h 幂等创建；告警、恢复/升级和 T+24h/T+72h/T+7d 探针仍待实现。

## 4. 调度和隔离

- [x] (integration) host limiter、轮询窗口、claim/checkpoint、Beat selector route、circuit 和 retry policy 已 RED -> GREEN；临时 PostgreSQL+Redis 下真实 broker/独立 worker 隔离 smoke 通过。
- [x] (application) 每分钟轻量 selector 与时间窗算法已实现：默认 scheduler off，batch cap + `skip_locked` 领取并阻止 active lease 重复派发。
- [x] (application) `poll_race_live_event_task` 已固定 route 到 `race_live` 且当前 fail closed；三份 Compose 已增加独立 worker，普通/live queue 显式隔离，live 默认并发 1、prefetch 1、soft/hard time limit 45/60 秒。
- [x] (integration) 离线 fixture runner 已完成 parse -> observation -> shadow revision -> checkpoint 端到端；受控路径、原始字节 SHA、bounded retry 和 offline 永不公开均有 RED/GREEN。真实 broker 与 HTTP adapter 仍待门禁。
- [ ] (application) DB 共享 host reservation/outcome/circuit 已接入真实 TRA runner；Redis 快速层、同批多 event endpoint cache 和条件请求仍待实现。
- [x] (application) 短事务 claim、claim TTL/generation、无锁网络 runner、返回 checkpoint 双 CAS 和 revision 投影 apply 已实现；网络后过期/被替换 lease 不推进 revision 或公开投影。
- [x] (integration) 隔离 PostgreSQL+Redis 真实 broker smoke 已证明 selector -> `race_live` worker 端到端和普通 `celery` queue 不被 live worker 消费；未挂载或读取历史 runtime。生产历史表/锁零变化仍需 handoff 后 shadow preflight 复核。
- [ ] (operations) 为全局/地区/来源/赛事写唯一发布 mode `off|shadow|provisional_public|official_public`；effective mode 取所有适用 cap 最小值，任一 off 为硬门，下层不可提权，未知/冲突/过期 fail closed。

## 5. 地区 adapters

- [ ] (integration) 逐 adapter 先补 racecard/scratch/provisional/official/corrected/schema drift fixtures 和 RED。
- [ ] (application) The Racing API 暂定赛果单 event 主 adapter 已实现并只提取客观字段；完整且身份无歧义时可在 `provisional_public` 下立即投影。当天响应的多 event 批量复用尚未实现，因此本项在缓存/去重完成前不标为全部完成。
- [ ] (application) 在同一门禁通过后实现首个 shadow 地区官方复核 adapter（默认英国 BHA；若 proof 决定则为 HKJC）。
- [ ] (application) 在条款许可门禁通过后依次实现 HKJC、JRA/NAR、France Galop、美国赛马场/Equibase 异步官方复核 adapters；它们负责 official/corrected，不阻塞 TRA provisional 首发。
- [ ] (integration) 每地区 identity/字段/延迟/失败降级 contract tests GREEN。
- [ ] (integration) 日本 J-G1-3 默认进入原始目标池；独立 proof 覆盖 90 天全部合资格赛事、至少 3 场及窗口内各实际等级，不足延长至最多 180 天。
- [ ] (integration) 按 source/identity/status/字段/延迟门槛生成 original/active/deferred 报告；只有客观失败证据和用户批准、未过期的 deferred artifact 才允许 selector 精确排除，不阻塞 G1-3/JpnⅠ-Ⅲ。
- [ ] (operations) 未获许可或不稳定来源保持 manual/blocked，不写占位 production adapter 绕过门禁。

## 6. 页面、后台和监控

- [x] (application) 已取得 provisional/official/corrected/stale/conflict 页面真实 RED；后台权限 RED 仍待补。
- [x] (application) 已增加赛事页状态 badge、来源类别、更新时间和更正提示；shadow 不泄漏，不复制专有内容。
- [x] (application) 增加运营后台 control/tracking/source/participant/observations/revisions/conflicts/publication/host budget 只读入口与 CAS kill switch；manual correction 保持禁用，须在共享 arbitration/权限另行完成后开放。
- [ ] (integration) 增加事件 cache version/invalidation 测试，Redis 故障下 DB 正确性不变。
- [x] (application) 增加默认关闭的公开详情读取门；任一适用 mode off 时立即隐藏已有 published live badge 和当前物化赛果。独立结果列表/sitemap/cache invalidation 仍在后续性能/读取面验收。
- [ ] (operations) 增加指标、聚合告警、dashboard 和每场 acceptance summary。
- [x] (integration) 安全测试覆盖 secret 权限、固定 host/path 与公网 DNS、redirect、响应上限、不落 raw、registry/条款/automation digest、HTTP/schema 和迟到 lease。

## 7. 验证与审核

- [x] (integration) 最终 finding 修复后目标 SQLite 准实时 `116/116`；latest-main 历史相邻模块组合 `252/252`（1 skip），均单独记录。
- [x] (integration) PostgreSQL `skip_locked`、host 串行预约、同 claim revision 单写、deferred pointer/supersedes guards 与迁移往返已单独 GREEN；真实 Redis broker queue integration 也已通过隔离 smoke。
- [x] (integration) 完整 stable 已运行：`1837` 项中 `2 failures / 13 errors / 23 skipped`；干净 `origin/main@c40a8c2b` 精确复跑同一 15 项得到完全相同结果，确认为主线基线问题。专项/latest-main 组合 `249/249`（1 skip）；Django check、migration drift、三份 Compose config、脚本语法和 `git diff --check` 通过。
- [x] (integration) 最终原生 review 的日历 N+1 P1 已取得真实 RED：40 场为 `525` queries；批量读取门修复后以 `<=12` 硬门禁 GREEN，公开状态 `6/6`、SQLite 专项 `160/160`、PostgreSQL `5/5`。
- [x] (integration) 最终候选镜像 `sha256:4a281e426e32...5b099` 已通过镜像内 check、初始化器+TRA runner `13/13`、registry/secret 检查；完整源码树、Compose、脚本、migration drift 和 diff 分层门禁通过。
- [x] (integration) latest main 单父整合已保留赛事身份锁修复/生产事实：SQLite 组合 `180/180`（1 PostgreSQL skip）、临时 PostgreSQL 精确目标 `6/6`、整合镜像 `sha256:87f8603320f8...73bcf` 的 check/`13/13`/registry/no-secret 通过；等待同一 reviewer 复审整合 diff。
- [ ] (integration) 压测 selector、host batch 去重、慢源/circuit、web p95 和新闻队列回归。
- [x] (operations) durable artifacts、current state、project status、decisions 与 deploy runbook 已按 latest main、验证证据和候选发布/回滚契约更新，纳入最终 review scope。
- [ ] (integration) 派未参与实现的 reviewer subagent 建立代码 reviewer 会话并实际执行只读原生 review；actionable findings 清零。
- [ ] (operations) 最新成功 review 后等待用户对当前任务的发布授权；授权前不 commit/push/PR/部署/迁移/生产写入。

## 8. 分阶段 rollout

- [ ] (operations) Source proof：历史 handoff 后、逐源联网许可门禁通过；全部只读、无业务 DB 写、无付费订阅。
- [ ] (integration) 本地模拟：fixture/clock/故障注入和 PostgreSQL 完整链路。
- [ ] (operations) 单地区 shadow：默认英国，公开投影零写入，至少 10 场/3 场重点赛事。
- [ ] (operations) 五地区 shadow：只有联网许可通过的地区可计作真实 shadow；未通过者仅做 fixture/人工验证，明确不计入 shadow 通过数。
- [ ] (operations) 暂定赛果灰度：精确赛事 allowlist，badge/告警/rollback 验收。
- [ ] (operations) 正式赛果灰度：只有官方来源许可和 official marker 验收通过的地区。
- [ ] (operations) 正式公开：用户在最新 review 后授权，先迁移/worker shadow，再按 allowlist 扩大。
