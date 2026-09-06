# 补齐赛事状态自动更新完整链路：测试方案

## 0. 预先声明的通过标准

实现前先冻结以下判断，测试后不能为了得到绿色结果再降低要求：

- 未来 30 天盘点分类数量 100% 守恒；
- 多个可信来源竞争不能制造 enrollment route ambiguity（先到先得 + 固定平局顺序）；
- 同一赛事的并发授予竞争只产生一条有效 enrollment（先到先得授予原子性）；
- 来源窗口内唯一匹配赛事 60 分钟内纳管；
- lifecycle 状态推进 P95 不超过 5 分钟；
- 正式终态识别到公开 P95 不超过 5 分钟、P99 不超过 10 分钟；
- 错误赛果、部分赛果公开、跨 event、人工锁覆盖、重复 current 和双 authority 写入均为 0；
- 任一 kill switch 关闭后一个 selector 周期内无新派发或业务写入；
- `race_live` 队列在全部测试和生产验收中保持不变。

## 1. Standing policy v2

1. 地区至少有一条 `enrollment_eligible` route，policy 正常通过；result-only route 被标记为不参与竞争。
2. 一个地区没有任何 `enrollment_eligible` route，整地区返回 `trusted_route_missing`。
3. 先到来源获得纳管后，后到来源不能再创建竞争 enrollment（重放为 noop）。
4. 同一轮多个来源命中同一赛事时按 `tiebreak_order` 确定性授予，审计记录全部候选与胜者。
5. 授予后粘滞：非获胜来源的 time/racecard/result 响应只保存 observation，不改写 canonical。
6. 获胜来源失效后赛事回池重新授予并留换手审计；无审计记录的接管必须失败。
7. policy 原始文件 SHA、canonical digest、有效期任一漂移，网络和业务写入均为 0。
8. v1 policy 不被 v2 代码静默解释为 v2；升级必须使用明确的新 SHA。

## 2. Future discovery 与身份

9. 未来 30 天每场赛事恰好进入一个分类。
10. 当地日期超出 today/tomorrow 的赛事进入 `awaiting_source_window`，不发送网络请求。
11. 来源窗口内 exact name + course + local date 唯一匹配，创建唯一 TRA source identity。
12. 已存在且仍有效的同一 identity 返回 replay，不重复创建。
13. 同一 provider race ID 指向另一 event，返回 ambiguous，两个 event 均零写。
14. 同名不同场地、同场地不同日期、别名未批准均不能匹配。
15. 来源窗口内没有匹配项，返回 `source_identity_not_found`。
16. 候选、already-valid、created、adopted、awaiting、unmatched、ambiguous、rejected 数量严格守恒。
17. 单轮最多 3 个 provider 请求，地区/日期桶公平轮转。
18. manual lock、owner conflict、contract/route/registry 过期均在请求或 enrollment 前阻断。
19. 最近 7 天恢复清单只包含已纳管、tracking 开启且确有未闭环证据的赛事，不吸入普通历史赛事。
20. 新纳管状态只接受 scheduled/postponed；已纳管 continuation 允许 running/finished。

## 3. Enrollment 与 lifecycle admission

21. 新 enrollment 在 lifecycle flag 关闭时只纳管，control 保持 off。
22. lifecycle flag 开启后，reconciliation 把合格 control 有界切为 data-sync enforce。
23. admission evidence 精确绑定 policy、manifest、entry、owner generation 和 source identity。
24. 旧 enrollment 在 policy v2 下通过 successor manifest 轮换，generation 只增加一次。
25. 相同 successor 重放为 noop；任一 baseline 漂移整场零写。
26. manual pause 不被 reconciliation 清除。
27. active legacy membership 继续使用 legacy validator，不被 data-sync 覆盖。
28. 未结束赛事同时命中 legacy 和 data-sync authority 时返回 `lifecycle_authority_conflict`。
29. event 956 这类已结束 legacy 赛事的历史 transition/revision/publication 保持不变。

## 4. 一个共享校验器

30. lifecycle task、result projection 和 public read 对同一合法 admission 都通过。
31. policy digest 漂移时三处都拒绝。
32. enrollment manifest/entry/generation 漂移时三处都拒绝。
33. source terms、automation permission、validity 或 route 漂移时三处都拒绝。
34. manual lock 或 manual pause 出现时三处都拒绝。
35. writer owner 不为 data_sync 时三处都拒绝。
36. 公共读取不得使用比写入更宽松的条件。

## 5. 时间、状态和较晚纳管

37. `scheduled -> running` 在 T 后只产生一条 transition。
38. `running -> finished` 在 T+30 后只产生一条 transition。
39. T+30 后才纳管可 `scheduled -> finished`，reason 明确为 late admission，不伪造 running。
40. postponed 无新时间不推进；cancelled 不推进；finished 不反向。
41. race_datetime/timezone 更新递增 generation，旧 lifecycle/provider task 零写退出。
42. schedule 与 lifecycle 并发无死锁、无重复 transition。

## 6. 赛果、公开与停滞赛事恢复

43. official + terminal + 完整 roster + 唯一身份在同一事务写 status/result/current/publication。
44. partial、无 terminal marker、缺 runner、多解或未知状态只保存 observation。
45. result apply/public 任一关闭时 canonical 和 public 均零写。
46. 755/756/757 形态：已有旧 official revision、无 lifecycle admission，未经来源证据复核不直接公开旧 revision。
47. 上述形态经来源证据复核、不可变候选、人工批准和 apply 后完成公开；verifier 与公网一致，同内容重放幂等。
48. 同内容重放不重复 revision/result/publication/transition。
49. 页面 root/www 同时显示已结束和赛果，不出现 provider/provisional/source phase。
50. 数据库写成功但 public validator 拒绝的路径必须为测试失败。

## 7. 更正

51. 正式结果不变时只推进 checkpoint，业务表计数不变。
52. 合法 correction marker + 内容变化创建 superseding revision，并更新 current/publication。
53. 内容变化但无 correction marker，只创建 conflict incident。
54. correction flag 关闭时新更正不投影。
55. 低优先级来源不能覆盖高优先级 current。
56. 两个相同 correction task 并发只有一个新 revision/publication。

## 8. 故障、容量和队列

57. claim 过期、token 被替换或 checkpoint generation 漂移时业务零写。
58. provider timeout/403/429/5xx 释放或延后 claim，不阻塞其他 provider。
59. artifact 容量、响应大小、每日预算或磁盘门禁失败时 request=0、business write=0。
60. ordinary worker 与专用 worker 队列隔离保持不变。
61. `race_live` 有历史积压时，本变更不消费、不 purge、不迁移。
62. 任一 10 个赛事开关关闭时，一个 selector 周期内停止对应派发/写入。
63. worker crash/retry 只重放相同 observation/revision。

## 9. PostgreSQL 16 并发必跑

- discovery × lifecycle reconciliation；
- 两个来源对同一赛事的并发 FCFS 授予（必须只有一条有效 enrollment）；
- schedule × lifecycle；
- lifecycle × result publication；
- result publication × public-read snapshot；
- correction × duplicate provider task；
- legacy registry × data-sync admission conflict；
- kill switch mid-transaction；
- batch 20 的后段漂移必须使当前 event 零写，不能跨 event 误写。

## 10. 生产只读和自然验收

生产验收不手工改 due time、claim、event status、result 或 publication：

1. 检查 deployment lock、exact revision/image、migration leaf、服务 restart/OOM；
2. 检查 10 个开关、policy/registry SHA、两类 lifecycle authority；
3. 检查 MemAvailable、SwapFree、磁盘和三队列；
4. 运行 `audit_race_data_sync`，要求 `would_write=false`；
5. 验证 30 天 census 数量守恒且 route ambiguity 为 0；
6. 等待一场 today/tomorrow 赛事自然创建 identity/enrollment；
7. 等待它自然更新时间、出马表、状态和正式赛果；
8. 核对 Celery terminal、业务返回、claim 释放、observation/revision/result/publication/transition；
9. 核对 root/www 页面内容一致；
10. correction 至少完成一次自然无变化轮询；真实变化分支不在生产造数。

## 11. 常规验证命令

实现阶段应补齐对应模块名后运行：

```bash
cd server
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py check
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test \
  stable.test_race_data_sync_audit \
  stable.test_race_data_sync_r0 \
  stable.test_race_data_sync_lifecycle \
  stable.test_race_data_sync_providers \
  stable.test_race_data_sync_results \
  stable.test_realtime_race_results --noinput
```

另需执行 PostgreSQL 16 专项、`makemigrations --check --dry-run`、compileall、三份 Compose config、
`git diff --check`、literal secret scan 和 public page 回归。
