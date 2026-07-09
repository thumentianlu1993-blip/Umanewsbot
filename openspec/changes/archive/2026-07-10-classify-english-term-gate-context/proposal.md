## Why

7 月 1 日以来海外候选池审计显示，英文新闻的 `core_term_missing` 仍会把一批普通英文词误当成核心赛马术语阻断，例如 `Were`、`Contact`、`Number`、`Live`、`AGENDA`、`Tuesday` 和 `GOOD JOB`。现有配置化高歧义词规则已经上线，但它只能按词表静态降级，无法判断“本次命中的上下文到底是专有名词还是普通词”，因此仍会造成候选池积压。

## What Changes

- 在英文发布门禁中增加“命中上下文语义判定”：当英文术语未在中文稿中稳定保留、且可能生成 `core_term_missing` 时，先判断该命中应作为真实专有名词还是普通英文词处理。
- 保留现有英文地区过滤、正式术语保留校验和真实核心专名 blocker 逻辑；普通英文词高置信命中降级为 warning/info，不再阻断自动发布。
- 对无法确定的命中保持保守：继续转人工或保留 blocker，不自动放行。
- 在门禁 issue payload 和校验 details 中记录分类结果、理由、置信度和命中上下文，便于后台和运行审计复核。
- 增加优化版重校验/审计能力，支持对目标地区、时间窗和旧 `core_term_missing` 文章输出完整 dry-run 结果，避免生产逐篇重复加载术语导致执行过慢。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `automation-publish-gates`: 英文术语门禁需要按上下文区分普通词和真实专有名词，普通词不应作为硬 blocker 阻断自动发布，真实专有名词仍应沿用当前核心术语缺失逻辑。

## Impact

- 主要影响 `server/stable/services/validation.py` 中英文术语命中、核心术语判断和 issue 生成流程。
- 可能影响 `server/stable/services/terms.py` 的命中上下文提取或辅助函数，但不改变正式术语库结构。
- 需要新增或扩展管理命令，用于优化旧 `core_term_missing` 文章的完整 dry-run 和受控重处理。
- 需要补充 Django 测试覆盖：普通英文词误挡、真实赛事/马名继续 blocker、不确定命中保守处理、payload 可审计、重校验命令输出。
- 不新增数据库模型或迁移；若需要生产可配置项，应通过 settings/env 提供默认关闭或保守默认值。
