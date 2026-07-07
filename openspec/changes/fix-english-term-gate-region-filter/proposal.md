## Why

生产只读审计显示，香港、英国和美国新闻源可以正常抓取并入库，但大量英文文章在发布校验阶段被 `core_term_missing` 转入 `manual_review_required`，导致 15 分钟发布窗口持续出现 `no_ready_candidates`。高频 blocker 包含 `CLASS`、`CONTENT`、`LINK`、`AGENT`、`Oaks`、`America`、`NUMBERS` 等普通词、短词或跨地区高歧义词，说明当前英文术语校验过于粗放，已经影响多地区常态发布量。

## What Changes

- 对英文正式术语发布校验增加地区过滤：第一版只检查同地区和全局通用术语；确需跨地区通用的词条先归入全局通用范围。
- 对高歧义英文短词 / 普通词做第一批止血治理：配置化降级为 warning、忽略或要求强上下文，不再默认触发 `core_term_missing` 硬门禁。
- 调整 `core_term_missing` 生成条件：仅可信核心实体缺失才作为 blocker；低可信或高歧义命中应记录为 warning，并保留可审计 payload。
- 保持真正硬门禁不放松：正文缺失、翻译失败、重复内容、可信核心赛事 / 马名缺失仍不得自动发布。
- 补充生产审计输出，使运营能看到各地区被哪些术语阻断，以及哪些 blocker 被降级为 warning。
- 提供受控重处理入口，用于术语规则修正后重新校验最近被误挡的非日本文章，使其可重新进入发布窗口候选池。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `automation-publish-gates`: 调整英文正式术语缺失的硬门禁边界，避免普通词和跨地区低可信术语误触发 blocker。
- `termbase-and-race-priority`: 调整正式术语库在多地区英文新闻中的匹配、地区过滤、普通词治理和审计要求。

## Impact

- 影响代码：`server/stable/services/validation.py`、`server/stable/services/terms.py`、自动化评分 / 发布候选服务、生产审计命令、术语后台或管理命令。
- 影响数据：第一版不新增术语模型字段，先通过配置化高歧义清单和上下文规则止血；后续如需运营后台维护，再单独评估字段和迁移。
- 影响运维：上线后需要运行只读审计确认 `core_term_missing` blocker 数下降，并对最近被误挡文章执行受控重处理。
- 不改变：抓取频率、法国新闻源覆盖、QQ 推送限流、真正硬门禁和人工终态边界。
