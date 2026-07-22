## Why

最近 61 小时新增文章中有 32 篇翻译失败，历史复核的 127 篇 `translation_failed` 两天后仍完全不变；错误同时包含 429/5xx/超时等瞬态故障，以及占位符、人物术语变化和响应结构错误等内容故障。当前任务只在单次翻译内部重试内容校验，任务失败后没有按错误类别、退避和次数上限自动恢复，导致可恢复稿件永久积压。

## What Changes

- 建立稳定的翻译失败分类：瞬态网络/限流、上游服务、响应结构、内容完整性、术语/占位符一致性、配置和未知错误；日志与文章状态使用稳定错误码而不是自然语言匹配。
- 对 429、5xx、超时和连接类瞬态错误使用 Celery 有界指数退避与抖动，默认最多 3 次任务级重试；对内容校验仅保留当前有界模型重试，失败后转人工，不形成无限循环。
- 为历史 `translation_failed` 提供 dry-run manifest、固定范围、稳定游标、错误分类汇总和显式 commit；commit 只重新排队批准的可恢复类别，不直接改写为成功或发布。
- 增加并发、预算和幂等保护，避免重试风暴、同篇并发翻译、旧结果覆盖人工编辑或新翻译结果。
- 在地区生产审计中展示翻译失败年龄、类别、重试次数、是否可自动恢复和最终处置，并为异常激增提供阈值告警。

## Capabilities

### New Capabilities

- `news-translation-recovery`: 定义翻译错误分类、瞬态重试、历史恢复、幂等和可观测性要求。

### Modified Capabilities

- `multiregion-news-production`: 地区审计增加翻译失败类别、年龄、重试和可恢复状态的生产漏斗。

## Impact

- 主要代码：`server/stable/services/translation.py`、`server/stable/tasks.py`、翻译/自动化审计服务、受控管理命令与测试。
- 配置：任务级最大重试、退避上限、抖动、批次上限和允许自动恢复的错误类别；默认保守。
- 数据：复用 `TranslationRun`、`NewsArticle.translation_*`、`TaskExecutionLog`，并以最小 migration 增加 `retrying` 状态、稳定错误码与下一重试时间；历史记录不猜测回填错误码。
- 不降低术语、占位符或完整性校验，不更换翻译供应商，不把失败文章直接公开。
