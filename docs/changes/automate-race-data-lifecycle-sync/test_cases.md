# 赛事时间、出马表与赛果自动同步测试用例

## 1. 测试原则

- R0–R4 每个切片先取得真实 RED，再实现 GREEN；缺方法、语法错误或测试环境错误不算 RED。
- 单元/集成测试禁止访问生产数据库、Redis、真实队列、凭据或第三方服务。
- 并发、`select_for_update(skip_locked)`、唯一约束、advisory lock 和 migration 必须在 PostgreSQL 16 验证。
- 真实网络 proof、生产 shadow 和公开灰度属于 rollout 门禁，不由离线测试替代。
- 每项错误必须证明 fail closed：没有“部分成功但未记录”的中间状态。

## 2. R0：调度、registry 与队列隔离

1. 所有总开关关闭时，selector 在 DB/文件/网络访问前返回 disabled。
2. selector 每分钟运行，只有 `next_poll_at <= now` 且 cohort/region/provider/data kind 允许的 tracking 入选。
3. due 排序固定为 `(next_poll_at,event_id)`，batch 截断稳定。
4. 两个 selector 并发只产生一个有效 claim 和一个 provider task。
5. provider task 只路由到 `race_sync_v2`；不能路由到 `race_live`、`celery`、邮件或 QQ 队列。
6. task 只携带 event/generation/token/plan hash，不接受任意 URL、文件路径或 shell 参数。
7. 旧 generation、过期 lease、错误 token、错误 plan hash 均零业务写退出。
8. 新队列 smoke 不消费、删除或查看为可执行对象的 7543 条遗留 `race_live` 消息。
9. per-provider checkpoint 独立 due/failure/circuit；父 next due 等于有效 checkpoint 最小值。
10. A provider timeout/429 不阻止 B provider；重投只 replay observation，不重复 revision。
11. host budget 在多 worker 下满足最小间隔；circuit 只影响对应 host/provider。
12. registry schema 拒绝重复 key、额外字段、未知 parser、naive datetime、过期 proof、错误 SHA。
13. transport 拒绝非 allowlist host/path/method、redirect、私网/保留 IP、超大响应和超时。
14. credential/header/cookie 不进入任务参数、数据库、artifact、日志和异常。
15. 以主干 Slice A 为唯一 roster/contract/reconciliation 内核；代码扫描与行为测试证明不存在第二个
    registry facade、第二套 field writer 或 `RACE_SYNC_V2_*` 业务开关。
16. 枚举 `RACE_DATA_SYNC_*` 与 legacy `RACE_LIVE_*` 的 on/off 组合；每个 event/data-kind 的 canonical
    writer 数只能为 0 或 1，冲突组合返回 `writer_owner_conflict` 且零写。
17. 当前快照 99 场 census 分类总数严格等于 99，每场恰有一个
    eligible/route_missing/identity_conflict/time_pending/owner-conflict/duplicate/cancelled/postponed 结果。
18. enrollment apply 绑定 exact manifest/before snapshot，重放 noop；identity/route/owner/generation 任一漂移
    单 event 零写，且不能接管 legacy/historical/manual-paused owner。
19. standing policy 内新 published event 可自动生成小批 enrollment；策略外、模糊 identity 或过期 route
    只能 proposal。data-sync enrollment 后 lifecycle membership 数保持不变。
20. disenroll 只停 tracking/checkpoint 并释放本方案 owner，不删除 observation/revision/audit；baseline 漂移拒绝。
21. stable identity 唯一键区分 region/namespace；相同 external ID 跨 region/namespace 不冲突，contract
    version 升级不新建 identity；无法确定性 adoption 的历史行关闭 automation 并进入 review。
22. 多进程相同 snapshot key 只有一次 transport；waiter 读取相同 complete SHA。owner crash、分页失败、
    TTL 边界与 lease takeover 各自产生一个新 owner，partial artifact 永不 published。
23. `run_application_release.sh` 对 sync worker running/stopped 冻结、drain、stop、restore 正确；probe/inspect
    失败在 stop 前 fail closed。
24. `manual_release.sh`、`resume_stopped_release.sh`、rollback/immutable-control resume 对新 worker 的
    stopped gate、intent trust、服务 catalog 与 old-image-no-service 语义一致；中断重试最终状态匹配 frozen intent。
24a. owner CAS truth table 全覆盖：unmanaged acquire、same-manifest replay、successor rotate、exact disenroll、
    live/historical/manual-paused conflict、stale generation/manifest；成功 enrollment 后下一次 census 不把
    自身 `data_sync` owner 误判为 legacy 冲突。
24b. 历史 `live` 不由 migration 自动转换；显式 reviewed transfer 只有在 legacy/new writers 全关、两队列
    drain、无 active claim 和 baseline 精确时才原子 `live -> data_sync`，旧代码遇到 data_sync 必须零写。

## 3. R1：时间、时区与 reschedule

15. aware UTC、IANA zone、local date/time round trip 一致才能形成 applied candidate。
16. 日本、香港、英国、法国和美国 DST 正反例正确；美国赛事不允许统一默认时区。
17. 只给日期时保持 `race_datetime=null`；不得用历史时间或当地中午填充。
18. 同 semantic time 重放 noop，不 bump generation、不失效缓存。
19. 同来源更晚 `source_updated_at` 可修正旧值并留下 before/after。
20. 跨来源相同值合并；不同值保持 canonical 并创建 `needs_review`。
21. manual lock 阻止自动覆盖，但仍保存 observation 和冲突 reason。
22. 真正时间变化在同一事务更新 event、field ledger、lifecycle/live generation、claim/token 和 next due。
23. 在任一写入点故障时整个事务回滚，缓存不失效。
24. 旧 lifecycle/race-sync task 使用旧 generation 时零 transition/observation/projection 写入。
25. cancelled/postponed 优先于旧时间；延期无新 T 时不得按旧 T 进入 running/finished/result poll。
26. finished 后未来 T 自动候选被阻断；受审 correction 可回退并产生新 generation。
27. 缺 source identity、route 或 IANA zone 只保存 observation，不创建 event/control。
27a. PostgreSQL 真并发 schedule×lifecycle、schedule×result projection、schedule×live checkpoint 在 bounded
    timeout 内完成，无 deadlock；所有路径服从 shared-advisory -> membership -> lifecycle control -> event ->
    projection -> tracking -> checkpoint 顺序。
27b. 上述锁图交叉并发在任一写点注入 abort 后完整 rollback；retry 仅一次 applied/replayed，不能出现 event 时间、
    generation、result/status 或 checkpoint 的部分提交。
27c. 保留的 Slice A racecard reconciliation 先无锁解析 hint、再按 event -> projection -> tracking -> source
    identity -> observation 顺序重锁重验；racecard×schedule、racecard×result PostgreSQL 真并发与 abort/retry
    无 deadlock、无部分 runner/field/revision 写入。

## 4. R2：出马表与 runner revision

28. provider participant ID 精确命中同 event participant；同名不能跨 event 自动合并。
29. 没有 provider ID 时只能创建 event-scoped stable key，并标记 review status。
30. 马号、档位、骑师、练马师、负磅和 status 逐字段变更，不改变 participant 唯一身份。
31. payload 缺 runner 不等于退赛；只有明确 withdrawn/scratched/non-runner marker 才改变状态。
32. 补出、换骑师、改档和退赛各生成新 revision，旧 revision 和 LKG 保留。
33. 相同 roster hash 重放 noop；并发刷新只分配一个合法 revision number/current pointer。
34. partial/重复 runner/未知身份/冲突 roster 只保存 observation，不移动 current pointer。
35. manual locked runner 字段不被覆盖；其他未锁字段可按合同独立更新。
36. 未关联 `HorseProfile` 的 runner 可公开显示并参与 result completeness。
37. legacy `RaceEventRunner` 与新 projection 冲突时进入审核，不静默删除或重建。
38. racecard apply 关闭时 observation/revision 可 shadow，公开 runner 零变化。

## 5. R3：赛果 finality、完整性与 revision

39. T 前 results transport 为 0；due 精确覆盖 T+3/5/10/15/20/25/30 分钟。
40. DORMANT、scheduled、partial、仅头马、部分 Also Ran、空 roster 均不能形成 confirmed result。
41. terminal marker 必须由 provider-specific parser/contract 解释，不能用统一字符串猜测。
42. declared/started/result runner 守恒；退赛、未完赛、拉停、取消和并列均有确定语义。
43. 死热内部顺序唯一；authority-neutral `reported_finish_position` 可重复，官方并列名次另存
    `official_finish_position`。
44. 官方完整终态形成 `source_label=official`；Racing API/可信第三方形成各自真实 source label。
45. API/第三方 confirmed result 的 `official_finish_position=null`，页面不得显示“官方赛果”。
45a. 可信第三方 `reported_finish_position=1,1,3` 经 revision、legacy projection、cache 与页面完整显示
    `1,1,3`，内部 `finish_position=1,2,3` 不能泄漏成展示名次。
46. `human_reviewed_reference` 只有精确人工 approval 可创建，自动任务调用必然拒绝。
47. 明确 provisional/unofficial 只形成 provisional revision，不设置平台 confirmed time。
48. 同 confirmed content 重放 noop；同来源 correction marker 形成 corrected revision。
49. 同资格来源冲突保持 current canonical 并创建 incident，不按抓取先后覆盖。
50. 并发 official/trusted/correction 乱序最终只有一个合法 current pointer 和完整 parent chain。
51. provider checkpoint 在 observation 后崩溃可重投补齐，不重复 result rows/revision/OperationLog。
52. result apply/public 任一开关关闭时只观察，不写 legacy projection或公开缓存。
53. R3 独立部署时不直接修改 `RaceEvent.status`；R4 接入前 public admission 固定关闭。
54. confirmed 后按 T+24h correction watch 低频运行；24h 后停止热轮询并进入日常补偿。
54a. R3 terminal/correction 只创建一个 unpublished immutable shadow revision，不移动 current、不写 legacy、
    不改 status；相同 content 重放命中同一 revision，correction 精确 supersedes current published revision。

## 6. R4：生命周期、公开与 SLO

55. result projection 与 lifecycle transition 在同 event 协调事务中无部分提交。
56. confirmed result 可通过唯一 lifecycle 接口推进 finished；provisional 不可。
57. 生命周期因时间已 finished 但无结果时，页面明确显示“赛果待补”，不伪造 confirmed。
58. cancelled/postponed 与 result 冲突进入审核，不能自动发布。
59. 页面分别显示官方、可信来源自动、人工审核和已更正标签，且来源 URL/时间可审计。
60. transaction commit 后详情页和日历缓存恰好失效一次；rollback 不失效。
61. terminal 首次发现到公开延迟指标按 observation fetched_at 计算，不使用任务启动时间伪造。
62. T+30 有 confirmed result 或唯一 reason-code alert；两者都没有时测试失败。
63. 上游 T+30 未终态记录 `source_not_terminal` 并继续补偿，不计为结果成功。
64. alert 去重键包含 event/source/data kind/generation/reason，不重复发同一 incident。
65. 本阶段新闻、QQ 和非明确批准的外部消息均为 0。
66. 公开 verifier 对 event identity、名次+马号序列、source label、revision SHA 和 status 完整校验。
66a. lifecycle off、无 membership、root/activation/count/digest/generation/claim/enrollment 任一漂移时，
    `apply_confirmed_result_with_lifecycle()` 仅保留允许的 shadow evidence，legacy/public/status 全部零写。
66b. shadow mode 只生成 proposal；enforce + exact trust root 才在同一 transaction 写 confirmed projection、
    publication 与 finished transition。
66c. event 已 finished 时 compatible result 幂等写入且无重复 transition；cancelled/postponed 时 canonical/public/
    status 零写并产生唯一 incident。
66d. 在 result rows、revision pointer、publication、lifecycle transition 任一位置注入异常，整笔事务回滚；
    task wrapper 不得打开或提交第二个业务事务。
66e. 冻结独立 reference snapshot 标记 T+30 前已完整终态的赛事；分别计算 upstream availability、
    terminal detection、confirmed/publication、blocked alert coverage，alert 不能提升前三项。
66f. 对“系统声称 source_not_terminal、但 reference 已有终态”的样本，测试必须判检测失败而不是 alert 成功。
66g. R4 只 promote expected unpublished shadow revision，绝不新增 revision；public off -> on 重试同一 revision、
    stale expected revision/current pointer、重复调用与 mid-transaction failure 分别为一次成功、零写拒绝、
    replay、完整 rollback。
66h. evidence-driven lifecycle atomic claim 覆盖 `next_refresh_at` 未到仍可取得、scanner 同时 claim、他人有效
    claim 返回 busy、过期 claim 接管、worker commit 前崩溃自动回滚，以及所有正常 success/noop/reject 分支
    清空自身 token/expiry；不得复用 scanner token。

## 7. Migration、兼容与回滚

67. 新字段和 provider checkpoint 使用 additive migration；旧代码在全部新开关关闭时可读取数据库。
68. 历史 source identity 默认 automation disabled，不因 migration 自动升级。
69. 移除 provider-name 特判前先建立等价或更严格的 contract eligibility constraint。
70. migration forward/backward、fresh install、已有数据 adoption 和 `migrate --plan` 通过。
71. provider/cohort/data kind/public flag 关闭后，一个 selector 周期内新 dispatch/write 为 0。
72. 已排队旧 task 通过 generation/CAS 零写退出，不要求 destructive purge。
73. reverse manifest 只能回退其绑定 event/field/revision/baseline；漂移时整项拒绝。
74. raw cleanup 只删除过期、非 hold 大文件；hash、normalized、revision、ledger 和 FK 完整。
75. 旧人工结果 review bundle、approval 和 receipt 语义不受新自动链改变。
75a. migration adoption：官方历史行只从 `official_finish_position` 回填 reported；human/reference 仅从冻结
    source proof 回填；无证据行保持 null，不能从唯一 internal order 猜测。
75b. 现有六个 `RaceEventLiveState` 前向/后向迁移不变；非法值 fail closed；time_pending/correction_watch/
    closed 只做派生 phase，不写入 state。
75c. 每 payload、provider/region 日预算、artifact root high/low water、min free disk 任一不足时 request=0、
    write=0 并报 `artifact_capacity_blocked`；cleanup failure、hold 膨胀与恢复后解封均有测试。

## 8. 性能与验收数据

76. 10,000 个 tracking 的 due selector 使用索引且 P95 小于 500ms，query 数有上限。
77. 同地区 20 场共享一次 provider snapshot，不产生 20 次相同列表请求。
78. 失败 provider 不造成每分钟热循环；backoff/jitter/circuit 在预算内。
79. 首发 shadow 连续至少 7 天且覆盖至少 10 场终态赛事。
80. T-24h 时间覆盖 >=95%，T-6h racecard freshness P95 <=15 分钟。
81. terminal-to-public P95 <=5 分钟、P99 <=10 分钟；reference 证明 T+30 可用的 canary
    confirmed/publication >=95%，扩展 cohort >=99%；真正 blocked 的 alert coverage >=99%，分别计算。
82. 错绑赛事、跨 event 写入、manual lock 覆盖、重复 current revision、无证据公开均为 0。

## 9. 必跑验证

- 新增 targeted tests；
- 现有 race-live/racecard/result-review/lifecycle 回归；
- PostgreSQL 并发与 migration 合同；
- Django `check`、migration drift、Compose config、Celery route/Beat schedule；
- `git diff --check`、敏感信息扫描和文档引用扫描；
- 独立只读工程 review；
- 生产关闭态 smoke、shadow verifier、公开 canary 验收分别保留 evidence。
