# hkjc-ja-alias-article-backfill

## Why

HKJC 2020-2023 赛事相关中文译名和大部分日语马名 alias 已经进入正式术语库，但仍有少量日语马名没有合并到对应的 HKJC 英文概念上。当前已知剩余项里，主体是“同一中文译名目标下已经存在日语主术语”的情况；这些日语 owner 虽然能让搜索命中，但没有统一到英文 HKJC 概念，导致后续文章术语替换链路仍可能漏掉日本马日文名。

同时，部分文章是在相关术语补齐前发布的。即使现在术语库已经包含对应 term/alias，已发布文章的中文字段仍可能保留原日文或英文原文。这个问题不应通过整篇重翻译解决，而需要一个可审计、可 dry-run、可按文章和字段精确回填的术语再应用流程。

## What Changes

- 增加 HKJC horse alias 概念合并流程：识别同 `term_type`、同 `target_zh`、且可安全并入目标 HKJC 英文概念的日语主术语，将其日文 source text 补为目标概念 alias，并将冗余日语主术语停用或标记为已合并。
- 对冲突项保持保守：如果日语 owner 的中文目标、术语类型或归属不一致，流程只输出人工复核记录，不自动移动 alias 或停用术语。
- 增加已发布文章术语精确回填流程：按 term、文章 ID、时间范围、来源语言等过滤，扫描已发布文章的中文标题、正文、摘要、推送摘要等字段，生成字段级 before/after diff；apply 时只替换明确命中的术语文本。
- 回填流程沿用现有术语替换语义，尊重 `manually_edited_fields`，不触发整篇重翻译、不改发布状态、不重新推送 QQ。
- 增加管理命令、服务层接口、测试和运维文档，生产执行必须先 dry-run、审核输出，再显式 apply。

## Capabilities

### New Capabilities

无。该变更补强现有术语库维护与术语应用能力。

### Modified Capabilities

- `termbase-and-race-priority`：补充正式术语概念合并、日语 alias 合并、已发布文章术语精确回填的要求。

## Impact

- 影响代码：`server/stable/services/term_admin.py` 或新增术语维护 service、`server/stable/services/terms.py`、相关 Django management command。
- 影响测试：增加术语概念合并、冲突跳过、文章字段级回填、手工编辑字段保护、幂等性测试。
- 影响运维：新增生产 dry-run/apply 命令、输出 artifact 目录、执行前备份和执行后健康检查记录。
- 不预期需要数据库结构迁移；审计输出优先写入 runtime CSV/JSON artifact 和术语 notes。
