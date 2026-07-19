# 五地区准实时赛果公开 Beta 发布与回滚

## 1. 发布原则

发布拆成代码、shadow 和 public 三层：

1. 代码层五地区同时部署，但所有新增地区默认关闭；
2. shadow 层按地区和 event 取得真实 racecard/result 证据；
3. public 层只晋级已证明的精确 event。

代码部署成功不等于五地区来源均已实时验收。香港下一场合资格赛事在 12 月时，允许
`code_ready/source_unproven`，禁止为了“凑齐五地区”跳过来源门禁。
香港和日本的代码资格范围均为 `G1/G2/G3/JPN1/JPN2/JPN3/JG1/JG2/JG3`；
Jpn/JG 只承认赛事总账已有标准化等级，不按香港地区或赛事名称推导。

## 2. Gate A：方案审核

入口：本目录五份 artifact 完成。

通过条件：

- reviewer 确认五地区范围、Free 能力边界、地区快照、分页、timezone、official manual
  route、调度隔离、关键 RED、灰度和回滚可执行；
- P0/P1 全部关闭。

未通过前不得写业务代码。

## 3. Gate B：RED/GREEN

按 `test_cases.md` 取得真实 RED，再由 implementation subagent 完成 GREEN/REFACTOR。

部署前必须通过：

- TRA registry/route；
- 五地区 racecard/timezone/identity；
- selector/region gate；
- cache/pagination；
- admission/transition/manual official receipt；
- event kill switch/前台状态；
- 邮件；
- PostgreSQL 关键竞争；
- Django check/migration drift/Compose contract。

全仓无关长回归可以在公开 Beta 后继续，不得替代上述关键门禁。

## 4. Gate C：独立 review 和授权

1. 未参与实现的 reviewer subagent 执行原生 review。
2. findings 由实现 subagent 修复，同 reviewer 复审。
3. 成功后冻结完整 scope/fingerprint/content hash。
4. 停止并向用户请求该精确冻结版本的发布授权。
5. 授权后若内容变化，旧 review/授权失效。

## 5. Gate D：代码部署，全部新增范围关闭

### 5.1 发布前

- 确认生产 HEAD/image 和 review parent；
- 历史 runner/receipt/import lock/one-off 均无 active 写入；
- Celery active/reserved 和 `race_live` queue 可排空；
- 内外 HTTP healthz 200；
- 创建 PostgreSQL 备份，校验 checksum 和 restore list；
- 保存旧 image tag、`.env` 备份和 rollback commit。
- 记录 `docker image inspect` 返回的 reviewed release image 完整不可变 image ID
  `sha256:<64hex>`，如推送 registry 再另记 repo digest；回滚演练和稳定窗口结束前保留
  release/old 两份 image，本机 one-shot 禁止只引用 mutable tag 或未核验的 repo tag。
- 用受审生成器从生产 `.env` 只提取必需 PostgreSQL 连接字段，生成 root `0600`
  `rollback.filtered.env`；记录 SHA-256 并写入 rollback manifest。生成器只输出 key
  校验结果和 SHA，绝不输出值；稳定窗口结束后删除该敏感 artifact。

### 5.2 初始设置

```text
RACE_LIVE_SCHEDULER_ENABLED=false
RACE_LIVE_ENABLED_REGIONS=
RACE_LIVE_RUNNER_MODE=the_racing_api_free
```

secret 只挂给 `race_live_worker`；racecard/publication artifact root 只按既有最小权限挂载。

### 5.3 验收

- web/worker/beat/live worker image revision 相同；
- migration 无意外新增；
- `stable.0047` 三项 additive schema 已应用，data migration 只标记既有 publication；
- registry SHA 与镜像/setting 一致；
- `manage.py check` 通过；
- event 924 仍显示暂定赛果且 read gate 正常；
- selector 返回 enabled false 或 claim 0；
- queue/active/reserved 为空；
- HTTP healthz、赛事页、五地区频道 200；
- 近期日志无 traceback/critical/integrity error。

## 6. Gate E：地区 racecard prepare

优先顺序由自然赛程和 TRA 返回决定，不按地区名称强行排序。每个 region：

1. 从未来 24 小时正式目标池选显式 event IDs；
2. 执行最多两次 Free racecard 请求；
3. 检查 match report、external ID、off time、timezone、participant 全集；
   如使用资格例外，另检查 `--eligibility-exception-file` 为 `0600` regular file，且
   approved commit、event IDs、有效期、scope digest 与本 run 精确一致；
4. blocker 非空则保持 off；
5. manifest 单独 dry-run；
6. apply + verify；
7. replay 必须零新增；
8. policy/event 保持 shadow。

`2026-07-19` 已知优先候选：

- 法国：event 733-735（若当日窗口尚有效）或 7 月 22 日 event 736；
- 日本：7 月 20 日 event 185，但当前明日 TRA racecard 未出现日本，因此先保持 blocked；
- 英国：7 月 25 日 event 925-928；
- 美国：event 420/421，但当前今日 racecard 未出现美国；
- 香港：event 2 为 12 月 13 日，当前不做虚假 live proof。

## 7. Gate F：单地区 shadow

每次只在 `.env` 加一个地区，仍保持 scheduler false：

1. 重建/重启 `race_live_worker` 和必要 selector service；
2. 手动调用 selector 或精确 claim/dispatch；
3. 验证只请求该地区 route；
4. 观察 cache miss/hit、页数、host budget、checkpoint；
5. 获得完整 shadow provisional revision；
6. 前台确认零泄漏；
7. 记录 last-empty/first-seen/provisional interval；
8. official manual route preflight 可执行；
9. SMTP real smoke 成功。

失败立即从 enabled regions 移除并重建相关 service，不影响 event 924。

## 8. Gate G：五地区 shadow 配置

只有分别通过 Gate F 的地区才加入集合。集合可以少于五个；代码能力仍为五地区。

开启 scheduler 前核对：

- tracking enabled 行的 event 全部在 enabled regions；
- 每行 source/terms/policy/allowlist/route/validity 完整；
- `next_poll_at` 位于合理窗口；
- active claim 为空；
- live queue 为空；
- 资源余量满足；
- 新闻/历史任务没有共享维护窗口冲突。

本 Gate 只准备 enabled region 集合，仍保持：

```text
RACE_LIVE_SCHEDULER_ENABLED=false
RACE_LIVE_MONITOR_ENABLED=false
```

先用精确手动 claim/dispatch 取得 shadow 证据，禁止在 publication transition 前开启
scheduler。

## 9. Gate H：精确 event 暂定/正式授权维护窗口

每个 event 单独：

1. coverage proof artifact 通过；
2. official route registry/URL/terms/validity preflight；
3. 明确关闭 scheduler/monitor，并重建 Beat/普通 worker/live worker 中实际消费相关配置的
   服务；
4. 确认 due selector 未运行、`race_live` queue、Celery active/reserved、active claim
   全空；
5. promotion/disable/restore bundle SHA 审核；
6. promotion dry-run/apply/verify/replay；
7. 如需 official public，另对 global/region/event coarse
   `official_public` 和目标 event official authorization 做
   dry-run/apply/verify；TRA source policy保持 provisional；
8. 首次无缓存详情和日历显示“暂定赛果”；
9. 执行 disable，确认仅该 event 隐藏，再按既定决定 restore 或保持 shadow；
10. 任一步失败保持 scheduler/monitor false，执行 event disable 后再恢复其他服务。

不得一次 promotion 一个地区全部赛事。

## 10. Gate I：恢复 scheduler 和 SLA monitor

全部目标 transition 完成且 claims 为空后：

```text
RACE_LIVE_SCHEDULER_ENABLED=true
RACE_LIVE_MONITOR_ENABLED=true
```

重建 Beat 和读取设置的 worker，观察至少 15 分钟：Beat 每分钟 selector/monitor、网络
请求合并、queue depth、alert incident、web/news worker 和历史 checkpoint 无回归。若
transition 因 scheduler true 被拒绝，这是正确门禁；下一次 transition 必须重新进入 Gate H。

## 11. Official 和 corrected

- `match`：manual receipt apply 后页面显示“正式赛果”。
- 首次官方 `conflict`：目标 event 先隐藏，官方 revision 保存，incident escalated；人工复核
  后另行 restore。
- 已有 official 的后续变化：corrected revision，页面显示“赛果已更正”。
- `unavailable`：provisional 继续显示，incident open，发送一次邮件，按 T+24h/T+72h/T+7d
  继续。
- match 前必须有 enabled official authorization；manual source 仍禁止自动网络。
- corrected 还必须把目标 authorization max_phase 从 official 显式提升为 corrected。

## 12. 监控窗口

上线后首 24 小时：

- 每 15 分钟核对 queue、active/reserved、host budget、HTTP 错误、cache hit、claim；
- 每场 off 后到 provisional 记录 3 分钟 poll 区间；
- T+15m 无 provisional 必须有邮件；
- T+2h official incident 状态必须准确；
- web/新闻 worker CPU/内存和任务时延无可归因回归。

完整 P50/P95 在至少 20 个有效样本后报告；样本不足明确写 `insufficient_sample`。

## 13. JG proof 边界

48 小时内香港和日本 JG 只能记录 `code_ready/source_unproven`。正式 deferred 必须：

1. 从首个可观测日连续 90 天覆盖全部合资格 JG；
2. 至少三场且覆盖窗口内实际举办的每个 JG 等级；样本不足延长至最多 180 天；
3. identity 100%、完整结果 >=99%、状态误标 0、延迟 SLO 合格；
4. 生成精确分母/赛事/证据 SHA/失败门槛/批准人/时间/review_due artifact；
5. 获得用户批准，且 review_due 不晚于批准后 180 天和下一场合资格赛事。

未满足时不能从 selector 或正式范围分母删除。

## 14. 回滚

### 12.1 单赛事异常

执行该 event 的 disable manifest：

- event policy 收紧为 shadow；
- read gate 立即隐藏；
- observation/revision/incident 保留；
- 其他 event 不变。

### 12.2 单地区来源异常

1. 从 `RACE_LIVE_ENABLED_REGIONS` 移除地区；
2. 重建 selector/live worker 所需服务；
3. 把该地区 policy 收紧为 shadow/off；
4. 失效该地区结果 cache；
5. 保留已发布 last-known-good 审计，read gate 按 policy 隐藏。

### 12.3 全链异常

1. `RACE_LIVE_SCHEDULER_ENABLED=false`；
2. `RACE_LIVE_MONITOR_ENABLED=false`；
3. global policy off；
4. 排空/revoke 尚未执行的 live queue，等待 active task 到安全 checkpoint；
5. 对 official/corrected event 执行精确 disable，并把 current pointer/legacy projection
   在单事务恢复到专用 `last_provisional_result_revision`，tracking 显式回到
   provisional rollback 状态并记录 OperationLog；此时 global/event 仍 off，专用
   validator 只验证受审 manifest 的计划 provisional policy 和非维护 gate；
6. 回滚旧 image/`.env`；
7. 旧 app services 运行后，用发布时记录的 reviewed release image 完整 image ID 执行只读
   validator；只加载 SHA/权限已核验的 `rollback.filtered.env`、只读 mount manifest，
   禁用 runner/scheduler/monitor，不存在 TRA/SMTP/通知/真实 Celery 凭据，数据库
   transaction read-only；
8. validator 退出 0 后，用相同 release image ID 和 manifest SHA 执行
   global/region/source restore，event 继续 off；
9. 再次用 release image ID 执行只读 validator；
10. 第二次退出 0 后，用 release image ID 最后恢复 event provisional policy，并从旧 web
    做首次无缓存真实 read gate；
11. 保留 additive `0047` 表/列；仅在结构/数据损坏时从已验证备份恢复；
12. 不反向删除 migration 或审计 revision。

filtered env 在切换 old image 前生成并核验：

```text
python3 scripts/build_race_live_rollback_env.py \
  --input /opt/umanewsbot/.env \
  --output <rollback-artifact-dir>/rollback.filtered.env \
  --sha256-output <rollback-artifact-dir>/rollback.filtered.env.sha256
test "$(stat -c '%a' <rollback-artifact-dir>/rollback.filtered.env)" = 600
sha256sum -c <rollback-artifact-dir>/rollback.filtered.env.sha256
```

生成器只允许从 input 复制 `POSTGRES_DB/USER/PASSWORD/HOST/PORT/CONNECT_TIMEOUT/SSLMODE`，
固定追加 non-production `SECRET_KEY`、`DEBUG=false`、`POSTGRES_CONN_MAX_AGE=0`、专用
application name、`CELERY_BROKER_URL=memory://`、`CELERY_RESULT_BACKEND=cache+memory://`、
dummy email backend、warning email off 和 runner/scheduler/monitor off。任何
`THE_RACING_API_*`、`RACE_LIVE_TRA_SECRET_ENV_FILE`、`EMAIL_HOST*`、通知收件人或其他
来源/通知凭据进入 output 都必须失败；禁止变量检查只回显 key。filtered env SHA 必须写入
rollback manifest，并由下述 pre-Django wrapper 再校验。

固定启动字段的精确值为：

```text
DB_ENGINE=postgres
DEBUG=false
SECRET_KEY=fixed-race-live-rollback-validation-key
POSTGRES_CONN_MAX_AGE=0
POSTGRES_APPLICATION_NAME=race-live-rollback-one-shot
CELERY_BROKER_URL=memory://
CELERY_RESULT_BACKEND=cache+memory://
EMAIL_BACKEND=django.core.mail.backends.dummy.EmailBackend
RACE_LIVE_RUNNER_MODE=disabled
RACE_LIVE_SCHEDULER_ENABLED=false
RACE_LIVE_MONITOR_ENABLED=false
```

manifest 是 root `0600`、非 symlink、最大 1 MiB 的严格 JSON；除 image/env SHA 外，至少
冻结 `event_id`、当前/暂定 revision ID、publication ID、allowlist version、tracking
lock version，以及四层 policy 的 `maintenance`/`restore` 两份完整
`mode/version/registry_digest/coverage_proof_digest/valid_until`。所有 restore version
必须精确等于对应 maintenance version + 1。

执行面模板（精确 image ID/路径在 release artifact 替换）：

```text
docker run --rm --network umanewsbot_default \
  --env-file <rollback-artifact-dir>/rollback.filtered.env \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  -v <rollback-artifact-dir>:/run/race-live/rollback:ro \
  --workdir /app/server \
  <reviewed-release-image-id-sha256:64hex> \
  /app/scripts/run_race_live_rollback_one_shot.py \
    --env-file /run/race-live/rollback/rollback.filtered.env \
    --manifest /run/race-live/rollback/manifest.json \
    --actual-image-id <reviewed-release-image-id-sha256:64hex> \
    --expected-filtered-env-sha256 <filtered-env-sha256> \
    --expected-manifest-sha256 <manifest-sha256> \
    --command validate
```

命令必须先用 `docker image inspect` 验证实际完整 image ID 等于 release artifact 的记录；
wrapper 必须在导入 Django 前验证 filtered env SHA、必需/禁止变量和固定安全值，失败时只
输出变量名/原因。exit code 非 0 立即停止。policy restore 使用同一 image/manifest/
filtered env/wrapper，命令序列精确为：

1. `--command restore-result`：页面仍处于四层 maintenance off，锁 event/control/
   tracking/current+provisional revision/items/observation/source/allowlist/publication/
   policies，重建 provisional legacy projection 并写 emergency OperationLog；
2. `--command validate`：PostgreSQL `SET LOCAL TRANSACTION READ ONLY`；
3. `--command restore-policies-coarse`：只把 global/region/source 从 maintenance
   snapshot CAS 到 restore snapshot；
4. 再次 `--command validate`：event 仍 off；
5. `--command restore-policy-event`：最后 CAS 恢复 event policy；
6. 从旧 web 发起首次无缓存 read gate 验收。

wrapper 内部只调用 `validate_race_live_rollback_target`、
`restore_race_live_provisional_result` 和
`restore_race_live_provisional_policies` 三个受审管理命令，并总是传递同一 manifest
路径和 `--expected-manifest-sha256`；禁止手工 SQL、mutable tag 或任意其他命令。

若专用 pointer 缺失或不合法，禁止猜测/搜索任意旧 revision，保持 global/event off 和页面
隐藏，告警并停在人工处置。临时 off 必须与 manifest 的 expected version/scope 精确一致；
其他 source/allowlist/digest/expiry 漂移仍 fail-closed。

### 12.4 回滚验收

- selector claim 0；
- live queue/active/reserved 0；
- event 924 或其他目标按预期隐藏/恢复；
- legacy results 与 current pointer 一致；
- 若执行 official/corrected 回滚，页面明确重新显示原 provisional，revision/incident
  审计仍完整；
- web/news/history 健康；
- 内外 HTTP healthz 200；
- 日志无持续异常。

## 15. Evidence-only closure

部署后只向以下获准路径追加事实：

- `docs/current_state.md`
- `docs/project_status.md`
- `docs/deploy_runbook.md`
- `docs/decisions.md`（仅不可避免且已经发生的必要发布决定）
- `docs/changes/five-region-race-live-public-beta/release_report.md`

证据 patch 复用本需求代码 reviewer 会话审核。不得通过 evidence 通道修改代码、测试、
配置、migration、spec、tasks 或治理。
