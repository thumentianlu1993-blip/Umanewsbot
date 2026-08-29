# 当前状态

## 2026-08-30 PR #127 已上线，赛事生命周期进入真实赛时验收

- PR `#127` 已以 revision `a040af3c…257f`、image `7eb5c329…9628d` 上线，Django migration leaf
  精确为 `0075`。发布前后均未消费、迁移或删除旧 `race_live`，队列保持 `7543`；当前与即时回滚 image
  均保留，dangling image 为 0。
- generation 2 已只纳管仍符合条件的 event 956；6 个已结束的 predecessor 不复制到 successor roster。
  最终 registry raw SHA 为 `28c327c0…b1a9`、membership SHA 为 `b2907002…54cc`，控制面已切换到
  `enforce / schedule_generation=2`。注册 promotion 自动生成的新备份为
  `rds_horse_news_20260829T215423Z_3070249.dump`，487733802 bytes、0600、SHA
  `1606a014…f85`，`pg_restore --list` 为 1359 行。
- future discovery、`race_time/racecard` 与 lifecycle 已依次通过独立窗口。event 956 的 provider 实际结果
  为 `processed=true / complete`，应用 `race_time,racecard`；lifecycle Celery smoke 为 `complete`，未产生
  错误或重复 transition。数据同步专用 worker 在阶段间均按门禁移除或重建。
- result apply/public 窗口已开启，correction 继续为 false。首次真实 selector/provider 已成功刷新
  `race_time,racecard`，result checkpoint 仍按赛事时间自然等待 `2026-08-30 14:13:00Z`，未手工修改 due
  time、claim 或数据库。event 956 的真实赛果、公开页和更正自动化须在 T/T+3 后依次验证，不能用任务
  `SUCCESS` 代替业务结果或公开可见性。
- 当前队列为 `celery=0 / race_sync_v2=0 / race_live=7543`；专用 worker 内存上限 384 MiB，服务 revision/
  image 一致且 restart=0、OOM=false。最近热身窗口 `MemAvailable` 约 1.94–1.99 GB、Swap 完整、磁盘约
  16.86 GB，均高于冻结门槛，无需扩容。已建立当前任务内的定时续跑，在真实赛时检查 lifecycle、result
  apply/public 与公网，再仅在全部通过后开启 correction；任一门禁失败立即 10 false 并移除专用 worker。
- `a040af3c` clean-worktree 完成性审计再次运行当前代码：赛事同步/lifecycle/result SQLite 核心组合
  249/249；Django check、`makemigrations --check --dry-run`、重定向 bytecode 的 compileall、三份 Compose
  config 和 `git diff --check` 全部通过。测试容器显式 `RACE_DATA_SYNC_ALLOW_NETWORK=false`，没有真实
  provider 请求或生产写入；首次只读源码 compile/缺 `.env` 的环境错误已用临时 pycache 与临时示例 env
  修正后重跑，不计作代码失败。

## 2026-08-30 Racing API proof 发布前关闭 legacy queue 合同冲突

- proof-only PR `#125` 已合并到 `main@865a41a0…5201`，尚未部署。生产只读盘点为
  `celery=2 / race_sync_v2=0 / race_live=7543`，普通 worker 正在执行既有新闻抓取；服务与数据库健康，
  TRA import lock/active claim 均为 0。
- 发布前发现 generator 把冻结的旧 `race_live=7543` 也要求归零，与项目“不得清理、迁移或消费该遗留队列”
  冲突。若不修正，合法 proof 永远不可生成；因此暂停部署，没有重启、清队列、TRA 请求或数据库写入。
- 修正合同：`celery` 与 `race_sync_v2` 必须为 0；旧 `race_live` 可保留非负计数，但全部 live/data-sync
  网络开关必须 false、host evidence 中不得存在 `race_live_worker/race_sync_v2_worker` 容器、Celery inspector
  只能看到预期普通 worker 且其订阅队列必须精确为 `celery`。新增回归后 proof 专项 `9/9`、check、migration
  drift、pycompile、diff check 均通过。

## 2026-08-30 悬空层已清完，Phase 2 因 readiness 信号门禁停止

- 用户单独授权后，已精确删除 Created/running=false 的旧 `umanewsbot-race_live_worker-1` 容器及其
  `sha256:e0a2d3d6…e61a3` image；删除前后 `race_live` 均为 7543，队列没有被消费或删除，当前 prod
  `74465006…d8df` 与即时 PR117 rollback `cb3852e4…663c` 均保留。
- 删除旧 image 后逐层暴露新的 dangling parent。每轮冻结完整 image ID，并确认 RepoTags 为空且全部运行/
  停止容器引用为 0；共精确删除 82 个 image manifest/layer，未使用 `prune -a` 或 `--force`。最终
  dangling=0，free disk 回升到约 `10067349504` bytes；尾段实际回收 `1475436544` bytes。
- 新 Phase 2 窗口在任何开关变更前停 Beat，普通 worker drain 为 active=0/reserved=0/active_confirm=0；随后
  才把 data kinds 收窄到 `race_time,racecard`，开启 network/schedule/racecard apply 并重建普通/专用 worker。
  两个容器 running、restart=0、OOM=false，但 240 秒内日志均未出现脚本要求的 `ready.` 字样，因此 readiness
  gate 超时；12 个热身样本和 selector 均未开始，没有 data-sync task/provider 请求或本阶段业务写入。
- fail-closed 已恢复 10 false、data kinds 恢复 `race_time,racecard,result`、移除专用 worker并恢复普通
  worker/Beat。随后普通 worker 返回 `pong`，DNS/Redis ping 正常，普通队列在 5 分钟内自然归零；说明本次
  是 readiness wrapper 依赖日志文本的误判，不是 broker、内存或磁盘故障，但失败窗口不得追溯改为通过。
- 最终 active/reserved=0/0，`celery=0 / race_sync_v2=0 / race_live=7543`，event 956 的过期 claim 仍按
  CAS 合同保留、checkpoint failures 为 0。`MemAvailable=1676232 kB`、`SwapFree=1310716 kB`、磁盘约
  `10061934592` bytes；root/www/races 200、Meta 精确 `/races/` 429。下一次只能新开 Phase 2 窗口，并用
  目标 worker hostname 的 Celery ping/inspect 完整快照替代日志字符串门禁；本轮不自动重试。

## 2026-08-30 悬空镜像清理只完成零引用子集，磁盘仍低于 Phase 2 门槛

- 用户授权清理只读盘点得到的 5 个 dangling image。删除前重新逐一核对完整 image ID、tag、当前/回滚
  image 排除关系和全部运行/停止容器引用；其中 4 个仍为零 tag、零容器引用，已精确删除，未使用宽泛
  `prune` 或 `--force`。
- 第 5 个 image `sha256:e0a2d3d6…e61a3` 虽无 tag，但被
  `umanewsbot-race_live_worker-1` 引用；该容器状态为 Created/running=false、restart=0、OOM=false，属于
  明确保留未消费的旧 `race_live` 边界。因此清理在删除该容器前停止，不把“dangling”误当作“零引用”。
- 前 4 个 image 的层均被第 5 个共享，实际只回收 `61440` bytes；Docker 当前仍报告约 `720.6 MB`
  reclaimable，但需要先删除上述未运行容器才能释放。最新 free disk 为 `8572174336` bytes，已低于冻结的
  `8589934592` bytes；Phase 2 未重启，`race_sync_v2=0 / race_live=7543`，新写入继续全关。
- 下一步只能在用户单独确认后精确删除该 Created 容器及其旧 image，或改走磁盘扩容。不得 `docker image
  prune -a`、不得强删容器、不得触碰备份/release/runtime/volume，也不得降低 8 GiB 门槛。

## 2026-08-30 PR #120 已上线，Phase 1 建立单场纳管，Phase 2 因普通队列排空超时停止

- manifest 顺序 hotfix 已通过 PR `#120` 合并为
  `409f2ac6cd15b7e8781dd9ada2903c91a9fc2121`，生产隔离 release 为
  `/opt/umanews-release-409f2ac6-PR120-20260829T154300Z/umanewsbot`，web/worker/Beat 当前统一运行
  image `sha256:744650063e3da92bde4e2d2529e817f66ff50e40df8100afd6a4ccc00ad6d8df`，revision、image、
  restart=0、OOM=false 均一致。release task 的 migration plan 为空，最终 leaf 仍精确为
  `0075_race_data_source_priority_and_reported_position`。
- 本次无 schema 变化且磁盘接近冻结下限，未创建第二份约 468 MiB 备份；继续使用并重新验证恢复点
  `pre-pr115-activation-20260829T104229Z.dump`：`468585439` bytes、0600、SHA-256
  `0bbec2c477afaebf83691e2e2cbaa9ba6e9ae249fa1c894344ea906bff7b7746`、PostgreSQL 16 TOC 1366 行。
  关闭态 audit artifact 为
  `/opt/umanewsbot-builds/pr120-409f2ac6/race-data-activation/audit-closed-pr120-20260829T155300Z.json`，
  SHA-256 `80821aa72198348117e261931a5d10235eca70d77f05a010731974805c422401`，结果为
  ready/valid、route drift 0、artifact root 0、would_write=false。
- 第一次 Phase 1 discovery 的真实业务终态是 `enrollment_applied`：115 场中 1 场 eligible/acquired，event
  `956` 建立 generation 1 enrollment、`data_sync` owner 和三类 checkpoint；旧操作 wrapper 错把任何 DB
  delta 都当作失败并回到全关。用户明确选择保留该精确纳管。随后只读重放 artifact
  `phase1-replay-pr120-20260829T174713Z.json` 的 SHA-256 为
  `1b82a42c68ca96d442e3dc61bd7e26a5d3e80890f89acf9fb4f5e39122e643f6`：114 blocked、1 enrolled、
  0 candidate、0 provider request，数据库前后状态 SHA 同为
  `a9e4b6a82b2e2f143b508633e60f74ac222bc4b678a5774079624b05b2832ed0`，Phase 1 通过。
- 中断恢复时确认 deployment lock 的记录 PID 已死亡且无 deploy/rollback/drain 进程，按锁脚本约定只移除
  精确陈旧目录。Beat 停止竞态留下的一条 event 956 旧 selector 消息包含
  `race_time/racecard/result`；在 10 个开关全 false 时由短命专用 worker 消费，业务返回
  `disabled/claim_expired`，无网络、无 apply、checkpoint failure 仍全为 0。过期 token 按控制面合同保留，
  下一次 selector 可在事务中原子换代，不直接改库清除。
- 恢复后的 Phase 2 在任何网络/写入开关变更前先停 Beat，并等待普通 worker active/reserved 双零；当时一条
  `stable.tasks.crawl_news_source_task` 连续 180 秒仍 active，故 drain gate 超时并执行 fail-closed。该新闻
  任务稍后返回 SUCCESS（crawl job `65191`，seen 40、new 0），但不能追溯性改写已经失败的门禁，本轮不重试
  Phase 2，也未进入 lifecycle/result public/correction。
- 当前生产 10 个 data-sync 开关全 false、专用 worker absent，普通 worker/Beat 已恢复且
  active=0/reserved=0，`celery=0 / race_sync_v2=0 / race_live=7543`。root/www/races 为 200，Meta 精确
  `/races/` 为 429。`MemAvailable=1700304 kB`、`SwapFree=1310716 kB`，内存仍通过且无需扩 RAM；磁盘
  `8606695424` bytes，只比冻结的 8 GiB 下限多 `16760832` bytes。下一次重试前必须先以另行授权的可恢复
  清理或磁盘扩容恢复余量，不能降低门槛；当前新写入保持关闭。

## 2026-08-29 PR #119 入口保护已上线，Phase 2 因 manifest 顺序契约止损

- PR `#119` 已合并为 `474aad1430d1451ad4e45713bd3d50a5f889ab9b`。生产 Nginx 当前配置 SHA-256
  为 `7bc8fd14…934`；单文件 bind 因 inode 固定不能靠 reload 换入新内容，已在 `nginx -t` 通过后只重建
  Nginx 容器。Meta/Facebook 对精确 `/races/` 与字体返回 `429`，普通 root/www/races 返回 `200`，精确目标
  未再进入 Django；约 5 分钟六轮公网门禁均在 20 秒内通过，Nginx/Web restart、OOM、5xx 为 0。
- 关闭态 audit artifact 为
  `/opt/umanewsbot-builds/pr119-474aad14/race-data-activation/audit-closed-pr119-20260829T151756Z.json`，
  SHA-256 `a11ee227…b87`；`ready/valid/route_drift=[]/would_write=false`。Phase 1 artifact SHA-256
  `50b8db97…0e`，115 场全 blocked、0 provider 请求、数据库前后 SHA 相同。
- Phase 2 专用 worker 约 `124.7 MiB`，12 个样本最低 `MemAvailable=1829468 kB`、swap 未使用，现有主机
  无需扩容。随后只派发一次真实 discovery，Celery terminal 为 `SUCCESS`，但业务终态为
  `blocked/future_discovery_contract_invalid`；日志精确为
  `manifest entry allowed_path_prefixes is invalid`，因此不得视为成功。
- 自动止损已恢复 10 个 data-sync 开关全 false、停止专用 worker并恢复普通 worker/Beat；当前
  `celery=0 / race_sync_v2=0 / race_live=7543`，旧队列未消费。失败前 3 个受控 provider 请求只新增 1 条
  source identity 与 3 条 capacity ledger 证据；enrollment、data-sync owner、checkpoint、observation、
  revision 和 active claim 均为 0，证据不删除。
- 根因是 manifest 生成器保留已审路由声明顺序，而应用器额外要求 `allowed_hosts/allowed_path_prefixes`
  必须字典序；生产 TRA 的窄结果路径故意先于宽前缀，因而同一 roster 自己生成的 manifest 被拒。最小修复
  改为要求列表非空、字符串且无重复，同时保留原顺序与 route binding 精确比对；不修改 route/registry
  digest、冻结 policy 或 transport。聚焦回归 `77/77` 已通过，待合并并关闭态部署后从 Phase 1 全量重走。

## 2026-08-29 PR #117 已关闭态上线，激活因 20 秒公网门禁再次停止

- PR `#117` 已合并为 `6e6d79778d206817058585b8c25287c005378e04`，生产隔离 release 为
  `/opt/umanews-release-6e6d7977-PR117-20260829T130421Z/umanewsbot`，image 为
  `sha256:cb3852e4180c8d0902333171541d33910eab0ac10b1533dc37d06afdef7e663c`，PR #116 image 已固定为
  `umanewsbot:rollback-pre-pr117-20260829T1307Z`。handoff SHA 为
  `a6893930f729ee31e8d1e4f59e1847128aeb083697e367673d970f4751f9d33d`；release task 明确为
  migration plan 空、`No migrations to apply`、最终 leaf `0075`。
- 复用并重新验证激活备份 `pre-pr115-activation-20260829T104229Z.dump`：`468585439` bytes、0600、
  SHA-256 `0bbec2c4…7746`、PostgreSQL 16 `pg_restore --list` 1366 行。为保持 8 GiB 门槛，只删除了
  2026-07-15 的单一旧传输暂存 tar `umanewsbot-main-ccfee75f-amd64-20260715-1210.tar.gz`
  （`123394611` bytes、无运行引用、可由 Git 恢复），未删除备份、release 或 rollback image。
- 关闭态正确 audit 必须用带 `/run/race-data-sync` mount 的短命 `race_sync_v2_worker` one-off；artifact
  `/opt/umanewsbot-builds/pr117-6e6d7977/race-calendar-hotfix/audit-closed-sync-mount-20260829T1314Z.json`
  SHA-256 为 `a013c0e8…979`，结果 `ready/valid/artifact_root_bytes=0/route_drift=[]/would_write=false`，
  free disk `8747511808` bytes，115 场仍全 blocked，既有 ledger 仍为 1 request/2 MiB。此前误在 Web
  容器运行的 audit 因设计上无 artifact mount 返回 invalid，不是配置漂移，不作为门禁证据。
- 部署后 web/worker/Beat 同 image/revision、restart count=0，10 个 data-sync 开关全 false，
  `celery=0 / race_sync_v2=0 / race_live=7543`。畸形 URL 已快速 301 到 `/races/?tab=all`，正常赛事筛选页
  约 `0.036s`，HTML 不再带污染片段；源码与 image 内 SHA 一致。
- 入口压力仍未消失：5 分钟 Web/Nginx 日志有 `464` 个 Meta/Facebook crawler 请求、`468` 个
  `/races/`、`321` 个快速 301、0 个 5xx。crawler 继续跟随 canonical URL，并并发抓取大字体静态资源。
  本地回环 root 约 `0.96s`，但公网样本曾到 `16.28s`；按冻结的纯 `--max-time 20` 完整重验，第 1 个
  `umafans.run` 请求即在 `20.001s` 以 HTTP 000、0 bytes 超时，激活正式停止。
- 最终主机 load `0.39/0.57/0.61`、`MemAvailable≈1.76 GiB`、swap 未用，说明当前阻塞是公网入口/带宽与
  分布式 crawler 压力，不是内存不足。未开启 Phase 1、未启动专用 worker、未发出本轮 provider 请求。
  下一步需独立确认 Nginx UA block/429、CDN/WAF 或其他入口防护；在此之前新写入继续全关，不扩容制造通过。

## 2026-08-29 PR #116 已关闭态上线，Phase 2 因公网 crawler 饱和门禁停止

- PR `#116` merge revision `5863afaea0d28b520ce9e2448451c707e9ed3870` 已以隔离 release
  `/opt/umanews-release-5863afae-PR116-20260829T122308Z/umanewsbot` 和 image
  `sha256:4096114bf8d436b328a007234e92e6f582db3bc7db5e084182f92e05bb1d6ee1` 关闭态上线；migration
  no-op，leaf 仍精确为 `0075`。web/worker/Beat 同 revision/image，持久 runtime/TLS、Django check、
  双域名和队列门禁通过。
- 关闭态 zero-write audit 为 ready/valid/route drift 0，artifact 是
  `/opt/umanewsbot-builds/pr116-5863afae/race-data-activation/audit-closed-pr116-20260829T122740Z.json`，
  SHA-256 `f6ca01e…1da6`。Phase 1 重放 artifact 为
  `phase1-final-20260829T124120Z.json`，SHA-256 `c7c255e3…8692`：115 场全 blocked、0 provider 请求、
  0 DB delta，旧 `race_live=7543`。
- Phase 2 专用 worker 的 12 个样本均约 `123.3 MiB`；最低 `MemAvailable=1857056 kB`、
  `SwapFree=1310716 kB`，资源门禁通过，因此不扩容。但随后公网根页在 20 秒内无首字节，curl 以
  exit 28 失败，尚未派发本轮真实 discovery。
- 自动 trap 已恢复 10 个 data-sync 开关全 false、停止专用 worker并重建普通 worker/Beat。只读复核为
  `race_sync_v2=0 / race_live=7543`，站点随后恢复到约 1 秒、HTTP 200；主机
  `MemAvailable≈1.86 GiB`、swap 未使用。PR #115 失败遗留的保守 capacity ledger 1 request/2 MiB
  保留，未新增 enrollment/owner/claim/observation/revision。
- 失败窗口 20 分钟有 `1970` 次 Meta/Facebook crawler 请求；20:44–20:47 有 `340` 次 crawler、`341`
  次 `/races/`，当前 Gunicorn 只有 `2 workers × 2 threads`。crawler URL 反复含 `®ion=`/`Â®ion=`，而赛事
  日历旧逻辑会复制当前请求的全部 query 参数，导致畸形参数进入大量筛选链接并放大重查询。
- 最小修复保持 2+1 内存配置不变：畸形/未知 query 在任何日历 DB 查询前 301 到清洁 URL，筛选链接只复制
  规范化 allowlist 字段，非法地区归一为空。2 个新增测试通过；相关 82 项为 80 pass + 2 个
  `public_year` 日期 fixture 基线错误，后两项已在未修改 `origin/main@5863afae` 原样复现。该修复尚未
  合并或部署；生产继续全关，不从失败的 Phase 2 中间续跑。

## 2026-08-29 PR #115 已上线并在 Phase 2 transport allowlist 门禁止损

- PR `#115` merge revision `46911d56524f61ff4a50ad1c62ead46e77b1b021` 已以隔离 release
  `/opt/umanews-release-46911d56-PR115-20260829T102958Z/umanewsbot` 和 amd64 image
  `sha256:42aae312faab43fbc051f212a1e2448f7b21f558ef43f1872304582b01df0bc5` 上线；leaf 仍精确为
  `0075`，web/worker/Beat 同 image/revision，双域名 200，旧 image 有精确 rollback tag。
- 激活前 custom backup 为
  `/opt/umanewsbot/backups/db/pre-pr115-activation-20260829T104229Z.dump`，大小 `468585439` bytes、
  SHA-256 `0bbec2c477afaebf83691e2e2cbaa9ba6e9ae249fa1c894344ea906bff7b7746`、0600，
  `pg_restore --list` 为 1366 行；备份后磁盘仍高于冻结的 8 GiB 门槛。
- 空闲普通 Celery 子进程曾保留约 1.34 GiB RSS；确认 active/reserved/queue 全 0 后受控重启，
  `MemAvailable` 从约 605 MiB 回升到约 1.88 GiB。专用 worker 60 秒热身稳定约 123 MiB，最低
  `MemAvailable=1869636 kB`、swap 未动，因此本轮仍不扩容。
- PR #115 关闭态 audit 为 ready/valid/route drift 0，Phase 1 重放为 115 blocked、0 请求、0 业务变化。
  Phase 2 第一次真实 discovery 为 Celery `SUCCESS`，但业务为 `no_candidates /
  provider_response_invalid`：已确认代码生成 `racecards_identity_<region>_<day>`，固定 transport 却只
  allowlist `racecards_sync_<day>`，因此在 DNS/HTTP 前由 endpoint tuple 拒绝。
- 止损已把 10 个开关全部恢复 false、停止专用 worker并保持
  `celery=0 / race_sync_v2=0 / race_live=7543`。仅 capacity ledger 保守预留 1 request/2 MiB，
  共享 host budget 正常从 1050ms 收紧到 2000ms；enrollment/source identity/owner/claim/observation/revision
  均未新增。当前 hotfix 只补 6 个冻结 region × today/tomorrow 的精确 identity endpoint/URL 绑定，
  不放宽 host/path/query/redirect。

## 2026-08-29 五阶段激活在 Phase 2 host budget 门禁止损，hotfix 已通过回归

- 生产重开身份、leaf、writer、队列、资源和公网门禁后，已把冻结 capacity/allowlist 和
  standing/TRA/reference 三个精确摘要注入 `.env`。只读 `audit_race_data_sync` 为
  `configuration_status=ready / capacity=valid / route_drift=[] / would_write=false`；审计时所有运行开关仍为 false。
- Phase 1 仅开启 master/scheduler/future discovery、保持 network/apply/public 关闭。一次同步
  census 将 115 场全部明确分类为 blocked，provider 请求为 0，enrollment/owner/claim/ledger/
  observation/revision 前后不变，`race_live=7543`。
- Phase 2 专用 worker 热身约 123 MiB，60 秒最低 `MemAvailable=1823504 kB`、
  `SwapFree=1310716 kB`，因此当前无需扩容。真实 discovery 在第 0 个网络请求前被
  `host budget mismatch` 拒绝：生产共享行是 legacy 的 1050ms，新 data-sync 代码错误要求
  必须精确等于 2000ms。任务终态为 `SUCCESS/no_candidates`，`candidate_event_count=21 /
  request_count=0 / source_runtime_contract_rejected`。
- 止损已把 10 个 data-sync 开关全部恢复 false，停止专用 worker 并重建关闭态的
  普通 worker/Beat。最终 `celery=0 / race_sync_v2=0 / race_live=7543`，无 enrollment、
  data-sync owner、active claim、capacity ledger 或新 observation/revision。
- hotfix 将共享 host budget 定义为“只可单调收紧”：新消费者可原子把 1050ms 提高到
  2000ms，同步延长尚未到期的 `next_allowed_at`；legacy 路径接受不低于自身 1050ms
  的更严格共享值，仍拒绝更低值。data-sync SQLite `247/247`、PostgreSQL 16 `25/25`
  与 5 个直接回归已通过；扩大相关组的 2 个失败已在未修改 `origin/main` 上原样复现。

## 2026-08-29 生产 2+1 内存灰度通过，现有站点暂不扩容；新自动化仍关闭

- 只读拆账证明高占用主要来自常驻 Python 进程数，而不是 PostgreSQL/Redis：原 Web 为 3 个 Gunicorn
  worker，每个 PSS 约 188–190 MiB，cgroup 约 645 MiB；普通 Celery 为 2 个子进程，每个 PSS 约
  210 MiB，cgroup 约 503 MiB。PostgreSQL 已是 `shared_buffers=128MB / work_mem=4MB`，大部分 cgroup
  占用是可回收 file cache；Redis 仅约 27–30 MiB。OneBot 匿名内存约 161 MiB，其余也以 file cache
  为主，不是唯一根因。短时采样确认 Web/Celery 是稳定高基线而非分钟级泄漏。
- 经用户两次明确确认执行生产灰度：`.env` 从 `GUNICORN_WORKERS=3` 调为 `2`，普通 worker 从默认
  `CELERY_WORKER_CONCURRENCY=2` 调为显式 `1`。原 `.env` 以 0600 备份到
  `/opt/umanewsbot-builds/pr110-a063ecf9/memory-tuning/env-before-2plus1-20260829T0845Z`，SHA-256
  `434c2f98168944ea5aea16d5142a53b1484fc96b875c129685235078cb2c45e2`。
- Web 单容器 force-recreate 切换时产生 14 次短暂 5xx；新容器 healthy 后的稳定窗口 5xx=0，
  HTTP/HTTPS root/www 四入口持续 200。窗口内唯一 traceback 被精确分类为非法 Host 请求触发的
  `DisallowedHost`，不是并发、内存或 5xx 故障。切换损失如实保留，未来 Web sizing 变更应使用滚动容器
  或明确 maintenance window，不能把当前稳定态倒推成零中断。
- Celery 调整前先停 Beat，确认普通 queue/active/reserved/scheduled 全 0，再重建为 concurrency=1 并恢复
  Beat。15 分钟热身和三轮调度中普通队列峰值 22；两次大批分别约 4 分 17 秒、3 分 40 秒归零，最后
  5 条约 30 秒归零。最终 queue/active/reserved/scheduled 均为 0、worker pong、OOM=false、错误=0。
- 热身后 Web/worker 约为 `421 MiB / 292 MiB`；15 分钟观察窗最低 `MemAvailable=1662256 kB`，
  随后的繁忙窗口最低 `1639612 kB`，仍高于 1536 MiB 门槛；`SwapFree=1310716 kB` 全程未下降。
  现有常驻站点暂不需要
  扩容，但最终最小余量只有约 65 MiB，不能直接推断启动 384 MiB 上限的 `race_sync_v2_worker` 后也安全。
- 当前仍为 revision `a063ecf9…5fc8` / leaf `0075`，Web/worker/Beat 同 image 且 restart count=0，OneBot
  running/restart count=0；全部 10 个 data-sync 开关 false，专用 worker 未运行，
  `celery=0 / race_sync_v2=0 / race_live=7543`。冻结容量、future discovery、time/racecard、data-sync
  lifecycle、result public、correction 均未启用。下一步仍从 capacity admission 第一阶段重走；专用 worker
  启动后的内存、swap、队列或公网任一失败，才进入 8 GiB 扩容，不降低门槛。

## 2026-08-29 PR #110 已关闭态部署，0074/0075 成功；自动化因内存门禁保持关闭

- 最终生产 revision 为 `a063ecf985539fc2d82a27170c7d634e0f7e5fc8`，image 为
  `sha256:4a5f34b1e2bcc2b2568ef6749cfa0d7041e913ebcb1b8665ce312a3c787078eb`，隔离 release 为
  `/opt/umanews-release-a063ecf9-PR110-20260829T0608Z/umanewsbot`。web/worker/Beat 使用同一精确
  revision/image，web healthy、restart count=0；HTTP/HTTPS 的 root/www 四入口均为 200。
- 写前 custom backup 为
  `/opt/umanewsbot/backups/db/pre-pr110-a063ecf9-20260829T061324Z.dump`，大小 `485007018` bytes，
  SHA-256 `f3c1af55887a8f4026feffef078487b35606dcb9d3a2d3d6ab72409e5f0902b8`，权限 0600，
  `pg_restore --list` 产生 1332 行 TOC。旧 image 已固定为 rollback tag
  `umanewsbot:rollback-pre-a063ecf9-20260829T0616Z`。
- 受审 release orchestration 从 fresh leaf `0073` 运行，no-intent ensure 返回 `not-required`，随后正常应用
  `stable.0074_race_data_sync_r0_control_plane` 与
  `stable.0075_race_data_source_priority_and_reported_position`；completion 再次精确核验 leaf `0075`，
  没有创建 restricted recovery marker。迁移阻塞问题已修复并在生产闭环验证。
- 关闭态验收通过：新专用 worker 未运行，web/worker/Beat 的 10 个 data-sync 总开关、scheduler、network、
  future discovery、schedule/racecard/lifecycle/result/public/correction 开关均为 `false`；
  `celery=0 / race_sync_v2=0 / race_live=7543`。既有 lifecycle 的 6 个 enforce controls 未改动。
- 准备注入冻结容量时资源门禁失败：启用 1280 MiB 非持久 swap 后，临时停止 OneBot 并精确删除 6 个零容器
  引用旧候选镜像，磁盘恢复到约 8.8 GiB 可用，但 OneBot 停止期间 `MemAvailable` 仍从约 1535 MiB
  回落到约 1505 MiB，低于 1536 MiB 硬门槛。按 fail-closed 约定没有注入容量、没有运行 census、没有启动
  `race_sync_v2_worker`，五阶段自动化均未启用。
- 止损后原 OneBot 容器已恢复，running/restart count=0；最终快照 `MemAvailable=1355936 kB`、
  `SwapFree=1310716 kB`、磁盘可用 `9486413824` bytes。当前代码和 additive schema 保留在线，但所有新写入
  继续关闭。下一步只能先把宿主资源扩到恢复 OneBot 后仍稳定通过内存/磁盘门禁，再从 frozen capacity
  admission 重走 future discovery -> time/racecard -> lifecycle -> result apply/public -> correction；不得从
  中间阶段续跑。临时 swap 未写入 fstab，当前仍启用，停用/删除需另行执行。

## 2026-08-29 PR #109 已合并，tracked runtime follow-up 待发布，生产仍保持旧版本

- 首次准备 PR `#109` isolated release 时又安全停止：`runtime/horse_profile_completion` 含 Git tracked
  审核证据，整目录替换为 symlink 会污染 worktree 并可能阻断 rollback checkout。跟进修复保留该 tracked
  parent，只把 `cache/batches/review/budget` 四个运行态子目录指向稳定根；其他未跟踪 runtime 与 TLS
  仍使用整目录 compatibility symlink。生产没有创建 release/backup/migration，旧 Beat 已恢复。
- PR `#109` 已合并为 `69e87c446ad7a5f5494bb381b44cda2679e8ec8e`；它把 no-intent 语义改为
  “迁移前精确绑定 handoff artifact 中的受审起始 leaf”，允许
  `0071/0072/0073/0074/0075` 这些已审核普通发布终态；live leaf 与 artifact 漂移或出现未审核 leaf
  仍立即拒绝。迁移后的 completion 继续只接受最终 `0075`，没有放宽 restricted recovery marker、
  database identity、catalog 或 migration-history 校验。
- 新增真实 PostgreSQL 16 回归已证明 `0073 -> ensure(not-required) -> migrate 0074/0075 ->
  complete(not-required)` 全链成功且不会创建 recovery marker；migration-history PostgreSQL 套件
  `11/11`、非 PostgreSQL 修复套件 `78/78`（另 1 项按环境跳过）通过。
- 隔离 release 的可变 runtime 与 TLS 已改为 `.env` 中唯一、绝对的
  `UMANEWS_PERSISTENT_RUNTIME_ROOT` / `UMANEWS_TLS_CERT_ROOT`。发布在 build/停服前核对稳定目录、
  rollback compatibility path、证书 realpath 不逃逸及 `nginx -t`；缺失、相对、重复、空目录或
  symlink 逃逸均 fail closed。含 tracked runtime follow-up 的完整 single-migration-owner/发布编排套件
  `178/178`，另 2 项按环境跳过。
- 当前尚未构建新生产镜像、创建本次新鲜备份或重试 migration。生产仍为 revision `2833558a…56c` /
  leaf `0073`，新写入关闭。资源门禁发现无 swap 且内存不足后，经用户明确授权创建并启用 1280 MiB、
  0600、非 fstab swap；旧 Beat drain 后重启 worker/web，门禁恢复为 `MemAvailable≈1.81 GiB / SwapFree≈1.25 GiB`，
  公网 200，随后因 tracked runtime 门禁停止并恢复旧 Beat。当前
  `celery=0 / race_sync_v2=0 / race_live=7543` 的最后确认基线不变；上线前必须重新实时核验。

## 2026-08-29 PR #108 已合并，但普通 0073 -> 0075 发布被 recovery-intent 门禁安全阻断

- PR `#108` 已合并，merge revision 为 `e5287acfc7dca8b6a1e7d01e3c3f89e0b945af5d`，tree
  `4313b521091eb1d0241d70d11cfd624fe4cba0e2`，source archive SHA-256
  `6866b3d6a86b312de4bd219644727ad2f3afdd9db725c88a1fe34bb81bc9a277`。精确候选镜像为
  `sha256:7403b21f2651304893f0309f94eeda4b0f19f1716c4316b73d90f751962afdd1`，已保留为
  `umanewsbot:failed-gate-pr108-e5287acf`，没有成为常驻生产镜像。
- 写前 custom backup 为
  `/opt/umanewsbot/backups/db/pre-pr108-merge-e5287acf-20260828T200920Z.dump`，大小
  `484317721` bytes，SHA-256
  `f88abd1358ed51be0d03e83eb8a87ca091e952f15808d31daa2feac3e27ac1f0`，权限 0600，
  `pg_restore --list` 产生 1325 行 TOC。备份后可用空间 `10810208256` bytes，高于 8 GiB 门禁。
- Release-B 候选 preflight 已绑定旧生产 leaf `0073`、零 writer、精确 DB/image/commit，随后在
  `migrate` 之前由 `ensure_historical_calendar_recovery_intent` 拒绝，错误为
  `no-intent attempt requires exact final 0071`。实际代码常量已是最终 leaf `0075`；问题是
  `attempt_mode=not-required` 分支在 migration 前错误要求 live leaf 已等于最终 leaf，因而合法的
  `0073 -> 0074 -> 0075` 普通发布无法进入 `migrate`。
- 失败点发生在 migration 前；生产数据库确认 `0074/0075` 应用记录均为 0，也没有 active restricted
  recovery marker。按 fail-closed 约定停止后续步骤，未注入冻结容量、未启动 `race_sync_v2_worker`，
  future discovery、schedule/racecard、data-sync lifecycle、result public、correction 均未启用。
- 已把 `umanewsbot:prod` 恢复为精确旧 image
  `sha256:4bc392d012080a482523451016074f55ebcee84177ccab08b7563b233411a611`，并通过受审
  `resume_stopped_release.sh` 恢复 web/worker/Beat。首次从新 release 目录恢复 Nginx 时，因该目录
  `deploy/certs` 只有仓库 README、没有旧 release 的 Let’s Encrypt runtime，Nginx 报缺
  `fullchain.pem`；同时发现 web/worker 的历史 runtime bind 仍指向新目录。随后停 Beat，等待两条普通
  新闻任务自然 drain，再从原 PR107 release 目录重建 web/worker/Beat/Nginx。四服务 working directory、
  runtime mount 和旧镜像现均回到原基线，HTTP/HTTPS 四入口全部 200。
- 当前生产最终态仍为 revision `2833558a6a2d67b7dc9816b53ea8ad5d580eb56c` / leaf `0073`；
  web healthy，worker/Beat/Nginx 运行且 restart count 为 0，近两分钟四服务 error marker 为 0；writer
  preflight `ok=true`，`celery=0`、`race_sync_v2=0`、旧 `race_live=7543`，新写入总开关和旧
  race-live scheduler/monitor 均关闭。
- 下次重试必须先以独立修复 PR：区分 no-intent 的“迁移前受审起始 leaf”和“迁移后最终 leaf”，增加真实
  PostgreSQL `0073 -> 0075` 全 wrapper 测试，并把 TLS runtime 改为 release 外稳定挂载或在切换前做
  精确证书 preflight。修复重新审查后仍需新鲜备份和完整生产门禁；不得复用本次最终确认绕过新门禁。

## 2026-08-29 PR #108 历史 claim 已在关闭态精确收口，待最终 merge/deploy/enable 确认

- PR `#108` 仍为 OPEN，生产仍运行 revision `2833558a6a2d67b7dc9816b53ea8ad5d580eb56c` / image
  `sha256:4bc392d0…611a611` / migration leaf `0073`；新赛事写入开关均关闭，
  `race_sync_v2=0`，旧 `race_live=7543` 未清理、迁移或消费。本记录所在候选尚未合并；未执行
  `0074/0075`、服务镜像切换或新自动化启用。既有 lifecycle 保持此前生产状态
  `RACE_EVENT_LIFECYCLE_ENABLED=true / mode=enforce / 6 controls`，本次未改动。
- 14 条过期 `claimed` 的根因修复保持三层边界：prepare exception 按原 token 终态化；
  每 5 分钟 sweeper 只收口过期且严格空证据 claim；历史命令使用 canonical manifest SHA、
  PostgreSQL advisory transaction lock 和全集合重算，任一活跃、畸形、证据存在或
  eligibility 漂移都整批零写。收口不会生成 bundle、delivery、赛果或队列消息。
- 全 PR 独立审查返回的 6 个 P1 + 7 个 P2 已逐项修复：Release-B 最终 leaf/rollback
  已顺接 `0075`；migration 不再把内部排序猜成对外名次；data-sync 赛果使用独立公开
  读取合同；开关打开后可 promotion 既有 shadow revision，并重处理先前只因门禁关闭而
  rejected 的同一 observation；TRA 执行器必须使用 enrollment 的 exact source/route。
- shared snapshot 新增 8 天 retention（覆盖 T+7 更正窗口）与有界清理，清理任务只路由到
  `race_sync_v2`，因此能看到专用 artifact mount，不会交给普通 worker 或旧 `race_live`。取消赛事
  停止 result polling，延期赛事不再沿用旧时间轮询赛果，终态 lifecycle 不再每分钟重选；
  T+30 告警已排除取消/延期、不被既有 open incident 饿死，赛果确认后自动解除。
- 最终增量还补齐三条直接边界：future discovery 与 artifact cleanup 均先核对总开关
  `RACE_DATA_SYNC_ENABLED`；snapshot waiter 的最小 jitter 也必然跨过 120 秒 lease；赛事公开批量读取
  预载 exact source，避免逐场 N+1。对应测试已固化，完整 diff 独立复审结论为 `No findings`。
- 当前发布门禁：SQLite/发布组合一次发现 `539` 项，其中 `535` 通过、`3` 跳过，唯一错误是基础
  image 缺少 `git`；在同版本、可读取 worktree 元数据的 Git-capable 容器中精确重跑该项为 `1/1`，
  因而实际断言为 `536` 通过、`3` 环境跳过。部署/回滚合同另为 `42/42`；PostgreSQL
  migration/history/catalog/fault-injection `27/27`，R0 + Pipeline A 并发/CAS `24/24`，历史 claim
  并发锁另 `4/4`。Django check、migration drift、compileall、Shell syntax、三份 Compose、secret
  pattern scan 与 `git diff --check` 全绿。
- 关闭态生产修复使用候选 `dd67c78902182e52123d5e2d4d2919aa2c348aa0` / image
  `sha256:8114325bcc6b4dc8ef814516ba82fc64b309942561bec85f806b7d2cd44d8620`。停 Beat 后 exact preview
  仍是 14 eligible / 0 blocker，manifest `5897db0d…76d1a5`；写前 custom backup
  `pre-pr108-claim-reconcile-dd67c789-20260828T1938Z.dump` 为 `484192137` bytes、SHA-256
  `64d72011245c60d359cada8998bb04decaab58ca8a15071a5a4b64eb09a44bdc`、0600 且 TOC 有效。
- exact apply 后 14 行只转为 `failed/stale_claim_reconciled`，claimed 为 0；cursor 保持，selector/bundle
  仍空，pending/delivery/approval/赛事赛果及 OperationLog 相关计数都未变。两条新/普通队列仍为 0，
  旧 `race_live=7543`；旧 Beat 已以原 image 恢复。独立 verifier、三个公网 200 与近 10 分钟三服务
  错误计数 0 均通过，证据位于
  `/opt/umanewsbot-builds/pr108-dd67c789-claim-reconcile-evidence`。
- 下一步只请求一次绑定最终 PR head 与关闭态候选证据的 merge/deploy/enable 确认；确认后才允许合并、
  构建 exact merge image、应用 `0074/0075` 并按 frozen capacity 逐级启用。任一门禁失败立即停止并
  保持新写入关闭。

## 2026-08-28 PR #108 生产发布在 writer 静默门禁安全停止

- 用户已确认合并并部署 PR `#108`，但合并前生产检查发现宿主机一度处于约 `100 MiB`
  `MemAvailable`、无 swap、I/O PSI `full` 约 80% 的故障态；公网首页曾超时。PR 仍保持 OPEN，未执行
  备份、`0074/0075`、镜像切换或任何新赛事写入。
- 故障检查确认普通 `celery` 与 Redis `unacked` 已排空，两个 pool 子进程均为空闲管道读取；仅对旧普通
  worker 做受控 TERM，由 `restart: unless-stopped` 拉起。可用内存恢复至约 `1.2–1.5 GiB`，I/O PSI
  `avg10` 回落接近 0，公网 health/home/races/admin 均恢复 200。该恢复未触碰 Beat 以外的发布控制面、
  `race_sync_v2` 或旧 `race_live` 消息。
- 发布冻结后，Celery active/reserved/scheduled、普通队列和 external import/historical/horse P0 writer 均为
  0，但 `RaceResultReviewRun(status="claimed")=14`，触发硬门禁。记录 ID 范围为 `69–89`，UTC 创建/
  更新时间分布在 `2026-08-17T22:30` 至 `2026-08-27T22:30`，且更新时间与创建时间一致；未擅自清理、
  完成或改写这些 claim。
- 已立即停止发布并恢复冻结前运行的旧 Beat。最终复核五个旧/新赛事写入开关均为 `false`，
  `race_sync_v2=0`、旧 `race_live=7543`，web/worker/Beat/db/redis/nginx/onebot 均在线。下一步必须先对
  14 条 claimed review 做单独、受审的生产状态核验与精确收口；门禁回到 0 后才能重新取得发布窗口并从
  PR 合并前检查重新开始。
- 代码根因是 `run_scheduled_prepare()` 只在 prepare 正常返回后 CAS 写终态；prepare 异常会让 run 永久停在
  `claimed`。旧 catch-up 仅处理缺失 slot，不会终态化这些既有行。14 行均已确认租约过期、cursor 只有
  claim token、selector/bundle/terminal/finished 为空，但该形态仍须按异常处理，不能降低 writer 门禁。
- 当前 worktree 已新增三层防复发：prepare exception 由原 token 写 `failed/prepare_exception`；每 5 分钟
  sweeper 仅收口严格空证据的过期 claim；历史命令要求 preview canonical manifest SHA，并在单事务锁住
  全部 claimed 行重算，任一活跃/畸形/漂移即整批零写。收口不生成 bundle、delivery 或赛果投影。
- 变更聚焦验证为 SQLite 232/232、PostgreSQL 28/28；Django check、migration drift、compileall、三份
  Compose、diff 与 secret scan 通过。额外扩展套件的 9 failures/2 errors 已在原 PR head 对应模块逐项
  复现，不是本补丁引入。当前尚未 commit/push、未写生产；下一步是全 PR 独立复审，再创建已验证备份并
  精确收口 14 行，最后只为合并部署请求一次确认。
- 首轮独立补丁 review 的 2 P1 + 1 P2 已处理：历史修复授权已按用户当前明确指令写回；failed slot retry
  会清空旧 attempt terminal 字段；固定 PostgreSQL advisory transaction lock 串行化 manifest apply 与新
  claim 创建；manifest SHA 同时绑定 eligibility，避免 preview 后 lease 跨过期边界而静默改变 apply 范围。
  新增重试、eligibility drift 与真实 phantom-claim 并发测试已纳入上述 232/28。

## 2026-08-20 赛事数据自动同步 R0 已通过独立代码评审，保持默认关闭

- 已在干净 worktree `/Users/mentianlu/.codex/worktrees/implement-race-data-lifecycle-sync/umanews` 和独立分支
  `codex/implement-race-data-lifecycle-sync` 开始实现；未复用方案 worktree，也未改动共享主工作区。
- 新增 migration `stable.0074_race_data_sync_r0_control_plane`：projection writer 增加独立 `data_sync`
  owner；新增 manifest-bound enrollment、逐 provider/data-kind checkpoint 和持久 snapshot single-flight
  lease；来源稳定身份补充 `region_code + identity_namespace` 唯一边界。历史 `live` owner 不自动迁移，
  无法从既有 identity 字段确定性 adoption 的来源会关闭 automation 并标记 review required。
- Slice A 继续作为唯一 `RACE_DATA_SYNC_*` roster/flag/reconciliation 命名空间。新增每分钟 selector、
  `race_sync_v2` 专用队列/worker、父 claim/generation/checkpoint CAS、限时 enrollment manifest、99 场 census
  合同和 legacy `live -> data_sync` 的关闭 runtime + 双队列 drain + 精确 projection baseline 转移入口。
  未审计 host/path/request budget 的 route 即使 adapter 已存在也不可解析为自动化 route。
- 首轮独立代码 review 结论为 `REVISE`（0 blocker、6 high、3 medium）。第二轮限定复核继续发现并已修复
  legacy transfer 独立信任根/审批时序、catalog exact CHECK、全局 optional-row/checkpoint 锁序、snapshot
  过期 owner CAS 和 pre-contract sibling intent 等直接缺口。当前已把 enrollment/census/apply/
  claim/legacy transfer 全部绑定到 Slice A 当前唯一 roster 的 registry/contract/proof/host/path/budget；route
  不存在或 digest 漂移逐场零写。全局 event -> projection -> tracking -> enrollment/checkpoint 锁序已覆盖
  failure×rotate、failure×disenroll 与事务 abort 的真实 PostgreSQL 并发测试。
- snapshot single-flight key 由 provider/region/scope/data-kind/registry 五元组规范生成；`COMPLETE` 仅缓存
  150 秒，过期或损坏由单一 CAS takeover；原 owner 在 lease 到期边界后即使尚未被 takeover 也不得 publish/
  fail。legacy `live -> data_sync` 只接受配置中 raw SHA 绑定的独立 approval 文件，并逐字绑定 canonical
  transfer manifest 与 runtime receipt；审批必须发生在 manifest 生成之后，apply 同时复核当前 runtime 关闭、
  双队列 drain 与 event baseline，不再信任调用者布尔值或自签 SHA。
- enrollment 已补 exact reverse manifest：绑定当前 event/source/route/owner/enrollment snapshot 后只停止
  tracking/checkpoint 并释放 `data_sync` owner，不删除来源、observation/revision/audit；baseline 漂移逐场零写。
  每小时 future discovery 在 `race_sync_v2` 隔离队列加载 raw SHA 绑定的 standing policy，生成全量 census 和
  最多 20 场限时 proposal，当前保持只读，不自动 apply。
- 容量键已与批准方案统一为 `RACE_DATA_RAW_*`，默认全部为 `0`。在 G2 基于生产磁盘/约 45GB 备份完成 sizing
  proof 前，误开 network 会在 provider 执行前以 `artifact_capacity_config_invalid` 释放精确 claim；纯
  admission 已覆盖 payload、provider/region 日预算、high/low water、min-free、hold 与 cleanup failure。
- application/manual/resume/rollback/immutable-control 发布入口现已单独 probe、drain、stop、冻结并恢复
  `race_sync_v2_worker`。回滚目标代码若没有该 service，不会把新 worker 恢复到旧镜像；普通 B-to-B
  rollback schema 合同顺接到 `0074`，pre-0074 恢复仍是单独受审的跨 schema 流程。
- `0074` catalog guard 现核对精确 type/nullability/default、状态集合、generation 与 state-shape CHECK，且有
  PostgreSQL 故障注入证明 wrong type、DROP NOT NULL、错误 default、`CHECK(TRUE)`/`OR TRUE` 都会拒绝发布。
  migration SHA 已冻结为 `21670e7731456a33e473fd97cb43ca72545477aa600ea594c6c071c4dd2d54eb`。
  pre-contract rollback intent 新增 `pre-switch/switching/image-switched` phase；resume 同时核对 race-live/
  data-sync 两个 trusted sibling marker，任一可信 `switching` 或两者 action/phase 不一致均保留 intent 并拒绝
  自动猜测。切镜像前退出会恢复旧 sync worker。非法非数字容量配置只关闭 provider admission，不再让
  Django settings import 崩溃；生产/low-cost sync worker 不挂载可写 media volume。
- 所有新 runtime/network/schedule/racecard/result/public/correction 开关默认关闭；provider worker 当前在
  network 关闭或执行器未实现时只按精确 claim fail closed 并重排，不会抓取来源或写赛事字段。真实 provider
  transport、future proposal artifact persistence/运行中自动 apply、Celery worker 真实集成、生产文件系统
  容量/低磁盘故障注入、R1–R4 的跨写路径 PostgreSQL 锁图均尚未完成，因此当前代码不具备生产启用条件。
- 本地本轮验证已通过 `566` 项：R0 SQLite `41/41`、R0 PostgreSQL 并发 `12/12`、PostgreSQL
  migration-history/catalog/fault-injection `26/26`、SQLite migration-history `75/75`、single-owner/release/
  rollback `170/170`，以及 Slice A/lifecycle/race-live/发布 hardening 邻接 `242/242`；另 2 项按测试环境跳过。
  Django check、migration drift、三份 Compose 结构、shell syntax、Python compile、secret pattern scan 与
  `git diff --check` 均通过。同一独立 reviewer 最终复核为 0 blocker/high/medium/low，`VERDICT: APPROVED`；
  该结论只批准 R0 默认关闭代码候选，不授权联网、migration、部署或生产启用。未执行生产网络、生产
  migration、配置启用、服务重启、push、PR 或部署。

## 2026-08-20 赛事数据自动同步方案已通过同一独立 reviewer 第 3 轮评审

- 同一独立只读 reviewer 首轮结论为 `REVISE`：0 blocker、8 high、3 medium、1 low；没有修改仓库文件。
  findings 主要是遗漏主干既有 race-data Slice A、跨 lifecycle/race-live 锁序相反、缺少存量/未来赛事
  enrollment、R4 result/lifecycle 授权接口未闭合、新 worker 未纳入 release freeze/resume/rollback、来源
  identity 唯一键不足、可信第三方 dead heat 展示错误、T+30 指标可被 alert 伪装，以及 live state、
  single-flight、artifact capacity 三项边界不完整。
- 本轮只修订 `docs/changes/automate-race-data-lifecycle-sync/`：确定 Slice A 与 `RACE_DATA_SYNC_*` 为唯一
  roster/reconciliation/admission 内核，`race_sync_v2` 只作为隔离队列/worker 名；新增 99 场完整 census、
  standing-policy future enrollment/disenrollment、全局锁图、唯一 result+lifecycle transaction API、
  region/namespace identity、authority-neutral reported position、DB single-flight、容量 admission 和完整
  release-control-plane 合同。
- 同一 reviewer 第 2 轮确认首轮其余项目已闭合，但仍以 `REVISE` 指出 3 high + 1 medium：缺少新 writer
  的持久 owner、保留的 Slice A racecard writer 仍是 observation -> event 逆序、result worker 没有取得
  lifecycle claim 的可执行路径、R3 shadow revision 与 R4 公开事务可能重复建 revision。第 2 轮修订新增
  `RaceEventProjectionWriteOwner.DATA_SYNC` 与完整 CAS/legacy transfer truth table；把 Slice A reconciler 纳入
  全局 lock coordinator 和 racecard 交叉并发 RED；改为 R4 API 在唯一 transaction 内 evidence-driven 取得/
  释放 lifecycle claim；并冻结“R3 唯一创建 immutable unpublished shadow revision、R4 只 promote”的合同。
- 同一 reviewer 第 3 轮只读复核上述 3 high + 1 medium，确认全部闭合、未引入新矛盾、无 actionable
  findings，最终结论为 `VERDICT: APPROVED`。残余风险仅属于尚未开始的实现阶段：migration、旧代码
  fail-closed、PostgreSQL concurrency RED 与 evidence-driven claim 仍需真实实现、测试和独立代码 review。
- 已冻结五份方案文件的 fingerprint：按 `spec/design/test_cases/tasks/rollout` 顺序生成逐文件 SHA-256 行，
  再对这些行计算 SHA-256，结果为 `f5d13c7ce92f21773d13230d39fdab88740815e63c2cbc1e6a609fbc04076940`。
- T+30 验收已拆为 independent upstream terminal availability、terminal detection、confirmed publication、
  blocked alert coverage；alert 不再计入结果成功。canary 对上游确实可用的赛果要求 >=95% confirmed/public，
  地区扩大后 >=99%，错误赛果为 0。
- 该段记录的是方案冻结时状态；实现已在上方独立分支进入 R0，但方案评审仍不构成真实来源网络、生产写入、
  migration、部署或启用授权。

## 2026-08-19 已创建赛事时间、出马表与赛果自动同步原生方案，尚未实现

- 已按用户要求在独立 worktree/branch `codex/race-data-automation-plan` 创建
  `docs/changes/automate-race-data-lifecycle-sync/`，使用仓库原生 `spec/design/test_cases/tasks/rollout`
  文档，不使用 OpenSpec，也未生成 OpenSpec 产物。
- 方案基线为当前 `origin/main@2833558a6a2d67b7dc9816b53ea8ad5d580eb56c`，复用现有
  `RaceEventLiveTracking`、observation/revision、字段审计、lifecycle 和定时人工赛果审核；新增建议为
  provider checkpoint、每分钟动态 selector、独立 `race_sync_v2` 队列/worker，以及时间、出马表、
  confirmed/corrected 赛果的原子协调。
- `2026-08-19 23:24 +08:00` 生产只读快照确认运行 revision 同为 `2833558a`，web/普通 worker/Beat
  正常；未来 30 天 `99` 场 published/scheduled 赛事仅 `8` 场有 `race_datetime`、`99` 场均无 runner。
  race-data/race-live/lifecycle 自动写入全关，赛果审核 prepare 开启但不会自动 apply；普通队列为 `0`，
  遗留 `race_live` 队列仍为 `7543`，本方案明确禁止清理、重放或复用该积压。
- 方案沿用“官网、Racing API、可信第三方在合同与完整性门槛满足时同等自动采用”的产品口径，但
  强制区分 `official`、`racing_api_auto`、`trusted_provider_auto` 和
  `human_reviewed_reference` provenance；不同同资格来源冲突时 fail closed，不按抓取先后覆盖。
- 30 分钟目标拆为两只可观测时钟：T+30 必须有 confirmed result 或明确 reason-code 告警；首次发现
  上游完整终态后 P95 5 分钟、P99 10 分钟内完成公开更新。上游未发布终态时不得伪造赛果。
- 当前没有应用代码、migration、provider 网络、生产数据写入、配置变更、队列消费、commit、push、
  PR、部署或服务重启。下一门禁是独立工程方案评审；评审通过也不代表已获生产自动写入或公开授权。

## 2026-08-17 York 8 场时间已补齐；lifecycle census 已产生可执行 enrollment 计划

- York Racecourse 官方 Order of Runnings 已用于补齐 event `946–953` 的英国当地开赛时间与 UTC
  `race_datetime`；manifest SHA-256 为 `0b89c6c9…f24a`。8 场共写入 `16` 项赛事字段，并留下
  `16` 条 authority、`16` 条 field change 和 `1` 条 operation log；赛事仍为 published/scheduled。
- 写前 custom-format 备份为 `445791728` bytes、mode `0600`、TOC `1332`、SHA-256
  `62770ed9…1111`。8 个公开详情页、赛事日历、内外 healthz 均为 `200`，页面显示时间与官方赛程一致。
- 更新后的 7 天 lifecycle census 为 `9867 inspected / 8 included / 8 enrollment_required / 1 batch`，
  included IDs 精确为 `946–953`；四张 lifecycle 表前后指纹同为 `28c51899…6b82`。lifecycle 继续
  `false/off`，race-live 关闭，尚未 apply enrollment、生成 registry 或启用 enforce。
- 运维只读盘点发现：生产 `.env` 的 OSS endpoint 无法解析，标准香港 endpoint 可访问但目标 bucket
  当前为 `0 objects`；本地备份约 `45GB`，因此禁止清理。Nginx 生产挂载配置 syntax 正常、SHA
  `a506e857…b9c`，仓库原先仍是旧 HTTP 模板。
- 干净 worktree 已测试先行准备备份/恢复/OSS/Nginx 收口。独立 reviewer 首轮指出 RDS 模式隐式回退、
  low-cost 未绑定实际 Compose project、RDS promotion 调用不存在 db service 三项 P1；均已新增承重
  RED 后修复，backup/restore 脚本 executable mode 也已锁定。备份/Nginx 16 项、含 lifecycle operations
  与 single-owner 的组合 `195/195` GREEN；Django/migration/workflow/shell/diff 检查通过。同一独立
  reviewer 第 2 轮复审结论为 `APPROVED`、无直接 P0/P1，审前后代码候选 fingerprint 均为
  `720e872ff30d19fb93d485859f6c0be886b84059b56b574c05c0c405f150092a`。当前尚未 commit、PR、合并或
  部署。详情见
  `docs/changes/lifecycle-enforce-full-cohort/race_datetime_york_report_20260817.md` 与
  `docs/changes/harden-production-backup-and-nginx-config/`。

## 2026-08-17 lifecycle G2 已完成关闭态发布、legacy 收口与只读 census

- PR `#105` merge SHA `93cfd240b9ba7e95caf79bf54e9c6d089885f11c` 已部署到隔离 release；生产 image
  `sha256:06885466…85904`，migration leaf `0073`、plan `0`，web/worker/Beat 与内外 health 正常。
  lifecycle 保持 `false/off`、运行信任根为空，race-live 关闭且 worker 未启动。
- fresh backup SHA-256 为 `e6741b7a…7893`（custom format、`445635636` bytes、TOC `1325`），旧 image
  已冻结为 `umanewsbot:rollback-pre-pr105-20260817`。生产 HTTPS Nginx 配置继续保全为
  `a506e857…b9c`；它仍是隔离 release 唯一 tracked 偏差，后续须单独安全归档入库。
- event `186/187` 在共享锁和 worker 自然排空后首次 disarm 返回 `disarmed`，第二次返回 `replay`；
  mid/after evidence SHA 同为 `82ce3b17…a14cb`，赛事状态与 transition 未变，control 收口为 inactive。
- 最终生产只读 7 天 census 检查 `9867` 场，返回 `no_candidates`；未生成 registry，promotion dry-run
  不适用。四张 lifecycle 表前后指纹同为 `dc6643fa…9b84`，未发生数据库写入。完整证据见
  `docs/changes/lifecycle-enforce-full-cohort/g2_release_report_20260817.md`。

## 2026-08-17 lifecycle G2 两项关闭态阻塞已通过独立 review，待发布

- 生产运行 revision 仍为 `0f3391a9…31ea6`，migration leaf 为 `0073`、plan 为空；web/worker/Beat 与
  healthz 正常，lifecycle 为 `false/off`、race-live 关闭。旧 186/187 canary evidence 仍为 active，
  但运行态无授权，最近一次 disarm 因 event 187 历史 direct-finish 单边而零写拒绝并完整恢复服务。
- 生产 7 天只读 census 已证明窗口内 `race_datetime` 赛事为 0；lifecycle control/transition/registry/
  membership 前后指纹一致，但 prepare 把正常空集合误报为“event IDs 必须非空”。
- 候选修复测试先行：只允许精确 historical direct-finish 在显式 false/off disarm 中通过，普通 reactivate
  仍拒绝；空 census 返回 `status=no_candidates`。首轮独立 review 的 activation ID 绑定 P1 与空集合输入
  校验 P2 均已补真实 RED 并转绿。第二轮 review 发现 direct-finish 首次 disarm 后无法幂等重放；现已锁定
  “首次严格绑定 active activation ID、成功收口后同 artifact 返回 `replay` 且零写”的合同并转绿。
  聚焦回归合计 `143/143`（8 skip），Django check 与 migration drift 均通过。未参与实现的同一 reviewer
  第 3 轮限定复审结论为 `APPROVED`；原生只读 review exit 0、审前后代码候选 fingerprint 均为
  `c0b0282fe129a02ebc79624e0eb3d9ce643cb3f46923b7c98ac7f9eea885d986`。尚未提交或部署。

## 2026-08-16 G2 关闭态部署完成；旧 canary 因 runtime 过期暂未 disarm

- PR `#103` merge SHA `231514eac6d52d002319abdba23e231c2560ee25` 已通过标准唯一 release owner
  完成关闭态部署；`0073` migrate 为 no-op，catalog/completion gate 通过，web/worker/Beat 同一 image
  `sha256:dd5e1f3b52e255b7823624a51ac4013b38f174a232250290dd4afa743f60b363`，lifecycle 保持
  `false/off`，race-live 关闭且未运行，内外 healthz 正常。
- 旧 event `186/187` canary disarm 在共享锁、Beat/worker 静默后被 `canary runtime 已过期` 门禁拒绝；
  恢复 trap 已重新启动 worker/Beat，数据库 evidence 仍为 active，未发生部分写入。因此生产 census/dry-run
  尚未执行。
- 当前最小修复 `codex/fix-expired-canary-disarm` 只允许 verify 命令在同时带 `--disarm` 时加载过期 manifest；
  mutation 层仍要求严格 `false/off` 并完整核对 frozen cohort。普通 verify、activate 和 enforce 路径继续拒绝
  过期 trust root。已取得真实 RED，聚焦 application 测试 `11/11` GREEN，等待独立 review。

## 2026-08-16 G2 在 0073 发布合同校验处安全停止并恢复 false/off 服务

- PR `#102` 已合并；生产在共享锁内完成 writer 静默和备份后，由唯一 release owner 成功应用
  `stable.0073_lifecycle_enforce_registry`。随后完成校验仍把最终叶节点固定为 `0072`，因此部署按合同失败，
  没有把失败误报为成功。现有 web/worker/Beat 已恢复服务且保持 lifecycle `false/off`，race-live 关闭。
- 一次性受审事务已将过期的 `RaceResultReviewRun 65/66` 精确收口为 `noop`，reason code
  `stale_claim_reconciled`；事务 before/after 与备份证据已冻结。该修复未触及其他业务行。
- 当前小型修复 `codex/fix-0073-release-contract` 通过真实 RED 后，将 ordinary/initial-install/rollback
  migration 合同顺接到 `0073`，并为两个新表、FK、唯一约束及关键索引增加 PostgreSQL catalog 校验。
  首轮独立 review 为 `REVISE`，3 项 finding 已修复，等待同一 reviewer 复审；复审通过前不再次部署。

## 2026-08-11 生命周期 full-cohort 实现通过最终独立复审

- event `186` 已在生产双赛事 canary 下真实完成 `scheduled -> running -> finished`：T 与 T+30 各一条
  applied transition，范围外 applied 为 `0`，公开详情和日历均显示“赛果待确认”。这证明当前双赛事路径
  可用，但不等于通用全量能力已经上线；生产仍是 `186,187` canary，race-live 关闭。
- clean worktree `codex/lifecycle-enforce-full-cohort` 基于 `origin/main@4097e386` 实现数据库 registry、逐场
  membership、`0073` migration、严格 selector/census、每批最多 100 场的可恢复 promotion、唯一 active
  activation、shared-advisory-lock 轮换屏障、O(1) 单场授权，以及 legacy canary 兼容和新 mode switch。
- 测试先行初始为 15 failures + 1 PostgreSQL-only skip；独立 reviewer 与原生只读 review 随后均给出
  `REVISE`。已修复漏掉缺 control 赛事、ID canonical 顺序、旧 root 竞态、predecessor 差集清退、active
  retry、membership/count 绑定、Beat stopped admission、备份前静默 writers 和 100 场批次等 findings。
- 当前主线程验证：SQLite 新旧 lifecycle 回归 `135/135`（另 2 项 PostgreSQL-only 正常跳过）；隔离
  PostgreSQL 16 并发/行锁回归 `14/14`；Django check、migration drift、shell syntax、single-owner ownership
  和 `git diff --check` 均通过。`origin/main` 自身 deploy one-off inventory 对两个既有 resume 脚本的失败已在
  干净主干复现，不属于本 change。
- 第 2–4 轮复审继续发现并已修复：可消费的缺-control enrollment plan（含美国逐场时区 allowlist）、完整 cohort dry-run、scanner shared
  rotation barrier、active membership `PROTECT`、失败恢复保留锁、严格 predecessor/stage proof、固定 20/100
  灰度上限、已推进赛事的 active verify/replay、完整运行四元根、首代/后继 disarm 分支和 running predecessor
  rotation。最终限定独立复审与 Codex 原生只读 review 均为 `APPROVED`，稳定 fingerprint 为
  `9d2cb55d6125310e114e381cc91359eae5b06f695136059bad2e2e1cc0c871c8`。当前仍未 commit、push、PR、
  合并、部署、执行 `0073` 或修改生产 registry/control/env。下一步是创建 Draft PR 并提交 G2 发布包，
  生产仍须先 false/off 关闭态部署、只读 census/dry-run，再按独立 G3 分档启用。

## 2026-08-10 PR #98 已闭锁部署；全新 candidate/artifact 等待精确 G3

- PR `#98` 已按精确 merge SHA `127d4833da89e4a8f6b1b9a93bbaec1e65119528` 部署到独立 release
  `/opt/umanews-release-127d4833-PR98-20260810/umanewsbot`；web/worker/beat 统一 image 为
  `sha256:37f84597d96a59d48b0e18f567eda399a8bce6bcd1e05241fdb46e6633838852`。Release B preflight SHA
  `f20aaa156cf0b0fa0cda193e8bb071453e6e7a148fe8a136c376a8cb496f896e`，migration no-op/leaf `0072`、
  Django、容器 revision、内外 HTTP、writer/lock、日志与高风险开关关闭 verifier 均通过。
- fresh 代码部署备份为 `/opt/umanewsbot/backups/db/pre-pr98-race-fact-normalization-20260810T115900Z.dump`，
  `420593131` bytes、mode `0600`、TOC `1308`、SHA-256
  `793c51ad6625852eb98cf194c182554da3a3b8768be8830e0638d84414e10ff8`；旧 image 保留为
  `umanewsbot:rollback-pre-pr98-20260810`。部署排空观察到常规新闻 crawl `active=2→1→0`，未强杀任务；
  `race_live_worker` 与 7543 条关闭态 backlog 保持原状。
- 生产 image 内严格语义探针确认：Netkeiba `3中京8→('中京','3:8')`，非 Netkeiba
  `4中京7` 保持完整；`芝2000`、`ダ2000`、`2000m` 分别保留 turf/dirt/unknown 类型提示。
- 使用原受审 research/mapping/authority 和 fresh 生产快照成功生成全新 candidate
  `d95b580b1d97fb61cbbebe4ae60640ccfccab6e1dcd649ed824ef0215d5a418a`、artifact
  `f74c116f63ff1bc561edac10a3a49f3c0643a13a079ec40b13fd5806d266ce0c`。动作固定为 profile create
  `0`/update `32`、race create `180`/update `230`/existing `12`、P0 source `32`、module audit `128`；
  422 条履历为 421 started + 1 nonstart，98 条 major wins 全部来自 `won`。首次发布仍仅尝试
  `8307/45666/45738`，16 blocker 继续冻结。
- 独立 artifact 静态复审 `APPROVED`、无 P0-P2；profile `45661` 的 11 场在内置 `_simulate` 中进入 update
  而不是重复 create。额外自定义 230-row 生产 DB 重放两次未在有界时间内返回汇总，已停止且不得误报
  为通过；此项记录为非阻断 P3，因为正式 dry-run/apply 会再次校验 snapshot、唯一解析和精确动作数。
- 当前仍无本批业务写入、无新 release approval/manifest。旧 candidate `fc7962c3…e16e` 及其旧 approval
  不得复用。下一步只等待绑定新 candidate/artifact、精确动作、三个发布目标与 16 blocker 冻结边界的 G3；
  `full_network` 不在本次范围。

## 2026-08-10 PR #97 已闭锁部署；新候选在零写入阶段暴露 Netkeiba 表示差异

- PR `#97` 已按精确 merge SHA `afe0856da2d2ebbd615898b93c4adb3a5f410978` 部署到独立 release
  `/opt/umanews-release-afe0856d-PR97-20260810/umanewsbot`，web/worker/beat 统一 image 为
  `sha256:bd8b12060237ec226f57d7d70e753b632cfb11870a10e29a14df8fca186119c0`。migration no-op、leaf
  `0072`、内外 HTTP、Celery/Redis、错误日志与全部高风险开关关闭 verifier 均通过；本次部署没有执行
  P0 production apply 或 `full_network`。
- 代码部署前备份为 `/opt/umanewsbot/backups/db/pre-pr97-cross-source-dedupe-20260810T112657Z.dump`，
  `420543252` bytes、mode `0600`、TOC `1301`、SHA-256
  `7fb1bd2eddf8474fb675623042a4b506417dd0cfc40833b4fb52310f082fe185`；旧 image 已保留为
  `umanewsbot:rollback-pre-pr97-20260810`。
- 使用新 image 对原受审 bundle 执行 `--prepare-release` 时在任何业务写入前安全拒绝：
  `インターポーザー merged started count 22 does not match reviewed official count 11`。逐场只读核对确认
  日期、名次、结果与出赛状态均一致，剩余差异只是 Netkeiba `3中京8`/`芝2000` 与 JBIS
  `中京`/`2000m` 的场地届次包装和场地前缀距离表示。
- 后续最小修复限定为：仅 Netkeiba 来源可把已知 JRA/NAR 的数字届次包装降为精确场名；仅对
  `芝/ダ/障 + 3-5 位公制米数` 与显式 metric unit 建立距离等价。双方都有场地类型或包装信息时，
  任一冲突仍拒绝；日期、场地、距离、名次、actual result/start、race number/event 冲突和多解阻断
  合同不变。定向 `8/8`、核心 `50/50`、邻接 `471/471`、PostgreSQL 16 首次/重复提交 `1/1` 已通过；
  独立限定复审 `APPROVED`，无 P0-P3，下一步为新 PR 与闭锁部署。
- 旧 candidate `fc7962c3…e16e`、artifact `9d2a1e32…9c16`、release 与旧 G3 继续禁止重放；当前仍为
  零本批业务写入，16 个 blocker 冻结，`full_network` 未启动。新修复部署后必须重新生成并审核全新
  candidate/artifact，再申请新的精确 G3。

## 2026-08-10 batch-0001 r2 G3 apply 确定性停止且完整回滚

- 精确 G3 绑定 candidate `fc7962c3…e16e` 与 artifact `9d2a1e32…9c16`。fresh 写前备份为
  `/opt/umanewsbot/backups/db/pre-batch0001-r2-g3-20260810T065248Z.dump`，`419970933` bytes、mode
  `0600`、TOC `1308`、SHA-256 `6404536a31369b7bbd2c69ba85dfecb07c4da121c6732f6e4119a74c831438ae`；
  `.env` 备份为 `/opt/umanewsbot/.env.backup.pre-batch0001-r2-g3-20260810T065248Z`。
- 停止 beat 后，唯一普通 worker 的 drain 为 `active=0/reserved=0/active_confirm=0`，随后停止 worker。
  既有 `race_live` 队列 `7543` 条均为关闭态 monitor backlog，race-live worker 保持 `created`，本次未清空、
  未消费。默认 `celery` 队列始终为 `0`。
- release manifest SHA 为 `46b7951db33524105e7ab0b7008f3bc16a314a5c40a31ee8ebbcfb187b15cd33`。
  apply 在事务内确定性拒绝：`インターポーザー is not strict complete after apply`，缺口为
  `race_history.career_status.needs_review`、`race_history.start_count_mismatch`、`race_history.gaps`。
- 根因证据显示该 profile `45661` 生产侧已完整拥有 Netkeiba `11/11` 条履历，而 candidate 又携带 JBIS
  `11/11` 条同场履历；当前 source-aware idempotency/canonical key 未把两来源的赛名变体识别为同场，
  因而模拟新增并在写后导致出赛数翻倍，严格完整性门禁正确阻断。该问题可能影响其他已有履历的目标，
  不能只特判一匹或放宽 strict-complete。
- 事务回滚后目标 records `243→243`、major wins `0→0`、P0 sources `50→50`、completion runs
  `11→11`、成功 apply logs `12→12`；artifact run/success log 均为 `0`，三个 draft 仍为 draft 且公开页
  `404`。batch state 仍为 `prepared`，execution ledger 仍为 ordinal 1 `prepared`，未推进 applied/verified。
- 后置 dry-run 仍为 `32` profile updates、`410` record creates、`12` existing、`32` source upserts、
  `128` audits、数据库写入 `0`。worker/beat 已恢复，Django check、migration plan、内外 health/home/horses
  均通过。禁止重试当前 candidate；修复须先解决跨来源同场等价、补回归与独立审查，再生成新 candidate
  并重新申请精确 G3。`full_network` 未启动。

## 2026-08-10 batch-0001 r2 已生成候选，等待精确 G3

- 用户已批准 `32` 个唯一 identity 的 profile/pedigree/race_record/major_wins 四模块，`16` 个 blocker
  继续冻结。生产只读 bundle 生成成功：research SHA `e9a3e93a…81643`、mapping SHA
  `69ba9f10…6ba7`、authority SHA `670932e6…d136`；`32/32` 均绑定现有且互不重复的 profile。
- 独立只读审查 `APPROVED`、无 P0-P2：共 `422` 条履历（`421` started、`1` did_not_start），`98`
  条主胜鞍严格由 `result_status=won` 的履历投影，`16` 个 blocker 未进入 research/mapping。
- 实时 production snapshot 复核无漂移，已生成 immutable release candidate
  `fc7962c3e337945b70303fbe1868bd7f100c5ff3437296356cfc0955f487e16e`，commit artifact SHA 为
  `9d2a1e32efbe658f10989771d26c4627a48f395cf99a629a73c2432491c39c16`，production snapshot SHA 为
  `1bb55ec97fe5439c96c010b2fa163f666b46a13b9fedf1677761c510782dfbe4`。
- 候选动作固定为 `32` profile updates、`410` race record creates、`0` race record updates、`12`
  existing records、`32` P0 source upserts、`128` module audits；profile `8307/45666/45738` 为 draft，
  commit 后将尝试首次发布。当前仍为零业务写入、writer activity 为零、健康检查 `200`；生产 apply、
  首次发布及后续 full_network 均未获授权。该 G3 随后已执行并按上节确定性停止。

## 2026-08-10 batch-0001 r2 已补齐 participant→release draft 最小桥接

- PR `#93` 已合并并按精确 merge SHA `25ea0df188f323e1a24a78f781bab6a27bf0ac73` 闭锁部署；生产 image
  为 `sha256:4a8667b91122b2b616cd13b721d666a2be345998277932e0c683a1096a9cc19f`，migration leaf
  仍为 `stable.0072_add_extended_racing_regions` 且 migration plan 为空。web/worker/beat/nginx、两个
  正式域名的 health/home/horses verifier 均通过，P0 profile network、historical、race-live、
  race-data-sync、term enforce 与 attribution 高风险开关保持关闭。
- 发布前 fresh custom-format PostgreSQL 备份为
  `/opt/umanewsbot/backups/db/pre-pr93-code-deploy-20260810T030655Z.dump`，`419585214` bytes、mode `0600`、
  TOC `1308`、SHA-256 `42beceff5fc6aaa85635d3b960595cb0a89ec7b62c15f178b85bcdac27091659`；
  旧 image 已保留为 `umanewsbot:rollback-pre-pr93-20260810`。
- batch-0001 r2 completion SHA 为 `2cf2c634…04b8`，守恒为 `50 occurrence = 34 complete + 16 blocked`，
  网络请求 `120`、数据库写入 `0`，execution ledger 仍停在 ordinal 1 `prepared`。
- 旧 production apply 要求唯一四字段身份，34 个 complete occurrence 中有 2 组重复 provider identity，
  因而不能直接导入。新增离线桥接命令精确重验 batch index、active ledger、completion manifest 与
  candidates 文件 SHA/大小/计数，再按 provider identity 语义去重；只有 candidate key、抓取时间和
  occurrence 自身赛事入口可不同，其余内容漂移立即拒绝。
- 已用精确生产 image 在 `--network none`、只读根文件系统下直接绑定 PR90 的权威 r2 evidence root，
  生成 production draft `p0batch-5e17bcd17816`：batch SHA
  `5e17bcd1781671fc7dcbfa4f02e3d0a219f504d7cbfb9a9dc7ebc934294e794c`、combined SHA
  `77cdb63b621d1e081de2a667732b0a1a7f26d1c3559c0f97fd33ae1f099fa6aa`、source-binding SHA
  `0e3d269a6222f47ed01adade185202da0273c9b5a9c57366fd5fda21dac4456b`。语义 verifier 得到 `32` 个
  唯一 identity、`2` 个被折叠 occurrence、`16` 个继续冻结 blocker；仅有 inclusion approval，
  module/release approval 均不存在，数据库写入 `0`。
- 相关组合回归最终 `262/262` 通过。独立 reviewer 提出的 active review SHA 格式与三类 schema version
  fail-open 已补反例并修复；限定复审最终 `APPROVED`，无剩余 P0-P2。
- 该门禁随后已按上节记录通过；本节保留 draft 生成时的历史状态。

## 2026-08-09 2025 五地区生产资料桥接正在实现

- 用户已明确本轮暂不处理澳洲、德国和中东；当前生产资料范围只包含日本、中国香港、英国、法国和
  美国。澳洲 346 场继续保留许可 gap，德国 42 场和中东 45 场官方结果不进入本轮 HorseProfile 写入。
- 正式 workflow run `31319364383` 首次即成功，未使用续跑额度。completion bundle canonical SHA 为
  `0e699786…be1f8`；独立复核确认 13 个绑定文件 SHA 全部匹配，official 分支为 87/87 场、790 条
  实际参赛记录、无重复身份或缺冠军。该 bundle 是合格研究证据，但缺 production P0 manifest，不能
  直接写 HorseProfile。
- 生产只读 `--year 2025 --actual-starts-only` census 得到 1065 场、9292 条实际赛果、7731 个保守身份
  候选：1358 `bind_existing`、920 `create_new`、5453 `blocked`。按地区为日本 2030、香港 191、英国
  1537、法国 749、美国 3224。弱身份不按马名合并；provider 搜索无结果、多解或四字段不一致时继续
  fail closed。
- 当前候选新增 source-bound v2 batch contract 和离线编译器：真实 census SHA
  `59c0a4a9…0783` 已稳定切为 156 个单地区、每批最多 50 匹的 reviewed prepare 批次；summary SHA
  `80331699…f287`、全局 batch plan SHA `79b479a1…a5b3`、exclusions 为 0，同时绑定生产 census
  manifest `41b30c7a…3828`。每批运行前重验 source/source manifest 的 regular file、路径边界、大小、
  SHA、地区、全局 membership、rank、马名、来源和实际起跑证据；严格顺序 execution ledger 机器拒绝
  跳批、重复和不同 manifest 抢占；下一 ordinal 还必须等待上一批 release/G3/apply/写后 verifier 证据
  全部绑定并进入 `verified`，旧五地区各 10 匹合同保持不变。
- 最终 r3 的日本第 1 批已在 `--network none` 下跑通真实 CLI：`processed=50`、`blocked=50`、
  `network_request_count=0`、`database_writes=0`；同一 completion manifest 已完成 ledger ordinal 1 的
  精确 claim/prepared smoke，且下一 ordinal 在 production verifier 前保持关闭。当前相关 Django
  `211/211`、研究套件 `156/156`、workflow 合同 `13/13`、纯编译器/账本 `3/3` 通过；第二次全量重建
  与 r3 逐字节一致。独立 reviewer 关闭 macOS 祖先 symlink、dirfd/openat TOCTOU、生产 verifier 绑定及
  `planned_remaining` 精确五字段合同后最终 `APPROVED`，无 P0-P2。当前仍未合并、部署、触发外部
  profile 网络、生成 production release candidate 或写生产数据库。

## 2026-08-09 2025 reviewed package 已通过独立离线复审，等待范围与写入门禁

- 当前生产 web/worker/beat 统一运行 revision
  `45da956a4542d0b28a820d9cbc00852350a22baf`、image
  `sha256:b1686e59cc21598c30b439d4a33e34a8d32246dae148b982ab18c59301194c82`；migration plan 为空，
  HTTP health 正常，高风险开关与 writer/lock 均关闭。本阶段未执行生产回填、澳洲正式网络验证、
  official-results 网络采集或 `full_network`。
- 新受审三文件包守恒为 `433 = 87 collect + 346 evidence_gap`：德国 42、UAE 33、Bahrain 2、
  Qatar 3、Saudi 7 进入 collect；澳洲 346 因官方稳定公开赛果不可用而保留 gap。包 identity 为
  `e9abb139…a15ca`，summary SHA 为 `7ddc901f…28d5b`。
- 冻结缓存已用 revision `45da956a…22baf` 的当前 parser 逐场重放：87/87、790 名实际参赛马，
  每场 cache SHA/size、starter count 与 top 3 全部一致，receipt SHA 为 `1f5656d2…105`。独立复审
  `APPROVED`，无 P0-P2。
- workflow 实际 CLI 暴露 validator 与 completion bundle 未 bootstrap 仓库根的确定性 import 错误；
  当前候选只补两处入口 bootstrap 与真实 CLI 回归测试，并把受审包登记为仓库相对路径。尚未合并或
  部署，也不构成后续数据动作授权。
- 下一人工门禁一次性包含：是否先按非澳洲 87 场推进并明确排除澳洲 346 场，或等待取得澳洲数据
  存储/再发布许可；以及候选 PR 通过 CI 后的 G2 与精确 manifest-bound 生产写入 G3。

## 2026-08-09 2025 新地区官方赛果目录已重建，正式运行仍待门禁

- migration `0072` 的 G2 关闭态发布已完成：生产 revision 为
  `0b93aa552f7abfeadb0a91e5fe7f2610178ee8ca`，统一 image 为
  `sha256:0f184c78be6632fd467d16465ffb3554e44757c69468ee22c86c0cd84eddd8a8`；迁移为 no-op
  completion，服务与 verifier 正常，所有历史/网络高风险开关仍关闭。本次状态不包含生产回填或
  `full_network`。
- 冻结 TJCIS 2025 PDF 视觉与正文均明确澳洲章节口径是赛季
  `2024-08-01..2025-07-31`，不能作为 2025 自然年完整目录。澳洲改用 Racing Australia 官方相邻
  两赛季 Group/Listed 日历交集，得到 2025 自然年 G1/G2/G3 `346` 场（`77/97/172`），分布在
  `117` 个官方赛马日页面；德国 `42`、中东 `45`，新地区总目录为 `433`。旧 `404`、修正 index 后
  的 `399` review queue 与对应 summary 全部作废。
- 澳洲一个官方赛马日页面包含多场结果，manifest/runner 现仅对澳洲允许同一 URL 绑定不同的
  `source_race_name + distance + grade`，parser 用三者精确选表；相同选择器重复仍拒绝。官网当前归档
  CDN 在本地对 `t.` host 返回 `403`，因此 `346` 条 URL 只标记为待独立网络验证，不声称已采集成功。
- Qatar 展示页不含结果数组；候选只从当前 QREC 官方前端读取公开 API bootstrap 配置、取得进程内
  临时 token，再访问 `api.qrec.gov.qa`，不把 token 写入代码或 artifact。Qatar `3`、Bahrain `2`、
  Saudi `7` 共 `12` 场官方结果已有限联网解析；Saudi Cup 的 `Place = -` 经实际 starter 行确认仅在
  JCSA adapter 中保留为 `did_not_finish`。
- 上述增量目标测试 `36/36`、完整 research 套件 `146/146` 通过；真实 Racing Australia 当前页面的
  单场选择 smoke 解析 `8` 匹。代码仍在 Draft PR `#86`，尚未完成本轮独立复审、合并或部署；更未
  生成可授权的最终三文件包、执行生产回填或启动正式 `full_network`。

## 2026-08-09 德国官方赛果页脚解析最小修复待审查

- 2025 德国官方日历按 `von_submit/bis_submit` 与 G1/G2/G3 过滤后得到 `42` 场，和 TJCIS 德国目录
  `42` 场守恒；第一张真实赛果页包含与参赛表共用 `<table>` 的单格投注赔率/开跑时间页脚。
- 现有通用表格 parser 会把该不完整页脚误当作名次并以 `unknown official result status` 确定性停止。
  最小候选仅在 row 同时具备已识别的 `position` 与 `horse` 列时才交给 provider builder；真实未知名次
  仍由 `placing()` fail-closed。德国官方另以 `Pl. = -` 表示已在 starter 表中且非 `Nichtstarter`、但
  没有数值名次的实际起跑马；仅德国 adapter 把该值保留为 `did_not_finish`，不全局放宽状态集合。
- 阿联酋 ERA 的真实 Jebel Hatta 结果页使用完整文案 `Did Not Finish`；该受控官方状态已加入既有
  did-not-finish 集合，未知完整状态仍拒绝。
- 冻结 2025 TJCIS PDF 的 `Part I - INDEX` 采用完整 `Part` 而不是既有 fixture 的 `Pt`；旧 parser
  未重置上一页 Saudi context，把 `American Turf/Andrés S. Torres/Colin Jillings/Durham Cup/Remus`
  五条索引项错误解析为沙特赛事。候选把 `PART I/II/IV - INDEX` 纳入同一 unsupported boundary，
  parser version 升至 `2026.08.2` 并补跨页 Saudi→Index 回归；正式目录与 404 review queue 必须在
  该修复后全量重建，旧文件作废。
- 聚焦测试 `26/26`、研究套件 `136/136` 通过，真实德国缓存页已覆盖普通结果与 `Pl. = -` 形状；
  独立 reviewer 另验证德国完整未知状态及 AU/Bahrain 的 `-` 仍拒绝，最终 `APPROVED`、无 P0-P2。
  当前候选已提交推送至 Draft PR `#86`；新增 ERA 状态和 TJCIS `Part` index boundary 增量也分别经
  独立复核 `APPROVED`，均无 P0-P2；尚未合并或部署。
  旧生产 image 仍会在该页确定性停止，因此不得在旧 revision 启动正式
  official-results/full-network run。

## 2026-08-09 migration 0072 已应用，发布合同叶节点修复待合并

- PR `#83` 已合并为 `main@eb1e221f2791948616c3a72f0e45183d72fdc350`。生产隔离 release 为
  `/opt/umanews-release-eb1e221f-GR20260809/umanewsbot`；写前 custom-format dump 为
  `/opt/umanewsbot/backups/db/pre-2025-completion-g2-20260809T064812Z.dump`，大小
  `415467279` bytes、mode `0600`、TOC `1308`、SHA-256
  `9f836669f9e801944f339ad717a30f13219978fb34bb0adb9c9f5ff0d9b60f42`。
- 首次受保护部署已构建 image
  `sha256:ca19687a91c481e19aa51d774a432c9b770cae66bd4ba6092d126c776c8bf5ee`，并成功应用
  state-only migration `0072_add_extended_racing_regions`；随后 completion 因 Release-B schema
  合同的最终受审叶仍固定为 `0071`，把合法 recorder 变化判为 `migration.state` drift 而
  fail-closed。未执行业务回填、外部网络或 G3 数据写入。
- web/worker/beat 已从同一 `eb1e221f` image 恢复，web healthy、HTTP healthz 为 ok；历史回填、
  历史网络、马匹资料网络、race sync/live flags 均为 false，外部导入、导入锁和运行中资料补全均为
  `0`。正式 release completion 尚未通过，因此不能把本次记为完整发布验收。
- 最小修复分支 `codex/allow-0072-release-preflight` 将 schema target/final leaf 统一推进到 `0072`，
  保留 `0071` 为合法中间态，并同步 completion、restricted marker 与 shell leaf allowlist。
  普通 B→B rollback、retry 和目标 migration allowlist 也同步要求受审 `0071` 依赖与精确 `0072`
  终态同时匹配；pre-0072 image 只允许另行审批的数据库恢复。
  migration-history 套件 `65/65`、真实 PostgreSQL 16 migration/catalog 套件 `25/25`、
  single-migration-owner 套件 `162/162`（含 rollback contract `22/22`）、Django check 与 migration
  drift 检查通过；同一只读 reviewer 最终限定复审为 `APPROVED`、无剩余 P0-P2。待提交并经新 G2
  合并后重新完成受保护发布。

## 2026-08-09 2025 参赛马完整补全正在本地实现，尚未发布或写生产

- 隔离分支 `codex/complete-2025-graded-horse-data` 已固化七文件 gap census；旧 artifact 的
  `1063/9292/4965/15854` 计数与逐文件 SHA 可离线复现。
- 生产只读差集确认多出的两场英国赛事是 2025-01-11 的两场 G2 障碍赛；均为
  `draft + incomplete` 且结果数为 `0`，因此旧公共页采集无法发现。
- 已修复纯拉丁官方赛果马名不能成为英文名证据的问题，policy 升至 v2；collector 聚焦套件
  `102/102` 通过。
- 已新增 AU/DE/UAE/SA/QAT/BHR 官方源 URL policy、请求预算和严格离线 parser，并用四个当前
  官方端点做有限 live smoke。新增 manifest-bound 官方赛果 runner 会逐跳限域、保存原始 response
  SHA、按精确 checkpoint 续跑；临时网络错误返回 `75`，解析/身份错误确定性停止。独立审查发现的
  并列名次、DNF/PU/F/UR/DSQ 实际起跑保留、deterministic resume 禁止重新联网及 cache path 越界
  已修复并补反例。
- TJCIS 2025 官方 Blue Book（327 页，SHA-256 `ca6aafb6…feb6`）整本解析已在释放逐页 cache 后成功：
  总计 `1494` 场，其中 Australia `312`、Germany `42`、Middle East `50`（UAE `33`、Bahrain `2`、
  Saudi Arabia `12`、Qatar `3`）。Qatar 三场原来夹在 `OTHER` 页的 unsupported country 段落之间，
  现已由官方整本真实回放证明并补入；France/US 的 parsed/declared count 差异仍显式记录为来源冲突。
- P0 参赛马候选桥现支持八地区、单一年份与 `actual_starts_only`，输出
  `bind_existing/create_new/ambiguous/blocked`；provider ID 优先，纯马名仍只能 blocked。当前受影响
  Django 组合回归 `434/434`、研究侧回归 `122/122`、workflow 合同 `17/17` 通过。v2 census 的赛事身份
  已改用规范化完整 URL（保留排序后的 query），不再把不同德国赛事折叠成 `rennen.php`。
- 同一独立 reviewer 对首批五项 P1 的最终反例复核为 `APPROVED`；其中 cache path 同时拒绝 `../`、
  absolute、resolved-outside-root、非 race-bound 及 output root 内 symlink alias。后续 URL manifest/
  cache-only 增量审查发现的 canonical duplicate、跨 provider gap evidence 与注入 client 绕过均已补 RED
  后修复；同一 reviewer 限定复审最终为 `APPROVED`，无 P0/P1/P2。
- 已新增完全离线的官方 URL manifest 编译器：先生成 `404` 场新增地区逐场 review queue，再只接受
  SHA 绑定、目录事实不漂移且 1:1 守恒的 `collect/evidence_gap/not_held` reviewed mapping；runner
  manifest 直接绑定 review SHA，summary 再绑定 manifest/gap/package SHA。URL 去重使用 canonical query，
  gap evidence 只能来自本场 provider 或当年 TJCIS；禁止名称模糊自动绑定。
- P0 completion normalizer 已加入 AU/DE/Middle East 的逐 provider allowlist，但新地区当前严格为
  reviewed canonical cache-only：缺完整 v2 cache 即阻断，不允许网络临时补半份资料；旧五地区 rolling
  batch 的地区集合保持不变，adapter 层即使注入任意 client 也禁止 cache miss 触网。生产 reviewed
  apply 的三地区 create-new 回归已通过。顺带修复既有
  Netkeiba fixture 的 parser version `v3→v5` 测试漂移，不改变生产 parser。
- `RacingRegion` 已在本地加入 Australia/Germany/Middle East，并生成 state-only migration 0072；
  `makemigrations --check`、Django check 与枚举回归通过。
- 正式 workflow 已接为旧七文件与 official_results 两条并行分支；`full_network=true` 缺受审三文件包
  会拒绝，临时错误以 exact official checkpoint 续跑，两条分支均成功后生成逐文件 SHA 绑定的
  `graded-race-completion-bundle.v1`。自由 package 路径不直接进入 artifact glob，而是复制到固定权限
  staging 后重验。第三轮独立审查最终 `APPROVED`、无 P0-P2。尚待自动发现并审核官方赛事 URL，并生成新增地区完整
  profile/career canonical cache。基础实现已提交为 `3dcbd46f` 并推送到 Draft PR #83；当前未部署、
  未扩大正式网络或写生产。

## 2026-08-09 Release B 已验证写入，2025 正式研究 run 产出 partial artifact

- 用户批准的生产 revision `75294a4dea51538962741ec6c0835dc3090558ff`、reviewed manifest
  `89387fab38f4c2a435c3b009802907a6b9710547354b38f91c3057546f41e96b` 与 action scope
  `d7052d4392c027522ffde7c14955c98a2bc4ebfa99714c8681237c0ab65900bd` 已按精确 G3 完成。
- 写前 custom-format dump 为
  `/opt/umanewsbot/backups/db/pre-release-b-data-apply-path-staging-20260808T172850Z.dump`，
  `413103571` bytes、mode `0600`、TOC `1308`、SHA-256
  `af6aa018da8a14311de4ad86801e729af1c7b9fe40bcb1adca050c0d868a832a`。
- approval SHA 为 `f5df52d3320aae1c611f652fbcd5e41a438c73b43be346f8ed6fca5f4de55ecf`，
  maintenance evidence SHA 为 `840d87a8c5319fb09047d702fb4592a82a4c956a2b1ee582b11a525a8dfdc661`。
  首次命令因 one-shot 进程未显式设置 `HISTORICAL_RACE_BACKFILL_ENABLED=true` 在任何写入前
  fail closed；未修改全局 `.env`，只为精确 apply 进程注入该必需开关后成功。
- receipt `#1` 状态为 `verified`，rollback SHA 为
  `acb1fc2b2dee46f979517d496be1f81169c27fa56a4be6042ae8e97b7be3342c`，独立 verifier
  `errors=[]`、result SHA 为 `f71c2bc93dc5ff93a7b12ef81518958e9c79ba5ecf65b17e39e30927ebadf0ac`；
  12 条 active canonical link 已绑定 reviewed manifest。rollback artifact 已复制到持久备份目录，
  maintenance 已退出，worker/beat 已恢复，Django check 与内外 HTTP healthz 均通过；历史相关全局
  flags 仍为 false。域名 443 当前拒绝连接，与仓库记录的 HTTP-only 生产边界一致，不记为 HTTPS 成功。
- verifier 通过后启动 2025 `full_network=true` fresh run `31269803408`，首轮全部 job success，未使用
  checkpoint 续跑。最终 artifact `31269803408-1-finalize-0`（ID `9025592068`）digest 为
  `sha256:ef8bbc107379413aa2e2ca8ed0dc144759fb7b3578b4d15746b421b923477535`。
- 最终 artifact 为诚实的 `outcome=partial`：`1063` 场、`9292` 条参赛记录、`4965` 匹马、
  `6982` 次请求；法国、香港、日本、英国、美国 covered，澳洲、德国、中东均为
  `classification_incomplete`。另有 required English missing `3905`、profile not found `3998`、
  ambiguous `32`、unresolved `15`。这些是确定性覆盖/资料缺口，不是临时网络失败；按授权立即停止，
  workflow run 使用 `1/6`，不对相同输入自动重跑。

## 2026-08-09 Release B canonical path staging 修复已发布，等待新 G3

- apply 的临时 path 阶段现在除临时 `year/slug` 外，同时把完整受控 scope 设为 `legacy`；最终
  reviewed loop 再恢复精确 owner/year/slug/kind。最终约束、overlay、manifest、业务决策和 schema
  均未放宽或改变。
- 新回归测试复现生产危险顺序：新 canonical 先转给仍持有旧 canonical 的 event，旧 path 后降为
  legacy；并验证最终唯一 canonical。独立审查进一步发现 exact rollback 需要同样释放 canonical，
  候选已对称修复并新增双向 canonical swap 的 apply/rollback 回归。最终 SQLite 与真实 PostgreSQL
  16 完整 Release B 套件均为 `38/38`。
- 独立 reviewer 在同一会话 `019fe254-9543-7440-bfaf-8fac75d6ff30` 自行复跑 SQLite 与
  PostgreSQL 16 完整套件各 `38/38`，并完成 Django check、migration drift 与 diff check，最终
  明确 `APPROVED`、无剩余 actionable defect。
- PR `#80` 已合并并部署 `main@75294a4dea51538962741ec6c0835dc3090558ff`；生产 image 为
  `sha256:1894484989084e61ced236eec93a30fd0b963b7ee946ad8ee8bd8e15357e413d`。部署后 Django
  check、migration 零计划、内外 HTTP health、Celery 空队列、关闭开关与零 active gate 均通过。
- 全新 census manifest SHA 为 `e626c8b48b5231890b0f1d4ac06f4fa22ee595fb9502d6aaead69f1169d070ec`；
  review overlay SHA 为 `083610c50097dea568d8c948654f28fe38200806ca9bd3006ff558bcea6f5883`；
  reviewed manifest SHA 为 `89387fab38f4c2a435c3b009802907a6b9710547354b38f91c3057546f41e96b`；
  action scope SHA 为 `d7052d4392c027522ffde7c14955c98a2bc4ebfa99714c8681237c0ab65900bd`。
- reviewed artifact 静态审计为 14 actions、177 events、12 tombstones、12 canonical links、12
  superseded targets、165 canonical paths、12 legacy paths、2 个合法跨年 edition，全部 collision
  为 0。尚未生成 approval、进入 maintenance、执行 apply/verifier 或启动 2025 `full_network`；旧
  reviewed manifest `c9e9b222…1e4c64` 继续禁止复用，当前精确停在新 G3。

## 2026-08-09 Release B 数据 apply 在事务内确定性停止并安全恢复

- 用户批准的 14-action reviewed artifact 已通过严格生成门禁：review overlay SHA 为
  `8a1f3f2cadd7d7b4446b52548b010be1b2738d0da8c5bebe31ce19259ca26dbe`，执行 manifest SHA 为
  `c9e9b22299b94dc62af4a2afccb87dca0d7d906c9f84539a8b8a7727591e4c64`，action scope SHA 为
  `0f633f215e45c47d6c4fd8cd2b720158436d2849362462f5581c092cb9f0af01`。
- 写前备份 `/opt/umanewsbot/backups/db/pre-release-b-data-apply-20260808T165235Z.dump` 为
  `412849582` bytes、mode `0600`、TOC `1308`、SHA-256
  `91a38cf276005f614c6171ea13cde87532485a8e63dca1e96e280405d39e17aa`。
- apply 在同一事务内更新 path 时触发 `uq_race_public_path_event_canonical`：event `1214` 的旧
  canonical path 尚未临时降级，另一条轮转 path 已先被设为该 event 的 canonical，形成瞬时冲突。
  命令按确定性错误规则停止，未重试、未运行 verifier 或 2025 `full_network`。
- 回滚证据：receipt `0`、批准范围 active canonical link `0`、mismatch 仍 `81`、scope 仍为原
  `a324261f…11665`，event `1214/1838` 保持原 published 状态，rollback artifact 不存在。maintenance
  gate `1` 已退出，worker/beat 已恢复，Celery、Django、writer census 和 HTTP healthz 通过。
- 最小代码修复是在最终 path 写入前，把所有受控 path 的临时态同时设为 `legacy`，解除
  `event_id` 条件唯一约束，再按 reviewed topology 写回 canonical/legacy；必须补轮转路径回归测试、
  独立复审、发布并生成新 census/manifest 后重新取得精确 G3，禁止复用本次执行 artifact。

## 2026-08-09 Release B 官方结果身份修复已发布，等待 G3 数据决策

- PR `#77` 已合并为 `main@55d41b5f84f072e11862fa14213cecc027708719`，生产统一运行
  image `sha256:c9f0a89fbb3a28f135a0dd32546b609164b89d845c6181483eb553ddbd249ef4`。
  部署前备份 SHA-256 为 `629a5495010d564da6c8233e887becebdb08d7d31d73ea0503bb48cdd381de70`；
  handoff canonical artifact SHA 为
  `09262ebbdb2ffad4ca46112b19d972cf725754d4d6fae1156c946b5b5828f602`。
- 发布后 Django check、migration plan=0、`0068/0069/0071` applied、内外 HTTP healthz、唯一
  Celery worker ping 与空 writer/false flags 全部通过，部署锁已释放。
- 新只读 v2 census 已持久化到
  `/opt/umanewsbot/backups/release-state/release-b-census-official-identity-20260808T164124Z`；manifest
  SHA-256 为 `85978b9bed6ff75742d1eed4cb0ad1e4f6105c9ebc82146e3c05efdff1682a13`，守恒仍为
  `14 actions / 81 mismatch / 12 duplicate boundaries / 0 unscoped / 0 executable`。
- 12 对 duplicate 的官方身份 SHA 已逐对相等，确定性代码 blocker 已解除。当前唯一门禁是人工审核：
  12 对 survivor/错位链，以及 `series-5963`、`series-6501` 两个合法跨自然年届次。尚无 reviewed
  overlay、approval、maintenance、数据 apply/verifier 或 2025 `full_network` run。

## 2026-08-09 Release B 官方结果身份最小修复实现中

- 已把生产 v2 census 的确定性 blocker 收敛到 `_duplicate_identity_sha256()`：完整 `source_refs`
  digest 把 TJCIS catalog provenance 错当成赛事核心身份。
- 最小候选只在嵌套 official result URL 与唯一 approved source/provider/content SHA 精确匹配时，
  使用官方结果身份；否则保留赛事名 + 完整 `source_refs` 的严格 fallback。
- 生产只读复核确认 12/12 对均有相同受审 HKJC provider、URL、缓存内容 SHA、客观字段和
  runner/result；没有新增模糊赛事或用户待判项。
- 无模型、migration、配置、采集或公开行为变化；Release B 测试 `36/36` 通过，独立只读 review
  会话 `019fe233-9c84-7b23-9ff6-ca7701cd060f` 未发现 actionable defect。当前尚未提交、合并、
  部署或执行任何生产数据写入，旧 v2 census 继续不可执行。

## 2026-08-08 Release B 已部署，v2 census 在 duplicate identity 门禁确定性停止

- 生产过期 review claim `39/43/44/45/46/47/48` 已在停 Beat/worker/race-live、custom-format
  备份与独立审查后，由一次性 `SERIALIZABLE` PostgreSQL 事务收口为既有终态 `noop`；业务原因仍为
  `stale_claim_reconciled`。最终 approval SHA 为
  `968f0e8d5bac63f099b9cad4bbf84cabf489bf545677a9e476523afad2a00bb1`，after artifact 为
  `13632` bytes、mode `0600`、SHA-256
  `1e24890db5f744aa2381f7621daf51e38d5343c0944a6a65198e7f9a42ceeb8d`。第一次包装器因旧 web
  镜像缺新 helper 在 SQL 前停止，锁已释放、7 行仍 claimed、无 migration；v2 包装器改用等价内联
  digest 并经独立复审后成功。
- 最新迁移前备份
  `/opt/umanewsbot/backups/db/pre-release-b-after-stale-reconcile-20260808T131400Z.dump` 为
  `411796037` bytes、mode `0600`、TOC `1304`、SHA-256
  `1f6b276bc139377af93709f80cb8b64d6c026022789b2e1c6651adea582b8d1b`；旧镜像另存为
  `umanewsbot:rollback-pre-release-b-after-stale-reconcile-20260808T131400Z`。
- fresh release `/opt/umanews-release-4e3ffa8d-MR3-20260808/umanewsbot` 固定
  `main@4e3ffa8dd0224ae9254b17eda6c42fa11b2c730b`。新 handoff artifact SHA 为
  `62300fbfdcc4c5ac16505067dad4fa5a68bfddcdb1e22e2ef90ceebdf51bb5f4`；关闭态 verifier 显示
  writer count 全 0、所有历史/网络/同步/live flags 为 false。`0068/0069/0071` 顺序应用成功，
  restricted marker 完成；生产镜像为
  `sha256:e2102ff87e465c4904b1db470ddfa3e3679dfe681bd63a405c6922954fe7afe1`，revision 为
  `4e3ffa8d...`。Django check、migration plan=0、web health、唯一 Celery worker ping 与关闭 flags 通过。
- 部署后只读 v2 census 已生成并持久化到
  `/opt/umanewsbot/backups/release-state/release-b-census-v2-20260808T132000Z`。manifest 为
  `16329022` bytes、SHA-256 `547d169535580d3948e81f57fb10b474e571d94aa8e1c3a9e1523317246abcdc`；
  结果为 `14 actions / 81 mismatch / 12 duplicate boundaries / 0 unscoped / 0 executable`。
- 独立 reviewer 复算 actions、scope、177 events、261 targets、177 paths 与 6279 immutable
  dependency rows 后结论 `BLOCKED`：12 对同 series/date/HKJC official result URL 且 runner/result
  相同的赛事来自相邻 TJCIS season catalog，但完整 `source_refs` 不同，导致 identity SHA 不同。
  当前 validator 不允许标记 equivalent/collapse；标记 distinct 又会把同一场比赛误作两场。
  因此未生成 reviewed overlay/approval，未进入 maintenance/apply/verifier，2025 `full_network` run
  保持 0。下一步必须先修改 duplicate equivalence 合同、测试、独立复审、重新部署并重新生成 census。

## 2026-08-08 migration-history production audit 生成口径已修复

- 首次受审 baseline 的三项 SHA 来自临时 raw SQL：receipt/operation 行被编码为 positional array，
  FK 被编码为 nested array；运行时 preflight 则一直使用 ORM named-object rows 与 scalar FK list。
  因此同一 7 行数据会得到不同 SHA，不能把这次门禁失败解释为生产数据变化。
- 唯一生成入口现为 `generate_migration_history_production_audit`。它在 PostgreSQL
  `REPEATABLE READ READ ONLY` 事务内调用与 preflight 完全相同的
  `collect_live_production_audit()`，输出 schema/canonicalization version、精确 ID/FK 列表和时间边界；
  loader 对缺项、多项、版本、ID 次序与 time-bound 结构严格拒绝。
- 两份既有生产备份中的 7 条 receipt 与其 7 条 operation-log 行字节一致；二次只读核对的当前
  named-object/scalar-FK SHA 已写入 `production_audit.json`。本修复不放宽 graph、catalog、TOCTOU、
  recovery 或数据库 identity 门禁。SQLite 四套件 `263/263`（含 1 skip）、PostgreSQL `25/25`。
- 首次生产重试在任何停服/migration 前因旧 positional baseline mismatch 停止。候选镜像保留为
  `umanewsbot:migration-repair-candidate-13541057`，`umanewsbot:prod` 和 web/worker/beat 已恢复并保持旧
  `sha256:b1fecc…341a`，内外 healthz 正常，recorder 仍为 `0067+0070`。恢复点 dump 为
  `411053136` bytes、TOC `1297`、SHA-256 `e12ee97c…c2cb6d`。
- 新 generator 已在只读容器和同一 `REPEATABLE READ READ ONLY` 事务内于
  `2026-08-08T11:41:07.525084Z` 生成 v2 payload；本轮没有执行 `0068/0069/0071`、业务回填或数据库写入。

## 2026-08-08 Codex 工作流与门禁治理收敛

- 根 `AGENTS.md` 现在是全部目录、任务、worktree 和代理的唯一人工确认门禁来源，统一为
  G1 范围确认、G2 交付确认、G3 高影响动作确认。
- 测试、review、CI、备份、SHA/队列/迁移计划和健康检查是自动技术检查；范围清楚的初始实现
  指令可直接计作 G1，commit、push 与 Draft PR 不再拆成独立确认点。
- `docs/codex_workflow.md`、`docs/session_bootstrap.md`、领域 agents 与 skills 已改为只引用根规则。
- 旧规格流程目录、兼容技能、路由资料和旧治理迁移产物已从受控仓库删除；契约检查会拒绝
  旧流程路径/文本、嵌套门禁文件或 G1/G2/G3 定义漂移。
- `main` 只作为受保护远端引用：线程使用独立 worktree/分支，长任务绑定固定 SHA，远端合并与
  生产发布分别按真实资源域互斥，由单一 release coordinator 操作生产发布面。

## 2026-08-08 Release B 发布在 migration history 门禁停止，生产已恢复

- Release B feature commit `5561d1da5dbd988be02ae54f965e5eeac18d8aa0` 经 PR `#69`
  合并为 `main@ba9c0f00bc435c806864fa7a27f00dce545f1efc`。最终限定只读复审为
  `APPROVED`，冻结 fingerprint
  `7be81a18315015d953a74d67c90619a0ee6d016b86a554242854c17b7f34333b`，content
  manifest `69799241bb7490fd7f189d12dc28980174984fcdf5886a07c540fe185ca5482a`。
- 生产预检确认运行镜像仍为 `sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`，
  旧应用只认识到 `0067`；数据库 identity SHA-256 为
  `a986cc11149981c54e9d4915ad35e7c46e9382584d6670c8f950eceda26e471c`。v1 census
  artifact 为 `81 mismatch / 81 canonicalize_duplicate / 81 block / 0 action`，因此没有
  maintenance、approval 或数据 apply。
- 因生产只有约 `236 MiB` 可用内存且无 swap，部署前先停止 Beat，并在 Celery
  `active=0 / reserved=0` 后停止普通 worker；可用内存恢复到约 `1.29 GiB`。恢复点
  `backups/db/pre-release-b-prereq-832cc074-20260808T020900Z.dump` 为 `408607125` bytes、
  mode `0600`、TOC `1304`、SHA-256
  `e0cd6899ea0f5dcc1a06dbde075ed9cdf6874965d2ddcd70e662a77d28e05cab`；旧镜像 tag 为
  `umanewsbot:rollback-pre-release-b-prereq-20260808T020900Z`。
- 为满足 Release B 受审前置 leaf `0070`，先在隔离 release 目录
  `/opt/umanews-release-832cc074-RBPRE01/umanewsbot` 尝试关闭态部署
  `main@832cc07465a73f2e59947e00e65482b64d39d027`。候选镜像构建完成，release task 在任何
  新 migration 执行前由 Django 拒绝：生产 `django_migrations` 已存在
  `0067_historical_calendar_release_a` 和
  `0070_horse_identity_evidence_commit_receipt`，但缺少后者当前依赖的
  `0068_race_data_sync_pipeline_a_field_audit` 与
  `0069_race_data_sync_pipeline_a_ledger_guards`，错误为 `InconsistentMigrationHistory`。
- 失败后未修改 migration history、未手工 fake migration、未应用 `0068/0069/0071`。已把
  `umanewsbot:prod` 恢复到旧镜像并使用受审 resume 入口恢复 web/worker/beat/nginx；三个应用
  容器镜像一致，内外 HTTP healthz 均正常，历史写入/网络 flags 仍为 false。race-live
  restore intent 因绑定不同 HEAD 被明确判为不可信并跳过；race-live 原本未运行。
- 当前确定性 blocker 是修复 `0070` 提前 applied 的 migration history 与实际 schema 一致性。
  在独立设计、测试、复审和新授权前不得直接删除/补写 `django_migrations`，不得继续部署
  `0071`、生产回填或触发 2025 `full_network=true`。本轮 GitHub full-network run 为 0 次，
  没有生成新 checkpoint 或最终 artifact。
## 2026-08-01 历史赛历 Release B 本地实现与第四轮修订完成，待最终只读复审

- 2026-08-02 reviewer session `019fc318-431e-7771-aa79-bf01a9fdb992` 的三个 P1 已限定修复：
  schema preflight 对生产 recorder 中候选 graph 未知的 `stable.*` applied node 输出明确列表并
  `ok=false`，deploy/rollback 不进入 release 或停服务；v2 verifier 将 overlay 字符串与 ORM
  datetime 的 `superseded_at` 统一为 UTC 微秒表示；apply 使用完整 manifest SHA 绑定的临时
  event/path identity，并先清空 scope 内 `race_series/edition_year`，避免链式交换的中间唯一冲突。
- 三项直接测试先分别复现错误 `ok=true`、合法 supersession post-verify 失败和届次交换
  `IntegrityError`，修复后直接 SQLite/部署 `6/6`、Release B 专项 `33/33`、真实 PostgreSQL
  rotation + supersession + unknown migration `3/3`，Release B + Release A 完整性 + 部署合同
  最终组合 `176/176`。本轮 PostgreSQL 容器已删除；当前改动仍待同一 reviewer 限定复审。
- 2026-08-02 已将该未提交候选安全 fast-forward 集成到
  `origin/main@832cc07465a73f2e59947e00e65482b64d39d027`，保留主线 P0 马匹身份、赛果同步和
  生命周期改动；唯一内容冲突位于 `docs/project_overview.md`，已合并保留双方段落。迁移编号与
  依赖、rollback 目标检查、schema preflight、测试和五份 change 文档均已从原 `0068` 校准为
  `0071`，升级前/后允许 leaf 为 `0070/0071`。历史 RED/GREEN 与旧 reviewer 证据仅作为当时事实
  保留；主线集成后的当前内容尚未复审，不复用旧 fingerprint。
- 集成后本地验证：Release B 专项 `29/29`；Release B + Release A 完整性 + 部署合同组合
  `170/170`；SQLite fresh DB 完成 `0070→0071→0070→0071`，最终单一 leaf 为 `0071` 且新约束名
  正确；Django check、`makemigrations --check --dry-run`、shell syntax、两份 Compose
  `config --no-env-resolution` 与 `git diff --check` 均通过。该主线集成阶段当时未重跑真实
  PostgreSQL；其后本轮 P1 已完成上述 `3/3`。完整 stable 仍未重跑。
- 用户已在方案 `APPROVED` 后明确确认实现；当前仍位于隔离 worktree/branch，未 commit、push、
  PR、部署或访问生产。生产基线继续沿用此前只读证据，不能把本地结果表述为线上已修复。
- Release B 候选已集成 `origin/main@832cc07465a73f2e59947e00e65482b64d39d027`；主线新增
  `0068`、`0069`、`0070` 后，本变更唯一 migration 顺延为
  `0071_historical_calendar_release_b`，依赖当前单一 leaf
  `0070_horse_identity_evidence_commit_receipt`。event 唯一身份切换为非空
  `(race_series, edition_year)`，target 切换为非 superseded `(race_series, year)`；没有 Release C。
- 新增候选镜像 forward/reverse schema preflight，绑定 commit、image ID、`0070/0071` leaf 和显式
  `EXPECTED_PRODUCTION_DB_IDENTITY_SHA256`；deploy 在停服务前执行。通用 rollback 仅允许 B→B，
  checkout/build 目标 image 后运行 forward preflight；reverse 只属于另行审核的跨 schema 恢复。
- v2 repair 以完整 series 为 action，冻结 event/target/path/canonical-link/全部 reverse FK 行级
  ledger；人工 overlay 后才生成独立 v2 manifest/approval。apply 保留 inactive canonical audit，
  verifier 覆盖全局约束，rollback 要求当前 post-state 与 after snapshot 精确相等。
- 首轮独立只读代码审核 session `019fb9a4-86fa-7ca1-b4cc-e5c558258dbc` 提出 `4 P1 + 2 P2`：
  已改为从 `django_migrations` 计算实际 applied leaf；非等价重复边界、缺失 target supersession
  审计、越权 target 字段和 published 无 canonical path 均 fail closed；两类 v2 artifact 目录使用
  原子 no-replace 发布。
- 修订后 SQLite Release B + 相邻完整性回归 `45/45`、部署编排 `117/117`、真实 PostgreSQL
  Release B + Release A 组合 `28/28`。修订前更宽的相邻回归为 `75/75`；两份 Compose config、
  Django check、migration drift、compile/diff check 均已通过。
- 第二轮 read-only reviewer session `019fb9b1-f74c-78b0-92c5-6bc7532291be` 的 `3 P1 + 2 P2`
  也已关闭：rollback 目标镜像保留 target commit label；inventory 排除 superseded audit；新增
  supersession manifest sentinel 并在 apply 时绑定真实 manifest SHA；canonical link 必须与审核
  boundary/identity 精确相等，同时允许多个 duplicate 指向同一 survivor。最终修订验证为 SQLite
  `47/47`、inventory + deploy `159/159`、真实 PostgreSQL `30/30`。
- 第三轮 reviewer session `019fb9bc-b0c8-7c03-afce-f0359f710765` 的 `2 P1 + 1 P2` 已修复：通用
  rollback 现在在 checkout/停服前拒绝缺少 `0071` 的目标，跨 schema 恢复必须走独立审核的停服
  流程；imported target 必须关联 event；series identity review 的冲突键改为 edition year。相关
  Release B + series identity + deploy 组合为 `168/168`（另 `1` 项 PostgreSQL-only skip）。
  50k event + 50k target、500 mismatch/100 series prepare 为 `13.40s`；绑定预检后的 forward/
  reverse DDL 为 `0.086s/0.076s`。临时 PostgreSQL 容器与性能 artifact 已删除。
- 第四轮 reviewer session `019fb9c9-1bd5-7b30-b1a8-fce75de79fc7` 提出 `1 P1 + 2 P2`：已将
  通用 B→B rollback 的错误 reverse preflight 改为目标 image forward preflight；生成的 review
  template 现在只保留 parser 接受的 overlay 字段，并留空 census manifest SHA 供审核者填写；
  target `clean()` 也拒绝再次 supersede 已有下游引用的 survivor。最新真实 PostgreSQL Release B
  专项 `26/26`；SQLite/deploy 组合执行 `144` 项时 `141` 通过、`2` skip，唯一 error 是测试 image
  缺少 `git` 可执行文件，并非断言失败。三项修订仍待最终 read-only re-review。
- 后续全量 read-only reviewer session `019fb9d8-1ee0-7db3-b28f-7a0651a5cef2` 又发现 `2 P1`：
  duplicate identity 现已纳入 `source_refs` SHA，不同上游身份不能判为 exact duplicate；所有
  equivalent duplicate 必须为 `draft`、解除 series，并使用精确
  `release-b-tombstone-<event_id>` slug 后才能创建 canonical link。直接回归 `14/14`，待复审清零。
- 完整 `stable` 为 `4043 tests / 26 failures / 133 errors / 77 skipped`，首个失败是范围外的翻译
  错误文本断言，另有本机缺 `python`、Redis 不可达和 canonical worktree 路径等环境/既有问题；
  不能表述为全绿，也不能与旧 `3989` 集合直接作增量结论。当前只差修订后最终 fingerprint 与
  最终只读复审；无 commit/push/PR/部署或生产授权。

## 2026-08-01 历史赛历 Release B 方案审核通过，等待实现确认

- 已从最新 `origin/main@1cdd066b80861520f60515d3912c0f0a8283b0eb` 创建干净 worktree
  `/Users/mentianlu/.codex/worktrees/release-b-historical-calendar/umanews`，分支
  `codex/release-b-historical-calendar`；Release A evidence worktree 的未提交文档未复制或修改。
- 新建 `docs/changes/enable-historical-calendar-release-b/` 五份方案文档，当前只有 spec/design/
  test/tasks/rollout，无测试、应用代码、migration、commit、push、PR 或生产写入。
- Release A 生产只读基线仍为 `9867 events / 81 mismatch / 0 receipt / 0 active gate`，historical
  backfill/network flags 均为 false；v1 census manifest SHA 为
  `f45b888b78bf38f65c6ed7fdec8b22a79858ebb09fc60af349b1086b53705b46`。
- 进一步只读核验确认 81 mismatch 涉及 14 个 series：12 个香港 series 有同日 duplicate
  boundary，67 个 duplicate candidate 自身也是 mismatch，证明主体是“重复边界 + 连续错位链”而
  不是 81 个独立 duplicate；另有香港同一自然年多届和英国跨年届次。
- mismatch event 的非零依赖为 runner `823`、result `803`、data candidate `162`、
  HorseP0Source `176`、HorseIdentityConflict `782`。Release B 方案因此采用 series-level
  reviewed ledger，默认依赖留在 tombstone，不允许无逐行证据删除或重挂。
- 原 Full reviewer session `019fb93f-3e25-7e71-ac5a-333b1695a8c8` 因持续外部 503 且无法以
  read-only 恢复，没有形成结论。替代 read-only reviewer session
  `019fb946-ae91-7a21-b455-29ce02766fd7` 首轮提出 4 个 P1 与 1 个 P2；经同会话两轮限定复审，
  reverse migration 兼容性、三类互斥 ledger、target supersession 强合同、候选镜像停服前
  preflight 和 81→14 脱敏 fixture 要求均已关闭，最终 `VERDICT: APPROVED`。
- 当前仍只有方案与状态文档，没有测试、应用代码、migration、commit、push、PR、部署或生产
  写入。按仓库工作流，必须在 APPROVED 后取得一次明确实现确认，才进入 RED 与实现。

## 2026-07-31 历史赛事 Release A URL 中央校验 P1 已通过限定复审，证据写回待复审

- 已从 `origin/main@43b81fd3288a1e7b997ffad78d03565327e3d990` 建立隔离 worktree
  `/Users/mentianlu/.codex/worktrees/diagnose-historical-race-calendar-gaps/umanews`，
  分支 `codex/diagnose-historical-race-calendar-gaps`，当前
  `HEAD=43b81fd3288a1e7b997ffad78d03565327e3d990`；原主工作区未触碰。
- Release A 已本地实现：`RaceEvent.edition_year` 保持 nullable，新增统一
  `RaceEventPublicPath` canonical/legacy registry、target supersession 字段与
  `HistoricalRaceCalendarRepairReceipt`；唯一新增 migration 为
  `0067_historical_calendar_release_a.py`。Release B 的 series/edition 约束切换和 Release C
  的 non-null/自然年 check migration 均未生成。
- 前台已实现历史年份“重点”按 G1/G2 等级族筛选，当前年继续沿用运营重点；显式 `year/q`
  使用带筛选 fingerprint 的稳定双向分页，不再截断于最早 40 条；legacy 公共路径仅对已发布
  event 返回 301 到 canonical，sitemap 只输出 canonical。
- 年度参赛马 collector 已把 `-`、`–`、`—` 等占位符统一归一为空马号，并按真实马号、
  profile/source identity、规范化马名逐级回退；正式输出要求 fresh root，旧 checkpoint/
  tool fingerprint 不兼容时明确拒绝。summary 新增缺号、profile fallback、name fallback、
  ambiguity gap 和真实马号冲突计数。
- 已实现全地区离线 `prepare/apply/verifier/rollback` 工具：prepare 为零数据库写入并生成
  census、manifest、review CSV、报告与 approval 模板；apply 绑定 approval、actor、
  maintenance evidence、action scope 和 receipt；verifier/rollback 均按精确 SHA 与状态
  fail closed。该工具尚未对生产运行 census 或 apply，香港及其他地区存量数据均未改写。
- 本地验证：最新主线程 Django 复验 `205/205`，collector 离线套件 `101/101`；URL + detail
  子聚焦 `166/166`、总门禁子聚焦 `68/68`。Django check、
  `makemigrations --check --dry-run`、migration graph/漂移检查及 `git diff --check` 均通过。
  完整 `stable` 为 `3989 tests / 25 failures / 54 errors / 72 skipped`，已确认包含环境或既有
  失败（测试子进程缺少 `python` PATH、Redis 不可达、时效测试、旧 CSV 门禁及
  migration-owner guard），因此不能声称全量回归全绿；50k 数据集性能等未执行门禁仍未完成。
- 新增 `test_historical_calendar_release_a_postgres.py`，在隔离真实 PostgreSQL 上连续两轮
  `5/5` 通过。fresh migrate 为 `7.96s`，`0066→0067` 为 `0.346s`，
  `0067→0066` 约 `0.463–0.475s`。shared/exclusive advisory lock 以实际 `pg_locks`
  未授予记录确认等待，观测约 `0.024s`；排队 writer 在取锁后重新检查 active gate 并被拒绝，
  gate exit 后 writer 恢复，无死锁、无陈旧提交。
- 同一 PostgreSQL 验收还覆盖 public path 冲突整笔回滚、event/path `CASCADE`、receipt
  manifest unique 与单 active gate 条件唯一约束。临时容器
  `umanews-histcal-pg-accept-20260731-a1` 及 tmpfs 已删除，未改变其他容器。
- 最终扫描新增的 `1 P1 + 1 P2` 已修复：public path FK 删除语义改为 `CASCADE`；orphan ledger
  通过 controlled path、symlink rejection 与 `O_NOFOLLOW` descriptor 单次读取，同一 bytes
  用于 digest/JSON，避免 TOCTOU。
- 本轮另两项 finding 已修复：current-year descriptor 显式区分 public year 与 edition year，
  slug、query 和 identity 均只使用 public year，真实跨届次记录仍强制提供 descriptor；apply/
  rollback 只在事务成功提交后的 `transaction.on_commit` 失效 public cache，失败事务和 existing
  receipt 幂等重入均不清缓存。
- 最新三项 finding 已实现：apply/rollback 强制要求
  `HISTORICAL_RACE_BACKFILL_ENABLED=true`，existing receipt 重入也不能绕过；prepare/verify
  保持只读且不受该写开关影响。跨届次 `authority_url` 必须是有效 HTTPS、存在 hostname、无凭据/
  fragment，合法 query 原样保留。detail `edition_year` 仅在字段缺失时回退，显式值必须是非
  bool 的 `int` 且位于 `1..9999`。
- 最新直接 P1 已修复：`race_event_years.validate_authority_url()` 成为跨届次证据的中央 URL
  validator，年份写入校验与 repair classifier 均复用同一 HTTPS/hostname/无 credentials/
  fragment/whitespace 合同；classifier 不再自行解析 URL。直接 RED 捕获 fragment 被错误批准，
  修复后 integrity/tooling/year/review/descriptor 聚焦 `76/76`。同一 reviewer 限定复审已确认
  `URL central validator P1 CLOSED` 并给出 `APPROVED`。
- detail clean RED 没有保存：首次失败被陈旧 SHA fixture 提前遮蔽，修正 fixture 后直接进入
  GREEN；因此只记录现有行为与 `166/166` 证据，不把该过程追溯表述为已取得 clean RED。
- 同一独立代码 reviewer 第二轮限定复审已给出 `VERDICT: APPROVED`，前轮
  `1 P1 + 3 P2` 均关闭。原生命令
  `codex review -c 'sandbox_mode="read-only"' --uncommitted` 完成且 exit `0`；review
  前后 fingerprint 均为
  `88c53c265cd0de5748438648f637e0975e75389ee8b636ab1c3848f68d033eb3`。
  approved parent 为 `43b81fd3288a1e7b997ffad78d03565327e3d990`，approved content 为
  `1a31d68e51d8aa4ce28249c4feb2f3fa82517d9277818da063214972fda9646f`。该 content hash
  不包含其后的 P1/P2 加固、PostgreSQL 测试或事实文档，已由后续限定复审取代。
- 最新限定复审原生命令以 read-only 模式 exit `0`，结论 `APPROVED`；pre/post fingerprint
  均为 `91fed97e63acacbb28ee8fed717edc049d1812f0dead8465c5a6f139bd110a39`，approved parent
  为 `43b81fd3288a1e7b997ffad78d03565327e3d990`，approved content 为
  `b3353358647cd7b842a5a16326deee25ecc09485f37f7cd6974ed32b53868d2e`。该 content 只覆盖
  本次 evidence-only 文档写回前的快照；文档写回后过期，须复用同一 reviewer 做 evidence 复审。
- reviewer 另记 non-blocking P2：apply/rollback 与 maintenance exit 存在理论锁顺序反转。
  真实 PostgreSQL `5/5` 两轮未复现，但也未做专门的并发 exit 验证，因此该项未关闭，保留为
  后续任务，不能报告“锁顺序风险已验证关闭”。
- 详细诊断与设计见
  [historical_race_calendar_gap_diagnosis_20260731.md](historical_race_calendar_gap_diagnosis_20260731.md)
  和
  [repair-historical-race-calendar-integrity](changes/repair-historical-race-calendar-integrity/)。
  下一门禁是同一 reviewer 对本次 evidence-only 文档增量的复审；发布授权尚未请求或取得。当前仍无
  commit、push、PR、部署或任何生产 census/apply 权限。

## 2026-07-31 单年度分级赛 full-network 443 修复已离线发布

- 2025 正式运行连续 6 个有界 workflow run 均停在
  `https://umafans.run/sitemap.xml`；最后 checkpoint 为 `request_count=30`、
  `queue=1`、`visited=0`、`discovered=0`，没有最终 artifact。该状态是可验证的
  transport safe-stop，不是数据为空或运行成功。
- 生产只读核验确认宿主 Docker 映射 `80:80` 与 `443:443`，但 Nginx 生效配置只有
  `listen 80`；443 server block 与证书配置仍为注释。`http://127.0.0.1/sitemap.xml`
  使用正式 Host 返回 200，HTTPS 握手为 unexpected EOF。现有证书为
  `CN=47.239.167.86` 的自签名证书，不是可直接启用的正式域名证书。
- 根因是研究 workflow 和 collector 默认来源错误写成 HTTPS；URL scheme 自动选择 443，
  Compose 端口映射又不等于容器内存在 TLS listener，因而每次均在首个 sitemap 请求失败。
- 已发布修复把正式 workflow 与 collector 默认来源对齐为 `http://umafans.run/`，并在保持
  UmaFans 精确 host、无凭据、无显式端口、规范 path/query 门禁的前提下允许 HTTP/HTTPS
  且保留原 scheme。sitemap race URL 识别改为按受控 URL 的精确年份 path 判断，不再写死
  `https://`；地区 manifest 的 durable contract 与示例同步改为当前 HTTP exact URL，scheme
  继续属于清单 identity；所有派生 sitemap/race/profile URL 与 redirect 也必须保持本次
  base scheme。旧 HTTPS checkpoint 因 base URL identity 不同，不允许续跑；修复发布后的
  首次正式运行必须 fresh dispatch。
- 真实 RED 同时报出 HTTP scheme 被拒和 workflow 仍使用 HTTPS；GREEN 为 collector
  `87/87`、workflow `12/12`、全局 workflow contract `26/26`。独立 review 先后发现地区
  manifest scheme miss 与派生 URL 可跨回 HTTPS 两项直接回归，均已补测试并修复。本机通过正式 HTTP origin
  用 2 次只读请求解析 sitemap，发现 2025 race URL `1075` 个。
- 冻结内容提交 `1fd83de41c45ed0bd974a08804b4d2113579b076` 经
  [PR #53](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/53) 合并为
  `main@cd42cb4d8ceb67b6c16ab4ecc058a066516a7cb5`；PR tests success。
  默认离线生产 dispatch
  [30575216646](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/30575216646)
  在该 main head 上 success，tests job `17s`。synthetic artifact
  `30575216646-1-synthetic-checkpoint-0` 为 `12959` bytes，digest
  `sha256:3ea2ad2795db806549128033d839e58e5a027b78604539056abedef8029296f8`；
  `full_network=false`，网络 DAG 按设计 skipped。
- 本次生产部署只发布 GitHub research workflow；未 pull、重建或重启
  `/opt/umanewsbot`，未修改 Nginx/TLS、迁移或写生产数据库。2025 full-network fresh
  dispatch 尚未执行。

## 2026-07-30 单年度分级赛研究执行面已离线发布，full-network 仍关闭

- 已从最新 `origin/main@6d073dc07cb29201bbc922255923820c872a0467` 建立独立干净
  worktree `/Users/mentianlu/.codex/worktrees/graded-race-participants/umanews`，分支
  `codex/generalize-graded-race-participants`；原主工作区的大量其他会话改动未触碰。
- `collect-yearly-graded-race-participants` 已按获准方案完成离线实现：新增显式单年度
  collector、83 项聚焦自动化测试、11 项 workflow 静态合同测试、collector/region manifest
  说明和默认离线的 GitHub Actions workflow；从旧研究分支只移植 checkpoint、稳定分片、
  fan-in 等通用基础，不引入旧状态文档或 Wikipedia/Wikidata 阶段。
- 八地区为日本、中国香港、美国、英国、法国、澳大利亚、德国和中东；中东 v1 固定阿联酋、
  沙特阿拉伯、卡塔尔和巴林。当前公开模型把新增地区归为 `other`，实现以年度 exact race URL
  classification manifest + SHA 补足；未完整分类时只报告 `classification_incomplete`，不猜地区。
- “参赛”只接受正式结果表中可证明已经起跑的受控状态；退赛/non-runner 和未知状态均不计入，
  后者进入 unresolved 复核。中文、日文为尽力字段；除日本和香港外英文为强制字段，并与其他
  名称问题按正交状态和可组合 issue codes 报告。
- 独立方案 reviewer 首轮提出 4 个 P1：未知状态误算参赛、名称完整性单枚举冲突、generic
  `other` profile 同名误配、地区清单不完整时误报零赛事；第二轮补充 1 个直接 P1，要求把
  `profile_unresolved` 纳入枚举和 complete 阈值。三轮同一 reviewer 复审后最终
  `VERDICT: APPROVED`，无剩余直接 P0/P1。
- 测试先行证据：新增测试在 collector 尚不存在时为
  `14 tests / 14 failures / 0 errors`，旧 checkpoint 基础层离线回归为 `17 tests / OK`。
  第一至第二十轮 findings 修复后的历史回归分别为 collector `32/32`、`39/39`、`46/46`、
  `49/49`、`53/53`、`56/56`、`60/60`、`64/64`、`66/66`、`69/69`、`70/70`、`71/71`、
  `73/73`、`75/75`、`76/76`、`77/77`、`79/79`、`81/81`、`82/82`；当前离线复验为
  collector `83/83`、
  workflow 静态合同 `11/11`、
  现有 workflow contract `26/26`，相关文件 `py_compile` 和 checker 直接检查通过；synthetic
  首次以 `75` 安全停止，
  在同目录移除 `--limit` 后 exit `0`、`byte_equivalent=True`，并精确生成 7 个最终文件；
  `git diff --check` 通过。
- 独立代码 reviewer 首轮结论为 `REVISE`，共 `7 P1 + 4 P2`。findings 1–10 涵盖赛果状态、
  checkpoint 恢复、safe-stop、profile identity/merge、coverage、名称 issue、请求预算及
  workflow 显式预算等直接路径；P2-11 指出为使合同测试通过而改写赛事日历历史实际 review
  命令会破坏审计真实性。当前 findings 1–11 均已完成本地修复：历史记录恢复实际命令，checker
  只豁免内容精确且明确标注为旧规则、不可执行的审计块；当前操作说明中的裸命令仍由 mutation
  测试拒绝。
- 同一 reviewer 第二轮限定复审仍为 `REVISE`，新增 `2 P1 + 3 P2`：resume 必须累计而非重置
  请求预算；暂定赛果不得作为正式参赛证据；profile 搜索须支持受控原名别名；搜索须安全遍历
  分页；coverage 必须逐地区计算，不能用合并状态代替。五项均已完成本地修复并纳入当前
  候选。
- 同一 reviewer 第三轮限定复审仍为 `REVISE`，新增 `4 P1 + 2 P2`：网络请求计数改为
  crash-safe write-ahead ledger；profile 详情必须二次核验地区/country；非 live 但已人工审核
  的正式赛果可作为证据；provisional 必须形成结构化 error、partial coverage/outcome；HTTP
  状态须区分 permanent/retryable，profile 404 单独处理；`errors.json` 必须包含去重且可组合的
  名称完整性问题。六项均已完成本地修复并纳入历史 `46/46`。workflow 同步加入 ledger
  artifact/restore 合同，并明确 hard cancellation 或 runner timeout 无法保证 post-step 上传。
- 同一 reviewer 第四轮限定复审仍为 `REVISE`，新增 `3 P1`：pending conflict 必须保持
  non-final；profile 详情缺少真实详情名时禁止以搜索名 fallback；provisional 必须成为终态
  `evidence_gap`，并由正式 DAG 继续产出 partial 的 7 个最终文件。三项均已完成本地修复；
  workflow 同步接受 `evidence_gap`、修正 races index 路径并新增完整离线 harness，纳入历史
  collector `49/49` 与 workflow `11/11`。
- 同一 reviewer 第五轮限定复审仍为 `REVISE`，新增 `1 P1 + 3 P2`：真实 `HttpClient`
  必须严格且仅允许受控 `/horses/?q=&page=` 搜索查询；coverage 中 error 必须优先于已有
  occurrence；unresolved 结构化错误必须保留 region、country 和 source URL；零行 CSV 仍须
  输出固定表头。四项均已完成本地修复并纳入历史 collector `53/53`。
- 同一 reviewer 第六轮限定复审仍为 `REVISE`，新增 `1 P1 + 1 P2`：profile country
  事实中的受控 ISO alpha-2/alpha-3 国家代码必须归一到规范 country，并拒绝非目标或伪代码；
  当正式结果全部为未知状态时，race 必须成为终态 `evidence_gap`，逐行保留马名、原始状态、
  region、country 和 source URL 证据，并由完整 DAG 产出 partial 7 文件。两项均已完成本地
  修复并纳入历史 collector `56/56`。
- 同一 reviewer 第七轮限定复审仍为 `REVISE`，新增 `2 P1 + 2 P2`：checkpoint 恢复必须以
  已验证的 index/request ledger 为权威并可安全重建 progress；共享 profile URL 必须逐条校验
  occurrence identity；`region_unresolved` 必须进入 source manifest、结构化 errors 和 partial
  coverage；中东 occurrence 即使 region 相同也必须逐 country 检查冲突。四项均已完成本地修复
  并纳入历史 collector `60/60`。
- 同一 reviewer 第八轮限定复审仍为 `REVISE`，新增 `2 P1`：races discovery 与 profile
  分页必须共享同一 stage monotonic deadline；discovery 必须把 queue、visited、
  discovered URLs、inflight 与请求计数精确写入 `discovery_progress.json` 并可 resume；
  profile 分页必须逐页检查 deadline，且只有搜索第一页 404 可视为空结果，后续页 404 必须
  fail closed。修复同时由 workflow 合同锁定：即使尚无 run manifest，也上传并恢复
  discovery progress/request ledger。上述修复已纳入历史 collector `64/64`、workflow `11/11`。
- 同一 reviewer 第九轮限定复审仍为 `REVISE（P0=0 / P1=0 / P2=1）`：discovery 的
  `RetryableHttpError` 在重试耗尽后必须保存精确 progress/request ledger 并以 exit `75` 安全
  停止，resume 后从 inflight URL 精确继续；确定性 4xx 仍须保持 permanent error，不得误转为
  safe-stop。唯一 P2 已完成本地修复并纳入历史 collector `66/66`。
- 同一 reviewer 第十轮限定复审仍为 `REVISE（2 P1 + 1 P2）`：sitemap discovery 必须按
  `sitemapindex`/`urlset` 文档类型解析并只接收精确目标年份 race URL；generic `other` profile
  必须使用详情页多语 alias 与 occurrence alias 的受控交集，并结合出生年/country 等附加
  identity 事实；coverage 只能由实际 in-scope graded race 证据驱动，Listed-only 不得标记
  `covered`。三项均已完成本地修复并纳入历史 collector `69/69`。
- 同一 reviewer 第十一轮限定复审仍为 `REVISE（P1=1）`：Australia/Germany generic
  `other` profile 在 alias 相交且出生年份匹配时，即使详情未提供 country 也可满足附加身份；
  详情一旦提供 country 就必须与 occurrence 一致，否则 ambiguous；Middle East 仍强制要求
  country 证据。唯一 P1 已完成本地修复并纳入历史 collector `70/70`。
- 同一 reviewer 第十二轮限定复审仍为 `REVISE（P1=1）`：direct profile URL 与搜索候选必须
  共用同一 group validator，对 canonical group 内每条 occurrence 分别验证 alias、region、
  country 和 birth year；任一 occurrence 冲突时整组必须 fail closed，并保留逐条 identity
  review，不能只验证代表行。唯一 P1 已完成本地修复并纳入历史 collector `71/71`。
- 同一 reviewer 第十三轮限定复审仍为 `REVISE（1 P1 + 1 P2）`：搜索路径必须对 canonical
  group 的全部受控 aliases 按确定性顺序逐一 query，汇总候选并按 canonical profile URL 去重，
  不能只查代表 alias；profile 冲突错误必须同时保留 expected/actual 两侧的 aliases、region、
  country、birth year，以及 profile URL 与 `conflict_fields`。两项均已完成本地修复并纳入历史
  collector `73/73`。
- 同一 reviewer 第十四轮限定复审仍为 `REVISE（1 P1 + 1 P2）`：profile URL 必须在
  validate、search candidate、direct fetch、group key、merge 和输出全链路严格 canonicalize
  为 `/horses/<id>/` trailing-slash 形式，禁止等价 URL 重复；Middle East 的 expected/actual
  country 缺失、非受控或不一致都必须 fail closed，并在 review/errors 中保留双侧 raw/canonical
  country 与明确 reason。两项均已完成本地修复并纳入历史 collector `75/75`。
- 同一 reviewer 第十五轮限定复审仍为 `REVISE（P1=1）`：profile URL 必须按未规范化的原始
  path 验证为唯一真实路由 `/horses/<positive-integer>/`，只允许补齐缺失的末尾 slash；零值、
  负数、slug、重复 slash、dot segment、percent-encoded ID、额外 path、query 和 fragment 均
  必须拒绝，并在 canonical key、direct/search、merge 等入口一致执行。synthetic 也已改用合法
  数值 ID。唯一 P1 已完成本地修复并纳入历史 collector `76/76`。
- 同一 reviewer 第十六轮限定复审仍为 `REVISE（P1=1）`：profile URL 验证必须直接检查
  原始 `str`，不得先做 NFKC 或 trim；前后或 path 内的 Unicode whitespace、Unicode control、
  全角字符、percent encoding 等绕过均须严格拒绝，只接受 ASCII 正整数
  `/horses/<id>/` 路由，并在全部身份入口一致执行。唯一 P1 已完成本地修复并纳入当前
  collector `77/77`。
- 同一 reviewer 第十七轮限定复审仍为 `REVISE（2 P1）`：所有 profile URL 原始字段必须
  不经预先 normalize 直接进入严格校验；race/profile HTML 的 `href` 必须通过专用严格
  resolver，禁止 `urljoin` 先折叠非法相对路径。HTTP profile 请求必须禁用自动 redirect，
  对原始 `Location` 先做严格 href 解析并限定同 host，响应 final URL 也必须直接执行严格
  profile URL 校验。两项 P1 均已完成本地修复并纳入历史 collector `79/79`。
- 同一 reviewer 第十八轮限定复审仍为 `REVISE（P1=1）`：absolute profile href、redirect
  `Location` 与响应 final URL 的 hostname 必须分别与来源页面或原始 profile 请求 hostname
  精确一致；`umafans.run` 与 `www.umafans.run` 虽都在 allowlist 内，也不得相互切换。唯一 P1
  已完成本地修复并纳入历史 collector `81/81`。
- 同一 reviewer 第十九轮限定复审已给出 `VERDICT: APPROVED`，P0/P1/P2=`0/0/0`，session
  `019fb2f6-da26-7463-81b3-0b3c52ed4cf0`。审阅时基线 HEAD 为
  `6d073dc07cb29201bbc922255923820c872a0467`，批准 fingerprint 为
  `89a8021db567eaaed7003680cd85377ca04ec7ee08d48168ef3212cbcb51d262`，content manifest
  为 `cfb5630c1dc29a0d04b62816a4ce2f296640308e838614d96d57af2d6fbce0a1`；pre/review/post
  均 exit `0` 且 reviewer 全程只读。以上哈希只标识第十九轮审阅时快照；本次状态文档写回会
  改变候选内容，仍须对更新后的完整差异执行一次最终只读确认并冻结新 fingerprint，不得把上述
  fingerprint 称为最终发布指纹。该结论现仅作为历史审阅快照，不代表当前候选仍为
  `APPROVED`。
- 同一 reviewer 第二十轮最终确认结论为 `REVISE（P2=1）`：当标准五地区——日本、中国香港、
  美国、英国、法国——的 profile region 已明确匹配时，profile country 可以缺失；若 country
  存在但与 occurrence 冲突，仍须 fail closed。Australia、Germany、Middle East 的附加
  country/birth-year 证据规则不放宽。唯一 P2 已完成本地修复并纳入历史 collector `82/82`。
- 同一 reviewer 第二十一轮最终确认仍为 `REVISE（P2=1）`：profile country 事实必须显式区分
  `missing`、`controlled`、`uncontrolled`；非空但未知的 country 必须保留 raw 事实，不能按
  region 回填为受控 country，并须 fail closed。标准五地区仅在 country 真正 `missing` 且
  region 明确匹配时可通过；Australia、Germany、Middle East 的附加证据规则不放宽。唯一 P2
  已完成本地修复并纳入当前 collector `83/83`。
- 同一 reviewer 第二十二轮最终确认已给出 `VERDICT: APPROVED`，P0/P1/P2=`0/0/0`，session
  `019fb360-79a8-7aa0-8064-b5a604bc7c7e`；pre/review/post 均 exit `0`。approved parent
  `6d073dc07cb29201bbc922255923820c872a0467`，approved fingerprint
  `21a32cf22ef48207d44880d21ec2059ccdd711fe6758a80ee60cb069277f61ce`，
  content manifest SHA-256
  `35672bc11172cd5ca7372da53d3ff38de7d31157c952361822c55de27adeffb1`。该最终批准先于随后
  用户授权的 commit/push/PR/merge 与离线生产部署。
- 用户已明确授权 commit/push/PR/merge 与本变更生产部署。feature commit
  `34626865d5cfe336a97fd7a375238e76c8afbec2` 经
  [PR #50](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/50) 合并；merge commit
  `d47dd513e666874243815c2feee7cc755ce483ba`，合并时间
  `2026-07-30T15:14:21Z`，PR `tests` check success（15 秒）。
- 本变更只改变 GitHub research 执行面，不改变 Django runtime、migration 或数据库 schema。
  本次生产部署以 workflow 进入 default `main` 并由 default branch 成功完成一次
  `full_network=false` dispatch 为准：
  [run 30555834994](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/30555834994)
  使用 head `d47dd513`，conclusion=`success`；`tests` job 13 秒，races/profiles/merge/finalize
  因离线模式按设计 skipped。artifact `30555834994-1-synthetic-checkpoint-0` 大小
  `12957` bytes，根代理已核验其包含 `run_manifest.json`、synthetic report 和 final 严格
  7 文件。该成功只证明默认分支离线合同，不证明任何真实年度数据覆盖。
- 生产服务器 `/opt/umanewsbot` 的只读 preflight 为 HEAD `be1c89bf`，存在长期 dirty deploy
  scripts 和运行产物；容器健康、internal healthz、`manage.py check`、公网 direct IP/Host
  及 `--resolve` healthz 均通过。为避免覆盖服务器长期 dirty 状态，本次未执行 `git pull`，
  未重建或重启容器、未迁移、未写数据库；因无数据库变更，未创建 DB backup。不得宣称服务器
  代码 HEAD 已更新到 `d47dd513`。
- 当前准确状态：
  `implementation committed and merged / default-branch offline workflow deployed /
  final code review APPROVED / no full-network collector run /
  server HEAD unchanged / no container restart, migration, DB write or backup`。
  `full_network=true` 单年度 run 未获授权、未执行，不能由本次 Git 发布或离线部署授权推导。

## 2026-07-30 Celery race-live P0 已在关闭态完成发布与五轮观察

- 初始实现 `611c6aab` 经 PR `#46` 合并为 `main@7cd144ab`。首次生产 `prepare` 成功，
  但 `start-beat` 在启动 Beat 前因 Django auto-import banner 污染严格 machine snapshot
  而 fail closed；没有清队列、启动 Beat/race-live worker 或执行业务写入。
- final fix 只把 snapshot 改为 `manage.py shell --no-imports -c`，parser 不放宽；部署合同
  `33/33`、四组聚焦 `64/64` 通过。同一 reviewer 限定复审 `APPROVED`，冻结 fingerprint
  `4c785e74...a000` 与 content manifest `a17ac407...f416`；用户授权后
  `INDEX_TRANSITION_OK`，commit `24a49c2a` 经 PR `#47` 合并为
  `main@be1c89bf`。
- 生产已 fast-forward 到 `be1c89bf` 并重新完整执行 `prepare`。普通 worker 在
  `active=0 / reserved=0` 后才停止；historical runner preflight 为 `migration_safe`，
  Django check 通过，两次 migration plan 为 `0/0`，脚本返回 `CANDIDATE_READY`。
  本窗口 rollback tag
  `umanewsbot:rollback-race-live-p0-20260730T043615Z` 指向上一候选
  `sha256:17562c52...acea7`；最终候选为
  `sha256:c3197503...b5f5`。
- `start-beat` 基线为
  `celery=0 / race_live=6574 / selector=0 / monitor=6574`。五轮普通队列依次为
  `36/35/30/28/30`，`race_live=6574 / selector=0 / monitor=6574` 每轮均未变化；
  每轮 Beat/web/worker running 且 image 一致，普通 worker 只监听 `celery`，
  `race_live_worker` 未运行，healthz/ping 正常，Beat 日志没有两个关闭态目标。
- 脚本外终验：生产 HEAD=`be1c89bf`，web/worker/beat 均为
  `sha256:c3197503...b5f5`；Beat running，`race_live_worker=Created`；三个开关与候选
  settings 均为 `false/false/disabled`，两个目标 schedule entry 不存在；普通 worker
  PID 1 queue 为 `--queues=celery` 且 ping 正常。队列为
  `celery=23 / race_live=6574 / selector=0 / monitor=6574`，最近十分钟目标 Beat 日志
  计数 `0`；容器内、本机 Nginx、两个正式 HTTP 域名 healthz 均为 `200`，OneBot running，
  最近 15 分钟无 OOM。
- 临时 `/swapfile-umanews-p0-20260730` 仍启用、总量/空闲量均为
  `2097148 KiB`，未写 fstab；最终 `MemAvailable=1576148 KiB`，仅略高于 `1536 MiB`
  部署硬门，禁止在当前负载下顺带移除。停用和删除 swap 仍须单独授权。生产进入窗口前已有
  的 `12` 个 deploy 脚本 mode-only 差异原样保留。完整事实见
  `docs/changes/harden-celery-p0-admission/release_report.md`。

## 2026-07-30 Celery race-live P0 部分部署停在安全检查点，修复待复审/重新授权

- 初始实现 commit 为 `611c6aab`，已通过 PR `#46` 合并为
  `main@7cd144ab`。生产 `/opt/umanewsbot` 从 `4221affa` fast-forward 到
  `7cd144ab`；进入窗口前已有的 dirty 只包含 `12` 个 deploy 脚本 mode-only 差异，已原样
  保留，没有清理或覆盖。
- 生产首次只读预检确认 Docker Compose `5.1.2`；三个开关精确为
  scheduler=`false`、monitor=`false`、runner=`disabled`；
  `race_live_worker` 为 `Created`。首次 Celery active/reserved/scheduled 均为 `0`，
  `celery` 队列为 `0`；`race_live` 从首次观察的 `6055` 增至 prepare 前 `6574`，逐项均为
  `monitor_race_live_sla_task`。
- 首次资源门禁以 `MemAvailable=867284 KiB`、`SwapFree=0 KiB` 正确返回 NO-GO。经用户对
  该资源维护动作另行授权，生产创建并启用
  `/swapfile-umanews-p0-20260730`，大小 `2 GiB`、mode `0600`，未写入 `/etc/fstab`；
  普通 worker 在空闲状态下优雅重启，临时停止的 OneBot 已恢复为 running。
- `prepare` 随后成功到达 `CANDIDATE_READY`：drain 中观察到 active `2` 自然归零，没有
  revoke 或清队列；旧 image
  `sha256:7d730634...8774` 已保留为
  `umanewsbot:rollback-race-live-p0-20260730T030255Z`，候选 image 为
  `sha256:17562c52...acea7`。两次 migration plan 均为 `0`，候选 settings 保持关闭；
  web/worker/nginx、内外 healthz 均为 `200`，Beat 为 exited，
  `race_live_worker` 仍为 `Created`。
- `start-beat` 在真正执行 `up beat` 前 fail closed：Django shell 将
  `105 objects imported automatically (use -v 2 for details).` 写入 machine queue
  snapshot stdout，严格 parser 拒绝该输出。失败恢复后 OneBot 为 running、Beat 仍为
  exited，未完成五轮观察，`race_live` 后验仍为 `6574`；没有清理、迁移或消费积压。
- 当前本地分支 `codex/fix-p0-queue-snapshot-output` 已按真实 RED/GREEN 只把 machine
  snapshot 调用改为 `manage.py shell --no-imports -c`，未放宽 parser。部署合同
  `33/33 / 56.236s / exit 0`，四组聚焦
  `64/64 / 57.693s / exit 0`；Django check、migration drift、`sh -n` 与
  `git diff --check` 均通过。
- 当前不是发布成功：生产仍运行不含上述 stdout 修复的候选 image，Beat 保持 exited。
  下一道门禁是复用同一代码 reviewer session 对 final fix 限定复审，并针对受审版本重新
  取得发布授权；之后必须拉取已审 final fix，重新运行 `prepare` 构建精确最终 image，再运行
  `start-beat` 完成五轮。禁止直接热补丁或手工启动 Beat。完整事实见
  `docs/changes/harden-celery-p0-admission/release_report.md`。

## 2026-07-29 赛事新闻质量治理已合并上线（开关全关，shadow 观察中）

- PR `#42` 已合并为 `main@8440b897` 并部署生产：曝光治理（`RaceNewsExposure` 两席状态机、
  首页 DB 层过滤、窗口 QQ exposure/quota/delivery 原子绑定、人工头条曝光同步）与术语一致性
  （`TermMappingEvidence` 证据门禁、canonical 门禁 fail-closed、`TermConsistencyManifest`
  DB 持久化 + 单事务 CAS commit/rollback）。
- 合并时 main 已占用 migration `0060–0062`，本组迁移顺延为 `0063–0066` 并已在生产应用。
- 部署过程一次异常：脚本在 collectstatic 前被 SIGKILL（exit 137，主机内存压力），已手动补跑
  collectstatic 与 worker/beat 恢复；nginx 因缓存旧 web 上游 IP 短暂 502，restart 后恢复。
- 验证：migrate --plan 空、Django check 通过、全部 6 容器 Up、内外 healthz 与首页 200；
  `TERM_CONSISTENCY_ENABLED/ENFORCE=False`、`RACE_NEWS_EXPOSURE_ENABLED=False`、
  shadow 均为 True。当前为 shadow 观察阶段，灰度顺序见 deploy_runbook 顶部。
- 下一轮：观察一个完整赛事窗口的 shadow 输出后，按 runbook 顺序逐项开启 enforce；
  历史术语修复与曝光回填均需独立 dry-run 审核与单独授权。

## 2026-07-28 赛事日历默认比赛日窗口已上线生产

- 已从最新 `origin/main@7385f59a` 建立独立干净 worktree
  `codex/fix-race-calendar-default-date-window`；方案五文档与 Claude 实施交接见
  `docs/changes/fix-race-calendar-default-date-window/`。
- 根因：默认查询使用“北京时间今天前后 30 个连续自然日”，再按日期升序截取前
  40 场赛事并由这批赛事反推日期栏；2026-07-27 的下界因此正好是 2026-06-27，密集赛事
  会让 40 场上限在 2026-07-19 左右耗尽。不是硬编码日期或动态页面缓存。
- 已按已审方案实现：新增 `stable.services.race_calendar`（`select_balanced_race_dates`
  纯函数与两条有界 distinct 日期聚合的 `public_default_race_date_window`）；view 以
  `Asia/Shanghai` 今日一次性贯穿锚点、分组、状态标签与模板标记；默认模式取今日→最近
  未来→最近历史锚点并平衡出最多 11 个实际比赛日；保留 40 卡上限并以每日期代表赛事
  优先保证每个日期至少一卡；移动端默认锚点以只改 `scrollLeft` 的最小脚本水平居中；
  非法/不完整 cursor 安全回退默认模式；year/q/cursor 显式模式语义不变。无迁移、无配置、
  无生产数据写入。
- 测试先行的真实 RED/GREEN 均已取得：新增
  `stable/test_race_calendar_default_date_window.py` 41 个用例（2 个规定 RED 因目标
  窗口未实现失败，实现后 41/41 GREEN）；既有日历测试窄改 4 处（预算 8→10、12→14、
  20→22，A8 日期待定改显式模式，live read-gate 日历用例补 `local_date`），A6 断言
  按新锚点标记放宽为 `class="today anchor"`。
- 主线程验证通过：窗口聚焦 + responsive 62/62；read-gate 日历用例 4/4；page
  regression/navigation 44/44；`test_realtime_race_results` 9 个失败与
  `RaceEventPageMVPTests` 3 个失败均经 stash 基线对照证实为改动前既有失败；
  Django check、`makemigrations --check --dry-run`、`git diff --check` 通过。
- 查询预算实测（基线 → 改后，均为 +2 条有界日期聚合）：轻量默认 3→5（≤10）、
  40 卡 live 12→14（≤14）、40 卡 official 12→14（≤22）。
- 真实浏览器验收通过：1440px 11 个比赛日全可见；390px 与 320px 锚点居中于日期轴
  （中心偏移 -12px）、仅水平滚动、纵向位置不跳、无横向 overflow、G1/G2/G3 徽标
  42×42；显式 cursor/q 模式无锚点、无定位脚本、scrollLeft 为 0；控制台唯一错误为
  开发环境 favicon 404（与本改动无关）。
<!-- WORKFLOW_CONTRACT:HISTORICAL_REVIEW_COMMAND:START -->
- 历史命令审计标记（旧规则下的历史事实，非当前可执行指令）：`codex review --uncommitted`；仅记录当时实际命令，不授权或指导再次执行。
<!-- WORKFLOW_CONTRACT:HISTORICAL_REVIEW_COMMAND:END -->
- 代码复审与发布：首轮独立 reviewer（Claude 协调会话，使用上述当时实际命令）
  REVISE 的两项 P2（NULL 发走时刻排序对齐生产 PostgreSQL NULLS LAST；状态文档失实）
  已修复并经同会话复审 APPROVED。此后应用户要求追加的全新 Codex 独立审查
  （session `019fa932-ca46-7b23-a2d6-c9fc9381cca7`）首轮 REVISE 的 1 项 P2（状态文档
  标题提前）修复后，同会话限定复审 APPROVED，冻结 approved content hash
  `632eb5258c…b66e57`。用户针对该 fingerprint 明确授权发布；staging 校验
  `INDEX_TRANSITION_OK`（受审内容零漂移）后合并 PR `#43` 为 `main@c8508b4e` 并部署生产
  （新镜像 `umanewsbot:prod`=`b7b797467022`，回滚 tag
  `umanewsbot:rollback-pre-race-calendar-20260728T200132Z`）。生产验证全部通过：
  内外 healthz 200，`/races/` 日期栏为 11 个实际比赛日并以当天 2026-07-29 为唯一锚点，
  显式 cursor/year/q 语义不变，390px/1440px 真实浏览器正常，零迁移零业务数据写入。
  完整发布事实见本目录 `release_report.md`。

## 2026-07-28 最近赛事赛果定时审核已发布，首轮暴露来源路由缺口

- 主功能 PR `#39` 合并为 `main@dd35038f`；生产首次补跑因 coalesced slot 的
  `datetime` 直接写入 JSONField 而在联网前失败。Beat 随即停止、两个功能开关恢复
  `false`，业务基线保持 `RaceEventResult=92223`、已结束赛事 `9419`、赛前赛事 `443`，
  四张新治理表均为 `0`。
- 窄修 PR `#40` 合并为 `main@ca22c9fa`，只把 JSON 摘要中的 slot 转为 ISO 8601，
  主 `schedule_slot` 仍为带时区字段；新增自动 catch-up 真实入库回归。修复版重新按关闭态
  部署并通过 `disabled` smoke，production image 为
  `sha256:0cb2e1787fadfb742d3733db3a53e0d08035c22d98d71779dd874bb4a06def65`。
- 随后启用总开关、受限联网和唯一收件人。首次受控 prepare 为 run `26`、bundle
  `07e7f22374bbc09a85df441f87da1cd0228f5431a8f9378a8f1e578bbecf4d47`；
  邮件发送成功，重复 wrapper 返回 `already_claimed`，delivery 仍为 `1`。
- 本轮 selector 找到 `13` 场，但 `candidate=0`、`blocker=13`，全部为
  `route_missing`。因此当前只证明调度、不可变审核包、邮件和幂等链路可用，尚未满足
  “除人工赛果审阅外无其他卡点”的产品验收；不得把 blocker 邮件表述为已收集完整赛果。
- Beat 已按 `Asia/Shanghai` 每日 `06:30/18:30` 注册；Codex automation
  `umanews` 作为同 slot 备用触发且仅失败通知。两者均禁止 apply，赛果审核仍是业务写入
  的唯一人工授权点。下一项实现缺口是为当前及未来目标建立可自动解析、可验证、已批准的
  来源身份/route discovery。

## 2026-07-27 正式 gap-v2 prepare 为 39/40，JRA 中止语义已本地修复

- 生产只读联网 prepare
  `formal-gap-v2-20260727T114705Z/outputs/prepare-20260727T114705Z`
  对冻结 40 场生成 40 个 candidate、319 条数值名次；实际请求 `56/75`，
  manual-only 请求为 `0`，未写 `RaceEventResult` 或 `RaceEventDataCandidate`。
- 39 场完整。唯一 blocker 为 event `80`（小仓纪念）：JRA 官方页完整列出第 1–17 名，
  #5 `エヒト` 的官方状态为 `中止`。旧 adapter 保留了原始文字，但错误规范化为
  `unknown`，聚合层因此报告 `runner_missing_from_result_order`；该马没有、也不应获得
  数值名次。
- 独立工作树 `codex/fix-jra-nonfinish-result-status` 基于
  `origin/main@a079c93c70086298e4ea68c9b9b37023ed587103` 完成测试先行窄修：
  JRA `中止 -> pulled_up`，恢复完整性只豁免受控退赛/非完赛状态；
  `unknown/declared/Also Ran` 仍然阻断，且不会按页面顺序补造名次。
- 新增真实 RED 精确失败于 `unknown != pulled_up`；修复后赛果恢复模块
  `40/40` 通过，另有 JRA 中止、Also Ran 和普通缺马三项定点回归 `3/3` 通过。
  扩大组合测试中的缺 fixture/子进程导入路径问题均位于未修改代码路径，不能计为本修复
  GREEN，也未据此扩大修改范围。
- 本修复尚未提交、推送、建 PR、独立发布复审或部署；生产仍运行旧解析语义，正式 prepare
  artifact 未被覆盖，4.4/4.5 仍未完成，更未取得生产赛果写入授权。

## 2026-07-27 P0 URL 开关已恢复并完成一次补跑

- 后续生产部署曾在 `2026-07-27 15:33 +08:00` 将
  `P0_RACECARD_URL_DISCOVERY_ENABLED` 恢复为 `false`，因此当日 `18:30` 的首次自然调度
  未执行。用户随后明确授权在不改代码的前提下恢复开关并立即补跑。
- 操作前生产为 `5fed1a964d099281f59ad6d39b13196ecffd2cbe`；P0 任务、service、settings、
  Compose 与 provider registry 相对原发布 revision `cfba7151` 无差异，registry SHA-256
  仍为 `c96f042941d38682ec3c77eb57b80f90d7810d69829543b82d6dcfee09819876`。
- beat 暂停后，默认队列从 `29` 自然排空到 `0`，Celery
  `active=0 / reserved=0 / active_confirm=0`。`.env` 恢复点为
  `.env.backup.pre-p0-reenable-20260727T114553Z`，mode `0600`；仅将 P0 开关从
  `false` 改为 `true`。
- 重建 worker 时 Compose 连带重建了 db/web；未改镜像或数据卷。重建前后五张业务表总数
  一致，db/web 恢复 healthy，回环 healthz 为 `200` 后才继续补跑。
- 补跑于 `2026-07-27 19:46:45 +08:00` 开始并成功，`TaskExecutionLog 2 -> 3`；
  结果为 `future_expected=6 / orphans=5 / listing_reachable=3 / found=0 /
  not_available=8 / blocked=6 / errors=2`。新 generation 为
  `19679c03583afb492a873c3ff5dfbdc6495ed69cb8af5e9c99b9c91b5dcc8612`，`current`
  已切换且 verifier 通过；两代保留策略使 generation 目录计数保持 `2 -> 2`。
- 本次运行窗口内 `RaceEvent / RaceEventRunner / RaceEventResult / ExternalRaceEntry /
  ExternalRaceResult` 的 `updated_at` 命中均为 `0`。worker/beat 最终开关均为 `true`，
  调度仍为 `Asia/Shanghai` 的 `30 6,18 * * *`；Django check、内外 healthz 均通过。
- beat 恢复后补投其他既有周期任务，验收快照默认队列为 `37`，其中 active 为既有
  `crawl_netkeiba_latest`，P0 日志仍精确为 `3`；未删除队列任务，也未额外触发 P0。

## 2026-07-27 P0 官方出马页 URL 定时任务已上线，Equibase 生产网络降级

- PR `#32` 已合并为 `main@cfba71518f1024d54cd5553b7f0bb35c780f5959`，生产
  `/opt/umanewsbot` 已快进到该 revision；`web/worker/beat` 使用镜像
  `sha256:a11d072d8a8fc9cc268db996bc916751cea51fe0b7a7cdfc16b715ab0f3e4bf7`。
- 发布前恢复点为
  `.env.backup.pre-p0-url-20260727T062445Z` 和
  `backups/db/pre-p0-url-20260727T062445Z.dump`；两者 mode 均为 `0600`。数据库备份
  `259806424` bytes，SHA-256
  `5a02d4b2e2da1f9040920e046bf4bff75790c9dc5ee4a9aed82390acfd894e76`，
  容器内 `pg_restore -l` 通过。
- 关闭态部署先验证 `P0_RACECARD_URL_DISCOVERY_ENABLED=false`，同步调用返回
  `{"enabled": false}`，`TaskExecutionLog` 与宿主文档文件数均保持 `0 -> 0`。随后设置
  worker/beat 的该开关为 true；beat 确认使用 `Asia/Shanghai` 和
  `30 6,18 * * *`，任务名为 `stable.tasks.discover_p0_racecard_urls_task`。
- 已完成两次受控运行，均为
  `future_expected=6 / orphans=5 / listing_reachable=3 / found=0 /
  not_available=8 / blocked=6 / errors=2`。两个 generation ID 分别为
  `d25176d9f07f960704caf13943f617a40e0a80a022557db9888e271791119ef9` 和
  `5868715fb4406b552132adf4e7a24372dba72253d20b25196ffc1368b2ce68db`；
  `current` 指向后者，generation verifier 通过。
- BHA 三场生成官方日期索引；France Galop 与五个时间证据不足的美国 orphan 按设计显示
  “暂无”。Equibase DMR/CNL 从香港生产服务器发起 HEAD 时连接超时，两个目标 fail closed
  为 `source_error/error_without_previous`，没有伪造 URL。该 provider 当前为生产网络降级，
  调度保留启用以在每日两次运行中自动重试，不能描述为全地区成功。
- 两次运行仅新增 `TaskExecutionLog=2` 和宿主 generation 文档。两次运行完整时间范围内，
  `RaceEvent / RaceEventRunner / RaceEventResult / ExternalRaceEntry / ExternalRaceResult`
  的 `updated_at` 命中数均为 `0`。Django check、generation verifier、回环/公网 healthz
  均通过；未启用 race-live、lifecycle、历史抓取、公开发布或 QQ 影响。
- beat 重启后会补投其他既有周期任务，验收快照默认 Celery 队列为 `19`；没有删除或清空这些
  生产任务，worker 保持运行消费。
## 2026-07-27 PR #33 完整名次门禁进入独立复审修复轮，尚未合并或部署

- 生产首轮 prepare 暴露的 NAR/Sporting Life/ZEturf `scheduled` 静默过滤已补有效 RED。
  runner 现在仅在 `purpose=race_result_recovery` 时向四类详情 adapter 传入
  `--recovery-mode`；普通模式继续只接受 `finished`。
- Sporting Life 若只给前若干名并将其余完赛马标为 `Also Ran/N/A`，不会按页面顺序补造名次。
  聚合层现对所有 recovery 来源强制核对冻结 `event_id`、完整参赛名单、非退赛马覆盖、
  连续唯一内部名次与非 discovery-only；任一不满足均写入 `result_order_complete=false`，
  coverage 以 `incomplete_result_order` 阻断。
- source-scoped adapter CSV 现携带生产 `event_id`，JRA、NAR、Sporting Life、ZEturf 与
  TOBA candidate 会原样回传，coverage 可以唯一绑定目标，不再把合法结果误列为
  `candidate_event_id_missing`。
- PR `#33` 以 `main@cfba7151` 为 base、首轮受审 head `1b11f985`。独立只读复审返回
  `REVISE`：UK/US Sporting Life 共用标准输出路径会覆盖英国候选；coverage 可接受外部
  JSONL 自报完整性并缺少 target 来源核对。两项 P1 已补 RED 并在同一分支修复：英美输出
  路径完全分离，recovery audit 只接受 state 中绑定 SHA/size 的标准 combined artifact，
  同时逐场核对 `source_provider/racing_region`。
- 同一 reviewer 已对修复 head `c4ce802c` 完成 closure review，结论
  `VERDICT: APPROVED`、无 findings；全程只读、未联网、未改文件。两个 P1 均已关闭。
- finding 修复后相关回归为 `142 tests / 141 passed / 1 skipped`；Django check、无迁移漂移、
  `py_compile`、旧规格流程 strict/all（`38/38`）与 `git diff --check` 均通过。Eddie Read
  已由 Racing Post 完整结果与 DRF 赛后文字交叉确认第 5–8 名依次为
  Seal Team、Almendares、Mondego、Mi Hermano Ramon；该结论仍是第三方候选，Del Mar 官方
  chart 当次复核尚不可用，不能提升为 confirmed。
- 修复位于 `codex/fix-race-result-recovery-completeness` 并已提交、推送至草稿 PR `#33`；
  独立复审已通过。PR 尚未合并或部署；
  生产仍运行 `main@e2ae3efe` 对应应用镜像，现有 candidate 与常驻关闭开关未改变。

## 2026-07-27 event 426 时间修正后已执行一次性联网 prepare，4/40 形成候选

- 用户明确授权写入 event `426` 的官方开赛时间。生产事务将 `race_datetime` 从 `null`
  更新为 `2026-07-27T01:10:00Z`，来源为 Del Mar 2026-07-26 Race 9 官方 entry
  （当地 post time `18:10`）；`status/local_start_time` 未改，赛果行仍为 `0`。写前快照
  SHA-256 为 `ce8e5fb9…1d53`，写入回执 SHA-256 为 `59627477…c74`，并新增
  `race_event_official_start_time_set` 审计。
- 新 inventory `inventory-20260727T060200Z.json` 仍满足 `59 event rows / 50 race groups`，
  分类保持 `40 missing + 9 duplicate-zero + 9 duplicate-confirmed + 1 provisional`；
  文件 SHA-256 `327e8c16…0aa3`、manifest SHA-256 `d569534a…cfda`。event `426/427`
  均为 `result_due=true`，精确 40 场 ID 不变。
- run `prepare-20260727T060300Z` 的 expected targets 为 `40`、preflight blocker 为 `0`；
  expected-target SHA-256 `5e444a53…03b`，审批 SHA-256 `87464712…0ca3`。一次性 one-off
  容器联网 prepare 已运行，实际请求 `12/75`，runtime 总大小约 `1.24 MiB`。
- JRA 官方详情形成 4 场候选、58 条 result item，combined candidate SHA-256
  `033fc60d…489c`。NAR 仅形成一场 racecard 候选、没有 result item；Mercury Cup 被上游页面
  判为 `racecard_not_published`。TOBA 2023–2026 四个年度页均返回 HTTP 403。
- 英国/美国 Sporting Life 与法国 ZEturf adapter 因仍只读取 `status=finished`，对 recovery
  CSV 中合法保留的 `scheduled` 目标产生 `events=0` 的静默空跑；因此 Eddie Read 未进入
  runner candidate。人工联网复核确认其前四名为 `#5 Gold Phoenix / #3 Cabo Spirit /
  #8 Formidable Man / #6 Stay Hot`，`#1 Astronomer` 退赛，但该网页证据尚未转换为受审
  recovery candidate/receipt。
- 四个常驻应用容器的 scheduler、monitor、runner、lifecycle、historical backfill/network
  八项仍全部关闭。40 个目标的生产 `RaceEventResult` 行为 `0`，event 426 赛果为 `0`，
  没有 `race_result_recovery_apply` 审计；本轮只写 event 426 的获批时间元数据，未写赛果。
  task 4.3 仍未完成，下一步必须修复并重新发布非 JRA adapter 的显式 recovery mode，不能改写
  CSV status、直接绕过 runner 或把空跑声明为完成。

## 2026-07-27 PR #30 已合并，联网 prepare 阻断修复已关闭态部署

- 修复提交 `00979dc443979ef0d982ae7776c3ff7dfb3d0572` 经 PR `#30` 合并为
  `main@e2ae3efe2349623dd60745bfef498af31d7d8d84`，生产已快进并构建统一应用镜像
  `sha256:e0a2d3d6612841df64f2ab1b8ca8ff6a749f4b14c8f4e3173317a394250e61a3`。
- 已用测试复现并修复 `expected_target_empty`：recovery plan 现在同时绑定 inventory 文件路径、
  文件 SHA 和内部 manifest SHA，调用既有 verifier 重算当前数据库身份后，再按冻结顺序批量加载
  40 个 event ID 和 active aliases。状态、可见性、日期、名称、系列、source facts、赛果数量/
  内容、event 消失、地区漂移或重复 ID 均 fail closed；既有 snapshot 恢复时也重新验证。
- adapter CSV 从仅按地区改为按 `region + source` 精确分片，避免日本 JRA/NAR 与美国
  TOBA/Sporting Life 互相取得对方目标；40 场 snapshot 与输入物化均固定为 2 条 SQL。
- JRA adapter 现在由 runner 物化年度列表缓存路径、精确 host/path request policy、
  shard/request-state/host-state，并在缺少缓存时先受控抓取年度列表。每个 JRA 请求同时进入
  全批次共享请求预算和 runner v2 host/path/间隔账本，每个 redirect 也单独占用共享预算；
  只有显式 recovery mode 才允许冻结目标保持 `scheduled` 时进入候选，旧模式仍只接收
  `finished`。manual-only 路由未改变。
- 首轮独立复审提出 inventory 未重验、scheduled 被过滤和 redirect 预算低报 3 个 P1；第二轮
  复审进一步发现可省略 `source_map_version` 绕过精确 40 场映射，现均已补 RED 并修复。
  recovery plan 必须携带当前批准的 source-map 版本且始终精确匹配冻结范围。受影响范围测试为
  `100 passed / 3 skipped`，HTTP 预算 `3/3`、runner-v2
  contract `29/29`；Django check、迁移漂移、旧规格流程 strict、
  `py_compile` 与 `git diff --check` 通过。现有本地测试镜像的完整 `stable` 因缺
  `openpyxl`、无 Redis 及既有无关失败只能如实记录为 `2003 tests / 19 failures /
  91 errors / 5 skipped`，不能作为本修复 GREEN 证据。
- 同一原生只读 reviewer 已对精确 fingerprint
  `db0e38b26bacb1c6bc798303d756e6fcf1a80e4203fb1778cd6a324d552c5135`
  给出 `VERDICT: APPROVED`，前后 fingerprint 一致且未修改文件。
- 部署恢复点为
  `backups/db/pre-race-result-prepare-fix-20260727T045500Z.dump`，大小
  `259584695` bytes、SHA-256
  `3a2d1b91ac1610e42c272957a3055067b1a326b2f11c71a81c3ce099b97cbf5c`、
  mode `0600`，`pg_restore -l` 为 1127 项；对应 `.env` 备份同为 `0600`。
- `web/worker/beat` 运行新镜像，`race_live_worker` 使用同镜像但保持 `Created`。四个应用容器中
  scheduler、monitor、runner、lifecycle、historical backfill/network 八项值全部关闭；4 条
  publication policy 为 off。event 924 的既有 `provisional_public` allowlist 保留，但在 policy
  off 且 worker 停止时不生效。迁移无变化，Django check、公网 HTTP healthz 与 `/races/`
  均通过，近 15 分钟应用日志无 traceback/critical/exception/error。
- 本次部署没有运行 prepare，没有新增 candidate/source cache，也没有赛果业务写入。下一门禁仍是
  对精确 40 场 snapshot/adapter 输入完成关闭态复核后取得新的有界联网 prepare 授权。

## 2026-07-27 赛果缺口恢复已关闭态部署，inventory 通过，联网 prepare 在零请求处阻断

- PR `#28` 已合并，release commit `88cc4eafe4a7b5263aa2a6c30cd7d70978323989`，
  merge/生产 HEAD `dfbd24e10f5910580945f29fe19219b7d838730c`。生产应用镜像为
  `sha256:35a53589e051c39806397fe8aec1e00f0bcbd1df9d0a9ffec29a72f35dc4d751`；
  `stable.0060_raceeventproductcanonicallink` 已成功应用，新增表保持 `0` 行。
- 部署恢复点为
  `backups/db/pre-race-result-recovery-20260726T200011Z.dump`，大小
  `257629113` bytes，SHA-256
  `682848bdb63edc43b809056fa3a5b1331ebca7f2f6e2cfae806208fa105c9efc`，
  mode `0600` 且 `pg_restore -l` 通过；环境恢复点为
  `.env.backup.pre-race-result-recovery-20260726T200011Z`，mode `0600`。
- 生产运行时保持关闭：race-live scheduler/monitor=false、enabled regions 为空、
  runner mode=disabled、lifecycle=false/off、historical backfill/network=false；
  4 条既有 race-live publication policy 已切到 off，1 条 allowlist 已 disabled。
  event `924` 的 7 条暂定结果未删除，未创建正式赛果或 canonical link。
- 只读 inventory 位于
  `runtime/race_result_recovery/inventory-20260726T200544Z.json`，文件 SHA-256
  `a4380f2b4bb5fafe96f7990e2bc0ef9e032a7d84e17718ebd0b091d5b60b267a`，
  manifest SHA-256
  `f3a4cb7f26bfac5db4312af3f3af46d9fe11f9e50d2241ef54d4606403dbed1b`。
  守恒精确为 `59 event rows / 50 race groups / 40 missing / 9 duplicate-zero /
  9 duplicate-confirmed / 1 provisional(event 924)`，并生成 9 组 pending identity review。
- 为保持 race-live worker 停止而执行 Compose `create` 时，Compose 意外连带重建 db
  容器但未删除 PostgreSQL 持久卷；db 一度处于 Created，`/races/` 瞬时返回 500。
  已启动原数据卷上的 db、等待 healthy 并重启 web/worker/beat，最终
  `RaceEvent=9867`、公网 HTTP healthz 与 `/races/` 均恢复 200；race-live worker
  使用新镜像但保持 Created/未运行。
- 有界联网 prepare 在 transport 前 fail closed：`race_result_recovery` plan 已正确验证
  40 个冻结 event ID，但 `expected_targets_from_plan()` 仍只处理普通 `series` 或历史
  `targets`，生产只读调用报 `expected_target_empty`。本次网络请求 `0`、manual-only
  请求 `0`、candidate/source cache `0`，未写赛果业务表。不得绕过 approved runner；
  需先补 recovery event-ID snapshot 路径并解决 JRA 受控请求输入，再重新测试、独立 review、
  发布和取得新的联网执行授权。

## 2026-07-27 赛事赛果缺口恢复方案已通过工程审核（待确认实施）

- 生产只读盘点确认 `2026-07-08..2026-07-27` 有 59 条公开 `RaceEvent`，初步对应约 50 场真实赛事；
  其中 9 组赛果落在跨 `RaceSeries` 的另一条实体，event `924` 有 7 条未确认 TRA 结果，重点口径有
  26 条已过期赛事仍为 `scheduled + results=0`。公网 `/races/?when=finished` 实际最晚只展示
  `2026-07-05`。
- 已从 `origin/main@a59956b3` 建立独立 worktree `recover-race-results-through-20260727`，
  旧规格流程 change 同名，proposal/design/四份 delta spec/tasks 均通过 strict 校验；另补
  `test_cases.md` 与 `rollout.md`。
- 首轮工程审核发现 direct `RaceEventResult` 写入会绕过 owner/revision arbitration、canonical
  映射未持久化、blocker 被误算完成以及缺测试/rollout 四项问题；现已改为 owner-aware official
  revision 投影、新增最小 `RaceEventProductCanonicalLink`、完成条件 `blocker=0`，同一 reviewer
  复审为 `VERDICT: APPROVED`。
- 本轮只执行生产数据库只读查询与公网页面核验；尚未实现代码、运行赛事来源网络 prepare、部署、迁移或
  写入生产。下一门禁是用户确认实施；实现完成后仍须分别取得 release、network prepare 和精确
  candidate/approval SHA 的生产写入授权。
## 2026-07-26 赛事新闻质量治理已实现（待独立代码审核）

- 基于 `origin/main@ef54a183`，worktree `impl-race-news-quality-20260726`，分支
  `codex/impl-race-news-quality-20260726`。两组方案均已于 2026-07-26 通过 fallback 工程方案审核
  （`VERDICT: APPROVED`）。
- 已完成测试先行（术语 27 RED / 曝光 46 RED → 实现后术语 29 GREEN / 曝光 47 GREEN）、
  串行子代理实现（术语 → 曝光）。
- 术语变更：
  - 新增 `TermMappingEvidence` 模型（migration `0063_add_term_mapping_evidence`（合并时顺延））
  - 新增 `server/stable/services/term_consistency.py`：occurrence resolver、canonical consistency gate、published dry-run/manifest/CAS apply
  - 新增 `server/stable/test_public_term_consistency.py`（32 tests, 29 GREEN, 3 性能在 SQLite 预期受限）
  - 新增 settings: `TERM_CONSISTENCY_ENABLED/SHADOW/ENFORCE`
- 曝光变更：
  - 新增 `RaceNewsExposure` 模型（migration `0064_add_race_news_exposure`（合并时顺延））
  - 新增 `server/stable/services/race_news_exposure.py`：race identity resolver、hard duplicate classifier、angle classifier、two-slot state machine、QQ exposure
  - 新增 `server/stable/management/commands/backfill_race_exposure.py`：历史 dry-run/apply
  - 新增 `server/stable/test_race_news_exposure.py`（47 tests, 47 GREEN）
  - 新增 settings: `RACE_NEWS_EXPOSURE_ENABLED/SHADOW/SECOND_SLOT_DELAY_MINUTES/HOMEPAGE_MAX/QQ_TARGET_MAX`
- 所有回归测试通过（test_editorial_headlines 57, test_english_term_context_gates + test_term_gate_reprocessing 57, 及其他 182 tests，总计 375+ tests）。
- Django check、makemigrations --check --dry-run 通过。
- 尚未执行：commit、push、PR、部署、生产迁移、生产写入、正式术语写入、历史文章修复。
- 下一门禁：独立代码 review。
## 2026-07-25 日本重赏 P0 身份补证进入本地实现（未部署、未触网）

- task 1.1 已在生产 `9b58bfd437f58dede0de5d11d64537e2e68e214e` 上完成只读盘点：
  7,228 个日本地区潜在 profile 中，直接 JRA/NAR 马匹锚点为 0，7,164 个只有官方赛事
  上下文；1,353 个有唯一 Netkeiba ID，60 个身份底稿已完整。可尝试“赛事上下文解析锚点 +
  双源补证”的底稿缺失上界为 1,283 个。
- 现有库没有结构化日本训练确认，7,228 个对象全部只能视为训练范围未确认；其中 5,875 个没有
  Netkeiba key，不能把 profile 行数直接解释为已跨赛事去重的真实马匹数。原设计“从已有官方
  马匹锚点选 PoC”无法执行，须先修订为第二层赛事上下文解析 PoC。
- 只读聚合前后 `RaceEvent/Runner/Result/HorseP0Source/HorseProfile` 计数完全一致，未访问
  JRA/NAR/Netkeiba。摘要 SHA 为
  `66d6415941810436ce9e657621f45c6f710ddf39e142a5e56cc67cf270ce086c`。
- `docs/changes/bootstrap-p0-horse-identity-evidence/` 已取消 JAIRS，核心链路改为
  `重赏赛事 → JRA/NAR 官方马匹锚点 → Netkeiba/JRA/NAR 四字段共识`；JRA-VAN 仅作为后续
  Windows 离线补证来源。
- 一期范围扩大为 1998–2026 年日本训练马参加的 G1/G2/G3、J-G1/J-G2/J-G3、
  JpnⅠ/JpnⅡ/JpnⅢ，以及资格与训练证据完整的海外 G1/G2/G3。赛事等级只决定处理优先级，
  不改变身份锁或证据等级。
- 候选从 `RaceEventRunner`、`RaceEventResult`、`HorseP0Source` 反向生成并按 profile
  去重；只有 JRA/NAR 所属或经审核的等价证据才能确认日本训练，只有赛事在日本或
  `racing_region=Japan` 不足以通过。
- 项目按个人非商用学习用途处理，不把另行申请商业数据授权设为实现前置；真实访问仍须一次性
  人工触发、双重网络开关、分 host 限速、请求预算、缓存，且不公开源页面副本。
- 修订方案已通过当时的规格严格校验（38/38）和两轮聚焦工程复审，`VERDICT: APPROVED`。
  复审补齐三项门禁：外国出生/转籍只作 `sampling_clue`，不冒充训练证据；第二层完整官方
  赛事上下文进入稳定排序；单匹总预算为 6 URL/18 次传输，其中 JRA/NAR 官方链最多
  3 URL/6 次传输。
- 当前任务清单进度为 `26/38`：任务 1.1–1.5、2.1–2.11、3.1–3.6、4.1–4.3 与 4.5 已完成。
  当前本地链路已经覆盖
  候选池、稳定排序、JRA/NAR 确定性锚点、三套独立 provider、Netkeiba/JRA/NAR 四字段
  A/A+ 共识、6 URL/18 次传输与官方 3 URL/6 次传输持久预算、缓存/断点恢复、拒绝即停、
  provider-neutral artifact、请求账本、逐马审核 xlsx、不可变审核事件、唯一 commit receipt
  及严格 replay verifier。`commit/verify` 必须显式提供 `--confirm-approved-artifact`；
  approve、commit 与 replay 都会复核资格、官方锚点、来源 URL/ID/内容 SHA、结果和
  OperationLog，任一漂移即阻断。真实 prepare 候选会携带 commit 复验所需的完整冻结选择字段；
  approve 会要求内嵌 candidate/blocker 与已哈希 JSONL sidecar 逐字节一致。旧 JAIRS/JBIS
  新命令路径和旧测试均已移除；审查修复后身份补证测试 `46/46` 通过。
- JRA-VAN 本轮只增加 Windows 离线交换 schema 与 Linux 校验器，要求 UM、血统登记编号、
  数据规格版本、带时区 snapshot、逐记录 SHA、输入/输出清单 SHA；拒绝夹带原始 UM record，
  未实现常驻 Windows 采集服务。
- 分支已无冲突同步最新 `origin/main@9b58bfd4`；新迁移顺延为
  `stable.0058_horse_identity_evidence_commit_receipt` 并依赖合并叶 `0057_merge_20260725_0448`，
  测试数据库已完整迁移到 `0058`。Django check、迁移漂移检查、两份生产 Compose 配置和
  `git diff --check` 的完整复验将在本轮修复后重跑。公开马匹履历模板已
  补上每页 20 条的上一页/下一页导航并保留排序参数；身份补证 `46/46`，分页、旧 P0 批次及
  P0/Netkeiba/补源/回填/发布门禁组合回归 `551/551` 均通过，新命令和服务
  未引用 JBIS/JAIRS。旧 `stable.tests.P0HorseProfileDataCompletionTests` 的 4 个公开内部状态
  文案断言与既有“公开页隐藏内部元数据”决策冲突，且最新主线已将该模块转为
  `tests_legacy.py`；不将它们解释为本变更回归。
- 第三次独立只读代码审查已返回 6 项 finding：迁移主线冲突、approve 未从来源身份重算共识、
  URL 未强制 HTTPS、直连官方锚点可缺来源 ID、请求无连接/读取超时，以及新 change 误放
  旧规格流程 目录。当前已同步主线并改为 `0058`，approve 会重算四字段共识，来源请求逐跳强制
  HTTPS 且使用 `5s/20s` 超时，JRA/NAR 锚点要求非空 `CNAME/k_lineageLoginCode`，durable
  artifacts 已迁至 `docs/changes/bootstrap-p0-horse-identity-evidence/` 并补齐
  `test_cases.md/rollout.md`；随后原生完整范围 review 又发现两项 P1：真实 prepare 候选缺少
  commit 冻结字段、approve 未把内嵌候选绑定到已审核 sidecar。两项均已补测试并修复：
  prepare 复制完整冻结选择字段，approve 对 candidate/blocker JSONL 做规范字节一致性校验。
  身份模块 `46/46`、相关主链 `551/551` 均通过。
  Django check、migration drift、`0057 → 0058 → 0057 → 0058` 往返迁移、两份生产 Compose
  config、durable artifact 五件套和 `git diff --check` 通过。原生 reviewer 会话
  `019f99c5-9fa6-7022-a0a6-c999e1dbd68d` 已复审确认两项 P1 均关闭、无直接相关
  actionable finding；受审指纹为
  `a8e8f7f18d0e37095ebc30789a103e046955213825dcac8390188b6ab25cb19b`。
- 2026-07-26 发布前发现 `origin/main` 已新增 HRN 正文边界修复及其发布证据；本分支未 staging、
  未提交，先后安全快进并恢复本任务改动，当前无冲突同步
  `origin/main@0aeb0ed7660746bdcdcbad0343aad771b1324918`。合并后身份模块 `46/46`、相关主链
  `551/551`、Django check、migration drift、两份 Compose config 和 diff check 再次通过；
  由于 approved parent 已变化，旧指纹和发布授权不再用于提交，当前等待同一原生 reviewer
  会话对最新组合版本复审。
  当前仍未部署、未执行生产迁移、未真实访问 JRA/NAR/Netkeiba、未写生产马匹数据。

## 2026-07-24 首页人工头条与 AI 编辑推荐控制已实现（待独立代码审核）

- 基于 `origin/main@10f341e6`，worktree `add-editorial-headline-control`，分支
  `codex/add-editorial-headline-control`。方案已于同日通过独立方案 reviewer 三轮审核
  （`VERDICT: APPROVED`，0 项待解决 finding）。
- 已完成安全 rebase（当前即为最新主干）、测试先行（57 测试 RED → 实现后 51 GREEN +
  2 PG skip + 6 测试边界待修）和串行子代理实现。
- 新增模型 `HomepageHeadlineSelection`（固定 slot 唯一控制行 + 乐观锁 version）和
  `HomepageHeadlineRecommendation`（独立推荐快照 + active 条件唯一约束）；迁移
  `0054_homepage_headline_control.py` 只新建两表及其索引/约束，不扫描 NewsArticle。
- 新增服务层 `server/stable/services/editorial_headlines.py`，包含统一资格校验、
  单例选择行 get_or_create 并发安全、预期版本冲突拒绝、72h→7d→all 三级窗口算法回退、
  AI 推荐生成/接受（推荐不修改首页）、失效协调等完整接口。
- 已扩展 `signals.py`：post_save(on_commit) 和 pre_delete 的失效协调，异常被记录而不
  重抛。修复 `admin.py` 的 `mark_pending_review` 批量绕过（改为逐行 save）。
- 新增后台路由 `/admin/headline/` 及选择/取消/推荐/接受端点；新增管理页模板
  `headline_control.html`；`article_editor.html` 增加 AI 推荐卡片（非嵌套 form）。
- 公开首页 `public_news_feed` 已接入 `resolve_homepage_headline()`：有效人工头条优先，
  否则使用统一资格的算法回退。公开来源/地区隐藏规则不变。
- 尚未执行：commit、push、PR、部署、生产迁移、生产写入。下一门禁：独立代码 review。

## 2026-07-24 首页人工头条与 AI 编辑推荐方案审核通过（待确认实现）

- 已从最新 `origin/main@10f341e6` 建立独立干净 worktree
  `/Users/mentianlu/Code/umanews/.worktrees/add-editorial-headline-control`，分支
  `codex/add-editorial-headline-control`；前序 `simplify-public-navigation-and-attribution` 已通过
  PR #16 合入当前基线。
- 当前首页没有人工头条状态：公开 queryset 只接收 `workflow_status=published` 且
  `published_to_web_at` 非空的文章；头条先看近 72 小时、再看近 7 天、最后回退全部，每层只取最新
  48 篇并按赛事优先级、自动分数、封面、发布时间和 ID 排序。首页本身没有 headline/page cache。
- 通过方案位于
  `docs/changes/add-editorial-headline-control/{spec,design,test_cases,tasks,rollout}.md`：采用唯一 slot 的
  `HomepageHeadlineSelection` 保存人工状态，独立 `HomepageHeadlineRecommendation` 保存推荐快照；
  推荐只复用已持久化的自动化/AI 编辑信号，不新增外部模型调用，也不能修改人工选择。
- 方案要求人工、推荐和算法 fallback 共用资格，并使用固定 slot CheckConstraint、selection 行锁、
  预期版本、PostgreSQL 条件唯一约束和失效读取双保险；无有效人工头条时保留现有三级窗口、48 篇合格
  候选和排序元组，公开来源/地区隐藏规则不变。已知 Django Admin 批量状态 action 也纳入失效协调。
- 独立方案 reviewer 首轮提出 6 项 finding；经同一会话三轮审核，统一资格、Django Admin bulk
  失效绕过、实现前安全 rebase、固定 slot 约束、候选查询边界和 `on_commit` 异常可观测性均已写回，
  最终 `VERDICT: APPROVED`，P0/P1/P2 finding 为 0。
- 已新增 `docs/changes/add-editorial-headline-control/handoff.md`，完整固化 Claude 接手所需的 Git
  基线、授权边界、现状入口、通过设计、RED/实现/验证顺序、方案审核历史、代码 review 和发布门禁。
- 当前只获准探索、规格和方案审核，尚未编写测试或应用代码、未创建迁移、未启动实现 subagent，也没有
  commit、push、PR、部署、生产迁移或数据写入。现已停在用户明确“确认实现/开始实现”的门禁。

## 2026-07-24 英文单词型马名语境门禁代码已部署，生产保持 shadow

- 受审 fingerprint 为
  `7ff685325de93578f0131a73746a50f23d627f5cd1dbb266f2afee372eb9aabd`，
  content hash 为
  `53d957ed41e6e0e5e0e68f4331cf9d0078a563129fbb9a995c845895f381a2cb`；
  独立只读 review 会话 `019f9252-e50c-7d30-8e49-d6765919a51d` 的 CORE 结论为
  `APPROVED`。本地完整矩阵 `333/333`、语言专项 `77/77`，Django check、migration
  drift 与 diff check 均通过。
- 本地 release commit 为 `1c34a00715aa3a0ac49153553622360afa10e049`，经
  [PR #14](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/14) 合并；生产
  `/opt/umanewsbot` 从 `97a38cf5` 快进到 merge commit
  `2a3c249f4ffce2e97a2133f9a932234f74ec1e1e`。使用 `bash ./deploy_lowcost.sh`
  部署，无 migration；`web/worker/beat` 重建后另行 force-recreate
  `race_live_worker`。
- `web/worker/beat/race_live_worker` 统一运行镜像
  `sha256:316e4563b306ca70bde8e55a78c79d48de1ac8ca09d7259a8a7d0b4f5044c364`，
  web healthy。Django check、`makemigrations --check --dry-run`、内网/公网及
  `www` healthz、首页和 admin login 均通过或返回 HTTP 200；Celery 两节点 ping
  正常。部署前 active/reserved 为空，部署后仅自然 netkeiba crawl 为 active，
  reserved 为空；外部导入 `started=0`、locks `=0`，磁盘可用 `54G`。
- 生产 `ENGLISH_TERM_CONTEXT_MODE=shadow`：新分类代码已部署，但尚未改变实际发布门禁。
  切换 `enforce` 必须另行取得明确授权，本次不执行。
- 对 article `9595` 仅做进程内 override `enforce` dry-run：
  `workflow=published`、`automation=auto_published`、`horse_alert_codes=[]`；
  `Logician` 为 `confirmed_horse` 且因已有正式译名 `needs_preserve=false`，
  `Africa/East` 为 `common_word` 且均 `needs_preserve=false`。未保存、未重处理、
  未发通知、未修改生产数据。
- 两项 discovery aggregation P2 继续 deferred 到后续 change
  `fix-term-discovery-visible-occurrence-aggregation`，本次发布不扩大范围。

## 2026-07-24 task 5.4 已正式写入并完成生产回归

- 修复提交 `044f3d57f4f3bb75eac31f0567917132e5ae5cff` 已推送 `main` 并部署；四应用统一
  镜像 `sha256:01f0fd3466873b0a1c44bb7ad4ab5d64d4a8f0e2e9d8a5a6df84a27dfad8861d`，
  宿主及 `web/worker/beat/race_live_worker` 的
  `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`。
- 新 candidate 为
  `6dc853a2b5581de3af241fca81fb76d0f48bcea600abcb7c231206d229a69f9b`，artifact 为
  `b1e123fa77387505a1380b6ae932712117c68aa8aef502deb66b149d25838863`，正式 release 为
  `8c6f2dc8d88abce2d432b3e3d174611dedbba2f5a04f174e17d1376365c1511d`。冻结集合仍为
  `61 complete / 39 blocker`，artifact 与 blocker 交集为 0；公开范围仍为
  `61 skip_already_published / 0 attempt / 0 create`。
- 正式写入成功，内置和普通重复 commit 幂等复验均为 passed，剩余 profile/record/audit 动作
  全为 0。61 匹全部 strict complete，含 10 匹真实无胜场；61 个公开详情页均返回 200。
- 写前后：HorseProfile `46318 -> 46318`、Japan `11642 -> 11642`、published
  `2797 -> 2797`、Japan published `2463 -> 2463`、HorseRaceRecord `1460 -> 2950`
  （`+1490`）、HorseProfileDataCandidate `200 -> 444`（`+244`）、
  HorseProfileCompletionRun `1 -> 2`（`+1`）、HorseP0Source `57332 -> 57393`
  （`+61`）、OperationLog `59362 -> 59362`。此前把 61 次 source upsert 估为净增 0 不准确；
  candidate 只冻结 upsert 动作数，实际 61 条均为新来源行。
- 恢复点：部署前
  `backups/db/pre-p0-task54-fix-20260724T025733Z.dump`
  （SHA-256 `94530cd15dbbcff316bfed6eb6325fe36ea348b8c52d648935c98fdaef6bc055`）；
  正式写入前
  `backups/db/pre-p0-task54-write-20260724T030415Z.dump`
  （SHA-256 `3f0c71122e62f6fc6940d4c142ea542653b4a7980c63723b953a87f5807fea6e`）。
  两者均为 custom-format 且通过 `pg_restore -l`；对应 `.env` 备份已保存。beat 在写入前暂停并
  等待 active/reserved/队列归零，回归后已恢复。Django check、迁移、容器、HTTP healthz、
  日本马匹列表及公网 HTTP 均正常，近 15 分钟应用日志无 error/traceback。

## 2026-07-24 task 5.4 已审核空胜绩语义完成本地修复（待独立复审）

- 用户已授权开始修复。测试先行确认两层旧行为：已 applied 的空 `major_wins` 仍被判
  `major_wins` 缺失，正式 artifact 因而不能写入 `full_profile_reviewed_by/at`。
- 本地窄修现只在最新非 ignored 的 `major_wins` 候选为 `applied`、审核结论为 `approved`、
  候选 payload 精确为空列表，且具有 `applied_by`、`applied_at` 时，把无胜绩解释为“已审核
  确认无胜绩”；无审核、非空 payload 或最新 conflict 仍阻断。
- 新 commit artifact 与 release candidate 均绑定完整度策略
  `p0-horse-full-profile-completeness.v2`。旧 artifact/candidate 会在数据库写入前 fail closed，
  因此已批准 candidate `8ef0f718...` 不会被静默复用；必须部署受审精确版本后重新
  prepare-release，得到新 artifact/candidate SHA。当前预授权不能替代最新成功 review 后的
  发布授权；review 成功后仍须请求当前任务发布授权。若对象、预计动作或公开范围漂移则
  fail closed。
- 关键 RED→GREEN 3 项通过；P0/完整度相关组合共运行 312 项，其中 308 项通过，4 项公开页面
  文案测试失败；同 4 项已在修复前基线 `04c89e35` 全部复现，确认不是本补丁回归。当前未触网、
  未连接或写入生产、未部署、未生成新 candidate。
- 排除上述已确认基线失败后，最终 P0 写入链路 246 项与三项新增完整度测试合计 `249/249`
  通过；Django
  check、迁移漂移、旧规格流程 strict/all `37/37` 与 diff check 全部通过。
- 独立审查发现并修复两项 P1：空胜绩证据曾误接受非空 applied payload；策略版本曾误阻断
  历史 v1 artifact 的只读复验。当前仅 v2 正式发布链路强制当前策略，历史 v1 仍只读兼容；
  两项均有先失败后通过的回归测试。
- 后续复审又发现并修复：历史 v1 release 曾仍可进入 commit，现已在数据库写入前明确拒绝；
  手工 ready 曾用非空 payload 覆盖无胜绩证据，现会继续保存空列表。两项也均完成 RED→GREEN，
  正等待同一审查会话最终确认。
- 冻结业务输入未变时，预计线上净增仍为：HorseProfile `+0`（更新 61）、HorseRaceRecord
  `+1490`、HorseProfileDataCandidate/module audits `+244`、HorseProfileCompletionRun `+1`；
  HorseP0Source 预计净增 `+0`（upsert 61 条既有来源），新增公开 `+0`。最终数字必须以新版本在
  生产重算出的 candidate 为准，若漂移即停步重新汇报。

## 2026-07-24 task 5.4 首次正式写入被 strict-complete 门禁整批回滚

- 用户已针对 candidate
  `8ef0f718803f7772db5b498925a71651e5c68cb331aeafa50f03dc831f8848fe`
  授权正式写入，`approved_by=mentianlu`。写前候选、账本、网络开关、空闲队列和数据库计数均
  无漂移；新增写前恢复点
  `backups/db/pre-p0-task54-20260723T203347Z.dump`（238,795,564 bytes、SHA-256
  `082e91d5e9d01ef5e04e8d7d3e16118eab8ae09ad2548b13378d49f23254c2ec`，
  `pg_restore -l` 通过）及 `.env.backup.pre-p0-task54-20260723T203347Z`。
- v2 release manifest 已按授权生成，SHA-256 为
  `5320c33c44d387b14e827b109353ffe5068d997bd9c62d9df903cb5de91e0c90`，
  `release_approved` 唯一写入账本。随后数据库事务在首个无胜场对象
  `イエローマジック` 的 strict-complete 复验处 fail closed：
  `major_wins / review.reviewer / review.reviewed_at`。
- PostgreSQL 事务整批回滚。HorseProfile `46318`、Japan `11642`、published `2797`、
  Japan published `2463`、HorseP0Source `57332`、HorseRaceRecord `1460`、
  HorseProfileCompletionRun `1`、OperationLog `59362` 均与写前一致；未执行自动首发，
  batch 仍为 prepared，commit/publish stage 均未完成，网络开关仍为 false。
- 只读检查确认 61 行中有 10 匹真实无胜场；这些行的 `major_wins` 模块已由 reviewer 批准为空，
  但全局完整度当前把“没有任何胜场”直接判为 `major_wins` 缺失，导致已审核的“暂无胜绩”无法
  表达。不得伪造胜场或绕过 strict-complete。建议另行授权窄修：只有存在 applied/approved
  major-wins 审核证据时才允许空列表表示“已核实无胜场”，并补 RED/GREEN、完整回归、独立复审、
  部署和新 candidate SHA 授权。task 5.4 仍未完成。

## 2026-07-24 task 5.3 已在生产无写入完成，停在精确候选授权门禁

- 最终集成版本 `4972a6b2eb35167d5783f5c37908b8b3d190160d` 经原生只读 full review
  `APPROVED`（P0/P1/P2=`0/0/0`，session
  `019f9095-2025-7a80-96be-b50800b18d82`）后推送并部署。生产四个应用服务统一运行镜像
  `sha256:eed9a3d3b4116644488e85929f475fa06a1072c30f40502b96b62a644fff8ea8`，
  宿主与四容器 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`；Django check、迁移、HTTP
  healthz、首页和马匹列表通过。
- 部署前恢复点为 `.env.backup.pre-p0-task53-20260723T201151Z`（SHA-256
  `dee182cb5b35194c3f3661e94119c36e63dc684d9fff992517d872fc50167d0a`）和
  `backups/db/pre-p0-task53-20260723T201151Z.dump`（238,713,659 bytes、SHA-256
  `341210bceff05064c1828914338aa82dc166773a605a3154cc54547f7f2522d8`，容器内
  `pg_restore -l` 通过）；回滚镜像标签为
  `umanewsbot:rollback-pre-p0-task53-20260723T201151Z`。
- `p0batch-20b59bda0608` 的 bundle 精确包含 61 匹，research/mapping/authority SHA 分别为
  `1afce80f871cc703e0527113bc4f33db06766770029ebf380444b77108fb115b`、
  `e96c8aa9a2fa965f9cc18b0b5931bc47af48f882d8c3833ef9b35a2fe414e826`、
  `759ac2dcdcbff1c22f62424f7c6167c417ae99d9d669c14a0ef0fa38ab1f7bdb`。
  39 个 blocker 与 artifact 交集为 0。
- release candidate SHA 为
  `8ef0f718803f7772db5b498925a71651e5c68cb331aeafa50f03dc831f8848fe`，commit artifact
  SHA 为 `1abbf475927c1e4391ab1ce851b3cd28958da2ec65641c28ec4f49e9608c4894`。
  预计动作是 61 profile updates、1,490 race record creates、61 P0 source upserts、244
  module audits；不创建 profile。61 匹当前均已 published，因此冻结 scope 为
  `61 skip_already_published / 0 attempt_publish / 0 create_new`。
- 重复 prepare-release 的 candidate 文件字节与 SHA 不变，账本行数保持 3，
  `release_candidate_prepared=1`、`release_approved=0`，未生成 v2 release manifest。
  HorseProfile `46318`、Japan `11642`、published `2797`、Japan published `2463`、
  HorseP0Source `57332`、HorseRaceRecord `1460`、HorseProfileCompletionRun `1`、
  OperationLog `59362` 均未变化。task 5.3 已完成并立即停步；task 5.4 必须由用户针对上述
  candidate SHA、预计写入和零新增公开范围重新明确授权。

## 2026-07-24 第二轮 fresh review P2 已完成本地返修（待复审）

- prepare-release 的 public service 入口现直接取得同 batch execution lock，再进入既有 state serial
  lock；direct service caller 不再能绕过 command 并发边界。
- 获锁后重新读取 manifest/state；commit 已完成或 batch 已 abandoned 时，在 candidate/state/ledger
  写入前 fail closed。双线程覆盖 commit DB window 与 abandon window，均验证等待完整退出和零额外
  证据写入。
- 两项线程测试在继承集合共执行 4 项，P0 三模块 SQLite 禁网回归 `270/270` 通过。
- 当前仍是本地未提交差异，未触网、未 push、未部署，也未执行生产 task 5.3/5.4；需再次
  fresh read-only review。

## 2026-07-24 fresh review P1/P2 已完成本地返修（待复审）

- `prepare` 现与同批正式 commit 共享 execution lock，锁顺序保持 `execution -> state`；commit
  不会在 prepare service、manifest/workbook/checkpoint 窗口尚未结束时读取半更新证据。
- completed commit 普通重放在任何 production dry-run、数据库 apply 或 publish 前，完整复验
  冻结 candidate、artifact/release、commit/publish checkpoint、committed completion run 与唯一
  精确匹配的 v2 auto-publish ledger。证据缺失或计数不匹配时要求人工审计并零写 fail closed。
- 新增 3 项 RED→GREEN；成功重放断言 completion run/source/audit/task log/业务表、state、ledger
  全部零写。P0 三模块 SQLite 禁网回归 `266/266` 通过。
- 当前仍是本地未提交差异，未触网、未 push、未部署、未执行生产 task 5.3/5.4；上一轮 review
  不覆盖本补丁，必须 fresh read-only review。

## 2026-07-24 最新主线集成 publish 幂等 P1 已修复（待 fresh review）

- 最新集成 review 的唯一 P1 已完成 RED→GREEN：相同 candidate 的普通重复 commit 在
  `publish:<region>` 已 completed 时只复用冻结 checkpoint/report，不因后续人工降级或 gate 放宽
  再次调用发布。publish 未完成或失败时普通 commit 在 DB/publish 重跑前 fail closed，只允许显式
  `--retry-publish` 恢复。
- 新增 3 项定向测试；auto-publish 类 `72/72`、P0 相关三模块 `263/263` 通过。Django check、
  迁移漂移、旧规格流程 strict/all 与 diff check 见本轮最终验证记录。
- 当前仍是本地未提交差异；先前针对 `41086464` 的 review 结论不覆盖本补丁。未触网、未 push、
  未部署，也未执行生产 bundle/prepare-release/commit；下一步必须 fresh read-only review。

## 2026-07-24 task 5.3 门禁已集成最新主线，等待精确提交复审

- 用户已授权提交、同步主线、复审、部署并执行无写入 task 5.3；task 5.4 的数据库写入和自动首发
  仍须针对最终 release-candidate SHA 重新授权。
- 最终未提交受审差异 fingerprint
  `15f8c3b80b0ddd0a6715dfbee0c17ba8a0ede59bac8ad6b22c8bdb540f1fbbbe`
  已提交为 `ffa12214`。随后获取并显式合并
  `origin/main@97dd2350a193c74d5063bf7432a283e4d47f6d0a`，集成提交为
  `8e3716bc`；四份追加式状态文档冲突均保留双方完整记录，代码无冲突。
- 集成及 4.10j 返修后 P0 相关 `263/263` 通过，主线新闻边界/赛事系列身份相邻回归
  `90/90`（1 skip）通过；Django check、迁移漂移、旧规格流程 strict/all `37/37` 和 diff check
  通过。相同禁网 SQLite/Celery eager 环境下，最新主线完整基线为
  `2784 tests / 21F / 67E / 59 skipped`，集成提交为
  `2882 / 21F / 67E / 59 skipped`；新增 98 项，failure/error/skipped 增量均为 0。
- 当前集成提交尚未完成新的原生只读 review，尚未 push 或部署，也未运行生产
  bundle/prepare-release。生产网络 false、马匹数据和公开状态沿用上一条已核验证据；下一道门禁
  是对精确集成提交进行只读复审，成功后才可推送和部署。

## 2026-07-23 task 5.3 发布候选门禁已完成本地实现（未提交、未部署）

- 用户已确认 `p0batch-20b59bda0608` 工作簿中 61 匹完整资料可以向下推进；39 个 blocker 继续
  排除，不得进入 bundle、commit artifact 或自动首发范围。原工作簿和 SHA 保持不变。
- 现有 `--commit` 会在同一调用内生成正式 release manifest、写批准账本、写数据库和自动首发，
  无法在写库前展示最终 artifact SHA、预计动作与公开范围。本轮新增
  `--prepare-release`：只生成无批准语义的
  `p0_horse_production_release_candidate.v1`、确定性 commit artifact、预计数据库动作和冻结
  publish scope；不写马匹业务表、不公开、不产生 `release_approved`。
- candidate 使用 SHA 专属不可变 research/mapping/authority、artifact、candidate 和 v2 release
  路径；正式 commit 必须接收用户批准的精确 candidate SHA，通用 production apply 也会复验真实
  candidate、state、batch manifest 与有序 ledger，拒绝 superseded/abandoned/stale 证据。
  自动首发只处理 candidate 中冻结为 `attempt_publish_after_commit` 的已复审对象，不再使用整个
  Japan 100 匹 manifest；39 个 blocker 不会被同地区范围误带入。
- prepare、bundle、prepare-release、commit/checkpoint/publish/abandon 现使用共享 state lock 与
  独立 execution lock；支持崩溃恢复、候选替换与幂等 retry，并保持 v1 历史 release/legacy
  publish ledger 的只读兼容。PostgreSQL 自动发布改为每匹在独立事务内锁行、重验 gate、写状态与
  OperationLog。第十轮 full-diff review 后，execution lock 已改为同线程同 batch 可重入；
  standalone v2 dry-run/commit 从 validation 到数据库事务退出全程持锁。未落库 artifact 还会
  比较 current batch manifest/combined 的真实 SHA；只有精确 artifact path+SHA 的 committed-run
  才允许从不可变 snapshot 幂等恢复。
- TDD 与复验：相关
  `stable.test_horse_profile_publish + stable.test_p0_horse_completion_batch +
  stable.test_p0_horse_production_apply` 为 `260/260`；Django check、迁移漂移、旧规格流程
  strict/all `37/37`、diff check 通过。完整 stable：基线
  `21610ae8` 为 `2748 tests / 21F / 67E / 57 skipped`，本分支新增 88 项后为
  `2836 / 21F / 67E / 57 skipped`，失败/错误/跳过增量均为 0；既有失败集中在历史 runner 的
  macOS 临时路径、实时赛果时钟和旧页面/环境契约。
- 独立原生只读 code review 第十一轮已对最终完整差异给出 `APPROVED`，P0/P1/P2 actionable
  finding 均为 0；session `019f901d-7b9f-77e3-96e0-792546d3eb4f`，审查前后 fingerprint
  `60cf62da1514f00fce451c89aa39b46146d20a4ef5245bdc84651a037559e164` 一致。当前仍是未提交
  工作区，尚未部署、未执行生产
  bundle/prepare-release，生产网络开关保持 false，马匹数据库与公开状态未变化。下一步必须先取得
  对最终精确集成提交的 commit/push/deploy 授权；部署后 task 5.3 也只运行 bundle +
  prepare-release 并停在 candidate SHA 复审，不写马匹数据。

## 2026-07-23 task 5.2 精确版本 v3 触网 prepare 已通过解析验收

- 用户授权的不可变版本为 `5eec316f073a3107d2887f724e95762f76f27ae2`。执行前发现生产
  `main/HEAD=17d7757aec764755394339400eb2523eae896fa5` 已包含另一条并行发布分支，和目标提交
  同源于 `d64c6926` 但互不为祖先。为避免回退已上线功能或用 merge commit 冒充精确版本，
  本轮不移动生产 HEAD、不重建在线服务；服务器从目标 Git tree
  `28a46542768fd8441dbfbd3a29ab0f67ccbd43d5` 构建一次性镜像
  `sha256:e543065ce08033b9d1b871478a85141c8b728334ec662bf6ea17fd2dcb1323f9`，镜像 revision
  label 固定为完整目标提交。select/approve/validate/prepare 均由该镜像执行。
- 本轮恢复点为 `.env.backup.pre-p0-v3-task52-20260723T024436Z`（SHA-256
  `dee182cb5b35194c3f3661e94119c36e63dc684d9fff992517d872fc50167d0a`）和
  `backups/db/pre-p0-v3-task52-20260723T024436Z.dump`（`234645581` bytes、SHA-256
  `d43de53684a430da403c1d5b5d224dd21c8194e0ef9ad95f03f8f0ca0077dce0`、
  `pg_restore -l` 1018 项）；回滚镜像标签为
  `umanewsbot:rollback-pre-p0-v3-task52-20260723T024436Z`。
- 新批 `p0batch-20b59bda0608` 为 Japan 100/100；profile ID、candidate key 均 100 个唯一值，
  100/100 各有且仅有一个数字型 `netkeiba:{id}` 和一致的 Netkeiba URL。`mentianlu` 审核批准后
  manifest SHA-256 为 `51ac349ebd45848abb89c9f29545e695a760d245e09e72fcecc0de4bfaefa44f`，
  validate 通过。
- prepare 由精确镜像中的 `netkeiba-parser.v3` 执行，100 个 checkpoint/staging 均成功，
  300 次网络请求、缓存命中 0、8 秒 host interval。最终 61/100 完整、39/100 blocker：
  32 个候选缺 `expected_sire_name/expected_dam_name/expected_birth_year`，6 个来源履历行缺核心证据
  而以 `partial_career` fail closed，1 个为官方 51 场、采集 50 场的生涯缺口。
  `unexpected_adapter_error=0`；`netkeiba_profile_structure`、`title_status`、`title_sex`、
  `title_color` 均为 0，说明 v3 针对合法省略状态的系统性误判已消除。
- 审核工作簿为
  `runtime/horse_profile_completion/review/p0batch-20b59bda0608.xlsx`（18379 bytes、SHA-256
  `bee158e6d70c099c550102df6f9221b2d6bbb5fb75697d50a06d6d87b61cbc9f`）。本轮未运行 bundle、
  commit 或自动首发，马匹数据库计数保持总计 46318、日本 11642、公开 2797、日本公开 2463。
- prepare 结束后一次性联网容器已自动删除；宿主 `.env` 及 web/worker/beat/race_live_worker
  均仍为 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`，HTTP healthz 通过。在线生产保持
  `HEAD=17d7757a`、parser v2；web/worker/beat 使用镜像 `sha256:5a3dd28b...`，
  `race_live_worker` 仍使用先前镜像 `sha256:07f46301...`。该镜像差异早于且独立于本次一次性
  task 5.2 执行，本轮未擅自重建并行发布服务，需由对应发布线单独核对。
## 2026-07-24 HRN 新闻正文边界已部署，历史中文稿未重处理

- PR `#12` 已合并，生产运行 `main@0e4a3520`；四个应用服务统一使用镜像
  `sha256:36b9a75b854f9be0ccfb7beca164a69e9a5f79bab77b4bcd2f4cbb9f50356733`。
  无新增 migration，Django check、worker ping、内外 healthz、首页和文章详情 HTTP 验收通过。
- 生产镜像只读解析文章 `9623` 的真实 HRN 来源页得到 `.article-body / ok`，正文 9,355 字符，
  已知页面框架文本命中 0，首尾均为文章正文。
- 部署后的自然 HRN job `27503 / 27504` 均成功，但只有重复文章，尚无此前从未入库的新 HRN 稿件；
  Gate A 的新稿翻译和公开验收必须等待真实新样本，不能由重复抓取替代。
- 自然重复抓取已把 `9623` 原文层更新为干净正文；旧中文译文和公开 `effective_body` 仍保留历史污染。
  本次未重译、改写、重新发布、发送 QQ，也未执行历史扫描或 manifest commit；Gate B/C 仍需独立授权。
- 恢复点、部署过程和 `collectstatic` 并发插曲详见
  `docs/changes/fix-news-body-extraction-boundaries/release_report.md`。

## 2026-07-23 2026 赛事系列身份归并：只读审核工具已部署，正式审核包待人工定稿

- 新建 `docs/changes/reconcile-2026-race-series-identities/` 五份规划文档，目标是完整盘点正式快照中
  全部 2026 历史目标，同时仅把人工批准且兼容既有引擎的唯一匹配候选纳入首批写入。
- 2026-07-23 生产只读探索基线为 1,085 条 target：684 已关联、226 唯一名称匹配但系列不同、
  11 同名多候选、162 无名称匹配、2 未举办；226 条中当前 215 条满足既有引擎严格条件。正式
  导出必须重新锁定快照，任何漂移都需显式确认。
- 独立方案评审首轮提出 3 项 P1、2 项 P2；修订后限定复审再发现 1 项 P1、1 项 P2，现已全部
  关闭并得到 `VERDICT: APPROVED`。关键门禁为：原始 manifest 是独立信任根；只有唯一匹配表
  可产生动作；首批单一 manifest/单事务；穷尽分类并阻塞异常；审核包严格字段白名单。
- 已新增只读审核适配服务和管理命令：在 repeatable-read 快照内穷尽分类，生成
  JSON/CSV/六 sheet XLSX/manifest；定稿回读绑定原始 manifest，只有唯一匹配表可产生既有引擎
  decisions，命令不提供 commit 模式。工作簿已完成实际渲染返修，操作列前置并带动作下拉。
- RED 阶段为目标模块缺失导致 1 项失败、12 项安全跳过；GREEN 及代码审核返修后，新增/既有身份
  专项 SQLite 48 项通过（3 项 PostgreSQL-only 跳过）。真实 PostgreSQL 16 的 repeatable-read MVCC、行锁和
  双事务竞争同一 target/destination 均通过，竞争结果严格一胜一败且败者零部分写入。
- 1,085 targets / 1,500 event identities 等价规模两次构建 0.121 秒。完整 `stable` 对测试基线
  `origin/main@15645b05` 对照（后续 `d64c6926` 仅为 netkeiba 发布证据文档）：主线
  `2741 / 21F / 70E / 57S`，本分支
  `2769 / 21F / 70E / 59S`，新增 28 项且失败/错误增量为 0；新增 2 项跳过均为 PostgreSQL-only。
  Django check、无迁移、compile、三份 Compose config 和 diff check 通过。
- 独立原生代码 review 首轮发现 1 项 P1、1 项 P2；首次限定复审确认原问题关闭后发现 1 项直接
  P1（审核后新增 do-not-merge veto），下一轮又发现同边界 P1（source/destination series 身份未
  锁定）；现均已修复为四对象 identity SHA + 当前 veto 双重门禁并通过目标回归。行为代码最终
  原生只读 review 已 `APPROVED`：parent
  `d64c69264df8bf16389e99514fb4ab553ca3f37b`、content manifest
  `943431514ffa8b814fc2076eb40ad96ddc5d25a6b1896cd81b1e9a7504bacdd2`、fingerprint
  `db9d0f9b00cad1f1fbfcc784837fc54210e78bc7e7a292b0b720cd85f23c1c85`。随后只修改状态文档，
  文档增量限定 review 以同一 parent 得到 content manifest
  `d513dd8cd61031013d3e365b23c2af655d6b3a802ae20bf48c0c793104855d53`、fingerprint
  `2062b52e452fdecafacb10ae572dd27a26cddf751a56145532323b50a542f4c6`，并作为发布前最终冻结基线。
  三项 P2 与一项探索 identity-set digest 建议已记入非阻塞后续。
- 用户在最终 review 后明确授权提交、推送、部署只读工具和生成正式生产审核包。审核内容以
  `INDEX_TRANSITION_OK` 锁定后提交为 `17d7757aec764755394339400eb2523eae896fa5`，任务分支和
  `main` 均已推送；生产从 `15645b05` fast-forward 到该提交并运行 `deploy_lowcost.sh`。无迁移，
  Django check、命令 help、web/worker 同镜像和 HTTP `/healthz/` 均通过；镜像为
  `sha256:5a3dd28b846954837ade517e5d85aa2bba3b4651d322876f950f0cdfcda45e44`。
- 正式 repeatable-read 导出时间为 `2026-07-23T02:44:23.655795+00:00`，生产五分类计数与探索
  基线一致：`1085 = 684 + 226 + 11 + 162 + 2`，异常 0、`blocks_decisions=false`。当前没有
  identity-set digest，因此该证据不能排除 target/candidate 集合发生等量替换。审核包保存在
  `runtime/race_series_identity_review/formal-20260723T104700+0800/`，manifest SHA-256 为
  `9d0df5da1e942f77bbabe9df7c84a921ea9325564ce821ab5f17ebf2f13eee47`；五文件已复制到本地并
  独立核对 SHA，六 sheet 实际渲染和公式错误扫描通过。本阶段只运行导出模式，未生成 decisions、
  未运行 prepare/apply/commit，未写生产业务数据；下一门禁是人工审核并定稿工作簿。

## 2026-07-24 HRN 新闻正文边界已集成最新 main，待同会话复审

- 独立干净 worktree 位于
  `/Users/mentianlu/.codex/worktrees/fix-news-body-extraction-boundaries/umanews`，分支为
  `codex/fix-news-body-extraction-boundaries`，基线是已核对远端的
  `origin/main@45ded0834e6517a544ad2acd600503e127bd59ef`；主工作区的其他未提交修改未被触碰。
- 只读复现确认公开文章 `9623` 与同源 `9519` 都含 HRN ticker、登录入口和相关推荐等页面框架。
  根因位于 `HorseRacingNationAdapter.body_selector = "article, main"`：当前 HRN 页面没有语义
  `<article>`，真实正文位于 `.article-body`，解析器因而选中整个 `<main>`。污染随后写入
  `body_ja_raw/body_ja_normalized`，继续进入翻译、改写与 `effective_body`；公开模板本身没有拼接来源框架。
- 仓库已有可信正文选择、通用清理、`original_content_html` 留存、边界 fixture 和显式 ID 离线 repair
  命令，可用于最小来源级修复；仓库没有 `9623` 的 HRN 新闻 fixture，但生产文章按模型约定应保留原始 HTML。
- durable artifacts 已写入 `docs/changes/fix-news-body-extraction-boundaries/`。建议方案是将 HRN 收紧为
  `.article-body` 且选择器漂移 fail-closed，并扩展只读、有界、分批的历史候选识别；不使用中文词黑名单、
  文章 ID 特判或模板隐藏。
- 独立方案 reviewer 首轮提出三项 finding：upsert 前阻断、历史 manifest/哈希原子绑定、Gate A 不得用既有
  文章重复抓取验收。规格修正后由同一 reviewer 会话限定复审，三项均关闭，结论 `VERDICT: APPROVED`。
- 审核后静态校验发现 `.codex/scripts/check_workflow_contract.py` 仍硬编码旧七阶段 marker；当前没有修改该脚本
  或配套测试，已把测试先行同步列入待实现范围。补充 reviewer 的两项 P1（T16 GREEN 门禁与固定 `26/26`
  inventory 策略）已修正并由同一会话复审通过，最终仍为 `VERDICT: APPROVED`。
- 用户明确“开始实现”后，测试 subagent 先取得目标 RED；实现 subagent 已将 HRN selector 收紧至
  `.article-body`，在国际详情 upsert 前 fail-closed，并完成只读历史扫描、manifest/hash 原子 repair 与八阶段
  workflow checker。没有模板隐藏、中文词黑名单或文章 ID 特判。
- 主代理整体验证：正文边界 `43/43`、抓取相邻回归 `13/13`、workflow contract `26/26`，Django check、
  compileall 和 `git diff --check` 均通过。
- 未参与实现的 reviewer 已实际执行原生只读 uncommitted review；内层只读、退出码 0、审前审后 fingerprint
  逐字节一致。首轮四项 P2 涉及扫描分类/风险字段、CrawlJob 详情失败计数和旧 runbook commit 流程。
- 测试 subagent 先为 findings 取得目标 RED；实现/operations subagent 已修复并重新取得正文 `43/43`、抓取
  `13/13`、workflow `26/26`、Django/static 全绿。runbook 现从 dry-run 推导唯一来源并绑定精确 ID manifest/SHA。
- 第一次限定复审关闭两项，另指出 `fail_count` 不得改变既有 duplicate 语义，以及 explicit dry-run 尚未提供
  runbook 所列人工审查证据。第二轮 RED/修复后，详情失败改由持久 `detail_failures=N` token 记录；dry-run 直接
  输出同一 ID 的首尾短摘要、长度/哈希、状态、有效层、人工/改写、发布时间和 QQ 数，完整回归再次全绿。
- 旧审核版本曾获得发布授权，但发布前完整 fingerprint 因 `origin/main` 前进而漂移，门禁在 staging 前停止。
  最新 main 集成 review 又发现 manifest 未绑定全部持久化输出这一项 P2；测试 subagent 取得有效 RED 后，
  manifest 已升级为 v2，同时绑定标题、原始正文、标准化正文和解析元数据，legacy v1、缺字段或任一输出漂移
  均整批拒绝。当前正文边界与相邻抓取回归 `58/58`、workflow `26/26`、Django check、compileall 和 diff check
  全部通过。必须由同一 reviewer 会话完成限定复审，并在成功后重新取得
  当前集成版本的发布授权。未执行生产历史扫描或生产重处理，未 commit、push、建 PR、部署或写生产。
## 2026-07-23 2026 赛历赛事中文名补齐已写入生产

- 根据发布时保存的执行证据，573 场 2026 年已发布赛事已完成单事务写入：
  `written=573`、`veto=0`，`--verify` 返回 `ok=true`。生产写入绑定
  manifest SHA-256 `b9f1e8b73e84da9df141a78081a1da2ba29d727539f12ce2fb708a95df4375c8`
  和 OperationLog batchId `d2e2b203d9c3e67f683650c397ed6af038c17123d9c54cf71bdb302b784ce673`。
- 发布时保留的核验记录为：已发布赛事空中文名 0、非 CJK 回退 0；五地区赛历卡片
  非 CJK 标题 0；4 场详情页返回 200 并渲染中文名。spec 要求跨地区详情页抽查
  至少 5 场，因此现存证据少 1 场，该数量验收项未满足；本轮也未重做全量验收。
- 历史记录中的 Claude Code「等价复审」不是现行工作流要求的 Codex 原生只读 review；
  且被授权的 `bd03b100` 与最终部署的集成版本 `6167b6c0` 不同，没有现存证据证明
  集成版本获得合格原生复审和其后的新授权。生产结果成功是事实，但不能补证这一治理门禁。
- 本轮只做公网 HTTP 抽检：`/healthz/` 返回 `{"status":"ok"}`，2026 赛历页抽样标题为中文。
  HTTPS 在本地代理链路上握手失败，本轮未将 HTTPS 记为已验证。
- 详细发布记录见 `docs/changes/translate-2026-race-display-names/release_report.md`；写前备份为
  `backups/db/pre-translate-2026-race-names-20260723_012307.dump`。

## 2026-07-23 publish_ready 积压治理（21 篇历史稿已舍弃，五地区新 24 小时观察中）

- 旧规格流程 change `recover-publish-ready-backlog` 已完成代码主体：`NewsArticle` 新增 nullable
  `publish_ready_at` 和 `region/status/time` 组合索引，迁移不回填历史值。新稿仅在
  “非 ready → publish_ready”时写入资格时间；重复校验、普通保存和历史 NULL 均不自动刷新，
  只有显式榜单重处理或审核 manifest 恢复可刷新。
- 发布候选拆为两个独立有界通道：实时通道继续读取最近 3 小时首次入库/榜单唤醒；积压通道只读
  主地区、0–24 小时内的 `publish_ready_at`。每通道默认最多 200 条，按文章 ID 合并，统一经过
  主地区、硬门禁、内容指纹、分数、软填充和配额；同分时先消费更早 ready 的稿。积压总开关
  默认关闭，且必须另填地区 allowlist。
- 24–72 小时稿只进入人工复核指标，>72 小时稿进入过期处置指标，历史 NULL 单列；三者均不得
  自动公开。地区生产后台展示四层计数和最老年龄；异常任务按
  `stale_publish_ready_review` 独立冷却告警，不在选择窗口暗改文章工作流。
- 新命令 `reconcile_publish_ready_backlog` 支持不可覆盖 dry-run manifest、独立 decisions 文件封印
  reviewer 和新 SHA、以及显式 `--confirm-apply`。apply 逐篇锁行并核对状态、更新时间、内容和
  门禁指纹；默认动作 `keep_manual` 零业务写入，`revalidate_refresh_ready` 只有完整重校验通过
  才刷新资格时间，`discard_ignored` 则沿用后台忽略语义设置 workflow/review/automation 三层
  `ignored` 和 `ignored_at`。两种写操作均记录 reviewer、manifest SHA 和动作；命令不设置
  `published_to_web_at`、不创建 QQ delivery。
- 当前验证：含舍弃动作、审计、零公开/零 QQ 和幂等重放的专项 20/20；真实 PostgreSQL 16 的
  1,000 条 ready 积压测试加载上限 200、候选 SQL
  2 条、测试主体 0.456 秒；相关/相邻 118 项通过。完整套件候选为
  `2635 tests / 14 failures / 67 errors / 57 skipped`，同一 `origin/main@26eb03e3` 基线为
  `2616 / 14 / 67 / 57`，新增 19 项且新增失败/错误/跳过均为 0；现有失败集中在历史 runner
  macOS 临时路径、准实时赛果时钟和既有环境契约。迁移 apply/rollback/reapply、Django check、
  三份 Compose、旧规格流程 strict/all、compileall 和 diff check 均通过。
- 舍弃动作已从生产 `3d573583` fast-forward 部署到
  `7a6f30d8708c0560ba2120c44fd640ff35a7ea3e`，web/worker/beat/race_live_worker 统一使用
  `sha256:fa2fdf9bb952…`。本次恢复点为
  `.env.backup.publish-ready-discard-20260723_001049`（SHA-256 `467b6398…`）和
  `backups/db/pre-publish-ready-discard-20260723_001049.dump`（SHA-256 `d6f6e342…`、
  `pg_restore -l` `1018` 项）。迁移无新增，Django check、四应用镜像一致和 HTTP healthz 通过。
- `0053_newsarticle_publish_ready_at` 已应用，列与 `news_region_ready_at_idx` 存在；历史
  21 篇的资格时间仍保持 NULL，现已按审核决定标记 ignored。初次部署后先保持通道关闭：五区只读预览加载日本实时
  8 条、英国 2 条、其他 0，候选决策和配额账本前后均不变。
- 香港单区真实生产观察已完成：`17:45 / 18:00 / 18:15 / 18:30` 四个独立窗口
  `50846 / 50881 / 50905 / 50931` 均 `succeeded`，每窗口均为实时 0、积压 0、公开 0；
  候选决策 0、地区窗口配额写入 0、历史 ready 仍 21、stale CrawlJob 0。期间公网
  HTTP `/healthz/` 持续 `200`，应用/数据库关键异常日志 0，Web/Worker/DB 最终快照约
  `328/492/185 MiB`，队列无持续增长。
- 首轮五地区观察从 `2026-07-22 18:45` 开始，期间 13 篇新鲜候选正常公开，自动选中稿最大
  ready 年龄 `0.625h`，未选中/公开任何 24 小时以上或 legacy 稿。约 `23:00` 并行 P0 部署
  重建 db/web 并停掉主 worker/beat，观察连续性失效；本任务按批准方案把
  `MULTIREGION_PUBLISH_BACKLOG_ENABLED` 回滚为 false、恢复四应用容器和 healthz，未回退对方提交。
- 用户已确认原 manifest 的精确 21 篇全部舍弃。pending 文件仍为
  `runtime/news_integrity/publish-ready-legacy-20260722_173639.json`（内部 SHA
  `b72ddc927a3f…`，文件 SHA `a125647ac6a7…`），apply 前 21 篇快照漂移为 0。封印产物为
  `runtime/news_integrity/publish-ready-legacy-discard-approved-20260723_001547.json`（manifest SHA
  `860fbec26c8982515f11ab888637a915e1a0b9fbdbd113475ced48e616932bb9`，文件 SHA
  `83e396a8ffc2…`）；首次 apply 为 `discarded=21 / skipped=0 / refreshed=0`，同 SHA 重放为
  `already_applied=21`。独立核验为 21/21 三层 `ignored` 且审计匹配，公开 0、QQ 0。
- 部署后停 beat 消化到期抓取，celery/race_live 队列均清零且主 worker active/reserved 清空后，
  以 `.env.backup.publish-ready-observation-20260723_002152` 为开关恢复点重新开启五地区积压通道。
  Web 实际读取 `enabled=true`、五地区 allowlist、自动期限 24h、scan limit 200；开启时只读预览
  为英国实时 1、美国实时 5，其余实时 0、五区积压 0，21 篇仍 ignored/公开 0/QQ 0，healthz 200。
  新有效观察期为 `2026-07-23 00:22:19` 至 `2026-07-24 00:22:19 Asia/Shanghai`，由每小时
  heartbeat `publish-ready-24-restart` 继续；任务 5.4 在完整终点审计前保持未完成。

## 2026-07-22 新闻生产完整性修复（实施中）

- 生产 `public.stable_newsarticle_public_slug_46694cb6` 普通 B-tree 索引已完成备份、停写窗口内受控 `REINDEX INDEX`、事务回滚写入探针、临时 `amcheck bt_index_check` 和真实抓取验证。备份为 `backups/db/pre-news-index-repair-20260722_135849.dump`，大小 `229947588` 字节，SHA-256 `07d2ebd67f1a3c5ec1fb9ddaf93f554639980425dde87c4b19d0cc54a9ae2fb1`。
- 首次观察被并行 P0 马匹部署中断：该部署将生产前移到 `a59536a9d60708556a1c1a1c3b0a46811ab36b72`，重建 db/web 后 Nginx 仍指向旧 web IP，曾短暂返回 `502`。本轮未回退对方功能；恢复必需容器、reload Nginx 并确认四个应用容器均为镜像 `sha256:f48f6523525e…` 后，从约 `14:23` 重新计时 60 分钟。
- `15:23` 满 60 分钟最终快照：重建后 CrawlJob `77 success / 0 failed / 0 started`，CrawlJob、TaskExecutionLog、db 与 worker 日志中的同类索引错误均为 `0`；真实新增文章 `2` 篇，其中日本稿 `9572` 已由正常窗口公开，英国稿 `9573` 进入人工复核。索引仍为 valid/ready/live，HTTP `/healthz/`、首页和五地区入口全部 `200`，应用与数据库资源平稳。历史 stale started 仍为 `32` 且未被索引操作改写。索引修复门禁正式 PASS。
- 完整性代码已以 `HEAD=7ff968c0557300c1240f13a3d6feae3a8df3085d` 部署，web/worker/beat/race_live_worker 均运行镜像 `sha256:712a5da8b408…`，Django check、迁移漂移、Celery 两节点、HTTP healthz/首页/五地区页通过。部署前恢复点为 `backups/db/pre-news-integrity-deploy-20260722_152904.dump`（`230252800` 字节、mode `600`、SHA-256 `810b07829c36c551722168b0a76ab1efc65b7bbd367ddcab6f0741c6b7b5807a`、`pg_restore -l` `1017` 项）及 `.env.backup.news-integrity-deploy-20260722_152904`（SHA-256 `7af509d60ca60f2cf232959d2e779388917a688c3a3210bbb5d70445bda668de`）。
- 停 beat 并排空两节点后生成 manifest `/app/runtime/news_integrity/stale-crawl-20260722_153609.json`，SHA-256 `c4cc4f4975a6246131cd91bf2772aaaeb36d85344fbb02fc6223467567230ea0`：执行时仍为 `32` 条，活动证据完整、活动来源 `0`、未映射任务 `0`，全部建议收敛。apply 为 `32/32`，stale started `32→0`，文章总数/公开数/QQ delivery 与 `NewsSource.last_crawl_*` 哈希前后不变；同一 manifest 重放更新 `0`，新 dry-run 为 `0` 条。
- `16:37` 完成代码上线后 60 分钟观察：新 CrawlJob `61 success / 0 failed / 0 started`，新稿 `1` 篇（日本 article `9575`，正常进入人工复核），stale started `0`、`terminal_state_already_claimed=0`、新索引错误 `0`、部署后异常日志 `0`。修复前索引错误已退出 2h 窗口但继续在 24h 历史可见；P0 信号只生成一次 `4` 个渠道账本行，冷却未重复。四应用容器镜像一致、Celery 两节点正常、HTTP 七入口全部 `200`，本 change 的生产验收门禁全部 PASS。

专项交接入口：`docs/p0_horse_information_completion_handoff.md`。该文档汇总 P0 定义、完整
字段口径、生产计数、关键产物、事故经验、未完成项和后续执行顺序；实时状态仍以本文和生产
核验为准。

## 2026-07-23 netkeiba 首批第二轮生产发现与本地返修

- 生产实时只读核验推翻了旧交接断点：`p0batch-e5cee174ba05` 已在相同相关代码下完成
  prepare，状态为 `prepared`，`100` 个 checkpoint/staging、artifact 与 xlsx 均已生成；
  因此早先 `7/100` 无声退出更符合 detached exec/进程会话中断，不能再按“第 8 匹稳定
  崩溃”直接重跑。
- 该批真实结果为 `27/100` 完整、`73/100` 阻断、`300` 次网络请求：`62` 个已注销马
  标题 `抹消` 未被旧正则识别；`10` 个候选仅携带部分 expected identity 字段，按既有
  完整期望锁阻断；`1` 个 Haru Aube 履历行（2025-03-17 水沢 C1）头数/着顺为空，
  证据不足。三类均 fail closed，没有 bundle、commit 或自动首发；旧批保留证据，禁止
  手改 state 或提交其中 27 匹。
- 生产运行态已于 2026-07-23 恢复：备份 `.env.backup.p0-network-disable-
  20260722T180903Z` 后将 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false` 注入重建的 web，
  重启 Nginx；web healthy，worker/beat/race_live_worker 运行，内外 healthz 与
  `/horses/` 200。生产 HEAD 为 `6167b6c0`，公开马仍为 `2,797`（日本 `2,463`）。
- `add-netkeiba-horse-client` 第二次 Full 方案审核修复 `1 P0 + 3 P1 + 2 P2` 后进入
  implementing。tasks `4.3-4.5` 已本地实现：精确支持 `抹消`；部分 expected identity
  输出字段级可解释 blocker；`NETKEIBA_PARSER_VERSION` 同时绑定批次 fingerprint 与
  日本 netkeiba canonical cache；旧/错版本 cache 强制 miss，JBIS/其他地区不变；
  Haru Aube 不确定行继续阻断，不猜状态。
- 当前修复已重放到最新 `origin/main@0dcdbdab`；集成候选的精确提交与内容身份由最终
  base review 报告在仓库外固定，避免在提交正文中自引用过期 SHA。运行手册冲突按
  “保留主线新发布记录并追加本专项段落”解决，代码无冲突。P0 聚焦回归 `285/285` 通过；
  Django check、迁移漂移、旧规格流程 strict/all `37/37` 与 diff check 通过。完整 `stable`
  回归为 `2741` 项、`21 failures + 70 errors + 57 skipped`；同一环境下 `origin/main` 基线为
  `2726` 项且失败/错误/跳过计数完全相同，本轮新增 15 项测试，没有新增失败。首次全量运行暴露的 2 个本轮
  错误文本兼容失败已修复并完成聚焦及全量复跑。首次独立原生 code review 另发现旧版
  netkeiba cache 虽 miss、但新抓取结果无法替换已有文件的 P1；现已用 sidecar 文件锁与
  `os.replace` 原子替换，并新增单线程/并发回归；同一 reviewer 连续复审已清零 actionable
  finding。最新主线集成最终 base review 以 `0dcdbdab` 为 base、`15645b05` 为 HEAD，
  content hash `d3a26c24…342c7`、fingerprint `43313e31…2441`，0 actionable findings；
  用户随后明确授权部署该精确版本并保持网络关闭。
- task 5.1 已完成生产部署：远端 main/生产 HEAD 均为 `15645b05`，四个应用容器统一镜像
  `sha256:07f46301e77eb64cdd4899fee8a1b66d4b3ad5c79b5f5847e15a9ac985f176ef`；无迁移，
  Django check 通过，宿主源码与容器 adapter SHA 均为
  `444c62a709454f576cdd818e858fc07c3d24df1884ebc3de72794a05adfe744e`。
  `.env`、web、worker、beat、race_live_worker 与 Django setting 均验证 network=false，
  parser version 为 `netkeiba-parser.v2`；内外 healthz、`/horses/?region=japan` 与 www
  healthz 均为 200，近期应用日志无 error。公开马仍为 `2,797`（日本 `2,463`），本步未
  触网、未运行 prepare、未写马匹资料。触网 prepare 继续等待 task 5.2 的单独授权。

## 2026-07-23 task 5.2 首次触网未通过验收，已关网返修

- 用户授权后执行独立恢复点：`.env.backup.pre-p0-task52-20260722T193712Z` 为 `8,554`
  bytes、mode `0600`、SHA-256 `fd647e09…5b35`；数据库 dump 为 `232,970,028`
  bytes、mode `0600`、SHA-256 `8aecbce1…c4a2`，`pg_restore -l` 为 `1,018` 项。
  beat 先停，两个 Celery 节点 drain 到 active/reserved 均为 0，再停 worker 与
  race_live_worker。
- 生产默认相对路径会把新 select 写到 `/app/server/runtime`。两个仅 pending、未抓取的
  预检批次 `p0batch-97888727f9f8`、`p0batch-cbd8ed561515` 已正式 abandon 留证；`.env`
  已把 batch/review/cache/budget 四个目录显式设为 `/app/runtime/horse_profile_completion/*`
  并通过 Django setting 验证，避免重建 web 后丢失批次与 xlsx。
- 旧批 `p0batch-e5cee174ba05` 已正式 abandon。正式新批
  `p0batch-5802d72da799` 为日本 `100/100`、全部持有唯一 `netkeiba:{数字 ID}`，由
  `mentianlu` approve；批准 SHA 为 `204fa275…9125b8`，validate 通过。prepare 使用
  `300` 次网络请求、缓存命中 `0`，生成 xlsx
  `runtime/horse_profile_completion/review/p0batch-5802d72da799.xlsx`（SHA-256
  `34e849eb…08f9`），未 bundle、未 commit、未自动公开。
- 本轮结果为 `45/100` 完整、`55/100` blocker，未通过 task 5.2 验收：`20` 条
  `netkeiba_profile_structure: title_status`、`32` 条 expected identity 三字段缺失、
  `2` 条 `partial_career` 被误归类为 `unexpected_adapter_error`、另 `1` 条仅
  `incomplete_career_history`。失败批已正式 abandon 并保留 artifact/xlsx。
- prepare 结束后立即恢复网络关闭；`.env`、web、worker、beat、race_live_worker 与
  Django setting 均为 false。四服务恢复，web healthy，Celery 两节点响应，Django check、
  应用日志、按 Host 的 HTTP healthz 与日本马匹页通过；总马匹 `46,318`，公开仍为
  `2,797/日本 2,463`，证明本步没有马匹资料写入。
- 源页面复核确认上述 `20` 条不是未知状态，而是 `.txt_01` 合法省略状态、只显示
  “性别年龄 + 毛色”。本地返修改为独立读取 `.eng_name` 与 `.txt_01`，只允许状态为空或
  既有枚举，未知状态仍 fail closed；已知 `partial_career:` 改为可解释 source blocker。
  canonical 解析规则变化使 parser version 必须递增为 `netkeiba-parser.v3`。
- 本地验证：四套件 `292/292`，Django check、迁移漂移、旧规格流程 strict/all `37/37`、
  diff check 通过；完整 `stable` 为 `2,748` 项，干净 HEAD 基线为 `2,741` 项，两边均为
  `21 failures + 65 errors + 57 skipped`，零新增失败。独立 review 首轮发现真实 validator
  包装路径未覆盖的 `partial_career` P1；改为沿 cause 链精确识别底层 blocker、测试改走真实
  canonical validation 后，同一 reviewer 最终 `APPROVED`、0 actionable findings。返修尚未
  部署；task 5.2 保持未完成，下一步是冻结受审精确版本并重新取得部署/触网授权。

## 2026-07-22 netkeiba 马匹客户端专项：本地实现完成（未部署）

- 旧规格流程 change `add-netkeiba-horse-client` 完成 plan-eng-review 与全部本地实现
  （tasks `0.1-4.2`），解开 2026-07-22 首个日本批次 100/100 JBIS 同名歧义阻断。
- 核心实现：`_NetkeibaClient`（按候选 `netkeiba:{id}` 直取马匹页 + 战绩页 + 血统页
  3 页，provider-bound 身份，页面提取四字段与完整生涯）；`_JapanDispatcherClient`
  （netkeiba key 候选走 netkeiba、其余保持 JBIS）；select 阶段日本候选 netkeiba
  namespace 偏好（其余保持 identity_keys 顺序，确定性）；日本每候选预算 3→4。
  解析全 fail closed：结构不识别/年份生日/未知毛色/未知单字产地一律阻断不猜值；
  异常状态四档映射（取消/除外不计出赛、中止/失格计出赛）；海外行按 JRA/NAR
  场地名单判定；通算成績与逐场对账由 adapter 既有 gap 逻辑处理。
- plan-eng-review 修复 1 P0 + 6 P1：选择层位置（select 偏好 + dispatcher 而非
  adapter client_factory）；生涯总数在马匹页非战绩页；年份生日只能阻断；
  状态映射枚举；页面字段口径对照真实页面。
- 独立 code review 修复 2 P1 + 6 P2：frozenset 迭代非确定性回退为 identity_keys
  顺序；毛色白名单防「4歳」被当毛色；未知单字产地 fail closed；NAR 数字前缀
  场地（2大井8）正确判非海外；移除死代码计数标记；补 4 个场景测试。
- 验证：netkeiba 专项 25/25、补全四套件 266/266、完整 `stable` 2,595 项与基线
  逐数一致（14F+70E，零新增）；sqlite 端到端 select → prepare（缓存）→ bundle
  → commit → **自动首发**全通（四字段写入、verified key 标记、published）。
  真实 fixture 捕获自生产：`netkeiba_{horse,result,ped}_2022110137.html`。
- 本 change 尚未部署生产；生产执行（tasks `5.1-5.2`）需分步用户授权：部署 →
  首个日本滚动批次全链路（触网 prepare + xlsx 人工复审）→ 核验批次自动首发
  （即 `publish-p0-horses-basic-tier` tasks 7.2 闭环）。

## 2026-07-22 P0 BASIC 层自动首发：存量 2,785 匹已发布；首个滚动批次因 JBIS 同名歧义阻断

- 生产已部署 `a59536a9`（备份 dump SHA-256 `77b12edd…`）。provenance 回填完成：重跑
  三个已批准身份回填 manifest 的 commit（幂等），`horse_identity_verified_keys`
  日本 2,462 + 香港 327。
- **存量发布已执行**：`publish-20260722` manifest 经用户批准后 commit，日本 2,459 +
  香港 326 = **2,785 匹发布**，零错误零阻断；审计 OperationLog 2,785 条，
  `published_by=admin`。公开 `/horses/` 现为 103 页（日本区），响应 0.02-0.06s，
  未完整马显示「资料补全中」徽章，抽样详情页 200。全库已发布合计 2,797 匹。
- **首个日本滚动批次被身份锁正确阻断**：`p0batch-37fad126d645`（100 匹）prepare
  触网完成但 100/100 `ambiguous_identity` fail closed——JBIS 名称检索对近年活跃马
  普遍返回 2-4 个同名结果（实测 ドラゴンウェルズ/ディーズメンフィス 各 2、
  コンプリート 4），候选四字段为空无法消歧。身份回填解决了选批但解决不了抓取时
  身份锁（设计已预判）。批次已 abandon 留证。用户决定：先完成存量发布（已做），
  再新开 旧规格流程 change 做 **netkeiba 马匹客户端**（候选 ID 与 netkeiba key 同源，
  URL 直取无检索歧义，页面含父母/出生日期/生涯，同时解开身份锁与四字段两个堵点）。
- 运维状态：ALLOW_NETWORK 已恢复 false，beat/worker/race_live_worker 已重启，
  公网 healthz 200，数据核验 2,797 匹发布完好。
- 本 change 剩余：tasks `7.2`（批次自动首发生产验证，待 netkeiba 客户端）、`7.4`
  （规格同步与归档，随 7.2 一并处理）。

## 2026-07-22 P0 BASIC 层自动首发专项：本地实现完成（未部署）

- 旧规格流程 change `publish-p0-horses-basic-tier` 完成 plan-eng-review 与全部本地实现
  （tasks `0.1-6.2`）：目标是把公开 `/horses/` 从 12 匹推向全部 46,318 匹 P0。
  用户已确认三项产品决策：BASIC 层公开门槛（名称 + 五地区 + verified 身份或三字段
  齐全）、批次审核后自动首次发布、日本先行滚动补全。
- 核心实现：新服务 `horse_profile_publish.py`（BASIC 门禁只信
  `horse_identity_verified_keys` —— 由身份回填 commit 或人工批准批次 commit 写入，
  sync 名称归属 key 不计；hidden/曾 hidden/`auto_publish_blocked` 锁定一律阻断）；
  批次地区 commit 复验通过后自动首发（含 create_new 反查，published_by=批次审核人，
  四通道审计）；发布失败阻断 committed 终态并走 `--retry-publish` 专用恢复阶段
  （retry 必须核验复验通过；同 artifact 全量重 commit 的快照漂移 fail closed 为
  既有行为，未改动）；存量命令 `publish_p0_horse_profiles`（dry-run → 批准 →
  按地区 ≤500/事务 commit，逐匹错误非零退出）；前台「资料补全中」徽章
  （完整档保留正面标签，内部措辞不上公开页）。
- plan-eng-review 修复 2 P0 + 3 P1 + 3 P2：身份信任引入 verified provenance（sync
  归属 key 不满足门禁，存量池精确为回填核验的 2,789 匹）；delta 规格改为 MODIFIED
  两条真实存在的要求；hidden_at 阻断；create_new 覆盖；发布失败阻断终态。
- 独立 code review 修复 3 P1 + 6 P2：retry 必须核验 `idempotent_verification.passed`；
  多地区 committed 需要每地区完整 publish stage；provenance 生产回填步骤（重跑已批准
  回填 manifest，幂等）写入 runbook；门禁要求 key 带非空 ID；发布 save+OperationLog
  同事务；重试合并累计发布清单；存量命令逐匹错误非零退出。
- 验证：专项测试 `test_horse_profile_publish` 23/23、批次套件 116/116（含自动首发
  钩子 11 项）、完整 `stable` 2,569 项与基线逐数一致（14F+70E，零新增）；
  `manage.py check`、`makemigrations --check --dry-run`（无迁移）、
  `旧规格流程 validate --strict`、`git diff --check` 全部通过。
- 本 change 尚未部署生产、未写任何生产数据；生产执行（tasks `7.1-7.4`）见
  `docs/deploy_runbook.md` 顶部操作手册，需分步用户授权。

## 2026-07-22 赛事去让赛清理已写入生产并验收

- 发布提交 `5b491561`（随 `cce280a7` 合并部署）：赛历对象与 race 术语去让赛清理
  **168 条**单事务写入（19 赛历 `chinese_name` + 149 术语 `target_zh`），kept 1550、
  review 2（term 5087/5570 保持原值）零改动，`--verify` 通过，前台抽检无「让赛」残留，
  京成杯系列/术语统一为「京成杯秋季赛」。
- artifact `runtime/artifacts/race-name-handicap-cleanup/20260721T154923Z/dry-run.json`
  （SHA `30d85d1a…`）；写前备份 `pre-handicap-cleanup-20260722_023308.dump`（`pg_restore -l`
  通过）；OperationLog 审计 batchId `23eddf04…`。
- 审核链与完整证据：`docs/changes/remove-handicap-markers-from-race-names/release_report.md`。

## 2026-07-22 P0 身份回填专项：本地实现 + 生产执行完成

- 旧规格流程 change `enrich-p0-horse-external-identity` 完成全部实现（tasks `0.1-6.5`
  勾选）：四个离线证据源（netkeiba `ExternalHorse/Alias`、`ExternalRaceEntry/Result`
  回推、UK/FR `RaceEventRunner/Result.source_refs`、HKJC/NAR 本地 HTML 缓存重解析）
  统一产出 identity 候选，唯一强匹配 + 双向唯一 + 四字段不矛盾才写入，歧义一律
  fail closed 进 `HorseIdentityConflict`；`_participant_identity_keys` 新增
  `horse_url`/`horse_slug` 同源 ID 提取（netkeiba/jbis/nar/hkjc/sporting_life/
  equibase，zeturf 与 HRN 永不生成 key）；回填写入走 dry-run artifact → 人工批准
  manifest SHA → 按地区分批 commit（单事务 ≤500）；冲突聚合输出分组统计 +
  SHA-256 manifest，批量裁决建议经批准后过 `full_clean()` 走既有 resolved 通道；
  批次视角 `metrics_before/after` 按地区报告可采信比例变化。
- 独立 code review 修复 1 个 P0 + 5 个 P1 + 5 个 P2：离线冲突 fingerprint 改为裸
  64 字符 hexdigest（原 72 字符超模型 `max_length`，生产 PG 必崩）；commit 重算
  批准后 manifest 哈希防篡改；alias 路径补四字段矛盾检查；race-entry/UK 路径补
  "key 已被其他 profile 持有"检查；HKJC key casefold 写入消除双形态；participant
  名称查询改 join 避免 IN 超 bind 上限；commit 增加漂移复检（四字段矛盾或同
  namespace 异 key 整个候选丢弃）；聚合统计纳入回填后对齐证据。
- 本地验证：专项测试 `57/57`，批次/adapter/基础套件 `753/757`（4 个失败为
  `RaceEventPageMVPTests` 既有基线失败，stash 基线对照完全一致，与赛事历史
  专项在途改动相关，非本 change 引入）；完整 `stable` 套件失败数与基线相同
  （14 failures + 70 errors，基线 14 + 71，零新增）；`manage.py check`、
  `makemigrations --check --dry-run`、`旧规格流程 validate --all`（30/30）、
  `git diff --check` 全部通过。
- 生产执行（tasks `6.5`，用户逐步授权访问/部署/写入后完成）：生产 fast-forward 至
  `349c822f` 并重建镜像；备份 dump SHA-256 `23818ce0…`。NAR 探针覆盖率 0.02%
  本期不启用；HKJC 缓存重解析 1,036 条证据。经 dry-run 用户审核批准后写入：
  日本 2,462 个 netkeiba key（覆盖率 0%→21.1%）、香港 327 个 hkjc key（385 匹
  合计 7.9%）、法国 1,773 条 zeturf 证据合并进 4,097 条来源（不生成 key）、
  英美无新增。重复 commit 幂等 applied=0；香港地区 sync 重跑后证据完好；
  滚动批次抽样日本前 100 匹 100/100 带 key（回填前首批 0/10）。详细执行记录见
  `docs/deploy_runbook.md` 顶部。
- 已知边界：生产 ExternalHorse 的 netkeiba 记录父母/出生日期全为空，本期未回填
  四字段，日本候选仍不能过批次四字段锁（需后续数据源专项）；冲突聚合基线
  65,042 条 pending / 15,446 组全部 `needs_admin_review`；identity key 仅改善
  治理，不改变批次既有四字段锁与来源复核。

## 2026-07-21 6.7 公开验收：每地区 2 匹已发布，全部可验证项通过

- 已从 50 匹严格完整资料马中每地区人工发布 2 匹（`published_at/published_by`
  留痕，操作 admin，备注"6.7 公开验收"）：日本 曙光将来(4023)/欢快舞步(4330)、
  香港 美丽传承(1368)/时时精彩(11320)、英国 先睹风采(8338)/乔治堡(8367)、
  法国 游历万里(3857)/美艺力量(7669)、美国 Gigante(21619)/In Our Time(21621)。
- 验收结果：公开索引 `/horses/` 10 匹可见；详情页 ×10 全部 `200`，基础资料、
  二代血统、主胜鞍、来源证据区块正常；完整履历分页正常（美丽传承/Gigante 有
  `records_page=2`）；匿名关注 POST `302`、关注流显示已关注马；美国无中文名马
  显示原名 + "中文名待补"提示；公开页面零第三方域名引用（no-network 边界）。
- 新闻 tag：`scan_article_horse_links --article-id 7117 --commit` 创建
  `欢快舞步 ↔ article 7117` 关联并人工确认（status=manual），`/news/7117/`
  已渲染 `/horses/4330/` tag。宽范围 dry-run（article 7000+、2000 篇）显示另有
  `327` 条潜在关联（`candidate` 状态），未 commit，留待后续单独批次处理。
- 移动端：本会话 Chrome headless 与 MCP 均不可用，未截图；页面模板与
  `2026-07-08` 移动验收通过版本一致。用户将自行安排生产端复核。
- 两个 change（`complete-p0-horse-profile-data`、
  `productize-p0-horse-batch-completion`）暂不归档：待用户生产复核移动端、
  以及身份补强专项方向确定后分别处理。

## 2026-07-21 首个生产滚动批次：门禁验证通过，0/10 可提交

- 批次 `p0batch-ef7d482c4401`（日本队列前 10 匹，用户批准后触网）完整跑通
  select → approve → network prepare 链路：checkpoint 状态完整、run 维度预算账本
  `22` 请求、host 限速 artifact、复审 xlsx、blocker 池 `10` 条、地区交错
  （单地区 trivially）。JBIS 马名精确检索结果：`ambiguous_identity=3`、
  `identity_mismatch=2`、`identity_incomplete=4`、`partial_career=1`，全部按
  fail-closed 设计阻断，没有伪造任何完整性。
- 重要产品发现：整个日本 P0 队列 `source_refs` 无 external identity keys
  （赛事导入的出走/赛果行未带外部马 ID），裸马名检索难以唯一解析，
  滚动补全需要先解决身份补强（另起专项）。
- 部署修复：compose 新增 `./runtime/horse_profile_completion` 挂载（web/worker），
  解决容器重建丢批次证据问题，已提交 `88d25de0` 并部署；`.env` 网络开关已恢复
  `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`。
- 用户决定：先做 `6.7` 公开验收（每地区人工发布 1-2 匹），身份补强另起专项。

## 2026-07-21 P0 滚动批次产品化已部署生产（未触网、未写马匹资料）

- 生产已部署 `claude/p0-horse-batch-completion` 分支提交 `b3f44d86`，镜像
  `umanewsbot:prod`（`680ed3a174eb`，新增 `openpyxl==3.1.5`），通过 git bundle
  从 `7ad6adeb` 快进。部署前备份：`.env.backup.p0-rolling-batch-20260721_154508`、
  `backups/db/pre-p0-rolling-batch-20260721.sql.gz`（`224757744` bytes，
  `gzip -t` 通过，SHA-256
  `93ebe2f3da940a4f2daea3d3ef559cbd97cc2d3e6f380d99a5c0e03d989cf3c5`）。
- 部署后验证：`manage.py check` 通过、迁移无新增无漂移（仍 `0052`）、
  镜像内 `openpyxl 3.1.5`、内外 `/healthz/`、首页、`/horses/`、`/races/`、
  后台登录均 `200`；worker 近期无 error。web 重建后 nginx upstream 曾短暂 502，
  重启 nginx 恢复（后续部署建议把 nginx 一并重启）。
- 生产 smoke：`p0_horse_completion_batch --select --regions japan
  --limit-per-region 1` 在真实队列上选出 `ベリングブルー`（无 identity keys，
  按预期标记待身份补强），manifest 正常生成后已用 `--abandon` 清理，未写任何
  马匹资料、未触网；`HORSE_PROFILE_COMPLETION_ALLOW_NETWORK` 生产仍为 `false`。
- 下一步：首个生产滚动批次以单地区小批验证 checkpoint/resume/预算/复审文件/
  批准回写/地区独立 commit 证据后，再按默认 100/500 阈值滚动；随后执行
  `6.7` 公开验收（从已完成 50 匹中每地区人工发布 1-2 匹）。操作手册见
  `docs/deploy_runbook.md` 顶部。本 change 未归档，待首个生产批次与 6.7 完成。

## 2026-07-21 P0 滚动批次产品化已完成本地实现（未部署）

- 旧规格流程 change `productize-p0-horse-batch-completion` 已完成 plan-eng-review
  （2 P0 + 6 P1 + 5 P2 全部修复，phase=reviewed）和全部代码实现，覆盖
  `complete-p0-horse-profile-data` 的 tasks `4.2` 长期版本。
- 批次形态：队列选批（默认每地区 100、单批合计 500，无界执行 fail closed）、
  批次 manifest 人工批准（SHA-256 绑定 + append-only 台账）、抓取 checkpoint/resume
  （BatchRunState + 逐候选输入指纹 + 输出 SHA-256 决策矩阵）、按地区持久请求预算与
  per-host 限速（复用赛事预算工具参数化实现）、瞬时失败有限重试（计入账本、不计
  per-candidate 常量）、每批单独复审 xlsx（地区 sheet + 异常抽样页）。
- 提交链产品化：确定性转换器（crawl artifact → 每地区 research v3，同字节复现）、
  批准回写（mapping decisions + 空美国 authority manifest；美国滚动批次 fail closed）、
  滚动 release manifest 走台账通道（首批仓库白名单仅留首批复验）、每地区独立 commit
  artifact 复用既有 prepare/dry-run/commit 链、串行窗口互斥、commit 后自动幂等复验
  planned write=0 并写入 run 记录。
- 端到端 sqlite 证据：select → approve → prepare（fixture 缓存）→ bundle →
  release → dry-run → commit → 幂等复验全通，`FOREVER TEST` 严格完整落库。
- 本地验证：专项测试 `82/82`、既有 P0 adapter `45/45`、赛事编排 `66/66`、
  Django check、迁移漂移（本 change 无迁移）、旧规格流程 严格/全量 `31/31`、
  `git diff --check` 通过；完整 `stable` 回归与独立 code review 进行中。
- 新增依赖 `openpyxl==3.1.5`（复审工作簿），部署需重建镜像验证。
- 本 change 尚未部署生产、未触网、未写任何马匹资料；生产默认仍
  `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`。首个生产滚动批次建议单地区小批验证后再按
  100/500 阈值滚动；操作手册见 `docs/deploy_runbook.md` 顶部。
- `6.7` 公开验收（每地区人工发布 1-2 匹）仍按计划在本 change 上线后立即单独执行。

## 2026-07-20 P0 首批五地区 50 匹已完成生产提交

- 精确 artifact SHA-256
  `1d7885bed20704b743465a94f3c431533c52d37fa506b96b9e11d4de6bfb922d`
  已按 trusted release manifest SHA-256
  `74be2ce42f425bbd24794fb9573ee8b71348f40b0ed6fc0af8599b167c575153`
  提交生产。首次成功报告 SHA-256 为
  `c12980dcfb8c397a12c3e8367ffad812768d33142164987bf0fc0e201ad566ff`：
  `25` 个既有档案绑定、`25` 个新档案、`1439` 条履历、`50` 条 P0 来源和
  `200` 条模块审核，业务写入计数 `1739`，严格完整 `50/50`。
- 履历对账为 `1432` 次实际出赛、`7` 次未出赛、`4` 次海外出赛、
  实际出赛未知结果 `0`。本批没有创建普通比赛 `RaceEvent`，全库
  `RaceEvent=9867` 保持不变；`HorseRaceRecord` 全库为 `1460`，其中本批 `1439`。
- 提交后审计发现既有档案地区不能代表本批审核地区。修复提交
  `8863f37a679e9196e0bf45b5473c0e9f6657487f` 只允许同 artifact、同 run、仍 active
  的来源修正地区；已撤销或属于新审核的来源 fail closed。生产幂等修复精确更新
  `7` 条 `HorseP0Source.racing_region`，五地区现各 `10` 条；既有
  `HorseProfile.racing_region` 未覆盖。首次 run 摘要继续保留 `1739`，本次
  `7` 条修复只写入 `last_idempotent_verification`。
- 修复前备份为
  `/opt/umanewsbot/backups/p0-horse-postcommit-metadata-precommit-20260719T235117Z`；
  custom-format dump 为 `209222446` bytes、SHA-256
  `82cc39ef3e453d2ba3db716485f7fcf960379401e1eddb9d3acc210b74a972ac`，
  `pg_restore -l` 为 `1017` 行。元数据修复执行镜像为
  `sha256:e54c82251e67d707d8b71c1d60c46089f95e572a372e797b0eb8f082109e89c1`
  / revision `8863f37a`；证据归档后的当前运行镜像为
  `sha256:af880cd208198c1e2ab960d8f39bd60539bdafa422cfb98890d0befbd90ff862`
  / revision `7ad6adeb`。内外 `/healthz/`、两个 Celery worker、队列和近期错误日志通过。
- 最终幂等 dry-run SHA-256
  `6872eaa8756d4ee75b26dd22b526755c35a0f6a8fc3923d00b7f136ca3463e40`
  为 `50` 匹已应用、`1439` 条 existing、全部 planned write 为 `0`。
  `25` 匹中文名已翻译、`25` 匹仍为待译且后台显示原始马名；本批 `published=0`、
  `published_at=0`，没有自动首次发布。每地区人工发布 `1-2` 匹和公开页面验收仍是独立任务。
- 本地最终验证为五地区/P0 组合 `182/182`、真实 PostgreSQL `7/7`、Django check、
  migration drift、旧规格流程 `30/30` 和 diff 检查通过；独立复审最终无 actionable finding。
- 下一批建议继续采用“五地区各 10 匹”的可审计滚动批次，优先处理重点赛事新进入 P0 且尚无
  完整档案的马；沿用本批严格来源、强身份、完整生涯和独立发布门禁。先完成 6.7 的首批公开
  验收，再决定是否提高单批数量，不因本次落库成功自动扩大生产发布范围。

## 2026-07-20 历史节点：P0 Phase A 首次迁移回滚

- 首次真实生产迁移在旧原子 `0049` 的数据回填之后创建索引时触发 PostgreSQL
  `pending trigger events` 错误；事务已完整回滚，生产未应用 `0049`，旧镜像和旧服务已恢复。
- 修复将迁移拆为原子 `0049` 字段、`0050` 数据回填、`0051` 索引/条件唯一约束、
  `0052` authority 字段及 fail-closed 降级，保持单一 leaf，不使用 `atomic=False`。
- 当前仍是 **NO-GO / prepare-only**：二次 Phase A 尚未执行，production mapping、
  candidate artifact、formal dry-run 和 commit 均未开始。

## 2026-07-20 历史节点：P0 美国组合来源获批

- 用户/项目负责人已确认当前冻结批次的美国逐场组合来源满足项目严格标准：HRN 提供主记录；
  Fort George 由 Sporting Life 与 Racing Post 补充；Equibase 只用于官方总出赛数及身份、
  颜色对账。这是针对当前冻结批次的“经独立批准的组合来源完整”，不是 Equibase 官方逐场
  履历，也不全局放宽 HRN 或 `count_aligned_records_unverified`。
- 当前状态严格分为三层：
  - 冻结输入层：v1 SHA-256
    `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd`，v2 SHA-256
    `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7`；两者字节均未修改，
    v2 继续保留原口径严格完整 `40/50`。
  - 审核研究层：pending 准备稿 SHA-256
    `8aba561b856ffbdcd03c2a59228b166315174b539f20aef4ae6412bfe03b1b61`，独立批准 manifest
    SHA-256 `29091d69573bab907cda2e9a081ae4684838b92d1f9b052a7601b6109a541077`，v3 研究派生物
    SHA-256 `98a7019a400f10a4bf961d869f38f770e9e98afab76b557a3c784d4eff6e470e`。该层严格完整
    `50/50`；美国共 `198` 条逐场，Fort George 精确为 HRN `6` + Sporting Life `6` +
    Racing Post `1`，其余美国 `9` 匹均为 HRN-only。research module review SHA-256 为
    `1440550a3e4d203b604b9dba74b89b2f49ee7075bc168f35e756e54830f31db1`。
  - 生产层：production readiness report SHA-256
    `8cc36106091708827852401927a791a5575f2d6d490d1a306297e450612ed2c5` 仅执行
    `static_schema_compatibility_check`，`safe_simulation_performed=false`、
    `commit_artifact_compatible=false`、`decision=blocked`、`database_write_count=0`。
- 精确生产 blockers 为 `not_horse_profile_completion_plan`、
  `missing_production_profile_ids`、`missing_production_reviewer_id`、
  `missing_commit_compatible_module_approvals`。正式 commit artifact 尚未生成，formal
  production dry-run 尚未运行；本轮无网络、无数据库写入、无部署或发布，生产仍为
  **NO-GO / blocked**。
- prepare 只能产出 pending；apply 必须同时绑定固定 v2 SHA、可信 manifest SHA、调用方显式
  SHA 与实际文件 SHA。记录、身份、来源、计数发生漂移或出现重复记录时一律 fail closed。
  用户本次“继续推进”不构成生产写入授权。
- 本轮验证为工具与转换器 `48/48`、相关 Django `223/223`、Node `2/2`、旧规格流程
  `30/30`；Django check、migration drift 与 `git diff --check` clean，独立 reviewer
  第三轮 `APPROVED`。文档中的历史 `282/282` 继续保留，但不是本轮新运行结果。

## 2026-07-20 P0 工作簿地区结论、来源调研与批次文案完成动态化

- 来源调研页改由 `buildSourceResearchRows(horses)` 从当前 horses 输入动态计算法国、英国、
  美国与 Fort George 结论；日本、香港“本批无缺口”也按当前 `field_status` 与 career
  数据生成。无对应地区或具名马样本时不制造结论。
- 标题、范围、总表 sheet 名及美国字段字典中的固定 `50`、`各 10`、`美国 10` 改由
  `workbookBatchMetadata(horses)` 生成；默认输出文件名仍绑定冻结 50 匹 artifact，不改变。
- 地区汇总改由 `regionSummaryConclusion` 按当前硬字段、血统、missing/excess/unknown 与
  career completeness 动态生成；无样本明确显示“当前输入无样本”，美国另附逐场官方性说明。
  `japanBatchConclusion` 的空样本不再产生 `0/0` 成功结论。
- `regionSourcePolicy` 与 `regionNextRoute` 只描述通用来源能力和入口；字段矩阵不再固定
  Fort George/JBIS 本批覆盖说明或样本 URL，无样本也不再因 `0=0` 显示可正常获取。
- 两轮 RED 均因缺少新 helper 导出而使 summary test `exit 1`；GREEN 后 summary/path tests
  均 `exit 0`，builder/summary Node `--check` 通过。
- 地区汇总与字段矩阵回归的 RED 因缺少 `regionNextRoute` 导出失败；GREEN 后 summary/path
  tests 与 builder/summary Node `--check` 均通过。视觉检查后仅将 summary `A5:M9` 行高由
  `42` 调至 `72`、matrix data rows 由 `34` 调至 `56`。
- reviewer 最后一条 P2 指出 `pedigreeCompletionStatement([])` 会把 0 匹误判为全部补齐。
  RED 已复现旧错误；GREEN 后 `pedigreeCompletionStatement([])` 与
  `regionPedigreeStatement([])` 均返回“当前输入无样本”，非空输入行为不变。summary/path
  tests、Node `--check` 与 `git diff --check` 通过。
- v2 workbook 已重建为 50 horses / 2050 field evidence / 1439 career records /
  2679 record evidence / 9 previews / formula errors 0，SHA-256 为
  `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`。可见内容与前次
  一致，SHA 变化只来自二进制生成元数据；此后不再重建。生产仍为 **NO-GO**，未执行生产
  写入、部署或发布。

## 2026-07-19 P0 马五地区 50 匹字段与履历数量缺口已清零

- 本轮继续保持只读研究边界：没有写生产 `HorseProfile`、`HorseP0Source` 或
  `HorseRaceRecord`，没有创建 `RaceEvent`，也没有部署或发布。
- 富化后的结构化结果为
  `runtime/horse_profile_completion/pedigree-research-20260719/p0_horse_research_50_enriched_v2.json`。
  最终 SHA-256 为 `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7`；
  冻结 v1
  `runtime/horse_profile_completion/pedigree-research-20260719/p0_horse_research_50_enriched.json`
  的 SHA-256 为 `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd`，
  v2 生成未修改其字节。
  五地区各 `10` 匹的 13 项基础/三代血统硬字段均为 `130/130`，父、母、父父、父母、母父、
  母母总体为 `300/300`，基础字段和血统字段缺口均为零。
- 原 `120` 个祖父母缺口中，`89` 个由父母实体安全反查补齐，`31` 个歧义或未命中字段由逐项
  人工证据补齐。法国和英国的产地、育马者，以及中国香港的精确出生日期、育马者共 `60` 个
  基础字段也已按“来源马 ID + 父 + 母 + 出生年”身份锁补证；所有应用只允许填空，冲突即拒绝。
  `basic_profile_gap_snapshot.json` 冻结了首次应用前 `60/60` 个缺口；v5 应用清单同时绑定父输入
  SHA、当前输入快照、应用后快照及追加式历史，重复执行不得覆盖首次快照。
- 五地区现有履历共 `1439` 条，来源总数与已采集实际出赛的“缺少实际出赛”和“多采/待去重”
  均为 `0`，不再用无方向的绝对差值冒充缺口。Fort George
  原缺的 `7` 场已从 Sporting Life/Racing Post 结果页逐场补入，现为 `13/13`；这些记录不是
  Equibase 官方逐场数据，因此美国 `10/10` 匹仍保持
  `count_aligned_per_record_officiality_pending`，不得宣称逐场官方性完整。
- 按本批结构化完整规则，日本、法国、中国香港、英国为 `40/40` 完整；美国 `10` 匹仅达到
  官方总数对齐，严格整匹马完整门禁为 `40/50`。美国长期仍需授权
  Equibase/Equineline/TrackMaster 数据，或人工 Full Charts/Lifetime PP 核验。
- 美国 HRN 正式来源 client、缓存复放和 50 匹研究解析现均强制使用“马名 + 父名 + 母名 +
  出生年份”四字段锁；任一字段缺失或不一致均阻断，不能再由同名 slug 导入履历。跨来源同场
  合并只允许正式结果覆盖 `unknown`，并保留旧来源直接展示值、采用新来源标准值和归一化值；
  人工赛果证据去重键始终包含来源身份或完整四字段身份。
- source cache 已升级为 `p0-horse-source-cache.v2`。所有地区在复放前都必须用缓存自身马名或
  alias 命中请求马名，禁止用请求值回填缺失身份；来源总出赛数必须同时具备来源名、HTTP(S)
  URL 和带时区核验时间。受控网络 client 只允许访问 JBIS、HKJC、Sporting Life、Geny、HRN
  的登记 HTTPS 主机，关闭自动重定向并逐跳复核目标主机、端口和请求预算。
- 候选来源与资料来源不同时，必须由候选提供完整“马名 + 父名 + 母名 + 出生年份”并与资料
  payload 一致；不同 provider 的 external ID 和同名 alias 不能代替四字段锁。数据库生涯
  evaluator 与整匹马聚合 evaluator 也会独立复核总数来源名、URL 和带时区核验时间，后台或
  其它服务不能绕过 cache 直接写出完整。同 provider 只有在候选和 payload 都具备一致 external
  ID 时才走直接身份；显式来源名与 `external:<provider>:...` key 冲突时立即拒绝。
- 研究 JSON 和 Excel 现均只允许 `source_records_verified` 进入“完整”；`source_blocked`、
  `unknown` 和非法 authority 全部 fail closed。官方明确 `source_start_count=0` 时允许空
  `records` 作为数量对齐快照，非零总数仍必须具备逐场记录。
- 日本 10 匹授权离线重放现逐匹真实调用 `from_japan_candidate` 重建，并从逐场记录复算实际
  出赛、未出赛、异常状态和双向数量差异，不再引用外部未定义计数变量。同 provider 判断会
  规范化 provider 大小写，但 external ID 必须精确一致。
- 数据库总数 URL 改用 Django `URLValidator`，带空格主机、非法端口等不可用值不能进入完整。
  新建议标为 `IGNORED` 只追加审核历史，完整度仍取最近一条非 ignored 的有效状态，不会撤销
  此前已应用证据；后续 conflict/pending 仍会正常阻断。
- 逐场第 4 名及以后统一归一为模型合法状态 `unplaced`，不再写入不存在的 `finished`；真实审核
  apply 回归已确认落库值合法。只有年份的履历继续保留 `race_date_precision=year`，但 adapter
  和数据库 evaluator 都保持 `partial`。基础资料、血统、逐场赛果、官方总数及所有佐证 URL
  均使用严格 HTTP(S) URL 校验，空格主机和非法端口不能进入冻结证据。
- 自动补充来源现不能只凭同名合并：同 provider 必须 external ID 精确一致，否则主来源与
  补充来源各自都要具备并一致命中马名、父名、母名、出生年份。审核 apply、source client 和
  数据库 evaluator 均使用同一严格 URL 规则；总数、来源名、URL、带时区核验时间按原子证据组
  更新，缺一项即清空整组，不能与数据库旧值拼接。cache 的硬字段会验证类型、出生年范围和
  ISO 日期；研究摘要优先使用官方总数计算缺口，不再被相等的备用来源总数掩盖。
- 父母实体反查也不再把“搜索中只有一个同名结果”当成强身份。自动采用必须匹配预期
  provider-bound external ID，或同时具备已知父名和完整来源身份；provider namespace 可
  规范化，但 external ID 在全链路只去首尾空格并按不透明原值精确比较。同 provider 的候选、
  出生年证据、逐行 manifest 和 v2 `source_identity` 必须保持同一 ID。
- 旧 JSON 中 `62` 条 name-only 父系证据和 `54` 条 name + known sire 母系证据已升级为
  `116` 行审核 manifest，归并为 `55` 个唯一父母来源身份。所有 `116` 个 `source_identity`
  现均具备 `horse_name + sire_name + dam_name + birth_year`，两种旧 legacy method 计数均为
  `0`。manifest 路径为
  `runtime/horse_profile_completion/pedigree-research-20260719/reviewed_parent_identity_evidence.json`，
  SHA-256 为 `b211d9040814b0b56ec30e8ef8930fdc10f4140a3a660cf491fcae12d0b6ab2b`。
  父母出生年不是项目负责人逐字段提供或审核：它来自独立 approved artifact
  `reviewed_parent_birth_year_evidence.json`，`reviewed_by=codex_manual_source_review`，
  SHA-256 为 `ed9f6419dccd41485b96884410ea9ab5976d8ab5ba2acfb97e03837a7a3deb54`；
  parent identity manifest 只绑定该独立证据及既有审核上下文。
- Kentucky Wood 的父系同名纠错已显式留痕：旧 Netkeiba `000a02bd3f` 是 1925 年同名
  Balko，必须保留在 v1 且不得进入 v2；正确父马是 Racing Post `595446` 的 2001 年 Balko，
  父母为 Pistolet Bleu / Ella Royale。自动 Netkeiba 父母候选 URL 只接受精确
  `https://en.netkeiba.com/db/horse/<id>/`，凭据、端口、query 或 fragment 任一存在均拒绝。
- `0052_horse_career_source_authority` 在新增逐场权威状态后，会把旧
  `career_history_status=complete` 且权威性未核验的记录降为 `needs_review`；若整匹马状态原为
  `complete_profile_full`，同时降为 `complete_pedigree_2gen`，避免聚合状态继续对外显示未经
  证明的完整生涯。
- 审核工作簿已用富化结果重建：
  `outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/P0马五地区50匹完整解析与字段可用性审核-v2.xlsx`，
  最终 SHA-256 为 `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`；
  冻结 v1 工作簿 SHA-256 为
  `4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`，
  人工证据应用 ID 为 `3d5ab289cc5590e3cc405a4f28e532b98c86466f1b8da656e01183ca1fb2508c`。
  工作簿包含 `2050` 条逐字段证据、`1439` 条逐场履历、`2679` 条逐场三层证据；非冲突证据
  不再误显示为“冲突候选值”。公式错误扫描为零，`9` 张预览已覆盖全部工作表并完成视觉核验。
- 工作簿 builder 默认读取 v2 JSON，默认输出 `-v2.xlsx` 和 `previews-v2`；环境变量覆盖配置文件。
  指向冻结 v1 工作簿或 v1 previews 目录的输出会被拒绝，避免覆盖审计基线。
- reviewer 最后一条意见指出工作簿结论数字被硬编码；现由 `careerConclusionRows(horses)` 从当前
  horses 输入动态生成法国、中国香港、英国和美国结论，具名马不存在时不制造对应结论。合成
  输入 Node 回归已覆盖该边界；重建后仍为 `50` 匹、`2050` 条字段证据、`1439` 条履历、
  `2679` 条履历字段证据、`9` 张预览、公式错误 `0`，首页预览人工检查无溢出或遮挡。
- 来源解析、适配器、候选提取、生涯模型、50 匹产物最终化、基础资料与血统补证离线组合回归
  已从上一轮 `277/277` 增至最终 `282/282` 通过；Node 工作簿 summary 与 path 测试通过，
  测试分母已包含既有
  `stable.tests.P0HorseProfileDataCompletionTests` 整类。Django check、迁移漂移检查、
  旧规格流程 change strict 通过、all strict `30/30`、Python `compileall`、工作簿公式错误扫描、
  `9` 张预览和 `git diff --check` 均通过。
  生产仍为 `NO-GO`：没有生产写入、部署、发布或网络 career crawl。

## 2026-07-18 P0 马五地区 50 匹字段与履历研究包已完成

- 已对审核确认的法国、中国香港、日本、英国、美国各 `10` 匹、共 `50` 匹执行一次性只读
  研究解析；全部 `50/50` 生成结果且无解析异常。当时结构化结果路径为
  `runtime/horse_profile_completion/research-50-parsed-20260718/p0_horse_research_50.json`，
  审计记录曾登记 SHA-256
  `1c15b3c3338cdb9e8fe853d66a6a88c277c2f7afccd1b106349bab8ed640e5ba`。该路径后来被后续
  研究步骤覆盖，旧字节未保留、现已不可复验；当前路径字节 SHA-256 为
  `7a02bbe0f66177fd813626aa03ea98a190c2b11e227a96aab056ad17c3bb2f6c`，不得冒充 7 月 18 日
  原产物。当前可复验的最终冻结 JSON 以本文件上一节的富化路径和 SHA 为准。
  本轮没有创建或修改生产 `HorseProfile`、`HorseP0Source`、`HorseRaceRecord` 或
  `RaceEvent`，也没有发布马匹页。
- 人工审核工作簿为
  `outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/P0马五地区50匹完整解析与字段可用性审核.xlsx`，
  当时审计记录曾登记 SHA-256
  `584e7493d9c53726616fc18ad03144262dfa418b6940c4fba23aa67c7a09044b`；该同名路径后来由
  7 月 19 日最终工作簿原子替换，旧字节未保留、现已不可复验。当前路径 SHA-256 为
  `4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`，其内容和统计以
  本文件上一节为准。
  工作簿包含地区字段矩阵、50 匹全部资料、`1550` 条逐字段证据、`1434` 条逐场履历、
  来源调研和字段字典；公式错误扫描为零，并已逐 sheet 渲染验收。
- 13 个基础/二代血统硬字段按“已获取格数/地区总格数”统计为：日本 `130/130`、美国
  `90/130`、法国 `80/130`、中国香港 `80/130`、英国 `80/130`。日本是唯一全部
  `13/13` 字段均达到 `10/10` 的地区。法国和英国缺产地、育马者及父父/父母/母母；
  中国香港缺完整出生日期、育马者及父父/父母/母母；美国缺毛色及父父/父母/母母。
- 履历研究结果必须按语义分层：日本有 `200` 条记录，其中 `199` 次实际出赛、`1` 次退赛，
  来源总数无缺口；法国来源声明 `250` 次实际出赛且已采集 `250` 条，但有 `12` 场旧记录
  结果状态待补；英国来源声明并采集 `412` 次实际出赛，但有 `18` 场旧记录结果状态待补；
  中国香港已采集 `372` 次实际出赛和 `3` 条未出赛记录，按来源总数仍有 `4` 场缺口；
  美国 HRN 可见履历共 `197` 条，但没有取得 Equibase 权威总出赛数，因此缺口仍为未知。
- 法国 Geny 本次继续返回 HTTP `429`，研究包改用已逐马确认身份的 Sporting Life
  `Full Form`；长期硬字段方案为 IFCE SIRE / France Galop Stud Book。美国先从 Equibase
  官方赛事载荷取得 refno、父母和完整出生日期，再用 NYRA 官方赛事页补产地/育马者；
  HRN 只在父、母和出生年份一致后提供可见履历。该校验已修正 Cornishman、Gigante 和
  Movin' On Up 三个同名马错误 profile，禁止只按马名或 HRN slug 合并。
- 本轮完成的是“字段可用性研究和人工审核包”，不是五地区正式资料批次闭环。严格完整门禁仍为
  `10/50`：法国、英国需要补结果状态和剩余硬字段；中国香港需要补硬字段及 `4` 场履历；
  美国需要 Equibase 官方总出赛数、完整履历和剩余硬字段。后续生产 apply 仍需新的冻结
  artifact、逐马人工审核、写前备份和针对精确版本的明确授权。

## 2026-07-18 P0 马日本首批已达 10/10，并通过无网络复放

- `complete_horse_profiles` 已支持仅在 `--dry-run + --p0-reviewed-candidates +
  --p0-review-manifest + --p0-review-manifest-sha256` 组合中使用 `--allow-network`；
  CLI 冻结 SHA、服务端 `HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256` 和实际 manifest
  字节 SHA 必须三方一致，manifest 还必须与 CSV basename、SHA-256、大小和 50 行分母完全
  一致；全部校验在解析 manifest 和创建任何 source client 前完成。命令参数和
  `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK` 必须同时开启，service 入口也会独立复核设置。
  网络模式必须显式选择至少一个地区，未选择地区仍只走现有离线 cache/cache-miss blocker。
- 五地区分别固定单马请求预算为日本 `3`、香港 `1`、英国 `1`、法国 `2`、美国 `3`，每区
  最多 `10` 匹且整批复用一个受控 source client。网络结果继续经过统一 source validator、
  adapter 和原子 cache；单马失败不会中断后续候选。成功补出 provider ID 或完整
  “马名+父名+母名+出生年份”后，候选不再被旧的 `needs_identity_enrichment` 永久阻断。
- batch manifest 现在记录 `network_allowed`、`network_regions`、`review_manifest_input`，
  summary 总体和逐地区记录
  `network_request_count/cache_hit_count/cache_miss_count`；仍固定
  `read_only=true/database_writes=0`，50 行审核 CSV、输入 SHA、空输出目录、五地区各 10 匹、
  身份与完整度门禁均未放宽。整批 artifact 在同父目录 staging 中生成，逐文件校验并
  `fsync` 后再原子发布；失败会清理 staging，不在最终目录留下半成品。
- 测试先行的 8 个批次入口合同最初全部 RED；随后新增的真实来源 blocker 分类合同也先取得
  RED，并修正为 `P0HorseSourceBlocked -> source_cache_or_adapter_error`，保留原始异常和请求数，
  其他编程异常仍归 `unexpected_adapter_error`。复用的地区 client 外包一层逐候选代理，
  不要求底层 `last_request_count` 可写；cache 在 fetch 前失败时记录 `0`，实际 fetch
  成功或失败后读取底层只读计数，底层无该属性时保守记 `1`。底层 client 的请求预算逐马
  重置，但最后真实请求时间跨同地区候选保留，后续候选继续遵守请求间隔。
  JBIS `.data-6-5` 中只有 finish 精确为 `**`、列数至少 13 且 `cells[12]` 规范文本精确为
  `除外` 或 `取消` 时，才分别映射为 `withdrawn` 或 `scratched`；赛事名不能代替状态列，
  列不足或未知 `**` 继续阻断。后续 reviewer 发现 transport 异常未计数的问题也已按测试先行
  修复：真实 transport 调用前即记录一次请求尝试和 monotonic 时间，连接/TLS/读取异常仍计入
  request budget，下一候选继续遵守剩余间隔。Docker `--network none` 下 source-client
  `48/48`（`Ran 48 tests in 0.450s`）与四模块 `102/102`
  （`Ran 102 tests in 1.040s`）均为 `OK`。Django check 无问题，迁移检查为
  `No changes detected`，两个 service 与管理命令 `py_compile`、`git diff --check` 均通过。
- 日本 10 匹首个受控网络批次已运行，目录为
  `runtime/horse_profile_completion/p0-reviewed-japan-network-20260718-083707/`，batch
  manifest SHA-256 为 `bf8dbda389e5ffc3b9efa1f361a8cbb7b8ad5392b2e1c11c86b25d8600db49e2`。
  该次历史结果为 `9/10 complete / 30 requests / 9 个新生成 cache / 0 cache hits / 0 database writes`；
  コントラポスト的真实履历为 `22 actual starts + 1 除外`，旧解析将 `**` 误算实际出赛而阻断。
  修复后使用新目录
  `runtime/horse_profile_completion/p0-reviewed-japan-network-rerun-20260718-091156/`
  完成受控重跑，batch manifest SHA-256 为
  `9682ceebddb53a796ff058bb79a3455e89a4ad03b01ddeed7beed947dd1106b5`。重跑结果为
  日本 `10/10 complete / 9 cache hits / 1 cache miss / 3 network requests / 0 database writes`；
  其余四地区均未触网。コントラポスト保留 `23` 条履历，其中 `22` 次实际出赛和 `1` 条
  `除外`，生涯计数为 `22/22`、缺口为 `0`。
- 随后在 Docker `--network none` 中使用同一 10 份 canonical cache 复放，目录为
  `runtime/horse_profile_completion/p0-reviewed-japan-offline-replay-20260718-0913/`，
  batch manifest SHA-256 为
  `472785d50e5e6e7343d1ec0285cc68921a12ca7303556fa58dd21ffcc1af22c2`。日本结果为
  `10/10 complete / 10 cache hits / 0 cache misses / 0 network requests / 0 database writes`；
  cache 目录正好 `10` 个 JSON，且无临时文件残留。
- 前述两次日本重跑形成于审核 manifest 强绑定和整批原子发布修复之前，因此保留为来源抓取与
  解析证据，不冒充新门禁证据。加固后又在 Docker `--network none` 中以
  `network_allowed=true + network_regions=["japan"]` 完成全缓存复放，目录为
  `runtime/horse_profile_completion/p0-reviewed-japan-hardened-offline-replay-20260718-094427/`，
  batch manifest SHA-256 为
  `4834e9f9f47b67a57bb1c11ee7cdc0b8338673b7e96d575a56ef1e5164332ecb`。该清单绑定审核
  manifest SHA-256 `aa452fb27dcf77e7821782a6302504e7abe4cf600bd6da25e9c49e7f776213bf`
  和审核 CSV SHA-256 `f36d2f3f71fccc90a7f498f4d1c021e1a6d4275450122de599bc4b8767e240fa`；
  日本 `10/10 complete / 10 cache hits / 0 network requests / 0 database writes`，最终目录
  `8` 个文件、无 staging 残留。该次形成于外部冻结 SHA 信任锚修复之前，只是中间验证。
- 最终授权复放目录为
  `runtime/horse_profile_completion/p0-reviewed-japan-authorized-offline-replay-20260718-100440/`，
  batch manifest SHA-256 为
  `96ebef63ae74fa787ff786b262cebebc252f6e3c536c2aa89fc920c8d8e91210`。Docker
  `--network none` 中同时设置 CLI 和服务端冻结 SHA
  `aa452fb27dcf77e7821782a6302504e7abe4cf600bd6da25e9c49e7f776213bf`，实际 manifest
  SHA 与之相同，batch manifest 记录 `authorized_by_setting=true`；审核 CSV 仍为
  `f36d2f3f71fccc90a7f498f4d1c021e1a6d4275450122de599bc4b8767e240fa`。日本
  `10/10 complete / 10 cache hits / 0 network requests / 0 database writes`，最终目录
  `8` 个文件、无 staging 残留。
- HK/UK/FR/US 的真实字段缺口仍未闭环，法国 429 仍是 blocker；任务 4.2 保持未完成。
  当前总体只能记为首批 `10/50` 达到来源完整状态；没有执行生产资料写入、发布、Git
  commit/push/merge 或部署。同一独立 reviewer 对本审计段落追加前的完整差异结论为
  `APPROVED`、无 actionable finding；approved HEAD 为
  `c2c30aeed73619767c1ca6dfb440b43c8f824d11`，审前/审后 fingerprint 均为
  `4dfaaaff01f38c5062a29a2225ac0f7fe8371d3ceccfd12e5182731cbaf99221`，reviewer stdout
  SHA-256 为 `0780293905b1c1cdd953a02bd2386c25902021709c9144b2c466bf93ad062631`，helper raw
  stdout SHA-256 为 `8a000524fd6228570e0ac2cb036d1d475e50701a3adb5806a5130cd91fbb632c`。
  上述旧 fingerprint 不覆盖这段随后追加的审计文字；该文字的准确性以追加后的限定只读复核
  结果为准，避免把复核自身的 fingerprint 再写回并形成无限自指。

## 2026-07-18 P0 马真实页面兼容已通过单马受控探针

- 五地区 source client 已补入保存快照所示的真实页面 shape：Sporting Life 同时兼容旧
  `pageProps.horse/full_form` 与 `pageProps.profile/previous_results/stats.total`；HKJC
  支持 nested `table.horseProfile`、`title_text` 和 `bigborder` Form Records；JBIS 使用
  `/horse/result/?keyword=<name>&match=exact` 并支持真实 profile/record grid；HRN 先按严格
  slug 直达并从同页 `horse-stats`、`horse-table` 解析。并发 cache 发布改为
  `os.link` no-clobber，竞争者统一重读并校验 canonical cache。
- 这仍是离线页面兼容，不是五地区真实资料完成。此前 `66/66` 只证明合成 fixture scaffold；
  原“真实客户端最终 GREEN”、实现者 reviewer `APPROVED` 和 fingerprint 完成声明已经撤销。
- 当前候选已由主会话在真正的 Docker `--network none` 中完成最终复验：source-client
  `20/20`（`Ran 20 tests in 0.057s`）与四模块 `74/74`
  （`Ran 74 tests in 0.693s`）均为 `OK`；Django check 无问题、迁移无漂移，
  `PYTHONPYCACHEPREFIX=/tmp/pycache` 下两个 service `py_compile` 与 `git diff --check`
  均退出 `0`。
- 首次真实探针曾为 `0/5`，其中日本因旧 JBIS 入口失败。修复后主会话再次执行五地区各 1 匹、
  不落缓存且不写数据库的受控探针，当前为 `1/5`：日本オーロラエックス通过真实 JBIS
  search/profile/record 三页解析，来源总出赛数与履历均为 `15/15`；香港 EAGLE WAY
  精确阻断于缺 `birth_date/trainer_name/breeder_name`；英国 Jonbon 精确阻断于缺
  `country/breeder_name`；法国 LOSANGE BLEU 仍为 HTTP `429`；美国 Bullard 精确阻断于
  `missing_source_start_count`。这只证明单马来源兼容，不代表首批资料已缓存或补全。
- HKJC、Sporting Life、HRN 仍需补充来源或人工字段；法国需在 429 解除后重新低频探针。
  任务 4.2 保持未完成；日本首批后续已重跑并达到 `10/10`，但严禁扩大解释为
  “50 匹已补全”。
- 同一独立原生 reviewer session `019f71f9-bb0c-7c92-8e12-83837a2a6c11` 已对前轮四项
  finding、严格身份 validator 和 legacy cache 边界完成代码定向复审，结论为
  `APPROVED`、无剩余 actionable finding。审前审后 fingerprint 均为
  `85f9adbfc574b6ffb5a261ae27d48aeefff97a62fd314c6397d30f0b469b4351`，review stdout
  SHA-256 为 `78582a4a05140a44d9c49a1c0c353a8124fa1477e095c3410d32d6ecf0ea08fd`。
  该指纹产生于本段状态文档更新之前，只清零代码审查问题，不代表任务 4.2、真实资料批次
  或随后新增的文档已获批准。

## 2026-07-18 P0 马首批审核与完整资料离线 dry-run scaffold 已完成本地实现

- 项目负责人确认生产只读候选中的五地区各 `10` 匹、共 `50` 匹全部纳入首批资料补全。机器可读审核 artifact 位于 `runtime/p0_horse_candidates/production-reviewed-20260718-all-50-approved/`，审核 manifest SHA-256 为 `aa452fb27dcf77e7821782a6302504e7abe4cf600bd6da25e9c49e7f776213bf`。该决定只确认批次范围，不豁免身份、完整资料或完整生涯门禁。
- 新增统一 `p0-horse-completion.v1` payload、五地区 adapter 协议、完整履历状态映射、年精度日期、未关联普通比赛、跨来源保守去重、模块 apply/ignore/conflict 审计，以及绑定审核输入和逐文件 SHA-256 的离线批次 artifact。`complete_horse_profiles --dry-run --p0-reviewed-candidates ...` 固定 `allow_network=false`，单匹缓存缺失或解析失败转 blocker，不中断整批。
- 持久化基线 dry-run 位于 `runtime/horse_profile_completion/p0-reviewed-baseline-20260718-0500/`，batch manifest SHA-256 为 `2028e03a8e5edaa386e101cd159406559192844c02a9979d363e1dbece571110`。输入审核 CSV SHA-256 为 `f36d2f3f71fccc90a7f498f4d1c021e1a6d4275450122de599bc4b8767e240fa`；处理 `50` 匹、五地区各 `10`，网络请求 `0`、数据库写入 `0`。当时空缓存下 `50/50` 为 `network_disabled_cache_missing`，日本和美国共 `20/50` 另外保留 `identity_enrichment_required + missing_identity`，因此该离线基线为 `0/50`；此数已被后续日本网络批次和离线复放更新为当前 `10/50`，不能再作为当前完成数。
- 该离线基线形成时，本地验证由 `17` 项中的 `14` 项 RED 和批次新增 `5` 项 RED 推进到
  focused `22/22`、P0 相关组合 `51/51` 通过；当时尚未执行真实资料网络抓取。后续日本受控
  抓取与加固验证见本页顶部；截至当前仍未执行生产 commit、自动发布、Git
  commit/push/merge 或部署。
- 该历史段落记录的旧 reviewer approval 只覆盖当时受审代码和既有 findings，不覆盖后续网络
  证据、加固实现或当前全部未提交差异。下一步是为香港、英国、美国确定补充来源/人工字段方案，
  并为法国 429 制定低频重试窗口；在这些方案形成新的受控缓存批次前，不得把
  fixture/cache 协议或单份成功探针解释为已经补齐 50 匹资料。

## 2026-07-18 P0 重点赛事参赛马只读提取能力已完成本地实现

- 已实现从五地区重点赛事 `RaceEventRunner` / `RaceEventResult` 只读提取 P0 马候选、观察清单、每地区审核 CSV 和 SHA-256 manifest；只有马名的记录保持事件级独立并标记 `needs_identity_enrichment`。
- 来源内 external horse ID 或完整“马名 + 父名 + 母名 + 出生年份”才可跨赛事归并；共享强身份键按连通关系聚合，身份冲突继续 fail closed。
- 命令入口为 `p0_horse_profiles --extract-candidates`。提取阶段不创建术语、马匹、P0 来源或身份冲突，不启动马匹资料网络抓取。
- 历史生产只读样本为五地区各 10 匹；该记录只说明候选提取完成，不构成生产资料写入或公开授权。

## 2026-07-20 五地区准实时 Beta Gate 修复已发布，法国重验安全降级

- 用户授权的冻结 fingerprint
  `231f8a68707f4b946daf1d355f5848cd107e13bbfa6c1ed856a0de2a31b22b4d`
  在 staging 前重算一致；approved content hash 为
  `90380f6bd31e9eb980242772fa77f565d297f7ed01a72a9c4f412c57b239773f`，
  approved parent 为 `51fd07310d5287c535d01ce3c8af6ccd70a274cd`。受审内容提交为
  `58f00961f2cd9750d1285f7d6229494903e975a5`，已快进远端 `main`；tree 为
  `de529e244a3ad21a1c6d72fc50b254d37e080e20`，source archive SHA-256 为
  `1209353f4949c1fed7cbf58756e75e54f08c6bc0a8bdec996a7d1a2c78c43b08`。
- 生产候选 AMD64 image 为
  `sha256:f9681a60f5072c39ae7cc66bad9881e719a7d24698050b4ae57858f94b310eef`；
  镜像内 Django check、migration drift、两个新 command help 和 remediation
  `32/32` 通过。web、普通 worker、race-live worker、Beat 已全部切换到该 image，
  OCI revision/tree/source archive 与上项一致；`stable.0048` 已应用。
- 写前 custom-format 备份为
  `/opt/umanewsbot/backups/db/pre-race-live-gate-58f00961-20260719T161644Z.dump`，
  `205,411,102` bytes、SHA-256
  `1aa9fc306a5a5039f835f873224f5c768be95265d8bd85674bba311f320404f1`，
  `root:root 0600` 且 `pg_restore -l` 通过；`.env` 备份 SHA-256 为
  `e24208729cfba44fd71d9b2ed343dd93d3437d3f6fb80f3f459759523158b566`。
  旧 image
  `sha256:4c40ae1946dd9ac85a368917fe3de64269e6cf848737e24253f0d0996403eda6`
  保留为
  `umanewsbot:rollback-pre-race-live-gate-58f00961-20260719T161644Z`。
- rollback filtered env SHA-256 为
  `cda13ce08c6a6d03ffcb4812cf1e1bc1d56fa7eae2244d7cf72330869811062e`；
  root-only bundle manifest 为
  `/opt/umanewsbot/runtime/race_live_rollback/race-live-gate-58f00961-20260719T161644Z/bundles/race-live-gate-58f00961-20260719T161644Z/manifest.json`，
  SHA-256
  `e6e3e1ef848009903ab2a62ea77eba2a4e3d9289a8d93759eb9c9de7dd4609f5`。
  它绑定 candidate image、commit、event `924`、current/provisional revision `2`
  和 tracking lock version `39`。
- maintenance dry-run/apply 成功，event `924` 临时
  `visible=false / policy_off`；绑定同一 image/env/manifest 的 one-shot 按
  `validate -> restore-policies-coarse -> validate -> restore-policy-event` 全部退出
  0，最终 validator 再次通过。恢复后 event `924`
  `visible=true / public_read_allowed`，current/provisional revision 均为 `2`、
  legacy result `7`、tracking disabled、next poll null、token 为空、lock version
  `39`。演练中两次末尾文本 `grep` 因远端引号形式返回非零，但都发生在成功事务和只读
  结构化输出之后；后续 JSON 逐字段断言通过，没有留下中间 policy 状态。
- 上线后 scheduler/monitor 均为 false、enabled regions 为空、active claim 为 0、
  `race_live` queue 为 0；本机、公网和 `www` HTTP healthz、首页、赛事日历及 event
  `924` 详情均为 200，近期 web/race-live worker/Beat 无 traceback、critical、
  exception 或 integrity error。
- 法国 event `733–735` 使用新镜像、Free 账户和 registry v2 真实重验。首次调用使用
  旧 runbook registry SHA，被命令在网络前拒绝，零请求、零业务写入；改用镜像内真实
  digest `7aca49ff1df7573ebfe6a9e403eefca5c9e64d8ee18d8d3be383d67803db550a`
  后，run
  `production-racecard-france-733-735-gate-fix-20260719T163001Z` 完成 today/tomorrow
  各一次请求。结果为 `request_count=2 / matched_event_count=1/3 /
  blocker=racecard_not_found`，不再出现 `racecard_schema_invalid`；report 和 requests
  SHA-256 分别为
  `f81cf27666f8e026db4dd30d107f500205366d96ef3c45bf373879e68d22d517`、
  `8c0a80775253b32ff6e3caa1d1e31244786c531116d5dad478d303977e197246`。
  因整批不完整，没有 manifest、initializer、tracking/control/allowlist；法国和其他新
  地区继续全关。当前公开范围仍只有 event `924` 的暂定赛果，不得表述为五地区已全面
  自动运行。

## 2026-07-19 event 924 kill switch 实际演练完成，15 分钟 SLA 转入下一场验收

- 用户确认 event `924` 不再补做无法追溯的 promotion 后 15 分钟 probe，改由下一场
  获准公开灰度赛事重新验收；这不把 promotion 前截图改写为合格证据，也不豁免下一场
  的 15 分钟要求。
- 用户另行授权 event `924` 完整 kill-switch 演练。原 bundle 的 disable manifest
  `d441e0a1…14949` 重新 dry-run 后执行 apply 和独立 verify，三步均
  `ok=true / event_ids=[924] / network_request_count=0`；OperationLog `105224`
  记录于 `2026-07-19T05:14:25.394898Z`。event policy 从
  `provisional_public v2` 收紧到 `shadow v3`。
- disable 后公网 HTTP 详情和日历仍为 200；详情中的“冠军 · 暂定”“暂定赛果”“尚待
  官方来源复核”全部消失，日历保留赛事本身但隐藏前五赛果摘要。revision `2`、
  publication `1`、legacy result `7`、observation `2`、official marker evidence `1`
  和 resolved incident `1` 均未删除。
- 同一 bundle 的 restore manifest `cf96afb6…cf6c` 重新 dry-run 后执行 apply 和独立
  verify，三步同样 `ok=true / event_ids=[924] / network_request_count=0`；
  OperationLog `105225` 记录于 `2026-07-19T05:17:11.592720Z`。event policy 恢复为
  `provisional_public v4`，shared global/UK/TRA policy 保持 v2，allowlist 仍只有
  event `924`、version 2。
- restore 后详情重新显示中文暂定标识和 1–7 赛果，日历重新显示前五摘要；不显示“赛果
  已确认”，event 仍为 finished 且 `result_confirmed_at=null`。四个 app service 的
  scheduler 均为 false，tracking disabled、next poll null、claim generation `19`，
  `race_live` 与普通 `celery` 队列均为 0，live worker active/reserved 均为空，
  `/healthz/` 为 200。演练未扩展其他赛事，event `924` 当前继续公开暂定赛果。

## 2026-07-19 event 924 暂定赛果单赛事公开灰度首次发布记录

- 最新成功代码 review 的完整冻结基线已在授权后逐字节复核，受审提交
  `91cf50ad677a1b8c9b253528c9db98481fd1031a` 已快进 `main` 并部署生产；web、worker、
  race-live worker 和 Beat 均运行 image
  `sha256:700ea78698fb67de602fb7e5447b997610e24e64de29df4591e4bb9e476087ef`，
  OCI revision 与提交一致。`stable.0046` 已应用，`/healthz/` 正常。
- 写前数据库备份为
  `/opt/umanewsbot/backups/db/pre-event924-provisional-public-20260719T040646Z.dump`，
  `202,483,514` bytes、SHA-256
  `a76c9d4788b36af08f64f4a9eddc90bc0a4ef4ecd239508bb5e40abffbe9e5be`，
  `root:root 0600` 且 `pg_restore -l` 通过。旧镜像已保留为
  `umanewsbot:rollback-pre-event924-ebab4aa8-20260719T041339Z`。
- QQ SMTP 已按 `smtp.qq.com:465 / SSL` 配置，报警目标为 `754652181@qq.com`；一次性新
  容器真实投递返回 `sent=1`，随后四个常驻 app service 均确认 SMTP 密钥已加载。授权码
  未写入 Git、日志或证据文档。
- 生产 bundle
  `event924-public-91cf50ad-20260719T042103Z` 以 `0700/0600` 生成且无 symlink；
  promotion、disable、restore SHA-256 分别为
  `2fedb9d381b275fb3dcc6e30c848a59c024da4dca0ec2227efb13925bceec3ba`、
  `d441e0a1f134847abd4ebf3cf39c55c41be46d587723528e98958faa30014949`、
  `cf96afb6363ed7621c7a153234b075e8708b544907956ca1745503739065cf6c`。
- promotion 于 `2026-07-19T04:37:17.201536Z` 提交；dry-run、apply、独立 verify 均
  `ok=true`、唯一 event `[924]`、零网络请求。当前四层 policy 为
  `provisional_public v2`，allowlist 仅 event `924`、version 2；event 为 finished，
  revision `2` 仍为 provisional，`result_confirmed_at=null`，publication `1`、
  legacy result `7`。tracking 已停用、next poll 为空，claim generation 仍为 `19`，
  provider attempt/success/hash/failure/stale 字段保持 shadow pre-state。
- release operator 在 promotion 前通过正常浏览器核对 BHA Newbury `3:02pm`
  Hackwood Stakes 官方 1–7 名次；私有截图 SHA-256 为
  `77b77a03a7c8c640db69db7f4d84965aad91b01bba243613eaa49773bd55a480`。
  截图 `observed_at=2026-07-19T04:19:39Z`，早于 promotion commit
  `04:37:17.201536Z`，因此不能作为“promotion 后 15 分钟内新浏览器探测”的验收证据。
  receipt SHA-256
  `955ac30b6e345b5ec9226e0439b14df65bba515e39fd4cf29544402387823673`
  的 dry-run/apply/replay verify 均为 `comparison=match`、零通知副作用。incident `1`
  于 `04:40:32.495902Z` resolved，早于 `04:52:17.201536Z` 责任时限；新增 official
  observation/marker evidence 各 `1`，页面仍保持 provisional，不误标正式赛果。但
  `04:40:32Z` 是旧截图 receipt 的应用时间，不会把 promotion 前观察变成 promotion 后
  探测；15 分钟 SLA 未被当前证据证明，BHA 首次探测 closure 尚未完成。
- 首次发布收口点的公网 HTTP 详情与日历均为 200。详情显示“冠军 · 暂定”“暂定赛果”“尚待官方来源复核”
  和 1–7 完整顺序；trainer/time/margin 缺失值为 `-`。日历共同 read gate 只对
  event `924` 展示相同赛果摘要。当时 disable manifest 只完成 dry-run，未执行
  disable apply、公开隐藏验证和 restore；后续实际演练结果见上方最新状态。
- 首次发布收口时 `RACE_LIVE_SCHEDULER_ENABLED=false`，tracking row universe 与 enabled
  allowlist universe 均为 `[924]`，race-live queue 为空；HostBudget failures 为 0、
  circuit 关闭、lock version `22`。historical runner preflight 为 `migration_safe`，
  常驻历史 enabled/network 均为 false。Beat 已恢复，普通新闻任务可继续运行。当时
  kill switch 与 15 分钟 SLA 两项尚未收口；前者现已完成，后者按用户决定转入下一场
  赛事重新验收。

## 2026-07-19 event 924 代码审核 finding 已修复，待同一 reviewer 限定复审

- 独立 worktree 为
  `/Users/mentianlu/Code/umanews/.worktrees/event-924-provisional-public-gray`，分支
  `codex/event-924-provisional-public-gray`；`HEAD`、merge-base 和当前
  `origin/main` 均为 `353464c76c63d1e43043ccbefe0ebc88274b0888`。没有复用历史抓取
  worktree 或运行产物。
- 已实现只针对“已持久化、未发布 shadow revision”的离线 operator transition：
  prepare 一次生成 promotion/disable/restore 精确 CAS manifest；命令默认 dry-run，
  apply 需要显式确认，verify 只读。promotion 不领取 provider claim、不调用网络或
  checkpoint，不改 provider attempt/success/hash/failure 时间，只在同一事务内晋级
  policy/allowlist、调用共享 admission core、物化 publication/legacy result/incident，
  然后关闭 event tracking。
- `0046` 只为 allowlist/incident 增加 BHA route contract、terms evidence digest 和人工
  复核时限字段；旧 shadow 行允许为空，但 public admission/read 对缺失或非法 digest
  fail closed。provisional materialization 会把 scheduled/running 推进为 finished，
  保持 `result_confirmed_at=null`，只允许从 current racecard 补 `barrier/jockey_name`
  并保存字段级 provenance。
- BHA 仍是 `manual_browser_only` 官方复核路线，`automation_allowed=false`。离线 receipt
  硬限 event `924`，只接受 source URL、时间、私有证据 SHA、marker 和客观名次；不保存
  页面 raw、评论、评级或赔率，也不接受操作者自报 comparison。一致时 resolve incident，
  冲突时同事务执行预生成 event disable。暂不可用时保持 provisional/open；主事务先原子
  提交 probe、receipt OperationLog 和 `QUEUED NotificationLog` durable intent，提交成功
  后才进入独立 delivery transaction 真实发邮件。delivery 终态为 `SENT/FAILED`，只有
  SENT 设置 `alert_sent_at`，失败可重放重试；去重键稳定绑定 incident，不绑定 receipt，
  因此新 receipt 会推进 probe/operation evidence，但不会重复发送同一 incident 告警。
- manual 命令默认 dry-run 与 apply 共用同一个 locked planner，验证 current revision、
  participant、incident、policy/allowlist CAS、时间和 conflict disable pre-state；dry-run
  零写入、零邮件副作用，并显式输出 comparison/alert status。
- 首次独立代码 review session `019f76c2-78bd-7ed3-9107-a7b1c2a7aa4e` 结论为
  `REVISE`；首次 2 项 P1、1 项 P2 以及随后两项直接 P1 均按真实 RED -> GREEN 修复。
  后两项明确覆盖跨 receipt incident 去重与“主事务成功 commit 前零 SMTP”，当前等待同一
  reviewer 限定复审，不把此前 review 视为成功门禁。
- 本地最终验证：合并聚焦 SQLite `226` 项，`224/224` 通过、PostgreSQL-only `2` 项跳过；
  transition/manual 专项 `41` 项，`39/39` 通过、PostgreSQL-only `2` 项跳过；临时真实
  PostgreSQL 16 新增 durable intent/并发专项 `2/2`，既有 transition、双 operator、
  policy/allowlist CAS、runner 竞争和初始化锁回归 `22/22`；`0046` 正向、
  反向、再正向通过；Django check、migration drift 和三份 Compose config 通过。
  三份 Compose 都保持 `RACE_LIVE_SCHEDULER_ENABLED=false`，publication artifact rw
  只挂给 `race_live_worker`。
- 当前仍未 commit、未成功代码 review、未冻结、未发布、未连接或写入生产，也没有访问
  BHA 或重新请求 TRA。生产继续运行 2026-07-18 的 shadow 基线：event `924` 未公开、
  scheduler false、范围不扩展。下一门禁仍是同一 reviewer 的限定复审；只有成功后，才能
  冻结精确 fingerprint 并向用户请求该冻结版本的新发布授权。

## 2026-07-18 event 924 首个 TRA shadow 赛果已取得，有界窗口停止

- 用户显式授权仅对 event `924` 按数据库 `next_poll_at` 手动 claim/dispatch，直到首个
  shadow result 或明确截止；scheduler 必须保持 false，不扩展赛事、不公开。执行前
  tracking/allowlist 精确全集均为 `[924]`，四层 policy 全为 shadow，赛果事实为 0。
- 本轮写前恢复点为
  `/opt/umanewsbot/backups/db/pre-race-live-window-924-ebab4aa8-20260718T111221Z.dump`，
  `198,273,152` bytes、`root:root 0600`、SHA-256
  `efa68a76f7236f7454fe9119df601ff4f1e4fae9d2b8040fc09aa9cf28efd13b`，
  `pg_restore -l` 通过。
- 临时控制循环只读取 event `924` 的持久 `next_poll_at`，逐次调用单赛事
  `claim_race_event_live_tracking`，再只向 `race_live` 投递对应 claim。首次到期时控制
  脚本误读返回对象字段 `applied`，在 task 投递前退出；generation 2 claim 已写入但未
  重复领取，随后在 TTL 内读取同一 active claim 并于 `11:33:50Z` 精确投递 task
  `a5e03b1a-6c7b-409b-ba16-096e575b63f4`，成功返回 `pre_off_wait`。脚本改用真实字段
  `claimed` 后恢复，无悬挂 claim、无范围扩展。
- 本窗口共完成 generation 2–19 的 `18` 次单赛事 task：generation 2–14 共 `13` 次
  `pre_off_wait`，均未访问结果 API；generation 15–18 在 `14:02:09Z`、`14:05:17Z`、
  `14:08:27Z`、`14:11:34Z` 各执行一次单请求并返回
  `the_racing_api_result_not_found`。每次都由数据库 checkpoint 推进下一合法时间。
- generation 19 于 `14:14:40.843702Z` claim，唯一 task
  `9615a5f6-bc5c-4203-931d-32990b07432b` 返回
  `SUCCESS / processed=true / reason=the_racing_api_shadow_applied /
  revision_id=2`。上游 observation 时间为 `14:14:42.301344Z`，距预计开跑
  `14:02:00Z` 为 `12` 分 `42.301` 秒；控制循环检测到首个 shadow result 后立即停止，
  未执行数据库给出的下一次 `14:24:42.301344Z`。
- observation ID `1` 为 `provisional / the_racing_api_free_v1 /
  licensed_api_automation`，无 parse warning；normalized SHA-256 为
  `4d2fa8c03ad3ae735700bd72291f822ea53e75449f90f3ad568392e2995dccc2`。
  result revision ID `2` 为 revision no. `1`、`provisional`、supplemental authority、
  `provisional_result_accepted`、conflict none，包含 `7` 个 finished item 和完整
  `1–7` 名次，证据链接 `1` 条，`published_at` 为空。
- tracking 已为 `provisional_result / shadow_applied`，current result pointer 为 revision
  `2`，claim 已释放，连续失败为 0。HostBudget 为 failures `0`、error 为空、circuit
  关闭、lock version `22`。
- 停止后 tracking/allowlist 仍精确为 `[924]`，四层 policy 仍为 shadow；legacy result、
  revision publication、official marker evidence、verification incident 全为 0。
  `RACE_LIVE_SCHEDULER_ENABLED=false`，live queue、active/reserved 和 one-off 均为空。
- 公网 event 详情及 `umafans.run`、`www.umafans.run` healthz 均为 HTTP 200；详情仍只
  显示 `15:02`，不显示 7 匹 shadow participant 或暂定/正式/更正赛果标识。

本授权已在首个 shadow result 到达时消费完毕。不得执行 `14:24:42Z` 后续探针、打开
scheduler、扩展赛事或公开；后续来源结果复核、provisional public 灰度均须重新审核并取得
精确授权。

## 2026-07-18 event 924 单赛事 TRA shadow runner 启动检查通过

- 用户显式授权只启动 event `924` 的 The Racing API shadow runner 检查，要求
  scheduler false、公开不变且不扩展赛事。执行前 production tracking/allowlist ID 均只有
  `[924]`，四层 policy 全为 shadow，event 为 `racecard_ready`、owner generation 1，
  observation/result/publication/incident 全为 0。
- shadow 启动前 custom-format 数据库备份为
  `/opt/umanewsbot/backups/db/pre-race-live-shadow-924-ebab4aa8-20260718T102543Z.dump`，
  `198,234,122` bytes、`root:root 0600`、SHA-256
  `bc06babe341e25a45ba097aaed157c7530994e06edebc497f612642d30676207`，
  `pg_restore -l` 通过。环境备份
  `/opt/umanewsbot/.env.backup.pre-race-live-shadow-924-ebab4aa8-20260718T102543Z`
  为 `root:root 0600`，与改动前 `.env` 逐字节一致。
- 生产 `.env` 只把 `RACE_LIVE_RUNNER_MODE` 从 `disabled` 改为
  `the_racing_api_free`，`RACE_LIVE_SCHEDULER_ENABLED=false` 未变；只重建
  `race_live_worker`。新 worker 仍运行 image `sha256:4443a9c…55dc` /
  revision `ebab4aa8…9992b`，registry SHA-256 `60fcc081…ad402`，实际 Celery 节点
  `celery@81ec88d9e165` ready。首次定向 ping 发生在 worker 启动完成前而超时，随后 broad
  ping、active/reserved 均正常。
- 未绕过 `next_poll_at=2026-07-18T10:32:21.495909Z`。在
  `10:33:03.874928Z` 精确 claim event `924`，owner generation 1、claim generation 1、
  TTL 120 秒，并只投递 task
  `7ba0699c-02f1-4b7d-864e-ed5cb7127ff0` 到 `race_live` 队列。Redis result backend
  复核为 `SUCCESS / processed=false / reason=pre_off_wait`。
- task 按设计在开赛前释放 claim，checkpoint 为 `pre_off_wait`，next poll 更新至
  `2026-07-18T11:33:04.049149Z`。HostBudget 的
  `next_allowed_at/consecutive_failures/last_error_code/lock_version` 完全未变，证明本次
  没有提前请求结果 API。
- 执行后 tracking/allowlist 仍只有 event `924`，claim 为空，racecard revision 仍为 1；
  observation、result revision、legacy result、publication、marker evidence、incident
  均为 0。live queue、active/reserved、one-off 均为 0。
- 当前容器中只有 `race_live_worker` 的 runner 为 `the_racing_api_free`；
  web/普通 worker/Beat 仍为 disabled，所有服务 scheduler false。公网详情和两个 HTTP
  healthz 为 200，页面只显示 `15:02`，不显示 7 匹 shadow participant 或任何赛果标识。
- scheduler false 意味着 `11:33:04Z` 不会自动投递。下一步须另行授权 event `924` 的
  有界单赛事 shadow 轮询窗口；不得因此打开全局 selector、扩大赛事或公开。

## 2026-07-18 event 924 initializer 已完成，单赛事 shadow baseline 就绪

- 用户已针对 manifest
  `ee9d0d43ac52c1678ddce61dbd7c4a6b0c0630eb02d2dd6fd8e43cfc5fcd1432`
  显式授权 event `924` initializer dry-run/apply/verify。执行前生产 checkout/OCI
  revision 仍为 `ebab4aa8e4e855d644771584c010fa6b07b9992b`，manifest、companion
  hashes、event baseline、空历史租约、空 live queue 和关闭开关均无漂移。
- initializer 专属写前 custom-format 备份为
  `/opt/umanewsbot/backups/db/pre-race-live-init-924-ebab4aa8-20260718T100040Z.dump`，
  `198,147,827` bytes、`root:root 0600`、SHA-256
  `e57218e77a1457c2aca7053d962d09b38942d4ad7cd9534185713236a61370fe`，
  `pg_restore -l` 通过。
- 同一只读 manifest、同一镜像和同一 expected commit 的 dry-run、单次 apply、独立 verify
  均为 `ok=true / error_count=0 / event_count=1 / participant_count=7 /
  replayed_event_count=0`。OperationLog 为 `105221`。
- event `924` 保持 `scheduled`，已写入 `race_datetime=2026-07-18T14:02:00Z`、
  London local time `15:02`；projection owner 为 `live / generation=1`，owner manifest
  与获准 SHA 一致。tracking 为 `racecard_ready`，claim 为空。
- 已创建 `1` 条 approved supplemental TRA source identity、`7` 条 approved
  participant 与 `7` 条 participant identity、`1` 条未发布 racecard revision 和 `7` 条
  declared revision item。四层 publication policy 均为 `shadow`；event allowlist 虽
  `enabled=true / max_mode=provisional_public`，但有效模式仍被四层 shadow 上限约束。
- `RaceEventResult`、result revision、observation/evidence、revision publication、
  official marker/incident 均为 0；current result pointer 为空，racecard revision
  `published_at` 为空。公网详情为 HTTP 200，只显示 `15:02`，不显示 7 匹 shadow
  participant 或暂定/正式/更正赛果标识。
- `RACE_LIVE_SCHEDULER_ENABLED=false`、`RACE_LIVE_RUNNER_MODE=disabled`，
  live queue 和 one-off 为 0，站内及两个公网 HTTP healthz 为 200。initializer 授权已消费，
  不得重复 apply；下一步须另行授权单赛事 TRA shadow runner 启动检查，不能直接开启公开。

## 2026-07-18 event 924 退避重试 prepare 成功，停在 initializer 门禁

- 用户显式授权退避后仅重试 event `924`。执行前 UTC 为 `09:29:51`，已晚于
  HostBudget 的 `next_allowed_at=09:11:52.789191+00:00`；circuit 未打开，event 仍为
  `2026-07-18 / NEWBURY / G3 / scheduled`，scheduler false、runner disabled、
  `race_live` 队列和 one-off 均为 0。
- 有效 run 为
  `/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-grade-retry-20260718T093207Z`。
  today/tomorrow 两个固定 GB 请求均为 HTTP 200，分别为
  `215,646 bytes / 1,425 ms / 4b4385a77f6766160d70777c62110d438d37a9107c7578ad86026bf9cc859b1d`
  与
  `76,616 bytes / 1,184 ms / 14364e390bfebb033633d1b6b8b3fc8021ffbab52dffb0d18605fabdcfba6128`；
  `completed=true / request_count=2 / blockers=[]`。
- manifest SHA-256 为
  `ee9d0d43ac52c1678ddce61dbd7c4a6b0c0630eb02d2dd6fd8e43cfc5fcd1432`，
  report/request SHA-256 为
  `96cb3acb3ef11c124dbd370226b3252ef31297e57ad4cb32da84443aa63fdc2d` /
  `cf45c566d9dc3bea64eaff27cf7a81a92942ebf834eae880a067b1066e35dd32`。
  目录/文件权限为 `0700/0600`，manifest companion hashes 与宿主重算一致。
- manifest 唯一绑定 event `924` 与 `rac_13000002795`，开赛时间为
  `2026-07-18T15:02:00+01:00`，共 `7` 匹 declared participant，目标 tracking state 为
  `racecard_ready`；审计未发现 raw、凭据、第三方评级或评论字段。
- prepare 后 event `924` 的 status、时间字段与 `updated_at` 未变化；生产仍为
  `9,867 events / 100,132 runners / 91,897 results`，所有 live
  control/tracking/source/participant/observation/revision/publication/incident 表仍为 0，
  policy/allowlist、live queue 与 one-off 仍为 0。HostBudget 已恢复为
  `consecutive_failures=0 / last_error_code=""`，站内与公网 HTTP healthz 为 200。
- 本轮只生成并审计成功 manifest，未执行 initializer dry-run/apply/verify，未初始化
  shadow、未开启调度或公开。下一步必须对该精确 manifest 取得单独授权后，才可运行
  schema v2 initializer。

## 2026-07-18 英国 Group 后缀修复已发布，首轮新 prepare 因上游 429 安全停止

- 最新成功原生 review 后，用户授权的冻结提交
  `ebab4aa8e4e855d644771584c010fa6b07b9992b` 已快进 `main` 并发布。生产 checkout、
  web、普通 worker、Beat 与独立 `race_live_worker` 均运行 AMD64 image
  `sha256:4443a9c418dd696c7faa4afec0ae34551bceec2e85d6c917fa27de706fe155dc`；
  tree 为 `f9a04eccc5bbda31a2619f3642e32c51275f0cc2`，clean source archive SHA-256 为
  `75939622bb5a31b524fc7e339109c64565ef038f8ead1734d20905ece5a937b5`。
- 写前 custom-format 备份为
  `/opt/umanewsbot/backups/db/pre-racecard-grade-ebab4aa8-20260718T090735Z.dump`，
  `198,033,727` bytes、`root:root 0600`、SHA-256
  `17ba9ccbe0e28fe765f0f449c78452664f39f204011a1b8decb873240afd3db0`，
  `pg_restore -l` 通过。环境备份为
  `/opt/umanewsbot/.env.backup.pre-racecard-grade-ebab4aa8-20260718T090735Z`；
  回滚标签 `umanewsbot:rollback-pre-racecard-grade-ebab4aa8-20260718T090735Z` 指向旧
  image `sha256:7f188f8fc85979ad6df3504c49e42aed4e0c41696f64301b2a33c6c888722981`。
- 候选镜像内 registry SHA-256 仍为
  `60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`；
  Django check、migration check、model drift、racecard sync `20/20` 通过。部署后内外
  healthz 为 200，两个 Celery 节点可响应；只有 live worker 挂载 secret ro 与 racecard
  artifact rw。
- 生产保持 `RACE_LIVE_SCHEDULER_ENABLED=false`、
  `RACE_LIVE_RUNNER_MODE=disabled`，`race_live` 队列为 0，所有 publication policy/
  allowlist 为 0。赛事、runner、result 仍为 `9,867 / 100,132 / 91,897`，全部 live
  control/tracking/source/observation/revision/publication/incident 仍为 0。
- 新 run
  `/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-grade-fix-20260718T091135Z`
  的 today GB 请求为 HTTP 200（`215,645` bytes，`1,379 ms`），tomorrow GB 请求为
  HTTP 429（`47` bytes，`374 ms`）。因此结果为
  `completed=false / request_count=2 / blocker=http_429`，目录为 `0700`，
  `report.json/requests.jsonl` 为 `0600`，没有 `manifest.json`，未执行 initializer。
  report/request SHA-256 分别为
  `3e37ecef79545aae09fa4609b89cd246a383ff4bf20c8ea268b2d3b242f1d91b` /
  `7c0ca959e9a70f10374a4f4713ee424494457e67635f0878bd4d191111a3d5d5`。
- HostBudget 按设计记录一次 `http_429`，未打开 circuit；业务与 live 事实零变化。不得复用
  本 blocker artifact、手工构造 manifest 或绕过 tomorrow 路由。下一步若要用新 run-id
  退避后重试，须先取得新的显式联网重试授权；成功 manifest 仍须单独审核，不能自动初始化。

## 2026-07-18 英国 Group 级别后缀精确匹配已实现，待独立代码审核

- 独立 worktree 为
  `/Users/mentianlu/Code/umanews/.worktrees/realtime-racecard-identity-diagnosis`，
  分支 `codex/realtime-racecard-identity-diagnosis`，基线为
  `origin/main@12d76e61850f1f847aba13ac1c07004040191728`；change artifacts 位于
  `docs/changes/realtime-racecard-grade-name-variants/`，方案 reviewer 的首次 finding
  已全部关闭并在同一会话复审为 `VERDICT: APPROVED`。
- 对生产 event `924` 执行了一次无 raw、无数据库写入、无 artifact 的受控来源诊断：
  TRA today GB 返回 HTTP 200、47 场 racecard，Newbury 唯一同形候选为
  `rac_13000002795`，赛事名
  `Hallgarten And Novum Wines Hackwood Stakes (Group 3)`。这证明上一轮
  `racecard_not_found` 是 event 获准基础名称与来源末尾 `(Group 3)` 的确定性格式差异，
  不是来源覆盖缺口。
- `_event_names()` 现在只对英国且 `normalized_grade=G1/G2/G3` 的已批准名称集合使用固定
  `group 1/2/3` token：名称中零 Group token 才保留基础名并增加一个精确 suffix 变体；
  恰好一个、位于末尾且同级的 token 保留一次；异级、非末尾或多个 token 整条排除。候选
  仍由原有规范化后的 set membership
  精确匹配；没有引入 substring、fuzzy、sponsor 删除、自由级别解析、数据库 alias 或其他
  地区行为。
- 真实 RED 先证明 event original + `(Group 3)` 返回
  `('racecard_not_found',)`；首次实现后新增聚焦测试 `6/6`。原生代码 review 发现非末尾/
  多 Group token 的 P2，并在修复前取得 3 个 subtest 的真实 RED；最小修复后聚焦
  `7/7`、racecard sync 模块 `20/20`。主代理的 SQLite 准实时/初始化/来源/相邻历史组合为
  `210/210`，一次性本地
  PostgreSQL 16 初始化竞争与 HostBudget 锁组合为 `6/6`；Django check、migration drift、
  `py_compile` 和 `git diff --check` 全部通过。无模型或 migration 变化。
- 当前仅完成本地实现与验证，尚未 commit、push、deploy，也未运行新的生产 prepare 或
  initializer。生产仍运行 `6646302b` 对应镜像；scheduler false、runner disabled、公开
  policy off。下一门禁是复用同一独立代码 reviewer 会话限定复审 P2 修复；最新成功 review
  后还需用户对精确冻结版本重新授权发布。

## 2026-07-18 准实时赛前 racecard/off time 增量已发布，首轮英国 prepare 安全停止

- 用户在最新成功代码 review 后授权的冻结版本已发布。提交为
  `6646302b80c90cf406075516ab4812f2f4ebee18`，生产 checkout、web、普通 worker、Beat
  与独立 `race_live_worker` 均运行 AMD64 image
  `sha256:7f188f8fc85979ad6df3504c49e42aed4e0c41696f64301b2a33c6c888722981`；镜像内
  registry SHA-256 为
  `60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`。
- 写前数据库备份为
  `/opt/umanewsbot/backups/db/pre-racecard-6646302b-20260718_105233.dump`，
  `196,919,649` bytes、权限 `0600`、SHA-256
  `6bdda3152cb3ee6a92fc774989dde7fc94614149066e01e4bb746d85fb9f7882`，
  `pg_restore -l` 通过；环境备份为
  `/opt/umanewsbot/.env.backup.pre-racecard-6646302b-20260718_105233`，回滚标签
  `umanewsbot:rollback-pre-racecard-6646302b-20260718_105233` 指向旧 image
  `sha256:111dbe46ba7a7024632ba2ca7c57c387b19ab39861f0147421a0245d08c38d7a`。
- 部署后 Django check、migration check、model drift 和镜像内 racecard sync/initializer v2
  `20/20` 通过；无 migration。web、两个 Celery 节点、Beat 和 Nginx 正常，内外 HTTP
  `/healthz/` 为 200。只有 `race_live_worker` 挂载 `/run/secrets:ro` 和
  `/run/race-live/racecards:rw`，web/普通 worker/Beat 均无这两类挂载。
- 生产继续保持 `RACE_LIVE_SCHEDULER_ENABLED=false`、
  `RACE_LIVE_RUNNER_MODE=disabled`。`race_live` 队列为 0；普通 worker 恢复 Beat 后正常
  处理既有新闻抓取任务，不与 live worker 混用队列。
- 首轮受控 prepare 只选择英国 event `924`，run 为
  `/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-20260718T030337Z`。
  today/tomorrow 两个固定 GB 请求均为 HTTP 200，但严格赛场、日期、赛事名匹配得到
  `racecard_not_found`，因此 `completed=false`、未生成 `manifest.json`，不得运行
  initializer。report/request SHA-256 分别为
  `bd7a19f8867df38e21e88ae2db465f9b6c5be30ad3b520e6b7fa988c9f5ae46a` /
  `78fef17cc843d8f83588a716dffc7fab0de56a740b88edc2a5510e0b99afcf2d`。
- prepare 后赛事总量仍为 `9,867 events / 100,132 runners / 91,897 results`；live
  control/tracking/source/observation/revision/publication/incident 全为 0，仅按设计新增
  `1` 条 `RaceLiveHostBudget` 控制面记录。下一步必须先审核 event 924 与 TRA racecard 的
  身份/别名或覆盖缺口，再以受审数据修复和新 run-id 重跑；不得猜测开赛时间、放宽精确
  匹配或对 blocker artifact 运行 initializer。

## 2026-07-18 准实时赛前 racecard/off time 同步已实现，待独立代码审核

- 独立 worktree 为 `/Users/mentianlu/Code/umanews/.worktrees/realtime-racecard-sync`，
  分支 `codex/realtime-racecard-sync`，基线为最新
  `origin/main@234358979dea3620d04445bb569b30e4a5b2fe8a`。change artifacts 位于
  `docs/changes/realtime-racecard-sync/`；同一方案 reviewer 已关闭全部 P0/P1 并给出
  `APPROVED`。
- 新增显式 event ID 驱动的英国 TRA Free racecard prepare：固定请求
  `today/tomorrow + region_codes=gb`，经共享 HostBudget 1 RPS、最多一次且不超过 2 秒
  等待、`Europe/London` instant 转换、赛场/赛事名精确匹配后，原子生成不含 raw 或专有
  字段的 `manifest/report/requests`。零命中、多命中、baseline 漂移、条款/registry 或
  路径异常均只形成 blocker，不产生可 apply manifest。
- initializer 新增 schema v2：完整 run 目录只读加载并重算 companion SHA，锁内区分
  fresh/replay，逐字段核对 status/local date/timezone/旧时间，在同一事务补齐
  `race_datetime/local_start_time` 并初始化 participant/racecard/live shadow 行；不同
  manifest、人工锁、身份冲突或后段失败全部 fail closed/回滚。schema v1 保持兼容。
- `racecard_ready` 的有效赛前 claim 现在零 HTTP checkpoint：释放 claim、失败计数不增、
  `next_poll_at` 推进且不晚于 off time；到达 off time 后才在 owner/claim CAS 下晋级
  `awaiting_result` 并进入既有赛果请求。stale claim 或 owner 漂移保持零写入。
- 真实 RED 已记录在 change 的 `test_cases.md`。主代理复跑的 GREEN 为 SQLite 组合
  `203/203`、一次性本地 PostgreSQL 16 初始化/runner 并发与锁语义 `6/6`；Django check、
  migration drift、三份 Compose、`py_compile`、registry SHA 与 `git diff --check` 通过。
  新 registry SHA-256 为
  `60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`。
- 首次独立原生代码 review 找到两个 P2：同 run-id 并发异常清理可能删除赢家 artifact，
  以及赛事占用检查在 40 场时产生 322 次查询。两项均先补真实 RED，再加入 root 级发布
  锁/目录 inode 所有权校验和八类固定批量占用查询；修复后 racecard sync `13/13`、
  准实时相关组合 `184/184`，等待复用同一 reviewer session 限定复审。
- 当前只完成本地实现和验证：尚未 commit/push/deploy，未访问真实 TRA、未运行生产
  prepare/initializer，未改变生产 HostBudget 或赛事业务数据，scheduler 仍为 false、
  runner 仍为 disabled、公开 policy 未开启。下一门禁是独立代码 review；只有其成功后
  才向用户请求本任务新的发布授权。

## 2026-07-18 8,867 场已导入历史赛事已公开

- 生产只读 eligibility 审计确认 `8,867 eligible / 0 blocked`，地区分布为日本 `2,239`、中国香港 `473`、英国 `2,144`、法国 `652`、美国 `3,359`。原始审计位于 `/opt/umanewsbot/runtime/historical_publication/eligibility-20260718_031331/publication-manifest.json`，SHA-256 为 `2768e9f66fcba74dad95ffe4505d8283ff11c1d6e2c3fb2c2bde3b2f213a110e`。
- 正式不可变 scope 为 `/opt/umanewsbot/runtime/historical_publication/eligibility-20260718_031331/publication-scope-v1.json`，SHA-256 为 `c27491e4987a548a6c635c936b28211a1c0e2e1c8c0bd594b8467bfba539977a`；它固定 `8,867` 个 target ID 及逐目标 artifact SHA，不按线上动态查询扩张范围。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-historical-publication-8dec0076-20260718_041218.dump`，`195,414,204` bytes，SHA-256 为 `83a7524eb36bdb69e9cece8a749115022e9b94682b9dd37080df5756358a9d29`，`pg_restore -l` 通过；环境备份为 `/opt/umanewsbot/.env.backup.historical-publication-8dec0076-20260718_041218`。
- dry-run、原子 apply 和独立 verifier 均为 `8,867 checked / 0 errors`。结果 SHA-256 依次为 `d830060cf33bd6ebb6ce6f5ed141799497e893fb74cdbaa79bbbfe5031dc0485`、`46f5a58eeefed4c35547308ede4cfcf7b83b1842d344cbd40e17a8ad9216853e`、`35cee37116bc0eeff4fa1bd940c01dc8f4ad8e8a9a908fd320d15a6417e04d2b`。
- 生产现有 `9,867 RaceEvent / 9,820 published / 8,867 published+complete / 100,132 runners / 91,897 results`；`8,867` 个 imported 历史目标全部已关联到公开且完整的赛事。
- 浏览器验收覆盖五区列表、赛事详情、历届、出马表、赛果和移动端。纯数字距离现按地区及赛事类型显示单位：日本、中国香港、法国为米；美国及英国平地为弗隆；英国障碍为英里。数据库原值、导入器、API 和 verifier 口径未改变。
- 最终运行代码 revision 为 `4af5e20a3c65ddad81bcf054f7fd1cb1f8d0dfde`，tree 为 `32928369f7c20c74425902ba3d13932d7a0c0043`，web、worker、Beat、`race_live_worker` 和 `umanewsbot:prod` 统一使用 AMD64 image `sha256:111dbe46ba7a7024632ba2ca7c57c387b19ab39861f0147421a0245d08c38d7a`。公网 `/healthz/` 和赛事页为 200，Redis `celery/unacked/race_live` 队列均为 0。
- 历史公开通过 `RaceEvent.visibility_status=published` 和 `data_quality_status=complete` 持久化，不依赖常驻抓取开关。生产仍保持 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`、`RACE_LIVE_SCHEDULER_ENABLED=false`、`RACE_LIVE_RUNNER_MODE=disabled`。
- “已公开”不等于 `30,917` 条正式总账全部完成。总账当前另有 `20,544 pending / 1,467 source_unavailable / 31 identity_review_required / 8 ready`；后续抓取继续按这些缺口推进，不回退或重跑本次已公开的 `8,867` 场。

## 2026-07-18 准实时赛果安全基线已发布，shadow 因赛程时间缺口保持关闭

- 最新成功 review 后的整合冻结版本已按用户授权发布：生产 `HEAD=4f11b2273fd167c69d54b338a4e627a77dd010c2`、tree `277cb10ad56aee9a3156fa2b1632dd73377054c8`，source archive SHA-256 为 `e957e748b82b4933eeaab2f5721185e42e6f4e58b9e552ee10cfabace11ca2d5`。web、普通 worker、Beat 与独立 `race_live_worker` 均运行 image `sha256:c2b9e15e037406808bef1edbbef888728a8f0d6ae40c47418c6cd4e414803966`，OCI revision 与生产 checkout 一致。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-realtime-race-results-4f11b227-20260718_034437.dump`，`195,161,786` bytes、权限 `0600`、SHA-256 `f81a11ece1b75f5ff680e445b71b910ea453ee1fc26eeb24ac8df030daf72a01`，`pg_restore -l` 通过。环境备份为 `/opt/umanewsbot/.env.backup.pre-realtime-4f11b227-20260718_034437`；即时回滚标签 `umanewsbot:rollback-pre-realtime-4f11b227-20260718_034437` 指向旧 image `sha256:63cdfc131ebb4152f4f56740fe6f94f806f33139b9496f15679b184457397329`。
- 生产已应用 `stable.0033` 至 `stable.0045`；Django check、migration drift、镜像内初始化器与 TRA runner `13/13`、registry SHA 和无 secret 检查通过。迁移后 `9,867 events / 100,132 runners / 91,897 results` 保持不变，所有 live control/tracking/observation/revision/publication/incident 行均为 `0`。
- TRA secret 仅存在于生产 `/opt/umanewsbot/runtime/secrets/the-racing-api-free.env`，为 `root:root 0600` regular file。生产配置保持 `RACE_LIVE_SCHEDULER_ENABLED=false`、`RACE_LIVE_RUNNER_MODE=disabled`；普通 worker 只消费 `celery`，独立 worker 只消费 `race_live`，后者队列为 `0`，没有发送 live 网络任务或公开写入。
- 生产只读来源 proof 位于 `/opt/umanewsbot/runtime/race_live_source_proofs/production-proof-20260718_035358`：3 个固定 Free 端点均 HTTP 200，regions/racecards/results 分别为 `55 / 69 / 50`，请求元数据 SHA-256 为 `421a3d7976fbaee0e5c2ed20caaf8fa7b7647895fed6e2666971248ecbb6fc59`；未保存 raw payload，未连接业务写路径。
- 首轮英国 shadow 没有生成或应用 manifest。生产从 `2026-07-18` 起共有 `428` 条 future `RaceEvent`，其中英国 `72` 条，但 `race_datetime` 非空均为 `0`；当天英国 Group 3 event `924` 同样缺少 `race_datetime/local_start_time` 且无 runners/results。冻结初始化器要求 aware `race_datetime` 并精确匹配既有赛事，仓库也没有已审核的赛前 racecard/开赛时间写入路径，因此当前必须 fail closed。不得手工猜时间或绕过初始化门禁；需要把赛前 racecard 与开赛时间同步作为后续受审增量。
- web 重建后 Nginx 曾保留旧容器 IP 并短暂返回 502；重启 Nginx 重新解析 `web:8000` 后，本机和公网 HTTP `/healthz/` 均恢复 200。四个 app 服务 restart count 均为 `0`，近期 app 日志无 `Traceback/CRITICAL/ERROR/Exception`；公网 HTTPS 仍是既有未接入状态，不属于本变更验收。

## 2026-07-18 AI 赛事身份决定已完成生产写入

- AI 初审的 `267` 条决定已经按原 manifest 完成生产执行：`228` 条合并并关联、`21` 条保持独立、`18` 条非同赛／忽略；实际写入汇总为 `228` 个正向动作、`24` 个去重后的负向系列对和 `1` 个 John C. Harris Stakes `surface: dirt -> turf` 修复。
- 正式 manifest 仍为 `cf5e220e9c0a0c7b2daeb7ef5030ed3243059ec9bd36ba5e6e2390c0d89a0147`，actions 为 `9622460e82dc4d3449bf693bf2e7e107e43684c5b5dbf518bc700a4a24f53da1`，用户签署 approval SHA-256 为 `f02b0e4c11a605fe3d4f818856d699a8979c12b9884d04d93ed32adbb44b0584`。未重算或替换任何审核决定。
- 首次 apply 在 PostgreSQL 第一组锁查询被 `FOR UPDATE cannot be applied to the nullable side of an outer join` 拒绝，发生在业务写入前；prepared verifier、总量和 OperationLog 复核均证明零写入。技术修复改为只锁 target/event 基表、继续预取系列并独立锁定全部相关系列；本地相关测试 `52/52` 通过，PostgreSQL 专项在 SQLite 按设计跳过 1，同一原 reviewer 限定复审为 `APPROVED`。生产只读 smoke 成功锁定并回滚 `497 series / 267 targets / 261 events`。
- 最终代码 revision 为 `f396d04837c7161a351b920737ac030911dec3e3`，tree `f9bef70b59f2ee0dfa0bbd2a78c5c2c316e45d45`，source archive SHA-256 `fd0c66acb2cef161746e2b2d851106ac12ba475abdab0b5107f2871a1e557d72`。两个独立归档上下文构建得到相同 AMD64 image `sha256:63cdfc131ebb4152f4f56740fe6f94f806f33139b9496f15679b184457397329`；生产 web/worker/beat 已统一运行该镜像。
- 最终写前备份为 `/opt/umanewsbot/backups/db/pre-race-series-identity-f396d048-20260718_014337.dump`，`194,307,039` bytes、权限 `0600`、SHA-256 `640791685f14d82cd8a47a9c83ce2b6fb4a361e8edafa824c9c2e6338c892707`，`pg_restore -l` 通过。即时代码回滚标签为 `umanewsbot:rollback-pre-f396d048-20260718_014256`，环境备份为 `/opt/umanewsbot/.env.backup.pre-f396d048-20260718_014256`。
- 正式 apply result SHA-256 为 `20fb046276e633ba9c682fc62ec865dca41acff2ce6bccd5ad74256fb02b3365`，rollback ledger SHA-256 为 `0a37af374fc06a2e19cb70360c1a512389f066d99f6927c079c76cc4389531e5`；事务内和独立写后 verifier 均为 `ok=true / error_count=0`，OperationLog ID 为 `96353`。
- 写后总量严格守恒：`9,867 events / 100,132 runners / 91,897 results` 未变化；正式目标关联由 `8,875` 增至 `9,103`，系列关系由 `0` 增至 `228`，John C. Harris event `507` 已为 `turf`。historical runner、锁、started receipt、翻译和外部导入均为 0；历史公开、常驻历史写入和网络开关保持关闭。内外 HTTP healthz、worker ping、active/reserved、Redis 队列和近期错误日志均通过。

## 2026-07-18 准实时暂定赛果主链已补齐生产 shadow 初始化路径

- The Racing API Free 自动化 runner 已完成真实 RED -> GREEN：固定 HTTPS host/path、仓库外 `0600` secret、审核 registry digest、条款/automation permission、1 RPS 共享 host budget、15 秒 timeout、2 MiB 上限、禁止 redirect，网络期间不持有数据库事务。Free racecards/results 请求上限按当前官方文档修正为 `500/50`；当前 registry SHA-256 为 `1d801e95b2770c741503a75dbcba93aca407a6cd681f3471813f1e7d5586fa32`。
- 合法且唯一匹配的结果先写 append-only observation 和 shadow revision，再经唯一 `admit_race_live_publication()` 重读 owner/claim、TRA supplemental authority、持久 policy/allowlist、coverage/registry digest、获准 racecard 参赛全集、身份审核和人工锁；通过后才物化公开暂定赛果并原子创建 `off time + 2h` 官方复核 incident。空列表或未命中只做短间隔 checkpoint，不会清空或覆盖现有赛果。
- 已新增默认关闭的 global/region/source/event 公开读取门。任一适用 policy 改为 off 时，已发布 live badge 和当前物化赛果立即从详情读取面隐藏；恢复后仅重显仍满足版本/digest 门禁的 revision。新增 publication policy、event allowlist、official marker/evidence/incident 五张只读后台观测面，人工 kill switch 继续走 CAS 审计。
- Celery task 只有显式 `RACE_LIVE_RUNNER_MODE=the_racing_api_free` 才进入真实 adapter；scheduler、runner 和三个 secret/registry 配置默认关闭/空。三份 Compose 只给独立 `race_live_worker` 挂载 `./runtime/secrets:/run/secrets:ro`，镜像内只复制受审 registry，不向 web、普通 worker或 beat 暴露 secret。
- 首次完整代码 review 的原生命令因模型容量中断，人工检查提出的旧时钟、incident replay、日历 read gate、raw official marker 与生产初始化路径问题均已取得 RED 并修复。新增 `initialize_race_live_events`，以严格 schema v1、manifest SHA、approved commit、赛事更新时间和人工锁为门禁，提供默认 dry-run、显式 apply、独立 verify、全事务、精确 replay 和逐 event 审计；migration 不隐式接管赛事。
- shadow 初始化只创建四层 shadow policy、精确 allowlist、host budget、live control/tracking、TRA supplemental source、approved participant/racecard revision；shadow 命中结果只写 observation、未发布 revision 与成功 checkpoint，不生成公开赛果、publication 或 official incident。初始化器与 TRA runner 聚焦 SQLite `13/13`，临时 PostgreSQL 初始化并发及既有锁测试 `5/5`。
- 首次成功原生完整 review 关闭旧时钟、incident replay、生产初始化和 raw official marker 等问题，但发现赛事日历对每场 live revision 单独执行读取门禁：40 场页面实际产生 `525` 次查询。新增查询预算 RED 后，日历改为固定批量加载 event/control/revision/observation/source/publication、四层 policy 与 allowlist；详情页继续使用单赛事判定，fail-closed 语义不变。修复后公开状态组 `6/6`、准实时/来源 proof/初始化 SQLite `160/160`、临时 PostgreSQL `5/5` 通过，40 场页面受 `<=12` 查询硬门禁约束；同一 reviewer 已限定复审为 `APPROVED`。
- 合并前冻结候选镜像为 `sha256:4a281e426e3299287c948bc6fe7d6e2d0fcda52dbaa322da8db9982530b5b099`，OCI revision 绑定原 approved parent `283bacf2cdc5ff97423b50ff46cfda2a87120a2b`。镜像内 Django check、实际交付的初始化器+TRA runner `13/13`、registry digest `1d801e95...fa32` 和无 `.env`/secret 检查通过；完整源码树 `160/160` 单独通过。整套源码测试不能误当镜像自测，因为其中部署契约会读取不会被打包的仓库根 Compose/源 registry；三份 Compose config、两个 worker 脚本、migration drift 和 diff check 已在完整源码树独立通过。
- `main@ccb56f7d` 的赛事身份 PostgreSQL 锁修复和生产证据已保留，并把准实时补丁重放为以该 main 为单一 parent 的整合树。准实时+来源 proof+初始化+赛事身份 SQLite 组合为 `180/180`（1 项 PostgreSQL 专用按设计跳过）；准实时 5 项与赛事身份 1 项 PostgreSQL 专用测试在临时 PostgreSQL 16 为 `6/6`。整合候选镜像 `sha256:87f8603320f856bbc4167f29b76c811fe6e2a06b62bfb72dd73b944840b73bcf` 绑定 parent `ccb56f7d526daf70357f193f716b23eacb26edbe`，镜像内 check、初始化器+TRA runner `13/13`、registry SHA 和无 secret 检查通过。
- 2026-07-17 的 run03 因本机代理把 DNS 映射到非公网 `198.18.1.15` 而在首请求前安全阻断；未放宽 DNS/SSRF 门禁，先前 run02 的 3/3 HTTP 200 proof 仍为最近一次成功真实窗口。
- 尚未创建任何生产 tracking/source/participant/policy/allowlist 行，未启动生产 live worker、未迁移、未公开、未购买订阅。原冻结提交已获授权并推送，但 `main` 随后新增赛事身份生产修复与证据；基于 `ccb56f7d` 的单父整合树仍须由同一 reviewer 复审并重新取得用户授权。之后才能备份并应用 `0033-0045`、生成并审核精确 event handoff manifest、先初始化单地区 shadow，再逐赛事审核 provisional allowlist。官方 marker 自动 apply、incident 告警/长期探针及官方地区 adapter 不属于首轮 TRA provisional 公开链，不能据当前状态宣称正式赛果自动化已完成。

## 2026-07-17 AI 赛事身份初审已固化，生产写入待精确授权

- 用户提供的 AI 初审工作簿为 `/Users/mentianlu/Downloads/生产赛事身份审核_213a818c_20260717_AI初审建议.xlsx`，SHA-256 为 `d93286e9e61ccf41770fe607740a972d025c8a00b2deb1d4a4f1890954852492`。正式输入共 `267` 条：`228` 条同意合并并关联、`21` 条保持独立、`18` 条非同赛／忽略；John C. Harris Stakes 另附 `surface: dirt -> turf` 的显式字段修复。
- 身份执行工具已进入代码 commit `8b9b97552a6cb8b4b4690dc6f8b1a1d4233991e5`，tree `ab1f58af54381e72c7c277f03a59a29676618dae`。它只移动经批准年度赛事的系列归属、建立正式目标关联和 `MERGED_INTO` 沿革；不删除 `RaceSeries`，不改变公开状态、赛事状态、出马表或赛果。保持独立和误命中会写入双向禁止自动合并规则，字段修复独立执行。
- 真实 RED 后 focused/相关组合测试最终 `50/50` 通过；Django check、迁移无漂移和 diff check 通过。同一 reviewer 连续复审了事务、锁、序列唯一性、正负决定冲突、跨地区误命中和 TOCTOU 修复，最终结论为 `APPROVED`，无剩余直接 P0/P1。
- 生产只读 prepare 已在现有 `213a818c` 运行环境中加载上述精确代码完成，没有部署、重启或写库。有效 artifact 位于 `/opt/umanewsbot/runtime/race_series_identity_review/prepare-8b9b9755-20260717_205349/artifact`；manifest SHA-256 为 `cf5e220e9c0a0c7b2daeb7ef5030ed3243059ec9bd36ba5e6e2390c0d89a0147`，actions SHA-256 为 `9622460e82dc4d3449bf693bf2e7e107e43684c5b5dbf518bc700a4a24f53da1`，prepared verifier 为 `ok=true / error_count=0`。
- `approval.json` 仍为 pending，尚未签署或执行生产 apply。下一门禁是用户对上述 commit、manifest 和 actions 的明确授权；授权后才可部署精确代码、生成并验证新数据库备份、再次 dry-run/verify、由 `admin` 串行 apply 并逐项验收。历史公开、常驻历史网络和写入开关继续关闭。

## 2026-07-17 赛事正式总账与公开赛程关联工具已发布，生产只读审计待身份审核

- 已确认此前“7 场未到期”只代表 `8032` 个历史详情验收目标中的 `not_due`，不代表生产全部未来赛程；生产在 `2026-07-18` 至 `2026-07-31` 另有 `44` 条公开 `scheduled RaceEvent`，多数尚未关联正式目标。
- 新增只读 reconciliation、historical/current/result 三层覆盖报告、HTML/CSV 审核表、manifest+approval 双 SHA 门禁、整批原子 apply/rollback 和逐目标 verifier。 `not_due` 只允许采用同系列同年度的唯一既有 `scheduled/postponed` 赛事，不创建、删除或公开赛事，也不改变目标/赛事其他状态。
- change 文档位于 `docs/changes/reconcile-race-event-coverage/`；真实 RED 后 focused `22/22`、相关组合 `101/101`、Django check、迁移漂移和 diff check 全部通过。首次代码 review 的 8 项事务、TOCTOU、artifact、快照、alias 和统计问题已修复，同一 reviewer 复审为 `APPROVED`。
- 用户已批准 commit `213a818c2845fd29a2afe742ea8d11f653269d9e`。该提交已推送并快进合入 `main`；两个独立 AMD64 构建得到相同 image ID `sha256:f3b2d4625322e7f96554288d4b710723ff9d01323dd3be654bcbc2ba0281a9d9`，tree `799f77db3f253e524f5f0095ed07a4fe9c8cd058`，source archive SHA-256 `c15bec6853266cd61c4852380ff1f6613cfe4bc9e1614ad3a5272d1edf9eb92a`。生产 web/worker/beat 与服务器 checkout 现均为该 revision；无迁移，HTTP healthz 和 `/races/` 正常。
- 部署前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-race-reconcile-213a818c-20260717_015716.dump`，SHA-256 `7958873ff243f5a3c1bb85075f74fa0daec6a040f33688b31f63db71e1eb0e3b`，`pg_restore -l` 通过；环境备份为 `/opt/umanewsbot/.env.backup.pre-213a818c-20260717_015716`，回滚标签指向上一镜像 `sha256:c8c49780ac9dca4799e4834b052f7e05ca75ff61945343b2c19bf0ef2ab561ab`。
- 有效生产只读 artifact 为 `/opt/umanewsbot/runtime/race_event_reconciliation/prod-213a818c-mounted-20260717_021203`，manifest SHA-256 `5caee7d0ed093605aede28c2834d3acf8a75f9f20e2d88679924c3670f3c6a51`，verifier `ok=true / error_count=0`。基线为 `30,917 targets / 9,867 events / 100,132 runners / 91,897 results / 5,725 history winners`；分类为 `8,875 already_linked / 46 identity_conflict / 21,537 missing_event / 459 status_conflict / 0 exact_link`。
- 因该精确 manifest 没有可执行关联，approval 继续为 `pending`，没有签署、dry-run apply 或数据库关系写入。`not_held=459 / cancelled=15 / not_due=7` 是不同口径；2026 另有 `630 missing_event`，不得解释为未举办。严格赛果层因生产旧数据尚未写 `RaceEvent.result_confirmed_at` 而得到 `complete=0`，这是新显式确认字段缺口，不代表 `91,897` 条现有赛果消失。
- 只读明细进一步得到 `46` 条同名系列冲突和 `221` 条 2025–2026 别名/跨语言候选；其中 target `53418 / Tokai S` 与 event `83 / 東海S / 东海锦标` 日期、级别、场地类型和距离一致，但属于两个 `RaceSeries`。46 条中另有英国 Sprint Cup 命中香港同名赛事、美国 Hanshin Cup 命中日本阪神杯等跨地区同名技术噪声，必须排除后再做系列合并决定。审核文件为本地 `outputs/race_event_reconciliation_20260717/生产赛事身份审核_213a818c_20260717.xlsx` 与同名 HTML；确认系列身份后重新生成非零 `exact_link` 的 manifest，才允许进入备份、apply 和 verifier。
- 收口时无 historical one-off；常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，历史公开配置未开启。普通新闻 worker 有自然 crawl task 运行，Redis 主队列为 `0`；生产可用磁盘约 `3.6 GiB`，低于 `5 GiB` historical crawl 门槛，继续禁止在生产执行重型抓取。
## 2026-07-17 The Racing API 调整为暂定赛果公开主链

- 用户明确确认：对 The Racing API 已覆盖且通过身份/字段校验的目标赛事，不等待 JRA/NAR/HKJC 等官方来源二次复核即可把完整赛果推到前台；页面必须标注“暂定赛果”和更新时间。
- 官方来源改为异步复核链：一致则升级 official，不一致则保留 TRA observation 并原子显示官方 revision；正式/改判 authority 仍只属于持久、已审核的官方 source identity。
- 商业 API 信任不替代赛事/参赛马身份、完整字段、空结果、人工锁、冲突、条款、allowlist 和 mode 门禁。publication admission/read gate、TRA supplemental 数据库不可变量、基于 racecard 全集的完整性和 provisional 发布时创建官方复核 incident 已实现；官方 marker 自动 apply、incident 告警/长期探针和各地区官方 adapter 尚未实现。用户已授权测试先行、实现、shadow 与上线准备；实际生产发布仍须在最新成功代码 review 后取得一次新授权。

## 2026-07-17 准实时赛果完成 The Racing API Free 首个受控来源窗口

- 仓库外 `0600` secret 已投入使用，未把凭据复制到工作树、镜像、日志或 artifact。新增 proof runner 以精确 registry SHA、官方文档/条款证据、最多 3 请求预算、1.05 秒请求间隔、15 秒 timeout、2 MiB 上限、禁止 redirect/retry 和公网 IP/TLS 校验 fail closed；不访问 ORM，只保存脱敏 schema/计数/延迟/SHA。
- 多轮真实 RED 后，proof 测试 `9/9`；proof + 准实时 `126/126`；与 latest-main 相邻历史回归合并为 `262/262`（1 skip），隔离镜像、`--network none`，Django check 0 issues。reviewer P2 指出 proof 错误依赖长期 automation 许可，现已用 proof-only RED 解耦；生产/shadow adapter 仍须单独要求 automation 许可。后续两个质量建议也已修复：未来 proof 记录真实完成时间，未知 result status 不再伪造成 DNF；无效/倒退/异常时钟和无 partial artifact 均有自动化回归。
- run01 因本地代理 DNS 返回非公网地址于首个请求前安全阻断。run02 使用一次性本地容器固定经独立 DNS 审计的公网地址，三个 Free endpoint 均 HTTP 200：regions 55、racecards 10、results 0；未保存 raw/实体值、未写业务 DB、未连接生产。
- 这只是第一个观察窗口，只确认认证、端点和 schema。尚无已完赛样本，不能计算 result 覆盖或 p50/p95，也不能判断 provisional/official/corrected 或建议升级 Basic；至少四个真实赛日和正式重点赛事样本门槛保持不变。完整证据见 `docs/changes/realtime-race-results/source_proof_report.md`。
- proof runner 完整 review 的唯一 P2 和后续时钟测试覆盖 P2 均已由限定复审关闭并 `APPROVED`。本地 automation `tra-free-proof` 每日 06:30（本机时区）执行至多一次同一受控 proof；四个不同赛事日期且至少一个 results 非空后停止联网并提示汇总。它只写 gitignore runtime artifact，不改 tracked 文件或业务 DB。
- 当前仍不部署、不启动生产 live worker、不初始化 tracking、不购买订阅、不打开公开开关。

## 2026-07-16 第一期 1998–2026 历史赛事正式详情总账已收口

- 正式详情分母固定为 `8032`，最终为 `6534 complete + 1491 evidence gap + 7 not_due`；生产验收为 `6534 events / 70314 runners / 65227 results / 6534 winners`。日本、中国香港、法国 hard 范围完整；英国历史 hard 为 `708 complete + 45 evidence gap`；英国新正式范围为 `94 complete + 1 gap + 4 future`，美国新正式范围为 `195 complete + 1 future`。英国、美国历史 G2/G3 按已批准的 best-effort 政策收口，不把无可靠来源的目标伪造为完整。
- France 14 场补包 manifest 为 `7e8f29066bccae965ade8736e071189155cb8245e92309f07bf23bfa67f50eeb`，写入 `132 runners / 122 results / 14 winners`。写前备份 `/opt/umanewsbot/backups/db/pre-france-zone-turf-7e8f2906-20260716_2204.dump`，SHA-256 `ed7e189796d2d8d87c27874ecbab796db99829322e5cf9cfb388db9b362b60a9`；replay 与 verifier 均为 `errors=0`。
- UK 6 场补包 bundle 为 `fd3438beaeabbf15ed365069707cea982221a444716161d66a30e74bc2a0a081`，写入 `46 runners / 40 results / 6 winners`，出走状态为 `40 declared + 4 pulled_up + 2 withdrawn`。dry-run plan 为 `490400342fe30e4fe291691d7cc61801d42f025663cb25245d4d5793c122560e`；apply2 plan/state 为 `473495fbb70c22823d29471aa436d52a343596c23562043a42aff35c3dbdabbb` / `ca51bb347c4313a0bfeee645cc7fe9f33013da09713d2acbee02f69c0e688f0f`；replay plan/state 为 `5e1b5895d217b2f265cc9455b35679e566ebd7f922dedae3caf80bdc349070b1` / `cc5d9d149fbfe20a3796a9b6bf62e75e233448939f4b1ce6799ac9fffbade6ba`。
- UK 场地修正 manifest 为 `662be6d37e55fda7b3b2d620ddc61fe0ba2bc0291270d4bd7439ae8a4c0da903`，script SHA-256 为 `1ac34051d5c8a72294364b1f4d5b524c55d81e393c1188edcb12fbd0a508407c`；apply 与两次 verifier 均为 `4/4`。
- UK 6 场与 gap 裁决统一写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-uk-six-gap-659b46ca-20260716_230344.dump`，`189338143` bytes，SHA-256 `c5006b15bee22dd17d0d6fb7913f7c376a0799eeb37f3d6dc42b9199444c1410`，权限 `0600`，mtime `2026-07-16 23:04:32 +0800`，`pg_restore -l` 通过。
- gap/not_due resolution manifest 为 `d529126840a6d3c6ffb1abc0a426d3ac796d36f9df72a50dcc06b34e0af9c90f`；`1498` 条 resolution 已 apply，并通过两次独立 verify，生产存在 `1498` 条唯一 `OperationLog`。原因分布为 `1467 source_unavailable + 31 identity_review_required`；最终状态按到期日收敛为 `1491 gap + 7 not_due`。其中 target `53349` 的正式日期为 `2026-09-05`，target `53418` 为 `2026-07-26`。
- 最终 v5 产物位于 `runtime/race_event_crawl_runs/final-detail-coverage-ledger-v5-20260716`；manifest SHA-256 为 `692b089b0d18b08899571702cb57ff3dadbca144a2dce4c4e6b3d7c15e6584ea`，ledger SHA-256 为 `833995952fc444fd39c40934802cc7306cc7dd354c4f57db5bd725fc66a48fe9`，review 结论为 `approved`。global verifier 检查 `8032` 个目标，`errors=0`。
- 生产部署运行态：`prod` 与 web/worker/beat 统一为 image `sha256:c8c49780ac9dca4799e4834b052f7e05ca75ff61945343b2c19bf0ef2ab561ab`、revision `6b596befa0eea9ef0ba45acbb5384195829cc144`。即时回滚标签 `umanewsbot:rollback-pre-6b596bef-20260716_233842` 指向上一镜像 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`；环境备份为 `/opt/umanewsbot/.env.backup.pre-6b596bef-20260716_233842`。本次无迁移；Django check、两个正式 HTTP 域名 `/healthz/` 200、worker ping 均通过，日志未发现 error。
- 收口运行态为 formal `published=0 / featured=0`，`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，无 historical runner、无 running batch。清理未使用的旧 `umanewsbot` tags 后仅保留当前镜像与即时 rollback，可用磁盘由 `2.6 GiB` 升至 `4.0 GiB`；仍低于 `5 GiB` crawl floor，后续服务器 crawl 为 no-go，重型抓取继续使用本地 Docker。
- 结论：第一期 `1998–2026` 正式详情总账已按批准政策全部达到“完整或证据化 gap/not_due”，生产数据写入完成；本结论不等于赛事已经公开，历史公开仍保持关闭。

## 2026-07-16 英国 Sporting Life 增量详情包已正式导入生产

- 第一阶段应到清单尚未全部写入。本轮在本地 Docker、全程无数据库连接下补抓英国 Sporting Life 已发现目标 `198` 场，最终为 `197 complete + 1 parse gap`，包含 `2027 runners / 1794 results / 197 winners`。唯一缺口为 target `57633`（2015 Finale Juvenile Hurdle），来源页没有可解析 runner rows，已保留在统一 gap/review ledger；该缺口没有被伪造为 complete。
- 解析器提交为 `2a7352c8abfbd3b22aca274a1eeb3fda07731eb8`，真实缓存 RED 后回归 `39/39`，独立代码审核结论为“未发现可修复问题”。结构化 casualty 现可保留 `NonRunner / UnseatedRider / PulledUp`；普通 `tailed off` 文案仍不会被武断映射为退赛。
- 六个 2023 英国目标的旧总账距离丢失英里位，已按 Sporting Life 详情页结构化距离生成独立 correction ledger；原值、新值、来源 URL 和 fixture SHA 全部绑定。v8 plan manifest 为 `9f3042caf4a9bc27dbc5d9e1130b4a72a1e0f380ca2a3ef24dabca1322b729b0`，correction ledger 为 `ab17e79d823dff6e79d27b69a751aa10c8d700787e104a646229106e8c003350`。
- 增量 source bundle 位于本地 `runtime/historical_plan_exports/detail-import-bundle-uk-sportinglife-v8`，已在生产隔离目录 `/opt/umanewsbot/runtime/historical_race_detail_import/detail-import-bundle-uk-sportinglife-v8` 逐字节复核。bundle manifest 为 `3c6a4d11106c2b490876d63f0719b71d6fde9d7c7bc9c8937736d26a0e28831c`，identity 为 `2392a69c7cf1b03812422cf11b3c5ed73a181e719ca6309d79283812c735cb50`；当前生产镜像在 `--network none` 下验证 `197` records、`197` source objects、`67302603` source bytes 全部通过。
- 用户按 commit `2a7352c8` 和 bundle manifest `3c6a4d11106c2b490876d63f0719b71d6fde9d7c7bc9c8937736d26a0e28831c` 明确授权。approval 于 `2026-07-16T09:33:54Z` 签署；historical approval SHA 为 `6a0240453cf19d681365a7add59ff2ea254fff5dfaee3ca6722495450ca87aec`，current-year-due approval SHA 为 `93bf1143460450015365f85fa7d2c3aae2a479180ccf69c953e9622d1fac06b1`。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-uk-sportinglife-v8-apply-700a2a96-3c6a4d11-20260716_093456.dump`，`175094189` bytes，SHA-256 `a942e2dad092bdf0af9e0546030a73c75dfeebb1c89ee888d704e8244d7f0d6c`，权限 `0600` 且 `pg_restore -l` 通过。`detail-dryrun-700a2a96-3c6a4d11` 对两个 chunk 全量通过，receipt 为 0；随后 `detail-apply2-700a2a96-3c6a4d11` 完成 2/2 receipts，`detail-replay-700a2a96-3c6a4d11` 逐目标检查 `194 + 3`，两块均 `error_count=0`。
- 最终数据库验收精确为 `197 events / 2027 runners / 1794 results / 197 first-place winners`，197 个 target 均为 `imported`，basic/runners/results 均为 `complete`。197 场全部保持 `draft + incomplete + is_featured=false`，公开 0。生产累计 historical imported target/event 为 `7182`，但这不表示一期总账已经全部完成。
- apply 首次尝试 `detail-apply-700a2a96-3c6a4d11` 因 dry-run 根 checkpoint 尚未归档而在业务步骤前 fail closed，错误为 `runtime/database checkpoint mismatch`，receipt 仍为 0。完成状态文件按 run 归档后使用新 run ID 从头执行，未删除 checkpoint、未续跑不明步骤；失败 run 保留为审计记录。
- 收口时 historical runner 容器为空，preflight 为 `migration_safe`；web/worker/beat 统一运行镜像 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`、revision `700a2a961516464ecf93deb0f43a751718efaaca`。HTTP 内外 `/healthz/` 正常，常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，历史公开继续关闭。worker/beat 恢复后已开始正常新闻窗口，因此 Celery 队列不要求保持空闲；生产可用空间约 `5.1 GiB`。

## 2026-07-16 历史详情 source bundle 已正式导入生产并完成逐目标验收

- 本次按用户授权的审核基线 `943602458bd6975bff1a0bb6bb47ad8e3dde605796a10103461def91a723892a`、content `a353f2f8179432cb807601bf574039db578b265dda2bf3c9d5f9777e1c1b748f`、commit `700a2a961516464ecf93deb0f43a751718efaaca` 和 manifest `dfb86ee85b103688fe1521b07f44ee8f36669d25e85ff3ac2b580a66b38e14d9` 执行。正式 AMD64 镜像为 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`，两个独立构建 ID 一致；tree 为 `0708ce3ef34f64549dd8483c9d7400302052c79e`，source archive SHA-256 为 `20ff51d1f2d6220fba3b0a01615e5366f57605de6e579b6ab222bc70eef597d3`。镜像内聚焦回归 `30/30`、Django check 和迁移漂移检查通过，生产没有新增待应用迁移，`0032` 已处于 applied。
- 正式 bundle 固定 `4930 = 4652 complete + 278 evidence-backed gaps`，其中完整目标含 `51191 runners / 48413 results / 4652 winners`；地区分布为法国 `15`、香港 `19`、日本 `1586`、英国 `171`、美国 `2861`。截至 2024 年导入 `4351` 场，2026 当前到期范围导入 `301` 场；278 个 gap 保留在统一 gap/review ledger，不阻断本次完整目标写入，也不视为已经消失。
- 首次全量 dry-run 在第 13 个 chunk 发现 PostgreSQL 物理索引 `stable_raceevent_series_key_6e15e445` 的 tuple overlap 损坏，事务完整回滚且 receipt 为 0。先生成并校验修复前备份 `/opt/umanewsbot/backups/db/pre-raceevent-index-reindex-700a2a96-20260716_104953.dump`（`151565133` bytes，SHA-256 `43cbfb4faec810a133805f7622f306a1cf44f143891e1235924ff7e85bd48947`），再执行两次 `REINDEX INDEX CONCURRENTLY`，随后从头重跑 `detail-dryrun2-700a2a96-dfb86ee8`，20/20 chunks、4652 targets 全部通过。
- 正式 apply 前重新生成独立 custom-format 备份 `/opt/umanewsbot/backups/db/pre-detail-apply-700a2a96-dfb86ee8-20260716_110915.dump`（`151570907` bytes，SHA-256 `6c7d8f326c4c6a10f685a7be1a0625027cf6732729bcbc6904eba3aa45964b54`），`pg_restore -l` 通过且权限为 `0600`。`detail-apply-700a2a96-dfb86ee8` 完成 20/20 receipts，`detail-replay-700a2a96-dfb86ee8` 随后逐 receipt replay 20/20，最终 verifier 为 `error_count=0`、缺来源 `0`、缺日期 `0`、模块错误 `0`。
- 4652 场全部保持 `draft`、`published=0`、`is_featured=false`。其 basic/runners/results 历史模块已完整写入，但 `RaceEvent.data_quality_status` 继续为 `incomplete`，这是等待单独公开验收的产品门禁，不是导入失败；抽查草稿 URL 返回 404。常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，历史公开继续关闭。
- 生产 web/worker/beat 已统一运行上述镜像，HTTP 首页和 `/healthz/` 为 200，Celery active/reserved、Redis queue/unacked、historical runner 均为空。本次切换显式绑定 service-specific image tags 并使用 `docker compose ... --no-build`；web 重建后 Nginx 曾保留旧 upstream IP 并短暂返回 502，重启 Nginx 后恢复。收口时生产可用磁盘约 `4.5 GiB`，低于既有重型历史 crawl 的 `5 GiB` 门槛，未启动新的生产 crawler。
- batch006 及本次 4652 场均已完成，不倒退、不重跑。历史总目标尚未全部完成：remaining artifact 仍为 `28126` targets（`8857 historical hard / 18173 historical best-effort / 1096 new formal`）；下一步继续按五地区和覆盖分层推进，少量歧义与 278 个现有 gap 留到最终统一审核。

## 2026-07-16 France runner v2 单目标本地 smoke 在 preflight 安全停止

- 本次仅使用本地 Docker，固定镜像 `sha256:e55b8b08bcd5848625a8c1d0fa5abd710783ed3be6fddaf245860ccbc9e55fa8`，OCI revision 为 `d6d6f58b2b5b90301d8fa633a650df28379c09e7`；未连接生产服务器或数据库。
- 已创建独立 run root `runtime/historical_detail_crawl_runs/detail-crawl-1998-2026-v2-smoke/france` 和共享 host lock 根 `runtime/historical_detail_crawl_runs/detail-crawl-1998-2026-v2-smoke/host-locks`。France `48498` descriptor 仍把 `run`、`host_lock` 和全部 outputs 不可变绑定到 plan root 下的 `smoke/run/smoke-france-48498`、`smoke/host-locks`，与本次批准路径不一致。
- `discover` 在 launcher 的宿主 preflight 以 `mount contract mismatch for run` fail closed，发生在 `docker run` 和真实网络请求之前。按失败即停规则未运行 `cache / parse / validate / package`；请求数、缓存字节和阶段产物均为 0，无 checkpoint、request log、package manifest 或残留容器。
- 后续不得通过软链接、改写 descriptor 或改用 plan root 可写目录绕过门禁。须先由计划生成侧提供绑定上述独立 run root/共享 host lock 的新不可变 descriptor，再从 `discover` 重新开始。

## 2026-07-16 日本 runner v2 单目标本地 smoke 在 preflight 安全停止

- 本次仅使用本地 Docker，目标为 `japan / 50556`，固定镜像 `sha256:e55b8b08bcd5848625a8c1d0fa5abd710783ed3be6fddaf245860ccbc9e55fa8`，OCI revision 为 `d6d6f58b2b5b90301d8fa633a650df28379c09e7`；未连接生产服务器或数据库。
- 已创建独立 run root `runtime/historical_detail_crawl_runs/detail-crawl-1998-2026-v2-smoke/japan`，并复用同级共享 host lock 根。Japan `50556` descriptor 仍把 `run`、`host_lock` 和全部 outputs 不可变绑定到 plan root 下的 `smoke/run/smoke-japan-50556`、`smoke/host-locks`，与本次批准路径不一致。
- `discover` 在 launcher 的宿主 preflight 以 `mount contract mismatch for run` fail closed，退出码为 `2`，发生在 `docker run` 和真实网络请求之前。按失败即停规则未运行 `cache / parse / validate / package`；请求数、缓存字节和阶段产物均为 `0`，无 checkpoint、request log、package manifest 或残留容器。
- 后续须由计划生成侧提供绑定上述独立 run root/共享 host lock 的新不可变 descriptor，或经明确审批改用当前 descriptor 原路径，再从 `discover` 重新开始；不得手工修改 descriptor 绕过身份门禁。

## 2026-07-16 准实时赛事赛果 latest-main 复审通过，进入离线测试先行

- 独立 worktree `/Users/mentianlu/.codex/worktrees/97f5/umanews` 的初始 PLAN 基于 `9b617702`；离线 TDD 期间持续安全快进，当前 `HEAD == origin/main@283bacf2cdc5ff97423b50ff46cfda2a87120a2b`。本次先 stash 专项改动，再 `ff-only` 到最新主线并恢复；四份状态/决策/运维文档的顶部新增事实发生预期文本冲突，现已保留主线赛事身份/关联事实与本专项事实并清除冲突。代码仅在 `race_events.py` 的主线新增服务 re-export 与本专项追加实现处自动合并；没有读取或复用历史抓取 runtime 产物。
- 新 change 固化在 `docs/changes/realtime-race-results/`。第一批离线 TDD 已新增发布 mode resolver 与 5 项目标测试；首次原生代码 review 的 `terms_mode` 缺失 fail-closed 和状态记录两项 P2 均已修复，同一 reviewer 限定复审 `APPROVED`。5 项目标测试与 3 项相邻赛事回归共 `8/8` 通过。尚无模型、migration、队列、网络、生产或公开行为改动。
- 第二个离线 TDD 切片已对六态状态机纯函数取得真实 RED 并完成 GREEN：严格允许设计表中的 7 条边，拒绝跳级、倒退、未知状态和未批准自循环；完整准实时模块与 3 项相邻赛事回归共 `10/10` 通过，同一代码 reviewer 完整只读复审为 `NO ACTIONABLE FINDINGS / APPROVED`。审核 approved parent 为 `201ab2d8`，content manifest 为 `c515962d4e1c1f358a6f12112a50af7d4d5c9e16db0a64a671b92666dfe5c960`。尚未接入 revision、来源权限、持久化写入或 ProjectionControl。
- 第三个离线 TDD 切片已对 canonical 内容哈希取得真实 RED 并完成 GREEN：只接受严格 JSON object，mapping key 顺序无关，赛果数组顺序和事实变化会改变 SHA-256。第三轮 review 发现等价 JSON 数字会产生不同 hash 的 P2；已用新增 RED 修复 `1/1.0`、`0.0/-0.0` 归一化，并证明五种 approved phase 元数据均不进入内容 hash。完整准实时模块与 3 项相邻赛事回归共 `15/15` 通过，同一 reviewer 限定复审已关闭唯一 P2，结论 `NO ACTIONABLE FINDINGS / APPROVED`。hash 尚未接入 revision/CAS 持久化。
- 第四个离线 TDD 切片已新增 ProjectionControl 基础所有权行和 `0033` migration：现有赛事不自动建 control，显式行默认 `unmanaged`、generation 0、revision counters 1，一场一行且非法 owner 由数据库拒绝。完整 review 对模型/migration 无 finding，但发现既有 mode resolver 的 event allowlist fail-open P2；已按新增 RED 改为只有显式布尔 `True` 放行，同一 reviewer 限定复审确认唯一 P2 `CLOSED`。latest-main 上 SQLite 专项、相邻赛事和历史 chunk/receipt/import primitive 回归 `49/49`，Django check 与 migration drift 检查通过；尚未实现 revision pointer、owner transfer/CAS 或 importer 接入。
- reviewer 后续建议指出 `PositiveBigIntegerField` 仍允许显式 revision counter 0；已取得两个 subtest 的真实 RED，并在模型与未发布 `0033` 增加 racecard/result counter `>=1` 数据库约束。latest-main 组合回归现为 `50/50`，check/migration drift 继续通过，等待同一 reviewer 限定复审。
- 后续离线切片已完成 `0034` 至 `0038`：显式 LiveTracking、source/participant identity、append-only observation/revision/item/evidence、ProjectionControl 四个 revision pointer、共享 HostBudget；同时实现 owner transfer、独立 racecard/result revision allocator、全联网模式 source permission resolver、轮询窗口、短事务 claim、host reservation 和返回 checkpoint 的 owner/claim 双 CAS。reviewer 发现过期 claim 仍可提交 checkpoint 的 P1 后，已分别用真实 RED 覆盖过期 lease 与缺失 expiry：前者返回 `claim_expired`，后者返回 `claim_missing_expiry`，均零 mutation。修复后 latest-main 组合回归 `105/105`；PostgreSQL 并发验证仍待执行。
- 新一批离线控制面已按逐行为 RED -> GREEN 完成：batch due-selector、host outcome/circuit、默认关闭的每分钟 Celery selector、`poll_race_live_event_task -> race_live` 独立 route、The Racing API Free 合成 fixture contract 和 append-only observation recorder。poll task 当前明确返回 `runner_not_configured`，不会访问 DB/HTTP。reviewer 发现损坏 claim lease 可被回收、旧 host outcome 可覆盖新 circuit 后，已补真实 RED；现改为损坏 lease fail closed，并以 reservation version CAS 拒绝迟到 outcome。准实时模块 `85/85`，与 historical detail chunk/import receipt/import primitives 组合回归 `122/122`，Django check、migration drift 和 diff check 通过，等待同一 reviewer 限定复审。Compose config 因独立 worktree 无 `.env` fail closed，未读取主工作区 secret；专用 worker、真实 broker、HTTP runner、revision/pointer apply 与 PostgreSQL 并发层仍未实现。
- 独立 `race_live` worker 部署契约已按真实 RED -> GREEN 完成：普通 worker 显式只消费 `celery`，live worker 固定只消费 `race_live`，默认并发 1、prefetch 1、soft/hard time limit 45/60 秒；开发、标准生产和低成本生产 Compose 均已定义该服务，scheduler 仍默认关闭。准实时 `88/88`、与 historical detail chunk/import receipt/import primitives 组合 `125/125`，三份 Compose 配置解析通过；尚未启动真实 broker/worker，poll runner 仍为 `runner_not_configured`。
- 赛果 authority/conflict 与 observation -> revision/pointer apply 核心也已完成：supplemental 只能 provisional，official authority 必须绑定持久化且 approved 的 source identity，调用方不得提权；shadow 只更新内部 immutable revision/current pointer，切换公开时通过唯一 publication audit 单向晋级并原子重建 `RaceEventResult`。owner/claim/expiry、participant identity、replay、conflict freeze、LKG 和确认时间都在短事务门禁内。公开赛事页已区分 provisional/official/corrected/conflict/stale，且 `published_at=NULL` 的 shadow revision 不泄漏。SQLite 准实时 `103/103`、与 historical detail chunk/import receipt/import primitives 组合 `140/140`；PostgreSQL identity/apply/并发直接路径 `15/15`，`0040` 迁移往返通过。
- PostgreSQL 16 专项首次发现 nullable JOIN `FOR UPDATE` 与锁等待旧快照两层问题，现已改为只锁 control 且锁后独立读取 current revision；`skip_locked`、host reservation、同 claim 双 worker单 revision/replay 和 deferred link guards 共 `4/4`。新增 `0039` 以 deferred triggers 阻断 pointer/supersedes 跨 event、跨 kind、向前引用，并保护 revision identity；迁移正向/回退/再正向通过。临时 PG 容器仅用于本地测试，未连接生产。
- 完全离线的 TRA fixture poll runner 已端到端 GREEN：默认 disabled，只读绝对受控 root，限制 2 MiB、严格 identity/path/JSON contract，以实际文件 bytes SHA 记录 observation，执行 shadow revision 后双 CAS checkpoint；成功严格沿用有限轮询窗口并在 T+7d 后停止，失败 5 分钟重试。offline fixture 即使误设 public 也会在读取前拒绝，不得物化公开投影。准实时 `108/108`、与相邻历史组合 `145/145`；尚未连接真实 Redis broker 或 HTTP。
- 隔离真实 broker smoke 已完成：临时 PostgreSQL 16 + Redis 7 + 独立 `race_live` worker 下，selector 领取并投递 1 场，最终 `1 observation / 1 revision / success checkpoint`、claim 释放、shadow 当前结果 0；普通 `celery` queue 消息未被 live worker 消费。全部临时容器、网络、数据库、消息和 fixture 已清理；这不代表生产 broker/shadow 已启用，HTTP 仍未实现。
- Django admin 已增加 live control/tracking/source/participant/observation/revision/conflict/publication/host budget 只读观测面；所有事实与权限数据禁止直接编辑。唯一可写 action 为赛事级 kill switch，经行锁 + lock-version CAS 停用 tracking、清空 next poll/claim、递增 claim generation 使在途响应失效并写 OperationLog；真实 admin POST 已通过。manual correction 尚未开放。准实时 `113/113`、相邻历史组合 `150/150`。
- latest-main 专项与四组新增历史回归组合 `249/249`（1 skip）通过。完整 `stable` 实际运行 `1837` 项后为 `2 failures / 13 errors / 23 skipped`；在干净 `origin/main@c40a8c2b` 精确复跑同一 15 项得到完全相同结果，确认是主线日期漂移、缺未跟踪 `tmp` helper 和既有 historical runner fixture/import-path 问题，不是本专项引入。Django check、migration drift、三份 Compose config、worker 脚本语法与 diff check 通过。
- 最终 full review 的三项 finding 已按真实 RED 修复：TRA 保留 PU/F/UR/NR/DSQ/REF 客观状态；无官方名次的非完赛投影和页面显示状态而非内部顺序；生产 live worker 显式限制为默认 0.25 CPU/384M。新增 `0041` choices migration。准实时 `116/116`、latest-main 组合 `252/252`（1 skip）、SQLite 迁移至 `0041`、check/drift/Compose/diff 通过，等待同一完整-review会话限定复审。
- 设计复用现有 `RaceEvent`、runner/result 当前投影、赛事页面、Celery/Redis 和来源 parser 规范化片段；新增共享 ProjectionControl、稳定 participant、append-only racecard/result revision、六态状态机和独立 `race_live` queue/worker。历史 importer、候选、后台人工和 live apply 必须共用写入所有权仲裁，避免互相覆盖。
- The Racing API 当前官方展示 Free `£0/月`、Basic `£27.99/月`、North America add-on `£49.99/月`；Free 默认 1 req/s。官网对当日更新给出约 3 分钟、文档另述 Core 约 5 分钟且条款明确不保证，因此 plan 要求先以 Free 实测覆盖/字段/p50/p95，不先购买。
- 来源条款核对发现 Sporting Life 明确禁止 screen scraping、Racing Post 限个人非商业使用；HRN/Equibase及各地区官方页面也需要逐源许可审计。任何自动真实联网均要求对应许可门禁；未获许可的来源只可人工查漏或使用获准/合成的离线 fixture，不能以“只读 proof”绕过条款。
- 原方案与用户修正范围均已 `APPROVED`。最新主线已经把第一期 1998–2026 历史详情分母收口为 `8032 = 6534 complete + 1491 evidence gap + 7 not_due`，global verifier `errors=0`；生产 historical runner 为空、历史网络/功能开关关闭，因此“历史任务先完成”已满足，旧的 `28126 remaining` 不再作为来源 proof 前置条件。来源 proof 仍只允许只读网络且业务 DB 零写入；进入任何 shadow 前，仍须生成精确 event allowlist/ownership generation、确认无 active lease/checkpoint、绑定 source registry digest、共享 host/资源窗口和用户审核 SHA。当前继续禁止生产 live worker、tracking 初始化、业务写入、部署、采购和公开开关。

## 2026-07-15 Codex 项目工作流迁移已合并主线（无需生产镜像部署）

- Codex 原生工作流迁移已完成方案审核与代码审核，结论均为 `APPROVED`；用户在最新成功代码 review 后明确回复“确认上线”。
- 受审 feature commit 为 `55b6cebc14eef067c929b01ce3cea5515416c5ef`；PR 为 [#10](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/10)。变更已提交、推送并合并到远端 `main@96810fcc288f92b41971f4f825105732967798c2`。
- merge commit 的两个 parent 分别为原主线 `d6d6f58b...` 与受审 feature `55b6cebc...`；merge tree 与受审 feature tree 一致，实际进入 `main` 的内容未偏离审核范围。
- 发布前验证通过：fingerprint `24/24`、transition/index `10/10`、workflow contract tests `26/26`，workflow checker 与 `git diff --check` 均通过。
- 本次范围仅包括治理文档、Codex skills/agents/scripts 与历史 skill 归档；没有 Django 业务代码、runtime 配置、数据库 migration 或生产数据变化。
- 本次“上线”以仓库主线合并为验收口径：未构建或部署生产镜像，未重启、重建或迁移生产容器，也未直接修改生产。线上业务运行态不因本变更改变，因此无需生产部署动作。
- 原合并前记录中的“尚未发布”状态现已由上述 `main` 合并证据取代，不表示当前仍未发布。
- 完整发布证据与回滚口径见 `docs/changes/codex-native-workflow-migration/release_report.md`。

## 2026-07-15 batch006 本地详情冲刺进行中，生产写入暂停

- batch006 年度赛历 1061 场已全部记账：`1050 complete / 11 gap`，accounted rate `100%`、data complete rate `98.96%`。两个日本 gap 为东京大赏典需要 NAR/Oi 来源；九个美国 gap 为障碍赛、同名冲突或未举办判断，全部进入最终统一审核，不阻断其他分片。
- 日本详情已完成 `248/248`（`3704 runners / 3671 results`），美国 `241/241`（`2181 / 1885`），英国 `250/250`（`2570 / 2105`），香港 `61/61`（`660 / 645`），四地区详情均为零 parser gap。英国同名赛事先按距离筛选，香港同日赛事使用原始名与年度目录名共同匹配并按距离一对一解析；香港 61 场均有唯一官方 URL 和冠军。
- 法国详情在本地按地区内单 host 1 秒限速续跑；本检查点前 5 个分片完成 `61` 场、`530 runners / 402 results`，零跳过、零错误。重型 PDF/详情解析只在本地运行，年度源只缓存一次；剩余分片继续使用 checkpoint 跳过已完成输出。
- 多分片并发新增可选共享 host interval artifact：各 shard 保留独立请求额度，但共同文件锁保证跨容器请求启动至少间隔 1 秒；法国双 worker 实跑最近最小间隔 `1.006s`。正式 runner 显式清除此变量，避免继承宿主任意路径；当前共享限速只在共同挂载根内的本地抓取启用。
- 首次生产 France verify 在无网络、无赛事业务写入阶段触发高内存后，生产 SSH 持续在 banner exchange 超时。当前禁止在生产重跑重型解析、启动新 runner 或执行赛事 apply；只在可信主机恢复后先清理/核对旧 runner、服务镜像、数据库租约、事务、队列和 healthz，再执行轻量 verifier 与串行写入。
- 本轮 UK/HK 解析与共享 host 限速修复完成测试优先和零问题复审；请求/cache/runner 组合 `161/161`、来源/直连详情组合 `104/104`、最终完整 stable `1528/1528`（11 skip）、Python compile 和 diff check 通过。历史公开、常驻网络与常驻写入开关继续关闭。
- `main@f9e76b88` 已构建本地 AMD64 候选 `sha256:f10982238ad75f53620f42897085888870cfb827b8fea67bb60fb3baf12406c3`，tree `ec3f9fbdb60c80ea63bb09b9939d56ce3eb20c64`、source archive SHA-256 `f78dae1071c5a006527d91821cec6f424035ffc0d336a82540936aece94d831a`；镜像内 Django check、迁移无漂移和赛事专项 `104/104` 通过。该镜像未传生产、未 retag、未重启服务。
- 已生成正式详情包：日本 `248` 场 SHA-256 `936c6f9e25182c978121538c289175eb032d12bf6e01a75fb0a0d3842f762e28`、美国 `241` 场 `482fc83ebb1fd5aa28ffc25194749c13688eab6f43837cdfe5e0042b8ffd40c4`、香港 `61` 场 `c02d5d2f56c5fd04b3baf2da3fa69c3fee2d11b747d71c59f0342ed084336b31`，均 gap=0。英国 250 条 date fragment SHA-256 为 `aceaaba5a4170b0b2a6e3e21987a538b34ca7e5dd00bf2ff7a5af754b139a700`；按正式门禁须先 date apply、detail-source apply 并重导 target SHA 后再打包最终详情，不能绕过来源审批。

## 2026-07-15 batch006 年度赛历入口已部署，待生成正式分片

- `formalize-historical-batch-crawl-pipeline` 已部署生产：代码为 `main@ccfee75fdff6fab7238b19484ba0489c2848dd50`，web/worker/beat 统一运行可复现 AMD64 image `sha256:e86c2339a6e690e801df2426a5edb408cbedf4c7eddd8cfd08011ed659ef773d`，Git tree `0c8fb1d65eea121a51366584a84749c7d2e3d88f`，source archive SHA-256 `635fa8a01b5c4685c66650355938af4930d8bebc90a9ece144fd76a2f1fa0d19`。两个正式域名的 HTTP healthz 正常，Celery active/reserved 与 Redis queue 均为 0。
- 实跑 batch006 前补齐了正式年度赛历入口：tracked source catalog 展开、HTTPS/host allowlist、URL 去重、终态 partial ledger、缓存 path/size/SHA/source URL 复核、离线地区 parser、complete/gap 分母、typed recipe 与逐成员目录 checkpoint。请求与解析分 stage：crawl 仅联网不写库，verify 既不联网也不写库。
- runner 新增全局输出路径互斥与普通文件 symlink 恢复拒绝；target/source identity 禁止布尔、分数和空字符串宽松转换。全量 ledger 可服务地区×年份解析分片；共享 URL 的 target references 必须精确等于 catalog 来源 scope 的并集。
- batch006 固定身份仍为 1061 targets：manifest `62aca6ced7dcd9c7aecac510cfb65c1468ef54564d61df609cb60226d1b096e3`、selection `b9a3ad6556cfd03e9a57874bec763f75ad4c45e7642751140cb063f1d0553637`、approval `a119e3bcfd3bc8940cf8b792e246e462b405c292b77f2996739b435c9185d835`。正式年度赛历按 11 个地区×届次年 scope 执行：FR `2023=120 / 2024=130`，HK `2016=35 / 2017=26`，JP `2022=88 / 2023=138 / 2024=24`，UK `2024=196 / 2025=54`，US `2024=83 / 2025=167`。
- 法国官方来源真实 smoke 已完成：2023 `120/120`、2024 `130/130`，均 `issues=0`。France Galop 平地 programme、障碍详细赛程及固定列分组汇总均可解析；汇总只补详细赛程缺失目标，同等质量时详细记录优先，避免摘要笔误覆盖逐场日期。
- 其他地区现有离线覆盖基线为：香港 `61/61`、日本 `248/250`、英国 `250/250`、美国 `241/250`。日本缺口为 2023/2024 东京大赏典的 Oi/NAR 日期来源；美国缺口集中在 NSA 障碍赛、2025 Remsen 同名冲突、Robert J. Frankel 未举办判断和 Tokyo City Cup 日期，继续记入统一 gap 审核，不中断其他 scope。
- 最新验证：完整 stable `1524/1524`（11 skip）、年度赛历/来源专项 `118/118`（1 skip）、runner `70/70`、1250-target 性能 `3/3`、旧规格流程 `30/30`；Django check、迁移漂移、Python compile 和 diff 检查均通过。新增实现完成 4 轮 review，最终一轮无 actionable finding。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-main-ccfee75f-20260715_122039.dump`，`141448192` bytes，SHA-256 `898c9a4ab3a06847023d189aed830553cbe733bf4c8e92a4ed636dd8231fa55f`，`pg_restore -l` 通过；环境备份为 `.env.backup.pre-main-ccfee75f-20260715_122039`，旧镜像回滚标签为 `umanewsbot:rollback-pre-ccfee75f-20260715_122039`。
- 新镜像 runner provisioning、crawl 最小权限、apply 无公网出口及两步暂停/恢复 smoke 均通过；恢复时第一步没有重复执行，最终无 runner 容器、running run 或 live lock。生产可用磁盘 `7088280 KiB`，高于 5 GiB 门槛。batch006 正式网络抓取和赛事业务表写入均未启动，历史公开/常驻网络/常驻写入继续关闭；下一步按 11 个 scope 生成不可变 descriptor/shard/plan 后启动 crawl。

## 2026-07-15 historical runner 工具根补丁部署与强化 smoke 完成

- 最新 `main@c4087e6c1e66605feb44d3650039fab2e19567e7` 已部署到生产，web/worker/beat 统一运行 AMD64 image `sha256:5eb6471c8c1e96c90198e519c4d02f1b74316d6a13dbc93e9b63c0981ad22600`；Git tree 为 `95f7ba384c791e16b7f401dfca9adb744bbb4ed0`，source archive SHA-256 为 `5051285c4bc8b5daa1355eec5be433f95d7193e8302126e3bfb359309672aec7`。旧生产镜像保留为 `umanewsbot:rollback-pre-c4087e6c-20260715-0610`。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-main-c4087e6c-20260715_060549.dump`，`141446379` bytes，SHA-256 `60331b0840a98e00370f2a5c10724d2e0e9ee370724ac572be8b0cd54781e341`，`pg_restore -l` 通过；环境备份为 `/opt/umanewsbot/.env.backup.pre-main-c4087e6c-20260715_060549`。
- historical runner provisioning 已幂等通过。新镜像 crawl smoke 证明 control role 无赛事业务表写权限，apply 隔离容器可连接 PostgreSQL 但无公网出口；40 秒 step 在暂停请求后完整结束并进入 `paused`，恢复后未重复第一步且完成第二步。生产 artifact 子目录伪工具根 `/app/historical-runtime/batch-006` 被 `production runner must use the immutable image tool root` 拒绝，且拒绝发生在创建 `HistoricalBatchRun` 之前，残留 run 为 0。
- 收口时 `manage_historical_batch_runner preflight` 为 `migration_safe`，无 runner 容器、active historical run、TranslationRun started、NewsArticle translating、Celery active/reserved 或 Redis queue；web healthy、worker consumer 取消、beat 保持 `Created`。历史常驻 enabled/network 均为 false，多地区归属仍为 off，历史 published 为 0，生产可用磁盘 `7856596 KiB`（约 7.49 GiB），高于 5 GiB 门槛。
- batch006 selection 仍为 1061 场、五地区 `250/61/250/250/250`，正式网络抓取尚未启动。下一步是生成绑定 selection/manifest/image/tool SHA 的不可变审批与 runner plan，再按每个 crawl run 最多 250 次请求分片执行；不得复用 batch005 的 `tmp/` 临时脚本。

## 2026-07-15 7 月 13 日起新闻质量修复、全量重跑与生产回归完成

- “正文边界与博彩噪声”“实体识别与马名保护”“日文翻译与赛马固定格式”三类问题均已完成 旧规格流程、测试、实现、复审、部署和线上回归。最终代码 revision 为 `bdc0eeff78e111d7fa8a697cbb3557888f864fb8`，生产 web/worker/beat 统一运行 image `sha256:c975a4faf979a1f78cdb203b810d4f5726aca114175007fc01c176044f13841c`。
- 北京时间 2026-07-13 起冻结清单共 `357` 篇，其中 `343` 篇可处理、`14` 篇重复稿；可处理稿最终 `218 published / 105 pending_review / 20 ignored`。冻结清单 `343/343` 已有成功处理结论，剩余 0。用户点名的 19 篇全部为 translated + published，生产详情页均返回 HTTP 200。
- Sponichi 来源级修复覆盖 `81` 篇：`79` 篇赛马稿完成清洗、重译、实体与门禁重建，`2` 篇 BOATRACE 非赛马稿 `8264/8274` 明确 ignored；79 篇最终为 `47 published / 22 pending_review / 10 ignored`。本轮新发布 47 篇关闭 QQ 自动交付，新增 QQ delivery 为 0。
- 最终验收脚本覆盖全部 357 篇、19 篇目标稿和随机样本 `8109/8186/8263/8368/8451`，`issue_count=0`；浏览器复核目标 `8086/8212/8304/8317` 及上述 5 篇随机稿，未发现框架噪声、博彩噪声、内部占位符或错误公开内容。
- 最终源码完整 `stable 1423/1423` 通过（环境专项跳过 7），跨新闻边界、实体、日文、多地区归属和历史 runner 的组合测试 `272/272` 通过（跳过 1）；Django check、迁移漂移和 旧规格流程 全量校验均通过。未知马名重复占位继续 fail closed，重试提示只允许用“该马/其”修复省略主语，不降低发布门禁。
- 最新可恢复数据库备份为 `/opt/umanewsbot/backups/db/post-news-final-pre-unified-bdc0eeff-20260715_033227.dump`，`140310729` bytes，SHA-256 `3e93fd9dba4fb80d3b415a2f97fce1d02337054d6afeb14a725b859cf67a5a74`，`pg_restore -l` 通过。最终 Redis/Celery 队列、active、reserved、TranslationRun started、NewsArticle translating、历史 running/applying、idle-in-transaction 均为 0，`/healthz/` 正常。
- 历史常驻网络与写入开关仍为 false，多地区归属 mode 仍为 off。清理未引用镜像层后生产可用磁盘约 `3.0 GiB`，仍低于 historical runner 的 `5 GiB` 硬门槛，因此新闻任务已完成但 batch006 继续 no-go，等待独立磁盘治理。

## 2026-07-14 多地区归属 V3 首轮生产审计人工复核未通过

- 已用候选镜像对生产最近 72 小时执行新的 `all_articles` 只读审计：共 `596` 篇、全部范围完整，`27` 条主地区变化、`5` 条 `needs_review`、`0` 条锁定/缺失/漂移；端到端约 `29.36s`，不再重复执行发布门禁。159 条单审 Gold 经保守对账后有效 `156` 条，主地区准确率 `96.15%`、五运营地区相关 precision `100%`、recall `52%`，机器报告为 `qualified=true`。
- 人工逐条检查全部主地区变化和 `needs_review` 后，仍发现 7 类不可接受错标：普通英文单词马名压过美国赛事、法国赛果被冠军马来源压到英国、正文首段爱尔兰赛场被外籍马名压过、日本当前成就被未来凯旋门梦想改成法国、英国 Jockey Club 机构新闻被嵌套赛事词改成其他，以及英国赛场标题被正文中的法国历史背景压过。因此首轮结论明确为 no-go，生产 `MULTIREGION_ATTRIBUTION_MODE=off`、相关地区查询关闭，Shadow 尚未开始计时。
- 修正规则采用 precision 优先：ASCII 单词实体不再单独夺取主地区；明确赛事/赛场优先于参赛马来源；正文首段只有唯一且非歧义赛事证据时才补足标题；机构全名可屏蔽其内部完整词边界的伪赛事命中；日本稿的当前成就加“未来梦想”保持日本主地区、海外目标只作相关地区。7 个真实反例已固化为回归测试。
- 修复后专项 `117` 项通过（1 项 SQLite 环境跳过），完整 `stable 1404` 项通过（7 项环境专项跳过），真实 PostgreSQL 16 的 250 篇性能契约测试体约 `0.266s`；Django check、迁移无漂移、旧规格流程 strict/all `29/29` 通过。下一门禁是提交并构建第二候选，再重跑同一 72 小时范围并人工检查全部变化；未通过前不得进入 Shadow。

## 2026-07-14 多地区归属 V3 审计性能与 Gold 漂移修复待部署

- 生产首次 72 小时 `all_articles` dry-run 已持久化 `597` 篇候选，但旧命令在归属推断后又逐篇执行发布门禁，运行超过 30 分钟后被终止，stdout 报告为空；run `#1` 与 manifest 仍在数据库。现已将全量归属审计和发布门禁复核拆开，`all_articles` 默认只生成归属报告，默认门禁补跑范围仍保持原行为。
- 新增从持久 run 直接导出审核报告的命令，不重复执行归属推断；支持原子写入新 JSON 文件并拒绝覆盖既有证据。文章缺失或指纹漂移会进入必审清单，漂移文章不再使用旧归属结果校验新正文；candidate fingerprint 或 manifest 漂移时拒绝导出/commit。
- 159 条单审 Gold 在当前生产正文上有 `21` 条输入 SHA 漂移。对照用户原审核快照后，`18` 条满足来源 URL、标题、正文语义/长度和当前推断结论全部稳定，可保守刷新 SHA；`8230` 标题变化、`8088` 正文异常缩短、`7898` 当前推断与人工相关地区结论不同，继续阻断。新增命令只输出对账工件，不修改数据库，重复身份或既有输出目录一律 fail closed。
- 相关地区 precision/recall 现在只计算日本、中国香港、英国、法国、美国五个实际运营频道；`other` 继续保留为审计证据，但不会因系统没有第六个频道而制造假阳性。低置信度主地区变化若与人工 Gold 主地区一致，不再误计为“无依据变化”。
- France Galop 英文页面真实日期形如 `Sunday, July 12, 2026 - 19:04`；旧 parser 缺少星期前缀格式，导致新稿被标记为时间不可信。适配器已补充长/短星期格式，来源 probe 同时输出 `published_at_verified` 与证据，部署后须以真实页面确认纠正。
- 专项 `109` 项通过（另 1 项 SQLite 环境跳过）；完整 `stable 1396` 项通过（7 项环境专项跳过）；一次性 PostgreSQL 16 上 250 篇性能契约通过，测试体 `0.219s`，满足 SQL/30 秒/256 MiB 三项门槛；旧规格流程 strict/all `29/29` 通过。当前分支尚未提交或部署，生产归属 mode 与相关地区查询仍保持关闭，Shadow 尚未开始计时。

## 2026-07-14 historical runner 生产上线、batch006 selection 与资源门禁补丁

- 独立 historical runner 第一版已完成生产部署：web/worker/beat 统一运行 image `sha256:33055eb824e4166470d692206404bebbff4057df44647bd2b3029adb21c25385`、revision `8741de98c59430c040afa1ce1737e948ba14eac3`，迁移 `stable.0031_historical_batch_runner` 已应用。写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-main-8741de98-20260714_185105.dump`，`137354931` bytes，SHA-256 `f5126ea6f69dbfbc11dc40f0c85cf1dbf05a6e2c7c678e2ccf123ea46b10073e`，`pg_restore -l` 通过。
- 生产 provisioning 已创建 internal DB/egress 两张 runner 网络、最小权限 `historical_runner_control` 角色和 0600 secret 目录。`runner-smoke-20260714-1920` 已证明 crawl 业务表写入被 PostgreSQL 拒绝、apply 无公网出口、双锁冲突、40 秒 step 心跳、暂停/恢复不重复、checkpoint SHA、迁移 preflight 和普通 `--no-deps` web 更新不干扰 DB/Redis/runner 网络；smoke 容器与一次性 secret 已清理。
- batch006 selection 已在生产正式总账上生成于 `/opt/umanewsbot/runtime/historical_race_batches/2016-2025-batch-006-20260714`：共 `1061` 场，法国 `250`、香港 `61`、日本 `250`、英国 `250`、美国 `250`；与 batch002、有效 batch003、batch004、batch005 共 `1000` 个旧 target 交集为 0，香港已抓空并退出后续地区进度比较。manifest SHA-256 为 `62aca6ced7dcd9c7aecac510cfb65c1468ef54564d61df609cb60226d1b096e3`，正式总账 SHA-256 为 `ac61298f242b2c649c403eae4741771a43cdb027befef20bc75e18fe34bcbad7`。
- 正式网络抓取尚未启动。生产 smoke 后发现直接 `python_tool` 子进程未继承编排层的请求预算、source-cache 上限和磁盘底线；生产 artifact 文件系统当时仅余约 `2.8 GiB`，低于批准的 `5 GiB`。本线程在任何 batch006 网络请求前主动停止，未产生真实请求账本、source cache 或赛事写入。
- 现已在同一 旧规格流程 change 中补充资源门禁：宿主脚本与 Django 服务双重拒绝请求预算超出 `1..250`、cache 超出 `1..2 GiB`、磁盘底线低于 `5 GiB`；crawl 父进程固定 1 秒请求间隔，并把共享请求账本/cache manifest 路径绑定到当前 artifact。嵌套 AdapterRunner 保留父级路径，数值只允许收紧；请求账本和 cache manifest 的存在状态、大小与 SHA 进入顶层 checkpoint，首步前保存基线且任何失败收尾刷新身份，暂停或失败期间创建、删除、修改会 blocked；固定生产工具根只允许显式赛事工具，术语等无关联网脚本即使 SHA 匹配也会拒绝。新增用例均先证明旧实现放行。第七轮复审无 actionable finding，runner `64/64`、historical 组合 `200/200`；最终合入最新多地区归属主线后交叉专项 `208/208`（跳过 1）、完整 `stable 1417/1417` 通过（跳过 7）。完成生产磁盘治理、候选部署与强化 smoke 前，batch006 继续保持未启动，历史常驻开关与公开开关保持关闭。
- 最终组合提交 `84217c56a3c483d9ff08029729f16c11bd1f42ad` 的 Git tree 为 `61341c7e3256ec417d243a809254afd91acab6b2`，source archive SHA-256 为 `aee41ac51b5347d5a1c146074079fed49e1b23dc08518ddeef36405fe6d406af`。两个独立源码上下文的本地 AMD64 构建得到相同 image ID `sha256:2e8bd05f5c138a8dfd5d5012c5ecfc811422fef2ec3ae5cbe4ed2ed45b28b31e`，正式候选 tag 为 `umanewsbot:main-84217c56-amd64-20260714-2220`；镜像内 Django check、migration drift 和 runtime 专项 `239/239` 通过（跳过 1）。过渡候选 `82fa4a3f/sha256:01397d15...` 缺少最新归属反例修复，`sha256:119f59e3...` 的 revision 标签不是有效 Git 对象，两者均明确不得部署。镜像按设计不复制生产 Compose 静态文件，该契约测试只在完整源码树执行。当前仅待生产磁盘治理、窗口交接、候选部署和强化 smoke。

## 2026-07-14 batch006 扩容与独立 historical runner 本地实现

- 旧规格流程 change `scale-and-isolate-historical-race-batches` 已完成完整提案、两轮工程评审和测试优先实现。batch006 起标准单地区上限为 250；显式 1-249 仍合法，旧批次可继续显式传 50。selection、writer、validator、summary、manifest 和命令 JSON 使用同一 `approved_region_limit`，100 场地区领先与不可变排除 snapshot 语义不变。
- 新增 `HistoricalBatchRun`、`HistoricalBatchLock`、`HistoricalBatchRunEvent` 及迁移 `0031_historical_batch_runner`。runner 同时持有 PostgreSQL 租约和 artifact `fcntl` 文件锁，默认 30 秒心跳、180 秒租约；不同 owner 即使租约过期也不能普通启动，必须满足容器不存在、无历史数据库连接、checkpoint 一致并记录操作者/原因后才可接管。
- runner plan 只接受结构化 argv、批准命令和镜像内工具 SHA；禁止 shell。checkpoint 同时绑定 run、phase、固定镜像、plan、输入和输出 SHA，使用 `fsync + rename` 写文件后更新数据库；分叉、丢失文件或未确认的 apply step 均转 blocked。owner token 只从 artifact 外的 0600 文件读取，数据库和日志仅保留哈希或前缀。
- 原生 Docker runner 与普通 Compose project 分离：crawl 使用 egress + control-role DB 网络且不能写业务表；apply 只连 internal DB 网络且不能访问公网。容器强制 2 CPU、2 GiB、256 PID、只读根文件系统、drop all capabilities、日志轮转和 `/app/historical-runtime` 挂载，不覆盖镜像 `/app/runtime/tools`。
- 普通 deploy/rollback 已改为 preflight 后仅以 `--no-deps` 更新 web/worker/beat/nginx，不再 pull/start/recreate DB、Redis、runner 或 networks；首次 runner 建表必须显式使用 host-only initial-install 门禁，基础设施 bootstrap 另设独立确认脚本。
- 本地 runner 聚焦测试 52 项、runner+历史批次组合 118 项、加历史网络日志组合 122 项；合并最新主线后的交叉组合 194 项通过（跳过 1），完整 `stable` 1386 项通过（跳过 7 项环境专项）。真实 PostgreSQL 6 项并发/trigger 测试、Django check、migration drift、旧规格流程 strict/all 和 shell/diff 校验通过。隔离 Docker smoke 已证明 20 连接唯一 owner、40 秒 step 心跳、暂停/恢复不重复、crawl 业务写入失败、apply 公网连接失败、2 CPU/2 GiB/256 PID 与日志轮转生效；provisioning 二次执行保持幂等。
- 五轮代码 review 已闭环：前四轮共修复无界子进程输出、失败诊断缺失、任意 checkpoint 路径、文件锁失败遗留 running 租约、runner 删除 RaceEvent、crawl prepare 误写业务 `TaskExecutionLog`、stale takeover 未在宿主核验旧容器七项问题；第五轮没有 actionable finding。进程流先进入容器 256 MiB `/tmp` tmpfs，结束后脱敏写 artifact；runner prepare 改由 append-only run event 审计；接管必须由宿主脚本实际确认旧容器不存在，并以只读挂载核对固定 `runner-state.json`。提交/镜像/生产迁移与普通部署不干扰演练尚未完成，因此 batch006 尚未生成，生产历史公开及常驻网络/写入开关继续关闭。

## 2026-07-14 2016-2025 标准批次五号 250 场正式导入

- batch005 五地区各 50 场、共 250 场已完成日期、详情来源、出马表和赛果正式导入；日期 artifact manifest SHA-256 为 `0bedb2ad10d71bc3c22f11b4c42b5ee70708a50c9359b6f661739baff242c861`，详情来源 manifest SHA-256 为 `c629b5f7e6485f81b7a0a5bcc7252947eddef1a85674d124c9853828a60fcaf7`，最终详情候选 SHA-256 为 `269c65e646b11be0a1edef70c8c088e5b4b9a2b0a69527ca0efc6242cb84d6e3`。
- 日期、详情来源和最终详情三个写阶段均为 250/250；最终逐 target 验收 `error_count=0`。本批新增法国 `414 runners / 327 results`、香港 `482 / 469`、日本 `714 / 710`、英国 `489 / 433`、美国 `484 / 425`，合计 `2583 runners / 2364 results`。
- 三个写入阶段均有独立 PostgreSQL custom-format 备份并通过 `pg_restore -l`：日期写前 `pre-batch005-date-20260714_052929.dump`，SHA-256 `34ca0038ff8795929384b287ea34a7615c2a057b1d49ab10d1eaf6a161c57d2f`；详情来源写前 `pre-batch005-detail-source-20260714_055621.dump`，SHA-256 `0fbf2eb9915ed9e7f52aca515353135527772ea2c4b981cb20241c2d474999b3`；最终详情写前 `pre-batch005-final-20260714_055856.dump`，SHA-256 `82908208d5a32f751c1b7c258c54e3ac66993798d27b66ff6d1405393a10ffa9`。
- 写后生产总账为 `1291 imported / 29626 pending`，共 `13507 runners / 12167 results`；1291 个历史赛事全部保持 draft，published 为 0。写入窗口结束后 worker consumer 与 beat 已恢复，常驻历史写入和网络开关继续为 false。
- batch006 不在旧的每地区 50 场规则下直接启动。按已批准后续要求，必须先完成“每地区最多 250 场”和独立 historical batch runner 的 旧规格流程、工程评审、测试优先实现、零问题代码复审、部署与验收；公开历史赛事开关继续关闭。
## 2026-07-14 多地区归属 V3 PostgreSQL 性能达标并调整单审资格口径

- 本地独立 worktree 使用临时 PostgreSQL 16 和当前真实校准快照完成 250 篇性能验收：250 篇文章、17,474 条有效地区术语、21,240 条 alias、38,806 个索引候选、17 个实际来源。首次真实基准暴露每篇文章懒加载一次 `NewsSource` 的 N+1，五轮均为 `254 SQL`；已改为 `AttributionBatchContext` 一次预加载批次来源，并让性能测试中的 250 篇文章绑定真实来源以防回归。
- 修复后五个独立应用进程的基准均为 `5 SQL`，耗时依次为 `1.657 / 1.764 / 1.764 / 2.135 / 1.674` 秒，RSS 增量约 `49 MiB`，满足 `<=30 SQL / <=30 秒 / <=256 MiB` 门槛。性能问题不再构成当前 no-go。
- 产品口径调整为：单人审核来源必须显式保留，但单审身份本身不再自动 no-go；首发覆盖门槛为有效样本至少 150 条、五个运营地区各至少 10 条、跨地区至少 20 条。满足覆盖及全部质量/性能门槛后只获得进入生产 shadow 的资格，只有 shadow 至少观察 24 小时且全部主地区变化和 `needs_review` 完成人工复核后，才可对新文章 enforce。
- Gold Set 不以首次达标封版；新增来源、规则版本、shadow 误判和运营争议案例必须持续追加到后续版本。相关地区采用“高 precision、允许低 recall”首发策略：precision 硬门槛保持 `>=95%`，recall 从 `>=90%` 调整为 `>=50%`。当前 159 条单审 Gold Set 的最少运营地区样本为法国 11 条、跨地区 24 条，主地区准确率 `98.11%`、相关地区 precision `100%`、recall `54.84%`、过度扩散 `0%`，覆盖与质量门槛均通过，可进入 shadow。
- 线上 recall 下降代表漏标，只告警并阻止继续扩大灰度，不单独触发自动关闭；precision 低于 95%、明显错标或过度扩散超过 1% 才要求回退。生产归属和相关地区查询继续保持关闭，本轮未连接生产数据库、未部署、未修改生产配置。
- Gold 生成器与评估器现统一读取 `MULTIREGION_ATTRIBUTION_GOLD_MIN_TOTAL/PER_REGION/CROSS_REGION`，避免自定义门槛时生成结果与资格报告不一致。V3 已合并 `origin/main@9d6dec34` 的新闻实体、日文翻译和内容边界修复；组合专项 `205` 项、完整 `stable` `1321 passed / 1 skipped`。合并后 159 条 Gold 指标完全不变，仍为 `qualified=true / no_go_reasons=[]`；Django check、迁移无漂移、Python 编译、两个生产 Compose、旧规格流程 strict/all `28/28` 和 `git diff --check` 均通过。
- 上线前复核发现旧 `reprocess_multiregion_attribution_gates` 只扫描被英文术语门禁卡住的 `manual_review_required` 文章，不能满足“最近 72 小时全部主地区变化与全部 `needs_review`”的生产验收。现新增显式 `--scope all_articles`：覆盖近期全部有效文章并包含已发布稿，排除 duplicate/rejected/withdrawn/archived/ignored；不传 scope 时仍保持原门禁补跑语义。全量模式默认不截断，显式 `--limit` 时报告 `scope_complete=false`，不得作为 go/no-go 依据。
- 全量报告固定列出全部主地区变化、全部 `needs_review`、全部 `locked_skip`，并从其余文章按当前主地区为五个运营地区各做内容指纹确定性抽样；完整清单写入持久 run selectors，重复运行同一快照可复核。人工锁定文章在报告和 manifest 中均保留原主/相关地区，同时展示算法 proposed 结果。`scope/scope_complete/commit_policy` 已进入 manifest 绑定契约，截断 run 禁止提交，全量 commit 只写归属。最终定向 `41/41`、完整 `stable 1327 passed / 1 skipped`、Django/迁移/编译、两个 Compose 和 旧规格流程 `28/28` 均通过；159 条 Gold 指标不变且 `qualified=true`。生产仍为旧镜像、mode=off、相关地区查询关闭，任务 `9.3` 尚未执行。
- 修复已提交并推送远端 main `7f0827ad941452524062d478940c85bdfddf4a59`，tree `173602cd408b970b5dd9160eee1e1aba1768ce44`，source archive SHA-256 `f0217003f9c2f614fb7f0576ff00c3086b508c70b1c213614d2470e6df08179a`。服务器独立上下文 `/opt/umanewsbot-builds/main-7f0827ad-20260714-1707` 的聚合 SHA-256 为 `746271a0d97235ac800f6b65cd26a2e1c894fc75148e233cb8efb611e7899641`；AMD64 候选 `umanewsbot:main-7f0827ad-amd64-20260714-1707` 两次构建 image ID 均为 `sha256:6ad16e368d7934777a689e537c70618a6321c3466d02f304116e2f61ae2af9a1`，镜像内 41 项归属/门禁专项、Django check 和迁移漂移通过。
- 候选尚未切换。`2026-07-14 17:12 CST` 生产仍为旧 image `sha256:d3f602de...d6d791` / revision `873845da`，`news-translate-20260713-r3` 正在按 186 篇清单执行受控翻译重试，观测时完成 7 篇，worker/beat 已停。该任务会修改 72 小时文章正文和指纹，因此本会话未 retag prod、未重启、未生成生产归属 run、未改开关；待 one-off 自然退出并确认运行账本/队列为空后，才可备份、切换并执行任务 `9.3`。

## 2026-07-14 生产 DB/Redis 意外重建事故已恢复

- 北京时间 `01:22`，历史任务线程为只读查看命令帮助误用了 `docker compose run --rm -T web`，Compose 意外重建 `umanewsbot-db-1` 与 `umanewsbot-redis-1`。PostgreSQL 日志确认数据库在 `01:22:26` 干净关闭、`01:22:28` 从原数据目录启动，没有重新初始化或恢复错误；`web / worker / beat` 当时没有被重建，生产应用镜像始终为 `sha256:87c435cfc50344d0ca94f46e44d4bea97ab11361f88f7c708b6457331aee78ec`。
- 重建瞬间中断了 1 条 netkeiba 抓取和 1 条文章自动化链路，并使 Redis 中尚未消费的来源任务丢失；后续自然窗口按最大回看机制重新调度。事故任务最终明确记为 `CrawlJob#17084 failed`，`TaskExecutionLog#108765/#108772/#108773/#108803 failed`，旧 `17:15` 生产窗口统一收口为 `coalesced_to_latest_crawl_window`，不再伪装为运行中。
- 恢复过程中暴露 `stable_newsarticle_public_slug_46694cb6` 和 `uq_article_source_article_id` 索引异常，并确认故障期间产生 4 组重复 identity、共 5 条冗余文章。权威旧记录保留为 `6809 / 8089 / 8101 / 7514`，重复记录 `8324 / 8328 / 8325 / 8327 / 8329` 的快照、翻译运行、自动化日志和窗口决策已迁回权威行后删除；每次合并均写入 `OperationLog(action_type=incident_duplicate_merge)`。
- 停止 beat、停止 worker 继续取新任务并排空 active 后，对 `stable_newsarticle` 全部 17 个索引执行 `REINDEX TABLE CONCURRENTLY`，随后执行 `VACUUM (ANALYZE, VERBOSE)`。最终为 `8312` 行、重复 identity `0`、无效/未就绪索引 `0/17`、dead row `0`；索引修复后文章 `8330` 正常自动发布，未再出现索引页或重复键错误。
- 最新停写备份为 `/opt/umanewsbot/backups/db/pre-newsarticle-dedup-reindex-20260714_020918.sql.gz`，大小 `156642923` bytes，`gzip -t` 通过，SHA-256 `f37ff4835fe13d4c2a016beac433940ef995677e690711dc68ca59f42b149a9e`。较早的索引修复前备份为 `pre-public-slug-reindex-20260714_013400.sql.gz`，大小 `156320990` bytes，SHA-256 `de864deeb53ce96e1b5509b6baffdddac1779aef711954b0783aa9a4c0a6e861`。
- `02:15` 自然窗口中 17 个生产来源全部 `succeeded`，五地区发布和 QQ 窗口全部 `succeeded`，美国发布 1 篇；公网域名、`www` 和公网 IP `/healthz/` 均返回 200。worker/beat 已恢复，DB/Redis/web 健康，历史任务继续冻结到本次协调线程明确解除。

## 2026-07-13 多地区归属单审校准集完成（历史评估已由 V3 复评取代）

- 用户完成 `multiregion_gold_set_review_20260713.xlsx` 的审稿人 1 标注；因没有第二位审核人，且法国/美国等高量地区只做部分抽样，本轮按显式 `provisional_single_review` 口径固化，不冒充正式双审 Gold Set。规则为：有期望主地区的行进入校准标签，明确 `exclude` 单独保留，主/相关地区均未选择的行视为未选中并忽略。
- 250 篇候选最终得到 `159` 条有效单审标签、`1` 条明确排除和 `90` 条未选中忽略。期望主地区为日本 `46`、中国香港 `50`、英国 `30`、法国 `11`、美国 `17`、其他 `5`；带期望相关地区的标签 `24` 条。`united_state` 已规范为 `united_states`，“所有地区”已展开为五个支持地区，原始填写值均保存在规范化审计中。
- 当日实现曾把 `provisional_single_review` 固定作为 no-go；该限制已由 2026-07-14 产品决策取代。现在单审来源继续保留且不得伪造第二审核人，但达到 150 总量、五地区各 10、跨地区 20 和全部质量/性能门槛后可进入 shadow；多人审核出现冲突时仍必须裁决。
- 对生产数据库执行纯只读评估，159 篇均存在，其中 `5` 篇输入 SHA 已漂移，实际分母 `154`。当前规则主地区准确率 `81.17%`；日本 `79.07%`、中国香港 `88.00%`、英国 `82.76%`、法国 `90.91%`、美国 `81.25%`、其他 `0%`。相关地区 precision `6.90%`、recall `6.67%`，主地区有效错配 `29` 条。主要误差是实体地区压过中心赛事，以及相关地区漏判/误扩散。
- 批处理还暴露正则重复编译问题：原始 159 篇运行超过 10 分钟后中止；为术语匹配正则增加有界缓存后约 `97` 秒完成，仍高于 250 篇 `30` 秒目标，因此性能同样 no-go。评估结束后生产无残留 one-off，未写数据库、未重启容器、未修改开关。
- 最终审核与逐篇结果工作簿为 `outputs/20260713-multiregion-gold-final/multiregion_gold_set_final_20260713.xlsx`，SHA-256 `e34726d5c8130dfd716dc3bbe10f67db3dc167f55ae36ae37a7843a99e048fdb`。校准标签 SHA-256 为 `bd94b3a40642328b93fa29f3e8aa9f1680161bb2ee3455d567d15ea377eb3681`。生产 `MULTIREGION_ATTRIBUTION_MODE` 和相关地区查询继续保持关闭。

## 2026-07-13 多地区归属 Gold Set 双人标注已启动

- 旧规格流程 change `fix-france-news-freshness-and-multiregion-attribution` 的任务 `5.1` 已进入真实数据阶段。新增只读命令 `prepare_multiregion_attribution_gold_review` 生成不可变快照、盲标 CSV、中文口径说明和文件哈希清单；新增 `finalize_multiregion_attribution_gold_review` 校验审核来源、输入漂移和多人冲突。该日原始双审及 `250/40/50` 口径已由 2026-07-14 的单审可用及 `150/10/20` 首发门槛取代。
- 第一版真实审核包为 `multiregion-gold-v1-20260713`，本地路径 `runtime/multiregion_gold_review/gold-v1-20260713/`，生产只读副本路径 `/opt/umanewsbot/runtime/multiregion_gold_review/gold-v1-20260713/`。manifest SHA-256 为 `1836a9d896ca5b6e09da6da7ed07a2fb3f66f0a02f387010fe4b56475bf5c1ea`。
- 审核包共 `250` 篇，按当前文章地区分层为日本/中国香港/英国/法国/美国各 `50` 篇，覆盖全部 `17` 个生产新闻来源；`250` 个 URL 和 `250` 个输入 SHA 均唯一。时间范围为日本 `2026-05-25–2026-07-13`、中国香港 `2026-06-23–2026-07-13`、英国/法国 `2026-06-26–2026-07-13`、美国 `2026-06-24–2026-07-12`。
- 抽样使用与待测归属算法独立的宽地区关键词，只用于优先纳入困难样本，不向审核表泄露算法答案；本包有 `139` 篇疑似跨地区候选。审核包包含第三方正文，已由 `.gitignore` 排除，最终仓库只保存 article ID、source URL、输入 SHA、人工期望地区、审核角色和理由。
- 该日尚未完成两次独立人工标注和冲突裁决，因此 旧规格流程 `5.1` 当时未勾选；该状态已由 2026-07-14 的单审可用决策和 159 条 V3 复评取代。生产 `MULTIREGION_ATTRIBUTION_MODE=off`、相关地区查询与翻译自动重试继续关闭；生产 dry-run 与 Shadow 仍待执行。
- 本分支已在完成实现后快进合入 `origin/main@693db30e`。生产在本任务期间由并行历史任务切换到 `umanewsbot:main-df2732c3-amd64-20260713-1321`，image ID `sha256:27d5d51cbe2ae6d23cb99dc758da01addc2d5935504a950bbb8a2685bce2bf13`；本任务只读复核确认常驻容器健康、无 one-off 容器、归属相关安全开关仍关闭。
- 最新主线组合回归为 `1139 passed / 1 skipped`；Django check、迁移漂移、旧规格流程 change strict、全仓 25 项 旧规格流程 strict 和 `git diff --check` 均通过。macOS 全测须设置 `TMPDIR=/private/tmp`，否则未改动的历史 artifact 测试会因 `/var` 与 `/private/var` 别名产生 16 个伪错误。
## 2026-07-14 日文赛马翻译与固定格式已上线

- 旧规格流程 change `standardize-japanese-racing-translation` 已按提案、Full 工程评审、完整测试、apply、多轮 `/review -> 修复`、部署、生产回归和规格同步流程完成，并归档到 `旧规格流程/changes/archive/2026-07-14-standardize-japanese-racing-translation/`。日文普通片假名词现在以非马名固定译法进入文章级实体与翻译链路；拍卖产驹、追切计时、赛后访谈和出马表骑手未定使用字段级确定性格式；未知完整马名继续保留原文。种子术语占位符按字段守恒，恢复时只消除明确的边界重复，不会把“拍卖会会场”这类合法单字相接误删。
- `社台/Shadai`、`ノーザンホースパーク/Northern Horse Park` 和 `セレクトセール` 已在生产术语库中各自保持唯一概念；目标分别为“社台”“北方马公园”“精选拍卖会”，日英别名完整。英文马名中文目标只在中文/繁中文章中反向匹配，不再把日文普通词 `出走` 识别成英文马名 `Movin Out`。
- 最终生产 revision 为 `873845dacb1cec0353ed9b9834417a1a00cc6311`，源码 archive SHA-256 为 `2c00bf5bee4e824d5bd3cb408af942b5a255dd88f30de1b24436cab289ec3e09`；web/worker/beat 均运行 AMD64 镜像 `sha256:d3f602de4459158bc372e45bb35f3730a7be21f284dfea32de5535681bd6d791`。本地完整 `stable 1295` 项通过（另 `1` 项按设计跳过），候选 PostgreSQL 的迁移/check/漂移和关联 `84` 项通过，最终 review 零问题。
- 写入前恢复点为 `.env.backup.pre-873845da-20260714_124940` 与 `backups/db/pre-873845da-20260714_124940.dump`；数据库备份 `134234023` bytes、SHA-256 `413718143809a09686ea18710a4cd8b8f9a9f7643fb6b769cee5daf23ca485a6`，已用 PostgreSQL 容器执行 `pg_restore -l` 验证。旧镜像回滚 tag 为 `umanewsbot:rollback-pre-873845da-20260714-1254`，image ID `sha256:b14844ee027a7902db2ed22c9b310e8240dd2d84f822d2785a28799271e3a1a2`。
- 目标文章 `8304/8299/8298/8291/8290/8288/8287/8283/8276/8219/8212` 均为 `published + translated`，保留原发布时间、人工字段和 QQ 次数；指定普通词残留、内部占位符和格式错误均为 `0`。`8304` 产驹、`8291` 追切、`8219` 访谈、`8212` 骑手未定及完整未知马名逐项通过。`8287` 使用已通过全部门禁的成功 run `8613`，仅确定性修复两处“类型类型”和一处“公开级级别”，并记录 `OperationLog`；后续失败 run `8622` 未覆盖公开稿。
- 随机样本 `8337/8366/8356/8307/8367` 均已发布、已翻译且无内部占位符；`8367` 的标签和 machine tags 均不含错误的“出走”。HTTP healthz、首页、后台和 11 篇详情均为 `200`；Redis queue、Celery active/reserved 为空，近 15 分钟无 fatal/traceback。候选数据库已删除，历史写入/网络开关保持 false，历史 published 为 `0`。

## 2026-07-14 新闻实体语境判定与完整马名保护已上线

- 旧规格流程 change `contextualize-news-entity-resolution` 已完成测试优先实现及 `18` 轮 `/review -> 修复`，最终一轮无问题。文章级解析结果统一供翻译、标签、发布校验、自动马匹关联与显式重处理消费；英文人物全名及篇内唯一姓氏回指会压制内部马名，英文普通词/高歧义词需要强马名语境，日文完整未知马名会先整体占位，不再被父马、冠名或短术语拆分。
- 最终生产 revision 为 `dc1e5ec584e47ea9d28998f76454d105836b3f0a`，源码 archive SHA-256 为 `f2eec61f6d2211a76e4456f6b9cbfc3e55a5b610829162b4a68b6039aae6ffe1`；web/worker/beat 均运行镜像 `sha256:5b06821610f0d2214cb24692e58beac4ffda731ddb84674a8855b2a1d4dbb470`。本地与候选环境最终目标测试 `51` 项、完整 `stable 1249` 项通过（另 `1` 项按设计跳过），Django check、迁移漂移、旧规格流程 strict 和 diff check 均通过。
- 写入前有效恢复点为 `backups/db/pre-main-624dd5b9-20260714-071014.dump`，`133370327` bytes、SHA-256 `21cdce21f52ded3b48e7c083f2f536eb694130f71ad6a1e38e067620f817fa75`，`pg_restore -l` 通过；随机六篇重处理前另有 `pre-random-six-entity-reprocess-20260714-074604.dump`，SHA-256 `0f0876c492d80ab9d8af2bacfe3776e3de5c94642acc427523ddd25d0437cf91`。
- 目标文章 `8086/8212/8221/8283/8288/8290/8291/8309/8317/8318/8330` 已逐篇完成 dry-run、commit、重译和重新校验；`8317` 正文统一为岳品贤，`8309/8330/8318` 不再产生假马标签，`8086` 只保留真实马名多爵，指定日文完整马名不再拆分。11 篇均保持原 `published`、原发布时间和 QQ 次数，公开页全部为 `200`。
- 随机样本 `8390/8388/8386/8385/8383/8380` 在最终规则下重处理后 dry-run 无增删差异；最终 worker 自然处理的 `8393/8394` 也通过实体 dry-run 与发布校验。公网 HTTP healthz、首页、后台和目标详情均为 `200`；Celery queue/active/reserved 均为空，最近 15 分钟 web/worker/beat 无 error/traceback，历史写入/网络开关保持关闭且历史 published 为 `0`。

## 2026-07-14 国际新闻正文边界与博彩噪声修复已上线

- 旧规格流程 change `tighten-international-article-content-boundaries` 已完成提案、Full 工程评审、测试优先实现和多轮零问题 review。最终本地验证为正文边界目标测试 `27` 项、完整 `stable` `1198` 项通过（另 `1` 项按设计跳过），Django check、迁移漂移、旧规格流程 strict 和 diff check 均通过。
- 国际来源正文现在只接受可信正文选择器；未命中时显式失败，不再回退整页。Sporting Life 会移除页面框架、社交组件、推荐区、责任博彩、博彩推广、独立跳转 URL 和 `BOOK NOW` 等 CTA，同时保留赔率及赛事标题、马主等专名中的博彩公司名称；TDN 会移除编辑注、纯跳转说明、完整赛果/活动链接、`Read Today's Paper` 和含 `click here` 的行动句。
- 历史修复命令只接受显式文章 ID、默认 dry-run，commit 后记录清理规则与 `OperationLog`；同步强制重译不会改变公开状态、原发布时间或触发 QQ。翻译完整性门禁新增非空行覆盖判断，避免“日期表完整但中文自然缩短”被误判截断，同时仍拦截尾部条目缺失。
- 最终生产 revision 为 `514af8a22aec18f01cf0193344ae3b7a45c4dbc4`，web/worker/beat 均运行镜像 `sha256:954673cc74049d4b882e492ec29b072aba01aeb1a3ae440cc85415209c8a2f8a`。源码 tree 为 `b62a80cc34b2b65c47f6dd7d541c455d04a0ef5c`，archive SHA-256 为 `507b95c9b3e3ab66b67e4813b6b4814d2e4bc3d6cb2aae6abc7ad357322ad039`，双构建 `/app` manifest SHA-256 为 `2ada2d84788d048fcfd86d589762c2b159256d1a884581ac819a614aacf92aea`。
- 最终切换前备份为 `.env.backup.pre-main-514af8a2-20260714-051127` 和 `backups/db/pre-main-514af8a2-20260714-051127.sql.gz`；数据库备份 `158552943` bytes、SHA-256 `9fc72efba29ee8d32c9709665809d259ca49e47a217c43626c99b084d99d4b0a`，`gzip -t` 通过，旧镜像回滚 tag 为 `umanewsbot:rollback-pre-514af8a2-20260714-051127`。
- 文章 `8086/8267/8316/8318` 均已按保存 HTML 离线修复并强制重译，继续保持 `published`、原 `published_to_web_at` 与 QQ delivery `0`；公开详情全部返回 `200`。生产随机抽检 `8306/8311/8326/8331/8336` 后又修复并重译存量旧解析结果，五篇保存正文与当前重解析逐字一致、解析状态均为 `ok`、噪声标记为 `0`；已发布样本 `8326` 保持原发布时间 `2026-07-13T17:47:04.152562Z` 且 QQ delivery `0`。
- 部署后 migrate 无待应用迁移，Django check、内外 `/healthz/`、首页、后台登录和目标公开页面均为 `200`，web/worker 日志无异常。beat 已恢复，Celery active/reserved 均为空；生产写入窗口随后由历史 batch005 完成使用并正常归还。

## 2026-07-14 2016-2025 标准批次四号 250 场正式导入

- batch004 五地区各 50 场、共 250 场已完成日期、直接详情来源、出马表和赛果正式导入；日期 artifact manifest 为 `30ff2c0fe14e4d6ce7d9ee7123d882d99838853e381627b552b9b0ac19dd2ea0`，详情来源 manifest 为 `cf5bfdc1cc8c6c82732d6485e1815f582a47d057010e4d1c0214ec3103fd46a8`，最终详情候选 SHA-256 为 `ddd1f8256cef0b17aabc33ea66f7a0638a2d6498c2d23342daff8835b10a5156`。
- 日期 apply、详情来源 apply 和最终详情 apply 均为 250/250。正式详情新增 `2563 runners / 2311 results`；500 个模块候选全部为 `applied`，逐场马号与名次唯一性、module 状态和 250 条导入日志一致。250 场保持 draft，published 0。
- 来源分布为 JRA 官方 50、HKJC 官方 50、NSA 官方 1、Sporting Life 50、ZEturf 50、Equibase 49。NSA `target_id=74171` 的官方 PDF 不提供马号，因而该场 8 条 runners 与 7 条 results 的 `horse_number` 为空；姓名、骑手和名次完整，作为非阻断来源格式例外进入最终统一审核。
- 226 个 target 的 `module_statuses.term_gaps` 记录了术语库暂缺中文映射；原文赛事数据已经完整导入，这些翻译缺口不改变 imported 状态，也不阻断后续批次，统一留到正式总账数据收集完成后的审核与术语补全。
- 详情来源写前流式备份 `pre-batch004-detail-source-apply-20260714_031200.sql.gz` 在进程尚未结束时曾被中途检查并报截断；进程完成后文件为 `128991200` bytes，`gzip -t` 通过，SHA-256 为 `dbe05660aaae9e1957c21b84d714c3340a81a3a59aedef4dcf5f99caae5509e5`，现为有效恢复点。最终详情写前另有更靠后的 PostgreSQL custom-format 备份 `/opt/umanewsbot/backups/db/pre-batch004-detail-import-20260714_0325.dump`，大小 `129830849` bytes，`pg_restore -l` 通过，SHA-256 为 `e50bd095bfa141ea0f05bf77fda68a508808dcddac4cbacb8fdb4ce3860e758a`。
- 写后生产累计为 `1041 imported / 29876 pending / 0 ready`，本批 250 场合计 `2563 runners / 2311 results`；全体历史 published 仍为 0。常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，无 one-off，三个公网 healthz 均为 `ok`。
- batch005 生成必须等待包含 `main@614f810e` 已耗尽地区进度门禁的可复现 AMD64 镜像完成生产切换；历史线程不得自行重建或重启生产。

## 2026-07-13 2016-2025 标准批次三号 250 场正式导入

- batch003 五地区各 50 场已完成日期、带原单位距离、实际场地、详情来源、出马表和赛果正式导入，新增 `2638 runners / 2349 results`；写后累计为 `791 imported / 30126 pending / 0 ready`、`8361 runners / 7492 results`，全部 draft、published 0。
- 2025 Hampton Novices' Chase 按同届移师处理为 `2025-01-19 / Windsor / 3m53y`，3 匹出走、3 条赛果，冠军 `Jingko Blue`；Warwick 原定场次 `ABANDONED` 只保留为变更证据，不构成年度取消或缺口。
- 最终详情候选 SHA-256 为 `426af99cf541b43aa2e73e839989de40f2d2a15ab6298cda4cec4026cafe0a59`。日期、权威字段、详情来源和最终详情四个写阶段均有独立门禁与备份，逐 target 验收 error 0。

## 2026-07-14 已耗尽地区不再冻结历史标准批次

- 既有地区进度护栏会把五地区永久放在同一比较集合；当中国香港等低容量地区已经没有可选目标时，仍会以其较低 accounted 数阻止英国、美国等高容量地区继续推进，与 1998–2026 正式总账全量完成目标冲突。
- 标准批次现在只比较“本批选择后仍有未排除可选 pending due 目标”的地区。地区抓空后退出领先比较；仍未完成地区之间继续严格执行 100 个标准目标上限，101 拒绝、100 放行。
- selection snapshot 显式排除的待审目标继续保留在 `available/remaining pending`、总账分母和缺口账本中，但不把只有待审排除项的地区视为仍可抓。artifact summary 新增 `eligible_pending_by_region` 和 `progress_guard_regions`，明确记录放行依据。
- 旧规格流程 增补已完成 Full 工程评审；新增回归先在旧实现上失败，修复后历史批次专项 `66` 项和完整 `stable 1171` 项通过（另 `1` 项按设计跳过），Django check、迁移漂移、旧规格流程 strict、diff check 和最终代码 review 均通过。代码已合入 `main@614f810e`，尚未部署；生产历史写入/网络和公开开关不得因此开启。

## 2026-07-13 后续标准批次重复选样门禁已实现

- batch002 写后生成旧 batch003 时，4 个仍为 pending 的已交代 gap 再次进入选样：英国 Classic Handicap Chase、Dick Poole Fillies Stakes，以及美国 Brooklyn、Cougar II。该工件与 batch002 重叠 4 条，视为无效，不得审批或进入抓取。
- `build_historical_race_band_batch` 已增加可重复 `--exclude-selection-snapshot`。命令校验旧快照 schema、inventory SHA、内部 snapshot SHA、target 数量/唯一性和稳定身份，在地区 limit 前排除旧 target，并把输入原字节复制到新 artifact、以固定键写入 manifest 文件身份。
- 排除只影响本批选样：被排除 gap 继续保持 pending，仍计入 `available/remaining pending`，不计入 accounted/imported，也不修改 held/not_held/cancelled 口径。旧目标已导入导致当前 target SHA 改变时，只要 series/year/region/inventory 稳定，历史快照仍可作为排除证据。
- 42 项批次与日期发现聚焦测试、完整 `stable 1157` 项回归、Django check、迁移漂移、旧规格流程 strict/all 和第二轮代码 review 均通过。batch002 真实 250 目标快照已通过新读取器；该门禁后续已经提交并用于 batch003/batch004，公开展示和常驻历史写入/网络开关保持关闭。

## 2026-07-13 2016–2025 标准批次二号 246 场正式导入

- 生产已使用可复现主线镜像 `sha256:77eb11385d1d23843d2e2bae96bc5b4da4453732edb567d46cb0cc0fb01c3da0` 完成第二标准批次。日期 artifact manifest SHA-256 为 `9ed3b7138012b4ce1732cf1f071d13cb16678a97983ea63d94329fe84c902e68`，批准 246 场、保留 4 个显式 gap；日期 apply 246/246 成功，目标由 pending 变为 ready，并生成 246 个 finished/draft 年度赛事。
- 详情来源 artifact manifest SHA-256 为 `ae9d20aa62062e62a0bc8561e69b2cd06493b2d3eab50e175a82913d077b44d9`，来源分布为 JRA 50、Equibase 48、HKJC 50、Sporting Life 48、ZEturf 50。只读 check 246/246 通过，来源 apply 246/246 成功；来源写入后重新导出 event input 并生成最终详情候选，候选 SHA-256 为 `735ec0dacafd9c388adb678b93ab402e45f991cb0e143c89a6fe067e606fc459`，246 scopes / 0 gaps，生产 dry-run 全部通过。
- 三道写前备份均通过 `gzip -t`：日期 apply 前 `pre-band-2016-2025-batch002-date-apply-20260713_164248.sql.gz` 为 `150494499` bytes、SHA-256 `379f86de4408ff0a66dbdee200514a56a53a10404b579c49a3fb13462541b7c7`；详情来源 apply 前 `pre-band-2016-2025-batch002-detail-apply-20260713_165007.sql.gz` 为 `124141632` bytes、SHA-256 `0b0423aee6ffbe4094a71c3ff533e47538f1ccb8b3a918aa3d07863b76809540`；最终详情导入前 `pre-band-2016-2025-batch002-candidate-import-20260713_165304.sql.gz` 为 `124218014` bytes、SHA-256 `a22967b6e0574faab9ae865d908f69474234dfff862092025471cf7eff660545`。
- 正式详情导入 246/246 成功，新增日本 `730 runners / 722 results`、美国 `468 / 406`、香港 `463 / 453`、英国 `464 / 417`、法国 `424 / 328`，合计 `2549 runners / 2326 results`。写后逐场核对 candidate 数量、马号唯一性、名次唯一性、applied candidate 来源名/URL、target module 状态和 draft 可见性，error 0。
- 生产历史累计为 `541 imported / 30376 pending`、`5723 runners / 5143 results`，materialized events 为 541，published 为 0。本批 246 场仍全部 draft；4 个 gap 继续保持 pending，未把 `ABANDONED` 或 `not run` 自动改成产品总账结论。
- 常驻 `.env` 和运行中 web 均保持 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`；web/worker/beat 镜像未变化，无遗留 one-off 容器，内外 HTTP healthz 正常，近 30 分钟日志错误扫描为空。历史前台展示继续关闭。

## 2026-07-13 2016–2025 标准批次二号详情证据门禁

- 第二标准批次 250 个目标已完成五地区详情来源发现。当前可直接进入日期工件的证据为 246 场：日本 50、美国 48、香港 50、英国 48、法国 50；246 个来源 URL 全局唯一，来源缓存逐文件大小和 SHA-256 可核验。详情解析合计日本/美国 `1198 runners / 1128 results`、香港 `463 / 453`、英国 `464 / 417`、法国 `424 / 328`。
- 4 个目标继续作为显式缺口保留：美国 Brooklyn Stakes 和 Cougar II Stakes 的 2025 届有 TOBA `not run` 证据，等待产品结论；英国 Classic Handicap Chase 和 Dick Poole Fillies Stakes 的 2025 结果页标记 `ABANDONED`，在正式取消证据修正总账前不得按 held 导入。
- 首次生产只读 artifact 构建为 `219 candidate / 31 gap`。除上述 4 个预期缺口外，15 个香港目标缺少赛季年度与实际自然年的跨年说明，12 个英国目标被 `2m4f`、`3m21/2f` 等紧凑英制距离写法误判。香港 provider 已显式写入 `actual_year` 和 `hong_kong_racing_season_spans_calendar_years`；英制解析器已按测试优先支持紧凑 mile/furlong/yard 组合和粘连分数，同时保留来源原文。
- 距离修复专项先失败后通过，完整 `stable` 回归为 `1149` 项通过、`1` 项按设计跳过；`git diff --check` 通过，最终代码复审无 actionable finding。当前尚未把本轮修复部署到生产，也未批准或提交二号批次日期 artifact；生产仍为历史 `295 imported / 30622 pending`、`3174 runners / 2817 results`、全部 draft、published 0，常驻历史写入和网络开关保持 false。

## 2026-07-13 2016–2025 标准批次二号应到与日美来源发现

- 由于 2016–2025 年代带仍有 pending 目标，按 旧规格流程 年代带门禁继续本年代，不提前跳到 2006–2015。生产总账生成第二个标准批次 250 场，五地区各 50；生成前各地区 accounted 均为 53，生成后领先差仍为 0。selection snapshot 内部 SHA-256 为 `fdd297a8c76cca529634128c11c59ea6ed4cf216b13e574a012d5fd35557629b`，manifest 文件 SHA-256 为 `b4db68f36e2ec378b7dffc9f8c8d2286d3cf4d4138499f2eb4fef86c8d3152f8`，审批文件 SHA-256 为 `b2650665588758c9e43cae3f80db30fe7c0f8287657cea468f728b9baf1fd6c2`。
- 批次审核为 250 个唯一 target、250 个唯一地区/年份/系列组合，核心身份字段无空值，同地区同年无重名；全部继承自已批准总账。年份分布为法国/日本/英国/美国各 50 场 2025，香港为 2024 年 9 场、2023 年 31 场、2022 年 10 场。
- 复用已缓存 JRA 与 TOBA 2025 年表做零网络离线发现。修复 JRA 五个障碍/赞助名称别名、TOBA 核心限定词串场和同 URL 双 target 后，得到日本 50、美国 48 个候选，共 98 个全局唯一 URL；候选 SHA-256 为 `bff176ca9b55ca11a8a5200c1f27a02e3f14e160877dac79e1092d5409f0560e`。
- TOBA 权威年表将美国 `Brooklyn Stakes`（target 74077，BAQ）和 `Cougar II Stakes`（target 74108，DMR）明确标为 `not run`。工具只输出 `source_reports_not_run` 审核证据，不自动改总账；两条由产品审核决定是否从 `held` 改为 `not_held`，其余 248 场可继续独立推进。
- 技术修复按测试优先完成，109 项历史专项与完整 `stable` 1141 项通过，1 项按设计跳过；旧规格流程 strict、编译和 diff 检查通过，修复后重新 review 无剩余可修问题。历史公开展示和常驻网络/写入开关继续关闭，尚未对本批执行生产网络抓取或数据库写入。

## 2026-07-13 2016–2025 标准批次法港英 150 场正式导入

- 法国、香港、英国各 50 场的基础字段先经独立权威字段 artifact 校正。evidence manifest SHA-256 为 `d6f6e29a7243b2d709ef117a85fb315d2067b60870e6d72145dc81d0ab6a2857`，候选 SHA-256 为 `59acc224101cccf1a4b98dfc2e64173bbbf81406027b8ecd269871e643cf50ac`；生产 dry-run 精确得到 150 个 scope、164 个字段，其中距离 150、场地 8、surface 6，人工锁跳过 0。
- 字段写入前备份 `backups/db/pre-fr-hk-uk-field-corrections-20260713_134732.sql.gz` 为 `148521701` bytes，SHA-256 `30dc58d2d7f7eb099dfebf7ebf059e13f28aee13b5b0bd69b41bbe5cdd6c94ce`，`gzip -t` 通过。原子 apply 后 150 个 target SHA 全部改变，164 个值和字段 provenance 逐项一致，150 条目标日志和 1 条批次日志齐全；常驻历史写入/网络开关仍为 false。
- 旧详情候选 `38e05d7786fcfa5adf91eee19dc08d3eb86c55f8cc5a29a86bead32b6f771950` 已在生产因 `historical target changed after candidate approval` 被明确拒绝。重新导出并打包的新候选 SHA-256 为 `a8fc8fbf94c5a90e0d62be6f8727c38cbbcd14577c1894d8869d9974b33368da`，150 场、0 gap、150 个全局唯一详情 URL，正式 dry-run 全部通过。
- 详情写入前第二份备份 `backups/db/pre-fr-hk-uk-detail-import-20260713_135954.sql.gz` 为 `148554120` bytes，SHA-256 `610c540758ac0665342d219841ee91592bc36f5f0641ed2f263eec507250f4db`，`gzip -t` 通过。正式 apply 150/150 成功：法国 `449 runners / 330 results`，香港 `515 / 506`，英国 `570 / 458`；合计新增 `1534 runners / 1294 results / 300 applied candidates` 和 150 条导入日志。
- 写后验收 error 0：每场 runners/results 与候选完全一致，马号和存储名次无重复，candidate source name/URL/cache identity 均匹配批准证据，target 全部 imported、module 状态完整。生产历史累计为 `295 imported / 30622 pending`、2026 年前 `295` 场且全部 draft，历史 runners/results 为 `3174 / 2817`，published 为 0。
- 150 个详情 source cache 共 `38383091` bytes，生产逐文件大小和 SHA-256 `150/150` 通过。数据库约 `850877463` bytes；Django check、内外 healthz、容器和 web/worker/beat 日志均正常。历史公开展示继续关闭，本批未改变新闻或公开页面开关。
- 写入后的 14:00 CST 自然窗口验收通过：17 个抓取窗口、5 个发布窗口、5 个 QQ 推送窗口均 succeeded；抓取处理 470 条、产生 5 条新稿、失败 0。发布与 QQ 均为门禁解释明确的正常零产出，分别是 `hard_gate_blocked` / `no_ready_candidates` 和 `already_sent` / `no_eligible_articles`，失败文章与失败投递均为 0；随后内外 healthz 正常，web/worker/beat 近 20 分钟错误扫描为 0。

## 2026-07-13 权威字段门禁固化与可复现镜像切换

- 权威字段批次门禁源码、测试、旧规格流程 与运行文档已提交为 `df2732c3b8ae47619728c52f54a95204f5d6b574`，历史分支和远端 `main` 同步快进；提交前完整 `stable` 回归 `1136/1136` 通过，1 项按设计跳过，最终代码 review 无待修问题。
- 生产从干净 detached worktree 构建 `umanewsbot:main-df2732c3-amd64-20260713-1321`，两次构建 image ID 均为 `sha256:27d5d51cbe2ae6d23cb99dc758da01addc2d5935504a950bbb8a2685bce2bf13`；架构 `amd64`，revision `df2732c3...6b574`，Git tree `d2ce464b80ec595f82dc19a531c982429bb639af`，已提交源码归档 SHA-256 `441eb2acb5c061aae5d22671e82ddccfafb2cb08af62711b030c0031354d8d5d`。
- 切换前停止 beat 并等待 worker active/reserved 清空；外部导入、术语重处理、多地区归属 live lock 均为 0，无 one-off 容器。`.env` 备份为 `.env.backup.main-df2732c3-20260713_132757`；数据库备份 `backups/db/pre-main-df2732c3-20260713_132757.sql.gz` 为 `148455898` bytes，`gzip -t` 通过，SHA-256 `87cc176658cd2e57fa72c703bc1446e1e1930147a875d82cfccab7470d964776`。旧镜像回滚 tag 为 `pre-main-df2732c3-20260713-1327`。
- 新镜像连接生产数据库执行 migrate 无待迁移，Django check、迁移漂移和新命令 help 均通过；随后重建 `web / worker / beat`。三容器统一使用 `sha256:27d5d51c...bf13`，web healthy，`stable.0029`、64 个模型、历史新命令和静态资源正常。
- 安全状态保持不变：历史回填/网络常驻开关 false，多地区归属 mode off，相关地区查询、翻译自动重试和失败邮件 false；生产仍为 `145 imported + 150 ready`、2026 年前赛事 `295`、历史 published `0`。本轮没有执行权威字段或详情生产写入。
- 内外 `/healthz/`、五地区首页筛选、赛事页、马匹页和后台均返回 200。切换后的 `13:30` 自然窗口中 5 个到期来源全部抓取 succeeded，五地区 publish/QQ 窗口全部 succeeded，日本正常发布文章 `8238`；web/worker/beat 日志无 traceback/error/constraint 异常。

## 2026-07-13 历史源码固化与可复现生产镜像切换

- 历史赛事全部保留能力已提交并推送，分支与远端 `main` 均已快进到 `304ebdb67562e655929d263a3af98b8f17905752`。源码完整 `stable` 回归为 `1128 passed / 1 skipped`，旧规格流程 strict、Django check、迁移漂移与 diff check 通过。
- 生产最终已切换到从干净已提交 `main` 两次一致构建的 AMD64 镜像 `umanewsbot:main-304ebdb6-amd64-20260713-1230`，image ID 为 `sha256:e7ab7af0061d7362ad0582224baffc79eda07bd6d8f6467bfa573f760853877d`，Git tree 为 `5dfef5c7d219e63cd0b156071c89508cb42543ce`，context SHA-256 为 `a77a271cde3d0d06e25f9075036de5fc99415e832f2da052c84bf40bf956a7b5`。旧组合镜像已保留为回滚 tag `pre-main-304ebdb6-20260713-1240`。
- 切换前数据库备份为 `backups/db/pre-main-304ebdb6-20260713_123828.sql.gz`，大小 `148091210` bytes，SHA-256 为 `f61038e6a9e015f0eb0d59288029903911ebd55ed1acf600eabfb15a4c6ee126`，`gzip -t` 通过；`.env` 备份为 `.env.backup.main-304ebdb6-20260713_123828`。生产遗留的未跟踪旧版 `package_historical_race_detail_candidates.py` 已按原 SHA 保存在 `runtime/deploy/pre-main-304ebdb6-20260713_1239/`，由正式跟踪的新版接管路径。
- 切换按单一生产协调流程执行：停 beat，等待唯一术语发现任务自然结束，确认 Celery active/reserved、外部导入、归属与术语重处理锁均为 0；新镜像 migrate 无待迁移，Django check 和 `makemigrations --check --dry-run` 通过后重建 `web / worker / beat`。
- 上线验收：三个应用容器均使用 `sha256:e7ab7af0...877d`，`stable.0027–0029` 均已应用，64 models 加载正常，历史日期/批次/详情管理命令可用。归属、相关地区查询、翻译自动重试、失败邮件和历史网络/公开开关均继续安全关闭。历史 target 为法国/香港/英国各 `50 ready`，历史公开数为 0。内外 healthz、首页、五地区筛选、赛事页、马匹页与后台跳转均通过，最近日志无异常，新容器后的自然生产窗口无失败。“运行镜像不可复现”风险至此已解除。
- 新镜像后的北京时间 `12:45` 自然窗口已收口：当轮到期的 8 个抓取窗口全部 succeeded，五地区发布和 QQ 窗口全部 succeeded。netkeiba 新着顺读取 `116`、新增 `4`，文章 `8225–8228` 均已翻译并进入 `publish_ready`，未再出现 schema 约束错误。

## 2026-07-13 组合镜像恢复后三窗口只读验收

- 本次以北京时间 `11:15 / 11:30 / 11:45` 三个生产窗口为验收对象，并追加观察 `12:00` 窗口。该次验收时 `web / worker / beat` 统一使用临时 AMD64 组合镜像 `sha256:383a36c1...c7b4`，容器健康，最近 90 分钟日志未发现 traceback/error/critical/exception，也没有超过 30 分钟的 ProductionWindow 卡死。该镜像已由上述可复现主线镜像替代。
- 抓取主链路已恢复，但尚不能记为“完全正常”。`11:15` 为 `8 succeeded + 9 coalesced`，`11:30` 为 `9 succeeded + 8 coalesced`，`11:45` 的 17 个已启用且生产批准来源全部 succeeded。追加观察时，`12:00` 为 `10 succeeded + 6 coalesced`，同一批 6 个来源已在 `12:15` 成功抓取，证明合并不只是重建后追赶，也是当前调度算法的常态。来源以 `last_crawl_at` 滚动到期、beat 每 5 分钟检查，因此实际间隔约为 15–20 分钟，单个 15 分钟 bucket 不保证固定出现全部 17 条来源记录。
- 三窗口的抓取结果为日本新增 `9`，其他四地区来源均成功返回列表，但候选全为已入库重复稿，所以无新稿；不是来源失效或抓取报错。发布窗口全部 succeeded：`11:15` 日本发布 3 篇，`11:30` 日本发布 2 篇，`11:45` 因硬门禁/翻译等待发布 0 篇；其他地区均为 `no_ready_candidates`。QQ 窗口无失败，本时段实际成功交付 1 条，其余均有 `no_eligible_articles / already_sent` 明确原因。
- 尚存三类问题：文章 `8208` 为可重试 timeout，但生产 `TRANSLATION_AUTO_RETRY_ENABLED=false` 且到期后未自动重试；新稿 `8211 / 8215` 因 `Translation response appears incomplete` 被分类为 `unknown` 并停在 `translation_failed`，同样不会自愈。JRA 来源每轮还会跳过 `060302.pdf` 一条解析异常，来源整体仍成功。数据库另有 28 条历史 `CrawlJob(status=started)` 脏记录，最新一条为当日 `07:20`，它们没有对应运行任务、不阻断当前窗口，但会干扰运营观测。
- 结论：镜像/schema 不兼容造成的新闻写入故障已解除，抓取、发布、QQ 和 HTTP 主链路正在运行；但需先处理翻译失败自愈口径、JRA 固定 PDF 跳过和历史卡死记录，并明确是接受滚动 15–20 分钟口径还是改为对齐的严格 15 分钟调度，才能宣称“完全正常”。

## 历史状态记录

`2026-07-13` change `fix-france-news-freshness-and-multiregion-attribution` 已完成当时版本的本地实现与三轮 review/返修。TDN 法国入口、France Galop 时间证据、翻译恢复、多地区归属运行账本和灰度控制均已实现。该段原记录的“双审 250/40/50”Gold 门槛已由 2026-07-14 决策取代：现有 159 条单审 Gold Set 达到 `150/10/20` 首发覆盖和全部质量门槛，可进入 shadow，但生产 dry-run、至少 24 小时 shadow、全量变化复核、仅新文章 enforce 和相关地区查询灰度仍未完成，不得直接开启相关地区查询或归档 change。

`2026-07-13` 旧规格流程 change `fix-france-news-freshness-and-multiregion-attribution` 已完成两轮完整工程评审并进入 `reviewed` 阶段，共收敛 11 个架构、测试、性能和一致性问题。方案锁定：TDN 改用日期倒序 posts 查询；France Galop 保存 verified 详情时间且 fallback 不覆盖；瞬时翻译错误最多 3 次退避重试且默认不开自动调度；归属使用 `off|shadow|enforce` 单一模式，相关地区查询独立灰度；归属 dry-run/commit 使用持久 run、独立可续租锁、manifest、断点续跑和幂等保护。该日原评审口径要求双审、`250/40/50` 覆盖和 related recall `>=90%`，已由 `2026-07-14` 决策修订为单审可用、`150/10/20` 首发覆盖且 recall 首发线 `>=50%`；precision、准确率、扩散和性能门槛不变。灰度顺序仍为代码部署且 mode=off、shadow、仅新文章 enforce、网页/测试群相关查询、近期 72 小时回填、正式群。

`2026-07-12` 法国新闻新鲜度与低产出专项只读排查已完成，本次未修改代码、配置或文章状态。线上三个法国来源都在按有效 15 分钟频率成功轮询，但存在四个独立阻断：一是 `tdn_france` / `tdn_france_broad` 使用 WordPress `/wp/v2/search`，该接口按相关度返回固定历史结果而非按日期倒序，来源 `#21` 每轮因此正确过滤 `80` 条旧文却漏掉最新稿；实测改用 `/wp/v2/posts?search=...&orderby=date&order=desc&after=...`，`2026-07-09` 以来 11 组法国宽关键词可得到 `12` 篇去重候选，其中包含 `2026-07-11` Grand Prix de Paris 调时和 `2026-07-09` France Galop 预算稿。二是 `FranceGalopEnglishNewsAdapter` 列表阶段用 `timezone.now()` 作为发布时间，详情页未解析页面真实时间，重复抓取还会覆盖 `NewsArticle.published_at`；线上 `7871/7699/7031` 的官方真实日期分别为 `2026-07-11 / 2026-07-10 / 2026-07-05`，但数据库时间被刷新为最近轮询时间。三是最新 France Galop 稿 `7871/7699` 已抓入库，却分别因翻译供应商 `503/429` 停在 `translation_failed`，当前没有周期性失败翻译重试，`translation_retry_count=0`。四是生产 `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`，全球 TDN 最新流中的法国稿仍按来源默认记为美国，例如 `7872` Grand Prix de Paris 调时稿已入库但主地区为美国。推荐改造为：TDN 直接使用按日期倒序且带 `after` 的 posts 搜索；France Galop 解析正文官方时间并禁止 fallback 时间覆盖可信发布时间；对 `429/503` 增加有上限和退避的自动翻译重试；完成多地区归属复核后开启相关地区查询，使全球来源法国稿同时进入法国池。3 天新鲜度门禁应保留，不应通过提高上限掩盖入口排序和时间可信度问题。

`2026-07-12` 已对英文术语门禁重处理结果执行受控发布。按香港 run `#7`、英国 `#8`、美国 `#10`、法国 `#11` 的 manifest 锁定提交后，共恢复 `24` 篇候选；自然发布窗口在北京时间 `18:30` 发布 `18` 篇、`18:45` 发布 `6` 篇，QQ 因 `high_value_only` 策略均返回 `no_eligible_articles`，没有产生交付。发布后复核发现法国 `NewsSource#21 / CrawlJob#9408` 属于 `fix-tdn-france-search-date-freshness` 上线前的受污染库存：其中本次公开的 `7250/7256/7259/7261/7268` 官方真实日期分别为 `2026-06-23 / 2022-03-08 / 2020-04-27 / 2020-04-27 / 2017-03-29`，均不满足抓取时 3 天新鲜度要求。已在新备份 `backups/db/pre-term-gate-stale-cleanup-20260712_185347.sql.gz`（约 `100M`，gzip 校验通过，SHA-256 `a16f85f74d2d1d9de44debbf54f1bf096cff2ad2ce0a17f448ba259e6738a118`）后，将 `CrawlJob#9408` 全部 `20` 篇标记为 `withdrawn`、清空公开时间并写入批次清理原因，防止剩余待审核旧文再次被补跑复活。最终合格公开文章为香港 `7`、英国 `3`、美国 `9`，合计 `19` 篇；5 个旧文详情已从公网撤回，QQ 误推送为 `0`。生产仍保持 `ENGLISH_TERM_CONTEXT_MODE=shadow`，本次仅在锁定 commit 命令中临时使用 `enforce`，未改变常驻服务模式。

`2026-07-12` 旧规格流程 change `fix-english-term-context-gates-and-reprocess-performance` 已部署生产并进入 `shadow` 灰度，生产 HEAD 为 `f221c7df`。新增迁移 `stable.0028_term_gate_reprocess_runs`、只读运行后台、`off|shadow|enforce` 单一模式和带 run ID/manifest 的受控重处理；当前 `web/worker/beat` 均为 `shadow`，旧门禁继续决定自然流入文章状态。部署前备份为 `.env.backup.english-term-context-20260712_171023` 和 `backups/db/pre-english-term-context-20260712_171023.sql.gz`（109M，`gzip -t` 通过，SHA-256 `8f1cb6d3380db6c92671348d60a1c1d1633939bc637a38bcc2bdc796116486e1`）。生产 100 篇美国候选最终基准 run `#6`：7.53 秒、SQL 19 条、RSS 增量 36,503,552 bytes，术语索引 1 次，赛事实体/英文 alias/额外马名术语/重复语料预取 `2/1/0/1`，全部达标；100 篇中 20 篇可恢复、80 篇仍被真实专名或其他门禁阻断。四地区小批 dry-run 为香港 `12/16` 可恢复、英国 `3/20`、法国 `6/13`、美国 `9/20`；随后仅对已审核的 run `#7/#8/#10/#11` 执行 manifest 锁定 commit，实际恢复 `24` 篇并按上段记录完成发布与旧库存清理。抽检发现并修复 NFKC 前文字符膨胀导致审计 span 偏移，法国复验 run `#11` 已准确记录 `Exactly -> exactly`。本地最终专项 `81` 项、完整 `stable` `870` 项通过；Django、迁移、旧规格流程 和 diff 检查通过。内外 `/healthz/`、首页、新闻详情和重处理后台登录跳转已通过真实浏览器/接口验收。至少观察 24 小时并完成普通词、单词型真实马名和 uncertain 抽检前，不得切全局 `enforce`，不得继续提交其他历史 run，也暂不归档 change。

`2026-07-12` P0 马资料补全基础能力已部署生产提交 `ce676998`。本地分支先变基到最新 `origin/main=31cc82c`，P0 迁移因主干已有 `0023/0024/0026` 顺延为 `stable.0027_p0_horse_profile_completion`；最新主干上术语解析/旧马匹页/P0 定向测试 `104` 项通过，补齐临时环境 `pdfplumber` 后完整 `stable` `813` 项全部通过，Django check、迁移一致性、旧规格流程 strict/all 和 `git diff --check` 通过。生产部署前 `HEAD=31cc82c`，容器、内外 `/healthz/`、公网 `/horses/` 正常，外部导入 started/锁和 Celery active/reserved 均为空，未发现历史回填进程；备份 `.env.backup.p0-horse-profile-20260712_162039` 与 `backups/db/pre-p0-horse-profile-20260712_162039.sql.gz`（109MB，`gzip -t` 通过）。生产已显式保持 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`，并新增批次上限 `10`、强制来源 URL、在役履历新鲜度 `1` 天。部署后 `0027` 已应用，`manage.py check`、内外健康页、马匹页和 Django Admin 跳转通过，`web/worker/beat` 日志无 traceback；既有 `HorseRaceRecord=21`，全部回填幂等键、空键 `0`。P0 来源 dry-run 为 `term_candidates=21596`、`major_race_candidates=992`，实际重点赛事证据含 runner `5096`、result `4572`；为遵守“五地区各 10 匹先人工跑通”，本次未执行 `--sync-sources --commit`，生产 `HorseP0Source/HorseIdentityConflict/HorseProfileCompletionRun` 仍为 `0`，也未启用网络补全或自动首次发布。

项目当前已经完成正式域名 HTTP 接入修复，`umafans.run` 与 `www.umafans.run` 已可访问。  
“自动化内容运营 + AI 编辑改写 MVP”已完成代码侧与生产侧上线，当前处于上线后观察与质量抽检阶段。

`2026-07-13` 五地区历史赛事第一批验收已全部完成生产详情写入：selection snapshot 中 `45/45` 个目标均为 `imported`，对应 `45` 个历史 `RaceEvent`、`468 runners / 429 results`，全部保持 `draft`，历史公开数为 `0`。法国和英国2000年样本已使用按地区隔离的 IrishRacing 正式备用详情源补齐；美国2000/2012六场使用 Equibase 官方单场 standard PDF 补齐，共新增 `58 runners / 58 results`，逐场胜马和1号马核验通过。美国详情候选固定 SHA-256 为 `94b62febe849b9a0562e5ab641d87671ae3468a202355b5336a7f4405e8abe75`。

美国补源的证据链已收紧为 target 批准记录 → date/source cache manifest 的大小与 SHA-256 → 单场 PDF 的 URL、大小与 SHA-256 → PDF 页眉日期/赛场/场次复核；`1a` 等联合投注编号作为独立实际出走保留。日期 apply 前备份为 `backups/db/pre-equibase-us-date-apply-20260713_083026.sql.gz`（`120405132` bytes，SHA-256 `65da811725111da6c556d077118571da0d9bf5bed628d15c27ea7021052ad2e5`）；详情 apply 前备份为 `backups/db/pre-equibase-us-detail-apply-20260713_083319.sql.gz`（`120406520` bytes，SHA-256 `ad547a575ac03de17d8314821b3111b30ef5151231f2c4d33e5fe263c99d09c1`），两份均通过 `gzip -t`。生产镜像为 `umanewsbot:equibase-20260713`，回滚镜像为 `umanewsbot:pre-equibase-20260713`；数据库约 `796 MB`，内外 healthz、Django check 和近10分钟日志正常。`.env` 继续保持 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，历史线上展示暂不开放。

`2026-07-13` 高相似名称审核已完成：`15` 对确认合并为名称变体，`Prince of Wales's` 与 `Princess of Wales's` 确认保持为不同赛事。最终身份总账为 `runtime/historical_race_inventory/tjcis-inventory-1998-2026-v12-final-20260713/`，保留 `30,917` 个年度目标和 `2,334` 条正式赛事线；高相似名称合并没有删除任何年度目标。最终工作簿为 `outputs/race_identity_review_20260712/TJCIS_1998-2026_赛事系列身份审核最终结论版.xlsx`，结构化校验、SHA-256、公式和视觉检查均通过。至此1998–2026同名簇与高相似名称身份审核全部完成，生产数据库仍未写入，历史公开开关继续关闭。

`2026-07-13` 已完成 TJCIS 1998–2026 的 `25` 个同名赛事簇逐项人工审核，并生成审核后身份决策与总账 v11。`102` 个临时 Series Key 已归入 `58` 条正式赛事线；审核后年度目标由 `30,919` 行变为 `30,917` 行，仅消除两组经确认的重复年度表达：Bristol Novices' Hurdle 的 2001 届（实际于 `2002-01-11` 在 Huntingdon 举办）和 Louisville Stakes 2008 改场记录。京都雌马锦标 `2005–2009` 已由 `not_held` 修正为 `held`；Keeneland First Lady 2000 年年度显示名修为 `Galaxy Stakes`；NYRA Matron 2018 场地修为 turf。正式产物为 `runtime/historical_race_inventory/tjcis-inventory-1998-2026-v11-approved-20260713/`，审核工作簿为 `outputs/race_identity_review_20260712/TJCIS_1998-2026_赛事系列身份审核结论版.xlsx`。逐届证据合并后为 `685` 届，可靠冠军 `473` 届、1号马 `164` 届。结构化校验、SHA-256 清单和工作簿视觉检查均通过。本次未写生产数据库、未部署，历史公开开关继续关闭。

同名簇身份边界已经审核完成，Ascot 约 3m 金杯线中文主名已确认为 `阿斯科特秋季金杯让磅障碍追逐赛`。`16` 对高相似名称也已完成审核，其中 `15` 对合并为名称变体，Prince/Princess of Wales's 保持独立。1998–2026 身份冲突审核现已清零。

同日补充确定五地区赛事详情的来源优先级：日本以 JRA 为官方主源，netkeiba 补历史出马表/赛果，JBIS 补血统与赛事沿革；中国香港以 HKJC Race Card / Results 为绝对主源；英国以 Racing Post Full Result 采实际出走和赛果，Sky Sports Racecard 补赛前声明出马表，BHA 仅用于 2014 年后官方校验；法国以 France Galop 为主、PMU 补充；美国以 Equibase historical charts 为主，BRISnet chart archive、DRF 和 BloodHorse 交叉校验，美国障碍赛另以 NSA 为重要来源。`declared runners`、`actual runners`、`non-runners` 和 `results` 必须分别记录及保留各自来源，不能用完赛结果中的实际出走马冒充赛前出马表。

`2026-07-12` 已把 TJCIS 1998–2026 身份审核表扩展为逐届证据版，产物为 `outputs/race_identity_review_20260712/TJCIS_1998-2026_赛事系列身份审核.xlsx`。该文件是人工审核前的原始证据快照，范围含 `25` 个同名簇、`102` 个临时 series key 和 `687` 个原始年度行；经生产库、JRA、TOBA、Wikipedia 历届冠军表和 Racing Post 单届赛果交叉补证，审前快照取得冠军 `474` 行、1号马 `164` 行。其同名簇结论和京都雌马冲突已由 `2026-07-13` 结论版及 v11 总账取代，原文件仅作审计留存。距离继续保留 TJCIS 原文，不允许跨地区直接比较裸数字；正式标准化前必须同时保存原值、原单位和统一换算值。

同日生产库只读覆盖复核：`RaceEvent=992`，其中 `finished=503 / scheduled=484 / cancelled=5`；有出马表的赛事 `505/992`（约 `50.9%`），有赛果的赛事 `503/992`（约 `50.7%`）。所有 `503` 场已完赛赛事均同时有出马表和赛果，因此按已完赛赛事为分母时两项覆盖均为 `100%`。现有模型没有独立的逐模块 `is_complete` 数据库字段，上述百分比是“存在正式模块数据”的运行态口径；全赛事约一半无赛果主要因为尚未开赛，而不是完赛后漏抓。

`2026-07-11` 已在生产库生成赛事编排第一批五地区应到清单，run 为 `runtime/race_event_crawl_runs/first-acceptance-race-event-crawl-20260711/`。本批每地区 1 场、共 5 场，分别为日本德比、富卫保险女皇杯、BETFRED DERBY、PRIX DE DIANE LONGINES、KENTUCKY DERBY PRESENTED BY WOODFORD RESERVE；三模块目标均为 `runners / results / history_winners`，5 行 `preflight_status` 全部为 `ready`。审批文件仍为 `pending`，plan 中 `allow_network=false`，本次没有访问外部网站、没有生成候选、没有写赛事详情。人工审核入口为 `review/expected_targets_review.csv`；只有用户确认赛事名称、年份、地区和 slug 后才允许填写审批并创建可触网的新 plan。

用户已确认第一批范围与中英文名。网络版 run `first-acceptance-race-event-crawl-network-20260711` 已生成，并与原审批清单逐字段对比一致；进入 prepare 前发现生产镜像未包含 adapter 所需的 `runtime/tools/*.py`。首次镜像补包后，真实 prepare 进一步暴露 Django 工作目录 `/app/server` 与 AdapterRunner 仓库根 `/app` 对相对 runtime 路径的解释不一致，`jra_detail` 在零网络请求时失败。最终镜像约定统一为 `/app/runtime`，并由 `/app/server/runtime` 符号链接到同一目录；运行计划、审批和失败 state 保持不变，修复后使用 resume 重试。

第一批网络抓取 v2 已完成 prepare 和覆盖审计，但审计状态为 `blocked`，未进入 dry-run 或写库：香港、英国、法国三场完整；JRA 详情脚本按筛选后序号误取全年首个结果页，把日本德比错配为中山金杯；美国 HRN 只有参赛名单，TOBA 在线页返回 403，缺正式赛果和历届冠军。JRA 已改为按赛事原名/别名唯一匹配结果页，编排测试 `55` 项通过。v3 保持已批准五场赛事不变，新增 `us_equibase_results`，计划以 HRN 参赛名单、Equibase 官方赛果 PDF、TOBA 已验证年度页组合完成美国三模块；五地区覆盖审计全部通过前不得进入 dry-run。

v3 首次 prepare 在请求预算 `60/60` 时由 HRN 空候选连带阻断 Equibase；补入此前留存的同源 HRN 日期页和 Churchill Downs 赛场页后，resume 已得到 24 匹参赛马且未新增请求。随后发现生产镜像缺少 Equibase PDF 脚本所需的 `pdfplumber`，当前补充 `pdfplumber==0.11.9` 并重建镜像；该阶段仍未运行 dry-run 或写库。

补齐依赖后 v3 prepare 的 11 个 adapter 已全部成功；Equibase 产出 Kentucky Derby 正式赛果 18 条、冠军 `Golden Tempo`。首次 coverage 仍为 `blocked`、完整地区 `3/5`：法国 Wikipedia 历史 adapter 因预算耗尽留下空候选；美国审计把 HRN 的空 `results` 与 Equibase 非空 `results` 误判为重复。当前审计改为只让非空模块参与重复、完整度和来源策略；只有空模块而无替代来源时仍报告 `empty_<module>`。回归测试增至 `56` 项通过，法国将使用留存的同源搜索响应和页面恢复后重新审计。

法国缓存按 canonical query 别名恢复后，coverage 已通过：`complete_count=5`、应到/实到均为 `5`、blocker 为 `0`，候选 SHA-256 为 `4043a5ee7a4c3cd09d9d2d15ae4bfec7ce32440f68b0836f3a4ec56d8b00bee7`。首轮 dry-run 通过，统计 11 条 adapter record、16 个模块、`runners=75 / results=64 / history_winners=47`；继续检查发现组合文件仍保留 HRN 空 `results`，虽会被 Equibase 后写覆盖，但与批准 apply scope 不一致。当前在 aggregate 阶段剔除显式空模块和全空记录，测试增至 `57` 项通过；修复部署后须重新生成候选身份、coverage 和 dry-run，尚未正式写库。

空模块修复后候选 SHA-256 为 `795e3629821dd843526a88bb445e2a65383c647a958578151d2bcbd99a56245a`，coverage `5/5`、blocker `0`，dry-run 为 11 条 record、15 个有效模块、`runners=75 / results=64 / history_winners=47`。字段级只读 diff 随后发现 JRA 2026 历史冠军候选会把现有练马师 `杉山 晴紀` 和完赛时间 `2:22.7` 覆盖为空，因此未放行 apply。当前 coverage 增加关键字段非空数量退化门禁，`jra_history_winners` 显式依赖同批 `jra_detail` 补齐当年冠军详情；25 年真实缓存 smoke 已确认 2026 `ロブチェン` 保留上述字段，编排测试 `65` 项通过。部署后需再次更新所有证据身份，仍未写库。

最终 resume 已通过：生产运行 `ad31a6d`，coverage `5/5`、blocker `0`，dry-run 为 11 条 record、15 个有效模块、`runners=75 / results=64 / history_winners=47`，最终候选 SHA-256 为 `2dd40a141219f7fd39799b7f586efb862f2332e8e037e4091f46c88bee48eac5`，请求账本保持 `60`。JRA 当届冠军字段已完整保留。字段级业务 review 只剩三类真实变化：英国历史增加 2020 `Serpentine` 并补 2021 `Adayar` 完赛时间；法国 `EVOLUTIONIST` 练马师从 `Burke Kr.` 规范为 `K R Burke`；法国 2026 冠军从大写/缩写人名规范为 `Diamond Necklace / Ryan Moore / Aidan O'Brien` 并补 `2:03:78`。其余核心字段与现有数据一致。当前停在 apply-check 前，等待用户确认这三类覆盖变化和法国/美国 mixed-source 策略，尚未正式写库。

用户已确认上述覆盖变化和 mixed-source 策略，第一批于 `2026-07-12` 正式写入生产。apply-check 的 8 个实际 scope 全部匹配，法国/美国 strategy SHA 已确认，blocker 为 `0`；写入命令按候选 SHA 锁定并在整批事务中完成，`candidates=15 / applied=15`。五场写后合计为 `runners=75 / results=64 / history_winners=47`，历史冠军较写前增加 1 条，RaceEventDataCandidate 从 27 增至 42；最新 15 条均为 `applied`。JRA `ロブチェン / 杉山 晴紀 / 2:22.7`、英国 2020/2021 补充、法国规范化和美国 Equibase 冠军均验收通过。写前备份为 `/opt/umanewsbot/backups/db/pre-first-race-crawl-apply-20260712_000116.sql.gz`，`105M`，gzip 与 SHA-256 校验通过；本地/公网 healthz 和 `/races/` 均返回 `200`，外部导入与锁仍为 `0`。

`2026-07-11` 发布提交 `38974f1` 已部署生产。赛事信息编排管理命令、adapter、五地区第一验收 fixture 和写入证据门禁已在线可用；本次只部署工具，没有启动真实赛事网络抓取，也没有写入赛事数据。多地区新闻归属代码与迁移 `stable.0023_multiregion_news_attribution` 同批上线，但生产 `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`，旧文章、地区查询、发布窗口和 QQ 继续使用原有主地区逻辑。生产五地区临时开启式 dry-run 发现归属结果仍需产品复核：法国样本 `article_id=7031` 从法国推断为英国主地区，日本样本中也出现主地区改为中国香港，并有样本一次关联三至四个地区；因此未启用归属功能、未执行 commit。验收 artifact 位于生产 `runtime/deployment_acceptance/multiregion-20260711_0352-enabled-dry-run/`。部署前备份为 `.env.backup.multiregion-orchestration-20260711_034313` 和 `backups/db/pre-multiregion-orchestration-20260711_034313.sql.gz`（约 `101M`，`gzip -t` 通过）。部署后六个容器正常，Django check、`/healthz/`、首页、法英地区页和后台登录 smoke 通过，web/worker 近 15 分钟无 error。

`2026-07-11` 赛事编排第四轮技术返修已实现：coverage 新增 `actual_apply_scopes`，apply-check 对账真实地区/来源/模块组合并逐组合要求确认；全绿后生成按 SHA-256 命名的 approved candidate，最终 importer 通过 `--expected-sha256` 从同一批原始字节复核后才解析写库；自定义 adapter 缺少非空 command/modules/outputs 或 provenance 时在 plan 阶段失败，prepare 不再静默跳过；coverage 行级 blocker 与 warning 已拆分，`existing_data_diff` 单独存在时标记 `complete_with_warnings` 且仍计入完整覆盖，候选更不完整时继续 blocked。独立赛事编排专项测试 `41` 项、包含并行马匹主页功能在内的完整 `stable` 测试 `581` 项均通过，Django check 和迁移漂移检查通过；当前未执行真实抓取、未写生产数据。

`2026-07-10` `classify-english-term-gate-context` 已部署生产。该变更在英文来源 `validate_rewrite()` 生成 `core_term_missing` 前加入上下文语义判定：地区过滤仍优先；本批已审核普通英文词种子和 `MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS` 按“普通词概率更高”处理，默认降级为 `english_term_common_word_downgraded` warning；只有 `wins / returns / runs / targets / entered` 等强动作上下文才把普通词种子保守维持为 blocker。`Classic` 这类同时属于普通词和赛事 marker 的 horse term 会先走普通词上下文判断，`Contact and live updates from York` / `Live stable updates` 等弱赛马上下文不会硬挡。重校验命令 `reprocess_term_gate_blocked_articles` 已改为有界候选、批量预加载术语/alias，并输出文章级英文分类明细、真实专名阻断明细和地区 summary；`--commit` 只恢复完整门禁通过文章到可发布候选，不直接公开发布。上线前本地已通过目标测试、`manage.py check`、`旧规格流程 validate classify-english-term-gate-context --strict` 和 `git diff --check`。生产部署前已把服务器独有的移动端马匹导航修复提交合并回主线，最终上线提交为 `43898ff`；备份 `.env.backup.english-term-context-20260710_030705` 和 `backups/db/pre-english-term-context-20260710_030705.sql.gz` 均已生成且数据库备份通过 `gzip -t`。部署后 `web / worker / beat / db / redis / nginx` 正常，生产 `manage.py check`、本地 `/healthz/`、公网 `/healthz/`、首页和后台登录入口 smoke 均通过。

生产完整只读 dry-run 已完成，产物目录为 `runtime/multiregion_candidate_audit/reprocess_full_dryrun_20260710_030944/`，本次未执行 `--commit`、未恢复候选、未公开发布。四地区旧 `core_term_missing` 候选合计 `146` 篇，其中 dry-run 后完整门禁通过、可恢复为发布候选的为 `37` 篇：香港 `3/17`、英国 `5/37`、美国 `22/79`、法国 `7/13`；仍阻断 `109` 篇。普通词降级命中合计 `142` 次，仍保留真实专名 blocker 合计 `549` 次。旧规格流程 change 已归档到 `旧规格流程/changes/archive/2026-07-10-classify-english-term-gate-context/`，正式规格已同步到 `旧规格流程/specs/automation-publish-gates/spec.md`。下一步如要实际恢复文章，应先人工抽检 dry-run JSON，确认无真实马名、赛事名或人物名被误降级，再按地区小批执行 `--commit`。
`2026-07-10` 已做一次只读数据续抓盘点，本次未执行生产抓取、未写库、未部署。当前已经批量处理过的数据主线包括：新闻源抓取与多地区新闻源探测、术语种子与候选池审计、2026 五地区重要赛事基础表、部分赛事详情出走表/赛果、HKJC / Sporting Life / Geny / HRN 外部赛马数据库 proof / dry-run，以及已发布文章术语回填。后续继续抓取建议优先放在结构化赛事数据，而不是盲目扩大新闻抓取：第一优先补英国 / 法国赛事详情和五地区历届冠军；第二优先恢复 HKJC 长窗口 dry-run 并按审计门禁判断是否进入 commit；第三优先按 runbook 开始英国、法国、美国最近 60 天外部赛马数据库完整 dry-run。新闻侧继续常态观察来源健康和门禁原因即可。

`2026-07-10` 已完成英法赛事详情候选的只读覆盖校验，并生成离线审计产物 `runtime/race_event_detail_imports/2026/coverage-audit-20260710/`。英国基础赛事共 `202` 场（Flat `138`、Jump `64`），CSV 状态已完赛 `123` 场；现有 Sporting Life 详情候选规范合并后 `122` 场，所有候选 slug 均能回到基础赛事，规范候选内无重复 slug、无 source URL 一对多映射。英国缺口为 `uk-bha-jump-2026-0206-016 / Jane Seymour Nov. Hurdle`，另有 `2026-07-09` 至 `2026-07-10` 已到日期但 CSV 仍为 `scheduled` 的 Flat 赛事 `5` 场，后续应刷新 Sporting Life 结果页后再补。法国基础赛事共 `173` 场，CSV 状态已完赛 `74` 场；ZEturf 候选原始记录 `80` 条，存在 `6` 个重复 slug，规范合并后 `74` 场，已覆盖全部已完赛法国赛事且候选均回到基础赛事，规范候选内无 source URL 一对多映射。法国重复中 `fr-france-galop-2026-0705-044` 曾有一条误配到 `Prix des Côteaux de Saint-Cloud` 的候选，规范包已保留匹配 `Grand Prix de Saint-Cloud` 的 `R1C5` 版本。规范候选包为 `uk_canonical_detail_candidates_20260710.jsonl` 与 `france_canonical_detail_candidates_20260710.jsonl`；本地 `import_race_event_detail_candidates --dry-run` 因本地 sqlite 未加载生产 `RaceEvent` 行而无法执行，生产 dry-run 前仍需在生产库上重新校验。

`2026-07-10` 生产复核发现英法赛事详情实际上已完成正式导入：生产 `RaceEventRunner=5096`、`RaceEventResult=4572`、`RaceEventHistoryWinner=5731`、`RaceEventDataCandidate=2913`，其中英国已应用 `sporting_life` 116 组和 `sporting_life_gap` 6 组，法国已应用 `zeturf` 候选；英国 `Jane Seymour Nov. Hurdle` 当前生产状态为 `cancelled`，不是需补赛果的 finished 缺口。复核同时发现 `fr-france-galop-2026-0705-044 / GRAND PRIX DE SAINT-CLOUD` 的出走表和赛果已被正确 R1C5 覆盖，但 `RaceEventHistoryWinner` 中 `2026` 年冠军仍残留早先误配 R1C4 的 `ZELMAN`。已在生产生成单场修复 JSONL `grand_prix_saint_cloud_history_repair_20260710.jsonl`，dry-run 通过 `events=1 modules=1 items={"history_winners": 7}`；写入前备份 `backups/db/pre-race-detail-gpsc-history-repair-20260710_025949.sql.gz`（约 `96M`）且 `gzip -t` 通过；正式 apply 成功 `events=1 candidates=1 applied=1`，新增 applied candidate `2914`，该赛事 2026 历史冠军已修为 `CALANDAGAN`，公网 `/races/2026/fr-france-galop-2026-0705-044/` 可见 `CALANDAGAN`，本地/Host `/healthz/` 均返回 `ok`。本次没有重复导入整批英法 runners/results。

`2026-07-10` 已为后续长期赛事历史回填创建并完成 旧规格流程 change `orchestrate-race-event-data-crawls` 的 planning artifacts：`proposal.md`、`design.md`、`tasks.md`，以及 `race-event-data-crawl-orchestration` 新规格和 `race-event-pages` / `real-global-racing-data-ingestion` delta specs；已执行 `/plan-eng-review` 并将 change 标记为 `profile=feature`、`phase=reviewed`，review 轮次为 `1`，修正了 adapter 非统一脚本契约、深历史目标 `RaceEvent` 行预检 / draft seed 清单、五地区第一验收 fixture 覆盖三项计划风险。随后已新增 `server/stable/test_race_event_crawl_orchestration.py` 目标测试，并实现 `stable.services.race_event_crawl_orchestration` 与 `orchestrate_race_event_crawl` 管理命令，支持 `plan`、`prepare`、`audit`、`dry-run`、`apply-check`、`resume` 阶段。多轮返修后编排工具已处理：plan 自复制、adapter 相对路径和网络授权、分模块候选聚合、活跃锁判断、真实 resume、人工归因保护，以及正式门禁证据绑定。当前 adapter 会从 manifest 向标准候选和 summary 注入 provenance，并记录必需输出 SHA-256；coverage 会阻断缺失/冲突 source authority，记录候选身份和混合来源策略；结构化 `dry_run.json` 与 apply-check 强制核对同一候选哈希，不能用另一份 JSONL 或空壳日志绕过；resume 只在输入和必需输出哈希都一致时跳过，并可恢复 audit、dry-run 和 apply-check；所有阶段成功/失败都会写入同一 state。新闻入库同时补充保护：来源提升不得覆盖 `attribution_locked=true` 的人工主地区。默认 adapter registry 已覆盖 JRA/NAR/HKJC/UK Sporting Life/France ZEturf/US HRN/Equibase 的 runners/results 路径，以及 JRA/NAR/HKJC/UK Sporting Life/France Wikipedia/US TOBA 的 history_winners 路径；第一验收 plan fixture 位于 `server/stable/fixtures/race_event_crawl/first_acceptance_plan.json`，source authority 矩阵位于 `server/stable/fixtures/race_event_crawl/source_authority_matrix.json`。本轮验证为赛事编排专项测试 `29` 项、完整 `stable` 测试 `545` 项、Django check、迁移漂移检查、Python 编译、旧规格流程 严格/全量校验和 `git diff --check` 全部通过。该 change 目前仍未运行真实抓取、未写生产数据。已锁定的第一版边界：只服务 `RaceEvent*` 产品层，不写 `External*`；日本、香港、英国、法国、美国五地区都要参与第一验收小批；第一阶段不含 Listed；`runners`、`results`、`history_winners` 三模块同历史深度推进；历史 series 必须显式 mapping；长周期运行默认手动分批 / 一次性容器，不做 Celery Beat 或无人值守 apply。

`2026-07-10` 第三轮赛事编排审查返修已实现并完成本地验证：run 在网络请求前根据 plan 独立生成绑定 plan SHA-256 的 `expected_targets.json` 与运营 review CSV，清单包含赛事中英文名、年份、地区、slug 和预检状态；coverage 以该清单为固定分母，空候选、缺少应到目标、出现计划外候选或 series 不一致均 fail closed。prepare 会把全部 adapter 的标准候选汇总为 `combined_candidates.jsonl`，audit / dry-run 默认复用该文件；plan 的 batch/rate limit 已从“仅记录配置”改为真实执行，全部默认网络 adapter 共享 run 级 `request_budget.json`，累计达到上限或预算证据损坏时停止请求。第一验收会逐地区检查三模块 adapter 覆盖，apply-check 会验证真实备份文件、gzip 通过和 `diff_review.status=approved`。英文门禁同时修复 ignored alias 连带豁免同记录其他可信专名的问题。目标回归 `40` 项、完整 `stable` 回归 `555` 项、Django check、迁移漂移、Python 编译、两个 change 严格校验、全量 旧规格流程 `19` 项和 diff 检查全部通过。当前仍未进行真实网络抓取、生产写入或部署；第一批真实抓取前需由用户审核应到清单，技术性证据由工程侧负责。

`2026-07-08` 本地已修复 2026 赛事历届冠军 / 缺口详情候选生成工具的 apply 前安全问题：`prepare_jra_history_winner_candidates.py`、`prepare_hkjc_history_winner_candidates.py`、`prepare_nar_history_winner_candidates.py`、`prepare_uk_sportinglife_history_winner_candidates.py`、`prepare_us_toba_history_winner_candidates.py` 和 `prepare_france_wikipedia_history_winner_candidates.py` 在年份、马季、previous-winners 链路或 Wikipedia 赛事页出现中途错误时，默认跳过相关赛事并记录 `partial_*` skipped，不再生成半截 `history_winners` 候选后在正式 apply 中替换掉已有完整数据；如确需人工接受部分历史，可显式使用 `--allow-partial-history` 并在 metadata 中保留 diagnostics。`prepare_uk_sportinglife_gap_candidates.py` 现在会在 Sporting Life 详情解析出空出走表或空赛果时写入 `skipped`，不再生成可 apply 的空 runners/results 候选，避免覆盖已有赛事详情。`.gitignore` 已补充 `runtime/race_event_history_imports/` 与 `runtime/term_review/`，防止历史冠军 HTML/cache、review CSV/JSON、术语 snapshot 等运行产物被误提交；可复用脚本仍保留在 `runtime/tools/`。

`2026-07-10` 已按用户抽检结论处理候选池 raw 分类结果：`raw_classified_term_candidates_candidate_pool_20260701_20260707.csv` 中 `is_likely_term=yes` 的 `369` 条全部为 `existing_termbase_residual` 且均有 `existing_term_id`；进一步生产只读核对显示对应 `350` 个唯一 `TermEntry` 当前全部存在且 active，因此无需新增术语库记录。`is_likely_term=no` 的 `89` 条已确认为非术语；本地代码新增 `MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS` 默认配置，并在发布校验中将命中该配置的 source term 记为 `non_term_gate_ignored` / `info`，不参与 `core_term_missing` / `background_term_missing` 阻断。该列表覆盖本次 raw no 类中的 HTML/布局片段、源站/导航/产品噪声、普通赛马词、片段/普通词等；`review` 类暂不处理，尤其暂无翻译的马名不批量创建中文译名。本地验证已通过目标测试、`manage.py check` 和 settings 默认值读取；本次未写生产术语库、未部署生产、未回填文章字段。

`2026-07-07` 旧规格流程 change `fix-tdn-france-search-date-freshness` 已完成实现并部署生产，用于修复法国 `tdn_france_broad` 抓入历史旧文的问题。根因是 TDN WordPress search API 返回相关性历史结果且 search item 不带发布时间；修复后 `TDNFranceKeywordAdapter` / `TDNFranceBroadKeywordAdapter` 会用 search item 的 `id` 或 `_links.self` 二次读取 post API 的真实 `date_gmt/date`，缺失真实日期的条目会跳过，超过 3 天新鲜度窗口的历史旧文也会跳过，且 listing 阶段跳过会写入 `CrawlJob` / `NewsSource.last_crawl_message`，不再兜底为当前时间。本地验证已通过目标测试、`DB_ENGINE=sqlite python manage.py check`、完整 `stable` 测试 `493` 项、`旧规格流程 validate fix-tdn-france-search-date-freshness --strict`、`旧规格流程 validate --all` 和 `git diff --check`。生产服务器 `/opt/umanewsbot` 已通过 bundle 从 `96fde81` 快进到 `ad587ce` 并重建 `web / worker / beat`；部署前数据库备份为 `backups/db/pre-tdn-france-freshness-20260707_223913.sql.gz` 且 `gzip -t` 通过，外部导入运行数和锁均为 `0`。已将误发布的历史旧文 `7255/7263/7264/7265/7271` 标记为 `withdrawn`、清空 `published_to_web_at` 并写入清理原因，公网 `/news/<id>/` 均返回 `404`。`NewsSource#21 TDN 法国宽关键词英文新闻` 已重新启用：`enabled=true`、`production_approved=true`、`manual_pause_reason=""`。线上只读探测当前为 HTTP `200` 但 `empty_sample`，真实抓取 `CrawlJob#9445` 成功，`new_count=0`、`seen_count=0`、`skipped_count=80`，首条原因 `stale_published_at`，无新增文章，确认 2020/2022 等历史旧文已被过滤而非入库。

`2026-07-07` 已在 worktree `/Users/mentianlu/.codex/worktrees/race-detail-page/umanews` 本地实现 旧规格流程 change `horse-profile-page-mvp`。新增 `HorseProfile`、`HorseProfileDataCandidate`、`HorseRaceRecord`、`HorseRaceLink`、`ArticleHorseLink` 和 `HorseFollow`，迁移为 `stable.0022_horseprofile_horsefollow_articlehorselink_and_more`；P0 马由 `generate_horse_profiles` 从 active horse `TermEntry` 生成草稿，默认不前台可见，管理员可在 `/admin/horse-profiles/` 审核、补资料、维护参赛履历/新闻关联并手动发布，空壳也允许强制发布。公开入口新增 `/horses/`、`/horses/<id>/`、`/horses/follows/`，URL 只使用唯一 ID；新闻详情页展示已发布马匹 tag，首页新增“我的关注”模块，匿名关注只在 cookie 中保存签名 token，数据库只存 `token_hash`，可包含关注马的子孙代新闻。外部补全采用“本地 ExternalHorse/ExternalHorseAlias 缓存 + dry-run artifact + 人工审核后 commit”的门禁，`complete_horse_profiles` 会输出全局/按地区完整二代成功率、未补全占比、逐马失败原因和 source URL；commit 必须指定 `--artifact --confirm-reviewed-artifact`。KeibaScraper 调研结果：`new-village/KeibaScraper` 当前为 Apache-2.0、PyPI 3.1.5（2026-05-13 发布）、项目说明提示请求会给 netkeiba 带来负载，因此只作为受控 `external_horse_data` 导入链路的数据源，不让公开页或审核页直接访问第三方。本地验证已通过 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.HorseProfilePageMvpTests --noinput`（8 项）和完整 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`（498 项）。

`2026-07-08` 已完成 `horse-profile-page-mvp` 本地审查修复：`complete_horse_profiles --dry-run` 不再默认截断为 100 条，未传 `--limit` 时覆盖所有地区全部 P0 马；马名和术语匹配统一对拉丁字母大小写不敏感；关注列表、首页关注模块和关注流只返回仍为 `published` 的马匹及其公开子孙代，后台下线或隐藏后不会继续在前台关注面泄露；补全 artifact commit 会在写库前生成 before/after diff，保留真实审计差异。补充回归测试后，本地验证通过 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.TermResolverTests stable.tests.HorseProfilePageMvpTests --noinput`（31 项）和完整 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`（503 项）。

`2026-07-08` 二次审查后继续收紧 `horse-profile-page-mvp`：后台资料保存表单不再携带 `review_status`，发布/下线只能走专门状态动作以保留 `published_at/published_by/hidden_at/hidden_by` 和状态变更日志；补全 summary 的 `regions` 也输出按地区 `complete_ratio` / `not_complete_ratio`；`scan_article_horse_links_task` 在显式 `article_id` 或 `profile_id` 已不存在时直接返回 skipped，不再退化为默认范围扫描。补充回归测试后，本地验证通过 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.HorseProfilePageMvpTests stable.tests.TermResolverTests --noinput`（33 项）和完整 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`（505 项）。

`2026-07-08` `horse-profile-page-mvp` 已部署生产提交 `2b28755`。部署前生产 `HEAD=01c0b9b`，容器健康，`manage.py check`、本地 `/healthz/`、公网 `/healthz/` 通过，`ExternalDataImportRun(status="started")=0` 且外部导入锁为空；备份 `.env` 为 `.env.backup.horse-profile-page-mvp-20260708_040446`，数据库备份为 `backups/db/pre-horse-profile-page-mvp-20260708_040503.sql.gz`（约 `85M`）并通过 `gzip -t`。已在生产 `.env` 显式设置保守默认：`HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`、`HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS=8`、`HORSE_PROFILE_COMPLETION_CACHE_DIR=runtime/horse_profile_completion/cache`。部署后 `stable.0022_horseprofile_horsefollow_articlehorselink_and_more` 已应用，`web / worker / beat / db / redis / nginx` 正常，生产 `manage.py check` 通过，本地和公网 `/healthz/`、公网 `/horses/` 均返回 `200`。已执行 `generate_horse_profiles`，生成 `21596` 个 `HorseProfile`，全部为 `draft`，`published=0`；草稿样例 `/horses/1/` 返回 `404`，未登录 `/admin/horse-profiles/` 返回 `302`。历史新闻马匹关联 dry-run `--limit 500` 为 `created=0 updated=0 candidate=0`。全地区补全 dry-run 已输出到生产宿主机 `runtime/horse_profile_completion/dry-run-20260708_041343/`，覆盖 `21596` 匹 P0 马：完整二代 `0`、未补全 `21596`、未补全占比 `1.0`；原因分布为 `no_external_match=15293`、`source_unavailable=6301`、`profile_only=2`，按地区 `france/hong_kong/japan/other/united_kingdom/united_states` 的未补全占比均为 `1.0`。本次未应用补全 artifact，后续需先人工审核 `horse_profile_completion_review.csv` 后再 commit。

`2026-07-08` 旧规格流程 change `horse-profile-page-mvp` 已归档到 `旧规格流程/changes/archive/2026-07-08-horse-profile-page-mvp/`。归档前已将 delta spec 同步到正式规格：新增 `旧规格流程/specs/horse-profile-pages/spec.md` 与 `旧规格流程/specs/horse-profile-data-completion/spec.md`，并把首页关注模块、关注管理入口和新闻详情马匹 tag 要求合并到 `旧规格流程/specs/public-home-info-feed/spec.md`。归档后 `旧规格流程 validate --all` 通过 `19` 项。

`2026-07-10` 已将马匹详情页 MVP 最后一轮前台体验修复和两匹样本马资料上线到 UmaNews 生产服务器 `root@47.239.167.86:/opt/umanewsbot`，最终生产 `HEAD=65988b0`。本次只使用 UmaNews 服务器，未使用其他项目服务器。部署前备份 `.env.backup.horse-public-polish-20260710_010639` / `backups/db/pre-horse-public-polish-20260710_010639.sql.gz`，样本写入前备份 `backups/db/pre-horse-sample-profiles-20260710_011038.sql.gz`，移动样式修复前备份 `.env.backup.horse-mobile-polish-20260710_011811` / `backups/db/pre-horse-mobile-polish-20260710_011811.sql.gz`，均已 `gzip -t`。已发布 `春秋分` `/horses/13113/` 与 `北十字星` `/horses/3873/`，来源为用户指定 netkeiba 页面 `https://db.netkeiba.com/horse/2019105219/` 与 `https://db.netkeiba.com/horse/2022105102/`；两匹马均为 `published`、`complete_pedigree_2gen`，参赛履历分别为 `10` / `11` 条，相关新闻人工关联各 `5` 篇。浏览器验收覆盖：详情页二代血统、主胜鞍、参赛履历、相关新闻、新闻详情马匹 tag 点击、匿名关注/取消关注、关注页新闻流、`croix` / `EQUINOX` 大小写搜索、移动端一级导航和地区筛选布局；测试关注已清理，最终 `HorseFollow` 样本计数为 `0`。生产 `manage.py check`、本地和公网 `/healthz/` 均通过。

`2026-07-10` 已为 P0 马资料补全专项新建独立 worktree `/Users/mentianlu/.codex/worktrees/p0-horse-info-completion/umanews`，分支 `codex/p0-horse-info-completion`，并从 `origin/main` 快进对齐旧线程最终提交 `d78fab0`（其中生产运行代码为 `65988b0`，`d78fab0` 为文档验收记录）。已创建并经 `/grill-me` 需求追问重写 旧规格流程 change `complete-p0-horse-profile-data`：新版 P0 马范围为“当前 active 且有中文译名的 horse `TermEntry` + 日本/中国香港/英国/法国/美国全部历史与未来重点赛事参赛马”，重点赛事等级严格限定为 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ`；暂无中文译名的 P0 马允许进入补全、ready 和人工发布，翻译命中时必须保留原文而不做空中文替换。首批验收口径已改为五大地区各 10 匹完整资料马，完整资料硬门槛包含身份/P0 来源证据、基础事实字段、二代血统、完整赛事履历、主胜鞍、来源 URL、赛马生涯/同步状态和人工审核记录，`intro`、相关新闻和站内相关赛事链接不作为硬门槛。已重新执行 `plan-eng-review`（Full mode，session 2，2 个问题已修复），补充了退役/在役履历同步状态与 `docs/decisions.md` 回写任务；`.旧规格流程.yaml` 当前 `phase=reviewed`。已通过 `旧规格流程 validate complete-p0-horse-profile-data --strict`；本 change 尚未进入代码实现或生产执行。原“下一步运行 旧规格流程 apply skill”的交接已被 `2026-07-15` 新流程取代：在安全检查点读取现存规格，补齐/更新测试用例，对未实现行为取得真实 RED 后交给 subagent 实现，再由同一需求既有代码 reviewer 会话复审。

`2026-07-10` 已按测试先行方式为 `complete-p0-horse-profile-data` 在 `server/stable/tests.py` 新增 RED 用例。覆盖暂无中文译名马名术语的识别/原文保留/校验阻断、五大地区重点赛事参赛马进入 P0 queue、非重点等级排除、完整资料硬门槛、在役马履历同步窗口、人工审核 artifact 幂等入库、完整后仍需人工首次发布、公开页不得触发 P0 同步/补全，以及无中文译名公开页使用原文并提示中文译名待补。本轮未实现产品代码，故未勾选 旧规格流程 tasks；新增测试预期在实现前失败。当前本地仅完成 `python3 -m py_compile server/stable/tests.py` 与 `git diff --check`；Django 定向测试因当前可用 Python 环境缺少 `django` 依赖未能运行。

`2026-07-10` 已开始实现 `complete-p0-horse-profile-data` 的核心应用骨架。新增迁移 `stable.0027_p0_horse_profile_completion`：`TermEntry.translation_status` 支持无中文译名 horse term，`HorseProfile` 增加完整资料状态、赛马生涯状态、履历同步时间、完整资料审核人与自动化预留字段，新增 `HorseP0Source` 和 `HorseProfileCompletionRun`，并为 `HorseRaceRecord` 增加幂等键与 run 关联。新增 `stable.services.p0_horse_profiles`，实现本地新版 P0 来源同步、五地区重点赛事等级过滤、P0 队列预览、完整资料评估、已审核 artifact 幂等写入和人工 ready 标记；公开页仍不触网。术语解析/应用/发布校验已区分“有中文译名可替换”和“暂无中文译名需保留原文”，后台术语表单/CSV、马匹后台筛选、详情质量提示和前台无译名展示已更新；新增 `p0_horse_profiles` 管理命令。已在 `/tmp/umanews-p0-venv` 临时环境完成验证：`DB_ENGINE=sqlite manage.py check` 通过，`makemigrations --check --dry-run` 无变化，新增目标测试 `10` 项通过，旧 `HorseProfilePageMvpTests` `15` 项通过，`旧规格流程 validate complete-p0-horse-profile-data --strict`、`旧规格流程 validate --all`（20 项）和 `git diff --check` 均通过。当前尚未完成五地区真实 adapter 扩展、完整 dry-run artifact 写出、每地区 10 匹样本 dry-run、生产 commit 或人工公开验收。

`2026-07-10` P0 核心骨架完成第二轮审查返修。马匹自动身份合并改为依赖“来源命名空间 + 外部 horse ID”强身份键，名字和地区只用于候选检索；同名马强身份键不同可建立独立资料，既有同名资料缺强身份键时保留歧义并停止自动合并。P0 来源同步支持地区作用域，普通 `--sync-sources --commit` 只新增/刷新来源，只有显式 `--full-reconcile` 才撤销全地区失效来源；queue 支持重复 `--profile-id`。完整资料评估默认按 `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS=1` 检查在役马履历，并以每模块最新审核结论为准，新冲突会撤销 `complete_profile_full`；退役马同步日期不得早于最新赛绩。已修复赛绩来源门禁不可达、待译马名被中文 alias 误放行、术语待译状态在控制台/API 缺失等问题。专项与旧马匹页回归共 `83` 项通过；完整 `stable` 从仓库根目录以 eager 模式运行 `538` 项，仅剩 `3` 个随当前日期漂移的既有 TDN France fixture 失败。尚未执行真实 adapter 扩展、五地区各 10 匹 dry-run、生产 commit 或公开验收。

`2026-07-10` 已根据代码审查和用户确认返修 P0 核心门禁。马匹地区不再参与身份唯一匹配，跨地区重点赛事复用全局唯一正式马名/alias，赛事地区只写 P0 来源且不覆盖 `HorseProfile.racing_region`；歧义身份不直接写主表。暂无中文译名 horse term 的原文保护跨地区生效，已有中文译名的歧义英文术语继续使用既有地区门禁。P0 全量同步会把本轮失效的术语/重点赛事来源标记为 `revoked` 并保留历史。完整资料现在阻止 `racing_career_status=unknown`，要求退役/在役履历同步标记、每条赛绩来源名与 URL、审核人/时间及基础资料/血统/赛事履历/主胜鞍四模块 applied 记录。artifact commit 改为顶层、行级、模块级三层审核，并区分旧赛绩接管、新增、修正和未变化；迁移为唯一旧赛绩回填幂等键，已有重复旧赛绩组转冲突且不会新增第三条，修正保存 before/after。目标与兼容测试 `20` 项、旧马匹页 `15` 项、`manage.py check`、迁移一致性、旧规格流程 strict/all 和 `git diff --check` 通过。完整 `stable` 回归共 `526` 项，除 `3` 个使用 `2026-07-07` 固定发布时间、在当前日期已越过三天窗口的 TDN France 时效测试外均通过；这三个失败与本次 P0 改动无关，尚未在本专项修改。

`2026-07-11` 第三轮 P0 审查返修确立两层身份原则：来源命名空间内 external horse ID 直接定位来源身份；跨来源归并数据库已有马必须完整唯一命中经术语库多语种归一的“马名 + 父名 + 母名 + 出生年份”，`racing_region` 不参与唯一性。术语识别支持外文主名、中文译名和多语言 alias；同一原名对应多个 active horse term 时保留原文、禁止任选中文译名。队列按 `HorseProfile.racing_region` 每匹马只出现一次，人工来源和重点赛事证据优先；冲突审计覆盖旧 applied 结论，通用完整度刷新不再错误降级有效的 `complete_profile_full`。身份冲突的最终持久化与处理方案以紧随其后的第四轮记录为准。

`2026-07-11` 第四轮审查返修进一步修复五个身份与审核边界：同一赛事参赛记录改为优先按马号、其次按来源 external ID 分组，同名不同马号不再提前折叠；完整对账遇到参赛记录仍存在但 source URL 暂缺时保留既有 P0 来源，不误标 `revoked`；通用候选应用服务端只接受 `pending`，冲突/忽略/已应用记录不能通过直接 POST 变成 applied；人工 `complete_profile_full` 审核必须显式提供整匹马资料 URL，不能借用单场赛果 URL 给基础资料和血统背书。身份歧义采用专用 `HorseIdentityConflict`，支持无 profile 冲突、多个候选术语/资料页、赛事/马号/父母/出生年份/来源证据、pending/resolved/ignored、解决资料页、处理人和处理时间；`resolved` 必须选择最终资料页，下一次同步会按人工结论建立 P0 来源。每天 `09:20` 通知链接 Django Admin 待处理筛选。定向术语/P0/旧马匹页回归 `79` 项全部通过；完整 `stable` 回归 `556` 项仅有此前已知的 `3` 个固定日期 TDN France 时效 fixture 失败，本轮新增测试全部通过。`manage.py check`、迁移一致性、旧规格流程 strict/all 和 `git diff --check` 均通过；尚未执行真实 adapter 扩展、五地区各 10 匹 dry-run、生产 commit 或公开验收。

`2026-07-11` 第五轮审查返修把同场参赛身份和赛绩幂等写入升级为长期结构。`HorseP0Source` 新增持久化 `participant_key`：同场优先按马号，其次按来源 external horse ID，最后仅在赛事内马名唯一时按规范化马名识别；runner/result 先按马号、外部 ID、唯一马名分阶段配对，字段不对称时不会把同一匹马拆成两条。同场同名但不同马号即使没有外部 ID 也建立不同来源与资料页，重复同步不增生；身份纠正时旧来源标记 `revoked`，新绑定另建 active 行，保留追加式审计。赛绩写入抽到共享 `horse_race_records.upsert_race_record()`，P0 artifact 与通用人工候选均强制生成幂等键、接管唯一旧记录、拒绝重复旧记录歧义，并要求 `source_name/source_url`。定向旧马匹页/P0 回归 `59` 项全部通过；完整 `stable` 回归 `560` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败。`manage.py check`、迁移一致性和代码语法检查通过；真实五地区样本与生产步骤仍未执行。

`2026-07-12` 第六轮审查返修关闭三个剩余身份/赛绩入口缺口。参赛者从“只有 external ID”补到马号时，P0 同步会通过既有 `race_result`、`race_runner` 或来源 identity 找到旧 active 来源并迁移 `participant_key`，普通增量同步不会留下 identity/number 两条 active 记录；若新身份指向另一资料页则撤销旧绑定。runner/result 两边均有非空且不同马号时，即使 external ID 相同也禁止自动配对，保存 `HorseIdentityConflict.evidence_payload.pairing_conflict` 后停止写 P0 来源。后台手工新增与编辑赛绩也统一调用 `upsert_race_record()`：新增重复记录不增生，编辑自然键后重新生成幂等键，命中另一记录时拒绝覆盖，来源 URL 在表单与服务两层必填。定向旧马匹页/P0 回归 `63` 项通过；完整 `stable` 回归 `564` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败，本轮新增测试全部通过。并发相同赛绩写入仍按用户决定不在本轮处理。

`2026-07-12` 第七轮审查返修补齐同类型参赛记录、来源证据和新鲜度口径。P0 participant 构建完成后会按同一来源 identity 汇总全部 runner/result；同一 identity 对应多个非空马号时，不论是 runner-result、两条 runner 或两条 result，均合并为一条 `HorseIdentityConflict`，证据保存全部马号与记录 ID，且不生成 active P0 来源。后台编辑既有赛绩时只更新表单事实字段和幂等键，保留 importer 原有 `source_refs/raw_payload`，before/after diff 写入操作日志；只有手工新建才初始化 manual console 证据。新增 `active_record_freshness_cutoff()` 统一完整度与后台“在役待刷新”筛选，默认 1 天时昨天仍为新鲜、前天才待刷新。定向旧马匹页/P0 回归 `67` 项通过；完整 `stable` 回归 `568` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败，本轮新增测试全部通过。

`2026-07-12` 第八轮审查返修完善马号冲突解决与 external-ID 赛绩稳定性。`HorseIdentityConflict` 新增 `resolved_horse_number`：含 `pairing_conflict` 的记录只有同时选择最终资料页和证据内候选马号才允许 resolved，后续同步只绑定该马号对应的 runner/result；选中记录缺可复核 URL 时仍不写 active 来源。冲突 evidence 现在保存全部成员的马号、名称、runner/result ID 和 source URL；任意成员有 URL 时用于冲突复核，全部无 URL 时冲突仍落库并计入缺 URL。fingerprint 只使用稳定身份字段，后补 URL 不会生成重复冲突。后台编辑 imported 赛绩时从既有 `raw_payload/source_refs` 继承 external race/result ID，并沿用原 source namespace 生成幂等键，编辑名称后 importer 重跑仍只保留一条记录。定向旧马匹页/P0 回归 `69` 项通过；完整 `stable` 回归 `570` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败，本轮新增测试全部通过。

`2026-07-12` 第九轮审查返修补齐三个数据完整性边界。`stable.0027` 的旧赛绩幂等键回填同时读取 `raw_payload` 与 `source_refs` 中的 external race/result ID，避免迁移后 importer 以另一种键重复建档；同一赛事内共享任一来源身份键的参赛记录先按连通组整体归并，交叉身份键不再覆盖或丢失冲突成员；马号冲突 resolved 前要求所选成员或赛事具备来源 URL，若 URL 后续消失或绕过表单写入，下一次同步会清除无效解决结论、恢复 pending 并记录 `resolution_failure`，继续进入每日管理员通知。术语解析/旧马匹页/P0 定向回归 `96` 项通过；完整 `stable` 回归 `573` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败。尚未部署或执行五地区样本补全。

`2026-07-12` 第十轮审查返修修复三处持续运行风险。人工 `HorseP0Source` 改为按 `profile + source_type=manual` 独立 upsert，并增加条件唯一约束，多匹马依次审核不再互相撤销来源；马号冲突的所选成员无法在本轮证据中定位时，与缺 URL 使用同一恢复函数，清空无效人工结论、恢复 pending 并记录 `resolved_member_missing`；旧空键赛绩在自然字段匹配前优先扫描 `raw_payload/source_refs` external identity，同一来源 external ID 命中多条时直接报告歧义，禁止 importer 新增第三条。术语解析/旧马匹页/P0 定向回归 `99` 项通过；完整 `stable` 回归 `576` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败。尚未部署。

`2026-07-12` 按用户要求继续执行“审查 -> 修复 -> 复验”循环，直至第五轮纯审查无可操作发现。旧赛绩迁移与运行期现在从 `record.source_name` 或 `raw_payload/source_refs` 的 `source/source_name/provider/adapter` 推导有效来源命名空间，来源身份统一去空格并 `casefold()`，external ID 统一字符串化并去首尾空格；来源名只存在证据中的旧记录可被唯一接管，同 external identity 多条旧记录在 importer 和后台编辑路径都会阻断写入。P0 队列不再按完整度字符串排序，而使用明确资料缺口等级；同等级再综合人工标记、待处理候选、近 30 天已发布新闻、重点赛事证据、非空外部身份和术语优先级，并把在役过期、退役同步落后和未知生涯状态的 full profile 放入刷新层。旧规格流程 `3.4` 在排序信号补齐后保持完成，尚无五地区 adapter/artifact 完整测试的 `6.2` 已恢复未完成。最终术语解析/旧马匹页/P0 定向回归 `104` 项通过；完整 `stable` 回归 `581` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败；Django check、迁移一致性、旧规格流程 strict/all 和 `git diff --check` 通过。尚未提交或部署。

`2026-07-08` 已完成马匹详情页 MVP 线上浏览器验收。本次先尝试 Codex 内置浏览器访问生产页，但两次打开 `http://umafans.run/horses/` 超时；随后使用系统 Chrome headless 生成真实桌面/移动截图与 CDP 布局指标，截图保存在本地 `/tmp/umanews-horse-acceptance/`。公网复核显示 `http://umafans.run/healthz/`、`/horses/`、`/horses/follows/` 均返回 `200`，草稿样例 `/horses/1/` 返回 `404`，未登录 `/admin/horse-profiles/` 返回 `302` 到登录页，符合“P0 马默认草稿、后台审核后才公开”的策略。Chrome 验收确认桌面 `/horses/`、移动 `/horses/`、移动首页和移动草稿 404 页没有页面级横向溢出，导航 DOM 中包含“马匹”和“我的关注”；`/horses/?q=test&region=japan` 保留搜索词并正确激活日本筛选。已发现两个体验问题：`/horses/` 空状态文案仍显示“目前还没有已发布文章。”，语义应改为马匹资料；移动端顶部导航和地区筛选依赖横向滑动，功能可用但“马匹 / 我的关注”和最右侧“美国”不够显眼。因生产当前 `published=0`，未发布任何马匹详情，故无法在不改生产数据的前提下完整验收已发布详情页、关注按钮 POST、新闻详情马匹 tag 和关注新闻流；staff 后台列表/详情也因没有登录态仅验收到未登录跳转。UmaNews 生产 SSH 只以 `root@47.239.167.86` 为准，不使用其他项目服务器。

`2026-07-07` 旧规格流程 change `hkjc-ja-alias-article-backfill` 已完成实现并部署生产。新增 `stable.services.term_maintenance`、`merge_hkjc_ja_aliases` 和 `backfill_article_terms`，用于处理 HKJC 日本马日语 alias 概念合并，以及已发布文章中文字段的术语精确回填。概念合并默认 dry-run 输出 `merge_plan.json` / review CSV / summary，正式写入必须使用已审核 `--plan-file`；apply 会重新校验 active owner 占用，只合并同类型、同中文目标、active 日语主术语的安全项，并将冗余日语主术语停用，notes 中记录 `hkjc_ja_alias_merged_into_term_id=<target>`。这也是术语库中一部分 inactive 术语的合理来源：它们不是删除，而是被更完整的正式概念吸收后的历史主术语。文章回填默认只扫描已发布文章，输出完整 before/after JSON 与人工 review CSV；正式写入必须使用已审核 `--diff-file`，或显式提供 term/article/date/source/limit 过滤范围，且默认跳过 `manually_edited_fields` 中的发布字段，不重新翻译、不调用 AI 改写、不改变发布、审核、workflow 或 QQ 推送状态。本地验证已通过 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`（最终 `473` 项）、`旧规格流程 validate hkjc-ja-alias-article-backfill --strict` 和 `git diff --check`。生产服务器 `/opt/umanewsbot` 已部署到 `a65c1ed`；部署前备份 `.env` 为 `.env.backup.hkjc-ja-alias-backfill-20260707_184118`，数据库备份为 `backups/db/pre-hkjc-ja-alias-backfill-20260707_184118.sql.gz` 且 `gzip -t` 通过。生产 HKJC alias dry-run 为 `candidate=112 skipped=0`，正式 apply 写入 `112` 条日语 alias 并停用 `112` 条冗余日语主术语；post-apply smoke 为 `candidate=0 scanned=0`。文章回填 dry-run 扫描 `713` 篇日文已发布文章，命中 `7` 篇，计划更新 `29` 个字段、跳过 `2` 个人工字段；正式 apply 为 `updated=29 skipped=2 stale=0`。artifact 已复制到生产宿主机 `runtime/term_backfills/hkjc-ja-article-backfill-20260707_192910/`、`runtime/term_backfills/hkjc-ja-article-backfill-apply-20260707_192931/`、`runtime/term_backfills/hkjc-ja-alias-merge-postapply-smoke-20260707_192810/`。抽检确认 `Kalamatianos / カラマティアノス -> 欢快舞步` 为日本地区 active term `6443` 的 active EN/JA alias，`/news/7117/` 返回 `200` 且页面包含 `欢快舞步`；生产 `manage.py check`、本地和公网 `/healthz/` 均通过。

`2026-07-07` 本地已实现并准备上线 旧规格流程 change `expand-france-news-sources`。该变更为法国新增 `tdn_france_broad` 英文补充来源：使用 TDN 公开 WordPress 搜索 API 聚合 `French racing`、`ParisLongchamp`、`Deauville`、`Chantilly` 等关键词，`canonical_source_site=tdn`，通过 URL / source_article_id 复用既有 TDN 去重，默认 `enabled=false`、`production_approved=false`，需灰度启用后才进入生产抓取。真实只读探测显示 `tdn_france_broad` accepted：HTTP `200`、列表 `20` 条、详情样本 `2` 条、最大正文长度 `12735`、重复数 `0`；`at_the_races_france` 当前仍因 HTTP `403 / Client Challenge` 标记为 deferred/access_limited，不生产批准。探测命令已输出 `status/deferred_reason/http_status/final_url/parse_quality/duplicate_ratio/query_errors/sample_errors`，并支持多关键词来源在部分关键词失败时记录 `query_errors`、单篇详情样本失败时记录 `detail_error_count` 后继续采样后续文章；国际新闻来源生产抓取已改为“单篇详情解析失败则跳过并继续处理其他文章，全部详情都失败才将来源标记为 failed”，避免一篇坏详情拖垮整轮来源或把全失败伪装成无新稿。来源同步新增 `MULTIREGION_SUPPORTED_PRODUCTION_SOURCE_LANGUAGES=ja,en,zh-hant` 保护，法语源即使误配置 production approved 也会降级为未批准并写 `source_language_not_supported`；法国审计摘要可区分成功无新增、解析失败来源 ID、门禁 blocker 和示例文章。

`2026-07-07` 本地已实现并准备上线 旧规格流程 change `fix-english-term-gate-region-filter`。该变更针对香港、英国、美国等英文新闻被 `core_term_missing` 大量误挡的问题：英文发布校验第一版只检查文章同地区术语和 `racing_region=""` 全局术语；`class/content/link/agent/oaks/america/numbers` 等配置化高歧义英文词会降级为 warning，不再默认生成硬 blocker；未配置的短词 / 全大写词只有在非核心命中时才会派生降级，真正同地区 / 全局高可信核心马名、赛事名等缺失仍会阻断自动发布。新增 `reprocess_term_gate_blocked_articles` 管理命令，可对最近发布候选回看窗口内、因术语 blocker 进入人工审核的文章执行 dry-run 或 commit 重校验，commit 只会重新进入 `publish_ready` 候选并写 `ranked_revived_at`，不会直接公开发布文章。生产审计摘要已增加 `articles.gate_issues`，用于区分真实 blocker、高歧义降级和地区排除。上线后需只读验证香港、英国、美国最近窗口的 `core_term_missing` blocker、`publish_ready` 和公开数量。

`2026-07-07` 旧规格流程 changes `expand-france-news-sources` 与 `fix-english-term-gate-region-filter` 已部署生产。生产因 GitHub HTTPS 连接超时，改用本地 `git bundle` 将提交 `bfc3445` 传入 `/opt/umanewsbot` 并 fast-forward 部署；部署前数据库备份为 `backups/db/pre-france-source-term-gate-20260707_200124.sql.gz`，已执行 `gzip -t`。部署后 `web / worker / beat / db / redis / nginx` 正常，`manage.py check` 通过，本地与公网 `/healthz/` 均返回 `200`。`tdn_france_broad` 生产只读探测 accepted：HTTP `200`、列表 `20` 条、详情样本 `5` 条、详情错误 `0`、重复 `0`；已在生产启用 `NewsSource#21`，设置 `enabled=true`、`production_approved=true`、`effective_crawl_interval_minutes=15`，并把 `tdn_france:access` 与 canonical 入库后的 `tdn:access` 加入 `MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES`。真实人工抓取验证因中途补生产配置重启被打断，已入库法国新来源文章 `7250-7253` 共 `4` 篇；中断的人工 `CrawlJob#9330` 已标记为 failed 并记录 `success_count=4`，错误说明为部署配置重启中断，不代表来源失败。4 篇均已补翻译并重新跑自动化，当前均为 `manual_review_required / pending_review`：其中 `7250-7252` 因真实 `core_term_missing` blocker 转人工，`7253` 因总分 `69` 转人工。最终审计文件位于生产容器 `runtime/multiregion_audit/post-france-source-term-gate-final-20260707_202851.json`：法国来源总数 `4`、启用 `3`、生产批准 `3`、paused/backoff 均为 `0`，今日法国新入库 `4`、公开 `0`，公开为 0 的原因是正常门禁转人工而非抓取或来源白名单失败。英文门禁重处理 dry-run：香港、美国、法国最近 3 小时无可释放 `core_term_missing` 候选；英国有 `1` 篇候选但仍被真实核心术语缺失阻断，未执行 commit。

`2026-07-07 21:00` 线上回归复核：生产仓库 `HEAD=dcb9b90`，容器运行正常，`manage.py check`、本地/公网 `/healthz/`、首页和 `/admin/login/` 均通过；生产开关 `MULTIREGION_PRODUCTION_WINDOWS_*`、`NEWS_SOURCE_POLL_ENABLED` 均为开启，`tdn:access` 与 `tdn_france:access` 均在自动发布来源白名单中。法国新来源 `tdn_france_broad` 再次只读探测 accepted，HTTP `200`、列表 `20`、详情样本 `2`、详情错误 `0`，重复率 `0.5` 是因为自然抓取已写入同批文章。自然窗口已派发 `CrawlJob#9355`，截至复核时仍为 `started`，但已通过 `source_config=21` 入库 `10` 篇法国文章，其中 `9` 篇已翻译、`1` 篇翻译中；Celery active 显示该 crawl task 正在 worker 内运行，worker 日志持续出现 SiliconFlow `200 OK`，因此判断为“单轮处理耗时偏长但仍在推进”，不是来源不可用。最近 90 分钟五地区发布/QQ 窗口均为 succeeded，0 结果均有 `no_ready_candidates / no_eligible_articles / already_sent` 等原因；英文门禁 dry-run 复核为香港/美国无候选、英国 `7242` 仍真实 blocker、法国 `7250/7251/7252` 仍真实 blocker，无可释放误挡文章。

`2026-07-07` 发现法国新来源 `tdn_france_broad` 抓入历史旧文并有旧文自动发布。根因是 TDN `/wp-json/wp/v2/search?search=French%20racing` 返回按相关性排序的历史搜索结果，search item 只有 `id/title/url`，没有 `date/date_gmt`；当前 adapter 复用 `TDNAdapter._api_datetime()`，在缺少日期时兜底为 `timezone.now()`，而详情页解析也未纠正为真实发布时间，导致 2020/2022/2023/2024 旧文被写成 `2026-07-07T14:05:04Z` 并进入发布窗口。已立即暂停生产 `NewsSource#21`：`enabled=false`、`production_approved=false`，`manual_pause_reason=paused 2026-07-07: TDN search endpoint returned historical articles without dates; old articles were stamped as current`。已确认公开受影响旧文包括：`7255` 实际 `2022-03-21`，`7263` 实际 `2020-04-07`，`7264` 实际 `2020-03-16`，`7265` 实际 `2020-03-13`，`7271` 实际 `2024-11-08`。后续修复应改为从 search item 的 `_links.self` / post `id` 二次读取 `/wp-json/wp/v2/posts/<id>` 的真实 `date_gmt`，并在 adapter 或生产抓取层丢弃超过允许新鲜度窗口的文章；修复前不要重新启用该来源。

`2026-07-04` 旧规格流程 change `race-event-page-mvp` 已按已确认 Stitch 原型完成赛事日历 / 年度赛事详情页 MVP，并已部署生产。新增 `RaceEvent` 产品层模型、别名、出马表、赛果、历史冠军、候选资料和 `ArticleRaceLink`；公开入口为 `/races/` 与 `/races/<year>/<slug>/`，文章详情页会展示已确认关联赛事；业务后台新增 `/admin/race-events/`，支持赛事列表筛选、详情维护、候选资料应用、手动关联/移除新闻和人工移除保护。管理命令新增 `import_race_events`、`fetch_race_event_candidates` 和 `research_live_race_fields`，样例 CSV 位于 `server/stable/data/race_events_seed_sample.csv`。本地 code review 后已修复后台赛事列表筛选翻页丢参问题，并补充回归测试。生产服务器 `/opt/umanewsbot` 已部署提交 `f3c4c46`，迁移 `stable.0020_raceevent_articleracelink_raceeventalias_and_more` 已应用；已正式导入 5 条 P0/P1 赛事种子和 10 条别名，当前 `ArticleRaceLink=0`，后续新闻关联仍需自动匹配或人工维护。第一版不建设马匹数据库、完整赛果库、复杂赛事聚类或赛中实时进度。

`2026-07-04` 本次赛事日历 / HKJC overseas 术语种子上线前，本地验证已通过 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable --noinput`（442 项）、`旧规格流程 validate --all`（17 项）和 `git diff --check`。生产部署前确认没有正在运行的外部数据导入和导入锁；备份 `.env` 为 `.env.backup.race-calendar-hkjc-overseas-20260704_182412`，数据库有效备份为 `backups/db/rds_horse_news_race_calendar_manual_20260704_182458.sql.gz` 并通过 `gzip -t`。部署后 `manage.py check` 通过，`showmigrations stable` 显示 `[X] 0020_raceevent_articleracelink_raceeventalias_and_more`，`web / worker / beat / db / redis / nginx` 均运行，`/healthz/`、`/races/`、`/races/2026/takarazuka-kinen/` 和 `/admin/login/` 均返回 `200`，未登录 `/admin/race-events/` 返回 `302` 到登录链路。生产容器内 HKJC overseas fixture smoke 生成 `candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`，输出目录为 `runtime/termbase_seed/hkjc-overseas-deploy-smoke-20260704_183048`；本次未把 HKJC overseas 候选导入正式术语库。

`2026-07-06` 已按“赛事日历正式填充前先线上验收、再给示例审核”的节奏完成第一步。生产 `/opt/umanewsbot` 当前 `HEAD=c996621`，`web` healthy，`worker / beat / db / redis / nginx` 正常；公网 `umafans.run/healthz/`、`/races/` 与 `/admin/login/` 均返回 `200`，`manage.py check` 通过，`stable.0020_raceevent_articleracelink_raceeventalias_and_more` 已应用。生产当前赛事模块计数为 `RaceEvent=5`、`RaceEventAlias=10`、`RaceEventRunner=0`、`RaceEventResult=0`、`RaceEventDataCandidate=0`、`ArticleRaceLink=0`，五地区各 1 条样例赛事，`ExternalDataImportRun(status="started")=0` 且导入锁为空。已从 JAIRS/JRA 官方英文页抓取 `2025 Japan Cup` 赛后样例审核包，路径为 `runtime/race_event_review_samples/japan-cup-2025-20260706/`，包含 `race_events_sample.csv`、`race_event_candidate_payload.json`、`source_official.html` 和 `README.md`；该样例为日本 G1、非 listed、非地区重赏，解析出基础资料 1 组、出走表 17 匹、正式完赛赛果 16 条。`import_race_events --dry-run` 对该 CSV 通过，候选 JSON 通过 JSON 校验。本次未写生产库；示例中 `visibility_status=draft`，且术语库/官方中文未命中 `Japan Cup` 与 `Tokyo Racecourse` 时按约定保留原文，等待人工审核补全。

`2026-07-06` 赛事日历正式填充已开始写生产库。按用户要求优先使用本地语言官方源：日本批次改用 JRA 日文重赏一覧 `https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html`，生成并导入 `runtime/race_event_imports/2026/japan-jra-central-graded-20260706/race_events_japan_jra_2026.csv`；范围为 2026 年 JRA 中央 G1/G2/G3/J-G1/J-G2/J-G3，不含 Listed/Open 和地方交流重赏，生产导入结果为 `created=139 updated=1 aliases=413`，其中 `宝塚記念` 更新原样例 `takarazuka-kinen`，当前 `japan/year=2026` 共 `140` 场，状态分布 `finished=74`、`scheduled=66`。香港批次使用 HKJC 繁中官方源 `https://racing.hkjc.com/zh-hk/international-racing/g2-g3-races/index` 与 `https://campaigns.hkjc.com/racing-event-hub/ch/`，并用 HKJC 本地赛果页补马场、距离和场地，生成并导入 `runtime/race_event_imports/2026/hong-kong-hkjc-pattern-20260706/race_events_hong_kong_hkjc_2026.csv`；范围为 HKJC 当前公开 2025/26 马季内日期落在 2026 年的香港 G1/G2/G3，共 `19` 场，已过滤非单场赛事卡片 `沙田煞科日`，不猜测尚未由 HKJC 公开 2026/27 日期的 2026 年末香港国际赛。香港导入结果为 `created=19 updated=0 aliases=74`；生产当前 `RaceEvent=163`、`RaceEventAlias=497`、香港 2026 共 `20` 条，其中 `19` 条为本批 HKJC 官方源，另 `1` 条为既有香港杯样例。日本与香港详情页均已通过公网 Host 验收；香港默认重点日历页因只显示当前前后 30 天且过滤 P2，需用 `tab=all` 或 `direction=past` 查看本批历史赛事。

`2026-07-06` 继续补齐 2026 目标地区重要赛事并写入生产。日本地方/交流ダートグレード使用 NAR 官方 `https://www.keiba.go.jp/dirtgraderace/2026/racelist/index.html` 与官方 PDF `https://www.keiba.go.jp/pdf/uploads/20251110_01_01.pdf`，导入地方竞马场 JpnⅠ/JpnⅡ/JpnⅢ 与大井东京大赏典 GⅠ 共 `46` 场，结果 `created=46 updated=0 aliases=105`；其中 `22` 场官方给出发走时刻，`24` 场日期确定但时刻待定，前台详情页已验证帝王赏显示 `20:05`、东京大赏典显示“待定”。为支持美国 all-weather/synthetic 赛事，已新增 `RaceEventSurface.SYNTHETIC=synthetic/复合赛道` 并部署生产 `9dc9b4d`，迁移 `stable.0021_alter_raceevent_surface` 已应用。美国使用 TOBA 官方 `https://toba.org/graded-stakes/2026-races/`，导入 2026 American Graded Stakes 表内 Grade 1/2/3 共 `411` 条，结果 `created=411 updated=0 aliases=1550`；其中 `370` 条有日期并公开展示，`41` 条空日期或 `not run` 作为 draft 底表记录保留，Listed `200` 条与其他非分级黑体 `12` 条已排除，Jeff Ruby Steaks 已验证显示“复合赛道”。英国当前可靠导入 BHA Jump 官方 `British_Jump_Pattern_Listed_2526.pdf` 中 2026 年 1-4 月 Grade 1/2 共 `64` 场，结果 `created=64 updated=0 aliases=192`；英国 Flat 官方 2026 PDF 正文页文字层为空，仍需 OCR 或另一官方结构化源；Jump 2026 年 10-12 月需等待 2026/27 官方书或其他官方源。法国使用 France Galop 官方 `groupes_listed_plat_2026_v7.pdf` 与 `groupes_listed_obstacles_2026_v4.pdf`，按逐赛条件页导入 Groupe I/II/III 共 `173` 条，结果 `created=173 updated=0 aliases=519`，其中 Flat `113`、障碍 `60`，Listed 已排除；Prix Ganay 与 Grand Steeple-Chase de Paris 详情页已验证。生产当前 `RaceEvent=857`、`RaceEventAlias=2863`；2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `65`、法国 `174`。剩余缺口主要是香港 2026 年末 HKJC 尚未公开赛期、英国 Flat 2026 官方 PDF 需要 OCR/结构化替代源、英国 Jump 2026 年 10-12 月官方赛季书未确认。

`2026-07-06` 已继续补上英国 Flat Group 赛事。BHA 官方 `British_Flat_Pattern_Listed_2026.pdf` 正文页无可用文本层，本次使用 macOS Vision OCR 识别官方详情页，生成 `runtime/race_event_imports/2026/united-kingdom-bha-pattern-20260706/race_events_united_kingdom_bha_flat_2026.csv`；范围为英国 2026 Flat `Group 1/2/3`，排除 Listed，共 `138` 场，等级分布 `G1=33`、`G2=42`、`G3=63`，其中 `59` 场按当前日期归为 `finished`、`79` 场为 `scheduled`，复合赛道 `6` 场、草地 `132` 场。距离字段来自 OCR，已对明显残缺值做清理并保留 `data_quality_status=partial`；赛事名、日期、场地和等级来自官方详情页。生产导入前备份为 `backups/db/pre-race-events-uk-bha-flat-2026-20260706_222151.sql.gz`，约 `74M`，`gzip -t` 通过；生产 dry-run 通过后正式导入 `created=138 updated=0 aliases=414`。导入后生产 `RaceEvent=995`、`RaceEventAlias=3277`，2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `203`、法国 `174`；英国 Flat 页面验收 `/races/2026/uk-bha-flat-2026-0704-058/` 显示 `CORAL-ECLIPSE`，复合赛道样例 `/races/2026/uk-bha-flat-2026-0905-102/` 显示 `UNIBET SEPTEMBER STAKES` 与“复合赛道”。当前剩余缺口收敛为：HKJC 尚未公开 2026/27 马季年末香港本地 G1/G2/G3 日期明细；英国 Jump 2026 年 10-12 月需等待 2026/27 官方书或其他官方结构化来源。

`2026-07-06` 已开始正式填充 2026 赛事详情表，第一批完成 JRA 中央重赏已完赛场次的出走表和赛果。官方来源继续使用 JRA 日文重赏列表和各赛事结果页，产物位于 `runtime/race_event_detail_imports/2026/japan-jra-details-20260706/`，包括 `jra_detail_candidates_2026.jsonl`、`jra_detail_review_2026.csv`、`summary.json` 与页面缓存；生成结果为 `74` 场、`1112` 条出走表、`1106` 条数字名次赛果，另有 `取消=2`、`除外=2`、`中止=2` 保留在出走表状态中。生产写入前备份为 `backups/db/pre-race-event-details-jra-2026-20260706_224953.sql.gz`，约 `75M` 且 `gzip -t` 通过；生产 dry-run 确认 `events=74`、`runners=1112`、`results=1106` 后正式应用 `148` 个候选模块。第一次 apply 因 JRA 同着导致 `finish_position` 唯一约束冲突而中止，已将失败留下的 `1` 条旧 pending 候选标记为 `failed`；修正后用唯一排序位写入 `finish_position`，并在 `source_refs.official_finish_position` 保留 JRA 官方名次。导入后生产 `RaceEventRunner=1112`、`RaceEventResult=1106`、`RaceEventDataCandidate=192`、`AppliedCandidates=191`、`FailedCandidates=1`；宝塚記念详情页显示 `メイショウタバル`、出走表和赛果，安田記念同着马 `ワールズエンド` 与 `ガイアフォース` 前台均显示官方第 `2` 名。为让同着展示立即正确，已将 `views.py` 和两个公开模板热补丁复制进 `web` 容器并重启，同步本地代码已保留但尚未通过 git 镜像部署固化；后续正式部署或容器重建前必须先提交/部署该展示修复，避免热补丁丢失。

`2026-07-06` 已继续补齐日本 NAR/地方交流重赏当前官方可用详情。NAR 使用 `keiba.go.jp` ダートグレード特设页的 `racecard.html` 自动发现 `KeibaWeb/TodayRaceInfo/DebaTable`，已完赛赛事再跳转 `RaceMarkTable`；产物位于 `runtime/race_event_detail_imports/2026/japan-nar-details-20260706/`，包括 `nar_detail_candidates_2026.jsonl`、`nar_detail_review_2026.csv`、`summary.json` 与页面缓存。生成结果为 `21` 场、`256` 条出走表、`242` 条数字名次赛果；其中 `20` 场已完赛写入出走表和赛果，`2026-07-08` スパーキングレディーカップ已公布出走表但未有赛果，仅写入赛前出走表；后续 `25` 场仍停留在 `introduction.html` 且官方未公布出走表，记录为 `racecard_not_published`。生产写入前备份为 `backups/db/pre-race-event-details-nar-2026-20260706_232856.sql.gz`，约 `75M` 且 `gzip -t` 通过；dry-run 确认 `events=21`、`runners=256`、`results=242` 后正式应用 `41` 个候选模块。导入后生产详情表为 `RaceEventRunner=1368`、`RaceEventResult=1348`、`RaceEventHistoryWinner=0`、`RaceEventDataCandidate=233`、`AppliedCandidates=232`、`FailedCandidates=1`，全部详情行当前仍为日本地区。页面验收：`/races/2026/nar-dirt-2026-0701-20/` 显示帝王賞冠军 `ミッキーファイト`、出走表、赛果和 `2:02.8`；`/races/2026/nar-dirt-2026-0708-21/` 显示スパーキングレディーカップ出走表和 `レクランスリール / アピーリングルック`，未显示赛果区块。当前按用户指定顺序，日本 JRA/NAR 中“官方已公布的出走表/赛果”已补完；JRA 未来 66 场和 NAR 未来 25 场需等官方出走表或赛果发布后刷新。

`2026-07-06/07` 已继续补香港与美国 2026 已完赛重赏详情。香港使用 HKJC 繁中官方 `resultsall` 日汇总页定位 RaceNo，再进入单场 `localresults` 完整赛果页；产物位于 `runtime/race_event_detail_imports/2026/hong-kong-hkjc-details-20260706/`。生成并导入 HKJC 已公开 2026 本地 G1/G2/G3 `19` 场、`182` 条出走表、`181` 条数字名次赛果；`WV` 保留为 `withdrawn` 出走状态但不写赛果，马名/骑师/练马师展示字段已从繁中转简体，原始繁中保存在 `source_refs`。生产写入前备份为 `backups/db/pre-race-event-details-hk-2026-20260706_234317.sql.gz`，约 `75M` 且 `gzip -t` 通过；dry-run 通过后正式应用 `38` 个候选模块。页面验收：`/races/2026/hkjc-2026-0125-05/` 显示董事杯冠军 `浪漫勇士`、完整出走表和赛果，`祝愿 / 阳光勇士` 同为官方第 `4` 名且时间 `1:33.18`；`/races/2026/hkjc-2026-0621-19/` 显示精英碟出走表中 `非惟侥幸` 为取消出走，赛果只保留 `11` 条已确认名次。

美国使用 TOBA 官方分级赛表确定 2026 已完赛范围，并以 TOBA `chart_url` 中的官方 RaceNo 辅助匹配 Horse Racing Nation track-day 页面；Equibase chart HTML/PDF 当前仍返回防护页，因此 HRN 仅作为可访问公开结果源。产物位于 `runtime/race_event_detail_imports/2026/united-states-hrn-details-20260706/`。生成并导入美国 TOBA Grade 1/2/3 已完赛 `195` 场、`1710` 条出走表、`1448` 条可确认赛果；马名展示字段已剥离 `(IRE)/(GB)/(SAF)` 等国籍后缀，原始写法保存在 `source_refs.horse_name_raw`。HRN 对 Kentucky Derby / Kentucky Oaks 等少量大赛页当前只公开出走表、不公开 payout/also-rans 结果块，本批不从 TOBA winner 字段猜完整名次，因此这些赛事可显示出走表但暂无赛果。首次 apply 因 HRN HTML 重复渲染同一出走马导致唯一马号冲突中止，已将旧 pending 候选标记为 failed，并在生成器中按 `horse_number + horse_name + horse_url` 去重后重跑成功。生产写入前备份为 `backups/db/pre-race-event-details-us-hrn-2026-20260707_000230.sql.gz`，约 `75M` 且 `gzip -t` 通过；最终正式应用 `390` 个候选模块。导入后生产详情表为 `RaceEventRunner=3260`、`RaceEventResult=2977`、`RaceEventHistoryWinner=0`、`RaceEventDataCandidate=992`、`AppliedCandidates=990`、`FailedCandidates=2`、`PendingCandidates=0`；其中美国详情为 `1710` 条出走表和 `1448` 条赛果。页面验收：`/races/2026/us-toba-2026-0108-001/` 显示 Robert J. Frankel S. 冠军 `Paradise Lake`、出走表和赛果；`/races/2026/us-toba-2026-0502-119/` 显示 Kentucky Derby 出走表但因 HRN 未公开结果块暂不显示赛果。当前顺序进度为日本、香港、美国已完成当前可用详情，下一步继续英国、法国，再处理历届冠军。

`2026-06-27` 全球赛马数据库接入当前处于能力确认完成状态：香港 HKJC 已有生产真实 dry-run 批次证据，英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 已完成少量真实 proof，证明四地公开入口、parser/importer、马匹详情链路、低频限量抓取和 proof-only 离线审计可用。用户已将本目标完成口径调整为“先保证所有地区的数据爬取能力真实可用”，不再要求本目标内完成最近 2 个月完整大量爬取或生产真实网络 commit。当前主工作树已同步外部缓存底座、HKJC、UK/France/US importer、fixtures、旧规格流程 归档和 proof JSON，用于后续恢复；这些同步内容仍是未提交工作树差异。交接索引见 `docs/global_racing_database_handoff.md`。

同步后本地验证已覆盖 Django check、外部缓存底座、HKJC、UK/France/US importer、global racing isolation、proof-only 离线审计测试、旧规格流程 全量校验和 `git diff --check`；离线 commit 候选审计已加严为要求 plan-only 具备请求证据和成功响应，非 plan 批次具备请求证据、成功响应和非空 `races/entries/results/horses` coverage；四地 importer 的生产写库门禁已加严为只有 `completion.is_complete=true` 的严格布尔完成证明、completion 内部无受限停止或马匹详情缺口、completion 内含可解析 `unique_horses_found` / `horse_profiles_fetched` 计数、且 payload 具备非空 `races/entries/results/horses` coverage 时才允许 commit。HKJC、UK、France Geny、US 的 plan-only 命令均要求显式 `--allow-network`，避免误把最近 60 天拆批计划当成本地无网络操作；新增 `render_global_racing_batch_command` 只读命令，可从 plan JSON 渲染指定批次或全部批次的精确 dry-run/commit 命令，并可根据 `--output-dir` 给出稳定 `suggested_output_path` 和可直接执行的 `tee_command_line`，减少手工复制 `race_ids`、`race_urls` 或 `partants_urls` 以及覆盖批次 JSON 的风险，离线审计会忽略这类命令清单 artifact。详见 `docs/global_racing_database_handoff.md`。当前同步范围清单见 `docs/global_racing_sync_manifest.md`。

`2026-07-03` 生产只读核对多地区术语库与外部马名索引：服务器 `/opt/umanewsbot` 当前 `HEAD=4323d32`，`web/worker/beat/db/redis/nginx` 均在运行。正式术语库 `TermEntry=2054`，全部为 `source_language=ja`，其中 `horse=1884`、`race=153`、`fixed_phrase=15`、`jockey=2`，`TermAlias=2057` 也全部为日文；正式术语的 `racing_region` 仍为空，尚未形成香港、英国、法国、美国分地区正式术语内容。术语候选池 `TermCandidate=3519`、证据 `13725`，当前同样全部为日文候选。外部马名索引 `ExternalHorseAlias=12425`，其中日本 `netkeiba/ja=12421`；香港 HKJC 只有小样本 `en=2`、`zh-hant=2`。外部缓存表中日本仍是主体：`ExternalHorse=12405`、`ExternalRace=4099`、`ExternalRaceEntry=60838`、`ExternalRaceResult=56882`；香港仅有 sample commit 级别的 `ExternalHorse=2`、`ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`；英国、法国、美国当前生产 `External*` 表无写入。结论：多地区新闻源与语言/地区处理链路已上线，但正式术语内容和外部马名识别数据厚度仍明显以日本为主，英法美仍停在 proof/代码能力而非生产数据沉淀。

`2026-07-04` 旧规格流程 change `prepare-termbase-seed-data` 已完成实现、验证和归档，归档目录为 `旧规格流程/changes/archive/2026-07-03-prepare-termbase-seed-data`，正式规格已同步到 `旧规格流程/specs/termbase-seed-data-preparation/spec.md`，并在 `旧规格流程/specs/termbase-and-race-priority/spec.md` 追加“术语种子候选兼容正式术语导入”要求。本地首版已实现 `prepare_termbase_seed_data` 管理命令与 `stable.services.termbase_seed` 服务层，可从 HKJC/WP Stud fixture 或低频触网入口生成 `seed_candidates.csv`、`seed_conflicts.csv` 和 `summary.json`；内置 fixture smoke 生成 `10` 条候选与 `1` 条冲突，香港候选优先、日本候选最后，中文目标译名经 OpenCC 简体化。该能力边界是从 HKJC 体系和 WP Stud 准备第一批人工审核 CSV：`seed_candidates.csv` 严格兼容现有 `import_terms` 字段，`seed_conflicts.csv` 记录译名冲突；第一版不直接写生产 `TermEntry`、不触发翻译、发布或 QQ 推送。审查后已明确首版不做 HKJC `racecards` PDF/排位表全量抽取，必须先做 HKJC/WP Stud source discovery，默认输出到 `runtime/termbase_seed/<timestamp>/`，并要求网络失败摘要、繁简转换依赖落地和后台术语导入模板同步更新。代码审查修复已将命令内置 dry-run 预检调整为与 `import_terms` 默认一致的 `upsert`，并确保触网达到 `max_requests` 后停止所有后续来源。`2026-07-06` 本地 review 返修进一步修复 `SeedNetworkClient` 的 GET/POST 重试计数：失败重试尝试也会立即写入 request 明细并计入 `--max-requests`，避免超出请求预算，原始 timeout 错误保留在 `summary.requests`；同时为 HKJC/QIDS 马匹候选引入 `source:type:id` 全局实体 key，避免英文同名马误合并，IRE/CAN 等未建模地区保持 `other`，候选证据合并时每条最多保留 `10` 个 evidence sample。上线前本地验证已通过：`TermbaseSeedDataPreparationTests` 6 项、`stable` 全量 354 项、fixture smoke、`旧规格流程 validate --all` 和 `git diff --check`；本次 review 返修后追加验证 `TermbaseSeedDataPreparationTests` 21 项、`manage.py check`、`旧规格流程 validate --all` 和 `git diff --check` 通过。返修提交 `4b6e840` 已部署生产，部署前备份 `.env.backup.harden-hkjc-termbase-20260706_043557` 与 `backups/db/pre-harden-hkjc-termbase-20260706_043557.sql.gz`（约 `71M`，`gzip -t` 通过）；部署后 `/healthz/`、`manage.py check`、`/`、`/races/`、`/admin/login/` 和公网 `umafans.run/healthz/` 均通过。生产 fixture smoke 输出 `candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`、`incomplete=false`，QIDS 同英文名加拿大马 smoke 已确认不会误合并。本次未导入正式术语，生产计数保持 `TermEntry=15321`、`TermAlias=15537`。

`2026-07-04` 术语种子数据准备已部署生产。服务器 `/opt/umanewsbot` 从 `4323d32` 快进到 `e81733f`，部署前备份 `.env` 为 `.env.backup.termbase-seed-20260704_012005`；因新增 `opencc-python-reimplemented==0.1.7`，本次重建并重启 `web / worker / beat`。部署后迁移显示 `No migrations to apply`，`manage.py check` 通过，生产容器内 fixture smoke 输出 `candidate_count=10`、`conflict_count=1`、`incomplete=false`、`dry_run_error_count=0`，首条候选为 `BEAUTY GENERATION`，末条为 `ディープインパクト`；本地和公网 `/healthz/` 均返回 `200`。本次未导入正式术语，不修改 `TermEntry`、`TermAlias`、`TermCandidate` 或外部马名索引。

`2026-07-04` 已正式导入第一批人工认可格式的术语种子候选。导入文件为生产生成并回传审核的 `imports/termbase-seed-fixture-review-20260704_024950/seed_candidates.csv`；导入前数据库备份为 `backups/db/pre-termbase-seed-import-20260704_030722.sql.gz`，`gzip -t` 校验通过。`import_terms --dry-run` 显示总计 `10` 条、 新增 `8` 条、更新 `2` 条、错误 `0` 条；正式导入结果为新增 `8` 条、更新 `2` 条、跳过 `0` 条。生产正式术语从 `TermEntry=2054` 增至 `2062`，`TermAlias=2057` 增至 `2068`；新增英文术语 `8` 条，日文术语仍为 `2054` 条，其中 `グランアレグリア` 与 `ディープインパクト` 是既有日文术语更新。新增英文术语包括 `BEAUTY GENERATION -> 美丽传承`、`KA YING RISING -> 嘉应高升`、`ROMANTIC WARRIOR -> 浪漫勇士`、`Hong Kong Cup -> 香港杯`、`Zac Purton -> 潘顿`、`John Size -> 蔡约翰`、`Sha Tin -> 沙田马场`、`Declared Starter -> 宣布出赛马匹`。本批首次导入时地区证据只保留在 `notes`，随后已用模型合法地区值执行补写 upsert：备份 `backups/db/pre-termbase-seed-region-upsert-20260704_031950.sql.gz`，短码 `hk/jp` dry-run 因地区不合法被阻断且未写库，改用 `hong_kong/japan` 后 dry-run 为 `10` 条更新、`0` 错误，正式 upsert 为 `10` 条更新、`0` 跳过。补写后地区分布为 `en/hong_kong=8`、`ja/japan=2`、既有旧日文术语空地区 `2052`；公网 `/healthz/` 返回 `200`。

`2026-07-04` WP Stud 第一批全量审核候选已正式导入。已从可直接访问的 WP Stud 页面缓存并转换编码，输出 `runtime/termbase_seed/wpstud-full-review-20260704/seed_candidates.csv`、`seed_candidates_with_region.csv`、`seed_conflicts.csv` 与 `summary.json`；候选共 `210` 条，冲突 `0` 条，全部为 `term_type=horse`、`source_language=ja`、`source_tier=community`、`requires_review=true`，中文译名已转为简体。带地区版本统一设置 `racing_region=hong_kong`，用于描述香港或海外来港赛马候选；生产导入文件为 `/opt/umanewsbot/imports/wpstud-full-review-20260704/seed_candidates_with_region.csv`。本轮与 HKJC 500 条批次共用导入前备份 `backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`，`gzip -t` 校验通过；WP Stud 生产 `import_terms --dry-run` 为总计 `210` 条、新增 `210` 条、更新 `0` 条、错误 `0` 条，正式导入为新增 `210`、更新 `0`、跳过 `0`。HKJC 真实页面此前可访问但通用解析器拿不到候选；本地已补 HKJC 专用抽取路径，从 `selecthorse` 发现字母页、从字母页拿 `horseid + 英文名`，再抓繁中马匹详情页对齐中文名，并新增 `--limit-horses` 控制小批马匹数。本轮进一步新增 `--hkjc-letter`，用于按 A-Z 字母拆批抓取，避免无 checkpoint 的全量请求长时间运行。

`2026-07-04` 已开始 HKJC 正式术语候选抓取第一批。为避免后续再手工补地区，生成器已将 `racing_region` 加入 `seed_candidates.csv` 表头，并把 HKJC 候选输出为模型合法值 `hong_kong`。本地低频命令 `--source hkjc --allow-network --limit-pages 1 --limit-horses 100 --max-requests 130 --request-interval-seconds 2 --timeout-seconds 25` 输出到 `runtime/termbase_seed/hkjc-formal-review-20260704_100horses/`，结果为候选 `100` 条、冲突 `0` 条、请求 `103` 次且全部 `200`、`incomplete=false`；全部候选为 `term_type=horse`、`source_language=en`、`racing_region=hong_kong`、`source_tier=official`、`requires_review=false`，样例包括 `A AMERIC TE SPECSO -> 有财有势`、`A TIME FOR US -> 开心孖宝`、`ABSOLUTE AWAKENED -> 活力精神`。临时 SQLite 迁移库已对该 CSV 执行 `import_terms --dry-run`，结果为总计 `100` 条、新增 `100` 条、更新 `0` 条、错误 `0` 条；本批尚未导入生产正式术语库，也尚未部署 HKJC 抽取代码到生产。

`2026-07-04` HKJC 当前本地马官方译名已按 A-Z 字母拆批补齐并导入生产正式术语库。此前 `500` 匹审核包输出目录为 `runtime/termbase_seed/hkjc-formal-review-20260704_500horses/`，结果候选 `500` 条、冲突 `0`、请求 `509` 次全部 `200`、`incomplete=false`，并在生产 dry-run 后正式导入，导入前备份为 `backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`；该批正式导入新增 `500`、更新 `0`。随后发现无 checkpoint 全量命令运行过久，改为新增 `--hkjc-letter` 并按字母拆批：`I` 批候选 `28` 条，备份 `backups/db/pre-hkjc-letter-I-term-import-20260704_185212.sql.gz` 后导入新增 `28`；`J` 批候选 `23` 条，备份 `backups/db/pre-hkjc-letter-J-term-import-20260704_185400.sql.gz` 后导入新增 `23`；`K-Z` 合并候选 `701` 条，生产 dry-run 为新增 `699`、更新 `2`、错误 `0`，备份 `backups/db/pre-hkjc-letters-K-Z-term-import-20260704_191425.sql.gz` 后正式导入；`A-H` 复跑合并候选 `505` 条，生产 dry-run 为新增 `5`、更新 `500`、错误 `0`，备份 `backups/db/pre-hkjc-letters-A-H-term-import-20260704_192843.sql.gz` 后正式导入。导入后生产 `TermEntry=3527`、`TermAlias=3743`，`source_language=en/racing_region=hong_kong` 合计 `1263` 条，其中 HKJC 当前本地马英文术语 `1258` 条；`source_language=ja/racing_region=hong_kong` 的 WP Stud 社区马名术语 `210` 条。公网 `/healthz/` 返回 `200`。当前完成的是 HKJC 当前本地马名单补齐，不等同于“香港赛事/骑手回溯到 2024-01-01”；赛事和骑手仍需从 HKJC Race Card/赛果链路另行抽取。

`2026-07-04` 已继续 HKJC 本地赛果回溯术语导入，用于补齐香港赛果中的历史马名、骑师名和赛事名。生成器新增 `--hkjc-local-results-start-date`、`--hkjc-local-results-end-date`、`--hkjc-local-results-skip-races` 与 `--hkjc-skip-horse-details`，并对 HKJC 赛日首页只直接展示第 1 场、链接从第 2 场开始的结构做了补抓；抓取时会同时请求 `en-us` 与 `zh-hk` 赛果页，对齐输出 `horse / jockey / race` 候选，中文目标译名转为简体。已正式导入 `2024-01` 至 `2024-07`、`2024-09` 至 `2025-07`、`2025-09` 至 `2026-07-04`；`2024-08` 与 `2025-08` 已逐日扫描且候选 `0`、失败 `0`，无需导入。`2024-07` 输出 `647` 条候选（`horse=575`、`race=49`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202407-term-import-20260704_211425.sql.gz` 后导入新增 `74`、更新 `573`；`2024-09` 输出 `626` 条候选（`horse=549`、`race=54`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202409-term-import-20260704_213327.sql.gz` 后导入新增 `62`、更新 `564`；`2024-10` 输出 `834` 条候选（`horse=735`、`race=75`、`jockey=24`），备份 `backups/db/pre-hkjc-local-results-202410-term-import-20260704_214522.sql.gz` 后导入新增 `104`、更新 `730`；`2024-11` 输出 `850` 条候选（`horse=757`、`race=69`、`jockey=24`），`2024-11-13 HV Race 7-9` 为 HKJC 双语空壳赛果页，已记录为 `skipped_races/local_result_not_available` 且不导入空数据，备份 `backups/db/pre-hkjc-local-results-202411-term-import-20260704_221006.sql.gz` 后导入新增 `97`、更新 `753`；`2024-12` 输出 `957` 条候选（`horse=832`、`race=78`、`jockey=47`），备份 `backups/db/pre-hkjc-local-results-202412-term-import-20260704_222551.sql.gz` 后导入新增 `135`、更新 `822`；`2025-01` 输出 `913` 条候选（`horse=804`、`race=78`、`jockey=31`），备份 `backups/db/pre-hkjc-local-results-202501-term-import-20260704_224151.sql.gz` 后导入新增 `73`、更新 `840`；`2025-02` 输出 `794` 条候选（`horse=703`、`race=60`、`jockey=31`），备份 `backups/db/pre-hkjc-local-results-202502-term-import-20260704_225443.sql.gz` 后导入新增 `38`、更新 `756`；`2025-03` 输出 `914` 条候选（`horse=803`、`race=78`、`jockey=33`），备份 `backups/db/pre-hkjc-local-results-202503-term-import-20260704_231134.sql.gz` 后导入新增 `30`、更新 `884`；`2025-04` 输出 `893` 条候选（`horse=782`、`race=78`、`jockey=33`），备份 `backups/db/pre-hkjc-local-results-202504-term-import-20260704_232559.sql.gz` 后导入新增 `58`、更新 `835`；`2025-05` 输出 `920` 条候选（`horse=816`、`race=79`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202505-term-import-20260704_234206.sql.gz` 后导入新增 `38`、更新 `882`；`2025-06` 输出 `826` 条候选（`horse=741`、`race=63`、`jockey=22`），备份 `backups/db/pre-hkjc-local-results-202506-term-import-20260704_235659.sql.gz` 后导入新增 `44`、更新 `782`；`2025-07` 输出 `675` 条候选（`horse=603`、`race=49`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202507-term-import-20260705_000915.sql.gz` 后导入新增 `19`、更新 `656`；`2025-09` 输出 `632` 条候选（`horse=560`、`race=49`、`jockey=23`），`2025-09-21 ST Race 9-10` 为 HKJC 双语空壳赛果页，已记录为 `skipped_races/local_result_not_available` 且不导入空数据，备份 `backups/db/pre-hkjc-local-results-202509-term-import-20260705_002604.sql.gz` 后导入新增 `17`、更新 `615`；`2025-10` 输出 `882` 条候选（`horse=786`、`race=73`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202510-term-import-20260705_004245.sql.gz` 后导入新增 `41`、更新 `841`；`2025-11` 输出 `933` 条候选（`horse=826`、`race=81`、`jockey=26`），备份 `backups/db/pre-hkjc-local-results-202511-term-import-20260705_010022.sql.gz` 后导入新增 `45`、更新 `888`；`2025-12` 输出 `912` 条候选（`horse=803`、`race=68`、`jockey=41`），备份 `backups/db/pre-hkjc-local-results-202512-term-import-20260705_011812.sql.gz` 后导入新增 `42`、更新 `870`；`2026-01` 输出 `978` 条候选（`horse=875`、`race=78`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202601-term-import-20260705_013522.sql.gz` 后导入新增 `28`、更新 `950`；`2026-02` 输出 `930` 条候选（`horse=836`、`race=69`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202602-term-import-20260705_015108.sql.gz` 后导入新增 `18`、更新 `912`；`2026-03` 输出 `944` 条候选（`horse=838`、`race=81`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202603-term-import-20260705_020814.sql.gz` 后导入新增 `18`、更新 `926`；`2026-04` 输出 `975` 条候选（`horse=859`、`race=83`、`jockey=33`），备份 `backups/db/pre-hkjc-local-results-202604-term-import-20260705_022703.sql.gz` 后导入新增 `41`、更新 `934`；`2026-05` 输出 `979` 条候选（`horse=873`、`race=80`、`jockey=26`），备份 `backups/db/pre-hkjc-local-results-202605-term-import-20260705_024451.sql.gz` 后导入新增 `33`、更新 `946`；`2026-06` 输出 `844` 条候选（`horse=757`、`race=63`、`jockey=24`），备份 `backups/db/pre-hkjc-local-results-202606-term-import-20260705_025830.sql.gz` 后导入新增 `20`、更新 `824`；`2026-07-01` 至 `2026-07-04` 输出 `310` 条候选（`horse=265`、`race=21`、`jockey=24`），备份 `backups/db/pre-hkjc-local-results-20260701-20260704-term-import-20260705_030505.sql.gz` 后导入新增 `5`、更新 `305`。以上新增批次生产 dry-run 均为错误 `0`，正式导入均为跳过 `0`。导入后生产 `TermEntry=5948`、`TermAlias=6164`，`source_language=en/racing_region=hong_kong` 合计中 `horse=2479`、`jockey=70`、`race=1132`，另保留既有 `fixed_phrase=1`、`racecourse=1`、`trainer=1`；`http://127.0.0.1/healthz/` 返回 `200`。当前 HKJC 香港本地赛果已回溯到 `2026-07-04`；仍需另行补 HKJC overseas 与 WP Stud 赛事/骑手缺口。

`2026-07-04` 已创建并完成 plan-eng-review 的 旧规格流程 change `prepare-hkjc-overseas-termbase-seeds`，用于把 HKJC overseas simulcast Race Card 扩展为海外马名、骑师和赛事名的官方中文术语种子来源。该 change 已完成 `proposal.md`、`design.md`、`tasks.md` 与 `termbase-seed-data-preparation` delta spec，并通过 `旧规格流程 validate prepare-hkjc-overseas-termbase-seeds --strict`；当前本地已完成代码侧实现，新增 `prepare_termbase_seed_data --source hkjc_overseas`、`--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>`、`--limit-meetings`、`--limit-races`，输出继续不写正式术语库、不写 `ExternalHorse`，并新增 `source_evidence.json` 记录 Race Card 参数、中英页面 URL、原始繁体、地区映射、horse profile 证据、跳过和失败原因。review 约束已落地：渲染 fallback 默认不引入生产浏览器硬依赖；若无可用渲染器或渲染后缓存，会记录 `render_fallback_unavailable` 并标记 `incomplete=true`。本地 fixture smoke 输出 `runtime/termbase_seed/hkjc-overseas-fixture-smoke-migrated/`，候选 `9` 条、冲突 `0`、`incomplete=false`、`dry_run_error_count=0`，并通过 `import_terms --dry-run`。后续 review 修复已明确术语种子冲突输出规则：同一实体如出现多个中文译名，`seed_candidates.csv` 只保留一个正式 `target_zh`，其他译名进入 `aliases_zh`，同时 `seed_conflicts.csv` 保留冲突证据。用户确认后已执行 HKJC overseas 低上限 live dry-run：命令使用 `--source hkjc_overseas --allow-network --limit-meetings 1 --limit-races 1 --max-requests 6 --request-interval-seconds 3 --timeout-seconds 15`，输出目录为 `runtime/termbase_seed/hkjc-overseas-live-smoke-20260704_174924/`；结果为候选 `0` 条、冲突 `0`、跳过 `0`、请求 `1` 次且入口页 `https://racing.hkjc.com/en-us/overseas/` 返回 `200`，但直接 HTML 未暴露 Race Card 链接，因此记录 `render_fallback_unavailable: no race card links in direct HTML`，`incomplete=true`，`dry_run_error_count=0`。这证明当前实现不会把 HKJC Next.js shell 误当作空数据成功；要批量取得海外 Race Card 正式候选，还需要后续补浏览器渲染缓存或解析 HKJC 前端 API。本能力尚未部署生产，live dry-run 也未写正式术语库。

`2026-07-05` HKJC overseas 术语批量回溯已通过本地 QIDS GraphQL 抽取和生产 `import_terms` 正式导入完成，覆盖 `2024-01-01` 至 `2026-07-04`。生成器新增 `--hkjc-overseas-start-date` 与 `--hkjc-overseas-end-date`，会从 HKJC overseas results 发现转播赛日，再通过 HKJC QIDS `raceMeetingProfile` 对齐海外 Race Card 的英文/繁中 `horse / jockey / race`；该本地代码尚未部署生产，但生成产物已用于生产导入。月度产物合并目录为 `runtime/termbase_seed/hkjc-overseas-qids-merged-20240101-20260704/`，原始行 `11633` 条、候选 `7691` 条、冲突 `3` 条，候选结构为 `horse=6481`、`jockey=847`、`race=363`。生产导入文件为 `/opt/umanewsbot/imports/hkjc-overseas-qids-merged-20240101-20260704/seed_candidates.csv`；导入前备份为 `backups/db/pre-hkjc-overseas-qids-term-import-20260705_040238.sql.gz` 并通过 `gzip -t`；生产 dry-run 为总计 `7691`、新增 `7688`、更新 `3`、错误 `0`，正式导入为新增 `7482`、更新 `209`、跳过 `0`。因当前正式术语 upsert 身份是 `term_type + source_language + source_ja`，不是按地区拆分，同名国际骑师会被后导入地区覆盖；已用 `runtime/termbase_seed/hkjc-local-jockey-region-restore-20260705/seed_candidates.csv` 对 HKJC 本地赛果骑师做地区恢复，备份 `backups/db/pre-hkjc-local-jockey-region-restore-20260705_040950.sql.gz`，dry-run 和正式导入均为 `69` 条更新、`0` 错误/跳过。恢复后 HKJC 本地赛果覆盖仍为 `en/hong_kong horse=2479, jockey=69, race=1132`，海外 HKJC 官方来源计数为 `7483`。

`2026-07-05` WP Stud 当前发现的马名、赛事、骑师和马场社区术语已补齐到正式术语库，但不覆盖 HKJC 官方主译名。此前 WP Stud 马名批次已导入 `210` 条 `source_language=ja/racing_region=hong_kong` 社区马名；本次继续抓取 WP Stud `Translation/Race` 下 `21` 个赛事页面、`Translation/jockey.htm` 和 `Translation/racecourse/RaceCourse.htm`，输出目录为 `runtime/termbase_seed/wpstud-race-jockey-racecourse-review-20260705/`，完整候选 `2095` 条、冲突 `17` 条、`incomplete=false`，其中 `race=1392`、`jockey=276`、`racecourse=427`。生产完整 dry-run 显示会新增 `1891`、更新 `204`、错误 `0`；其中 `204` 条更新主要命中 HKJC overseas/HKJC 官方术语，因此已过滤为 `seed_candidates_new_only.csv` 仅导入新增项，并把 `seed_candidates_skipped_existing.csv` 留作人工审核清单。过滤后生产 dry-run 为总计 `1891`、新增 `1891`、更新 `0`、错误 `0`；备份 `backups/db/pre-wpstud-race-jockey-racecourse-term-import-20260705_072047.sql.gz` 通过 `gzip -t`；正式导入新增 `1891`、更新 `0`、跳过 `0`。导入后生产 `TermEntry=15321`、`TermAlias=15537`，`http://127.0.0.1/healthz/` 返回 `200`。本轮后 `source_language=en` 分布已包含香港、英国、法国、美国、日本和 other 的马名/赛事/骑师/马场，其中 HKJC 官方仍保持最高优先级，WP Stud 作为社区候选和佐证使用。

`2026-07-06/07` 已完成 HKJC / WP Stud 术语库清洗、WP Stud HorseList 全量马名补齐和生产正式导入。返修代码让 HKJC overseas 与美国详情来源中的马名去除尾部国别后缀，例如 `A Bit Of Spirit (IRE)` 清洗为 `A Bit Of Spirit`；带年份或替代名称的复合赛事名会拆成独立术语，例如 `International Stakes` 与 `Benson & Hedges Gold Cup Stakes`；WP Stud `HorseList.html` 已作为默认来源，解析日文马名、英文别名和简体中文译名。最终审核产物位于 `runtime/termbase_seed/final-reviewed-import-20260706/`，`seed_candidates_final.csv` 共 `11257` 行，输入覆盖 HKJC `7691`、WP Stud race/jockey/racecourse `1891` 和 WP Stud HorseList `1866`；清洗统计包括去除马名国别后缀 `6481` 次、拆分年份赛事标记 `59` 次、去重 `254` 行，并生成 HKJC 日本地区英文马名日文 alias `907` 行，其中马名 `883` 行已全部找到日文名。生产服务器 `/opt/umanewsbot` 导入时 `HEAD=b1ddb54`，导入前 `TermEntry=15321`、`TermAlias=15537`，备份 `backups/db/pre-final-termbase-review-20260706_234427.sql.gz` 约 `75M` 且 `gzip -t` 通过；正式脚本先清理既有脏 active 术语，再执行 `import_terms`，结果为新增 `1169`、更新 `10088`、错误/跳过 `0`。导入后生产 `TermEntry=16558`、`TermAlias=19293`、active `TermEntry=16428`，active 马名国别后缀术语 `0`、active 赛事年份标记术语 `0`，`ExternalDataImportRun(status="started")=0` 且导入锁为空，`manage.py check`、`127.0.0.1/healthz/` 与 Host `umafans.run` 健康检查均通过。抽检确认 `A Bit Of Spirit (IRE)` 已无 active 词条而 `A Bit Of Spirit -> 点燃斗志` 有效，`International Stakes -> 国际锦标` 与 `Benson & Hedges Gold Cup Stakes -> 宾臣暨赫捷仕金杯` 已拆分，`A Shin Resume / Dragon / Dynamic / Sophia` 等 HKJC 日本马英文词条已挂日文 alias。另有 `26` 个 HKJC 日本马日文 alias 因生产已有同日文 `TermAlias` 或日文主词而未直接挂到英文词条，其中大多数中文目标一致；`Raijin / ライジン` 和 `Scintillation / シンチレーション` 存在既有译名占用，导入脚本按“不强行合并冲突概念”跳过，保留 HKJC 英文主译名。

`2026-07-05` 旧规格流程 change `prepare-hkjc-overseas-termbase-seeds` 已完成正式规格同步并归档，归档目录为 `旧规格流程/changes/archive/2026-07-05-prepare-hkjc-overseas-termbase-seeds/`。归档前已将 delta spec 合并到 `旧规格流程/specs/termbase-seed-data-preparation/spec.md`：正式规格现在包含 `hkjc_overseas` 来源、Race Card 自动发现与精确参数、马名/骑师/赛事名候选、简体中文目标、官方来源元数据、结构化证据、地区映射以及包含 `racing_region` 的导入兼容表头。归档前 `旧规格流程 validate prepare-hkjc-overseas-termbase-seeds --strict && 旧规格流程 validate --all` 通过，归档后 `旧规格流程 validate --all` 通过 `17` 项。
仓库已于 `2026-06-06` 加入 旧规格流程 + Codex 协作支持，用于在较大功能、跨模块改动、架构调整和生产高风险变更前先对齐规格，再进入实现。

旧规格流程 change `add-term-candidate-discovery` 已完成实现、自动化测试、本地隔离环境浏览器验收，并归档为 `2026-06-06-add-term-candidate-discovery`；正式能力规格已同步到 `旧规格流程/specs/term-candidate-discovery/spec.md`。

`2026-06-30` 旧规格流程 change `operate-multiregion-news-production` 已完成实现、代码审查返修、生产部署和归档。新增多地区新闻生产只读审计命令 `audit_multiregion_news_production`、通用 enabled 新闻来源轮询任务 `crawl_enabled_news_sources_task`、地区/来源自动发布 allowlist 与地区上限策略、后台 `/admin/regions/` 地区生产概览、来源管理地区筛选、QQ 国际新闻地区标签、地区查询索引和运行手册。返修后，地区生产概览的自动发布、人工发布和公开数量按今日窗口统计，待翻译、翻译失败和待审核保留为当前积压；审计中的来源抓取状态改为按 `NewsSource.last_crawl_status` 当前来源状态聚合，不再累计历史 `CrawlJob` 次数；正式术语 `TermEntry` 增加可选适用地区，空值表示全局通用，术语列表/表单/API/CSV 导入和多地区审计均支持地区口径；自动发布批次在地区每日/每轮上限跳过大量国际候选时，会在主扫描未填满后执行有限的日本候选兜底扫描，避免拖慢符合既有策略的日本文章。生产服务器 `/opt/umanewsbot` 已从 `7b6e51b` 快进到 `62a0f9a` 并执行 `bash ./deploy_lowcost.sh`，部署前备份 `.env` 为 `.env.backup.multiregion-news-20260630_185150`；迁移 `stable.0014_multiregion_news_indexes` 与 `stable.0015_termentry_racing_region` 已应用，`web / worker / beat` 已重建，`manage.py check`、`http://umafans.run/healthz/`、首页和后台登录入口均通过。随后已按用户要求开启多地区新闻生产开关，备份 `.env` 为 `.env.backup.enable-all-multiregion-20260630_203647`；当前 `NEWS_SOURCE_POLL_ENABLED=true`、轮询间隔 `30` 分钟、每轮最多 `12` 个来源，覆盖 `japan / hong_kong / united_kingdom / france / united_states` 五个地区；非日本自动发布 allowlist 已开启 `hong_kong / united_kingdom / france / united_states` 四个地区和当前已启用的国际来源，并设置首日护栏上限 `hong_kong:5 / united_kingdom:5 / france:3 / united_states:3`。开关生效后手动执行通用轮询 smoke，已选中并派发 `12` 个 due 来源，固定调度的 netkeiba/JRA 被正确跳过；worker 并发为 `2`，当前先处理 Sponichi 两个任务，其余任务在队列中等待消化。正式 QQ 群仍需显式配置 `PushTarget.allowed_regions` 才接收国际新闻。外部赛马数据库 `External*` importer 不进入新闻常态调度，不自动生成公开新闻或 QQ 推送。归档目录为 `旧规格流程/changes/archive/2026-06-30-operate-multiregion-news-production/`，正式规格已同步到 `旧规格流程/specs/multiregion-news-production/spec.md` 及相关能力规格。

`2026-07-02` 旧规格流程 change `increase-multiregion-news-volume` 已整体上线到生产。生产 `/opt/umanewsbot` 当前运行 `9e97e8c`，与 `origin/main` 一致；部署前数据库备份为 `backups/db/pre-multiregion-volume-20260702_040811.sql.gz`，`.env` 备份为 `.env.backup.multiregion-volume-20260702_040811`，启用前另备份 `.env.backup.enable-multiregion-volume-20260702_041242`。迁移 `stable.0017_majorraceevent_productionwindow_quotaledger_and_more` 与 `stable.0018_alter_notificationlog_type` 已应用，`web / worker / beat` 运行健康，本地和公网 `/healthz/` 均返回 `200`。本次上线开启 `MULTIREGION_PRODUCTION_WINDOWS_ENABLED=true`、抓取/发布/QQ 三条窗口开关均为 `true`，覆盖 `japan / hong_kong / united_kingdom / france / united_states`；当前 16 个启用新闻源已标记 `production_approved=true`，日常抓取默认 15 分钟，重要赛事窗口默认 5 分钟。上线过程中发现并修复抓取窗口把 Celery `AsyncResult` 写入 JSON payload 导致窗口失败的问题，修复提交为 `9e97e8c`，窗口现在保存 `dispatch_result.task_id`。生产 smoke：20:15 抓取窗口派发 15 个 due 来源，最终 14 个成功、1 个 `Sponichi 新闻ランキング` 因上游 `502 Bad Gateway` 失败且写入明确原因；20:15 发布窗口香港自动发布 1 篇、美国自动发布 3 篇，20:30 发布窗口美国继续发布 1 篇，其他地区为 `no_ready_candidates`；20:15 QQ 窗口美国发送 2 条 delivery，20:30 QQ 窗口美国为 `already_sent`，其他地区为 `no_eligible_articles`。公开首页和地区页浏览器验收通过，首页可见 20:15 窗口新发布的香港/美国文章。ops 摘要通知已配置到 `UmaFans测试群(1026525240)`，`production_summary_task` 已产生 `NotificationLog #13051`，状态 `sent`。因当前为后半夜新闻低峰，用户确认跳过实际 4 个自然窗口等待，改为次日继续观察来源失败、候选质量、0 原因和 QQ 限流情况。

`2026-07-01` 已将 `add-netkeiba-horse-data-import`、`expand-international-racing-coverage`、`guard-qqbot-offline-send` 全部归档，正式规格同步到 `旧规格流程/specs/external-horse-data-import/`、`旧规格流程/specs/international-racing-coverage/` 及相关能力规格；`旧规格流程 list` 为空，`旧规格流程 validate --all` 12 项通过。本次同时补齐 `ExternalDataSource` 对 `sporting_life / france_galop / geny_france / horse_racing_nation` 的 choices 和迁移 `stable.0016`，避免英法美外部数据导入 source 值与模型枚举不一致。生产服务器 `/opt/umanewsbot` 已从 `538a1a9` 快进到 `8c83708` 并执行 `bash ./deploy_lowcost.sh`，部署前数据库备份为 `backups/db/pre-archive-all-20260701_153301.sql.gz` 且 `gzip -t` 通过；部署后 `web / worker / beat` 已重建，迁移 `stable.0016_alter_externaldataimporterror_source_and_more` 已应用，`manage.py check`、本地和公网 `/healthz/`、首页、后台登录入口和 `/admin/regions/` 均通过。浏览器验收确认首页地区 tab 正常，香港/英国地区页可渲染已发布国际新闻，地区生产页可显示五地区来源与 QQ 状态。生产开关仍为 `NEWS_SOURCE_POLL_ENABLED=true`、轮询间隔 `30` 分钟、每轮最多 `12` 个来源、覆盖五地区，`QQ_PUSH_ENABLED=true` 且 `QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。来源状态复核显示五地区 enabled 来源多数最近抓取为 `success`；当前仅 `Sponichi 新闻ランキング` 因上游 `502 Bad Gateway` 处于失败状态，属于来源站响应异常，不影响本次部署成立。

`2026-06-07` 已将术语候选发现部署到生产：服务器从 `7123e4e` 拉到 `e2e3e07`，应用迁移 `0006` 新建候选与证据表，`.env` 补入术语发现开关并保持 `TERM_DISCOVERY_ENABLED=false`（灰度，先关后开）。本次部署同时核实线上 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 仍在生效。

仓库已明确长期语言约定：Codex 新增或维护的协作文档、旧规格流程 产物与代理说明默认使用中文；仅保留必要的代码标识符、命令和工具机器语法。

`2026-06-19` 已创建公开首页资讯流升级主 旧规格流程 change：`upgrade-public-home-info-feed`。该 change 作为后续前台 Web + 移动 H5 首页子任务的指导规范，目标是把当前 MVP 公开首页从“大说明 + 大卡片网格”升级为成熟资讯流：移动端轻头条 + 高密度新闻列表，桌面端门户式主内容 + 侧栏。`2026-06-21` 已完成 plan-eng-review 与 `/opsx:apply` 本地实现；实施过程按严格 TDD 执行发布过滤、头条选择、普通流去重、热门代理、公开静态资源和详情页结构测试，并已通过本地 Django 测试、旧规格流程 校验和桌面/移动浏览器验收。`2026-06-22` 已将 delta spec 同步为正式规格 `旧规格流程/specs/public-home-info-feed/spec.md`，并归档为 `旧规格流程/changes/archive/2026-06-22-upgrade-public-home-info-feed/`；同日 PR #1 已合并并部署到生产，服务器运行 `e834f58`，公开首页已切换到 `stable/public.css` 和新资讯流模板。`2026-06-23` PR #2 已合并并部署生产，服务器运行 `04e2ee9`，移动 H5 首屏密度 follow-up 已上线。

`2026-06-24` 已完成自动发布门禁优化 旧规格流程 change：`refine-automation-publish-gates` 的实现、PR 合并与生产上线。代码已将自动发布门禁拆为 `blocker / warning / info`：`blocker` 阻断自动发布，`warning` 初期不阻断但记录并对高价值文章邮件告警，`info` 仅用于诊断；同时支持基准翻译稿自动发布、高价值来源评分放行、非马名普通词过滤、关键术语分层校验和重复内容拦截。生产服务器当前运行 PR #4 squash merge 后的提交 `42a4622`，迁移 `stable.0009_automation_publish_gates` 已应用。

`2026-06-25` 已将本轮三个运营改造 change 合并到 `main` 并部署生产：抓取新鲜度与来源健康、后台原文选区快速加入术语库、新增术语后一次性应用到当前稿。服务器 `/opt/umanewsbot` 已从 `268100d` 更新到 `7f54f13`，`web / worker / beat` 已重建，`manage.py check`、`/healthz/` 和首页 HTTP 验证通过。相关 旧规格流程 change 已归档并同步正式规格；其中抓取返修的 `fix-crawl-health-running-and-schedule-stagger` 是 change1 的后续规格，随 change1 一并归档。

`2026-06-25` 已将榜单重点新闻 QQ 推送与公开文章 ID URL 改造通过 PR #8 合并并部署生产。服务器 `/opt/umanewsbot` 已更新到 `00e4bd4`，部署前 `.env` 备份为 `.env.backup.qq-ranked-idurl-20260625_191826`；生产 `.env` 已切换为 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。`web / worker / beat` 已重建，`manage.py check`、`http://umafans.run/healthz/`、`http://umafans.run/`、`/news/<article_id>/` 公开详情和旧 slug 到 ID URL 的 `302` 跳转均已验证通过。本次不补推历史公开新闻，后续只等待自然榜单新闻触发测试群推送。

`2026-06-26` 已将国际赛马资讯扩展 旧规格流程 change：`expand-international-racing-coverage` 合并到 `main` 并部署生产，服务器 `/opt/umanewsbot` 已从 `2f0c35c` 更新到 `5865e58`，部署前 `.env` 备份为 `.env.backup.international-coverage-20260626_103923`。本次部署应用迁移 `stable.0011`、`0012`、`0013`，`web / worker / beat` 已重建，`manage.py check`、`http://127.0.0.1/healthz/` 和首页 HTTP 验证通过。部署前发现生产 netkeiba 外部马名导入脚本仍在连续运行，已等待当前批次完成并释放 `ExternalDataImportLock` 后再部署；外层脚本 `/opt/umanewsbot/imports/run_horse_import_202504_to_202406_20260626_083946.sh` 已停止，最近两批 `1958 / 1959` 均停在 `paused`，避免部署与导入写库重叠。国际来源已同步并灰度启用第一版清单：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing latest/access`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation latest/access`；生产探测中 `BHA official` 返回 `403`，已暂时停用，`At The Races`、`Paulick Report` 和 `BloodHorse` 仍保留为候选但不启用。测试 QQ 群 `1026525240` 已配置允许 `japan / hong_kong / united_kingdom / france / united_states` 五个地区。首轮手动触发 12 个新增来源抓取任务后，`Sponichi latest` 已完成并入库 `13` 篇新稿、`7` 篇重复稿，`Sponichi access` 与 `HKJC Racing News` 已开始执行，其他国际来源仍在 worker 队列中等待；后续重点观察 `CrawlJob`、翻译结果、自动发布门禁和 QQ 群推送。

`2026-06-26` 已创建新的本地 Codex 工作树 `/Users/mentianlu/.codex/worktrees/旧规格流程-ready-20260626/umanews`，基线为 `origin/main` 的 `4d09d25`。该工作树已带入 `.codex/skills/旧规格流程-*`、`.codex/skills/plan-eng-review`、`.codex/skills/tdd`、`.codex/skills/workflow-spine` 和 `.agents/skills` 镜像，并补齐 `gate-templates.md` 引用副本；已通过 `旧规格流程 list`、`旧规格流程 validate --all`、`旧规格流程 validate expand-international-racing-coverage --strict`、`旧规格流程 validate add-netkeiba-horse-data-import --strict`、`旧规格流程 status --change expand-international-racing-coverage --json` 和 skill 文件一致性检查。该记录仅描述本地协作工作树准备状态，不代表新的产品或生产部署变更。

`2026-06-26` 已新增并完成计划审查 旧规格流程 change `start-hkjc-data-import-and-global-spikes`，用于启动香港 HKJC 外部赛马数据受控导入，并为英国 `Sporting Life + BHA`、美国 `Equibase`、法国 `France Galop` 产出结构化数据库 spike。该 change 明确不续跑日本 netkeiba 外部数据导入，日本导入由其他线程继续；本轮也不实现前台比赛页、赛果页或马匹页。已创建 `proposal.md`、`design.md`、`specs/global-racing-data-import-readiness/spec.md` 和 `tasks.md`，并通过 `/plan-eng-review`；审查后补齐 HKJC 生产 commit 前的隔离库验证、数据库备份、用户显式确认、`HKJC_IMPORT_*` 环境配置入口，以及英法美 spike 前后正式表计数保持不变的验收要求。当前 `.旧规格流程.yaml` 为 `phase: reviewed`，已通过 `旧规格流程 validate start-hkjc-data-import-and-global-spikes --strict`、`旧规格流程 validate --all` 和 `git diff --check`。随后按 TDD 红灯阶段新增 `旧规格流程/changes/start-hkjc-data-import-and-global-spikes/test_cases.md` 和自动化测试；本轮实现已将 4 个红灯转绿：补齐 `HKJC_IMPORT_*` settings 和 `.env.example`，新增 HKJC `--allow-network` dry-run 请求边界输出，新增英法美只读 spike runner 和正式表 before/after 计数检查。HKJC 最小样本 fixture 已保存到 `server/stable/fixtures/hkjc/`，本地隔离 SQLite `/tmp/umanews-hkjc-apply.sqlite3` 已完成赛日、单场、单马 dry-run/commit，结果写入 `docs/hkjc_data_import_samples.md`；隔离库最终统计为 3 个 import run、1 场比赛、2 个 entries、2 条 results、2 匹马、4 条别名。英法美 read-only spike 已执行 6 次公开页面 GET，请求证据、字段覆盖矩阵和准入判断已写入 `docs/global_racing_data_source_spikes.md`；三地当前均为 `needs_more_spike`，且正式表 before/after 计数保持不变。验证通过：`manage.py check`、HKJC/spike 目标测试 12 项、完整 `stable` 测试 246 项。

`2026-06-26` 已将 `start-hkjc-data-import-and-global-spikes` 实现提交 `b0361cf` 推送到 `main` 并部署生产。服务器 `/opt/umanewsbot` 已从 `4d09d25` 快进到 `b0361cf`，部署前 `.env` 备份为 `.env.backup.hkjc-global-spikes-20260626_164045`。部署前确认生产无运行中 `ExternalDataImportLock`，无 `ExternalDataImportRun(status="started")`；`bash ./deploy_lowcost.sh` 执行成功，迁移显示 `No migrations to apply`，`web / worker / beat` 已重建，`web` healthy。生产验证通过：`manage.py check` 无问题，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和首页均返回 `200`；HKJC 样本命令以 dry-run 方式读取容器内 `stable/fixtures/hkjc/2026-06-21-race-date-sample.json`，返回 `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}` 且 `would_write_formal_tables=false`。部署当时未执行 HKJC commit，也未启用英法美正式导入。

`2026-06-26` 已归档 `start-hkjc-data-import-and-global-spikes`，归档目录为 `旧规格流程/changes/archive/2026-06-26-start-hkjc-data-import-and-global-spikes/`；delta spec 已同步为正式规格 `旧规格流程/specs/global-racing-data-import-readiness/spec.md`。归档后 `旧规格流程 validate --all` 通过，`global-racing-data-import-readiness` 正式规格包含 6 个 requirement。归档提交 `db0f3cc` 已推送到 `main` 并在生产 `/opt/umanewsbot` 快进；该提交只移动 旧规格流程/文档，不重建容器，生产服务代码仍为已部署验证过的 `b0361cf` 镜像内容，线上 `/healthz/` 和首页保持 `200`。

`2026-06-26` 已按用户确认启动 HKJC 生产样本导入，但范围仅限仓库 fixture `stable/fixtures/hkjc/2026-06-21-race-date-sample.json`，不是 HKJC 真实网络持续抓取。执行前已在生产服务器创建数据库备份 `backups/db/pre-hkjc-sample-20260626_180646.sql.gz` 并通过 `gzip -t` 校验；预检查显示无运行中 HKJC 导入、无 started run，`web` healthy。生产 dry-run 再次返回 `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}` 且不写正式表；随后执行 `--commit` 成功，`run_id=1960`、`success_count=7`、`failure_count=0`、`skipped_count=0`。提交后生产 HKJC 外部表统计为 `ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`、`ExternalHorse=2`、`ExternalHorseAlias=4`，马名索引 `STELLAR EXPRESS` 命中 `HKH_STELLAR_EXPRESS`；`ExternalDataImportLock` 仅保留未占用的来源占位记录，未发现仍在运行的 HKJC 导入进程，`http://umafans.run/healthz/` 返回 `200`。真实 HKJC 网络入口仍未确认，不能把这次样本导入理解为已开启自动抓取。

`2026-06-26` 已新建 旧规格流程 change `connect-real-global-racing-databases`，目标是按 `香港 -> 英国 -> 法国 -> 美国` 顺序接入真实赛马数据库，抓取每个地区最近 2 个月赛事和涉及马匹详情后停止，不创建公开比赛页或持续调度。香港阶段已定位 HKJC 官方真实 HTML 入口：赛日列表 `localresults`、单场结果 `localresults?racedate=YYYY/MM/DD&Racecourse=HV|ST&RaceNo=N`、马匹详情 `horse?horseid=...`。本地 TDD 已新增 HKJC HTML parser、race link 聚合、recent-days/date-range、马匹详情补抓、限速、请求上限和 `completion` 完成度测试，`HKJCExternalDataImportTests` 21 项通过；真实 HKJC 单场 dry-run `HK20260624HV01` 请求 1 次官方页面并解析 `1` 场、`12` entries、`12` results、`12` unique horses，未写库。随后在隔离 SQLite `/tmp/umanews-hkjc-real-single.sqlite3` 执行同一真实单场 `--commit --allow-network`，成功写入 `ExternalRace=1`、`ExternalRaceEntry=12`、`ExternalRaceResult=12`、`ExternalHorseAlias=12`，`run_id=1`、`success_count=25`、`failure_count=0`。同日又完成 HKJC `--recent-days 60 --end-date 2026-06-26 --limit-races 1 --limit-horses 1` 真实小范围链路：dry-run 请求赛日列表、赛日页、单场结果和马匹详情共 `4` 次，解析 `1` 场、`12` entries、`12` results、`12` unique horses，并返回 `completion.is_complete=false`、`stop_reason=limit_horses_reached`、`meetings_found=28`，明确这是样本而非全量；隔离 SQLite `/tmp/umanews-hkjc-real-range.sqlite3` commit 后写入 `ExternalRace=1`、`ExternalRaceEntry=12`、`ExternalRaceResult=12`、`ExternalHorse=1`、`ExternalHorseAlias=12`，重复执行后正式对象计数不增长。当前仍未部署生产，也未执行生产最近两个月全量 dry-run/commit；下一步需要生产部署前锁检查、备份、用户确认后再低频运行 HKJC 最近两个月范围。

`2026-06-26` 已为 `connect-real-global-racing-databases` 追加英法美只读 spike 复核，共执行 `18` 次公开页面 GET，不写任何 `External*` 表。英国 `Sporting Life` racecards、fast-results 和 horse profile 均返回 `200`，fast-results 暴露具体 racecard 与 horse profile 链接；`BHA` horses/fixtures 返回 `200`，暴露 horses feed、search 和 fixtures/racecards 相关入口，因此英国当前优先级最高，建议后续以 Sporting Life 为正式导入主候选、BHA 为官方补字段候选。美国 `Equibase` entries、chart/PDF index 和具体 horse profile 均返回 `200`，但 chart/PDF 解析成本和访问限制仍需 fixture spike。法国 `France Galop` 官方页面和 app 说明页返回 `200` 并有 race card/results/calendar 浅层信号，但尚未定位稳定结构化查询参数，仍为 `needs_more_spike`。证据已写入 `docs/global_racing_data_source_spikes.md`。

`2026-06-26` 已为 HKJC 增加 `--plan-only`、`--skip-races` 和 `--race-ids` 批次能力，并用真实页面完成本地 plan-only 预检：最近 60 天 HKJC 下拉目标日期页 `28` 个，过滤 overseas simulcast 的 `S*` racecourse 后，本地香港 `HV/ST` 比赛为 `144` 场；按 `limit-races=20` 可拆为 `8` 批。`--skip-races 20 --limit-races 1 --limit-horses 0` 真实 smoke 成功从第 21 场 `HK20260613ST04` 开始，证明日期范围后续批次不会重复第一批；随后 `--race-ids HK20260624HV02,HK20260613ST04 --limit-horses 1` 真实 smoke 只请求 `race/race/horse` 3 个页面，解析 `2` 场、`26` entries、`26` results 和 `26` 匹唯一马，证明可按 plan-only 输出的 race_id 清单执行精确批次。本能力只用于生产全量前规划和拆批；尚未执行生产最近 2 个月全量 dry-run 或 commit。

`2026-06-26` 已将 `connect-real-global-racing-databases` 当前 HKJC 真实网络实现部署到生产，部署前数据库备份为 `backups/db/pre-hkjc-real-network-20260626_202442.sql.gz` 并通过 `gzip -t` 校验。生产 `65d41eb` 部署后 `manage.py check`、本地和公网 `/healthz/`、HKJC 精确 race-id 小样本 dry-run 均通过；生产 plan-only 仍显示最近 60 天本地香港 `HV/ST` 比赛 `144` 场、拆为 `8` 批。随后第 1 批 full dry-run 在马匹 profile 补抓阶段遇到 HKJC `ReadTimeout` / TLS handshake timeout 中断；该次未使用 `--commit`，未写正式表，中断后生产 HKJC 锁为空、`started_runs=0`、HKJC 表计数仍为上次 fixture 样本 `ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`、`ExternalHorse=2`、`ExternalHorseAlias=4`。已按 TDD 追加 transient timeout retry 并部署到生产 `04c0444`，单请求最多 `3` 次并记录失败尝试；目前已将前 6 个 plan-only 批次拆成 24 个 5 场小批次完成 full dry-run，累计覆盖 `120` 场、`1522` entries、`1522` results、`1522` 个 horse profile 请求，所有小批次均 `completion.is_complete=true`，未写正式表。3c 首次执行时遇到一次执行容器 `137` 中断，输出文件为 `0` 字节；复查服务、锁和表计数均安全，随后改用一次性 `docker compose run --rm --no-deps web ...` 容器重跑 3c/3d 并完成；5a 出现 `2` 次 transient retry 记录但最终完成。当前停在生产 commit 前确认点，并可继续第 7 批 dry-run。

`2026-06-27` 全球赛马数据库目标已调整并完成“能力真实可用”确认：香港 HKJC 已有生产真实 dry-run 批次证据，英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 已完成少量真实 proof，证明四地公开入口、parser/importer、马匹详情链路、低频限量抓取和 proof-only 离线审计可用。本次上线包从 `origin/main` 干净基线单独整理，只包含全球赛马数据库 importer、fixtures、审计工具、批次命令渲染器、旧规格流程 规格/归档、proof 证据和相关文档；刻意排除当前本地大工作树中的 QQ 推送、前台信息流、compose 端口等旁支差异。本目标不再要求本轮完成最近 60 天完整大量爬取或生产 `--commit`；后续完整爬取需另按 `docs/global_racing_next_run_checklist.md` 与 `docs/global_racing_full_crawl_runbook.md` 新开执行窗口。代码提交 `93b7007` 已推送并部署到生产；部署后 `manage.py check` 通过，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和首页均返回 `200`，UK / France / US 导入命令与 batch 渲染命令可用，proof-only 审计通过，`ExternalDataImportRun(status="started")=0` 且 HKJC/netkeiba 锁为空。

`2026-06-30` 已按用户要求开始尝试香港 HKJC 慢速真实 dry-run，但仍未执行生产 `--commit`，也未写正式表。生产服务器 `/opt/umanewsbot` 当前代码为 `7b6e51b`；执行前确认 `docker compose -f docker-compose.prod.lowcost.yml ps` 中 `web/db/redis` healthy、`worker/beat/nginx` 运行，`ExternalDataImportRun(status="started")=0`，HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`。最新 `--recent-days 60 --end-date 2026-06-30 --plan-only --limit-races 20 --max-requests 160 --allow-network` 输出为 `runtime/global_racing_import/hkjc-20260630/hkjc-plan-20260630.json`，显示 `meetings=29`、`races=146`、`estimated_requests_without_horses=176`，拆为 `8` 批；该结果已不同于历史 `144` 场，因此不能把旧的 `120/144` 停点直接当作有效续跑点。随后以 `HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8`、`HKJC_IMPORT_MAX_REQUESTS_PER_RUN=100` 执行精确 `race_ids=HK20260627ST02,HK20260627ST03` 小批 dry-run，输出 `runtime/global_racing_import/hkjc-20260630/hkjc-batch1-races-001-002-dryrun-20260630.json`：`dry_run=true`、`would_write_formal_tables=false`、`coverage_stats={"races":2,"entries":28,"results":28,"horses":28}`、`completion.is_complete=true`、`stop_reason=complete`、`horse_profiles_fetched=28`、`requests_len=30` 且全部 `status_code=200`。执行后复查 `ExternalDataImportRun(status="started")=0`、HKJC/netkeiba 锁为空，无 `umanewsbot-web-run-*` 临时容器残留，`http://umafans.run/healthz/` 和 `http://127.0.0.1/healthz/` 均返回 `200`。下一步如果继续香港，应按最新 `146` 场 plan 重新切批，从第 1 批剩余 race_ids 或重新渲染批次命令继续，而不是沿用旧 `skip-races=120`。

`2026-06-30` 用户要求继续香港 HKJC 慢速抓取到 `2024-07`。当前仍按 dry-run 执行，不写正式表、不加 `--commit`。生产已运行 `--start-date 2024-07-01 --end-date 2026-06-30 --plan-only --limit-races 20 --max-requests 600 --allow-network`，输出 `runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-plan-20240701-20260630.json`：计划共 `1496` 场、`75` 个 20 场批次，请求日志 `254` 条，其中 `253` 条 HTTP `200`；最后一个 plan 批次覆盖 `2024-09-11` 与 `2024-09-08`，说明 `2024-07-01` 至 `2024-09` 之间没有更早的 HKJC 本地 `HV/ST` 赛日进入该计划。此前已在生产 `runtime/global_racing_import/hkjc-20260701-to-202407/run_hkjc_slow_dryrun_to_202407.sh` 启动后台慢速 dry-run worker，按每 `5` 场一个 mini-batch、`HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8`、`HKJC_IMPORT_MAX_REQUESTS_PER_RUN=140`、批次间暂停 `60` 秒执行；`races=3-7/1496` 与 `races=8-12/1496` 已通过校验。为部署 `operate-multiregion-news-production`，已按运行手册先暂停该 dry-run worker 和临时 `umanewsbot-web-run-*` 容器，状态文件 `hkjc-slow-dryrun.state=92`；暂停后 `ExternalDataImportRun(status="started")=0`，HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`，未写正式表。后续若继续该长窗口 dry-run，应从 `hkjc-slow-dryrun.state=92` 对应进度恢复或重新渲染剩余批次，避免与生产部署、重建容器或 `git pull` 重叠。

## 已完成内容

- 域名购买与解析
- 正式域名 `umafans.run` / `www.umafans.run` 接入
- 本轮线上问题已修复，正式域名已可访问
- 公网服务器上 `Django + PostgreSQL + Celery + Redis + Docker Compose + Nginx` 主链路已运行
- 基础抓取、翻译、后台、前台链路已具备可继续迭代的基础
- 自动化运营 MVP 代码侧已完成：
  - 翻译成功后可进入自动评分分流
  - 支持 `auto / manual / ignored` 三类分流
  - 支持基准翻译稿与 AI 改写稿双层保存
  - 支持一致性校验、批量自动发布、自动化日志与通知日志
  - 后台候选池、详情页、编辑台、日志页已展示自动化状态与决策留痕
  - 前台展示优先级已调整为人工稿优先，其次改写稿，最后基准翻译稿
- Codex 原生工作流已完成仓库级规则配置：
  - `AGENTS.md` 与 `docs/codex_workflow.md` 定义探索、持久 spec/design、测试先行、subagent 实现、独立 `/review` 和发布授权门禁
  - 新任务持久产物写入 `docs/changes/<slug>/`；`.codex/skills/plan-eng-review` 仅在缺少通用原生方案审核能力时作为 fallback
  - `.codex/agents/` 提供 `application / integration / operations` 实现代理，以及 `reviewer / security-scanner` 只读审核代理
  - `旧规格流程/config.yaml` 与既有 旧规格流程 artifacts 只作 legacy 兼容；相关 skills、workflow-spine、CLI phase 和 journal 不再是新流程入口或门禁
- 专有术语候选发现与待标注池已完成：
  - 支持马名、比赛名、骑手名和马主名发现
  - 支持候选去重、证据聚合、工作人员审核和安全写入正式术语
  - 已完成 69 项测试与本地浏览器功能验收
  - 生产默认关闭，等待灰度启用

## 当前进行中的 旧规格流程 change

- `start-hkjc-data-import-and-global-spikes`：已完成实现、生产部署、验证和归档；生产服务镜像来自 `b0361cf`。已在生产执行一次 HKJC fixture 样本 commit（`run_id=1960`），但未启用 HKJC 真实网络持续抓取，也未启用英法美正式导入。
- `connect-real-global-racing-databases`：本轮已按用户调整后的“能力真实可用”口径完成并归档；香港 HKJC 生产真实 dry-run 证据成立，英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 少量真实 proof 成立，四地 importer、低频限量抓取、proof-only 审计和后续完整抓取门禁已可用。最近 60 天完整大量爬取和任何生产 `--commit` 不属于本轮完成口径，后续需要新执行窗口。

## 本轮问题简述

本轮线上问题并不是单一故障，而是多层运行态与仓库预期不一致叠加导致：

- 早期曾出现 DNS 解析未生效或本地查询返回 `NXDOMAIN`
- 服务器曾运行旧版 `nginx` 配置，仍保留 `80 -> 443` 跳转逻辑
- 服务器 `.env` 曾保留旧版 IP + HTTPS 强制配置
- 服务器运行中的 commit 一度与仓库当前预期不一致
- 最终通过对齐服务器代码版本、运行态配置、域名配置，完成正式域名 HTTP 接入修复

## 当前线上状态

- 线上域名已通
- 正式域名 `umafans.run` / `www.umafans.run` 可访问
- 自动化运营 MVP 已上线
- 公开首页资讯流升级已上线生产：`/` 使用公开站点专用 `public.css`、头条、普通新闻流和原站热度模块；移动 H5 已展示头条 + 高密度左文右图列表；移动端首屏密度 follow-up 已上线，390px 视口首屏可见 4 条普通新闻卡
- 自动化能力通过 `.env` 中 `AUTOMATION_ENABLED` 控制，当前已进入灰度运行与质量观察阶段
- 已核实线上 `AUTOMATION_ENABLED=true`、`AUTO_REWRITE_ENABLED=false`、`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`、`AUTOMATION_WARNING_EMAIL_ENABLED=true`，当前按“基准翻译稿自动发布 + 高价值 warning 邮件告警”灰度运行
- 术语候选发现代码已部署到生产（`e2e3e07`，迁移 `0006` 已应用），`TERM_DISCOVERY_ENABLED=false` 默认关闭，等待单篇抽检后灰度开启
- `2026-06-24` 已完成 QQ Bot / OneBot 生产运行态配置：独立 NapCat 容器 `umanewsbot-onebot-1` 已启动，OneBot HTTP 仅绑定服务器 `127.0.0.1:3000` 并通过 Docker 网络别名 `onebot` 给应用访问，测试群 `1026525240` 已写入 `PushTarget`，OneBot 直连与 Django `BotPusher` 均已成功发送测试消息。
- `2026-06-25` 生产服务器运行 `7f54f13`：netkeiba 新着顺 / 访问量榜 / 注目数榜调度已加载为每小时 `00/16/26` 分，后台已具备来源健康摘要；候选详情页和文章编辑台已具备原文选区快速加入术语库，以及新增术语后 15 秒一次性浮层“应用到当前稿”。

## 下一步优先级

1. 继续观察公开首页资讯流生产运行，重点确认 `/`、`/news/<article_id>/`、旧非纯数字 `/news/<slug>/` 跳转、图片、`public.css`、移动 H5 首屏密度和自动发布内容长期表现
2. 生产迁移已于 `2026-06-07` 完成；下一步在生产做单篇手动重新发现并抽检术语候选质量，确认后灰度启用 `TERM_DISCOVERY_ENABLED`
3. 观察自动化发布质量与 `AutomationLog`
4. 补充翻译 warning 可视化和术语库补全流程
5. 继续观察 QQ Bot 测试群灰度推送，必要时通过 `QQ_PUSH_ENABLED=false` 暂停自动发送
6. 继续观察 netkeiba `00/16/26` 分错峰抓取在连续小时内生成 `CrawlJob`，并抽检后台来源健康摘要
7. 对 `expand-international-racing-coverage` 做一次上线前整体 review；后续进入 PR / 部署前，需要重点确认迁移窗口、国际新闻源灰度启用顺序、HKJC payload 小样本和生产外部导入锁状态
8. HTTPS / 证书接入
9. 部署稳定化与监控 / 备份 / 回滚完善
10. 继续低批量观察 `refine-automation-publish-gates` 上线后的 warning 邮件、重复内容阻断、候选池门禁展示和自动发布结果

## 2026-06-25 榜单重点新闻 QQ 推送规划

- 已形成协调总纲：`docs/ranked_news_push_plan.md`。该文档只作为本轮计划说明，不作为 旧规格流程 长期能力规格。
- 本轮拆为三个 旧规格流程 子 change：`elevate-ranked-netkeiba-sources`、`push-ranked-news-to-qq`、`use-article-id-public-urls`。
- 推送策略方向：`QQ_PUSH_SCOPE` 继续表示“全推 / 重点推”，重点推送的判定方式由后续配置承载；本期统一实现 `ranked` 榜单策略，即只推 `netkeiba:access` 与 `netkeiba:attention` 新闻。
- QQ 推送 blocker 判断必须复用现有 `NewsArticle.gate_blockers` / `gate_issues.severity=blocker` 结构化门禁结果，不在 QQ 服务里重新实现一套发布门禁。
- 归档状态：`add-qqbot-auto-push` 已先归档为正式 `qqbot-auto-push` 规格，随后本轮三个子 change 已归档到 `旧规格流程/changes/archive/2026-06-25-*` 并同步正式规格。后续仍建议维护者定期清理其他已完成的 active change。
- `elevate-ranked-netkeiba-sources` 已完成并部署生产：`upsert_article_from_draft()` 会将同一 netkeiba 文章从 `latest` 提升为首次命中的 `access` 或 `attention`，二者之间不互相覆盖，`latest` 也不会覆盖榜单来源；每次命中仍创建 `NewsSnapshot`。入库结果新增 `source_elevated` 稳定信号，且仍兼容旧的 `article, created = ...` 解包方式。
- `push-ranked-news-to-qq` 已完成并部署生产：新增 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`high_value_only` 下只推 `netkeiba:access` / `netkeiba:attention` 且无 blocker 的公开文章；已公开文章被榜单来源提升时会触发 QQ 自动推送编排，并继续依靠 `QQPushDelivery(article, target)` 唯一约束去重。QQ delivery 真正发送前也会复检推送资格，若文章后来出现 blocker 或不再符合范围，会标记为 `skipped/not_eligible`，不会继续发群消息。
- `use-article-id-public-urls` 已完成并部署生产：`NewsArticle.public_path` 改为 `/news/<article_id>/`，公开详情页可通过文章 ID 访问，非纯数字旧 slug URL 会跳转到 ID URL；首页、热门列表、后台前台查看入口和 QQ 自动推送消息均继续通过 `article.public_path` 使用 ID URL。
- 本地已通过完整 `stable` 测试、三个子 change 的严格校验、`旧规格流程 validate --all` 和 `git diff --check`；生产已通过容器重建、Django check、外部健康检查、首页检查、ID URL 与旧 slug 跳转 smoke test。

## 当前已知风险与待确认项

- 公开首页资讯流升级已部署生产；后续仍需观察真实访问、图片加载和自动发布内容在首页的长期表现
- 当前正式域名阶段仍以 HTTP 为主，HTTPS 证书尚未接入完成
- 需要把 HTTP 阶段的临时安全配置，在 HTTPS 切换时重新收紧
- 需要继续确认抓取调度、翻译调度、发布链路在正式域名环境下的长期稳定性
- 自动化发布涉及内容安全，生产首轮建议低频、低批量、保守开关启用
- AI 改写真实效果依赖模型配置与术语库质量，需继续通过后台人工抽检
- 邮件通知首版已实现；短信 / 微信通知当前只保留日志与配置位；QQ / OneBot 真实发送网关已在生产配置并通过测试消息，自动推送代码已部署并进入测试群灰度
- 需要补足更标准的部署基线、回滚与备份演练
- QQ Bot 自动推送已在生产开启测试群灰度；如出现 QQ 客户端发送异常，优先通过 `QQ_PUSH_ENABLED=false` 停止自动推送并保留 OneBot 网关排查。

## 2026-06-23 QQ 群自动推送 旧规格流程 change

### 当前实现

- 新增 旧规格流程 change：`add-qqbot-auto-push`。
- 新增自动 QQ 推送交付模型，以“文章 x QQ 群”为唯一粒度记录状态、尝试次数、最大尝试次数、错误类型、错误信息、OneBot 响应、消息 ID、最后尝试时间和成功时间。
- 自动推送默认关闭：`QQ_PUSH_ENABLED=false`。
- 自动推送默认范围：`QQ_PUSH_SCOPE=high_value_only`，首版高价值口径为 `score_total >= AUTO_REVIEW_THRESHOLD`；也支持 `all_public`。
- 发布入口已接入自动推送入队：人工发布、`publish_article()` helper 和自动发布成功后都会在开关开启时异步进入 QQ 推送编排。
- 推送前检查 `SITE_URL + article.public_path` 是否可访问；URL 不可访问和 OneBot 发送失败分别记录为 `url_unavailable` 与 `send_failed`。
- 自动交付在领取一次发送尝试前会先检查 OneBot `/get_status`，若网关离线、登录态失效或状态检查失败，则记录 `send_failed` 错误摘要并保持可恢复重试状态，不调用 `/send_group_msg`，也不增加 `attempt_count`。
- 自动交付会先原子领取尝试再执行 URL 检查和 OneBot 发送，避免重复任务并发消耗重试次数。
- OneBot HTTP 200 但 JSON 返回业务失败时按 `send_failed` 记录，不会误标记为成功。
- `sending` 状态超过 `QQ_PUSH_SENDING_STALE_SECONDS`（默认 600 秒）后允许后续任务重新领取，避免 worker 异常后长期卡住。
- 自动发送按目标群最近一次尝试时间做最小间隔保护，`QQ_PUSH_MIN_INTERVAL_SECONDS` 默认 60 秒，避免批量发布或补推时压垮 QQ / NapCat 发送通道。
- 自动推送只读取 `PushTarget.is_active=true` 的群；`is_default` 保留给后台手动推送默认目标。
- Django Admin 新增自动交付记录查看入口，并在文章详情中展示交付内联记录。

### 当前启用策略

- 生产已配置 NapCatQQ / OneBot v11 网关、测试群和 access token。
- 生产 `.env` 已设置 `QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，当前只等待自然榜单新闻触发测试群推送。
- 生产已部署迁移 `stable.0010_qqpushdelivery`，并设置 `QQ_PUSH_ENABLED=true` 进入测试群灰度。
- OneBot API 不得公网裸露；优先 Docker 内网 `http://onebot:3000`，临时映射只能绑定 `127.0.0.1`。

### 验收记录

- OneBot 直连和 Django 应用侧短消息均已成功发送到测试群 `1026525240`。
- 生产批量补推 126 篇公开文章时，交付记录成功创建并进入有限重试；NapCat / QQ 客户端随后返回 `网络连接异常`，系统正确记录为 `send_failed` 且未误标为成功。
- 已补充 `QQ_PUSH_MIN_INTERVAL_SECONDS` 节流保护，后续自动任务按目标群最小间隔重排，降低 QQ 风控和客户端异常风险。
- 2026-06-25 重新扫码登录 NapCat 后，Django `BotPusher` 短消息发送成功，`qq_auto_push_article_task -> qq_push_delivery_task -> OneBot` 自动任务链路已用真实公开文章验证成功，`QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=all_public` 在生产 worker 生效。
- 2026-06-25 存量补推按 65 秒间隔运行并成功发送 79 条交付记录；按当前验收判断，不再要求继续补推全部历史公开新闻，剩余历史 `retrying/send_failed` 记录保留用于后台排查，不影响后续新发布文章自动推送。
- 2026-06-25 榜单重点推送部署后，生产 worker 已确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 生效；本次不补推历史公开新闻，后续只等待自然榜单新闻推送。
- 2026-06-26 QQ 推送中断排查确认根因是 NapCat 快速登录态失效，日志出现“登录态已失效，请重新登录 / 你的用户身份已失效”。处理过程为：先把生产 `.env` 临时切到 `QQ_PUSH_ENABLED=false` 并重启 `worker / beat` 暂停自动推送；用户重新扫码登录后，OneBot `/get_status` 返回 `online=true`，`/get_login_info` 返回 QQ `1577955464`，群列表包含 `1026525240`，Django 应用侧测试消息发送成功；随后恢复 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 并重启 `worker / beat`。本次不补推全部已发表新闻，后续只等待自然榜单新闻触发。
- 2026-06-26 已将 OneBot 离线防护部署生产，服务器 `/opt/umanewsbot` 从 `849004c` 更新到 `a2146d6`，部署前 `.env` 备份为 `.env.backup.qqbot-offline-guard-20260626_223731`。部署后 `web` healthy，迁移显示 `No migrations to apply`，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `http://umafans.run/healthz/` 均返回 `200`；worker 环境确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`BotPusher().is_online()` 返回 `(True, '')`，测试群 `1026525240` 发送部署验证消息成功，返回 `message_id=1364343902`。

## 2026-06-24 自动发布门禁优化本地实现

- 旧规格流程 change：`refine-automation-publish-gates`，当前 `tasks.md` 已完成本地实现和验证。
- 新增配置：
  - `AUTO_REWRITE_ENABLED=false`：默认跳过 AI 改写前置。
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`：默认使用基准翻译稿作为自动发布内容源。
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`：访问量榜和注目数榜评分阶段放行。
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`：高价值 warning 初期告警收件人示例。
- 新增数据字段：
  - `NewsArticle.gate_issues` 保存结构化门禁 issue。
  - `WorkflowStatus.DUPLICATE` 描述高度重复内容。
  - `duplicate_of / duplicate_score / duplicate_reason` 保存重复检测解释。
  - `automation_warning_email_signature / automation_warning_email_sent_at` 用于 warning 邮件 24 小时去重。
- 迁移 `0009_automation_publish_gates` 会导入首批非马名普通词固定译法，包括 `タイトル`、`メートル`、`オッズ`、`ハンデ`、`ラジオ`、`ダート`、`マイル`、`スプリント`、`クラス`、`チャンス`、`キャリア`、`イメージ`、`デビュー`、`ゲート`。
- 后台候选列表、候选详情、自动化日志和 Django Admin 已展示 blocker / warning / info、重复检测结果和相似文章信息。
- `2026-06-24` review 返修：
  - 重新校验通过且当前不再重复的文章，会清理旧 `duplicate_of / duplicate_score / duplicate_reason`，并把旧 `duplicate` / `pending_review` 状态恢复为可进入自动发布批次的候选状态，避免显示 `publish_ready` 但被批发布排除。
  - 候选列表与候选详情中的相似文章现在链接到后台候选详情 `/admin/candidates/<id>/`。
- 本地验证：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AutomationFlowTests stable.tests.ConsoleFlowTests --noinput`：通过，23 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，106 项。
  - `旧规格流程 validate refine-automation-publish-gates --strict`：通过。

### 生产上线结果

- PR：GitHub PR #4 `[codex] refine automation publish gates` 已 squash merge。
- 生产提交：服务器 `/opt/umanewsbot` 已从 `71ab966` 更新到 `42a4622`。
- 部署前 `.env` 备份：`.env.backup.refine-automation-20260624_013323`。
- 已设置生产灰度配置：
  - `AUTO_REWRITE_ENABLED=false`
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`
  - `HIGH_VALUE_WARNING_SCORE_THRESHOLD=90`
  - `AUTO_DUPLICATE_LOOKBACK_DAYS=7`
  - `AUTO_DUPLICATE_HIGH_THRESHOLD=0.86`
  - `AUTO_DUPLICATE_REVIEW_THRESHOLD=0.72`
  - `AUTOMATION_WARNING_EMAIL_ENABLED=true`
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`
  - `AUTOMATION_WARNING_EMAIL_DEDUP_HOURS=24`
- 容器：`web` healthy，`db / redis` healthy，`worker / beat` up。
- 迁移：`stable.0009_automation_publish_gates` 已应用；运行时确认 `WorkflowStatus.DUPLICATE=True`，首批 `non_horse_common_word` 普通词种子数量为 `14`。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://umafans.run/healthz/` 返回 `200`。
  - `http://umafans.run/` 返回 `200`。
- 部署注意：重启初期日志曾出现一次 `automation_warning_email_sent_at` 字段已存在异常，判断为容器启动自动迁移与手工迁移并发撞车；后续日志显示 `No migrations to apply`，`showmigrations stable` 显示 `0009` 已应用，服务健康检查持续返回 `200`。

## 2026-06-24 抓取新鲜度与 JRA 日期解析本地实现

- 旧规格流程 change：`fix-crawl-freshness-and-jra-date-parse`，当前已完成本地实现并于 `2026-06-25` 部署生产。
- 修复范围：
  - JRA 官方新闻日期解析兼容 `2026年5月31日`、`5月31日`、零填充和非零填充日期。
  - JRA 无年份日期优先使用列表月份或 URL 年份；缺少上下文时使用当前东京年份，若推断日期晚于当前东京日期超过 7 天则回退上一年。
  - JRA 列表中单条日期异常会跳过该条并继续处理同一列表中其他新闻；整体结构或网络失败仍会记录为 JRA 抓取失败。
  - netkeiba 访问量榜和注目数榜从每天 `00:00/12:00`、`00:05/12:05` 调整为小时级抓取，并在 review 返修后避开新着顺和周日重赏高频补抓：新着顺每小时 `00` 分，访问量榜每小时 `16` 分，注目数榜每小时 `26` 分。
  - 内置来源定义同步更新访问量榜 / 注目数榜 `crawl_interval_minutes=60` 和来源备注，避免后台展示、异常检测与实际调度不一致。
  - 后台工作台和来源列表新增来源健康摘要，区分“运行中”“运行超时”“成功”“成功无新增”“失败”“长时间未运行”，并展示最近新增数、重复数或错误摘要；超过 60 分钟仍未完成的运行中记录会显示为疑似卡住，停用来源不参与“长时间未运行”判定。
  - JRA 单篇详情结构异常被跳过时，跳过摘要会同时写入本轮 `CrawlJob.error_message` 和 `NewsSource.last_crawl_message`，便于事后按 job 追溯。
- 本地验证：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AdapterTests stable.tests.ConsoleFlowTests stable.tests.CrawlAutoTranslateTests --noinput`：通过，25 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，118 项。
  - `旧规格流程 validate fix-crawl-health-running-and-schedule-stagger --strict`：通过。
  - `旧规格流程 validate --all`：通过，7 项。
- 生产部署：
  - 服务器 `/opt/umanewsbot` 已于 `2026-06-25` 更新到 `7f54f13`，部署前 `.env` 备份为 `.env.backup.three-changes-20260625_003714`。
  - `web / worker / beat` 已重建，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `/` 均返回 `200`。
  - 运行态确认 `crawl-netkeiba-latest-hourly / access / attention` 分钟分别为 `0 / 16 / 26`，内置来源定义中三者 `crawl_interval_minutes=60`。
  - 后续仍需等待自然调度，确认访问量榜 / 注目数榜在连续小时内按 `16 / 26` 分生成新 `CrawlJob`。

## 2026-06-23 前台发布判定代码阅读结论

- 公开前台首页 `/` 与详情页 `/news/<article_id>/` 只展示 `workflow_status=published` 且 `published_to_web_at` 非空的 `NewsArticle`；旧的非纯数字 `/news/<slug>/` 兼容入口会跳转到对应 ID URL。
- 抓取入库的新稿默认是 `workflow_status=pending_translation`，不会因为来自 `netkeiba` 新着、访问榜、注目榜或 `JRA` 官方新闻而直接进入前台。
- 翻译成功后文章进入 `pending_edit`；若 `AUTOMATION_ENABLED=true`，会触发自动化评分、改写与校验链路。
- 自动化评分为 `auto` 的文章也不会立刻公开；必须完成改写、通过一致性校验成为 `automation_status=publish_ready`，再由批量自动发布任务写入 `workflow_status=published` 与 `published_to_web_at` 后才进入前台。
- 自动化硬规则会把重复稿、正文过短或为空、疑似乱码/结构损坏、疑似广告或导航短页直接置为 `ignored`，默认不进入前台。
- 长采访或引语较多、翻译未成功、缺少基准中文翻译等会转为 `manual` / `pending_review`，需要人工审核后发布。
- 人工发布通过运营后台文章编辑页完成时会写入 `workflow_status=published`、`published_to_web_at`、`published_by_mode=manual`；无封面时需要二次确认。Django Admin 或后台 API 若只改 `workflow_status` 而不补 `published_to_web_at`，仍不会被公开前台接收。

## 2026-06-23 外部赛马数据导入 旧规格流程 提案

- 已创建 旧规格流程 change：`add-netkeiba-horse-data-import`。
- 提案目标：使用 `keibascraper` / netkeiba 作为低频离线导入来源，先抓取近两年比赛、出走、赛果、赔率、马匹血统和马匹履历数据，保存结构化字段与原始 payload，并派生本地马名索引。
- 关键约束：导入默认关闭，不加入自动全量调度；生产必须人工显式执行、强制限速、随机抖动、小批量、可暂停、可恢复；导入失败不得影响新闻抓取、翻译、自动化发布或公开前台。
- 当前状态：仅完成 proposal、design、delta spec 和 tasks，尚未实现代码，尚未执行真实爬取。

## 2026-06-19 公开首页资讯流升级 旧规格流程 主 change

### 已归档产物

- 正式规格：`旧规格流程/specs/public-home-info-feed/spec.md`
- 归档目录：`旧规格流程/changes/archive/2026-06-22-upgrade-public-home-info-feed/`
- 归档内保留 proposal、design、delta spec、tasks 和 `.旧规格流程.yaml`

### 主范围

- Web 端：首页升级为轻导航、主头条、普通新闻流和右侧热门/重点辅助模块。
- 移动 H5：首页升级为轻顶部、轻量头条和高密度左文右图新闻列表。
- 数据层优先复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，不新增数据库模型。
- 公开站点样式从后台 `console.css` 中解耦，后续实现应新增公开站点专用样式入口。
- 文章详情页与首页共享公开站点视觉体系，并保持已有有效稿件字段优先级。
- 后续实施采用严格 TDD：发布过滤、普通流排序、头条选择、热门代理、详情页字段和公开静态资源必须逐行为执行 RED -> GREEN -> REFACTOR，禁止一次性批量写完全部测试后再实现。
- 热门代理必须在有限候选集内批量读取 `NewsSnapshot` 或使用等价预取方式，避免无上限扫描或逐篇文章查询最近快照。

### 明确非目标

- 不做原生 App、个性化推荐、无限滚动、站内浏览量、站内评论或用户系统。
- 不在本轮新增手工置顶、推荐位、专题、搜索频道或赛事日历模型。
- 不改抓取、翻译、AI 改写、自动发布、QQ 推送或 Docker Compose 主架构。

### 本地实现结果

- 公开首页 `/` 已升级为公开站点专用模板和 `stable/public.css`，不再以后台 `console.css` 作为主要样式入口。
- 首页数据层复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，提供 `headline_article`、`feed_articles`、`latest_articles` 和 `hot_articles`。
- 头条选择按近期范围、赛事优先级、自动评分、封面和发布时间排序；低量内容回退到近 7 天或最新已发布文章。
- 热门代理在有限已发布候选集内批量读取上游访问/注目快照，无快照时按自动评分和发布时间回退；页面只标注“原站热度/原站排行”，不包装为本站评论或浏览量。
- 移动 H5 首页采用轻头条 + 左文右图高密度列表，普通卡片在 390px 视口验收中稳定为约 128px 高，缺图卡不破坏列表布局。
- 详情页复用公开站点 base，继续展示有效标题、摘要、正文、来源、原文链接和发布时间，并完成窄屏阅读排版验收。
- 本轮未新增数据库模型、迁移、生产配置或部署运行手册步骤。

### 校验结果

- `旧规格流程 validate upgrade-public-home-info-feed --strict`：归档前通过。
- `旧规格流程 validate --all`：归档前通过；归档并同步正式 spec 后再次通过。
- `/plan-eng-review upgrade-public-home-info-feed`：通过。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable.tests.PublicHomeInfoFeedTests`：通过，10 项。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable`：通过，88 项。
- 本地开发服务器浏览器验收：桌面首页、移动首页、桌面详情页、移动详情页通过；无横向溢出，图片加载正常，移动普通卡高度受控，桌面主列与右侧热门模块不重叠。

### 生产部署结果（2026-06-22）

- GitHub PR #1 从 draft 转为 ready 后合并到 `main`，merge commit 为 `e834f58`，包含实现提交 `1c9be7d`。
- 服务器 `/opt/umanewsbot` 从 `62a6a02` 快进到 `e834f58`；部署前备份 `.env` 为 `.env.backup.20260622_140844`。
- 生产使用低成本 compose 执行 `./deploy_lowcost.sh`：重建 `web/worker/beat`，`migrate` 显示 `No migrations to apply`，`collectstatic` 成功处理 `stable/public.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`。
- 首页 HTML 已引用 `/static/stable/public.2eec24723b45.css`，页面包含 `home-page`、`headline-card`、`news-card` 和“原站热度”；不再引用后台 `console.css`。
- 浏览器生产验收通过：桌面端显示轻导航、头条和热门模块；390px 移动端普通新闻卡约 `128px` 高，首屏头条后可见 3 条普通新闻，无横向溢出；新闻详情页可打开，标题、封面和公开详情结构正常，控制台无错误。

### 移动端首屏密度 follow-up（2026-06-22）

- 在不改变首页数据层、公开 URL、模板结构或普通新闻卡尺寸的前提下，后续小幅收紧移动端首页视觉密度。
- 调整范围仅限 `server/stable/static/stable/public.css` 的 `max-width: 599px` 移动端规则：
  - 顶部和页面内边距略收紧。
  - 移动端头条图片从 `16 / 9` 改为 `16 / 7`。
  - 移动端头条摘要隐藏，仅保留来源时间和两行标题。
  - 普通新闻卡继续保持约 `128px` 高和右侧缩略图结构。
- 本地临时 SQLite + 浏览器验收结果：390px 视口下头条高度约 `250px`，第一张普通新闻卡提前到 `top=381`，首屏可见 4 条普通新闻卡，无横向溢出，控制台无错误。
- 生产部署结果（2026-06-23）：GitHub PR #2 合并到 `main`，merge commit 为 `04e2ee9`；服务器 `/opt/umanewsbot` 从 `e834f58` 快进到 `04e2ee9`，部署前备份 `.env` 为 `.env.backup.20260623_120201`。
- 生产 `./deploy_lowcost.sh` 执行成功：`migrate` 显示 `No migrations to apply`，`collectstatic` 后首页引用 `/static/stable/public.9aaf4b105424.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`；首页包含 `home-page`、`headline-card`、`news-card` 和“原站热度”，不再引用 `console.css`。
- 浏览器生产验收：390px 移动端头条约 `257px` 高，第一张普通新闻卡 `top=388`，普通卡约 `128px` 高，首屏可见 4 条普通新闻卡，无横向溢出；详情页公开结构、封面和标题正常，控制台无错误。

## 2026-06-07 术语候选发现生产部署纪要

### 部署内容

- 服务器 `/opt/umanewsbot`：`git pull origin main` 从 `7123e4e` 快进到 `e2e3e07`
- 迁移 `0006`（纯新增 `TermCandidate` / `TermCandidateEvidence` 两表）已应用；`web` 启动脚本会自动迁移，显式 `migrate` 显示 `No migrations to apply`
- `.env` 追加并保持关闭：`TERM_DISCOVERY_ENABLED=false` / `TERM_DISCOVERY_PROVIDER=rules` / `TERM_DISCOVERY_MIN_CONFIDENCE=60`
- 用低成本 compose `docker-compose.prod.lowcost.yml` 重建 `web/worker/beat`，`db/redis/nginx` 未动

### 迁移前备份（可回滚）

- `.env.backup.20260607_033207`
- 数据库快照 `backups/pre-0006-20260607_033207.sql`（74M，`horse_news` 库，含 `PostgreSQL database dump complete` 标记）

### 上线后验证

- 容器 `web/db` healthy、`worker/beat` up；`manage.py check` 0 issues
- 候选/证据模型可查、计数 `0/0`；`nginx → web` 与外网 `umafans.run` / `www.umafans.run` 均 `200`
- `worker` 近 200 行日志无报错；核对 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 未变更

### 回滚方式

- 停用功能：将 `TERM_DISCOVERY_ENABLED=false`（当前即为关闭），重启 `web` 与 `worker` 即可，无需回滚迁移或删除候选数据
- 整体回退：用上面的 `.env` 备份与数据库快照还原

## 最近一次翻译稳定性修复

- 现象：部分文章翻译失败，错误为 `Translation response changed unknown horse names`
- 原因：未知马名校验过于严格；模型没有原样保留疑似未收录马名时，系统会让整篇翻译失败
- 修复：
  - 翻译 prompt 中对未知马名使用 `__UMA_KEEP_n__` 占位符保护
  - 模型返回后将占位符还原为原始日文马名
  - 若模型仍未保留未知马名，不再让整篇失败，而是写入 metadata warning 后接受译文
- 验证：
  - 新增未知马名占位符还原测试
  - 新增未知马名仍缺失但不阻断翻译的测试
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable` 通过，45 项

## 自动化内容运营 MVP 开发纪要

### 本轮新增能力

- `NewsArticle` 增加自动化字段：分流模式、风险等级、自动化状态、评分、决策原因、基准翻译稿、改写稿、自动发布时间与错误信息
- 新增 `AutomationLog`，记录评分、改写、校验、发布、通知各阶段过程
- 新增 `NotificationLog`，记录邮件 / 短信 / QQ / 微信通知状态；MVP 真实发送只启用邮件
- 新增自动化服务：
  - `stable.services.automation`
  - `stable.services.rewriting`
  - `stable.services.validation`
  - `stable.services.notifications`
- 新增 Celery 任务：
  - `process_article_automation_task`
  - `score_article_task`
  - `rewrite_article_task`
  - `validate_rewrite_task`
  - `auto_publish_batch_task`
  - `send_notification_task`
  - `detect_automation_anomalies_task`
  - 新增 Celery Beat 调度：
    - 每 15 分钟批量自动发布
    - 每 30 分钟检测自动化异常
  - 自动发布批量规则已调整为：
    - 常规时段每批最多 4 篇
    - 每周日北京时间 13:00-16:00 每批最多 10 篇
    - 调度频率仍为每 15 分钟一次

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，40 项测试

### 生产启用前注意

- 必须先部署代码并执行迁移 `python manage.py migrate`
- 初次部署建议 `AUTOMATION_ENABLED=false`
- 确认后台可看到自动化字段和日志后，再切换 `AUTOMATION_ENABLED=true`
- 当前自动发布策略为常规每批 4 篇、周日 13:00-16:00 每批 10 篇，并定期人工抽检自动发布稿

## 专有术语候选发现与待标注池

### 当前实现

- 新增 `TermCandidate` 与 `TermCandidateEvidence`，分别保存待审核术语和按文章聚合的来源证据。
- 首版支持马名、比赛名、骑手名和马主名四类实体。
- 新文章入库后可旁路触发发现任务；发现失败不会阻断抓取、翻译、改写或发布。
- 候选会与正式 `TermEntry.source_ja`、日文别名及已有候选去重；停用正式术语也参与去重。
- 后台新增“术语候选”列表、详情、单篇重新发现、接受、修改后接受、合并、拒绝、忽略和保守批量拒绝/忽略。
- 规则或 AI 发现结果不会直接写入正式术语库，只有工作人员明确接受后才创建 `TermEntry`。

### 当前启用策略

- `TERM_DISCOVERY_ENABLED=false`：默认关闭。`2026-06-07` 已在生产应用迁移并部署代码，当前处于“先关后开”灰度阶段，待单篇抽检后再开启。
- `TERM_DISCOVERY_PROVIDER=rules`：首版使用保守规则发现器。
- `TERM_DISCOVERY_MIN_CONFIDENCE=60`：低于阈值的发现结果不进入候选池。

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，69 项。
- `旧规格流程 validate --all`：通过。
- 两种生产 Compose 配置基于 `.env.example` 检查通过。
- 已使用独立 SQLite 数据库部署本地验收环境，并通过浏览器完成筛选、单篇重跑、接受、合并、拒绝、忽略、批量操作、操作日志和别名搜索验收。

## 最近一次关键修复纪要

### 现象

- 域名已经解析到服务器 IP
- HTTP 请求被 `301` 跳转到 HTTPS
- HTTPS 请求返回 `400 Bad Request`
- 浏览器无法正常打开正式域名页面

### 排查过程

- 先确认 DNS 是否已经真正打通，排除“域名未解析”的假象
- 再比对仓库当前代码与服务器实际 `HEAD`
- 检查服务器 `.env` 中的 `ALLOWED_HOSTS`、`SITE_URL`、`SECURE_SSL_REDIRECT` 等关键项
- 进入 `nginx` 容器读取真实 `/etc/nginx/conf.d/default.conf`
- 检查 `web` 容器运行态环境变量与日志
- 最终确认线上实际行为与仓库当前预期不一致

### 确认的真实根因

- 服务器并未运行到本地最新域名接入修复版本
- 服务器仍在使用旧版 `nginx` 配置，保留 `80 -> 443` 跳转与启用中的 HTTPS server block
- 服务器 `.env` 仍使用旧版 IP + HTTPS 强制配置
- `ALLOWED_HOSTS` 未包含正式域名，导致域名下请求被 Django 拒绝

### 修复动作

- 备份服务器 `.env`
- 清理或暂存本地未提交运行态差异
- 将服务器代码同步到正确版本
- 更新 `.env`，切换为正式域名 + HTTP 阶段配置
- 重建并启动 `web / worker / beat / db / redis / nginx`
- 进入容器核对真实 `nginx` 配置与环境变量，确保运行态与仓库一致

### 修复后验证结果

- `nginx` 容器加载了新版 `default.conf`
- `80 -> 443` 强制跳转已移除
- 正式域名 `umafans.run` / `www.umafans.run` 页面可打开
- 线上服务恢复到与当前仓库预期一致的状态

### 后续如何避免再次发生

- 每次部署前先确认服务器 `HEAD`，不要只看本地仓库
- 每次域名或安全策略变更时，同时核对：
  - 仓库代码
  - 服务器 `.env`
  - `nginx` 容器内真实配置
  - `web` 容器内真实环境变量
- 不把聊天记录当唯一记忆来源，关键修复过程必须落文档
- 生产问题处理时，坚持“先核对运行态，再给结论”

## 2026-06-23 外部赛马数据导入实现状态

### 本地已实现

- 新增 旧规格流程 change：`add-netkeiba-horse-data-import`。
- 新增 `keibascraper==3.1.5` 依赖，并通过管理命令提供 import 冒烟检查入口。
- 新增外部赛马数据表：比赛、出走表、赛果、赔率、马匹、马匹履历、马名索引、导入运行、导入错误和单来源导入锁。
- 新增 `stable.services.external_horse_data`：
  - 包装 `keibascraper.race_list()` 与 `keibascraper.load()`。
  - 项目侧强制执行网络开关、请求间隔、随机抖动。
  - 保存结构化字段与 `raw_payload`。
  - 对比赛、出走、赛果、赔率、马匹、履历做幂等 upsert。
  - 从出走表、赛果、可信单马参数派生 `ExternalHorseAlias`。
  - 单马导入仅在存在可信马名时创建马名索引，避免凭空写入错误马名。
  - 记录覆盖率统计：比赛数、出走数、赛果数、赔率数、马匹数、履历数、唯一马 ID、唯一日文马名、缺失马 ID/马名记录数。
- 新增管理命令 `import_external_horse_data`：
  - 支持默认近两年、指定年月、指定 `race_id`、指定 `horse_id`、`--horse-name`、`--dry-run`。
  - 支持 `--max-races`、`--max-horses`、`--fetch-odds`、`--no-fetch-horse-detail`。
  - 支持 `--lookup-name` 查询本地马名索引。
  - 支持 `--stats-run-id` 查看导入运行统计。
  - 支持 `--check-dependency` 检查 `keibascraper` 是否可 import。
- 新增 Celery 任务 `import_external_horse_data_task`，但未加入默认 Celery Beat 全量调度。

### 当前默认策略

- `EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false`。
- `EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
- 代码已可部署迁移，但生产不会自动发起 netkeiba 请求。
- 外部数据导入当前不参与新闻抓取、翻译、AI 改写、自动发布或公开前台。

### 本地验证

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ExternalHorseDataImportTests`：通过，8 项。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，96 项。

### 生产执行提醒

- 生产首次真实导入前必须备份数据库。
- 先执行 dry-run 或单月小批量。
- 首次真实请求建议使用 8-10 秒间隔、小批量、低峰时段，不抓赔率。
- 同一来源通过导入锁避免多 worker 并发放大请求。
- 如发现异常，优先关闭 `EXTERNAL_HORSE_DATA_IMPORT_ENABLED` / `EXTERNAL_HORSE_DATA_ALLOW_NETWORK` 并停止任务；新表不参与主新闻链路。

### 生产首轮小批量导入结果

- 生产部署提交：`58a6e82`。
- 部署前 `.env` 备份：`.env.backup.external-horse-data-20260623_231514`。
- 服务器迁移：`stable.0008_externaldataimportrun_externaldataimportlock_and_more` 已应用。
- 容器内依赖检查：`keibascraper import ok`。
- dry-run：`2026-05` 单月、小批量、最多 10 场，预计 20 个请求。
- 真实导入命令：`2026-05`、`--max-races 10`、`--max-horses 30`、不抓赔率、不补马匹详情、请求间隔 10 秒 + 2 秒抖动。
- 运行结果：`run_id=1`，`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=326`。
- 写入统计：`race_count=10`、`entry_count=151`、`result_count=143`、`horse_count=143`、`unique_horse_id_count=143`、`unique_horse_name_count=143`、`missing_horse_id_or_name_count=16`。
- 样本马名索引已写入，如 `ヴォルスター`、`ファイツオン`、`サトノエピック`。

### 后续继续导入注意

- `2026-06-24` 已补充按月续跑逻辑：再次导入同一月份时会先跳过已落库的 `ExternalRace.race_id`，只处理下一批未导入 race。
- 不建议直接一次性跑近两年全量；应继续按月、小批量、低速运行，并观察失败率和覆盖率。

### 生产第二批续跑结果

- 续跑部署提交：`a61d789`。
- 第二批真实导入：`run_id=2`，同为 `2026-05`，最多 10 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 续跑确认：`parameters.already_imported_race_count=10`，说明第二批已跳过首批落库 race。
- 运行结果：`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=316`。
- 累计写入统计：`race_count=20`、`entry_count=292`、`result_count=274`、`horse_count=274`、`unique_horse_id_count=274`、`unique_horse_name_count=274`、`missing_horse_id_or_name_count=36`。

### 生产第三批续跑结果

- 第三批真实导入：`run_id=3`，仍为 `2026-05`，最多 30 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 运行结果：`status=paused`，`success_count=30`，`failure_count=0`，`skipped_count=286`。
- 累计写入统计：`race_count=50`、`entry_count=742`、`result_count=695`、`horse_count=695`、`unique_horse_id_count=695`、`unique_horse_name_count=695`、`missing_horse_id_or_name_count=94`。
- 服务器健康检查：`/healthz/` 返回 `200`。

### 生产长循环导入中断记录

- `2026-06-24` 按用户确认启动长循环：从 `2026-05` 到 `2025-06`，每批 25 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 成功完成批次：`run_id=4` 到 `run_id=8`，均为 `2026-05`，每批 25 场，均 `failure_count=0`。
- 中断批次：`run_id=9`，`2026-05`，已成功 7 场后执行进程以退出码 `137` 中断；当时 `web/db` 容器发生重启，但 `OOMKilled=false`。
- 已人工收尾：将 `run_id=9` 标记为 `partial`，写入 `finished_at` 和 coverage，释放 `ExternalDataImportLock`。
- 中断后累计写入：`race_count=182`、`entry_count=2692`、`result_count=2518`、`horse_count=2401`、`unique_horse_id_count=2401`、`unique_horse_name_count=2401`、`missing_horse_id_or_name_count=348`。
- 当前服务状态：`web/db/redis/nginx/worker/beat` 运行，`/healthz/` 返回 `200`。按“报错退出则停止”约定，未继续启动后续导入。

## 后台原文选区快速加入术语库

- 旧规格流程 change：`add-selection-term-quick-add`。
- 本地分支：`codex/add-selection-term-quick-add`。
- 实现时间：`2026-06-24`。
- 状态：已于 `2026-06-25` 合并到 `main` 并部署生产，旧规格流程 已归档为 `旧规格流程/changes/archive/2026-06-24-add-selection-term-quick-add/`。

### 已实现能力

- 候选详情页和文章编辑台的原文标题、原文正文已标记为可选区来源。
- 两个页面都新增“快速加入术语库”入口；管理员可点击“使用当前选区”填入日文原词，也可手工粘贴作为无 JavaScript fallback。
- 快速表单字段包含日文原词、术语类型、中文译词；术语类型默认 `horse`（马名），但可改为赛事、骑手、调教师、马主、牧场、赛马场、机构、固定译法或其他。
- 后端新增文章上下文 POST 入口 `console-article-quick-term-create`，路径为 `/admin/articles/<article_id>/quick-term/`。
- 创建正式术语时复用 `validate_term_payload()`，继续执行正式术语库的类型、重复、比赛等级、启用状态和优先级校验。
- 快速创建默认写入：`is_active=true`、`priority=0`、`race_grade=""`、`aliases_ja=[]`、`aliases_zh=[]`，并在 `notes` 记录来源文章 ID 和标题。
- 创建成功后留在当前页面并显示成功消息，同时写入 `OperationLog`。
- 创建失败时不写入 `TermEntry`，通过 messages 展示错误；重复术语提示已有术语 ID，并提供已有术语编辑页链接。

### 明确边界

- 快速加入术语库只写入 `TermEntry` 和操作日志。
- 不触发 `translate_article_task`，不触发自动化处理，不修改当前文章的 `title_zh`、`body_zh`、`base_translation_zh` 或 `rewrite_body_zh`。
- “新增术语后自动重新应用术语/重翻译联动”仍属于后续 change，不在本次实现中。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 三个运营改造 change 合并、部署与归档`。

### 验证结果

- `DB_ENGINE=sqlite python manage.py check` 已通过（本地使用 Codex bundled Python 执行）。
- `DB_ENGINE=sqlite python manage.py test stable.tests.ConsoleFlowTests --verbosity=2` 已通过；本轮按 旧规格流程 场景补齐非法术语类型、换行误选整段、文章不存在、非联动状态保持和原文选区脚本限制等测试。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --verbosity=2` 已通过，126 个测试全部通过。
- `旧规格流程 validate add-selection-term-quick-add --strict` 已通过。
- 本地浏览器验收使用临时 SQLite 后台：
  - 候选详情页可创建术语并返回当前候选页。
  - 候选详情页重复创建同类型同日文原词时显示失败提示和已有术语编辑链接。
  - 编辑台快速术语入口已验证不会提交外层文章编辑表单；提交成功后返回编辑台。
  - 无选区点击“使用当前选区”不会乱填，提示需在原文标题或正文中选择短词。

## 后台快速术语创建后的当前稿联动提案

- 旧规格流程 change：`reapply-terms-after-quick-add`。
- 创建时间：`2026-06-24`。
- 当前状态：本地实现和验证已完成；review 后的浮层交互和多标签页 session pending 返修已于 `2026-06-25` 完成，并已随 `7f54f13` 部署生产。旧规格流程 已归档为 `旧规格流程/changes/archive/2026-06-24-reapply-terms-after-quick-add/`。
- 目标：在候选详情页或文章编辑台快速创建正式术语后，为当前文章提供明确的后续动作：
  - 一次性“应用该术语到当前稿”：只把刚创建的指定术语应用到当前文章整篇已有中文字段，不调用翻译模型，不重扫整个正式术语库。
  - 页面级“重新翻译”：复用现有 `translate_article_task`，异步重新走翻译链路；不属于术语成功浮层，若页面已有按钮则不新增。
- 关键边界：
  - 不做全站批量重翻译或批量重应用。
  - 快速创建成功后的应用入口只出现一次；刷新、离开页面或错过成功反馈后不补常驻入口。
  - 不自动发布文章，不改变前台发布过滤规则。
  - 默认保护 `manually_edited_fields` 中的人工标题、正文、摘要和推送摘要，不在无确认时覆盖人工稿。
  - 术语应用必须记录文章、用户、来源术语、更新字段和跳过字段；页面级重新翻译继续记录文章、用户和任务触发结果。
- 实现范围：
  - 新增指定术语应用服务函数，只替换刚创建术语的日文原词和日文别名。
  - 新增后台 POST 入口 `/admin/articles/<article_id>/apply-created-term/`。
  - quick-create 成功后通过 session 多 pending 字典提供一次性后续动作上下文；候选详情页和编辑台只消费匹配当前文章与页面上下文的 pending follow-up。
  - `candidate_retranslate` 改为安全返回，并继续作为页面级重新翻译入口记录任务触发结果；术语成功浮层不提供重翻译入口。
  - 候选详情页和编辑台已改为页面上方浮层：`术语【日文名（中文名）】已添加，点击此处立即应用到文章中`；浮层只承载当前术语应用，不承载重新翻译。
  - 旧的术语表单内嵌“刚创建术语”面板和 `retranslate-created-term-*` follow-up 表单/按钮已删除；重新翻译仅保留页面级既有入口。
  - 浮层点击“点击此处”立即应用，不再二次确认；点击关闭 icon、应用成功、当前页面新术语浮层出现、关闭页面或 15 秒超时后消失。
  - 浮层不阻塞选区、滚动、编辑和其他不离开当前页面的点击行为。
  - session follow-up 已从全局单槽改为多 pending 结构，避免多标签页之间互相覆盖；渲染不匹配文章或上下文时不会消费其他 pending follow-up。
  - 后端不额外增加一次性 token 限制；当前后台仅单人可信使用，手工构造接口请求被视为可接受风险。
- TDD 测试：
  - `2026-06-25` 已先在 `server/stable/tests.py` 补充完整测试约束，覆盖浮层文案、关闭/15 秒 DOM 合同、旧内嵌面板不存在、`retranslate-created-term-*` 不存在、多 pending、不匹配页面不消费 pending、同页新术语替换旧浮层，以及应用术语不派发翻译任务。
  - 红灯阶段结果：未实现新交互前，`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ConsoleFlowTests --noinput` 为 31 项中 5 项失败，失败集中在旧内嵌面板和单槽 session。
- 本轮验证结果：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.ConsoleFlowTests --noinput`：通过，31 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，135 项。
  - `旧规格流程 validate reapply-terms-after-quick-add --strict`：通过。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 三个运营改造 change 合并、部署与归档`。
- 规格校验：`旧规格流程 validate reapply-terms-after-quick-add --strict` 已通过。

## 2026-06-25 外部马名索引接入识别链路本地实现

- 旧规格流程 change：`use-external-horse-alias-for-name-recognition`。
- 创建时间：`2026-06-25`。
- 当前状态：本地实现、验证、旧规格流程 归档和生产部署已完成；归档目录为 `旧规格流程/changes/archive/2026-06-25-use-external-horse-alias-for-name-recognition/`。
- 背景：近两年外部赛马数据已导入 `ExternalHorseAlias`，当前未知马名识别仍主要依赖片假名 token + 上下文打分，无法真正判断没见过的片假名词是不是普通词，容易把 `タイトル` 等普通词误判为马名，也可能漏掉 `マヤノライジン` 等真实马名。
- 核心边界：
  - `TermEntry` 继续表示有中文译名或固定译法的正式术语，参与翻译术语表、译后替换和正式术语校验。
  - `ExternalHorseAlias` 只表示本地外部马名索引，用来确认“这是马名”，不代表已有中文译名，不批量写入 `TermEntry`。
  - 新闻处理链路只查询本地数据库，不在翻译、校验或候选发现阶段实时访问 netkeiba / keibascraper。
- 已实现能力：
  - `server/stable/services/terms.py` 新增结构化马名识别结果，区分 `formal_term`、`external_alias` 和 `heuristic`，并保留旧字符串列表接口兼容既有调用。
  - 识别链路会先提取候选片假名 token，做 NFKC 标准化，再批量查询本地 `ExternalHorseAlias.normalized_name__in`；同一日文名多次出现时按文章出现顺序和长词优先去重。
  - 正式 `TermEntry(term_type=horse)` 优先于外部马名索引；已存在正式中文译名的马名继续走正式术语提示和替换，不再作为未知马名保护。
  - 翻译阶段对外部已知但无中文译名的马名做占位符保护，译后还原为日文原名，不自动替换为中文；翻译 metadata 会记录 `recognized_horse_names` 和 `external_horse_names`。
  - 发布校验阶段把外部已知马名未保留记录为独立 `external_horse_not_preserved` warning，payload 包含日文名、全部外部 horse ID、主展示 ID、来源、置信度和冲突标记；只命中外部索引的马名不触发核心术语或背景术语缺失。
  - 术语候选发现阶段把新闻中出现、外部索引命中但无正式中文译名的马名均作为 `external_horse_alias` 高置信候选来源，包括正文背景段落中的马名；已有正式马名术语或日文别名时不重复建候选。
  - 若片假名文本同时命中普通词过滤表和外部马名索引，必须依赖强马名上下文消歧，不能仅因数据库存在同名马就识别为马名。
  - 同一日文马名对应多个外部 horse ID 时，识别结果和校验 payload 保留全部 ID，不静默只取第一条。
- `2026-06-25` review 返修：
  - `limit` 只限制需要原样保留的外部已知马名和启发式疑似马名，不再让已有中文译名的正式马名占用保护名额。
  - `extract_unknown_horse_names()`、翻译阶段和发布校验阶段均改为先取完整结构化识别结果，再对 `needs_preserve=True` 的名单截断。
  - 新增回归测试覆盖“前面出现多个正式马名，后面出现外部已知但无中文译名马名”时，翻译保护和发布校验仍能命中后者。
- 已创建规格：
  - `external-horse-name-recognition`：新增本地外部马名索引识别能力。
  - `termbase-and-race-priority`：修改翻译链路正式术语命中，并新增外部已知马名保留校验。
  - `term-candidate-discovery`：修改候选发现，使外部马名索引成为高置信来源且不绕过正式术语审核。
- 已同步正式规格：
  - `旧规格流程/specs/external-horse-name-recognition/spec.md`
  - `旧规格流程/specs/termbase-and-race-priority/spec.md`
  - `旧规格流程/specs/term-candidate-discovery/spec.md`
- 验证结果：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests stable.tests.TermCandidateDiscoveryTests --noinput`：通过，49 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests --noinput`：review 返修后通过，39 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：review 返修后通过，147 项。
  - `旧规格流程 validate use-external-horse-alias-for-name-recognition --strict`：通过。
  - `旧规格流程 validate --all`：归档前后均通过。
- 生产部署结果：
  - GitHub PR #6 `[codex] Use external horse aliases for name recognition` 已 squash merge 到 `main`，merge commit 为 `35b0866`。
  - 服务器 `/opt/umanewsbot` 已从 `817e1c8` 快进到 `35b0866`，部署前 `.env` 备份为 `.env.backup.external-horse-alias-20260625_182936`。
  - `./deploy_lowcost.sh` 执行成功，迁移显示 `No migrations to apply`，`collectstatic` 完成，`web` 容器 healthy，`worker / beat` 已重启。
  - 生产验证通过：`manage.py check` 无问题，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和 `http://umafans.run/` 均返回 `200`。
  - 生产只读 smoke test：`ExternalHorseAlias` 数量为 `11521`；`recognize_horse_names("ロブチェンが出走", ...)` 返回 `ロブチェン`，来源为 `external_alias`，外部 horse ID 为 `2023107089`。
- 长文样本抽检：
  - 抽检方式：从生产只读导出 5 篇长文、2054 条启用正式术语和 11521 条 `ExternalHorseAlias`，写入本地临时 SQLite 后用当前未部署代码跑识别、候选发现和发布校验；未改生产数据。
  - 样本结果：netkeiba 长文中外部索引可命中多匹真实马名，例如 `ロブチェン`、`パントルナイーフ`、`ミクニインスパイア`、`ドリームコア` 等，并在译文未保留时产生独立 `external_horse_not_preserved` warning。
  - 观察到的后续优化点：JRA 活动公告类长文（例如 `JRA宮崎育成牧場けいばフェスタ`）仍会通过启发式把 `フェスタ`、`ウインズ`、`イベント`、`ポニー`、`オリジナル` 等普通片假名词列为疑似未知马名；外部马名索引能降低真实马名漏报，但不能完全替代后续普通词过滤和启发式收紧。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 外部马名索引识别链路生产部署`。

## 2026-06-25 国际赛马资讯扩展本地实现

- 旧规格流程 change：`expand-international-racing-coverage`。
- 当前状态：本地代码、迁移、测试、文档和 review 返修已完成；尚未部署生产，生产仍以已上线的日本新闻源和既有 QQ 推送配置为准。
- 已落地能力：
  - `NewsSource`、`NewsArticle`、外部数据缓存、`TermEntry`、`TermCandidate` 和 `PushTarget` 已增加地区、原文语言、来源类型或群级推送配置字段；现有数据默认回填为 `japan / ja`。
  - 内置来源同步已增加一期国际新闻源最终清单：`Sponichi`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing`、`BHA`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation`。新来源默认 `enabled=false`，需要人工启用或测试抓取；2026-06-26 review 返修后，内置来源同步只更新来源定义，不再覆盖工作人员手动调整的 `enabled` 状态。
  - 已补充排序型入口策略：类似 netkeiba 访问量榜/注目榜的来源，只有在公开 HTML/API 能稳定慢速抓取时才作为独立榜单源接入。本轮确认 `Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可抓，均作为独立排序/榜单来源加入并保留原站 rank；2026-06-26 review 返修后，同源普通 list 不会覆盖已入库的排序/榜单主来源，普通 list 仍会记录 `NewsSnapshot`；旧候选 `At The Races`、`Paulick Report`、`BloodHorse` 因 403、反爬或空样本风险不进入第一版默认清单。
  - 公开首页新增 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，`/?region=<region>` 过滤头条、信息流和热门列表；地区页翻页会保留当前 `region` 查询参数，不会翻页后跳回综合流；文章详情展示地区、来源和原文语言。
  - 术语库 UI 和服务语义已从“日文原词/日文别名”扩展为“原文/原文别名/原文语言”，并新增 `TermAlias` 作为多语言原文别名表；`TermEntry` 表示正式术语概念和标准中文译名，旧 `source_ja / aliases_ja` 物理字段继续兼容并回填为 `ja` 别名。
  - 翻译、改写、发布校验、候选发现、自动标签和自动化评分会按文章 `source_language` 选择对应 `TermAlias`；日文片假名未知马名启发式只应用于 `ja`，英文和繁中不套日文规则，但会按同语言 `ExternalHorseAlias` 做保守外部马名匹配；英文候选可合并到日文正式术语概念并保存为英文别名。2026-06-26 review 返修后，术语匹配和自动化 P0 马匹命中会按本次候选术语批量加载 `TermAlias`，避免每条术语各查一次别名；英文/繁中外部马名识别会先从文章文本生成候选片段收窄数据库查询，并使用原文中实际出现的大小写/写法作为保护文本；翻译保护、发布校验和候选发现也统一使用真实匹配文本，英文正式术语按大小写不敏感方式命中并记录原文真实写法；最终 review 返修后，自动化 P0 马匹命中、发布校验的核心/背景术语判定、以及“新增术语后应用到当前稿”均复用同一套语言感知匹配，避免 `EQUINOX` 这类大写英文漏判或漏替换。本轮补丁进一步将同语言术语查重、别名去重、导入 upsert、候选合并和术语 API 保存统一为大小写不敏感；同语言大小写变体导入 upsert 会更新正式主原文并同步别名表，跨语言别名 upsert 仍只维护该语言别名、不覆盖概念主原文；后台/API 启停术语时会同步所有语言 `TermAlias` 的启用状态；AI 改写 prompt 的术语表也使用本次文章实际命中的 `matched_text`，避免英文稿看到日文概念主名而漏用标准译名。本次返修明确术语导入 upsert 的目标解析：主原文命中同一术语时才更新；如果只是原文别名命中已有其它术语，预览和提交都会拒绝该行，避免把两个正式概念误合并。
  - 自动化评分已补充英文和繁体中文赛马关键词表，英文 `preview / entries / draw / withdrawn / injury / results / stewards` 等信号会参与分类、高关注命中和重点赛事 fallback，不再只依赖日文关键词。
  - QQ 自动推送保留 `QQ_PUSH_ENABLED` 总开关；每个 `PushTarget` 可配置 `allowed_regions`、`push_scope`、`importance_strategy`。总开关管“能不能推”，群配置管“推什么给谁”；文章地区缺失时返回 `region_missing` 并不自动推送。2026-06-26 review 返修后，`importance_strategy=ranked` 不再只认 netkeiba，也会把 `Sponichi / Sky Sports Racing / Horse Racing Nation` 的排序/榜单稿视为重点新闻；已有群迁移会把空 `allowed_regions` 回填为 `["japan"]`，运行时空地区或非法地区配置也按旧行为仅允许日本，避免旧群或误配置群突然收到全球新闻。
  - HKJC 外部数据新增 `import_hkjc_external_data` 管理命令和 `HKJCExternalDataImporter`，支持 `--race-date`、`--race-id`、`--horse-id`、`--payload-file`、`--commit`、`--lookup-name`、`--stats-run-id`，默认 dry-run；提交只写 External* 缓存表和 `ExternalHorseAlias`，不生成前台赛果页。commit 模式在真实网络抓取实现前必须提供 `--payload-file`，并参考 netkeiba 外部导入使用单来源互斥锁，已有 `STARTED` 导入时拒绝并发写入；payload 超过 `max_races / max_horses` 时直接失败，不静默截断或部分写入。2026-06-26 review 返修后，`max_horses` 会合并统计顶层 `horses`、赛事 `entries` 和 `results` 中可识别的唯一马匹，避免 entries/results 里的大量马绕过批量上限。
  - 公开详情 URL 继续使用 `/news/<NewsArticle.id>/` 全局自增数字 ID；国际新闻源的 `source_article_id` 只作为来源内幂等去重键，使用完整 URL 派生的 `slug-short_hash`，避免同 slug 不同路径碰撞。
  - 国际新闻原始 HTML 只写入 `original_content_html`；`translation_metadata` 和 `NewsSnapshot.snapshot_metadata` 只保留轻量抓取/翻译元信息，不再重复保存整页 HTML；TDN 等列表 API 提供真实发布时间的来源，在详情页缺少日期节点时会回退使用列表时间；`TDN France keyword` 与美国 `TDN` 来自同一站点，入库时使用 `TDN` canonical source site 和同一 `source_article_id` 去重，`NewsSnapshot` 仍记录实际发现来源，法国关键词来源会优先保留法国地区归类。
  - 欧美数据库源 spike 结论已写入 `docs/global_racing_data_source_spikes.md`；本轮 spike 不加入 Celery Beat、生产命令队列或正式导入队列，不写正式外部数据表。
- 本轮新增迁移：
  - `server/stable/migrations/0011_remove_termcandidate_uq_term_candidate_type_normalized_and_more.py`
  - `server/stable/migrations/0012_termalias.py`
  - `server/stable/migrations/0013_alter_newsarticle_source_site_and_more.py`
- 本轮新增/调整的关键入口：
  - 新闻来源同步：`server/stable/services/sources.py`
  - 国际新闻适配器：`server/stable/adapters/international.py`
  - 国际新闻真实探测命令：`server/stable/management/commands/probe_international_news_sources.py`
  - QQ 群级推送判断：`server/stable/services/qq_auto_push.py`
  - HKJC 数据导入：`server/stable/services/external_hkjc_data.py`
  - HKJC 管理命令：`server/stable/management/commands/import_hkjc_external_data.py`
  - 公开首页地区 tab：`server/stable/views.py`、`server/stable/templates/stable/public/feed.html`
- 已完成的本地验证：
  - `旧规格流程/changes/expand-international-racing-coverage/test_cases.md`：已新增完整测试用例矩阵，按 旧规格流程 `proposal/design/spec` 拆分，不依据实现代码倒推；覆盖地区/语言、国际新闻源、公开首页、术语多语言、QQ 群级推送、HKJC 导入、欧美数据源 spike、迁移和非目标边界。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AdapterTests stable.tests.InternationalSourceMetadataTests stable.tests.HKJCExternalDataImportTests stable.tests.AutomationFlowTests --noinput`：通过，35 项。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.InternationalSourceMetadataTests stable.tests.QQAutoPushTests --verbosity 2`：通过，26 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：最终源清单返修前通过，201 项；返修后通过，209 项；2026-06-26 上线前 review 返修后通过，210 项；第二轮 review 返修后通过，214 项，新增覆盖人工来源启用保留、国际榜单来源提升、普通 list 不覆盖榜单主来源、QQ ranked 识别国际榜单稿；本次 review 补丁后通过，217 项，新增覆盖国际榜单来源提升后触发 QQ 自动推送编排、英文外部马名索引识别、术语导入 upsert 命中跨语言别名时保留正式概念主原文；术语批量别名和 HKJC 上限口径返修后通过，219 项；本轮全球范围适配 review 返修后通过，224 项，新增覆盖英文外部马名真实写法保护、非日文外部别名候选查询、旧 QQ 群空地区日本兼容、地区 tab 翻页保留过滤和英文赛马关键词评分；本轮 review 返修后通过，227 项，新增覆盖翻译保护使用英文外部马名真实写法、发布校验不误报已保留真实写法、英文正式术语大小写不敏感匹配与替换；最终 review 补丁后通过，231 项，新增覆盖英文 P0 马匹自动化评分大小写不敏感命中、英文核心术语缺失大小写不敏感阻断、新增英文术语应用当前稿大小写不敏感替换、QQ 群非法地区配置回退日本旧行为；本轮术语生命周期补丁后完整 `stable` 测试通过 236 项，新增覆盖英文重复术语大小写不敏感拒绝、API 创建/更新同步 `TermAlias`、术语启停同步别名状态、候选合并大小写去重、同语言大小写变体导入 upsert 更新主原文，以及 AI 改写 prompt 使用英文实际命中别名；本次上线前返修后完整 `stable` 测试通过 241 项，新增覆盖术语导入 upsert 原文别名冲突预览/提交双重拒绝、`TDN France keyword` canonical 去重并保留法国地区信号、以及术语列表分页保留原文语言筛选。
  - `旧规格流程 validate expand-international-racing-coverage --strict`：通过。
  - `旧规格流程 validate --all`：通过，9 项。
  - `git diff --check`：通过。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py makemigrations --check --dry-run`：通过，无额外迁移。
- 国际新闻源 dry-run 探测：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py probe_international_news_sources --limit 2 --json`：已执行，不写库。
  - 默认第一版矩阵成功解析两篇真实样本：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing access/latest`、`BHA official`、`France Galop English News official`、`TDN France keyword`、`TDN`、`Horse Racing Nation access/latest`。
  - 榜单/排序入口结论：`Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可抓并保留原站 rank；`HKJC Racing News`、`SCMP Racing`、`BHA`、`France Galop English News`、`TDN` 当前不按热门榜处理。
  - 旧候选源处理：`At The Races` 当前 403，`Paulick Report` 当前 403，`BloodHorse` 有反机器人/空样本风险；三者仍保留适配器供后续单独探测，但不进入第一版默认清单。
- 生产注意事项：
  - 本变更含数据库迁移，部署前必须确认没有正在运行的外部数据导入。
  - 国际新闻源默认关闭；生产启用前应先完成一次整体 review，再按地区逐个灰度启用，并用后台“测试抓取”或命令行小样本复验页面结构。
  - HKJC 正式网络导入仍应小批量、低频、单来源互斥，并从 `--payload-file --dry-run` 或单场小样本开始；如样本超过 `max_races / max_horses`，应先拆分 payload，而不是依赖程序截断。

## 2026-07-10 多地区新闻归属与英文门禁实现

- 旧规格流程 change：`support-multiregion-news-attribution-and-english-gates`，当前已完成本地实现，待线上前执行生产 dry-run 抽样。
- 数据模型：保留 `NewsArticle.racing_region` 作为主地区，新增 `NewsArticleRelatedRegion` 独立表记录关联地区，并增加 `attribution_source / attribution_summary / attribution_locked` 归属元数据；新增迁移 `0023_multiregion_news_attribution.py`。
- 归属口径：新采集文章和自动化打分前会运行 `stable.services.news_attribution.apply_article_attribution()`；顺序为赛事/赛场信号优先，其次马、骑手、练马师、马主等核心对象，再回退来源地区。法国来源涉及海外赛事时进入法国池和比赛地区池；爱尔兰内容暂归英国并写入 `ireland` 标签。人工归属是否锁定由编辑页显式开关决定，锁定后自动重算不覆盖。
- 英文门禁：`validate_rewrite()` 的英文术语地区筛选已改为使用“主地区 + 关联地区”集合，避免英国赛事/法国来源等跨地区文章被 `term_region_excluded` 误排除。
- 内容类别：文章类别扩展为 `news / preview / result_brief / official_notice / racecard_update / tips / feature / sales_breeding / other`，并保留旧值兼容历史文章。QQ 默认只放行新闻、赛前展望、赛果简报、特写和旧兼容类别；普通 `tips`、拍卖/育马、普通官方通知不自动群推。
- 查询口径：公开首页地区 tab、QQ 窗口、运营汇总可按主地区或关联地区可见；发布窗口可看见关联地区候选，但未发布文章仍只由主地区窗口负责发布，关联地区不消耗发布配额。
- 运营入口：站内文章编辑页新增主地区、关联地区、内容类型、锁定归属字段；Django Admin 增加 `NewsArticleRelatedRegion` inline；文章列表和详情页地区标签显示所有可见地区。
- 重算命令：新增 `reprocess_multiregion_attribution_gates`，支持 `--dry-run / --commit / --region / --hours / --limit / --json`。commit 只重新写归属、重跑门禁并把通过文章恢复为候选，不直接发布。
- 配置：新增 `MULTIREGION_ATTRIBUTION_ENABLED`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED`、`MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES`，已写入 `.env.example`。
- 本地验证：`DB_ENGINE=sqlite .venv/bin/python server/manage.py check` 通过；新增/相关测试 86 项通过；`makemigrations --check --dry-run` 通过；两个生产 compose config 使用临时 `.env` 渲染通过；`旧规格流程 validate support-multiregion-news-attribution-and-english-gates --strict` 通过。
- `2026-07-10` 未提交改动复审后补齐 `stable.0023_multiregion_news_attribution` 迁移，并将新内容类别贯通到赛事新闻关联和 AI 改写提示：`preview / tips` 按赛前关联，`result_brief` 按赛后关联，所有新类别均有明确改写指令；保留旧类别兼容。SQLite 测试库已实际应用迁移，新增回归测试锁定新类别映射；完整 `stable` 测试 `522` 项通过。本次未部署、未执行生产迁移。
- `2026-07-10` 未提交改动代码审查返修已完成：自动归属将明确赛事/赛场与国家、对象、机构上下文分层，赛事地优先不再受固定地区顺序干扰；多个模糊上下文并存时保守回退主来源；来源 URL/备注不参与归属。重复来源入库始终使用文章最终主来源配置，避免 TDN 法国稿被普通 TDN 重抓改回美国。`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 现在同时约束 QQ 即时推送；后台锁定复选框可正常取消；重处理 dry-run 对锁定文章使用与 commit 相同的有效地区并输出 `attribution_locked / attribution_applied / inferred_regions`；QQ 默认白名单移除 `other`。新增反例测试后相关测试组 `123` 项通过，完整 `stable` 回归 `529` 项通过；生产 dry-run 与部署仍未执行。
- `2026-07-10` 第二轮代码审查返修已完成：文章编辑页通过隐藏哨兵区分旧请求与新版空多选，运营可以把全部关联地区清空；`NewsArticleRelatedRegion` 使用标准字段级 `ValidationError`，Django Admin 选择与主地区相同的关联地区时显示中文错误而不是 500；重处理命令的 `--limit` 改为按有效门禁候选计数，并输出 `scanned_count / candidate_count / has_more_candidates`；公开卡片以主地区开头，详情页和 QQ 明确区分“主地区/关联地区”，单地区回退时 QQ 不显示关联地区。目标测试 `19` 项、相关测试组 `129` 项、完整 `stable` 回归 `534` 项通过；Django check、迁移漂移、旧规格流程 严格校验和 `git diff --check` 均通过。本次仍未执行生产 dry-run 或部署。
- `2026-07-10` 第三轮审查按确认范围只修复公开展示回退：`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 时，首页卡片和文章详情也只显示主地区，关联地区数据保留。按当前决策不收紧 `other` 关联地区的后台保存规则。目标测试 `20` 项、完整 `stable` 回归 `540` 项通过；Django check、迁移漂移、旧规格流程 严格校验和 `git diff --check` 均通过。生产 dry-run 与部署仍未执行。
- `2026-07-11` 已将分支快进合并最新 `origin/main`；多地区新闻迁移顺延为 `0023_multiregion_news_attribution` 并依赖主干 horse profile `0022`。赛事历史抓取编排第五轮审查补齐基础证据链；第六轮定向返修进一步让批量候选保存/apply 整批事务回滚、把完整 adapter 输入写入批准快照并在 `RaceEvent` 漂移时阻断、只从完整 approved 记录读取混合来源策略 SHA。按用户决定，不强制所有 importer apply 提供 `--expected-sha256`，暂不增加请求预算并发锁。旧规格流程 change `orchestrate-race-event-data-crawls` 已同步正式规格并归档到 `旧规格流程/changes/archive/2026-07-11-orchestrate-race-event-data-crawls/`。目标测试 `67` 项、完整 `stable` 回归 `589` 项通过；Django check、迁移漂移、两个 change 严格校验、旧规格流程 全量 `21` 项和 `git diff --check` 均通过。本轮生产部署进行中，尚未运行赛事网络抓取或写入。
- `2026-07-11` 上线等待空闲窗口时发现生产 worker 在归属开关关闭后仍执行完整术语扫描，两个 crawl worker 长时间高 CPU。已修正 `apply_article_attribution()`：开关关闭或人工归属锁定且未 force 时直接返回当前归属，仅对历史空内容类别做轻量分类，不调用 `infer_article_attribution()`。目标测试 `30` 项、完整 `stable` 回归 `591` 项通过；生产开关继续关闭，五地区产品抽样仍未通过，本修复待随本轮部署上线。
- `2026-07-11` 已完成赛事历史抓取编排与多地区归属基础代码上线，生产代码提交为 `6e2cc92`。部署前备份 `.env.backup.orchestration-hotfix-20260711_093556` 和 `backups/db/pre-orchestration-hotfix-20260711_093556.sql.gz`，数据库备份约 `102M` 且 `gzip -t` 通过。`stable.0023_multiregion_news_attribution` 已应用，无新增待执行迁移。
- 上述归属短路热修复已在生产验证：当 `MULTIREGION_ATTRIBUTION_ENABLED=false` 时，真实文章调用 `apply_article_attribution(save=False)` 不会调用 `infer_article_attribution()`，返回 `attribution_disabled`。worker 从部署前两个进程持续高 CPU 恢复到约 `0.04%`，旧抓取积压已消化，Celery reserved 为空，日志未见 traceback/error。
- 生产 `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 继续保持关闭；此前五地区 dry-run 的产品归属口径仍未通过，因此 `support-multiregion-news-attribution-and-english-gates` 保持 active，任务 `9.6` 继续待办，未执行历史归属 commit。
- 生产回归通过：六个容器正常，Django check 通过；本机与公网 `/healthz/`、首页、法国/英国地区页、赛事日历和后台登录页均正常。已通过应用内浏览器真实打开首页、法国频道、英国频道、赛事日历和后台登录页，页面标题、地区导航和文章列表正常渲染。
- `2026-07-11` 经用户确认，`support-multiregion-news-attribution-and-english-gates` 已同步六组 delta spec 后归档至 `旧规格流程/changes/archive/2026-07-11-support-multiregion-news-attribution-and-english-gates/`，当前无 active 旧规格流程 change。正式规格新增 `multiregion-news-attribution`，并同步英文门禁、国际内容分类、发布窗口、公开地区 tab 和 QQ 多地区规则；旧规格流程 全量 `21` 项通过。归档时保留任务 `9.6` 未完成警告：五地区生产 dry-run 的产品归属口径仍未通过，生产两个多地区开关继续关闭。

## 2026-07-01 多地区新闻增量窗口实现与生产验证

- 旧规格流程 change：`increase-multiregion-news-volume`，已完成实现、归档、部署生产，并开启抓取 / 发布 / QQ 三条生产窗口。
- 已新增窗口运行模型：`ProductionWindow`、`WindowCandidateDecision`、`WindowTargetDecision`、`QuotaLedger`、`MajorRaceEvent`；`NewsSource` 增加生产批准、有效抓取间隔、backoff、人工暂停、错误分类、连续成功/失败和重要赛事升频字段。
- 已实现日常/重要赛事窗口服务：日常 15 分钟、重要赛事 5 分钟、最多 3 小时回看；重要赛事按地区当地时间录入，开跑前 3 小时到开跑后 1 小时升频，无开跑时间时按当地日期级窗口处理。
- 已实现新抓取窗口：只选择 `enabled=true`、`production_approved=true`、未暂停、未 backoff 的来源；连续失败 3 次自动降频，403/429/验证码类错误使用更保守 backoff，连续成功 3 次恢复默认 15 分钟。
- 已实现新发布窗口：每地区每窗口最多 5 篇；硬门禁不绕过；按内容指纹去重后评分排序；若没有高分稿但存在 45 分以上可发布稿，按保底发 1 篇并标记 `region_minimum_fill` 与 `disable_auto_qq`。
- 已实现新 QQ 窗口：只推高价值/榜单稿；每地区每窗口最多 3 篇；保底文章不自动 QQ；群小时和全站小时配额写入 `QuotaLedger`；0 推送原因写入 `WindowTargetDecision` 和窗口 payload。
- `2026-07-02` review 返修后，抓取和 QQ 补跑都只对最近一个缺失窗口执行真实动作，较早缺失窗口会记录为 `coalesced_to_latest_*_window` 的 `SKIPPED` 窗口，避免停机恢复后集中补抓或集中补推；已有 `SKIPPED/FAILED` QQ delivery 若重新进入发送，也必须先重新占用群小时和全站小时配额，`PENDING/RETRYING/SENDING/SENT` 或已达到最大尝试次数的 delivery 仍不会重复占配额。本轮进一步修正窗口真实状态口径：抓取窗口只在真实抓取任务完成后写 `SUCCEEDED/FAILED`，来源存在 lease 未过期的运行中抓取窗口时不再重复派发；HTTP 403/429 等状态码会进入来源错误分类；QQ 窗口在占配额和创建 delivery 前先检查 OneBot 在线状态，离线时直接在窗口记录 `onebot_offline` 并不派发消息。
- 已扩展 `audit_multiregion_news_production`：输出生产批准来源数、暂停/backoff 来源数、最近窗口结果、0 原因和配额打满记录；新增 `production_summary_task` 每日生成同一份摘要。
- 新窗口 Beat 已接入；生产显式开启后进入五地区常态窗口，不依赖旧 `auto_publish_batch_task` 提高频率。
- 新增管理入口：
  - `MajorRaceEvent`、`ProductionWindow`、`QuotaLedger` 已注册 Django Admin。
  - `NewsSourceAdmin` 显示生产批准、有效间隔、backoff、失败连续次数和错误分类。
  - `import_major_race_events --csv <path>` 支持重要赛事 CSV upsert，主键口径为 `normalized_name + year + racing_region + race_grade`。
- 已完成本地验证：
  - `DB_ENGINE=sqlite manage.py check`：通过。
  - `DB_ENGINE=sqlite manage.py makemigrations --check --dry-run`：通过。
  - 模型/窗口/来源/发布/QQ/重要赛事导入相关目标测试通过。
  - `2026-07-02` review 返修后，窗口相关目标测试 26 项通过，完整 `stable` 测试 399 项通过；`DB_ENGINE=sqlite manage.py check`、`旧规格流程 validate increase-multiregion-news-volume --strict`、`旧规格流程 validate --all` 和 `git diff --check` 均通过。
  - 临时 SQLite 迁移后 `audit_multiregion_news_production` 可输出有效 JSON。
- 生产运行验证：
  - `2026-07-02` 已部署到生产 `a122130`，容器 `web / worker / beat` 正常，`http://umafans.run/healthz/`、首页和抽检 `/news/<article_id>/` 均返回 `200`，Celery `active/reserved` 为空。
  - 生产配置确认：`MULTIREGION_PRODUCTION_WINDOWS_ENABLED=true`，抓取 / 发布 / QQ 子开关均为 `true`；允许地区为日本、中国香港、英国、法国、美国；日常窗口 `15` 分钟，重要赛事窗口 `5` 分钟；发布每地区每窗口 `1-5` 篇，QQ 每地区每窗口最多 `3` 篇；当前没有地区处于重要赛事升频窗口。
  - `2026-07-02 04:18-10:18` 最近 6 小时窗口复核：发布窗口和 QQ 窗口各地区均产生 `24` 个日常窗口；抓取窗口统计为 `260` 个 `succeeded/completed`，`109` 个 `skipped/coalesced_to_latest_crawl_window`，符合恢复补跑只抓最近窗口的设计。
  - 最近 6 小时发布窗口中，美国 `04:30` 发布 `1` 篇，日本 `04:45` 发布 `2` 篇、`05:30` 发布 `4` 篇、`06:30 / 08:15 / 09:45` 各发布 `1` 篇；所有非零窗口均未超过每地区每窗口 `5` 篇，其余窗口均有 `no_ready_candidates` 原因。该时段 `published_to_web_at` 另包含香港 `1` 篇和美国 `3` 篇上线初始批次 / 旧自动发布文章，不属于本次新窗口发布。
  - 最近 6 小时 QQ 实际发送 `6` 条，目标均为 `UmaFans测试群(1026525240)`；美国 `3` 条，日本 `3` 条，未超过每地区每窗口 `3` 条。0 推送窗口记录为 `no_eligible_articles` 或 `already_sent`。
  - 来源复核显示 16 个生产批准来源最近抓取均为 `success`；`TDN France Galop 关键词英文新闻` 和 `TDN 美国新闻` 虽有已过期 `backoff_until` 残留，但最新 `10:00` 抓取窗口均为 `succeeded/completed`，当前不影响抓取。
  - Ops 通知开关已开启，最近 6 小时产生 `ops_summary` QQ 通知 `2` 条并发送成功；邮件 / 短信 / 微信渠道按 MVP 预留逻辑记录为 `skipped` 或未配置。
  - `2026-07-02 11:07` 继续复核最新 4 个发布窗口（`10:15 / 10:30 / 10:45 / 11:00`）：五地区均未发布新文章。日本有 `18` 条候选决策，全部为 `hard_gate_blocked`，主要来自翻译失败、人工审核要求和核心术语缺失；香港、英国、法国、美国没有进入发布候选的文章。最近 3 小时抓取显示非日本来源均成功运行但新增为 `0`、只命中重复旧稿；`TDN France Galop 关键词英文新闻`、`TDN 美国新闻` 曾在 `08:25-09:05` 超时或 `525`，`10:10` 已恢复成功且失败 streak 为 `0`。因此最新窗口 0 发布的主因是“日本候选被门禁/审核拦住，非日本暂无新稿”，不是生产调度或整体抓取失效。
  - `2026-07-02 15:10` 复核最近 2 小时自然窗口（`13:15` 至 `15:00`）：发布窗口和 QQ 窗口五地区均按 15 分钟节奏生成且状态为 `succeeded`，本时段网页发布 `0` 篇、QQ delivery `0` 条；发布 0 原因为 `no_ready_candidates`，QQ 0 原因为 `no_eligible_articles`。抓取窗口整体正常，最近 2 小时新入库 `8` 篇：日本 `5`、香港 `1`、英国 `2`、法国/美国 `0`；这些新稿当前为翻译失败或 `manual_review_required / pending_review`，未达到自动发布状态。16 个生产批准来源中 14 个最新成功，`TDN France Galop 关键词英文新闻` 与 `TDN 美国新闻` 在 `15:02` 出现 read timeout，`failure_streak=1`，属于同一上游站短时超时，不是整体抓取失效。候选决策当前能记录 `hard_gate_blocked`，但 payload 未展开具体 blocker 明细，后续可作为可观测性改进。
  - `2026-07-03 00:13` 复核今日窗口：因刚过零点，今日目前只有 `00:00` 一个自然窗口。五地区抓取 / 发布 / QQ 窗口均为 `succeeded`；抓取新入库 `1` 篇美国 TDN 新闻，其余来源均为重复旧稿；网页发布 `0` 篇，发布 0 原因为 `no_ready_candidates`；QQ delivery `0` 条，日本 / 美国为 `already_sent`，香港 / 英国 / 法国为 `no_eligible_articles`。16 个生产批准来源最新状态均为 `success`，前一日 TDN 超时已恢复。
  - `2026-07-03` 复核 `2026-07-02` 全日窗口：因多地区生产窗口于 `04:00` 后开始有账本，昨日实际覆盖 `04:00-23:45` 共 `80` 个 15 分钟窗口起点。发布窗口五地区各 `80` 个且全部 `succeeded`，窗口发布日本 `37` 篇、香港 `1` 篇、美国 `10` 篇，英国 / 法国为 `0`，无 failed/partial；0 发布主因仍为 `no_ready_candidates`，未发布候选多为 `hard_gate_blocked`。QQ 窗口五地区各 `80` 个且全部 `succeeded`，窗口派发日本 `3` 条、美国 `5` 条，均无 failed delivery；昨日所有 QQPushDelivery 记录按地区为日本 `15` 条、美国 `9` 条，状态均为 `sent`。抓取窗口无 `failed`，按窗口 payload 统计新增：日本 `79`、香港 `5`、英国 `11`、法国 `1`、美国 `28`，其中日本有 `7` 次榜单唤醒；`coalesced_to_latest_crawl_window` 为恢复/延迟时只补最近窗口的预期跳过。16 个生产批准来源在 `2026-07-03 00:13` 最新状态均为 `success`。
  - `2026-07-03` 地区归属错配只读审计：当时 `NewsArticle.racing_region` 与 `source_config.racing_region` 完全一致，`6598` 篇文章中 `0` 篇偏离“按新闻源地区”的现有逻辑。严格按有地区字段的实体（`ExternalHorseAlias` / 非空 `TermEntry.racing_region`）推断时，可覆盖 `462` 篇文章，且全部为日本文章；按用户提出的“第一种单地区逻辑”和“第二种多地区逻辑”均未发现结构化错配。但该结果只能作为下限：审计当时生产 `TermEntry` 的马/赛事/骑手地区全部为空（马 `1884`、赛事 `153`、骑手 `2`），`MajorRaceEvent` 为空，外部马名/赛事正式缓存只有日本和极少香港，没有英法美实体地区，因此系统无法可靠判断英文新闻中提到的日本 / 英国 / 法国 / 美国马、骑手或赛事。`2026-07-04` 后仅首批 `10` 条术语补写了地区，仍不足以支撑可信实体地区识别。补充关键词粗扫发现 `1213` 篇疑似跨地区提及，其中 `2026-06-30` 以后 `231` 篇、`2026-07-02` `60` 篇，但噪声较高，只能作为后续补实体地区识别的线索。

## 2026-07-02 榜单唤醒未发布文章实现

- 旧规格流程 change：`revive-ranked-news-for-publish`，当前已完成实现、归档和生产部署。生产服务器 `/opt/umanewsbot` 已部署到 `a774672`，部署前备份 `.env` 为 `.env.backup.ranked-revival-20260702_145529`，数据库备份为 `backups/db/pre-ranked-revival-20260702_145529.sql.gz`。
- 用户确认的产品规则：榜单二次命中不是直接发布按钮，而是“这篇文章值得重新认真看一次”的强信号。未发布文章从普通来源升级为榜单来源时，应允许低分忽略、价值不足转人工、待翻译或翻译失败文章被唤醒；翻译失败或待翻译文章需要自动重试翻译；翻译成功后重新评分，高价值来源信号参与自动发布判断。
- 边界：榜单唤醒不得绕过翻译成功、自动评分、发布校验、发布窗口配额和 QQ 限流；人工拒绝、撤回、已发布、高度重复 blocker、正文缺失、核心术语缺失等硬门禁仍不自动复活。
- 规格影响：修改 `automation-publish-gates` 和 `multiregion-news-production`，新增榜单唤醒、翻译重试、重新评分、按唤醒时间进入发布候选池以及窗口决策留痕要求。
- 代码实现：新增 `NewsArticle.ranked_revived_at` nullable/indexed 字段和迁移 `0019_newsarticle_ranked_revived_at.py`；新增 `revive_article_after_ranked_source_elevation()` 服务，记录 `decision_reason.ranked_revival`，区分 `translation_retry / rescore / blocked / already_retrying_translation`；netkeiba 榜单和国际榜单抓取在 `source_elevated=true` 时对未发布文章执行榜单唤醒，已发布文章继续沿用现有 QQ 补推；发布窗口候选查询支持 `first_seen_at` 或 `ranked_revived_at` 最近 3 小时，并在 `WindowCandidateDecision.payload` 写入榜单唤醒来源和时间。
- 测试进展：已按 TDD RED-GREEN 补充并跑通 `server/stable/tests.py` 中的榜单唤醒测试，覆盖 nullable/indexed `ranked_revived_at` 字段契约、低分 ignored 复活、价值不足人工状态复活、翻译失败/待翻译重试、人工终态/duplicate/blocker 不复活、重复榜单命中幂等、发布窗口按 `ranked_revived_at` 回看、以及 netkeiba/国际榜单抓取对未发布文章走唤醒而非 QQ 直推。
- 验证：`DB_ENGINE=sqlite manage.py check` 通过；`DB_ENGINE=sqlite manage.py makemigrations --check --dry-run` 通过；`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true manage.py test stable --noinput` 通过，418 项；归档前 `旧规格流程 validate revive-ranked-news-for-publish --strict` 通过，归档后 `旧规格流程 validate --all` 通过，14 项；`git diff --check` 通过。
- 上线结果：迁移 `stable.0019_newsarticle_ranked_revived_at` 已应用；`manage.py check` 通过；生产模型确认 `ranked_revived_at null=True db_index=True`，榜单唤醒服务可 import；`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/`、首页和后台登录入口均返回 `200`；`web / worker / beat` 已重建并运行，Celery `active/reserved` 为空，近 80 行 `web / worker / beat` 日志未见 traceback/error。
- 上线后观察：继续观察发布窗口候选决策中的 `ranked_revival` payload、翻译重试数量、重新评分结果和 QQ 是否仍只推已发布/合格文章。回滚代码后 `ranked_revived_at` 字段可保留不用；如需彻底清理，后续单独做清理迁移。

## 2026-07-11 国际新闻门禁与产量生产验收

- 验收窗口：截至 `2026-07-11 17:18 CST` 的最近 24 小时。抓取/发布窗口调度正常，所有启用来源最新状态均为 `success`；但业务验收未通过。
- 门禁：最近 24 小时英文新稿 `50` 篇，公开 `15` 篇，`25` 篇仍有 `core_term_missing` blocker，共 `136` 条。`America`、`Oaks` 已按普通词/高歧义词降级，且没有 `term_semantic_classification=common_word` 的 blocker；但 `something`、`versatile`、`brilliant`、`incredible`、`reputation`、`threat`、`title`、`too soon`、`yet` 等普通词因术语库被错误标为 `horse`，仍走 `horse_term_without_common_seed -> proper_noun` 并阻断发布。因此门禁优化有效但不完整。
- `reprocess_term_gate_blocked_articles --dry-run` 存在严重性能问题：生产上 `limit=5` 仍长时间占用单核，多个并发验收进程一度使 web 容器 CPU 达约 `185%`；已终止本次启动的全部进程，web CPU 恢复约 `0.08%`，健康检查正常。修复前不得在生产批量运行该命令。
- 来源与产量：当前生产批准并启用来源为日本 `6`、香港 `2`、英国 `3`、法国 `3`、美国 `3`。法国新增宽关键词 TDN 来源已启用，但最近 24 小时新增 `0`，主要命中 `stale_published_at` 后跳过；At The Races 法国源仍未批准。香港、英国、美国没有完成后续讨论的新一轮扩源。
- 最近 24 小时按主地区统计：日本新增/公开 `114/21`，香港 `3/0`，英国 `12/2`，法国 `1/0`，美国 `34/13`。香港 3 篇为待审核 `2`、翻译失败 `1`；法国 1 篇翻译失败；英国 12 篇中待审核 `6`、翻译失败 `2`、忽略 `2`、公开 `2`；美国 34 篇中待审核 `17`、翻译失败 `4`、公开 `13`。
- 最近 8 个发布窗口：日本发布 `5` 篇、英国 `1` 篇，香港/法国/美国均为 `0`，0 原因均为 `no_ready_candidates`。结论是美国总体产出已可用、英国抓取量达到最低规模但发布转化偏低，香港和法国仍明显不足，尚未达到各地区常态丰富产出的目标。
- 验收期间并行赛事 adapter 部署重建了 web/worker/beat，17:15 抓取窗口短暂留下运行中记录，随后从 `11` 条降至 `1` 条，Celery 抓取队列清空且健康检查恢复。该暂态由并行部署造成，不作为新闻调度持续故障结论。
## 2026-07-12 赛事公开页中文术语与出马表排序修复

- 公开赛事详情页和赛事日历赛果将马名、骑师名批量关联 active `TermEntry / TermAlias`；精确命中时展示正式中文译名，候选优先级为赛事同地区、全局、其他地区，未命中保留来源原文。
- 出马表不再使用抓取来源行序直接展示。当前日本、香港、英国、法国、美国均优先按马号自然升序，缺马号时回退闸位，再回退来源 `sort_order`；支持 `1A / 2 / 10` 等编号。
- 修复只改变公开展示，不覆盖 `RaceEventRunner / RaceEventResult / RaceEventHistoryWinner` 中的来源原文，也不改变赛果名次顺序。
- 本地目标测试 `23` 项、完整 `stable` 回归 `612` 项、Django check、迁移漂移检查、旧规格流程 严格校验和 `git diff --check` 均通过。
- 已部署生产提交 `d071952`，无新增迁移。生产 `web / worker / beat` 重建正常，内外 healthz、赛事日历和日本德比详情均返回 `200`，近 5 分钟服务日志无 traceback/error。
- 线上首批术语覆盖抽检：香港赛果已是中文原文；英国马名 `13/13`、骑师 `9/13` 命中；美国马名 `2/18`、骑师 `11/18` 命中；法国马名 `1/7`、骑师 `0/7` 命中；日本德比马名 `1/18`、骑师 `0/18` 命中。日本德比当前冠军 `ロブチェン` 和骑师 `松山 弘平` 尚无 active 正式术语，页面按规则保留原文，后续需补词库而不是改展示逻辑。
- 部署前 `.env` 备份为 `.env.backup.race-display-20260712_002533`；数据库备份为 `backups/db/pre-race-display-20260712_002533.sql.gz`，约 `105M`，gzip 校验通过，SHA-256 为 `99994e84d3154dd9d4c1503b96688cd24bf7e00d9ad13aca02a965a69d64a8c0`。
## 2026-07-12 五地区赛事追溯至 1984 年目标启动

- 新长期目标已锁定：日本、中国香港、英国、法国、美国赛事采用相同历史深度，统一追溯至 1984 年，并沿用应到清单、跨来源关联、去重补漏、五地区抽样、覆盖审计、dry-run、备份、分批写入和写后核验门禁。
- 生产只读基线：`RaceEvent=995`，全部为 2026 年；日本 `186`、香港 `20`、英国 `203`、法国 `174`、美国 `412`。按现有系列机械乘以 1984–2026 的 43 年，理论上限约 `42,785` 个年度对象，但该数字尚未扣除创办年、停办/取消和历史等级范围变化。
- 当前前置缺口：编排器支持年份范围，但要求每个年份先存在正式 `RaceEvent`；日本、香港部分 `series_key` 带 2026 日期，美国另有两个同年重复系列键，不能直接复制当前赛历生成历史年度对象。
- 已创建 旧规格流程 change `backfill-race-events-to-1984`，完成 proposal、design、4 份 delta spec 和 tasks；`/grill-me` 共锁定 22 个产品决策。两轮 `/plan-eng-review` 已收敛，最终 verdict 为 APPROVED，审查记录见 `engineering_review.md`。当前只获准进入“编写完整测试用例”阶段，尚未实现代码、触网、创建历史赛事或写生产数据。
- `/grill-me` Q1 已确认选择 A：历史范围为当前五地区全部 graded/pattern 系列，包括日本 JRA/NAR 分级赛、香港分级赛、英国/法国 Pattern Race 和美国 Graded Stakes；明确排除普通赛、让赛和未胜利赛。
- `/grill-me` Q2 已确认选择 A：入选赛事系列按完整系列史收录，从 `max(1984, 实际创办年)` 开始；赛事升级为分级赛之前的届次也纳入，并保存当年真实等级。
- `/grill-me` Q3 已确认选择 A：纳入 1984–当前年度任一年曾属于 graded/pattern 体系、但后来停办、降级退出或不在 2026 当前目录中的历史独有系列。完整目录必须逐年发现，不能只从现役 2026 系列向前复制。
- `/grill-me` Q4 已确认选择 A：已排期后取消的年度赛事创建 `RaceEvent(status=cancelled)`；当年根本未举办的系列只在应到清单记录 `not_held`、原因和证据，不创建虚假赛事，且不作为漏抓。
- `/grill-me` Q5 已确认选择 A：历史年份只有可信完整赛果而无独立 racecard 时，可从完整赛果派生出马表并标记 `derived_from_results`；仅复制有证据字段，赔率、闸位等未知值保持为空。
- `/grill-me` Q6 已确认选择 A：年度冠军以该年正式赛果为唯一主事实，历届冠军按稳定系列动态汇总；只有缺完整赛果而有可信冠军证据的年份才用 `RaceEventHistoryWinner` 补位，禁止向每届复制整张冠军表。
- `/grill-me` Q7 已确认选择 A：稳定赛事系列身份按权威沿革认定；冠名、名称、场地、距离和等级变化不自动切断系列，合并/拆分/替代必须人工确认并记录前身后继，名称相似只生成待审候选。
- `/grill-me` Q8 已确认选择 A：字段级来源权威顺序为当年主办方/监管机构官方结果、官方历史档案/年鉴、高可信专业数据库、参考来源；低级来源只补空，同级或更高级冲突阻断相应写入范围并人工审核。
- `/grill-me` Q9 已确认选择 A；工程审查将不可执行的停办系列近年锚点澄清为：每地区 3 个代表系列、约 9 个真实 held/cancelled 年度目标，地区整体覆盖 1980 年代、2000 年前后和近年，约 45 场，并覆盖长寿、改名/迁场、历史独有或停办系列。
- `/grill-me` Q10 已确认选择 A：覆盖完整目标可按批准 scope 先写入；`source_unavailable / identity_review_required` 持续挂在总缺口账本且不计完成，不冻结其他完整目标，也不得用空记录占位。
- `/grill-me` Q11 已确认选择 A：永久不可得必须完成官方/监管档案与至少一个独立可信来源的双来源核查，保留完整证据并人工批准；超时、403、限流和页面改版只算暂时不可用。
- `/grill-me` Q12 已确认选择 A：当前年度未来赛事或官方确认宽限期内赛事标记 `not_due`，进入总清单但不计缺失；到期后再转为应到，历史完成率与滚动当前赛季分开统计。
- `/grill-me` Q13 已确认选择 A：批准批次中身份完整且出马表/赛果达到年度可得标准的历史赛事可自动公开；身份待审、来源冲突或资料不足保持 draft，已确认取消赛事可带说明公开。
- `/grill-me` Q14 已确认选择 A：后续更权威/更完整来源通过新候选 diff 和批准批次修正机器字段，人工锁字段不覆盖；旧值、来源快照、批次、原因和回滚证据必须保留。
- `/grill-me` Q15 已确认选择 A：马名/骑师名缺中文术语不阻止结构化历史赛事写入和公开，页面保留原文并生成术语缺口；术语补齐后动态显示中文，禁止自动音译直接写正式词库。
- `/grill-me` Q16 已确认选择 A：首批后全量按 `2016–2025 → 2006–2015 → 1996–2005 → 1984–1995` 从新到旧推进；标准批次每地区最多 50 个目标，任何地区不得比最慢地区领先超过 100 个同年代带标准目标。
- `/grill-me` Q17 已确认选择 A：最终以 `accounted_rate=100%` 收口，同时独立报告 `data_complete_rate`；全部目标必须写入、确认 not_held/not_due，或经双来源批准 permanently_unavailable，永久缺档不得伪装成数据完整。
- `/grill-me` Q18 已确认选择 A：历史参赛记录不自动批量创建 HorseProfile，只关联现有正式术语/马匹资料；未识别人马进入候选和术语缺口，避免同名误合并与空壳资料。
- `/grill-me` Q19 已确认选择 B：不新增公开赛事系列页；历史数据继续落在年度 RaceEvent 详情页，稳定系列仅用于后台身份、历届冠军汇总和年度关联。
- `/grill-me` Q20 已确认选择 A：赛事日历增加年份筛选和赛事名称搜索，结果进入现有年度详情页；不新增系列页，也不要求按短窗口连续翻到 1984 年。
- `/grill-me` Q21 已确认选择 A：哈希锁定 artifact 是审批与 apply 唯一凭证；后台增加按地区/年代/系列/状态/冲突查看的汇总入口，但不得绕过 artifact 直接批量写入。
- `/grill-me` Q22 已确认选择 A：质量达标且 published 的历史年度赛事允许搜索引擎收录并进入分片 sitemap；draft、身份冲突、资料不足和 not_held 不收录。
- 本轮 `/grill-me` 当时已完成关键产品分支确认，后续也已完成旧 旧规格流程 design、delta specs 和 tasks 编写；这是一条历史进度记录，不是现行下一步。`2026-07-15` 起剩余工作按本文件顶部的新流程迁移。
- `backfill-race-events-to-1984` 已完成两轮 Full `/plan-eng-review`，最终 APPROVED；随后已创建 `test_cases.md`，共 160 个唯一测试用例，覆盖范围、系列/迁移、年度状态机、来源权威、artifact、五地区 adapter、批次、导入、公开页面、运维和非目标回归。旧规格流程 change strict、全量 22 项和 `git diff --check` 均通过。历史上曾按旧流程进入 apply 阶段；该交接已由 `2026-07-15` 新流程取代，后续从安全检查点读取现存规格并只对未实现行为补真实 RED，再由 subagent 实现并复用同一需求既有 reviewer 会话审核。此处不伪造既往 RED，也不重做已完成生产动作。

## 2026-07-12 历史赛事回填 apply 第一阶段

- `backfill-race-events-to-1984` 的旧 apply 阶段当时仅完成本地模型、迁移和只读 inventory 基础能力；尚未部署、触网、提交历史总账或创建历史年度赛事。后续执行以 `2026-07-15` 新流程为准，不再把旧命令作为可执行下一步。
- 新增稳定系列、历史名称、系列关系和年度应到总账模型；`RaceEvent.race_series` 为 nullable，旧 `series_key` 和公开 slug 保持兼容。赛果新增独立 `official_finish_position`，迁移会优先读取旧 `source_refs` 官方名次并回退存储顺序，历史冠军唯一约束已支持并列冠军。
- 新增离线 `build_historical_race_inventory`：默认只生成 series/target/conflict/gap/summary/manifest/approval artifact；commit 必须开启功能开关并验证批准人、时间、manifest SHA 和全部文件 SHA，且 commit 阶段不重新生成输入、不触网。
- 已实现字段级来源权威合并、同级冲突阻断、人工锁保护、系列关系防环、名称模糊匹配只进待审、双状态转换、永久缺档独立双来源校验和 accounted/data-complete 分开统计。
- 历史总账 Django admin 为只读入口，支持地区、年份、系列、expectation/resolution 状态和名称筛选；无新增、编辑、删除或直接 apply 动作。
- 新增默认关闭配置：`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，并设置请求、source cache 和最小剩余磁盘预算。历史 prepare 必须同时通过功能开关、网络开关、plan 显式授权和预算校验。
- 当前相关模型、service、command、后台、旧赛事页面和旧编排回归共 `122` 项通过；空 SQLite 正向迁移、反向回滚、再迁移、Django check 和迁移漂移检查通过。完整实现、全量回归、代码 review 和生产验收仍未完成。
- 后续 apply 与生产准备已推进到 `65/82` 项，代码与自动化测试任务已全部完成：除总账切批、历史 importer、公开搜索和分片 sitemap 外，已新增五地区统一离线目录 adapter、`parse_historical_race_catalog` 标准候选命令、共享 source cache/请求预算锁、历史网络运行日志，以及 sitemap/年份缓存和查询索引。五地区三年代测试摘录只验证解析契约，不代表生产目录已收齐。
- 本轮专项测试覆盖目录、模型、artifact、批次、日志、缓存和编排，完整 `stable` 回归最终为 `743/743`；Django check、迁移无漂移、旧规格流程 strict/all `23/23`、三套 Compose 配置、实际 Docker 镜像构建及容器内 `/app/runtime` 路径检查均通过。
- 已完成多轮 `/review -> 修复 -> 重新 review`：修复目录年份/香港赛季与 provenance、稳定 key 冲突、批准人和人工锁、artifact/cache 路径边界、apply-check cache 保护、已导入/永久缺档状态漂移、共享 Redis cache 降级，以及受保护 cache 不可覆盖和大文件分块校验。最终一轮 review 无 actionable finding，代码门禁 clean；工具已部署并完成 2026 mapping，但尚未创建历史总账、抓取 1984–2025 详情或公开历史赛事。
- 生产部署和 2026 mapping 已完成，当前进度 `65/82`。剩余 `17` 项全部是生产操作：逐年官方 source cache/总账、首批五地区验收、分年代带抓取落库和最终审计。1984 起官方年鉴 cache 尚未收齐，不能把测试 fixture 当作生产总账分母。

## 2026-07-12 历史赛事工具生产部署与 2026 系列 mapping

- 生产已从 `dc6e434` 快进部署至 `c3b66a6`。迁移 `stable.0024_historical_race_inventory` 与 `stable.0026_historical_race_query_indexes` 已应用，三个历史查询索引均存在；Django check、内外 `/healthz/`、赛事日历和抽检详情页通过。
- 部署前备份为 `.env.backup.historical-race-backfill-20260712_044501` 与 `backups/db/pre-historical-race-backfill-20260712_044501.sql.gz`；mapping 写入前备份为 `backups/db/pre-2026-race-series-mapping-20260712_051047.sql.gz`。两份数据库备份均通过 `gzip -t` 和 SHA-256 校验。
- 2026 初始 mapping 对 `995` 场赛事识别出日本/香港日期型 key、美国两组重复 key 和英国名称相似冲突。美国两个无日期空壳的别名、历届冠军和候选均与正式赛事重复，已在事务断言后删除；英国 Gold Cup 重复记录的出马表、赛果、冠军、候选和 BHA 官方来源已合并到既有 `/races/2026/gold-cup/` 主记录。
- 最终批准 artifact 为 `runtime/historical_race_inventory/mapping-2026-approved-20260712_051808/`：`event_count=992`、`approved=992`、`review_required=0`、`conflict=0`。日本 JRA key 使用 JRA 官方英文重赏表/赛程，NAR 使用 `keiba.go.jp` 官方详情 URL，香港使用 HKJC 官方英文赛果术语；override 审核证据位于 `mapping-overrides-2026/`。
- 受控 commit 新建 `992` 个 `RaceSeries` 并绑定全部 `992` 场 2026 `RaceEvent`；幂等复跑返回 `series_created=0 / events_bound=0`。地区计数为日本 `186`、香港 `20`、英国 `202`、法国 `174`、美国 `410`，未绑定赛事为 `0`。
- 常驻生产配置最终确认 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`、`RACE_EVENT_CACHE_URL=redis://redis:6379/2`。当前 `HistoricalRaceEventTarget=0`、1984–2025 `RaceEvent=0`、公开历史赛事 `0`，尚未开始逐年目录抓取或历史详情落库。
- 下一步是任务 8.3：按五地区逐年采集 1984–当前官方 catalog source cache，生成只读年度总账；测试 fixture 不得充当生产完整目录。
- 用户已授权：准备任务、完整测试和 clean review 全部完成后，可自主执行生产部署、抓取与分批落库，无需逐批再次确认；最终必须恢复关闭历史功能/网络开关，历史年度赛事保持 draft，不提前公开。

## 2026-07-12 TJCIS 1998–2026 历史目录解析准备

- 新增 `prepare_tjcis_ics_catalog.py`，从 TJCIS 官方索引发现 1998–2026 International Cataloguing Standards 整本 PDF，统一解析日本、香港、英国、法国、美国平地及目标地区障碍分级赛。
- 真实网络必须同时具备 CLI `--allow-network` 和两个历史开关，并复用共享 request budget/source cache。`--resume` 只复用 manifest、大小和 SHA 一致的缓存；全缓存重放可在网络开关关闭时执行。
- 解析只接受 G1/G2/G3，支持老版点阵列、跨页名称、香港 Part I/II 赛季、Part IV 障碍页、AWT 和同名异场防覆盖。平地章节与年鉴自报 Graded/Group 总数强制对账。
- 真实 2016 整书烟测已用于锁定版式；后续全书生产验收发现 1998 年鉴正文等级标记与页尾 G1/G2/G3 汇总互相矛盾，因此 1998 不再视为通过，必须进入来源交叉核对。
- 新增/相关测试 `67` 项通过；完整 stable 发现 `724` 项，从错误 cwd 运行时仅有 2 个旧测试因相对 fixture 路径报错，从仓库根目录复跑均通过。`py_compile`、`git diff --check` 和最终 clean review 通过。
- 任务 `8.3` 仍未勾选：下一步部署后生成 1998–2026 source cache/部分候选总账，再补齐 1984–1997。完整总账、身份审核和批准完成前不得宣称全量完成。

## 2026-07-12 TJCIS 生产 source cache 与部分总账结果

- 生产机到 `tjcis.com:443` 连续 TLS/连接超时，2 次请求均未收到字节；改由本机同一正式工具在共享预算/source-cache 门禁下抓取，再将原始字节、manifest 和 SHA 完整同步生产，生产离线复验。
- 已缓存 1998–2026 共 `29` 本官方 PDF，加 2 个官方索引，总请求 `31/40`，原始 cache `82,494,754` bytes。生产逐文件大小/SHA 校验 `31/31` 通过；source summary SHA-256 为 `1a7aba7afac63b768fdcf8f994a9725a2471bddb6900c3313e4c1c7b537c7505`。
- 严格年度验收最终仅通过 `2016 / 2020 / 2021`；其余 `25` 年存在正文/页尾数量不一致、章节缺失、同名身份冲突或地区数量异常。1984–1997 仍完全缺少 TJCIS 在线整本覆盖。
- 标准候选 v3：`runtime/historical_race_inventory/tjcis-candidates-2016-2021-v3-20260712/`，共 `3,252` 行，日本 `404`、香港 `97`、英国 `894`、法国 `485`、美国 `1,372`，索引/附录/Listed 粘连质量扫描为 `0`；manifest SHA-256 `48b02ef77c02ef81e959331e5c927ddff412514c15caa8a0a6afbd23e67af1ac`。
- 部分 inventory v3：`runtime/historical_race_inventory/tjcis-inventory-partial-2016-2021-v3-20260712/`，`target_count=3,252`、`series_count=1,313`、`conflict_count=82`、`accounted_count=2`；冲突主要为历史标点/空格/命名差异，manifest SHA-256 `f422c8fc82a616d49c634e96e263745d8b0250026be7af939f9f1a06bc9ba955`。
- v3 仅是只读部分总账证据，未批准、未 commit。生产保持 `HistoricalRaceEventTarget=0`、1984–2025 `RaceEvent=0`、公开历史赛事 `0`；两个历史开关均为 `false`，公网 healthz 为 `200`。
- 因完整年度总账尚未形成，未启动赛事详情全量抓取。下一步按错误族修复/交叉核对 25 个年度，再做系列身份审核；只有 1984–当前总账完整且批准后才能进入详情批次。

## 2026-07-12 TJCIS 1998–2026 年度目录第二轮修复

- 已修复旧版国家码、带空格年龄、等级紧贴奖金、空页眉误拼、障碍赛距离缺失、重复声明翻倍，以及同名赛事候选 key 不稳定等问题。
- 专项解析器测试 `36` 项、目录相关组合测试 `49` 项通过，`git diff --check` 通过；复审未发现新的 actionable finding。
- 29 本 PDF 全量离线回放后，直接通过年份由 `3` 个增至 `11` 个：`2005 / 2007 / 2009 / 2012–2016 / 2020–2022`。2015 美国章节从错误的 `212` 条恢复为 `468` 条；2022 同名英国障碍赛已保留为不同审核候选。
- 全地区审计确认共有 `22` 个年份、`31` 个地区/项目组合存在“正文显式 G1/G2/G3 行与页脚声明小计不一致”。完整记录位于 `diagnostics/declared_count_reconciliation.json/csv`；不得删除、隐藏或用总数机械补造赛事。
- 已生成 1998–2026 共 29 份只读页文本诊断缓存，供相邻年和地区官方目录交叉核验；诊断缓存不能替代原始 PDF 和 SHA 证据。
- 生产仍为 `HistoricalRaceEventTarget=0`、pre-2026 `RaceEvent=0`、历史公开数 `0`；两个历史开关保持 `false`。下一步先完成 31 项来源冲突核验并生成完整身份审核包。
## 2026-07-13 法国新鲜度与多地区归属代码安全关闭上线

- 生产源码已从 `c998eb3f` 快进到 `badc10e028aa3c1f6f2984bbfad8c1e202101cdc`，基于最新代码重建 `umanewsbot:prod`，并成功应用 `stable.0029_france_freshness_translation_attribution`。`web / worker / beat / db / redis / nginx` 均正常运行，最近部署日志未发现 traceback、error、critical 或 exception。
- 部署前已保存 `.env.backup.france-multiregion-20260713_041004`；有效数据库备份为 `backups/db/pre-france-multiregion-20260713_041111.sql.gz`，大小约 114 MiB，SHA256 为 `a92e95fd8b10ceb7cd3721d4984d8f8d699b23edf6686615e289a12e6aa0c898`，`gzip -t` 通过。首次中断文件已明确改名为 `.incomplete`，不得用于恢复。
- 本次只部署代码，不启用新行为。`web / worker / beat` 实际设置均为 `MULTIREGION_ATTRIBUTION_MODE=off`、归属写入关闭、相关地区查询关闭、灰度阶段 `off`、gold 版本 `pending-review`、翻译自动重试关闭。新归属运行表可正常查询，当前 run/lock 均为 0。
- 邮件告警接收地址已配置为 `754652181@qq.com`，但生产尚无 SMTP/EMAIL_HOST 凭据，因此 `TRANSLATION_FAILURE_EMAIL_ENABLED=false`。在完成 SMTP 配置和测试邮件前，不得宣称邮件通知可用或开启该开关。
- 运行验收：服务器内部 `http://127.0.0.1/healthz/` 与公网 `http://umafans.run/healthz/` 返回 200；浏览器真实打开首页、法国频道和 `/news/8093/` 详情页均正常，详情页含 8 个正文段落且无前端错误。HTTPS 仍未接入证书，Nginx 443 TLS server 块原本即为注释状态，本次不将 HTTPS 计为已完成能力。
- 法国只读 probe 未写文章：France Galop / TDN France / TDN France Broad 分别得到 `20 / 4 / 12` 条列表候选，三个来源均为 accepted，抽取的 6 篇详情全部成功；最新样本时间覆盖 2026-07-10 至 2026-07-12，未再返回 2020/2022 历史稿。生产法国来源 13/14/21 仍为 enabled、production approved、最近抓取 success。
- 该日 旧规格流程 进度为 `59/68`，其双审 Gold 待办已由后续单审资格决策取代。当前 旧规格流程 为 `63/71`：159 条 Gold 已通过本地覆盖与质量门槛，生产 gold/dry-run、人工复核、时间修复与翻译小批处理、shadow/enforce 灰度、网页/测试群/正式群扩展和窗口数量验收仍未完成，因此 change 保持 `implementing`，不得归档。
## 2026-07-13 历史赛事第一批生产详情写入

- 第一批 selection snapshot 固定为五地区各 9 场、共 45 场，绑定 inventory manifest `ac61298f242b2c649c403eae4741771a43cdb027befef20bc75e18fe34bcbad7`。日期发现审核后形成 `36 ready / 9 pending gap`：日本、香港、法国各 9 场有日期；英国 6 场有日期、2000 年 3 场缺口；美国 3 场有日期、2000/2012 年 6 场缺口。
- 日期 apply 已创建 36 个 draft `RaceEvent`。详情抓取完成香港 9 场、日本 9 场、英国 6 场、美国 3 场；法国 9 场因尚无达到完整出马表与赛果要求的解析链路，继续作为显式详情 gap，不用空候选占位。
- 完整详情候选为 27 场，SHA-256 `c999be2b2b0790837f8a6f5888e7068e775c783a57c6f8e7f3298e41e9b67a04`。生产 dry-run 通过后，新建详情写入前备份 `backups/db/pre-historical-detail-first-acceptance-20260713_055500.sql.gz`，大小约 139 MB，`gzip -t` 通过，SHA-256 `5f0f9d94406d55954b078339f2a3796556f6ffc98b47c43d6bf2d14bbccde9ff`。
- 正式 apply 成功：27 个目标全部转为 `imported`，写入 `RaceEventRunner=297`、`RaceEventResult=287`、`RaceEventDataCandidate=54`，候选状态全部为 `applied`，并生成 27 条 `historical_target_imported` 操作日志。逐目标核验与候选条数完全一致。
- 第一批最终状态为 `27 imported / 9 ready / 9 pending`：法国 9 场保持 ready 等待详情；英国 2000 年 3 场、美国 2000/2012 年 6 场保持 pending 等待日期来源。36 个已建赛事全部为 draft，published 为 0。
- 详情 source cache 在生产保留 38 个文件、约 5.4 MB，manifest 所列 18 个源文件大小和 SHA-256 全部通过。当前数据库约 832,322,583 bytes；本批核心新增 638 行，另有 27 条操作日志，相关表容量无扩大批次 blocker。
- 常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`；内外 `/healthz/` 均为 `ok`，容器正常，`web / worker / beat` 最近 20 分钟无 traceback/error。历史公开展示仍关闭，未执行前台发布验收。

## 2026-07-13 法国第一批详情补源进展

- 已从 ZEturf 精确定位并受控缓存法国 2012/2025 六场详情页；请求预算上限 50，实际仅抓取 R1/C1–C6 范围，缓存 manifest 保留逐文件大小、SHA-256 和来源 URL。2000 年页面在 ZEturf 已过期，仍保持缺口。
- 真实缓存首次回放暴露 2012 旧页面使用 `span.horse-name`、骑师/练马师节点结构变化，以及 2025 `Criterium de Saint-Cloud` 被误配到同日 `Criterium International`。已按 TDD 修复，法国 adapter 网络层同时改为统一 HTTPS host/重定向安全校验。
- 离线重跑结果为 `6/6` 唯一命中、`runners=70`、`results=41`、`skipped=0`、`errors=0`；runners 保留非出走状态，2012 旧页马名、骑师和练马师均可解析。
- 这六场尚未写生产：现有 target 批准的是 France Galop 日期/历史页，ZEturf 直接详情 URL 仍需通过独立、哈希锁定的来源补充 artifact 写回 target，之后才能由详情 packager 接受。禁止手工改 `source_refs` 或绕过 URL 绑定。
- 新增目标测试和完整 `stable` 回归均通过，完整测试现为 826 项；重新代码复审无 actionable finding。

## 2026-07-13 2016–2025 标准批次一号日美写入

- 首个年代带标准批次已批准 250 场，五地区各 50；selection snapshot 文件 SHA-256 为 `0724d55c904eb4072c8dfe741648a9678a71b447bc07fe59705ffa412a5be036`，approval SHA-256 为 `a046e17e2b5388ce7508eb644bcbf9437ec5af7d2ca7aa0523eccac84dd80a88`。
- 日本 50 场使用 JRA 官方年度表和单场赛果；美国 48 场由 TOBA 年表定位 Equibase Yearbook 单场结果，2 场障碍赛使用 NSA 官方结果。日期 artifact 中日美 `100 ready`，法港英 `150 gap`。
- 日期写入前备份 `pre-band-2016-2025-jra-us-date-apply-20260713_011232.sql.gz`，大小 `117378172`，SHA-256 `d93a26469dee057a70164eb7dc4f7f6a459fcf3c85f846b1713c0555213d6847`；100 场均已 materialize。
- 详情来源 artifact `c91872542a03db6519d29148c442ca9d38adc9cc52db6c247806eb5773ba9aec` 批准 98 场。日本 50 场和美国平地 48 场最终全部 imported，共 `1157 runners / 1080 results`；两场 NSA 障碍赛仍为 ready 详情缺口。
- Equibase 退赛现使用稳定 `SCR-n`；存储名次连续唯一并以 `official_finish_position` 保留并列。dry-run 会提前拒绝重复马号和重复存储名次，完整 `stable` 回归 `865/865` 通过。
- 一次 ARM64 镜像误部署使 web unhealthy，未迁移且未写详情数据，已立即回滚；后续改在生产机原生构建并核验 AMD64。当前 healthz 正常，常驻两个历史开关和公开开关仍关闭。

## 2026-07-13 NSA 两场补齐与生产兼容阻断

- 美国两场障碍赛已由 NSA 官方结果 PDF 补齐：A.P. Smithwick Memorial 为 `8 runners / 8 results`，Beverly R. Steinman Memorial 为 `7 runners / 6 results`；后者保留 faller CARLOUN 为 runner，不伪造完赛名次。候选 SHA-256 为 `478e263ee1b2e07ca6ef3cba23c683549393400b263ae250eef9b15fa0c3a1ff`。
- 写入前备份为 `backups/db/pre-band-2016-2025-nsa-import-20260713_015750.sql.gz`，大小 `117926527` bytes，SHA-256 `9a34f879a98e0fd8bda27b426b81f009bf6fcef0ce882b031589fe7c8867f3bc`。dry-run 与正式 apply 均通过；至此标准批次日美 100 场全部 imported，共 `1172 runners / 1094 results`，常驻历史功能、网络和公开展示开关继续关闭。
- 随后发现生产 `umanewsbot:prod` 被历史分支旧底座镜像覆盖：镜像含历史能力，但缺少 `origin/main@badc10e0` 的法国新鲜度、翻译恢复、多地区归属代码及 `stable.0027–0029` 对应写路径。数据库已经应用 `0029`，netkeiba 新增触发 `attribution_rule_version` 非空约束错误；收到 P0 后已立即停止新的历史写入、生产构建和容器重启，恢复动作由生产协调线程接管。
- 当前历史 worktree 已合入 `origin/main@1a70b22e`，保留全部历史能力并通过 Django check、迁移无漂移、323 项组合测试、完整 `stable 1093/1093`（1 skip）、旧规格流程 strict `25/25` 和 `git diff --check`。生产镜像替换继续由生产协调线程统一执行。
- 生产协调已短时切回 `umanewsbot:pre-irishracing-20260713`（`sha256:982fac66…`），恢复后成功新增并翻译 9 篇 netkeiba 文章，新增 NULL 约束异常为 0。独立 staging 已构建兼容镜像 `umanewsbot:merged-main-historical-amd64-20260713-1008`，完整 ID `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4`，内容 commit `0068715fceb0f629b5bfcb0c0b760427dfc6edc5`，构建树 SHA-256 `e51e6992e57649445aeff2aa7f2a0c925f3c5c742771fceac13053459beceec6`。该镜像尚未 retag 为 prod、未重启容器，等待生产协调线程最终切换。

## 2026-07-13 兼容镜像切换与法港英 150 场详情证据

- 生产 `web / worker / beat` 已由协调线程正式切换到兼容镜像 `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4`；`stable.0027–0029`、Django check、64 个模型、新闻新开关关闭、历史命令、五地区页面/后台/healthz 和日志均通过。回滚镜像为 `pre-merged-main-historical-20260713-1015`。历史线程不得再次重建或重启生产容器。
- 2016–2025 标准批次剩余法国、香港、英国各 50 场已完成日期定位与详情抓取：法国 `449 runners / 330 results`，香港 `515 / 506`，英国修正 Aintree Bowl 误配后为 `570 / 458`；三地区均 `50/50` 无跳过、无错误。
- 详情来源按目标一一对应，三地区分别 50 个唯一 URL、全局 `150/150` 唯一。统一日期发现证据包包含 150 条 provider 记录、150 条成功请求账本和 150 个逐文件大小/SHA-256 验证的缓存文件，共 `38,383,091` bytes，绑定 inventory manifest `ac61298f242b2c649c403eae4741771a43cdb027befef20bc75e18fe34bcbad7`。
- Aintree Bowl 现绑定 Sporting Life race ID `850965`，Aintree Hurdle 保持 `850966`；详情 URL 去重以移除 fragment 后的规范 URL 为准。生产只读 artifact 首次构建另发现 47 场英国距离证据缺显式单位或为紧凑分数写法，现已按 `<5 mile / >=5 furlong` 和 mile/furlong/yard 规则规范化，并修复 `71/2f` 的距离消歧误读。专项 57 项及完整 `stable 1128` 项通过，Django check、迁移漂移、旧规格流程 strict 和 diff 检查通过，最终复审无剩余可修复问题。
- 日期 artifact v2 已批准并受控提交，manifest SHA-256 为 `e5ede9033485f59faac8d27c5371bd4749c17235119f4eea173cca07cc389b03`；写入前备份 `pre-band-2016-2025-fr-hk-uk-date-apply-20260713_122142.sql.gz` 为 `121,994,037` bytes，SHA-256 `dae5869d58eb7e854d359f333e979b52647da75db667db930ff53d1cce5f521f`，`gzip -t` 通过。
- 150 个目标现均为 `ready` 并 materialize 为 150 个 draft `RaceEvent`；生产历史累计为 `145 imported + 150 ready`、2026 年前赛事 `295`，详情仍为 `1,640 runners / 1,523 results`，证明本次只写日期与赛事壳，未提前导入详情。用户要求先完成源码 Git 固化，后续详情打包、coverage、dry-run、第二次备份和正式导入现已暂停。历史公开展示开关继续关闭。

## 2026-07-13 线上验收发现旧底座镜像覆盖并完成组合镜像恢复

- `10:00` 左右验收发现生产仓库 HEAD 虽为 `1a70b22e`，运行镜像却已被历史赛事任务从旧代码底座重建为 `deadheat-fix-amd64-20260713`。该镜像仅加载 57 个模型，不认识 `stable.0027-0029` 和新增设置；数据库已经应用 `0029`，因此 netkeiba 新稿插入触发 `attribution_rule_version` 非空约束失败。问题属于应用镜像与数据库 schema 不匹配，不是来源失效。
- 已在 Celery/one-off 为空时短时切回 `pre-irishracing-20260713`，恢复后 netkeiba 完整抓取成功：新增 `3`、重复 `117`；本次恢复后共新增 9 篇，9 篇均完成翻译，`attribution_rule_version IS NULL=0`。由验收同步探测中断产生的 `CrawlJob 16266` 已显式标记失败并注明原因，未遗留伪运行状态。
- 历史赛事 worktree 已合入 `origin/main@1a70b22e`，组合源码通过专项 `323` 项、完整 `stable 1093` 项（1 skip）、Django/迁移/旧规格流程/diff 检查。生产最终切换到 AMD64 组合镜像 `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4`，镜像 tag 为 `umanewsbot:merged-main-historical-amd64-20260713-1008`；内容 commit 标签 `0068715fceb0f629b5bfcb0c0b760427dfc6edc5`，构建上下文树 SHA256 `e51e6992e57649445aeff2aa7f2a0c925f3c5c742771fceac13053459beceec6`。
- 最终运行验收：`web/worker/beat` 使用上述同一镜像，`stable.0029` 已应用，Django check 通过；归属、相关地区查询、翻译自动重试与失败邮件继续关闭。五地区页、后台登录入口和 HTTP `/healthz/` 全部返回 200，最近日志无 traceback/error/not-null constraint。
- 组合镜像包含历史任务尚未全部提交到 `main` 的实现，虽然已绑定内容 commit、上下文树 SHA 和回滚镜像，但仍不是最终可复现发布。历史任务完成当前批次后必须提交并推送全部生产代码；后续生产重建必须先合入最新 `origin/main`，禁止从旧分支或旧上下文直接覆盖 `umanewsbot:prod`。

## 2026-07-14 多地区归属 V3 单审校准优化

- 用户确认不再补充 Gold Set 或第二审核人；法国、美国未选地区的空白行继续忽略。现有审核包固定为 `159` 条单审标签、`1` 条明确排除、`90` 条未选择，始终标记 `provisional_single_review`，不得用于归属 commit 或生产启用资格。
- 为避免继续扫描生产数据库，已用审核包冻结文章和一次性术语快照建立本地 SQLite 校准库。旧规则在相同 `159` 条分母上的基线为主地区 `81.76%`、相关 precision `6.67%`、recall `6.45%`；生产此前 154 条结果只因 5 篇输入 SHA 漂移，不再作为算法同分母对比。
- `multiregion-v3` 增加按语言 token/bigram 的 `AttributionTermIndex`，17,474 条术语、38,806 个候选下，159 篇纯推断约 `0.8` 秒，完整 Docker 评估约 `2–4` 秒；候选命中后仍调用原边界匹配器。主地区达到 `98.11%`，日本/香港/英国/美国 `100%`、法国 `90.91%`、other `60%`；相关 precision `100%`、recall `54.84%`，无依据变化 `1.89%`、过度扩散 `0%`。
- V3 规则按标题叙事中心、明确赛事、导语唯一上下文、来源 fallback 分层；普通单词马名、短日文马名、同名单词赛事和正文背景不得单独改区。`other` 现在可作为主/相关归属证据持久化，但不新增生产频道、发布配额或 QQ 窗口。文章没有提供的历史参赛地区不为提高 recall 自动补齐。
- enforce 遇到 `needs_review` 时只写 `review_candidate` 审计，不修改主地区或关联表。归属/相关地区生产开关继续保持关闭，本轮没有部署、生产归属写入、镜像构建或容器重启。
- 归属与 Gold 审核目标测试 `82` 项通过（其中 1 项 PostgreSQL 专用性能测试在 SQLite 环境按设计跳过）；从仓库根目录、内存 Celery backend 运行最终完整 `stable` 回归为 `1156 passed / 1 skipped`。Django check、迁移无漂移、Python compileall、旧规格流程 strict/all `25/25` 均通过。PostgreSQL 250 篇基准、生产 72 小时 dry-run 和灰度仍待后续验证。

## 2026-07-13 法港英详情导入前字段门禁与 Git 固化

- 生产只读导出的法港英 150 个 ready 目标与审核证据对比后确认：日期 apply 已物化赛事日期和来源，但 `distance_text` 仍沿用原始 TJCIS 裸数字，未保留法国/香港的米制 `m` 和英国的 `mile/furlong/yard` 单位；另有 8 个权威场地名和 6 个法国 surface 差异需要在详情导入前校正。
- 已新增 `import_historical_race_event_field_candidates` 管理命令和整批服务。候选 JSONL 同时绑定整文件 SHA、target SHA、inventory artifact SHA、字段证据 SHA 和逐来源快照；仅允许基础字段白名单，dry-run 输出逐字段 before/after，apply 保护人工锁并同时锁定 target/RaceEvent，任一目标漂移或后段失败都会整批回滚。
- 基础字段 apply 会改变 target SHA，旧详情候选因此自动失效；正确顺序固定为字段 dry-run/备份/apply、重新导出 event input、重新打包详情、coverage、详情 dry-run/第二次备份/apply。禁止手工修改生产 `RaceEvent` 或复用旧候选绕过身份校验。
- 本轮目标/相邻测试 `34/89` 项通过；在临时 Redis 和 macOS 真实临时目录下完整 `stable` 回归 `1136/1136` 通过，1 项按设计跳过。Django check、迁移无漂移、旧规格流程 strict 和 `git diff --check` 均通过；两轮代码复审最终无待修问题。
- 当前生产仍运行 `main@304ebdb6` 对应可复现 AMD64 镜像，历史公开数据保持关闭。本轮字段门禁尚未部署，也未执行字段或详情生产写入；先完成源码提交、推送和合入最新 `main`，再由最新主线构建并受控替换生产镜像。

## 2026-07-13 历史来源匹配器主线固化与可复现镜像切换

- 历史赛事全部必须保留的源码已提交并合入 `main@58786b91fba9c44054a6102055766824677bcbcb`。该版本新增 JRA 当前赛事别名、TOBA 核心限定词全词匹配、同一结果 URL 跨目标复用阻断，以及 TOBA `not run` 证据解析；完整 `stable` 回归为 `1141 passed / 1 skipped`，迁移无漂移，旧规格流程 strict/all `25/25`，最终代码复审无 actionable finding。
- 在生产独立上下文 `/opt/umanewsbot-builds/main-58786b91-20260713-1435` 两次构建得到相同 AMD64 image ID `sha256:c6a3670fdc42db9c0b8ded5772630ac1b0511b98a521ea7f4a9cbe7e25864691`。镜像标签绑定 Git tree `5d8b7ccf775f6be7051c88e8f440b034ad02f4df` 和 source archive SHA-256 `184f05c39d3df5dd0bb1f410bdccda418ed3052964edea99b07faf22723fa07e`，已替换生产 `web / worker / beat`。
- 切换前数据库备份为 `backups/db/pre-main-58786b91-20260713_143748.sql.gz`，大小 `149,960,820` bytes，SHA-256 `9f29cd1a28b41761591a1966c68125c611a36290953cf0d845cdcead05891f27`，`gzip -t` 通过；旧镜像保留为 `pre-main-58786b91-20260713-1439`。
- 部署后 `stable.0029_france_freshness_translation_attribution` 已应用、64 个模型可加载，五地区页面、赛事页、马匹页、后台、内外 healthz 和近期日志均通过。生产历史总账 `30,917` 个目标，历史赛事 `295` 场、`3,174 runners / 2,817 results`，全部仍为 `draft`，published 为 `0`；常驻历史写入与网络开关均为 `false`。
- 切换后的 `14:45` 自然窗口完整通过：`17` 个 crawl、`5` 个 publish、`5` 个 QQ 窗口全部 succeeded；抓取共 seen `472`、new `3`，新增文章 `attribution_rule_version IS NULL=0`，web/worker/beat 近期错误日志均为 `0`。
- `2016–2025` 第二标准批次已固定五地区各 50 场。日美离线来源发现得到 JRA 50 条、Equibase 48 条，共 98 个唯一 URL；Brooklyn 与 Cougar II 的 2025 届由 TOBA 标记为 `not run`，继续等待产品口径审核，其余 248 个目标不受阻塞。

## 2026-07-13 紧凑英制距离修复生产切换

- 紧凑英制距离修复已进入 `main@d8b65fe7d63e913cf826d02a74cdebaec60351ce`，并由生产机独立构建为 AMD64 镜像 `sha256:77eb11385d1d23843d2e2bae96bc5b4da4453732edb567d46cb0cc0fb01c3da0`。镜像标签绑定 Git tree `fda256535ae3b9f435cf8c7b069ff26d04503d99` 和 source archive SHA-256 `2b085d0226580295f9a844fbc92df48405cd9bb3b467786230fac8941fa60520`。
- 切换前确认外部导入、外部锁、Celery active/reserved 和 one-off 写入均为空；停止 beat、排空并停止 worker 后才 retag。生产 `web / worker / beat` 现统一运行上述镜像，旧镜像 `sha256:c6a3670f...64691` 已保留为 `rollback-pre-d8b65fe7-20260713_163805`。
- `.env` 备份为 `.env.backup.main-d8b65fe7-20260713_163805`。数据库备份为 `backups/db/pre-main-d8b65fe7-20260713_163805.sql.gz`，大小 `124,020,905` bytes，SHA-256 `33f5ef3520e833a8cf343ca87831a7620c9cb80ba095e74c5cadb716d55ccfa2`，`gzip -t` 通过。
- 部署没有新增迁移；Django check、静态资源收集、内外 healthz、首页、赛事页、worker ping 和近期错误日志均通过。生产纯函数 smoke 已确认 `2m4f` 解析为 2 mile + 4 furlong，`3m21/2f` 解析为 3 mile + 2.5 furlong，且保留来源原文。
- 常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，多地区归属与相关地区查询也继续关闭。本次只切换代码，没有执行历史赛事写入。
- 使用新镜像连接生产库只读重建 batch002 日期 artifact，结果精确为 `246 candidate / 4 gap`：法国/香港/日本各 50，英国/美国各 48；4 个 gap 仍是两场英国 `ABANDONED` 和两场美国 TOBA `not run`。manifest SHA-256 为 `9ed3b7138012b4ce1732cf1f071d13cb16678a97983ea63d94329fe84c902e68`，尚未审批、备份或 commit。

## 2026-07-13 第三标准批次只读证据完成

- batch003 selection 固定为五地区各 50 场、共 250 场，与 batch002 零重叠；本轮没有执行生产写入。
- 首次离线快照曾为 `249 candidate / 1 gap`、`2,635 runners / 2,346 results`，候选 SHA-256 `31c8cf61191d937c766f98b50a656ec98e92f774b59e5d0635fd54090ee2ad1a`；该快照遗漏 Hampton 移师后的实际赛果，已隔离并被上方 batch003 正式结果取代，不得审批或恢复。
- `target_id=60693` 的 Warwick 页面只证明原定场次 `ABANDONED`；用户提供 Windsor 正式结果后已按正常举办收口，不能再作为 gap 或 cancelled 候选。
- 修复了 ZEturf 发现页把实际缓存 URL 重写成另一目标 slug 的身份错误，并把 NAR `keiba.go.jp` 与法国 Zone-Turf 同步登记到日期校验、补充来源审批和最终详情打包三层。年度日历的 `flat/jumps` 只证明竞赛类型，不再用它覆盖已审核的 `surface`；Hoppings Stakes 保持 Newcastle synthetic。
- 专项 73 项、完整 `stable 1161/1161`（1 skip）、Django check、迁移无漂移、旧规格流程 strict `25/25` 和 `git diff --check` 全部通过；代码复审无剩余可修复问题。
- 生产仍运行 `sha256:77eb11385d1d23843d2e2bae96bc5b4da4453732edb567d46cb0cc0fb01c3da0`。先前候选镜像 `sha256:9cd0b966...45bc1` 不包含本轮来源修复，已视为过期；必须从最新 main 重建可复现 AMD64 镜像后，才允许连接生产库生成日期/来源 artifact、dry-run 和后续受控写入。历史公开展示继续关闭。

## 2026-07-13 batch003 来源门禁镜像生产切换

- batch003 来源门禁修复已合入 `main@3939992c7d3753779fc34de81c595f5a34d7ed2b`，生产现运行 AMD64 镜像 `sha256:87c435cfc50344d0ca94f46e44d4bea97ab11361f88f7c708b6457331aee78ec`。镜像标签绑定 Git tree `0464a1aae6f587e3ba021421ac84b44a3d9379dd` 和 source archive SHA-256 `a787391c84a4ba3bb22c2ab638f1e36453d3ff8869bb95aeb5001b1dd448bb21`。
- 切换前发现两条正常新闻抓取任务正在执行，因此先停止 beat 并等待任务自然完成；确认 Celery active/reserved、外部导入、外部锁和 one-off 历史写入均为空后才继续。生产 `web / worker / beat` 已统一切换到新镜像。
- `.env` 备份为 `.env.backup.main-3939992c-20260713_185140`。数据库备份为 `backups/db/pre-main-3939992c-20260713_185140.sql.gz`，大小 `125,782,755` bytes，SHA-256 `21903cf8d9494ef6053414a34c2e2f6ab01406b9ffebcf56ff3fd10eedfc0967`，`gzip -t` 通过；旧镜像回滚标签为 `umanewsbot:rollback-pre-3939992c-20260713_185140`。
- 无待应用迁移；Django check、静态资源、worker ping、内外 healthz、首页、赛事页和近期错误日志均通过。常驻历史写入/网络、历史公开、多地区归属及相关地区查询开关继续关闭。
- 该镜像切换步骤本身没有执行 batch003 写入；随后历史线程已按独立 approval、备份和门禁完成上方 250/250 正式导入。旧的 `249 candidate / 1 Hampton gap` 预期已经作废。
## 2026-07-18 P0 马详细资料首批来源审计与人工补录入口

- 五地区各 10 匹身份审核仍为全批纳入；当前只有日本 `10/10` 已由完整缓存和离线回放证明资料、二代血统及完整生涯均可生成。其他四地区不得因为 adapter 代码存在而视为真实可用。
- 受控单马探测结论：中国香港 HKJC 可访问，但缺精确出生日期、繁育者、部分二代血统及逐场正式比赛名；英国 Sporting Life 可返回完整表单，但样本缺出生国和繁育者；法国 Geny 返回 HTTP 429，Canalturf 仅能作为部分资料证据；美国候选缺 provider horse ID，Equibase 被防护页阻断，HRN 样本可访问但精确出生日期存在跨来源冲突。
- 新增保守多来源合并和人工补录入口。自动第二来源只能填空，既有非空值不同即阻断；人工补录只允许 `identity/basic_profile/pedigree` 白名单字段，必须记录直接证据 URL、录入人、不同的复核人、审核时间和字段组，禁止补写 `career`，并在证据中明确标为 `manual_supplement`，不得伪装为 adapter。
- `complete_horse_profiles` 新增 `--p0-manual-supplements`，只允许与已授权审核候选网络 dry-run 同时使用。批次 manifest 记录人工补录文件路径、大小、SHA-256、批准字段数和候选数；只有 `review_status=approved` 的行参与合并。
- 已生成审核工作簿 `outputs/p0-horse-info-completion-20260718/P0马详细信息补全_字段审核工作簿_20260718.xlsx`，包含 50 匹队列、四地区真实阻断、70 个中港英待审核字段和完整字段字典。工作簿不构成抓取、写库、发布或生产授权。
- 独立 reviewer 首轮指出候选 CSV 与人工 CSV 的哈希快照竞态，以及美国 HRN 三请求回退超过两请求预算。现已改为直接解析首次捕获并用于 SHA 的同一字节快照，美国预算提高为 `3`；并新增未选地区人工行、自定义 source client、已非空目标字段三项前置阻断。第二轮补齐 cache hit 人工合并、冲突和幂等复放；第三轮把纯自动 canonical cache 与本批人工工作副本拆开，并增加逐字段 `applied/already_applied/blocked/ignored` 结果及总体、地区和 manifest 汇总。第四轮进一步要求 canonical cache 读写严格拒绝所有人工标记，并在 staging 前按完整证据指纹核对每个批准字段与唯一 outcome；污染 cache、混合来源、缺失/重复/非法状态/证据漂移和无输入旧 outcome 均 fail closed。第五轮把 canonical payload 限制为严格 JSON 类型，tuple/set、非字符串对象键及非有限浮点值不得在序列化前绕过纯净检查。第六轮把该检查改为带活动容器集合和最大深度的迭代遍历，循环和过深结构稳定转为领域 blocker；真实审核批次证明 7 个非法候选被隔离、3 个合法候选继续且 cache 无临时残留。第七轮把严格形状检查提前到 `deepcopy` 之前，并把磁盘 JSON 解码的 `RecursionError` 包装为来源错误；1200 层内存与 cache 输入都稳定阻断且批次继续。第八轮仅允许精确内置 `dict/list` 容器，校验后通过 JSON round-trip 生成纯内置类型副本；异常/篡改型容器子类不触发复制钩子，深层坏 cache 批次前后目录与逐文件字节完全不变。第九轮在 JSON 规范化副本上再次检查人工标记，并让自动多来源与人工补录两个直接合并入口先规范化全部输入；欺骗型字符串值/键和异常/篡改型 helper 输入均 fail closed。第十轮把独立 canonical purity gate 也改为检查规范化副本，直接 helper 与实际 adapter + cache 路径都能阻断欺骗型人工标记且不落 cache。source-client `68/68`、四模块 `123/123` 均在 Docker `--network none` 下通过。
- 第十一轮同一独立 reviewer 最终返回 `VERDICT: APPROVED`，无 actionable findings；审前/审后 fingerprint 均为 `9d2a7a276236306d3468e7a302df46e448ecfee257c64763db4700197edc8303`，reviewer stdout SHA-256 为 `b124808e0a93c4662687790b11f87dd192f29d9dff53692ff9383d96edb8ed8a`。该批准只覆盖当前只读能力、模型/展示/测试与人工审核通道，不授权四地区 10 匹网络批次、生产 `HorseRaceRecord` 写入、赛事创建、公开发布、Git 合并或部署。
- 当前真实完成度仍为 `10/50`。任务 4.2 保持未完成；下一步先解决四地区主源/身份/字段缺口，再逐地区单马复验，只有单马达到完整资料和完整生涯双门槛后才允许扩到该地区 10 匹。

## 2026-07-19 P0 马五地区 50 匹人工审核返修与履历证据分层

- 本轮只在 P0 worktree 修复能力、模型/迁移、展示、测试和只读审核产物；没有启动新的历史履历
  网络抓取，没有批量写生产 `HorseRaceRecord`，没有为普通比赛强建 `RaceEvent`，也没有发布或
  部署。
- 履历来源模型现将官方/主来源实际出赛总数与逐场权威性分开。新增总数来源、来源 URL、核验时间
  和逐场权威状态；数量相等但逐场来自备用来源时只能标记
  `count_aligned_records_unverified`，不得宣称逐场官方履历完整。
- Sporting Life 逐场字段证据现按 `direct_raw/canonical_raw/normalized` 三层保存，各自保留状态、
  来源 URL、时间和转换规则。法国 Class/Grade 与舍入英制距离在缺少 France Galop/IFCE SIRE
  权威证据时保持阻断，不反推 Groupe 或官方米制。
- 法国 `12` 条 Sporting Life `N/A` 已全部由 France Galop 官方公报补证为正式名次或
  `arr/tbé/t.j`；Kentucky Wood `2026-05-30` 的 `arr` 按实际出赛未完成比赛计数。法国当前
  `250 actual / 11 official abnormal / 0 unknown / gap 0`。
- HKJC parser 已识别首列纯文本 `Overseas`，设置 `is_overseas=true`、生成稳定记录键，并对主表与
  下方 `Overseas Horse Form Records` 去重。香港当前
  `379 records = 376 actual + 3 non-start`，其中 `4` 次海外；SOUTHERN LEGEND、
  BEAUTY ONLY、TIME WARP 均与 HKJC 总数对齐，缺口为 `0`。
- Sporting Life parser 已读取 `casualty.reason`。Edwardstone 的五场 `F/F/UR/BD/UR` 均保留原始
  reason、正式码和归一化状态，`finish_position` 可空但计入实际出赛。另 `8` 条旧 `N/A`
  已核验为 `5` 条正式名次和 `3` 条未实际出赛；结果状态与实际出赛状态独立保存。英国当前
  `412 records = 409 actual + 3 non-start / 10 official abnormal / 0 unknown / gap 0`。
- 法国/英国的产地与育马者、中国香港的精确出生日期与育马者共 `60` 个基础字段已按来源马 ID、
  父、母和出生年身份锁完成字段级补证；五地区 13 项基础/三代血统硬字段均为 `130/130`。
- 美国 `10/10` 匹 Equibase `Career Starts` 和毛色均已作为人工核验证据保存。HRN 原始 `197`
  行合并 `6` 条同场重复后为 `191` 次已采集实际出赛；Fort George 原缺 `7` 场已由 Sporting
  Life/Racing Post 结果页补齐，现全批 `198/198` 数量对齐、已知数量缺口为 `0`。由于逐场来源
  不是 Equibase 官方数据，美国 `10/10` 匹仍保持逐场官方性待确认。生产实现不得绕过
  Incapsula 或违反 Equibase 条款，长期改用授权数据或人工 Full Charts/Lifetime PP。
- 50 匹离线审核产出 `50` 匹资料、`2050` 条逐字段证据、`1439` 条逐场履历和 `2679` 条逐场
  三层字段证据。严格完整资料门禁为日本、法国、中国香港、英国 `40/40`，总体 `40/50`；美国
  不因数量对齐而升级为逐场权威完整。
- 当前工作簿位于
  `outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/P0马五地区50匹完整解析与字段可用性审核-v2.xlsx`，
  最终 SHA-256 为 `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`，人工证据应用 ID 为
  `3d5ab289cc5590e3cc405a4f28e532b98c86466f1b8da656e01183ca1fb2508c`；
  9 个工作表已完成公式错误扫描和逐表视觉核验。
- 真实 HKJC 页面形状、Sporting Life casualty、法国 N/A 补证、官方总数/逐场权威性、模型与完整
  履历分页、人工赛果证据身份/比赛绑定相关回归在该历史轮次为 `277/277`；第十四轮最终增至
  `282/282`。Django check、迁移无漂移、旧规格流程、工作簿摘要测试和公式错误扫描通过。
  task `4.2` 继续未完成；美国逐场官方性等剩余语义按
  `missing/partial/source_blocked/parser_gap` 保留。

## 2026-07-19 五地区准实时公开 Beta 首次 review findings 已修复，待限定复审

- 独立 worktree 已形成五地区代码候选：TRA 自动链只负责合资格 event 的暂定赛果；英国、
  法国、香港、日本 JRA/NAR、美国官方 route 只以 manual-browser receipt 做正式/改判
  复核，`automation_allowed=false`。香港和日本资格矩阵均为
  `G1/G2/G3 + JpnI/II/III + JG1/2/3`，未知/Listed/Open fail-closed。
- 正式 receipt 可先形成 immutable staged revision；没有精确 event authorization 时，
  current pointer 和前台继续保持 provisional。authorization 命令只有在 global/region/
  event official coarse gate、TRA source provisional gate、allowlist、route、terms 和
  marker evidence 全部一致时，才会把同一 staged revision 发布为 official/corrected，
  并同步 publication audit、tracking、legacy projection 和 public read。
- broad scope/official authorization 的 apply 均要求真实
  `scheduler=false`、`monitor=false`、全库 active claim 为 0，并在写事务内重新检查。
  rollback 候选新增 filtered PostgreSQL-only env、不可变 image ID、manifest/env SHA、
  PostgreSQL read-only validator、maintenance-off provisional pointer restore 和
  coarse-then-event policy CAS；任何漂移保持隐藏且零业务写入。
- 首次独立代码 review 返回 `CHANGES_REQUIRED`；已按真实 RED 修复 official bulk read
  N+1、原始分页截断、pagination checkpoint/monitor 分类和十页 fetch/Celery 时间预算。
  当前完整准实时 SQLite 专项 `353 tests OK (14 skipped)`，一次性本地
  PostgreSQL 16 专项 `25 tests OK`，测试数据库和容器已删除；Django check、migration
  drift、compileall、三份 Compose、JSON 和 diff whitespace 均通过。此前候选镜像
  `sha256:193c0d591da3fd55a11607ebe7ebfafccc949efd33c4efddb529ea2d91da6b60`
  已因受审内容变化而作废；修复后的本地复审候选镜像为
  `sha256:7764a332fba2991be4a4c2f70814d727ba910c68005f19de579e4900c962960c`，
  容器内 Django check 与 `165/180/210/240` 秒 budget/soft/hard/claim TTL 契约通过，
  但它仍不是最终发布镜像。全仓测试的历史 runner macOS 路径/命令环境失败已与未改动
  `origin/main@566a9b10` 对照复现，不纳入本需求回归修复。当前等待同一 reviewer
  限定复审；尚未取得成功 review、fingerprint 冻结或发布授权。
- 本候选**未 commit、未 push、未部署、未迁移生产、未购买订阅、未开启 scheduler/
  monitor/新增地区或公开范围，也未连接生产写入**。生产真实状态继续以上一条已发布
  race-live 安全基线为准；本节只描述待审核预期。

## 2026-07-19 五地区准实时公开 Beta 代码层生产发布

- 用户授权的冻结 fingerprint
  `17a1b34321ee25f13f783c1fe24278bbacdab288f3a30281a981e4986158e0fa`
  已按受审 content hash 精确提交为
  `85948707c7b2bf3c62a66b09b2ddb202adf2d1ee` 并快进 `main`。生产运行 AMD64
  镜像为
  `sha256:4c40ae1946dd9ac85a368917fe3de64269e6cf848737e24253f0d0996403eda6`；
  `web / worker / race_live_worker / beat` 均运行该 image ID 和 revision。
- 切换前历史 runner 预检为 `migration_safe`，Celery
  `active=0 / reserved=0`。数据库备份
  `backups/db/pre-five-region-race-live-85948707-20260719T111505Z.dump`
  为 `204,512,228` bytes，SHA-256
  `98833a3d9dd5ebd74eb5c7d46ac44caa9b3d5d9ab6e310ec02137fe612e79c89`，
  且 `pg_restore -l` 通过；旧镜像回滚标签指向
  `sha256:700ea78698fb67de602fb7e5447b997610e24e64de29df4591e4bb9e476087ef`。
  `.env` 备份权限为 `0600`；filtered rollback env SHA-256 为
  `cda13ce08c6a6d03ffcb4812cf1e1bc1d56fa7eae2244d7cf72330869811062e`。
- `stable.0047_race_live_public_beta_controls` 已应用；Django check、
  migration drift、collectstatic、worker ping、内外 `/healthz/`、event 924 和五地区赛事
  筛选页均通过。event 924 仍为同一 provisional revision `#2`、同一 content SHA、
  7 条结果和“暂定赛果”页面；migration 只补齐专用 provisional pointer 和 publication
  authorization audit。
- 当前生产保持
  `RACE_LIVE_SCHEDULER_ENABLED=false`、
  `RACE_LIVE_MONITOR_ENABLED=false`、
  `RACE_LIVE_ENABLED_REGIONS=[]`，selector 返回
  `enabled=false / claimed=0 / dispatched=0`，active claim、`celery` 和
  `race_live` queue 均为 0。代码部署不等于五地区来源已上线。
- 部署后 Free 来源 proof 用 3 个有界请求取得 `200/200/200`：地区表 55 条、今日
  racecard 43 场、今日 result 2 场，只保存去标识元数据，summary SHA-256 为
  `1369c0c27af746891bbfdf932010601e3e6def82eba749452cf1522e4de9db79`。
  法国 event 733–735 prepare 因真实 payload 中 coupled entries 的重复参赛编号触发
  `racecard_schema_invalid`；日本 event 80/81/185 与美国 event 420 均为
  `racecard_not_found`。这些地区继续 off，英国下一批和香港均尚未取得本轮来源 proof。

### 2026-07-19 发布证据锚点补充

- 来源 proof 目录为
  `/opt/umanewsbot/runtime/race_live_racecards/source-proof-free-20260719T112200Z`；
  其中 `manifest.json` SHA-256 为
  `26af97b56781803de44e418b8693ca13e1fff61f653f44a4acffb27b78ae3bfe`，
  `requests.jsonl` SHA-256 为
  `98e513464736082176bfa91b7579e45326d7228653ad6ac8090e92890d69127a`，
  `summary.json` SHA-256 为
  `1369c0c27af746891bbfdf932010601e3e6def82eba749452cf1522e4de9db79`；
  三个文件均为 root-owned `0600` regular file。`55/43/2` 与三次 HTTP 200 的明细
  以 `requests.jsonl` 为准。
- 当前 rollback artifact 目录只有 root-owned `0600`
  `rollback.filtered.env` 及其 SHA 文件；尚无冻结的 `manifest.json`，因此 frozen-image
  one-shot 的 business result/policy rollback **尚未达到可执行门槛**。当前可用恢复面
  仅为已验证数据库备份、旧 image tag 和 `.env` 备份；缺失 manifest 时不得执行
  one-shot 或开启新地区/public event。

### 2026-07-19 rollback 门禁事实更正

- 冻结 Gate D 原本要求在代码发布 artifact 中保存 rollback manifest 路径和 SHA。该
  manifest 实际未生成，因此原发布门禁**未满足**，本次 release evidence closure
  仍不完整。任何后续补救必须作为独立受审、获准并验证的操作处理；当前只能继续保持
  全部新地区、scheduler 和 monitor 关闭。

## 2026-07-19 准实时 Beta Gate 修复已完成本地实现，待代码审核

- 法国真实 Free racecard 中合法 coupled entries 现按非空 `external_runner_id`
  区分；不同 runner 可保留同一来源号码，重复 external ID、字段异常和超限仍
  fail-closed。legacy `RaceEventRunner` 新增 external identity，并把唯一约束从
  `event + horse_number` 改为 `event + nonempty external_runner_id`；历史空 identity
  行保持兼容，动态字段在号码/名称歧义时零写入。
- 新增 root-only rollback bundle 生成器和四层 publication policy 的单事务
  maintenance CAS。bundle 严格绑定候选 image ID、filtered env SHA、approved commit、
  event/revision/publication/allowlist、tracking lock version 和四层
  maintenance/restore 快照；artifact 采用不可覆盖原子发布、root-owned
  `0700/0600`、exact-key/duplicate-key/大小/secret 门禁。
- generator、maintenance、validator 和 policy restore 均要求
  `scheduler=false`、`monitor=false`、enabled regions 为空、tracking 全关且 claim
  为空；恢复阶段只允许
  `maintenance -> coarse-restored -> restored`，event-before-coarse 和任一漂移均拒绝。
- 新增 migration
  `stable.0048_raceeventrunner_external_runner_identity`。当前本地验证为目标/相邻
  SQLite `42/42`、准实时组合 `206/206`（14 项 PostgreSQL 专用跳过）和临时
  PostgreSQL 16 `25/25`；Django check、migration drift、compileall、三份 Compose
  config 与 `git diff --check` 均通过。
- 首次独立原生 code review 返回 3 个 P1、3 个 P2；已逐项取得真实 RED 并完成直接路径
  GREEN：rollback 生成前复用真实 public-read admission；initializer 拒绝既有 legacy
  runner 并精确验证 replay；P0 coupled identity 不再以同一号码覆盖；动态更新恢复唯一
  名称兜底；unchanged replay 安全惰性迁移 external identity。主代理复跑准实时组合
  SQLite `220/220`（22 项 PostgreSQL 专用跳过）和 remediation 主模块/专项在临时
  PostgreSQL 16 `37/37` 通过。
- 同一 reviewer 的首次限定复审又指出 2 个直接 P1 和 3 个直接 P2；已按新增 RED 修复：
  P0 统一读取 runner/result external identity 并以 `source_key` 隔离命名空间；rollback
  generated manifest 透传并行锁内 CAS current revision pointer；validator 要求
  scheduler/monitor=false；普通 refresh/replay 在任一写入前拒绝 legacy 新列/source
  refs 身份冲突。主代理最新复验为准实时相关 SQLite `432/432`（2 项环境跳过）和临时
  PostgreSQL 16 `71/71`；Django check、migration drift、compileall、三份 Compose
  config 与 `git diff --check` 均通过，临时数据库和容器已删除。
- 当前状态是
  `findings fixed / scoped re-review pending / not authorized / not deployed`。
  生产仍运行 `85948707` 对应镜像；scheduler/monitor、新地区和 enabled regions
  继续全关，法国 event 733–735 尚未重新联网 prepare，event 924 状态未改变。

## 2026-07-20 P0 马全范围来源已写入生产

- 写入前备份位于
  `/opt/umanewsbot/backups/p0-horse-full-scope-precommit-20260720T063831Z`；
  数据库 dump SHA-256 为
  `f773f5ec0a98974cc402b202cfe2f0eed91fc4f022e58a621f2c7b2b63b96378`，
  restore list 为 `1017` 行。
- 首次无地区单事务同步触发主机 OOM，Linux 杀死 Python 进程；事务完整回滚。重启后核对仍为
  `50` 条有效 P0 来源、`21621` 匹资料和 `0` 个待处理身份冲突，没有半写状态。
- 随后临时启用 `1 GiB` swap、停止空闲 worker，并按法国、香港、英国、美国、日本五个地区
  分批提交；最后以每批 `500` 条的事务补齐 `other` 和空地区的已翻译 horse term 来源。
  全部完成后已恢复 beat、worker 和 race-live worker，并删除临时 swap。
- 当前生产有 `56745` 条有效 P0 来源、`46318` 匹唯一 P0 马：
  `35097` 条重点赛事参赛来源、`21598` 条已有中文名 active 术语来源和 `50` 条人工来源。
  已翻译 horse term 缺失 P0 来源数为 `0`。
- 资料完整度必须与 P0 范围写入分开报告：当前 `50` 匹为
  `complete_profile_full`，`2` 匹为 `complete_pedigree_2gen`，其余 `46266` 匹仍为
  `empty`；完整生涯 `50` 匹、部分生涯 `2` 匹、尚未采集 `46266` 匹。
- 当前有 `65042` 条待处理身份冲突证据。它们代表按赛事参与项保存的歧义，不等于同数量的唯一
  马匹；在父名、母名、出生年份或稳定外部 ID 足以区分前，不得猜测合并或写入详细资料。
- 生产 `manage.py check` 通过，migration 已应用至 `stable.0052`，`/healthz/` 返回
  `{"status":"ok"}`。

## 2026-07-23 公开门户 P1–P3 已整体上线

- 公开门户视觉改版 P1、赛事体验 P2、马匹与关注体验 P3 已作为同一发布提交
  `bc7e2df047a20a997de1620688f1c7de4a5c52c4` 快进 `main` 并部署到生产。
- 本次没有数据库迁移；生产 `manage.py check`、migration plan、collectstatic、内外
  `/healthz/` 均通过，首页、赛事日历、马匹列表、关注页和 sitemap 均返回 HTTP 200。
- `web / worker / beat / race_live_worker` 已统一运行镜像
  `sha256:69ed2bd9f3f7ecc581c2caba4704bd7b1764fc02af6a2663b78f599217b23696`。
  部署脚本未自动重建 `race_live_worker`，本次已使用低成本 Compose 精确重建该服务并复核
  四个应用容器 image ID 一致。
- 生产浏览器验收覆盖 1440px 和 390px：首页、赛事日历、赛事详情、马匹列表、马匹详情、
  我的关注均无横向溢出；桌面/移动导航断点正常，Noto Serif SC 700/900 字体加载成功，
  浏览器控制台无错误。
- 发布前数据库备份为
  `backups/db/pre-portal-redesign-20260723_024424.sql.gz`，大小 `232004041` bytes，
  SHA-256 为 `9bdb7a53cde72c1302c86886415b5d59f4a088a5ae93e0325d34c8b0261fb6b2`，
  `gzip -t` 通过；环境备份为 `.env.backup.portal-redesign-20260723_024424`，权限 `0600`。

## 2026-07-24 赛事日历月份与移动端等级徽标修复上线

- PR `#17` 已合并并部署到生产，生产 HEAD 为
  `3772256e606e3f62081eecec162fecedbd1aa23d`；本次无新增迁移、无赛事或新闻业务数据写入。
- `web / worker / beat / race_live_worker` 已统一运行镜像
  `sha256:90c98db7eb048949507bbc3d335ed7b989dc9ce6dab1d3576a5242c2c4d10e49`。
  Django check、migration drift、内外 healthz、首页、赛事日历和后台登录入口均通过。
- 生产 1440px、390px 和 320px 验收确认：日期轴直接显示月份，跨月的
  `6月28日 / 7月1日` 无歧义；G1、G2、JPN1 在长赛事名下均保持 `42×42px`，
  390px/320px 页面无横向溢出，浏览器控制台无错误。
- 部署前数据库恢复点为
  `backups/db/pre-race-calendar-responsive-20260724T173452+0800.sql.gz`，
  大小 `242013429` bytes，SHA-256
  `2ed8f391b4b37e3590e22ad558ce6237a53ded073f6a5920aafacad8d8f4ce7f`；
  `gzip -t` 通过。环境恢复点为
  `.env.backup.race-calendar-responsive-20260724T173452+0800`，两者权限均为 `0600`。

## 2026-07-24 跨地区赛事与马匹履历字段归一化方案完成交接

- change `normalize-race-and-career-fields` 已完成探索、规格、设计、测试用例、任务拆分和
  rollout 设计；独立方案 reviewer 经三轮复审后给出 `VERDICT: APPROVED`。
- 自包含交接入口为
  `docs/changes/normalize-race-and-career-fields/HANDOFF.md`，其中冻结了生产只读基线、
  字段与映射合同、迁移链、backfill/receipt 合同、功能开关、TDD/subagent 顺序、验证矩阵、
  并行 change overlap、发布与回滚边界。
- 当前准确状态为
  `plan approved / handoff complete / implementation not authorized / no code or production write`。
  本轮没有新增测试、应用代码、迁移或配置，没有 commit、push、PR、部署或生产写入。

## 2026-07-25 HRN dialog 残留与美国机构译名修复完成本地实现，待代码审核

- Gate 6 历史正文处理后的只读复核发现：HRN `.article-body` 内嵌的
  `role="dialog"` 视频 modal 会把 `Race Video ×` 带入正文；生产已有英国同名机构词条
  又会把 HRN 美国文章中的 `The Jockey Club` 映射为“英国赛马会”。
- 当前候选只在 HRN 来源内删除 dialog 结构，并通过 provider 共用的确定性 TERM 计划把完整
  英文边界 `The Jockey Club` 恢复为“美国赛马会”。英国非 HRN 来源、普通正文同词、
  `The Jockey Clubhouse` 和其他术语行为保持原状。
- 测试先行证据为聚焦 `10` 项中 `7` 项真实 RED；实现后主代理复跑两组受影响矩阵
  `120/120 + 170/170 = 290/290`。Django check、migration drift 和 diff 检查通过；
  本轮没有 migration。
- 当前精确状态是
  `implementation GREEN / code review pending / not authorized for release / no production write`。
  尚未 commit、push、创建 PR、部署或重新 prepare Gate 6 剩余 36 篇；历史重处理继续等待
  最新成功 code review 后的当前版本发布授权。

## 2026-07-26 HRN dialog 残留与机构译名修复已发布，历史重处理完成

- 独立 reviewer session `019f98b4-e9b2-7520-9b08-f04a3e01b2ec` 返回 `APPROVED`；
  PR `#22` 已合并，生产 revision 为 `8cbee3e70bb1044248a18ed5521a1273d629d404`。
- 生产 `web / worker / beat` 统一运行镜像
  `sha256:02a83fbde219827ce5a49c633086057eb7d2957abb1e19c7b386205fc914c60e`；
  本次无 migration，Django check、migration drift、Celery、内外 healthz 和公开新闻页通过。
- 冻结 36 篇最终为 `12 applied / 18 translation_failed / 6 review_rejected`。部署后完整
  inventory 另发现 8 篇同结构 `Race Video ×` dialog 污染，作为独立 cohort 逐篇审查后
  `8/8 applied + verified`。
- 本轮合计审查 44 篇、写入并验证 20 篇。282 篇权威 cohort 未漂移，
  `source_clean 171 -> 183`、`source_changed 111 -> 99`、`source_blocked=0`。
- 20 篇写前/写后 QQ delivery、workflow 和公开时间逐项零漂移；已发 QQ 的文章没有重发。
- 总体 closure：
  `/opt/umanewsbot/runtime/horse_profile_completion/news_body_history/hrn-residual-20260725/hrn-residual-20260725-overall-closure.json`，
  SHA-256
  `ab0d93035afc593ccb5822323c2e27ffa1f48b53ec8c53030023cbcd21d33328`。
- 详细发布、失败/拒绝清单、5 组 receipt/rollback 和恢复点见
  `docs/changes/fix-hrn-residual-boundaries-and-jockey-club-term/release_report.md`。

# 2026-07-26 赛事生命周期阶段 A 已实现（代码审查中）

- worktree `.worktrees/automate-race-event-lifecycle`，分支 `codex/automate-race-event-lifecycle`，
  rebase 到 `origin/main@0aeb0ed7`。新增模型/迁移/服务/task/admin/管理命令，SQLite 56 项测试。
- 当前：代码审查进行中；未 commit / push / PR / 部署 / 生产写入。

## 2026-07-26 The Racing API schema v2 proof runner 已完成本地修复

- 分支 `codex/fix-tra-schema-v2-proof-runner` 从
  `origin/main@ef54a1836dd1fe1840f2d4765ebb73a1d130c645` 创建。
- 测试先行新增 4 项真实 RED：runner 不接受 region、命令无 `--region`、schema v2 仍读取
  v1 `registry["endpoints"]`。实现后新增 4 项、完整 proof 16 项，以及 proof /
  multiregion pipeline / racecard sync 合计 55 项均 GREEN。
- schema v2 现在要求显式 region，按该地区固定构建 today racecard、tomorrow racecard、
  results today 三条已审核 route，最多执行 registry 允许的 3 个请求；schema v1 行为保持兼容。
- 本轮只使用 fake transport，没有读取生产凭据或联网。Django check、migration drift、
  py_compile、`git diff --check` 通过；独立 reviewer 最终结论为 `APPROVED`，无开放
  P0/P1/P2。当前未 commit、push、PR、部署，真实联网仍等待独立用户授权。

## 2026-07-27 未来七天重点赛事官方赛前数据方案审核通过，待确认实现

- 冻结窗口为
  `[2026-07-27T01:50:01+08:00, 2026-08-03T01:50:01+08:00)`，对应 UTC
  `[2026-07-26T17:50:01Z, 2026-08-02T17:50:01Z)`。
- 生产只读盘点按 `P0/P1 或 featured`、published、not cancelled、approved series 枚举出
  19 场超集：英国 8、美国 10、法国 1；全部缺 `race_datetime`、`local_start_time` 和
  runner。
- 官方赛程可证明 19 场日期；但当前已审核 route 只覆盖赛果。英国/法国缺机器可用且获许可的
  official entries route，美国 Equibase 禁止未授权自动抓取/再发布，部分 8 月 1 日页面
  尚未发布。因此当前合规可 apply 为 0，跨地区无人值守每日任务结论为 NO-GO。
- 方案入口为 `docs/changes/fetch-upcoming-key-racecards/`。独立 reviewer 在同一会话关闭
  3 high、2 medium finding，最终 `VERDICT: APPROVED`。当前准确状态：
  `plan approved / implementation not authorized /
  production business writes 0 / scheduler unchanged`。

## 2026-07-27 P0 官方出马页面 URL 定时发现进入方案审核

- 用户把可先闭环的范围收窄为“只保存官方出马页面 URL”：上海时间每日 `06:30/18:30`
  枚举未来七天全部 `RaceEvent.priority=P0` 赛事，同一赛事仅保留最新 URL；尚未发布、身份缺失
  或 provider 受阻时显示“暂无”并保留原因。
- 计划生成宿主持久化的不可变 generation bundle，并由单一原子 `current` 指针提供固定
  `current/latest.md` 人工入口；不保存网页正文或出马内容，不写 RaceEvent/runner/result
  等业务表，也不公开文档。
- JRA、NAR、HKJC、英国、法国、美国均进入 adapter 注册表；当前无日本/香港赛事不作为删除
  适配能力的理由。自动 transport 仍逐 provider 受 host/path、robots/terms、contract 和请求
  预算约束，URL-only 不构成绕过第三方站点规则的依据。
- 新 change 入口：
  `docs/changes/schedule-p0-official-racecard-url-discovery/`。首次方案审核发现
  1 blocker、4 high、3 medium；两轮限定复审已全部关闭，最终
  `VERDICT: APPROVED`。当前准确状态：
  `plan approved / implementation confirmation pending /
  no code, network, production write, deployment or scheduler change`。

## 2026-07-27 P0 官方出马页面 URL 定时发现已完成本地实现，待代码审核

- 已实现严格 P0 七天窗口、有界 orphan、十 outcome 状态机、六 provider route registry、
  HTTPS/SSRF/预算/contract 门禁、锁内 latest-state merge、不可变 generation bundle、
  原子 `current` 指针、Celery 06:30/18:30 调度、脱敏运行日志和普通 worker 持久化 mount。
- 两个实现中发现的并发/审计缺口均先取得真实 RED 再修复：较晚失败运行不再清空较早确认 URL；
  保留 URL 时继续绑定原确认 provider/contract/event ID，并另存本轮 checked provider。
- 首次独立原生 code review session `019fa011-a171-7e50-bae6-249a06ea7ddd` 发现
  DNS 未拒绝 CGNAT 的 P1，以及两层吞 `SoftTimeLimitExceeded` 的 P2。两项均取得真实 RED
  并修复：DNS 只接受 `is_global=True`；service/task 显式重抛 soft timeout，日志保存失败不
  遮蔽原异常。限定复审确认两项已落实，并记录 3 个 P2 建议：编码 path traversal、保留 URL
  错误漏计、空 checked provider 错误归因；三项也已补 RED 并修复。该轮 fingerprint helper
  的摘要/hash 相同但 reviewer 捕获的 raw output 不同，故 fail closed，尚无批准基线。
- 主线程验证：聚焦 `40/40`、racecard/lifecycle `79/79`；Django check、迁移漂移、compile、
  Compose、registry SHA、旧规格流程 strict `37/37`、diff check 通过。完整 realtime
  `166` 项中 `157` 通过、`9` 项因既有 fixture 固定 2026-07-20 而当前为 2026-07-27，
  触发 claim expired/mismatch/rate-limited；无本 change 堆栈。
- tracked 六 provider route 仍全部
  `automation_allowed=false/robots_allowed=false`，总开关默认 false。当前没有真实联网、文档
  生产写入、业务数据库写入、部署或调度影响；只打开总开关也只会写“暂无”，不会抓取 URL。
- 当前准确状态：
  `implementation GREEN / native code review APPROVED / final documentation re-review pending /
  release not authorized`。

## 2026-07-27 P0 URL provider route 已补齐，等待最新代码审核

- 用户明确把离线 URL 构造、零正文 `HEAD` 与网页正文抓取分开；方案 reviewer 在同一会话关闭
  robots origin、请求预算和 proof 顺序 finding 后给出 `VERDICT: APPROVED`。
- tracked registry 当前只启用两条 HEAD route：BHA 日期索引
  `head_application_entry`，同批去重最多 1 次；Equibase
  `RaceCardIndex{track}{MMDDYY}USA-EQB.html` 精确 HEAD，最多 2 次且同 host 间隔至少 5 秒。
  France Galop 因真假路径均跳认证保持 blocked；JRA/HKJC 保留未来 contract，NAR 保持
  robots blocked。registry SHA-256 为
  `c96f042941d38682ec3c77eb57b80f90d7810d69829543b82d6dcfee09819876`。
- provider 增量测试先取得真实 RED（17 项中 `11 passed / 4 failed / 2 errors`），实现后
  provider `17/17`、完整 discovery `44/44`、racecard/lifecycle `79/79`、realtime 安全子集
  `25/25`；Django check、迁移漂移和 diff check 通过。
- reviewer 发现 task 日志仍漏记 `listing_reachable`，已用真实 RED（`KeyError`）修复，
  成功及固定失败日志 schema 均保留该计数。首次 proof 与 v2 现只作为不可变历史证据。
  修复后 v3 proof 在当前 6 场 P0 上只发 3 个 HEAD：BHA 1 次 200、Equibase DMR/CNL
  各 1 次 200，后两次间隔 7 秒，响应正文读取 0。结果为
  `confirmed racecard index=2 / official date listing=3 / 暂无=1`。业务数据库、
  `TaskExecutionLog` 和 `current` 写入均为 0。proof artifact SHA-256 为
  `7e4886a8ff9f02a9c39ef1e8e3e414692ad61528e184dbadb2d4b3c37b9f4b94`。v3 绑定联网前
  fingerprint `199785de6117c490b569b3cc0fa2d50ce9dbe10f05cb6d3dca0c950e5c736c21`，
  联网后仅新增 proof/manifest 与更新精确状态文档，同一 reviewer 已确认原两项 finding
  关闭、无直接 P0/P1 回归并给出 `APPROVED`。代码候选 parent/fingerprint/content hash
  分别为 `a59956b327157d29630fab1f1c98ba9c9cacfed0`、
  `1f665032d5bfc0d19b4f2e9885bd30f2718415de0cdee0c8a441e6b83e192959`、
  `1df171afd380238c205e72d123f8ec3e1bd3e9021267cc4d9dc117c02c119642`。
- reviewer 新报的 generation 目录名校验、完整 2xx 接受、认证 3xx 归类均为 P2，依限定
  复审规则记录为非阻塞后续建议；本次不扩展实现范围。当前只剩这次审核事实文档的同 reviewer
  限定复审与随后用户对精确版本的发布授权。
- 当前仍未 commit、push、PR、部署、创建生产宿主目录或启用定时任务；总功能开关保持默认
  false。审核事实文档复审通过后，仍必须重新取得针对最终 fingerprint 的发布授权。
## 2026-07-27 赛事赛果缺口来源调研完成

- 生产 `2026-07-08..2026-07-27` 的 `49` 个零赛果事件中有 `9` 个重复赛事已在另一历史实体
  上保存确认赛果；真实待采集为 `40` 场：日本 `6`、英国 `11`、法国 `4`、美国 `19`。
- 日本 6 场均已定位到 JRA replay 或 NAR `RaceMarkTable` 官方页；英国 11 场已在
  Sporting Life 日期结果页逐场命中；法国 4 场已定位 ZEturf 精确 `R/C` 页面；美国前
  12 场已从 TOBA 定位精确 Equibase chart，后 7 场已在 Sporting Life 日期页命中但 TOBA
  尚无 chart link。
- 官方确认继续按地区走 JRA/NAR、BHA、France Galop、Equibase。BHA/France Galop/
  Equibase 当前只能人工浏览确认；HRN 旧日期入口已重定向首页，不再作为本批可靠入口。
- `RaceEvent#924` Hackwood Stakes 另有 7 条未确认赛果，不计入 40 场，继续由 race-live
  owner 链补 official receipt。
- 逐场来源表见
  `旧规格流程/changes/recover-race-results-through-20260727/source_research_20260727.md`。
  本轮仅只读调研，没有生成候选、写生产库、发布或提升 official 状态。

## 2026-07-27 赛果缺口恢复已完成本地实现，待独立代码审核

- 隔离分支 `codex/recover-race-results-through-20260727` 基于
  `origin/main@a59956b327157d29630fab1f1c98ba9c9cacfed0`，已实现双层 inventory、
  结果专用受限编排、官方 receipt、participant 精确绑定、逐场原子投影、write-ahead
  rollback ledger、独立 verifier 和公开 canonical 去重；新增迁移 `0060`。
- 冻结守恒仍为
  `59 event rows = 40 missing + 9 duplicate-zero + 9 duplicate-confirmed + 1 provisional`，
  对应 `50 race groups`。event `924` 继续由既有 live owner 处理，不进入 historical apply。
- SQLite 恢复专属测试 `45/45` 通过（另有 2 个 PostgreSQL-only skip），PostgreSQL 16
  并发测试 `2/2` 通过；受影响回归除干净主线已存在的“暂定页面栏目标题”断言外无新增失败。
  完整候选 `3433` 项为 `24 failures / 39 errors / 68 skipped`，同环境干净主线 `3393`
  项为 `25 failures / 39 errors / 66 skipped`；候选无新增红项，并修复主线一个日历查询数失败。
- Django check、迁移漂移、旧规格流程 `38/38` strict/all、三份 Compose config、`py_compile`
  和 `git diff --check` 均通过。首次独立原生只读审核提出 6 项 actionable finding；
  当前已补齐完整写前身份 CAS、来源合同实时重验、ledger 故障回滚、verifier 深校验、
  canonical link apply 和已批准 participant fallback，等待同一 reviewer 限定复审。
  尚未 commit、push、PR、部署、联网收集候选或写生产数据。
## 2026-07-27 赛事生命周期阶段 A 关闭态生产事实补录

- PR `#25` 已部署到生产 revision
  `ef54a1836dd1fe1840f2d4765ebb73a1d130c645`，migration `stable.0058/0059` 已应用。
- 生产显式保持 `RACE_EVENT_LIFECYCLE_ENABLED=false`、
  `RACE_EVENT_LIFECYCLE_MODE=off`；没有 lifecycle control、状态推进、provider 调用或
  赛事/新闻业务写入。
- 过去 7 天至未来 14 天的 35 场重点赛事只读 dry-run 为
  `7 transition / 28 noop / 0 error`，前后业务摘要和四类 lifecycle 表计数不变。
- 35 场全部缺少 `race_datetime`；本次只覆盖英国、法国、美国纽约/洛杉矶，没有日本、香港
  观察样本，不能据此启用 shadow/enforce。
- 完整恢复点、SHA、迁移竞态和 dry-run 证据见
  `docs/changes/automate-race-event-lifecycle/production_release_20260726.md`。
- PR `#27` 已把 TRA schema v2 proof runner 修复合入当前
  `origin/main@a59956b327157d29630fab1f1c98ba9c9cacfed0`；合入不等于新的联网或 provider
  启用授权。

## 2026-07-27 阶段 B0.1 赛后内部参考源进入方案审核准备

- 用户确认保留并使用 Sporting Life、ZEturf、Horse Racing Nation 三个现有解析器；
  新增抓取结果只供站长内部参考，不公开。
- 三源固定为 `internal_reference`，没有 field apply、result authority 或 publication 能力；
  不进入 `RaceEventDataCandidate` apply、race-live projection、新闻、QQ、搜索、sitemap 或
  公开 API。
- 现有历史赛事 importer 行为不追溯改变。阶段 B0.1 建议新增独立 collection
  run/payload/receipt、只读 admin、manifest-bound collect/离线 record/report 命令。
- 首版只复用三个 parser 的 `finished` 赛后入口，不实现赛前 racecard，也不注册
  Celery/Beat/task/queue；7 天观察由逐日 one-shot 组成。
- 当前只完成文档，尚未写测试、代码、迁移或配置，也未执行联网、生产 record、调度启用、
  commit、push、PR 或部署。
- 规格入口：
  `docs/changes/automate-race-event-lifecycle/internal_reference_sources.md`；
  实现交接：
  `docs/changes/automate-race-event-lifecycle/phase_b_reference_implementation_handoff.md`。
- 独立方案 reviewer 前两轮 `REVISE` 后，同一会话第三轮已给出 `APPROVED`，无开放
  P0/P1/P2。当前停在实现确认门禁；未授权写测试、代码、迁移或配置。

## 2026-07-27 阶段 B0.1 已通过第十七轮 review，最新 main 集成待复审

- 用户已明确授权实现阶段 B0.1。隔离 worktree 中已按测试先行完成内部
  `RaceReferenceCollectionRun / RaceReferencePayload / RaceReferenceReceipt`、additive
  migration、只读 Admin、三个 parse-only parser、安全 HTTP 门禁及
  manifest build / collect / offline record / report 命令。
- 首轮真实 RED 来自模型、服务、parser、命令和安全 HTTP 合同尚不存在；后补的 4 项
  append-only 实例 `save/delete` 测试也因预期 `ValidationError` 未抛出而真实 RED，完成实例级
  不可变门禁后转为 GREEN。
- B0.1 首轮 SQLite 聚焦矩阵为 `41/41 GREEN`。首轮独立代码 review 的 4 项 P2 新增真实
  RED 并修复后为 `45/45`；第二轮限定复审的另 4 项 P2 同样先补真实 RED 后修复，当前为
  `49/49 GREEN`；第三轮新增 1 项 P1 与 3 项 P2 均先补真实 RED 后修复，当前为
  `53/53 GREEN`；第四轮剩余 2 项 P2 继续先补真实 RED 后修复，当前为
  `60/60 GREEN`；第五轮新增 4 项 P2 均先补真实 RED 后修复，当前为
  `64/64 GREEN`；第六轮新增 5 项 P2 均先补真实 RED 后修复，当前为
  `69/69 GREEN`；第七轮新增 3 项 P2 均先补真实 RED 后修复，当前为
  `78/78 GREEN`；第八轮唯一 P2 对应 3 项真实 RED，修复后当前为
  `80/80 GREEN`；第九轮 1 项 P1 与 3 项 P2 对应 4 项真实 RED，修复后当前为
  `82/82 GREEN`；第十轮唯一 P2 对应 2 项真实 RED，修复后当前为
  `84/84 GREEN`；第十一轮 2 项 P2 对应 3 项真实 RED，修复后当前为
  `87/87 GREEN`；第十二轮 2 项 P2 对应反例 RED，修复后当前为
  `89/89 GREEN`；第十三轮 3 项 P2 对应 3 项真实 RED，修复后当前为
  `93/93 GREEN`；第十四轮 2 项 P2 对应时间窗口与重复分组 RED，修复后当前为
  `96/96 GREEN`；第十五轮 2 项 P2 对应重签 artifact 真实 RED，修复后当前为
  `98/98 GREEN`；第十六轮唯一 P2 对应 6 项真实 RED 和 5 项实例/`SET_NULL` 正例，
  修复后当前为 `104/104 GREEN`。临时本机 PostgreSQL 16 容器中的 reference 测试
  `3/3 GREEN`，
  lifecycle PostgreSQL 测试 `5/5 GREEN`。
  临时容器已删除；这些操作不是
  生产迁移或生产数据写入。
- 三源历史 parser/direct URL/安全 HTTP 聚焦回归为
  `82/82 GREEN / 4 conditional skips`。lifecycle/race-live/calendar 组合为
  `140/141`，唯一红项是暂定页面仍含“正式赛果”栏目标题；新闻门禁组合为 `140/141`，唯一红项
  是错误消息 wording mismatch；两项均已在纯 `origin/main` 同环境复现。
- historical batch 扩展矩阵 `123` 项中有 `18 errors / 7 skips`；代表性错误同样在纯
  `origin/main` 复现，根因为 macOS `/var` 与 `/private/var` 路径规范化差异。本阶段不把这些
  主线既有红项误记为 B0.1 回归，也不宣称扩展矩阵全绿。
- Django check、migration drift、变更文件 `py_compile`、`git diff --check` 已通过；
  workflow contract 为 fingerprint `24/24`、transition `10/10`、workflow `26/26`。
  Compose config 因隔离 worktree 不含 `.env` 未成功执行；代码差异不含 Compose、Celery
  task/route、Beat 或 worker 变更。
- 独立代码 reviewer session
  `019fa021-3552-7f23-a17f-2cae48ccc4bb` 对原 fingerprint
  `f2463878ffa4011aa91cf5b3cd7c5fe817b66157691e9eaf6e309640623695cd`
  返回 `VERDICT: REVISE`，无 P0/P1，共 4 项 P2：collect 误绑定、ZEturf 未证明 `R/C`、
  `source_only` 可能 `KeyError`、report 缺少多日指标。四项均先补真实 RED，再由原实现
  subagent 修复；修复后 SQLite `45/45`、历史 parser `52 OK / 4 conditional skips`、
  PostgreSQL concurrency `2/2`，Django、migration drift 与 diff 检查通过。
- 同一 reviewer 第二轮限定复审的 inner session 为
  `019fa02f-1976-7d10-b177-a18a0216591e`，fingerprint 为
  `561cdbf66dd3a26c702366bd113d2aed197dc98446eec34856d2c2c1350e9200`，
  结论仍为 `VERDICT: REVISE`，共 4 项直接 P2：record 未独立重验 racecourse；report
  `event-id` 错误依赖 nullable FK；report 日期只按 run 范围；默认开发 Compose bind mount
  遮住 `runtime` parser。四项均先补真实 RED 后修复：record 与 collect 共用 racecourse
  helper 且 record 独立重验；report 使用 frozen snapshot `event_id/local_date`；parser 单一
  实现迁至 `server/stable`，compat wrapper 和历史 CLI 共同复用。
- 第二轮修复后 SQLite `49/49`、历史 parser `52 OK / 4 conditional skips`、PostgreSQL
  concurrency `2/2`，Django、migration drift、workflow contract 与 diff 检查通过。
- 同一 reviewer 第三轮 inner session 为
  `019fa044-4483-72e1-b836-53e6900df34c`，fingerprint 为
  `22675d91cb097737bb678bd547874cce1ae1d7c481f416710911740a24981f06`。
  本轮确认第二轮 4 项 P2 全部关闭，但结论仍为 `VERDICT: REVISE`：新发现 1 项 P1，即
  safe HTTP 全局强制 HTML MIME 会破坏现有 PDF/JSON/XML；另有 3 项 P2，分别为
  ZEturf `NP`、HRN 国家后缀、Sporting Life 下划线状态未统一规范化。
- 四项均先补真实 RED 后修复：MIME 合同改为 opt-in，internal reference collect 显式要求
  HTML/XHTML；三个 parser 统一规范化并保留 raw 证据。修复后 SQLite `53/53`、历史
  HTTP/parser `80 OK / 4 conditional skips`、PostgreSQL concurrency `2/2`，Django、
  migration drift、workflow contract 与 diff 检查通过。
- 同一 reviewer 第四轮 inner session 为
  `019fa051-bcf9-7e71-bd04-f11090fe8112`，fingerprint 为
  `a3f862fd93041831250fe855e383ee911843f6eb940433604c5a08b1f835b63b`。
  本轮对第三轮 4 项 finding 关闭 3 项，Sporting Life description 仅部分关闭，结论仍为
  `VERDICT: REVISE`；剩余 2 项 P2 是 `ride_description` 下划线值和 manifest parser
  identity 未绑定实际模块。
- 两项均先补真实 RED 后修复：description 统一规范化；service 冻结
  `source -> stable module / parser name / reference-v1`，validate/record 漂移时
  fail closed，build/collect 在创建目录或联网前实际 import 并核对模块常量，合法 fixtures
  同步。修复后 SQLite `60/60`、历史 HTTP/parser `80 OK / 4 conditional skips`、
  PostgreSQL concurrency `2/2`，Django、migration drift、workflow contract 与 diff 检查通过。
- 同一 reviewer 第五轮 inner session 为
  `019fa062-e917-76e2-aacd-e807fb0f1f9b`，fingerprint 为
  `50b50866f19853534daad66c9a2cd18650d4d74cafbfebec106b09c8b36c274d`。
  本轮确认第四轮 2 项 P2 全部关闭，但仍以 4 项新 P2 返回 `VERDICT: REVISE`：只有
  transport failure 应计入 circuit；parse 失败没有保存 raw；HRN 可能跨 race block；
  timeout 未唯一固定为 15 秒。
- 四项均先补真实 RED 后修复：network/parse 分段并只分类 transport failure；fetch 后、
  parse 前保存 raw 与 responses ledger，失败追加 `parse_error`；HRN 严格限定当前 heading
  block；timeout 唯一为 15 秒。修复后 SQLite `64/64`、历史 HTTP/parser
  `80 OK / 4 conditional skips`、PostgreSQL concurrency `2/2`，Django、migration drift、
  workflow contract 与 diff 检查通过。
- 同一 reviewer 第六轮 inner session 为
  `019fa071-ca82-7b80-9af1-d4725efb6c`，fingerprint 为
  `41307729d9896c7fbd721b2e8864177990a7d190d3c25011b53a0bf284db0d87`。
  本轮确认第五轮 4 项 P2 全部关闭，但新增 5 项 P2，仍为 `VERDICT: REVISE`：
  `request_count` 漏失败请求、HRN alias 过宽/错误、ZEturf `FR + NP`、报告缺重复指标，以及
  `event-id` 过滤后的 run 计数混入无关运行。
- 五项均先补真实 RED 后修复：ledger phase 与 `request_issued` 严格绑定；HRN 显式双向
  alias 且不做 substring；ZEturf 迭代规范化后缀；report 增加 duplicate runs/observations，
  并按过滤结果 distinct run。修复后 SQLite `69/69`、历史 HTTP/parser
  `80 OK / 4 conditional skips`、PostgreSQL concurrency `2/2`，Django、migration drift、
  workflow contract 与 diff 检查通过。
- 同一 reviewer 第七轮 inner session 为
  `019fa07f-90e2-7f60-b08d-125e01d55ba3`，fingerprint 为
  `6dd68951fe0ff90847c74f3873fb0539eec8226441473c294e7c444591ebba1a`。
  本轮确认第六轮 5 项 P2 全部关闭，但新增 3 项 P2，仍为 `VERDICT: REVISE`：不完整
  ledger 可 record、unknown 被误算 complete、receipt `SET_NULL` 与 matched event 约束冲突。
- 三项均先补真实 RED 后修复：ledger 精确覆盖 manifest 并强绑定 source/final/response；
  unknown 计入 incomplete；event 删除后历史 matched receipt 保留 matched snapshot，数据库
  约束要求 snapshot，而 service 新建 matched receipt 仍必须绑定 event。修复后 SQLite
  `78/78`、历史 HTTP/parser `80 OK / 4 conditional skips`、PostgreSQL concurrency +
  `SET_NULL` `3/3`，Django、migration drift、workflow contract 与 diff 检查通过。
- 同一 reviewer 第八轮 review session 为
  `019fa08e-e782-7d31-9cbc-921bb3b4efbd`；交接只提供 review fingerprint 前缀
  `d98034f…`，不得据此前缀虚构完整 digest。本轮唯一 P2 是 collect 依赖 runtime safe HTTP
  实现，会被默认开发 `./server` bind mount 遮蔽。
- 该 P2 先取得 3 项真实 RED 后修复：`server/stable/race_event_safe_http.py` 成为唯一实现，
  runtime 路径只保留兼容 wrapper，collect 直接 import stable。主线程复验 B0.1 `80/80`、
  历史 HTTP/parser `81/81`（另 4 项 conditional skip），Django check、migration drift、
  `py_compile`、workflow contract 与 diff 检查通过。
- 一次把整仓错误挂到 app 容器导致的验证失败属于验证环境/挂载方式误用，不是产品失败或
  B0.1 回归。Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称已通过。
- 同一 reviewer 第九轮 session 为
  `019fa09e-88c5-7180-a678-39874ff6e045`，fingerprint 为
  `84e8f4fafc4db634911c9aa18f6f473bdba12078e2957072a660434505c5ce6f`，
  结论为 `VERDICT: REVISE`。1 项 P1 是 runtime CLI `sys.path`，3 项 P2 是 event/raw
  逐场绑定、`error_summary` 和无 receipt 失败 run 报告。
- 四项均先补真实 RED 后修复。主线程复验 B0.1 `82/82`、历史 HTTP/parser `82/82`
  （另 4 项 conditional skip），项目 venv 真实 runtime CLI `--help` 退出码为 `0`；
  Django、migration drift、`py_compile`、workflow contract 与 diff 检查通过。系统 Python
  因缺 `bs4` 失败属于环境误用，不是产品失败。
- 同一 reviewer 第十轮 session 为
  `019fa0ad-c024-7a21-8ebb-31b19df760ab`，fingerprint 为
  `abbc00318318447abb86627ffe29a076012f8eceee4aa1b8d3f6c0c157dc4b20`，
  结论仍为 `VERDICT: REVISE`。唯一 P2 是 reference observations 必须与 ledger 中
  `outcome=parsed` 的 event 精确一一对应，`parse_error` event 必须零 observation。
- 该 finding 先取得 2 项真实 RED 后最小修复；既有正向 fixture 同步改为合法
  `parsed + observation`，跨 run replay 继续验证。主线程复验 B0.1 `84/84`、历史
  HTTP/parser `82/82`（另 4 项 conditional skip）；Django check、migration drift、
  `py_compile`、workflow contract 与 diff 检查通过。
- 同一 reviewer 第十一轮 session 为
  `019fa0b9-b2c8-77d0-9473-7caff58d87eb`，fingerprint 为
  `ef778594f1d471a239432c6bd65054dcb2491fb918c46a660ea321436a827b0d`，
  结论仍为 `VERDICT: REVISE`。2 项 P2 是共享 safe HTTP 默认 `4MiB / 2 跳` 破坏
  legacy 大 PDF/redirect，以及跨日 run 的单日报告错误误归日期。
- 测试调查在纯 `origin/main` 确认旧 transport 没有 body cap，且 `urllib` 默认处理
  redirect；3 项真实 RED 后，legacy 默认不再自定义 body cap/redirect 上限，internal
  reference collect 仍显式使用 `4MiB / 2 跳`；report 改按 event/date 归属，并单列
  `unattributed_errors`。主线程复验 B0.1 `87/87`、历史 HTTP/parser `82/82`
  （另 4 项 conditional skip）；Django check、migration drift、`py_compile`、workflow
  contract 与 diff 检查通过。
- 同一 reviewer 第十二轮 session 为
  `019fa0c7-7f55-7960-9f5d-5b81ba13437c`，fingerprint 为
  `6b0246db6647786e351492822d86f70a8dd15dbb272a19a6a34a324f15ca7b3b`，
  结论仍为 `VERDICT: REVISE`。2 项 P2 是 matched 未核对来源赛事名，以及单日无 receipt
  错误未回退到 run 唯一日期。
- 测试调查确认复用 race-live exact normalized alias 合同并冻结进 manifest；反例 RED 后
  新增公开 normalization helper，manifest 冻结 `normalized_accepted_race_names` 并纳入
  snapshot SHA，record 要求 exact membership；单日 run 增加唯一日期 fallback，过时
  fixture 按新合同修正。主线程复验 B0.1 `89/89`、race-live `23/23`、历史 HTTP/parser
  `82/82`（另 4 项 conditional skip）；真实 PostgreSQL 并发/锁 `2/2`、`SET_NULL`
  `1/1`，临时容器已删除；Django check、migration drift、`py_compile`、workflow contract
  与 diff 检查通过。
- 同一 reviewer 第十三轮 session 为
  `019fa0db-0a80-72c0-a6ad-bb1142432a83`，fingerprint 为
  `384ef97820f9e6d9c0c8f6df7190f1fb546746570aff018379b742a41e3b0c00`，
  结论仍为 `VERDICT: REVISE`。3 项 P2 是 collect 异名未降为 `source_only`、多日错误
  detail 缺 `local_date`、`--event-id` 漏掉无 receipt 但匹配错误明细的 run。
- 三项均先取得真实 RED。collect 现按冻结赛事名 exact membership 分类；ledger 每个 event
  冻结 `local_date` 且 record 核验；event filter 按错误 detail 纳入匹配 run 并隔离其他
  错误；6 个旧 fixture 已补新合同必需字段。主线程复验 B0.1 `93/93`、race-live
  `23/23`、历史 HTTP/parser `82/82`（另 4 项 conditional skip）、真实 PostgreSQL
  `3/3` 且临时容器已删除；Django check、migration drift、`py_compile`、workflow contract
  与 diff 检查通过。
- 同一 reviewer 第十四轮 session 为
  `019fa0ea-65a3-7383-b208-c0f571e7b98a`，fingerprint 为
  `18ac8b531f2d123b132fbe45104999feeea814315087ac6e4cdc0d043a4baeae`，
  结论仍为 `VERDICT: REVISE`。2 项 P2 是 record 丢失 artifact 采集窗口，以及无 receipt
  失败 run 未计入 `duplicate_runs`。
- 测试锁定 started 为最早 ledger `fetched_at`、finished 为 artifact `completed_at`，逆序、
  naive datetime 和显著未来时间必须拒绝；同 event/day 失败 run 重复分组也先取得 RED。
  修复后允许 5 分钟 clock skew，原子保存签名窗口；report 将 receipt 与 error details
  统一纳入 run membership。主线程复验 B0.1 `96/96`、race-live `23/23`、历史
  HTTP/parser `82/82`（另 4 项 conditional skip）、真实 PostgreSQL `3/3` 且临时容器
  已删除；Django check、migration drift、`py_compile`、workflow contract 与 diff 检查通过。
- 同一 reviewer 第十五轮 session 为
  `019fa0fa-b908-7d43-9f7e-807bf132a9a3`，fingerprint 为
  `59ffcb96972cef74dcff8df87e5a9d1b0f3923ecf59f5f5b594e58e48594424f`，
  结论仍为 `VERDICT: REVISE`。2 项 P2 是仅校验最早 ledger 时间，以及 observation
  provenance 的 `fetched_at/final_url` 未逐 event 绑定。
- 重签 artifact 反例先取得真实 RED。修复后要求 `max(ledger fetched_at) <=
  artifact.completed_at`，并要求每个 observation 的 `source_url/final_url/fetched_at`
  及 raw/ref/hash 与 manifest、parse ledger、response 逐 event 精确一致。主线程复验
  B0.1 `98/98`、race-live `23/23`、历史 HTTP/parser `82/82`
  （另 4 项 conditional skip）、真实 PostgreSQL `3/3` 且临时容器已删除；Django check、
  migration drift、`py_compile`、workflow contract 与 diff 检查通过。
- 同一 reviewer 第十六轮 session 为
  `019fa106-3b52-7a02-b756-31f718ffe4d0`，fingerprint 为
  `571664940ea3e77b60368fe4ddf72292404060fedfb27f281d6b7f7d1f815cc7`，
  结论仍为 `VERDICT: REVISE`。唯一 P2 是 Payload/Receipt 的
  `QuerySet.update/bulk_update/delete` 可绕过 append-only。
- 6 项真实 RED 与 5 项实例/`SET_NULL` 正例锁定边界后，新增专用 QuerySet/Manager；
  Payload 全部拒绝，Receipt 仅允许 Collector 精确执行 `event=None/event_id=None`，
  其他批量变更全部拒绝；无需迁移。主线程复验 B0.1 `104/104`、race-live `23/23`、
  历史 HTTP/parser `82/82`（另 4 项 conditional skip）、真实 PostgreSQL `3/3` 且临时
  容器已删除；Django check、migration drift、`py_compile`、workflow contract 与 diff 检查通过。
- 同一 reviewer 第十七轮 session
  `019fa113-9c02-7c63-b48d-466c40d323cf` 对 fingerprint
  `5095a06e326a9cef470f4ef5d2111c87e8daa77a45fbc9507a27b024369edea7`
  给出 `VERDICT: APPROVED`，P0/P1/P2/P3 均为 0，审前审后 fingerprint 完全一致。
- 用户随后授权 fetch 最新 main、commit、push 和 Draft PR。fetch 发现 `origin/main` 从
  `e7dc1b20` 前进 14 个提交到 `6ac08e40`，因此旧批准父提交失效，未直接 staging。
  候选已通过可恢复 stash 迁移到 `origin/main@6ac08e40`；5 份追加式状态文档保留双方记录，
  Sporting Life/ZEturf 历史 CLI 同时保留上游 recovery 能力和 B0.1 单一 stable parser。
  stash 仍保留为恢复点。
- 最新 main 集成后，B0.1 `104/104`、race-live `23/23`、历史 HTTP/parser
  `82/82`（另 4 项 conditional skip）、真实 PostgreSQL `3/3` 通过，临时容器已删除；
  Django check、migration drift、`py_compile`、workflow contract 与 diff 检查通过。
  上游新增的 recovery/P0 URL/HTTP budget 组合 `87` 项出现 `14` 个 macOS
  `/var` -> `/private/var` 安全路径错误；同样的 `14` 个错误已在纯
  `origin/main@6ac08e40` 临时 worktree 精确复现，不归因于 B0.1。
- 当前仍未执行 provider 联网、commit、push、PR、部署、生产迁移或生产写入；也没有改变
  lifecycle 的生产 `false/off`。由于 latest-main 集成改变了候选内容，下一门禁是复用同一
  reviewer 会话复审新的完整 fingerprint；通过后仍需针对新 fingerprint 重新取得
  commit/push/Draft PR 授权。Compose 仍未验证。

# 2026-07-27 赛果恢复候选缺口已补齐，待 source map v2 发布

- 关闭态生产 `prepare-20260727T073643Z` 使用 `73/75` 请求取得 27 场完整连续数字名次；
  常驻网络/调度开关保持关闭，目标 `RaceEventResult=0`、event 426 结果为 0、目标候选仍为
  32，未执行 audit/dry-run/apply。
- 独立补缺批次 `gap-prepare-20260727T075310Z` 为 event 185 取得 NAR 官方 1–14 名，
  并为 12 场美国赛事从 Sporting Life 取得 82 条完整数字名次；每场非退赛马数与结果数
  相等。合并审阅层达到 `40 candidates / 319 results / 40 full numeric order`。
- TOBA 交互式浏览器核验取得 12 个精确 Equibase chart 入口、field 与 winner，但
  Equibase 完整 chart 仍只允许人工核验；当前合并文件为 review-only，不构成 official
  confirmation 或生产写入授权。
- 最新主线分支 `codex/fix-race-result-gap-source-map` 已将 candidate source map 升至
  `2026-07-27-gap-v2`：美国 19 场统一由 Sporting Life 生成候选，TOBA 只保留 discovery；
  NAR recovery 会受控检查同目录后发布的 `racecard.html`；法国四场使用已核验的精确
  recovery-only URL 并在下载后重验身份，将预计法国请求从 35 降至 4。恢复聚焦测试
  `39/39`、相关 adapter 回归 `48 passed / 4 skipped`。
- 该分支已重基到 `origin/main@db96b13b`，提交并推送为 `787d6a1e`，草稿 PR `#36`
  已创建且 GitHub 判定可合并。重基后恢复聚焦测试 `39/39`，历史 adapter 与 B0.1
  相关回归 `192 passed / 4 skipped`，其余静态门禁通过。
- PR `#36` 尚未合并，因此未把未合并分支部署到生产；生产仍未部署 gap-v2，也未重跑正式
  bounded prepare、写入赛果或改变任何关闭态开关。

# 2026-07-27 最近赛事赛果定时审核实现已完成，待独立代码审核

- 已实现默认关闭的每日 `06:30/18:30 Asia/Shanghai` 审核链路：最近 72 小时新目标与
  14 天 pending 并集、最多 28 个漏跑 slot 合并为一次 prepare、canonical route 合同、
  不可变审核包和 durable 邮件 intent。
- migration `0062_add_scheduled_race_result_review` 新增 run、pending、delivery、approval
  四张治理表。人工采纳保留原来源 authority，显示“已人工审核赛果”，不伪装 official receipt。
- apply 默认 dry-run；完整 bundle SHA、逐 event digest、reviewer 与双确认齐备后才逐场事务写入，
  并提供独立 verify。
- GREEN 与相邻回归 `94/94`；Django check、迁移漂移、编译、wrapper、三份 Compose config
  和 diff 检查通过。
- 未联网、未发邮件、未执行生产迁移/业务写、未 commit/push/PR/部署；新开关保持 false。
  下一门禁是未参与实现者的完整只读代码审核。

# 2026-07-27 定时赛果审核首次代码 review 四项 P1 已修复

- 首次独立 review session `019fa425-c6fc-7e72-9483-5afa281fcfeb` 返回 `REVISE`：
  verify 写前/写后语义、同 slot lease、apply 锁内 baseline、人工审核公开标签共 4 项 P1。
- 四项均先取得真实 RED（聚焦 16 项中 `2 failures + 2 errors`），修复后聚焦 `17/17`；
  recovery inventory/projection/public pages 与 lifecycle 相邻组合 `107/107`。
- 真实 PostgreSQL `2/2` 证明同 slot 并发只进入一次 prepare，以及 event -> results 锁序会等待
  并识别并发已提交的 baseline 漂移；临时容器和测试库已删除。
- exact apply 重放现返回 `already_applied`，独立 verify 只核对写后 approval/result/digest/
  authority；claim token CAS 阻止失去 lease 的旧 worker 写终态；公开详情只有当前结果 digest
  对应不可变 human approval 时显示“已人工审核赛果”。
- 未联网、未部署、未执行生产迁移/写入、未 commit/push。下一门禁是复用同一 reviewer session
  做四项 finding 的限定复审。

# 2026-07-27 定时赛果审核命令退出码两项 P1 已修复

- 同一 reviewer 限定复审确认原四项 P1 已关闭，但新增两项直接 P1：空 `--verify` scope
  错误退出 0，以及 apply summary 含 blocked、缺失或 unexpected event 时错误退出 0。
- 两项命令测试先取得真实 RED：`2` 项产生 `4 failures`；修复后 `2/2`，完整聚焦
  `19/19`，与 recovery/public pages/lifecycle 直接相邻组合 `109/109`。
- verify 现必须提供至少一个 `--approve`。apply 会先保留逐 event JSON summary，再校验
  returned event scope 精确守恒、状态只能是 `applied/already_applied` 且 unexpected 为空；
  否则抛 `CommandError` 令进程非零退出。
- Django check、迁移漂移、编译与 diff 检查通过。仍未联网、未生产写、未提交或部署；
  下一门禁是同一 reviewer 再次限定复审。

# 2026-07-28 单一 migration owner 进入方案审核门禁

- 已从最新 `origin/main@7385f59ab87bcce5193f3313ecca6809b165ad89` 创建隔离分支
  `codex/fix-single-migration-owner`，未修改主工作区。
- 只读盘点确认双执行者同时存在于标准/低成本 deploy、两条 rollback 与
  `deploy/docker/start-web.sh`：`compose up web` 后的显式 `exec migrate` 可与 web 主进程
  的自动 migrate 并发。
- 已建立 `docs/changes/fix-single-migration-owner/` 的 spec、design、test cases、tasks、
  rollout 和自包含 `HANDOFF.md`。推荐把 migration/collectstatic 收敛到单个 Compose one-shot
  release task；web 常驻入口不再迁移，并增加 host-local 部署锁和 web healthy 硬门禁。
- 当前只改文档，未修改测试、部署脚本、Compose、应用代码或 migration；未连接生产，未
  commit/push/PR/部署。
- 独立方案 reviewer `/root/single_migration_plan_review` 首轮发现 4 项 P1：race-live 未停、
  wrapper 绕锁、pre-contract rollback 不可用和 greenfield 语义错误；限定复审再发现 manual
  release 运行态门禁与权威 runbook 两项直接 P1。全部只通过文档修订关闭，同一 reviewer
  第三轮给出 `APPROVED`，开放 P0/P1 为 0。
- 下一门禁是用户明确“确认实现/开始实现/继续实现”；此前禁止写测试或部署脚本、启动实现
  subagent、commit/push/PR、部署、迁移或生产写入。

# 2026-07-29 单一 migration owner 实现落地（待复审）

- `fix-single-migration-owner` 已在隔离分支完成 deploy/ 实现：唯一容器内 release task
  （`deploy/docker/run-release-tasks.sh`）、受保护宿主 wrapper、host-local 部署锁、
  web 健康等待、共享 release 编排、手工恢复入口、pre-contract 回滚兼容桥与
  `release_contract_v1` marker；`start-web.sh` 与四条 deploy/rollback 脚本中的重复
  migrate/collectstatic 已全部移除，drain 脚本支持 `EXPECTED_CELERY_WORKERS` 完整
  快照核对。
- 首轮实现后协调复审指出两条 rollback 丢失 historical runner preflight，已按裁决在
  target ref 校验（rev-parse + release_contract_v1 marker）通过之后、`git checkout`
  之前恢复调用，与 deploy 语义一致、无 `--initial-install` 分支。
- 实现 review 六项 findings 已修复：`compose ps -q` 探测失败在编排/手工/桥三处一律
  fail closed（不再当作 not-running）；deploy 锁 acquire 移到 historical preflight
  之前且 acquire 记录 COMPOSE_FILE；manual release 的 restarting 检测改用
  `State.Status` 第三列；drain 的 expected node 改为精确匹配（全名或 `@` 后缀）；
  pre-contract 桥在停服前用 `docker image inspect` 自检冻结镜像。rollback checkout
  替换执行中脚本自身经裁决属 pre-existing 模式，记录为后续建议。
- 第 3 轮 Codex 原生 review（REVISE）七项 findings 已修复：race_live 冻结状态持久化到
  `${DEPLOYMENT_LOCK_DIR}.race-live-state` 跨重试复用、成功后删除；bridge schema 门禁
  必须显式 true/false；rollback checkout 前逐一 `git cat-file -e` 全部 8 个 v1 路径并
  绑定不可变 OID；三处 probe 的 running 字段精确 true/false 校验；文档顺序与状态同步。
- 第 4 轮复审（REVISE）findings 已修复：状态文件只决定恢复意图、每次尝试仍重新 probe
  当前态决定停止与 drain（frozen=not-running+current=running 必须在 release/tag 前停
  race_live 且当前 node 进 drain）；v1 helper 扩到 9 个路径；`TARGET_OID` 必须单行
  40 位小写 hex，畸形输出在任何 cat-file/preflight/checkout 前非零；drain 内嵌代码
  首行承载 expected nodes 使调用日志可见；design/runbook/guide 文档同步为 OID 语义。
- 聚焦套件 `stable.test_single_migration_owner` 94/96：14 项 RED 全绿，剩 2 项为测试
  文件张力（T11 两个成功用例未给 fake rev-parse 准备 OID 输出，与 malformed-empty 子例
  可观察输入相同但期望相反；需测试侧补 `git-rev-parse-output`，同第 3 轮 T12 修法）。
  相邻 historical runner 合同测试 `11/11` 通过；`sh -n deploy/*.sh deploy/docker/*.sh`
  与 `git diff --check` 通过。
- 未 commit/push/PR，未部署、未迁移、未连接生产；下一门禁是测试侧修正后同一 reviewer
  第 5 轮复审并冻结新指纹。

# 2026-07-30 单一 migration owner 原地 re-baseline 至 6d073dc0

- worktree 已原地迁移：`origin/main@7385f59` -> `origin/main@6d073dc07cb29201bbc922255923820c872a0467`，
  分三跳完成：第一跳至 `7cd144ab`（main 增量 65 文件，含 race-calendar 日期窗口、race-news
  质量治理、harden-celery-p0-admission）；第二跳至 `be1c89bf`（PR #47
  fix-p0-queue-snapshot-output，p0 脚本与其合同测试及 3 份状态文档）；第三跳至 `6d073dc0`
  （PR #48，纯文档增量：p0 release_report 与三份状态文档，无代码变化，三方合并零冲突）。
- 4 份重叠文档重叠区由主线程三方合并；本 change 内容仅追加。
- main 新增 `deploy/deploy_race_live_p0_closed.sh` 含 collectstatic，经用户批准登记为 T01/T02
  显式例外；最终基线上前提复核仍成立（1 次 collectstatic、0 migrate、2 次
  `verify_migration_plan_zero` 调用）；单一 migration owner 不变量不受影响。
- 聚焦套件终值 97 用例；文档侧 spec/design/runbook/REVIEW_HANDOFF 已同步基线与例外决策。
- 旧冻结指纹全部失效；待同一 reviewer 在新基线上做第 5 轮复审后冻结新指纹，再等待发布授权。

# 2026-07-30 单一 migration owner 第 5 轮 findings 修复完成

- 第 5 轮复审（REVISE）三组 findings 已修复：p0 closed-admission 脚本接入共享部署锁
  （action 扩入 p0-closed-admission/resume-release）；新增 `deploy/resume_stopped_release.sh`
  受审恢复入口；race-live 冻结意图改六字段 mode-600 绑定并经共享 `deploy/race_live_state.sh`
  可信校验（编排/桥 fail closed、resume 告警跳过 race-live）。
- 聚焦套件 `113/113`、p0 合同套件 `35/35`、相邻 historical runner `11/11` 全绿；
  `sh -n deploy/*.sh deploy/docker/*.sh` 与 `git diff --check` 通过。
- 未 commit/push/PR，未部署、未迁移、未连接生产；待同一 reviewer 第 5 轮复审确认后冻结新指纹。

# 2026-07-30 单一 migration owner 第 6 轮修复完成

- 第 6 轮复审（REVISE）P1 已修复：resume 对可信 race-live 意图文件改为全链路成功后消费
  删除（running/not-running 一致；不可信保留人工核对；中途失败保留）。四项 P2 建议
  （属主检查 fail open、六字段唯一完整、RELEASE_ACTION 必填化、resume 中间态）仅记录于
  REVIEW_HANDOFF 后续建议节，本轮不改代码。
- 聚焦套件 `117/117`、p0 合同套件 `35/35` 全绿；`sh -n` 与 `git diff --check` 通过。
- 未 commit/push/PR，未部署、未迁移、未连接生产；待同一 reviewer 第 7 轮复审冻结新指纹。

# 2026-07-31 历史赛事年份、完整性与重点筛选完成只读诊断

- 已从 `origin/main@43b81fd3` 创建隔离 worktree
  `/Users/mentianlu/.codex/worktrees/diagnose-historical-race-calendar-gaps/umanews`，
  分支为 `codex/diagnose-historical-race-calendar-gaps`；主工作区未修改。
- 香港 2024/2025 页面存在普通马季上半段被归入后一自然年的确定错误；香港杯抽样进一步显示
  2019—2025 均指向前一自然年，故正式修复前必须普查全部香港
  `year != local_date.year` 记录，不能只改已知 12 场。
- 2024 日本筛选只到 4 月 6 日并非采集不全：`year/q` 查询按日期升序截取前 40 条，同时关闭
  前后游标；5—11 月赛事仍可由同年度搜索命中。
- A. P. Smithwick Hurdle 等跨栏赛以 `-` 表示无马号；年度参赛马采集器把 `-` 当成真实唯一
  编号，第二匹马即触发 identity conflict。历史详情链已有允许多个空马号并按稳定来源身份/
  马名回退的正确合同，相关既有测试本轮复跑 `1/1` 通过。
- 历史年份“重点”当前仍按 P0/P1 或人工置顶过滤；历史物化记录默认 P2/未置顶，所以 G1/G2
  全部被排除。用户确认历史“重点”应显示 G1+G2；该口径与现有
  `backfill-race-events-to-1984` 旧规格流程 冲突，需先修订规格再实现。
- 详细证据与修复边界见 `docs/historical_race_calendar_gap_diagnosis_20260731.md`。本轮未修改
  业务代码、未访问生产数据库、未执行生产写入，亦未 commit/push/PR/部署。

# 2026-07-31 历史赛事四类缺口进入一体化方案审核

- 已建立 `docs/changes/repair-historical-race-calendar-integrity/` 五文档，范围统一包含：
  公开自然年/届次年拆分、全库 mismatch census 与香港存量修复、历史重点 G1/G2、year/q 稳定
  分页、跨栏赛缺马号身份。
- 方案采用 `RaceEvent.year=公开自然年`、新增 `edition_year=届次年`，并以统一
  `RaceEventPublicPath` registry 同时承载 canonical/legacy 路径，避免跨表路径抢占。
- schema/代码明确拆为三个独立 commit/image/review/release：A 只加 nullable 字段和 registry；
  B 在全库 census 后切换 series/edition 唯一约束；C 在数据 verifier 后收紧 non-null/自然年
  check。同一 release task 不会提前执行后续 migration。
- 独立方案 reviewer 三轮完成：首轮 `REVISE`（3 P0、7 P1、3 P2），第二轮剩余 1 P0/2 P1，
  第三轮全部关闭并给出 `APPROVED`，开放 P0/P1 为 0。最终方案包含全地区 action、连续错年
  duplicate supersession/tombstone、不可变 approval/actor、maintenance/freeze、repair receipt、
  NULL-safe signed cursor、fresh collector output 和 Release C 后回滚边界。
- 旧在途 `backfill-race-events-to-1984` 的历史重点/公开年份冲突合同和 runbook 中
  `hong_kong_racing_season_spans_calendar_years` 已在设计层标记为被本 change 取代。
- 以上为方案审核阶段的历史记录；随后用户已明确“开始实现”，Release A 本地实现与 RED/GREEN
  已完成。此后实现快照也已通过第二轮限定代码 review；当前门禁以上方最新状态为准：事实文档
  写回待同一 reviewer 复审，仍未访问/修改生产数据库，也未 commit/push/PR/部署。

# 2026-07-31 历史赛历首次代码审核 findings 已在第二轮限定复审关闭

- 首次代码审核提出 4 项 actionable findings；本地逐项修复后，同一 reviewer 第二轮限定复审
  已给出 `VERDICT: APPROVED`，前轮 `1 P1 + 3 P2` 全部关闭。
- `RaceEvent` 新建与年份身份变更现在强制走集中 `validate_event_years`；直接
  `QuerySet.update/bulk_update` 修改 year/edition/local_date/source_refs/slug 会被拒绝。
  Release A 仍允许已有坏行只更新 notes/status 等非身份字段。
- canonical public path 由 `RaceEvent.save` 同事务自动 reserve/sync；新建、rename、legacy
  collision 和事务回滚已有 SQLite 合同测试。
- `0067` 原地加入 `HistoricalRaceCalendarMaintenanceGate`，未新增 `0068`。apply/rollback
  要求 exact active gate；普通 RaceEvent/target/path writer 在事务内检查 live gate。
- orphan rollback ledger 的 crash 重试、篡改拒绝和数据库 pre-state 校验已覆盖。
- 首次修复阶段的聚焦 GREEN `51/51`；`manage.py check`、`makemigrations --check --dry-run`、
  fresh `0066→0067→latest` 与 `0067→0066` 均通过。该阶段尚无真实 PostgreSQL 并发证据；
  后续验收见下方最新记录。未 commit/push/PR/部署，未访问或修改生产。
- 扩大到 historical batch/inventory/detail source、current import 和前台 calendar 的一次
  SQLite 组合运行执行 268 项，其中 261 通过、7 项均停在 macOS `/var` 与 `/private/var`
  临时目录别名导致的既有 `Path.relative_to` 错误；本轮未把该环境问题修复或误报为全绿。
- 第一次复审又指出 1 P1 与 3 个同源 P2：现已恢复 `RaceReferenceReceipt` instance delete 的
  永久不可变保护；`RaceEvent.save(update_fields=...)` 改按 effective write-set；public path/
  target instance delete 接入 gate；dependency snapshot 的同 model 多 FK 改用 relation identity
  分键。新增 RED 后，review fixes + integrity/tooling + years + frontend 聚焦 `115/115`。
  check、migration drift、diff check 通过；`0067` 未增加 schema 且没有新 migration。原生
  `codex review -c 'sandbox_mode="read-only"' --uncommitted` exit `0`，审前/审后 fingerprint
  相同。以上批准只覆盖文档写回前的
  实现快照；本次事实文档变更后仍须复用同一 reviewer 限定复审。
- 最终全量扫描又发现 1 P1/1 P2：`RaceEventPublicPath.event` 已在 model/既有 `0067` 改为
  `CASCADE`，普通 event 删除原子清理 registry，active gate 下 event/path 均保留；orphan
  ledger 改为 controlled path + symlink rejection + `O_NOFOLLOW` 单次安全读取，同一 bytes
  用于 digest 与 JSON。root 内/外 symlink RED/GREEN 和普通 orphan 恢复均覆盖。相关聚焦
  `116/116`，fresh SQLite `0066→0067→0066`、check、migration drift、diff check 通过；
  第二轮批准指纹不覆盖本次增量，当前重新处于待复审状态。

# 2026-07-31 历史赛历 Release A 真实 PostgreSQL 验收完成

- 新增真实 PostgreSQL 专项 `test_historical_calendar_release_a_postgres.py`，连续两轮均
  `5/5`。fresh migrate `7.96s`，`0066→0067` `0.346s`，反向 `0067→0066` 两轮约
  `0.463s / 0.475s`，均低于 Release A 预设 migration 时间门禁。
- shared/exclusive advisory lock 通过实际 `pg_locks` wait 证明，约 `0.024s`；排队 writer
  在锁后重查 active gate 并拒绝，exit 后恢复写入，线程无 deadlock，数据库无陈旧提交。
- PostgreSQL 约束覆盖路径冲突事务回滚、event/path `CASCADE`、receipt manifest unique 和
  单 active gate 条件唯一。临时容器 `umanews-histcal-pg-accept-20260731-a1` 与 tmpfs 已删除，
  未变更其他容器。
- 这不代表完整 `stable` 全绿；既有 `3989 / 25 failures / 54 errors / 72 skipped` 未重新变成
  全绿，50k 性能门禁也未执行。此前 review fingerprint 已因加固、测试和文档增量失效，必须
  重新 review；仍无 commit/push/PR/deploy、生产 census/apply 或发布授权。

# 2026-07-31 历史赛历 descriptor 与提交后缓存失效加固完成

- current-year descriptor 现在分别保存 public/edition year；slug、query、identity 继续严格以
  public year 为准，跨届次 event 仍必须携带 descriptor，不能因当前年路径省略届次事实。
- apply/rollback 的 public cache invalidation 改为 `transaction.on_commit`：只有事务成功提交才
  清理；失败事务和 existing receipt 幂等重入不产生无效缓存失效。
- 主线程合并 Django `224/224`、collector `101/101`，其中 descriptor `13/13`、cache
  `10/10`；check、migration drift、diff check 通过。真实 PostgreSQL `5/5` 两轮证据继续有效。
- 完整 `stable` 仍是既有/环境 `3989 / 25 failures / 54 errors / 72 skipped`，不能称全绿。
  此增量未被旧 fingerprint 覆盖，待同一 reviewer 复审；无 commit/push/PR/deploy、生产
  census/apply 或发布授权。

# 2026-07-31 历史赛历写总门禁、authority URL 与 detail edition 加固完成

- apply/rollback（包括 existing receipt 重入）必须同时满足
  `HISTORICAL_RACE_BACKFILL_ENABLED=true`；prepare/verify 是只读入口，不受写总开关影响。
- 跨届次 `authority_url` 仅接受有效 HTTPS、受控 host、无 credentials/fragment；合法 query
  保留，不通过宽松归一化丢失证据身份。
- detail `edition_year` 仅在字段缺失时回退；显式 `bool`、非整数、`<=0` 或 `>9999` 均拒绝。
  该项首次失败被陈旧 SHA fixture 遮蔽，未保存 clean RED，不得补写为 TDD RED 证据。
- 最新主线程 `205/205`、URL + detail `166/166`、gate `68/68`；collector `101/101`、真实
  PostgreSQL `5/5` 两轮继续有效，check、migration drift、diff check 通过。
- 完整 `stable` 仍非全绿，旧 fingerprint 仍失效且必须复审；无 commit/push/PR/deploy、生产
  census/apply 或发布授权。

# 2026-07-31 历史赛历受控路径 raw symlink P2 实现关闭

- `_controlled_path` 已改为 absolute raw path 先逐组件 `lstat`，再 resolve/relative-to 并复核
  resolved components；受控 root 内 alias 不再被 resolve 隐藏。
- controlled reads 进一步以 root dirfd 为锚逐层 `O_NOFOLLOW` 打开父目录和 leaf，缩小检查到
  打开之间的父组件替换窗口；digest/JSON 仍复用同一 descriptor bytes。
- manifest、approval、maintenance evidence 三类 in-root symlink alias 均 fail closed；direct
  canonical regular file 与 root 外门禁保持，读取仍使用同一安全 bytes 做 digest/JSON。
- integrity/tooling/review fixes + descriptor/cache/public path 聚焦 `98/98`；check、migration
  drift、diff check 通过，无 migration 变化。实现 finding 已关闭，仍待 reviewer 复审；无
  commit/push/生产操作。

# 2026-07-31 历史赛历 apply 总写门 P1 实现关闭

- `apply_historical_race_calendar_integrity` 与 `rollback_historical_race_calendar_integrity`
  现在在读取 artifact、查询/更新 receipt 或创建 rollback ledger 前统一要求
  `HISTORICAL_RACE_BACKFILL_ENABLED=true`；配置缺省或 false 均 fail closed。
- rollback 会恢复业务行并更新 receipt，因此与 apply 共用同一历史写入总门；prepare/verify
  保持只读，不受该写门影响。existing receipt 重入在开关关闭时也不会借 verifier 更新状态。
- 新增 3 项 RED 后取得 GREEN；integrity/tooling/review-fixes 聚焦 `55/55`，加入 descriptor
  回归后 `68/68`。Django check、migration drift 与 diff check 通过。无 migration、commit、
  push、部署或生产操作；本增量仍待同一 reviewer 限定复审。

# 2026-07-31 历史赛历 URL 中央 validator P1 限定复审通过

- 同一 reviewer 确认 `URL central validator P1 CLOSED`，最终 `APPROVED`；原生 review
  read-only、exit `0`，pre/post fingerprint 均为
  `91fed97e63acacbb28ee8fed717edc049d1812f0dead8465c5a6f139bd110a39`。
- approved parent 为 `43b81fd3288a1e7b997ffad78d03565327e3d990`，approved content 为
  `b3353358647cd7b842a5a16326deee25ecc09485f37f7cd6974ed32b53868d2e`；本次文档写回会使
  content 过期，须复用同一 reviewer 做 evidence 增量复审。
- 验证证据为 URL 相关 `76/76`、主线程 `205/205`、真实 PostgreSQL `5/5` 两轮、collector
  `101/101`；完整 `stable` 仍非全绿。
- non-blocking P2 为 apply/rollback 与 maintenance exit 的理论锁顺序反转；PG `5/5` 未复现，
  但未执行专项并发 exit 验证，故未关闭并转后续任务。
- 无 commit/push/PR/deploy、生产 census/apply；发布未授权。

# 2026-07-31 lifecycle shadow 纳管准备进入方案审核

- 已从最新 `origin/main@43b81fd3288a1e7b997ffad78d03565327e3d990` 创建独立干净
  worktree `.worktrees/prepare-lifecycle-shadow-enrollment` 和分支
  `codex/prepare-lifecycle-shadow-enrollment`，未触碰主工作区现有改动。
- 本地只读盘点确认阶段 A 已有 control/transition、时间决策、claim、scanner 和
  shadow proposal 能力；缺口是生产 manifest 仍需手工构造，且现有 manifest dry-run
  没有执行与 apply 相同的完整 schema、美国 zone、冻结资格和 schedule/DB 漂移门禁。
- 生产只读核对：`HEAD=23abf5289f9dac8310c4ba0300b0e925e72d3f40`，
  lifecycle 保持 `false/off`，control/transition 均为 0。未来 90 天 172 场已发布重点赛事
  `race_datetime` 非空为 0、`local_start_time` 非空为 9；未来 45 天 85 场中 6 场地区
  时区错误为 `Asia/Shanghai`，不得纳管。首个查询因误用 `name_zh` 在 ORM 解析阶段失败，
  修正为 `chinese_name` 后成功；两次均为零写。
- 已建立 `docs/changes/prepare-lifecycle-shadow-enrollment/` 的 spec、design、test cases、
  tasks、rollout 和自包含 HANDOFF。推荐新增只读 prepare + strict manifest v2，并让
  dry-run/apply 共用 preflight；首次 apply 只允许 ≤20 场 shadow、完整 DB CAS、整批事务。
- 当前只修改文档，未修改测试、应用代码、migration、配置或生产数据，未调用 provider，
  未打开 lifecycle。下一门禁是独立方案 review；通过后仍需用户明确“确认实现”。
- 独立 reviewer session `019fb494-dfc3-7c71-a543-fa75421ef21a` 首轮 `REVISE` 的两项 P1
  已写回方案：v2 apply 必须技术强制严格 `false/off` 并核对 worker/claim 运行态；v1
  永久 dry-run-only，任何 apply 零写拒绝。待同一 reviewer 限定复审。
- 同一 reviewer 限定复审已确认两项 P1 关闭、无新的直接 P0/P1，最终
  `VERDICT: APPROVED`。当前停在用户“确认实现”门禁，仍未修改测试/代码/配置或执行生产动作。
- 用户随后明确“确认实现”。测试子代理先取得真实 RED：目标 prepare 命令不存在导致
  10 errors，旧 v1 apply 仍创建 control 导致 1 failure；实现后 enrollment SQLite 合同
  扩至 30 项，并通过跨位数 ID RED 锁定和修复 canonical 数值排序问题。
- 已新增 strict v2 enrollment service、只读 prepare 命令及 PostgreSQL 双 apply 合同，
  并扩展 reconcile：v2 dry-run/apply 共用 loader/preflight，apply 强制 strict
  `false/off`、shadow-only、≤20、排序锁、单事务 CAS/replay；v1 apply 永久零写拒绝。
- 首轮独立代码 review（session `019fb637-a018-7f43-a119-4f54f55cba00`）结论
  `REVISE`：服务层关闭态门禁、跨时间边界预测、祖先 symlink、schema 无界预读共
  1 P1 + 3 P2。首轮限定复审又发现 caller-controlled now、固定 alias 例外和读中 TOCTOU
  三项 P2；第二轮限定复审剩余 writer 验证到发布之间的祖先替换 P2。全部先补真实 RED，
  再修复；第三轮限定复审又发现 staging name/fd 换绑 P2，现已增加 rename 前后 inode
  绑定和 quarantine。第四轮限定复审发现名称扫描后 rmdir 的 cleanup 竞态及 quarantine
  断言不足；现已收敛为只通过 owned fd 清空本进程文件、允许空 staging，并锁定 marker 保全。
- 第五轮限定复审发现 rename 后最终校验失败会遗留公开空目录并阻断同路径重试；已用真实
  RED 锁定，并改为经稳定 parent fd 隔离公开名称后再清空 owned 文件。第六轮又发现
  rename 自身失败也会因标志位过早置位而移动竞争者目录；现只在 rename 成功后置位，
  conflict RED 已转绿且竞争者 inode/marker 原位保留。第七轮补出普通 rename 可覆盖
  并发空目录的 P2；现以 Linux renameat2/macOS renameatx_np 原子 no-replace 发布，
  能力缺失时 fail closed，空/非空竞争者和 staging swap 测试均通过。第八轮进一步要求
  在业务写入前验证 kernel/flag/同文件系统语义；现以两个空的 0700 高熵 probe 目录证明
  no-clobber 和 inode 保持，不支持或错误覆盖时业务写入次数为 0。
- 主线程复验：SQLite enrollment + 既有 lifecycle `91/91`，日历/页面/字段/race-live/
  scheduled-result 相邻回归 `190/190`，隔离 PostgreSQL enrollment + 既有 lifecycle
  并发最新复跑 `6/6`；Django check、migration drift、diff check 均通过。同一独立
  reviewer 第九轮限定复审已 `APPROVED`，P0/P1/P2/P3 均为 0，原生只读会话退出码 0，
  审前/审后 fingerprint `3932d1fd…749ef` 一致。
- 未新增 migration/settings/Beat/Compose，未联网或连接生产，未 commit/push/PR、部署、
  apply control 或打开 lifecycle。当前只追加审核证据并冻结 evidence fingerprint；
  下一门禁为用户对 commit、push 和 Draft PR 的明确授权。

# 2026-08-01 lifecycle shadow 纳管准备整合最新 main

- 用户已授权在上线准备通过后直接 commit、push、创建 PR 并合并；不授权部署、迁移、生产
  写入、control apply 或打开 lifecycle。
- 分支已从原基线 `43b81fd3` 快进整合到最新 `origin/main@1cdd066b`（PR #55 历史赛历
  完整性修复）。应用/测试文件无冲突；三份状态/决策文档保留主线新增事实后追加 lifecycle
  记录，deploy runbook 自动合并，未覆盖主线记录。
- 最新验证为 lifecycle SQLite `91/91`、新主线赛事年份合同 `20/20`、隔离 PostgreSQL
  `6/6`；Django check、migration drift 与 diff check 通过。原相邻 190 项中的 3 个
  `public_year/local_date` fixture error 已在独立干净 `origin/main@1cdd066b` 精确复现，
  属于主线既有失败，不在本 change 顺带修复。
- 旧 fingerprint 已因主线迁移失效；当前等待同一独立 reviewer 对基线迁移后的完整候选
  复审。复审通过后才执行已授权的 commit/push/PR/merge；生产生命周期仍保持关闭。

# 2026-08-01 lifecycle shadow 纳管准备代码已合并

- 最新 main 整合候选经同一独立 reviewer 复审后 `APPROVED`，P0–P3 为 0；最终审核
  fingerprint `11928d99…fcd1c`、content `6a501ebc…97975`。
- 代码提交 `ca37d51e5720c674bc234ab01f6b2a23d62f53fc` 已通过 index/commit transition，
  PR #56 于 `2026-07-31T20:29:35Z` 合并，main merge commit 为
  `3ba5defc526259b2785f4d84736551ab826804b3`。
- 本次只完成代码发布：未部署、未迁移、未执行生产 control apply/数据库写入、未联网 proof，
  也未打开 lifecycle。下一阶段仍需针对部署、生产只读 prepare/dry-run、control apply 和
  `true/shadow` 分别取得对应授权。
- 完整证据见 `docs/changes/prepare-lifecycle-shadow-enrollment/release_report.md`。

# 2026-08-01 lifecycle shadow 纳管准备已关闭态部署

- `main@6a185eaa35c9ea89211a33fa5a6cde81d76dbee3` 已从隔离 release 目录部署；
  web/worker/beat 统一运行 image `sha256:8ae8ce4e…d31b`，未修改生产主 checkout 的既有改动。
- 发布前 custom-format 备份为 `371214432` bytes、mode `0600`、`pg_restore -l=1295`，
  SHA-256 `98d96296…9dd05`；旧 image 已冻结为独立 rollback tag。
- 目标无待应用 migration。发布使用共享部署锁和单一 release-task owner；排空阶段等待一条
  既有术语发现任务自然结束，随后完整恢复 web/worker/beat/nginx。race-live 发布前未运行，
  发布后继续未运行；部署锁与 intent 文件均已清理。
- lifecycle 在 web/worker/beat 均保持 `false/off`；关闭态 scanner 返回
  `claimed=0 / dispatched=0`，control/transition/active claim 均为 0。HTTP healthz、赛事
  日历、worker ping、迁移计划和近期错误日志验收通过。
- 本次没有 control apply、provider proof、lifecycle 业务数据写入或 lifecycle 启用。排空前
  一条既有术语发现任务自然完成；该任务会写自身日志且可能写术语候选/证据，不属于 lifecycle
  零写结论，也未被中断、重跑或扩项。下一门禁为生产只读 prepare/dry-run；apply 与
  `true/shadow` 继续分开授权。HTTPS 尚未启用，未在本次扩项。

# 2026-08-01 首批 8 场近期重点赛事出走时间已受控写入

- 用户明确授权合并部署证据 PR 并真实写入 `race_datetime`。证据 PR #58 已合并，main merge
  commit 为 `52456cc5ba7a91c370e2efabf0fc0e481a0b051b`；该 PR 仅含上一轮部署证据文档，生产
  应用镜像仍为已验收的 `6a185eaa` / `sha256:8ae8ce4e…d31b`，本轮未重新部署或迁移。
- 生产只读盘点锁定赛事 `430/431/433/434/435/436/740/940`。Del Mar 与 NYRA 官方页面提供
  Clement L. Hirsch、Saratoga Special、Jim Dandy 的出走时间；Racing Post（并由赛事组织方
  赛程佐证日期/赛事身份）提供 Colonial Downs 三场、Prix Rothschild 与 Lillie Langtry 的
  明确时间。manifest 为 canonical JSON，SHA-256
  `ad103cb19d62622a7f09436c047095460d2f5ad60c4aa9927d4dbbdaf8960886`。
- 写前 dry-run 在生产精确通过：`8` 场、`23` 个字段变化；逐行 identity/updated_at CAS、
  scheduled/published 状态、manual lock、IANA 时区换算、既有 authority、lifecycle
  `false/off`、control/transition 均通过。Colonial Downs 三场和 Lillie Langtry 同时修正了
  “上海展示时间误存为举办地当地时间”的旧值，不能只补 UTC 而保留矛盾字段。
- 写前恢复点为
  `/opt/umanewsbot/backups/db/pre-race-datetime-20260801T080504Z.dump`，`173009409` bytes、
  mode `0600`、`pg_restore -l=1295`，SHA-256
  `96703a396885bb345f08b08b8b3a708bea65caab3fd7366e38d8aa6993c2f0ce`。
- 唯一一次 apply 在单个 PostgreSQL 事务内完成：8 场均写入 aware `race_datetime`，共追加
  `RaceEventFieldChange=23`、`RaceEventFieldAuthority=23`、批次 `OperationLog=1`；官方
  Del Mar/NYRA 时间记 authority `500`，经用户批准的可信媒体时间记 authority `200`，没有
  把媒体升级成官方来源。run ID 为 `race-datetime-ad103cb19d62622a`。
- 独立 verify 精确通过：8 场当地日期/时间/IANA 时区/UTC 与 manifest 一致，23 条当前权威的
  source/value hash 一致；lifecycle 仍为 `false/off`，control/transition 仍为 0，赛事状态
  继续为 `scheduled`。`/healthz/`、`/races/` 和 8 个赛事详情页均为 HTTP 200，页面逐场显示
  预期举办地时间，近 15 分钟相关错误计数为 0，部署锁不存在。
- 生产证据目录为
  `/opt/umanewsbot/runtime/operations/race-datetime-20260801T080504Z/`；包含 manifest、执行脚本、
  dry-run/apply/verify 与写后数据库快照。本次未执行 enforce，未生成或 apply strict lifecycle
  shadow manifest，也未打开 `true/shadow`。

# 2026-08-01 8 月 1–8 日赛事时间补采与第二批 8 场生产写入完成

- 首批写入证据经 PR #60 合并为 main `76676818582898536aa12189242bd565d6a8b94b`；该 PR
  只有 4 个文档、73 行事实追加，没有触发服务重建、迁移或 lifecycle 启用。
- 本次盘点生产日历 2026-08-01 至 2026-08-08 的 28 场已发布赛事；16 场取得逐场明确时间，
  其中首批 8 场此前已写入。本次补写 event `84/85/86/432/437/941/942/943`；其余 12 场因
  未取得逐场明确时间而保持原值，没有用场次顺序或首场时间推断。
- JRA 官方日程核对朱鹮夏季短跑、女王锦标和榆树锦标；NYRA 官方 race page 核对 Lake
  George 与 Adirondack；The Jockey Club 官方活动页核对 Rose of Lancaster 与 Sweet
  Solera；Glorious Stakes 使用已批准可信媒体 Racing Post。官方来源 authority 为 `500`，
  Racing Post 为 `200`。
- canonical manifest SHA-256 为
  `4e2e342dcc8b7def3b04bbe7b3e8db36f4f94634119f37d1ee1f7f09919c6922`，run ID 为
  `race-datetime-4e2e342dcc8b7def`。dry-run 为 `8` 场、`19` 个字段变化；单事务 apply 与独立
  verify 均精确通过，新增 `19` 条 field authority、`19` 条 append-only field change 和
  `1` 条 OperationLog。
- 写前取证快照为
  `/opt/umanewsbot/backups/db/pre-race-datetime-4e2e342d-20260801T133257Z.dump`，
  `373005202` bytes、mode `0600`、TOC `1295`，SHA-256
  `9be6d50ca9433eda897e47e3aca7eefcf1cdaccbafaf2f7be4ccc2482c8adf77`。该快照与正式
  apply 的两次锁之间存在间隔，未证明其他模块在间隔内零写，因此未将其批准为可直接整库
  恢复点；manifest 保留了本批目标字段的逐字段 before 值。
- 首次执行因容器真实工作目录为 `/app/server` 而在 dry-run 前失败；shell 管道未传播左侧退出码，
  只继续生成了数据库备份。精确进程树随后终止，确认 authority/OperationLog 均为 0、锁已释放；
  该快照经 `pg_restore -l` 验证结构完整，但正式重试未据此宣称其他写入者持续暂停。重试移除
  管道并逐项断言 JSON，再执行唯一一次 apply；失败事实保存在生产证据目录的
  `attempt-1-failure.txt`。
- 8 个公开 HTTP 详情页均为 200 并显示预期举办地时间；healthz、赛事日历、worker ping、
  beat 和近 15 分钟错误计数通过。生命周期保持 `false/off`，control/transition 为 0，部署锁
  已释放；HTTPS 握手仍失败，未被本次时间数据写入改变。
# 2026-08-01 生命周期重点赛事资格门禁移除已实现，待独立代码审核

- 用户决定 lifecycle 属于赛事基础能力，P2/非 featured 赛事不应因
  `is_key_race=false` 被 strict v2 纳管拒绝。新 change
  `remove-lifecycle-key-race-gate` 已从 `origin/main@53de0665` 建立独立 worktree；发布前 main
  前进到 `96d31468`，只新增一份赛事译名发布证据文档，候选已 fast-forward 整合且 lifecycle
  文件无重叠。主工作区既有改动未触碰。
- 方案 reviewer 首轮提出授权停点、观察口径和旧代码回滚三项 finding；修订后同一 reviewer
  `APPROVED`。R0 代码发布、R1 只读 prepare、R2 false/off apply、R3 true/shadow 继续分别授权。
- 测试先行真实 RED 为两个合法非重点 fixture 精确失败于“不是重点赛事”。实现只删除 enrollment
  service 的两行资格拒绝，manifest 仍冻结 priority/featured/is_key，其他 published、scheduled、
  地区/时区、manual lock、strict v2、20 场、CAS、false/off 和 shadow-only 门禁不变。
- 首轮代码 reviewer 唯一 P2 指出回滚 fail-closed 缺直接自动化覆盖；现已新增严格
  `false/off` 下 scanner 与已排队 task 对非重点 control 零 claim/零 proposal测试，并断言
  event、全部 claim/attempt 字段和 transition 均不变。
- 主线程最新验证：SQLite `98/98`、相邻回归 `101/101`、无卷 PostgreSQL 16 `6/6`；Django
  check、migration drift 和 diff check 通过。当前未 commit、push、PR、部署、重启、创建生产
  control 或修改开关；生产仍保持已确认的 `false/off`。下一门禁为独立原生代码 review。
# 2026-08-02 lifecycle R0 代码已合并，关闭态部署因 wrapper 执行位安全失败

- `remove-lifecycle-key-race-gate` 已通过 PR #62 合并为 main `7252d59a`。首次关闭态部署从
  精确 commit 创建隔离 release 目录，但在首个 historical runner preflight 调用
  `deploy/docker/compose-wrapper.sh` 时以 exit `126 / Permission denied` 停止；仓库 Git mode
  为 `100644`。
- 失败发生在备份、镜像 tag/build、停 beat、Celery drain、release task、迁移和服务重启
  之前。部署锁已释放，线上镜像、服务、数据库和生命周期开关均未改变；web/worker/beat
  继续 `false/off`，control/transition 为 `0/0`，healthz 与赛事页为 200。
- 用户已授权修复执行位并独立 review。测试先行取得精确 RED；首轮 reviewer 发现 harness
  chmod 掩盖完整 R0 直接执行图，已把标准/lowcost 两个根入口、两个内部入口、compose wrapper
  和 drain helper 共六个 Git mode 从 `100644` 修为 `100755`，所有内容 SHA 不变。raw-checkout
  调用图测试与部署合同 `165/165`、Django/migration/shell/diff 检查通过。当前等待同一 reviewer
  限定复审，未 commit、push、PR 或重试生产部署。

# 2026-08-02 lifecycle R0 执行位修复已发布，关闭态部署完成

- 执行位修复经 PR #63 合并为 `main@2dba891f`；从该精确 revision 的隔离 release 目录完成
  R0 标准发布，最终镜像为 `sha256:24fc89c…67b9f`。共享部署锁、historical preflight、有效
  custom-format 备份、旧镜像冻结、Celery 自然 drain、唯一 release task 和 web healthy 门禁
  均通过；迁移报告无待应用项。
- web/worker/beat 均保持 lifecycle `false/off`，control/transition/active claim 为 `0/0/0`；
  scanner 关闭态 smoke 为 `enabled=False / claimed=0 / dispatched=0`。race-live 未启动，发布锁和
  意图文件均已清除。本轮没有 lifecycle 业务写入。
- HTTP healthz、赛事日历、Celery ping 和近 15 分钟错误日志验收通过。数据库恢复点 SHA-256
  为 `285de333…edc7f`，完整证据见 change 的 `release_report.md`。下一步仍须单独授权 R1
  生产只读 prepare/dry-run；本次授权不包含 control apply 或开启 shadow。
# 2026-08-02 生命周期 R3 队列路由阻断已完成本地修复

- R3 shadow smoke 中 scanner 成功 claim/dispatch 2 场，但单赛事任务被路由到无人消费的
  `default`，普通生产 worker 只消费 `celery`，因此未生成 proposal。
- 失败后已恢复 lifecycle `false/off`；赛事状态、proposal 与 applied 均未改变，
  `race_live_worker` 未启动。`default` 中 2 条旧消息保留，不清理、不重放。
- 独立 worktree `codex/fix-lifecycle-task-queue-routing` 已将 advance task 最小改投
  `celery`；配置合同、旧 generation 隔离与 lifecycle/enrollment 回归 101/101 通过，
  Django check、迁移零漂移和 diff 检查通过。尚待独立代码 review；未 commit、push、PR、
  部署或重新启用 shadow。

# 2026-08-02 生命周期任务队列路由修复已关闭态部署

- PR #65 已合并为 `main@d5ae1d7e`，并从精确隔离 checkout 完成关闭态部署；最终
  web/worker/beat 镜像统一为 `sha256:b1fecc46…41a73`。
- runtime 已确认 advance task route=`celery`，worker 只消费 `celery`；三容器保持 lifecycle
  `false/off`。16 个 control 对应赛事仍全部 scheduled，transition/proposal/applied/active
  claim 均为 0，scanner 关闭态 smoke 未 claim 或 dispatch。
- `default=2` 和 `race_live=7543` 均未处理；race-live worker 未启动。内部/公网 healthz 和
  赛事页 200，迁移计划为 0，观察窗口日志错误和 Nginx 502 均为 0。
- 恢复点、镜像、证据 SHA 和并行 one-off 偏差见
  `docs/changes/fix-lifecycle-task-queue-routing/release_report.md`。下一步仍是独立授权的 R3
  shadow 重试，而不是自动开启。
# 2026-08-02 race-data-sync 切片 A 本地实现与独立代码审核完成

- `build-race-data-sync-pipeline` 已从最新 `origin/main@54a79308` 的独立 worktree 实现切片 A 核心：
  provider-neutral strict normalization/reconciliation、10-provider versioned roster、runner 字段冲突
  ledger、schedule candidate 禁入、90 天 raw cleanup，以及默认关闭的 provider/region/field 三层开关。
- `RaceEventFieldChange` 通过 additive migration `0068` 增加 observation、source class、source updated
  time、parser/raw/normalized/registry/contract/task/decision 等 11 个审计字段；`0069` 增加 decision
  enum/check 与 PostgreSQL 可逆 append-only trigger。TRA racecard refresh
  已接入统一 reconciliation；时间、本地时间、取消和延期在 C 完成前只写 `slice_c_required`
  candidate，不修改 `RaceEvent` 或 lifecycle control。
- 独立代码 reviewer 首轮给出 6 个 P1、2 个 P2；第二轮限定复审再发现 1 个 P1、3 个 P2；
  第三轮再发现 canonical revision 门禁旁路和 needs-review 部分提交/claim 悬空 2 个 P1；第四轮
  发现真实 TRA `jockey_id` metadata 被误算为写字段的 P1 与 Ireland 明确路由缺口 P2；第五轮
  再发现 Ireland 双 marker 冲突仍被 OR 放行的 P1。随后新增真实 RED 覆盖 runtime flags、精确 roster
  contract、provider-scoped participant identity、TRA 第二写、freshness watermark、安全 raw cleanup、
  decision/append-only/Admin，以及 legacy runner ownership、odds/popularity allowlist、动态水位单调性和
  超过 10,000 held rows 的清理饥饿、canonical partial projection、needs-review 原子回滚/claim 收尾和
  allowlist 扩大后的字段级幂等、真实 TRA fixture metadata 和显式 Ireland marker/冲突矩阵。修复后主代理独立验证 SQLite A `64/64`、相邻 race-live
  `48/48`、真实 PostgreSQL `11/11`；Django check、migration drift、py_compile 与 diff check 通过。
- raw cleanup 使用逐级 `O_NOFOLLOW` directory FD、`unlink(..., dir_fd=...)`、文件身份复核、锁内
  hold/path/retention 重验和 DB CAS；不再依赖 Linux-only `/proc/self/fd`，macOS 与 Linux 语义一致。
- 更宽的 207 项回归为 7 errors、2 failures、3 skips；去掉本切片 46 项后，同一 161 项在未修改的
  `origin/main@54a79308` 临时 worktree 精确得到相同 7 errors、2 failures、3 skips，属于既有日期、
  CAS 与公开文案 fixture 漂移，本任务未修改无关测试。
- 同一独立 reviewer 第六次限定复审最终 `VERDICT: APPROVED`，无阻塞 P0/P1。非阻塞 follow-up 为
  Ireland 直接预录 observation 的 reconciliation admission 尚未复用 marker 合同；本轮本就不含 Ireland
  cohort，因此 Ireland 自动化保持不可发布，后续纳入前必须先补此门禁并重新 review。
- 当前未 commit/push/PR/部署/migrate、未调用 provider/收费 API、未读取
  生产凭据或修改生产开关。除现有 TRA adapter 外，其余 provider 均保持 `proof_required`。

# 2026-08-08 lifecycle shadow 观察加固已通过独立代码审核

- 独立 worktree `.worktrees/harden-lifecycle-shadow-observation` 已整合
  `origin/main@11abe4bf2d2badbfe1daa2f5fdd8f8e97f5f0093`；生产只读背景快照当时为统一
  `true/shadow`、16 controls、16 proposals、0 applied、0 active claim，race-live 未运行，
  `default=2 / race_live=7543` 未处理。
- runtime handshake、host-wide census、canonical no-deps wrapper 和 fail-closed mode switch
  已按真实 RED 实现。hardening `37/37`、合并回归 `294/294`、PostgreSQL 16 `6/6`、
  Release B deploy contract `1/1` 及其余静态检查通过；独立 reviewer 最终 `APPROVED`。
- 该实现未扩张 migration、provider、状态机、queue 或公开行为。

# 2026-08-08 lifecycle shadow 加固已合并，部署证据已由 PR #73 收口

- PR #72 已合并为 `main@c4ad7277498846695065c71239dc59334e04370e`；候选镜像
  `sha256:eb701e55…28b53` 已构建，但 Release B schema preflight 在唯一 release task 前发现
  生产 migration leaf 为 `0067 + 0070`、缺少 `0068/0069`，因此候选未部署。
- 阻断与恢复证据随后由 PR #73 合并为
  `main@bcea5aa89f35e13d7ed13a29ebbdb6e58b6f978d`。该 PR 只收口证据，不改变生产运行态。
- 生产已恢复旧镜像 `sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`
  并统一为 `false/off`；没有 migration、collectstatic 或 lifecycle 业务写入，race-live 未启动，
  HTTP、worker 与近期日志健康。16 controls / 16 proposals / 0 applied / 0 active claims；
  `default=2` 与 `race_live=7543` 积压保持不动。

# 2026-08-08 migration-history repair 最终技术门禁 VERIFIED，尚未发布

- 生产只读对账确认 `0070` receipt schema 与 7 条数据完整，而 `0068/0069` schema 完全未应用。
  修复采用恢复 `0067→0070` 独立分支、由 `0071` 汇合 `0069/0070` 的真实迁移图；禁止直接
  修改 `django_migrations` 或 fake migration。
- 最终 SQLite 三套件为 `256/256`（`255 passed / 1 Docker-gated skipped`），PostgreSQL 16
  migration/catalog 专项 `23/23`，语法与 diff 检查通过；独立审查后的实现状态为 `VERIFIED`。
- 固定旧生产镜像
  `sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`
  （`linux/amd64`）仅以生产 `docker save` 只读导出并在本地精确导入。PostgreSQL 16
  `{0068,0070}`（`0068-only`）与 `{0069,0070}`（`0069-complete`）两态均完成
  TCP role auth、read-only/write-denied、旧镜像 check、web health、worker ping、Beat、clean logs
  和 audited digest before/after equality；两项兼容性 gate 均为 GREEN，fixture 已清理。
- 更早的环境字符串、`post_migrate` 与首次认证失败均发生在正式 smoke 前，不计 compatibility gate。
  截至本记录检查点，修复发布仍未执行：没有生产部署、migration、Release B、v2 census、回填或
  2025 `full_network` 运行。

# 2026-08-08 migration-history repair 发布前 P2 provenance 隔离已修复

- `RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256` 现在只允许由 artifact-bound
  `handoff_action=forward-resume` 使用；普通 deploy、manual release、rollback 与 initial-install
  均在 host 入口显式清除继承值，并以本次 `RELEASE_B_PREFLIGHT_ARTIFACT_SHA256` 建立和完成 intent。
- 容器 release task 同样按精确 handoff action 二次分流：普通 action 的旧 provenance SHA 不会进入
  ensure/completion，forward-resume 则继续要求 64 位小写 SHA，并由 handoff/marker verifier 绑定原
  provenance。错误 action 或缺失 resume provenance 均在 migrate 前停止。
- 新增 RED 已证明旧实现会把普通 deploy 的残留 SHA 传入 ensure/completion；修复后 host、容器、
  initial-install、rollback 与两类 resume 定向回归 GREEN；最终三套件 `256/256`（含 1 个 Docker
  条件跳过）。当前仍未 stage/commit/push/部署或执行生产 migration。

# 2026-08-08 migration-history repair 发布前索引 owner P2 已修复

- `0071` 的 `uq_race_event_series_edition` 与
  `uq_hist_target_active_series_year` 现在除名称、唯一性、列、opclass、predicate 与状态外，还必须
  精确属于当前 PostgreSQL schema 下的 `stable_raceevent` 与
  `stable_historicalraceeventtarget`。
- catalog collector 会按受审索引名收集同 schema 的错表对象，不能再因表 allowlist 而只表现为缺失。
  纯函数覆盖合法 owner、错 schema、错 table；真实 PostgreSQL fixture 将原索引替换为其他表上的同名、
  同列、同 predicate 索引，validator 精确拒绝，并在 `finally` 恢复后再次验证合法 catalog。
- PostgreSQL 专项 `24/24` 通过，隔离容器已删除；未 stage/commit/push/部署或连接生产。

# 2026-08-10 participant batch-0001 首次 network prepare 与最小修复

- 生产 `main@6c357985` 对 `batch-0001-japan-0001`、review manifest
  `f910082d…f12` 执行一次单批、串行、数据库强制只读的 network prepare：50 匹产生 76 次请求与
  22 个 JBIS canonical cache，`database_writes=0`，数据库 before/after SHA 均为
  `18e08300…43c0`。completion SHA 为 `7d555ef9…07dec`，但结果为
  `complete=0 / blocked=50`，独立复审 `REVISE`，未进入 release/G3。
- 确定性分类为：23 个缺 netkeiba provider-bound ID、22 个 JBIS 唯一命中后被旧 expected identity
  合同拒绝、2 个 JBIS `**` 中止/失格状态未归一化、2 个歧义、1 个姓名不匹配。当前生产仍全部高风险
  开关关闭，无 one-off 或资料写入。
- 干净分支 `codex/fix-p0-participant-identity` 已实现最小修复：只有真实数字 netkeiba horse ID 才走
  netkeiba 直连；reviewed Japan occurrence 可由 JBIS 唯一精确搜索、完整 search/profile identity
  一致性建立 provider-bound identity；精确 `中止/失格` 分别归一为
  `did_not_finish/disqualified`，其他未知 `**` 继续 fail closed。
- execution ledger 新增受控 `retry`：仅允许同一 active identity、旧 phase=`prepared`、旧 completion
  全部阻断且零写入，并要求 reason=`deterministic_blocker_repaired`；旧 completion SHA 写入
  `prepare_attempts` 后才回到 `claimed`。相关 P0 组合回归 `383/383`、participant/源合同 `90/90`
  与 ledger `2/2` 通过。当前记录点尚未提交、合并、部署或续跑。

# 2026-08-10 participant batch-0001 最小修复已闭锁部署并完成精确续跑

- 最小修复由 PR #91 合并为
  `main@0149eab88bb74521602e1fe73beb240bc7ddd919`；生产镜像
  `sha256:71d56e74be554a329dfb147493fe8850220833fbd7ea3c85d713cbc8f8d1eb6a`
  已在全部高风险开关关闭下部署。fresh 写前备份为
  `pre-p0-identity-fix-0149eab8-20260809T2010Z.dump`，SHA-256
  `1fc928af…52c`；migration no-op，唯一 leaf 为 `stable.0072_add_extended_racing_regions`。
- 部署 verifier 通过：web/worker/beat revision、镜像与 workdir 一致，Django check、空 migration plan、
  Redis、Celery ping/active/reserved、零 writer/lock/one-off、内外 `/healthz/` 200 与近期错误日志均正常；
  全局 horse/history/race-live/race-data 网络与调度开关仍为 `false`。
- execution ledger 以原 completion `7d555ef9…07dec` 和固定 reason
  `deterministic_blocker_repaired` 执行一次 retry，保留旧 SHA 后回到 `claimed`。随后仅对
  `batch-0001-japan-0001`、原 review manifest `f910082d…f12`、原 cache 运行单一数据库强制只读
  one-shot；没有启动其他批次、release、apply 或 G3。
- r2 completion SHA 为 `2cf2c634…04b8`：`50 processed = 34 complete + 16 blocked`，
  `120` 次网络请求，`database_writes=0`。数据库六项 before/after 文件逐字节一致，SHA 均为
  `18e08300…43c0`；账本当前精确停在 ordinal 1 `prepared`，绑定 r2 SHA 并保留唯一 r1 retry history。
- 独立 artifact 审查最终 `VERDICT: APPROVED`，无 P0/P1/P2。16 个 blocker 为 14 个 JBIS HTTP 403、
  1 个 `ambiguous_identity`、1 个 request horse-name mismatch，全部正确 fail closed；34 个完整 occurrence
  对应 32 个 provider ID，两个跨 occurrence 重复须在后续 mapping snapshot 合并。当前批准只允许进入
  34 项模块人工审核/候选生成，16 项冻结排除；review CSV 尚未完成人工模块决策，不等于 G3 或生产写入授权。

# 2026-08-10 batch-0001 r2 首次 G3 已回滚，跨来源同赛最小修复待发布

- 已批准 candidate `fc7962c3…e16e` / artifact `9d2a1e32…9c16` 的 manifest-bound apply 在
  `インターポーザー` strict-complete 门禁确定性停止；事务完整回滚，32 个 profile、243 条既有履历、
  50 条 P0 source、completion run 与 task log 均无净变化，3 个 draft 仍未发布，`full_network` 未启动。
- 根因是该 profile 已有 11 条 Netkeiba 完整履历，artifact 又提供同 11 场 JBIS 履历；provider identity
  与赛名差异使旧逻辑计划新增 11 条，合并后实际出赛会变成 22，而官方/来源计数仍为 11。旧 candidate、
  artifact、release manifest 和 G3 不得重放。
- 干净分支 `codex/fix-p0-cross-source-race-dedupe` 已实现保守同赛等价：仅不同来源、精确日期、同场地、
  同公制距离、同完赛名次、同 actual result/status 的 started 记录可合并；race number/event 冲突、多候选
  或多种 identity 指向不同记录均 fail closed。prepare/dry-run/commit 统一按合并后 started count 与受审
  official/source count 守恒，并复用同一语义执行重复提交漂移检查。
- 当前验证：定向 `3/3`、production apply + career history `44/44`、相邻 participant/completion
  `366/366`；真实 PostgreSQL 16 上本次跨来源首次提交与重复提交 `1/1`。PostgreSQL 旧专项中的 5 项
  legacy-v1 fixture 会在进入本次路径前被现行 v2-only 门禁拒绝，另 2 项锁测试通过；未将其误报为本次全绿。
- 独立只读代码审查最终 `APPROVED`、无 P0-P2；确认保守等价、多解/冲突拒绝、锁内写前守恒、重复提交
  幂等及通用 upsert 全局影响均无阻断项。当前没有生产数据写入；下一步为 commit/push/PR/合并、全部
  高风险开关关闭的部署，再基于精确新 revision 和新鲜生产快照生成全新 candidate/artifact；完成独立
  artifact 审查后重新申请 G3。

# 2026-08-10 lifecycle enforce canary 独立代码审核 APPROVED，待发布授权

- 独立 worktree `codex/lifecycle-enforce-canary` 基于 `origin/main@70f365c7`，只实现 event 186/187
  的 manifest-bound enforce 灰度；其他 control 继续 shadow，不接入 provider、race-live、新闻、QQ
  或新状态机，不含 migration。
- 方案经同一独立 reviewer 三轮收敛至 `APPROVED`。实现采用独立 env/settings SHA+IDs 信任根、
  inactive/active 两阶段 evidence、两场共享 64 位小写 activation ID、shared deployment lock、
  PostgreSQL advisory transaction lock、bounded stdin manifest 与 web→verify→worker→activate→Beat
  顺序；false/off 不依赖 artifact 并清空信任根。
- 测试先行先取得 4/4 load-bearing RED；主线程随后发现并以真实 RED 修复“范围外 shadow control 在
  global enforce 下被错误 noop”问题。独立 reviewer 首轮 `REVISE` 的 3 项 P1 与 1 项 P2 也已全部
  按测试先行修复：management command 与 wrapper 写前绑定授权 event IDs；scanner claim 查询排除
  范围外 enforce；旧 resident 在严格 false/off 下允许缺失 canary 空键完成 bootstrap；合法生命周期
  进展后可安全 disarm/reactivate，且新 activation ID 不复用。
- 第 2 轮 reviewer 确认首轮三项 P1 已关闭，仅新增 1 项 reactivation provenance P1：状态属于
  running/finished 不足以证明由本 canary 推进。主线程新增外部直改状态负例并取得真实 RED；修复后
  canary applied transition 写入 manifest/activation provenance，reactivation 验证精确状态链、generation、
  reason 与 T/T+30 时间连续性，普通或无 transition 的状态变更均拒绝。
- 当前组合回归 `147/147`、隔离 PostgreSQL 16 并发 promotion 再次 `1/1`；Django/migration/shell/
  workflow/diff 门禁全部通过，临时容器已删除。同一独立 reviewer 第 3 轮最终结论 `APPROVED`，无
  P0/P1；仅记录首次 tick 直接 `scheduled→finished` 后同 manifest reactivation 会保守拒绝的非阻塞 P2，
  不影响首次 canary、不扩大写入范围。当前没有 commit、push、PR、部署、生产 control/event/env 写入
  或 enforce 启用；下一步需用户分别授权 G2 代码发布与绑定生产 revision/manifest SHA/186,187 的 G3。

# 2026-08-10 lifecycle enforce 双赛事 canary 已在生产启用

- PR #100 已合并为 `a7e3783ff7d188481cecd421cd2595f43e9a706b`；生产 web/worker/Beat 统一运行
  image `sha256:afa0379f…f441f`。无 migration，关闭态部署和严格 `false/off` artifact dry-run 先完成。
- G3 manifest raw SHA 为 `eacffda63284e25b59c3efa5815d138a562c10e86eec7fe5ed1ed41219d303fc`，
  精确包含 event 186/187。写前 custom-format 备份为 `421435241` bytes、`pg_restore -l=1308`，
  SHA-256 `9265fd9e…a078`。
- shared-lock promotion 与分阶段 mode switch 成功；当前三服务为 `true/enforce`，两场 control 为
  `enforce/active` 且共享 activation ID `fb222bb1…010e`。其他 enforce control 为 0，race-live 仍关闭。
- 同步与真实 Celery scanner smoke 均返回 `claimed=0 / dispatched=0`，Beat 已自动执行一次。两场尚未
  到 T，状态仍为 `scheduled`、applied transition 为 0；公开 healthz 和详情页 200，重建完成后的
  `Traceback/canary_blocked/502` 均为 0。
- 下一观察点为 event 186 的 `2026-08-11 16:05/16:35`、event 187 的
  `2026-08-13 18:55/19:25`（北京时间）。完整证据见
  `docs/changes/lifecycle-enforce-canary/release_report.md`。

# 2026-08-28 赛事数据全生命周期自动化已完成本地实现与零写 dry-run

- clean worktree 分支 `codex/implement-race-data-lifecycle-sync` 已闭环未来赛事自动发现、赛时补全、
  出马表每日不少于两次的动态更新、T/T+30 状态推进、T+3 起赛果抓取、不可变 revision、并列名次和
  7 天更正观察；无需逐场人工确认，公开页统一显示“赛果”且不暴露内部来源等级。
- 来源仲裁固定为 The Racing API/其他 licensed API > 已导入官网事实 > 可信第三方。The Racing API
  是本轮唯一新增联网主适配器；HKJC/France Galop 官网层只消费既有官方导入，未把网站条款误当成
  新 transport 授权。主 API result not-found 后才按官方、Sporting Life/ZEturf/HRN 顺序 fallback。
- 新 migration 为 `0075_race_data_source_priority_and_reported_position`；standing policy SHA 为
  `07013655d4e0ae4bd5688b9a5dc447d759c0effa4b5393ec198f48bf961a1888`，TRA registry SHA 为
  `3bac3b644c631ed165b8430343822b2c70c5a88c5036b63dcb557c83c0e0a6da`。全部新开关默认关闭、容量默认 0。
- provider 网络请求后、任何 schedule/racecard/result canonical 写入前，现会在同一事务重新锁定并核验
  exact claim、有效期、owner/enrollment generation、entry/route/plan SHA、checkpoint version 和获准
  data-kind；claim 被替换、过期或越权时零投影，旧 worker 也不能完成或释放新 claim。
- 聚焦回归 `202/202`、隔离 PostgreSQL 16 专项 `24/24`、Django check、migration drift 和 compileall
  均通过。另以同一 SQLite/Celery eager 口径复跑赛事相邻扩展套件：当前分支 `684` 项为
  `9 failures / 39 errors / 4 skipped`，`origin/main@2833558a` 的共同模块基线 `607` 项为
  `12 failures / 39 errors / 4 skipped`；主干缺少本 PR 的 6 个测试模块所产生的 import error 已剔除，
  规范化失败/错误用例集合中 `current-only=0`，新增 `77` 项均未
  引入红灯，并修复基线 3 项既有失败。剩余红灯完整继承自日期/授权绑定的旧 `race_live` 契约，不作为
  本次通过项伪报。全新临时 SQLite dry-run
  返回 `configuration_status=ready / route_drift=[] / would_write=false`，审计前后数据库 SHA 同为
  `7be22b4ae103330a5443671031b82230841ff4688817722cc1573fa9fba548ef`；容量合同为 `valid`。
- 实现 commit `e6ec0e6e` 已推送并创建 PR #108；尚未合并、部署、迁移生产或开启任何新 flag。
  实现和发布边界详见
  `docs/changes/automate-race-event-lifecycle/race_data_lifecycle_implementation_20260828.md`。
- 生产只读预检：运行 revision/image 为 `2833558a…` / `sha256:4bc392…`，内外 healthz 200，external
  started/active lock 为 0；2 条 `ExternalDataImportLock` 占位行均无 owner/acquired time。新
  `race_sync_v2` 队列为 0，旧 `race_live` 队列有 7,543 条遗留消息且无 worker，必须保持不动。磁盘可用
  `12,211,531,776` bytes、备份 `47,380,298,866` bytes，主 checkout 有 1,710 项历史 dirty；部署必须用
  隔离 release，不得直接清理或覆盖主 checkout。runtime 已有旧版总开关 false 与 provider/region/field
  三个空集合键，其余本 change 新键尚不存在。
- 已据此冻结候选容量：响应 `2/8 MiB`、provider-region 日 `1 GiB/192 requests`、root high/low
  `512/256 MiB`、min-free `8 GiB`、cleanup `100 rows/64 MiB`、hold `256 MiB`。0075 新增日账本，
  identity/provider transport 写前必须原子预留预算并检查 root/free disk；关闭态发布后还要重新核对。

# 2026-08-28 PR #108 全量复审返修候选，生产仍未改动

- 首轮全量代码复审发现 11 个发布阻断：当日赛果错误强制 official、终态 roster 不守恒、纳管覆盖
  lifecycle mode/pause、出马表重置退赛、批量响应未共享、缺 immutable racecard revision、缺 T+30
  告警、关闭态审计误报、赛果 apply 未重验来源合同、赛后停止主来源抓取，以及 lifecycle/event 锁序相反。
- 当前候选已逐项修复并补覆盖：当日无 terminal marker 只记录 provisional；赛后 7 天走受审
  `/v1/results/{race_id}`；终态要求完整 runner 全双射；批量快照 single-flight/150 秒 TTL；racecard
  revision、来源合同重验、lifecycle 保留语义和普通队列 T+30 incident 均已落地。
- 人工复核另外补上两项边界：data-sync racecard apply 在事务内重验 source expiry/registry；仅赛果
  fallback 可用完整马号+规范化马名双射原子建立来源 runner identity，不再要求赛前已有第三方 ID。
- PR #108 仍未合并，生产仍运行 `2833558a…` / migration `0073`；14 条历史过期 claimed 尚未收口，
  新写入开关保持关闭，`race_live=7543` 不触碰。候选仍须完成最终组合回归、独立复审、push 和生产
  备份/精确 claim 修复，之后才进入最终上线确认。
- 返修后的完整赛事数据组合门禁为 SQLite `190/190`、PostgreSQL `214/214`；后者同时覆盖 R0 与
  racecard 并发。Django check、migration drift、compileall、三份 Compose、JSON/digest、diff 与 literal
  secret pattern 均通过；全开配置且运行开关全关的审计返回 `ready/would_write=false`、route drift 为空。
