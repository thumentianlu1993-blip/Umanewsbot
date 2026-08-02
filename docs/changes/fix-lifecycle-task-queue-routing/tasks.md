# 生命周期单赛事任务队列路由修复任务

## 测试

- [x] (integration) 新增 route 与生产 worker 默认队列一致性合同测试。
- [x] (integration) 新增旧 claim 过期后重新 claim、旧消息 stale、新消息可执行的回归测试。
- [x] (integration) 在旧 route 上运行测试并取得目标能力缺失导致的真实 RED。

## 实现

- [x] (integration) 将 `advance_race_event_lifecycle_task` route 改为 `celery`，不改其他 task route。
- [x] (operations) 更新当前状态、决策、运维和发布边界文档。

## 验证

- [x] (integration) 运行聚焦 route 测试与完整 lifecycle/enrollment 回归（101/101）。
- [x] (application) 运行 Django check 与 migration drift 检查。
- [x] (operations) 运行 `git diff --check`；review fingerprint 待 reviewer 冻结。

## review

- [ ] (integration) 由未参与实现的 reviewer subagent 执行原生只读 review。
- [ ] (integration) 如有 finding，由原 reviewer 同一会话复审。

## 发布

- [ ] (operations) review 通过后等待用户针对冻结 fingerprint 授权 commit/push/PR/合并。
- [ ] (operations) 另行授权后执行 lifecycle `false/off` 关闭态部署与验收。
- [ ] (operations) 再次单独授权后先核对实际 active queues，再重试 R3 shadow smoke并确认
  generation 增长；不处理旧 `default` 消息。
