# 历史新闻正文污染盘点与重处理任务清单

## 0. 规划与授权

- [x] 0.1 (operations) 从已验证 `origin/main@97dd2350` 建立独立干净 worktree 和 `codex/` 分支
- [x] 0.2 (integration) 只读核对既有解析修复、翻译/改写写入路径、状态模型及生产冻结 cohort
- [x] 0.3 (operations) 编写 spec/design/test/tasks/rollout 与零上下文 handoff
- [x] 0.4 (operations) 完成独立方案审核；两轮 finding 修订后复用同一 reviewer 会话复审通过
- [x] 0.5 (operations) 方案审核通过后停止，等待用户明确确认实现

## 1. 测试（仅在用户确认实现后）

- [ ] 1.1 (integration) 测试 subagent 添加层级污染、正常正文、缺 HTML/解析失败 fixture 与 inventory RED
- [ ] 1.2 (application) 测试 subagent 添加 candidate prepare 零写入、人工字段保护、exact output hash RED
- [ ] 1.3 (application) 测试 subagent 添加模板/提交工作簿分离、证据列白名单、manifest 绑定与篡改拒绝 RED
- [ ] 1.4 (application) 测试 subagent 添加逐字段 allowlist、apply 原子漂移、并发、幂等、发布/QQ 不变量 RED
- [ ] 1.5 (operations) 测试 subagent 添加 verifier/rollback、持久 artifact 权限和真实 PostgreSQL RED
- [ ] 1.5a (operations) 测试 subagent 添加 DB read-only 写探针、rollback 预写 fsync 失败和 post-commit
  receipt crash recovery RED
- [ ] 1.6 (integration) 实际运行聚焦测试并记录目标行为未实现导致的 RED

## 2. 实现（仅在有效 RED 后）

- [ ] 2.1 (integration) 实现 subagent 扩展 DB 强制只读 inventory，分开事实分类与人工 action
- [ ] 2.2 (application) 实现 subagent 增加 detached DTO + pure provider candidate prepare，禁止所有在线写路径
- [ ] 2.3 (application) 实现 subagent 增加 immutable template evidence、submitted workbook 严格回读和
  canonical exact-output 批准 manifest
- [ ] 2.4 (application) 实现 subagent 增加 dry-run/commit 服务，单事务锁全集并精确写批准字段
- [ ] 2.5 (application) 实现 subagent 增加事务前完整 rollback artifact 原子持久化、可重建 receipt、
  独立 verifier 和 CAS rollback
- [ ] 2.6 (operations) 实现 subagent 增加显式持久 artifact 挂载/运行说明；默认生产 Compose 不扩大常驻挂载
- [ ] 2.7 (operations) 更新 current_state/decisions/project_status/deploy_runbook 与命令帮助

## 3. 验证与代码审核

- [ ] 3.1 (integration) 运行聚焦及既有正文、翻译、改写、发布、QQ 回归并取得 GREEN
- [ ] 3.2 (application) 运行真实 PostgreSQL 原子性/并发/rollback、等价规模和查询数验证
- [ ] 3.3 (operations) 运行 Django check、migration drift、compile/static、Compose config、diff check
- [ ] 3.4 (operations) 未参与实现的 reviewer 执行 Codex 原生只读 `/review` 并记录 fingerprint
- [ ] 3.5 (application) 有 actionable finding 时由实现 subagent 修复并复用同一 reviewer 会话复审
- [ ] 3.6 (operations) 最新 code review 通过后停止，等待当前精确版本发布授权

## 4. 工具发布（独立授权）

- [ ] 4.1 (operations) 核对受审 fingerprint、生产 HEAD/镜像/队列/磁盘和恢复点
- [ ] 4.2 (operations) 经用户授权后 commit/push/PR/merge/deploy，无业务数据写入
- [ ] 4.3 (operations) 验证命令可见、Django check、migration drift、容器 revision、healthz 与 artifact 挂载方案

## 5. 正式 inventory 与人工审核（再次独立授权）

- [ ] 5.1 (operations) 在显式持久挂载的一次性只读容器生成 282 篇冻结总账，不运行 apply
- [ ] 5.2 (operations) 拷贝并核对 manifest/SHA，独立验证穷尽计数、权限、零业务写入
- [ ] 5.3 (integration) 选择小批候选并在获准后生成 exact translation/rewrite candidate
- [ ] 5.4 (operations) 生成人审包，由人工逐篇决定并定稿，冻结批准 manifest SHA

## 6. 历史写入（绑定精确 manifest 的再次授权）

- [ ] 6.1 (operations) 创建并验证 PostgreSQL custom-format 备份与环境/镜像恢复点
- [ ] 6.2 (operations) 先对 pilot 批次运行 dry-run，独立核对字段 diff 与全部不变量
- [ ] 6.3 (operations) 经用户针对 exact manifest SHA 授权后 apply pilot（默认最多 10 篇）
- [ ] 6.4 (operations) 立即运行 verifier 和浏览器验收 `9623/9519/正常反例`
- [ ] 6.5 (operations) pilot 通过后逐批申请授权；失败则停止并按 CAS rollback 方案处理
- [ ] 6.6 (operations) 输出最终总账：批准/成功/失败/阻断/未处理、receipt、rollback 和不可逆 QQ 说明
