# 出马资料、赛果同步与生命周期集成测试用例

## 1. TDD 与 RED

命令、语法或 SQLite 锁语义失败不算 RED。A、A2、B、C 分别取得 RED，不补写历史 RED。

## 2. A：racecard、来源合同与字段冲突

1. raw/normalized SHA、URL/external ID、observed/source-updated time、parser/registry/contract/task/run
   identity 完整落审计；raw 不含 secret/header。
2. strict schema 拒绝重复 key、额外字段、NaN、超深/超大 payload、naive datetime。
3. 同 semantic observation 重放 noop；parser/HTTP/identity 失败不生成成功 revision。
4. event identity 缺失/歧义只保存 observation，不创建 `RaceEvent`、不写字段。
5. runner provider identity 精确复用；仅同名不能跨来源静默合并；缺 runner 不等于退赛。
6. 明确 withdrawal 只更新对应 runner；马号/闸位/骑师/练马师/weight/status 分字段决策。
7. 所有 roster source class 均可按地区/字段合同自动 apply，不因 provider 类别固定拒绝。
8. 相同跨来源值合并；同源新版本可修正；跨来源异值保持 canonical 并 `needs_review`。
9. canonical 为空时首个完整候选可 apply；后来冲突不覆盖；manual lock 不被任何来源覆盖。
10. C 未启用时 schedule-impacting 候选 fail closed；TRA 旧入口不能绕过统一服务直接改 T。
11. provider kill switch、host/path/content/size/timeout/request budget 独立；一个来源失败不阻塞其他。
12. 赔率存在则 best-effort 保存，不存在不失败；赔率不触发高频 poll 或 lifecycle reschedule。
13. raw 90 天 cleanup 只清非 hold 大字段，保留 hash/ledger/FK；可重入且有界。
14. 旧 high/low `authority_level` 的跨来源冲突仍不覆盖；新 row 写 neutral level，Admin 只读标注
    legacy；同源版本与 manual lock 仍按新合同工作。
15. authority migration forward/backward 与旧代码关闭态读取通过；回滚旧代码时 auto-apply=0。

## 3. A2：runner 与 HorseProfile

14. 未关联 profile 的 runner 可正常保存、公开并进入结果链。
15. 候选生成展示 external ID、别名、出生年/性别/国家、历史记录和匹配理由，但不自动确认。
16. 管理员可确认既有 profile、选择其他 profile、创建新 profile、暂不确定。
17. 确认写 link、actor/reason/audit/manual lock 原子一致；重放不重复。
18. 人工锁后任何 provider 只能创建冲突提醒，不能自动改绑。
19. 撤销/改绑要求权限与原因，并保留完整 before/after history。
20. 两个管理员并发确认通过 CAS/约束只产生一个 current link，无丢失更新。
21. A2 不合并两个既有长期 profile；骑师/练马师不创建主档。

## 4. B：赛果 observation/revision

22. T 前 result network=0；due 精确覆盖 T+3/5/10/20/30m、每 30m 至 6h、每 3h 至 24h。
23. 24h 无结果进入 stale + daily compensation；不得热循环或伪造结果。
24. HTTP/parse/schema/identity/部分结果失败不生成 canonical revision，lifecycle 独立工作。
25. 任一获准可信来源的完整结果可单独形成 official，无需第二来源或 provider 等级。
26. 明确 provisional/unofficial 只形成 provisional，不设置 confirmed time；部分名次只 observation。
27. 阶段未明确但 payload 完整时按可信合同默认 official；不得因 T+30 自行造结果。
28. official 后跨来源不同内容保持 current official 并创建 conflict；明确 correction 形成新 revision。
29. provisional/official/corrected 乱序、重放和并发最终只有一个合法 current revision。
30. public admission 关闭时只审计；开启后 provisional 有醒目标记，部分/冲突 observation 不公开。
31. B projection 对 provisional/official 均不直接改变 `RaceEvent.status`；只写 revision/result/evidence。
32. C 未部署时新 result public admission 保持关闭；B 独立部署不存在 status/revision 中间态错误。
33. 两个 provider 同时 due 可在一个父 claim 处理；A 429/timeout 不阻止 B 成功并独立更新 checkpoint。
34. fallback 成功后其他来源仍按 correction due 运行；父 `next_poll_at` 等于 provider due 最小值。
35. worker 在部分 observation 后崩溃，重投 replay observation 并补 checkpoint，不重复 revision。
36. TRA Pro 历史 identity migration 后仍 supplemental/official_eligible=false，不被自动升级。
37. TRA Pro 经未过期 contract、完整 payload 与 `complete_payload_defaults_official` marker 可 official；
    contract 缺失/过期、显式 provisional、partial 或 marker 不满足均零 official。
38. provider-name 硬约束移除后，新 eligibility DB constraint 仍阻断未批准/未自动化/空 contract。
39. source identity migration forward/backward、旧代码关闭态读取与 rollback flag-off 通过。
40. news/QQ 发送均为 0；预留通知 key 对相同 revision 重放保持唯一。

## 5. C：schedule/lifecycle 集成

33. T/local time/timezone/status、field audit、event、lifecycle/live reschedule 同事务提交。
34. local time、aware T、IANA zone 不一致整组拒绝；美国必须逐场 `America/*`。
35. semantic schedule 不变不 bump；真正变化同时 bump lifecycle schedule/claim generation、live
    claim generation/lock version，并清 token/attempt、重算 due。
36. 旧 lifecycle/live task 持旧 generation/token 时零 transition/observation/projection 写入。
37. 两个来源/worker 并发按固定锁序和 CAS 无 deadlock、lost update 或部分提交。
38. 单一获准可信来源 cancel/postpone 可直接 apply，优先于 T/T+30；延期无新 T 不按旧 T finished。
39. finished 后未来 T 不自动回退；无 official 转高优先审核，有 official 保持 finished。
40. 管理员 correction 可回退并生成新 generation、完整审计；重放 noop。
41. 来源失败不阻止 T/T+30，且不产生空赛果。
42. C 接收 B 的 official evidence，经既有 lifecycle control/transition 提前 finished；provisional
    evidence 不触发 transition，重复 official evidence 为 noop。

## 6. Shadow/enforce 与自动纳管

42. global enforce + control shadow 的 effective mode 仍为 shadow；只改全局 mode 不应用 proposal。
43. shadow terminal proposal 可使 next refresh None，但历史 proposal 永不直接 apply。
44. re-arm manifest 冻结 event/control/generation/claim/schedule/proposal/commit/expiry/SHA。
45. false/off 且无有效 active/reserved/claim 才可 apply；否则整批零写。
46. re-arm CAS 验证 `mode=shadow`，同事务写 `mode=enforce`、bump generation、清 claim、保留旧
    proposal 审计并按 current truth 重算；manifest 固定 before/after mode。
47. re-arm 后全局仍 false/off 时无执行；另开全局 enforce 后 effective mode 为 enforce。
48. mode/generation/claim 漂移、过期 manifest 分别整批零写；相同 manifest 重放 noop，不重复
    transition/cache/notification。
48. 地区未验收或缺 identity/IANA/T/route 时只 observation；不得自动建 event/control enforce。
49. 地区验收后新符合条件 event 自动创建/更新现有 control 并 enforce，重复 enrollment 幂等。

## 7. 公开、迁移与运行态

50. transaction rollback 不失效 cache；commit 恰好一次；日历与详情读到同一持久状态。
51. lifecycle finished 无 revision 显示“赛果待补”；official/provisional/corrected 概念不混淆。
52. cancelled/postponed 与结果冲突进入审核；现有 event 924 与历史回归不破坏。
53. nullable additive migration 在旧代码关闭态可读；data backfill 与 constraint 收紧可重入、可回滚。
54. 真 PostgreSQL 验证 schedule vs lifecycle/live/result、双 promotion、双管理员确认的锁/CAS。
55. offline tests 不用生产 secret/真实网络；Django check、migration drift、diff check 和相邻回归通过。
56. 六 cohort 每区 2–4 场 verifier 覆盖 observation、字段、结果、generation、公开状态与零通知；
    单 cohort 失败不影响其他 cohort rollback/晋级。

生产历史 `race_live` 积压必须另获授权；不得在 smoke 中消费或清理。
