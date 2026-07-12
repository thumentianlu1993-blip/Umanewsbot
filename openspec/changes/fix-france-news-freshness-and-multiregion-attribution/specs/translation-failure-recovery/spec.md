## ADDED Requirements

### Requirement: 系统必须区分可恢复与永久翻译失败 <!-- id: req-translation-errors -->
系统 MUST 将翻译异常规范为可恢复、永久或未知类别，并保存原始错误摘要。HTTP `429 / 502 / 503 / 504`、明确限流和网络超时 SHALL 归为可恢复；认证、请求结构和内容永久无效 SHALL 归为永久；未知错误 MUST NOT 无界自动重试。

#### Scenario: 供应商繁忙可恢复
- **WHEN** 翻译请求返回 `429`、`503` 或明确的系统繁忙错误
- **THEN** 系统 SHALL 将文章标记为可恢复翻译失败
- **AND** 系统 SHALL 保存错误类别和原始错误摘要

#### Scenario: 永久错误不自动循环
- **WHEN** 翻译请求因认证失败或永久无效 payload 失败
- **THEN** 系统 SHALL 将失败标记为永久
- **AND** 系统 MUST NOT 自动重复派发该文章

### Requirement: 可恢复翻译失败必须有限退避重试 <!-- id: req-translation-backoff -->
系统 SHALL 对到期的可恢复失败执行有限次数自动重试，默认最多 3 次，并使用递增退避和抖动。若供应商提供 `Retry-After`，系统 MUST 不早于该时间重试。

#### Scenario: 瞬时失败自动恢复
- **WHEN** 一篇文章首次因可恢复错误翻译失败
- **THEN** 系统 SHALL 保存下一次重试时间
- **AND** 到期后 SHALL 自动重新派发翻译

#### Scenario: 达到重试上限
- **WHEN** 一篇文章已达到配置的自动重试上限且仍失败
- **THEN** 系统 SHALL 进入重试耗尽终态
- **AND** 系统 SHALL NOT 继续自动重试

#### Scenario: 自动重试默认关闭
- **WHEN** 新代码首次部署且生产未显式开启翻译自动重试
- **THEN** 周期任务 MUST NOT 派发历史失败文章
- **AND** 现有首次翻译链路 SHALL 保持不变

#### Scenario: 陈旧 translating 状态恢复
- **WHEN** 文章处于 translating 且开始时间超过配置的陈旧阈值
- **THEN** 系统 SHALL 将其恢复为可重试的 transient stale failure
- **AND** SHALL 记录 worker 中断恢复原因

### Requirement: 翻译重试必须幂等且受全局限流 <!-- id: req-translation-idempotency -->
系统 MUST 防止周期调度、人工重试和其他唤醒路径对同一文章并发翻译，并 SHALL 限制每轮重试文章数量，避免供应商异常时形成请求风暴。

#### Scenario: 同一文章只有一个重试任务
- **WHEN** 周期任务与运营人员同时请求重试同一文章
- **THEN** 系统 MUST 只允许一个有效翻译执行
- **AND** 其他请求 SHALL 返回已派发或正在执行状态

#### Scenario: 到期失败超过批次上限
- **WHEN** 到期可恢复失败数量超过每轮配置上限
- **THEN** 系统 SHALL 只派发上限内文章
- **AND** 其余文章 SHALL 保留下次可继续处理的状态

### Requirement: 运营必须感知并快速处理最终翻译失败 <!-- id: req-translation-operations -->
系统 SHALL 在运营后台和通知中展示重试中、下次重试时间、已用次数、错误类别和重试耗尽状态，并提供单篇和受控批量立即重试入口。

#### Scenario: 查看翻译失败详情
- **WHEN** 运营查看翻译失败文章
- **THEN** 系统 SHALL 展示最近错误、错误类别、已用重试次数和下次重试时间

#### Scenario: 人工立即重试
- **WHEN** 运营对一篇重试耗尽文章点击立即重试
- **THEN** 系统 SHALL 重新进入受控翻译队列
- **AND** 系统 SHALL 记录操作人和操作结果
