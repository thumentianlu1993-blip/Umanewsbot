## Context

生产 `NewsArticle` 只有约 9.5k 行，`public_slug` 是 Django `SlugField` 自动创建的普通 B-tree 索引，不是唯一约束或主键。该索引在最近 61 小时内反复报告 `overlaps with invalid duplicate tuple` / `cannot find insert offset`，说明需要按物理损坏处理，不能通过调整 slug 去重逻辑绕过。与此同时，抓取任务用 `CrawlJob.status=started` 表示运行中，当前完成函数会无条件保存旧内存对象；若运维先把超时任务收敛为失败，迟到任务仍可能覆盖结论。

本设计必须保持公开读服务、Django 单体和现有任务链路，且任何生产写入都要有备份、清单、回滚与写后验证。P0 索引修复不依赖应用代码变更，在用户批准维护窗口后立即执行；任务终态与健康代码随后实现、部署，再处理遗留任务。

## Goals / Non-Goals

**Goals:**

- 在最小写入暂停窗口内重建损坏索引，并用结构、物理和真实写入三层证据验收。
- 让超时 `CrawlJob` 可安全、可审计地收敛，且迟到任务不能覆盖终态。
- 让滚动失败、超时遗留和当前运行分别可见，最新成功不能掩盖近期异常。
- 为本次 32 条遗留任务提供 SHA 锁定的 dry-run/apply 流程。

**Non-Goals:**

- 不修改 `public_slug` 的业务生成规则、唯一性或公开 URL。
- 不借索引修复清理文章、重跑翻译或发布积压。
- 不自动杀 Celery 任务、数据库会话或容器进程。
- 不把所有历史 `started` 记录无条件改成失败。

## Decisions

### Decision 1: 以短维护窗口执行原位 `REINDEX INDEX` <!-- adr: adr-001-reindex-window -->

**Choice：** 先确认 `pg_get_indexdef`、`pg_index`、索引所属关系和非约束身份；暂停 beat、worker 与后台文章编辑，完成数据库备份并校验后，默认执行 `REINDEX INDEX stable_newsarticle_public_slug_46694cb6`。索引体量小，优先换取更短、更低资源的确定性修复。公开只读页面可保持，但维护窗口内不允许文章写入。

**Alternatives considered：**

- `REINDEX ... CONCURRENTLY` — 写阻塞更低，但需要额外扫描、临时索引和磁盘，失败时还会遗留 invalid index；当前 2C4G 单机优先减少资源放大。
- 删除索引后由 migration 重建 — 会制造无索引窗口且把一次运维修复混入业务部署，不采用。
- 仅重启 PostgreSQL — 不会修复已观测到的 B-tree 物理异常。

### Decision 2: 验收同时覆盖目录、物理检查和事务内写入 <!-- adr: adr-002-three-layer-check -->

**Choice：** 重建后核对索引定义、`indisvalid/indisready/indislive`，使用标准 `amcheck` 的 `bt_index_check`（若生产镜像具备扩展）检查索引，并在事务内创建/更新一条不会提交的 `NewsArticle` 写入探针后回滚；最后恢复 worker/beat 并观察 60 分钟真实抓取。若 `amcheck` 不可用，必须记录降级并以重建成功、事务探针和真实抓取共同验收，不能伪造物理检查通过。

**Alternatives considered：**

- 只看 `REINDEX` 退出码 — 无法证明应用写入和恢复后的真实链路正常。
- 直接创建并保留测试文章 — 会污染生产数据，不采用。

### Decision 3: 超时任务收敛使用清单和条件终态写 <!-- adr: adr-003-stale-job-cas -->

**Choice：** 新管理命令先生成包含 job ID、source、started_at、当前状态、关联文章数、Celery active/reserved 证据摘要和 manifest SHA 的 dry-run。apply 必须引用 manifest，并以 `WHERE id=? AND status='started'` 条件更新为 failed；`_finish_crawl_job()` 同样只允许从 `started` 抢占终态。没有活跃任务证据且超过 60 分钟的记录才可进入清单。

**Alternatives considered：**

- 直接批量 `UPDATE status='failed'` — 无法区分真实长任务，也无法防迟到覆盖。
- 打开 `NEWS_SOURCE_POLL_RETRY_STALE_RUNNING=true` 而不收敛旧记录 — 会并发重跑且保留错误账本，不采用。

### Decision 4: 来源健康使用滚动聚合而非单一最新状态 <!-- adr: adr-004-rolling-health -->

**Choice：** 复用 `CrawlJob` 和 `TaskExecutionLog`，分别输出当前运行、最近完成、最近 2 小时/24 小时失败数、最近同类数据库错误、超时遗留数和最后成功时间。任一 B-tree 插入错误触发 P0 `ops_anomaly`；成功结果只更新最后成功，不清除滚动异常。

**Alternatives considered：**

- 新增独立监控服务 — 超出当前单体与单机阶段范围。
- 继续只读 `NewsSource.last_crawl_*` — 已证明会被最后成功覆盖，不能回答近期是否持续失败。

## Risks / Trade-offs

- [重建期间仍有文章写入] → 暂停 beat/worker、禁止后台编辑、记录容器状态；锁等待超阈值立即中止，不强杀会话。
- [备份成功但不可恢复] → 至少执行 `gzip -t`、`pg_restore -l` 或对应 SQL 可读检查，并记录大小与 SHA-256。
- [误判真实长任务为遗留] → 清单同时检查超时、Celery active/reserved 和关联窗口租约；证据不完整则跳过。
- [迟到任务覆盖 failed] → 所有 CrawlJob 终态更新改为 compare-and-set，未抢到终态只写任务日志。
- [修复后其他索引也损坏] → 只读枚举近期 PostgreSQL 索引错误；发现第二个索引时停止扩大范围并重新评估。

## Migration Plan

1. 用户确认后立即记录生产 HEAD、容器、数据库版本、索引定义、失败基线、活动任务和磁盘，生成并验证备份。
2. 暂停 beat/worker 和后台文章编辑，执行索引重建与三层验证；失败时保持写入暂停并按原索引状态/备份决策，不删除业务数据。恢复后观察至少 60 分钟。
3. 在独立干净工作树实现条件终态、dry-run/apply 命令、滚动健康与回归测试；迁移编号按合并时实际图生成。
4. 部署代码后重新生成遗留任务 manifest，人工确认后 apply；旧审计中的 32 只作基线，不作为写入清单。
5. 再观察至少 60 分钟：同类索引错误为 0、真实新稿可写、无新增长期 `started`、`/healthz/` 与地区页正常。
6. 回滚代码时保留已修复索引；若数据异常，先停止写入并按维护前备份恢复到新实例/隔离库验证。

## Open Questions

- 是否批准一次预计 10 分钟的新闻写入维护窗口，并允许在备份通过后执行生产 `REINDEX INDEX`？推荐批准。
- 是否批准把 manifest 中确认无活跃执行证据的 32 条超时 `CrawlJob` 标记为 failed？推荐批准，但实际数量以执行时新快照为准。
