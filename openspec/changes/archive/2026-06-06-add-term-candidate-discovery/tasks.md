## 1. 持久化与核心发现能力

- [x] 1.1 (application) 新增支持的候选状态和类型、`TermCandidate` 与 `TermCandidateEvidence` 模型，包括审核信息、合并/接受关联、受限 JSON 证据字段和数据库唯一约束。
- [x] 1.2 (application) 创建并审查候选与证据表的 Django 迁移、索引、约束和安全的可空关联。
- [x] 1.3 (integration) 实现保守的日文术语标准化，以及与相同类型正式 `TermEntry.source_ja`/`aliases_ja` 的匹配，包括停用术语和跨类型冲突报告。
- [x] 1.4 (integration) 实现马名、比赛名、骑手名和马主名的结构化规则发现器，复用现有未知马名行为且不破坏翻译保护。
- [x] 1.5 (integration) 实现幂等候选与证据聚合，包括原文精确校验、置信度过滤、受限上下文、计数更新和稳定的拒绝/忽略状态。

## 2. 异步入库集成

- [x] 2.1 (application) 新增 `TERM_DISCOVERY_ENABLED`、发现 provider 和最低置信度设置，并在 `.env.example` 中记录默认值。
- [x] 2.2 (application) 新增 `discover_term_candidates_task`，记录 `TaskExecutionLog` 成功/失败详情，并返回适合运维排查的结果数据。
- [x] 2.3 (application) 仅对新增文章在现有翻译链路旁路触发发现任务，并捕获调度/任务错误，确保抓取、翻译、改写和发布不受影响。
- [x] 2.4 (application) 新增仅工作人员可用的单篇文章重新发现操作，复用幂等任务且不提供历史全量发现。

## 3. 审核与正式确认工作流

- [x] 3.1 (integration) 实现接受、修改后接受、合并、拒绝和忽略的事务化候选审核服务，包括操作时重新检查正式术语和记录操作日志。
- [x] 3.2 (integration) 将候选文本加入正式术语日文别名前必须获得明确确认，并在合并后保留全部来源候选证据。
- [x] 3.3 (application) 新增候选审核表单与校验，覆盖支持类型、中文译词、别名、优先级、备注、审核备注和合并目标。
- [x] 3.4 (application) 新增仅工作人员可用的候选列表、详情和操作路由与视图，支持状态、类型、置信度、来源、时间、关键词筛选和正式术语冲突上下文。
- [x] 3.5 (application) 使用现有运营后台样式新增响应式候选列表/详情模板、证据展示、审核操作、导航入口和待审核候选徽标。
- [x] 3.6 (application) 新增保守的批量拒绝/忽略操作，接受和合并仍只允许单条处理。

## 4. 验证

- [x] 4.1 (integration) 增加发现器、标准化、正式术语匹配、跨类型冲突、聚合、置信度、原文精确校验和受限证据测试。
- [x] 4.2 (application) 增加模型约束、任务隔离/幂等、工作人员鉴权、列表/详情筛选、审核操作、确认事务、合并和操作日志测试。
- [x] 4.3 (application) 运行 `DB_ENGINE=sqlite python manage.py check` 和 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`，并解决回归。
- [x] 4.4 (operations) 运行两种生产 Compose 配置检查，确认新环境变量进入 `web`、`worker` 和其他受影响的运行服务。

## 5. 灰度与文档

- [x] 5.1 (operations) 记录默认关闭部署、迁移、单篇手动验证、候选质量抽检、逐步启用、监控和无需回滚数据结构即可关闭的步骤。
- [x] 5.2 (operations) 使用中文更新 `docs/current_state.md`、`docs/decisions.md`、`docs/deploy_runbook.md`、`docs/project_status.md` 和相关管理员/术语文档，记录已实现行为和验证命令。
- [x] 5.3 (operations) 生产启用前检查密钥泄露、不安全候选确认路径、无界证据增长和回滚缺口。
