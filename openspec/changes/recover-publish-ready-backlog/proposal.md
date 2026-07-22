## Why

生产中 21 篇文章持续满足 `is_ready_for_auto_publish=True`，但因 `MULTIREGION_PUBLISH_CANDIDATE_LOOKBACK_HOURS=3` 只按首次入库或榜单唤醒时间取候选，超过 3 小时后永久退出窗口；两天后这 21 篇仍完全未动。现有实现把“候选新鲜度”误当成“候选消费状态”，既丢稿也没有明确过期处置。

## What Changes

- 将发布窗口候选分成“实时新稿”和“仍未消费的 `publish_ready` 积压”两条有界查询，按状态、年龄、地区、稳定游标和每轮扫描上限消费，而不是无限扩大 3 小时时间窗。
- 为积压候选定义三段时效策略：默认 24 小时内可自动补发，24–72 小时进入人工复核，超过 72 小时不自动公开并标记为过期待处置；阈值可配置且默认保守。
- 在窗口决策和地区审计中记录 `fresh / backlog / stale_review`、候选年龄、上次被窗口考虑时间与未发布原因，避免候选静默永久丢失。
- 提供当前 21 篇的只读 manifest、逐篇重新校验和人工审核入口；任何 apply 只改变经批准文章的候选/处置状态，不直接绕过窗口、配额、去重、门禁或 QQ 规则。
- 保持 `ranked_revived_at` 榜单唤醒语义；榜单唤醒仍可让旧稿重新进入实时窗口，但不作为普通积压唯一恢复方式。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `multiregion-news-production`: 把候选池补量从固定 3 小时时间过滤升级为实时候选与有界积压双通道，并定义过期候选的可审计处置。

## Impact

- 主要代码：`server/stable/services/publishing_windows.py`、发布窗口任务、`audit_multiregion_news_production`、运营后台地区指标及测试。
- 配置：保留现有 3 小时实时回看，新增积压自动年龄、人工复核年龄和每轮扫描上限等保守配置。
- 数据：优先复用 `NewsArticle`、`ProductionWindow` 与 `WindowCandidateDecision`；除非查询基准证明必要，不新增主数据模型或迁移。
- 生产恢复：当前 21 篇只生成审核清单；是否公开由用户确认的时效规则和逐篇审核结果决定。
