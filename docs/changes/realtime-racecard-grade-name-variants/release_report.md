# 英国 racecard Group 后缀精确匹配发布报告

## 发布结论

> 历史快照提示：本节记录首次 HTTP 429 run，不代表当前状态。退避重试已经成功生成
> manifest；当前权威状态与唯一操作门禁见文末“退避重试最新结果（当前状态）”。

> 最新状态提示：上述权威状态指针也已被后续执行取代；当前唯一权威状态与操作门禁见文末
> “单赛事 TRA shadow runner 启动检查（当前状态）”。下文 runner disabled 仅为早期历史
> 快照；当前 live worker 已启用 TRA runner，但 scheduler 仍为 false。

> 当前状态提示：runner 启动检查也已被后续获准的有界轮询取代；当前唯一权威状态与操作
> 门禁见文末“event 924 有界 shadow 轮询（当前状态）”。首个 shadow result 已取得并停止，
> scheduler 和公开模式仍未开启。

冻结代码已部署生产，Group 后缀匹配能力进入运行镜像；scheduler、真实 runner 与公开门禁
继续关闭。event `924` 的新受控 prepare 因 tomorrow GB 请求 HTTP 429 fail closed，没有
manifest、initializer 或业务事实写入。

## 冻结身份

- review fingerprint：
  `f9b40a0ec60f3a75dbfcbaa36739e564575def8e5c88f56833b71419f6cb92f8`
- reviewed parent：`12d76e61850f1f847aba13ac1c07004040191728`
- approved content manifest：
  `aa92ba27a17592287c101aa16380fb80e1293a2f5e4ddf9510c35ed2b94b87f7`
- release commit：`ebab4aa8e4e855d644771584c010fa6b07b9992b`
- tree：`f9a04eccc5bbda31a2619f3642e32c51275f0cc2`
- source archive SHA-256：
  `75939622bb5a31b524fc7e339109c64565ef038f8ead1734d20905ece5a937b5`
- production image：
  `sha256:4443a9c418dd696c7faa4afec0ae34551bceec2e85d6c917fa27de706fe155dc`

## 恢复点

- 数据库：
  `/opt/umanewsbot/backups/db/pre-racecard-grade-ebab4aa8-20260718T090735Z.dump`
- 大小/权限：`198,033,727` bytes，`root:root 0600`
- SHA-256：`17ba9ccbe0e28fe765f0f449c78452664f39f204011a1b8decb873240afd3db0`
- 格式：`pg_restore -l` 通过
- 环境：`/opt/umanewsbot/.env.backup.pre-racecard-grade-ebab4aa8-20260718T090735Z`
- 回滚标签：`umanewsbot:rollback-pre-racecard-grade-ebab4aa8-20260718T090735Z`
- 回滚 image：
  `sha256:7f188f8fc85979ad6df3504c49e42aed4e0c41696f64301b2a33c6c888722981`

## 部署验证

- 镜像为 AMD64，OCI revision/tree 与生产 checkout 一致。
- registry SHA-256 为 `60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`。
- Django check、migration check、model drift、镜像 racecard sync `20/20` 通过。
- web、普通 worker、Beat、`race_live_worker` 均运行新镜像；内外 healthz 为 200。
- 只有 live worker 挂 secret ro 与 artifact rw；其余 app service 无这两类挂载。
- scheduler false、runner disabled、live queue 0、publication policy/allowlist 0。
- 生产保持 `9,867 events / 100,132 runners / 91,897 results`，全部 live fact 表为 0。

## 受控 prepare

run：
`/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-grade-fix-20260718T091135Z`

- today GB：HTTP 200，`215,645` bytes，`1,379 ms`，response SHA-256
  `e0e32e0df476df8949a9a7b5be6a60db0be9e527b5904c9d63a4da8514274efd`。
- tomorrow GB：HTTP 429，`47` bytes，`374 ms`，response SHA-256
  `e4c164264df24ba41848041ac37a930dd9157e3b66081293922c1d354dc091e9`。
- 结果：`completed=false / request_count=2 / blocker=http_429`。
- 目录 `0700`；`report.json/requests.jsonl` 为 `0600`。
- report SHA-256：
  `3e37ecef79545aae09fa4609b89cd246a383ff4bf20c8ea268b2d3b242f1d91b`。
- requests SHA-256：
  `7c0ca959e9a70f10374a4f4713ee424494457e67635f0878bd4d191111a3d5d5`。
- `manifest.json` 不存在，initializer 未执行。
- HostBudget 只记录一次 `http_429`；业务/live 事实零变化。

## 下一门禁

> 历史门禁提示：本节要求的联网重试授权已完成，不得据此再次发起 prepare。当前只允许在
> 对文末精确 manifest SHA 单独授权后进入 initializer dry-run/apply/verify。

本 blocker artifact 不得复用或手工补 manifest。退避后新 run 会再次产生最多两个真实请求，
需要用户新的显式联网重试授权；若以后得到成功 manifest，仍须单独审核后才能决定
initializer dry-run/apply/verify。

## 退避重试最新结果（当前状态）

用户已显式授权 event `924` 退避后重试。上述 HTTP 429 门禁是首次 run 的历史记录；有效
联网 run `production-racecard-gb-924-grade-retry-20260718T093207Z` 已成功生成精确
manifest，initializer、shadow 与公开门禁仍未执行。

- 执行前 UTC `2026-07-18T09:29:51Z`，HostBudget 的
  `next_allowed_at=2026-07-18T09:11:52.789191+00:00` 已过去，circuit 未打开。
- 一次使用旧参数别名的命令在 argparse 阶段退出，没有发出网络请求，也没有创建对应
  artifact；随后使用当前命令的正式参数名执行唯一一次有效联网重试。
- 有效 run：
  `/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-grade-retry-20260718T093207Z`
- today GB：HTTP 200，`215,646` bytes，`1,425 ms`，response SHA-256
  `4b4385a77f6766160d70777c62110d438d37a9107c7578ad86026bf9cc859b1d`。
- tomorrow GB：HTTP 200，`76,616` bytes，`1,184 ms`，response SHA-256
  `14364e390bfebb033633d1b6b8b3fc8021ffbab52dffb0d18605fabdcfba6128`。
- 结果：`completed=true / request_count=2 / blockers=[]`。
- manifest SHA-256：
  `ee9d0d43ac52c1678ddce61dbd7c4a6b0c0630eb02d2dd6fd8e43cfc5fcd1432`。
- report SHA-256：
  `96cb3acb3ef11c124dbd370226b3252ef31297e57ad4cb32da84443aa63fdc2d`。
- requests SHA-256：
  `cf45c566d9dc3bea64eaff27cf7a81a92942ebf834eae880a067b1066e35dd32`。
- 目录 `0700`；`manifest.json/report.json/requests.jsonl` 均为 `0600`。
- manifest companion hashes 与宿主重算一致；唯一事件为 event `924`、
  external race `rac_13000002795`、开赛时间
  `2026-07-18T15:02:00+01:00`、`7` 匹 declared participant，tracking state 为
  `racecard_ready`。字段审计没有发现 raw、凭据、第三方 rating 或 comment。
- 执行后 event `924` 仍为 `scheduled`，其 `race_datetime/local_start_time` 仍为空，
  `updated_at` 未变化；`9,867 events / 100,132 runners / 91,897 results` 与全部 live
  事实表守恒，policy/allowlist、live queue、one-off 仍为 0。
- HostBudget 恢复为
  `consecutive_failures=0 / last_error_code="" / circuit_open_until=null`；站内与公网
  HTTP healthz 为 200。

当前唯一门禁是对精确 manifest SHA
`ee9d0d43ac52c1678ddce61dbd7c4a6b0c0630eb02d2dd6fd8e43cfc5fcd1432`
取得单独授权，再执行 schema v2 initializer 的 dry-run/apply/verify。当前不得复用旧
blocker artifact、启动 scheduler/runner 或公开。

## initializer 执行结果（当前状态）

> 状态更新：上一节的 initializer 授权门禁已经完成并消费，不得重复 apply。当前仍未授权
> runner、scheduler 或公开。

- 用户授权的精确范围：event `924`、manifest SHA-256
  `ee9d0d43ac52c1678ddce61dbd7c4a6b0c0630eb02d2dd6fd8e43cfc5fcd1432`。
- 执行前 checkout/OCI revision 为
  `ebab4aa8e4e855d644771584c010fa6b07b9992b`，image 为
  `sha256:4443a9c418dd696c7faa4afec0ae34551bceec2e85d6c917fa27de706fe155dc`；
  manifest、companion、event baseline、空历史租约、队列和关闭开关无漂移。
- 写前 backup：
  `/opt/umanewsbot/backups/db/pre-race-live-init-924-ebab4aa8-20260718T100040Z.dump`，
  `198,147,827` bytes、`root:root 0600`、SHA-256
  `e57218e77a1457c2aca7053d962d09b38942d4ad7cd9534185713236a61370fe`，
  `pg_restore -l` 通过。
- dry-run：`ok=true / error_count=0 / event_count=1 / participant_count=7 /
  replayed_event_count=0`。
- 单次 apply：`ok=true / error_count=0 / event_count=1 / participant_count=7 /
  replayed_event_count=0`。
- 独立 verify：`ok=true / error_count=0 / event_count=1 / participant_count=7 /
  replayed_event_count=0`。
- event `924` 写入 UTC `14:02` / London `15:02`，保持 `scheduled`；live owner 为
  generation 1，tracking 为 `racecard_ready` 且 claim 为空。OperationLog ID 为
  `105221`。
- 写入 `1` 个 approved supplemental TRA source、`7` 个 approved participant、
  `7` 个 participant identity、`1` 个未发布 racecard revision 和 `7` 个 declared item；
  四层 policy 均为 shadow。
- legacy result、result pointer/revision、observation/evidence、publication、official
  marker/evidence/incident 均为 0。公网详情只显示 `15:02`，7 匹 shadow participant 与
  暂定/正式/更正赛果标识均未泄漏。
- scheduler false、runner disabled、live queue/one-off 为 0，站内和公网 HTTP healthz
  为 200。

下一门禁是另行授权 event `924` 的 The Racing API 单赛事 shadow runner 启动检查；该步骤
仍不得扩大到公开模式或其他赛事。

## 单赛事 TRA shadow runner 启动检查（当前状态）

> 状态更新：上一节的 runner 启动检查授权已经完成。scheduler 仍关闭，尚未授权自动或有界
> 后续轮询。

- 用户授权边界：仅 event `924`、The Racing API shadow runner、scheduler false、公开
  不变、不扩展赛事。
- 启动前 tracking/allowlist ID 均只有 `[924]`，四层 policy 全为 shadow，赛果事实全为 0。
- shadow 写前 backup：
  `/opt/umanewsbot/backups/db/pre-race-live-shadow-924-ebab4aa8-20260718T102543Z.dump`，
  `198,234,122` bytes、`root:root 0600`、SHA-256
  `bc06babe341e25a45ba097aaed157c7530994e06edebc497f612642d30676207`，
  `pg_restore -l` 通过。
- `.env` backup：
  `/opt/umanewsbot/.env.backup.pre-race-live-shadow-924-ebab4aa8-20260718T102543Z`，
  `root:root 0600`，与改动前 `.env` 逐字节一致。
- 只把 `RACE_LIVE_RUNNER_MODE` 改为 `the_racing_api_free`，保持
  `RACE_LIVE_SCHEDULER_ENABLED=false` 并只重建 live worker；镜像 revision/tree 和
  registry SHA 未变。
- worker `celery@81ec88d9e165` ready。首次定向 ping 在启动完成前超时，随后 ping、
  active/reserved 正常。
- event `924` 只在合法 next poll 后 claim；claim time
  `2026-07-18T10:33:03.874928Z`，owner generation 1、claim generation 1、TTL 120 秒。
- 唯一 task `7ba0699c-02f1-4b7d-864e-ed5cb7127ff0` 经实际 `race_live` 队列执行，Redis
  result backend 为 `SUCCESS / processed=false / reason=pre_off_wait`。
- claim 已释放，checkpoint 为 `pre_off_wait`，next poll 为
  `2026-07-18T11:33:04.049149Z`。HostBudget 未变，未发结果 API 请求。
- observation/result revision/legacy result/publication/marker evidence/incident 全为 0；
  queue、active/reserved、one-off 为 0。公网详情和 healthz 为 200，无 participant 或
  result shadow 泄漏。
- 当前只有 live worker runner enabled；web/普通 worker/Beat runner disabled，所有服务
  scheduler false。

下一门禁是对 event `924` 的有界单赛事 shadow 轮询窗口取得单独授权。该轮询必须遵守每次
数据库 `next_poll_at`、共享 HostBudget 和单请求上限，直到首次 shadow result 或明确截止；
不得打开全局 selector、扩展其他赛事或公开。

## event 924 有界 shadow 轮询（当前状态）

> 状态更新：上一节要求的单独授权已经取得并消费。首个 shadow result 已到达，控制循环
> 已停止；本节是当前唯一权威状态。

- 用户授权边界为 event `924`、scheduler false、逐次遵守数据库 `next_poll_at`、直到首个
  shadow result 或明确截止，不扩展赛事、不公开。
- 写前备份
  `/opt/umanewsbot/backups/db/pre-race-live-window-924-ebab4aa8-20260718T111221Z.dump`
  为 `198,273,152` bytes、`0600`，SHA-256
  `efa68a76f7236f7454fe9119df601ff4f1e4fae9d2b8040fc09aa9cf28efd13b`，
  `pg_restore -l` 通过。
- 临时循环只按 event `924` 执行单赛事 claim/dispatch。首轮误读 claim 返回对象字段，
  在 task 投递前退出；已写入的 generation 2 claim 未重复领取，而是在 TTL 内原样投递
  task `a5e03b1a-6c7b-409b-ba16-096e575b63f4`。改用真实 `claimed` 字段后恢复。
- generation 2–14 共 `13` 次 `pre_off_wait`、零 API 请求；generation 15–18 在
  `14:02:09Z` 至 `14:11:34Z` 的四次单请求均为 `result_not_found`。
- generation 19 task `9615a5f6-bc5c-4203-931d-32990b07432b` 于
  `14:14:42.301344Z` 返回 `processed=true /
  the_racing_api_shadow_applied / revision_id=2`，距预计开跑 `12` 分 `42.301` 秒。
  控制循环随即停止，未执行 next poll `14:24:42.301344Z`。
- observation ID `1` 为 provisional、licensed API automation、parse warning 0；
  normalized SHA-256
  `4d2fa8c03ad3ae735700bd72291f822ea53e75449f90f3ad568392e2995dccc2`。
  revision ID `2` 含 `7/7` finished item、完整 1–7 名次、evidence 1，且
  `published_at=null`。
- tracking 为 `provisional_result / shadow_applied`，claim 空、failures 0。tracking /
  allowlist 仍为 `[924]`，四层 policy 仍为 shadow；legacy result、publication、official
  marker/incident 全为 0。
- scheduler 仍为 false；live queue、active/reserved、one-off 为空。公网详情和两个正式
  healthz 为 200，页面无 shadow participant 或赛果标识。

本授权已经完成并关闭。下一步只能是先审核这份真实 shadow evidence，再对后续复核或
provisional public 灰度取得新的精确授权；不得直接执行后续探针、打开 scheduler 或扩展赛事。
