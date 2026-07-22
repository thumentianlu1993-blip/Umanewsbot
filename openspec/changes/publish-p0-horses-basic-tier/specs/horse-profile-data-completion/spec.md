## ADDED Requirements

### Requirement: 批次地区 commit 复验通过后自动首次发布

滚动批次地区 commit 的幂等复验通过后，系统 SHALL 对本地区 profile 按 BASIC 发布门禁自动首次发布；复验未通过时 MUST NOT 发布任何 profile。自动首发 SHALL 以批次 commit 审核人为 `published_by`，经 `transition_review_status` 写入 OperationLog，并在批次台账、批次 checkpoint 与 completion run summary 中留下含 profile 列表与计数的记录。逐匹失败 SHALL 汇总报告且不回滚已成功发布。

#### Scenario: 复验通过才发布

- **WHEN** 某地区 commit 的幂等复验通过
- **THEN** 系统 SHALL 对本地区通过 BASIC 门禁的 profile 执行首次发布并留下四通道审计记录

#### Scenario: 复验失败零发布

- **WHEN** 某地区 commit 的幂等复验未通过
- **THEN** 系统 MUST NOT 发布任何 profile，commit 以错误结束

#### Scenario: 自动首发幂等

- **WHEN** 对同一批次同一地区重复执行 commit
- **THEN** 已发布 profile SHALL 计为 skipped_already_published，不产生重复发布或重复审计结论

### Requirement: 存量批量发布必须经 dry-run artifact 与人工批准

存量批量发布命令 SHALL 默认只输出 dry-run artifact（候选清单、阻断原因直方图、SHA-256 manifest、前后对比）；commit MUST 要求显式批准的 manifest SHA 与 active-superuser 审核人，按地区分批单事务不超过 500 个 profile 执行，重复 commit MUST 幂等。

#### Scenario: 未批准不得批量发布

- **WHEN** 操作者未提供经批准的 manifest SHA 即执行存量发布 commit
- **THEN** 系统 SHALL fail closed，不修改任何 profile 的发布状态
