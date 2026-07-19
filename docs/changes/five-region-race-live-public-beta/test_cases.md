# 五地区准实时赛果公开 Beta 测试清单

## 1. RED 规则

实现前新增本文件列出的关键行为测试，并实际看到因目标能力不存在而失败：

- 五地区 racecard 路由/时区；
- selector 地区和 policy 门禁；
- results 地区快照/分页；
- 通用 publication transition；
- 通用 official receipt；
- 前台状态和 event 级 kill switch；
- 邮件告警去重。

环境、依赖或既有失败不能充当 RED。RED 证据记录命令、失败测试名、失败原因和时间。

### 1.1 已取得的关键 RED 证据

- 时间：`2026-07-19T14:58:28+08:00`。
- 命令：仓库 `.venv` 执行
  `python manage.py test stable.test_race_live_target_eligibility
  stable.test_race_live_multiregion_selector stable.test_race_live_multiregion_pipeline
  stable.test_race_live_official_publication stable.test_race_live_sla_monitor
  stable.test_race_live_rollback_contract --verbosity 1`。
- 结果：exit `1`；共 `46` 项，`41` 项因本变更目标能力尚未实现而 RED，`5` 项既有复用
  能力通过，无 test error。
- RED 分组：eligibility `5/5`；selector `5 RED + 2 GREEN`；multiregion pipeline
  `7 RED + 2 GREEN`；official publication `10 RED + 1 GREEN`；SLA monitor `8/8`；
  rollback control `6/6`。
- 已有 GREEN 只证明有界轮询窗口、明确结果 `NR` 和 host `1050ms` 限速等复用点；不代表
  五地区能力已经实现。
- 首次误用系统 Python 导致 Django 缺失的运行已排除，不计入 RED。正式证据未访问真实
  网络、生产数据库、Redis、队列或服务器。

### 1.2 实现阻塞修复的追加 RED

- rollback env/wrapper：三个精确测试 exit `1`，实际暴露缺少 `DB_ENGINE=postgres`、
  错误 DB engine/SECRET_KEY 未拒绝和 `main()` 不支持受控注入；修复后同命令 GREEN。
- rollback control：新增 maintenance/planned policy、allowlist/publication/tracking/
  manifest CAS 测试先因 service 参数/分阶段 restore 不存在而 error；late-scope drift
  测试随后真实捕获“前三层已写、event 漂移却提交”的原子性缺陷，改为全量预检后统一写。
- official staged publication：精确测试先因
  `publish_authorized_staged_official_revision` 不存在而 ImportError；GREEN 后改用真实
  `authorize_race_live_official_publication --apply` 证明后授权可发布既有 staged revision。
- broad apply preflight：monitor-on 和 active-claim 四个测试均先以“未抛异常”失败，补齐
  scheduler/monitor/全库 tracking 锁后 GREEN。
- route evidence：六个 entry 先因缺独立 permission/terms evidence 全部失败；单 route
  registry digest 测试随后捕获错误使用整文件 digest，改为 route-specific digest 后 GREEN。

### 1.3 首次代码审核 findings 的追加 RED

- official bulk read：40 场 official/corrected 日历实际 `770` 次查询，超过固定上限
  `20`；预加载 authorization、official source、marker/contract、TRA source、policy 和
  allowlist 后，同一测试及上轮 audit 漂移测试 GREEN。
- 原始分页完整性：首/中/末页各少一条时三个测试均误返回 `processed=true`；地区过滤前
  精确校验原始条数后，三项均以 `results_pagination_incomplete` fail-closed。
- pagination 告警：`total=501` 与页间 total 漂移均被改写为普通
  `the_racing_api_payload_invalid`；保留结构化 reason/checkpoint 后，两条链路均生成
  `pagination_overflow` incident，普通 malformed payload 继续不生成该 incident。
- 时间预算：十页每页 17 秒时旧实现仍发布成功；加入 `165s` deadline 与 remaining-time
  timeout 后超预算测试 GREEN，十页每页 15 秒边界仍成功。settings/env/worker script 的
  soft/hard 默认值统一为 `180/210s`；追加 RED 证明旧 claim lease `120s` 无法覆盖完整
  链路，现统一为 `240s`。

## 2. TRA registry v2

- [ ] 五地区 code 精确为 `gb/fr/hk/jpn/usa`。
- [ ] racecard 只允许 today/tomorrow、limit 500、skip 0。
- [ ] results 只允许 limit 50 和 skip 0..450 的 50 倍数。
- [ ] 未知 region、query 重排/重复、skip 25/500、host/port/scheme/fragment 漂移拒绝。
- [ ] registry SHA、evidence staleness、valid_until 和 automation permission 保持 fail-closed。
- [ ] proof 默认仍最多三次请求，不因 v2 route contract 扩大。
- [ ] Docker 镜像内 registry SHA 与三份 Compose expected SHA 一致。

## 3. racecard prepare

### 3.0 资格矩阵

- [ ] UK/FR/US 2025+ G1/G2/G3 允许；2024/更早拒绝。
- [ ] HK/JP 均允许 G1/G2/G3/JPN1/JPN2/JPN3/JG1/JG2/JG3。
- [ ] HK/JP 的 Jpn/JG 只读取总账既有标准化等级；不得按地区、赛事名或来源文本自造。
- [ ] 五地区的 Listed/Open/普通赛拒绝。
- [ ] prepare 与 initializer 对同 event 返回相同 eligibility reason/matrix version。
- [ ] 合法 exception artifact 只放行精确 event；SHA/commit/expiry/scope/event 漂移拒绝。
- [ ] exception 文件必须绝对路径、regular、`0600` 且无 symlink ancestor；过宽 event
  scope 在网络前拒绝，完整 artifact 副本/digest 由 initializer 重验。
- [ ] manifest/verifier 缺 eligibility 或 exception digest 拒绝。

### 3.1 路由

- [ ] 每个地区 today/tomorrow URL 精确生成。
- [ ] 同一 run 混合地区拒绝。
- [ ] event region 与 `--region` 不同拒绝且网络请求 0。
- [ ] 一个地区多个 event 仍只有两次请求。

### 3.2 时区

- [ ] UK `Europe/London` 夏令时转换正确。
- [ ] France `Europe/Paris` 夏令时转换正确。
- [ ] HK `Asia/Hong_Kong` 正确。
- [ ] Japan `Asia/Tokyo` 正确。
- [ ] US `America/New_York` 和 `America/Los_Angeles` 同 UTC instant 得到不同当地时间。
- [ ] 无效 IANA timezone、source naive time、local date 跨日冲突拒绝。
- [ ] initializer v2 不再要求 London，但必须与 event 既有 timezone 精确相同。

### 3.3 身份

- [ ] 五地区各一份最小 fixture 唯一匹配。
- [ ] 日文原名/已审核英文 alias 可匹配；中文展示名和自动翻译不参与。
- [ ] Jpn/JG 不被 Group token 规则改写。
- [ ] 零命中、多命中、外部 race ID 重用、runner ID 重复、participant 缺字段阻断。
- [ ] 人工锁、occupied event、状态非 scheduled、日期超 today/tomorrow 阻断。

### 3.4 artifact/initializer

- [ ] requests/report/manifest SHA 绑定、权限和 symlink 防护。
- [ ] fresh dry-run 零业务写入。
- [ ] apply 全部创建且默认 shadow。
- [ ] verify 精确通过；同 manifest replay 零新增。
- [ ] event/CAS/companion/registry 任一漂移整批失败回滚。
- [ ] schema v1 既有 fixture 兼容。

### 3.5 赛前 refresh

- [ ] pre-off due task 获取/复用地区 racecard 快照，不进入 results endpoint。
- [ ] 相同 racecard hash replay，只推进 checkpoint。
- [ ] jockey/draw/number/weight 变化生成新 immutable racecard revision。
- [ ] 新 runner 在 off 前加入并建立唯一 source identity。
- [ ] runner 从后续列表缺失只写 source gap，不能自动标 withdrawn。
- [ ] results 明确 `NR` 后可投影 non-runner；结果缺 runner 且无 NR 时 provisional 门禁失败。
- [ ] 同 external race ID 同当地日期的 off time 漂移在 12h 内 CAS 更新。
- [ ] 跨日/>12h/人工锁/进入 provisional 后 off time 变化阻断。
- [ ] 旧快照迟到、owner/claim/current revision 漂移只留 observation，不更新 current。
- [ ] 两个 event 同地区 150 秒内 racecard refresh 只发一组网络请求。

## 4. selector 和 worker 隔离

- [ ] `RACE_LIVE_ENABLED_REGIONS=[]` 时 scheduler true 仍 claim 0。
- [ ] 只启用 France 时 UK/JP/US/HK due row 均不 claim。
- [ ] tracking disabled、not due、owner 非 live、active claim 不过期均不 claim。
- [ ] source/terms/automation/validity/allowlist/policy 任一不合格不发网络 task。
- [ ] selector claim 后 policy 漂移，worker 网络前拒绝并释放/失败 checkpoint。
- [ ] 普通 worker queue 不含 `race_live`；live worker 只含 `race_live`。
- [ ] Beat task 不调用 transport。
- [ ] batch size 上限和 `skip_locked` 并发正确。

## 5. 地区 results 快照与分页

- [ ] 同地区两个 due event 在 150 秒内只发一组网络请求。
- [ ] 不同地区分别使用独立 cache key。
- [ ] registry digest/provider date/route version 改变后 cache miss。
- [ ] cache value 不含用户名、密码、评论、评级、tips 或未白名单字段。
- [ ] total 0 形成合法空快照并给所有 event `result_not_found` checkpoint。
- [ ] total 51 请求 skip 0/50；total 500 请求 10 页。
- [ ] 每个原始响应页在地区过滤前必须精确包含
  `min(limit, total - skip)` 条；首/中/末页任一截断均结构化标记 incomplete，不缓存、
  不覆盖 last-known-good。
- [ ] total 501、页间 total 漂移、重复 race ID、缺页、页大小异常全部 fail-closed。
- [ ] overflow/incomplete/metadata drift 从 runner reason 到 tracking checkpoint 保留
  结构化 pagination category，monitor 生成 `pagination_overflow` incident；普通 JSON/
  schema payload 错误不得误分类为 pagination 告警。
- [ ] 第 N 页 429/403/5xx 时不使用前 N-1 页发布。
- [ ] cache get 异常可按 host budget 重抓；cache set 异常不丢弃已验证当前响应。
- [ ] host reservation/outcome CAS、1.05 秒最小间隔和 circuit 三连失败正确。
- [ ] 10 页各耗时 15 秒时可在 165 秒 results fetch deadline 内完成；每次 transport
  timeout 取 `min(15, remaining)`，超预算立即以结构化 deadline checkpoint fail-closed，
  不缓存、不更新 last-known-good。Celery task/worker soft/hard 默认分别为 180/210 秒，
  claim lease 默认 240 秒，且文档、settings、env 和启动脚本一致。
- [ ] 同 external ID 零/一/多命中分别 checkpoint / apply / blocker。

## 6. provisional 写入

- [ ] TRA source authority 在模型/DB/apply 三层仍固定 supplemental。
- [ ] participant 全集、身份、人工锁和 payload 完整性由 admission 内部重算。
- [ ] 完整 TRA result 生成唯一 provisional observation/revision。
- [ ] shadow event 只保存 revision，不投影页面。
- [ ] public event 原子投影 legacy results、current pointer、publication 和 tracking。
- [ ] 同 observation 重放 10 次无重复业务变化。
- [ ] 迟到 claim、owner generation、allowlist/policy version 漂移拒绝。
- [ ] apply 中任一故障 observation 之外的 canonical/current/legacy/public 状态原子回滚。

## 7. 通用 publication transition

- [ ] UK/FR/HK/JP/US 各一个 event 可构建 promotion bundle。
- [ ] 不再限制 event 924，也不要求全库 universe 只有目标 event。
- [ ] event route 与地区 registry 不符拒绝。
- [ ] promotion 只改变目标 event；另一个 event 全部 snapshot 不变。
- [ ] disable/restore 只影响目标 event read gate。
- [ ] global/region/source scope 不被 event transition 偷偷提升。
- [ ] manifest SHA、approved commit、expected snapshot、participant digest、
  unrelated scope digest 任一漂移拒绝。
- [ ] scheduler true 或 active claim 时 transition 拒绝。
- [ ] event 924 既有 transition fixture 保持兼容。

## 8. 通用 official receipt

- [ ] 六个 route registry entry schema/digest/host/path/validity 通过。
- [ ] 每个 route 的 permission evidence、terms evidence、contract digest 三者独立；
  terms digest 不得复用 contract digest，generic registry digest 只绑定本 route，
  修改其他 route 不使当前 route authorization 漂移。
- [ ] tracked evidence 明确绑定 `user_source_use_authorization_2026-07-19`、
  manual access，且 `automation_allowed=false`；BHA 既有冻结 registry 仍走兼容 reader。
- [ ] 调用方 route 与 event allowlist 不一致拒绝。
- [ ] source URL 不在精确官方 host/path 约束内拒绝。
- [ ] `available` 需要 marker 和 participant 全集；`unavailable` 禁止伪造 participants。
- [ ] match 生成 official source/observation/marker evidence/revision 并 resolved incident。
- [ ] provisional 不同的首次 official 仍是 official，不误标 corrected。
- [ ] 已有 official 后变化才 corrected。
- [ ] conflict 只收紧目标 event read gate，其他 event 可见。
- [ ] unavailable 保持 provisional，incident open，next probe 推进。
- [ ] 同 receipt replay 零新增；receipt/contract/terms/CAS 漂移拒绝。
- [ ] event 924 既有 BHA receipt replay 继续可验证。

## 8.1 official/corrected 独立公开授权

- [ ] migration 不创建授权，event 924 provisional 可见性不变。
- [ ] manual official source 保持 `terms_status=manual/automation_allowed=false`，网络
  permission resolver 仍拒绝。
- [ ] coarse global/region/event 未达 official_public 时 official admission/read 拒绝。
- [ ] TRA source policy 即使只有 provisional_public，也不阻止独立 official gate。
- [ ] authorization/source/route/version/registry/contract/terms/coverage/expiry 任一漂移
  拒绝或立即隐藏。
- [ ] match receipt 后 official revision publication audit 使用
  `official_route + authorization version`，详情可见。
- [ ] match receipt 先到而 authorization 未到时只产生 staged revision、provisional
  继续可见；随后真实 authorization 命令发布同一 revision，不新增重复 revision。
- [ ] publication audit 保存真实 authorization version、当前 allowlist version、四层
  policy versions、route registry digest 和 coverage digest；任一漂移 read gate 隐藏。
- [ ] authorization max_phase=official 时 corrected 拒绝；显式提升 corrected 后可见。
- [ ] authorization 精确 replay 不增加 version；只把 max_phase 从 official 安全提升为
  corrected 时，详情与批量/赛历 read gate 均继续显示既有 official audit/version，后续
  corrected 使用新 version；两种读取对四层 policy、allowlist 和 route digest 漂移保持
  相同的 fail-closed 审计语义。
- [ ] 单页混合 40 场 official/corrected 时，批量 read gate 必须预加载 authorization、
  official source、marker/contract、TRA coarse policy 与 allowlist；查询数保持固定上限，
  不得逐赛事回调单赛事 resolver。
- [ ] current official 隐藏时 provisional observation/revision/publication 仍完整保留。
- [ ] provisional publish 更新专用 pointer；official/corrected publish 不覆盖。
- [ ] migration 只回填同 event、result/provisional、published/audit 一致的最新 revision。
- [ ] `provisional -> official -> corrected -> disable/rollback` 在单事务恢复 current
  pointer、legacy projection、tracking 后页面显示原 provisional。
- [ ] rollback 过程任一点故障时 pointer/legacy/tracking/OperationLog 全部回滚。
- [ ] 与 rollout 完全相同的 `scheduler/monitor off + global/event off` 状态下，页面仍
  隐藏，但合法 provisional 和计划 policy 可通过 rollback-target validator 并在单事务
  恢复 pointer/legacy/tracking。
- [ ] validator 不把 manifest 精确声明的临时 global/event off 当成失败，也不允许未在
  manifest 中的任意 off/version 漂移。
- [ ] policy restore 先验证全部四层 maintenance/restore snapshot，再统一写；最后一个
  scope 漂移时前三层也保持零写入。
- [ ] rollback policy restore 的 source 目标必须精确为 `provisional_public`；即使
  global/region/event 可恢复到 `official_public`，source=`official_public` 仍须在
  validator/command/service 写入前拒绝。
- [ ] pointer 缺失、跨 event、非 provisional、未 published、audit 漂移，或 TRA
  source/allowlist/registry/coverage/expiry/计划 policy 任一真实漂移时零写入并保持隐藏。
- [ ] 旧 image 启动后先恢复 global/region/source、event 仍 off，validator 通过；最后恢复
  event policy 后真实 public read 可见 provisional。
- [ ] 部署契约模拟 web/worker 已切旧 image，但 validator/restore one-shot 使用精确冻结
  release image digest；mutable tag 或 digest 不匹配拒绝。
- [ ] filtered env 生成器只复制必需 PostgreSQL 字段，拒绝缺项、重复项、空值、变量展开，
  固定 `DB_ENGINE=postgres` 和受审 SECRET_KEY，写 `0600` 文件和 SHA；manifest 绑定
  SHA，漂移、symlink、非普通文件、超限或宽权限拒绝。
- [ ] one-shot wrapper 在导入 Django 前验证环境：容器中不存在 `THE_RACING_API_*`、
  `RACE_LIVE_TRA_SECRET_ENV_FILE`、SMTP host/user/password、通知收件人或真实 Celery
  broker/result backend；broker 为 `memory://`、result backend 为 `cache+memory://`、
  email backend 为 dummy、runner/scheduler/monitor disabled。
- [ ] one-shot validator 使用 filtered env、只读 manifest/文件系统和 PostgreSQL
  read-only transaction；restore 只产生 manifest 允许的 policy 写入，其他模型零变化。
- [ ] validator 非 0 时 policy restore 零写入；stdout 不含 secret、participant 原始
  payload 或任意第三方版权字段。
- [ ] global/region/source restore 与 event-final restore 均校验同一 manifest SHA；event
  在最终一步前始终 off。
- [ ] official authorization 和 broad scope 的 apply 都在事务内锁定 control/tracking，
  重检 scheduler=false、monitor=false、active claims=0；任一不满足时零写入。

## 9. 邮件

- [ ] subject/body 使用真实地区、event 名、route、incident，不含 event 924 硬编码。
- [ ] dedupe key 含 region/event/incident/route version。
- [ ] 收件人为空、SMTP 失败写 FAILED，不把 incident 错标 sent。
- [ ] SMTP 成功写 SENT 和 alert_sent_at；重复 apply 不二次发送。
- [ ] 事务失败不留下孤立 SENT/incident 状态。

## 9.1 自动 SLA monitor

- [ ] T+15 无 provisional 自动创建唯一 alert incident/queued notification。
- [ ] T+2h official incident open 自动告警，无需人工 unavailable receipt。
- [ ] consecutive failures=3、pagination overflow、host circuit、queue age>3m 分别告警。
- [ ] 未启用地区、shadow 但不在 monitor scope、已 resolved 不告警。
- [ ] 两个并发 monitor 只创建一个 dedupe key。
- [ ] delivery 短事务 claim，测试证明 SMTP 调用期间不持 alert row lock。
- [ ] SMTP 成功 SENT；失败按 1m/5m/15m 重试，三次后保留 FAILED。
- [ ] delivery lease 过期可接管；旧 token 不能覆盖新结果。
- [ ] 一个 event 告警/resolve 不影响另一个 event。

## 10. 前台

- [ ] provisional 显示“暂定赛果”“尚待官方来源复核”“补充来源”和更新时间。
- [ ] official 显示“正式赛果”和官方来源。
- [ ] corrected 显示“赛果已更正”。
- [ ] conflict 显示“赛果待复核”，不泄漏未获准 revision。
- [ ] stale 显示过期提示并保留 last-known-good。
- [ ] event off 后详情、日历、结果摘要均隐藏 live revision。
- [ ] 一个 event disable 不隐藏另一个公开 event。
- [ ] 页面不渲染赔率、ratings、comments、tips 或 raw payload。

## 11. PostgreSQL/竞争

- [ ] 两个 selector 竞争同 due rows，无重复有效 claim。
- [ ] 两个同地区 task 串行复用快照，host budget 无超发。
- [ ] owner transfer 与网络迟到 response 竞争，迟到 response 不投影。
- [ ] policy/allowlist CAS 与 admission 竞争，旧检查不能公开。
- [ ] transition/official apply 并发，单 event 串行且无死锁。
- [ ] rollback 注入后 pointer、legacy results、incident、OperationLog 一致。
- [ ] official authorization 与 receipt/policy 并发 CAS，不出现隐藏 current pointer。
- [ ] monitor stage/delivery lease 并发无重复邮件。
- [ ] corrected publication 与 emergency provisional restore 并发串行，无混合 legacy
  projection 或错误 pointer。
- [ ] PostgreSQL read-only validator 尝试写入时测试失败，证明执行面不是伪只读。

## 12. 关键测试命令

具体模块由 RED 切片最终确定，至少包括：

```text
python manage.py test \
  stable.test_race_live_source_proof \
  stable.test_race_live_racecard_sync \
  stable.test_race_live_initialization_v2 \
  stable.test_realtime_race_results \
  stable.test_race_live_publication_transition \
  stable.test_race_live_manual_official_evidence
```

新增模块至少包括：

```text
stable.test_race_live_target_eligibility
stable.test_race_live_official_publication
stable.test_race_live_sla_monitor
```

另运行：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python -m compileall server/stable server/app
```

PostgreSQL 专项：

```text
python manage.py test \
  stable.test_race_live_initialization_postgres \
  stable.test_race_live_publication_transition_postgres
```

首次 review findings 收口后的扩大验证为：

- SQLite 准实时专项 `353 tests OK (14 skipped)`；
- 临时本地 PostgreSQL 16 专项 `25 tests OK`，测试数据库与容器均已删除；
- 未访问生产数据库、Redis、SMTP 或第三方网络。

## 13. 延迟验收

每个公开候选保存：

- off time；
- last empty poll；
- first TRA seen；
- provisional published；
- official observed/applied；
- cache hit/miss 和页数。

有 source timestamp 时直接计算；没有时使用 `[last_empty, first_seen]` 区间上界。公开 Beta
最低要求是下一场真实候选 T+15m 告警可用；P50/P95 需累计样本后报告，不能用 event 924
或合成 fixture 伪造。

## 14. 上线后可滞后的非阻塞回归

只有以下项目可以在公开 Beta 后继续：

- 全仓与本变更无直接关系的长时间回归；
- 五地区自然赛程的 P50/P95 样本积累；
- 香港下一场 12 月自然赛事 shadow；
- JG1/JG2/JG3 的 90 天、必要时延长至 180 天 proof；在用户批准精确 artifact 前只能
  `code_ready/source_unproven`，不能形成 deferred；
- 官方网页自动 adapter 的后续许可/设计。

权限、身份、分页、幂等、状态标识、event kill switch、告警和关键 PostgreSQL 竞争测试不得
滞后。
