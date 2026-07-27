# 最近赛事赛果定时收集与邮件审阅规格

## 1. 目标

把本次会话验证过的赛事赛果恢复流程固化为可重复使用的生产工具，并在每天
`06:30`、`18:30`（`Asia/Shanghai`）自动运行：

1. 冻结最近 72 小时内已经过正式开赛时点、但尚无完整确认赛果的赛事；
2. 自动完成受限联网、候选收集、完整名次检查和 dry-run；
3. 将完整、可审计的赛果审核包发送到生产配置的唯一收件人
   `754652181@qq.com`；
4. 只有用户明确审阅通过审核包 SHA 后，才允许把该包写入生产库并独立验证。

“唯一需授权点”是运行时业务授权：赛果审核包的人工通过。目标枚举、受限联网、
候选解析、覆盖审计、dry-run、邮件投递和失败重试不再要求逐次人工授权。代码实现、
审核和首次发布仍遵守仓库发布治理，不与运行时业务授权混为一谈。

## 2. 时间窗口与目标定义

- 调度时区固定为 `Asia/Shanghai`，每天 `06:30`、`18:30` 运行。
- 每次运行先冻结 aware `run_started_at`，新到期赛事窗口为
  `[run_started_at - 72 hours, run_started_at]`。
- 实际目标为“新到期赛事”与 durable pending backlog 的并集。pending 最长保留 14 天；
  已取得完整确认赛果、取消、延期或被确认为非 canonical duplicate 时终止。超过 14 天仍未解决的
  赛事进入 `expired_pending` 异常清单，但仍可由同一工具无额外授权地执行手工 catch-up。
- 有 `race_datetime` 的赛事，以该 aware datetime 是否落窗且是否已过时点为准。
- 缺 `race_datetime` 但有 `local_date + timezone_name` 的赛事，只有在赛事当地日期完整结束后
  才视为到期；不得把当地比赛日上午猜作“已完赛”。
- 缺少可验证时区或日期身份的赛事进入 `time_identity_missing`，不联网、不猜测，并进入
  脱敏运行异常摘要。
- 只扫描公开赛事，排除 `cancelled`、`postponed` 和已链接到其他 canonical event 的重复记录。
- 下列任一情况视为“尚未刷新完整确认赛果”：
  - 没有 `RaceEventResult`；
  - 存在未确认结果；
  - `result_confirmed_at` 为空；
  - 已存结果无法证明覆盖全部应出赛马匹。
- 已有完整确认赛果但赛事状态仍为赛前，不重复联网；记为 `status_repair_required`，由受审写入工具
  在不改变赛果内容的前提下修复为 `finished`，并纳入同一审核包说明。

## 3. 来源与路由

- 使用仓库内受审、版本化的赛果来源路由注册表，不再使用上次 40 场的静态 event ID 映射。
- 路由必须由 `RaceEvent.id + country_region + source_refs/provider identity` 唯一决定，禁止按赛事名
  模糊匹配或按注册顺序猜选。
- 官方自动化路由可用时优先官方来源；官方路由不可自动访问或暂未发布时，可使用注册表明确允许的
  `internal_reference` 赛果来源，但它只能生成内部参考观察，不能冒充 official receipt。
- 用户对精确审核包的批准是一种新的 `human_reviewed_reference` authority：它允许把完整的内部参考
  结果发布为“平台人工审核赛果”，不把 Sporting Life、ZEturf、HRN 等来源升级为官方，也不填写
  `official_finish_position` 或 official receipt/confirmed timestamp。官方来源直接取得的结果继续使用
  现有 `official` authority。
- 日本必须在 JRA/NAR namespace 间唯一命中；香港只接受 HKJC；英国、法国、美国只接受注册表中
  对应地区且 contract 未过期的 provider。
- route 未启用、条款/robots/host/path 不允许、稳定身份缺失或多路由冲突时，赛事标为 blocker，
  不联网、不生成可写候选。
- 所有网络访问受 HTTPS、host/path allowlist、redirect、超时、响应大小、每 host 间隔、单次请求
  总预算和磁盘预算约束；禁止绕过验证码、认证或站点限制。

## 4. 完整赛果要求

- 每个候选必须绑定内部 `event_id`、稳定外部身份、来源 URL 摘要、provider、authority、
  `observed_at` 和源时区证据。
- 所有应出赛马匹必须被结果覆盖；退赛、未出赛、未完赛、拉停、落马、失格等以结构化
  `running_status` 单列。
- 正常完赛马匹必须有正整数名次；同着按现有导入合同表达，但不得把文本占位符当名次。
- `Also ran`、`others`、`unplaced` 或类似文本永远不能成为顺序，也不能作为完整性通过依据。
- `result_order_complete` 必须为 `true`，且覆盖审计 blocker 为零，才可形成“可审阅”审核包。
- 任一赛事不完整时整批可以保留已完成候选，但邮件主题和清单必须明确区分
  `reviewable` 与 `blocked`；blocked 赛事绝不可进入 apply scope。

## 5. 审核包与邮件

每次有缺口时生成不可覆盖 generation：

`/app/runtime/race_result_review/generations/<bundle_sha256>/`

至少包含：

- `inventory.json`：冻结目标和基线 SHA；
- `candidates.jsonl`：仅含 results 模块的结构化候选；
- `review.csv`：按赛事和名次展开的人读审核表；
- `dry_run.json`：逐事件写入预览、状态变化和零写入证明；
- `blockers.json`：缺来源、身份冲突、不完整顺序等；
- `manifest.json`：全部文件 SHA、代码 revision、route registry SHA、目标数和候选数。
- `review_payload.json`：逐 event 的规范可写字段全集及 `reviewed_row_digest`；apply 只消费该文件，
  不直接消费邮件之外的 parser candidate。

邮件要求：

- 收件人从 `RACE_RESULT_REVIEW_NOTIFY_EMAILS` 读取；生产唯一值为
  `754652181@qq.com`，为空或多于一个地址时 fail closed。
- 标题包含窗口、可审赛事数、blocked 数和审核包 SHA 前缀。
- 正文包含逐场 event ID、中文/原名、开赛时间、来源 authority、赛果行数、完整性结论、
  blocker 以及明确的审核回复格式。
- 附件为 `review_payload.json`、`review.csv`、`dry_run.json` 和 `manifest.json`；
  `review.csv` 必须是 `review_payload.json` 的确定性展开，verifier 逐行复算二者等价。附件总大小
  超限时不静默截断，
  将邮件标为失败并保留本地包。
- 邮件发送采用 durable intent：先保存 bundle 与 `RaceResultReviewDelivery=QUEUED`，事务提交后发送；
  成功写 `SENT`，失败写 `FAILED` 并在下一调度重试。
- 投递语义为 at-least-once：相同 `bundle_sha256 + recipient` 使用数据库唯一键、发送 lease、attempt
  和确定性 `Message-ID`。已知 `SENT` 时不重发；SMTP 已接受但进程在落 `SENT` 前崩溃属于未知终态，
  stale lease 恢复时可能重发同一 Message-ID，邮件正文明确以 bundle SHA 去重审阅。无缺口时成功
  noop 且不发邮件。

## 6. 审阅后写入

- 审阅回复必须明确引用完整 `bundle_sha256`，并列出批准的 event ID；每个 event 的 approval
  持久绑定邮件内 `reviewed_row_digest`。“看起来可以”等未绑定 SHA 的回复不能写库。
- apply 必须使用审核包原件、`--expected-bundle-sha256` 和精确 event scope，重新验证：
  当前代码 revision、manifest、inventory 基线、候选文件、route contract、赛事身份及现有赛果
  都未漂移。
- 写入只允许审核通过且 `result_order_complete=true` 的 event；blocked 或未列入批准范围的 event
  零写入。
- apply 采用逐 event 原子语义：每个批准 event 在独立数据库事务内 upsert 结果、写平台确认时间、
  把赛事状态改为 `finished`，并写 approval/operation receipt；同一 bundle 中其他 event 的漂移不回滚
  已成功 event。最终 summary 必须逐场列出 `applied/already_applied/blocked`，blocked event 留在
  pending backlog 重试。
- `official` receipt 继续设置现有官方确认字段；`human_reviewed_reference` 设置
  `is_confirmed=true` 和平台 `result_confirmed_at`，但以新增 approval ledger 与 result provenance
  明确来源，不生成 official receipt，不宣称官方 authority。公开读取显示“已人工审核赛果”，而非
  “官方赛果”。
- 独立 verify 必须核对结果行数、完整顺序、非完赛状态、event 状态、receipt 和重放幂等性。
- 同一 bundle/event/digest 重放返回 already applied，不重复创建结果或审计事实。

## 7. 并发、恢复与可观测性

- 每个计划时点形成唯一 `schedule_slot` 数据库记录。生产 Beat 与 Codex cron 都可触发同一 slot，
  只有取得 slot lease 的执行者进入 prepare；另一执行者返回 `already_claimed`。过期 lease 可恢复，
  durable cursor 会在下一次运行补齐遗漏 slot。
- 每个 run 和 bundle 不可覆盖；只允许原子创建 generation，不得修改已发邮件所引用的文件。
- provider 局部失败不伪装成功；完整候选仍可审核，blocked 目标留到下一调度自动重试。
- 数据库与日志只保存固定错误码、event ID、计数、SHA 和脱敏 provider；不得保存 credential、
  cookie、header、原始响应正文或未脱敏异常。
- `TaskExecutionLog` 和专用 run ledger 记录 schedule slot、窗口、target/reviewable/blocked/noop、
  请求计数、bundle SHA、邮件终态和耗时。durable cursor 最多检查 14 天内的遗漏 slot；多个遗漏
  slot 全部记录为 `coalesced_to_latest_due_slot`，只对最新到期 slot 执行一次 selector/prepare 和
  一份全局请求预算，禁止逐 slot 重复联网。

## 8. 非目标

- 定时 prepare 绝不自动写生产赛事、赛果、出马、新闻或 QQ 数据。
- 不启用 race-live scheduler，不改变准实时 publication policy。
- 不把内部参考来源宣称为官方；`human_reviewed_reference` 只批准当前 bundle/event/digest，
  不升级来源 authority，也不扩展为未来 bundle 的长期授权。
- 不在本变更中建设通用邮件审批 UI；回复由当前 Codex 任务读取并按精确 SHA 执行现有人工闭环。

## 9. 验收标准

- 两个北京时间触发点准确，无 DST 漂移。
- 最近 72 小时到期目标全量守恒，重复/cancelled/postponed/时间身份缺失有明确处置。
- 全开关关闭 smoke 为网络 0、邮件 0、业务写 0。
- 启用 prepare 后只发生受审 provider 请求、artifact/审计写和单封去重邮件，业务表写 0。
- `Also ran`、缺马、名次不连续、重复身份或空 runner roster 全部 blocked。
- 邮件失败可重试；已知 SENT 不重发，SMTP 未知终态允许同 Message-ID 的 at-least-once 重试；
  并发 slot 不重复联网。
- 主调度面在生产 Beat；同频 Codex cron 是幂等备用触发。任一触发面短时不可用时，由另一面执行；
  两者都曾中断时下一次运行把历史遗漏 slot 合并到最新到期 slot，只执行一次联网 prepare。
- 审阅前 apply 必然拒绝；精确 SHA + event digest 审阅后逐 event apply/verify 成功且重放幂等。
