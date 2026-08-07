# 最近赛事赛果定时收集与邮件审阅任务

## 1. 方案与门禁

- [x] (operations) 从最新 `origin/main` 建立干净隔离 worktree 和分支。
- [x] (integration) 只读梳理一次性 recovery inventory、adapter、coverage、dry-run/apply 与邮件链路。
- [x] (application) 明确最近 72 小时、完整赛果、Also ran、唯一审核授权和状态修复语义。
- [x] (application) 完成首次独立方案审核并关闭全部阻断 finding。
- [x] (operations) 方案通过后向用户汇报并取得“G1 范围确认”。

## 2. 测试先行

- [x] (application) 新增时间窗口、到期状态、canonical duplicate 和 result completeness RED。
- [x] (integration) 新增动态 route、machine-bound snapshot、网络合同和来源 authority RED。
- [x] (integration) 新增完整顺序、Also ran、runner 守恒和 coverage blocker RED。
- [x] (application) 新增不可变 bundle、SHA、文件安全和 dry-run 零写入 RED。
- [x] (integration) 新增 durable email intent、附件、失败重试、成功去重和并发 RED。
- [x] (application) 新增 exact reviewed bundle apply/verify/rollback/replay RED。
- [x] (application) 新增 run/pending/delivery/approval 四个治理模型及 migration RED。
- [x] (operations) 新增 Beat/Codex slot claim、catch-up、wrapper、Compose mount 和默认关闭 RED。
- [x] (integration) 实际运行并保存真实 RED 证据。

## 3. 实现

- [x] (application) 实现最近 72 小时 selector、result completeness 和 status repair 分类。
- [x] (integration) 实现版本化动态来源 route registry 与唯一 adapter 选择。
- [x] (integration) 复用 recovery 完整顺序与 B0.1 receipt，保留旧一次性 recovery 合同。
- [x] (application) 实现 prepare 管理命令、不可变 bundle 和 verifier。
- [x] (integration) 实现 RaceResultReviewDelivery durable intent、EmailMessage 附件、重试与去重。
- [x] (application) 实现 reviewed bundle dry-run/apply/verify 管理命令。
- [x] (application) 实现 human-reviewed-reference promotion、公开 authority 语义和四个治理模型 migration。
- [x] (operations) 增加默认关闭设置、env 示例、生产持久化 mount 和固定备用 wrapper。
- [x] (operations) 更新 current state、decisions、runbook、project status 和本 change 状态。

## 4. 验证与独立审核

- [x] (application) 聚焦测试 GREEN，运行现有 recovery/lifecycle 回归。
- [x] (operations) Django check、migration drift、compile、Compose config、shell 静态检查。
- [x] (integration) fake transport 端到端 prepare，验证邮件附件、业务写 0 和重放去重。
- [x] (application) 未参与实现的 reviewer 使用
  `codex review -c 'sandbox_mode="read-only"' --uncommitted` 完成首次完整审核。
- [x] (application) 如有 finding，由实现 subagent 修复并复用同一 reviewer 限定复审。
- [x] (operations) 冻结完整 fingerprint、approved parent 和 content manifest hash。

最终独立审核已批准 fingerprint
`a8b8a4f5dc7879d378137d88acbbfe7bb6849d8446825419a2ee9a35622c76f0`；
approved parent 为 `0bf3fd975155795c6df885b1055bd97c342db880`，content manifest 为
`0a20affb4c574b715b874575159d42366609e17e8edbf2cec091854f997d67e7`。

## 5. 发布与调度

- [x] (operations) commit、push、创建 PR、合并并部署，应用 migration，保持两个新开关关闭。
- [x] (operations) 验证生产版本、Compose mount、SMTP 配置、SSH wrapper 和 flag-off 三个零。
- [x] (integration) 在已授权窗口启用 prepare/network 和唯一收件人，执行一次受控生产 prepare。
- [ ] (application) 用户核对测试审核邮件格式和 bundle SHA。
- [x] (operations) 启用生产 Beat schedule，并创建同 slot 的 Umanews Codex cron 备用触发。
- [x] (operations) 验证两次等价 scheduled smoke、失败通知与无重复邮件。
- [x] (operations) 按 evidence-only allowlist 写回生产 SHA、run ID、bundle/email/health 事实。

生产首轮虽完成调度与邮件闭环，但 `13/13` 目标为 `route_missing`、候选为 `0`。因此本 change
的发布任务已完成，产品验收未完成；必须新增来源身份 discovery 修复并重新 prepare，不能把
blocker 包当作完整赛果审核包。

## 6. 后续运行

- [ ] (application) 每封审核邮件等待用户以完整 bundle SHA 和 event scope 明确批准。
- [ ] (operations) 批准后执行 apply dry-run -> apply -> 独立 verify。
- [ ] (operations) 未批准、blocked 或漂移候选保留，不写库；下一调度自动重新检查。
