## 1. 术语门禁规则实现

- [x] 1.1 (integration) 梳理 `validate_rewrite()`、`source_terms_by_entry()` 和正式术语匹配调用点，确认英文发布校验当前术语范围和 blocker 生成路径。
- [x] 1.2 (integration) 实现英文发布校验的地区过滤，第一版只纳入文章同地区和 `racing_region=""` 的全局通用术语。
- [x] 1.3 (integration) 实现 settings 驱动的高歧义英文术语治理规则，支持配置化降级、忽略或强上下文要求。
- [x] 1.4 (integration) 调整 `core_term_missing` 生成逻辑，使高歧义低可信命中降级为 warning/info，可信核心实体缺失仍生成 blocker。
- [x] 1.5 (application) 不新增 `TermEntry` 字段；补充 settings 默认配置和服务层读取逻辑，确保未配置时行为可预测。
- [x] 1.6 (operations) 如高歧义词清单通过环境变量或部署配置暴露，补充 `.env.example` 和运维说明。

## 2. 重处理与审计

- [x] 2.1 (application) 增加受控重处理入口，支持 dry-run、地区、来源、时间范围和提交模式，默认只处理最近一次候选回看窗口内的误挡文章。
- [x] 2.2 (integration) 重处理入口复用现有评分和发布校验，不直接发布文章，不绕过人工拒绝、撤回、重复内容或其他硬门禁。
- [x] 2.3 (application) 让通过重处理的文章重新具备发布窗口可见性，例如设置复审时间或等价候选回看信号。
- [x] 2.4 (application) 扩展生产审计输出，按地区统计高频 `core_term_missing`、地区排除、降级 warning、仍需治理的高频词和示例文章。
- [x] 2.5 (operations) 更新 `docs/current_state.md`、`docs/project_status.md` 和 `docs/deploy_runbook.md`，记录门禁规则、重处理方式和上线验收口径。

## 3. 测试与验证

- [x] 3.1 (application) 补充英文高歧义词不生成 blocker 的单元测试，覆盖 `CLASS`、`CONTENT` 或等价配置词。
- [x] 3.2 (application) 补充同地区可信赛事 / 马名缺失仍生成 `core_term_missing` blocker 的回归测试。
- [x] 3.3 (application) 补充非同地区术语不阻断当前地区文章、全局术语仍纳入校验的测试。
- [x] 3.4 (application) 补充重处理 dry-run、提交、跳过人工终态和重新进入发布候选的测试。
- [x] 3.5 (operations) 执行 `DB_ENGINE=sqlite python manage.py check`、目标测试、`openspec validate fix-english-term-gate-region-filter --strict`、`openspec validate --all` 和 `git diff --check`。
- [ ] 3.6 (operations) 上线后只读验证香港、英国、美国最近窗口的 `core_term_missing` blocker 数、`publish_ready` 数和公开数量，并记录到运行文档。
