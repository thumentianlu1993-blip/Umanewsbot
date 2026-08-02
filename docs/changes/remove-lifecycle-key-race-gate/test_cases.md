# 移除 lifecycle 重点赛事资格门禁测试用例

## RED

1. 合法 P2、非 featured、`is_key_race=false` 赛事执行 prepare 时，旧实现应以“不是重点赛事”
   失败；fixture 的 published、scheduled、地区、时区、local_date、manual lock 和 control
   absence 必须全部合法，并断言具体领域错误；该失败构成本 change 的真实 RED。
2. P0/P1 与 P2 混合 manifest 在旧实现中整批失败，证明不是 fixture、语法或环境问题。

实际 RED：聚焦 `2` 项均失败于旧实现的
`EnrollmentError: event <id>: 不是重点赛事`；Django system check 与 fixture 正常。首次错误
虚拟环境路径未启动测试，不计为 RED。

## GREEN

1. 非重点赛事可生成 v2 manifest，manifest 精确冻结 `eligibility.is_key_race=false`。
2. 非重点赛事 dry-run 返回 `would_create`，数据库零写。
3. 严格 `false/off` 下非重点赛事 apply 创建一个 `mode=shadow`、generation=1 的 control。
4. 重点与非重点混合批次整批创建，control ID 集合与 manifest 一致。
5. manifest 生成后 priority、featured 或派生 key-race 值漂移，preflight/apply 仍拒绝。
6. 未发布、非 scheduled、取消、无 local_date、manual lock、错误地区时区继续拒绝。
7. 美国非重点赛事仍必须提供非空逐场 `America/*` allowlist，并命中当前时区。
8. v1 apply、非 `false/off` apply、非 shadow mode 和超过 20 场继续拒绝。
9. shadow proposal 不修改公开 `RaceEvent.status`，不触发 provider、race-live、新闻或 QQ。
10. 已存在非重点 shadow control 时，全局严格 `false/off` 的 scanner 和已排队 task 均零
    claim/零 proposal；作为旧代码回滚后的 fail-closed 保障测试。

## 回归验证

- enrollment 与既有 lifecycle SQLite 套件；
- lifecycle PostgreSQL 并发套件；
- Django check；
- `makemigrations --check --dry-run`；
- `git diff --check`。

实际 GREEN：新增 prepare/dry-run/apply/混合批次 `5/5`，并补充严格 `false/off` 下 scanner
与已排队 task 对非重点 control 零 claim/零 proposal `2/2`；完整 enrollment + 既有 lifecycle
SQLite `98/98`，相邻日历/详情/race-live eligibility/scheduled-result `101/101`，无持久卷的
隔离 PostgreSQL 16 并发/事务 `6/6`；Django check、migration drift、diff check 均通过。

## 生产验收

- R1 审核表至少包含一个 `is_key_race=false`，否则不得继续；
- 24–48 小时只统计真实跨过 T/T+30 的逐场证据，未到期赛事单列为未观察；
- 回滚时 web/worker/beat 全部核对严格 `false/off`、lifecycle active/reserved/claim 为 0，
  非重点 control 完成受审处置前不得重新开启。
