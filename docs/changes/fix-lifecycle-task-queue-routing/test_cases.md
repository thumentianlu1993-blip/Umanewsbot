# 生命周期单赛事任务队列路由修复测试用例

## T01：路由与生产 worker 默认队列一致

- 前置：读取真实 Django settings 与 `deploy/docker/start-worker.sh`。
- 断言：普通 worker 默认队列为 `celery`；advance lifecycle route 为 `celery`。
- RED：旧代码 route 为 `default`，仅因目标能力缺失失败。
- mutation：将 route 改回 `default` 或改变 worker 默认队列，测试必须失败。

## T02：race-live 隔离不回归

- 断言：poll/monitor 两个 race-live task route 仍为 `race_live`。
- 目的：防止修复时误把 race-live 工作引入普通 worker。

## T03：生命周期聚焦回归

- 运行完整 lifecycle/enrollment 测试，确认 claim、shadow、enforce、关闭态和并发语义不变。

## T03A：残留旧消息在重新 claim 后失效

- 构造已过期 generation=1 claim 并保存旧 token/generation。
- scanner 服务重新 claim 同一 control，断言得到 generation=2。
- 调用旧消息参数，断言零 proposal、零 applied、赛事状态与当前有效 control 状态不变。
- 调用 generation=2 新 claim，断言 shadow proposal 正常生成且赛事公开状态不变。

## T04：Django 与迁移静态检查

- `manage.py check`
- `makemigrations --check --dry-run`
- `git diff --check`

## T05：发布后关闭态验收（需另行授权）

- web/worker/beat 均保持 lifecycle `false/off`。
- 无新增 lifecycle proposal/transition/applied。
- 不消费或清理 `default` 队列旧消息。

## T06：R3 重试验收（不属于本轮发布授权）

- beat 停止，手工 scanner 最多处理目标 16 场的 due controls。
- 启用前用实际 worker `active_queues` 证明无人消费 `default`，否则 fail closed。
- claimed/dispatched 消息进入 `celery` 并由普通 worker 消费。
- 手工 scanner 后先证明相关 control generation 已增长，使旧 generation=1 消息 stale。
- shadow 只生成 proposal，不修改 `RaceEvent.status`。
- 失败时恢复 `false/off`，保留证据，不猜测成功。
