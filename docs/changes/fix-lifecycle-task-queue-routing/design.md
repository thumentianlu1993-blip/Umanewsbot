# 生命周期单赛事任务队列路由修复设计

## 当前数据流

```text
Beat/手工 smoke
  -> scan_due_race_event_lifecycle_task（普通 celery 队列）
  -> claim_due_lifecycle_controls
  -> transaction.on_commit(dispatch advance task)
  -> default 队列（错误：生产无 consumer）
  -> 无 apply / 无 proposal
```

生产普通 worker 由 `deploy/docker/start-worker.sh` 启动，默认参数为
`--queues="${CELERY_WORKER_QUEUES:-celery}"`。生命周期 route 位于
`server/app/settings.py::CELERY_TASK_ROUTES`，当前却显式指定 `default`。

## 最小修复

仅把 `advance_race_event_lifecycle_task` 的 route 从 `default` 改为 `celery`。不通过扩大
worker 队列来兼容错误 route，因为 `default` 的任务类型和积压范围没有在本变更中完成
审计，扩大消费面会带来不可控副作用。

修复后数据流：

```text
scanner -> claim -> advance task -> celery 队列 -> 普通 worker -> shadow proposal/enforce apply
```

## 旧消息与幂等

生产 `default` 中已观察到 2 条 generation=1 的旧消息，本变更不处理。claim 过期本身
**不等于**消息已经 stale；只有后续 scanner 成功重新 claim、使对应 control 的
`claim_generation` 增长后，旧 token/generation 才会被既有身份校验拒绝。因此 R3 必须先
确认没有 worker 消费 `default`，再执行手工 scanner，并核对目标 control generation 已增长，
之后才能开始观察。发布与 R3 重试仍不依赖清理旧消息。

## 测试设计

在生命周期测试模块新增配置合同测试：

- 读取真实 `settings.CELERY_TASK_ROUTES`；
- 读取真实 `deploy/docker/start-worker.sh`；
- 从 `${CELERY_WORKER_QUEUES:-celery}` 提取默认队列；
- 断言 lifecycle advance route 与该默认队列均为 `celery`；
- 同时断言 race-live 两个 task 仍为 `race_live`。
- 构造已过期 generation=1 claim，重新 claim 得到 generation=2；旧 token/generation 执行时
  必须零 proposal、零 applied、零赛事状态改变，新 claim 则可正常生成 shadow proposal。

测试先在旧 route 下取得真实 RED，再由实现 subagent 修改 settings 取得 GREEN。

## 部署与回滚

- 无 migration、无 schema 或业务数据变化。
- 关闭态部署：`.env` 仍为 `RACE_EVENT_LIFECYCLE_ENABLED=false`、
  `RACE_EVENT_LIFECYCLE_MODE=off`。
- 回滚代码即可恢复旧 route，但正常回滚后 lifecycle 仍关闭；不得以回滚为理由消费
  `default` 队列。
- 关闭态部署验收后，另行授权 R3：启用前以实际 worker `active_queues` 确认无人消费
  `default`；再启用 web/worker 的 true/shadow，beat 仍停，手工 scanner smoke；核对目标
  control generation 已增长、`celery` 消息被消费并生成 proposal，然后才决定是否启动
  24–48 小时观察。

## 可观测性

R3 重试至少记录 scanner claimed/dispatched、`celery`/`default` 队列深度、worker task 日志、
proposal 数、applied 数、赛事业务快照和失败恢复结果。
