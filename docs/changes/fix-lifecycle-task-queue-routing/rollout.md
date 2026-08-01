# 生命周期单赛事任务队列路由修复发布方案

## 当前生产安全检查点

- R3 于 proposal 有界等待失败后自动恢复。
- lifecycle 当前为 `false/off`，web/worker/beat 已恢复，`race_live_worker` 未启动。
- 16 个 enrollment controls 保留为 shadow；赛事业务状态、proposal 和 applied 均未变化。
- `default` 队列中的 2 条旧 advance 消息不在本变更处理范围；claim 过期不自动使其 stale。

## 分阶段门禁

1. 本地：测试 RED → 子代理实现 → GREEN/回归 → 独立 review。
2. Git：取得当前 fingerprint 授权后方可 commit、push、PR、合并。
3. 关闭态部署：再次授权；保持 lifecycle `false/off`，不运行 scanner。
4. R3 重试：再次授权；启用前核对实际 worker `active_queues`，任何 worker 消费
   `default` 都 fail closed；保持 Beat 停止，仅手工 scanner smoke。
5. Generation 门禁：scanner 后核对目标 control generation 已增长，旧 generation=1 消息
   已被身份校验隔离；否则停止并恢复 `false/off`。
6. 观察：proposal 链路正确后才开始 24–48 小时 shadow 观察。

## 并行边界

- 不触碰主工作区或其他 worktree 的改动。
- 不处理新闻批次、普通 Celery 活跃任务或 race_live 积压。
- 部署时仍遵循共享 deployment lock 与 Celery drain；本地实现不接触生产。

## 回滚

- 代码回滚不涉及数据库恢复。
- 任一生产异常立即恢复 `.env` 为 `false/off` 并按现有受审部署恢复路径恢复服务。
- 不通过启动额外 `default` consumer 规避本修复。
