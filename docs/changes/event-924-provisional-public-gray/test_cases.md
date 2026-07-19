# event 924 暂定赛果单赛事公开灰度测试清单

## RED 规则

本变更改变生产 policy、publication、projection 和前台行为，不适用 RED 豁免。进入实现前
必须先新增测试并实际看到目标能力缺失导致失败；不得用语法错误、错误 fixture 或环境故障
冒充 RED。

### 首批真实 RED 证据（2026-07-19）

命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
  stable.test_realtime_race_results.RaceLivePublicationPolicyResolutionTests.test_missing_event_policy_fails_closed_even_when_shared_caps_are_public \
  stable.test_realtime_race_results.RaceLiveOfficialVerificationModelTests.test_public_route_contract_and_manual_due_fields_are_persisted \
  stable.test_realtime_race_results.RaceLivePublicStatusTests.test_published_provisional_result_is_clearly_labeled_unofficial \
  stable.test_realtime_race_results.RaceResultRevisionApplyTests.test_unique_admission_promotes_complete_tra_shadow_and_freezes_policy_snapshot \
  --noinput
```

结果：exit `1`，Django test DB 和 system check 正常，`4/4` 因目标能力缺失失败：

- missing event policy 当前错误返回 `allowed=true`；
- allowlist/incident route contract 与 manual due 字段尚不存在；
- provisional hero 当前显示“冠军 · 赛果已确认”；
- provisional publication 后 `RaceEvent.status` 仍为 `scheduled`。

这些测试分别可捕获：移除 event-scope fail-closed、遗漏 `0046` 字段、恢复旧 hero fallback、
以及删除 provisional finished 状态推进。

## 1. manifest 与 bundle prepare RED

- [x] 首批 RED 证明目标 service 能力缺失；实现后 service 可导入并由聚焦测试实际调用。
- [x] 合法 event 924 同形 fixture 可解析，manifest SHA 与规范化摘要稳定。
- [x] 未知字段、缺字段、重复 policy scope、非 aware time、非 40-hex commit、非 SHA-256、
  非法 transition、额外 event 均失败。
- [x] `--apply` 缺 `--confirm-apply`、apply/verify 同时使用、confirm 单独使用均失败。
- [x] expected manifest SHA 或 approved commit 不一致时在 DB 首写前失败。
- [x] prepare 从一个只读一致快照生成 promotion/disable/restore/report/SHA ledger，三段
  pre/post CAS 链可重复且 digest 稳定。
- [x] prepare 拒绝相对 root、root/ancestor symlink、非目录 ancestor、非法 run ID、已存在
  run、宽权限覆盖和非独占创建。
- [x] 成功 bundle 目录为 `0700`、全部文件为 `0600`，临时目录原子 rename，异常不留下
  半成品。
- [x] promotion 后的真实 DB 漂移不会被预生成 disable/restore 静默覆盖；每一步仍须独立
  dry-run。

## 2. exact pre-state / CAS RED

以下任一漂移均必须使 dry-run/apply 返回明确 reason 且业务零写入：

- [x] event ID/slug/year/region/off time 不匹配；
- [x] owner generation/owner manifest/current pointer 不匹配；
- [x] tracking state、claim generation、active claim、tracking enabled 不匹配；
- [x] observation ID/parser/phase/normalized SHA 不匹配；
- [x] result revision ID/no/phase/content SHA/published state 不匹配；
- [x] racecard revision ID 或 participant 集合摘要不匹配；
- [x] participant 有 pending/rejected；
- [x] manual results/runners lock；
- [x] source review/terms/automation/authority/registry/validity 不匹配；
- [x] policy 缺失、额外、mode/version/digest/validity 漂移；
- [x] allowlist disabled、source/max mode/version/coverage/route/version/contract
  digest/terms digest/validity 漂移；
- [x] tracking/allowlist universe 不再精确为 `[924]`；
- [x] 已有 legacy result/publication/incident；
- [x] scheduler 为 true。

## 3. PostgreSQL operator promotion 原子性 RED

- [x] 合法 manifest 一次 apply 后四条 policy mode/version 精确更新。
- [x] allowlist 在相同 transaction 内从 v1 到 v2，并持久写入受审 route contract/terms
  digest。
- [x] operator 路径按 `control -> tracking -> event -> source -> observation ->
  racecard/result revision -> revision items -> participants/source identities ->
  policy/allowlist/incident` 加锁，调用唯一 locked admission core 后完成 projection、incident 和
  tracking stop。
- [x] admission、projection、incident、allowlist CAS、tracking stop 或 operation log
  任一点注入失败时，policy/publication/legacy result/incident/allowlist/tracking 全部回滚。
- [x] policy 行并发改动时 CAS 失败，不能覆盖对方版本。
- [x] allowlist 行并发改动时 CAS 失败，不能覆盖 route contract/version。
- [x] 两个并发 apply 只有一个成功；另一个精确 replay 或 drift reject。
- [x] apply 后 active claim/expiry 仍为空，claim generation 保持原值；`last_attempt_at`、
  `last_success_at`、`last_observation_hash`、failures/stale 全部逐字段不变。
- [x] apply 后只把 `tracking_enabled=false`、`next_poll_at=null`，并写
  `provisional_published_at`。
- [x] apply 不改变 host budget，不产生网络请求。
- [x] 一个真实 poll transaction 与一个 operator transition 并发竞争，在 PostgreSQL
  无死锁；只允许一个合法结果，另一方得到明确 claim/drift reject。

## 4. admission/replay RED

- [x] 已存未发布 provisional revision 可在不重新创建 observation/revision 的情况下晋级。
- [x] poll `admit_race_live_publication()` 和 operator transition 均实际调用同一个
  `_admit_race_live_publication_locked()`；operator 不伪造 claim/checkpoint。
- [x] TRA 仍为 supplemental，不能通过 manifest 改成 official。
- [x] result/racecard participant 集合不相同则拒绝。
- [x] 同一 manifest 重放 10 次，revision/publication/legacy result/incident/operation log 的
  业务事实各只存在一份。
- [x] post-state 不完整时不能把混合状态误判为成功 replay。
- [x] 单赛事 resolver 与批量 read resolver 在 event policy 缺失时都 fail closed。
- [x] promotion 后 shared global/UK/TRA policy 为 public v2 时，用 initializer 初始化第二
  个 event 仍成功，并只创建 `event:<new-id> shadow v1`。
- [x] 第二个 event 即使 allowlist enabled，也因 event policy shadow 而不能公开。
- [x] 新 event 已存在非 shadow v1 event policy 时 initializer fail closed，不继承 shared
  public cap。

## 5. projection 与事件状态 RED

- [x] revision 1–7 顺序原样投影，不按马号、内部 participant ID 或名称重排。
- [x] result 非空字段优先，racecard fallback 不覆盖它。
- [x] 同 participant 的 racecard `barrier`、`jockey_name` 可补空值。
- [x] 不同 event/participant、pending racecard 或非 current racecard 不能提供 fallback。
- [x] trainer/weight/time/margin 未取得时保持空。
- [x] fallback 只允许 `barrier`、`jockey_name`；trainer/carried weight 即使 racecard
  fixture 非空也禁止带入。
- [x] 每个 fallback 字段的 `source_refs.field_provenance` 精确保存 racecard revision ID、
  revision item ID 和 source key；非 fallback 字段不得伪造 provenance。
- [x] legacy projection 不包含 raw response、rating、comment、form、odds analysis。
- [x] provisional publish 把 scheduled/running 推进为 finished。
- [x] provisional publish 不设置 `result_confirmed_at`。
- [x] cancelled/postponed event 晋级 fail closed。

## 6. 前台集成 RED

- [x] 成功 apply 后详情页包含“暂定赛果”“尚待官方来源复核”“补充来源”和发布时间。
- [x] 详情页显示 event 924 的 1–7 顺序和获准 fallback 字段。
- [x] 不显示“正式赛果”“更正赛果”或“官方来源”。
- [x] hero/概览不再显示 scheduled。
- [x] provisional 且 margin 为空时 hero 明确显示“冠军 · 暂定”，绝不显示“赛果已确认”。
- [x] 日历和详情页都经过 read gate，结果可见性一致。
- [x] event/global/region/source 任一 mode 收紧后，详情和日历立即隐藏 live result。
- [x] 隐藏后数据库 publication/revision/incident 数量不减少。
- [x] 重新打开只恢复当前获准 revision。

## 7. BHA manual official 闭环 RED

- [x] migration `0046` 正向/反向通过；shadow 旧行允许空 digest，但 public
  admission/read 对空或非法 digest fail closed。
- [x] route registry exact schema、canonical contract digest、terms digest、有效期、
  `manual_browser_only`、`automation_allowed=false`、责任角色和 15 分钟 SLA 全部校验。
- [x] promotion 创建唯一 open incident，route/version/contract digest/terms digest 与
  allowlist v2 一致。
- [x] deadline 精确等于 off time + 2h。
- [x] `manual_verification_due_at` 精确等于 promotion commit + 15 分钟。
- [x] event 924 在 deadline 后晋级时 verify 报告 overdue/open。
- [x] 重放不修改 opened_at，不新增 incident。
- [x] 未有 official marker evidence 时 revision 保持 provisional。
- [x] manual evidence prepare 不联网，拒绝 raw HTML/页面文本/评论/评级/赔率字段，receipt
  为 `0600`，comparison 不是可输入字段。
- [x] manual apply 要求 expected receipt SHA、approved commit、route contract、incident、
  revision 和 participant 全集完全匹配，任一漂移零写入。
- [x] manual receipt 在 schema/prepare/apply 三层都硬限 `event_id=924`；即使其他 event
  拥有完整合法 source/revision/participant/open incident 也必须拒绝。
- [x] match receipt 创建唯一 `bha_manual` official source、official observation、approved
  marker contract/evidence；服务计算顺序一致后 incident resolved，页面仍为 provisional。
- [x] conflict receipt 创建不可变 evidence，把 incident escalated，并在同一 transaction
  应用预生成 event disable；任何一步失败则 evidence/incident/policy 全回滚。
- [x] unavailable receipt 不创建 observation/marker，写脱敏 operation evidence，通过
  配置的 race-live 运营收件人真实发送邮件。主事务先原子提交 probe、receipt
  `OperationLog` 和 `QUEUED NotificationLog` 持久意图，提交成功后才进入独立 delivery
  transaction；主事务晚期写入或 commit 失败时必须零 SMTP、零残留 intent。
- [x] unavailable 告警按 incident 稳定去重，不按 receipt SHA 去重。receipt A 发送成功后，
  具有新 observed/evidence 的 receipt B 仍推进 `last_probe_at/next_probe_at` 并新增脱敏
  `OperationLog`，但不得再发邮件；receipt B 自身重放继续幂等。
- [x] delivery 将持久 intent 写为 `SENT/FAILED`，仅 `SENT` 设置 `alert_sent_at`；失败保留
  审计并可由同 receipt 重放创建新 intent 重试，已存在 `QUEUED` intent 时重放继续投递，
  已有 `SENT` 时不重复发送。
- [x] 同一 receipt 重放不新增 source/observation/marker/evidence/`OperationLog`，不改
  resolved/open 时间；失败通知的重试历史按 `FAILED -> SENT` 保留。

## 8. 管理命令/安全 RED

- [x] 默认命令通过与 apply 共用的 locked planner 验证 receipt、current revision、
  participant、incident、policy/allowlist CAS 和 conflict disable pre-state；数据库零写入、
  邮件零发送，输出 comparison、alert status 与 notification side-effect count。
- [x] dry-run 对 stale revision、closed/missing incident、participant conflict 和
  policy/allowlist CAS 漂移全部 fail closed。
- [x] 输出不含 attempt token、API username/password、raw payload。
- [x] manifest 必须是安全绝对路径，拒绝 symlink/目录/非普通文件/过大文件。
- [x] promotion/disable/restore/manual evidence 都生成稳定 JSON summary 和明确 reason。
- [x] disable 只收紧 manifest 指定 scope，不清理审计事实。
- [x] restore 只接受 disable 的精确 post-state；不能恢复不同 revision 或覆盖更高版本
  operator 变更。

## 9. 回归与验收命令

实现后至少执行：

```bash
python server/manage.py test \
  stable.test_race_live_publication_transition \
  stable.test_race_live_manual_official_evidence \
  stable.test_realtime_race_results

python server/manage.py check
python server/manage.py makemigrations --check --dry-run
```

PostgreSQL 专项必须覆盖真实行锁、嵌套 transaction/savepoint、runner/operator 竞争、并发
CAS、deadlock timeout 和 rollback；SQLite 结果不能替代该证据。

生产候选还需执行：

- 三份 Compose `config`；
- `race_live` worker route/limits 静态门禁；
- event 924 promotion manifest dry-run；
- apply 后独立 verify；
- event 924 disable 演练；
- healthz、详情页、日历、队列、容器资源、scheduler=false、tracking/allowlist universe
  核验。

## 10. 时间与产品验收

本次 event 924 不是新的 provider latency 样本。延迟报告固定使用已经取得的：

- scheduled off -> first seen：`12m42.301s`；
- source availability 区间：`(14:11:34Z, 14:14:42.301344Z]`。

公开灰度验收时间从 promotion transaction commit 到 public HTTP 首次可见计算：

- 本地/候选环境：p95 不超过 5 秒；
- 生产单次 event 924：页面在 apply 完成后的首次无缓存请求中可见；
- kill switch：disable commit 后首次无缓存请求立即隐藏。

## 11. 本地执行证据（2026-07-19）

真实 RED 除本文件开头四项外，还包括：

- transition registry/安全 root 初版对 63 位 terms digest 和 macOS `/var` alias 处理错误；
- verify 未报告 `official_incident_status/overdue`；
- manual receipt replay 在 post-state 漂移后错误返回成功；
- event identity、manual lock、participant review 和 racecard fallback 内容未进入 exact
  pre-state；
- publication timeline 漂移未阻止 replay；
- BHA receipt 曾允许同 host 的非 Results URL；
- manual receipt 的未来时间或赛前时间曾可进入 apply；
- 完整合法的 event 925 open incident 曾可通过 manual apply；
- unavailable 曾只写 `QUEUED` 日志并提前设置 `alert_sent_at`，没有真实发送、失败终态或
  同 receipt 重试闭环；
- management command 默认 dry-run 曾只回显 receipt 静态字段，放过 stale revision、
  closed/missing incident、participant conflict 和 policy/allowlist CAS 漂移。
- unavailable 告警曾按 receipt SHA 去重：receipt A 已发送后，新 receipt B 会因
  `unavailable alert post-state 不一致` 失败，不能推进新的 probe/operation evidence；
- SMTP 曾位于主事务内：发送回调观察不到已持久的 `OperationLog`，晚期
  `OperationLog` 写入失败或主 transaction commit 失败时仍已产生邮件副作用。

上述缺口均先由聚焦测试失败捕获，再完成实现。最终命令、数量和退出状态以本文件后续冻结前
证据追加为准；生产 promotion、BHA 浏览器 preflight、HTTP 可见时延和 kill-switch 时延仍
只能在最新 review/授权后的维护窗口验收，不能用本地测试冒充。

冻结前本地结果：

- 本轮两项直接 P1 的 4 个 SQLite RED：exit `1`，分别暴露跨 receipt incident 去重失败、
  SMTP 前 operation 尚未持久、晚期主写入失败仍发信、主 commit 失败仍发信；GREEN
  `4/4`；
- transition/manual 专项：`41` 项，`39/39` 通过，PostgreSQL-only `2` 项按设计跳过；
- 合并聚焦 SQLite（transition、manual、现有准实时、initializer v1/v2、racecard）：
  `226` 项，`224/224` 通过，PostgreSQL-only `2` 项按设计跳过；
- 临时 PostgreSQL 16 新增 durable intent/incident 并发专项 `2/2`：两个不同 unavailable
  receipt 并发只生成一个 intent/一次 SMTP，独立连接在 SMTP 前可见已提交 intent 与
  operation；晚期主写入失败完整回滚且零 SMTP；
- 临时 PostgreSQL 16 既有回归（双 operator 串行 replay、policy/allowlist 并发 CAS、
  runner/operator 无死锁、manual conflict 同事务和既有初始化锁）：`22/22`；
- `stable.0046 -> 0045 -> 0046` 往返成功，最终 `0046` 为 applied；
- Django system check、`makemigrations --check --dry-run`、相关模块 compileall、
  三份 Compose `config --no-env-resolution` 和 registry canonical contract digest 全部
  通过；
- 所有服务测试均使用本地 fixture/临时数据库，`network_request_count=0`，未访问 BHA、
  未重新请求 TRA、未连接或写入生产。
