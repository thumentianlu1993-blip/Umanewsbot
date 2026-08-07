# Lifecycle shadow 观察加固任务

## 测试

- [x] (application) 为 shadow success/duplicate、真实 error、旧消息兼容和配置 mismatch 编写测试，取得真实 RED。
- [x] (operations) 为 wrapper canonical run grammar、宿主全量 census 和专用 mode switch 编写 fake-Docker/文件系统合同测试，取得真实 RED。

## 实现

- [x] (application) 修正 shadow attempt 成功语义，不改变状态机、去重键和公开状态。
- [x] (integration) 在 scanner/advance task 间加入向后兼容的运行配置握手和结构化 mismatch 日志。
- [x] (operations) 加固 Compose wrapper one-off 参数合同，实现只读宿主全量一致性检查和共享锁保护的 mode switch。

## 验证

- [x] (application) 运行 lifecycle/enrollment 聚焦测试、SQLite 回归和 PostgreSQL 并发测试。
- [x] (operations) 运行单一 migration owner、P0 deployment、shell、Compose、Django、migration drift 和 diff 检查。
- [x] (integration) 核对 task route、旧消息兼容、mismatch→TTL→重领完整链及真实错误退避。

## Review

- [x] (application) 由未参与实现的独立 reviewer 执行原生只读 `/review`，修复全部 actionable findings 并复用同一会话复审。
- [ ] (operations) 冻结最终 fingerprint、approved parent 与 content hash，停止等待发布授权。

## 发布

- [ ] (operations) 获得当前 fingerprint 授权后 commit、push、PR、merge，并以 `false/off` 从隔离 release 部署。
- [ ] (operations) 核对备份、共享锁、单一 release owner、三服务一致性、HTTP、队列、migration 和 race-live 关闭态。
- [ ] (operations) 另获授权后恢复现有 16 场 `true/shadow`，运行一致性检查并观察两地区 2–4 场自然 T/T+30。
- [ ] (integration) 追加 evidence-only 发布报告并复用同一 reviewer 完成证据收口；enforce 另立 change。
