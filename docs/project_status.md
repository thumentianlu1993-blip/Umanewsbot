# 项目状态文档

## 2026-07-19 event 924 kill-switch 演练完成

- event `924` 的预生成 disable 和 restore manifest 均重新完成
  dry-run/apply/verify，所有步骤 `ok=true`、唯一 event `[924]`、零网络请求。
- disable 后详情隐藏全部 live result 标识，日历保留赛事但隐藏赛果摘要；restore 后中文
  暂定标识、1–7 详情和日历前五摘要恢复。两次切换均保留 revision、publication、legacy
  result、observation、marker evidence 和 resolved incident。
- 最终 event policy 为 `provisional_public v4`，allowlist 仍只有 event `924`；
  scheduler false、tracking 停止、两个 Celery 队列为 0，live worker active/reserved
  为空，健康检查 200。当前灰度继续公开，未扩展其他赛事。
- event `924` 的 promotion 后 15 分钟新 probe 仍未发生，不能追溯补证。用户已决定由
  下一场获准公开灰度赛事重新执行该 SLA 验收；下一场未通过前不得把本次记录解释为
  15 分钟能力已验收。

## 2026-07-19 event 924 暂定赛果单赛事公开灰度首次上线记录

- 冻结提交 `91cf50ad677a1b8c9b253528c9db98481fd1031a` 已进入生产，四个 app service
  统一运行 image `sha256:700ea786…087ef`；`stable.0046`、健康检查和回滚点均已验证。
- QQ SMTP 真实投递成功后，event `924` promotion dry-run/apply/verify 全部通过。
  当前仅 event `924` allowlist 生效，四层 policy 为 `provisional_public v2`，
  scheduler 仍为 false，tracking 已停止，不会扩展到其他赛事。
- promotion 前 BHA 截图中的官方 1–7 名次与 TRA 暂定结果一致；其 receipt 在 promotion
  后应用并把 incident 写为 resolved，但截图早于 promotion，不能证明“promotion 后
  15 分钟内新浏览器探测”。该 SLA 验收仍未完成，页面继续明确标记“暂定赛果”。
- 首次上线收口点的详情页和日历 HTTP 验收通过；当时 disable kill-switch 只完成
  dry-run，尚未实际隐藏、验证和 restore。后续完整演练现已完成，结果见上方最新状态；
  historical runner 仍为 `migration_safe`，常驻历史开关关闭，race-live queue 为空。

## 2026-07-19 event 924 代码 review finding 已修复，待限定复审

- 候选变更基于当前 `origin/main@353464c7` 的独立 worktree，实现 event `924` 已存
  shadow result 的无网络 promotion、精确 disable/restore、页面“冠军 · 暂定”、客观
  racecard fallback，以及 BHA manual official receipt 的 match/conflict/unavailable
  闭环。
- operator promotion 与 runner 复用同一 admission core，但不伪造 claim/checkpoint；
  policy、allowlist、projection、incident 和 tracking stop 位于同一事务。scheduler
  默认仍为 false，Compose 没有增加 worker 或扩大赛事范围。
- 首次独立 code review 结论为 `REVISE`；2 项 P1、1 项 P2 已完成真实 RED/GREEN：
  receipt 硬限 event 924、unavailable 真实邮件 SENT/FAILED/retry、manual dry-run/apply
  共用 locked planner。随后两项直接 P1 也已用真实 RED/GREEN 修复：告警按 incident 跨
  receipt 去重；probe/receipt operation/QUEUED intent 先原子 commit，SMTP 后置于独立
  delivery transaction，主事务晚期写入或 commit 失败均零 SMTP。
- SQLite 合并聚焦 `226` 项（`224` 通过、`2` 项 PostgreSQL-only 跳过）；PostgreSQL
  durable intent/并发新增 `2/2`、既有锁/竞争 `22/22`；migration `0046` 往返、
  Django/migration drift 和三份 Compose 校验均通过。
- 这是“全部已知 finding 已修复、待同一 reviewer 限定复审”的状态，不是生产发布或
  event `924` 已公开。
  当前未提交、未部署、未联网、未写生产；最新成功代码 review 和其后的精确发布授权仍是
  后续硬门禁。

## 2026-07-19 新五地区新闻抓取代码复审已通过，待用户授权

- `codex/add-new-region-news-sources-integrated` 已在独立 worktree 完成爱尔兰、加拿大、阿联酋、沙特和
  澳大利亚五个独立新闻地区及五个默认关闭来源的本地候选；补救方案两轮复审已批准，真实
  结构/许可/透明 UA/XML/结构化 HTTP 的 RED-GREEN 已完成。
- 最新完整指纹的原生代码审查首轮为 `REVISE`：既有 `other` 赛事/马匹无法通过表单保存，
  Ireland 来源关键词 `hri` 会误命中 `thrilling`。两项均先取得真实 RED，再以表单专用
  旧五区加 `other` choices 和边界感知关键词匹配最小修复；没有扩大赛事、马匹或 race-live
  执行地区。
- 同一原生 session 对 fingerprint `def49ae…d9e` 的限定复审再次为 `REVISE`：Django
  `RaceEventAdmin` 仍暴露五个 news-only 地区，测试文档顶部计数仍为旧值。Admin 缺口先用
  真实 `ModelAdmin.get_form()` 取得 `1` 项内 `2` 个 failure，再复用受限地区集合修复；
  文档摘要已同步。
- 当前专用 `55/55`，新地区/归属/法国时间组合 `155` 个通过加 `1` 个既有 skip，相邻加
  旧爱尔兰合同 `70/70`，event 924 最新邻接
  `200` 个通过加 `2` 个 PostgreSQL-only skip。
- 候选已同步最新 `origin/main@566a9b10`；本 change migration 因主线占用 `0046` 顺延为
  `0047`。完整 `stable` 的剩余 `12 ERROR / 2 FAILURE` 已在干净主线精确复现，属于
  current-year CSV、缺失 tmp helper 和既有 historical runner 基线问题，不是本 change
  新增回归。
- JCSA、Racing Victoria 的受控补救在线复测都仍为 technical `deferred`；已保存的 JCSA
  当前详情可在修复后离线解析，RV 真实斜杠日期路径也已进入严格 fixture，但请求预算已用完，
  不重复联网。HRI、Woodbine、ERA permission 为 `blocked`，JCSA/RV 为 `unknown`，当前
  没有 `eligible` 来源。
- 同一 reviewer/session 的第三次限定复审已通过：前后 fingerprint
  `83675edc…b1353` 一致，`VERDICT: APPROVED`，无 P0/P1/P2 actionable finding。该冻结
  版本仍未 commit、push、PR 或 deploy，后续必须取得用户针对本版本的新授权。
- 这是本地候选，待用户决定后续，不是已上线。五来源仍
  `enabled=false / production_approved=false`，全局归属和 source-scoped candidate 均默认
  关闭；未 commit、push、deploy 或生产验证，生产状态未改变。
- 临时 PostgreSQL、390px 和 Compose 尚未验证，不能宣称五区来源齐备或生产可用。
- 正式候选只位于
  `/Users/mentianlu/Code/umanews/.worktrees/add-new-region-news-sources-integrated`；旧同名
  worktree 是错误全局 stash 的隔离现场，不参与后续 review 或发布。

## 2026-07-18 event 924 首个 TRA shadow 赛果到达

- 已在 scheduler false、四层 policy shadow、tracking/allowlist 仅 `[924]` 的边界内完成
  有界手动轮询。写前恢复点 `efa68a76…fd13b` 已通过 `pg_restore -l`。
- generation 2–14 为 `13` 次无网络 `pre_off_wait`；generation 15–18 在预计开跑后按
  3 分钟窗口返回 `result_not_found`；generation 19 的 task `9615a5f6…432b` 于
  `14:14:42.301344Z` 获得首个 shadow result，距 `14:02:00Z` 预计开跑
  `12` 分 `42.301` 秒，控制循环随即停止。
- observation ID `1`、result revision ID `2` 已写入，7 匹均为 finished 且名次 1–7
  完整，无 parse warning；tracking 为 `provisional_result / shadow_applied`。
- publication、legacy result、official marker/incident 均为 0；公网仍无 participant 或
  赛果标签，healthz 为 200，live queue/worker/one-off 为空。scheduler 仍为 false，
  `14:24:42Z` 后续探针不会自动执行。
- 上述“worker 为空”只表示 live worker 的 active/reserved task set 均为 0；
  `race_live_worker` 节点本身仍在线并运行 `the_racing_api_free`。
- 本轮授权已消费；下一步须先审核本次真实 observation，再对后续复核或 provisional public
  灰度取得精确授权，不得扩展其他赛事。

## 2026-07-18 event 924 TRA shadow worker 启动检查通过

- 已只为 `race_live_worker` 启用 `the_racing_api_free`，scheduler 继续 false；tracking 和
  allowlist 唯一 ID 均为 `924`。写前数据库备份 `bc06babe…6207` 与逐字节一致的 `.env`
  备份已验证。
- 在合法 due 点后，实际 Celery task `7ba0699c…7ff0` 通过 live queue 执行并返回
  `SUCCESS / pre_off_wait`；claim 已释放，next poll 为 `11:33:04Z`，HostBudget 未变，
  因而没有提前请求 API。
- 赛果、observation、publication、incident 和公网 shadow 泄漏均为 0，队列/active/
  reserved/one-off 为空，healthz 为 200。下一步需单独授权 event 924 的有界 shadow
  轮询；scheduler 关闭期间不会自动执行 next poll。

## 2026-07-18 event 924 shadow baseline 初始化完成

- 精确 manifest `ee9d0d43…1432` 的 initializer dry-run、单次 apply 和独立 verify 均为
  `ok=true / error_count=0 / 1 event / 7 participants / replayed=0`；新写前备份
  `e57218e7…70fe` 为 custom-format、`0600` 且通过 `pg_restore -l`。
- event `924` 已获得 London `15:02` 开赛时间、live owner generation 1、7 匹 approved
  participant、1 个未发布 racecard revision 和四层 shadow policy；赛果、observation、
  publication、official marker/incident 仍为 0。
- 公网页面只新增客观开赛时间，不泄漏 shadow 出马表或赛果标识。scheduler false、runner
  disabled、live queue/one-off 为 0；下一门禁是单独授权 event 924 的 TRA shadow
  runner 启动检查，不得重复 initializer 或直接公开。

## 2026-07-18 event 924 已生成成功 racecard manifest，尚未初始化

- 用户授权的单次退避重试已完成；有效 run
  `production-racecard-gb-924-grade-retry-20260718T093207Z` 的 today/tomorrow GB
  请求均为 200，`completed=true / request_count=2 / blockers=[]`。
- manifest SHA-256 为 `ee9d0d43…1432`，精确绑定 event `924`、
  `rac_13000002795`、伦敦时间 `15:02` 和 `7` 匹 declared participant；companion
  hashes、`0700/0600` 权限和禁止字段检查通过。
- prepare 没有修改 event 或 live 业务事实：`9,867 / 100,132 / 91,897` 守恒，全部 live
  事实表、policy/allowlist、队列和 one-off 为 0；HostBudget 的 429 失败状态已清零。
  initializer、shadow、scheduler、runner 和公开仍未执行或开启，下一步需对精确 manifest
  单独授权。

## 2026-07-18 英国 Group 后缀修复已生产发布，prepare 被 429 阻断

- 冻结提交 `ebab4aa8` 已快进 `main` 并部署，四个 app service 统一运行 AMD64 image
  `sha256:4443a9c…55dc`；Django、迁移、镜像 racecard sync `20/20`、挂载隔离、内外
  healthz 与 Celery ping 通过。写前备份 SHA-256 为 `17ba9ccb…db0`，`pg_restore -l`
  通过，旧镜像与环境回滚点已保留。
- scheduler false、runner disabled、公开 policy/allowlist 为 0、live queue 为 0。生产
  `9,867 events / 100,132 runners / 91,897 results` 和全部 live fact 表均未改变。
- event `924` 新 prepare 的 today GB 请求为 200，tomorrow GB 请求为 429，因此
  `completed=false / blocker=http_429`。blocker artifact 无 manifest，未执行 initializer
  或公开；下一次联网重试需要新授权，成功 manifest 仍进入单独审核。

## 2026-07-18 英国 Group 后缀精确匹配实现完成

- 只读生产镜像诊断确认 event `924` 的 TRA 唯一候选存在，上一轮零命中的唯一身份格式差异
  是来源赛事名末尾 `(Group 3)`，不是 API 覆盖缺口；诊断没有保存 raw、写数据库或生成
  可 apply artifact。
- 新增行为只覆盖英国 `normalized_grade=G1/G2/G3`：从既有获准名称精确派生
  `group 1/2/3` suffix；零 token 才派生，唯一 terminal 同级 token 不重复，异级、非末尾
  或多个 token 整条排除，非 G1-G3 和其他地区维持原语义。
  精确匹配、日期、赛场、唯一性、HostBudget、artifact 和 initializer 门禁均未放宽。
- 真实 RED 为 `racecard_not_found`；首次代码 review 的非末尾/多 Group token P2 也已先补
  3 个失败 subtest 再修复。GREEN 后聚焦 `7/7`、完整受影响 SQLite `210/210`、临时
  PostgreSQL 16 锁/竞争 `6/6`，Django、迁移、语法和 diff 门禁通过。当前待同一 reviewer
  限定复审；未提交、未部署、未重跑生产 prepare，全部准实时与公开开关仍关闭。

## 2026-07-18 准实时 racecard 增量已生产发布，英国首轮 prepare fail closed

- 冻结提交 `6646302b80c90cf406075516ab4812f2f4ebee18` 已进入 `main` 并部署生产，四个
  app service 统一运行 image
  `sha256:7f188f8fc85979ad6df3504c49e42aed4e0c41696f64301b2a33c6c888722981`；新 registry
  digest `60fcc081...ad402`、artifact/secret 挂载隔离、Django/migration/model drift、镜像
  目标测试 `20/20`、Celery ping 与内外 healthz 均通过。
- scheduler/runner/public policy 继续关闭。英国 event `924` 的受控 production prepare
  请求 today/tomorrow GB racecards 均为 200，但严格身份匹配返回
  `racecard_not_found`；blocker run 没有 manifest，因此没有运行 initializer，也没有写入
  赛事时间、participant、racecard、tracking 或赛果。
- 生产业务总量保持 `9,867 / 100,132 / 91,897`，全部 live 事实表仍为 0，仅 HostBudget
  为 1。下一步是对 event 924 的来源覆盖或赛事别名做独立身份审核；修复后重新 prepare，
  成功 manifest 仍需单独批准才可 initializer apply。

## 2026-07-18 准实时赛前 racecard/off time 同步实现完成

- 基于最新 `main@23435897` 的独立 change 已实现英国 TRA Free today/tomorrow racecard
  prepare、精确赛事绑定、Europe/London 开赛时间、schema v2 原子初始化、动态
  HostBudget、companion SHA 和 pre-off claim checkpoint；方案审核已 `APPROVED`。
- SQLite 准实时/初始化/来源/相邻历史组合为 `203/203`，一次性本地 PostgreSQL 16 的
  新旧初始化、竞争 manifest 与 runner 锁语义为 `6/6`；Django、迁移、Compose、语法和
  registry SHA 门禁通过。新 registry digest 为 `60fcc081...ad402`，无模型或迁移变化。
- 首次代码 review 的 artifact 并发误删与 event 占用 N+1 两个 P2 已用新 RED 修复：
  发布失败只清理本调用拥有的 inode，40 场占用检查改为固定批量查询；限定复审待执行。
- 本变更仍处于独立代码 review 前：未提交、未发布、未真实联网、未连接生产写入，也未
  开启 scheduler、runner 或 provisional public。生产仍运行上一安全基线，首次英国
  prepare 和 schema v2 初始化必须等最新 review 后的新用户授权。

## 2026-07-18 历史赛事公开状态

- `8,867` 个已导入且完整的历史目标已全部公开，五区分布为日本 `2,239`、中国香港 `473`、英国 `2,144`、法国 `652`、美国 `3,359`；eligibility、dry-run、apply 和独立 verifier 均为零错误。
- 生产当前为 `9,867 events / 9,820 published / 8,867 published+complete / 100,132 runners / 91,897 results`。五区浏览器验收、移动端、出马表顺序、赛果、历届、中文术语展示和距离单位展示通过。
- 最终运行 revision 为 `4af5e20a`，四个 app 服务统一使用 image `sha256:111dbe46...8d7a`；公网 healthz、赛事列表和详情为 200，队列为空。历史常驻写门和网络门、准实时 scheduler/runner 继续关闭。
- 正式总账仍为 `30,917` 条，其中另有 `20,544 pending / 1,467 source_unavailable / 31 identity_review_required / 8 ready`。这部分是后续抓取范围，不影响本轮 `8,867` 场已完成赛事的公开状态。

## 2026-07-18 准实时赛果生产安全基线已发布

- 用户授权的最新整合冻结版本 `4f11b227` 已部署；生产 tree `277cb10a...54c8`，web/普通 worker/Beat/独立 `race_live_worker` 均运行 image `sha256:c2b9e15e...03966`，迁移已从 `stable.0032` 前进至 `stable.0045`。
- 写前数据库备份 SHA-256 为 `f81a11ec...2a01`，`pg_restore -l` 通过；旧 image `sha256:63cdfc13...7329`、环境备份和精确回滚标签已保留。Django check、migration drift、镜像聚焦 `13/13`、registry/no-secret 检查及 HTTP healthz 通过。
- live scheduler 与 runner 分别保持 `false / disabled`，live 业务表和 `race_live` 队列均为 `0`；来源 proof 的 3 个固定端点均为 200，当前得到 `55 regions / 69 racecards / 50 results`，未保存 raw payload 或写业务 DB。
- 首轮 shadow 因生产赛程时间缺口未启动：未来 `428` 条赛事、英国 `72` 条的 `race_datetime` 非空数均为 `0`。严格初始化器会拒绝无法精确匹配开赛时间的 manifest；下一步必须先以独立受审增量补齐赛前 racecard/开赛时间同步，不能手工猜时间或直接打开 runner。

## 2026-07-18 AI 赛事身份决定已生产完成

- `267` 条 AI 初审决定已经受控落库：`228` 个正向关联、`24` 个去重负向系列对，另完成 John C. Harris Stakes 草地修正。业务 manifest `cf5e220e...a0147`、actions `9622460e...f53da1` 和 approval `f02b0e4c...0584` 保持不变。
- 首次 PostgreSQL apply 在任何业务写入前暴露 nullable outer join 锁错误；零写入核验后完成基表定向锁修复、真实 RED、相关 `52/52`、生产只读锁 smoke 和同一 reviewer 限定复审。最终 revision `f396d048`，生产三服务统一运行 image `sha256:63cdfc13...7329`，无迁移。
- 最终写前备份 SHA-256 为 `640791685f14d82cd8a47a9c83ce2b6fb4a361e8edafa824c9c2e6338c892707`，`pg_restore -l` 通过；apply result `20fb0462...3365`、rollback ledger `0a37af37...31e5`、独立 verifier `ok=true / error_count=0`。
- 写后为 `9,867 events / 100,132 runners / 91,897 results / 9,103 linked targets / 228 relations`；前三项完全守恒，OperationLog ID `96353`。John C. Harris event `507` 为 `turf`。
- web/worker/beat、内外 HTTP healthz、worker ping、队列、事务和日志均正常；历史公开、常驻历史网络和写入开关继续关闭。生产磁盘清理后约剩 `3.07 GiB`。

## 2026-07-18 准实时赛果生产 shadow 初始化器已完成

- 新增严格 manifest 驱动的 `initialize_race_live_events`：默认 dry-run、显式 apply、独立 verify、全事务和精确 replay；初始化范围仅为 shadow 的 control/tracking/source/participant/racecard/host budget/policy/allowlist/audit，不在 migration 隐式回填。
- shadow runner 的 `shadow_only` 现在是成功 checkpoint，不再累计失败；仍保持公开物化、publication 和 official incident 为零。SQLite 聚焦 `13/13`、PostgreSQL 初始化并发及既有锁语义 `5/5`。
- 首次成功原生完整 review 关闭既有 findings，另发现赛事日历 live read gate 的直接 P1：40 场页面为 `525` 次查询。真实 RED 后已改为固定批量读取，新增硬门禁 `<=12`；公开状态 `6/6`、准实时/来源 proof/初始化 SQLite `160/160`、临时 PostgreSQL `5/5` 通过，同一 reviewer 限定复审 `APPROVED`。因 `main` 随后新增赛事身份生产修复与证据，当前基于 `ccb56f7d` 的整合树仍需复审和新授权；生产未迁移、未初始化、未启动 live worker、未公开。
- 合并前候选镜像 `sha256:4a281e426e32...5b099` 已通过镜像内 check、初始化器+TRA runner `13/13`、registry SHA 和无凭据检查；三份 Compose、worker shell、迁移漂移与 diff check 在完整源码树通过。部署契约测试依赖仓库根 Compose/源 registry，继续只在完整源码树运行，不为镜像自测复制非运行时文件。
- 基于最新 `main@ccb56f7d` 的单父整合已完成：SQLite 准实时/来源/初始化/赛事身份组合 `180/180`（1 项 PostgreSQL 专用 skip），临时 PostgreSQL 精确目标 `6/6`；整合候选 image `sha256:87f8603320f8...73bcf` 的 check、初始化器+TRA runner `13/13`、registry/no-secret 检查通过。等待同一 reviewer 对 main 增量、冲突解法和直接路径复审。

## 2026-07-17 AI 赛事身份初审已形成生产候选

- 已正式采用 AI 初审的 `267` 条决定：`228` 条合并并关联、`21` 条保持独立、`18` 条非同赛／忽略；John C. Harris Stakes 另有一条 `surface=turf` 修复。正向决定保留来源系列，负向决定写入双向禁止自动合并规则。
- 执行代码 commit 为 `8b9b9755`，最终相关测试 `50/50`、Django check、迁移和 diff 检查通过；同一 reviewer 最终批准，无剩余直接 P0/P1。
- 生产只读 prepare 已完成：artifact 为 `/opt/umanewsbot/runtime/race_series_identity_review/prepare-8b9b9755-20260717_205349/artifact`，manifest `cf5e220e...a0147`、actions `9622460e...f53da1`，verifier 为 `ok=true / error_count=0`。对 228 个正向系列对的只读审计无同年目标冲突、既有关联冲突或第三方占用。
- 当前仍是 pending approval，生产数据库没有执行本轮写入；生产运行镜像仍为 `213a818c`。待用户针对当前 commit+manifest+actions 明确授权后，执行精确部署、新备份、dry-run、串行 apply 和逐项 verifier；历史公开保持关闭。

## 2026-07-17 赛事总账/公开赛程关联工具已发布，关联写入待身份审核

- 已完成 `reconcile-race-event-coverage` 本地实现和零问题复审：允许 `not_due` 安全采用唯一既有赛程，新增历史/当前/赛果三层报告、不可变 artifact、approval 双 SHA、原子 apply/rollback 和 verifier。
- 相关测试 `101/101`、Django check、迁移漂移和 diff check 通过；无模型或迁移变化。
- commit `213a818c` 已合入 `main` 并部署；生产 web/worker/beat 统一运行 image `sha256:f3b2d4625322e7f96554288d4b710723ff9d01323dd3be654bcbc2ba0281a9d9`，无迁移，healthz 与赛事页正常。部署前数据库备份 SHA-256 为 `7958873ff243f5a3c1bb85075f74fa0daec6a040f33688b31f63db71e1eb0e3b`。
- 有效生产只读 manifest 为 `5caee7d0ed093605aede28c2834d3acf8a75f9f20e2d88679924c3670f3c6a51`，verifier 无错误；`30,917` 个目标分为 `8,875 already_linked / 46 identity_conflict / 21,537 missing_event / 459 status_conflict / 0 exact_link`。因此 approval 保持 pending，本轮没有数据 apply。
- `7` 是 not_due，不是未举办总数；全账本另有 `459 not_held / 15 cancelled`，2026 还有 `630 missing_event`。东海锦标等线上赛程与英文总账被拆为不同系列，另有跨地区同名误命中，需先完成系列身份审核。
- 可读审核入口为 `outputs/race_event_reconciliation_20260717/生产赛事身份审核_213a818c_20260717.xlsx` 与 HTML，包含 46 条明确冲突、221 条别名/跨语言候选、冠军马、1号马、来源和线上页面。身份确认后重新生成具有明确动作的新 manifest，再执行备份、串行 apply 和逐目标 verifier；历史公开继续关闭。
## 2026-07-17 准实时赛果来源路由产品口径修正

- The Racing API 调整为覆盖范围内的暂定赛果公开主链：完整结果通过身份/字段门禁后可在官方二次复核前发布，并明确标注 provisional。
- JRA/NAR/HKJC 等官方来源继续异步复核并决定 official/corrected；TRA 不获得 official authority，空结果、缺马、身份冲突、人工锁、条款和发布 mode 门禁不放宽。
- 首轮方案复审提出的唯一 publication admission/read gate、TRA supplemental 数据库约束、racecard 全集完整性、不可变 official marker、异步 incident 闭环和 `0041` 迁移口径均已补齐；同一 reviewer 限定复审逐项关闭并给出 `APPROVED`。用户已授权进入测试先行、实现、shadow 与上线准备；实际生产发布仍须在最新成功代码 review 后取得一次新授权。当前没有本轮新增的网络 adapter、生产写入、部署或公开开关变化。

## 2026-07-17 准实时赛果首个 TRA Free 来源 proof 已完成

- 新增受控、脱敏、业务 DB 零写入的 The Racing API Free proof runner；仓库外 `0600` secret 已验证可用，不进入工作树/镜像/日志/artifact。
- 首个成功窗口完成 3 个 Free 请求：regions 55、racecards 10、results 0，均 HTTP 200。reviewer P2 指出的 proof/长期 automation 许可耦合已用真实 RED 修复并通过限定复审；完成时间与 unknown 状态两个后续建议也已按 RED 修复，无效时钟和无 partial artifact 契约已补自动化。离线 proof + 准实时 `126/126`，合并 latest-main 相邻历史回归 `262/262`（1 skip）。
- 当前只确认认证、端点与 schema；尚未取得已完赛样本或四赛日数据，覆盖、暂定/正式分类、p50/p95 和 Basic 升级门槛均未通过。无部署、生产写入、订阅采购或公开开关变化。
- proof runner 与后续时钟/unknown 状态增量已完成复审。已启用本地 `tra-free-proof` 每日低频 automation 收集四个不同赛事日期；达到四日且至少一个非空 results 窗口后不再联网，等待主任务汇总。automation 不写 tracked 文件或业务 DB。

## 2026-07-16 第一期历史赛事正式详情总账完成

- `1998–2026` 正式详情范围已固定为 `8032`，最终 `6534 complete + 1491 evidence gap + 7 not_due`；生产共有 `6534 events / 70314 runners / 65227 results / 6534 winners`，global verifier 为 `8032 checked / 0 errors`。日本、中国香港、法国 hard 范围完整；英国历史 hard 为 `708 complete + 45 evidence gap`，英国新正式为 `94 complete + 1 gap + 4 future`，美国新正式为 `195 complete + 1 future`；英美历史 G2/G3 按批准的 best-effort 口径收口。
- France 14 场和 UK 6 场补包已完成备份、dry-run/apply/replay/verifier；France manifest 为 `7e8f2906...eeb`，UK bundle 为 `fd3438be...081`。UK 6 场为 `46 runners / 40 results / 6 winners`，包含 `40 declared + 4 pulled_up + 2 withdrawn`；UK 场地修正 apply 与两次 verifier 均为 `4/4`。UK 6 场与 gap 裁决统一写前备份为 `189338143` bytes，SHA-256 `c5006b15bee22dd17d0d6fb7913f7c376a0799eeb37f3d6dc42b9199444c1410`，权限 `0600`，mtime `2026-07-16 23:04:32 +0800`，`pg_restore -l` 通过。
- resolution manifest `d5291268...c90f` 的 `1498` 条记录已 apply 并通过两次独立 verify，对应 `1498` 条唯一 `OperationLog`；原因为 `1467 source_unavailable + 31 identity_review_required`，按日期最终归入 `1491 gap + 7 not_due`。target `53349=2026-09-05`、`53418=2026-07-26`。
- 最终审核产物位于 `runtime/race_event_crawl_runs/final-detail-coverage-ledger-v5-20260716`，manifest `692b089b...584ea`、ledger `83399595...8fe9`，review 为 `approved`。生产 formal `published=0 / featured=0`，历史 enabled/network 均为 false，无 runner 或 running batch；历史公开仍关闭。
- 生产已统一到 image `sha256:c8c49780ac9dca4799e4834b052f7e05ca75ff61945343b2c19bf0ef2ab561ab` / revision `6b596befa0eea9ef0ba45acbb5384195829cc144`，无迁移；Django check、两域 healthz 200、worker ping 与日志检查通过。即时回滚标签和 `.env` 备份已保留。删除未使用旧 tag 后磁盘从 `2.6 GiB` 回升至 `4.0 GiB`，仍低于 `5 GiB` 门槛，服务器后续 crawl 为 no-go，重型抓取继续放在本地 Docker。
- 第一期正式详情总账的数据写入已完成，完成口径是“完整或证据化 gap/not_due”，不是“全部 complete”或“已经公开”。

## 2026-07-16 英国 Sporting Life 197 场增量详情已写入生产

- 用户按 commit `2a7352c8` 与 manifest `3c6a4d11...831c` 授权后，已完成独立备份、全量 dry-run、两块串行 apply 和逐目标 replay verifier。写前备份 SHA-256 为 `a942e2dad092bdf0af9e0546030a73c75dfeebb1c89ee888d704e8244d7f0d6c`，两个 verifier 均 `error_count=0`。
- 本包范围为 `198 = 197 complete + 1 evidence gap`；新增 `197 events / 2027 runners / 1794 results / 197 first-place winners`。唯一 gap 为 target `57633`，未伪造为 complete。197 个完整目标均为 imported，basic/runners/results 全部 complete。
- 全部新增赛事仍为 `draft + incomplete`、公开 0、featured 0。生产 web/worker/beat 已恢复并统一运行 `sha256:97b49b...397473` / revision `700a2a96`，HTTP 内外 healthz 正常，historical runner 为 `migration_safe`，常驻历史网络/写入和公开开关保持关闭。
- 生产累计 historical imported target/event 当前为 `7182`，但一期 master ledger 尚未全部完成；后续继续处理剩余分片和统一 gap/review ledger，不重跑本包已验收目标。

## 2026-07-16 4652 场历史详情已写入生产，公开门禁保持关闭

- 审核基线 `94360245...892a`、content `a353f2f8...748f`、commit `700a2a96` 与 manifest `dfb86ee8...14d9` 已按授权发布。生产 web/worker/beat 统一运行可复现 AMD64 镜像 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`；镜像内测试 `30/30`、Django check、迁移状态和运行健康检查通过。
- 正式 bundle 为 `4930 = 4652 complete + 278 gap`。4652 场已写入 `51191 runners / 48413 results / 4652 winners`，地区为法国 `15`、香港 `19`、日本 `1586`、英国 `171`、美国 `2861`；截至 2024 年 `4351` 场，2026 当前到期范围 `301` 场。
- 首次 dry-run 发现 `stable_raceevent_series_key_6e15e445` 物理索引损坏，事务回滚且无 receipt；在独立备份后以 concurrent reindex 修复，再从头 full dry-run 20/20。正式写前备份 SHA-256 为 `6c7d8f326c4c6a10f685a7be1a0625027cf6732729bcbc6904eba3aa45964b54`，apply 20/20、replay verifier 20/20，最终错误、缺来源和缺日期均为 0。
- 全部新事件仍为 `draft + incomplete`、`published=0`；历史模块完整表示详情已写入，事件级 `incomplete` 表示尚未通过独立公开验收。常驻历史写入、网络和公开能力均关闭，草稿 URL 返回 404，HTTP healthz 正常，队列和历史 runner 为空。
- batch006 和本次 4652 场不再重跑。278 个 gap 继续保留在统一审核账本；remaining `28126` targets 仍按 `8857 historical hard / 18173 historical best-effort / 1096 new formal` 推进。收口时生产约 `4.5 GiB` 可用，低于既有重型 crawler 的 5 GiB 门槛，本次没有启动新的生产 crawler。

## 2026-07-16 France runner v2 单目标 smoke 待重新生成 descriptor

- 本地固定镜像与独立 run/host-lock 根已核验，但 France `48498` descriptor 的 mounts/outputs 仍绑定 plan root，和批准的 runtime 根不一致。
- `discover` 在容器创建前 fail closed；请求、缓存、阶段产物和残留容器均为 0，后续四阶段未运行，生产与数据库未接触。
- 下一步由计划生成侧提供绑定独立 runtime 根的新不可变 descriptor，再从 `discover` 重跑；不得绕过路径身份门禁。

## 2026-07-16 日本 runner v2 单目标 smoke 待重新生成 descriptor

- 本地固定镜像与独立 run/共享 host-lock 根已核验，但 Japan `50556` descriptor 的 mounts/outputs 仍绑定 plan root，和本次批准的 runtime 根不一致。
- `discover` 在容器创建前 fail closed；请求、缓存、阶段产物和残留容器均为 `0`，后续四阶段未运行，生产与数据库未接触。
- 下一步由计划生成侧提供绑定独立 runtime 根的新不可变 descriptor，或经明确审批改用 descriptor 原批准路径，再从 `discover` 重跑；不得绕过路径身份门禁。

## 2026-07-16 准实时赛事赛果 latest-main 复审通过，进入离线测试先行

- 独立专项初始 PLAN 基于 `9b617702`，离线 TDD 期间持续安全快进，当前 `HEAD == origin/main@283bacf2`；专项经 stash、`ff-only`、恢复后保留主线与专项双方文档事实并解决四份文档顶部冲突，代码仅有 `race_events.py` 的新增 re-export 与专项追加内容自动合并。五份 durable artifacts 位于 `docs/changes/realtime-race-results/`。
- 目标是重点赛事完赛后数分钟展示明确标注的暂定赛果，再由官方来源确认/更正；不提供逐秒位置，不接管历史回填。
- 已完成计划、latest-main 复用审计和第一批离线 TDD：发布 mode resolver 的 5 项目标测试与 3 项相邻赛事回归共 `8/8` 通过。首次原生代码 review 的 terms permission 缺失 fail-closed 和状态记录两项 P2 已修复，同一 reviewer 限定复审 `APPROVED`。The Racing API 仍采用 Free 先 proof，且历史 handoff 前不联网。
- 第二个离线 TDD 切片已完成六态状态机纯函数 RED -> GREEN：只允许审核设计中的 7 条边，准实时模块与 3 项相邻赛事回归共 `10/10` 通过，同一代码 reviewer 完整只读复审 `APPROVED`；持久化 revision/ownership 尚未实现。
- 第三个离线 TDD 切片已完成严格 JSON canonical SHA-256 RED -> GREEN；review P2 指出的等价数字 hash 抖动已按新增 RED 修复，五种 approved phase 均明确排除于内容 hash。准实时模块与 3 项相邻赛事回归共 `15/15` 通过，同一 reviewer 限定复审已关闭唯一 P2并 `APPROVED`；尚未接入 revision/CAS。
- 第四个离线 TDD 切片已新增 ProjectionControl 基础一对一模型与 `0033` migration，不自动回填或接管既有赛事；完整 review 对本模型无 finding，既有 mode resolver 的 event allowlist P2 已按新增 RED 修复并由同一 reviewer 限定复审关闭。latest-main 上 SQLite 专项、相邻赛事及历史 chunk/receipt/import primitive 回归 `49/49`，check/migration drift 通过。revision pointer、owner transfer/CAS 和 importer 接入仍未实现。
- reviewer 后续建议的 revision counter 0 风险也已按真实 RED 修复：模型与未发布 `0033` 增加两个 `>=1` 数据库约束；组合回归 `50/50`，等待限定复审。
- 离线数据与调度骨架继续按真实 RED -> GREEN 推进：`0034` 至 `0038` 已覆盖 LiveTracking、身份、append-only revision/evidence、current/LKG pointers 和共享 HostBudget；owner transfer、revision allocator、source permission、时间窗、claim、host reservation、checkpoint 双 CAS 已实现。reviewer 的过期 claim P1 已分别补齐过期与缺失 expiry 的真实 RED 并修复，latest-main 组合回归 `105/105`；PostgreSQL 并发层仍待执行。未联网、启 worker、初始化 tracking、写生产、部署或购买订阅。
- 新一批离线控制面已完成 due-selector、host circuit、默认关闭的 Beat selector、`race_live` poll route、The Racing API Free 合成 fixture contract和 append-only observation recorder；并按 reviewer finding 将损坏 claim lease 改为 fail closed、host outcome 改为 reservation version CAS。准实时 `85/85`、与 historical detail chunk/import receipt/import primitives 组合 `122/122`，check/migration drift/diff check 通过。poll runner 仍 fail closed，专用 worker/真实 HTTP/revision apply/PostgreSQL 并发未完成，等待同一 reviewer 限定复审；Compose 解析因 worktree 无 `.env` 未完成，未借用主工作区 secret。
- 三份 Compose 的独立 `race_live` worker 也已按真实 RED -> GREEN 完成：普通/live queue 显式隔离，live 默认并发 1、prefetch 1、45/60 秒软硬时限，scheduler 默认关闭；准实时 `88/88`、与 historical detail chunk/import receipt/import primitives 组合 `125/125`，Compose 解析与脚本检查通过。尚未连接真实 broker/worker，poll runner 仍 fail closed。
- 赛果 conflict policy、observation -> immutable revision/items/evidence、current/LKG pointer 与 shadow/public projection apply 已完成；official authority 已绑定持久且 approved 的 source identity，shadow 可通过唯一 publication audit 单向晋级。公开赛事页已区分 provisional/official/corrected/conflict/stale，shadow 不泄漏。SQLite 准实时 `103/103`、相邻历史组合 `140/140`。真实 PostgreSQL 16 identity/apply/并发直接路径 `15/15`，覆盖 `skip_locked`、host 串行预约、同 claim 单 revision/replay、deferred pointer/supersedes guards 与 shadow promotion；`0039`/`0040` 迁移往返通过。仍未连接真实 broker、HTTP 或生产。
- 完全离线 TRA fixture runner 已完成受控文件 parse -> observation -> shadow revision -> checkpoint，使用实际文件 bytes SHA、失败 bounded retry、成功有限窗口/T+7d 停止，并强制 offline 永不公开。SQLite 准实时 `108/108`、相邻历史组合 `145/145`；仍未连接真实 Redis broker、HTTP 或生产。
- 临时 PostgreSQL+Redis 的真实 broker smoke 已证明 selector -> live worker 端到端与普通队列隔离：1 observation、1 revision、成功 checkpoint、shadow result 0，普通 `celery` 消息未被消费；临时资源已全清。生产 broker、HTTP 和 shadow 仍未启用。
- 后台已具备 live 模型只读观测面与赛事级 CAS kill switch；停用会立即失效在途 claim 并写审计，真实 Django admin POST 通过。manual correction 未开放。准实时 `113/113`、相邻历史组合 `150/150`。
- latest-main 组合回归 `249/249`（1 skip）通过；完整 `stable` 的 `2 failures / 13 errors / 23 skipped` 已在干净 `origin/main@c40a8c2b` 精确复现为相同 15 项主线基线问题。Django check、migration drift、三份 Compose、脚本语法和 diff check 通过。
- 最终 full review 的 2 项 P1、1 项 P2 已按真实 RED 修复：TRA non-finisher 状态保真，非完赛公开显示不再 fallback 内部顺序，两份生产 live worker 增加 0.25 CPU/384M 默认限制，并新增 `0041` choices migration。准实时 `116/116`、latest-main 组合 `252/252`（1 skip）和静态/迁移门禁通过，等待限定复审。
- 计划采用共享写入所有权仲裁、稳定 participant、append-only racecard/result revision、现有当前投影、独立 `race_live` Celery queue/worker 和按 host 共享限速；网络任务使用短 claim、无锁联网、短 CAS/apply。
- 原方案和用户修正范围均已 `APPROVED`；最新主线已把第一期历史详情正式分母收口为 `8032 = 6534 complete + 1491 gap + 7 not_due`，global verifier `errors=0`，历史 runner 为空且网络/功能开关关闭。来源 proof 的“历史先完成”条件已满足，但 proof 必须业务 DB 零写入；任何 shadow 仍需精确 event ownership allowlist、无 active lease/checkpoint、source registry digest 和共享 host/资源窗口的 SHA handoff。当前未联网、部署、购买、连接生产或开启公开展示。
- The Racing API Free 暂定赛果核心链已完成：安全网络 runner -> append-only observation -> shadow revision -> 持久 admission -> 暂定赛果投影 -> 官方复核 incident；公开读取门、只读后台、独立 Celery queue、容器 secret 隔离和默认关闭配置均已落地。当前 registry digest 为 `1d801e95b2770c741503a75dbcba93aca407a6cd681f3471813f1e7d5586fa32`，专项回归 `149/149`。仍未生产迁移或初始化任何 event；最新成功代码 review 和其后的用户发布授权仍是硬门，官方结果自动复核不计入首轮完成范围。

## 2026-07-15 Codex 原生工作流迁移已进入 `main`

- durable change 位于 `docs/changes/codex-native-workflow-migration/`；方案审核与代码审核均为 `APPROVED`，用户在最新成功代码 review 后回复“确认上线”。
- 受审 feature commit `55b6cebc14eef067c929b01ce3cea5515416c5ef` 已通过 [PR #10](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/10) 合并到远端 `main@96810fcc288f92b41971f4f825105732967798c2`。merge parents 为 `d6d6f58b...`、`55b6cebc...`，merge tree 与受审 feature tree 一致。
- 本迁移五份 durable artifacts 已随 PR 合并；发布验证为 fingerprint `24/24`、transition/index `10/10`、workflow contract tests `26/26`，workflow checker 与 `git diff --check` 通过。
- 本次仅发布仓库治理文档、skills/agents/scripts 和历史 skill 归档，不含 Django/runtime config/migration/生产数据变化；未构建或部署生产镜像，未重启、重建、迁移生产容器，线上业务运行态保持不变。
- 本次验收以远端 `main` 合并完成为准，无需生产部署。发布证据和回滚方式记录在 `docs/changes/codex-native-workflow-migration/release_report.md`。
- 原合并前记录中的“尚未发布”状态现已由上述 `main` 合并证据取代，不表示当前仍未发布。

## 2026-07-15 batch006 五地区详情抓取冲刺

- 1061 场正式 selection 的年度日期已达到 `1050 complete + 11 evidence gap`，完整记账率 100%。零星日美缺口继续累计到最终审核，不中断地区或年代分片。
- 日本、美国、英国、香港详情分别完成 `248/248`、`241/241`、`250/250`、`61/61`；对应出马/赛果为 `3704/3671`、`2181/1885`、`2570/2105`、`660/645`。法国详情已启动 checkpoint 续跑，本检查点完成 61 场且无解析错误。
- 英国距离单位歧义、香港同日同前缀赛事的一对一解析和跨 shard 共享 host 限速已修复，完整 stable `1528/1528`（11 skip）通过，最终 review 无 actionable finding。
- 生产 SSH 因此前重型 France verify 后持续握手超时，赛事 apply 暂停；所有重解析留在本地。主机恢复后先做事故清理与健康核验，再按 dry-run、独立备份、apply、只读 verifier 串行推进。历史公开开关继续关闭。
- 日、美、港正式详情包已分别生成 `248/241/61` 场且 gap=0；英国 250 条真实赛果 URL 已形成 date fragment，待日期和详情来源阶段写入后重新绑定 target SHA。共享 host limiter 已让法国两个本地 worker 在独立 shard 预算下严格保持跨容器至少 1 秒启动间隔。
- 最新已提交修复的 AMD64 候选为 `sha256:f1098223...06c3`、revision `f9e76b88`，镜像内 check/migration/赛事专项通过；生产不可达期间不部署。

## 2026-07-15 batch006 年度赛历流水线已部署

- 正式年度赛历 request/cache/parse 流水线已完成实现和零问题 review：支持全量或分片 ledger、共享 URL 去重、partial 终态、缓存身份复核、五地区 parser、complete/gap 分母及 runner 目录 checkpoint；完整 stable `1524/1524`（11 skip），专项 `118/118`（1 skip）、runner `70/70`、性能 `3/3`、OpenSpec `30/30`。
- 法国真实官方来源已达到 2023 `120/120`、2024 `130/130`、issues=0；香港现有覆盖 `61/61`、日本 `248/250`、英国 `250/250`、美国 `241/250`，剩余日美缺口继续进入统一审核账本。
- 生产 web/worker/beat 已统一到 `main@ccfee75f` / image `sha256:e86c2339...773d`；迁移、Django check、runner provisioning、crawl/apply 隔离、暂停/恢复和最终空锁验收均通过。写前备份 SHA-256 为 `898c9a4ab3a06847023d189aed830553cbe733bf4c8e92a4ed636dd8231fa55f`，历史常驻与公开开关继续关闭。
- batch006 仍为 1061 场 approved selection，按 11 个地区×届次年 scope 执行：FR `120/130`、HK `35/26`、JP `88/138/24`、UK `196/54`、US `83/167`。正式网络请求与赛事业务表写入尚未开始；下一步生成不可变 descriptor/shards/runner plans 后逐 scope crawl，并把日美少量 gap 累计到最终统一审核。

## 2026-07-15 historical runner 新镜像已部署，batch006 待正式审批与分片 crawl

- 生产已统一切换到 `main@c4087e6c` / image `sha256:5eb6471c8c1e96c90198e519c4d02f1b74316d6a13dbc93e9b63c0981ad22600`，写前数据库备份 SHA-256 为 `60331b0840a98e00370f2a5c10724d2e0e9ee370724ac572be8b0cd54781e341`，旧镜像回滚标签已保留。
- runner provisioning、crawl 最小权限、apply 无公网出口、暂停/恢复不重复、资源限制、迁移 preflight 和生产工具根 fail-closed smoke 均通过；伪造 artifact 子目录工具根时未创建数据库 run。
- 历史公开、常驻网络和常驻写入继续关闭，归属 mode 仍为 off；收口时队列、active/reserved、翻译/归属/历史运行和事务均为空，生产约 7.49 GiB 可用。
- batch006 已有 1061 场 selection，但正式审批与 runner plan 尚未固化，未发出网络请求、未写赛事业务表。下一步按请求预算拆分 crawl，并只使用镜像内白名单工具。

## 2026-07-15 新闻质量修复与 7 月 13 日起存量重跑完成

- 三类新闻质量缺陷已上线：正文边界/博彩噪声、实体语境/完整未知马名保护、日文普通词/产驹/追切/访谈/出马表固定格式。
- 冻结范围 `357` 篇，`343` 篇可处理、`14` 篇重复；最终 `218 published / 105 pending_review / 20 ignored`，点名 19 篇全部公开且 HTTP 200。
- 生产 web/worker/beat 已统一到 revision `bdc0eeff78e111d7fa8a697cbb3557888f864fb8`、image `sha256:c975a4faf979a1f78cdb203b810d4f5726aca114175007fc01c176044f13841c`；最终任务、队列、翻译状态和数据库事务均为空，healthz 正常。
- OpenSpec 相关 change 已归档且全量校验通过。历史 batch006 因生产可用磁盘约 `3.0 GiB < 5 GiB` 继续关闭，不属于新闻发布完成状态。

最后更新时间：`2026-07-16`
当前版本：`v0.0.1`（正式域名 HTTP 接入已修复，自动化运营 MVP、公开首页资讯流、抓取新鲜度修复、后台快速术语创建与当前稿术语应用、外部马名索引识别链路、榜单重点 QQ 推送、公开文章 ID URL、国际赛马资讯扩展、多地区生产窗口、术语种子数据准备、赛事日历 MVP 和马匹详情页 MVP 均已部署生产）

## 2026-07-14 多地区归属 V3 首轮生产审计 no-go

- 首轮候选在生产 72 小时只读范围内完成 `596` 篇审计，约 `29.36s`；Gold 有效 156 条，主地区准确率 `96.15%`、相关 precision `100%`、recall `52%`，机器门槛合格。
- 人工全量复核主地区变化与 `needs_review` 仍发现 7 类错标，涉及普通单词马名、赛事与马来源优先级、日本当前成就/海外梦想、机构名嵌套赛事词及正文历史背景。因此生产继续 `off`，没有开始 Shadow。
- 反例已固化并完成规则修复；专项 117、完整 stable 1404、真实 PostgreSQL 250 篇性能、Django/迁移和 OpenSpec 29/29 均通过。下一步是第二候选的生产只读重跑和同口径人工验收，不以旧 `qualified=true` 直接上线。

## 2026-07-14 多地区归属 V3 生产审计性能修复

- 生产首个 72 小时全量 run 已覆盖 597 篇，但旧报告阶段因逐篇发布门禁超过 30 分钟而中断。当前分支已把全量归属报告与门禁复核拆开，并支持从持久 run 原子重建审核 JSON；缺失/漂移文章自动必审，run 内容漂移直接拒绝。
- 159 条单审 Gold 当前有 21 条正文 SHA 漂移；原审核快照对账预计可安全续签 18 条，标题变化、正文异常缩短和推断变化各 1 条继续阻断。该结果尚待新代码部署后在生产只读命令中生成正式 artifact 与 SHA。
- France Galop 已补星期前缀英文日期解析和 probe 时间证据字段；部署后应能把真实官方日期标为 verified，而不是使用抓取时间。当前生产多地区 mode 与相关查询仍关闭，尚未进入 24 小时 Shadow。
- 本地专项 109 项、完整 stable 1396 项、一次性 PostgreSQL 250 篇性能契约和 OpenSpec 29/29 均通过。下一步是提交/构建安全关闭候选，生产只读重建 Gold 与 72 小时报告，再依据完整清单决定是否开始 Shadow。

> 角色说明：
> 本文档用于保留项目级概览与摘要信息。
> 当前真实工作状态、最近一次关键修复、线上实际进展，请以 [docs/current_state.md](E:/Codex/docs/current_state.md) 为准。

## 2026-07-14 batch006 前置能力已部署，资源门禁补丁待上线

- `scale-and-isolate-historical-race-batches` 已把 batch006+ 单地区标准上限统一为 250，并将可恢复的独立 historical runner、迁移 `0031`、最小权限 provisioning、隔离 smoke、迁移暂停 preflight 和独立 infrastructure bootstrap 部署到生产。当前生产镜像为 `sha256:33055eb8...25385` / revision `8741de98`。
- runner 使用数据库租约 + runtime 文件锁、30 秒心跳/180 秒租约、固定镜像与 plan/input/output SHA checkpoint；crawl 只有网络和控制账本权限，apply 只有内部数据库写入权限，全部历史 RaceEvent 继续保持 draft。
- 生产 runner smoke、双锁、暂停/恢复、越权拒绝和普通部署不干扰均已通过；batch006 selection 已生成 `1061` 场，五地区为 `250/61/250/250/250`，与前四个有效批次零重叠。正式网络抓取尚未启动。
- smoke 后发现直接 `python_tool` 未强制继承请求/cache/磁盘预算，且生产仅余约 2.8 GiB，低于 5 GiB 门禁。已按 OpenSpec 补充宿主与 Django 双层校验、共享账本、失败/强杀 checkpoint、显式赛事工具白名单及嵌套 AdapterRunner 收紧继承；第七轮 review 无问题，本地 runner `64/64`、historical 组合 `200/200`。最终合入最新主线后交叉专项 `208/208`（跳过 1）、完整 `stable 1417/1417` 通过（跳过 7）。释放生产空间、部署候选和强化 smoke 完成后才允许启动 batch006。
- 最终组合提交 `84217c56` 的两个独立本地 AMD64 构建 image ID 一致为 `sha256:2e8bd05f...28b31e`；候选 tag `umanewsbot:main-84217c56-amd64-20260714-2220`，OCI revision 精确匹配真实 Git 对象，镜像内 check、migration drift、runtime 专项 `239/239` 通过（跳过 1）。旧 `82fa4a3f` 候选及 revision 标签错误的 `sha256:119f59e3...` 均明确作废。仍未 retag `prod`、未部署、未连接生产、未启动 batch006；必须等待新闻维护窗口重新交还后先治理磁盘并执行 hardened smoke。
## 2026-07-14 多地区归属 V3 性能与审核策略

- 已用临时 PostgreSQL 16 和真实校准规模完成 250 篇基准。首次发现来源配置 N+1 导致 254 SQL；批上下文增加 17 个来源一次预加载后，五轮稳定为 5 SQL、1.66–2.14 秒、约 49 MiB，性能门槛已通过。
- 单审身份不再自动 no-go：首发覆盖门槛为有效样本至少 150、五个运营地区各至少 10、跨地区至少 20；达到全部质量/性能门槛后可进入生产 shadow。至少 24 小时 shadow 和全量差异复核通过后，才允许仅新文章 enforce；多人审核冲突仍须裁决。
- 现有 159 条单审 Gold Set 的最少运营地区样本为法国 11、跨地区 24，主地区准确率 98.11%、相关地区 precision 100%、recall 54.84%、过度扩散 0%，已达到进入 Shadow 的覆盖与质量线。Gold Set 后续持续吸收新增来源、规则改版、shadow 误判和运营争议；生产归属和相关地区查询尚未开启，本轮没有生产操作。
- Gold 生成器与评估器已共用可配置的 `150/10/20` 默认门槛；合并 `origin/main@9d6dec34` 并补齐全量审计契约后，完整 `stable` 1327 项通过（1 项按设计跳过），159 条 Gold 仍为合格，OpenSpec strict/all 28/28 通过。
- 上线前补齐了生产审计入口：`--scope all_articles` 才表示最近窗口全量有效文章（包含已发布稿），默认 `gate_candidates` 继续只服务术语门禁补跑。全量审计输出全部主地区变化、全部 `needs_review/locked_skip` 和五地区可重复分层样本；显式 limit 导致不完整时会明确阻断验收。当前改动尚未部署，生产 dry-run 与 24 小时 Shadow 仍待执行。
- 代码已推送 main `7f0827ad`，可复现 AMD64 候选为 `sha256:6ad16e36...af9a1`，镜像内专项通过。生产切换因正在运行的 186 篇受控翻译重试 one-off 暂停；生产仍是旧镜像，归属 mode=off、相关查询关闭，尚无 72 小时归属 run。

## 2026-07-14 生产 DB/Redis 意外重建恢复

- `01:22` 的误用 `docker compose run` 意外重建 DB/Redis，造成短时连接中断、Redis 待消费任务丢失、新闻索引异常和 4 组重复 article identity。web 镜像未变化，PostgreSQL 为干净关闭后从原目录恢复。
- 已通过停 beat/排空 worker、完整备份、5 条重复记录受控合并、`stable_newsarticle` 全部 17 个索引并发重建和 `VACUUM ANALYZE` 完成恢复；最终 8312 行、重复 0、无效索引 0、dead row 0。
- 最新备份为 `pre-newsarticle-dedup-reindex-20260714_020918.sql.gz`，SHA-256 `f37ff4835fe13d4c2a016beac433940ef995677e690711dc68ca59f42b149a9e`。`02:15` 自然窗口 17 个来源、五地区发布和 QQ 全部成功，公网健康检查正常。

## 2026-07-13 多地区归属单审校准结果（已由 V3 复评更新）

- 审稿人 1 已完成部分抽样标注：159 条有效、1 条排除、90 条未选中忽略。没有第二位审核人这一事实继续以 `provisional_single_review` 保留，不伪造 reviewer B；2026-07-14 起单审身份本身不再自动 no-go。
- 当日生产只读旧规则评估有效分母 154，主地区准确率 81.17%、相关地区 precision 6.90%、recall 6.67%，属于历史基线。冻结 159 条完整分母上的 V3 复评已提升到主地区 98.11%、相关 precision 100%、recall 54.84%，并达到 `150/10/20` 首发覆盖门槛。
- 已补充单审固化/只读评估、原始值规范化审计和正则模式复用。逐篇结果保存在 `outputs/20260713-multiregion-gold-final/multiregion_gold_set_final_20260713.xlsx`；当前只取得进入 Shadow 的资格，归属 enforce 与相关查询仍不得直接开启。

## 2026-07-13 多地区归属 Gold Set 标注包

- 已从生产库只读生成 `multiregion-gold-v1-20260713` 双人盲标包：共 `250` 篇，五地区各 `50`，覆盖 `17` 个来源，URL 和输入 SHA 各自全量唯一，manifest SHA-256 为 `1836a9d896ca5b6e09da6da7ed07a2fb3f66f0a02f387010fe4b56475bf5c1ea`。
- 已补齐抽样与合并命令，能阻止同一审核人重复充当双审、正文/身份漂移、未裁决冲突和样本结构不足；正文审核包不进入 Git，正式 Gold Labels 才进入版本控制。
- 本段是原始候选包记录。用户后续明确不再补第二审核人，OpenSpec `5.1` 已按 159 条单审 Gold Set 完成；若未来增加多人审核，仍需合并冲突并裁决。多地区归属和相关地区查询继续关闭，下一步是生产 Gold/dry-run 与 Shadow 验收。
- 本分支已同步 `origin/main@693db30e`，最新组合回归 `1139 passed / 1 skipped`，Django、迁移、OpenSpec strict 和 diff 检查通过。
## 2026-07-14 日文赛马翻译与固定格式上线

- `standardize-japanese-racing-translation` 已部署 `main@873845da` 并归档。普通片假名、完整未知马名、产驹、追切、访谈、骑手未定及三语机构术语均进入确定性翻译契约；种子术语恢复会处理明确边界重复，英文术语中文目标不会反向污染日文普通词。
- 11 篇目标文章全部保持原公开身份并通过逐篇正文验收；随机样本 `8337/8366/8356/8307/8367` 无占位符或假马标签。最终本地完整 `stable 1295` 项通过（跳过 1），候选 PostgreSQL 关联 84 项和最终零问题 review 通过。
- web/worker/beat 统一镜像为 `sha256:d3f602de4459158bc372e45bb35f3730a7be21f284dfea32de5535681bd6d791`；HTTP、空队列、术语唯一性、历史安全开关和日志验收正常。最新写前备份为 `pre-873845da-20260714_124940.dump`，SHA-256 `413718143809a09686ea18710a4cd8b8f9a9f7643fb6b769cee5daf23ca485a6`。

## 2026-07-14 新闻实体语境修复上线

- `contextualize-news-entity-resolution` 已部署 `main@dc1e5ec5`；统一文章级实体解析覆盖翻译、标签、校验和自动关联，解决英文人物/普通词误作马名、姓氏回指以及日文完整马名被内部短术语拆分。
- 11 篇问题文章已修复并保持原公开状态、发布时间与 QQ 幂等；随机六篇及最终 worker 新处理两篇通过回归。最终验证为目标 `51`、完整 `stable 1249` 项通过（跳过 1），第 18 轮 review 无问题。
- web/worker/beat 统一镜像为 `sha256:5b06821610f0d2214cb24692e58beac4ffda731ddb84674a8855b2a1d4dbb470`；HTTP 健康、目标详情、空队列及错误日志正常。最近有效写前备份为 `pre-main-624dd5b9-20260714-071014.dump`，SHA-256 `21cdce21f52ded3b48e7c083f2f536eb694130f71ad6a1e38e067620f817fa75`。

## 2026-07-14 第五标准批次 250 场导入完成

- batch005 五地区各 50 场已完成日期、详情来源、出马表和赛果正式导入，最终逐场验收 `0 errors`；新增 `2583 runners / 2364 results`。
- 最终详情候选 SHA-256 为 `269c65e646b11be0a1edef70c8c088e5b4b9a2b0a69527ca0efc6242cb84d6e3`；最终写前备份为 `pre-batch005-final-20260714_055856.dump`，SHA-256 `82908208d5a32f751c1b7c258c54e3ac66993798d27b66ff6d1405393a10ffa9`，`pg_restore -l` 通过。
- 生产累计为 `1291 imported / 29626 pending`、`13507 runners / 12167 results`；全部历史赛事仍为 draft，published 0，常驻历史网络/写入开关 false。
- batch006 前先建设每地区最多 250 场与独立 historical batch runner，完成 OpenSpec、工程审查、测试、实现、零问题 review 和部署验收后再继续抓取。

## 2026-07-14 国际新闻正文边界修复上线

- `tighten-international-article-content-boundaries` 已完成完整 OpenSpec 流程并部署 `main@514af8a2`；web/worker/beat 同为镜像 `sha256:954673cc74049d4b882e492ec29b072aba01aeb1a3ae440cc85415209c8a2f8a`。
- Sporting Life/TDN 现在只从可信正文容器解析，并清理站点框架、社交/推荐、编辑注、结果/活动链接、责任博彩、博彩推广、独立跳转 URL 与行动 CTA；赔率和赛事/马主专名中的博彩公司名称继续保留。
- 目标文章 `8086/8267/8316/8318` 已修复、重译并保持原公开状态/发布时间，QQ 零重复；随机抽检 `8306/8311/8326/8331/8336` 的保存正文、当前重解析和译文均通过，噪声标记为 0。
- 最终验证为目标测试 `27`、完整 `stable 1198` 项通过（跳过 1）；内外 healthz、目标详情、容器、空队列和日志正常。最新可读数据库备份为 `pre-main-514af8a2-20260714-051127.sql.gz`，SHA-256 `9fc72efba29ee8d32c9709665809d259ca49e47a217c43626c99b084d99d4b0a`。

## 2026-07-14 历史批次已耗尽地区门禁修正

- 标准批次进度护栏改为只比较本批后仍有未排除可抓 pending due 目标的地区；低容量地区抓空后退出比较，其他未完成地区仍严格遵守 100 场领先上限。
- 待审 selection snapshot 排除项继续保留总账和 remaining pending 分母，不会被技术修复伪装成完成；artifact summary 新增可抓分母和实际护栏地区，便于审批追溯。
- OpenSpec、测试优先实现和最终 review 已完成；专项 `66` 项、完整 `stable 1171` 项通过，`1` 项按设计跳过。代码已合入 `main@614f810e`，尚待可复现 AMD64 镜像切换；生产历史开关和公开展示保持关闭。

## 2026-07-14 第四标准批次 250 场导入完成

- batch004 五地区各 50 场已完成日期、详情来源、出马表和赛果正式导入；新增 `2563 runners / 2311 results`，500 个模块候选全部 applied，逐场验收无重复非空马号或重复名次。
- 最终详情候选 SHA-256 为 `ddd1f8256cef0b17aabc33ea66f7a0638a2d6498c2d23342daff8835b10a5156`；最终写前有效备份 SHA-256 为 `e50bd095bfa141ea0f05bf77fda68a508808dcddac4cbacb8fdb4ce3860e758a`。
- NSA 官方 PDF 不提供 `target_id=74171` 的马号，8 条 runners 与 7 条 results 保留空号并进入最终统一审核，不阻断后续批次。
- 226 场存在术语库暂缺中文映射的非阻断记录；原文出马表和赛果已完整入库，术语补全待总账数据收集完成后统一审核。
- 生产累计为 `1041 imported / 29876 pending / 0 ready`；本批全部 draft，历史 published 0，常驻写入/网络开关 false。batch005 等待 `main@614f810e` 镜像由生产协调线程切换。

## 2026-07-13 第三标准批次 250 场导入完成

- batch003 五地区各 50 场已完成正式导入，新增 `2638 runners / 2349 results`；写后累计 `791 imported / 30126 pending / 0 ready`、`8361 runners / 7492 results`，全部 draft、published 0。
- 2025 Hampton Novices' Chase 已按 Windsor 移师后的正式赛果收口为 `2025-01-19 / Windsor / 3m53y`，冠军 `Jingko Blue`，Warwick `ABANDONED` 不再视为年度 gap。

## 2026-07-13 标准批次重复选样门禁

- batch002 的 4 个 pending gap 曾再次占用旧 batch003 配额；该旧工件作废，不得审批。
- 批次命令已支持显式引用既有不可变 selection snapshot，在每地区上限前跳过旧目标并补入新目标；排除证据复制进新 artifact 并由 manifest 哈希绑定。
- 排除不会改变 gap 的产品状态或总账分母。实现已通过 42 项聚焦测试、完整 `stable 1157` 项回归和两轮 review，尚待提交、交付 AMD64 镜像并在生产只读重建 batch003。

## 2026-07-13 第二标准批次 246 场导入完成

- 2016–2025 第二标准批次 250 个目标中，246 场已完成日期、直接来源、出马表和赛果正式导入；五地区分别为日本 50、美国 48、香港 50、英国 48、法国 50。写后逐场验收 error 0。
- 生产历史累计为 `541 imported / 30376 pending`、`5723 runners / 5143 results`，541 个历史赛事仍全部未公开，published 为 0。常驻历史写入与网络开关保持 false。
- 4 个未导入目标继续保留为产品待审缺口：美国 2 场 `not run`、英国 2 场 `ABANDONED`。本批没有借技术导入自动改变其 `held/not_held/cancelled` 口径。
- 日期、来源、最终详情三阶段均有独立校验与写前备份；最终详情候选 SHA-256 为 `735ec0dacafd9c388adb678b93ab402e45f991cb0e143c89a6fe067e606fc459`。下一步继续生成同年代带后续均衡批次，不提前跳到更早年代。

## 2026-07-13 可复现主线镜像上线

- 历史源码已全部提交到 `main@304ebdb6`，不再依赖未提交构建上下文。源码完整回归为 `1128 passed / 1 skipped`。
- 生产 `web / worker / beat` 已切换到从干净 `main` 两次一致构建的 AMD64 镜像 `sha256:e7ab7af0061d7362ad0582224baffc79eda07bd6d8f6467bfa573f760853877d`；迁移、64 models、历史命令、安全开关、HTTP 和自然生产窗口验收通过。
- 法国/香港/英国各 `50` 场日期 target 仍为 `ready/draft`，详情未写，历史公开数为 `0`。镜像不可复现风险已清除，新闻调度/翻译的既有运营问题仍按下节跟踪。

## 2026-07-13 组合镜像恢复后窗口验收

- 最新完整窗口已证明 17 个生产来源全部抓取成功，发布/QQ 窗口无失败，最近日志无 schema 约束错误；镜像与 `0029` 不兼容造成的新闻写入故障已解除。
- 尚不宣称完全正常：当前调度会常态将跨 bucket 到期的旧窗口合并到最新窗口；3 篇翻译失败稿不会在当前安全关闭配置下自愈；JRA 有 1 个固定 PDF 解析跳过；28 条历史 CrawlJob `started` 脏记录会干扰观测。
- 当前来源是每 5 分钟检查、按上次完成时间滚动到期，15 分钟配置在线上体现为约 15–20 分钟，不能用“每个 bucket 都有 17 条”作为验收口径。

## 2026-07-13 法国新鲜度与多地区归属本地实现（历史状态）

- change 保持 `implementing`：本地已完成 TDN 日期查询、France Galop 可信时间、翻译失败有界恢复、多地区归属 run/manifest/灰度和运营可观测性，生产尚未部署。
- 三轮 review/返修后专项 `120` 项全部通过；完整 `stable` 回归 `968` 项通过，PostgreSQL 专项性能契约 `1` 项在 SQLite 按设计跳过，最终 review 无待修复问题。
- 配置默认保持归属 `off`、相关地区查询关闭、翻译自动重试关闭。该日 OpenSpec 为 `57/68`；双审与 `250/40/50` 门槛已由 2026-07-14 的单审及 `150/10/20` 决策取代，当前进度和资格以本文顶部为准。
- 因此代码已具备灰度基础，但功能尚未在线，也不能据本地合成测试宣称多地区归属已达到生产准确率。
- 终态翻译失败将向 `754652181@qq.com` 发送包含文章、失败分类和后台快速入口的邮件；生产部署仍须确认 SMTP 配置。测试群通过 `PushTarget.multiregion_test_enabled` 显式标记，默认关闭，避免 `web_test_groups` 阶段影响正式群。

## 2026-07-13 法国新鲜度与多地区归属方案完成工程评审（历史状态）

- OpenSpec change `fix-france-news-freshness-and-multiregion-attribution` 当日已完成两轮 full review 并进入 `reviewed`；后续代码已安全关闭部署，当前仍待生产 dry-run 与 Shadow 验收。
- 方案覆盖 TDN 日期倒序抓取、France Galop 可信发布时间、瞬时翻译失败有界重试、多地区归属准确度和分阶段上线。
- 上线前必须通过版本化 gold set、真实生产 dry-run、250 篇批处理性能门槛和单次发布/QQ 交付幂等测试；归属默认 `off`，相关地区查询默认关闭。

最新生产状态：提交 `f221c7df` 已部署。英文术语命中级上下文门禁、运行账本和高性能重处理已在线，迁移 `0028` 已应用，`web/worker/beat` 统一处于 `shadow`。`2026-07-12` 已对四个锁定 dry-run 执行受控 commit，并由两个自然窗口公开 24 篇；复核发现其中法国 5 篇来自 TDN France 日期修复前的污染批次，已撤回该批次全部 20 篇以阻止再次复活，最终保留香港 7、英国 3、美国 9，共 19 篇，QQ 交付 0。至少观察 24 小时且人工抽检通过前不切全局 `enforce`。赛事历史主干能力和 P0 马资料补全基础代码继续在线，网络补全、P0 全量来源写入、多地区归属开关和自动首次发布仍保持关闭。

法国新闻低产出排查确认不是 3 天门禁过严，而是 TDN 关键词入口按相关度返回历史稿、France Galop 未解析真实发布时间、两篇最新稿因翻译供应商 `429/503` 且没有周期重试，以及多地区归属开关仍关闭四项叠加。TDN 按日期 posts 搜索在 `2026-07-09` 以来可找到 `12` 篇宽口径候选；本次仅记录证据，尚未改代码、重试文章或开启归属。

上述四类问题已纳入 OpenSpec change `fix-france-news-freshness-and-multiregion-attribution`。该 change 同时要求提高多地区归属准确度，以真实五地区 Gold Set 和明确 precision/recall/过度扩散门槛控制生产资格，并按 shadow、仅写入、网页/测试群、72 小时回填、正式群五阶段启用。该段为早期规划记录；当前代码已部署为安全关闭，159 条首发 Gold 已达标，生产多地区开关仍为关闭。

历史首批45个目标当前为 `33 imported / 3 ready / 9 pending`。法国2012/2025六场已通过独立补充来源审批链导入 `70` 条出马和 `41` 条赛果；36个已materialize历史赛事仍全部为draft，历史回填与网络开关继续保持false，线上未公开。下一步补法国2000、英国2000和美国2000/2012来源缺口。

历史赛事回填已完成1998–2026全部身份审核：`102` 个同名簇临时Key先归并为 `58` 条正式赛事线，随后 `15` 对高相似名称合并为名称变体，Prince of Wales's与Princess of Wales's保持独立。最终v12总账包含 `30,917` 个年度目标和 `2,334` 条正式赛事线。京都雌马2005–2009、Bristol 2001届、Louisville 2008、Keeneland First Lady 2000和NYRA Matron 2018等异常已修正；Ascot约3m金杯线中文主名确认为 `阿斯科特秋季金杯让磅障碍追逐赛`。原始v10和同名簇v11均保留作审计。生产已开始按批准总账分批写入详情，历史公开开关继续关闭。

五地区详情抓取来源口径已补充：日本 JRA/netkeiba/JBIS，中国香港 HKJC，英国 Racing Post/Sky Sports/BHA，法国 France Galop/PMU，美国 Equibase/BRISnet/DRF/BloodHorse及障碍赛NSA。后续抓取必须分别处理赛前声明出马表、实际出走、退出马与赛果，不能互相替代。

`2026-07-12` 的审前逐届证据表保留 `687` 个原始年度行、冠军 `474` 行和1号马 `164` 行，现仅作为审计快照；其同名簇结论与京都雌马冲突已由 `2026-07-13` 的结论版和 v11 总账取代。生产现有 `992` 场赛事中，出马表存在覆盖约 `50.9%`、赛果存在覆盖约 `50.7%`；以 `503` 场已完赛赛事为分母时，两项覆盖均为 `100%`。

## 1. 项目背景

目标是构建一个面向中文用户的日本赛马新闻系统，形成：

`采集 -> 翻译 -> 自动分流/改写 -> 人工编辑 / 自动发布 -> 发布 -> QQ 群自动推送`

当前阶段重点是让站点进入“可持续自动更新”的内容运营阶段，同时继续保证真实上线稳定性。

## 2. 当前技术方案

- 后端：`Django + Celery`
- 数据库：`PostgreSQL / SQLite`
- 队列：`Redis`
- 翻译：`OpenAI-compatible`（已支持 SiliconFlow）
- 媒体存储：`local / OSS` 双后端
- 推送：`OneBot`
- 部署：`Docker Compose`

## 3. 已完成（业务能力）

- `netkeiba` 与 `JRA` 采集
- 新闻/图片/快照/术语/推送/日志等数据模型
- 翻译状态机与失败重试
- 未收录马名保留日文、翻译完整性校验
- 未收录马名翻译保护已增强：使用占位符保留原文名，模型仍漏保留时记录 warning 但不阻断整篇翻译
- 外部马名索引识别链路已部署生产：`ExternalHorseAlias` 可参与马名识别、翻译保护、发布校验和候选发现；外部马名只用于确认“这是马名”，不批量写入正式术语库 `TermEntry`
- 术语工作台与批量导入
- 候选池、编辑台、发布流
- 自动化内容运营 MVP：
  - 自动评分分流 `auto / manual / ignored`
  - AI 编辑改写稿与基准翻译稿双层保存
  - 一致性校验、批量自动发布、自动化日志
  - 自动发布批量规则：常规每批 4 篇，周日北京时间 13:00-16:00 每批 10 篇
  - 邮件通知 MVP 与通知日志
- 前台信息流与详情页已升级为公开站点专用 Web + 移动 H5 资讯流
- QQ 推送链路：已新增并部署自动推送实现，支持重点优先/全公开、多群、去重、有限重试、OneBot 业务失败识别、OneBot 离线发送前预检、`sending` 陈旧恢复、后台交付记录和按群限速；生产 OneBot / NapCat 网关已登录并在测试群验证发送，当前生产 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 已生效。
- 抓取新鲜度与来源健康：netkeiba 新着顺 / 访问量榜 / 注目数榜已切换为每小时 `00/16/26` 分错峰抓取，JRA 无年份日期解析已修复，后台来源健康摘要已上线
- 榜单来源提升：已部署 `netkeiba:latest -> access/attention` 主来源提升，访问量榜和注目数榜不互相覆盖，并为 QQ 榜单推送暴露 `source_elevated` 信号。
- 榜单重点推送：已部署 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`QQ_PUSH_SCOPE=high_value_only` 下只推 netkeiba 访问量榜 / 注目数榜且无 blocker 的公开文章。
- 公开文章 ID URL：已部署公开详情主路径 `/news/<article_id>/`，非纯数字旧 slug URL 跳转到 ID URL，QQ 消息链接不再包含标题全文。
- 赛事日历 / 年度赛事页 MVP：已部署生产 `f3c4c46`。已实现 `RaceEvent` 产品层、公开 `/races/` 赛事日历、年度详情页、后台 `/admin/race-events/` 工作台、CSV 种子导入、候选资料写入/应用、新闻自动/手动关联和人工移除保护；生产已导入 5 条 P0/P1 赛事种子与 10 条别名，第一版不建设马匹数据库或完整赛果库。
- 马匹详情页 MVP：`2026-07-10` 已更新部署到生产 `65988b0`，OpenSpec change `horse-profile-page-mvp` 已归档到 `openspec/changes/archive/2026-07-08-horse-profile-page-mvp/`，正式规格已同步到 `horse-profile-pages`、`horse-profile-data-completion` 和 `public-home-info-feed`。新增 `HorseProfile`、候选资料、参赛履历、马-赛事/新闻关联和匿名关注模型；公开 `/horses/`、`/horses/<id>/`、`/horses/follows/` 已实现，后台 `/admin/horse-profiles/` 支持审核发布、字段锁定、候选 diff、参赛履历和新闻关联维护。P0 马已默认生成 `21596` 个草稿，前台默认不可见，管理员可强制发布空壳；外部补全走本地缓存 dry-run artifact + 人工审核 commit，公开请求路径不访问第三方。`2026-07-08` 已补审查修复：全量 dry-run 默认不截断、马名和术语匹配大小写不敏感、关注面过滤未发布马匹、补全 commit 保留写库前 diff、资料保存不能绕过发布审计、按地区输出补全比例、stale 扫描任务不扩大范围。生产全地区补全 dry-run artifact 位于 `runtime/horse_profile_completion/dry-run-20260708_041343/`，当前完整二代 `0/21596`，未补全占比 `100%`，主要原因是本地外部缓存无匹配或来源不可用；本次未 commit 补全结果。线上已发布样本 `春秋分` `/horses/13113/` 与 `北十字星` `/horses/3873/`，均为完整二代血统，参赛履历分别 `10` / `11` 条，相关新闻各 `5` 篇；浏览器验收确认详情页、新闻 tag 点击、关注 / 取消关注、关注页新闻流、英文大小写搜索和移动端一级导航 / 地区筛选布局均通过。
- P0 马资料补全专项：`2026-07-10` 已在独立 worktree `/Users/mentianlu/.codex/worktrees/p0-horse-info-completion/umanews` 创建并重写 OpenSpec change `complete-p0-horse-profile-data`，并对齐旧线程最终提交 `d78fab0`。新版 P0 范围扩展为“当前 active 且有中文译名的 horse `TermEntry` + 五大地区全部历史与未来重点赛事参赛马”，重点赛事等级限定为 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ`；暂无中文译名的 P0 马允许补全和人工发布，翻译命中时保留原文。首批验收为日本、中国香港、英国、法国、美国各 10 匹完整资料马，完整资料硬门槛包括 P0 来源证据、基础事实字段、二代血统、完整赛事履历、主胜鞍、来源 URL 和人工审核记录。计划工程审查已重新完成，`.openspec.yaml` 当前 `phase=reviewed`。核心骨架已完成三轮审查返修：马匹地区不属于身份键，来源内 external horse ID 可直接定位；跨来源归并数据库已有马必须完整唯一命中经术语库多语种归一的“马名 + 父名 + 母名 + 出生年份”，歧义写候选并每天通知管理员；同一原名对应多个马术语时保留原文且禁止任意替换。管理员可从冲突筛选列表进入详情填写处理说明；P0 普通同步只增量刷新，显式全量对账才执行 revoked，待处理歧义不会误撤销仍在输入中的来源；artifact 使用顶层/行级/模块级审核；完整资料按最新模块审核结论、在役马同步新鲜度、退役马最新赛绩、逐条赛绩来源和四模块审计判断。定向 P0 回归 `35` 项、系统/迁移检查和 OpenSpec 校验通过；完整 `stable` `549` 项仅剩 `3` 个随日期漂移的既有 TDN France 时效 fixture 失败。当前尚未执行五地区真实 adapter 扩展、每地区 10 匹 dry-run、生产 commit 或人工公开验收。
- P0 第四轮审查返修：同场同名参赛马改按马号/来源身份拆分，URL 暂缺的仍存在来源不会在完整对账中误撤销；非 pending 候选不能通过通用应用入口改为 applied；人工完整审核必须提供明确整匹马资料 URL。身份歧义采用专用 `HorseIdentityConflict`，可在无 profile 时保存多个候选术语、身份原始证据和人工解决状态；resolved 必须选择最终资料页，后续同步按人工结论建立 P0 来源。每日运营通知链接到 Django Admin pending 列表。定向术语/P0/旧马匹页回归 `79` 项通过；完整 `stable` `556` 项仅剩 `3` 个随日期漂移的既有 TDN France fixture 失败。
- P0 第五轮审查返修：`HorseP0Source.participant_key` 持久化同场参赛身份，runner/result 按马号、来源 ID、赛事内唯一马名配对；无外部 ID 的同场同名马可按不同马号稳定拆分，重复同步不增生，身份纠正保留 revoked 旧绑定。P0 artifact 与通用人工候选统一调用共享赛绩幂等 upsert，并强制完整来源名/URL。定向旧马匹页/P0 回归 `59` 项通过；完整 `stable` `560` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败。
- P0 第六轮审查返修：参赛键从 external identity 升级到马号时迁移既有 active 来源，不保留重复 active；runner/result 非空马号冲突时禁止按 external ID 降级合并并写身份冲突证据；后台手工新增/编辑赛绩统一走共享幂等服务，编辑后重算键且来源 URL 双层必填。定向旧马匹页/P0 回归 `63` 项通过；完整 `stable` `564` 项仅有既知 `3` 个 TDN France 固定日期 fixture 失败；并发争用按用户决定不在本轮处理。
- P0 第七轮审查返修：同一来源 identity 对应多个马号时，runner-result、两条 runner、两条 result 都汇总成单条身份冲突并停止写 active 来源；后台编辑保留 importer 的 `source_refs/raw_payload`，修改 diff 写操作日志；完整度与后台待刷新筛选统一使用配置化新鲜度截止日期。定向旧马匹页/P0 回归 `67` 项通过；完整 `stable` `568` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败。
- P0 第八轮审查返修：马号冲突 resolved 必须同时选择最终资料页和候选马号，后续只绑定该马号记录；冲突 evidence 保存全部成员与 URL，完全无 URL 也落库，fingerprint 排除可变 URL；imported 赛绩人工编辑继续沿用 external ID 和原 source namespace 幂等键。定向旧马匹页/P0 回归 `69` 项通过；完整 `stable` `570` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败。
- P0 第九轮审查返修：迁移回填同时读取 `raw_payload/source_refs` 的 external ID；共享任一身份键的参赛记录按完整连通组生成单条冲突，交叉身份不会丢成员；resolved 马号必须具备成员或赛事 URL，URL 后续缺失时同步恢复 pending、清空无效选择并记录原因，确保继续通知管理员。定向回归 `96` 项通过；完整 `stable` `573` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败，当前仍未部署。
- P0 第十轮审查返修：人工 P0 来源按马匹独立 upsert 并增加唯一约束；resolved 马号成员无法定位时统一恢复 pending 并重新通知；旧空键赛绩优先按 external identity 接管或报告多记录歧义，不再因事实字段变化新增第三条。定向回归 `99` 项通过；完整 `stable` `576` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败，当前仍未部署。
- P0 连续审查收敛：按用户要求持续执行审查与返修，第五轮纯审查无可操作发现。旧赛绩来源命名空间支持从证据回填并统一大小写/空格，external ID 统一去空格，importer 与后台编辑都会阻断多条旧 external identity；补全队列按真实资料缺口和刷新需求排序，再综合人工、候选、近期新闻、重点赛事、外部身份和术语优先级，完整马不再挤占未完成样本限额。OpenSpec `6.2` 因五地区 adapter/artifact 尚未完成而恢复未勾选。定向回归 `104` 项通过；完整 `stable` `581` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败，当前仍未提交或部署。
- 2026 五地区重要赛事填充：已按官方来源导入日本 JRA/NAR、香港 HKJC 当前公开 2025/26 马季内香港 G1/G2/G3、美国 TOBA Grade 1/2/3、英国 BHA Flat Group 1/2/3 与 Jump 2026 年 1-4 月 Grade 1/2、法国 France Galop Groupe I/II/III。当前生产 `RaceEvent=995`、`RaceEventAlias=3277`；2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `203`、法国 `174`。剩余缺口是 HKJC 尚未公开 2026/27 年末香港本地分级赛日期，以及英国 Jump 2026 年 10-12 月仍需下一季官方书或其他官方结构化来源。
- 赛事信息编排工具：`2026-07-11` 已完成第四轮技术返修，在既有独立应到清单、run 级候选汇总、共享请求预算和全阶段 state 基础上，新增实际 apply scope 对账与逐组合确认、按哈希命名的 approved candidate、importer 执行时 `--expected-sha256` 复核、严格 adapter manifest，以及 `complete_with_warnings` 行状态。独立赛事编排专项测试 `41` 项、完整 `stable` 测试 `581` 项、Django check 和迁移漂移检查均通过；当前尚未运行真实抓取、未写生产数据。
- 国际赛马资讯扩展：已部署多地区新闻源、公开首页地区 tab、多语言术语别名、群级 QQ 地区配置和 HKJC 受控导入；生产第一版已启用 `Sponichi`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation`，其中 `BHA` 因生产探测返回 `403` 暂停启用。
- 全球赛马数据库抓取能力：香港 HKJC、英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 的受控 importer 能力已部署；`2026-06-30` 已开始香港 HKJC 慢速真实 dry-run，最新 plan 为 `146` 场且前两场完整 dry-run 成功，仍未执行生产 `--commit`。
- 香港 HKJC 长窗口 dry-run：`2026-06-30` 已按用户要求启动到 `2024-07-01` 的慢速后台抓取计划，plan 共 `1496` 场；为部署多地区新闻常态生产，当前 dry-run worker 已暂停在 `hkjc-slow-dryrun.state=92`，仍未写正式表。
- 多地区正式术语库补齐：`2026-07-04` 已导入 WP Stud 香港/来港社区马名 `210` 条、HKJC 当前本地马 A-Z 官方译名 `1258` 条，并从 HKJC 本地赛果回溯香港历史马名、骑师名和赛事名到 `2026-07-04`。`2026-07-05` 已继续完成 HKJC overseas 官方 Race Card/QIDS 术语回溯，覆盖 `2024-01-01` 至 `2026-07-04`，正式导入海外 `horse / jockey / race` 候选 `7691` 条中的新增/更新项；同时补齐当前发现的 WP Stud 赛事、骑师和马场社区术语，正式新增 `1891` 条。`2026-07-06/07` 已完成最终清洗与 WP Stud HorseList 全量马名补齐：最终 `seed_candidates_final.csv` 共 `11257` 行，生产正式导入新增 `1169`、更新 `10088`、错误/跳过 `0`，并修复既有马名国别后缀和赛事年份标记脏数据。当前生产正式术语为 `TermEntry=16558`、`TermAlias=19293`，active 马名国别后缀术语 `0`、active 赛事年份标记术语 `0`；`source_language=en` 已覆盖香港、英国、法国、美国、日本和 other 的马名/赛事/骑师/马场，HKJC 官方仍保持最高优先级，WP Stud 只作为社区来源和人工审核佐证。
- HKJC 日语 alias 合并与文章术语回填工具：`2026-07-07` change `hkjc-ja-alias-article-backfill` 已实现并部署生产 `a65c1ed`。新增 `merge_hkjc_ja_aliases` 用于把同中文目标的日语主术语安全并入 HKJC 英文概念并停用冗余日语主术语；新增 `backfill_article_terms` 用于对已发布文章中文字段执行可审计术语回填。生产已合并 `112` 条 HKJC 日语 alias，文章回填扫描 `713` 篇日文已发布文章并更新 `29` 个字段、跳过 `2` 个人工字段；`/news/7117/` 已确认显示 `欢快舞步`。
- 多地区新闻常态生产：`operate-multiregion-news-production` 已实现、部署生产并归档；`2026-07-01` 已继续归档 `add-netkeiba-horse-data-import`、`expand-international-racing-coverage`、`guard-qqbot-offline-send`，生产服务器运行 `8c83708`，已具备只读审计、通用 enabled 新闻来源轮询、非日本默认人工审核、地区/来源自动发布灰度、后台地区生产概览、QQ 国际新闻地区标签和运行手册。当前 `NEWS_SOURCE_POLL_ENABLED=true`，轮询覆盖五个地区，每轮最多 12 个来源；非日本自动发布 allowlist 已开启香港、英国、法国、美国四个地区并保留每日小上限护栏，正式群仍需显式配置地区。
- 法国新闻源扩展：`2026-07-07` OpenSpec change `expand-france-news-sources` 已部署生产提交 `bfc3445`。新增 `tdn_france_broad` 英文补充来源，生产只读探测 accepted：HTTP `200`、列表 `20`、详情样本 `5`、详情错误 `0`、重复 `0`。生产已启用 `NewsSource#21`，`enabled=true`、`production_approved=true`、有效轮询 `15` 分钟；发布白名单已加入 `tdn_france:access` 和 canonical 入库使用的 `tdn:access`。真实抓取验证已入库法国新来源文章 `4` 篇，均完成翻译并进入正常人工复核，当前无来源白名单或抓取失败阻断。
- 英文术语门禁误挡修复：`2026-07-07` OpenSpec change `fix-english-term-gate-region-filter` 已部署生产提交 `bfc3445`。英文发布校验第一版改为同地区 + 全局术语范围，配置化高歧义英文词降级为 warning；新增近期误挡文章重处理命令和生产审计 `gate_issues` 摘要。上线后 dry-run 验证：香港、美国、法国最近 3 小时无可释放 `core_term_missing` 候选；英国有 `1` 篇候选但仍是真实核心术语缺失，未执行 commit。
- 非术语门禁误挡修复：`2026-07-10` 本地已按候选池 raw 分类检查 `is_likely_term=yes/no/review`。`yes` 共 `369` 条均已存在正式术语 ID，生产只读核对对应 `350` 个唯一 `TermEntry` 全部存在且 active，无需补库；`no` 共 `89` 条已确认为非术语，代码新增 `MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS` 默认列表，发布校验命中后写 `non_term_gate_ignored` / `info` 且不生成核心术语 blocker；`review` 类暂不批量建词。当前已通过本地目标测试和 `manage.py check`，尚未部署生产。
- `2026-07-07 21:00` 线上回归复核：生产 `HEAD=dcb9b90`，服务健康；`tdn_france_broad` 再次探测 accepted，生产自然窗口已通过 `source_config=21` 入库法国文章 `10` 篇，其中 `9` 篇已翻译、`1` 篇翻译中。该来源当前 `CrawlJob#9355` 仍在运行，Celery 日志显示模型接口持续 `200 OK`，结论为单轮处理耗时偏长但仍在推进；最近 90 分钟发布/QQ 窗口均有成功账本和明确 0 原因。英文门禁 dry-run 未发现可释放误挡文章。
- `2026-07-07` 已修复并重新启用 `tdn_france_broad`：该来源此前使用 TDN WordPress search API，返回历史相关性结果且不带发布时间，adapter 将缺失日期兜底为当前时间，导致 2020/2022/2023/2024 旧文被当作当天新闻入库并有 5 篇自动发布。OpenSpec change `fix-tdn-france-search-date-freshness` 已部署生产 `ad587ce`，现在会二次读取 TDN post API 的真实 `date_gmt/date`，缺失日期或超过 3 天新鲜度窗口的条目会跳过且写入抓取摘要。已将误发布旧文 `7255/7263/7264/7265/7271` 撤回公开，公网详情均返回 `404`；生产 `NewsSource#21` 已恢复 `enabled=true`、`production_approved=true`。线上真实抓取 `CrawlJob#9445` 成功，`new_count=0`、`seen_count=0`、`skipped_count=80`，无新增旧文。
- 后台术语运营：候选详情页和文章编辑台支持原文选区快速加入术语库；新增术语成功后可一次性将该术语应用到当前文章已有中文稿
- 前后台移动端适配

## 3.1 已完成并部署生产（体验升级）

- 公开首页资讯流升级主 OpenSpec change：`upgrade-public-home-info-feed`
  - Web 端已实现：轻导航、主头条、普通新闻流、右侧热门/重点辅助模块
  - 移动 H5 已实现：轻顶部、轻量头条、高密度左文右图新闻列表
  - 实施方式：严格 TDD，按可测试行为逐轮执行 RED -> GREEN -> REFACTOR；热门代理使用有限候选集与批量快照读取
  - 首版不做原生 App、手工置顶、搜索频道、专题、赛事日历、站内评论或站内浏览量
  - 当前状态：本地实现、Django 测试、OpenSpec 校验、桌面/移动浏览器验收和 OpenSpec 归档已完成；`2026-06-22` 已通过 PR #1 合并并部署到生产 `e834f58`
- 移动端首页密度 follow-up：
  - 已小幅压缩移动端头条区域，隐藏头条摘要并收紧顶部间距
  - 390px 浏览器验收中，首屏普通新闻卡可见数量从生产基线的 3 条提升到 4 条
  - 当前状态：`2026-06-23` 已通过 PR #2 合并并部署到生产 `04e2ee9`

## 4. 已完成（上线准备）

### 4.1 生产配置

- 安全配置：`DEBUG`、`ALLOWED_HOSTS`、`CSRF_TRUSTED_ORIGINS`、Cookie、HSTS、反代头
- 日志配置：控制台 + 可选文件日志
- 数据库配置：支持 RDS 参数（超时、连接复用、sslmode）

### 4.2 后台入口与路由

- 后台入口：`/admin/`
- 后台登录：`/admin/login/`
- Django Admin：`/django-admin/`
- 兼容跳转：
  - `/login/` -> `/admin/login/`
  - `/console/` -> `/admin/`

### 4.3 OSS 媒体存储

- 新增 OSS 存储后端：`stable.services.oss_storage.AliyunOSSStorage`
- 图片本地化、封面上传统一走 `default_storage`
- URL 解析兼容本地与 OSS

### 4.4 部署资产

- 标准模式（RDS）：`docker-compose.prod.yml`
- 低成本模式（本机 PG）：`docker-compose.prod.lowcost.yml`
- Compose 兼容包装脚本：`deploy/docker/compose-wrapper.sh`
- Docker 与启动脚本：
  - `Dockerfile`
  - `deploy/docker/start-web.sh`
  - `deploy/docker/start-worker.sh`
  - `deploy/docker/start-beat.sh`
  - `deploy/docker/wait_for_services.py`
- Nginx：`deploy/nginx/nginx.conf`
- 部署脚本：
  - `deploy.sh`
  - `deploy_lowcost.sh`
  - `deploy/deploy.sh`
  - `deploy/deploy_lowcost.sh`
- 回滚脚本：
  - `deploy/rollback.sh`
  - `deploy/rollback_lowcost.sh`
- 备份恢复脚本：
  - `deploy/backup_db.sh`
  - `deploy/upload_backup_to_oss.py`
  - `deploy/restore_db.sh`

### 4.5 文档资产

- [生产部署指南](E:/Codex/docs/deploy_production.md)
- [阿里云香港手把手指南](E:/Codex/docs/alicloud_hongkong_step_by_step.md)
- [回滚指南](E:/Codex/docs/rollback_guide.md)
- [备份与恢复指南](E:/Codex/docs/backup_recovery.md)
- [生产检查清单](E:/Codex/docs/production_checklist.md)
- [后台使用说明](E:/Codex/docs/backend_usage.md)
- [PRD 归档说明](E:/Codex/docs/PRD/README.md)

### 4.6 Codex 协作资产

- 当前规则入口：`AGENTS.md`、`docs/codex_workflow.md`
- 新任务持久规格：`docs/changes/<slug>/`
- 工程计划审核 fallback：`.codex/skills/plan-eng-review`
- Codex 领域代理：`application`、`integration`、`operations`
- Codex 只读审核代理：`reviewer`、`security-scanner`
- OpenSpec legacy 配置与历史/在途 artifacts：`openspec/config.yaml`、`openspec/specs/`、`openspec/changes/`；相关 skills 与 workflow-spine 已停用，不作为新流程入口或门禁
- 当前流程为“探索 -> spec/design -> 方案审核 -> 测试先行 -> 子代理实现 -> 新子代理 `/review` -> 用户授权后发布”
- `start-hkjc-data-import-and-global-spikes` 已完成 `/plan-eng-review`、TDD 红灯测试、最小实现、read-only spike、生产部署、验证和归档；生产服务镜像来自 `b0361cf`。2026-06-26 已在生产执行一次 HKJC fixture 样本 commit（`run_id=1960`），写入 `1` 场、`2` 条报名、`2` 条成绩、`2` 匹马和 `4` 条别名；该样本不来自真实网络抓取，也不生成公开比赛页。英法美三地当前均为 `needs_more_spike`。正式规格已同步到 `openspec/specs/global-racing-data-import-readiness/spec.md`；后续如要正式导入英法美或真实 HKJC 网络适配，应另起 change。
- `connect-real-global-racing-databases` 已创建并通过 OpenSpec 严格校验；目标按香港、英国、法国、美国顺序接入真实赛马数据库，每地抓最近 2 个月赛事和涉及马匹详情后停止。当前香港阶段已完成 HKJC 官方 HTML 单场真实 dry-run 和隔离 SQLite commit：`HK20260624HV01` 解析并写入 `1` 场、`12` 条报名、`12` 条成绩、`12` 条英文别名；并已完成 recent-days/date-range 小范围真实链路，`--recent-days 60 --end-date 2026-06-26 --limit-races 1 --limit-horses 1` dry-run 请求 `4` 次官方页面，返回 `completion.is_complete=false`、`meetings_found=28`，隔离 SQLite commit 写入 `1` 场、`12` 条报名、`12` 条成绩、`1` 匹马 profile 和 `12` 条别名，重复执行正式对象计数不增长。HKJC 追加 plan-only 批次预检：过滤 overseas `S*` racecourse 后，最近 60 天本地香港 `HV/ST` 比赛为 `144` 场，可按每批 `20` 场拆为 `8` 批；已通过 `--skip-races 20` 真实 smoke 证明日期范围后续批次可从第 21 场开始，并通过 `--race-ids HK20260624HV02,HK20260613ST04 --limit-horses 1` 真实 smoke 证明可按指定 race_id 精确批次只请求目标比赛和受限马匹详情。英法美已追加 `18` 次只读入口复核：英国 `Sporting Life + BHA` 可行性最高，美国 `Equibase` 入口更具体但 chart/PDF 仍需 fixture spike，法国 `France Galop` 仍未定位稳定结构化查询参数。下一步仍需部署后执行 HKJC 生产最近 2 个月全量 dry-run/commit，香港完成后再按顺序进入英国正式 parser/importer TDD。
- 生产 HKJC 真实网络运行状态：`connect-real-global-racing-databases` 当前实现已部署到生产 `04c0444`，备份 `backups/db/pre-hkjc-real-network-20260626_202442.sql.gz` 通过校验，部署后 check/healthz/小样本 dry-run 通过，生产 plan-only 仍为 `144` 场、`8` 批；第 1 批 full dry-run 曾在马匹 profile 补抓阶段遇到 HKJC `ReadTimeout` / TLS handshake timeout 中断，该次未 commit、未写表，HKJC 锁为空且表计数仍为上次 fixture 样本 `1/2/2/2/4`。已按 TDD 补 transient timeout retry 并重新部署，随后将前 6 个 plan-only 批次拆成 24 个 5 场小批次 dry-run，均 `completion.is_complete=true`，累计覆盖 `120` 场、`1522` 条 entries、`1522` 条 results 和 `1522` 个 horse profile 请求，当前停在生产 commit 前确认点。
- `connect-real-global-racing-databases` 的本轮目标已在 `2026-06-27` 调整为确认四地真实抓取能力可用，并按该口径完成：HKJC 生产真实 dry-run 证据成立，UK / France / US 少量真实 proof 证明 Sporting Life、Geny、Horse Racing Nation 的赛事、赛果和马匹详情入口可访问并可解析；新增 importer、审计命令、batch command 渲染器、fixtures、OpenSpec 规格/归档和 proof 文档已从干净 `origin/main` 基线整理为独立上线包。代码提交 `93b7007` 已部署生产，check/healthz/首页/命令入口/proof-only 审计和导入锁状态均通过；最近 60 天完整大量爬取和生产 `--commit` 保持为后续单独执行窗口。

## 5. 当前验证结果

- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py check`：通过
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable`：通过，147 项
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests stable.tests.TermCandidateDiscoveryTests --noinput`：通过，49 项
- `openspec validate use-external-horse-alias-for-name-recognition --strict`：通过
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable.tests.PublicHomeInfoFeedTests`：通过，10 项
- `openspec validate upgrade-public-home-info-feed --strict`：归档前通过
- `openspec validate --all`：归档前通过；同步正式规格并归档后再次通过
- 公开首页资讯流浏览器验收：桌面首页、移动首页、桌面详情页、移动详情页通过；移动普通卡约 128px 高，无横向溢出，图片加载正常
- 公开首页资讯流生产验收：服务器 HEAD `e834f58`，`http://umafans.run/healthz/` 与 `/` 均返回 `200`，首页引用 `/static/stable/public.2eec24723b45.css`，390px 移动端普通新闻卡约 `128px` 高且首屏头条后可见 3 条普通新闻
- 移动端首页密度 follow-up 生产验收：服务器 HEAD `04e2ee9`，`http://umafans.run/healthz/` 与 `/` 均返回 `200`，首页引用 `/static/stable/public.9aaf4b105424.css`，390px 视口下头条约 `257px` 高，第一张普通新闻卡 `top=388`，首屏可见 4 条普通新闻卡，普通卡仍约 `128px` 高，无横向溢出
- 自动发布门禁优化生产验收：服务器 HEAD `42a4622`，迁移 `stable.0009_automation_publish_gates` 已应用，`AUTO_REWRITE_ENABLED=false`、`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`、`AUTOMATION_WARNING_EMAIL_ENABLED=true` 已生效，`http://umafans.run/healthz/` 与 `/` 均返回 `200`
- 三个运营改造 change 生产验收：服务器 HEAD `7f54f13`，`web / worker / beat` 已重建，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `/` 均返回 `200`；运行态确认 netkeiba 新着顺 / 访问量榜 / 注目数榜调度分钟为 `00/16/26`，OpenSpec 归档后 `openspec validate --all` 通过
- 外部马名索引识别链路生产验收：服务器 HEAD `35b0866`，`manage.py check` 通过，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和 `/` 均返回 `200`；生产只读 smoke test 确认 `ExternalHorseAlias=11521`，`ロブチェン` 可识别为 `external_alias`
- 榜单重点 QQ 推送与公开文章 ID URL 生产验收：服务器 HEAD `00e4bd4`，生产 `.env` 已切换为 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`；`manage.py check` 通过，`http://umafans.run/healthz/` 与 `/` 均返回 `200`，抽检 `/news/<article_id>/` 返回 `200`，旧 slug URL 返回 `302` 并跳转到 ID URL
- 榜单重点 QQ 推送相关 OpenSpec 归档：`add-qqbot-auto-push`、`elevate-ranked-netkeiba-sources`、`push-ranked-news-to-qq`、`use-article-id-public-urls` 已归档并同步正式规格，归档后 `openspec validate --all` 通过
- QQ Bot 登录态恢复与离线防护本地验证：2026-06-26 排查确认 NapCat 登录态失效会导致 OneBot 无法发送；重新扫码登录后 `/get_status online=true`、测试群消息发送成功，并恢复 `QQ_PUSH_ENABLED=true`。本轮补充自动推送发送前 OneBot 在线预检，离线或状态检查失败时不调用发送接口、不增加 `attempt_count`，完整 `stable` 测试通过 268 项。
- QQ Bot 离线防护生产验收：服务器 HEAD `a2146d6`，部署前 `.env` 备份为 `.env.backup.qqbot-offline-guard-20260626_223731`；部署后 `manage.py check` 通过，本地和公网 `/healthz/` 均返回 `200`，worker 环境确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`BotPusher().is_online()` 返回 `(True, '')`，测试群 `1026525240` 发送部署验证消息成功。
- `docker compose -f docker-compose.prod.yml config`：通过
- `docker compose -f docker-compose.prod.lowcost.yml config`：通过

说明：本地 `.env` 若指向不存在的 `postgres@db`，测试建库会失败，这是本地环境问题。

## 6. 当前待办（项目级摘要）

- 观察公开首页资讯流生产运行，重点看首页、详情页、图片、静态资源和移动端首屏密度
- 下一轮数据续抓建议优先补结构化赛事数据：先补英国 / 法国赛事详情与五地区历届冠军，再恢复 HKJC 长窗口 dry-run，最后按 `global_racing_full_crawl_runbook` 推进英国、法国、美国最近 60 天外部赛马数据库完整 dry-run。`2026-07-10` 已只读校验英法赛事详情候选：英国基础赛事 `202` 场、已完赛 `123` 场、规范候选 `122` 场；法国基础赛事 `173` 场、已完赛 `74` 场、规范候选 `74` 场，原始 ZEturf 候选 `80` 条中的 `6` 个重复 slug 已在规范包中去重。随后生产复核显示英法详情已经正式导入，英国 `Jane Seymour Nov. Hurdle` 在线状态为 `cancelled` 不需补赛果；本次仅修复 `GRAND PRIX DE SAINT-CLOUD` 历史冠军当前年残留误配，将 `2026` 冠军从 `ZELMAN` 修为 `CALANDAGAN`，生产备份为 `backups/db/pre-race-detail-gpsc-history-repair-20260710_025949.sql.gz`。
- 赛事日历正式填充：`2026-07-06` 已按“官方源优先、本地语言优先、先 CSV/JSONL dry-run 再正式导入”的流程批量写入 2026 目标地区重要赛事。生产当前 `RaceEvent=995`、`RaceEventAlias=3277`；2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `203`、法国 `174`。已完成基础表：日本 JRA 中央重赏 `140` 场、日本 NAR/交流ダートグレード `46` 场、香港 HKJC 已公开 2026 分级赛 `19` 场、美国 TOBA Grade 1/2/3 `411` 条、英国 BHA Flat Group 1/2/3 `138` 场、英国 BHA Jump 2026 年 1-4 月 Grade 1/2 `64` 场、法国 France Galop Groupe I/II/III `173` 条。详情表已导入日本、香港、美国当前可用批次：JRA 已完赛中央重赏 `74` 场、NAR 已完赛 `20` 场、NAR `2026-07-08` 已公布赛前出走表 `1` 场、HKJC 已公开香港分级赛 `19` 场、美国 TOBA 已完赛 Grade 1/2/3 `195` 场；生产 `RaceEventRunner=3260`、`RaceEventResult=2977`、`RaceEventHistoryWinner=0`。`取消/除外/中止/空白着顺/WV` 保留在出走表状态中，同着用唯一排序位写库并在 `source_refs.official_finish_position` 保留官方名次，前台已热补丁为展示官方名次。美国 Equibase chart 当前仍返回防护页，因此美国赛果暂用 HRN track-day 可见结果顺序；Kentucky Derby / Oaks 等 HRN 未公开结果块的场次只显示出走表。剩余详情缺口：JRA 未来 66 场、NAR 未来 25 场需等官方出走表或赛果发布，英国/法国详情来源解析，以及五地区历届冠军。
- 多地区术语库与外部马名索引：`2026-07-03` 生产只读核对显示，正式术语库和术语候选池仍主要是日文。`2026-07-04` 至 `2026-07-07` 已连续导入术语种子：第一批 fixture 候选、WP Stud 香港/海外来港社区马名、HKJC 当前本地马 A-Z 官方英文马名、HKJC 本地赛果 `2024-01-01` 至 `2026-07-04` 候选、HKJC overseas `2024-01-01` 至 `2026-07-04` 官方 `horse / jockey / race` 候选、WP Stud 赛事/骑师/马场社区候选，以及 WP Stud HorseList 全量马名。当前生产为 `TermEntry=16558`、`TermAlias=19293`；`source_language=en` 已覆盖香港、英国、法国、美国、日本和 other 的马名/赛事/骑师/马场，active 马名国别后缀和赛事年份标记脏数据均为 `0`。外部马名索引仍以日本 `netkeiba` 为主体；英国、法国、美国当前生产 `External*` 表无写入。当前应把多地区识别能力理解为“正式术语库已大幅补齐，尤其 HKJC 官方本地/海外术语可用于英文新闻识别”，仍不等同于英法美外部赛马数据库正式落库。
- 术语种子数据准备：OpenSpec change `prepare-termbase-seed-data` 已完成实现、验证和归档；本地首版已新增 `prepare_termbase_seed_data` 管理命令、`stable.services.termbase_seed` 服务层、HKJC/WP Stud fixture、操作文档和后台术语导入模板更新；内置 fixture smoke 可生成 `seed_candidates.csv`、`seed_conflicts.csv` 与 `summary.json`，候选主表严格兼容现有 `import_terms` 字段，中文目标译名统一简体化。HKJC 专用抽取已从真实页面打通 `selecthorse -> selecthorsebychar -> zh-hk horse detail`，并新增 `--hkjc-letter` 支持按 A-Z 拆批；本地赛果路径已支持日期范围、跳过马匹详情页、双语空壳赛果页进入 `skipped_races`。OpenSpec change `prepare-hkjc-overseas-termbase-seeds` 已完成本地实现、正式规格同步和归档，归档目录为 `openspec/changes/archive/2026-07-05-prepare-hkjc-overseas-termbase-seeds/`；正式规格已包含 `hkjc_overseas` 来源、Race Card 自动发现/精确参数、QIDS 日期范围抽取、官方来源元数据、结构化证据、地区映射和 `racing_region` 导入表头。`2026-07-05` 已用该路径生成并导入 `2024-01-01` 至 `2026-07-04` 海外术语。WP Stud 解析器已扩展到赛事、骑师、马场和 HorseList 马名表；生产导入时遇到既有 HKJC 官方术语或既有日文 alias 占用时，不覆盖官方主译名，不强行合并冲突概念。`2026-07-06/07` 最终返修已验证 WP Stud HorseList 触网解析、HKJC 马名国别后缀清洗、复合年份赛事拆分和 HKJC 日本马日文 alias 补充；正式导入后生产计数为 `TermEntry=16558`、`TermAlias=19293`。
- 观察自动发布质量与自动化日志
- 补充翻译 warning 可视化和术语库补全流程
- 继续评审 OpenSpec change `expand-international-racing-coverage` 的本地实现：多地区新闻源、公开首页地区 tab、`TermEntry + TermAlias` 多语言术语概念模型、群级 QQ 推送配置、HKJC 外部数据导入和全球数据源 spike 已完成本地实现与 review 返修；上线前 review 已补齐快照 metadata 不保存整页 HTML、TDN 缺详情日期时保留列表 API 时间、英文外部马名索引识别、跨语言术语 upsert 主原文保护、术语批量别名匹配、HKJC entries/results 马匹上限统计、英文术语生命周期大小写不敏感、术语启停同步别名状态、术语导入别名冲突保护、TDN/TDN France canonical 去重和术语列表语言筛选翻页保留，尚未部署生产
- 观察外部马名索引识别链路生产效果，重点抽检 `external_horse_not_preserved` warning、候选池 `external_horse_alias` 来源质量和 JRA 活动公告类启发式误报
- 推进 HTTPS / 证书接入
- 做部署稳定化
- 完善监控、备份与回滚流程
- 观察 QQ Bot 测试群灰度；OneBot 已接通并开启 `QQ_PUSH_ENABLED=true`，当前按 `QQ_PUSH_SCOPE=high_value_only` + `QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 只等待自然榜单新闻自动推送。存量公开新闻已完成部分限速补推，剩余历史失败记录暂不继续补推。
- 验证并评审 `operate-multiregion-news-production` 本地实现；部署前必须执行只读审计、`.env` 备份、通用轮询默认关闭检查、测试群地区配置核验和至少一个自然调度窗口观察。

## 6.1 国际赛马资讯扩展规划状态

- OpenSpec change：`expand-international-racing-coverage`
- 当前状态：已完成 proposal、design、tasks、delta specs 和本地实现；尚未部署生产
- 一期新闻源本地接入最终清单：
  - 日本：`Sponichi`
  - 中国香港：`HKJC Racing News`、`SCMP Racing`
  - 英国：`Sporting Life Racing`、`Sky Sports Racing`，官方补充 `BHA`
  - 法国：仅接英文来源 `France Galop English News`、`TDN France keyword`，不接法语新闻正文
  - 美国：`TDN`、`Horse Racing Nation`
- 一期数据库实现：新增 HKJC 受控导入命令 `import_hkjc_external_data`，默认 dry-run，支持 payload 小样本提交、统计查询和马名索引查询；commit 模式必须提供 `--payload-file`，使用单来源互斥锁防止并发写入，并在超过 `max_races / max_horses` 时直接失败；`max_horses` 会合并统计顶层 `horses`、赛事 `entries` 和 `results` 中可识别的唯一马匹；`Equibase`、英国 `Sporting Life + BHA`、法国 `France Galop` 已形成 spike 文档 `docs/global_racing_data_source_spikes.md`
- 排序型入口：本轮确认 `Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可公开抓取，已作为独立排序/榜单源加入并保留原站 rank；review 返修后，同源普通 list 不会覆盖已入库的排序/榜单主来源，QQ `ranked` 重点策略也会识别这些国际榜单稿；`At The Races`、`Paulick Report`、`BloodHorse` 因 403、反爬或空样本风险保留为候选，不进入第一版默认清单
- 前台实现：公开首页增加 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，综合流第一期使用已发布文章倒序；地区页翻页保留 `region` 查询参数；公开详情继续使用 `/news/<NewsArticle.id>/` 全局自增数字 ID，国际来源去重键与公开 ID 分离
- 后台实现：术语库支持 `TermEntry` 正式术语概念 + `TermAlias` 多语言原文别名，先保留 `source_ja / aliases_ja` 现有物理字段兼容；翻译、改写、自动标签和自动化评分的术语命中按文章原文语言选择别名，并批量加载参与匹配术语的别名，避免每条术语各查一次；英文/繁中外部马名索引按同语言参与识别，先按文章候选片段收窄查询，并使用原文真实写法做保护和校验；英文正式术语按大小写不敏感方式命中并保留原文真实 matched_text；最终 review 返修后，自动化 P0 马匹命中、发布校验核心/背景术语判定和“新增术语后应用当前稿”也统一复用语言感知匹配，避免英文大小写漏判或漏替换；本轮补丁进一步将同语言术语查重、别名去重、导入 upsert、候选合并和术语 API 保存统一为大小写不敏感，并让后台/API 启停术语同步所有语言 `TermAlias` 状态；同语言大小写变体导入 upsert 会更新正式主原文并同步别名表，术语导入 upsert 命中跨语言别名时仍只维护该语言别名、不覆盖正式概念主原文；本次返修又补齐别名冲突保护，只有主原文命中时才允许 upsert，别名撞到其它术语会报错；AI 改写 prompt 的术语表使用文章实际命中的 `matched_text`，避免英文稿看到日文概念主名而漏用标准译名；自动化评分补充英文/繁中赛马关键词；QQ 推送从全局范围配置扩展为群级地区 / 范围 / 重点策略配置，旧群空地区或非法地区配置按日本兼容；内置来源同步保留人工 `enabled` 状态，支持后续按来源灰度启用
- 测试用例：`openspec/changes/expand-international-racing-coverage/test_cases.md` 已按 OpenSpec `proposal/design/spec` 建立完整验收矩阵，覆盖地区/语言、国际新闻源、公开首页、术语多语言、QQ 群级推送、HKJC 导入、欧美数据源 spike、迁移和非目标边界
- 真实新闻源探测：`probe_international_news_sources` dry-run 默认探测第一版最终矩阵；`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing access/latest`、`BHA official`、`France Galop English News official`、`TDN France keyword`、`TDN`、`Horse Racing Nation access/latest` 均已成功解析两篇真实样本
- 验证：新增测试用例矩阵和最终源清单返修后，本地 `manage.py check`、完整 `stable` 测试、`makemigrations --check --dry-run`、`openspec validate expand-international-racing-coverage --strict`、`openspec validate --all` 和 `git diff --check` 均已通过；2026-06-26 最终 review 返修后完整 `stable` 测试通过 231 项，已覆盖国际榜单来源提升后触发 QQ 自动推送编排、英文外部马名索引识别与真实写法保护、翻译保护和发布校验使用真实 matched_text、英文正式术语大小写不敏感匹配与当前稿替换、英文 P0 马匹评分、跨语言术语 upsert 主原文保护、术语别名批量匹配、HKJC entries/results 马匹上限统计、旧 QQ 群空/非法地区日本兼容、地区 tab 翻页保留过滤和英文赛马关键词评分；本轮术语生命周期补丁后完整 `stable` 测试通过 236 项，新增覆盖英文重复术语大小写不敏感拒绝、API 创建/更新同步别名、术语启停同步别名状态、候选合并大小写去重、同语言大小写变体导入 upsert 更新主原文，以及 AI 改写 prompt 使用英文实际命中别名；本次上线前返修后完整 `stable` 测试通过 241 项，新增覆盖术语导入 upsert 原文别名冲突预览/提交双重拒绝、`TDN France keyword` canonical 去重并保留法国地区信号、以及术语列表分页保留原文语言筛选

## 7. 当前上线进展（摘要）

- 2026-07-10 `classify-english-term-gate-context` 已部署生产 `43898ff` 并归档到 `openspec/changes/archive/2026-07-10-classify-english-term-gate-context/`，正式规格已同步到 `automation-publish-gates`：英文术语门禁会在生成 `core_term_missing` 前按上下文输出 `common_word / proper_noun / uncertain`；普通英文词种子默认降级为 warning，只有 `wins / returns / runs / targets / entered` 等强动作上下文才继续保守阻断；`Classic`、`Contact and live updates from York`、`Live stable updates` 等普通语境均有回归测试覆盖。重校验命令已支持有界候选、批量术语/alias 预加载、文章级英文分类明细和地区 summary。上线前后已通过本地 check、11 项目标测试、OpenSpec 严格校验、语法检查、生产 `manage.py check` 和内外 `/healthz/` smoke。生产只读完整 dry-run 产物在 `runtime/multiregion_candidate_audit/reprocess_full_dryrun_20260710_030944/`：四地区旧 `core_term_missing` 候选合计 `146` 篇，完整门禁通过可恢复候选 `37` 篇（香港 `3`、英国 `5`、美国 `22`、法国 `7`），仍阻断 `109` 篇；本次未执行 `--commit`。
- 2026-07-10 `support-multiregion-news-attribution-and-english-gates` 已完成本地实现：文章从单地区扩展为“主地区 + 关联地区”，英文术语门禁改为使用文章地区集合，公开地区 tab / QQ / 运营汇总按关联地区可见，发布配额仍只由主地区消耗；站内编辑页和 Django Admin 支持人工修正并锁定归属。新增 `reprocess_multiregion_attribution_gates` 命令用于 dry-run/commit 重算归属与门禁，commit 不直接发布。新增配置 `MULTIREGION_ATTRIBUTION_ENABLED`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED`、`MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES`；关联地区查询开关关闭时，公开卡片和详情也只显示主地区，不删除关联数据。本地目标测试 20 项、完整 `stable` 回归 540 项通过，线上前仍需执行生产 dry-run 抽样。
- 2026-07-10 未提交改动复审已补齐 `stable.0023_multiregion_news_attribution` 迁移，并修正新内容类别的下游兼容：赛事关联识别 `preview / tips / result_brief`，AI 改写覆盖全部新类别，同时保留旧类别；SQLite 测试库已实际应用迁移并新增类别映射回归测试，完整 `stable` 测试 `522` 项通过。本次未部署或执行生产迁移。
- 2026-07-10 多地区 change 代码审查返修已完成：赛事/赛场与一般地区上下文分层，多个模糊上下文回退主来源，来源 URL 不参与归属，重复来源抓取使用文章最终主来源；单地区回退开关覆盖 QQ 即时推送；人工归属锁定可取消；重处理 dry-run 与 commit 对锁定文章保持一致；`other` 默认不进入 QQ。相关测试组 `123` 项、完整 `stable` 回归 `529` 项通过，生产抽样任务仍保持未完成。
- 2026-07-10 第二轮审查返修已完成：编辑页可清空全部关联地区，Admin 非法主/关联地区重复改为字段级错误，重处理 `--limit` 按有效候选计数并输出扫描/截断状态，网页和 QQ 明确区分主地区与关联地区。目标测试 `19` 项、相关链路 `129` 项、完整 `stable` 回归 `534` 项通过；生产抽样任务仍未完成。
- 2026-07-01 本地新增 `increase-multiregion-news-volume` 实现：以 `ProductionWindow` 为抓取、发布和 QQ 推送的统一窗口账本；日常 15 分钟、重要赛事 5 分钟；每地区发布窗口最多 5 篇、保底 1 篇且不绕硬门禁；QQ 每地区每窗口最多 3 篇并保留群/全站小时配额。2026-07-02 review 返修后，抓取和 QQ 恢复补跑只执行最近缺失窗口，历史窗口记为合并跳过；可重试 QQ delivery 重新发送前必须占用配额；抓取窗口由真实抓取完成后回写成功/失败，HTTP 403/429 进入来源错误分类，QQ 窗口会在创建 delivery 前检查 OneBot 在线状态。新窗口生产开关默认关闭，需审计通过后再在生产显式启用。
- 2026-07-02 `increase-multiregion-news-volume` 已上线生产：生产运行 `9e97e8c`，迁移 `0017/0018` 已应用，新窗口抓取/发布/QQ 开关均已开启，16 个启用新闻源已 `production_approved=true`。生产 smoke 显示 20:15 抓取窗口 14 成功、1 个 Sponichi 上游 502 失败；20:15 发布窗口香港 1 篇、美国 3 篇，20:30 美国继续发布 1 篇，其余地区均有 `no_ready_candidates` 原因；20:15 QQ 美国发送 2 条，20:30 美国为 `already_sent`，其余地区为 `no_eligible_articles`。公开首页和地区页浏览器验收通过，ops 摘要通知已发送到测试群 `1026525240`。因当前为后半夜新闻低峰，用户确认实际 4 个自然窗口验证延期到次日继续。
- 2026-07-02 白天复核最近 6 小时自然窗口：生产已运行 `a122130`，公网 `/healthz/`、首页和抽检文章页均返回 `200`，Celery 队列为空。发布 / QQ 各地区均有 `24` 个 15 分钟日常窗口；抓取窗口 `260` 个成功、`109` 个因恢复补跑合并跳过。新窗口实际发布美国 `1` 篇、日本 `9` 篇，所有非零窗口均未超过每地区 `5` 篇；QQ 实际发送美国 `3` 条、日本 `3` 条，未超过每地区每窗口 `3` 条；其余 0 发布 / 0 推送窗口均有 `no_ready_candidates`、`no_eligible_articles` 或 `already_sent` 原因。16 个生产批准来源最新抓取均为 `success`。
- 2026-07-02 11:07 追加按地区拆因：最新 4 个发布窗口五地区均 0 发布；日本有候选但全部被 `hard_gate_blocked`（翻译失败、人工审核要求、核心术语缺失），香港 / 英国 / 法国 / 美国没有进入发布候选的文章。最近 3 小时非日本来源抓取成功但新增为 0、只命中重复旧稿；TDN France / TDN 美国早间短暂超时后已恢复，当前不是 0 发布主因。
- 2026-07-02 15:10 复核最近 2 小时窗口：五地区发布 / QQ 窗口均按 15 分钟节奏成功运行；网页发布 0 篇、QQ delivery 0 条，原因分别为 `no_ready_candidates` / `no_eligible_articles`。最近 2 小时抓取新入库 8 篇（日本 5、香港 1、英国 2），但均处于翻译失败或人工审核要求状态，未达到自动发布条件；TDN France 与 TDN 美国 15:02 各出现一次 read timeout，failure streak 为 1，属于上游短时超时。
- 2026-07-03 00:13 今日窗口复核：今日目前只有 `00:00` 一个自然窗口，抓取 / 发布 / QQ 均正常生成并成功；新入库 1 篇美国 TDN 新闻，发布 0 篇、QQ 0 条，原因分别为 `no_ready_candidates` 和 `already_sent / no_eligible_articles`；16 个生产批准来源最新状态均为 `success`。
- 2026-07-03 复核 2026-07-02 全日窗口：昨日实际覆盖 `04:00-23:45` 共 80 个 15 分钟窗口起点；发布窗口五地区各 80 个且全部成功，窗口发布日本 37、香港 1、美国 10，英国/法国 0；QQ 窗口五地区各 80 个且全部成功，窗口派发日本 3、美国 5，所有昨日 QQPushDelivery 记录均为 sent；抓取窗口无 failed，窗口 payload 新增日本 79、香港 5、英国 11、法国 1、美国 28，日本榜单唤醒 7 次。
- 2026-07-03 地区归属错配审计：现有 `NewsArticle.racing_region` 与新闻源地区完全一致，6598 篇中 0 篇偏离“按新闻源地区”。严格实体地区口径只覆盖 462 篇且均为日本文章，按用户提出的第一种/第二种逻辑未发现结构化错配；但生产实体地区数据不足，审计当时 `TermEntry.racing_region` 全为空，英法美外部马名/赛事正式缓存未落库，因此该 0 只能视为下限。2026-07-04 仅补写了首批 `10` 条术语地区，仍不足以支撑可信实体地区识别。关键词粗扫有 1213 篇疑似跨地区提及，需后续做实体地区识别改造后才能给出可信错配数。
- 2026-07-02 OpenSpec change `revive-ranked-news-for-publish` 已完成本地实现：未发布文章从普通来源升级为榜单来源时会写入 `ranked_revived_at` 和 `decision_reason.ranked_revival`；低分 ignored、价值不足人工状态、翻译失败和待翻译文章可被唤醒，翻译未完成先重试，已翻译文章重新进入自动化评分；人工拒绝、撤回、重复 blocker 和硬门禁不绕过。发布窗口候选回看同时支持 `first_seen_at` 与 `ranked_revived_at`，候选决策 payload 会记录榜单唤醒来源和时间；已发布文章仍只沿用现有 QQ 补推，不重复发布。
- 2026-07-02 `revive-ranked-news-for-publish` 验证与上线：目标榜单唤醒测试通过，完整 `stable` 测试通过 418 项；`manage.py check`、`makemigrations --check --dry-run`、OpenSpec 严格校验、全量 OpenSpec 校验和 `git diff --check` 均通过。OpenSpec change 已归档并部署生产 `a774672`，迁移 `0019_newsarticle_ranked_revived_at` 已应用；生产 `/healthz/`、首页、后台登录入口、容器状态、Celery 队列和日志 smoke 均通过。
- 目标服务器：阿里云香港 ECS，采用低成本部署方案（本机 PostgreSQL + OSS）
- 仓库线上基线：`main` 分支已包含生产化改造与低成本部署脚本
- 已发现并修复一项部署兼容性风险：
  - 部分 Ubuntu 镜像仅提供 `docker-compose`
  - 项目部署/回滚脚本现已兼容 `docker compose` 与 `docker-compose`
  - 兼容包装脚本已调整为优先使用 `docker-compose`，避免旧环境误判
- 已发现并修复一项镜像拉取风险：
  - `worker / beat` 使用本地构建镜像 `umanewsbot:prod`
  - 部署脚本已改为仅拉取外部依赖镜像，避免误向公共仓库拉取业务镜像失败
- 已发现并修复一项健康检查风险：
  - 容器内 `curl http://127.0.0.1:8000/healthz/` 会命中 Django `DisallowedHost`
  - 应用现已自动允许回环地址进入 `ALLOWED_HOSTS`，兼容 Docker 健康检查
- 已识别一项远端编排兼容性风险：
  - 服务器自带 `docker-compose 1.29.2` 在重建带卷容器时会触发 `KeyError: 'ContainerConfig'`
  - 部署策略调整为优先使用 `docker compose` v2 插件，必要时在 ECS 上手动安装官方 CLI plugin
- 已开始域名接入准备：
  - 目标域名为 `umafans.run` 与 `www.umafans.run`
  - 当前阶段正式域名 HTTP 接入修复已完成
  - 下一阶段进入 HTTPS / 证书接入与部署稳定化
- 已拿到生产所需核心密钥：
  - `SILICONFLOW_API_KEY`
  - `OSS_ACCESS_KEY_ID`
  - `OSS_ACCESS_KEY_SECRET`
  - `OSS_BUCKET_NAME`
- 当前下一步：
  - 观察自动化发布质量，重点看 warning 邮件、重复内容阻断和候选池门禁展示
  - 生产灰度前先评审外部赛马数据导入配置，执行 dry-run 和单月小批量验证
  - 补充翻译 warning 可视化和术语库补全流程
  - 推进 HTTPS / 证书接入
  - 做部署稳定化
  - 完善监控、备份与回滚流程

## 8. 协作约定

1. 每次开始项目前优先阅读 [docs/current_state.md](E:/Codex/docs/current_state.md) 与 [AGENTS.md](E:/Codex/AGENTS.md)，本文档作为项目级摘要辅助阅读。  
2. 每次更新完成后同步回写本文件与 [docs/current_state.md](E:/Codex/docs/current_state.md)。  
3. 每次收到新 PRD 归档到 `E:/Codex/docs/PRD/`。  
4. 每次阶段性收工时同步更新 [docs/work_log.md](E:/Codex/docs/work_log.md)。

## 9. 专有术语候选发现状态

- 已完成四类实体候选发现：马名、比赛名、骑手名、马主名。
- 已完成正式术语去重、已有候选聚合、按文章证据留存和跨类型冲突提示。
- 已完成工作人员候选审核后台与单篇重新发现入口。
- 已完成接受、修改后接受、合并、拒绝、忽略和保守批量操作。
- `2026-06-07` 已部署生产并应用迁移 `0006`（服务器到 `e2e3e07`），生产默认关闭，待单篇抽检后通过 `TERM_DISCOVERY_ENABLED` 灰度启用。
- 当前验证：Django 检查通过，`stable` 69 项测试通过，两种生产 Compose 配置检查通过，并完成本地隔离环境浏览器功能验收。

## 10. 外部赛马数据导入状态

- 已实现 `add-netkeiba-horse-data-import` OpenSpec change 的首版代码。
- 新增外部比赛、出走、赛果、赔率、马匹、履历、马名索引、导入运行、错误记录和单来源锁模型。
- 新增 `import_external_horse_data` 管理命令和 `import_external_horse_data_task` Celery 任务。
- 生产默认关闭：`EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false`、`EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
- 当前能力只维护本地外部赛马数据缓存，不改变新闻抓取、翻译、改写、自动发布或公开前台。
- 当前验证：Django check 通过，`stable` 147 项测试通过。
- 生产首轮小批量已完成：`run_id=1`，`2026-05` 前 10 场，成功 10、失败 0，写入 143 个唯一马 ID/马名索引。
- `2026-06-24` 已补充按月续跑跳过已落库 race 的逻辑，后续可继续对 `2026-05` 做小批量下一批导入。
- 生产第二批续跑已完成：`run_id=2`，累计 20 场比赛、274 个唯一马 ID/马名索引，失败 0。
- 生产第三批续跑已完成：`run_id=3`，累计 50 场比赛、695 个唯一马 ID/马名索引，失败 0。
- 生产长循环导入在 `run_id=9` 以退出码 `137` 中断；已停止继续导入、释放锁并标记 partial。当前累计 182 场比赛、2401 个唯一马 ID/马名索引，服务健康。
- 外部马名索引已接入生产识别链路：翻译阶段保护外部已知但无中文译名的马名，发布校验输出独立 `external_horse_not_preserved` warning，术语候选发现会把新闻中出现且缺少正式中文译名的外部马名以 `external_horse_alias` 来源送入候选池；同名普通词需要强马名上下文才会被识别为马名；review 返修后，保护名单 `limit` 不再被已有中文译名的正式马名占用。OpenSpec change `use-external-horse-alias-for-name-recognition` 已归档到 `openspec/changes/archive/2026-06-25-use-external-horse-alias-for-name-recognition/`，正式规格已同步，并已通过 PR #6 部署到生产 `35b0866`。
- 长文样本抽检显示：netkeiba 长文可有效命中外部马名索引，但 JRA 活动公告类长文仍会通过启发式误报普通片假名词，后续需要继续补普通词过滤或收紧启发式马名规则。

## 11. 2026-07-11 未提交变更状态

- 当前分支已快进到最新 `origin/main`，保留并整合多地区新闻归属、英文门禁和赛事历史抓取编排两组未提交改动。
- 多地区新闻迁移已调整为 `0023_multiregion_news_attribution`，依赖主干 horse profile `0022`，本轮未执行生产迁移。
- 赛事抓取编排已补齐应到审批、地区专属 adapter 输入、空内容与来源 URL 门禁、应到身份复核、真实 gzip 校验和完整人工批准元数据。
- 目标测试 `48` 项、完整 `stable` 回归 `588` 项通过；Django check、迁移漂移、两个 change 严格校验、OpenSpec 全量 `21` 项和 `git diff --check` 均通过。
- 后续 review 中纯技术问题由 Codex 直接判断修复；产品能力、运营口径和交互变化仍由用户审核。
- 2026-07-11 第六轮赛事抓取返修：批量 importer 已整批事务化；应到快照保存完整 adapter 输入且审批后 `RaceEvent` 漂移会阻断；pending 混合来源确认不再提供策略 SHA。按用户决定暂不强制哈希参数、暂不增加请求预算并发锁。目标测试 `67` 项、完整 `stable` 回归 `589` 项通过，Django/迁移/OpenSpec/diff 校验均通过；`orchestrate-race-event-data-crawls` 已同步正式规格并归档。
- 2026-07-11 生产部署前发现多地区归属开关关闭后仍扫描完整术语库，导致 crawl worker 高 CPU；已增加禁用/人工锁定短路，目标测试 `30` 项、完整回归 `591` 项通过。归属开关保持关闭，五地区产品抽样仍待修正口径后重验。
- 2026-07-11 已部署生产提交 `6e2cc92`：赛事历史抓取编排已归档并上线，多地区归属模型/迁移已上线但两个功能开关继续关闭。部署前 `.env` 与数据库备份均已完成并校验；归属短路热修复使 worker CPU 从持续高占用恢复至空闲约 `0.04%`。Django、容器、Celery、健康检查、首页、法国/英国频道、赛事日历及后台登录页回归通过。`support-multiregion-news-attribution-and-english-gates` 仍待五地区产品口径验收，不得开启开关或提交历史重算。
- 2026-07-11 `support-multiregion-news-attribution-and-english-gates` 已在用户接受任务 `9.6` 未完成警告后归档；六组 delta spec 已同步到正式规格，OpenSpec 全量 `21` 项通过，当前无 active change。归档不代表五地区产品归属验收通过，多地区生产开关仍须保持关闭。
- 2026-07-11 已生成赛事编排第一批五地区应到清单：日本德比、富卫保险女皇杯、BETFRED DERBY、PRIX DE DIANE LONGINES、KENTUCKY DERBY PRESENTED BY WOODFORD RESERVE 各 1 场，三模块齐全且 5 行预检均为 `ready`。run 审批仍为 `pending`、网络关闭，等待用户审核 `expected_targets_review.csv`，尚未开始真实抓取。
- 用户已批准上述清单；网络版 run 与原清单逐字段一致。prepare 前检查发现生产镜像遗漏 `runtime/tools` adapter 脚本，当前先修复 Docker 构建内容并部署，尚未发出网络请求。
- 第一批网络抓取 v2 已由覆盖审计安全阻断且未写库：香港、英国、法国完整，日本详情错配到中山金杯，美国缺 Equibase 赛果与可用 TOBA 历届冠军。JRA 已改为按赛事名称唯一匹配；v3 不改变已批准五场赛事，只新增美国 Equibase 赛果适配器，并复用已验证 TOBA 年度页缓存。必须先取得五地区三模块完整覆盖，才进入 dry-run。
- v3 已在 `60/60` 请求预算内完成日港英法抓取；HRN 通过同源留存页恢复出 24 匹参赛马。Equibase 执行暴露生产镜像缺少 `pdfplumber`，当前补齐依赖后从失败状态 resume；尚未 dry-run 或写库。
- `pdfplumber` 部署后 11 个 adapter 均完成，Equibase 产出 Kentucky Derby 18 条正式赛果。coverage 仍阻断法国空历史和美国空 HRN 赛果与非空 Equibase 赛果的误重复；审计已修为“非空候选优先、只有空候选仍阻断”，法国待用留存 Wikipedia 原件 resume。尚未 dry-run 或写库。
- 法国恢复后 coverage 已达 `5/5` 且 blocker 为 0，首轮 dry-run 通过。正式 apply 前又发现 combined candidate 仍携带 HRN 空赛果模块；当前增加聚合层空模块剔除并重新生成证据，避免 apply scope 与实际候选不一致。尚未正式写库。
- 空模块剔除后的 coverage/dry-run 已通过，但字段级 review 发现 JRA 当届历史冠军会丢练马师和完赛时间。当前已增加关键字段完整性阻断，并让 JRA history 从同批 detail 补齐当届冠军；真实缓存 smoke 通过。尚未正式写库。
- 最终候选 `2dd40a...8eac5` 已通过 coverage `5/5` 和 dry-run，JRA 字段退化已消除。剩余业务变化为英国补 2020 冠军及 2021 时间、法国练马师/冠军人名规范化及完赛时间补充；等待用户确认 mixed-source 与覆盖变化后进入 apply-check，尚未写库。
- 用户确认后第一批五地区赛事已正式写入：apply-check 8 个 scope 全绿，15 个候选全部 applied；写后合计 runners 75、results 64、history winners 47，服务健康。写前 105M 数据库备份已通过 gzip/SHA 校验，最终运行证据已同步到生产宿主机和本地审核目录。
- 2026-07-11 国际新闻生产验收未通过：最近 24 小时英文稿 `50` 篇中 `25` 篇仍有 `core_term_missing`；`America/Oaks` 等已降级，但一批被错误登记为马名的普通词仍作为 proper noun 阻断。地区新增/公开为日本 `114/21`、香港 `3/0`、英国 `12/2`、法国 `1/0`、美国 `34/13`；法国宽关键词新源 24 小时新增 `0`，香港/英国/美国后续扩源尚未实施。重处理 dry-run 即使 `limit=5` 也存在长时间满核问题，修复前不得在生产批量运行。
- 2026-07-12 已部署赛事公开页展示修复 `d071952`：出马表、赛果、历史冠军和赛事日历前列赛果中的马名/骑师名会精确关联 active 正式术语及别名，命中时显示中文译名、未命中保留原文；出马表按马号自然升序，缺号回退闸位，不再沿用赛果来源行序。目标测试 `23` 项、完整回归 `612` 项通过；线上排序已生效。首批术语覆盖不均，日本德比当前马名仅命中 `1/18`、骑师 `0/18`，后续应补正式术语库。
- 2026-07-12 已启动五地区赛事统一追溯至 1984 年的新目标，并创建 OpenSpec change `backfill-race-events-to-1984`。生产基线 `RaceEvent=995` 且全部集中在 2026 年；按当前目录机械外推为约 `42,785` 个年度对象，但真实分母必须由逐年目录和系列 timeline 生成。proposal、design、4 份 delta spec、82 项 tasks 和 22 轮问答决策已完成；两轮 `/plan-eng-review` 最终 APPROVED。当前下一门禁是编写完整测试用例，尚未实现、触网或写历史赛事。
- 用户已确认范围选择 A：覆盖五地区当前全部 graded/pattern 系列，不扩展到普通赛、让赛或未胜利赛。
- 用户已确认完整系列史口径：入选系列从 1984 年或实际创办年起收录，成为分级赛之前的年度届次也纳入，等级使用各年真实值。
- 用户已确认历史独有系列也纳入：凡 1984 年以来任一年进入 graded/pattern 体系，即使后来停办或降级退出，也进入系列目录。
- 用户已确认缺届口径：排期后取消创建 cancelled 年度赛事；当年未举办只记 `not_held` 证据，不创建虚假赛事。
- 用户已确认历史出马表可从可信完整赛果派生，必须保留派生来源且不得填造缺失字段。
- 用户已确认历届冠军采用系列动态汇总：年度正式赛果为主，缺完整赛果时才以冠军证据补位，不在每届重复整张历史表。
- 用户已确认稳定系列按权威沿革治理，冠名/场地/等级变化可连续，合并拆分必须人工确认并保留关系。
- 用户已确认多来源采用字段级权威规则，低级来源仅补空，同级或高级冲突阻断写入并人工审核。
- 用户已确认第一批跨年代验收约 45 场：五地区各 3 个系列，每系列抽 1980 年代、2000 年前后和近年 3 个年度。
- 用户已确认完整目标可先分批写入，暂时不可得或身份待审目标继续挂账且不计完成。
- 用户已确认永久不可得必须有官方/监管档案加独立可信来源的双来源证据，并经人工批准。
- 用户已确认当前年度未到期赛事使用 `not_due`，进入清单但不影响历史缺失率，到期后再纳入详情应到。
- 用户已确认历史赛事按质量门槛公开：完整且通过批准批次可自动 published，冲突/不足保持 draft，确认取消可公开说明。
- 用户已确认历史数据可受控增量修正，必须经新 diff/批准批次并保护人工锁，保留完整审计和回滚证据。
- 用户已确认中文术语缺口不阻止历史赛事结构化写入，未命中时保留原文并挂术语待办，不自动造词。
- 用户已确认全量按年代带从新到旧、五地区同步推进，禁止单地区长期领先。
- 用户已确认最终验收采用 accounted/data-complete 双指标，全部目标须有结论，永久缺档单列披露。
- 用户已确认历史赛事回填不自动创建马匹资料页，未识别人马只进入候选/术语缺口。
- 用户已确认不新增赛事系列页，前台继续使用年度赛事详情页。
- 用户已确认赛事日历增加年份筛选和赛事名称搜索，作为历史年度赛事入口。
- 用户已确认 artifact 为唯一批量审批/apply 凭证，同时增加后台汇总和冲突查看入口。
- 用户已确认达标 published 历史赛事允许被搜索引擎收录，使用分片 sitemap 排除草稿/冲突/空壳/not_held。
- OpenSpec 文档已通过两轮 Full 工程审核并获得 APPROVED；`test_cases.md` 已建立 160 个唯一用例。代码实现、clean review、生产部署和 2026 mapping 已完成，生产历史功能和网络门禁仍关闭。

### 2026-07-12 历史赛事工具上线与系列身份基线

- 历史赛事编排工具已随 `c3b66a6` 部署，模型、只读 inventory、五地区 catalog parser、批次 importer、年份搜索、分片 sitemap 与共享 Redis 缓存均已上线；历史功能和网络开关仍关闭。
- 2026 mapping 已完成审核和提交：清理 3 条确认重复赛事后，现有 `992` 场赛事全部绑定 `992` 个稳定系列，五地区 `review_required=0 / conflict=0 / unbound=0`，幂等复跑无新增写入。
- 当前尚未创建历史年度总账或 1984–2025 赛事。下一阶段只推进五地区 1984–当前官方逐年目录 source cache、系列 timeline 和只读总账审批，不能从 2026 现役系列机械外推历史分母。

### 2026-07-12 历史赛事回填实现进度

- 已完成 `/opsx:apply`、完整测试、反复 review、生产迁移和 2026 系列 mapping；稳定赛事系列、年度应到总账、official finish position、并列冠军迁移，以及离线 inventory artifact/审批/幂等 commit 基础能力均已上线。
- 历史功能和网络开关继续默认关闭；生产当前只有 2026 系列绑定，没有历史年度总账、1984–2025 赛事或历史公开数据。
- 后续仍需完成五地区逐年官方 source cache、年度总账审批、首批详情验收和分年代带回填；所有写入继续走既定 artifact、coverage、备份和写后核验门禁。
- 当前 OpenSpec 任务进度 `62/82`；代码与自动化测试任务已完成，包含五地区目录 cache parser、标准候选命令、共享预算/缓存锁、历史网络日志、批次 importer、公开搜索、动态冠军、sitemap 缓存与索引。完整 `stable` 回归最终 `743/743`，Django/迁移/OpenSpec/Compose/实际 Docker 镜像检查通过。
- 多轮代码 review 的全部技术 finding 已修复并逐轮复审，最终 review clean。剩余 `20` 项均为生产 mapping、官方逐年 source cache、总账审批、首批及四年代带抓取落库和最终审计；生产功能和网络开关继续关闭，尚未部署或写入本变更的历史数据。

### 2026-07-12 历史目录年鉴解析器就绪

- TJCIS International Cataloguing Standards 1998–2026 整本年鉴已确定为五地区共同年度 graded/group 目录骨架；原始 PDF、派生 CSV 和逐行 provenance 受共享预算/cache 门禁管理。
- 解析器已完成 1998 老版和 2016 中版真实样本迭代；1998 年鉴本身存在正文与页尾汇总矛盾，不能视为通过。专项回归与多轮 review 已通过，生产 source cache 已执行。
- 1984–1997 仍是任务 `8.3` 正式缺口。1998–2026 候选只形成部分只读总账，不批准完整 manifest、不创建历史 `RaceEvent`，直到旧年代来源和身份 timeline 补齐。

### 2026-07-12 历史目录生产抓取阶段结果

- 1998–2026 共 29 本 TJCIS 年鉴已经完整缓存并在生产校验 SHA；严格验收仅 `2016 / 2020 / 2021` 通过，25 个年份保留明确错误，1984–1997 尚未覆盖。
- clean 部分候选为 `3,252` 行，部分 inventory 为 `1,313` 个系列、`3,252` 个年度目标候选、`82` 个身份冲突；所有 artifact 均未批准或写库。
- 任务 `8.3` 继续未完成，详情抓取尚未开始。生产数据库仍无历史总账和 2026 年前赛事，公开开关继续关闭。

### 2026-07-12 1998–2026 年度目录修复进展

- TJCIS 全书解析修复后，严格直接通过年份从 `3/29` 提升为 `11/29`，2015 美国截断和 2022 英国同名障碍赛碰撞已解决。
- 全地区审计发现 `22` 个年份共 `31` 项正文/声明小计冲突；当前已生成逐项 JSON/CSV 和 29 年页文本诊断缓存，正在关联 JRA、BHA、France Galop、TOBA/AGSC 等地区来源。
- 尚未批准或写入 1998–2026 总账，尚未启动历史详情抓取或公开。生产历史功能/网络开关继续关闭。
## 2026-07-13 法国新鲜度与归属能力部署状态

- `fix-france-news-freshness-and-multiregion-attribution` 的代码和 `stable.0029` 已部署到生产 commit `badc10e0`，容器、迁移、HTTP 健康检查、首页、法国频道、详情页及法国三来源只读 probe 均通过。
- 新归属、相关地区查询、翻译自动重试和失败邮件仍全部关闭；这是安全部署，不是功能灰度完成。现有 159 条 Gold Set 已取得 Shadow 资格，但生产 dry-run、至少 24 小时 shadow、全量变化复核及后续灰度未完成前不得开启 enforce 或归档 change。
- 法国来源实时探测已能命中近期英文稿，未复现 2020/2022 历史稿；邮件通知因生产没有 SMTP 配置暂不可用，HTTPS 证书接入仍是独立待办。
### 2026-07-13 历史赛事第一批详情生产进展

- 此前 1998–2026 总账已完成审核和受控写入；第一批五地区 45 场验收样本现已完成日期发现和首轮详情落库：27 场详情正式导入，9 场法国赛事已有日期但等待完整详情，英国 2000 年 3 场和美国 2000/2012 年 6 场等待日期来源。
- 已导入 297 条出马表、287 条赛果和 54 条已应用候选；36 个已建年度赛事全部保持 draft，线上历史展示开关继续关闭。
- 生产详情写入前备份、候选/缓存 SHA 核验、dry-run、正式 apply、逐目标写后计数、容量检查和服务健康检查均已通过。下一步优先补齐本批 18 个显式缺口，再做五地区前台验收和扩大年代带抓取。

- 法国补源已向前推进：2012/2025 六场 ZEturf 详情离线解析完成，共 70 条 runners、41 条官方名次；旧页面兼容和同名误配已修复，826 项完整回归通过。该批仍停在本地候选阶段，必须先完成详情来源补充 artifact 和 target URL 绑定，不能直接写生产。法国 2000 三场仍待其他可信来源。
- 英法IrishRacing备用源与美国Equibase单场PDF能力已完成测试、反复review和生产部署；最终完整`stable`回归 `848` 项通过，OpenSpec strict/all、Django check、迁移漂移和diff检查均通过。
- 第一批五地区45个历史目标现已全部完成生产写入：`45/45 imported`，合计 `468 runners / 429 results`，全部保持draft且历史published为0。美国最后六场写入 `58 runners / 58 results`，候选SHA-256为 `94b62febe849b9a0562e5ab641d87671ae3468a202355b5336a7f4405e8abe75`；长期历史抓取/网络开关继续关闭。
- 2016–2025 首个标准批次已批准 250 场。日本和美国 100 场日期已写入，其中 98 场完整详情已 imported，新增 `1157 runners / 1080 results`；两场 NSA 障碍赛待详情，法国、香港、英国各 50 场仍处于日期来源缺口。公开开关继续关闭。

- 两场 NSA 官方 PDF 已补齐并正式写入，标准批次日美达到 `100/100 imported`、`1172 runners / 1094 results`；法国、香港、英国各 50 场仍是下一批日期/详情来源缺口，历史公开开关保持关闭。
- 生产曾被未合入 `stable.0027–0029` 对应应用代码的历史旧底座镜像覆盖，导致 netkeiba 新增违反 `attribution_rule_version` 非空约束。P0 后历史线程已停止所有生产动作；本地已合入最新 main 并通过 1093 项完整组合回归，等待生产协调解除构建冻结后再准备 AMD64 兼容镜像。
- 生产已短时回滚并验证 9 篇 netkeiba 新增/翻译恢复。AMD64 兼容镜像 `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4` 已独立构建并通过镜像内 check；尚未切换生产，后续由单一生产协调线程完成替换与验收。
- 上述兼容镜像现已由协调线程正式切换并完成生产验收，历史数据写入冻结解除；历史线程继续使用该镜像，不重建或重启生产。
- 2016–2025 标准批次的法国、香港、英国各 50 场已完成日期与详情证据，合计 150 个来源 URL 全局唯一；英国 47 条紧凑/裸数字距离证据已显式补单位。日期 artifact 已在备份后提交，150 场均为 ready/draft；详情导入暂停，优先把全部历史源码提交、推送并合入 main，避免下一次构建丢失能力。公开开关继续关闭。
- 历史赛事镜像曾以旧代码底座覆盖生产，造成已应用 `0029` 的数据库与旧应用不兼容并阻断 netkeiba 新稿。新闻写入先由临时组合镜像恢复，随后历史实现已完整提交到 Git，生产也已切换到 `main@304ebdb6` 的可复现镜像 `sha256:e7ab7af0...877d`；“仓库 HEAD 与运行镜像内容不同”的发布风险已解除。
- 法港英 150 场详情导入前只读复核发现原始赛事字段丢失地区距离单位，并有少量场地/surface 需要按已审核权威证据校正。新的整文件 SHA 锁定字段批次命令、RaceEvent 并发锁、整批回滚和旧详情候选失效门禁已完成，完整 `stable` 回归 `1136` 项通过；生产写入暂停，先把本轮源码合入 `main` 并重新交付可复现 AMD64 镜像。
- 上述门禁已提交到 `main@df2732c3` 并切换为可复现 AMD64 镜像 `sha256:27d5d51c...bf13`；切换前备份、排空 worker、无迁移检查、三容器一致性、五地区页面和首个自然窗口均通过。历史仍为 `145 imported + 150 ready`、published 0，本轮未执行字段或详情写入。

## 2026-07-14 多地区归属 V3 校准状态

- 现有 Gold Set 以用户完成的 `159` 条单审标签固定校准，不再补第二审核人；审核来源始终保留为 `provisional_single_review`。该身份本身不再禁止进入生产 Shadow；只有生产全量 dry-run、至少 24 小时 Shadow 和全量差异复核也通过后，才允许仅对新文章 enforce。
- 本地冻结快照对比：旧规则主地区 `81.76%`，V3 为 `98.11%`；V3 的日本/香港/英国/美国均 `100%`、法国 `90.91%`，相关 precision `100%`、recall `54.84%`，过度扩散 `0%`。低 recall 主要是文章未提供的历史参赛地区，不自动猜测。
- 术语候选索引把 159 篇纯推断降到约 `0.8` 秒；相关目标测试 `82` 项通过，最终完整 `stable` 回归 `1156 passed / 1 skipped`，Django/迁移/编译/OpenSpec strict/all 均通过。生产归属、相关地区查询仍关闭，本轮未部署或写生产数据。
- 下一门禁是 PostgreSQL 250 篇性能基准、生产 72 小时只读 dry-run 和运营复核；未满足前不得归档本 change。
- 法港英 150 场已完成权威字段校正、旧候选失效验证、重新导出、0-gap 打包、dry-run、第二次备份、正式导入和写后核验。新增 `1534 runners / 1294 results`，标准批次累计 250 场全部 imported；生产历史合计 295 场、3174 runners、2817 results，全部 draft、published 0，常驻历史写入/网络开关保持关闭。
- 2016–2025 第二标准批次已固定五地区各 50 场并完成日美离线来源发现：日本 50、美国 48 个候选对应 98 个唯一 URL；Brooklyn 与 Cougar II 的 2025 届被 TOBA 明确标为 `not run`，保留为产品审核项。来源匹配技术修复完整 `stable` 1141 项通过，尚未开始本批生产网络抓取或写入。
- 历史赛事完整源码和来源匹配修复已合入 `main@58786b91`，生产已切换到由该主线两次一致构建的 AMD64 镜像 `sha256:c6a3670f...4691`。迁移、64 个模型、五地区页面、健康检查和日志通过；生产历史仍为 295 场、3174 runners、2817 results，全部 draft、published 0，常驻历史写入/网络开关关闭。
- 新镜像切换后的 14:45 自然窗口已完成：17 个抓取、5 个发布、5 个 QQ 窗口全部成功，seen 472/new 3，新增 NULL 归属版本为 0。当前“主线源码、可复现镜像、生产数据库”重新一致。
- 第二标准批次五地区详情证据已收敛为 `246/250`：日本 50、美国 48、香港 50、英国 48、法国 50，246 个详情 URL 全局唯一且来源缓存身份可核验。两场美国 `not run` 和两场英国 `ABANDONED` 保留为显式缺口；香港跨年字段及英国紧凑英制距离解析修复已完成 `stable 1149` 项回归和 clean review，等待合入 main、交付可复现 AMD64 镜像后重新构建日期 artifact。尚未执行本批生产写入，历史公开开关继续关闭。
- 紧凑英制距离修复已合入 `main@d8b65fe7` 并切换生产镜像 `sha256:77eb1138...c3da0`；web/worker/beat 镜像一致，迁移无变化，Django、健康检查、页面和日志验收通过。新镜像只读重建 batch002 得到预期 `246 candidate / 4 gap`，manifest 尚未审批或写入；历史常驻写入、网络和公开开关保持关闭。
- 第三标准批次首次只读快照为 249 场、`2,635 runners / 2,346 results`，曾把 Hampton 的 Warwick 原场次 `ABANDONED` 误作年度 gap；该快照已隔离，不得审批。
- 用户提供 Windsor 正式结果后，batch003 已修正为 `250 candidate / 0 gap`、`2638 runners / 2349 results`，并完成 250/250 正式导入。NAR、Zone-Turf、ZEturf URL 身份和 surface 门禁修复继续有效。
- batch003 来源门禁已合入 `main@3939992c` 并由可复现 AMD64 镜像 `sha256:87c435cf...e78ec` 执行；正式写入后的最终状态以上方“第三标准批次 250 场导入完成”为准，公开状态继续关闭。
