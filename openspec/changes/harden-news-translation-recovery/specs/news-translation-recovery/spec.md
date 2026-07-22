## ADDED Requirements

### Requirement: 翻译失败必须使用稳定错误分类 <!-- id: req-translation-error-classification -->
系统 MUST 为每次翻译失败保存稳定错误码，并区分瞬态网络/上游错误、内容校验错误、认证配置错误和未知错误。自动重试策略 MUST 只依赖稳定码或异常类型，不得依赖自然语言消息。

#### Scenario: 上游返回 429
- **WHEN** 翻译供应商返回 HTTP 429
- **THEN** 系统 SHALL 记录 `rate_limited` 或等价稳定码
- **AND** 系统 SHALL 将该失败识别为可自动恢复的瞬态错误

#### Scenario: 响应改变必需术语或占位符
- **WHEN** provider 内有界重译耗尽后仍未保留必需术语或占位符
- **THEN** 系统 SHALL 记录对应内容错误码
- **AND** 系统 SHALL NOT 将其识别为瞬态网络错误

#### Scenario: 未知编程异常
- **WHEN** 异常不匹配已声明的可恢复类别
- **THEN** 系统 SHALL 记录 `unknown`
- **AND** 默认 SHALL NOT 自动重试

### Requirement: 瞬态翻译失败必须有界退避重试 <!-- id: req-transient-translation-retry -->
系统 SHALL 仅对已允许的瞬态错误执行 Celery 级重试，默认含首次执行总尝试次数不超过 3，并使用指数退避、抖动和最大等待时间。

#### Scenario: 第一次超时
- **WHEN** 文章首次翻译因 timeout 失败且未达到尝试上限
- **THEN** 系统 SHALL 将文章标记为 retrying 并安排下一次执行
- **AND** 系统 SHALL 保存下一重试时间和当前尝试次数

#### Scenario: 第三次仍为 503
- **WHEN** 同一文章达到总尝试上限后仍因 upstream 503 失败
- **THEN** 系统 SHALL 将文章标记为 translation_failed
- **AND** 系统 SHALL 只发送一次终态失败通知

#### Scenario: 内容校验失败
- **WHEN** 翻译因 required term 或 placeholder 内容校验耗尽 provider 内重试
- **THEN** 系统 SHALL 直接进入人工可见的失败状态
- **AND** 系统 SHALL NOT 再触发 Celery 级自动重试

### Requirement: 翻译任务必须幂等认领并保护终态 <!-- id: req-translation-task-claim -->
系统 MUST 防止同一文章被多个翻译任务并发处理，并且旧任务不得覆盖已成功翻译、已发布、人工终态或人工修改后的新状态。

#### Scenario: 重复任务同时到达
- **WHEN** 两个 task 同时尝试翻译同一 pending 文章
- **THEN** 只有一个任务 SHALL 成功认领外部 API 调用
- **AND** 另一个任务 SHALL 幂等跳过并记录原因

#### Scenario: 迟到任务返回
- **WHEN** 旧翻译任务返回时文章已经由另一任务成功翻译或被人工接管
- **THEN** 旧任务 MUST NOT 覆盖文章的新内容和终态

### Requirement: 历史翻译失败恢复必须受控 <!-- id: req-translation-recovery-manifest -->
系统 SHALL 提供按地区、来源、时间、错误码和 limit 生成的 dry-run manifest。apply MUST 绑定 manifest SHA、逐篇检查漂移，并仅重新排队批准的文章。

#### Scenario: dry-run 分类历史失败
- **WHEN** 运维人员扫描历史 translation_failed 文章
- **THEN** 系统 SHALL 输出错误码、分类证据来源、置信度、年龄、尝试次数、是否可恢复、内容指纹和建议处置
- **AND** 错误码为空的历史记录 SHALL 优先使用 TranslationRun 结构化元数据，message projection 必须显式标记
- **AND** dry-run SHALL 不修改文章或派发任务

#### Scenario: apply 仅恢复瞬态类别
- **WHEN** 审核 manifest 只批准 429、5xx、超时和连接错误
- **THEN** 系统 SHALL 仅重新排队这些未漂移文章
- **AND** 内容、配置和 unknown 错误 SHALL 保持人工处理

#### Scenario: 历史错误仅有低置信消息投影
- **WHEN** 某历史失败没有结构化元数据，且只能从自然语言消息低置信投影类别
- **THEN** 系统 MUST NOT 自动把该文章加入 apply
- **AND** 只有用户在审核 manifest 中逐批批准后才可重新排队

#### Scenario: 已发布或人工终态文章
- **WHEN** manifest 中文章在 apply 前已经发布、撤回、拒绝或人工修改
- **THEN** 系统 SHALL 跳过并报告漂移
- **AND** 不得重新翻译或改变终态

### Requirement: 翻译重试必须受预算和并发限制 <!-- id: req-translation-retry-budget -->
系统 SHALL 对自动重试和历史恢复设置每分钟派发、单批数量和并发上限，避免上游限流时形成重试风暴。

#### Scenario: 待恢复文章超过批次上限
- **WHEN** 可恢复文章数量超过当前批次上限
- **THEN** 系统 SHALL 只派发允许数量并输出下一游标
- **AND** 未派发文章 SHALL 保持原状态

#### Scenario: 全局重试预算耗尽
- **WHEN** 当前时间窗已达到配置的自动重试派发预算
- **THEN** 系统 SHALL 推迟剩余重试并记录 `retry_budget_exhausted` 或等价原因
