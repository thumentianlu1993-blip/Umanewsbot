# 英国 racecard 级别后缀精确匹配测试清单

## A. RED

1. G3 event base name 对来源同名 `(Group 3)`：当前实现返回
   `racecard_not_found`，新增测试必须先真实失败。
2. RED 失败必须来自目标 suffix variant 尚未实现，不得来自 fixture、时钟、HostBudget、
   artifact 权限或数据库环境错误。
3. RED 命令与完整失败摘要记录回本文件后，才可交实现 subagent。

## B. 正常路径

1. `G1/G2/G3` 分别只生成末尾 `group 1/2/3` 变体。
2. event original name + 正确 Group 后缀唯一命中并生成 manifest。
3. active 英文 alias + 正确 Group 后缀唯一命中。
4. `RaceSeries.canonical_name_original` + 正确 Group 后缀唯一命中；测试中 event original 和
   其他名称均不得提供同名兜底，以捕获遗漏该路径的 mutation。
5. 当年有效 series name + 正确 Group 后缀唯一命中。
6. active、同年度 MajorRaceEvent 的 `name`、`normalized_name`、aliases 分别可提供正确
   Group 后缀命中；每项测试隔离其他名称路径。
7. 原始无级别精确名称继续命中，且不会因重复 variant 变成 ambiguous。
8. 已批准名称本身末尾同级 `(Group 3)` 只保留一次，不派生
   `group 3 group 3`，且单个来源候选仍唯一命中。

## C. 失败边界

1. G3 event 对 `(Group 2)` 为 `racecard_not_found`。
2. G3 event 的已批准 original/alias/series/major 名称末尾若为 `(Group 2)`，该名称本身和
   `Group 2 Group 3` 均不得进入获准集合；来源两种写法均为 `racecard_not_found`。
3. G3 event 的已批准名称含非末尾 `Group 2`、非末尾 `Group 3` 或多个 Group token 时，
   名称本身与追加 `Group 3` 的形式都不得进入获准集合。
4. G3 event 对 `(Listed Race)` 为 `racecard_not_found`。
5. G3 event 对 `(Group 3) Sponsored` 为 `racecard_not_found`。
6. `normalized_grade` 为空、Listed、Open、Jpn 或 J-G 时不生成 Group 变体。
7. expired/inactive alias 或 series name 即使 suffix 正确也不能命中。
8. MajorRaceEvent inactive、年份不符时不参与；其 name/normalized_name/alias 含汉字时不派生。
9. 中文 alias 或含汉字名称不参与派生。
10. substring、sponsor 增删、拼写差异继续拒绝。
11. 两个正确 Group 候选继续 `racecard_ambiguous` 且无 manifest。
12. 日期、地区或赛场不一致继续无命中。

## D. 回归

1. London instant/local date 测试。
2. HostBudget bootstrap、等待上限、CAS outcome 测试。
3. registry/terms/confirm-real-network 门禁测试。
4. artifact root、同 run-id、fsync、companion SHA 测试。
5. `_event_names()` 现有 original/alias/series/major 名称收集回归，防止过滤阶段误删非 Group
   名称。
6. schema v1/v2 initializer fresh/replay/竞争/回滚测试。
7. pre-off claim checkpoint 与 off-time awaiting_result 晋级测试。
8. Django check、`makemigrations --check --dry-run`、`git diff --check`。

## E. PostgreSQL 与生产验收

- 本变更不改变事务、锁、模型或 initializer；既有 PostgreSQL v2 初始化/竞争组合需回归通过，
  不新增专属并发行为。
- 生产代码部署后 flags 必须保持 `scheduler=false / runner=disabled / public=off`。
- 一个显式英国 G1-G3 event 的 prepare 最多两个请求。
- blocker artifact 无 manifest；成功 artifact 的 manifest 只进入单独审核，不自动 apply。
- 业务总量与 live fact 表在 prepare 后保持不变；HostBudget 动态更新按既有设计允许。

## RED/GREEN 证据

2026-07-18 在任何生产实现修改前，以 SQLite 测试数据库、Celery eager 和内存 transport
取得真实 RED；没有访问真实网络、生产数据库、Redis、队列或密钥。

核心最小命令：

```text
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
/Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
stable.test_race_live_racecard_sync.RaceLiveRacecardPrepareTests.test_g3_event_original_name_matches_exact_source_group_suffix \
--noinput
```

结果为退出码 `1`、`1/1` 失败；测试数据库正常创建/销毁且 system check 无异常。唯一失败
断言为 `result.completed` 预期 `True`、实际 `False`，失败消息明确给出
`('racecard_not_found',)`。受控 payload 的日期、地区、赛场、赛事名、runner 和 transport
均有效，因此该失败证明现有 `_event_names()` 未生成 `group 3` 精确变体，而不是 fixture、
导入或环境问题。

随后运行 6 个新增聚焦测试：

```text
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
/Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
stable.test_race_live_racecard_sync.RaceLiveRacecardPrepareTests.test_g3_event_original_name_matches_exact_source_group_suffix \
stable.test_race_live_racecard_sync.RaceLiveRacecardPrepareTests.test_group_suffix_variants_are_grade_exact_and_fail_closed \
stable.test_race_live_racecard_sync.RaceLiveRacecardPrepareTests.test_group_suffix_variants_cover_alias_and_series_name_paths \
stable.test_race_live_racecard_sync.RaceLiveRacecardPrepareTests.test_group_suffix_variants_cover_major_event_names_and_gates \
stable.test_race_live_racecard_sync.RaceLiveRacecardPrepareTests.test_mismatched_group_tokens_from_all_approved_paths_are_excluded \
stable.test_race_live_racecard_sync.RaceLiveRacecardPrepareTests.test_two_group_suffix_candidates_remain_ambiguous \
--noinput
```

结果为退出码 `1`、`6/6` 测试中产生 `19` 个预期 assertion failure、无 error：G1/G2/G3
变体、alias/series/major 各路径均缺少正确 suffix；异级 `Group 2` 基础名仍错误保留；
两个正确 `Group 3` 来源候选仍落为 `racecard_not_found` 而非
`racecard_ambiguous`。这些断言可捕获以下 mutation：

- 完全遗漏级别派生或只对 event original 派生；
- 遗漏 alias、series canonical、有效 series name 或 MajorRaceEvent 任一来源；
- 对已经同级的名称重复追加 suffix；
- 保留异级 terminal Group token，或继续派生双级别 token；
- 给非 G1-G3 event 派生 Group token；
- 放松 active、年度、语言、汉字、额外 sponsor、Listed、substring 或唯一性门禁。

## GREEN 与回归证据

实现 subagent 只修改 `race_live_racecard_sync.py`，先运行上述 6 个新增聚焦测试，结果为
退出码 `0`、`6/6 OK`；随后运行 `stable.test_race_live_racecard_sync`，结果为退出码
`0`、`19/19 OK`。

主代理运行 SQLite 完整受影响组合：

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

结果为退出码 `0`、`209/209`。这覆盖 racecard parser/prepare/matching/artifact、
schema v1/v2 initializer、TRA runner/publication/read gate 和相邻历史
importer/receipt/距离显示。

另以一次性本地 `postgres:16-alpine` 运行：

```text
DB_ENGINE=postgres POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55441 \
POSTGRES_SSLMODE=disable POSTGRES_CONN_MAX_AGE=0 \
CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python \
server/manage.py test stable.test_race_live_initialization_postgres \
stable.test_realtime_race_results_postgres --noinput
```

结果为退出码 `0`、`6/6`；覆盖 schema v1/v2 并发初始化、不同 manifest 单一 winner、
HostBudget 串行 reservation 与既有 PostgreSQL 锁语义。测试数据库创建/销毁正常，一次性
容器已停止并删除。

以下门禁均为退出码 `0`：

- `manage.py check`：0 issues；
- `manage.py makemigrations --check --dry-run`：`No changes detected`；
- 服务与测试 `py_compile`；
- `git diff --check`。

本轮没有执行真实网络、生产 prepare/initializer、迁移、队列或公开切换。

## 首次代码 review finding 的 RED/GREEN

首次原生只读 review 发现一个 P2：仅检查 terminal token 会把
`Foo (Group 2) Stakes` 当成“无 token”，错误保留基础名并派生
`foo group 2 stakes group 3`；`Foo (Group 2) (Group 3)` 也会因末尾同级而错误保留。

在修改实现前新增
`test_group_tokens_outside_the_only_terminal_suffix_are_excluded` 并单独运行。退出码为
`1`，一个测试产生 `3` 个预期 subtest failure、无 error；测试数据库正常创建/销毁且
system check 无异常。失败集合分别为：

- `{'foo group 2 stakes', 'foo group 2 stakes group 3'}`；
- `{'foo group 2 group 3'}`；
- `{'foo group 3 stakes', 'foo group 3 stakes group 3'}`。

最小修复改为扫描全部独立 Group token，只允许“恰好一个、位于末尾且同级”的名称直接
保留；零 token 才派生，其他情况全部排除。新增回归 `1/1`、全部聚焦 `7/7`、racecard
sync `20/20` GREEN。主代理再次运行完整受影响 SQLite 组合为 `210/210`；Django check、
migration drift、`py_compile` 和 `git diff --check` 再次为 0。该修复不触及数据库或并发
路径，因此前一轮一次性 PostgreSQL 16 `6/6` 证据仍有效。
