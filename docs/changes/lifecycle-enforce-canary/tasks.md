# lifecycle enforce canary 任务

## 测试

- [x] (application) 新增 canary manifest、apply/runtime 双期限、关闭态原子 apply、重放/漂移/审计 RED。
- [x] (application) 新增运行时精确 cohort、状态更新、缓存、并发与幂等 RED。
- [x] (operations) 新增 promotion shared-lock wrapper、true/enforce 分阶段 mode switch、激活与失败回退 RED。

## 实现

- [x] (application) 实现 canary artifact loader/prepare/preflight/apply/verify/advisory lock，复用 enrollment 安全原语。
- [x] (application) 将 enforce runtime 与独立 settings、control 证据及原子 activation 三重绑定。
- [x] (operations) 实现 promotion wrapper，扩展部署 mode switch 与只读 verifier，保留 false/off 无条件止损路径。
- [x] (operations) 更新 `.env.example` 与运行手册，但不写任何生产值。

## 验证

- [x] (application) 运行聚焦、生命周期/纳管回归及 PostgreSQL 并发测试。
- [x] (operations) 运行 shell fake harness、`sh -n`、Django/migration/workflow/diff 检查。
- [x] (application) 证明其他 control 保持 shadow、race-live/新闻/QQ 零触发。

## review

- [x] (application) 未参与实现的 reviewer 以只读 sandbox 审核未提交全集。
- [x] (application) 在同一 reviewer 上下文关闭 findings 并复验。
- [x] (operations) 冻结 review fingerprint 与精确候选文件清单。

## 发布

- [ ] (operations) 等待用户绑定 commit/PR 的 G2 授权；本实现轮不提交或发布。
- [ ] (operations) 另行等待绑定 canary manifest SHA、event 186/187 和生产 revision 的 G3 授权。
- [ ] (operations) 获准后按 false/off→control apply→true/enforce→smoke/观察执行；异常立即 false/off。
