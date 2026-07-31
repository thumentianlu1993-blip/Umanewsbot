# Lifecycle shadow 纳管准备测试用例

取得“确认实现”后先写测试并取得真实 RED。RED 必须来自新 prepare/v2 parity/CAS 能力不存在，
不能来自 fixture、环境、迁移或语法错误。

## A. Manifest 与 prepare

1. 显式 1–20 个 event IDs 生成稳定、排序、UTF-8 manifest 和 summary。
2. 重复 ID、非正整数、空范围和第 21 场在任何 artifact 写入前拒绝。
3. 输出目录已存在、symlink、非普通祖先或越界路径拒绝。
4. manifest 拒绝重复 key、BOM、NaN/Infinity、未知字段和超过 1 MiB。
5. content SHA 与原始文件 SHA 可独立复算；任一字节变化使校验失败。
6. prepare 对不存在、非重点、未发布、非 scheduled、已取消、无 local_date、manual lock
   的赛事整批拒绝。
7. 日本、香港、英国、法国正确 IANA 时区通过；错误地区时区拒绝。
8. 美国缺/空 allowlist、非 `America/*`、当前 zone 不在 allowlist 均拒绝。
9. `local_start_time` 非空但 `race_datetime` 为空时仍走无时间路径，不推导 instant。
10. aware `race_datetime` 正确冻结；naive 值拒绝。
11. prepare 只读数据库，不创建 control/transition，不改 event。

## B. Dry-run parity

12. v2 dry-run 完整执行与 apply 相同的 schema、SHA、expiry、commit、zone 和 DB drift 门禁。
13. 美国 manifest 在 dry-run 和 apply 对 allowlist 的结论相同。
14. manifest 生成后修改 eligibility、status、region、timezone、local date/time、
    race_datetime 或 event_updated_at，dry-run/apply 均零写拒绝。
15. manifest 生成后并发创建不同 control，dry-run/apply 均拒绝。
16. 合法无时间赛事 dry-run 输出当地次日午夜 next refresh 和 predicted decision。
17. 合法有时间赛事 dry-run 输出 race_datetime next refresh。
18. dry-run 前后 control、transition、event、result、news 和 QQ 相关计数不变。

## C. Atomic apply 与 replay

19. apply 缺 manifest file/SHA/expected commit/确认参数均拒绝。
20. v1 manifest 即使 SHA 正确、mode 为 shadow/enforce/off、≤20 或 >20 场，任何
    `--apply` 都非零且零写；v1 dry-run 兼容仍通过。
21. v2 apply 只接受严格 `false/off`；`true/shadow`、`true/off`、`false/shadow`、
    `true/enforce` 全部拒绝，control/transition/claim/dispatch 均为零。
22. v2 manifest 中任一 mode 非 shadow 拒绝。
23. 两场合法赛事一次 apply 创建两个 shadow control，generation 均为 1。
24. 一场合法、一场漂移时整批零 control。
25. 相同 manifest 重放返回 replay，control 内容、generation、next refresh 和 transition
    计数不变。
26. 不同 manifest 命中已有 control 拒绝，不更新 mode/generation/manifest data。
27. 两进程并发 apply 同一 manifest，最终只存在一组 control；另一方为 replay 或受控冲突。
28. PostgreSQL 真实并发中锁顺序稳定，无重复 control、死锁或部分提交。

## D. Scanner 与 shadow

29. 全局 `false/off` 时即使存在 due shadow control 也零 claim/dispatch。
30. `true/shadow` 时只 claim manifest 内 due control，不扫描无 control 的全表赛事。
31. shadow 到期只创建 proposal，不改 `RaceEvent.status`。
32. 同一 generation/task 重复执行不重复 proposal。
33. 已排队 task 在开关关闭后事务内返回 disabled，零 proposal。
34. 生命周期任务不调用 provider、不 dispatch race-live、不发新闻或 QQ。
35. 无时间赛事在当地次日边界前 noop、边界后 proposal finished。
36. 有时间赛事到点 proposal running、T+30 proposal finished；该用例只作为代码回归，
    不冒充当前生产观察证据。
37. cancelled/postponed 漂移在 apply 前拒绝；运行期若状态改变也不误推正常完赛。

## E. 回归与检查

38. 既有 lifecycle SQLite 套件全部通过。
39. 既有 PostgreSQL claim/apply 并发套件全部通过。
40. 日历、详情页、race-live、scheduled result review 相邻回归无新增失败。
41. Django check、`makemigrations --check --dry-run`、`git diff --check` 通过。
42. 查询数测试证明 prepare ≤20 场无逐场隐式大查询，scanner 查询边界不退化。
