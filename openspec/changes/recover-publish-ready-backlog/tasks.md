## 0. Pre-declared hypotheses

- [x] 0.1 (application) 正确性 PASS：入库超过 3 小时但最近进入 ready 的文章能被积压通道选中，超过自动期限的文章为 0 自动发布；任一漏选或过期自动公开为 BLOCKER
- [x] 0.2 (application) 安全 PASS：当前 21 篇历史候选在无审核 manifest 时写入和公开均为 0，apply 不绕过门禁/去重/配额/QQ；任一越权为 BLOCKER
- [x] 0.3 (integration) 性能 PASS：每地区每窗口实时/积压查询均命中有界 limit，总候选 SQL 不超过既有基线 +4，生产等价 1,000 条 ready 积压选择低于 2 秒；无界扫描为 BLOCKER

## 1. 发布资格时间与配置

- [x] 1.1 (application) 为 NewsArticle 增加 nullable `publish_ready_at` 和地区/状态/时间组合索引，历史数据不回填，并生成安全 migration (req: req-publish-ready-time) (adr: adr-001-ready-timestamp)
- [x] 1.2 (integration) 统一非 ready→publish_ready 路径设置资格时间，增加显式 refresh 意图；已 ready 的重复校验、普通保存和非资格更新不得刷新 (req: req-publish-ready-time)
- [x] 1.3 (application) 增加实时回看、自动消费 24h、人工复核 72h、双通道 limit 和灰度开关 settings/.env.example，默认积压通道关闭 (req: req-stale-ready-review) (req: req-backlog-query-bounded) (adr: adr-003-age-policy)

## 2. 双通道候选选择

- [x] 2.1 (integration) 将 publishing window 候选拆成实时和 publish_ready 积压两个有界 queryset，按 article ID 合并去重 (req: req-candidate-backlog-fill) (adr: adr-002-dual-candidate-lane)
- [x] 2.2 (integration) 保持现有主地区、硬门禁、内容指纹、分数、软填充和配额逻辑，并在同分时优先更早 ready 的候选 (req: req-candidate-backlog-fill)
- [x] 2.3 (integration) 为候选决策记录通道、publish_ready_at、年龄、截断、未选原因和过期层级 (req: req-stale-ready-review) (req: req-backlog-query-bounded)
- [x] 2.4 (application) 扩展地区生产审计和后台概览，展示 0–24h ready、24–72h 待复核、>72h 过期处置和最老年龄 (req: req-stale-ready-review)
- [x] 2.5 (application) 为过期待复核增加有冷却的积压异常信号，不在发布窗口隐式修改文章工作流 (req: req-stale-ready-review) (adr: adr-003-age-policy)

## 3. 历史积压审核与恢复

- [x] 3.1 (application) 新增历史 publish_ready dry-run 命令，固定 ID/状态/内容/门禁指纹并输出建议处置与 manifest SHA (req: req-backlog-recovery-manifest) (adr: adr-004-legacy-manifest)
- [x] 3.2 (application) 实现已审核 manifest apply：逐篇锁定、漂移跳过、完整重校验，仅通过者刷新 publish_ready_at (req: req-backlog-recovery-manifest)
- [x] 3.3 (integration) 确保恢复路径不设置 published_to_web_at、不创建 QQ delivery，并继续等待正常窗口 (req: req-backlog-recovery-manifest)

## 4. 文档与自动化验证

- [x] 4.1 (operations) 更新 current_state、decisions、deploy_runbook、project_status 和 `.env.example`，记录年龄策略、灰度、恢复与回滚 (adr: adr-003-age-policy) (adr: adr-004-legacy-manifest)
- [x] 4.2 (application) 增加旧行为红灯测试：first_seen 超 3h、刚进入 ready 的文章旧查询不可见 (req: req-candidate-backlog-fill)
- [x] 4.3 (application) 增加双通道、重复合并、年龄边界、配额竞争、相关地区和关闭开关回归测试 (req: req-candidate-backlog-fill) (req: req-stale-ready-review)
- [x] 4.4 (application) 增加 migration、资格时间不误刷、manifest 零写入/漂移/幂等和不直接发布测试 (req: req-publish-ready-time) (req: req-backlog-recovery-manifest)
- [x] 4.5 (integration) 增加有界查询、SQL 数、1,000 条积压性能与内存测试 (req: req-backlog-query-bounded)
- [x] 4.6 (operations) 运行目标/完整测试、migration apply/rollback/reapply、Django check、Compose config、OpenSpec strict 和 `git diff --check` (req: req-backlog-query-bounded)

## 5. 生产灰度与历史处置

- [x] 5.1 (operations) 部署前备份并核对生产 HEAD/环境/容器/迁移，部署后保持积压通道关闭并执行只读候选预览 (req: req-candidate-backlog-fill)
- [x] 5.2 (operations) 先开启一个地区并观察 4 个窗口，再扩到五地区；验证每窗口和全站配额未变化 (req: req-candidate-backlog-fill)
- [ ] 5.3 (operations) 对当前历史候选生成新 manifest，按“默认不自动公开”提交用户审核后再执行批准动作 (req: req-backlog-recovery-manifest)
- [ ] 5.4 (operations) 观察 24 小时候选消费、过期队列、窗口决策、公开页和 QQ，异常时关闭积压通道 (req: req-stale-ready-review)
