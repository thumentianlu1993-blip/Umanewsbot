## Context

翻译服务当前在一次 provider 调用中最多尝试 `TRANSLATION_MAX_ATTEMPTS` 次，用于缺字段、未完整结束或马名占位符问题；但网络 429、5xx、超时或连接异常会直接让 Celery task 失败，并把文章长期留在 `translation_failed`。文章已有 `translation_retry_count`，每次任务也有 `TranslationRun`，但错误只有自然语言，无法稳定聚合、自动选择可恢复类别或控制终态通知。

本变更需要区分“同一任务内修正模型内容”和“跨任务等待上游恢复”两种重试，同时保护人工编辑、发布终态和成本预算。

## Goals / Non-Goals

**Goals:**

- 以稳定错误码区分瞬态、内容、配置和未知失败。
- 对明确瞬态故障执行总尝试次数有界的 Celery 退避重试。
- 为历史失败提供固定范围、可审核、幂等的重新排队入口。
- 在地区漏斗中显示错误类别、年龄、次数、下一重试和最终处置。

**Non-Goals:**

- 不降低术语、占位符、正文完整性或 JSON 响应校验。
- 不自动重试认证失败、配置错误或未知编程异常。
- 不更换翻译模型/供应商，也不引入第二家自动故障切换。
- 不让恢复命令直接评分、公开或 QQ 推送；成功后沿用现有自动化链路。

## Decisions

### Decision 1: 以纯分类器生成稳定错误码 <!-- adr: adr-001-translation-error-codes -->

**Choice：** 新增不依赖文章状态的异常分类器，基于异常类型、HTTP 状态和 provider 元数据输出稳定码：`rate_limited`、`upstream_5xx`、`timeout`、`connection_error`、`response_json_invalid`、`response_incomplete`、`placeholder_mismatch`、`required_term_mismatch`、`auth_or_config`、`unknown`。文章和 `TranslationRun` 保存 error code；自然语言只作摘要。

**Alternatives considered：**

- 在审计时正则匹配 `translation_error_message` — 供应商文案变化会让分类漂移。
- 只按 HTTP 状态分类 — 内容校验和本地配置错误没有可靠 HTTP 状态。

### Decision 2: 瞬态错误总任务尝试默认上限为 3 次 <!-- adr: adr-002-bounded-task-retry -->

**Choice：** 将任务改为 bound task。首次执行计为第 1 次，只有 `rate_limited/upstream_5xx/timeout/connection_error` 可进入 Celery retry，总执行次数默认不超过 3；使用指数退避、抖动和上限。等待期间文章状态为 `retrying`，保存下一重试时间；最终失败才进入 `failed` 并发送一次告警。

**Alternatives considered：**

- 使用 OpenAI SDK 的隐式无限/默认重试 — 无法与文章状态、成本和通知一致。
- 所有错误统一重试 — 会对术语或占位符确定性失败重复收费。
- 仅人工重试瞬态错误 — 已导致 127 篇历史失败长期不动。

### Decision 3: 内容校验继续在 provider 内有界重试 <!-- adr: adr-003-content-retry-boundary -->

**Choice：** 缺字段、正文未完整、占位符或必需术语不一致仍由现有 `TRANSLATION_MAX_ATTEMPTS` 在单任务内从头重译；耗尽后记录稳定内容错误码并转人工，不再触发 Celery 级重试。内容问题只有人工修正规则/术语或显式历史恢复后才能再次执行。

**Alternatives considered：**

- 把每次内容重译拆成 Celery retry — 会丢失同一输入的 retry hint 和连续元数据。
- 接受缺术语/占位符译文继续发布 — 违反既有质量门禁。

### Decision 4: 任务认领使用文章行条件状态保护 <!-- adr: adr-004-translation-claim -->

**Choice：** 任务开始在短事务中锁定文章：已 translated/已发布/人工终态直接幂等跳过；正在 translating 且未超时的重复任务跳过；pending、failed 或到期 retrying 才可认领。每个 task execution 建一条 `TranslationRun`，成功/失败/重试状态和 article 字段按清晰顺序写入，旧任务不得覆盖更新后的人工内容或成功结果。

**Alternatives considered：**

- 依赖 Celery task ID 去重 — 调度器和人工命令仍可能创建不同 ID。
- 持有数据库事务跨外部 API 调用 — 会长期占锁并阻塞后台，不采用。

### Decision 5: 历史恢复采用错误类别 manifest <!-- adr: adr-005-translation-manifest -->

**Choice：** 管理命令按地区、来源、时间、错误码、limit 和稳定游标生成 SHA manifest；默认只建议恢复瞬态错误。新失败直接使用持久化稳定码；历史错误码为空时，先读取 `TranslationRun.raw_response` 中的 HTTP/异常元数据，只有缺少结构化元数据时才做一次性自然语言投影，并在 manifest 标记 `legacy_message_projection`、置信度和证据，绝不据此自动派发。apply 逐篇检查未发布、非人工终态、内容指纹未漂移且没有活跃翻译，再按用户批准清单重新排队；每批和全局并发有硬上限。

**Alternatives considered：**

- 批量把所有 failed 改成 pending — 会重跑确定性内容错误和人工已接管文章。
- 在命令中同步翻译 — 会长时间占用运维会话且难以退避。

## Risks / Trade-offs

- [429 时形成重试风暴] → 指数退避、随机抖动、worker 并发上限和全局每分钟派发预算。
- [重试增加费用] → 总执行次数 3、仅瞬态类别、审计展示 attempts 与 token usage。
- [重复任务并发覆盖] → 短事务认领、状态和开始时间 compare-and-set，完成前重读终态/人工字段。
- [分类器误把编程错误当瞬态] → 未知默认不可自动重试，错误码测试覆盖每种异常类型。
- [历史自然语言错误被错误投影] → 结构化 run 元数据优先，message projection 明示低置信且必须逐批人工批准，unknown 保持人工。
- [新 `retrying` 状态影响旧查询] → 更新所有状态枚举、后台筛选、地区审计和 SQLite/PostgreSQL 测试；回滚时可将 retrying 视为 pending。

## Migration Plan

1. 增加 `retrying` 状态、`translation_error_code`、`translation_next_retry_at`，并为 `TranslationRun` 增加 error code；历史行保持原状态，错误码为空。
2. 先补 429、503、超时、内容校验、并发任务和终态通知红灯测试。
3. 实现分类器、任务级重试、认领与审计；默认 `TRANSLATION_TRANSIENT_RETRY_ENABLED=false`。
4. 部署迁移后只对新稿开启一个地区，观察至少 24 小时的重试成功率、费用和队列长度，再扩到五地区。
5. 对历史 127 篇先生成 manifest；按地区每批最多 10 篇恢复瞬态类别，观察成功后继续。
6. 异常时关闭任务级重试；已排队任务仍受认领和最大次数保护，必要时撤销队列但不批量改文章终态。

## Open Questions

- 是否确认瞬态错误“含首次执行总共最多 3 次”，内容错误不做任务级自动重试？推荐确认。
- 历史 127 篇是否只自动恢复 429/5xx/超时/连接类，其余进入人工队列？推荐确认。
