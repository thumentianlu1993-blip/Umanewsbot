# 赛事数据生命周期生产发布证据

更新时间：2026-08-30 08:24 Asia/Shanghai

## 2026-08-30 08:14–08:24 PR #129 资源修复后赛前链路已重新启用

- PR #129 已合并为 `cbf3f0436aae99890ca2498bff7761adf4a71ccf`，生产隔离 release 为
  `/opt/umanews-release-cbf3f043-PR129-20260829T2250Z/umanewsbot`，image 为
  `sha256:8e70cc43667f946ac4329cf4a70c1be6ddc3cc63b9bfd3eccff8f28e8c36fc76`；回滚 tag 为
  `umanewsbot:rollback-pre-pr129-a040af3c-20260829T2306Z`。migration leaf 复核为 exact `0075`，
  `0073/0074/0075` 均已应用。
- 普通 worker 降为 `concurrency=1 / prefetch=1 / max-tasks-per-child=20 / max-memory-per-child=262144`
  并设置 512 MiB cgroup；专用 worker 为单并发、单预取、384 MiB cgroup。Web 修正为 2 workers/2 threads；
  canonical 与 release env 已恢复冻结容量、持久目录、TLS 根和 registry SHA
  `3bac3b644c631ed165b8430343822b2c70c5a88c5036b63dcb557c83c0e0a6da`。
- `2026-08-30T00:14:14Z` 写前门禁为 `MemAvailable=1949796 kB`、`SwapFree=1310716 kB`、
  `disk=16410984448 bytes`，三队列为 `0/0/7543`，随后按冻结顺序启用 future discovery、
  race time/racecard、lifecycle、result apply/public；9 个前置开关为 true，correction 仍为 false。
- future discovery 的当前业务 census 为 `total=113 / blocked=112 / enrolled=1`；本轮无候选、无 provider
  请求、无数据库写，前后数据库 SHA 均为
  `2ba2016cfaf229361b93d8d518ed03ff0e6f654806157967c46dae9042f4f274`。这里冻结的是“唯一已纳管赛事且
  其他候选保持阻断”的业务不变量，不再把会随时间自然变化的绝对 115/114 当作发布常量。
- race time/racecard task `6a82f8de-3a60-468c-9c68-f753fda5defe` 返回 `SUCCESS`、
  `processed=true / complete`，只应用 `race_time,racecard`；lifecycle smoke 为 complete、0 error、0 transition，赛前状态
  仍为 scheduled。独立审计返回 `configuration_status=ready / capacity=valid / route_drift=[] /
  would_write=false`，audit SHA 为
  `6c4bfb7ae9fa4072337da191428a1be9893319a1a80b02e84623ea4ec52829ae`。
- 专用 worker 冷启动约 2 分钟，最终拓扑为恰好两个隔离节点且均 idle；Beat 最后恢复。激活终态为
  `MemAvailable=1788692 kB / SwapFree=1310716 kB / disk=16410525696 bytes`，队列 `0/0/7543`，
  5 个公网验收 URL 均 200，赛前页面仍无赛果，锁已释放。
- 激活前发生的 discovery census 漂移、checkpoint 脚本引号错误、过早检查专用 worker 拓扑和普通 Beat
  backlog 均按规则真实 fail-closed；每次都恢复 10 false、普通 worker/Beat，移除专用 worker并保留队列，
  未伪装为成功窗口。最终成功窗口改用业务不变量与有界冷启动重试，没有放宽资源、路由或写入门禁。
- 随后完成 120 次、每 5 秒一次的 10 分钟热身观察：最低 `MemAvailable=1598324 kB`，全程
  `SwapFree=1310716 kB`、`race_sync_v2=0`、`race_live=7543`，普通 Beat backlog 自然入队并排空；最低值
  只比硬门槛高约 25 MiB，因此继续保留硬门禁，不追加联网 proof，也不以本次通过作为扩容理由。
- 独立复核时资源为 `1709212 kB / 1310716 kB / 16409595904 bytes`，锁 absent、三队列 `0/0/7543`；
  Web、普通 worker、Beat、专用 worker 均运行 exact PR #129 image/revision，restart=0、OOM=false，cgroup
  分别符合未设/512 MiB/未设/384 MiB。三类消费者的 9 true + correction false 完全一致。
- event 956 独立数据库复核为 `scheduled / is_public=true / runners=10 / results=0`，tracking 无 active token、
  lifecycle generation 2、transition 0、result revision null，result checkpoint 仍等待 `14:13Z`；root/www
  首页、带尾斜杠 healthz 和赛事页共 5 个 URL 均为 200，页面 9542 bytes 且 `results` 区块 absent。首次
  只读查询误用了不存在的 `is_published` 属性而中止，未发生写入；改用真实 `is_public` 字段后完整重跑通过。
- 激活与观察临时脚本已在确认无进程占用后从本地 worktree 和生产 `/tmp` 精确删除；未执行广义 prune、
  队列清理或其他文件删除。

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
