# 准实时赛前 racecard/off time 同步发布报告

## 发布结论

2026-07-18 已按最新成功代码 review 后的用户授权发布冻结版本。代码、容器挂载、来源
registry 和受控 prepare 能力已进入生产；调度、真实 runner 和公开读取保持关闭。首个英国
event `924` prepare 因严格身份匹配返回 `racecard_not_found` 而 fail closed，没有生成
initializer manifest，也没有写入赛事时间、出马表、live tracking 或赛果。

## 冻结版本与镜像

- reviewed parent：`234358979dea3620d04445bb569b30e4a5b2fe8a`
- release commit：`6646302b80c90cf406075516ab4812f2f4ebee18`
- review fingerprint：`fdd1ec6f322af250adb7c2464d01090f8a04d3a90e4a268bf4a3aab66896453f`
- approved content manifest：`60638fe18d35fdee98743c02fe73aae91f8a58b58e60fcd05ae86059e38625fe`
- source tree：`d163a2a582a939cb2612436f9b87549ddd4ed6fc`
- clean source archive SHA-256：`34af751dcb568095fb1489288db4b0110606d98d3c858996a1ddc47120dcdf5b`
- production image：`sha256:7f188f8fc85979ad6df3504c49e42aed4e0c41696f64301b2a33c6c888722981`
- registry SHA-256：`60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`

发布前用相同 scope 重算 fingerprint，与 review 基线逐字节一致；显式 stage 后 index content
hash 与 approved content hash 一致，commit parent 精确等于 reviewed parent。分支和
`origin/main` 均已验证指向 release commit。

## 恢复点

- 数据库备份：`/opt/umanewsbot/backups/db/pre-racecard-6646302b-20260718_105233.dump`
- 大小：`196,919,649` bytes
- 权限：`root:root 0600`
- SHA-256：`6bdda3152cb3ee6a92fc774989dde7fc94614149066e01e4bb746d85fb9f7882`
- 格式验证：独立 PostgreSQL 容器执行 `pg_restore -l` 通过
- 环境备份：`/opt/umanewsbot/.env.backup.pre-racecard-6646302b-20260718_105233`
- 回滚标签：`umanewsbot:rollback-pre-racecard-6646302b-20260718_105233`
- 回滚 image：`sha256:111dbe46ba7a7024632ba2ca7c57c387b19ab39861f0147421a0245d08c38d7a`

## 部署与运行态验证

- 本变更无 migration；候选镜像执行 Django check、`migrate --check`、
  `makemigrations --check --dry-run` 均通过。
- 镜像内 racecard sync + initializer v2 目标测试 `20/20` 通过；发布前完整相关验证为
  SQLite `203/203`、本地 PostgreSQL `6/6`。
- web、普通 worker、`race_live_worker`、Beat 均运行 production image；两个 Celery 节点
  ping 成功，web healthy，Nginx 已刷新容器地址。
- 内部、`umafans.run` 和 `www.umafans.run` 的 HTTP `/healthz/` 均为 200。
- 只有 `race_live_worker` 挂载 `/run/secrets:ro` 和
  `/run/race-live/racecards:rw`；其余 app service 不挂这两类目录。
- `RACE_LIVE_SCHEDULER_ENABLED=false`、`RACE_LIVE_RUNNER_MODE=disabled`；
  `race_live` 队列为 0。普通 worker 在 Beat 恢复后处理既有新闻 crawl，专用 live worker
  保持空闲。
- 生产赛事总量为 `9,867 events / 100,132 runners / 91,897 results`；live
  control/tracking/source/observation/revision/publication/incident 均为 0。

## 受控来源与 prepare 证据

执行前只读核对 The Racing API 条款和 BHA Results 官方路由，均为 HTTP 200；本次绑定：

- 既有生产来源 proof manifest：
  `5d6e458b50b96151dc0d7d8559d24776d70af60ef78236c74b37be9edba2bbae`
- The Racing API 条款响应 SHA-256：
  `657aaaaeeeaac27796b6c74c44b300f63be3191b5c497aa6f9a1b8a4879c7e81`
- BHA Results 路由响应 SHA-256：
  `4bc3f9a6486bc373a27289dac8adf9a1f3180eff873f8e378577589bdc0fade7`
- evidence/policy 上限：`2026-08-16T16:00:00+00:00`

prepare run：
`/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-20260718T030337Z`

- 目标：英国 event `924`，Newbury，2026-07-18，Group 3。
- today GB endpoint：HTTP 200，`215,648` bytes，`1,419 ms`，response SHA-256
  `31c547999f374f78512fa731db622338808fc92ab597294afc7646c97edc8e45`。
- tomorrow GB endpoint：HTTP 200，`76,663` bytes，`1,220 ms`，response SHA-256
  `26c7beccb342677a62a0cb42887d51191a844efccc3aba25d1c048456dbae9b3`。
- 结果：`completed=false / requested=1 / matched=0 / blocker=racecard_not_found`。
- run 目录权限 `0700`，`report.json/requests.jsonl` 权限 `0600`；report SHA-256
  `bd7a19f8867df38e21e88ae2db465f9b6c5be30ad3b520e6b7fa988c9f5ae46a`，request ledger
  SHA-256 `78fef17cc843d8f83588a716dffc7fab0de56a740b88edc2a5510e0b99afcf2d`。
- 没有 `manifest.json`，因此没有执行 initializer dry-run/apply/verify。
- prepare 只新增 `1` 条 `RaceLiveHostBudget` 控制面记录；赛事业务事实和全部 live 事实表
  保持不变。

## 后续门禁

下一步先审核 event `924` 与 TRA 当日 racecard 的覆盖、赛事名和 alias。若确认为别名缺口，
必须通过独立受审的数据修复补齐，再使用新 run-id 重跑 prepare；若来源没有该场，则记录
覆盖缺口并选择另一个明确赛事。禁止放宽精确匹配、猜测 off time、复用 blocker artifact
或手工构造 manifest。只有成功 run 的完整 artifact 经单独批准后，才可执行 initializer
dry-run/apply/verify；scheduler、runner 和 provisional public 仍需后续独立门禁。
