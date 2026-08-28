# 赛事时间、出马表与赛果自动同步测试用例

## 1. 测试原则

- 单元/集成测试不得连接生产数据库、Redis、真实队列、凭据或第三方服务。
- `select_for_update`、唯一约束、并发幂等和 migration 必须另在 PostgreSQL 16 验证。
- 每个拒绝分支都检查业务表、current pointer、status、claim/checkpoint 是否零越权写入。
- HTTP 200、task exit 0、notification 或 queue 下降不能代替端到端业务断言。
- 生产只有在最终确认后才运行关闭态 smoke 和真实来源窗口验收。

## 2. 来源、身份与仲裁

1. 来源等级固定为 `licensed_api=300 > official_operator=200 > trusted_publisher=100`。
2. 高等级覆盖低等级；同等级按 observation 时间和稳定 provider key 确定性决胜；相同 semantic value replay。
3. manual lock、身份多解、route/contract/proof 失效、schema/完整性失败时 canonical 零写。
4. stable identity 包含 provider、region、identity namespace、external race ID；contract 升级不制造新身份。
5. The Racing API result not-found 后先尝试持久化 HKJC/France Galop 官方事实，再按地区尝试
   Sporting Life/ZEturf/HRN；主 API 有完整结果时不得降级。
6. 三类来源都可自动投影，不要求 `human_reviewed_reference`；旧人工链不为自动链提供权限。
7. 前台统一显示“赛果”，不显示 provider/source class 或 provisional/official/corrected 标签。

## 3. Future discovery 与控制面

8. 总开关关闭时 selector/discovery 在 DB/网络前返回 disabled。
9. standing policy 只纳管 published + scheduled/postponed 且 route/identity 唯一的赛事；策略外只 proposal。
10. provider/日期桶按 UTC 小时公平轮转，单轮 3 请求预算不会长期饿死后排地区。
11. enrollment acquire/replay/rotate/disenroll 服从 owner/generation/manifest CAS；legacy `live` 不自动接管。
12. selector 只 claim `next_poll_at <= now`，按 `(next_poll_at,event_id)` 稳定排序；并发 selector 只有一个 token。
13. 新任务只进入 `race_sync_v2`；worker 不消费普通 `celery` 或遗留 `race_live`。
14. 发布/恢复/回滚状态机覆盖新 worker running/stopped/probe failure/interrupted/old-image-no-service。

## 4. Claim 与 stale-worker 安全

15. claim 冻结 enrollment/owner/claim generation、attempt token、entry SHA、route、checkpoint version 和 plan SHA。
16. provider transport 前先做一次只读 exact-claim 检查；每次 canonical apply 事务内再次锁定并重验。
17. 网络期间 claim 被新 worker 接管时，旧 worker可保留 immutable observation，但时间、runner、result、
    revision、current pointer、status 和 checkpoint 全部零写。
18. `claim_expires_at <= now` 时 apply、complete 和 failure release 都返回 `claim_expired`，不能清理或重排新任务。
19. checkpoint version、plan、route、enrollment entry 或 owner 漂移时返回精确 reason code，不能部分提交。
20. worker 崩溃重投只 replay 相同 content SHA，不重复 revision、result rows 或 transition。

## 5. 时间、时区与 lifecycle

21. aware UTC、IANA timezone、local date/time round trip 一致才可 apply；只有日期时不猜默认时间。
22. 日本、香港、英国、法国和美国 DST/时区合同均有正反例。
23. 相同时间 replay；同源更晚时间可更新；跨源按固定优先级仲裁；manual lock 保持当前值。
24. 时间变更写 field decision 并使旧 generation/token 失效，commit 后才失效公开缓存。
25. `scheduled -> running` 在 T，`scheduled/running -> finished` 在 T+30；transition dedupe 唯一。
26. postponed 无新时间时等待 12 小时重试，cancelled 不推进；finished 不反向猜回 scheduled。
27. 完整赛果可在同事务补齐 finished；仅 finished 不会伪造赛果或 confirmed time。

## 6. 出马表

28. 远期 time/racecard cadence 不超过 12 小时，临近缩短到 6 小时、1 小时、15/10 分钟。
29. provider participant ID 或 event-scoped stable key 唯一；同名不能跨 event 自动合并。
30. 马号、档位、骑师、练马师、负磅和 status 可更新；缺行不等于退赛或删除。
31. 明确 withdrawn/scratched/non-runner、补出、换骑师和改档保留 before/after 与 immutable revision。
32. 未关联 HorseProfile 不阻塞公开 runner 或赛果；partial/重复身份/manual lock fail closed。
33. racecard apply 关闭时可保存 observation，legacy runner 和 schedule 零写。

## 7. 赛果、并列与更正

34. T 前 result transport 为 0；due 包含 T+3/5/10/15/20/25/30，之后 15/30 分钟补偿。
35. confirmed 后保留 7 天 correction watch；correction 生成新 superseding revision，不覆盖旧 revision。
36. 只有 terminal + 完整 runner 守恒 + 唯一身份 + 合法名次/非完赛状态才能自动公开。
37. partial、DORMANT、仅头马、部分 Also Ran、重复身份或未知缺口只保存 observation。
38. `reported_finish_position` 允许 `1,1,3`；内部 `finish_position` 为 `1,2,3` 但前台必须显示前者。
39. 高优先级 current 不被较晚低优先级覆盖；同源 correction 仅在 correction flag 开启时投影。
40. result apply/public 任一关闭时不写 legacy/current/status；开启时 revision、result rows、pointer、confirmed
    time、tracking 和 lifecycle transition 在同一事务提交。
41. 相同 content SHA replay 既有 revision；mid-transaction fault 不留下半套 result/status。

## 8. 容量、网络与可观测性

42. 单响应压缩/解压大小、provider/region/day requests/bytes、root high/low water、hold 和 free disk 全校验。
43. 每次 transport 前原子预留当日最大请求与响应字节；并发 worker 不能超额。
44. 任一容量配置缺失/非法或 free disk 低于门槛时 request=0、business write=0。
45. host/path/method/redirect、timeout、schema、pagination 和 secret redaction 均 fail closed。
46. `audit_race_data_sync` 固定 `would_write=false`，输出 flags、route drift、inventory、checkpoint、capacity、
    daily ledger 和 blocker；审计前后数据库 hash 不变。
47. kill switch 关闭 provider/region/data kind/network/apply/public 后，一个 selector 周期内无新 dispatch/write。

## 9. 必跑验证

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test \
  stable.test_race_data_sync_audit \
  stable.test_race_data_sync_lifecycle \
  stable.test_race_data_sync_pipeline_a \
  stable.test_race_data_sync_policy \
  stable.test_race_data_sync_providers \
  stable.test_race_data_sync_r0 \
  stable.test_race_data_sync_results \
  stable.test_race_event_lifecycle --noinput
```

PostgreSQL 16 必跑：

```bash
DB_ENGINE=postgres python manage.py test \
  stable.test_race_data_sync_r0_postgres \
  stable.test_race_data_sync_pipeline_a_postgres --noinput
```

另需：`manage.py check`、`makemigrations --check --dry-run`、Python compileall、三份 Compose config、
`git diff --check`、secret scan、zero-write full-config audit、与 `origin/main` 的扩展回归失败集合归因。

## 10. 定时赛果审核 claim 异常收口

48. prepare 抛出异常时，原 token 精确写 `failed/prepare_exception`、清租约且不落异常正文；token 已被新 owner
    替换时旧 worker 零写。
49. sweeper 只终态化租约过期、cursor 合同正确且 selector/bundle/terminal/finished 全空的 claim；审核总开关
    关闭时任务零写。
50. 未过期、token 畸形或已有任一证据的 claim 阻断自动收口；与合格行混合时人工 apply 整批回滚。
51. management command 默认只预览，apply 必须绑定 64 位 manifest SHA；错误 SHA 零写，正确 SHA 精确收口，
    重放返回空 manifest 且不重复修改。
52. PostgreSQL 并发覆盖 sweeper 先取得终态后旧 prepare worker 只能返回 `lease_lost`，不能覆盖 `failed`。
53. Beat 每 5 分钟调度 sweeper、任务固定普通 `celery` 队列且消息 240 秒过期。
54. PostgreSQL advisory transaction lock 必须串行化 manifest apply 与新 slot claim 创建；apply 锁内的
    `remaining_claimed_count=0` 不能被并发 phantom claim 绕过。
55. failed slot 显式 retry 在进入 prepare 前清空上一 attempt 的 selector/bundle/terminal/finished 字段；若新
    attempt 再次超时，sweeper 仍能识别标准空 claim。
56. manifest SHA 同时绑定 eligible IDs 与 blocked reason；活租约在 preview 后变为过期也必须 SHA drift，
    不能在未复核新 eligibility 的情况下 apply。
