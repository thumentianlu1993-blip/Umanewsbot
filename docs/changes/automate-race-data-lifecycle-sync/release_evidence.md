# 赛事数据生命周期生产发布证据

更新时间：2026-08-30 20:05 Asia/Shanghai

## 2026-08-30 20:00 普通 worker OOM 门禁失败与自动关闭

- `12:00:57Z` 只读检查发现普通 worker `OOMKilled=true`；它仍 running、restart=0，但该标记是独立硬门禁。
  同时资源为 `MemAvailable=1736044 kB / SwapFree=1310716 kB / disk=16365473792 bytes`，四服务仍为
  exact PR #129，9 true + correction false，队列 `8/0/7543`。event 956 仍 scheduled、10 runners、
  0 results/transition、无 claim/revision，result checkpoint `14:13Z`、last attempt null。
- lock absent 后，自动保护用自己的 `manual-release` token 获取锁，将 canonical/active env 10 flags 全设
  false，依次停止 Beat、专用 worker、普通 worker和 Web，移除专用 worker，再以 exact image 重建 Web
  1×4、普通 worker与 Beat。没有 purge、消费、迁移或人工重排队列，也没有改 event/due/claim/result。
- `12:03:54Z` 独立复核为 lock absent、三服务 exact revision/image、restart=0/OOM=false、Web healthy、
  专用 worker absent、队列 `0/0/7543`，`MemAvailable=2127476 kB / SwapFree=1310716 kB /`
  `disk=16366440448 bytes`，6 个公网 URL 200；event 956 数据库状态与 checkpoint 未变化。
- 本窗口结论为 `CLOSED_AFTER_ORDINARY_WORKER_OOM`。相邻普通 worker 日志曾出现 DeepSeek 402、OSS 404
  和 backlog，但旧容器销毁后没有足够 cgroup/task 证据把它们直接定为 OOM 单一根因。必须先在关闭态完成
  归因、修复和热身，再从 future discovery 全量重走；不直接续开 result/public/correction。

## 2026-08-30 11:47–12:19 Web 1×4 后全量重开与 active 热身

- 关闭态全量 preflight 为 `MemAvailable=1932892 kB / SwapFree=1310716 kB / disk=16397012992 bytes`、
  lock absent、`celery/race_sync_v2/race_live=0/0/7543`、10 false、专用 worker absent。one-off audit 为
  `ready / valid / policy loaded / route_drift=[] / would_write=false`。摘要口径重新核清：TRA registry
  `3bac3b64…a6da`，provider roster `26e0625d…32d4`；后者与服务器 7 份历史独立 audit 一致。
- 在 shared `manual-release` lock 内停 Beat 并自然 drain 普通 worker；Phase 1 重跑为
  `total=113 / blocked=112 / enrolled=1 / requests=0 / writes=0`，相关数据库前后 SHA 同为
  `827ff114c2d0be78e9f1548ef291e412e4d183abec6aca4bca3b6d9295dd9e88`。没有调用 provider。
- 随后按冻结顺序启用 time/racecard、lifecycle、result apply、result public。每次重建后两个 Celery 节点
  均 exact/idle；event 956 一直为 scheduled、10 runners、0 results、0 transition。lifecycle smoke 为
  `selected=0 / not_due=0 / transitioned=0 / error=0`；active audit 为 ready/valid、route drift 0、
  9 true + correction false、would_write false。Beat 最后恢复。
- 期间身份探针误依赖 release 内 `.git`、普通 backlog 零值检查位置错误、Compose wrapper 参数顺序错误、
  控制会话中断以及 `numfmt` 不接受 Docker 小数 MiB 均被当作真实脚本失败；每次都自动 10 false、移除专用
  worker、恢复 Web/普通 worker/Beat并释放自己的锁，队列始终保留。最终脚本以 image label 识别身份、在
  停 Beat 后 drain、遵守 `run --rm --no-deps` grammar，并用自校验单位转换采样；没有把失败窗口改写成功。
- 最终 active 热身完成 120 个样本：最低 `MemAvailable=1767740 kB`，Web 峰值 `230057574 bytes`，普通
  `celery` 最高 26 并自然归零，`race_sync_v2=0 / race_live=7543` 全程不变，Swap 未下降，四服务
  restart=0/OOM=false，分段公网验收全部通过。终态
  `MemAvailable=1825508 kB / SwapFree=1310716 kB / disk=16389996544 bytes`，锁正常释放。
- 独立终态复核确认四服务均为 PR #129 exact image/revision，Web 进程确为 1×4，普通/专用 Celery 命令行
  符合冻结容量，0073/0074/0075 均 applied，无 one-off 残留；复核资源为 `1853372/1310716 kB`、
  `16389922816 bytes`，三队列 `0/0/7543`，5 个公网 URL 200、Meta 赛事入口 429。event 956 result
  checkpoint 仍是 `14:13Z` 且 last attempt null，公开页尚无 results 区块。
- 中断续跑终检于 `04:27–04:30Z` 完成：本轮自己创建的本地脚本及服务器 `/tmp` 脚本、日志、PID 文件已
  精确删除，deployment lock 始终 absent。Beat 周期使普通 `celery` 短时升至 29 后自然归零，期间最低
  `MemAvailable=1663796 kB`；`race_sync_v2=0 / race_live=7543` 不变。event 956 的 root/www canonical
  页面均为 200、9542 bytes 且 SHA-256 同为 `ebf7740c…df978`；没有人为消费、清队列或改写赛事记录。
- 当前权威状态为 9 true + correction false；heartbeat 已切换为 active 只读门禁与授权 fail-closed。只有真实
  result apply/public 通过后才单独开启 correction。UK/USA proof 与法国/爱尔兰未批准 proposals 继续暂停；
  后续 Beat 周期把已观测最小资源余量收窄到约 89 MiB，因此不扩容、不并发新增 proof，并保持硬门槛。

## 2026-08-30 09:41 运行期内存门禁失败、关闭态与 Web 第二轮优化

- 连续监视在 `2026-08-30T01:41:35Z` 第 77 次采样发现
  `MemAvailable=1496692 kB < 1572864 kB`；当时 Swap、磁盘、四服务和三队列其他不变量仍正常，
  `celery=5 / race_sync_v2=0 / race_live=7543`，deployment lock absent。该窗口立即以失败终止，未等待
  下一轮采样、未继续 provider 或数据库写入。
- 同一 owner 随即取得 `manual-release` 锁并完成 fail-closed：canonical 与 active release 双 env 10 false，
  专用 worker 停止并移除，Web/普通 worker/Beat 以 exact PR #129 image 重建；普通 backlog 自然排空，
  终态 `MemAvailable=1931332 kB / SwapFree=1310716 kB / disk=16398266368 bytes`，队列 `0/0/7543`，
  5 个公网 URL 均 200，自己的锁正常释放。
- 独立关闭态复核确认三服务 restart=0、OOM=false、10 false，专用 worker absent；event 956 仍为 scheduled，
  result/transition/active claim 均为 0，result checkpoint 未提前执行。关闭态常驻 cgroup 约为 DB 579–777
  MiB、Web 360 MiB、普通 worker 199 MiB、Beat 109 MiB；PostgreSQL 的主要部分是可回收 file cache，
  `shared_buffers=128MB`，而 Web 两个 worker 各约 173 MiB PSS，是下一项可逆优化目标。
- 在全部新写入关闭且共享锁独占时，Web 从 2 workers × 2 threads 调整为 1 worker × 4 threads，保持 4 个
  请求线程；失败路径已绑定自动回退 2 × 2。重建成功后 Web cgroup 为 `197246976 bytes`，公网和三队列
  均通过，自己的锁正常释放。
- 之后完成 10 分钟关闭态热身：88 次完整采样最低 `MemAvailable=1915052 kB`，Web cgroup 峰值
  `217976832 bytes`，普通 Beat backlog 自然入队并排空，Swap、磁盘、锁、三服务、专用 worker absent、
  `race_sync_v2=0 / race_live=7543` 与分段公网验收全程通过。独立终态为 `MemAvailable=2014948 kB`、
  Web cgroup `211234816 bytes`、5 个 URL 均 200。
- 当前权威生产状态仍是 10 false、专用 worker absent；Web 1 × 4 优化通过不等于自动化已重开。必须重新
  完成全量 preflight、关闭态配置审计和按冻结顺序的独立启用窗口，才可考虑恢复赛事链。

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
  仍为 scheduled。独立审计返回 `configuration_status=ready / capacity=valid / route_drift=[]`、
  `would_write=false`，audit SHA 为
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
- `2026-08-30T00:44:00Z–01:00:01Z` 又完成 149 次、每 5 秒一次的连续赛前观察：最低
  `MemAvailable=1604772 kB`，Swap、磁盘、deployment lock、四服务 running/restart/OOM、新队列为空与旧
  `race_live=7543` 均逐次通过。期间普通 `celery` backlog 最高 21 并自然排空，未 purge、重排或干预。
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
