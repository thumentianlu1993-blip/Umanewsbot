# 赛事时间、出马表与赛果自动同步发布与回滚方案

## 1. 当前停点

- 方案 worktree：`/Users/mentianlu/.codex/worktrees/race-data-automation-plan/umanews`。
- 分支：`codex/race-data-automation-plan`。
- 基线：`origin/main@2833558a6a2d67b7dc9816b53ea8ad5d580eb56c`。
- 当前只创建方案文档；没有代码、migration、联网、生产写入、commit、push、PR 或部署。
- 所有生产自动化开关仍按只读快照保持关闭；现有人工结果审核调度不变。

## 2. 发布单元

发布顺序固定：

```text
R0 queue/registry/checkpoint
-> R1 race time
-> R2 racecard
-> R3 result revision shadow
-> R4 lifecycle/public/SLO
```

每个单元独立 PR、独立 review、独立关闭态部署和回滚；不能把五个单元合并成一次高风险启用。

## 3. 阶段 0：方案评审

进入实现前必须：

- 独立 reviewer 核对架构、模型、迁移、Celery、来源、并发、测试、发布与回滚；
- actionable findings 清零；
- 冻结 plan fingerprint、review 结论与最新 `origin/main`；
- 若 review 改变产品范围、来源权威、30 分钟口径或队列方案，回到 G1。

## 4. 阶段 1：关闭态部署

每个发布单元均执行：

1. 只读盘点生产 revision、migration、服务、队列、active/reserved/scheduled、claims、磁盘和锁；
2. 冻结 exact commit/image/config/migration/release manifest；
3. 创建 PostgreSQL custom-format 备份，验证非空、0600、SHA 和 `pg_restore --list`；
4. 记录旧镜像和精确 rollback target；
5. 部署代码/migration，但保持所有 `RACE_DATA_SYNC_*` 新旧开关关闭；
6. 验证 Django、migration、Compose、web/worker/Beat、healthz 和运行 revision；
7. flag-off smoke 必须为 selector 0、network 0、business write 0、public change 0；
8. `race_live=7543` 保持不变；新 `race_sync_v2` 队列从 0 开始；
9. 发布前 `run_application_release.sh` 必须已把 `race_sync_v2_worker` 纳入 frozen intent、完整 Celery
   node drain、stop/restore；`manual_release.sh`、`resume_stopped_release.sh`、rollback 与 immutable-control
   resume 的 service catalog 同步更新并通过 running/stopped/probe-failure/interrupted/old-image tests。
10. 基于 live free disk、现有约 45GB backups、抓取增长率和 hold 上界冻结 artifact daily quota、root
    high/low water 与 min-free；未取得 sizing proof 时 network admission 保持关闭。
11. migration 后只读证明历史 projection owner 原值不变、`live` 未自动转为 `data_sync`；旧候选 image 对
    `data_sync` owner 的兼容 smoke 必须 fail closed，不能把未知值当 unmanaged/live。

该阶段属于 G2 精确发布包；不得顺带启用真实网络或自动公开。

## 5. 阶段 2：离线与只观察

1. 使用固定 fixture 验证五地区 time/racecard/result adapters；
2. 只启用 selector 与 observation，network 仍关闭；
3. 使用受审 synthetic due events 验证 cadence、claim、generation、checkpoint 和 verifier；
4. observation artifact、DB ledger 和公开业务表必须证明零越权写入；
5. 关闭后一个 selector 周期内无新 dispatch。
6. 对生产当前 99 场运行只读 enrollment census，逐场给出唯一分类且总数严格等于 99；本阶段不 apply。
7. 对 owner acquire/replay/rotate/disenroll 与单独 reviewed `live -> data_sync` transfer manifest 做离线/影子
   dry-run；未获单独 transfer 授权时所有既有 live owner 保持冲突、零写。

## 6. 阶段 3：真实网络 shadow

这是首次 G3：发布包必须精确列出 provider、region、data kind、cohort、request budget、registry SHA、
proof digest、有效期和 artifact root。

shadow 至少连续 7 天且覆盖至少 10 场终态赛事：

- 允许受限来源网络和 observation/artifact/metric 写入；
- schedule/racecard/result canonical apply 与 public 全部关闭；
- 与公开官网/API/可信第三方和现有人工 review bundle 对照；
- 每日输出 identity coverage、datetime coverage、roster completeness、terminal detection、冲突、
  请求预算、artifact 容量、错误率和预计 T+30 四分指标；
- 任一跨 event identity、secret 泄露、请求越界或 parser schema drift 立即关闭该 provider。

shadow 晋级门槛：

- identity 误绑 0；
- source route 明确或 route_missing 100% 可解释；
- T-24h datetime coverage >=95%；
- T-6h racecard freshness P95 <=15 分钟；
- terminal detection cadence 足以满足公开 P95/P99；
- 无 manual lock override、重复 revision 或未审计 payload。
- 独立 reference snapshot 能区分“上游 T+30 已终态但系统漏检”和“上游确实未终态”，alert 不计结果成功。

## 7. 阶段 4：日本重点赛事 canary

首发范围：JRA 已发布 P0/P1/重赏 2–4 场。先从 99 场 census 生成 exact enrollment manifest；只有同时
命中已批准 standing policy、data-sync enrollment 与独立 active lifecycle membership 的 event 才可进入。

按能力分三次启用，不能合并：

1. time apply：允许时间/时区字段写入与 reschedule，racecard/result public 仍关闭；
2. racecard apply/public：允许 runner revision 投影，result 仍只 shadow；
3. result confirmed/public：允许完整终态赛果自动更新与 lifecycle 协调。

每次启用前重新冻结 event/source identity、baseline、registry、generation、开关和 rollback manifest。
每场完成后验证：

- DB event/runner/result/revision/field ledger；
- 完整“名次 + 马号”序列、source label 和页面状态；
- independent upstream terminal availability、terminal detection、confirmed publication、blocked alert
  coverage 与 terminal-to-public 延迟；
- task/queue/checkpoint/claim 归零或进入 correction watch；
- 新闻和 QQ side effect 为 0。

晋级要求：reference 证明 T+30 前终态完整的 canary，confirmed/publication rate >=95%，错误结果 0；
确实 unavailable/blocked 的 alert coverage >=99%。地区扩大后前一指标升至 >=99%。

## 8. 阶段 5：地区扩展

顺序建议：

```text
日本 JRA 全部已发布重点赛事
-> 英国
-> 法国
-> 美国
-> 中国香港
-> 日本 NAR
-> 所有已发布且身份/route/time 合格赛事
```

顺序是 rollout 建议，不是来源置信度排名。每个地区先 2–4 场 canary，达到相同指标后独立扩大；
某地区失败不阻塞已通过地区，也不能借其他地区证据自动放行。

没有确定性 identity、有效 IANA zone、有效 route 或时间的 event 只进入 discovery/observation，不能
自动 apply。每小时 future census 只能把命中未过期 standing policy 的新赛事纳入小批 manifest；策略外
赛事只 proposal。新增 provider、付费套餐或扩大真实网络预算需要新的 G3 精确范围。

## 9. 生产监控

发布后持续观察：

- web/ordinary worker/Beat/race_sync_v2_worker 状态与 image revision；
- `celery`、`race_sync_v2`、遗留 `race_live` queue depth；
- due/claimed/dispatched/replayed/stale/circuit；
- provider request、错误、预算、schema/contract 到期；
- future datetime/racecard/result coverage；
- upstream terminal availability、terminal detection、confirmed publication、blocked alert coverage、
  terminal-to-public、correction latency；
- DB/public verifier、manual lock 和 identity incident。

不能用 HTTP 200、task exit 0 或 queue 下降单独证明端到端成功。

## 10. Kill switch

止血顺序按影响最小原则：

1. 关闭单 provider；
2. 关闭单 region/cohort；
3. 关闭 result public；
4. 关闭 result/racecard/schedule apply；
5. 关闭 network；
6. 关闭 selector；
7. 停止 `race_sync_v2_worker`。

关闭后等待 active task 自然退出，并验证一个 selector 周期内新 dispatch/write 为 0。不得使用
`docker compose down`，不得清空 Redis 队列；旧 task 由 generation/CAS 失效。

若 release 中断，恢复必须使用该 attempt 的 mode-600、compose/action/HEAD 绑定 frozen intent；不得手工
`up` 新 worker。intent 不可信时保持新 worker stopped 并告警。回滚到不含新 service 的旧 target 时，
immutable control catalog 明确记录 `service_absent`，不得把 probe failure 当 absent。

## 11. 行为回滚

- 关闭相关 provider/cohort/data kind/public flag；
- 冻结当前 observation/revision/field decision/checkpoint/incident，禁止删除审计事实；
- 核对公开 current/LKG pointer 和 event status；
- 对错误字段或结果生成 exact reverse manifest，绑定 event、before/current baseline、revision 和 SHA；
- dry-run 后在单 event 事务回退 canonical projection，append correction audit；
- 独立 verifier 与公开页面核对后关闭 incident。

赛果 correction 优先于删除；已公开错误结果不能由 cron 自动覆盖或静默回滚。

## 12. 代码与 migration 回滚

- 回到旧代码前先关闭 selector/network/apply/public/lifecycle integration；
- 恢复精确旧镜像和 Compose 配置，不重用浮动 tag 作为证据；
- additive nullable schema 默认保留，旧代码关闭态必须可读；
- 只有旧版本无法与新 schema 共存且审计数据已被保全时，才使用受审 reverse migration；
- 数据库级损坏才考虑已验证备份恢复，并作为独立高影响发布包授权。

## 13. 完成定义

只有以下全部成立才可宣称功能完成：

- 所有五个发布单元已合并并通过独立 review；
- 至少日本、英国、法国、美国、香港/NAR 的目标 cohort 分别验收；
- future datetime/racecard coverage 和结果 SLO 达标；
- 当前 99 场均有稳定 enrollment 分类，之后新 published event 的 standing-policy 纳管链已验收；
- 30 天内没有 P0 数据错误、跨 event 写入或无证据公开；
- kill switch 和 reverse manifest 至少完成一次受控演练；
- current_state、decisions、deploy runbook、release evidence 与生产运行态一致。
