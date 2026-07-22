## 0. Pre-declared hypotheses

- [x] 0.1 (operations) 索引修复 PASS：维护后 60 分钟同类 B-tree 错误为 0，事务写入探针和至少一轮真实抓取成功；任一同类错误或写入失败为 BLOCKER
- [ ] 0.2 (application) 任务收敛 PASS：dry-run 对业务表零写入，apply 只更新 manifest 中仍为 started 且无活动证据的记录，迟到任务零终态覆盖；任一误收敛或覆盖为 BLOCKER
- [ ] 0.3 (application) 可观测性 PASS：最近成功与 2h/24h 滚动失败、超时任务可同时展示，任一索引物理错误产生 P0 信号；被成功状态掩盖为 BLOCKER

## 1. P0 索引即时修复

- [x] 1.1 (operations) 取得维护窗口确认，记录生产 HEAD/数据库版本/索引身份/磁盘/活动写入，生成并验证数据库与 `.env` 备份 (req: req-index-repair-preflight)
- [x] 1.2 (operations) 暂停 beat/worker 和后台文章编辑，按锁定索引执行受控 `REINDEX INDEX`，禁止 drop index 或删除文章 (req: req-controlled-reindex) (adr: adr-001-reindex-window)
- [x] 1.3 (operations) 完成 pg_index、可用时 amcheck、事务回滚写入探针和真实抓取验证后恢复服务 (req: req-index-repair-verify) (adr: adr-002-three-layer-check)
- [x] 1.4 (operations) 连续观察 60 分钟索引错误、新稿入库、CrawlJob、`/healthz/`、首页和五地区页，BLOCKER 立即停止扩大 (req: req-index-repair-verify) (req: req-index-error-alert)

## 2. 抓取终态与遗留任务收敛

- [x] 2.1 (application) 将 `_finish_crawl_job()` 改为 started→success/failed 的条件终态写，并在未抢到终态时记录 `terminal_state_already_claimed` (req: req-crawl-terminal-cas) (adr: adr-003-stale-job-cas)
- [x] 2.2 (integration) 调整来源最近状态更新，只允许成功抢占 CrawlJob 终态的执行更新 `NewsSource.last_crawl_*` (req: req-crawl-terminal-cas)
- [x] 2.3 (application) 新增遗留 CrawlJob dry-run manifest 命令，输出固定选择器、活动执行证据、关联文章数、建议动作和 SHA-256 (req: req-stale-crawl-reconcile)
- [x] 2.4 (application) 为 manifest apply 实现逐行锁定、状态漂移跳过、幂等更新和有界批次，禁止无 manifest 写入 (req: req-stale-crawl-reconcile) (adr: adr-003-stale-job-cas)

## 3. 索引与来源健康审计

- [x] 3.1 (application) 新增只读新闻数据库完整性审计入口，输出目标索引定义、pg_index 状态、表/索引大小和可用的物理检查能力 (req: req-index-repair-preflight) (adr: adr-002-three-layer-check)
- [x] 3.2 (integration) 扩展来源健康聚合，分开当前运行、最近完成、2h/24h 失败、超时 started、最后成功和稳定错误类别 (req: req-source-rolling-failures) (adr: adr-004-rolling-health)
- [x] 3.3 (application) 在地区概览/异常检测复用滚动健康聚合，任一索引物理错误生成有冷却的 P0 `ops_anomaly` (req: req-index-error-alert)

## 4. 配置、文档与自动化验证

- [x] 4.1 (operations) 更新 `.env.example` 与 settings 中遗留任务阈值、滚动失败窗口和 P0 冷却配置，默认保持自动 apply 关闭 (req: req-stale-crawl-reconcile) (req: req-index-error-alert)
- [x] 4.2 (operations) 在 deploy_runbook 记录索引预检/重建/三层验收和遗留任务 manifest/apply/回滚步骤 (req: req-controlled-reindex) (req: req-stale-crawl-reconcile)
- [x] 4.3 (operations) 更新 current_state、decisions 和 project_status，明确即时生产修复与后续代码部署是两个独立门禁 (adr: adr-001-reindex-window)
- [x] 4.4 (application) 增加 CrawlJob 条件终态、迟到结果、manifest 零写入/SHA/活动任务跳过/漂移/幂等回归测试 (req: req-crawl-terminal-cas) (req: req-stale-crawl-reconcile)
- [x] 4.5 (application) 增加滚动健康与索引错误 P0 信号测试，覆盖“最后成功但近期失败” (req: req-source-rolling-failures) (req: req-index-error-alert)
- [x] 4.6 (operations) 运行目标/完整测试、Django check、Compose config、OpenSpec strict 校验和 `git diff --check` (req: req-index-repair-verify)

## 5. 代码部署与遗留任务处置

- [ ] 5.1 (operations) 在独立干净工作树完成代码集成，备份并部署后核对 HEAD/容器环境/worker/beat/healthz (req: req-crawl-terminal-cas)
- [ ] 5.2 (operations) 以执行时新快照生成遗留 CrawlJob manifest，经用户确认后 apply；审计中的 32 条只作基线 (req: req-stale-crawl-reconcile)
- [ ] 5.3 (operations) 再观察 60 分钟滚动错误、迟到任务、来源健康和真实入库，异常时停止遗留处置并回滚代码 (req: req-source-rolling-failures) (req: req-index-error-alert)
