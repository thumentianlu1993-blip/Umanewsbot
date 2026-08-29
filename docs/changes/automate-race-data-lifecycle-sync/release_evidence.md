# 赛事数据生命周期生产发布证据

更新时间：2026-08-30 06:40 Asia/Shanghai

## 2026-08-30 06:36 内存门禁失败与关闭态

- `2026-08-29T22:36:06Z` `MemAvailable=751020 kB < 1572864 kB`，后续最低约 528300 kB；普通
  worker cgroup 约 1.344 GiB，是主要异常占用。Swap 完整、磁盘约 16.85 GB。
- 先等待并尊重其他任务持有的 `manual-release` 锁；其停止联网并安全释放后，本窗口另取锁执行止损。
- 双 env 10 false，`race_sync_v2_worker` 已移除；Web/普通 worker/Beat 以当前 image 重建。终态
  `MemAvailable=2050808 kB`、三队列 `0/0/7543`、root/www healthz 200、锁 absent。
- 本文件下方的 result/public “赛前窗口已开启”现只作为历史阶段证据；当前权威状态是全部新写入关闭。
  correction 从未开启，result checkpoint 未提前执行。完成普通 worker 内存保护 hotfix 和新热身前不得重开。

## 发布身份与恢复点

- 合并：PR #127，revision `a040af3c0db61ed7bafd6f46c56f55510d90257f`。
- 隔离 release：`/opt/umanews-release-a040af3c-PR127-20260829T2121Z/umanewsbot`。
- 生产 image：`sha256:7eb5c32919cb5a378e4b2e15f663ef00c5ea0f2a08012346f125919c7259628d`。
- migration leaf：`0075`，包含 `0074/0075`。
- generation 2 registry：raw SHA
  `28c327c0897f3c1559dfa99fc9fed76532dc1b1bee6f2ed994db4e680e5bb1a9`，membership SHA
  `b290700270b4d813134a671e19d25f38e77d6d98d6a11f8f16954c59bae754cc`，member_count=1，event 956。
- promotion 备份：`rds_horse_news_20260829T215423Z_3070249.dump`，487733802 bytes、0600、SHA
  `1606a014b81ffc730f827aa4e69841e72133e447dc51b187ea006498b0003f85`，`pg_restore --list` 1359 行。

## 冻结不变量

- 旧 `race_live` 队列始终为 7543，不删除、迁移或消费，也不启动旧 worker。
- 新同步只使用 `race_sync_v2`，专用 worker 只订阅该队列；普通 worker 只订阅 `celery`。
- 资源门槛为 `MemAvailable>=1572864 kB`、`SwapFree>=524288 kB`、free disk
  `>=8589934592` bytes；专用 worker cgroup 上限 384 MiB。
- correction 在 result apply/public 的真实赛事验证前保持 false；禁止手工修改 due time、claim 或结果行。
- 任一门禁失败执行 10 false、移除专用 worker、恢复普通 worker/Beat；不清 Redis、不删除不可变证据。

## 已通过阶段

1. future discovery：真实纳管 event 956，generation/owner/checkpoint 建立；没有接管旧 live owner。
2. race time/racecard：provider business result 为 `processed=true / complete`，应用
   `race_time,racecard`；checkpoint failures=0。
3. lifecycle：event 956 控制为 `enforce / schedule_generation=2`；Celery smoke 为
   `complete`，无 error、重复 transition 或数据库漂移。
4. result apply/public 赛前窗口：两个开关为 true，result checkpoint 自然等待
   `2026-08-30 14:13:00Z`；correction=false。
5. fail-closed：早期 discovery contract 与 worker readiness 门禁失败时，均真实执行 10 false、移除专用
   worker、恢复普通 worker/Beat，并验证 `race_sync_v2=0 / race_live=7543`；失败窗口没有追溯改写为通过。

## 赛时前公开页与数据库基线

采样时间：2026-08-29T22:33Z。验收路径：
`/races/2026/uk-bha-flat-2026-0830-099/`。

- `umafans.run` 与 `www.umafans.run` 均为 HTTP 200，响应均为 9542 bytes，SHA-256 均为
  `ebf7740cb7c084914ff971b3fc0fec90bf3b5d45340f8579b1ba7405c26df978`。
- 页面已有出马表；没有 `id="results"`、没有“赛果”标题，也没有 provider/source phase 标签。
- 数据库 event 956 为 `scheduled/published`，`race_datetime=2026-08-30T14:10:00Z`；result 行 0、result
  observation 0、result revision/publication 0、`result_confirmed_at=NULL`。
- result checkpoint `last_attempt_at=NULL / last_success_at=NULL / failures=0 / next_poll_at=14:13Z`；
  tracking 无 active token，correction/publication 时间均为空。

## 上线后完成性回归

- 当前代码以只读 mount、SQLite 和 `RACE_DATA_SYNC_ALLOW_NETWORK=false` 运行赛事同步/lifecycle/result
  核心组合：249/249。
- 当前代码另在一次性 PostgreSQL 16 容器运行 R0 与 pipeline A 专项：25/25；覆盖真实数据库行锁、并发
  claim/CAS、幂等、约束与 migration 路径。测试数据库创建和销毁正常，临时数据库容器与网络已回收。
- Django check、migration drift、重定向 bytecode 的 compileall、三份 Compose config 和
  `git diff --check` 全部通过。
- 首次 compileall/Compose 只出现只读目录无法写 pycache、worktree 缺 `.env` 的验证环境错误；改用临时
  pycache 与由 `.env.example` 生成的临时 Compose project 后完整重跑通过，未修改用户 checkout。

## 尚待真实赛事证明

- T/T+30 lifecycle transition 与唯一 transition 记录。
- T+3 后 provider 终态、完整 roster、immutable result revision、canonical projection 与 publication。
- root/www 公开详情页出现统一“赛果”，不泄露 provider/source phase，且与数据库一致。
- result/public 全部通过后，单独开启 correction，观察一个无重复写、无 revision 反转、无错误的完整周期。
- 将最终证据补入本文件和五份项目文档，完成 PR #128 后暂停 heartbeat。
