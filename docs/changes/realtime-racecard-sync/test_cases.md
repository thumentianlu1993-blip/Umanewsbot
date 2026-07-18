# 准实时赛前 racecard/off time 同步测试清单

## 测试原则

- 所有运行时行为先取得真实 RED，再交实现 subagent。
- 测试默认断网；真实网络只用于发布后的受控 proof，不作为单元测试依赖。
- SQLite 验证业务分支，PostgreSQL 16 验证事务锁、竞争 manifest 和回滚。
- 现有 initializer schema v1、results runner、公开 read gate 和历史 importer 必须回归。

## A. TRA racecard parser

1. 合法 today/tomorrow racecards 只归一化客观白名单字段。
2. `form/ofr/rating/prize/pedigree/odds/comments` 不出现在 normalized payload。
3. `off_dt` 必须包含 offset。
4. race/runner ID、horse、number 缺失时整场拒绝。
5. race ID、runner ID、runner number 重复时拒绝。
6. 空 racecards 合法返回空 snapshot，供 report-only 使用。
7. 超过 500 races、100 runners 或非严格 JSON 时拒绝。
8. 现有 results parser 和 offline fixture contract 不变。

## B. 精确匹配

1. `GB + local_date + course + original_name` 唯一命中。
2. active `RaceEventAlias` 唯一命中。
3. 年度有效 `RaceSeriesName` 唯一命中。
4. 过期/inactive alias 不参与匹配。
5. major event alias 唯一命中。
6. case、NFKC、标点和空白差异可匹配。
7. substring、sponsor 删除、编辑距离相似不得匹配。
8. 日期、地区或赛场不符时零命中。
9. 两个 racecard 同时满足时为 ambiguous。
10. 一个 external race ID 命中两个 event 时整批 blocker。
11. 非英国、非显式 event ID、已完赛、已有赛果、人工锁或已有 live 行拒绝。
12. event 的非空冲突时间拒绝；相同时间允许 replay 准备。

## C. Manifest 与 artifact

1. 输出 schema v2 精确键集合和确定性 SHA。
2. stable key 为 `tra:<sha256(horse_id)>`，不含马号/姓名。
3. participant country 留空，不伪造成举办地区。
4. source off time、本地日期/时间和 response SHA 正确。
5. manifest 不含 raw、credential、secret path 或禁止字段。
6. 配置 root 必须绝对、非 symlink、预先存在；run-id 只能在该 root 内创建。
7. 文件 exclusive create、`0600`；同 run-id 不覆盖。
8. 任一目标 blocker 时只输出 report/requests，不输出 manifest。
9. stdout 只含路径、SHA、计数、blocker code。

## D. 网络与来源门禁

1. 未确认真实网络时零请求。
2. registry digest/terms/automation/有效期失败时零请求。
3. secret 非 regular、非 `0600`、symlink 或缺字段时零请求。
4. 固定请求仅 today/tomorrow + `region_codes=gb`。
5. HostBudget 缺失时精确 bootstrap；最多两次请求且相邻预约满足 1 RPS。
6. redirect、非 JSON、超限、401/403/429/5xx/timeout/schema drift 输出 blocker。
7. transport/clock 注入测试不访问互联网。
8. HTTP 运行时不持有 `transaction.atomic`。
9. registry 保留旧三条并追加精确 sync today/tomorrow；旧 SHA、未知 query、参数重排拒绝。
10. 两次请求后 initializer v2 dry-run/apply/verify 允许 HostBudget 动态字段非零。
11. 并发 prepare/runner reservation 串行；迟到 outcome 不覆盖较新 reservation。
12. policy valid-until 晚于 registry valid-until 时 prepare 与 initializer 均拒绝。
13. 首次 reservation 未到期时最多等待并重试一次；不超过 2 秒可继续，超过时零请求并
    返回 `host_budget_wait_exceeded`，不 busy-loop。

## E. Initializer schema v2

1. v2 loader 接受精确 schema；未知/缺失键拒绝。
2. pre-race datetime 只允许 JSON null/aware datetime；pre-local-time 只允许
   JSON null/严格本地 time 字符串。
3. source off time naive、转换 Europe/London 后当地日期不符、wall time 不一致拒绝。
4. participant barrier/jockey 字段长度和 JSON 类型严格校验。
5. v1 现有所有测试保持 GREEN。
6. expected status/local date/timezone 缺失、取消/延期或错误 `Asia/Tokyo` 拒绝。
7. `Z/+00:00/+01:00` 及 BST/GMT 切换按 Europe/London 得到正确本地日期/时间。
8. manifest requests/report SHA 或 official route evidence SHA 漂移拒绝；只挂载孤立
   manifest、缺 sibling 或 sibling symlink 同样拒绝。

## F. Apply、Replay 与回滚

1. dry-run 对 RaceEvent 和全部 live 表零写入。
2. fresh apply 原子设置 `race_datetime/local_start_time`。
3. fresh apply 创建 control/tracking/source/participant/racecard revision/policy/allowlist/budget。
4. racecard revision 保存 number/barrier/jockey 和 bounded provenance。
5. `timezone_name/local_date` 不被猜测或改写。
6. initializer 后段外部 ID 冲突时，RaceEvent 时间和全部 live 行回滚。
7. 人工锁、event `updated_at` 漂移或时间漂移时零写入。
8. 相同 manifest replay 不增加 revision、counter、participant 或 OperationLog。
9. 不同 manifest 不得进入 replay 分支。
10. verify 对时间和全部初始化行精确检查。
11. apply 后删除/修改任一行时 verify 失败。
12. `QuerySet.update()` 绕过 updated_at 改 status/local_date/timezone 仍被逐字段 CAS 阻断。
13. pre-off state/next poll 由调度函数确定；post-off 为 awaiting+立即 due。
14. 有效 pre-off claim 在未到 off 时零请求、不晋级，但 checkpoint 清 claim、failure
    counter 不增加且 next poll 前移且不晚于 off；旧 claim/owner 漂移仍零 mutation。
15. 到达 off 后只在有效 owner/claim 下原子晋级 awaiting 并进入结果请求；stale claim
    不能晋级或发请求。

## G. PostgreSQL 与并发

1. 同一 event 两个 v2 apply 并发，至多一个 manifest 成功。
2. 失败事务不残留时间或 partial live rows。
3. external race/runner unique constraint 竞争保持全事务原子。
4. v1 现有 PostgreSQL初始化并发回归不变。
5. HostBudget 已经经过多次 reservation/outcome 后 v2 竞争仍保持原子。

## H. 相邻回归

1. TRA live results runner 继续只读取已初始化 source identity。
2. selector/claim/checkpoint 和 `race_live` queue route 不变。
3. publication admission participant completeness 不变。
4. shadow 不产生 `RaceEventResult`、publication 或 official incident。
5. 赛事详情/日历无 live 数据时展示行为不变。
6. historical runner/importer/receipt 测试不受影响。
7. Django check、`makemigrations --check --dry-run`、Compose config、脚本语法和
   `git diff --check` 通过。
8. 三份 Compose 只有 race_live_worker 同时拥有 secret ro 与 artifact rw mount；
   web/worker/beat 均无 secret。

## I. Artifact 原子性

1. 固定 configured root，root/祖先 symlink、相对路径和 run-id traversal 拒绝。
2. requests 写入失败不产生最终目录。
3. report 写入/fsync 失败不产生最终目录。
4. manifest 写入/fsync 失败不产生最终目录。
5. rename/fsync 失败不产生 apply-ready final manifest。
6. blocker run 原子完成 report 目录但没有 manifest。
7. manifest 绑定 requests/report SHA，替换任一文件后 initializer 拒绝。

## RED 证据

2026-07-18 在任何对应生产代码修改前，使用
`/Users/mentianlu/Code/umanews/.venv/bin/python` 取得以下真实 RED；所有 SQLite 命令均带
`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true`，均未访问真实网络、生产数据库、Redis
或队列。

| 行为 | 最小命令（`server/manage.py test ... --noinput`） | 退出码 | 目标失败 |
| --- | --- | ---: | --- |
| live racecard parser/客观字段 | `stable.test_race_live_racecard_sync.TheRacingApiLiveRacecardPayloadTests.test_normalizes_only_the_objective_allowlist_and_accepts_empty_collection` | 1 | `parse_the_racing_api_live_racecards_payload` 尚不存在 |
| today/tomorrow prepare 主链 | `stable.test_race_live_racecard_sync.RaceLiveRacecardPrepareTests.test_exact_today_tomorrow_prepare_bootstraps_budget_and_writes_bound_artifact` | 1 | `stable.services.race_live_racecard_sync` 尚不存在 |
| registry/transport 精确路由 | `stable.test_race_live_source_proof.TheRacingApiFreeSourceProofTests.test_sync_routes_are_exactly_allowlisted_without_expanding_proof_budget` | 1 | 现有三路径 registry 与新增两条 GB sync 路由不匹配 |
| schema v2 全模块 | `stable.test_race_live_initialization_v2` | 1 | 7/7 因 v2 顶层字段仍被旧 loader 判为 unknown 而失败 |
| 有效 pre-off claim | `stable.test_realtime_race_results.RaceLiveTheRacingApiFreeRunnerTests.test_pre_off_claim_checkpoints_without_http_or_failure_increment` | 1 | runner 提前进入 HTTP 并返回 `the_racing_api_payload_invalid`，未执行 `pre_off_wait` |
| off-time 晋级 | `stable.test_realtime_race_results.RaceLiveTheRacingApiFreeRunnerTests.test_at_off_claim_is_promoted_before_the_first_results_request` | 1 | transport 看到的仍是 `racecard_ready`，未先 CAS 晋级 |
| setting/三份 Compose mount | `stable.test_realtime_race_results.RaceLiveWorkerDeploymentContractTests` | 1 | 5 项中 4 项失败：缺 artifact root setting/env 与 worker-only rw mount |

PostgreSQL 事务 RED 使用一次性本地 `postgres:16-alpine`，连接
`127.0.0.1:55439`，命令为：

```text
DB_ENGINE=postgres POSTGRES_DB=racecard_red POSTGRES_USER=racecard_red \
POSTGRES_PASSWORD=racecard_red_password POSTGRES_HOST=127.0.0.1 \
POSTGRES_PORT=55439 POSTGRES_SSLMODE=disable POSTGRES_CONN_MAX_AGE=0 \
CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python \
server/manage.py test \
stable.test_race_live_initialization_postgres.RaceLiveInitializationV2PostgresTests \
--noinput
```

退出码为 `1`；测试数据库成功创建/销毁，唯一测试因 v2 loader 尚未接受
`registry_valid_until/requests_sha256/report_sha256/official_verification_evidence_sha256`
而在并发 apply 前失败。这是目标 schema 能力缺失，不是 PostgreSQL 环境错误；一次性容器
随后已停止并自动删除。

这些测试分别可捕获：禁止字段重新泄漏、放松精确匹配、绕过 HostBudget/1 RPS、扩大来源
allowlist、接受 companion 漂移、非原子时间写入、不同 manifest 被误判 replay、遗漏
Europe/London 转换、赛前提前请求、claim 不释放、off-time 晋级顺序错误，以及把 secret
或 artifact 永久挂给 web/普通 worker/Beat。

已有能力边界未冒充 RED：

- `stable.test_race_live_initialization`：6/6 GREEN，证明 schema v1 基线正常；
- `stable.test_realtime_race_results.RaceLiveOfflineFixtureRunnerTests`：7/7 GREEN，证明
  offline fixture runner 未因测试准备而破坏；
- `py_compile` 与 `git diff --check`：退出码 0；
- stale owner 零 mutation 属于既有安全能力，继续作为回归断言。

## GREEN 证据

实现 subagent 和主代理分别复跑了受影响组合。主代理的 SQLite 命令为：

```text
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
/Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
stable.test_race_live_racecard_sync \
stable.test_race_live_initialization_v2 \
stable.test_race_live_initialization \
stable.test_race_live_source_proof \
stable.test_realtime_race_results \
stable.test_historical_race_detail_import_receipt \
stable.test_historical_race_detail_import_primitives \
stable.test_race_event_distance_display --noinput
```

结果为退出码 `0`、`203/203`；覆盖 parser、prepare/matching/artifact、schema v1/v2、
TRA runner、publication/read gate、部署契约和相邻历史 importer/receipt/距离展示。

主代理另以一次性本地 `postgres:16-alpine` 运行：

```text
DB_ENGINE=postgres POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55439 \
POSTGRES_SSLMODE=disable POSTGRES_CONN_MAX_AGE=0 \
CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python \
server/manage.py test stable.test_race_live_initialization_postgres \
stable.test_realtime_race_results_postgres --noinput
```

结果为退出码 `0`、`6/6`；覆盖 schema v1/v2 并发初始化、不同 manifest 单一 winner、
HostBudget 串行 reservation 和既有 PostgreSQL 锁语义。测试数据库已创建/销毁，一次性
容器随后停止并自动删除。

以下验证均为退出码 `0`：

- `manage.py check`；
- `manage.py makemigrations --check --dry-run`，结果 `No changes detected`；
- 三份 Compose 的 `config --no-interpolate`；
- 变更 Python 文件 `py_compile`；
- `git diff --check`；
- tracked registry SHA-256 为
  `60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`；
- 实现 subagent 的断网 Docker build 成功，镜像内 registry SHA 与仓库一致，临时镜像已
  删除；部署契约断言 web/普通 worker/Beat 无 secret/artifact 永久挂载。

实现 subagent 还运行了 `stable` 全套：共发现 `1967` 项，但因仓库既有历史 runner
artifact 的 macOS `/var -> /private/var` canonical path、缺少 `python` 可执行名、历史
runtime tool 导入和既有 CSV descriptor 预期，得到 `4 failures / 70 errors / 26 skipped`。
这些环境/历史资产失败不作为本变更 GREEN；本变更以相同进程中通过的受影响 `203/203`
和真实 PostgreSQL `6/6` 为验收证据。独立代码 reviewer 仍须检查是否存在被误分类的直接
回归。

首次独立代码 review 的两个 P2 另有真实修复 RED/GREEN：

- artifact 并发：失败注入在 rename 前模拟另一进程发布同 run-id；修复前退出码 1，
  败者异常清理误删赢家并触发 `winner.json FileNotFoundError`。加入非阻塞 root 发布锁、
  不覆盖 final、以及仅删除本调用已发布且 device/inode 仍一致的目录后，同一测试 1/1
  GREEN；恢复“final 存在就删除”或移除所有权校验会重新失败。
- event 占用查询：40 个 event 分别让 control/tracking/source/allowlist/participant/
  revision/result/observation 八类命中，修复前为 322 queries 并超过 `<=20` 门禁。改为
  八类固定批量 event ID 查询后 1/1 GREEN；恢复任一逐 event `.exists()` 会打破查询预算，
  漏任一占用类型会使 blocker 数不再为 8。
- 修复后 `stable.test_race_live_racecard_sync` 为 `13/13`，准实时相关组合为
  `184/184`，完整受影响组合为 `203/203`；`py_compile` 与 `git diff --check` 继续为 0。

仍未执行真实 TRA 网络、生产 prepare、生产 initializer 或任何公开切换；这些属于最新
成功代码 review 后另行授权的发布/灰度步骤。
