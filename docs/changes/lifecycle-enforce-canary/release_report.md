# lifecycle enforce canary 生产发布报告

## 发布身份与范围

- PR：[#100](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/100)
- merge revision：`a7e3783ff7d188481cecd421cd2595f43e9a706b`
- 生产镜像：`sha256:afa0379f04d1ca8d0115f4ef724fdc9d08a4e34157682c2f657a6fd59f0f441f`
- release 目录：`/opt/umanews-release-a7e3783f-PR100-20260810/umanewsbot`
- 范围：仅 event `186,187` 的 lifecycle enforce canary；不含 migration、provider、race-live、
  新闻门禁、QQ 或赛果写入。

## 关闭态部署与 artifact

- 先将生产收敛为 lifecycle `false/off`，补齐但保持为空的 canary SHA/IDs 配置键；从隔离 release
  完成 web/worker/Beat 重建。三服务 revision、image、workdir 一致，web healthy，migration plan 为空。
- 生产只读生成 artifact：
  `/opt/umanews-release-a7e3783f-PR100-20260810/umanewsbot/runtime/lifecycle_enforce_canary/`
  `pr100-events-186-187-20260810/manifest.json`。
- manifest raw SHA-256：
  `eacffda63284e25b59c3efa5815d138a562c10e86eec7fe5ed1ed41219d303fc`；content SHA-256：
  `c06e5a3ec74d079b0a4e631dacc43d1dd9d4c081d99fda4462e9aec4a5d18950`。
- apply 截止为 `2026-08-11T15:04:38.661279Z`；runtime 截止为
  `2026-08-14T11:25:00Z`。关闭态 dry-run 返回 `outcome=would_apply events=186,187`，前后数据库
  指纹一致。

## G3 apply 与启用

- 用户 G3 授权精确绑定上述 revision、raw SHA 与 event `186,187`。写前等待两个无关新闻抓取任务
  自然结束，未 revoke、terminate 或跳过排空。
- 写前 PostgreSQL custom-format 恢复点：
  `/opt/umanewsbot/backups/db/pre-lifecycle-enforce-canary-20260810T153347Z.dump`，
  `421435241` bytes、mode `0600`、`pg_restore -l` 计数 `1308`，SHA-256
  `9265fd9e6619cee3d036f5db2da5eaecdede532694f5453338584c504a53a078`。
- shared-lock promotion 在严格 `false/off` 下返回 `outcome=applied events=186,187`。写后只有两场
  control 为 `enforce/inactive`，全局仍为 `false/off`，赛事仍为 `scheduled`，applied transition 为
  `0`，且恰有一条绑定 raw SHA 的 promotion `OperationLog`。
- mode switch 在 `active=0 / reserved=0` 后执行，按 Beat/worker stop、web healthy、inactive verify、
  worker coherence、原子 activate、active verify、Beat-last 完成。最终为 `true/enforce`，canary
  信任根为上述 raw SHA 与 `186,187`；共享 activation ID 为
  `fb222bb197952937540f061eff82e19e18a43e37d5b40505181c213dfe59010e`。
- active verifier 返回 `outcome=verified_active events=186,187`。其他 enforce control 为 `0`，
  race-live scheduler/monitor 仍为 false，race-live worker 未运行，部署锁已释放。

## Smoke 与线上验收

- 用户的精确 G3 覆盖手工 scanner smoke，因此在原 rollout 候选“不另发手工 scanner”之外，实际
  执行了一次进程内 smoke 和一次真实 Celery 队列 smoke。两次均返回
  `enabled=True / claimed=0 / dispatched=0`；队列 task ID 为
  `f9dfc0ee-0664-42e8-bce3-dc8c7432cb0f`，目标数据库前后指纹一致。
- Beat persistent scheduler 已自动执行生命周期 scanner：`last_run_at=2026-08-10 23:40:00+08:00`、
  `total_run_count=1`、schedule=`*/5 * * * *`。
- event 186/187 仍为 `scheduled`，control 均为 `enforce/active`、无 claim，applied transition 为 `0`；
  下一次刷新分别为 `2026-08-11T08:05:00Z` 与 `2026-08-13T10:55:00Z`。
- Django check、空 migration plan、runtime coherence、Celery ping、HTTP healthz 与两场公开详情页均
  通过。重建 web 的瞬间 `2026-08-10T15:37:08Z` 有一次 Googlebot 首页请求收到 502；从
  `15:38:00Z` 起复查为 `0 Traceback / 0 lifecycle_canary_scanner_blocked / 0 502`，未触发回滚。
- 当前仅 HTTP 接入；HTTPS listener 仍未在 Nginx 配置中启用，不属于本次 lifecycle change。

## 后续观察时间

- event 186：T=`2026-08-11 16:05`、T+30=`16:35`（北京时间）。
- event 187：T=`2026-08-13 18:55`、T+30=`19:25`（北京时间）。
- 到点核对公开状态、applied transition 的 manifest/activation provenance、详情与日历缓存、Beat/worker
  日志；任何范围外 applied、重复 applied、状态/审计不一致或 canary verifier 失败均立即收敛到
  `false/off`，不自动反向修改已经合法推进的状态。
