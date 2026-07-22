## Why

`2026-07-22` 生产复核确认 `stable_newsarticle_public_slug_46694cb6` 在 61 小时内触发 39 次 PostgreSQL B-tree 插入错误，并遗留 32 条超过 60 分钟的 `CrawlJob(status=started)`；当前“最新成功”摘要还会掩盖近期失败。索引物理异常已经直接损失日本新闻入库，任务账本漂移则会阻塞后续轮询并误导运营判断，必须先于产量优化修复。

## What Changes

- 建立生产索引完整性修复门禁：确认索引身份与依赖、暂停相关写入、生成并校验数据库备份、执行受控重建、验证写入与查询，再恢复抓取。
- 增加只读索引健康预检和可复跑的写后验证；任何同类 B-tree 插入错误均按 P0 暴露，不依赖 `NewsSource.last_crawl_status` 的最新成功值。
- 为超时 `CrawlJob` 增加可审计的收敛机制：只处理超过租约/超时且没有真实活跃任务证据的记录，保留原始计数和原因，并防止旧任务晚到覆盖新结论。
- 调整来源健康摘要，分别展示当前运行、最近完成、滚动窗口失败和超时遗留；成功不得清除近期失败信号。
- 提供针对当前 32 条遗留任务的 dry-run manifest 与显式 apply 路径，禁止无清单批量更新。
- 补齐部署、停写、回滚、恢复抓取和 60 分钟观察手册；本变更不调整来源、翻译、评分或发布策略。

## Capabilities

### New Capabilities

- `news-production-integrity`: 定义新闻主表索引完整性预检、备份、受控修复、写后验证和 P0 告警要求。

### Modified Capabilities

- `crawl-freshness-and-source-health`: 增加超时抓取任务的受控收敛、晚到结果保护和滚动失败可见性要求。

## Impact

- 生产 PostgreSQL：`stable_newsarticle_public_slug_46694cb6` 及其所属 `NewsArticle.public_slug` 普通索引；修复操作只允许在批准维护窗口执行。
- 主要代码：`server/stable/services/source_polling.py`、抓取任务完成逻辑、来源健康聚合、只读/受控管理命令及相关测试。
- 运维资产：`.env.example`（如新增超时或观察阈值）、`docs/deploy_runbook.md`、备份与回滚检查。
- 不新增外部依赖，不修改公开 URL 语义，不删除新闻或抓取历史。
