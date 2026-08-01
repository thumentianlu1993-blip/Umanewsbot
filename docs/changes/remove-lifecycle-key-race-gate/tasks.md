# 移除 lifecycle 重点赛事资格门禁任务

- [x] (application) 测试先行：新增非重点赛事 prepare、dry-run、apply 与混合批次测试并取得真实 RED。
- [x] (application) 实现：移除 strict v2 enrollment 的 `is_key_race` 资格拒绝，保留审计快照与其他硬门禁。
- [x] (application) 验证：运行 lifecycle SQLite、PostgreSQL 并发和 Django/migration/diff 检查。
- [ ] (operations) review：由未参与实现的 reviewer 执行原生只读代码审核并冻结 fingerprint。
- [ ] (operations) R0 代码发布：最新 review 后取得授权，commit、push、PR、合并并以 `false/off` 部署。
- [ ] (operations) R1 只读准备：另获授权后生成 16 场逐场审核表、strict manifest 和 dry-run，停止并提交精确 SHA。
- [ ] (operations) R2 control 纳管：另获精确 manifest 授权后备份，在 `false/off` 下 apply/verify，再次停止。
- [ ] (operations) R3 shadow：另获 16 IDs、manifest、revision 和 24–48 小时窗口授权后启用 `true/shadow` 并观察。
- [ ] (operations) enforce：作为独立 change 完成观察复盘、测试、review 和用户授权，不由本任务自动开启。
