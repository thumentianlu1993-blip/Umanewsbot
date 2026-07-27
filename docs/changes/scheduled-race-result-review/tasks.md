# 最近赛事赛果定时收集与邮件审阅任务

## 1. 方案与门禁

- [x] (operations) 从最新 `origin/main` 建立干净隔离 worktree 和分支。
- [x] (integration) 只读梳理一次性 recovery inventory、adapter、coverage、dry-run/apply 与邮件链路。
- [x] (application) 明确最近 72 小时、完整赛果、Also ran、唯一审核授权和状态修复语义。
- [x] (application) 完成首次独立方案审核并关闭全部阻断 finding。
- [x] (operations) 方案通过后向用户汇报并取得“确认实现”。

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
- [ ] (integration) fake transport 端到端 prepare，验证邮件附件、业务写 0 和重放去重。
- [ ] (application) 未参与实现的 reviewer 使用
  `codex review -c 'sandbox_mode="read-only"' --uncommitted` 完成首次完整审核。
- [ ] (application) 如有 finding，由实现 subagent 修复并复用同一 reviewer 限定复审。
- [ ] (operations) 冻结完整 fingerprint、approved parent 和 content manifest hash。

当前审核状态：首次 review session `019fa425-c6fc-7e72-9483-5afa281fcfeb` 返回
`REVISE`（4 项 P1）；四项均已真实 RED -> GREEN，含 PostgreSQL `2/2` 锁证据，待同一 session
限定复审后确认原四项已关闭。该轮新增的 verify 空 scope 与 apply 部分失败退出 0 两项 P1
也已真实 RED -> GREEN；最新聚焦 `19/19`、直接相邻组合 `109/109`，仍待同一 session
再次限定复审后再勾选上述审核任务。

## 5. 发布与调度

- [ ] (operations) 最新成功 review 后取得当前冻结版本发布授权。
- [ ] (operations) commit、push、创建 PR、合并并部署，应用 migration，保持两个新开关关闭。
- [ ] (operations) 验证生产版本、Compose mount、SMTP 配置、SSH wrapper 和 flag-off 三个零。
- [ ] (integration) 在已授权窗口启用 prepare/network 和唯一收件人，执行一次受控生产 prepare。
- [ ] (application) 用户核对测试审核邮件格式和 bundle SHA。
- [ ] (operations) 启用生产 Beat schedule，并创建同 slot 的 Umanews Codex cron 备用触发。
- [ ] (operations) 验证两次等价 scheduled smoke、失败通知与无重复邮件。
- [ ] (operations) 按 evidence-only allowlist 写回生产 SHA、run ID、bundle/email/health 事实。

## 6. 后续运行

- [ ] (application) 每封审核邮件等待用户以完整 bundle SHA 和 event scope 明确批准。
- [ ] (operations) 批准后执行 apply dry-run -> apply -> 独立 verify。
- [ ] (operations) 未批准、blocked 或漂移候选保留，不写库；下一调度自动重新检查。
