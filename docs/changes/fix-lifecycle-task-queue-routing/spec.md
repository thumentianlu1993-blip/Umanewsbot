# 生命周期单赛事任务队列路由修复规格

## 背景与根因

生产 R3 shadow smoke 中，`scan_due_race_event_lifecycle_task` 成功 claim 并 dispatch 了
2 个单赛事任务，但未生成 proposal。代码把
`stable.tasks.advance_race_event_lifecycle_task` 路由到 `default`，而普通 worker 的生产
启动脚本默认且实际只消费 `celery`。因此消息停留在无人消费的 `default` 队列。

## 目标

- 将生命周期单赛事推进任务投递到普通 worker 已消费的 `celery` 队列。
- 用自动化合同测试绑定 Celery route 与生产 worker 默认队列，防止再次漂移。
- 保持 lifecycle 全局开关默认关闭；本变更不重新启用 shadow。

## 非目标

- 不扩大普通 worker 到 `default` 或 `race_live` 队列。
- 不删除、清空、重放或消费生产 Redis 中既有的 2 条 `default` 消息。
- 不修改 scanner、claim generation、状态机、数据库模型、迁移或 Beat 频率。
- 不启用 lifecycle，不恢复 `race_live_worker`，不修改赛事业务数据。

## 验收标准

1. `CELERY_TASK_ROUTES["stable.tasks.advance_race_event_lifecycle_task"]` 精确为
   `{"queue": "celery"}`。
2. 合同测试从真实 `deploy/docker/start-worker.sh` 解析普通 worker 默认队列，并断言它与
   生命周期单赛事任务 route 一致；若任一侧改回 `default`，测试必须失败。
3. `poll_race_live_event_task` 与 `monitor_race_live_sla_task` 仍只进入 `race_live`。
4. lifecycle 开关默认值仍为 `false/off`。
5. 无 migration、无生产数据写入、无队列清理。

## 失败边界

- 若无法证明普通 worker 消费 `celery`，发布 fail closed。
- 若聚焦测试或独立 review 未通过，不得发布。
- 关闭态部署完成后，必须取得新的用户授权才能重新执行 R3 shadow。
