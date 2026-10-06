# B037 测试清单：自动重试 claim/fence

输入为最终已审 B036 方案（来源 `82b0c725`，原 R 复审由 ROOT 确认 APPROVED_PLAN_ONLY）。固定实现基线 `2c72521c55b6cdc24f7650d172b48079cbff969a`。本清单落成该方案的测试设计，不扩大业务；准备提交 `a4022503` 上五项实际 RED 已取得（5 failures/0 errors/0 skips），之后才修改应用代码；`bb572df2` 同5IDs已GREEN。`9498edf1` 全63项已在ROOT另分配的隔离PG16窗口通过，包括两backend真并发；待独立review及正式full。

## 首批 RED（五项，单批）

模块 `stable.test_translation_claim_fence`，类 `TranslationClaimFenceRedTests`。测试直接捕获 selector 既有 delay envelope 再调用 task.run，不用新签名 TypeError 作为 RED。

| ID 后缀 | 业务断言 | 可捕获 mutation |
|---|---|---|
| test_same_preclaimed_message_is_consumed_once | provider 返回前同消息入场，调用仅一次；成功派发仅一次 | 删除 claimed→executing 消费保护 |
| test_late_success_cannot_overwrite_new_claim | mock provider 内 stale 回收并新领取；旧结果不覆盖新状态/正文，零派发 | 删除成功写入归属核对 |
| test_late_terminal_exception_cannot_notify_or_fail_new_claim | 同上但旧 provider 抛 terminal 异常；新轮状态不变、零通知 | 异常分支先写状态/同步通知再核归属 |
| test_terminal_notification_observes_committed_article_and_exact_run_once | 通知时无事务，article+指定run都已失败；重投不通知 | 独立写run终态、通知在事务内或重复登记 |
| test_terminal_run_save_failure_rolls_back_without_notification | run保存失败时 article/run终态全部回滚、通知零 | 失败状态与run不原子、直接发送后回滚 |

TransactionTestCase 使 on_commit 真实退出最外层事务后执行；邮件、provider 和 automation 调度均替身。可控交错不是数据库真并发证据。首批完整 canonical ID = `stable.test_translation_claim_fence.TranslationClaimFenceRedTests.` + 表内后缀。

## 首批 GREEN 后的边界验证与相邻回归

按 B036 方案再覆盖：源内容改变、run/article身份不符与缺 envelope、claimed_at保持、deadline精确边界与不得续期、保存成功原子回滚、终态重投、派发失败释放与stale归属/通知回滚、notify失败不回流provider、受管翻译明确run及无锁外部调用、JSON claim metadata兼容。分别拒绝删除输入摘要/fence/deadline/指定run/提交后通知的 mutation。

这些新增断言验证首批业务RED后已实现的同一组保护，不因此新增应用行为。首次失败若证明实现缺口，保留新RED及固定SHA再修，不把环境/夹具问题冒RED。当前源码未再改。

新增边界 canonical IDs 前缀 `stable.test_translation_claim_fence.TranslationClaimFenceBoundaryTests.`：

| 后缀 | 验证点 |
|---|---|
| test_success_run_save_failure_rolls_back_article_without_dispatch | 成功终态保存失败回滚且零派发 |
| test_ordinary_service_cannot_overwrite_managed_claim_metadata | 普通服务不覆盖受管JSON |
| test_ordinary_translation_keeps_existing_manual_field_protection | 普通路径人工字段保护 |
| test_force_published_keeps_workflow_and_does_not_dispatch | force published工作流及零派发 |
| test_outer_transaction_denies_external_call_without_consuming | 外层事务下拒绝provider，claim不消费 |
| test_source_change_rejects_result_and_preserves_current_manual_fields | 输入变化后不覆盖编辑内容 |
| test_exact_deadline_denies_entry_without_provider_call | 精确到期时零provider |
| test_result_at_deadline_is_not_committed_or_dispatched | 返回到期时零终态/派发 |
| test_later_consumption_does_not_reset_start_or_deadline | 领取时间/截止不可延长 |
| test_old_message_without_envelope_is_closed | 旧消息不借用最新run |
| test_wrong_run_and_invalid_identity_do_not_consume_current_claim | 非法ID不能消费当前run |
| test_dispatch_release_only_finishes_bound_run | 释放只终止绑定run |
| test_stale_recovery_only_finishes_bound_run | stale只终止绑定run |
| test_recovery_and_release_run_save_failure_leave_no_state_or_notification | 回收/释放保存失败全回滚/零通知 |
| test_notification_failure_does_not_retry_or_rewrite_translation | 回调失败不回流provider/状态 |
| test_managed_service_keeps_exact_run_and_metadata_with_no_external_lock | 真服务封装的指定run/metadata/事务外provider |
| test_two_pg_connections_consume_only_once | 两独立PG backend单消费者/连接清理 |

下一批准确63项：本模块22+既有 `stable.test_translation_failure_recovery_change` 22+`stable.test_responses_analysis` 19；以runtime AST清单固定准确方法ID，未经ROOT窗口不执行。本片原5方法AST保持不变；既有selector仅更新新消息契约断言，未缩其批量/失败范围。不是正式collector/catalog/full证据。

上述63项随后已按ROOT明确窗口一次实际执行，全部通过、零failure/error/skip，名单与执行集合逐项相等。PG真并发backend93/94及连接清理断言通过，原日志/完整结果/隔离与清理证据在 `/Users/mentianlu/.codex/runtime/b037-m02-boundary-63-pg-window-001`；固定受测SHA `9498edf185a99d6defc041cfabc714adc039d5a0`。原RED→GREEN与此补证没有替代正式catalog/impact/full或独立代码review。

## B037-R01 新反例：锁等待跨deadline（准备，未执行）

依据原R唯一P2，新增类 `stable.test_translation_claim_fence.TranslationClaimPostLockDeadlineTests`，准确三方法：

| 后缀 | 目标缺失行为 / mutation |
|---|---|
| test_consumption_waiting_for_locks_past_deadline_never_calls_provider | 锁前now仍有效，锁等待后已到期；旧判断允许executing/provider，修后零provider且claim仍claimed；捕获删除取得锁后时钟读取 |
| test_success_waiting_for_locks_past_deadline_never_commits_or_dispatches | 先消费，provider事件把回写暂停在主线程持锁后；旧now允许到期后保存/派发，修后article/run快照不变；捕获成功路径沿用锁前now |
| test_terminal_error_waiting_for_locks_past_deadline_never_commits_or_notifies | 同上但mock provider抛terminal；旧now允许状态/通知，修后零终态/通知；捕获异常路径缺少锁后deadline检查 |

每方法两subcases：主线程分别持article/run行锁；pg_stat_activity实际显示对应FOR UPDATE的Lock等待才推进时钟，精确到期/过期一秒。claim身份/阶段/输入不变，断言真实状态差异，不以签名、导入、环境错误作RED。主线程持锁连接兼作PG观察（清stats snapshot避免缓存），加一worker连接共两条；所有线程有界、finally close_all。mock provider/通知/send_mail/派发，无真实发送或付费。

旧三个测试类AST与63方法保持不变；准备提交不改三应用源码。C032占用期间仅AST/diff检查，未经ROOT新的精确窗口不执行DB/容器。资源和后续修复边界见B037报告。

首轮固定5b703193一次运行：三run锁subcases为有效状态差异RED，三article锁subcases因观察器要求可能截断query的FOR UPDATE尾部而未匹配，不计目标RED。新测试只把观察谓词改为实际Lock+对应表+pg_blocking_pids包含持锁owner，记录query长度/跟踪上限，仍两PG连接；不改应用逻辑、不提高PG配置或改官方控制。准确三canonical IDs不变，六subcases均须得到业务失败后再修实现；旧63PASS证据不覆盖本缺口。

非法值、空值、旧 preclaimed 消息均 fail closed；普通首次翻译/force/manual 保留现有行为与人工字段保护。无 models/settings/migration变化。无新权限或对外发送开关。deadline只约束准入/回写，跨轮费用预算与outbox不在本片，按方案保留真实缺口。

PG并发后续两独立连接在消费点同步，证实只有一位消费成功及统一 article→run 锁顺序，事务不包provider；无需多容器。禁止以顺序测试替代该项。

## 执行与资源申请

准备时 C029 占用 collector，未运行 DB 测试或容器；随后 ROOT 分配精确一次 RED 窗口，实际使用候选外受信 `scripts/run_test_plan.py --batch b037-red-five`、django profile 与指定现有镜像运行表内五ID。其隔离 DiscoverRunner 执行等价五方法测试，不用项目 dotenv/真实 broker。新模块临时精确 label 仅用于 RED 诊断，不是正式 catalog/full 收据。实证见 B037 报告及 `/Users/mentianlu/.codex/runtime/b037-m02-red-pg-window-001`；窗口已实测清理释放，不继续沿用。

首批建议单 runner，2 CPU / 4 GiB、硬超时180秒（库迁移准备由 ROOT 独立计量/复用现有测试库），无其他并行任务、无新镜像或容器构建。如既有 runner 契约更严格沿其约束。命令/实际镜像/隔离DB设置及连接范围由 ROOT 回传后绑定运行 receipt，未经窗口不执行。

GREEN 同例之后扩展上列场景及 PG 真并发；相邻回归优先现有 recovery 测试、provider元数据/术语人工字段保护和 M01 mock。最终模块 catalog、共享 tasks 的 impact/full由 ROOT/C整合，不改共享登记或降低门槛。记录实际日志、exit、固定SHA和输入摘要，失败环境不算 RED。
