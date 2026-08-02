# Lifecycle shadow 纳管准备任务

按“测试 → 实现 → 验证 → review → 发布”执行。当前只授权文档与方案审核。

## 测试

- [x] (application) 为 strict manifest、prepare 资格/路径/哈希先写测试并取得真实 RED。
- [x] (application) 为 v2 dry-run/apply parity、DB drift 和 shadow-only 门禁先写 RED。
- [x] (application) 为 v1 apply 永久拒绝和 v2 apply 严格 false/off 门禁先写 RED。
- [x] (application) 为整批事务、replay、不同 manifest control 冲突先写 RED。
- [x] (integration) 在隔离 PostgreSQL 为双 apply 并发、锁序和零部分提交补充合同并实测。
- [x] (integration) 为 scanner false/off、true/shadow、mid-flight disable 和零 race-live
  dispatch 先写/补强 RED。

## 实现

- [x] (application) 实现 `race_event_lifecycle_enrollment.py` 的 strict loader、schema v2、
  snapshot、hash、preflight 和 verify。
- [x] (application) 实现只读 `prepare_race_event_lifecycle_enrollment` 命令和原子 artifact。
- [x] (application) 扩展 reconcile 命令，使 v2 dry-run/apply 共用 preflight。
- [x] (application) 将 v1 限定为 dry-run compatibility，并在 v2 写入前硬校验 false/off。
- [x] (application) 实现 shadow-only、≤20 场、排序行锁、单事务 create/replay。
- [x] (operations) 补充 false/off 下 prepare、dry-run、apply、verify 和后续 shadow
  开启/紧急停止命令模板；模板不得包含凭据。

## 验证

- [x] (application) 运行聚焦 lifecycle enrollment 和完整 lifecycle SQLite 回归。
- [x] (integration) 运行隔离 PostgreSQL 并发套件和 Celery task 回归。
- [x] (application) 运行日历、详情、race-live、scheduled result review 相邻回归。
- [x] (operations) 运行 Django check、migration drift、diff check、shell syntax/Compose
  config（若运维文件有变化）。
- [x] (operations) 冻结实现 fingerprint、文件范围、测试证据和残余风险。

## Review

- [x] (application) 使用未参与实现的独立 reviewer 做完整只读代码 review。
- [x] (application) 有 finding 时先写/补测试修复，并复用同一 reviewer 会话复审。
- [x] (operations) review 通过后冻结精确 fingerprint，停止并请求 commit/push/PR 授权。

## 发布

- [ ] (operations) 获授权后 commit、push、Draft PR；合并需要独立授权。
- [ ] (operations) 获授权后关闭态部署；不得同时打开 lifecycle。
- [ ] (operations) 生产只读 prepare 与 dry-run，提交精确 IDs/manifest SHA/预测结果供确认。
- [ ] (operations) 获独立授权后在 false/off 下 apply control 并 verify。
- [ ] (operations) 再获独立授权后打开 true/shadow，观察至少 48 小时且跨实际边界。
- [ ] (operations) 完成 observation report；不得自动进入 enforce。
